"""
research_tick_filters.py -- Deep verification of velocity and volume filters.

Questions to answer:
1. Does the velocity filter hold OOS (2021+)? Or is it IS-fitted?
2. Annual breakdown — does it work in EVERY year or just a few?
3. Is the relationship monotonic? (higher velocity = better, consistently?)
4. What about the REJECTED trades? Are they truly bad?
5. Combined filters: velocity + buy_ratio together?
6. Is velocity just proxying for time-of-day? (London open = fast market)
7. Rolling window stability: train on 3 years, test on next year
8. What does velocity actually measure in our tick data?
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v5_xauusd_orb.backtest_tick import (
    load_tick_bars, backtest_orb_tick, BacktestConfig, compute_stats, Trade
)

ROOT = Path(__file__).resolve().parents[1]


def trades_to_df(trades: list[Trade]) -> pd.DataFrame:
    """Convert list of Trade objects to DataFrame for analysis."""
    return pd.DataFrame([{
        'date': t.date,
        'year': t.date.year,
        'direction': t.direction,
        'entry_price': t.entry_price,
        'exit_price': t.exit_price,
        'entry_type': t.entry_type,
        'exit_type': t.exit_type,
        'pnl': t.pnl,
        'range_size': t.range_size,
        'hold_minutes': t.hold_minutes,
        'entry_hour': t.entry_hour,
        'gap_from_level': t.gap_from_level,
        'vol_imbalance': t.vol_imbalance_at_entry,
        'buy_ratio': t.buy_ratio_at_entry,
        'tick_velocity': t.tick_velocity_at_entry,
        'spread_cost': t.spread_cost,
    } for t in trades])


def sharpe(pnl: pd.Series) -> float:
    if len(pnl) < 5:
        return 0
    s = pnl.std()
    return pnl.mean() / s * np.sqrt(252) if s > 0 else 0


def pf(pnl: pd.Series) -> float:
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl < 0].sum())
    return gp / gl if gl > 0 else float('inf')


def wr(pnl: pd.Series) -> float:
    return (pnl > 0).mean() * 100 if len(pnl) > 0 else 0


def main():
    df = load_tick_bars()
    print(f"Loaded {len(df):,} tick bars ({df.index.min().date()} to {df.index.max().date()})")

    # Run the base backtest: stop entry, NO time exit (the winner from previous analysis)
    cfg = BacktestConfig(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest_orb_tick(df, cfg)
    tdf = trades_to_df(all_trades)
    print(f"Total trades: {len(tdf)}")
    print(f"Overall: Sharpe {sharpe(tdf['pnl']):.2f}, PF {pf(tdf['pnl']):.2f}, WR {wr(tdf['pnl']):.1f}%")

    oos_start = 2021

    # ═══════════════════════════════════════════════════════════════════════
    # 0. WHAT IS TICK VELOCITY?
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  0. WHAT IS TICK VELOCITY?")
    print("=" * 100)
    print("""
  tick_velocity in the 1000-tick bar data measures how fast the 1000 ticks
  arrived (ticks per second). High velocity = fast, active market.
  Low velocity = slow, quiet market.

  The hypothesis: breakouts in fast markets are momentum-driven and more
  likely to follow through. Breakouts in slow markets are noise.""")

    print(f"\n  Velocity statistics:")
    print(f"    Mean:   {tdf['tick_velocity'].mean():.2f}")
    print(f"    Median: {tdf['tick_velocity'].median():.2f}")
    print(f"    P25:    {tdf['tick_velocity'].quantile(0.25):.2f}")
    print(f"    P75:    {tdf['tick_velocity'].quantile(0.75):.2f}")
    print(f"    P90:    {tdf['tick_velocity'].quantile(0.90):.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 1. VELOCITY QUINTILE ANALYSIS (IS THE RELATIONSHIP MONOTONIC?)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  1. VELOCITY QUINTILES: Is the relationship monotonic?")
    print("     (Q1=slowest 20%, Q5=fastest 20%)")
    print("=" * 100)

    tdf['vel_quintile'] = pd.qcut(tdf['tick_velocity'], 5, labels=['Q1_slow', 'Q2', 'Q3', 'Q4', 'Q5_fast'])

    print(f"\n  {'Quintile':>10} | {'N':>5} | {'VelRange':>20} | {'Sharpe':>7} | {'PF':>5} | "
          f"{'WR':>5} | {'Mean':>7} | {'Total':>10}")
    print(f"  {'-'*10}-+-{'-'*5}-+-{'-'*20}-+-{'-'*7}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*10}")

    for q in ['Q1_slow', 'Q2', 'Q3', 'Q4', 'Q5_fast']:
        subset = tdf[tdf['vel_quintile'] == q]
        vmin = subset['tick_velocity'].min()
        vmax = subset['tick_velocity'].max()
        p = subset['pnl']
        print(f"  {q:>10} | {len(p):>5} | {vmin:>8.2f} - {vmax:>8.2f} | "
              f"{sharpe(p):>7.2f} | {pf(p):>5.2f} | {wr(p):>4.1f}% | "
              f"${p.mean():>+6.2f} | ${p.sum():>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 2. VELOCITY QUINTILES — OOS ONLY (2021+)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print(f"  2. VELOCITY QUINTILES — OOS ONLY ({oos_start}+)")
    print("=" * 100)

    oos = tdf[tdf['year'] >= oos_start]
    oos['vel_quintile'] = pd.qcut(oos['tick_velocity'], 5, labels=['Q1_slow', 'Q2', 'Q3', 'Q4', 'Q5_fast'])

    print(f"\n  {'Quintile':>10} | {'N':>5} | {'Sharpe':>7} | {'PF':>5} | {'WR':>5} | {'Mean':>7} | {'Total':>10}")
    print(f"  {'-'*10}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*10}")

    for q in ['Q1_slow', 'Q2', 'Q3', 'Q4', 'Q5_fast']:
        subset = oos[oos['vel_quintile'] == q]
        p = subset['pnl']
        print(f"  {q:>10} | {len(p):>5} | {sharpe(p):>7.2f} | {pf(p):>5.2f} | "
              f"{wr(p):>4.1f}% | ${p.mean():>+6.2f} | ${p.sum():>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 3. ANNUAL BREAKDOWN BY VELOCITY HALF (top 50% vs bottom 50%)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  3. ANNUAL: Top 50% velocity vs Bottom 50%")
    print("=" * 100)

    vel_median = tdf['tick_velocity'].median()
    fast = tdf[tdf['tick_velocity'] >= vel_median]
    slow = tdf[tdf['tick_velocity'] < vel_median]

    print(f"\n  Velocity median = {vel_median:.2f}")
    print(f"\n  {'Year':>6} | {'Fast N':>6} | {'Fast Sh':>8} | {'Fast PnL':>10} | "
          f"{'Slow N':>6} | {'Slow Sh':>8} | {'Slow PnL':>10} | {'Better':>7}")
    print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*8}-+-{'-'*10}-+-{'-'*6}-+-{'-'*8}-+-{'-'*10}-+-{'-'*7}")

    fast_wins = 0
    total_years = 0
    for yr in sorted(tdf['year'].unique()):
        fyr = fast[fast['year'] == yr]
        syr = slow[slow['year'] == yr]
        if len(fyr) < 5 or len(syr) < 5:
            continue
        total_years += 1
        f_sh = sharpe(fyr['pnl'])
        s_sh = sharpe(syr['pnl'])
        better = "FAST" if f_sh > s_sh else "SLOW"
        if f_sh > s_sh:
            fast_wins += 1
        print(f"  {yr:>6} | {len(fyr):>6} | {f_sh:>8.2f} | ${fyr['pnl'].sum():>+9.2f} | "
              f"{len(syr):>6} | {s_sh:>8.2f} | ${syr['pnl'].sum():>+9.2f} | {better}")

    print(f"\n  Fast beats Slow in {fast_wins}/{total_years} years ({fast_wins/total_years*100:.0f}%)")

    # ═══════════════════════════════════════════════════════════════════════
    # 4. IS VELOCITY JUST A TIME-OF-DAY PROXY?
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  4. IS VELOCITY JUST A TIME-OF-DAY PROXY?")
    print("     (If fast = London open, the filter might just be 'trade at 8-10')")
    print("=" * 100)

    print(f"\n  Average velocity by entry hour:")
    for h in sorted(tdf['entry_hour'].unique()):
        subset = tdf[tdf['entry_hour'] == h]
        print(f"    {h:02d}:xx  vel={subset['tick_velocity'].mean():.2f}  "
              f"(median={subset['tick_velocity'].median():.2f})  N={len(subset)}")

    # Within the 8:xx hour only, does velocity still predict?
    h8 = tdf[tdf['entry_hour'] == 8]
    if len(h8) > 50:
        print(f"\n  WITHIN 08:xx entries only (N={len(h8)}):")
        h8_med = h8['tick_velocity'].median()
        h8_fast = h8[h8['tick_velocity'] >= h8_med]
        h8_slow = h8[h8['tick_velocity'] < h8_med]
        print(f"    Fast half (vel>={h8_med:.2f}): N={len(h8_fast)}, "
              f"Sharpe {sharpe(h8_fast['pnl']):.2f}, PF {pf(h8_fast['pnl']):.2f}")
        print(f"    Slow half (vel< {h8_med:.2f}): N={len(h8_slow)}, "
              f"Sharpe {sharpe(h8_slow['pnl']):.2f}, PF {pf(h8_slow['pnl']):.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 5. BUY RATIO ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  5. BUY RATIO ANALYSIS (momentum confirmation)")
    print("     For LONG: want buy_ratio > 0.5 (more buying)")
    print("     For SHORT: want buy_ratio < 0.5 (more selling)")
    print("=" * 100)

    # Create "aligned momentum" score: for LONG, use buy_ratio; for SHORT, use (1-buy_ratio)
    tdf['momentum_score'] = tdf.apply(
        lambda r: r['buy_ratio'] if r['direction'] == 'LONG' else (1 - r['buy_ratio']),
        axis=1
    )

    print(f"\n  Momentum score quintiles (1=against, 5=with the breakout):")
    tdf['mom_quintile'] = pd.qcut(tdf['momentum_score'], 5, labels=['Q1_against', 'Q2', 'Q3', 'Q4', 'Q5_with'], duplicates='drop')

    for q in ['Q1_against', 'Q2', 'Q3', 'Q4', 'Q5_with']:
        subset = tdf[tdf['mom_quintile'] == q]
        p = subset['pnl']
        if len(p) < 5:
            continue
        print(f"    {q:>12}: N={len(p):>5} | Sh {sharpe(p):>6.2f} | PF {pf(p):>5.2f} | "
              f"WR {wr(p):>4.1f}% | ${p.sum():>+9.2f}")

    # OOS
    print(f"\n  OOS ({oos_start}+) momentum score:")
    oos2 = tdf[tdf['year'] >= oos_start].copy()
    oos2['mom_quintile'] = pd.qcut(oos2['momentum_score'], 5, labels=['Q1_against', 'Q2', 'Q3', 'Q4', 'Q5_with'], duplicates='drop')

    for q in ['Q1_against', 'Q2', 'Q3', 'Q4', 'Q5_with']:
        subset = oos2[oos2['mom_quintile'] == q]
        p = subset['pnl']
        if len(p) < 5:
            continue
        print(f"    {q:>12}: N={len(p):>5} | Sh {sharpe(p):>6.2f} | PF {pf(p):>5.2f} | "
              f"WR {wr(p):>4.1f}% | ${p.sum():>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 6. COMBINED FILTER: velocity + momentum
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  6. COMBINED FILTERS: velocity + momentum")
    print("=" * 100)

    vel_p50 = tdf['tick_velocity'].quantile(0.50)
    mom_p50 = tdf['momentum_score'].quantile(0.50)

    combos = [
        ("All trades", tdf),
        ("Fast only (vel>=P50)", tdf[tdf['tick_velocity'] >= vel_p50]),
        ("Momentum only (mom>=P50)", tdf[tdf['momentum_score'] >= mom_p50]),
        ("Fast + Momentum", tdf[(tdf['tick_velocity'] >= vel_p50) & (tdf['momentum_score'] >= mom_p50)]),
        ("Slow + Against", tdf[(tdf['tick_velocity'] < vel_p50) & (tdf['momentum_score'] < mom_p50)]),
    ]

    print(f"\n  Full sample:")
    for label, subset in combos:
        p = subset['pnl']
        print(f"    {label:>30}: N={len(p):>5} | Sh {sharpe(p):>6.2f} | PF {pf(p):>5.2f} | "
              f"WR {wr(p):>4.1f}% | ${p.sum():>+9.2f}")

    print(f"\n  OOS ({oos_start}+):")
    for label, subset in combos:
        oos_sub = subset[subset['year'] >= oos_start]
        p = oos_sub['pnl']
        if len(p) < 5:
            continue
        print(f"    {label:>30}: N={len(p):>5} | Sh {sharpe(p):>6.2f} | PF {pf(p):>5.2f} | "
              f"WR {wr(p):>4.1f}% | ${p.sum():>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 7. ROLLING WALK-FORWARD: Train on 3 years, test on next year
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  7. WALK-FORWARD: Train velocity threshold on 3yr, test on next year")
    print("     (Most rigorous test of whether the filter is predictive)")
    print("=" * 100)

    years = sorted(tdf['year'].unique())
    print(f"\n  {'Test':>6} | {'Train':>12} | {'Thresh':>6} | {'N_all':>6} | {'N_filt':>6} | "
          f"{'Sh_all':>7} | {'Sh_filt':>7} | {'Sh_rej':>7} | {'Filter helps?':>14}")
    print(f"  {'-'*6}-+-{'-'*12}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*14}")

    filter_helps = 0
    total_tests = 0

    for i, test_yr in enumerate(years):
        # Train on 3 years before test year
        train_years = [y for y in years if y < test_yr][-3:]
        if len(train_years) < 2:
            continue

        train = tdf[tdf['year'].isin(train_years)]
        test = tdf[tdf['year'] == test_yr]

        if len(train) < 20 or len(test) < 10:
            continue

        # Find optimal velocity threshold on training data (median as simple rule)
        thresh = train['tick_velocity'].median()

        # Apply to test year
        test_fast = test[test['tick_velocity'] >= thresh]
        test_slow = test[test['tick_velocity'] < thresh]

        sh_all = sharpe(test['pnl'])
        sh_fast = sharpe(test_fast['pnl']) if len(test_fast) >= 5 else 0
        sh_slow = sharpe(test_slow['pnl']) if len(test_slow) >= 5 else 0

        total_tests += 1
        helps = sh_fast > sh_all
        if helps:
            filter_helps += 1

        print(f"  {test_yr:>6} | {train_years[0]}-{train_years[-1]} | {thresh:>6.2f} | "
              f"{len(test):>6} | {len(test_fast):>6} | "
              f"{sh_all:>7.2f} | {sh_fast:>7.2f} | {sh_slow:>7.2f} | "
              f"{'YES' if helps else 'no':>14}")

    print(f"\n  Filter helps in {filter_helps}/{total_tests} test years ({filter_helps/max(total_tests,1)*100:.0f}%)")

    # ═══════════════════════════════════════════════════════════════════════
    # 8. VOL_IMBALANCE (buy_vol - sell_vol) — directional conviction
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  8. VOLUME IMBALANCE (directional conviction)")
    print("     For LONG: positive imbalance = more buying = good")
    print("     For SHORT: negative imbalance = more selling = good")
    print("=" * 100)

    # Create aligned imbalance: positive = in-direction
    tdf['aligned_imbalance'] = tdf.apply(
        lambda r: r['vol_imbalance'] if r['direction'] == 'LONG' else -r['vol_imbalance'],
        axis=1
    )

    tdf['imb_quintile'] = pd.qcut(tdf['aligned_imbalance'], 5,
                                    labels=['Q1_against', 'Q2', 'Q3', 'Q4', 'Q5_with'],
                                    duplicates='drop')

    print(f"\n  Aligned imbalance quintiles:")
    for q in ['Q1_against', 'Q2', 'Q3', 'Q4', 'Q5_with']:
        subset = tdf[tdf['imb_quintile'] == q]
        p = subset['pnl']
        if len(p) < 5:
            continue
        print(f"    {q:>12}: N={len(p):>5} | Sh {sharpe(p):>6.2f} | PF {pf(p):>5.2f} | "
              f"WR {wr(p):>4.1f}% | ${p.sum():>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 9. REJECTED TRADES: What happens to the ones we skip?
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  9. REJECTED TRADES: What happens to filtered-out trades?")
    print("=" * 100)

    # If we filter vel >= P50, the rejected trades are the slow ones
    accepted = tdf[tdf['tick_velocity'] >= vel_p50]
    rejected = tdf[tdf['tick_velocity'] < vel_p50]

    print(f"\n  Accepted (fast, vel>={vel_p50:.2f}): N={len(accepted)}, "
          f"Sharpe {sharpe(accepted['pnl']):.2f}, Total ${accepted['pnl'].sum():+.2f}")
    print(f"  Rejected (slow, vel< {vel_p50:.2f}): N={len(rejected)}, "
          f"Sharpe {sharpe(rejected['pnl']):.2f}, Total ${rejected['pnl'].sum():+.2f}")

    print(f"\n  Rejected trade outcomes:")
    for outcome in rejected['exit_type'].value_counts().index:
        subset = rejected[rejected['exit_type'] == outcome]
        print(f"    {outcome:>10}: N={len(subset):>5} | Mean ${subset['pnl'].mean():>+6.2f}")

    print(f"\n  Accepted trade outcomes:")
    for outcome in accepted['exit_type'].value_counts().index:
        subset = accepted[accepted['exit_type'] == outcome]
        print(f"    {outcome:>10}: N={len(subset):>5} | Mean ${subset['pnl'].mean():>+6.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 10. CORRELATION MATRIX: Are these features independent?
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  10. FEATURE CORRELATIONS")
    print("=" * 100)

    features = ['tick_velocity', 'momentum_score', 'aligned_imbalance',
                'range_size', 'entry_hour', 'gap_from_level']
    corr = tdf[features + ['pnl']].corr()
    print(f"\n  Correlation with PnL:")
    for f in features:
        print(f"    {f:>25}: r = {corr.loc['pnl', f]:>+.4f}")

    print(f"\n  Feature cross-correlations:")
    print(f"    tick_velocity vs momentum_score:  r = {corr.loc['tick_velocity', 'momentum_score']:>+.4f}")
    print(f"    tick_velocity vs aligned_imbal:   r = {corr.loc['tick_velocity', 'aligned_imbalance']:>+.4f}")
    print(f"    tick_velocity vs entry_hour:      r = {corr.loc['tick_velocity', 'entry_hour']:>+.4f}")
    print(f"    tick_velocity vs range_size:      r = {corr.loc['tick_velocity', 'range_size']:>+.4f}")

    print(f"\n{'='*100}")
    print("  DONE")
    print("=" * 100)


if __name__ == "__main__":
    main()
