"""
research_velocity_threshold.py -- Find the optimal velocity filter threshold.

Tests:
1. Fine-grained percentile sweep (P10 to P90)
2. Walk-forward at each percentile (train on 3yr, test on next)
3. Different lookback windows (entry bar only vs avg of last N bars)
4. Fixed vs adaptive threshold
5. Robustness: how sensitive is the result to the exact threshold?
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from v5_xauusd_orb.backtest_1m import load_1m_bars, backtest, Config, stats, Trade


def main():
    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars")

    oos_start = dt.date(2021, 1, 1)
    cfg = Config(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest(df, cfg)
    print(f"Total trades: {len(all_trades)}")

    oos_trades = [t for t in all_trades if t.date >= oos_start]
    is_trades = [t for t in all_trades if t.date < oos_start]
    print(f"IS: {len(is_trades)}, OOS: {len(oos_trades)}")

    tc_all = np.array([t.entry_tick_count for t in all_trades])

    # ═══════════════════════════════════════════════════════════════════
    # 1. PERCENTILE SWEEP — keep trades above P-th percentile
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  1. PERCENTILE SWEEP — keep trades with tick_count >= threshold")
    print("     (threshold = P-th percentile of ALL trades)")
    print("=" * 110)

    print(f"\n  {'Pct':>5} | {'Thresh':>6} | {'N_pass':>6} | {'N_rej':>5} | "
          f"{'Sh_pass':>7} | {'PF_pass':>7} | {'WR_pass':>6} | "
          f"{'Sh_rej':>7} | {'$_pass':>10} | {'$_rej':>10} | "
          f"{'OOS_Sh':>7} | {'OOS_$':>10}")
    print(f"  {'-'*5}-+-{'-'*6}-+-{'-'*6}-+-{'-'*5}-+-"
          f"{'-'*7}-+-{'-'*7}-+-{'-'*6}-+-"
          f"{'-'*7}-+-{'-'*10}-+-{'-'*10}-+-"
          f"{'-'*7}-+-{'-'*10}")

    pcts = list(range(0, 85, 5))
    results = []

    for pct in pcts:
        thresh = np.percentile(tc_all, pct)
        passed = [t for t in all_trades if t.entry_tick_count >= thresh]
        rejected = [t for t in all_trades if t.entry_tick_count < thresh]
        sp = stats(passed)
        sr = stats(rejected) if rejected else {'sharpe': 0, 'pf': 0, 'wr': 0, 'total': 0}

        oos_passed = [t for t in oos_trades if t.entry_tick_count >= thresh]
        so = stats(oos_passed) if oos_passed else {'sharpe': 0, 'total': 0}

        results.append({
            'pct': pct, 'thresh': thresh, 'n_pass': len(passed),
            'sh_pass': sp['sharpe'], 'pf_pass': sp['pf'], 'wr_pass': sp['wr'],
            'total_pass': sp['total'], 'sh_rej': sr['sharpe'], 'total_rej': sr['total'],
            'oos_sh': so['sharpe'], 'oos_total': so['total'],
        })

        print(f"  P{pct:>3} | {thresh:>6.0f} | {len(passed):>6} | {len(rejected):>5} | "
              f"{sp['sharpe']:>7.2f} | {sp['pf']:>7.2f} | {sp['wr']:>5.1f}% | "
              f"{sr['sharpe']:>7.2f} | ${sp['total']:>+9.2f} | ${sr['total']:>+9.2f} | "
              f"{so['sharpe']:>7.2f} | ${so['total']:>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════
    # 2. WALK-FORWARD AT EACH PERCENTILE
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  2. WALK-FORWARD at each percentile (3yr train, 1yr test)")
    print("=" * 110)

    by_year = {}
    for t in all_trades:
        by_year.setdefault(t.date.year, []).append(t)
    years = sorted(by_year.keys())

    # Test percentiles
    test_pcts = [20, 30, 40, 50, 60, 70]

    header = f"  {'Year':>6}"
    for p in test_pcts:
        header += f" | P{p} Sh"
    header += " | Unfiltered"
    print(header)
    print(f"  {'-'*6}" + "".join(f"-+-{'-'*6}" for _ in test_pcts) + f"-+-{'-'*10}")

    wf_totals = {p: {'helps': 0, 'total_tests': 0, 'sum_sh': 0} for p in test_pcts}

    for test_yr in years:
        train_yrs = [y for y in years if y < test_yr][-3:]
        if len(train_yrs) < 2:
            continue
        train_trades = [t for t in all_trades if t.date.year in train_yrs]
        test_trades = by_year[test_yr]
        if len(test_trades) < 10:
            continue

        train_tc = np.array([t.entry_tick_count for t in train_trades])
        sh_all = stats(test_trades)['sharpe']

        row = f"  {test_yr:>6}"
        for p in test_pcts:
            thresh = np.percentile(train_tc, p)
            passed = [t for t in test_trades if t.entry_tick_count >= thresh]
            sh = stats(passed)['sharpe'] if len(passed) >= 5 else 0
            row += f" | {sh:>5.2f}"
            wf_totals[p]['total_tests'] += 1
            wf_totals[p]['sum_sh'] += sh
            if sh > sh_all:
                wf_totals[p]['helps'] += 1

        row += f" | {sh_all:>9.2f}"
        print(row)

    print(f"\n  Summary:")
    print(f"  {'Pct':>5} | {'Helps':>12} | {'Avg Sh':>7}")
    for p in test_pcts:
        wf = wf_totals[p]
        n = wf['total_tests']
        avg = wf['sum_sh'] / n if n > 0 else 0
        print(f"  P{p:>3} | {wf['helps']}/{n} ({wf['helps']/max(n,1)*100:.0f}%) | {avg:>7.2f}")

    # ═══════════════════════════════════════════════════════════════════
    # 3. LOOKBACK WINDOW — average tick count over N minutes before entry
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  3. LOOKBACK WINDOW — use avg tick count from bars around entry")
    print("     (requires re-running backtest with lookback context)")
    print("=" * 110)

    # For this we need to enrich trades with surrounding bar data
    # Let's compute tick_count averages from the raw 1-min data
    # We'll look at the 5 and 10 bars preceding the entry time

    for window_min in [1, 3, 5, 10]:
        enriched = []
        for t in all_trades:
            entry_ts = t.entry_time
            if pd.isna(entry_ts):
                continue
            # Get bars in the window before entry
            start_ts = entry_ts - pd.Timedelta(minutes=window_min)
            mask = (df.index > start_ts) & (df.index <= entry_ts)
            window_bars = df.loc[mask]
            if len(window_bars) == 0:
                avg_tc = t.entry_tick_count
            else:
                avg_tc = window_bars['tick_count'].mean()
            enriched.append((t, avg_tc))

        # Use median of avg_tc as threshold
        avg_tcs = np.array([e[1] for e in enriched])
        med = np.median(avg_tcs)
        fast = [e[0] for e in enriched if e[1] >= med]
        slow = [e[0] for e in enriched if e[1] < med]

        sf = stats(fast)
        ss = stats(slow)
        oos_fast = [t for t in fast if t.date >= oos_start]
        oos_slow = [t for t in slow if t.date >= oos_start]
        sof = stats(oos_fast)
        sos = stats(oos_slow)

        print(f"\n  Window = {window_min} min (median={med:.0f}):")
        print(f"    Fast: N={sf['n']:>5} | Sh {sf['sharpe']:>6.2f} | Total ${sf['total']:>+9.2f} | "
              f"OOS Sh {sof['sharpe']:>6.2f} | OOS ${sof['total']:>+9.2f}")
        print(f"    Slow: N={ss['n']:>5} | Sh {ss['sharpe']:>6.2f} | Total ${ss['total']:>+9.2f} | "
              f"OOS Sh {sos['sharpe']:>6.2f} | OOS ${sos['total']:>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════
    # 4. FIXED THRESHOLDS — absolute tick count cutoffs
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  4. FIXED THRESHOLDS — absolute tick count cutoffs")
    print("=" * 110)

    print(f"\n  {'Thresh':>6} | {'N':>5} | {'Sh':>7} | {'PF':>5} | {'Total':>10} | "
          f"{'OOS_Sh':>7} | {'OOS_$':>10} | {'OOS_N':>5}")
    print(f"  {'-'*6}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*10}-+-"
          f"{'-'*7}-+-{'-'*10}-+-{'-'*5}")

    for thresh in [50, 75, 100, 125, 150, 175, 200, 225, 250, 300, 350, 400]:
        passed = [t for t in all_trades if t.entry_tick_count >= thresh]
        sp = stats(passed)
        oos_p = [t for t in oos_trades if t.entry_tick_count >= thresh]
        so = stats(oos_p) if oos_p else {'sharpe': 0, 'total': 0, 'n': 0}
        print(f"  {thresh:>6} | {sp['n']:>5} | {sp['sharpe']:>7.2f} | {sp['pf']:>5.2f} | "
              f"${sp['total']:>+9.2f} | {so['sharpe']:>7.2f} | ${so['total']:>+9.2f} | {so['n']:>5}")

    # ═══════════════════════════════════════════════════════════════════
    # 5. ROBUSTNESS — Sharpe as a function of threshold (smooth curve?)
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  5. ROBUSTNESS — is the edge stable across nearby thresholds?")
    print("     (testing every 10 ticks from 100 to 350)")
    print("=" * 110)

    print(f"\n  {'Thresh':>6} | {'N':>5} | {'Full Sh':>7} | {'OOS Sh':>7} | {'Bar':>30}")

    for thresh in range(100, 360, 10):
        passed = [t for t in all_trades if t.entry_tick_count >= thresh]
        sp = stats(passed)
        oos_p = [t for t in oos_trades if t.entry_tick_count >= thresh]
        so = stats(oos_p) if oos_p else {'sharpe': 0}

        bar_len = int(max(0, min(30, sp['sharpe'] * 15)))
        bar = '#' * bar_len
        print(f"  {thresh:>6} | {sp['n']:>5} | {sp['sharpe']:>7.2f} | {so['sharpe']:>7.2f} | {bar}")

    # ═══════════════════════════════════════════════════════════════════
    # 6. TRADE FREQUENCY — how many trades per year at each threshold
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  6. TRADE FREQUENCY at key thresholds")
    print("=" * 110)

    key_thresholds = [0, 100, 150, 200, 250, 300]
    header = f"  {'Year':>6}"
    for th in key_thresholds:
        header += f" | tc>={th:>3}"
    print(header)

    for yr in sorted(by_year.keys()):
        row = f"  {yr:>6}"
        for th in key_thresholds:
            n = len([t for t in by_year[yr] if t.entry_tick_count >= th])
            row += f" |   {n:>4}"
        print(row)

    print(f"\n{'='*110}")
    print("  DONE")
    print("=" * 110)


if __name__ == "__main__":
    main()
