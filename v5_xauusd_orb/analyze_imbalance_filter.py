"""
Analyze volume imbalance as an entry confirmation filter for ORB.

Tests whether filtering entries by buy_ratio agreement with direction
improves performance. Uses existing V5 backtest trades.

Approach:
  - Run baseline backtest (stop entry, no time exit)
  - Filter trades: LONG requires buy_ratio > threshold, SHORT requires buy_ratio < (1 - threshold)
  - Sweep thresholds and compare Sharpe, PF, WR
  - Also test lookback-averaged imbalance (avg of N bars before entry)
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import datetime as dt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_1m import load_1m_bars, backtest, Config, stats, print_stats, Trade


def main():
    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")

    oos_start = dt.date(2021, 1, 1)

    # Baseline: stop entry, no time exit
    cfg = Config(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest(df, cfg)
    oos_trades = [t for t in all_trades if t.date >= oos_start]

    print(f"\nBaseline: {len(all_trades)} trades ({len(oos_trades)} OOS)")
    print_stats(stats(all_trades, "ALL"))
    print_stats(stats(oos_trades, "OOS"))

    # ═══════════════════════════════════════════════════════════════════════
    # 1. Buy ratio distribution at entry
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  1. BUY RATIO AT ENTRY — distribution by direction")
    print("=" * 110)

    long_trades = [t for t in all_trades if t.direction == 'LONG']
    short_trades = [t for t in all_trades if t.direction == 'SHORT']

    long_br = [t.entry_buy_ratio for t in long_trades]
    short_br = [t.entry_buy_ratio for t in short_trades]

    print(f"\n  LONG entries  (N={len(long_br)}):")
    print(f"    buy_ratio: mean={np.mean(long_br):.4f}, median={np.median(long_br):.4f}, "
          f"P25={np.percentile(long_br,25):.4f}, P75={np.percentile(long_br,75):.4f}")

    print(f"  SHORT entries (N={len(short_br)}):")
    print(f"    buy_ratio: mean={np.mean(short_br):.4f}, median={np.median(short_br):.4f}, "
          f"P25={np.percentile(short_br,25):.4f}, P75={np.percentile(short_br,75):.4f}")

    # Directional agreement rate
    long_agree = sum(1 for br in long_br if br > 0.50)
    short_agree = sum(1 for br in short_br if br < 0.50)
    print(f"\n  Agreement rate (flow matches direction):")
    print(f"    LONG  with buy_ratio > 0.50: {long_agree}/{len(long_br)} ({long_agree/len(long_br)*100:.1f}%)")
    print(f"    SHORT with buy_ratio < 0.50: {short_agree}/{len(short_br)} ({short_agree/len(short_br)*100:.1f}%)")

    # ═══════════════════════════════════════════════════════════════════════
    # 2. Agreement vs disagreement performance
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  2. FLOW AGREEMENT vs DISAGREEMENT — does matching flow help?")
    print("=" * 110)

    agree = [t for t in all_trades if
             (t.direction == 'LONG' and t.entry_buy_ratio > 0.50) or
             (t.direction == 'SHORT' and t.entry_buy_ratio < 0.50)]
    disagree = [t for t in all_trades if
                (t.direction == 'LONG' and t.entry_buy_ratio <= 0.50) or
                (t.direction == 'SHORT' and t.entry_buy_ratio >= 0.50)]

    print_stats(stats(agree, "Flow AGREES"))
    print_stats(stats(disagree, "Flow DISAGREES"))

    agree_oos = [t for t in agree if t.date >= oos_start]
    disagree_oos = [t for t in disagree if t.date >= oos_start]
    print_stats(stats(agree_oos, "Flow AGREES (OOS)"))
    print_stats(stats(disagree_oos, "Flow DISAGREES (OOS)"))

    # ═══════════════════════════════════════════════════════════════════════
    # 3. Threshold sweep — how aggressive should the filter be?
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  3. BUY RATIO THRESHOLD SWEEP — LONG requires > thresh, SHORT requires < (1-thresh)")
    print("=" * 110)

    print(f"\n  {'Thresh':>8} | {'N_pass':>6} | {'N_rej':>5} | {'Sh_pass':>7} | {'Sh_rej':>6} | "
          f"{'PF_pass':>7} | {'WR_pass':>7} | {'Total_pass':>10} | {'OOS_Sh':>6} | {'Better':>6}")
    print(f"  {'-'*8}-+-{'-'*6}-+-{'-'*5}-+-{'-'*7}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}-+-{'-'*10}-+-{'-'*6}-+-{'-'*6}")

    base_sh = stats(all_trades)['sharpe']
    base_oos_sh = stats(oos_trades)['sharpe']

    for thresh in [0.48, 0.49, 0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.58, 0.60]:
        passed = [t for t in all_trades if
                  (t.direction == 'LONG' and t.entry_buy_ratio > thresh) or
                  (t.direction == 'SHORT' and t.entry_buy_ratio < (1.0 - thresh))]
        rejected = [t for t in all_trades if t not in passed]

        sp = stats(passed)
        sr = stats(rejected)

        passed_oos = [t for t in passed if t.date >= oos_start]
        sp_oos = stats(passed_oos)

        better = "YES" if sp['sharpe'] > base_sh else "no"
        print(f"  {thresh:>8.2f} | {sp['n']:>6} | {sr['n']:>5} | {sp['sharpe']:>7.2f} | "
              f"{sr['sharpe']:>6.2f} | {sp['pf']:>7.2f} | {sp['wr']:>6.1f}% | "
              f"${sp['total']:>+9.2f} | {sp_oos['sharpe']:>6.2f} | {better:>6}")

    # ═══════════════════════════════════════════════════════════════════════
    # 4. Combined: velocity + imbalance
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  4. COMBINED: velocity (tick_count >= median) + imbalance filter")
    print("=" * 110)

    tc_med = np.median([t.entry_tick_count for t in all_trades])
    fast_trades = [t for t in all_trades if t.entry_tick_count >= tc_med]

    print(f"\n  Velocity filter: tick_count >= {tc_med:.0f} (median)")
    print_stats(stats(fast_trades, "Velocity only"))
    print_stats(stats([t for t in fast_trades if t.date >= oos_start], "Velocity only (OOS)"))

    for thresh in [0.50, 0.52, 0.54, 0.56]:
        combined = [t for t in fast_trades if
                    (t.direction == 'LONG' and t.entry_buy_ratio > thresh) or
                    (t.direction == 'SHORT' and t.entry_buy_ratio < (1.0 - thresh))]
        combined_oos = [t for t in combined if t.date >= oos_start]

        sc = stats(combined, f"Vel+Imb>{thresh:.2f}")
        sco = stats(combined_oos, f"Vel+Imb>{thresh:.2f} OOS")
        print_stats(sc)
        print_stats(sco)

    # ═══════════════════════════════════════════════════════════════════════
    # 5. Annual breakdown: agree vs disagree
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  5. ANNUAL: flow-agree (>0.50) vs flow-disagree trades")
    print("=" * 110)

    by_year_agree = {}
    by_year_disagree = {}
    for t in all_trades:
        yr = t.date.year
        flow_agrees = ((t.direction == 'LONG' and t.entry_buy_ratio > 0.50) or
                       (t.direction == 'SHORT' and t.entry_buy_ratio < 0.50))
        if flow_agrees:
            by_year_agree.setdefault(yr, []).append(t)
        else:
            by_year_disagree.setdefault(yr, []).append(t)

    print(f"\n  {'Year':>6} | {'N_agree':>7} | {'Sh_agree':>8} | {'PnL_agree':>10} | "
          f"{'N_disagree':>10} | {'Sh_disagree':>11} | {'PnL_disagree':>12}")
    print(f"  {'-'*6}-+-{'-'*7}-+-{'-'*8}-+-{'-'*10}-+-{'-'*10}-+-{'-'*11}-+-{'-'*12}")

    for yr in sorted(set(list(by_year_agree.keys()) + list(by_year_disagree.keys()))):
        sa = stats(by_year_agree.get(yr, []))
        sd = stats(by_year_disagree.get(yr, []))
        print(f"  {yr:>6} | {sa['n']:>7} | {sa['sharpe']:>8.2f} | ${sa['total']:>+9.2f} | "
              f"{sd['n']:>10} | {sd['sharpe']:>11.2f} | ${sd['total']:>+11.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 6. Walk-forward: train imbalance threshold, test on next year
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  6. WALK-FORWARD: Train imbalance threshold on 3yr, test on next")
    print("=" * 110)

    by_year = {}
    for t in all_trades:
        by_year.setdefault(t.date.year, []).append(t)
    years = sorted(by_year.keys())

    print(f"\n  {'Test':>6} | {'Train':>12} | {'Thresh':>6} | {'N_all':>6} | {'N_filt':>6} | "
          f"{'Sh_all':>7} | {'Sh_filt':>7} | {'Sh_rej':>7} | {'Better?':>8}")

    wf_helps = 0
    wf_total = 0

    for test_yr in years:
        train_yrs = [y for y in years if y < test_yr][-3:]
        if len(train_yrs) < 2:
            continue

        train_trades = [t for t in all_trades if t.date.year in train_yrs]
        test_trades = [t for t in all_trades if t.date.year == test_yr]
        if len(train_trades) < 20 or len(test_trades) < 10:
            continue

        # Find optimal threshold on training data
        best_thresh = 0.50
        best_sh = stats(train_trades)['sharpe']
        for th in [0.50, 0.51, 0.52, 0.53, 0.54, 0.55]:
            filt = [t for t in train_trades if
                    (t.direction == 'LONG' and t.entry_buy_ratio > th) or
                    (t.direction == 'SHORT' and t.entry_buy_ratio < (1.0 - th))]
            if len(filt) >= 20:
                sh = stats(filt)['sharpe']
                if sh > best_sh:
                    best_sh = sh
                    best_thresh = th

        # Apply to test year
        test_filt = [t for t in test_trades if
                     (t.direction == 'LONG' and t.entry_buy_ratio > best_thresh) or
                     (t.direction == 'SHORT' and t.entry_buy_ratio < (1.0 - best_thresh))]
        test_rej = [t for t in test_trades if t not in test_filt]

        sh_all = stats(test_trades)['sharpe']
        sh_filt = stats(test_filt)['sharpe'] if len(test_filt) >= 5 else 0
        sh_rej = stats(test_rej)['sharpe'] if len(test_rej) >= 5 else 0

        wf_total += 1
        helps = sh_filt > sh_all
        if helps:
            wf_helps += 1

        print(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {best_thresh:>6.2f} | "
              f"{len(test_trades):>6} | {len(test_filt):>6} | "
              f"{sh_all:>7.2f} | {sh_filt:>7.2f} | {sh_rej:>7.2f} | "
              f"{'YES' if helps else 'no':>8}")

    print(f"\n  Filter helps in {wf_helps}/{wf_total} years ({wf_helps/max(wf_total,1)*100:.0f}%)")

    print(f"\n{'='*110}")
    print("  DONE")
    print("=" * 110)


if __name__ == "__main__":
    main()
