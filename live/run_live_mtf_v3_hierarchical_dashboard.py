from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.mtf_v3_config import load_mtf_v3_config
from live.hmtf_csv_logger import HmtfCsvLogger
from live.hmtf_engine import (
    BarEvent,
    BarEventRouter,
    DummySoldierModel,
    FeatureStore,
    MultiTimeframeEngine,
    SyncGate,
    TradingStateMachine,
)
from live.ib_bar_streamer import IBBarStreamer
from live.master_mtf_v2_model import MtfV2SklearnMasterModel
from live.soldier_xgb_model import XgbSoldierModel, load_feature_list
from utils.run_metadata import log_and_write_run_metadata

logger = logging.getLogger("live_mtf_v3_hierarchical")


def _load_env_file() -> None:
    env_file = PROJECT_ROOT / ".env.mtf_v3"
    if env_file.exists():
        # Don't clobber runtime env vars (e.g., temporary client id overrides for testing).
        load_dotenv(env_file, override=False)


def _instrument_to_ib_symbol(instrument: str) -> str:
    # Expected format: "EUR/USD.IDEALPRO" -> "EUR/USD"
    s = str(instrument).strip()
    if "." in s:
        s = s.split(".", 1)[0]
    return s


def _nt_bar_to_event(nt_bar, timeframe: str) -> BarEvent:
    # Nautilus Bar uses nanosecond ts_event; treat it as the bar close timestamp.
    end_time = datetime.fromtimestamp(nt_bar.ts_event / 1_000_000_000, tz=timezone.utc)
    return BarEvent(
        timeframe=timeframe,
        end_time_utc=end_time,
        o=float(nt_bar.open.as_double()),
        h=float(nt_bar.high.as_double()),
        l=float(nt_bar.low.as_double()),
        c=float(nt_bar.close.as_double()),
        v=float(nt_bar.volume.as_double()) if hasattr(nt_bar.volume, "as_double") else 0.0,
    )


