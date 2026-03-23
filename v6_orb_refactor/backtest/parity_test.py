"""
Parity test: Run V5 and V6 backtests on the same XAUUSD 1m data,
compare trade-by-trade to prove identical behavior.

Usage:
    python -m v6_orb_refactor.backtest.parity_test
"""
from __future__ import annotations
import sys
from pathlib import Path
import logging

# Ensure project root on path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pandas as pd

# ── V5 imports ───────────────────────────────────────────────────────────
from v5_xauusd_orb.backtest_1m import (
    load_1m_bars, backtest as v5_backtest, Config as V5Config, stats as v5_stats,
    print_stats as v5_print_stats, Trade as V5Trade
)

# ── V6 imports ───────────────────────────────────────────────────────────
from v6_orb_refactor.config.config import StrategyConfig
from v6_orb_refactor.backtest.engine import BacktestRunner


DATA_FILE = ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv'


def run_v5(df: pd.DataFrame) -> list[V5Trade]:
    """Run V5 backtest: stop entry, no time exit, no velocity filter, skip Wed."""
    cfg = V5Config(
        range_start=0,
        range_end=6,
        trade_start=8,
        trade_end=16,
        rr_ratio=2.5,
        min_range_pct=0.05,
        max_range_pct=2.0,
        skip_weekdays=[2],
        time_exit_minutes=0,
        entry_method='stop',
    )
    return v5_backtest(df, cfg)


def run_v6() -> list[dict]:
    """Run V6 backtest with matching config, return list of trade dicts."""
    logger = logging.getLogger('v6_parity')
    logger.setLevel(logging.WARNING)  # Suppress per-trade logs

    config = StrategyConfig(
        instrument="XAUUSD",
        range_start_hour=0,
        range_end_hour=6,
        trade_start_hour=8,
        trade_end_hour=16,
        skip_weekdays=(2,),
        velocity_filter_enabled=False,  # Disable for parity
        gap_filter_enabled=False,       # Disable for parity
        velocity_lookback_minutes=3,
        velocity_threshold=0.0,
        rr_ratio=2.5,
        min_range_pct=0.05,
        max_range_pct=2.0,
        be_hours=999,           # No breakeven
        be_offset=2.0,
        max_pending_hours=0,    # No pending timeout
        time_exit_minutes=0,    # No time exit
        qty=1,
        point_value=1.0,
        price_decimals=2,
    )

    runner = BacktestRunner(
        data_path=str(DATA_FILE),
        config=config,
        logger=logger,
    )
    fills = runner.run()

    # Convert fills to trade dicts (pair ENTRY with exit)
    trades = []
    current = None
    for fill in fills:
        if fill.reason == "ENTRY":
            current = {
                "direction": fill.direction,
                "entry_price": fill.price,
                "entry_time": fill.timestamp,
            }
        elif current is not None:
            mult = 1 if current["direction"] == "LONG" else -1
            pnl = (fill.price - current["entry_price"]) * mult
            current["exit_price"] = fill.price
            current["exit_time"] = fill.timestamp
            current["exit_type"] = fill.reason
            current["pnl"] = pnl
            current["date"] = current["entry_time"].date() if hasattr(current["entry_time"], 'date') else current["entry_time"]
            trades.append(current)
            current = None

    return trades


