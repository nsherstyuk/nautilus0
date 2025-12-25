from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from live.hmtf_engine import (
    BarEvent,
    BarEventRouter,
    FeatureStore,
    MultiTimeframeEngine,
    SyncGate,
    TradingStateMachine,
    get_dynamic_size,
)
from live.hmtf_csv_logger import HmtfCsvLogger
from live.master_precomputed_model import PrecomputedMasterModel
from live.soldier_xgb_model import XgbSoldierModel, load_feature_list
from scripts.build_hmtf_stitched_dataset import _compute_master_predictions


@dataclass
class Position:
    entry_time: datetime
    entry_price: float
    size_units: int
    sl_price: float
    tp_price: float
    atr_15m: float
    side: str  # "LONG" or "SHORT"
    master_asof_15m_close: datetime
    master_confidence: float
    soldier_score_entry: Optional[float] = None
    # Stall state
    bars_in_trade: int = 0
    max_profit_atr: float = 0.0
    stall_sl_applied: bool = False


@dataclass
class PendingEntry:
    requested_time: datetime
    trigger_score: float


def _setup_logging(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    fh = logging.FileHandler(out_dir / "backtest_v3_replay.log", mode="w", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)

    # Keep console output quiet for long replays; full detail goes to the log file.
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)

    root.handlers.clear()
    root.addHandler(fh)
    root.addHandler(sh)

    # The v3 engine can log per-bar at INFO; suppress on console by default.
    logging.getLogger("hmtf_engine").setLevel(logging.WARNING)

def _load_env_file() -> None:
    env_file = PROJECT_ROOT / ".env.mtf_v3"
    if env_file.exists():
        load_dotenv(env_file, override=False)


def _get_env_date_range() -> Tuple[str, str]:
    # Prefer explicit v3 keys if present; fall back to v2 or generic BACKTEST_* keys.
    s1 = os.getenv("MTF3_BACKTEST_START")
    s2 = os.getenv("MTF2_BACKTEST_START")
    s3 = os.getenv("BACKTEST_START_DATE")
    
    e1 = os.getenv("MTF3_BACKTEST_END")
    e2 = os.getenv("MTF2_BACKTEST_END")
    e3 = os.getenv("BACKTEST_END_DATE")
    
    
    start = (
        s1
        or s2
        or s3
        or "2025-12-01"
    )
    end = (
        e1
        or e2
        or e3
        or "2025-12-05"
    )
    return start, end


