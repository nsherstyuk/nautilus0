"""
research_wednesday.py -- Does skipping Wednesdays still matter with the velocity filter?
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from v5_xauusd_orb.backtest_1m import load_1m_bars, backtest, Config, stats, print_stats, Trade


def enrich_with_3min_tc(trades, df):
    enriched = []
    for t in trades:
        start_ts = t.entry_time - pd.Timedelta(minutes=3)
        mask = (df.index > start_ts) & (df.index <= t.entry_time)
        window_bars = df.loc[mask]
        avg_tc = window_bars['tick_count'].mean() if len(window_bars) > 0 else t.entry_tick_count
        enriched.append((t, avg_tc))
    return enriched


def main():
    df = load_1m_bars()
    oos_start = dt.date(2021, 1, 1)

    # ── Run with and without Wednesday skip ──
    cfg_skip = Config(entry_method='stop', time_exit_minutes=0, skip_weekdays=[2])
    cfg_noskip = Config(entry_method='stop', time_exit_minutes=0, skip_weekdays=[])

    trades_skip = backtest(df, cfg_skip)
    trades_noskip = backtest(df, cfg_noskip)

    # Extract Wednesday-only trades
    wed_trades = [t for t in trades_noskip if pd.Timestamp(t.date).weekday() == 2]

    print(f"{'='*100}")
    print(f"  WEDNESDAY ANALYSIS")
    print(f"{'='*100}")

    print(f"\n  --- UNFILTERED (no velocity filter) ---")
    print(f"  {'Config':>25} | {'N':>5} | {'Sharpe':>7} | {'PF':>5} | {'WR':>5} | {'Total':>10} | {'OOS Sh':>7}")

    for label, trades in [("Skip Wed", trades_skip),
                          ("Include Wed", trades_noskip),
                          ("Wed ONLY", wed_trades)]:
        s = stats(trades, label)
        oos = [t for t in trades if t.date >= oos_start]
        so = stats(oos)
        print(f"  {label:>25} | {s['n']:>5} | {s['sharpe']:>7.2f} | {s['pf']:>5.2f} | "
              f"{s['wr']:>4.1f}% | ${s['total']:>+9.2f} | {so['sharpe']:>7.2f}")

    # ── Now with velocity filter ──
    print(f"\n  --- WITH VELOCITY FILTER (3min avg >= median) ---")

    for label, trades in [("Skip Wed", trades_skip),
                          ("Include Wed", trades_noskip),
                          ("Wed ONLY", wed_trades)]:
        enriched = enrich_with_3min_tc(trades, df)
        med = np.median([e[1] for e in enriched]) if enriched else 0
        fast = [e[0] for e in enriched if e[1] >= med]
        sf = stats(fast)
        oos_fast = [t for t in fast if t.date >= oos_start]
        sof = stats(oos_fast)
        print(f"  {label:>25} | {sf['n']:>5} | {sf['sharpe']:>7.2f} | {sf['pf']:>5.2f} | "
              f"{sf['wr']:>4.1f}% | ${sf['total']:>+9.2f} | {sof['sharpe']:>7.2f}")

    # ── Wednesday by year ──
    print(f"\n  --- WEDNESDAY P&L BY YEAR (unfiltered) ---")
    by_year = {}
    for t in wed_trades:
        by_year.setdefault(t.date.year, []).append(t)

    for yr in sorted(by_year):
        s = stats(by_year[yr])
        print(f"    {yr}: N={s['n']:>3} | P&L ${s['total']:>+8.2f} | Sh {s['sharpe']:>6.2f} | WR {s['wr']:.1f}%")

    # ── Wednesday with velocity filter by year ──
    print(f"\n  --- WEDNESDAY P&L BY YEAR (velocity filtered) ---")
    wed_enriched = enrich_with_3min_tc(wed_trades, df)
    wed_med = np.median([e[1] for e in wed_enriched]) if wed_enriched else 0
    wed_fast = [e[0] for e in wed_enriched if e[1] >= wed_med]

    by_year_f = {}
    for t in wed_fast:
        by_year_f.setdefault(t.date.year, []).append(t)

    for yr in sorted(by_year_f):
        s = stats(by_year_f[yr])
        print(f"    {yr}: N={s['n']:>3} | P&L ${s['total']:>+8.2f} | Sh {s['sharpe']:>6.2f} | WR {s['wr']:.1f}%")

    # ── Weekday comparison ──
    print(f"\n  --- ALL WEEKDAYS (unfiltered) ---")
    names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    for wd in range(5):
        wd_trades = [t for t in trades_noskip if pd.Timestamp(t.date).weekday() == wd]
        s = stats(wd_trades)
        oos_wd = [t for t in wd_trades if t.date >= oos_start]
        so = stats(oos_wd)
        print(f"    {names[wd]:>3}: N={s['n']:>4} | Sh {s['sharpe']:>6.2f} | PF {s['pf']:>5.2f} | "
              f"WR {s['wr']:>4.1f}% | ${s['total']:>+9.2f} | OOS Sh {so['sharpe']:>6.2f}")

    print(f"\n  --- ALL WEEKDAYS (velocity filtered) ---")
    all_enriched = enrich_with_3min_tc(trades_noskip, df)
    all_med = np.median([e[1] for e in all_enriched])
    all_fast = [(e[0], e[1]) for e in all_enriched if e[1] >= all_med]

    for wd in range(5):
        wd_trades = [e[0] for e in all_fast if pd.Timestamp(e[0].date).weekday() == wd]
        s = stats(wd_trades)
        oos_wd = [t for t in wd_trades if t.date >= oos_start]
        so = stats(oos_wd)
        print(f"    {names[wd]:>3}: N={s['n']:>4} | Sh {s['sharpe']:>6.2f} | PF {s['pf']:>5.2f} | "
              f"WR {s['wr']:>4.1f}% | ${s['total']:>+9.2f} | OOS Sh {so['sharpe']:>6.2f}")

    print(f"\n{'='*100}")
    print("  DONE")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()