def compare(v5_trades: list[V5Trade], v6_trades: list[dict]):
    """Compare V5 and V6 trades, print discrepancies."""
    print(f"\n{'='*90}")
    print(f"  PARITY TEST: V5 vs V6")
    print(f"{'='*90}")
    print(f"  V5 trades: {len(v5_trades)}")
    print(f"  V6 trades: {len(v6_trades)}")

    # Build date-indexed dicts for matching
    v5_by_date = {}
    for t in v5_trades:
        v5_by_date[t.date] = t

    v6_by_date = {}
    for t in v6_trades:
        d = t["date"]
        v6_by_date[d] = t

    all_dates = sorted(set(v5_by_date.keys()) | set(v6_by_date.keys()))

    v5_only = []
    v6_only = []
    matched = []
    mismatches = []

    for d in all_dates:
        in_v5 = d in v5_by_date
        in_v6 = d in v6_by_date

        if in_v5 and not in_v6:
            v5_only.append(d)
        elif in_v6 and not in_v5:
            v6_only.append(d)
        else:
            t5 = v5_by_date[d]
            t6 = v6_by_date[d]
            matched.append(d)

            # Compare key fields
            diffs = []
            if t5.direction != t6["direction"]:
                diffs.append(f"dir: {t5.direction} vs {t6['direction']}")
            if abs(t5.entry_price - t6["entry_price"]) > 0.011:
                diffs.append(f"entry: {t5.entry_price:.3f} vs {t6['entry_price']:.3f}")
            if abs(t5.exit_price - t6["exit_price"]) > 0.011:
                diffs.append(f"exit: {t5.exit_price:.3f} vs {t6['exit_price']:.3f}")
            if t5.exit_type != t6["exit_type"]:
                # Map V5 "EOD" to V6 "MARKET"
                v5_etype = "MARKET" if t5.exit_type == "EOD" else t5.exit_type
                if v5_etype != t6["exit_type"]:
                    diffs.append(f"exit_type: {t5.exit_type} vs {t6['exit_type']}")
            if abs(t5.pnl - t6["pnl"]) > 0.011:
                diffs.append(f"pnl: {t5.pnl:.3f} vs {t6['pnl']:.3f}")

            if diffs:
                mismatches.append((d, diffs))

    print(f"\n  Matched dates:     {len(matched)}")
    print(f"  V5-only dates:     {len(v5_only)}")
    print(f"  V6-only dates:     {len(v6_only)}")
    print(f"  Mismatched trades: {len(mismatches)}")

    # Show V5-only and V6-only
    if v5_only:
        print(f"\n  V5-ONLY trades (first 20):")
        for d in v5_only[:20]:
            t = v5_by_date[d]
            print(f"    {d} | {t.direction:5s} | entry={t.entry_price:.3f} | "
                  f"exit={t.exit_price:.3f} | {t.exit_type:3s} | pnl={t.pnl:+.3f}")

    if v6_only:
        print(f"\n  V6-ONLY trades (first 20):")
        for d in v6_only[:20]:
            t = v6_by_date[d]
            print(f"    {d} | {t['direction']:5s} | entry={t['entry_price']:.3f} | "
                  f"exit={t['exit_price']:.3f} | {t['exit_type']:3s} | pnl={t['pnl']:+.3f}")

    # Show mismatches
    if mismatches:
        print(f"\n  MISMATCHED trades (first 30):")
        for d, diffs in mismatches[:30]:
            t5 = v5_by_date[d]
            t6 = v6_by_date[d]
            print(f"    {d} | {'; '.join(diffs)}")

    # Aggregate PnL comparison
    v5_total_pnl = sum(t.pnl for t in v5_trades)
    v6_total_pnl = sum(t["pnl"] for t in v6_trades)
    v5_wins = sum(1 for t in v5_trades if t.pnl > 0)
    v6_wins = sum(1 for t in v6_trades if t["pnl"] > 0)

    print(f"\n  {'Metric':>20s} | {'V5':>12s} | {'V6':>12s} | {'Diff':>12s}")
    print(f"  {'-'*20}-+-{'-'*12}-+-{'-'*12}-+-{'-'*12}")
    print(f"  {'Total PnL':>20s} | ${v5_total_pnl:>+11.2f} | ${v6_total_pnl:>+11.2f} | ${v6_total_pnl - v5_total_pnl:>+11.2f}")
    print(f"  {'Trades':>20s} | {len(v5_trades):>12d} | {len(v6_trades):>12d} | {len(v6_trades) - len(v5_trades):>12d}")
    v5_wr = v5_wins / len(v5_trades) * 100 if v5_trades else 0
    v6_wr = v6_wins / len(v6_trades) * 100 if v6_trades else 0
    print(f"  {'Win Rate':>20s} | {v5_wr:>11.1f}% | {v6_wr:>11.1f}% | {v6_wr - v5_wr:>+11.1f}%")

    if not mismatches and not v5_only and not v6_only:
        print(f"\n  ** PERFECT PARITY: All {len(matched)} trades match exactly! **")
    else:
        total_issues = len(mismatches) + len(v5_only) + len(v6_only)
        pct = (len(matched) - len(mismatches)) / max(len(all_dates), 1) * 100
        print(f"\n  Parity: {pct:.1f}% of dates have identical trades ({total_issues} issues)")

    print(f"{'='*90}\n")


def main():
    print("Loading 1-minute bars...")
    df = load_1m_bars(DATA_FILE)
    print(f"Loaded {len(df):,} bars ({df.index.min().date()} to {df.index.max().date()})")

    print("\n--- Running V5 backtest ---")
    v5_trades = run_v5(df)
    print(f"V5: {len(v5_trades)} trades")

    print("\n--- Running V6 backtest ---")
    v6_trades = run_v6()
    print(f"V6: {len(v6_trades)} trades")

    compare(v5_trades, v6_trades)


if __name__ == "__main__":
    main()