def _parse_date_range(start_date: str, end_date: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(start_date).tz_localize("UTC")
    end = pd.Timestamp(end_date).tz_localize("UTC") + pd.Timedelta(days=1)
    return start, end


def _parse_excluded_hours() -> Dict[int, List[int]]:
    """
    Parse excluded hours from env vars (MTF2_EXCLUDED_HOURS_MONDAY, etc.)
    Returns a dict mapping weekday (0=Monday, 6=Sunday) to list of excluded hours (0-23).
    Assumes env vars are in EST (as per v2 config comments) and converts to UTC if needed?
    Actually, v2 config says:
    # TIMEZONE: Set to 'EST' to use Eastern Time, 'UTC' for UTC
    # When EST: Hours are automatically converted to UTC in code
    MTF2_CONFIG_TIMEZONE=EST
    
    For simplicity in this script, we will assume the env vars are provided in the timezone
    specified by MTF2_CONFIG_TIMEZONE (default EST), and we will convert the check time 
    to that timezone before checking.
    """
    mode = os.getenv("MTF2_EXCLUDED_HOURS_MODE", "simple").strip().lower()
    if mode != "weekday":
        print(f"DEBUG: Excluded hours mode is '{mode}' (not 'weekday'); skipping exclusions.")
        return {}

    excluded = {}
    days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
    for i, day in enumerate(days):
        val = os.getenv(f"MTF2_EXCLUDED_HOURS_{day}")
        if val:
            try:
                hours = [int(h.strip()) for h in val.split(",") if h.strip()]
                excluded[i] = hours
            except ValueError:
                pass
    print(f"DEBUG: Parsed excluded hours (mode={mode}): {excluded}")
    return excluded

def _is_excluded_time(ts_utc: datetime, excluded_hours: Dict[int, List[int]], tz_name: str) -> bool:
    if not excluded_hours:
        return False
    
    # Convert UTC timestamp to the config timezone
    if tz_name.upper() == "EST":
        # Approximation for EST/EDT (US/Eastern)
        # Using pytz or zoneinfo would be better, but let's use pandas for robust conversion
        ts_local = pd.Timestamp(ts_utc).tz_convert("US/Eastern")
    elif tz_name.upper() == "UTC":
        ts_local = pd.Timestamp(ts_utc).tz_convert("UTC")
    else:
        # Default to UTC if unknown
        ts_local = pd.Timestamp(ts_utc).tz_convert("UTC")
        
    weekday = ts_local.weekday() # 0=Monday
    hour = ts_local.hour
    
    if weekday in excluded_hours:
        if hour in excluded_hours[weekday]:
            return True
            
    return False
            
    return False



def _instrument_to_catalog_bar_type(instrument: str, minutes: int, what: str = "MID") -> str:
    s = str(instrument).strip()
    venue = "IDEALPRO"
    if "." in s:
        s, venue = s.split(".", 1)
    sym = s.replace("/", "").upper()

    what_norm = str(what).strip().upper()
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


def _commission_usd(size_units: int) -> float:
    # Match v2 backtests.
    return max(1.00, float(size_units) * 0.00002)


def _write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _compute_master_map(df15: pd.DataFrame, model_path: Path) -> Dict[datetime, float]:
    master = _compute_master_predictions(df15, model_path=model_path)

    out: Dict[datetime, float] = {}
    if master.empty:
        return out

    for ts, pred in zip(master["ts_master_15m_close"], master["last_15m_prediction"], strict=False):
        ts_utc = pd.Timestamp(ts).tz_convert("UTC") if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).tz_localize("UTC")
        out[ts_utc.to_pydatetime()] = float(pred)
    return out


