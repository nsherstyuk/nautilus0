"""
research_category_b_filter.py -- Validate Category B filter on 1-minute bar dataset.

Category definitions (based on gap period 06:00-08:00 UTC behavior):
  A: Price crossed range level during gap AND still past it at 08:00 (gap-open)
  B: Price crossed range level during gap but RETURNED to range by 08:00
  C: Price never crossed the range level during the gap (clean breakout)

Prior finding (5-min, 625 trades): Cat B has Sharpe 0.13, WR 50%, ~zero edge.
This script validates on 1-min data (1,613 trades) with walk-forward.

Usage:
  python -m v5_xauusd_orb.research_category_b_filter
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd

from .backtest_1m import load_1m_bars, backtest, stats, print_stats, Config, Trade


OOS_START = dt.date(2021, 1, 1)


def classify_gap(day_df, rh, rl, direction):
    """
    Check gap period (06:00-08:00 UTC) to classify the trade.
    Returns: 'A' (gap-open), 'B' (returned), 'C' (clean), and gap metadata.
    """
    gap_bars = day_df[(day_df['hour'] >= 6) & (day_df['hour'] < 8)]
    if len(gap_bars) == 0:
        return 'C', {}

    level = rh if direction == 'LONG' else rl

    crossed = False
    first_cross_time = None
    max_excursion = 0.0

    for idx, bar in gap_bars.iterrows():
        if direction == 'LONG':
            if bar['high'] >= rh:
                if not crossed:
                    crossed = True
                    first_cross_time = idx
                max_excursion = max(max_excursion, bar['high'] - rh)
        else:
            if bar['low'] <= rl:
                if not crossed:
                    crossed = True
                    first_cross_time = idx
                max_excursion = max(max_excursion, rl - bar['low'])

    if not crossed:
        return 'C', {'max_excursion': 0}

    # Check price at 08:00
    window_start = day_df[(day_df['hour'] == 8) & (day_df['minute'] == 0)]
    if len(window_start) == 0:
        # Fallback: use first bar in trade window
        window = day_df[day_df['hour'] >= 8]
        if len(window) == 0:
            return 'C', {'max_excursion': 0}
        open_at_8 = window.iloc[0]['open']
    else:
        open_at_8 = window_start.iloc[0]['open']

    if direction == 'LONG':
        still_past = open_at_8 >= rh
        gap_distance = open_at_8 - rh
    else:
        still_past = open_at_8 <= rl
        gap_distance = rl - open_at_8

    meta = {
        'first_cross_time': first_cross_time,
        'max_excursion': max_excursion,
        'gap_distance': gap_distance,
        'open_at_8': open_at_8,
    }

    if still_past:
        return 'A', meta
    else:
        return 'B', meta


def enrich_trades(df, trades):
    """Add gap category to each trade."""
    enriched = []
    by_date = {d: g for d, g in df.groupby('date')}

    for t in trades:
        day_df = by_date.get(t.date)
        if day_df is None:
            continue

        cat, meta = classify_gap(day_df, t.range_high, t.range_low, t.direction)
        enriched.append({
            'trade': t,
            'category': cat,
            **meta,
        })

    return enriched


def main():
    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")

    cfg = Config(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest(df, cfg)
    print(f"Total trades: {len(all_trades)}")
    print_stats(stats(all_trades, 'ALL'))

    enriched = enrich_trades(df, all_trades)
    print(f"Enriched {len(enriched)} trades with gap category")

    cats = {'A': [], 'B': [], 'C': []}
    for e in enriched:
        cats[e['category']].append(e)

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 1: Category breakdown
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 1: CATEGORY BREAKDOWN")
    print("=" * 110)

    for cat_name, cat_label in [('A', 'Gap-open (still past level at 08:00)'),
                                 ('B', 'Returned (crossed but came back by 08:00)'),
                                 ('C', 'Clean (never crossed during gap)')]:
        cat_trades = [e['trade'] for e in cats[cat_name]]
        n = len(cat_trades)
        pct = n / len(enriched) * 100
        s = stats(cat_trades, f"Cat {cat_name}")
        oos = [e['trade'] for e in cats[cat_name] if e['trade'].date >= OOS_START]
        so = stats(oos, f"Cat {cat_name} OOS")

        print(f"\n  Category {cat_name}: {cat_label}")
        print(f"    N={n:>5} ({pct:.1f}%)")
        print_stats(s)
        print_stats(so)

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 2: Filter impact (A+C only vs ALL)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 2: CATEGORY B FILTER IMPACT")
    print("=" * 110)

    filtered_trades = [e['trade'] for e in enriched if e['category'] != 'B']
    filtered_oos = [t for t in filtered_trades if t.date >= OOS_START]

    all_oos = [e['trade'] for e in enriched if e['trade'].date >= OOS_START]

    print(f"\n  ALL data:")
    print_stats(stats([e['trade'] for e in enriched], 'Baseline (all)'))
    print_stats(stats(filtered_trades, 'Filtered (A+C)'))
    removed = len(enriched) - len(filtered_trades)
    print(f"    Removed: {removed} trades ({removed/len(enriched)*100:.1f}%)")

    print(f"\n  OOS (2021+):")
    print_stats(stats(all_oos, 'Baseline OOS'))
    print_stats(stats(filtered_oos, 'Filtered OOS'))
    removed_oos = len(all_oos) - len(filtered_oos)
    print(f"    Removed: {removed_oos} trades ({removed_oos/len(all_oos)*100:.1f}%)")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 3: Walk-forward validation
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 3: WALK-FORWARD VALIDATION (annual)")
    print("=" * 110)

    by_year = {}
    for e in enriched:
        yr = e['trade'].date.year
        by_year.setdefault(yr, []).append(e)

    years = sorted(by_year.keys())

    print(f"\n  {'Year':>6} | {'N_all':>6} | {'N_filt':>6} | {'N_catB':>6} | "
          f"{'Sh_all':>7} | {'Sh_filt':>7} | {'PF_all':>6} | {'PF_filt':>6} | {'Better?':>8}")
    print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}-+-{'-'*6}-+-{'-'*6}-+-{'-'*8}")

    helps = 0
    total = 0

    for yr in years:
        yr_all = [e['trade'] for e in by_year[yr]]
        yr_filt = [e['trade'] for e in by_year[yr] if e['category'] != 'B']
        yr_catb = [e['trade'] for e in by_year[yr] if e['category'] == 'B']

        if len(yr_all) < 10:
            continue

        sa = stats(yr_all)
        sf = stats(yr_filt)

        total += 1
        better = sf['sharpe'] > sa['sharpe']
        if better:
            helps += 1

        print(f"  {yr:>6} | {sa['n']:>6} | {sf['n']:>6} | {len(yr_catb):>6} | "
              f"{sa['sharpe']:>7.2f} | {sf['sharpe']:>7.2f} | "
              f"{sa['pf']:>6.2f} | {sf['pf']:>6.2f} | {'YES' if better else 'no':>8}")

    print(f"\n  Filter helps in {helps}/{total} years ({helps/max(total,1)*100:.0f}%)")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 4: Category B characteristics
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 4: CATEGORY B CHARACTERISTICS")
    print("=" * 110)

    cat_b_entries = cats['B']
    if cat_b_entries:
        excursions = [e['max_excursion'] for e in cat_b_entries if 'max_excursion' in e]
        ranges = [e['trade'].range_size for e in cat_b_entries]
        pnls = [e['trade'].pnl for e in cat_b_entries]
        exits = {}
        for e in cat_b_entries:
            et = e['trade'].exit_type
            exits[et] = exits.get(et, 0) + 1

        print(f"\n  N = {len(cat_b_entries)}")
        print(f"  Range size: mean=${np.mean(ranges):.2f}, median=${np.median(ranges):.2f}")
        if excursions:
            print(f"  Max gap excursion: mean=${np.mean(excursions):.2f}, median=${np.median(excursions):.2f}")
            exc_pct = [e / r if r > 0 else 0 for e, r in zip(excursions, ranges)]
            print(f"  Excursion as % of range: mean={np.mean(exc_pct)*100:.1f}%, median={np.median(exc_pct)*100:.1f}%")
        print(f"  P&L: mean=${np.mean(pnls):.2f}, median=${np.median(pnls):.2f}")
        print(f"  Exit types: {exits}")

        # Direction split
        long_b = [e for e in cat_b_entries if e['trade'].direction == 'LONG']
        short_b = [e for e in cat_b_entries if e['trade'].direction == 'SHORT']
        print(f"  Direction: LONG={len(long_b)}, SHORT={len(short_b)}")

        sl = stats([e['trade'] for e in long_b], 'Cat B LONG')
        ss = stats([e['trade'] for e in short_b], 'Cat B SHORT')
        print_stats(sl)
        print_stats(ss)

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 5: Category B exit type distribution vs A and C
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 5: EXIT TYPE DISTRIBUTION BY CATEGORY")
    print("=" * 110)

    for cat_name in ['A', 'B', 'C']:
        cat_trades = [e['trade'] for e in cats[cat_name]]
        if not cat_trades:
            continue
        exit_counts = {}
        for t in cat_trades:
            exit_counts[t.exit_type] = exit_counts.get(t.exit_type, 0) + 1
        total_n = len(cat_trades)
        print(f"\n  Category {cat_name} (N={total_n}):")
        for et in sorted(exit_counts.keys()):
            pct = exit_counts[et] / total_n * 100
            print(f"    {et:>10}: {exit_counts[et]:>5} ({pct:>5.1f}%)")

    print(f"\n{'='*110}")
    print("  DONE")
    print("=" * 110)


if __name__ == "__main__":
    main()
