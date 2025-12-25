from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.mtf_v3_config import load_mtf_v3_config
from live.hmtf_csv_logger import HmtfCsvLogger
from live.hmtf_engine import (
    BarEvent,
    BarEventRouter,
    DummyMasterModel,
    FeatureStore,
    MultiTimeframeEngine,
    SyncGate,
    TradingStateMachine,
)
from live.master_mtf_v2_model import MtfV2SklearnMasterModel
from live.soldier_xgb_model import XgbSoldierModel, load_feature_list


@dataclass(frozen=True)
class ReplayConfig:
    catalog_path: Path
    bar_type_15m: str
    bar_type_5m: str
    start: pd.Timestamp
    end: pd.Timestamp
    out_dir: Path
    out_dataset: Path
    warmup_15m_bars: int


def _setup_logging(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(out_dir / "replay_v3.log", mode="w", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def _load_env_file() -> None:
    env_file = PROJECT_ROOT / ".env.mtf_v3"
    if env_file.exists():
        # Do not override runtime env variables.
        load_dotenv(env_file, override=False)


def _parse_date_range(start_date: str, end_date: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(start_date).tz_localize("UTC")
    # End is exclusive: include full end_date by adding 1 day.
    end = pd.Timestamp(end_date).tz_localize("UTC") + pd.Timedelta(days=1)
    return start, end


def _instrument_to_catalog_bar_type(instrument: str, minutes: int, what: str = "MID") -> str:
    # instrument example: "EUR/USD.IDEALPRO" -> symbol "EURUSD", venue "IDEALPRO"
    s = str(instrument).strip()
    venue = "IDEALPRO"
    if "." in s:
        s, venue = s.split(".", 1)
    sym = s.replace("/", "").upper()

    what_norm = str(what).strip().upper()
    # Live uses MIDPOINT; catalog uses MID.
    if what_norm == "MIDPOINT":
        what_norm = "MID"

    return f"{sym}.{venue}-{minutes}-MINUTE-{what_norm}-EXTERNAL"


def _iter_events_from_catalog(
    catalog: ParquetDataCatalog,
    bar_type: str,
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> List[BarEvent]:
    bars = catalog.bars(bar_types=[bar_type])
    if len(bars) == 0:
        raise FileNotFoundError(f"No bars found in catalog for bar_type={bar_type}")

    events: List[BarEvent] = []
    for b in bars:
        ts = pd.Timestamp(b.ts_init, unit="ns", tz="UTC")
        if ts < start or ts >= end:
            continue
        events.append(
            BarEvent(
                timeframe=timeframe,
                end_time_utc=ts.to_pydatetime(),
                o=float(b.open),
                h=float(b.high),
                l=float(b.low),
                c=float(b.close),
                v=float(getattr(b, "volume", 0.0) or 0.0),
            )
        )

    events.sort(key=lambda e: e.end_time_utc)
    return events


def _compute_warmup_cutoff(events_15m: List[BarEvent], warmup_15m_bars: int) -> Optional[datetime]:
    if warmup_15m_bars <= 0:
        return None
    if len(events_15m) < warmup_15m_bars:
        return events_15m[-1].end_time_utc if events_15m else None
    return events_15m[warmup_15m_bars - 1].end_time_utc


def _run_replay(cfg: ReplayConfig) -> None:
    logger = logging.getLogger("mtf_v3_replay")

    catalog = ParquetDataCatalog(str(cfg.catalog_path))

    events_15m = _iter_events_from_catalog(catalog, cfg.bar_type_15m, "15m", cfg.start, cfg.end)
    events_5m = _iter_events_from_catalog(catalog, cfg.bar_type_5m, "5m", cfg.start, cfg.end)

    logger.info("Catalog: %s", cfg.catalog_path)
    logger.info("Bar type 15m: %s (%d bars)", cfg.bar_type_15m, len(events_15m))
    logger.info("Bar type 5m: %s (%d bars)", cfg.bar_type_5m, len(events_5m))
    logger.info("Range UTC: %s to %s (end exclusive)", cfg.start.isoformat(), cfg.end.isoformat())

    if not events_15m:
        raise SystemExit("No 15m bars in requested range")
    if not events_5m:
        raise SystemExit("No 5m bars in requested range")

    warmup_cutoff = _compute_warmup_cutoff(events_15m, cfg.warmup_15m_bars)
    if warmup_cutoff is not None:
        logger.info("Warmup: first %d 15m bars (cutoff=%s)", cfg.warmup_15m_bars, warmup_cutoff.isoformat())

    dataset_logger = HmtfCsvLogger(path=cfg.out_dataset)

    store = FeatureStore()
    sync = SyncGate(store)
    sm = TradingStateMachine(cooldown_minutes=int(os.getenv("MTF3_COOLDOWN_MINUTES", "30")))

    soldier_model_path = Path(os.getenv("MTF3_SOLDIER_MODEL_PATH", "models/soldier_5m_xgb.pkl"))
    if not soldier_model_path.is_absolute():
        soldier_model_path = (PROJECT_ROOT / soldier_model_path).resolve()

    feature_list_path = Path(os.getenv("MTF3_FEATURE_LIST_PATH", "models/soldier_5m_feature_names.txt"))
    if not feature_list_path.is_absolute():
        feature_list_path = (PROJECT_ROOT / feature_list_path).resolve()

    feature_names = load_feature_list(feature_list_path)
    soldier_model = XgbSoldierModel(model_path=soldier_model_path, feature_names=feature_names)

    master_threshold_mode = os.getenv("MTF3_MASTER_THRESHOLD_MODE", "abs").strip().lower()

    # Use the real master model (same feature recipe as offline builder) so replay matches live.
    try:
        master_model_path = Path(os.getenv("MTF3_MASTER_MODEL_PATH", "models/ml_model_mtf.pkl"))
        if not master_model_path.is_absolute():
            master_model_path = (PROJECT_ROOT / master_model_path).resolve()
        master_model = MtfV2SklearnMasterModel(model_path=master_model_path)
        logger.info("Master model enabled: %s", master_model_path)
    except Exception as e:
        logger.exception("Failed to load master model; falling back to DummyMasterModel: %s", e)
        master_model = DummyMasterModel()

    engine = MultiTimeframeEngine(
        store=store,
        sync=sync,
        sm=sm,
        master_model=master_model,
        soldier_model=soldier_model,
        master_threshold=float(os.getenv("MTF3_MASTER_PREDICTION_THRESHOLD", "0.70")),
        master_threshold_mode=master_threshold_mode,
        dataset_logger=dataset_logger,
    )

    router = BarEventRouter(
        engine,
        max_hold_seconds=float(os.getenv("MTF3_ROUTER_MAX_HOLD_SECONDS", "420")),
        time_basis="event_time",
    )

    # Merge-sort all events; if tied, 15m before 5m.
    all_events: List[BarEvent] = []
    all_events.extend(events_15m)
    all_events.extend(events_5m)
    all_events.sort(key=lambda e: (e.end_time_utc, 0 if e.timeframe == "15m" else 1))

    logger.info("Replay events: total=%d", len(all_events))

    # Disable dataset logging during warmup (matches live runner behavior).
    saved_logger = engine.dataset_logger
    if warmup_cutoff is not None:
        engine.dataset_logger = None

    processed = 0
    for ev in all_events:
        if warmup_cutoff is not None and ev.end_time_utc > warmup_cutoff and engine.dataset_logger is None:
            engine.dataset_logger = saved_logger
            logger.info("Warmup ended at %s; dataset logging enabled", warmup_cutoff.isoformat())

        router.submit(ev)
        processed += 1
        if processed % 5000 == 0:
            logger.info("Progress: processed %d / %d events", processed, len(all_events))

    # Restore logger (defensive).
    if engine.dataset_logger is None:
        engine.dataset_logger = saved_logger

    logger.info("Replay complete: events=%d dataset_out=%s", len(all_events), cfg.out_dataset)


def main() -> int:
    _load_env_file()

    # Use v3 config for sensible defaults if available.
    try:
        cfg_v3 = load_mtf_v3_config()
        default_instrument = cfg_v3.instrument
        default_what = cfg_v3.what_to_show
    except Exception:
        default_instrument = os.getenv("MTF3_INSTRUMENT", "EUR/USD.IDEALPRO")
        default_what = os.getenv("MTF3_WHAT_TO_SHOW", "MIDPOINT")

    parser = argparse.ArgumentParser(description="Replay v3 HMTF engine on historical catalog bars (no PnL)")
    parser.add_argument("--catalog", default=str(Path("data") / "historical"), help="Catalog root (default: data/historical)")
    parser.add_argument("--instrument", default=default_instrument, help="Instrument like EUR/USD.IDEALPRO")
    parser.add_argument("--start", default=os.getenv("MTF3_BACKTEST_START", "2025-12-01"), help="YYYY-MM-DD (UTC)")
    parser.add_argument("--end", default=os.getenv("MTF3_BACKTEST_END", "2025-12-05"), help="YYYY-MM-DD (UTC, inclusive)")
    parser.add_argument("--bar-type-15m", default=None, help="Override full catalog bar type for 15m")
    parser.add_argument("--bar-type-5m", default=None, help="Override full catalog bar type for 5m")
    parser.add_argument("--what", default=default_what, help="whatToShow, used only for default bar type construction")
    parser.add_argument("--warmup-15m-bars", type=int, default=30, help="Disable dataset logging for first N 15m bars")
    parser.add_argument("--out", default=None, help="Output directory (default: backtest_results/MTF_V3_REPLAY_<ts>)")
    args = parser.parse_args()

    start, end = _parse_date_range(args.start, args.end)

    bar_type_15m = args.bar_type_15m or _instrument_to_catalog_bar_type(args.instrument, minutes=15, what=args.what)
    bar_type_5m = args.bar_type_5m or _instrument_to_catalog_bar_type(args.instrument, minutes=5, what=args.what)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else (PROJECT_ROOT / "backtest_results" / f"MTF_V3_REPLAY_{ts}")
    out_dataset = out_dir / "hmtf_5m_dataset_replay.csv"

    _setup_logging(out_dir)

    replay_cfg = ReplayConfig(
        catalog_path=Path(args.catalog),
        bar_type_15m=bar_type_15m,
        bar_type_5m=bar_type_5m,
        start=start,
        end=end,
        out_dir=out_dir,
        out_dataset=out_dataset,
        warmup_15m_bars=int(args.warmup_15m_bars),
    )

    _run_replay(replay_cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
