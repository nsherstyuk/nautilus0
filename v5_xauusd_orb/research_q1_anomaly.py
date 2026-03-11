"""
research_q1_anomaly.py -- Investigate the Q1 (slowest velocity) anomaly.

Q1 has Sharpe 1.43 (full) and 1.40 (OOS) despite being the SLOWEST quintile.
Q2 is -1.76. Why is the slowest group better than the next-slowest?

Also: assess whether 1000-tick bars provide sufficient resolution for:
1. Measuring velocity at the breakout moment
2. Detecting the exact crossing time
3. The stop-order entry simulation

Key concerns with 1000-tick resolution:
- During slow hours (Asian), a bar spans ~10-15 minutes
- The "velocity" of a slow bar might be measuring the wrong thing
- Entry simulation assumes we see the cross on the bar, but the bar
  might aggregate 10+ minutes of price action
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v5_xauusd_orb.backtest_tick import (
    load_tick_bars, backtest_orb_tick, BacktestConfig, Trade
)

ROOT = Path(__file__).resolve().parents[1]


def trades_to_df(trades: list[Trade]) -> pd.DataFrame:
    return pd.DataFrame([{
        'date': t.date,
        'year': t.date.year,
        'direction': t.direction,
        'pnl': t.pnl,
        'range_size': t.range_size,
        'hold_minutes': t.hold_minutes,
        'entry_hour': t.entry_hour,
        'entry_min': t.entry_time.minute if hasattr(t.entry_time, 'minute') else 0,
        'gap_from_level': t.gap_from_level,
        'buy_ratio': t.buy_ratio_at_entry,
        'tick_velocity': t.tick_velocity_at_entry,
        'entry_type': t.entry_type,
        'exit_type': t.exit_type,
        'entry_price': t.entry_price,
        'exit_price': t.exit_price,
        'range_high': t.range_high,
        'range_low': t.range_low,
        'spread_cost': t.spread_cost,
        'entry_spread': t.entry_spread,
    } for t in trades])


def sharpe(pnl):
    if len(pnl) < 5:
        return 0
    s = pnl.std()
    return pnl.mean() / s * np.sqrt(252) if s > 0 else 0


def main():
    df = load_tick_bars()
    print(f"Loaded {len(df):,} tick bars")

    cfg = BacktestConfig(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest_orb_tick(df, cfg)
    tdf = trades_to_df(all_trades)

    # Add quintile labels
    tdf['vel_quintile'] = pd.qcut(tdf['tick_velocity'], 5,
                                    labels=['Q1_slow', 'Q2', 'Q3', 'Q4', 'Q5_fast'])

    q1 = tdf[tdf['vel_quintile'] == 'Q1_slow']
    q2 = tdf[tdf['vel_quintile'] == 'Q2']

    # ═══════════════════════════════════════════════════════════════════════
    # 1. PROFILE: What do Q1 trades look like vs Q2?
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  1. Q1 vs Q2 PROFILE: What's different about them?")
    print("=" * 100)

    for label, subset in [("Q1 (slowest)", q1), ("Q2", q2)]:
        print(f"\n  {label} (N={len(subset)}):")
        print(f"    Velocity:      {subset['tick_velocity'].mean():.2f} (range {subset['tick_velocity'].min():.2f}-{subset['tick_velocity'].max():.2f})")
        print(f"    Sharpe:        {sharpe(subset['pnl']):.2f}")
        print(f"    Mean PnL:      ${subset['pnl'].mean():+.2f}")
        print(f"    Win rate:      {(subset['pnl']>0).mean()*100:.1f}%")
        print(f"    Entry hour dist:")
        for h in sorted(subset['entry_hour'].unique()):
            n = (subset['entry_hour'] == h).sum()
            pct = n / len(subset) * 100
            h_pnl = subset[subset['entry_hour'] == h]['pnl']
            print(f"      {h:02d}:xx  N={n:>4} ({pct:>5.1f}%)  Sharpe {sharpe(h_pnl):>6.2f}  Mean ${h_pnl.mean():>+6.2f}")
        print(f"    Direction dist:")
        for d in ['LONG', 'SHORT']:
            n = (subset['direction'] == d).sum()
            d_pnl = subset[subset['direction'] == d]['pnl']
            print(f"      {d}:  N={n:>4}  Sharpe {sharpe(d_pnl):>6.2f}")
        print(f"    Exit dist:")
        for ex in subset['exit_type'].value_counts().index:
            n = (subset['exit_type'] == ex).sum()
            ex_pnl = subset[subset['exit_type'] == ex]['pnl']
            print(f"      {ex:>6}: N={n:>4}  Mean ${ex_pnl.mean():>+6.2f}")
        print(f"    Avg range size: ${subset['range_size'].mean():.2f}")
        print(f"    Avg hold (min): {subset['hold_minutes'].mean():.0f}")
        print(f"    Avg gap:        ${subset['gap_from_level'].mean():.2f}")
        print(f"    Avg spread:     ${subset['entry_spread'].mean():.3f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 2. DATA RESOLUTION CHECK: How long is a Q1 tick bar in minutes?
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  2. DATA RESOLUTION: How long are tick bars in minutes?")
    print("     (1000-tick bar with low velocity = long time span)")
    print("=" * 100)

    # Calculate time span of each tick bar
    df_copy = df.copy()
    df_copy['next_ts'] = df_copy.index.to_series().shift(-1)
    df_copy['bar_duration_min'] = (df_copy['next_ts'] - df_copy.index).dt.total_seconds() / 60

    # By velocity quintile of ALL bars (not just entry bars)
    df_copy['vel_quintile'] = pd.qcut(df_copy['tick_velocity'], 5,
                                       labels=['Q1_slow', 'Q2', 'Q3', 'Q4', 'Q5_fast'])

    print(f"\n  Tick bar duration (minutes) by velocity quintile:")
    for q in ['Q1_slow', 'Q2', 'Q3', 'Q4', 'Q5_fast']:
        subset = df_copy[df_copy['vel_quintile'] == q]['bar_duration_min'].dropna()
        print(f"    {q:>10}: mean={subset.mean():>6.1f}min  median={subset.median():>6.1f}min  "
              f"P90={subset.quantile(0.90):>6.1f}min  max={subset.max():>6.0f}min")

    # For our key hours (8-9 UTC), what's the resolution?
    print(f"\n  During 08:xx-09:xx UTC (our primary entry window):")
    for q in ['Q1_slow', 'Q2', 'Q3', 'Q4', 'Q5_fast']:
        window = df_copy[(df_copy['hour'] >= 8) & (df_copy['hour'] < 9) & (df_copy['vel_quintile'] == q)]
        dur = window['bar_duration_min'].dropna()
        if len(dur) > 10:
            print(f"    {q:>10}: mean={dur.mean():>5.1f}min  median={dur.median():>5.1f}min  "
                  f"P90={dur.quantile(0.90):>5.1f}min  (N={len(dur):,} bars)")

    # ═══════════════════════════════════════════════════════════════════════
    # 3. THE REAL PROBLEM: Q1 entry bars span how many minutes?
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  3. Q1 ENTRY BAR RESOLUTION: How precise is the entry?")
    print("     (If a Q1 entry bar spans 15 minutes, we don't know when the cross happened)")
    print("=" * 100)

    # For each trade, find the entry bar and calculate its duration
    for label, subset in [("Q1 (slowest)", q1), ("Q2", q2), ("Q4", tdf[tdf['vel_quintile'] == 'Q4']), ("Q5 (fastest)", tdf[tdf['vel_quintile'] == 'Q5_fast'])]:
        # Use velocity to estimate bar duration: 1000 ticks / velocity = seconds
        durations = 1000 / subset['tick_velocity']  # seconds per bar
        dur_min = durations / 60
        print(f"\n  {label} entry bar duration (estimated 1000/velocity):")
        print(f"    Mean: {dur_min.mean():>6.1f} min")
        print(f"    Median: {dur_min.median():>6.1f} min")
        print(f"    P90: {dur_min.quantile(0.90):>6.1f} min")
        print(f"    Max: {dur_min.max():>6.0f} min")

    # ═══════════════════════════════════════════════════════════════════════
    # 4. Q1 IS LIKELY WEEKEND/HOLIDAY/DEAD MARKET — CHECK
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  4. Q1 CONTEXT: Is it happening on specific days/months?")
    print("=" * 100)

    print(f"\n  Q1 entry weekday distribution:")
    for wd in range(5):
        wd_name = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'][wd]
        mask = pd.to_datetime(q1['date']).dt.weekday == wd
        n = mask.sum()
        if n > 0:
            p = q1[mask.values]['pnl']
            print(f"    {wd_name}: N={n:>4}  Sharpe {sharpe(p):>6.2f}  Mean ${p.mean():>+6.2f}")

    print(f"\n  Q2 entry weekday distribution:")
    for wd in range(5):
        wd_name = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'][wd]
        mask = pd.to_datetime(q2['date']).dt.weekday == wd
        n = mask.sum()
        if n > 0:
            p = q2[mask.values]['pnl']
            print(f"    {wd_name}: N={n:>4}  Sharpe {sharpe(p):>6.2f}  Mean ${p.mean():>+6.2f}")

    # Monthly patterns
    print(f"\n  Q1 by month:")
    q1_months = pd.to_datetime(q1['date']).dt.month
    for m in sorted(q1_months.unique()):
        mask = q1_months == m
        n = mask.sum()
        if n > 3:
            p = q1[mask.values]['pnl']
            print(f"    Month {m:>2}: N={n:>3}  Sharpe {sharpe(p):>6.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 5. RESOLUTION IMPACT: Compare 1000-tick vs 5-min bar results
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  5. RESOLUTION IMPACT: What are we missing with 1000-tick bars?")
    print("=" * 100)

    # The core issue: when a slow bar crosses the range level,
    # the OHLC doesn't tell us WHEN within that 10-15 minute window it crossed.
    # This affects:
    # 1. Entry price accuracy (same as 5-min bar problem!)
    # 2. Whether SL/TP was hit within the bar
    # 3. The velocity measurement itself

    # How many Q1 entry bars have BOTH range_high AND range_low within the bar?
    # (i.e., the bar is so wide it touches both levels)
    q1_ambiguous = 0
    q5 = tdf[tdf['vel_quintile'] == 'Q5_fast']
    q5_ambiguous = 0

    for _, row in q1.iterrows():
        # Estimate: slow bar has wide range, might touch both levels
        # We can check if the gap_from_level is large
        pass

    # Better check: what % of Q1 entries are gap-opens?
    for label, subset in [("Q1", q1), ("Q2", q2), ("Q4", tdf[tdf['vel_quintile'] == 'Q4']), ("Q5", q5)]:
        gap_pct = (subset['gap_from_level'] > 0).mean() * 100
        avg_gap = subset[subset['gap_from_level'] > 0]['gap_from_level'].mean() if (subset['gap_from_level'] > 0).any() else 0
        print(f"    {label}: Gap-open% = {gap_pct:.1f}%  Avg gap (when >0) = ${avg_gap:.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 6. WHAT IF Q1 IS JUST SMALL RANGE + LARGE TP?
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  6. Q1 HYPOTHESIS: Is it correlated with small range sizes?")
    print("     (Small range = tight SL = less risk, but also larger RR moves)")
    print("=" * 100)

    for label, subset in [("Q1", q1), ("Q2", q2), ("Q3", tdf[tdf['vel_quintile'] == 'Q3']), ("Q4", tdf[tdf['vel_quintile'] == 'Q4']), ("Q5", q5)]:
        print(f"    {label}: Avg range ${subset['range_size'].mean():>6.2f}  "
              f"Median range ${subset['range_size'].median():>6.2f}  "
              f"TP hit% {(subset['exit_type']=='TP').mean()*100:>5.1f}%  "
              f"SL hit% {(subset['exit_type']=='SL').mean()*100:>5.1f}%")

    # ═══════════════════════════════════════════════════════════════════════
    # 7. THE BIG QUESTION: With 1000-tick bars, is our "velocity" measurement
    #    actually measuring velocity at the MOMENT of breakout?
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  7. VELOCITY MEASUREMENT ACCURACY")
    print("     Is 'tick_velocity' of the entry bar measuring the right thing?")
    print("=" * 100)

    # The entry bar's tick_velocity tells us how fast the market was DURING
    # that specific 1000-tick window. But:
    # - For Q1: the bar spans ~20 minutes. The breakout might happen at any
    #   point within that window. The velocity is an average over 20 min.
    # - For Q5: the bar spans ~1 minute. The velocity is a precise snapshot.

    # This means Q1's "velocity" is a poor measure of conditions at the
    # actual moment of breakout. It's averaging fast and slow periods together.

    # What if we use the PREVIOUS bar's velocity instead? (conditions leading up to entry)
    print("\n  Using PREVIOUS bar's velocity (conditions leading to breakout):")
    print("  (Requires re-running backtest with prev_bar velocity capture)")
    print("  — Skipping for now, but this is a key follow-up.")

    # ═══════════════════════════════════════════════════════════════════════
    # 8. DECILE ANALYSIS: Finer granularity than quintiles
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  8. VELOCITY DECILE ANALYSIS (10 buckets instead of 5)")
    print("=" * 100)

    tdf['vel_decile'] = pd.qcut(tdf['tick_velocity'], 10,
                                  labels=[f'D{i+1}' for i in range(10)])

    print(f"\n  {'Decile':>6} | {'N':>5} | {'VelRange':>18} | {'~BarMin':>7} | {'Sharpe':>7} | "
          f"{'PF':>5} | {'WR':>5} | {'Mean':>7} | {'Total':>10}")
    print(f"  {'-'*6}-+-{'-'*5}-+-{'-'*18}-+-{'-'*7}-+-{'-'*7}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*10}")

    for d in [f'D{i+1}' for i in range(10)]:
        subset = tdf[tdf['vel_decile'] == d]
        vmin = subset['tick_velocity'].min()
        vmax = subset['tick_velocity'].max()
        bar_min = (1000 / subset['tick_velocity']).median() / 60
        p = subset['pnl']
        gp = p[p > 0].sum()
        gl = abs(p[p < 0].sum())
        pf_val = gp / gl if gl > 0 else float('inf')
        print(f"  {d:>6} | {len(p):>5} | {vmin:>7.2f} - {vmax:>7.2f} | {bar_min:>5.1f}m | "
              f"{sharpe(p):>7.2f} | {pf_val:>5.2f} | {(p>0).mean()*100:>4.1f}% | "
              f"${p.mean():>+6.2f} | ${p.sum():>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 9. OOS DECILE
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n  OOS (2021+) deciles:")
    oos = tdf[tdf['year'] >= 2021].copy()
    oos['vel_decile'] = pd.qcut(oos['tick_velocity'], 10,
                                  labels=[f'D{i+1}' for i in range(10)],
                                  duplicates='drop')
    print(f"\n  {'Decile':>6} | {'N':>5} | {'Sharpe':>7} | {'PF':>5} | {'WR':>5} | {'Mean':>7} | {'Total':>10}")
    print(f"  {'-'*6}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*10}")

    for d in sorted(oos['vel_decile'].unique()):
        subset = oos[oos['vel_decile'] == d]
        p = subset['pnl']
        gp = p[p > 0].sum()
        gl = abs(p[p < 0].sum())
        pf_val = gp / gl if gl > 0 else float('inf')
        print(f"  {d:>6} | {len(p):>5} | {sharpe(p):>7.2f} | {pf_val:>5.2f} | "
              f"{(p>0).mean()*100:>4.1f}% | ${p.mean():>+6.2f} | ${p.sum():>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 10. RESOLUTION VERDICT
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  10. RESOLUTION VERDICT")
    print("=" * 100)

    # Count how many trades have entry bar duration > 5min, > 10min, > 15min
    tdf['est_bar_duration_min'] = 1000 / tdf['tick_velocity'] / 60

    print(f"\n  Entry bar duration distribution:")
    for thresh in [1, 2, 5, 10, 15, 20, 30]:
        n = (tdf['est_bar_duration_min'] > thresh).sum()
        pct = n / len(tdf) * 100
        print(f"    Bar > {thresh:>2}min: {n:>5} trades ({pct:>5.1f}%)")

    # For trades with bars > 10 min, what's their Sharpe?
    long_bars = tdf[tdf['est_bar_duration_min'] > 10]
    short_bars = tdf[tdf['est_bar_duration_min'] <= 10]
    print(f"\n  Entry bar > 10min: N={len(long_bars)}, Sharpe {sharpe(long_bars['pnl']):.2f}")
    print(f"  Entry bar <=10min: N={len(short_bars)}, Sharpe {sharpe(short_bars['pnl']):.2f}")

    long_bars2 = tdf[tdf['est_bar_duration_min'] > 5]
    short_bars2 = tdf[tdf['est_bar_duration_min'] <= 5]
    print(f"\n  Entry bar > 5min: N={len(long_bars2)}, Sharpe {sharpe(long_bars2['pnl']):.2f}")
    print(f"  Entry bar <=5min: N={len(short_bars2)}, Sharpe {sharpe(short_bars2['pnl']):.2f}")

    print(f"\n{'='*100}")
    print("  DONE")
    print("=" * 100)


if __name__ == "__main__":
    main()
