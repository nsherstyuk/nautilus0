"""
Breakeven Rule Sensitivity Analysis for v5 XAUUSD ORB Strategy

Tests the 1h BE rule at different time intervals to verify it's not overfitted
to the exact 60-minute threshold.

Usage:
  python -m v5_xauusd_orb.analyze_be_sensitivity
  python -m v5_xauusd_orb.analyze_be_sensitivity --start 2019-01-01 --end 2026-01-01
"""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from v5_xauusd_orb.config import load_config
from v5_xauusd_orb.backtest import build_5min_bars
from v5_xauusd_orb.backtest_exits import ExitStrategy, run_strategy, stats


def main():
    parser = argparse.ArgumentParser(
        description="BE Rule Sensitivity Analysis for v5 XAUUSD ORB")
    parser.add_argument("--start", default="2019-01-01",
                        help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None,
                        help="End date YYYY-MM-DD (default: latest)")
    parser.add_argument("--rr", type=float, default=None,
                        help="Override RR ratio")
    parser.add_argument("--spread", type=float, default=0.10,
                        help="One-way spread per oz in $")
    parser.add_argument("--slippage", type=float, default=0.15,
                        help="Slippage per stop/market order per oz in $")
    parser.add_argument("--save", default=None,
                        help="Save results to CSV")
    args = parser.parse_args()

    cfg = load_config()
    rr = args.rr if args.rr is not None else cfg.strategy.rr_ratio
    skip = cfg.strategy.skip_weekdays
    qty = cfg.position.qty
    
    # Adjust spread to account for slippage
    total_cost_per_side = args.spread + args.slippage

    print("Loading data...")
    ohlcv = build_5min_bars(cfg.paths.tick_bar_file)
    start = pd.Timestamp(args.start, tz='UTC')
    end = pd.Timestamp(args.end, tz='UTC') if args.end else ohlcv.index.max()
    ohlcv = ohlcv.loc[start:end]
    print(f"Bars: {len(ohlcv):,}  ({ohlcv.index.min().date()} -> {ohlcv.index.max().date()})")
    print(f"RR={rr}  skip_weekdays={skip}  cost={total_cost_per_side}/side\n")

    # Test BE rule at different time thresholds (in 5-min bars)
    # 30min = 6 bars, 45min = 9 bars, 60min = 12 bars, 75min = 15 bars, 90min = 18 bars, 120min = 24 bars
    be_times = [
        ("Baseline (no BE)", None),
        ("30 min BE", 6),
        ("45 min BE", 9),
        ("60 min BE (current)", 12),
        ("75 min BE", 15),
        ("90 min BE", 18),
        ("120 min BE", 24),
    ]

    results = []
    
    for label, be_bars in be_times:
        print(f"Testing: {label} ...", end=' ', flush=True)
        
        strat = ExitStrategy(
            name=f"be_{be_bars}bars" if be_bars else "baseline",
            label=label,
            time_be_bars=be_bars
        )
        
        df = run_strategy(ohlcv, strat, cfg, rr, skip, qty, total_cost_per_side)
        s = stats(df)
        s['strategy'] = label
        s['be_minutes'] = be_bars * 5 if be_bars else 0
        results.append(s)
        
        print(f"  -> P&L={s['total_pnl']:+.2f}  Sharpe={s['sharpe']}  PF={s['pf']}  MaxDD={s['max_dd']}")

    results_df = pd.DataFrame(results).set_index('strategy')

    print("\n" + "=" * 120)
    print(f"  BREAKEVEN RULE SENSITIVITY ANALYSIS  (RR={rr}, cost={total_cost_per_side}/side, {args.start} -> {args.end or 'latest'})")
    print("=" * 120)
    header = f"  {'Strategy':<25}  {'BE(min)':>8}  {'Trades':>6}  {'TP%':>5}  {'SL%':>5}  {'BE%':>5}  {'EOD%':>5}  {'P&L':>10}  {'Avg':>7}  {'MaxDD':>10}  {'Sharpe':>7}  {'PF':>5}"
    print(header)
    print("-" * 120)
    
    for name, row in results_df.iterrows():
        marker = " ◄ BEST" if row['total_pnl'] == results_df['total_pnl'].max() else ""
        print(f"  {name:<25}  {int(row['be_minutes']):>8}  {row['trades']:>6}  {row['TP%']:>4.1f}%  {row['SL%']:>4.1f}%  {row['BE%']:>4.1f}%  {row['EOD%']:>4.1f}%  {row['total_pnl']:>+10.2f}  {row['avg_pnl']:>+6.2f}  {row['max_dd']:>+10.2f}  {row['sharpe']:>7.2f}  {row['pf']:>5.2f}{marker}")
    print("=" * 120)

    # Check for sensitivity cliff
    print("\n  ROBUSTNESS CHECK:")
    baseline_pnl = results_df.loc["Baseline (no BE)", "total_pnl"]
    current_pnl = results_df.loc["60 min BE (current)", "total_pnl"]
    neighbors = [
        ("45 min BE", results_df.loc["45 min BE", "total_pnl"]),
        ("75 min BE", results_df.loc["75 min BE", "total_pnl"]),
    ]
    
    print(f"  Baseline (no BE):      ${baseline_pnl:+,.2f}")
    print(f"  Current (60min BE):    ${current_pnl:+,.2f}  (improvement: ${current_pnl - baseline_pnl:+,.2f})")
    
    avg_neighbor_pnl = np.mean([p for _, p in neighbors])
    pnl_drop_vs_neighbors = ((current_pnl - avg_neighbor_pnl) / current_pnl * 100) if current_pnl != 0 else 0
    
    print(f"  Avg of neighbors:      ${avg_neighbor_pnl:+,.2f}")
    print(f"  Current vs neighbors:  {pnl_drop_vs_neighbors:+.1f}% deviation")
    
    if abs(pnl_drop_vs_neighbors) > 20:
        print("\n  WARNING: >20% deviation from neighbors suggests overfitting to 60min threshold!")
    else:
        print("\n  OK: 60min BE rule is robust (neighbors perform similarly)")

    # Per-year breakdown for top 3
    print(f"\n  Annual P&L for top 3 BE strategies:")
    top3 = results_df.nlargest(3, 'total_pnl').index.tolist()
    
    print(f"  {'Year':<6}", end='')
    yearly_data = {}
    for strat_label in top3:
        be_bars_val = int(results_df.loc[strat_label, 'be_minutes'] / 5) if results_df.loc[strat_label, 'be_minutes'] > 0 else None
        strat = ExitStrategy(
            name=f"be_{be_bars_val}bars" if be_bars_val else "baseline",
            label=strat_label,
            time_be_bars=be_bars_val
        )
        df = run_strategy(ohlcv, strat, cfg, rr, skip, qty, total_cost_per_side)
        df['year'] = pd.to_datetime(df['date']).dt.year
        yearly_data[strat_label] = df
        print(f"  {strat_label[:20]:<22}", end='')
    print()
    print("  " + "-" * 80)
    
    all_years = sorted(set(
        y for df in yearly_data.values() for y in df['year'].unique()))
    for yr in all_years:
        print(f"  {yr:<6}", end='')
        for sn in top3:
            df = yearly_data[sn]
            yr_pnl = df[df['year'] == yr]['pnl'].sum()
            print(f"  {yr_pnl:>+10.2f}          ", end='')
        print()

    if args.save:
        results_df.to_csv(args.save)
        print(f"\nSaved to {args.save}")


if __name__ == "__main__":
    main()