async def main_async() -> int:
    _load_env_file()
    cfg = load_mtf_v3_config()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_and_write_run_metadata(
        logger,
        output_dir=PROJECT_ROOT / "logs" / "live_mtf",
        run_kind="live",
        run_id=run_id,
        entrypoint=__file__,
        extra={"logger": "live_mtf_v3_hierarchical", "env_file": ".env.mtf_v3"},
    )

    logger.info(
        "Router hold config: router_max_hold_seconds=%.1f (env MTF3_ROUTER_MAX_HOLD_SECONDS=%r)",
        cfg.router_max_hold_seconds,
        os.getenv("MTF3_ROUTER_MAX_HOLD_SECONDS"),
    )

    symbol = _instrument_to_ib_symbol(cfg.instrument)

    dataset_logger = None
    if cfg.dataset_enabled:
        dataset_path = Path(cfg.dataset_path)
        if not dataset_path.is_absolute():
            dataset_path = (PROJECT_ROOT / dataset_path).resolve()
        logger.info("Dataset logging enabled: path=%s", dataset_path)
        dataset_logger = HmtfCsvLogger(path=dataset_path)

    # Soldier model (optional trained model)
    soldier_model = DummySoldierModel()
    if cfg.soldier_model_enabled:
        try:
            soldier_model_path = Path(cfg.soldier_model_path)
            if not soldier_model_path.is_absolute():
                soldier_model_path = (PROJECT_ROOT / soldier_model_path).resolve()

            feature_list_path = Path(cfg.feature_list_path)
            if not feature_list_path.is_absolute():
                feature_list_path = (PROJECT_ROOT / feature_list_path).resolve()

            feature_names = load_feature_list(feature_list_path)
            soldier_model = XgbSoldierModel(model_path=soldier_model_path, feature_names=feature_names)
            logger.info(
                "Soldier model enabled: xgboost model=%s features=%d (%s)",
                soldier_model_path,
                len(feature_names),
                feature_list_path,
            )
        except Exception as e:
            logger.exception("Failed to load trained soldier model; falling back to DummySoldierModel: %s", e)
            soldier_model = DummySoldierModel()
    else:
        logger.info("Soldier model disabled: using DummySoldierModel")

    store = FeatureStore()
    sync = SyncGate(store)
    sm = TradingStateMachine(cooldown_minutes=cfg.cooldown_minutes)

    # Master model (15m)
    try:
        master_model_path = Path(cfg.master_model_path)
        if not master_model_path.is_absolute():
            master_model_path = (PROJECT_ROOT / master_model_path).resolve()
        master_model = MtfV2SklearnMasterModel(model_path=master_model_path)
        logger.info("Master model enabled: %s", master_model_path)
    except Exception as e:
        logger.exception("Failed to load master model; master signals will be neutral: %s", e)
        from live.hmtf_engine import DummyMasterModel

        master_model = DummyMasterModel()

    engine = MultiTimeframeEngine(
        store=store,
        sync=sync,
        sm=sm,
        master_model=master_model,
        soldier_model=soldier_model,
        master_threshold=cfg.master_prediction_threshold,
        master_threshold_mode=cfg.master_threshold_mode,
        dataset_logger=dataset_logger,
    )
    router = BarEventRouter(engine, max_hold_seconds=cfg.router_max_hold_seconds)

    streamer = IBBarStreamer(
        host=cfg.ibkr_host,
        port=cfg.ibkr_port,
        client_id=cfg.ibkr_client_id,
    )

    stop_event = asyncio.Event()

    def _request_stop(_sig=None, _frame=None) -> None:
        try:
            logger.info("Stopping v3 runner...")
            streamer.disconnect()
        finally:
            stop_event.set()

    try:
        signal.signal(signal.SIGINT, _request_stop)
    except Exception:
        pass
    try:
        signal.signal(signal.SIGTERM, _request_stop)
    except Exception:
        pass

    if not streamer.connect():
        logger.error("IBBarStreamer connect failed")
        return 1

    ok_15m = streamer.subscribe_bars_sync(
        symbol=symbol,
        bar_size=cfg.master_bar_size,
        what_to_show=cfg.what_to_show,
        use_rth=cfg.use_rth,
        duration=cfg.initial_duration,
        callback=lambda b: router.submit(_nt_bar_to_event(b, timeframe="15m")),
        is_resubscribe=True,  # skip per-stream warmup feeding; we merge-sort warmup across TFs below
    )

    ok_5m = streamer.subscribe_bars_sync(
        symbol=symbol,
        bar_size=cfg.soldier_bar_size,
        what_to_show=cfg.what_to_show,
        use_rth=cfg.use_rth,
        duration=cfg.initial_duration,
        callback=lambda b: router.submit(_nt_bar_to_event(b, timeframe="5m")),
        is_resubscribe=True,  # skip per-stream warmup feeding; we merge-sort warmup across TFs below
    )

    if not ok_15m or not ok_5m:
        logger.error("Failed to subscribe bars (15m_ok=%s, 5m_ok=%s)", ok_15m, ok_5m)
        streamer.disconnect()
        return 1

    # Warmup: merge-sort historical bars across timeframes to avoid lookahead artifacts.
    warmup_15m = streamer.get_warmup_bars_sync(
        symbol=symbol,
        bar_size=cfg.master_bar_size,
        what_to_show=cfg.what_to_show,
        use_rth=cfg.use_rth,
    )
    warmup_5m = streamer.get_warmup_bars_sync(
        symbol=symbol,
        bar_size=cfg.soldier_bar_size,
        what_to_show=cfg.what_to_show,
        use_rth=cfg.use_rth,
    )

    def _floor_to_15m(ts: datetime) -> datetime:
        minute = ts.minute - (ts.minute % 15)
        return ts.replace(minute=minute, second=0, microsecond=0)

    # Ensure we don't feed 5m bars that cannot be stitched to an available 15m close.
    # This avoids warmup ending with stale master_asof simply because IB didn't include
    # the latest completed 15m bar in the initial history snapshot.
    warmup_15m_events = [_nt_bar_to_event(b, timeframe="15m") for b in warmup_15m]
    master_close_set = {ev.end_time_utc for ev in warmup_15m_events}
    warmup_5m_filtered = []
    dropped_5m = 0
    for b in warmup_5m:
        ev5 = _nt_bar_to_event(b, timeframe="5m")
        expected_master_close = _floor_to_15m(ev5.end_time_utc)
        if expected_master_close in master_close_set:
            warmup_5m_filtered.append(b)
        else:
            dropped_5m += 1

    if dropped_5m:
        logger.info(
            "Warmup: dropped %d 5m bar(s) with missing expected 15m close (kept=%d)",
            dropped_5m,
            len(warmup_5m_filtered),
        )

    logger.info(
        "Warmup merge-sort: 15m=%d bars, 5m=%d bars",
        len(warmup_15m),
        len(warmup_5m_filtered),
    )

    warmup_events = []
    warmup_events.extend(warmup_15m_events)
    for b in warmup_5m_filtered:
        warmup_events.append(_nt_bar_to_event(b, timeframe="5m"))

    # Sort by close timestamp; if tied, 15m before 5m.
    warmup_events.sort(key=lambda e: (e.end_time_utc, 0 if e.timeframe == "15m" else 1))

    # Do NOT log dataset rows during warmup (prevents duplicates on restart).
    saved_logger = engine.dataset_logger
    engine.dataset_logger = None
    try:
        for ev in warmup_events:
            if ev.timeframe == "15m":
                engine.on_15m_close(ev)
            elif ev.timeframe == "5m":
                engine.on_5m_close(ev)
    finally:
        engine.dataset_logger = saved_logger
    logger.info("Warmup complete")

    logger.info(
        "MTF v3 runner started. symbol=%s 15m='%s' 5m='%s' dataset=%s",
        symbol,
        cfg.master_bar_size,
        cfg.soldier_bar_size,
        cfg.dataset_path if cfg.dataset_enabled else "disabled",
    )

    run_task = asyncio.create_task(streamer.run_forever())
    await stop_event.wait()

    try:
        await asyncio.wait_for(run_task, timeout=5.0)
    except Exception:
        pass

    return 0


def main() -> int:
    if "--check-soldier-model" in sys.argv:
        _load_env_file()
        cfg = load_mtf_v3_config()

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

        soldier_model_path = Path(cfg.soldier_model_path)
        if not soldier_model_path.is_absolute():
            soldier_model_path = (PROJECT_ROOT / soldier_model_path).resolve()

        feature_list_path = Path(cfg.feature_list_path)
        if not feature_list_path.is_absolute():
            feature_list_path = (PROJECT_ROOT / feature_list_path).resolve()

        feature_names = load_feature_list(feature_list_path)
        soldier_model = XgbSoldierModel(model_path=soldier_model_path, feature_names=feature_names)

        score = soldier_model.predict({name: 0.0 for name in feature_names})
        logger.info(
            "Soldier model OK: enabled=%s model=%s features=%d score(sample_zeros)=%.6f",
            cfg.soldier_model_enabled,
            soldier_model_path,
            len(feature_names),
            score,
        )
        return 0

    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
