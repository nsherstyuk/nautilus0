"""
research_tweaks.py -- Two investigations:

1. VELOCITY FILTER TWEAKS:
   - Measure velocity before entry (1,2,3,5 min before entry bar)
   - At entry bar only
   - After entry (1,2,3 min after)
   - Various combos
   - Different percentile thresholds for each

2. ENTRY OFFSET FROM 08:00:
   - Instead of sharp 08:00 start, try 07:55, 07:57, 07:58, 07:59
   - And 08:01, 08:02, 08:03, 08:05
   - Uses fractional trade_start via custom backtest
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from dataclasses import dataclass
import numpy as np
import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from v5_xauusd_orb.backtest_1m import load_1m_bars, backtest, Config, stats, Trade


# ── Helpers ───────────────────────────────────────────────────────────────

def get_velocity(trades, df, before_min=0, after_min=0, include_entry=True):
    """Compute avg tick_count over a window around entry for each trade."""
    results = []
    for t in trades:
        ts = t.entry_time
        start = ts - pd.Timedelta(minutes=before_min)
        end = ts + pd.Timedelta(minutes=after_min)

        if include_entry:
            mask = (df.index >= start) & (df.index <= end)
        elif before_min > 0:
            mask = (df.index >= start) & (df.index < ts)
        elif after_min > 0:
            mask = (df.index > ts) & (df.index <= end)
        else:
            mask = (df.index == ts)

        bars = df.loc[mask]
        tc = bars['tick_count'].mean() if len(bars) > 0 else t.entry_tick_count
        results.append((t, tc))
    return results


def filter_stats(enriched, oos_start, pct=50):
    """Split by percentile, return fast/slow stats."""
    tcs = np.array([e[1] for e in enriched])
    thresh = np.percentile(tcs, pct)
    fast = [e[0] for e in enriched if e[1] >= thresh]
    slow = [e[0] for e in enriched if e[1] < thresh]
    sf = stats(fast)
    ss = stats(slow)
    oos_fast = [t for t in fast if t.date >= oos_start]
    sof = stats(oos_fast) if oos_fast else {'sharpe': 0, 'n': 0, 'total': 0}
    return sf, ss, sof, len(fast), len(oos_fast), thresh


def backtest_with_offset(df, offset_minutes):
    """
    Run backtest but with trade_start shifted by offset_minutes.
    Positive offset = later (e.g., +2 = 08:02)
    Negative offset = earlier (e.g., -3 = 07:57)
    
    We do this by filtering the trade window manually.
    """
    # Use trade_start=7 to include 07:xx bars, then filter precisely
    if offset_minutes < 0:
        start_hour = 7
    else:
        start_hour = 8

    cfg = Config(entry_method='stop', time_exit_minutes=0, trade_start=start_hour)
    all_trades = backtest(df, cfg)

    # Filter: only keep trades where entry_time >= 08:00 + offset
    cutoff_minutes = 8 * 60 + offset_minutes  # minutes from midnight
    filtered = []
    for t in all_trades:
        entry_min = t.entry_time.hour * 60 + t.entry_time.minute
        if entry_min >= cutoff_minutes:
            filtered.append(t)

    return filtered


def main():
    df = load_1m_bars()
    oos_start = dt.date(2021, 1, 1)

    cfg = Config(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest(df, cfg)
    print(f"Base trades: {len(all_trades)}")

    # ═══════════════════════════════════════════════════════════════════
    # 1. VELOCITY MEASUREMENT TIMING
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  1. VELOCITY MEASUREMENT TIMING")
    print("     Testing: where to measure tick count relative to entry bar")
    print("=" * 110)

    configs = [
        # (label, before_min, after_min, include_entry)
        ("Entry bar only",           0, 0, True),
        ("1 min before only",        1, 0, False),
        ("2 min before only",        2, 0, False),
        ("3 min before only",        3, 0, False),
        ("5 min before only",        5, 0, False),
        ("Entry + 1 before",         1, 0, True),
        ("Entry + 2 before",         2, 0, True),
        ("Entry + 3 before",         3, 0, True),
        ("Entry + 5 before",         5, 0, True),
        ("Entry + 10 before",       10, 0, True),
        ("Entry + 1 after",          0, 1, True),
        ("Entry + 2 after",          0, 2, True),
        ("Entry + 3 after",          0, 3, True),
        ("1 before + entry + 1 after", 1, 1, True),
        ("2 before + entry + 2 after", 2, 2, True),
    ]

    print(f"\n  {'Config':>30} | {'Thresh':>6} | {'N_fast':>6} | {'Sh_f':>6} | {'PF_f':>5} | "
          f"{'Sh_slow':>7} | {'OOS_N':>5} | {'OOS_Sh':>7} | {'Separation':>10}")
    print(f"  {'-'*30}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*5}-+-"
          f"{'-'*7}-+-{'-'*5}-+-{'-'*7}-+-{'-'*10}")

    for label, bef, aft, inc in configs:
        enriched = get_velocity(all_trades, df, bef, aft, inc)
        sf, ss, sof, nf, nof, thresh = filter_stats(enriched, oos_start, pct=50)
        sep = sof['sharpe'] - ss['sharpe'] if ss['n'] > 0 else 0
        print(f"  {label:>30} | {thresh:>6.0f} | {nf:>6} | {sf['sharpe']:>6.2f} | "
              f"{sf['pf']:>5.2f} | {ss['sharpe']:>7.2f} | {nof:>5} | "
              f"{sof['sharpe']:>7.2f} | {sep:>10.2f}")

    # ═══════════════════════════════════════════════════════════════════
    # 2. BEST TIMING × PERCENTILE SWEEP
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  2. TOP 3 TIMINGS × PERCENTILE SWEEP")
    print("=" * 110)

    top_timings = [
        ("Entry + 3 before", 3, 0, True),
        ("Entry + 2 before", 2, 0, True),
        ("3 min before only", 3, 0, False),
    ]

    for label, bef, aft, inc in top_timings:
        enriched = get_velocity(all_trades, df, bef, aft, inc)
        print(f"\n  {label}:")
        print(f"    {'Pct':>5} | {'Thresh':>6} | {'N':>5} | {'Sh':>6} | {'PF':>5} | "
              f"{'OOS_N':>5} | {'OOS_Sh':>7} | {'OOS_$':>10}")
        for pct in [30, 40, 50, 60, 70]:
            sf, ss, sof, nf, nof, thresh = filter_stats(enriched, oos_start, pct=pct)
            print(f"    P{pct:>3} | {thresh:>6.0f} | {nf:>5} | {sf['sharpe']:>6.2f} | "
                  f"{sf['pf']:>5.2f} | {nof:>5} | {sof['sharpe']:>7.2f} | "
                  f"${sof['total']:>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════
    # 3. ENTRY OFFSET FROM 08:00
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  3. ENTRY OFFSET FROM 08:00")
    print("     Negative = start earlier, Positive = start later")
    print("=" * 110)

    offsets = [-5, -3, -2, -1, 0, 1, 2, 3, 5]

    print(f"\n  --- UNFILTERED ---")
    print(f"  {'Offset':>8} | {'Time':>7} | {'N':>5} | {'Sh':>6} | {'PF':>5} | "
          f"{'Total':>10} | {'OOS_N':>5} | {'OOS_Sh':>7}")

    for off in offsets:
        trades = backtest_with_offset(df, off)
        s = stats(trades)
        oos = [t for t in trades if t.date >= oos_start]
        so = stats(oos) if oos else {'sharpe': 0, 'n': 0}
        h = 8 + off // 60
        m = off % 60 if off >= 0 else 60 + (off % 60) if off % 60 != 0 else 0
        if off < 0:
            h = 7
            m = 60 + off
        time_str = f"{h:02d}:{m:02d}"
        print(f"  {off:>+5}min | {time_str:>7} | {s['n']:>5} | {s['sharpe']:>6.2f} | "
              f"{s['pf']:>5.2f} | ${s['total']:>+9.2f} | {so['n']:>5} | {so['sharpe']:>7.2f}")

    print(f"\n  --- WITH VELOCITY FILTER (entry + 3min before, P50) ---")
    print(f"  {'Offset':>8} | {'Time':>7} | {'N':>5} | {'Sh':>6} | {'PF':>5} | "
          f"{'Total':>10} | {'OOS_N':>5} | {'OOS_Sh':>7}")

    for off in offsets:
        trades = backtest_with_offset(df, off)
        if not trades:
            continue
        enriched = get_velocity(trades, df, before_min=3, after_min=0, include_entry=True)
        sf, ss, sof, nf, nof, thresh = filter_stats(enriched, oos_start, pct=50)
        h = 8 + off // 60
        m = off % 60 if off >= 0 else 60 + (off % 60) if off % 60 != 0 else 0
        if off < 0:
            h = 7
            m = 60 + off
        time_str = f"{h:02d}:{m:02d}"
        print(f"  {off:>+5}min | {time_str:>7} | {nf:>5} | {sf['sharpe']:>6.2f} | "
              f"{sf['pf']:>5.2f} | ${sf['total']:>+9.2f} | {nof:>5} | {sof['sharpe']:>7.2f}")

    print(f"\n{'='*110}")
    print("  DONE")
    print(f"{'='*110}")


if __name__ == "__main__":
    main()
