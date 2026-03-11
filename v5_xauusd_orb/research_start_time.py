"""
research_start_time.py -- With velocity filter, is 08:00 UTC still the best trade start time?
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from v5_xauusd_orb.backtest_1m import load_1m_bars, backtest, Config, stats, Trade


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

    print(f"{'='*110}")
    print(f"  TRADE START TIME SWEEP (stop entry, no time exit, skip Wed)")
    print(f"{'='*110}")

    print(f"\n  --- UNFILTERED ---")
    print(f"  {'Start':>7} | {'N':>5} | {'Sh':>6} | {'PF':>5} | {'WR':>5} | {'Total':>10} | "
          f"{'OOS N':>5} | {'OOS Sh':>7} | {'OOS $':>10}")

    for start_h in [6, 7, 8, 9, 10]:
        cfg = Config(entry_method='stop', time_exit_minutes=0, trade_start=start_h)
        trades = backtest(df, cfg)
        s = stats(trades)
        oos = [t for t in trades if t.date >= oos_start]
        so = stats(oos)
        print(f"  {start_h:02d}:00 | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['pf']:>5.2f} | "
              f"{s['wr']:>4.1f}% | ${s['total']:>+9.2f} | "
              f"{so['n']:>5} | {so['sharpe']:>7.2f} | ${so['total']:>+9.2f}")

    print(f"\n  --- WITH VELOCITY FILTER (3min avg >= median) ---")
    print(f"  {'Start':>7} | {'N':>5} | {'Sh':>6} | {'PF':>5} | {'WR':>5} | {'Total':>10} | "
          f"{'OOS N':>5} | {'OOS Sh':>7} | {'OOS $':>10}")

    for start_h in [6, 7, 8, 9, 10]:
        cfg = Config(entry_method='stop', time_exit_minutes=0, trade_start=start_h)
        trades = backtest(df, cfg)
        enriched = enrich_with_3min_tc(trades, df)
        med = np.median([e[1] for e in enriched])
        fast = [e[0] for e in enriched if e[1] >= med]
        sf = stats(fast)
        oos_fast = [t for t in fast if t.date >= oos_start]
        sof = stats(oos_fast)
        print(f"  {start_h:02d}:00 | {sf['n']:>5} | {sf['sharpe']:>6.2f} | {sf['pf']:>5.2f} | "
              f"{sf['wr']:>4.1f}% | ${sf['total']:>+9.2f} | "
              f"{sof['n']:>5} | {sof['sharpe']:>7.2f} | ${sof['total']:>+9.2f}")

    # Also check: what hour do most entries actually happen?
    print(f"\n  --- ENTRY HOUR DISTRIBUTION (start=08:00, filtered) ---")
    cfg = Config(entry_method='stop', time_exit_minutes=0, trade_start=8)
    trades = backtest(df, cfg)
    enriched = enrich_with_3min_tc(trades, df)
    med = np.median([e[1] for e in enriched])
    fast = [e[0] for e in enriched if e[1] >= med]

    hour_counts = {}
    hour_pnl = {}
    for t in fast:
        h = t.entry_time.hour
        hour_counts[h] = hour_counts.get(h, 0) + 1
        hour_pnl.setdefault(h, []).append(t.pnl)

    print(f"  {'Hour':>6} | {'N':>5} | {'%':>5} | {'Sh':>6} | {'Avg PnL':>8}")
    for h in sorted(hour_counts):
        n = hour_counts[h]
        pnls = np.array(hour_pnl[h])
        sh = pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0
        print(f"  {h:02d}:xx | {n:>5} | {n/len(fast)*100:>4.1f}% | {sh:>6.2f} | ${pnls.mean():>+7.2f}")

    print(f"\n{'='*110}")
    print("  DONE")
    print(f"{'='*110}")


if __name__ == "__main__":
    main()
