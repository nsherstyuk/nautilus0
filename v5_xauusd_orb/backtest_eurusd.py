"""
Quick EURUSD velocity filter backtest using existing backtest_1m.py engine.
Adapts for EURUSD: different pip scale, trade times, costs.
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v5_xauusd_orb.backtest_1m import (
    load_1m_bars, backtest, Config, stats, print_stats
)

DATA_FILE = ROOT / 'data' / '1m_csv' / 'eurusd_1m_tick.csv'

# EURUSD parameters (from config.yaml)
ASIAN_START = 0
ASIAN_END = 6
TRADE_START = 7      # London open for EURUSD
TRADE_END = 16
RR_RATIO = 2.0
MIN_RANGE_PCT = 0.01
MAX_RANGE_PCT = 2.0
SKIP_WEEKDAYS = [2]  # Wednesday
VELOCITY_LOOKBACK_MIN = 3

# Costs (EURUSD)
SPREAD_PIPS = 0.5    # typical EURUSD spread
SLIPPAGE_PIPS = 0.3  # realistic slippage
COST_PER_TRADE = (SPREAD_PIPS + SLIPPAGE_PIPS) * 0.0001  # convert pips to price

def main():
    print("="*110)
    print("  EURUSD Asian Range Breakout + Velocity Filter Backtest")
    print("  Data: eurusd_1m_tick.csv (Dukascopy 2018-2026)")
    print("="*110)
    
    # Load data
    df = load_1m_bars(DATA_FILE)
    print(f"\nLoaded {len(df):,} bars from {df.index[0]} to {df.index[-1]}")
    
    # Quick velocity stats
    print(f"\nVelocity distribution:")
    print(f"  Median tick_count: {df['tick_count'].median():.0f}")
    print(f"  P25: {df['tick_count'].quantile(0.25):.0f}")
    print(f"  P50: {df['tick_count'].quantile(0.50):.0f}")
    print(f"  P75: {df['tick_count'].quantile(0.75):.0f}")
    
    morning = df[df.hour == TRADE_START]
    print(f"\n{TRADE_START:02d}:00 UTC velocity (trade start):")
    print(f"  Median: {morning['tick_count'].median():.0f}")
    
    # Run backtest: stop entry, no time exit
    print(f"\n{'='*110}")
    print("  BACKTEST: Stop entry, NO time exit, NO BE")
    print("="*110)
    
    cfg = Config(
        range_start=ASIAN_START,
        range_end=ASIAN_END,
        trade_start=TRADE_START,
        trade_end=TRADE_END,
        rr_ratio=RR_RATIO,
        min_range_pct=MIN_RANGE_PCT,
        max_range_pct=MAX_RANGE_PCT,
        skip_weekdays=SKIP_WEEKDAYS,
        time_exit_minutes=0,
        entry_method='stop',
    )
    
    all_trades = backtest(df, cfg)
    
    print(f"\nTotal trades: {len(all_trades)}")
    
    if len(all_trades) == 0:
        print("No trades generated. Check data/parameters.")
        return
    
    # Split by OOS
    oos_trades = [t for t in all_trades if t.date.year >= 2021]
    full_stats = stats(all_trades, "Full (2018-2026)")
    oos_stats = stats(oos_trades, "OOS (2021-2026)")
    
    print_stats(full_stats)
    print_stats(oos_stats)
    
    # Velocity filter analysis
    print(f"\n{'='*110}")
    print("  VELOCITY FILTER ANALYSIS")
    print("="*110)
    
    tc_med = np.median([t.entry_tick_count for t in all_trades])
    fast = [t for t in all_trades if t.entry_tick_count >= tc_med]
    slow = [t for t in all_trades if t.entry_tick_count < tc_med]
    
    fast_oos = [t for t in oos_trades if t.entry_tick_count >= tc_med]
    slow_oos = [t for t in oos_trades if t.entry_tick_count < tc_med]
    
    print(f"\nMedian tick_count threshold: {tc_med:.0f}")
    print(f"\n--- FULL PERIOD ---")
    print_stats(stats(fast, "Fast (>=median)"))
    print_stats(stats(slow, "Slow (<median)"))
    
    print(f"\n--- OUT-OF-SAMPLE (2021-2026) ---")
    print_stats(stats(fast_oos, "Fast OOS"))
    print_stats(stats(slow_oos, "Slow OOS"))
    
    # Annual breakdown
    print(f"\n{'='*110}")
    print("  ANNUAL BREAKDOWN")
    print("="*110)
    
    by_year = {}
    for t in all_trades:
        yr = t.date.year
        by_year.setdefault(yr, []).append(t)
    
    for yr in sorted(by_year):
        s = stats(by_year[yr], "")
        flag = " <<< LOSS" if s['total'] < 0 else ""
        print(f"  {yr}: N={s['n']:>4} | P&L ${s['total']:>+9.4f} | "
              f"Sh {s['sharpe']:>6.2f} | DD ${s['max_dd']:>+9.4f} | MCL {s['mcl']}{flag}")
    
    print(f"\n{'='*110}")
    print("  DONE")
    print("="*110)


if __name__ == "__main__":
    main()
