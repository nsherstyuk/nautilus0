"""
research_gap_entry.py -- Investigate how pre-window level crossing affects trade quality.

Key questions:
1. When price already crossed range_high/low BEFORE trade_start (8:00 UTC),
   how far past the level is it? (This is the "gap" the backtest ignores.)
2. Does the SIZE of this gap predict trade quality?
3. What if we only enter on pullback (price returns to the level)?
4. What if we add a "must cross DURING window" filter?
5. What does the 6-8 UTC gap period look like — when exactly does the cross happen?

Usage:
  python -m v5_xauusd_orb.research_gap_entry
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_5m(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    return df


def compute_stats(pnl_series: pd.Series) -> dict:
    if len(pnl_series) == 0:
        return {'n': 0, 'sharpe': 0, 'mean': 0, 'wr': 0, 'total': 0}
    n = len(pnl_series)
    mean = pnl_series.mean()
    std = pnl_series.std()
    sharpe = mean / std * np.sqrt(252) if std > 0 else 0
    wr = (pnl_series > 0).mean() * 100
    return {'n': n, 'sharpe': round(sharpe, 2), 'mean': round(mean, 2),
            'wr': round(wr, 1), 'total': round(pnl_series.sum(), 2)}


def main():
    csv_path = str(ROOT / 'data' / '5m_csv' / 'xauusd_5m.csv')
    df = load_5m(csv_path)
    print(f"Loaded {len(df):,} 5-min bars ({df.index.min().date()} to {df.index.max().date()})")

    RR = 2.0
    SLIP = 0.15
    SPREAD = 0.10

    results = []

    for day, day_df in df.groupby('date'):
        weekday = day_df['weekday'].iloc[0]
        if weekday >= 5 or weekday == 2:
            continue

        # Asian range (0-6 UTC)
        asian = day_df[(day_df['hour'] >= 0) & (day_df['hour'] < 6)]
        if len(asian) < 36:
            continue

        rh = asian['high'].max()
        rl = asian['low'].min()
        rs = rh - rl
        if rs <= 0:
            continue
        mid = (rh + rl) / 2
        rpct = rs / mid * 100
        if rpct < 0.05 or rpct > 2.0:
            continue

        # Gap period (6-8 UTC)
        gap = day_df[(day_df['hour'] >= 6) & (day_df['hour'] < 8)]

        # Track when the level was first crossed in the gap
        first_cross_high_time = None
        first_cross_low_time = None
        max_above_rh_in_gap = 0  # max price excursion above range_high during gap
        max_below_rl_in_gap = 0  # max price excursion below range_low during gap

        for idx, bar in gap.iterrows():
            if bar['high'] >= rh:
                if first_cross_high_time is None:
                    first_cross_high_time = idx
                max_above_rh_in_gap = max(max_above_rh_in_gap, bar['high'] - rh)
            if bar['low'] <= rl:
                if first_cross_low_time is None:
                    first_cross_low_time = idx
                max_below_rl_in_gap = max(max_below_rl_in_gap, rl - bar['low'])

        # Price at window open (8:00 UTC bar)
        window = day_df[(day_df['hour'] >= 8) & (day_df['hour'] < 16)]
        if len(window) == 0:
            continue

        first_bar = window.iloc[0]
        open_at_8 = first_bar['open']

        # Classify entry type
        # Does the first 5-min bar at 8:00 already cross the level?
        gap_crossed_high = first_cross_high_time is not None
        gap_crossed_low = first_cross_low_time is not None

        # Price gap at 8:00 (how far past the level is the open?)
        gap_above = max(0, open_at_8 - rh) if open_at_8 > rh else 0
        gap_below = max(0, rl - open_at_8) if open_at_8 < rl else 0

        # Did price RETURN to range before 8:00 after crossing?
        # (i.e., crossed high during gap, but came back below by 8:00)
        returned_to_range = False
        if gap_crossed_high and open_at_8 < rh:
            returned_to_range = True
        if gap_crossed_low and open_at_8 > rl:
            returned_to_range = True

        # Now simulate the trade on 5-min bars (same as research_5m.py)
        long_entry = rh + SLIP
        short_entry = rl - SLIP
        long_tp = rh + RR * rs
        short_tp = rl - RR * rs

        direction = None
        entry_bar_i = None
        for i, (idx, bar) in enumerate(window.iterrows()):
            if bar['high'] >= rh:
                direction = 'LONG'
                entry_bar_i = i
                entry_px = long_entry
                sl_px = rl
                tp_px = long_tp
                break
            if bar['low'] <= rl:
                direction = 'SHORT'
                entry_bar_i = i
                entry_px = short_entry
                sl_px = rh
                tp_px = short_tp
                break

        if direction is None:
            continue

        # Monitor trade (60-min time exit = 12 bars of 5 min)
        monitor = window.iloc[entry_bar_i + 1:]
        result = 'EOD'
        exit_px = None
        TIME_EXIT_BARS = 12  # 60 min

        for j, (idx, bar) in enumerate(monitor.iterrows()):
            if j >= TIME_EXIT_BARS:
                exit_px = bar['open']
                exit_px = exit_px - SLIP if direction == 'LONG' else exit_px + SLIP
                result = 'TIME_EXIT'
                break
            if direction == 'LONG':
                if bar['low'] <= sl_px:
                    exit_px = sl_px - SLIP
                    result = 'SL'
                    break
                if bar['high'] >= tp_px:
                    exit_px = tp_px
                    result = 'TP'
                    break
            else:
                if bar['high'] >= sl_px:
                    exit_px = sl_px + SLIP
                    result = 'SL'
                    break
                if bar['low'] <= tp_px:
                    exit_px = tp_px
                    result = 'TP'
                    break

        if exit_px is None:
            if len(monitor) > 0:
                exit_px = monitor['close'].iloc[-1]
                exit_px = exit_px - SLIP if direction == 'LONG' else exit_px + SLIP
            else:
                exit_px = entry_px

        raw_pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)
        pnl_usd = raw_pnl - (SPREAD * 2)

        # Entry bar info
        entry_hour = window.index[entry_bar_i].hour
        entry_minute = window.index[entry_bar_i].minute
        enters_on_first_bar = (entry_bar_i == 0)

        # For long: gap = open_at_8 - range_high (how far past the level)
        # For short: gap = range_low - open_at_8
        if direction == 'LONG':
            price_gap = open_at_8 - rh
            pre_crossed = gap_crossed_high
            gap_excursion = max_above_rh_in_gap
        else:
            price_gap = rl - open_at_8
            pre_crossed = gap_crossed_low
            gap_excursion = max_below_rl_in_gap

        # Normalize gap by range size
        gap_pct_of_range = price_gap / rs if rs > 0 else 0

        results.append({
            'date': day,
            'direction': direction,
            'result': result,
            'pnl_usd': round(pnl_usd, 2),
            'range_size': round(rs, 2),
            'entry_hour': entry_hour,
            'entry_minute': entry_minute,
            'enters_first_bar': enters_on_first_bar,
            'pre_crossed': pre_crossed,
            'price_gap': round(price_gap, 2),
            'gap_pct_of_range': round(gap_pct_of_range, 4),
            'gap_excursion': round(gap_excursion, 2),
            'returned_to_range': returned_to_range,
            'open_at_8': round(open_at_8, 2),
            'range_high': round(rh, 2),
            'range_low': round(rl, 2),
        })

    trades = pd.DataFrame(results)
    print(f"Total trades: {len(trades)}")

    # ═══════════════════════════════════════════════════════════════════════════
    # ANALYSIS 1: Entry categories
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  1. ENTRY CATEGORIES")
    print("=" * 95)

    # Category A: Price crossed level BEFORE 8:00 AND is still past it at 8:00
    #   → These are "gap-open" entries (stop fills immediately at market)
    # Category B: Price crossed level BEFORE 8:00 BUT returned to range by 8:00
    #   → Level was tested, price came back. Stop order placed at level, waits for re-cross
    # Category C: Price never crossed level before 8:00
    #   → Clean breakout during the window

    cat_a = trades[trades['pre_crossed'] & trades['enters_first_bar'] & ~trades['returned_to_range']]
    cat_b = trades[trades['pre_crossed'] & trades['returned_to_range']]
    cat_c = trades[~trades['pre_crossed']]
    # There could also be: pre-crossed, but entry happens on a later bar (price pulled back then re-broke)
    cat_d = trades[trades['pre_crossed'] & ~trades['enters_first_bar'] & ~trades['returned_to_range']]

    print(f"\n  Category A: Gap-open (crossed before 8:00, still past at 8:00, fills immediately)")
    sa = compute_stats(cat_a['pnl_usd'])
    print(f"    N={sa['n']:>4} ({sa['n']/len(trades)*100:.1f}%) | Mean ${sa['mean']:>+6.2f} | "
          f"Sharpe {sa['sharpe']:>5.2f} | WR {sa['wr']:.0f}% | Total ${sa['total']:>+8.2f}")

    print(f"\n  Category B: Returned (crossed before 8:00, but price came back to range by 8:00)")
    sb = compute_stats(cat_b['pnl_usd'])
    print(f"    N={sb['n']:>4} ({sb['n']/len(trades)*100:.1f}%) | Mean ${sb['mean']:>+6.2f} | "
          f"Sharpe {sb['sharpe']:>5.2f} | WR {sb['wr']:.0f}% | Total ${sb['total']:>+8.2f}")

    print(f"\n  Category C: Clean breakout (never crossed level before 8:00)")
    sc = compute_stats(cat_c['pnl_usd'])
    print(f"    N={sc['n']:>4} ({sc['n']/len(trades)*100:.1f}%) | Mean ${sc['mean']:>+6.2f} | "
          f"Sharpe {sc['sharpe']:>5.2f} | WR {sc['wr']:.0f}% | Total ${sc['total']:>+8.2f}")

    print(f"\n  Category D: Pre-crossed but entered on later bar (price pulled back, re-broke)")
    sd = compute_stats(cat_d['pnl_usd'])
    print(f"    N={sd['n']:>4} ({sd['n']/len(trades)*100:.1f}%) | Mean ${sd['mean']:>+6.2f} | "
          f"Sharpe {sd['sharpe']:>5.2f} | WR {sd['wr']:.0f}% | Total ${sd['total']:>+8.2f}")

    # ═══════════════════════════════════════════════════════════════════════════
    # ANALYSIS 2: For gap-open entries (Cat A), how far past the level is price?
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  2. GAP-OPEN DISTANCE: How far past the level is price at 8:00?")
    print("     (This is the extra slippage the backtest doesn't capture)")
    print("=" * 95)

    gap_entries = trades[trades['pre_crossed'] & trades['enters_first_bar']]
    if len(gap_entries) > 0:
        pg = gap_entries['price_gap']
        gp = gap_entries['gap_pct_of_range']

        print(f"\n  Price gap (absolute $):")
        print(f"    Mean: ${pg.mean():>+6.2f}")
        print(f"    Median: ${pg.median():>+6.2f}")
        print(f"    P25: ${pg.quantile(0.25):>+6.2f}")
        print(f"    P75: ${pg.quantile(0.75):>+6.2f}")
        print(f"    P90: ${pg.quantile(0.90):>+6.2f}")
        print(f"    Max: ${pg.max():>+6.2f}")

        print(f"\n  Price gap as % of range size:")
        print(f"    Mean: {gp.mean():>+6.1%}")
        print(f"    Median: {gp.median():>+6.1%}")
        print(f"    P75: {gp.quantile(0.75):>+6.1%}")
        print(f"    P90: {gp.quantile(0.90):>+6.1%}")

        # Distribution buckets
        print(f"\n  Distribution of gap distance (% of range):")
        bins = [(-999, 0), (0, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 999)]
        labels = ['<0 (inside range)', '0-10%', '10-25%', '25-50%', '50-100%', '>100%']
        for (lo, hi), label in zip(bins, labels):
            mask = (gp > lo) & (gp <= hi)
            subset = gap_entries[mask]
            if len(subset) >= 3:
                ss = compute_stats(subset['pnl_usd'])
                print(f"    {label:>18}: N={ss['n']:>4} | Mean ${ss['mean']:>+6.2f} | "
                      f"Sharpe {ss['sharpe']:>5.2f} | WR {ss['wr']:.0f}%")

    # ═══════════════════════════════════════════════════════════════════════════
    # ANALYSIS 3: What if we adjust entry price by the gap? (realistic fill)
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  3. REALISTIC FILL: What if gap-open entries fill at open price, not range level?")
    print("     (Simulates the live script's actual fill for pre-crossed trades)")
    print("=" * 95)

    # Recalculate P&L with realistic fill for gap-open trades
    realistic_pnl = trades.copy()
    gap_mask = trades['pre_crossed'] & trades['enters_first_bar']

    # For gap entries, the actual fill would be at open_at_8 (+ slip), not range level
    for idx in realistic_pnl[gap_mask].index:
        row = realistic_pnl.loc[idx]
        if row['direction'] == 'LONG':
            # Real entry would be at open_at_8 + slip (worse than range_high + slip)
            real_entry = row['open_at_8'] + SLIP
            ideal_entry = row['range_high'] + SLIP
            # P&L reduced by the gap
            extra_cost = real_entry - ideal_entry
        else:
            real_entry = row['open_at_8'] - SLIP
            ideal_entry = row['range_low'] - SLIP
            extra_cost = ideal_entry - real_entry

        realistic_pnl.loc[idx, 'pnl_usd'] = row['pnl_usd'] - max(0, extra_cost)

    s_ideal = compute_stats(trades['pnl_usd'])
    s_real = compute_stats(realistic_pnl['pnl_usd'])

    print(f"\n  Backtest (ideal fill at level):  Sharpe {s_ideal['sharpe']:>5.2f} | "
          f"Mean ${s_ideal['mean']:>+6.2f} | Total ${s_ideal['total']:>+9.2f}")
    print(f"  Realistic (gap fill at market):  Sharpe {s_real['sharpe']:>5.2f} | "
          f"Mean ${s_real['mean']:>+6.2f} | Total ${s_real['total']:>+9.2f}")
    print(f"  Difference:                      Sharpe {s_real['sharpe']-s_ideal['sharpe']:>+5.2f} | "
          f"Mean ${s_real['mean']-s_ideal['mean']:>+6.2f} | Total ${s_real['total']-s_ideal['total']:>+9.2f}")

    # With 60min time exit
    print(f"\n  (Note: above includes 60min time exit)")

    # ═══════════════════════════════════════════════════════════════════════════
    # ANALYSIS 4: What if we SKIP gap-open trades entirely?
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  4. FILTER: What if we only trade clean breakouts (skip gap-opens)?")
    print("=" * 95)

    clean = trades[~(trades['pre_crossed'] & trades['enters_first_bar'] & (trades['price_gap'] > 0))]
    s_clean = compute_stats(clean['pnl_usd'])
    print(f"\n  All trades:     N={s_ideal['n']:>4} | Sharpe {s_ideal['sharpe']:>5.2f} | Total ${s_ideal['total']:>+9.2f}")
    print(f"  Clean only:     N={s_clean['n']:>4} | Sharpe {s_clean['sharpe']:>5.2f} | Total ${s_clean['total']:>+9.2f}")
    print(f"  Skipped:        N={s_ideal['n']-s_clean['n']:>4}")

    # What about filtering by gap size?
    print(f"\n  Filtering by max gap (keep trades where gap < X% of range):")
    for max_gap_pct in [0.0, 0.10, 0.25, 0.50, 1.0, 999]:
        filtered = trades[trades['gap_pct_of_range'] <= max_gap_pct]
        if len(filtered) >= 10:
            sf = compute_stats(filtered['pnl_usd'])
            label = f"<={max_gap_pct*100:.0f}%" if max_gap_pct < 999 else "all"
            print(f"    Gap {label:>6}: N={sf['n']:>4} | Sharpe {sf['sharpe']:>5.2f} | "
                  f"Mean ${sf['mean']:>+6.2f} | Total ${sf['total']:>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════════
    # ANALYSIS 5: When exactly do gap crosses happen? (6-8 UTC timeline)
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  5. GAP TIMELINE: When do levels get crossed during 6-8 UTC?")
    print("=" * 95)

    # Analyze the 5-min bars in the 6-8 gap for days that have gap-open entries
    gap_days = trades[trades['pre_crossed']]['date'].unique()
    cross_times = []

    for day in gap_days:
        day_df_local = df[df['date'] == day]
        asian = day_df_local[(day_df_local['hour'] >= 0) & (day_df_local['hour'] < 6)]
        if len(asian) < 36:
            continue
        rh = asian['high'].max()
        rl = asian['low'].min()

        gap_bars = day_df_local[(day_df_local['hour'] >= 6) & (day_df_local['hour'] < 8)]
        for idx_bar, bar in gap_bars.iterrows():
            if bar['high'] >= rh or bar['low'] <= rl:
                cross_times.append({
                    'hour': idx_bar.hour,
                    'minute': idx_bar.minute,
                    'hhmm': f"{idx_bar.hour:02d}:{idx_bar.minute:02d}",
                })
                break  # first cross per day

    ct = pd.DataFrame(cross_times)
    if len(ct) > 0:
        print(f"\n  First level cross time distribution (for {len(ct)} days with gap crosses):")
        for h in [6, 7]:
            for m in range(0, 60, 5):
                mask = (ct['hour'] == h) & (ct['minute'] == m)
                n = mask.sum()
                if n > 0:
                    pct = n / len(ct) * 100
                    bar_chart = '#' * int(pct)
                    print(f"    {h:02d}:{m:02d}: {n:>4} ({pct:>5.1f}%) {bar_chart}")

    # ═══════════════════════════════════════════════════════════════════════════
    # ANALYSIS 6: Realistic vs ideal — OOS comparison
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  6. OOS COMPARISON: Ideal fill vs Realistic fill")
    print("=" * 95)

    oos_start = pd.Timestamp('2021-01-01').date()
    oos_ideal = trades[trades['date'] >= oos_start]
    oos_real = realistic_pnl[realistic_pnl['date'] >= oos_start]

    si = compute_stats(oos_ideal['pnl_usd'])
    sr = compute_stats(oos_real['pnl_usd'])
    print(f"\n  OOS (2021-2026):")
    print(f"    Ideal fill:    N={si['n']:>4} | Sharpe {si['sharpe']:>5.2f} | Total ${si['total']:>+9.2f}")
    print(f"    Realistic fill: N={sr['n']:>4} | Sharpe {sr['sharpe']:>5.2f} | Total ${sr['total']:>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════════
    # ANALYSIS 7: What if we DELAY entry to require pullback + re-cross?
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  7. ALTERNATIVE: What if gap-open trades wait for pullback + re-cross?")
    print("     (Skip the immediate fill, wait for price to touch range level again)")
    print("=" * 95)

    # For gap-open days, instead of entering on first bar, wait for price to
    # pull back to range_high/low and then re-cross
    pullback_results = []
    for _, row in trades[gap_mask].iterrows():
        day_data = df[df['date'] == row['date']]
        window_bars = day_data[(day_data['hour'] >= 8) & (day_data['hour'] < 16)]
        rh_local = row['range_high']
        rl_local = row['range_low']
        rs_local = row['range_size']

        if row['direction'] == 'LONG':
            # Wait for price to come back to range_high, then break above again
            touched_back = False
            entry_bar_new = None
            for i, (idx, bar) in enumerate(window_bars.iterrows()):
                if i == 0:
                    continue  # skip the gap-open bar
                if bar['low'] <= rh_local:
                    touched_back = True
                if touched_back and bar['high'] >= rh_local:
                    entry_bar_new = i
                    break
        else:
            touched_back = False
            entry_bar_new = None
            for i, (idx, bar) in enumerate(window_bars.iterrows()):
                if i == 0:
                    continue
                if bar['high'] >= rl_local:
                    touched_back = True
                if touched_back and bar['low'] <= rl_local:
                    entry_bar_new = i
                    break

        if entry_bar_new is not None:
            # Simulate trade from new entry point
            entry_px_new = (rh_local + SLIP) if row['direction'] == 'LONG' else (rl_local - SLIP)
            sl_px_new = rl_local if row['direction'] == 'LONG' else rh_local
            tp_px_new = (rh_local + RR * rs_local) if row['direction'] == 'LONG' else (rl_local - RR * rs_local)

            monitor_new = window_bars.iloc[entry_bar_new + 1:]
            result_new = 'EOD'
            exit_px_new = None

            for j, (idx, bar) in enumerate(monitor_new.iterrows()):
                if j >= TIME_EXIT_BARS:
                    exit_px_new = bar['open']
                    exit_px_new = exit_px_new - SLIP if row['direction'] == 'LONG' else exit_px_new + SLIP
                    result_new = 'TIME_EXIT'
                    break
                if row['direction'] == 'LONG':
                    if bar['low'] <= sl_px_new:
                        exit_px_new = sl_px_new - SLIP
                        result_new = 'SL'
                        break
                    if bar['high'] >= tp_px_new:
                        exit_px_new = tp_px_new
                        result_new = 'TP'
                        break
                else:
                    if bar['high'] >= sl_px_new:
                        exit_px_new = sl_px_new + SLIP
                        result_new = 'SL'
                        break
                    if bar['low'] <= tp_px_new:
                        exit_px_new = tp_px_new
                        result_new = 'TP'
                        break

            if exit_px_new is None:
                if len(monitor_new) > 0:
                    exit_px_new = monitor_new['close'].iloc[-1]
                    exit_px_new = exit_px_new - SLIP if row['direction'] == 'LONG' else exit_px_new + SLIP
                else:
                    exit_px_new = entry_px_new

            raw_pnl_new = (exit_px_new - entry_px_new) if row['direction'] == 'LONG' else (entry_px_new - exit_px_new)
            pnl_new = raw_pnl_new - SPREAD * 2
            pullback_results.append({'date': row['date'], 'pnl_usd': round(pnl_new, 2), 'result': result_new})

    if pullback_results:
        pb_df = pd.DataFrame(pullback_results)
        sp = compute_stats(pb_df['pnl_usd'])

        # Compare: original gap-open trades vs pullback re-entry vs skipping entirely
        gap_only = trades[gap_mask & (trades['price_gap'] > 0)]
        sg = compute_stats(gap_only['pnl_usd'])

        print(f"\n  Original gap-open trades:  N={sg['n']:>4} | Sharpe {sg['sharpe']:>5.2f} | Mean ${sg['mean']:>+6.2f}")
        print(f"  Pullback re-entry trades:  N={sp['n']:>4} | Sharpe {sp['sharpe']:>5.2f} | Mean ${sp['mean']:>+6.2f}")
        print(f"  (Trades with no pullback are skipped: {sg['n'] - sp['n']} trades lost)")

    print(f"\n{'='*95}")
    print("  DONE")
    print("=" * 95)


TIME_EXIT_BARS = 12  # module-level for pullback section


if __name__ == "__main__":
    main()