def main() -> int:
    _load_env_file()

    parser = argparse.ArgumentParser(
        description="Replay v3 HMTF on historical bars and simulate PnL (paper execution; no IBKR)"
    )
    parser.add_argument("--catalog", default=str(Path("data") / "historical"), help="Catalog root")
    parser.add_argument("--instrument", default=os.getenv("MTF3_INSTRUMENT", "EUR/USD.IDEALPRO"))
    parser.add_argument("--what", default=os.getenv("MTF3_WHAT_TO_SHOW", "MIDPOINT"))

    env_start, env_end = _get_env_date_range()
    parser.add_argument("--start", default=env_start, help="YYYY-MM-DD (UTC)")
    parser.add_argument("--end", default=env_end, help="YYYY-MM-DD (UTC, inclusive)")

    parser.add_argument("--bar-type-15m", default=None)
    parser.add_argument("--bar-type-5m", default=None)

    parser.add_argument(
        "--out",
        default=None,
        help="Output directory (default: backtest_results/MTF_V3_BACKTEST_REPLAY_<ts>)",
    )
    args = parser.parse_args()

    start, end = _parse_date_range(args.start, args.end)

    bar_type_15m = args.bar_type_15m or _instrument_to_catalog_bar_type(args.instrument, minutes=15, what=args.what)
    bar_type_5m = args.bar_type_5m or _instrument_to_catalog_bar_type(args.instrument, minutes=5, what=args.what)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else (PROJECT_ROOT / "backtest_results" / f"MTF_V3_BACKTEST_REPLAY_{ts}")
    _setup_logging(out_dir)

    logger = logging.getLogger("mtf_v3_backtest")

    catalog_path = Path(args.catalog)
    catalog = ParquetDataCatalog(str(catalog_path))

    # Load extra data for warmup
    warmup_days = 5
    load_start = start - timedelta(days=warmup_days)
    logger.info(f"Loading data from {load_start} (warmup) to {end}")

    events_15m = _iter_events_from_catalog(catalog, bar_type_15m, "15m", load_start, end)
    events_5m = _iter_events_from_catalog(catalog, bar_type_5m, "5m", load_start, end)

    logger.info("Catalog: %s", catalog_path)
    logger.info("Bar type 15m: %s (%d bars)", bar_type_15m, len(events_15m))
    logger.info("Bar type 5m: %s (%d bars)", bar_type_5m, len(events_5m))
    logger.info("Range UTC: %s to %s (end exclusive)", start.isoformat(), end.isoformat())

    if not events_15m or not events_5m:
        raise SystemExit("Need both 15m and 5m bars in range")

    # Build 15m DataFrame for master predictions.
    df15 = pd.DataFrame(
        {
            "ts": [pd.Timestamp(e.end_time_utc).tz_convert("UTC") for e in events_15m],
            "open": [e.o for e in events_15m],
            "high": [e.h for e in events_15m],
            "low": [e.l for e in events_15m],
            "close": [e.c for e in events_15m],
            "volume": [e.v for e in events_15m],
        }
    )

    master_model_candidates = [
        os.getenv("MTF3_MASTER_MODEL_PATH"),
        os.getenv("MTF2_MODEL_PATH"),
        "models/ml_model_mtf.pkl",
    ]

    master_model_path: Optional[Path] = None
    for cand in master_model_candidates:
        if not cand:
            continue
        p = Path(cand)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        if p.exists():
            master_model_path = p
            break

    if master_model_path is None:
        raise SystemExit(
            "Master model not found. Set MTF3_MASTER_MODEL_PATH in .env.mtf_v3 (or ensure MTF2_MODEL_PATH exists)."
        )

    predictions_by_close = _compute_master_map(df15, model_path=master_model_path)
    logger.info("Master predictions precomputed: %d timestamps", len(predictions_by_close))

    # Soldier model is always used for scoring in v3 replay PnL.
    soldier_model_path = Path(os.getenv("MTF3_SOLDIER_MODEL_PATH", "models/soldier_5m_xgb.pkl"))
    if not soldier_model_path.is_absolute():
        soldier_model_path = (PROJECT_ROOT / soldier_model_path).resolve()

    feature_list_path = Path(os.getenv("MTF3_FEATURE_LIST_PATH", "models/soldier_5m_feature_names.txt"))
    if not feature_list_path.is_absolute():
        feature_list_path = (PROJECT_ROOT / feature_list_path).resolve()

    feature_names = load_feature_list(feature_list_path)
    soldier_model = XgbSoldierModel(model_path=soldier_model_path, feature_names=feature_names)

    master_threshold = float(os.getenv("MTF3_MASTER_PREDICTION_THRESHOLD", "0.70"))
    master_threshold_mode = os.getenv("MTF3_MASTER_THRESHOLD_MODE", "signed").strip().lower()
    soldier_entry_threshold = float(os.getenv("MTF3_SOLDIER_ENTRY_THRESHOLD", "0.50"))
    print(f"DEBUG: soldier_entry_threshold={soldier_entry_threshold}")
    soldier_exit_threshold = float(os.getenv("MTF3_SOLDIER_EXIT_THRESHOLD", "0.10"))

    tp_atr_mult = float(os.getenv("MTF3_TP_ATR_MULT", "0.6"))
    sl_atr_mult = float(os.getenv("MTF3_SL_ATR_MULT", "1.4"))

    # Stall Detection Config (using MTF2 keys as requested/configured)
    stall_detection_enabled = os.getenv("MTF2_STALL_DETECTION_ENABLED", "False").strip().lower() == "true"
    stall_check_bars = int(os.getenv("MTF2_STALL_CHECK_BARS", "6"))
    stall_min_profit_atr = float(os.getenv("MTF2_STALL_MIN_PROFIT_ATR", "0.2"))
    stall_sl_atr = float(os.getenv("MTF2_STALL_SL_ATR", "0.2"))

    starting_equity = float(
        os.getenv(
            "MTF3_PAPER_STARTING_EQUITY_USD",
            os.getenv(
                "BACKTEST_STARTING_CAPITAL",
                os.getenv("MTF3_INITIAL_EQUITY_USD", "4500"),
            ),
        )
    )
    equity = starting_equity

    tie_policy = os.getenv("MTF3_TP_SL_TIEBREAK", "sl_first").strip().lower()

    # Exclusion Config
    excluded_hours = _parse_excluded_hours()
    config_timezone = os.getenv("MTF2_CONFIG_TIMEZONE", "EST")

    if master_threshold_mode not in {"signed", "abs"}:
        logging.getLogger("mtf_v3_backtest").warning(
            "Unknown MTF3_MASTER_THRESHOLD_MODE=%r; defaulting to 'signed'", master_threshold_mode
        )
        master_threshold_mode = "signed"

    def _macro_permission_ok(conf: float) -> bool:
        if master_threshold_mode == "abs":
            return abs(conf) > master_threshold
        return conf > master_threshold

    def _side_from_master(conf: float) -> str:
        # In signed mode we only enter LONG (conf > threshold).
        if master_threshold_mode == "abs":
            return "SHORT" if conf < 0 else "LONG"
        return "LONG"

    # Output collectors
    trades: List[Dict[str, object]] = []
    equity_curve: List[Dict[str, object]] = []

    # Strategy state
    position: Optional[Position] = None
    pending_entry: Optional[PendingEntry] = None

    # We need access to the *next* 5m bar open for entry fills.
    next_5m_by_close: Dict[datetime, BarEvent] = {e.end_time_utc: e for e in events_5m}

    def on_soldier(bar: BarEvent, master, score: float, features: Dict[str, float]) -> None:
        nonlocal position, pending_entry

        # Gate entries by macro permission. (Engine state-machine may be long-only unless enabled.)
        if not _macro_permission_ok(float(master.confidence)):
            return

        # Gate entries by excluded hours
        if _is_excluded_time(bar.end_time_utc, excluded_hours, config_timezone):
            return

        if position is not None or pending_entry is not None:
            return

        # Entry rule: soldier score threshold.
        if score >= soldier_entry_threshold:
            pending_entry = PendingEntry(requested_time=bar.end_time_utc, trigger_score=score)

    store = FeatureStore()
    sync = SyncGate(store)
    sm = TradingStateMachine(cooldown_minutes=int(os.getenv("MTF3_COOLDOWN_MINUTES", "30")))

    master_model = PrecomputedMasterModel(predictions_by_close=predictions_by_close)

    # Disable dataset logging by default for backtests.
    dataset_logger = None
    if os.getenv("MTF3_DATASET_ENABLED", "False").strip().lower() == "true":
        dataset_path = Path(os.getenv("MTF3_DATASET_PATH", "logs/live_mtf/hmtf_5m_dataset.csv"))
        if not dataset_path.is_absolute():
            dataset_path = (PROJECT_ROOT / dataset_path).resolve()
        dataset_logger = HmtfCsvLogger(path=dataset_path)

    engine = MultiTimeframeEngine(
        store=store,
        sync=sync,
        sm=sm,
        master_model=master_model,
        soldier_model=soldier_model,
        master_threshold=master_threshold,
        master_threshold_mode=master_threshold_mode,
        dataset_logger=dataset_logger,
        on_soldier_evaluated=on_soldier,
    )

    router = BarEventRouter(
        engine,
        max_hold_seconds=float(os.getenv("MTF3_ROUTER_MAX_HOLD_SECONDS", "420")),
        time_basis="event_time",
    )

    # Prepare combined event stream.
    # To mimic IBKR reality: at quarter-hour boundaries, the 5m bar close may arrive before the 15m.
    events_by_time: Dict[datetime, List[BarEvent]] = {}
    for ev in events_15m + events_5m:
        events_by_time.setdefault(ev.end_time_utc, []).append(ev)

    all_times = sorted(events_by_time.keys())

    # Replay loop
    for t in all_times:
        evs = events_by_time[t]

        # If both 5m and 15m exist at this time, submit 5m first to test router hold logic.
        evs_sorted = sorted(evs, key=lambda e: 0 if e.timeframe == "5m" else 1)

        for ev in evs_sorted:
            router.submit(ev)

        # After engine processed this timestamp, manage paper execution using 5m bars.
        # Entry fill happens on the next 5m bar open after an entry trigger.
        bar5 = next_5m_by_close.get(t)
        if bar5 is None:
            continue

        # Exit logic first (manage open position on current bar)
        if position is not None:
            # Update position stats
            position.bars_in_trade += 1
            current_price = float(bar5.c)
            atr_val = position.atr_15m
            
            if position.side == "LONG":
                profit_atr = (current_price - position.entry_price) / atr_val if atr_val > 0 else 0
            else:
                profit_atr = (position.entry_price - current_price) / atr_val if atr_val > 0 else 0
            
            if profit_atr > position.max_profit_atr:
                position.max_profit_atr = profit_atr

            # Stall Detection Logic
            if (
                stall_detection_enabled
                and not position.stall_sl_applied
                and position.bars_in_trade >= stall_check_bars
                and position.max_profit_atr >= stall_min_profit_atr
                # Ensure we don't apply if we are already past TP (though TP check is below)
            ):
                # Calculate new SL distance
                new_sl_dist = atr_val * stall_sl_atr
                
                if position.side == "LONG":
                    new_sl = position.entry_price - new_sl_dist
                    # Tighten only
                    if new_sl > position.sl_price:
                        position.sl_price = new_sl
                        position.stall_sl_applied = True
                else:
                    new_sl = position.entry_price + new_sl_dist
                    # Tighten only
                    if new_sl < position.sl_price:
                        position.sl_price = new_sl
                        position.stall_sl_applied = True

            exit_reason: Optional[str] = None
            exit_price: Optional[float] = None
            soldier_score_exit = engine.last_soldier_score

            # DISABLED: Master Reversal Check
            # If the Master Model flips to a strong signal in the OPPOSITE direction, exit immediately.
            # current_master = engine.store.last_master
            # if current_master and exit_reason is None:
            #     conf = float(current_master.confidence)
            #     if master_threshold_mode == "abs":
            #         # In 'abs' mode: LONG > +0.7, SHORT < -0.7
            #         if position.side == "LONG" and conf < -master_threshold:
            #             exit_reason, exit_price = "MASTER_REVERSAL", float(bar5.c)
            #         elif position.side == "SHORT" and conf > master_threshold:
            #             exit_reason, exit_price = "MASTER_REVERSAL", float(bar5.c)

            # Hard TP/SL intrabar
            if exit_reason is None:
                if position.side == "SHORT":
                    hit_sl = bar5.h >= position.sl_price
                    hit_tp = bar5.l <= position.tp_price
                else:
                    hit_sl = bar5.l <= position.sl_price
                    hit_tp = bar5.h >= position.tp_price
                if hit_sl and hit_tp:
                    if tie_policy == "tp_first":
                        exit_reason, exit_price = "TP", position.tp_price
                    else:
                        exit_reason, exit_price = "SL", position.sl_price
                elif hit_sl:
                    exit_reason, exit_price = "SL", position.sl_price
                elif hit_tp:
                    exit_reason, exit_price = "TP", position.tp_price

            # DISABLED: Optional early exit if soldier score flipped materially against
            # if exit_reason is None:
            #     score = engine.last_soldier_score
            #     if score is not None and score <= soldier_exit_threshold:
            #         exit_reason, exit_price = "SOLDIER_FLIP", float(bar5.c)

            if exit_reason is not None and exit_price is not None:
                if position.side == "SHORT":
                    pnl_gross = (float(position.entry_price) - float(exit_price)) * float(position.size_units)
                else:
                    pnl_gross = (float(exit_price) - float(position.entry_price)) * float(position.size_units)
                commission = _commission_usd(position.size_units) * 2.0
                pnl_net = pnl_gross - commission

                equity_before = equity
                equity = equity + pnl_net

                trades.append(
                    {
                        "entry_time": position.entry_time.isoformat(),
                        "exit_time": bar5.end_time_utc.isoformat(),
                        "entry_price": position.entry_price,
                        "exit_price": float(exit_price),
                        "side": position.side,
                        "size_units": int(position.size_units),
                        "atr_15m": float(position.atr_15m),
                        "tp_price": float(position.tp_price),
                        "sl_price": float(position.sl_price),
                        "reason": exit_reason,
                        "pnl_gross": float(pnl_gross),
                        "commission": float(commission),
                        "pnl_net": float(pnl_net),
                        "equity_before": float(equity_before),
                        "equity_after": float(equity),
                        "master_asof_15m_close": position.master_asof_15m_close.isoformat(),
                        "master_confidence": float(position.master_confidence),
                        "soldier_score_entry": (
                            float(position.soldier_score_entry) if position.soldier_score_entry is not None else None
                        ),
                        "soldier_score_exit": float(soldier_score_exit) if soldier_score_exit is not None else None,
                    }
                )

                sm.enter_cooldown(bar5.end_time_utc)
                
                # Log exit
                print(f"[{bar5.end_time_utc}] EXIT {position.side} @ {exit_price:.5f} ({exit_reason}) PnL: ${pnl_net:.2f}")
                
                position = None
                pending_entry = None

        # Entry fill
        if position is None and pending_entry is not None:
            # Fill at next bar open (current bar open is already known; pending_entry came from prior close).
            if bar5.end_time_utc > pending_entry.requested_time:
                master = store.last_master
                if master is not None and _macro_permission_ok(float(master.confidence)) and master.atr_15m > 0:
                    size_units = int(get_dynamic_size(equity, master.atr_15m, bar5.o))
                    side = _side_from_master(float(master.confidence))
                    soldier_score_entry = pending_entry.trigger_score
                    if side == "SHORT":
                        sl_price = float(bar5.o) + float(sl_atr_mult) * float(master.atr_15m)
                        tp_price = float(bar5.o) - float(tp_atr_mult) * float(master.atr_15m)
                    else:
                        sl_price = float(bar5.o) - float(sl_atr_mult) * float(master.atr_15m)
                        tp_price = float(bar5.o) + float(tp_atr_mult) * float(master.atr_15m)
                    
                    # Log entry with sizing details
                    risk_pct = equity * 0.01
                    sl_dist = float(master.atr_15m) * float(sl_atr_mult)
                    print(f"[{bar5.end_time_utc}] ENTRY {side} @ {bar5.o:.5f} Size: {size_units} (Equity: ${equity:.2f}, Risk: ${risk_pct:.2f}, ATR: {master.atr_15m:.5f}, SL_dist: {sl_dist:.5f})")
                    
                    position = Position(
                        entry_time=bar5.end_time_utc,
                        entry_price=float(bar5.o),
                        size_units=size_units,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        atr_15m=float(master.atr_15m),
                        side=side,
                        master_asof_15m_close=master.asof_15m_close,
                        master_confidence=float(master.confidence),
                        soldier_score_entry=float(soldier_score_entry) if soldier_score_entry is not None else None,
                    )

                    pending_entry = None

        equity_curve.append({"ts": bar5.end_time_utc.isoformat(), "equity": float(equity)})

    # Write outputs
    trades_path = out_dir / "trades.csv"
    eq_path = out_dir / "equity_curve.csv"

    if trades:
        _write_csv(
            trades_path,
            trades,
            fieldnames=list(trades[0].keys()),
        )
    else:
        trades_path.write_text("", encoding="utf-8")

    _write_csv(eq_path, equity_curve, fieldnames=["ts", "equity"])

    # Generate PnL Matrix and other reports if trades exist
    if trades:
        df_trades = pd.DataFrame(trades)
        # Ensure entry_time is datetime
        df_trades['entry_time'] = pd.to_datetime(df_trades['entry_time'])
        df_trades['pnl'] = df_trades['pnl_net'] # Use net pnl for analysis

        # Convert to config timezone for analysis
        if config_timezone.upper() == 'EST':
             df_trades['entry_time_local'] = df_trades['entry_time'].dt.tz_convert('US/Eastern')
        else:
             df_trades['entry_time_local'] = df_trades['entry_time'].dt.tz_convert('UTC')

        df_trades['entry_weekday'] = df_trades['entry_time_local'].dt.weekday
        df_trades['entry_hour'] = df_trades['entry_time_local'].dt.hour
        df_trades['entry_month'] = df_trades['entry_time_local'].dt.to_period('M')

        weekday_names = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri', 5: 'Sat', 6: 'Sun'}

        # === performance_by_weekday.csv ===
        weekday_stats = df_trades.groupby('entry_weekday').agg({
            'pnl': ['sum', 'count', lambda x: (x > 0).mean() * 100]
        }).round(2)
        weekday_stats.columns = ['pnl', 'trades', 'win_rate']
        weekday_stats.index = weekday_stats.index.map(weekday_names)
        weekday_stats.to_csv(out_dir / 'performance_by_weekday.csv')
        
        # === performance_by_month.csv ===
        month_stats = df_trades.groupby('entry_month').agg({
            'pnl': ['sum', 'count', lambda x: (x > 0).mean() * 100]
        }).round(2)
        month_stats.columns = ['pnl', 'trades', 'win_rate']
        month_stats.to_csv(out_dir / 'performance_by_month.csv')

        # === hour_weekday matrices ===
        logger.info(f"Generating hour statistics in {config_timezone} timezone")
        
        pivot_pnl = df_trades.pivot_table(values='pnl', index='entry_hour', columns='entry_weekday', aggfunc='sum', fill_value=0)
        pivot_pnl.columns = [weekday_names.get(c, c) for c in pivot_pnl.columns]
        pivot_pnl.index.name = f'hour_{config_timezone}'
        pivot_pnl.to_csv(out_dir / 'hour_weekday_pnl_matrix.csv', float_format='%.1f')
        
        pivot_trades = df_trades.pivot_table(values='pnl', index='entry_hour', columns='entry_weekday', aggfunc='count', fill_value=0)
        pivot_trades.columns = [weekday_names.get(c, c) for c in pivot_trades.columns]
        pivot_trades.index.name = f'hour_{config_timezone}'
        pivot_trades.to_csv(out_dir / 'hour_weekday_trades_matrix.csv')
        
        # Win rate matrix
        def win_rate_agg(x):
            return (x > 0).mean() * 100 if len(x) > 0 else 0
        
        pivot_wr = df_trades.pivot_table(values='pnl', index='entry_hour', columns='entry_weekday', aggfunc=win_rate_agg, fill_value=0)
        pivot_wr.columns = [weekday_names.get(c, c) for c in pivot_wr.columns]
        pivot_wr.index.name = f'hour_{config_timezone}'
        pivot_wr.to_csv(out_dir / 'hour_weekday_winrate_matrix.csv')

    summary = {
        "start": str(start.date()),
        "end": str((end - pd.Timedelta(days=1)).date()),
        "starting_equity": float(starting_equity),
        "ending_equity": float(equity),
        "net_pnl": float(equity - starting_equity),
        "trades": int(len(trades)),
        "master_threshold": float(master_threshold),
        "master_threshold_mode": master_threshold_mode,
        "soldier_entry_threshold": float(soldier_entry_threshold),
        "tp_atr_mult": float(tp_atr_mult),
        "sl_atr_mult": float(sl_atr_mult),
        "tiebreak": tie_policy,
    }

    (out_dir / "summary.json").write_text(pd.Series(summary).to_json(indent=2), encoding="utf-8")

    logger.info("Backtest complete: trades=%d net_pnl=%.2f ending_equity=%.2f", len(trades), equity - starting_equity, equity)
    logger.info("Outputs: %s", out_dir)

    # Print summary to console (matching v2 style)
    print("\n" + "=" * 80)
    print("BACKTEST SUMMARY")
    print("=" * 80)
    print(f"Total Trades: {len(trades)}")
    print(f"Total P&L: ${equity - starting_equity:,.2f}")
    win_rate = (sum(1 for t in trades if t['pnl_net'] > 0) / len(trades) * 100) if trades else 0.0
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Output Directory: {out_dir}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
