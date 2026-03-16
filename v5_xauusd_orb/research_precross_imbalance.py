"""
research_precross_imbalance.py -- Pre-crossing volume imbalance analysis.

As price approaches the range level, what does order flow look like in the
bars BEFORE the crossing? Is it correlated with trade outcome?

Key advantage: this info is known BEFORE entry, so it's actionable.

Tests:
1. Correlation between pre-crossing buy_ratio and trade P&L
2. Multiple lookback windows (3, 5, 10, 15, 20 bars before crossing)
3. Matching vs divergent pre-crossing flow
4. Quintile analysis
5. Walk-forward validation of the best filter
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

from .backtest_1m import load_1m_bars, backtest, Config, Trade, stats, print_stats

ROOT = Path(__file__).resolve().parents[1]


def main():
    import datetime as dt

    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")

    oos_start = dt.date(2021, 1, 1)

    cfg = Config(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest(df, cfg)
    print(f"Total trades: {len(all_trades)}")
    print_stats(stats(all_trades, "ALL"))

    # =====================================================================
    # For each trade, compute pre-crossing buy_ratio over various windows
    # =====================================================================
    windows = [3, 5, 10, 15, 20, 30]

    # Build enriched trade data
    enriched = []
    for t in all_trades:
        try:
            idx = df.index.get_loc(t.entry_time)
        except (KeyError, TypeError):
            continue

        record = {
            'trade': t,
            'pnl': t.pnl,
            'direction': t.direction,
            'date': t.date,
            'win': t.pnl > 0,
            'entry_br': t.entry_buy_ratio,
        }

        for w in windows:
            if idx < w:
                record[f'pre_br_{w}'] = np.nan
                record[f'pre_imb_{w}'] = np.nan
                continue

            pre_bars = df.iloc[idx - w:idx]
            br = pre_bars['buy_ratio'].mean()
            record[f'pre_br_{w}'] = br

            # Direction-normalized: >0.5 means flow supports the trade direction
            if t.direction == 'LONG':
                record[f'pre_imb_{w}'] = br  # high br = buyers = supports long
            else:
                record[f'pre_imb_{w}'] = 1 - br  # low br = sellers = supports short

        enriched.append(record)

    print(f"Enriched {len(enriched)} trades with pre-crossing imbalance data")

    # =====================================================================
    # TEST 1: Raw correlation between pre-crossing buy_ratio and P&L
    # =====================================================================
    print(f"\n{'='*120}")
    print("  TEST 1: CORRELATION -- Pre-crossing buy_ratio vs trade P&L")
    print("  (Direction-normalized: >0.5 means flow supports trade direction)")
    print("=" * 120)

    edf = pd.DataFrame([{k: v for k, v in r.items() if k != 'trade'} for r in enriched])

    print(f"\n  {'Window':>8} | {'Corr(imb,pnl)':>13} | {'p-value':>8} | {'Mean_imb_win':>12} | {'Mean_imb_lose':>13} | {'Diff':>6}")
    print(f"  {'-'*8}-+-{'-'*13}-+-{'-'*8}-+-{'-'*12}-+-{'-'*13}-+-{'-'*6}")

    from scipy import stats as sp_stats

    for w in windows:
        col = f'pre_imb_{w}'
        valid = edf.dropna(subset=[col])
        if len(valid) < 50:
            continue

        corr, pval = sp_stats.pearsonr(valid[col], valid['pnl'])
        mean_win = valid[valid['win']][col].mean()
        mean_lose = valid[~valid['win']][col].mean()
        diff = mean_win - mean_lose

        sig = '***' if pval < 0.01 else ('**' if pval < 0.05 else ('*' if pval < 0.1 else ''))
        print(f"  {w:>6}m | {corr:>+12.4f} | {pval:>7.4f}{sig} | {mean_win:>12.4f} | {mean_lose:>13.4f} | {diff:>+5.4f}")

    # =====================================================================
    # TEST 2: Matching vs Divergent pre-crossing flow
    # =====================================================================
    print(f"\n{'='*120}")
    print("  TEST 2: MATCHING vs DIVERGENT pre-crossing flow")
    print("  Matching = flow supports direction (buy_ratio > 0.5 for LONG, < 0.5 for SHORT)")
    print("  Divergent = flow opposes direction")
    print("=" * 120)

    for w in windows:
        col = f'pre_imb_{w}'
        valid = [r for r in enriched if not np.isnan(r.get(col, np.nan))]
        if not valid:
            continue

        matching = [r['trade'] for r in valid if r[col] > 0.5]
        divergent = [r['trade'] for r in valid if r[col] <= 0.5]

        sm = stats(matching, f'{w}m match')
        sd = stats(divergent, f'{w}m div')

        # OOS
        match_oos = [r['trade'] for r in valid if r[col] > 0.5 and r['date'] >= oos_start]
        div_oos = [r['trade'] for r in valid if r[col] <= 0.5 and r['date'] >= oos_start]
        smo = stats(match_oos, '')
        sdo = stats(div_oos, '')

        print(f"\n  Window = {w} bars before crossing:")
        print(f"    Matching : N={sm['n']:>5} | Sh {sm['sharpe']:>6.2f} | WR {sm['wr']:>5.1f}% | Mean ${sm['mean']:>+7.2f} | OOS Sh {smo['sharpe']:>6.2f} N={smo['n']}")
        print(f"    Divergent: N={sd['n']:>5} | Sh {sd['sharpe']:>6.2f} | WR {sd['wr']:>5.1f}% | Mean ${sd['mean']:>+7.2f} | OOS Sh {sdo['sharpe']:>6.2f} N={sdo['n']}")

    # =====================================================================
    # TEST 3: Quintile analysis for each window
    # =====================================================================
    print(f"\n{'='*120}")
    print("  TEST 3: QUINTILE ANALYSIS of pre-crossing imbalance")
    print("  (Direction-normalized: Q5 = strongest flow supporting trade direction)")
    print("=" * 120)

    for w in windows:
        col = f'pre_imb_{w}'
        valid = [r for r in enriched if not np.isnan(r.get(col, np.nan))]
        if len(valid) < 50:
            continue

        imbs = np.array([r[col] for r in valid])
        edges = np.percentile(imbs, [0, 20, 40, 60, 80, 100])

        print(f"\n  Window = {w} bars:")
        labels = ['Q1_opp', 'Q2', 'Q3', 'Q4', 'Q5_supp']
        for qi in range(5):
            lo, hi = edges[qi], edges[qi + 1]
            subset = [r['trade'] for r, imb in zip(valid, imbs) if lo <= imb < (hi if qi < 4 else hi + 0.01)]
            s = stats(subset, labels[qi])
            # OOS
            sub_oos = [r['trade'] for r, imb in zip(valid, imbs)
                       if lo <= imb < (hi if qi < 4 else hi + 0.01) and r['date'] >= oos_start]
            so = stats(sub_oos, '')
            print(f"    {labels[qi]:>8} imb={lo:.3f}-{hi:.3f}: N={s['n']:>4} | Sh {s['sharpe']:>6.2f} | "
                  f"WR {s['wr']:>5.1f}% | Mean ${s['mean']:>+7.2f} | OOS Sh {so['sharpe']:>6.2f}")

    # =====================================================================
    # TEST 4: Different thresholds (not just 0.5)
    # Maybe the signal is at extremes, not at the median
    # =====================================================================
    print(f"\n{'='*120}")
    print("  TEST 4: THRESHOLD SWEEP -- pre-crossing imbalance filter")
    print("  (Keep trades where pre-crossing imbalance is above threshold)")
    print("=" * 120)

    best_w = None
    best_thr = None
    best_sharpe = -999

    for w in [5, 10, 15]:
        col = f'pre_imb_{w}'
        valid_oos = [r for r in enriched if not np.isnan(r.get(col, np.nan)) and r['date'] >= oos_start]
        if len(valid_oos) < 50:
            continue

        print(f"\n  Window = {w} bars, OOS only:")
        print(f"    {'Threshold':>10} | {'N_keep':>6} | {'N_rej':>6} | {'Sh_keep':>7} | {'Sh_rej':>7} | "
              f"{'Mean_keep':>9} | {'Mean_rej':>9}")

        for thr in [0.40, 0.45, 0.48, 0.50, 0.52, 0.55, 0.60]:
            keep = [r['trade'] for r in valid_oos if r[col] >= thr]
            rej = [r['trade'] for r in valid_oos if r[col] < thr]

            sk = stats(keep, '')
            sr = stats(rej, '')

            marker = ' <--' if sk['sharpe'] > best_sharpe and sk['n'] > 100 else ''
            if sk['sharpe'] > best_sharpe and sk['n'] > 100:
                best_sharpe = sk['sharpe']
                best_w = w
                best_thr = thr

            print(f"    {thr:>10.2f} | {sk['n']:>6} | {sr['n']:>6} | {sk['sharpe']:>7.2f} | {sr['sharpe']:>7.2f} | "
                  f"${sk['mean']:>+8.2f} | ${sr['mean']:>+8.2f}{marker}")

    # Also test DIVERGENT filter (keep low imbalance)
    print(f"\n  --- Divergent filter (keep trades where flow OPPOSES direction) ---")
    for w in [5, 10, 15]:
        col = f'pre_imb_{w}'
        valid_oos = [r for r in enriched if not np.isnan(r.get(col, np.nan)) and r['date'] >= oos_start]
        if len(valid_oos) < 50:
            continue

        print(f"\n  Window = {w} bars, OOS only (keep imb <= threshold):")
        for thr in [0.40, 0.45, 0.48, 0.50, 0.52, 0.55, 0.60]:
            keep = [r['trade'] for r in valid_oos if r[col] <= thr]
            rej = [r['trade'] for r in valid_oos if r[col] > thr]

            sk = stats(keep, '')
            sr = stats(rej, '')

            print(f"    <={thr:.2f}: N={sk['n']:>6} | Sh {sk['sharpe']:>7.2f} | "
                  f"Mean ${sk['mean']:>+8.2f} || Rejected: N={sr['n']:>6} | Sh {sr['sharpe']:>7.2f}")

    # =====================================================================
    # TEST 5: Walk-forward validation of best pre-crossing filter
    # =====================================================================
    print(f"\n{'='*120}")
    print("  TEST 5: WALK-FORWARD -- Pre-crossing imbalance filter")
    print("  (Train threshold on 3yr, test on next year)")
    print("=" * 120)

    by_year = {}
    for r in enriched:
        yr = r['date'].year
        by_year.setdefault(yr, []).append(r)

    years = sorted(by_year.keys())

    for w in [5, 10, 15]:
        col = f'pre_imb_{w}'
        print(f"\n  Window = {w} bars:")
        print(f"  {'Test':>6} | {'Train':>12} | {'Thr':>6} | {'Dir':>5} | "
              f"{'N_all':>6} | {'N_filt':>6} | {'Sh_all':>7} | {'Sh_filt':>7} | {'Better?':>8}")

        helps = 0
        total = 0

        for test_yr in years:
            train_yrs = [y for y in years if y < test_yr][-3:]
            if len(train_yrs) < 2:
                continue

            train = [r for r in enriched if r['date'].year in train_yrs and not np.isnan(r.get(col, np.nan))]
            test = [r for r in enriched if r['date'].year == test_yr and not np.isnan(r.get(col, np.nan))]
            if len(train) < 30 or len(test) < 10:
                continue

            # Try both matching (>thr) and divergent (<thr) filters
            best_train_sh = -999
            best_train_thr = 0.5
            best_train_dir = '>'

            for thr in [0.40, 0.45, 0.48, 0.50, 0.52, 0.55, 0.60]:
                # Matching: keep > thr
                keep_m = [r['trade'] for r in train if r[col] >= thr]
                sm = stats(keep_m, '')
                if sm['n'] > 20 and sm['sharpe'] > best_train_sh:
                    best_train_sh = sm['sharpe']
                    best_train_thr = thr
                    best_train_dir = '>='

                # Divergent: keep < thr
                keep_d = [r['trade'] for r in train if r[col] <= thr]
                sd = stats(keep_d, '')
                if sd['n'] > 20 and sd['sharpe'] > best_train_sh:
                    best_train_sh = sd['sharpe']
                    best_train_thr = thr
                    best_train_dir = '<='

            # Apply to test
            if best_train_dir == '>=':
                filt = [r['trade'] for r in test if r[col] >= best_train_thr]
            else:
                filt = [r['trade'] for r in test if r[col] <= best_train_thr]

            s_all = stats([r['trade'] for r in test], '')
            s_filt = stats(filt, '')

            better = s_filt.get('sharpe', 0) > s_all.get('sharpe', 0) if s_filt['n'] > 0 else False
            total += 1
            if better:
                helps += 1

            print(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {best_train_thr:>6.2f} | {best_train_dir:>5} | "
                  f"{s_all['n']:>6} | {s_filt['n']:>6} | {s_all.get('sharpe',0):>7.2f} | {s_filt.get('sharpe',0):>7.2f} | "
                  f"{'YES' if better else 'no':>8}")

        print(f"  Helps in {helps}/{total} years ({helps/max(total,1)*100:.0f}%)")

    # =====================================================================
    # TEST 6: Pre-crossing imbalance + velocity combined
    # =====================================================================
    print(f"\n{'='*120}")
    print("  TEST 6: PRE-CROSSING IMBALANCE + VELOCITY (walk-forward)")
    print("=" * 120)

    for w in [5, 10]:
        col = f'pre_imb_{w}'
        print(f"\n  Window = {w} bars + velocity filter:")
        print(f"  {'Test':>6} | {'Train':>12} | {'Vel':>5} | {'Imb_thr':>7} | {'Dir':>5} | "
              f"{'N_all':>6} | {'N_combo':>7} | {'Sh_all':>7} | {'Sh_vel':>7} | {'Sh_combo':>8}")

        for test_yr in years:
            train_yrs = [y for y in years if y < test_yr][-3:]
            if len(train_yrs) < 2:
                continue

            train = [r for r in enriched if r['date'].year in train_yrs and not np.isnan(r.get(col, np.nan))]
            test = [r for r in enriched if r['date'].year == test_yr and not np.isnan(r.get(col, np.nan))]
            if len(train) < 30 or len(test) < 10:
                continue

            vel_thr = np.median([r['trade'].entry_tick_count for r in train])

            # Find best imbalance filter on velocity-filtered training set
            train_fast = [r for r in train if r['trade'].entry_tick_count >= vel_thr]
            best_sh = -999
            best_thr = 0.5
            best_dir = '>='

            for thr in [0.40, 0.45, 0.48, 0.50, 0.52, 0.55]:
                for d, fn in [('>=', lambda r, t: r[col] >= t), ('<=', lambda r, t: r[col] <= t)]:
                    keep = [r['trade'] for r in train_fast if fn(r, thr)]
                    s = stats(keep, '')
                    if s['n'] > 15 and s['sharpe'] > best_sh:
                        best_sh = s['sharpe']
                        best_thr = thr
                        best_dir = d

            # Apply to test
            test_all = [r['trade'] for r in test]
            test_vel = [r['trade'] for r in test if r['trade'].entry_tick_count >= vel_thr]
            if best_dir == '>=':
                test_combo = [r['trade'] for r in test
                              if r['trade'].entry_tick_count >= vel_thr and r[col] >= best_thr]
            else:
                test_combo = [r['trade'] for r in test
                              if r['trade'].entry_tick_count >= vel_thr and r[col] <= best_thr]

            s_all = stats(test_all, '')
            s_vel = stats(test_vel, '')
            s_combo = stats(test_combo, '')

            print(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {vel_thr:>5.0f} | {best_thr:>7.2f} | {best_dir:>5} | "
                  f"{s_all['n']:>6} | {s_combo['n']:>7} | {s_all.get('sharpe',0):>7.2f} | {s_vel.get('sharpe',0):>7.2f} | {s_combo.get('sharpe',0):>8.2f}")

    print(f"\n{'='*120}")
    print("  DONE")
    print("=" * 120)


if __name__ == "__main__":
    main()
