"""
research_walkforward_filters.py -- Walk-forward validation of two ORB filters:

1. Entry bar direction filter: only take trades where entry bar close-vs-open
   aligns with trade direction (bullish bar + LONG, bearish bar + SHORT)

2. SHORT + high buy_ratio filter: for SHORT trades, require buy_ratio above
   a threshold (trapped longs fueling the move). LONG trades unfiltered.

Walk-forward protocol:
  - Train on 3 years, test on the next year
  - For filter 1: no parameter to train (it's binary), just measure stability
  - For filter 2: train the buy_ratio threshold (percentile) on training set,
    apply to test set
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

from .backtest_1m import load_1m_bars, backtest, Config, Trade, stats, print_stats, _monitor

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv'


def get_entry_bar_direction(trade: Trade, df: pd.DataFrame) -> str:
    """Returns 'aligned', 'opposed', or 'unknown'."""
    try:
        bar = df.loc[trade.entry_time]
        bar_bullish = bar['close'] > bar['open']
    except (KeyError, TypeError):
        return 'unknown'

    if trade.direction == 'LONG':
        return 'aligned' if bar_bullish else 'opposed'
    else:
        return 'aligned' if not bar_bullish else 'opposed'


def main():
    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")

    cfg = Config(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest(df, cfg)
    print(f"Total trades: {len(all_trades)}")

    # Group trades by year
    by_year = {}
    for t in all_trades:
        yr = t.date.year
        by_year.setdefault(yr, []).append(t)

    years = sorted(by_year.keys())

    # =================================================================
    # FILTER 1: Entry bar direction (walk-forward stability test)
    # No parameter to optimize -- just test if the aligned/opposed
    # separation holds year after year
    # =================================================================
    print(f"\n{'='*120}")
    print("  FILTER 1: ENTRY BAR DIRECTION -- Walk-forward stability")
    print("  (No parameter to train -- just checking if the separation is consistent across years)")
    print("=" * 120)

    print(f"\n  {'Year':>6} | {'N_all':>6} | {'N_aln':>6} | {'N_opp':>6} | "
          f"{'Sh_all':>7} | {'Sh_aln':>7} | {'Sh_opp':>7} | "
          f"{'Mean_all':>9} | {'Mean_aln':>9} | {'Mean_opp':>9} | {'Filter helps?':>14}")
    print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-"
          f"{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-"
          f"{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*14}")

    f1_helps = 0
    f1_total = 0

    for yr in years:
        trades_yr = by_year[yr]
        aligned_yr = [t for t in trades_yr if get_entry_bar_direction(t, df) == 'aligned']
        opposed_yr = [t for t in trades_yr if get_entry_bar_direction(t, df) == 'opposed']

        s_all = stats(trades_yr, '')
        s_aln = stats(aligned_yr, '')
        s_opp = stats(opposed_yr, '')

        helps = s_aln['sharpe'] > s_all['sharpe'] if s_all['n'] > 0 and s_aln['n'] > 0 else False
        f1_total += 1
        if helps:
            f1_helps += 1

        print(f"  {yr:>6} | {s_all['n']:>6} | {s_aln['n']:>6} | {s_opp['n']:>6} | "
              f"{s_all['sharpe']:>7.2f} | {s_aln['sharpe']:>7.2f} | {s_opp['sharpe']:>7.2f} | "
              f"${s_all['mean']:>+8.2f} | ${s_aln['mean']:>+8.2f} | ${s_opp['mean']:>+8.2f} | "
              f"{'YES' if helps else 'no':>14}")

    print(f"\n  Filter helps in {f1_helps}/{f1_total} years ({f1_helps/max(f1_total,1)*100:.0f}%)")

    # Cumulative equity comparison
    print(f"\n  Cumulative P&L comparison:")
    pnl_all = sum(t.pnl for t in all_trades)
    pnl_aln = sum(t.pnl for t in all_trades if get_entry_bar_direction(t, df) == 'aligned')
    pnl_opp = sum(t.pnl for t in all_trades if get_entry_bar_direction(t, df) == 'opposed')
    n_aln = sum(1 for t in all_trades if get_entry_bar_direction(t, df) == 'aligned')
    n_opp = sum(1 for t in all_trades if get_entry_bar_direction(t, df) == 'opposed')

    print(f"    All trades:     N={len(all_trades):>5}, Total ${pnl_all:>+10.2f}, Mean ${pnl_all/len(all_trades):>+7.2f}")
    print(f"    Aligned only:   N={n_aln:>5}, Total ${pnl_aln:>+10.2f}, Mean ${pnl_aln/max(n_aln,1):>+7.2f}")
    print(f"    Opposed (rej):  N={n_opp:>5}, Total ${pnl_opp:>+10.2f}, Mean ${pnl_opp/max(n_opp,1):>+7.2f}")
    print(f"    Rejected P&L is {'POSITIVE (you lose edge by filtering)' if pnl_opp > 50 else 'NEAR ZERO or NEGATIVE (safe to filter)'}")

    # =================================================================
    # How does filter 1 interact with velocity?
    # =================================================================
    print(f"\n  --- Filter 1 + Velocity filter interaction ---")
    tc_median = np.median([t.entry_tick_count for t in all_trades])
    fast_trades = [t for t in all_trades if t.entry_tick_count >= tc_median]
    fast_aligned = [t for t in fast_trades if get_entry_bar_direction(t, df) == 'aligned']
    fast_opposed = [t for t in fast_trades if get_entry_bar_direction(t, df) == 'opposed']

    print(f"    Velocity-filtered (fast half) baseline:")
    print_stats(stats(fast_trades, "Fast"))
    print(f"    Fast + aligned bar:")
    print_stats(stats(fast_aligned, "Fast+Aligned"))
    print(f"    Fast + opposed bar:")
    print_stats(stats(fast_opposed, "Fast+Opposed"))

    # =================================================================
    # FILTER 2: SHORT + high buy_ratio (walk-forward with threshold)
    # Train: find optimal buy_ratio percentile cutoff on training years
    # Test: apply that threshold on test year
    # =================================================================
    print(f"\n{'='*120}")
    print("  FILTER 2: SHORT + HIGH BUY_RATIO -- Walk-forward with trained threshold")
    print("  (For SHORT trades: require buy_ratio > threshold. LONG trades: unfiltered)")
    print("=" * 120)

    print(f"\n  {'Test':>6} | {'Train':>12} | {'BR_thr':>7} | "
          f"{'N_all':>6} | {'N_filt':>6} | {'N_rej':>6} | "
          f"{'Sh_all':>7} | {'Sh_filt':>7} | {'Sh_rej':>7} | "
          f"{'Mean_filt':>9} | {'Mean_rej':>9} | {'Better?':>8}")

    f2_helps = 0
    f2_total = 0

    for test_yr in years:
        train_yrs = [y for y in years if y < test_yr][-3:]
        if len(train_yrs) < 2:
            continue

        train_trades = [t for t in all_trades if t.date.year in train_yrs]
        test_trades = [t for t in all_trades if t.date.year == test_yr]
        if len(train_trades) < 20 or len(test_trades) < 10:
            continue

        # Train: find buy_ratio threshold for SHORT trades
        # Use median buy_ratio of winning SHORT trades as threshold
        train_short_winners = [t for t in train_trades if t.direction == 'SHORT' and t.pnl > 0]
        train_short_losers = [t for t in train_trades if t.direction == 'SHORT' and t.pnl <= 0]

        if not train_short_winners:
            continue

        # Try percentiles P40, P50, P60 on training SHORT trades' buy_ratio
        # Pick the one that maximizes Sharpe on training set
        train_short = [t for t in train_trades if t.direction == 'SHORT']
        best_thr = 0.5
        best_train_sharpe = -999

        for pct in [30, 40, 50, 60, 70]:
            thr = np.percentile([t.entry_buy_ratio for t in train_short if t.entry_buy_ratio > 0], pct)
            # Apply filter: keep SHORT with br > thr, keep all LONG
            filt = [t for t in train_trades
                    if t.direction == 'LONG' or (t.direction == 'SHORT' and t.entry_buy_ratio >= thr)]
            s = stats(filt, '')
            if s['sharpe'] > best_train_sharpe:
                best_train_sharpe = s['sharpe']
                best_thr = thr

        # Apply best threshold to test year
        test_filt = [t for t in test_trades
                     if t.direction == 'LONG' or (t.direction == 'SHORT' and t.entry_buy_ratio >= best_thr)]
        test_rej = [t for t in test_trades
                    if t.direction == 'SHORT' and t.entry_buy_ratio < best_thr]

        s_all = stats(test_trades, '')
        s_filt = stats(test_filt, '')
        s_rej = stats(test_rej, '')

        helps = s_filt['sharpe'] > s_all['sharpe'] if s_filt['n'] > 0 else False
        f2_total += 1
        if helps:
            f2_helps += 1

        print(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {best_thr:>7.3f} | "
              f"{s_all['n']:>6} | {s_filt['n']:>6} | {s_rej['n']:>6} | "
              f"{s_all['sharpe']:>7.2f} | {s_filt['sharpe']:>7.2f} | {s_rej['sharpe']:>7.2f} | "
              f"${s_filt['mean']:>+8.2f} | ${s_rej['mean']:>+8.2f} | "
              f"{'YES' if helps else 'no':>8}")

    print(f"\n  Filter helps in {f2_helps}/{f2_total} years ({f2_helps/max(f2_total,1)*100:.0f}%)")

    # =================================================================
    # FILTER 2B: Both directions -- buy_ratio alignment filter
    # LONG: keep br > threshold, SHORT: keep br < (1-threshold)
    # Essentially: require "matching" flow, but with optimized threshold
    # Wait -- the data showed DIVERGENT is better. So let's test:
    # LONG: keep br < threshold (divergent buyers = sellers dominate)
    # SHORT: keep br > threshold (divergent = buyers dominate)
    # =================================================================
    print(f"\n{'='*120}")
    print("  FILTER 2B: DIVERGENT FLOW FILTER -- Walk-forward")
    print("  (Keep trades where order flow OPPOSES trade direction)")
    print("  LONG: keep buy_ratio < threshold | SHORT: keep buy_ratio > threshold")
    print("=" * 120)

    print(f"\n  {'Test':>6} | {'Train':>12} | {'BR_thr':>7} | "
          f"{'N_all':>6} | {'N_div':>6} | {'N_match':>7} | "
          f"{'Sh_all':>7} | {'Sh_div':>7} | {'Sh_match':>8} | {'Better?':>8}")

    f2b_helps = 0
    f2b_total = 0

    for test_yr in years:
        train_yrs = [y for y in years if y < test_yr][-3:]
        if len(train_yrs) < 2:
            continue

        train_trades = [t for t in all_trades if t.date.year in train_yrs]
        test_trades = [t for t in all_trades if t.date.year == test_yr]
        if len(train_trades) < 20 or len(test_trades) < 10:
            continue

        # Train: find threshold that maximizes divergent subset Sharpe
        best_thr = 0.5
        best_train_sharpe = -999

        for thr in [0.40, 0.45, 0.48, 0.50, 0.52, 0.55, 0.60]:
            # Divergent = LONG with br < thr OR SHORT with br > (1 - thr)
            filt = [t for t in train_trades if t.entry_buy_ratio > 0 and (
                (t.direction == 'LONG' and t.entry_buy_ratio < thr) or
                (t.direction == 'SHORT' and t.entry_buy_ratio > (1 - thr))
            )]
            s = stats(filt, '')
            if s['n'] > 10 and s['sharpe'] > best_train_sharpe:
                best_train_sharpe = s['sharpe']
                best_thr = thr

        # Apply to test
        test_div = [t for t in test_trades if t.entry_buy_ratio > 0 and (
            (t.direction == 'LONG' and t.entry_buy_ratio < best_thr) or
            (t.direction == 'SHORT' and t.entry_buy_ratio > (1 - best_thr))
        )]
        test_match = [t for t in test_trades if t.entry_buy_ratio > 0 and (
            (t.direction == 'LONG' and t.entry_buy_ratio >= best_thr) or
            (t.direction == 'SHORT' and t.entry_buy_ratio <= (1 - best_thr))
        )]

        s_all = stats(test_trades, '')
        s_div = stats(test_div, '')
        s_match = stats(test_match, '')

        helps = s_div['sharpe'] > s_all['sharpe'] if s_div['n'] > 0 else False
        f2b_total += 1
        if helps:
            f2b_helps += 1

        print(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {best_thr:>7.3f} | "
              f"{s_all['n']:>6} | {s_div['n']:>6} | {s_match['n']:>7} | "
              f"{s_all['sharpe']:>7.2f} | {s_div['sharpe']:>7.2f} | {s_match['sharpe']:>8.2f} | "
              f"{'YES' if helps else 'no':>8}")

    print(f"\n  Filter helps in {f2b_helps}/{f2b_total} years ({f2b_helps/max(f2b_total,1)*100:.0f}%)")

    # =================================================================
    # COMBINED: Velocity + bar direction
    # =================================================================
    print(f"\n{'='*120}")
    print("  COMBINED: Velocity + Entry Bar Direction -- Walk-forward")
    print("=" * 120)

    print(f"\n  {'Test':>6} | {'Train':>12} | {'Vel_thr':>7} | "
          f"{'N_base':>6} | {'N_vel':>6} | {'N_vel+bar':>9} | "
          f"{'Sh_base':>7} | {'Sh_vel':>7} | {'Sh_vel+bar':>10} | {'Bar helps?':>10}")

    comb_helps = 0
    comb_total = 0

    for test_yr in years:
        train_yrs = [y for y in years if y < test_yr][-3:]
        if len(train_yrs) < 2:
            continue

        train_trades = [t for t in all_trades if t.date.year in train_yrs]
        test_trades = [t for t in all_trades if t.date.year == test_yr]
        if len(train_trades) < 20 or len(test_trades) < 10:
            continue

        vel_thr = np.median([t.entry_tick_count for t in train_trades])

        test_vel = [t for t in test_trades if t.entry_tick_count >= vel_thr]
        test_vel_bar = [t for t in test_vel if get_entry_bar_direction(t, df) == 'aligned']

        s_base = stats(test_trades, '')
        s_vel = stats(test_vel, '')
        s_vel_bar = stats(test_vel_bar, '')

        helps = s_vel_bar['sharpe'] > s_vel['sharpe'] if s_vel_bar['n'] > 0 and s_vel['n'] > 0 else False
        comb_total += 1
        if helps:
            comb_helps += 1

        print(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {vel_thr:>7.0f} | "
              f"{s_base['n']:>6} | {s_vel['n']:>6} | {s_vel_bar['n']:>9} | "
              f"{s_base['sharpe']:>7.2f} | {s_vel['sharpe']:>7.2f} | {s_vel_bar['sharpe']:>10.2f} | "
              f"{'YES' if helps else 'no':>10}")

    print(f"\n  Bar direction adds value on top of velocity in {comb_helps}/{comb_total} years ({comb_helps/max(comb_total,1)*100:.0f}%)")

    print(f"\n{'='*120}")
    print("  DONE")
    print("=" * 120)


if __name__ == "__main__":
    main()
