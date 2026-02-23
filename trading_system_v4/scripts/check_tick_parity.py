"""
check_tick_parity.py — Multi-Session Broker Tick Parity Calibration

Measures the IBKR/Dukascopy tick ratio across four session windows per day
and accumulates results in parity_snapshots/session_parity.json.

After 5+ days of measurements, run_live_tick.py automatically uses
session-aware bar sizes instead of a single hardcoded constant.

Session windows measured (UTC):
  asian         01:00–02:00
  london_open   08:00–09:00
  london_ny     14:00–15:00   ← original single-sample window
  ny_afternoon  20:00–21:00

Usage:
  # Measure all 4 sessions for a given date (requires IB Gateway on port 4002)
  python -m trading_system_v4.scripts.check_tick_parity --date 2026-02-18

  # Show summary of accumulated measurements without connecting to IBKR
  python -m trading_system_v4.scripts.check_tick_parity --summary
"""
import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ib_insync import IB, Forex, util
from tick_vault import download_range, read_tick_data

# ── Config ─────────────────────────────────────────────────────────────────────
SYMBOL = "EURUSD"
DUKA_TICKS_PER_TRAINING_BAR = 1_000   # what the model was trained on

ROOT         = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = ROOT / "parity_snapshots"
PARITY_FILE  = SNAPSHOT_DIR / "session_parity.json"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Each entry: (session_label, start_hour_utc, end_hour_utc)
SESSION_WINDOWS = [
    ("asian",        1,  2),
    ("london_open",  8,  9),
    ("london_ny",   14, 15),   # originally measured single window
    ("ny_afternoon", 20, 21),
]


# ── IBKR tick fetch ────────────────────────────────────────────────────────────
def _fetch_ibkr_ticks(ib: IB, start_utc: datetime, end_utc: datetime) -> int:
    contract = Forex(SYMBOL)
    ib.qualifyContracts(contract)

    all_ticks = []
    current_end = end_utc

    while current_end > start_utc:
        end_str = current_end.strftime("%Y%m%d %H:%M:%S UTC")
        try:
            ticks = ib.reqHistoricalTicks(
                contract,
                startDateTime="",
                endDateTime=end_str,
                numberOfTicks=1000,
                whatToShow="BID_ASK",
                useRth=False,
                ignoreSize=False,
            )
        except Exception as e:
            print(f"    [WARN] IBKR error: {e}")
            break

        if not ticks:
            break

        all_ticks.extend(ticks)
        oldest = ticks[0].time
        if oldest >= current_end:
            break
        current_end = oldest
        ib.sleep(1)   # IBKR pacing: max 60 req/10 min

    valid = [t for t in all_ticks if t.time >= start_utc]
    return len(valid)


# ── Dukascopy tick fetch ───────────────────────────────────────────────────────
async def _fetch_duka_ticks(start_utc: datetime, end_utc: datetime) -> int:
    # tick_vault expects naive UTC datetimes
    start = start_utc.replace(tzinfo=None)
    end   = end_utc.replace(tzinfo=None)
    await download_range(symbol=SYMBOL, start=start, end=end)
    df = read_tick_data(symbol=SYMBOL, start=start, end=end)
    if df is None or df.empty:
        return 0
    return len(df)


# ── Persistence ────────────────────────────────────────────────────────────────
def _load_parity_db() -> dict:
    """Load existing measurements. Structure: {session: [ratio, ratio, ...]}"""
    if PARITY_FILE.exists():
        with open(PARITY_FILE) as f:
            return json.load(f)
    return {s: [] for s, *_ in SESSION_WINDOWS}


def _save_parity_db(db: dict) -> None:
    with open(PARITY_FILE, "w") as f:
        json.dump(db, f, indent=2)


def _append_measurement(session: str, ratio: float) -> None:
    db = _load_parity_db()
    if session not in db:
        db[session] = []
    db[session].append(round(ratio, 4))
    _save_parity_db(db)
    print(f"    Saved to {PARITY_FILE}")


