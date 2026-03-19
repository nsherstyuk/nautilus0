"""
research_range_quality.py -- Explore Range Quality features as trade outcome predictors.

Hypothesis: Characteristics of the Asian session range (00:00-06:00 UTC) can predict
whether the subsequent London breakout will follow through or fail.

Features tested:
  1. NR4/NR7 (narrow range relative to recent sessions)
  2. Range size relative to recent ATR
  3. POC position (Point of Control — highest-volume price within range)
  4. VWAP position within range
  5. Intra-range volatility (normalized)
  6. Time at extremes (directional bias)
  7. Touch count at boundaries

Usage:
  python -m v5_xauusd_orb.research_range_quality
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd

from .backtest_1m import load_1m_bars, backtest, stats, print_stats, Config, Trade


OOS_START = dt.date(2021, 1, 1)


def compute_range_features(day_df, rh, rl, rs, recent_ranges):
    """
    Compute range quality features from Asian session bars.
    Returns dict of feature values or None if insufficient data.
    """
    asian = day_df[(day_df['hour'] >= 0) & (day_df['hour'] < 6)]
    if len(asian) < 10:
        return None

    features = {}

    # ── Feature 1: NR (Narrow Range) ──
    if len(recent_ranges) >= 4:
        features['nr4'] = 1 if rs <= min(recent_ranges[-4:]) else 0
    else:
        features['nr4'] = np.nan
    if len(recent_ranges) >= 7:
        features['nr7'] = 1 if rs <= min(recent_ranges[-7:]) else 0
    else:
        features['nr7'] = np.nan

    if len(recent_ranges) >= 4:
        rank = sum(1 for r in recent_ranges[-20:] if r >= rs) / len(recent_ranges[-20:])
        features['range_rank'] = rank  # 1.0 = narrowest, 0.0 = widest
    else:
        features['range_rank'] = np.nan

    # ── Feature 2: Range size relative to recent ATR ──
    if len(recent_ranges) >= 5:
        features['range_vs_5d'] = rs / np.mean(recent_ranges[-5:])
        features['range_vs_10d'] = rs / np.mean(recent_ranges[-10:]) if len(recent_ranges) >= 10 else np.nan
    else:
        features['range_vs_5d'] = np.nan
        features['range_vs_10d'] = np.nan

    # ── Feature 3: POC position ──
    # Bin prices and find the bin with highest volume
    if 'total_volume' in asian.columns and asian['total_volume'].sum() > 0:
        # Use $0.50 bins for gold
        bin_size = max(0.5, rs / 20)  # at least 20 bins across range
        bins = np.arange(rl, rh + bin_size, bin_size)
        if len(bins) >= 2:
            typical_price = (asian['high'] + asian['low'] + asian['close']) / 3
            vol = asian['total_volume'].values
            bin_idx = np.digitize(typical_price.values, bins) - 1
            bin_idx = np.clip(bin_idx, 0, len(bins) - 2)
            bin_vol = np.zeros(len(bins) - 1)
            for i, v in zip(bin_idx, vol):
                bin_vol[i] += v
            poc_bin = np.argmax(bin_vol)
            poc_price = (bins[poc_bin] + bins[poc_bin + 1]) / 2
            features['poc_position'] = (poc_price - rl) / rs if rs > 0 else 0.5
        else:
            features['poc_position'] = 0.5
    else:
        features['poc_position'] = 0.5

    # ── Feature 4: VWAP position ──
    if 'total_volume' in asian.columns and asian['total_volume'].sum() > 0:
        typical = (asian['high'] + asian['low'] + asian['close']) / 3
        vol = asian['total_volume']
        vwap = (typical * vol).sum() / vol.sum()
        features['vwap_position'] = (vwap - rl) / rs if rs > 0 else 0.5
    else:
        features['vwap_position'] = 0.5

    # ── Feature 5: Intra-range volatility ──
    returns = asian['close'].pct_change().dropna()
    if len(returns) > 5:
        intra_vol = returns.std()
        # Normalize by range size (as fraction of mid price)
        range_pct = rs / ((rh + rl) / 2)
        features['intra_vol'] = intra_vol / range_pct if range_pct > 0 else 0
    else:
        features['intra_vol'] = np.nan

    # ── Feature 6: Time at extremes ──
    close_vals = asian['close'].values
    top_zone = rh - 0.2 * rs
    bottom_zone = rl + 0.2 * rs
    time_at_top = np.sum(close_vals >= top_zone) / len(close_vals)
    time_at_bottom = np.sum(close_vals <= bottom_zone) / len(close_vals)
    features['time_at_top'] = time_at_top
    features['time_at_bottom'] = time_at_bottom
    features['top_minus_bottom'] = time_at_top - time_at_bottom

    # ── Feature 7: Touch count ──
    touch_zone = 0.05 * rs  # 5% of range
    touches_high = np.sum(asian['high'].values >= (rh - touch_zone))
    touches_low = np.sum(asian['low'].values <= (rl + touch_zone))
    features['touches_high'] = touches_high
    features['touches_low'] = touches_low
    features['total_touches'] = touches_high + touches_low

    return features


def enrich_trades(df, trades):
    """Add range quality features to each trade."""
    enriched = []
    by_date = {d: g for d, g in df.groupby('date')}

    # Build running list of recent ranges
    all_dates = sorted(by_date.keys())
    range_by_date = {}
    for d in all_dates:
        day_df = by_date[d]
        asian = day_df[(day_df['hour'] >= 0) & (day_df['hour'] < 6)]
        if len(asian) >= 10:
            rh = asian['high'].max()
            rl = asian['low'].min()
            rs = rh - rl
            if rs > 0:
                range_by_date[d] = rs

    for t in trades:
        day_df = by_date.get(t.date)
        if day_df is None:
            continue

        # Get recent ranges (preceding days only)
        recent = [range_by_date[d] for d in sorted(range_by_date.keys()) if d < t.date]

        features = compute_range_features(day_df, t.range_high, t.range_low, t.range_size, recent)
        if features is None:
            continue

        enriched.append({
            'trade': t,
            **features,
        })

    return enriched


def quintile_analysis(enriched, feature_name, label, reverse=False):
    """Split trades into quintiles by feature, report stats."""
    vals = [(e, e[feature_name]) for e in enriched if not np.isnan(e.get(feature_name, np.nan))]
    if len(vals) < 25:
        print(f"  {label}: insufficient data (N={len(vals)})")
        return

    vals.sort(key=lambda x: x[1], reverse=reverse)
    n = len(vals)
    q_size = n // 5
    remainder = n % 5

    print(f"\n  {label} (N={n}):")
    print(f"  {'Quintile':>10} | {'Range':>20} | {'N':>5} | {'Sharpe':>7} | {'WR':>5} | "
          f"{'Mean':>7} | {'Total':>10} | {'OOS_Sh':>7}")

    idx = 0
    for qi in range(5):
        size = q_size + (1 if qi < remainder else 0)
        subset = vals[idx:idx + size]
        idx += size

        trades_q = [e[0]['trade'] for e in subset]
        feat_vals = [e[1] for e in subset]
        oos_trades = [t for t in trades_q if t.date >= OOS_START]

        s = stats(trades_q)
        so = stats(oos_trades)

        lo, hi = min(feat_vals), max(feat_vals)
        q_label = f"Q{qi+1}"
        if qi == 0:
            q_label = "Q1_low" if not reverse else "Q1_high"
        elif qi == 4:
            q_label = "Q5_high" if not reverse else "Q5_low"

        print(f"  {q_label:>10} | {lo:>9.4f} - {hi:>8.4f} | {s['n']:>5} | {s['sharpe']:>7.2f} | "
              f"{s['wr']:>4.1f}% | ${s['mean']:>+6.2f} | ${s['total']:>+9.2f} | {so['sharpe']:>7.2f}")


def main():
    from scipy.stats import pearsonr

    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")

    cfg = Config(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest(df, cfg)
    print(f"Total trades: {len(all_trades)}")

    enriched = enrich_trades(df, all_trades)
    print(f"Enriched {len(enriched)} trades with range quality features")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 1: Feature distributions
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 1: FEATURE DISTRIBUTIONS")
    print("=" * 110)

    feature_names = ['nr4', 'nr7', 'range_rank', 'range_vs_5d', 'range_vs_10d',
                     'poc_position', 'vwap_position', 'intra_vol',
                     'time_at_top', 'time_at_bottom', 'top_minus_bottom',
                     'touches_high', 'touches_low', 'total_touches']

    print(f"\n  {'Feature':>20} | {'N':>5} | {'Mean':>8} | {'Median':>8} | {'Std':>8} | {'Min':>8} | {'Max':>8}")
    print(f"  {'-'*20}-+-{'-'*5}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}")

    for fname in feature_names:
        vals = [e[fname] for e in enriched if not np.isnan(e.get(fname, np.nan))]
        if vals:
            print(f"  {fname:>20} | {len(vals):>5} | {np.mean(vals):>8.4f} | {np.median(vals):>8.4f} | "
                  f"{np.std(vals):>8.4f} | {np.min(vals):>8.4f} | {np.max(vals):>8.4f}")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 2: Correlation with P&L
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 2: CORRELATION WITH TRADE P&L")
    print("=" * 110)

    continuous_features = ['range_rank', 'range_vs_5d', 'range_vs_10d',
                           'poc_position', 'vwap_position', 'intra_vol',
                           'time_at_top', 'time_at_bottom', 'top_minus_bottom',
                           'total_touches']

    print(f"\n  {'Feature':>20} | {'Corr':>8} | {'p-value':>10} | {'N':>5}")
    print(f"  {'-'*20}-+-{'-'*8}-+-{'-'*10}-+-{'-'*5}")

    for fname in continuous_features:
        pairs = [(e[fname], e['trade'].pnl) for e in enriched
                 if not np.isnan(e.get(fname, np.nan))]
        if len(pairs) < 30:
            continue
        x, y = zip(*pairs)
        corr, pval = pearsonr(x, y)
        sig = "***" if pval < 0.001 else "**" if pval < 0.01 else "*" if pval < 0.05 else ""
        print(f"  {fname:>20} | {corr:>+8.4f} | {pval:>10.6f} | {len(pairs):>5} {sig}")

    # Direction-normalized POC: for LONG, POC>0.5 is supportive
    print(f"\n  Direction-normalized features:")
    dn_pairs = []
    for e in enriched:
        poc = e.get('poc_position', np.nan)
        if np.isnan(poc):
            continue
        # Normalize: for LONG, higher POC is supportive; for SHORT, lower POC is supportive
        if e['trade'].direction == 'LONG':
            dn_poc = poc
        else:
            dn_poc = 1.0 - poc
        dn_pairs.append((dn_poc, e['trade'].pnl))

    if len(dn_pairs) >= 30:
        x, y = zip(*dn_pairs)
        corr, pval = pearsonr(x, y)
        print(f"  {'dn_poc_position':>20} | {corr:>+8.4f} | {pval:>10.6f} | {len(dn_pairs):>5}")

    dn_vwap_pairs = []
    for e in enriched:
        vwap = e.get('vwap_position', np.nan)
        if np.isnan(vwap):
            continue
        if e['trade'].direction == 'LONG':
            dn_vwap = vwap
        else:
            dn_vwap = 1.0 - vwap
        dn_vwap_pairs.append((dn_vwap, e['trade'].pnl))

    if len(dn_vwap_pairs) >= 30:
        x, y = zip(*dn_vwap_pairs)
        corr, pval = pearsonr(x, y)
        print(f"  {'dn_vwap_position':>20} | {corr:>+8.4f} | {pval:>10.6f} | {len(dn_vwap_pairs):>5}")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 3: Quintile analysis
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 3: QUINTILE ANALYSIS")
    print("=" * 110)

    for fname, label in [('range_rank', 'Range Rank (1=narrowest)'),
                          ('range_vs_5d', 'Range vs 5d avg'),
                          ('range_vs_10d', 'Range vs 10d avg'),
                          ('poc_position', 'POC Position (0=bottom, 1=top)'),
                          ('vwap_position', 'VWAP Position (0=bottom, 1=top)'),
                          ('intra_vol', 'Intra-range Volatility'),
                          ('total_touches', 'Total Boundary Touches'),
                          ('top_minus_bottom', 'Time at Top minus Bottom')]:
        quintile_analysis(enriched, fname, label)

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 4: NR4/NR7 filter
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 4: NR4/NR7 FILTER")
    print("=" * 110)

    for nr_name in ['nr4', 'nr7']:
        nr_trades = [e for e in enriched if e.get(nr_name) == 1]
        non_nr = [e for e in enriched if e.get(nr_name) == 0]

        if len(nr_trades) < 5:
            print(f"\n  {nr_name.upper()}: insufficient NR trades (N={len(nr_trades)})")
            continue

        s_nr = stats([e['trade'] for e in nr_trades], f'{nr_name.upper()} days')
        s_non = stats([e['trade'] for e in non_nr], f'Non-{nr_name.upper()} days')

        oos_nr = stats([e['trade'] for e in nr_trades if e['trade'].date >= OOS_START],
                       f'{nr_name.upper()} OOS')
        oos_non = stats([e['trade'] for e in non_nr if e['trade'].date >= OOS_START],
                        f'Non-{nr_name.upper()} OOS')

        print(f"\n  {nr_name.upper()} analysis:")
        print_stats(s_nr)
        print_stats(s_non)
        print_stats(oos_nr)
        print_stats(oos_non)

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 5: POC directional alignment
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 5: POC DIRECTIONAL ALIGNMENT")
    print("  (LONG + POC>0.5 = aligned, SHORT + POC<0.5 = aligned)")
    print("=" * 110)

    aligned = []
    misaligned = []
    for e in enriched:
        poc = e.get('poc_position', 0.5)
        if e['trade'].direction == 'LONG':
            if poc > 0.5:
                aligned.append(e)
            else:
                misaligned.append(e)
        else:  # SHORT
            if poc < 0.5:
                aligned.append(e)
            else:
                misaligned.append(e)

    s_a = stats([e['trade'] for e in aligned], 'Aligned (POC supports direction)')
    s_m = stats([e['trade'] for e in misaligned], 'Misaligned (POC opposes direction)')
    oos_a = stats([e['trade'] for e in aligned if e['trade'].date >= OOS_START], 'Aligned OOS')
    oos_m = stats([e['trade'] for e in misaligned if e['trade'].date >= OOS_START], 'Misaligned OOS')

    print()
    print_stats(s_a)
    print_stats(s_m)
    print_stats(oos_a)
    print_stats(oos_m)

    # Same for VWAP
    print(f"\n  VWAP directional alignment:")
    aligned_v = []
    misaligned_v = []
    for e in enriched:
        vwap = e.get('vwap_position', 0.5)
        if e['trade'].direction == 'LONG':
            if vwap > 0.5:
                aligned_v.append(e)
            else:
                misaligned_v.append(e)
        else:
            if vwap < 0.5:
                aligned_v.append(e)
            else:
                misaligned_v.append(e)

    print_stats(stats([e['trade'] for e in aligned_v], 'VWAP Aligned'))
    print_stats(stats([e['trade'] for e in misaligned_v], 'VWAP Misaligned'))
    print_stats(stats([e['trade'] for e in aligned_v if e['trade'].date >= OOS_START], 'VWAP Aligned OOS'))
    print_stats(stats([e['trade'] for e in misaligned_v if e['trade'].date >= OOS_START], 'VWAP Misaligned OOS'))

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 6: Promising feature combinations
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 6: FEATURE COMBINATIONS")
    print("=" * 110)

    # Narrow range + POC aligned
    print(f"\n  Combo 1: Narrow range (range_vs_5d < 0.8) + POC aligned")
    narrow_aligned = [e for e in enriched
                      if e.get('range_vs_5d', 999) < 0.8
                      and ((e['trade'].direction == 'LONG' and e.get('poc_position', 0.5) > 0.5)
                           or (e['trade'].direction == 'SHORT' and e.get('poc_position', 0.5) < 0.5))]
    narrow_only = [e for e in enriched if e.get('range_vs_5d', 999) < 0.8]

    print_stats(stats([e['trade'] for e in enriched], 'Baseline'))
    print_stats(stats([e['trade'] for e in narrow_only], 'Narrow only'))
    print_stats(stats([e['trade'] for e in narrow_aligned], 'Narrow + POC aligned'))
    print_stats(stats([e['trade'] for e in narrow_aligned if e['trade'].date >= OOS_START],
                      'Narrow + POC aligned OOS'))

    # Low intra-vol + POC aligned
    print(f"\n  Combo 2: Low intra-vol (Q1-Q2) + POC aligned")
    intra_vals = [e['intra_vol'] for e in enriched if not np.isnan(e.get('intra_vol', np.nan))]
    if intra_vals:
        med_vol = np.median(intra_vals)
        low_vol_aligned = [e for e in enriched
                           if e.get('intra_vol', 999) <= med_vol
                           and ((e['trade'].direction == 'LONG' and e.get('poc_position', 0.5) > 0.5)
                                or (e['trade'].direction == 'SHORT' and e.get('poc_position', 0.5) < 0.5))]
        low_vol_only = [e for e in enriched if e.get('intra_vol', 999) <= med_vol]

        print_stats(stats([e['trade'] for e in low_vol_only], 'Low intra-vol only'))
        print_stats(stats([e['trade'] for e in low_vol_aligned], 'Low vol + POC aligned'))
        print_stats(stats([e['trade'] for e in low_vol_aligned if e['trade'].date >= OOS_START],
                          'Low vol + POC OOS'))

    # Wide range filter (remove widest 20%)
    print(f"\n  Combo 3: Remove widest 20% of ranges")
    rv5_vals = [e['range_vs_5d'] for e in enriched if not np.isnan(e.get('range_vs_5d', np.nan))]
    if rv5_vals:
        p80 = np.percentile(rv5_vals, 80)
        not_wide = [e for e in enriched if e.get('range_vs_5d', 0) <= p80]
        print_stats(stats([e['trade'] for e in not_wide], f'Range_vs_5d <= {p80:.2f} (P80)'))
        print_stats(stats([e['trade'] for e in not_wide if e['trade'].date >= OOS_START],
                          'Not-wide OOS'))

    print(f"\n{'='*110}")
    print("  DONE")
    print("=" * 110)


if __name__ == "__main__":
    main()