# ── Summary / public API ───────────────────────────────────────────────────────
def print_summary() -> None:
    db = _load_parity_db()

    print("\n" + "=" * 65)
    print("PARITY CALIBRATION SUMMARY")
    print(f"  File: {PARITY_FILE}")
    print("=" * 65)
    print(f"  {'Session':<18} {'Samples':>7}  {'Mean ratio':>10}  "
          f"{'Min':>7}  {'Max':>7}  {'IBKR bar size':>13}")
    print("  " + "-" * 63)

    overall_ratios = []
    for session, _, _ in SESSION_WINDOWS:
        ratios = db.get(session, [])
        if not ratios:
            print(f"  {session:<18} {'0':>7}  {'—':>10}")
            continue
        mean_r  = sum(ratios) / len(ratios)
        ibkr_sz = round(DUKA_TICKS_PER_TRAINING_BAR * mean_r)
        overall_ratios.extend(ratios)
        print(f"  {session:<18} {len(ratios):>7}  {mean_r:>10.4f}  "
              f"{min(ratios):>7.4f}  {max(ratios):>7.4f}  {ibkr_sz:>13,}")

    if overall_ratios:
        overall = sum(overall_ratios) / len(overall_ratios)
        overall_sz = round(DUKA_TICKS_PER_TRAINING_BAR * overall)
        print("  " + "-" * 63)
        print(f"  {'OVERALL':<18} {len(overall_ratios):>7}  {overall:>10.4f}  "
              f"{'':>7}  {'':>7}  {overall_sz:>13,}")

    sample_counts = [len(db.get(s, [])) for s, *_ in SESSION_WINDOWS]
    min_samples   = min(sample_counts) if sample_counts else 0
    print("=" * 65)

    if min_samples < 5:
        needed = 5 - min_samples
        print(f"\n  [!] Need {needed} more day(s) of measurements before "
              f"session-aware sizing is reliable.")
        print(f"  Run:  python -m trading_system_v4.scripts.check_tick_parity "
              f"--date YYYY-MM-DD")
    else:
        print(f"\n  [OK] >=5 samples per session. "
              f"run_live_tick.py will use session-aware bar sizes.")
    print()


def build_session_ratios() -> dict[str, int]:
    """
    Return {session: ibkr_ticks_per_bar} from accumulated measurements.
    Falls back to the original single measurement (7854) if data is insufficient
    (< 3 samples for a given session).
    Imported by run_live_tick.py at startup.
    """
    FALLBACK = 7_854
    db = _load_parity_db()
    result = {}
    for session, _, _ in SESSION_WINDOWS:
        ratios = db.get(session, [])
        if len(ratios) >= 3:
            mean_r = sum(ratios) / len(ratios)
            result[session] = round(DUKA_TICKS_PER_TRAINING_BAR * mean_r)
        else:
            result[session] = FALLBACK
    return result


# ── Main ───────────────────────────────────────────────────────────────────────
async def measure_day(target_date: datetime) -> None:
    print(f"\n{'='*65}")
    print(f"PARITY MEASUREMENT  {SYMBOL}  {target_date.strftime('%Y-%m-%d')}")
    print(f"{'='*65}")

    util.startLoop()
    ib = IB()
    try:
        ib.connect("127.0.0.1", 4002, clientId=99)
    except Exception as e:
        print(f"[ERROR] Cannot connect to IBKR: {e}")
        print("Ensure IB Gateway is running on port 4002 (paper account).")
        return

    print("Connected to IBKR.\n")

    for session, h_start, h_end in SESSION_WINDOWS:
        start_utc = target_date.replace(
            hour=h_start, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        end_utc = target_date.replace(
            hour=h_end, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

        if start_utc > datetime.now(tz=timezone.utc):
            print(f"  [{session}] {h_start:02d}:00-{h_end:02d}:00 UTC  SKIPPED (future)")
            continue

        print(f"  [{session}] {h_start:02d}:00-{h_end:02d}:00 UTC")

        duka_count = await _fetch_duka_ticks(start_utc, end_utc)
        ibkr_count = _fetch_ibkr_ticks(ib, start_utc, end_utc)

        if duka_count <= 0 or ibkr_count <= 0:
            print(f"    [SKIP] duka={duka_count}  ibkr={ibkr_count}  "
                  f"(no data for this window)")
            continue

        ratio     = ibkr_count / duka_count
        ibkr_size = round(DUKA_TICKS_PER_TRAINING_BAR * ratio)
        print(f"    Dukascopy: {duka_count:,}  IBKR: {ibkr_count:,}  "
              f"ratio={ratio:.4f}  IBKR bar size={ibkr_size:,}")
        _append_measurement(session, ratio)

    ib.disconnect()
    print("\nDisconnected from IBKR.")
    print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date", default=None,
        help="Date to measure (YYYY-MM-DD). Defaults to most recent weekday.",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="Print accumulated summary without connecting to IBKR.",
    )
    args = parser.parse_args()

    if args.summary:
        print_summary()
    else:
        if args.date:
            target = datetime.strptime(args.date, "%Y-%m-%d")
        else:
            target = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            while target.weekday() >= 5:
                target -= timedelta(days=1)

        if os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(measure_day(target))
