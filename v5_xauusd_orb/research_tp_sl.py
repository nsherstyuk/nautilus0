"""
research_tp_sl.py -- Investigate optimal TP/SL parameters for ORB strategy.

Tests:
1. RR ratio sweep (1.0 to 5.0) with velocity filter
2. Velocity-conditioned RR (different RR for fast vs very-fast markets)
3. Range-size-conditioned RR (wider range → different RR?)
4. Partial TP / trailing stop concepts
5. Fixed $ TP/SL vs range-relative

All tests use: stop entry, no time exit, skip Wed, velocity filter (entry+3min, P50).
"""
from __future__ import annotations
import datetime as dt
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path

# Reuse data loader and stats from backtest_1m
from v5_xauusd_orb.backtest_1m import load_1m_bars, Trade, stats, print_stats

ROOT = Path(__file__).resolve().parents[1]
OOS_START = dt.date(2021, 1, 1)


def compute_velocity(day_df, entry_ts, lookback_minutes=3):
    """Compute average tick count over entry bar + lookback minutes before."""
    entry_bar_start = entry_ts
    window_start = entry_ts - pd.Timedelta(minutes=lookback_minutes)
    window = day_df[(day_df.index >= window_start) & (day_df.index <= entry_bar_start)]
    if len(window) == 0:
        return 0
    return window['tick_count'].mean()


def run_backtest_with_rr(df, rr_ratio, vel_thresh=0, vel_lookback=3):
    """Run backtest with given RR and optional velocity filter.
    Returns list of Trade-like dicts with extra fields."""
    trades = []
    skip_wd = [2]

    for day, day_df in df.groupby('date'):
        wd = day_df['weekday'].iloc[0]
        if wd >= 5 or wd in skip_wd:
            continue

        asian = day_df[(day_df['hour'] >= 0) & (day_df['hour'] < 6)]
        if len(asian) < 10:
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

        tp_long = rh + rr_ratio * rs
        tp_short = rl - rr_ratio * rs

        window = day_df[(day_df['hour'] >= 8) & (day_df['hour'] < 16)]
        if len(window) < 5:
            continue

        bars = list(window.iterrows())
        n = len(bars)

        # Stop entry
        for i in range(n):
            ts, bar = bars[i]
            hs = bar['avg_spread'] / 2

            direction = None
            entry_px = None

            if bar['high'] >= rh:
                direction = 'LONG'
                entry_px = (bar['open'] + hs) if bar['open'] >= rh else (rh + hs)
            elif bar['low'] <= rl:
                direction = 'SHORT'
                entry_px = (bar['open'] - hs) if bar['open'] <= rl else (rl - hs)

            if direction is None:
                continue

            # Velocity filter
            if vel_thresh > 0:
                vel = compute_velocity(day_df, ts, vel_lookback)
                if vel < vel_thresh:
                    break  # skip this day
            else:
                vel = compute_velocity(day_df, ts, vel_lookback)

            sl = rl if direction == 'LONG' else rh
            tp = tp_long if direction == 'LONG' else tp_short

            # Monitor
            exit_px = None
            exit_type = 'EOD'
            exit_ts = ts

            for j in range(i + 1, n):
                ts_j, bar_j = bars[j]
                hs_j = bar_j['avg_spread'] / 2

                if direction == 'LONG':
                    if bar_j['low'] <= sl:
                        exit_px = sl - hs_j
                        exit_type = 'SL'
                        exit_ts = ts_j
                        break
                    if bar_j['high'] >= tp:
                        exit_px = tp - hs_j
                        exit_type = 'TP'
                        exit_ts = ts_j
                        break
                else:
                    if bar_j['high'] >= sl:
                        exit_px = sl + hs_j
                        exit_type = 'SL'
                        exit_ts = ts_j
                        break
                    if bar_j['low'] <= tp:
                        exit_px = tp + hs_j
                        exit_type = 'TP'
                        exit_ts = ts_j
                        break

            if exit_px is None:
                last_ts, last_bar = bars[-1]
                hs_l = last_bar['avg_spread'] / 2
                exit_px = last_bar['close'] - hs_l if direction == 'LONG' else last_bar['close'] + hs_l
                exit_ts = last_ts

            pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)
            hold = (exit_ts - ts).total_seconds() / 60

            trades.append({
                'date': day,
                'direction': direction,
                'entry_price': entry_px,
                'exit_price': exit_px,
                'exit_type': exit_type,
                'pnl': round(pnl, 3),
                'hold_minutes': hold,
                'range_size': rs,
                'range_pct': rpct,
                'velocity': vel,
                'entry_tick_count': int(bar.get('tick_count', 0)),
            })
            break  # one trade per day

    return trades


def trades_stats(trades, label=''):
    """Compute stats from list of trade dicts."""
    if not trades:
        return {'label': label, 'n': 0, 'sharpe': 0, 'pf': 0, 'wr': 0,
                'mean': 0, 'total': 0, 'max_dd': 0}
    pnl = pd.Series([t['pnl'] for t in trades])
    n = len(pnl)
    mean = pnl.mean()
    std = pnl.std()
    sharpe = mean / std * np.sqrt(252) if std > 0 else 0
    wr = (pnl > 0).mean() * 100
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl < 0].sum())
    pf = gp / gl if gl > 0 else float('inf')
    eq = pnl.cumsum()
    dd = (eq - eq.cummax()).min()
    return {
        'label': label, 'n': n, 'sharpe': round(sharpe, 2),
        'pf': round(pf, 2), 'wr': round(wr, 1),
        'mean': round(mean, 3), 'total': round(pnl.sum(), 2),
        'max_dd': round(dd, 2),
    }


def main():
    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars\n")

    VEL_THRESH = 168  # P50 from research

    # ═══════════════════════════════════════════════════════════════════════
    # 1. RR RATIO SWEEP (with velocity filter)
    # ═══════════════════════════════════════════════════════════════════════
    print("=" * 110)
    print("  1. RR RATIO SWEEP (stop entry, no time exit, vel filter P50=168)")
    print("=" * 110)
    print(f"  {'RR':>5} | {'N':>5} | {'Sharpe':>7} | {'PF':>5} | {'WR':>5} | "
          f"{'Mean':>8} | {'Total':>10} | {'MaxDD':>9} | "
          f"{'OOS_N':>5} | {'OOS_Sh':>7} | {'OOS_$':>10}")
    print(f"  {'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*5}-+-"
          f"{'-'*8}-+-{'-'*10}-+-{'-'*9}-+-"
          f"{'-'*5}-+-{'-'*7}-+-{'-'*10}")

    rr_results = {}
    for rr in [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        trades = run_backtest_with_rr(df, rr, vel_thresh=VEL_THRESH)
        s = trades_stats(trades)
        oos = [t for t in trades if t['date'] >= OOS_START]
        so = trades_stats(oos)
        rr_results[rr] = (s, so)
        print(f"  {rr:>5.2f} | {s['n']:>5} | {s['sharpe']:>7.2f} | {s['pf']:>5.2f} | "
              f"{s['wr']:>4.1f}% | ${s['mean']:>+7.3f} | ${s['total']:>+9.2f} | "
              f"${s['max_dd']:>+8.2f} | "
              f"{so['n']:>5} | {so['sharpe']:>7.2f} | ${so['total']:>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 2. RR SWEEP WITHOUT VELOCITY FILTER (baseline)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  2. RR RATIO SWEEP (NO velocity filter - baseline)")
    print("=" * 110)
    print(f"  {'RR':>5} | {'N':>5} | {'Sharpe':>7} | {'PF':>5} | {'WR':>5} | "
          f"{'Total':>10} | {'OOS_N':>5} | {'OOS_Sh':>7} | {'OOS_$':>10}")

    for rr in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]:
        trades = run_backtest_with_rr(df, rr, vel_thresh=0)
        s = trades_stats(trades)
        oos = [t for t in trades if t['date'] >= OOS_START]
        so = trades_stats(oos)
        print(f"  {rr:>5.2f} | {s['n']:>5} | {s['sharpe']:>7.2f} | {s['pf']:>5.2f} | "
              f"{s['wr']:>4.1f}% | ${s['total']:>+9.2f} | "
              f"{so['n']:>5} | {so['sharpe']:>7.2f} | ${so['total']:>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 3. VELOCITY-CONDITIONED RR (different RR for different velocity bands)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  3. VELOCITY-CONDITIONED RR")
    print("     Test: Does optimal RR differ for fast vs very-fast markets?")
    print("=" * 110)

    # First, get all trades with RR=2.0 and velocity data
    all_trades_rr2 = run_backtest_with_rr(df, 2.0, vel_thresh=0)

    # Split by velocity quartiles
    vels = [t['velocity'] for t in all_trades_rr2 if t['velocity'] > 0]
    vel_p25 = np.percentile(vels, 25)
    vel_p50 = np.percentile(vels, 50)
    vel_p75 = np.percentile(vels, 75)
    print(f"\n  Velocity quartiles: P25={vel_p25:.0f}, P50={vel_p50:.0f}, P75={vel_p75:.0f}")

    # For each velocity band, sweep RR
    bands = [
        ('P50-P75 (medium-fast)', vel_p50, vel_p75),
        ('P75+ (very fast)', vel_p75, 99999),
    ]

    for band_name, vel_lo, vel_hi in bands:
        print(f"\n  --- {band_name} (vel {vel_lo:.0f}-{vel_hi:.0f}) ---")
        print(f"  {'RR':>5} | {'N':>5} | {'Sharpe':>7} | {'PF':>5} | {'WR':>5} | "
              f"{'Total':>10} | {'OOS_N':>5} | {'OOS_Sh':>7} | {'OOS_$':>10}")

        for rr in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]:
            trades = run_backtest_with_rr(df, rr, vel_thresh=0)
            band_trades = [t for t in trades
                           if vel_lo <= t['velocity'] < vel_hi]
            s = trades_stats(band_trades)
            oos = [t for t in band_trades if t['date'] >= OOS_START]
            so = trades_stats(oos)
            print(f"  {rr:>5.2f} | {s['n']:>5} | {s['sharpe']:>7.2f} | {s['pf']:>5.2f} | "
                  f"{s['wr']:>4.1f}% | ${s['total']:>+9.2f} | "
                  f"{so['n']:>5} | {so['sharpe']:>7.2f} | ${so['total']:>+9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 4. RANGE-SIZE-CONDITIONED RR
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  4. RANGE-SIZE-CONDITIONED RR")
    print("     Test: Does optimal RR differ for tight vs wide ranges?")
    print("=" * 110)

    # Split by range_size quartiles (filtered trades only)
    base_trades = run_backtest_with_rr(df, 2.0, vel_thresh=VEL_THRESH)
    range_sizes = [t['range_size'] for t in base_trades]
    rs_p25 = np.percentile(range_sizes, 25)
    rs_p50 = np.percentile(range_sizes, 50)
    rs_p75 = np.percentile(range_sizes, 75)
    print(f"\n  Range size quartiles: P25=${rs_p25:.2f}, P50=${rs_p50:.2f}, P75=${rs_p75:.2f}")

    range_bands = [
        ('Tight (P0-P50)', 0, rs_p50),
        ('Wide (P50-P100)', rs_p50, 99999),
    ]

    for band_name, rs_lo, rs_hi in range_bands:
        print(f"\n  --- {band_name} (range ${rs_lo:.2f}-${rs_hi:.2f}) ---")
        print(f"  {'RR':>5} | {'N':>5} | {'Sharpe':>7} | {'PF':>5} | {'WR':>5} | "
              f"{'Total':>10} | {'OOS_N':>5} | {'OOS_Sh':>7}")

        for rr in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]:
            trades = run_backtest_with_rr(df, rr, vel_thresh=VEL_THRESH)
            band_trades = [t for t in trades
                           if rs_lo <= t['range_size'] < rs_hi]
            s = trades_stats(band_trades)
            oos = [t for t in band_trades if t['date'] >= OOS_START]
            so = trades_stats(oos)
            print(f"  {rr:>5.2f} | {s['n']:>5} | {s['sharpe']:>7.2f} | {s['pf']:>5.2f} | "
                  f"{s['wr']:>4.1f}% | ${s['total']:>+9.2f} | "
                  f"{so['n']:>5} | {so['sharpe']:>7.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 5. EXIT TYPE BREAKDOWN BY RR
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  5. EXIT TYPE BREAKDOWN (vel filtered)")
    print("     How often do we hit TP vs SL vs EOD at each RR?")
    print("=" * 110)
    print(f"  {'RR':>5} | {'%TP':>5} | {'%SL':>5} | {'%EOD':>5} | "
          f"{'TP_avg':>8} | {'SL_avg':>8} | {'EOD_avg':>8}")

    for rr in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]:
        trades = run_backtest_with_rr(df, rr, vel_thresh=VEL_THRESH)
        n = len(trades)
        if n == 0:
            continue
        tp_t = [t for t in trades if t['exit_type'] == 'TP']
        sl_t = [t for t in trades if t['exit_type'] == 'SL']
        eod_t = [t for t in trades if t['exit_type'] == 'EOD']
        tp_pct = len(tp_t) / n * 100
        sl_pct = len(sl_t) / n * 100
        eod_pct = len(eod_t) / n * 100
        tp_avg = np.mean([t['pnl'] for t in tp_t]) if tp_t else 0
        sl_avg = np.mean([t['pnl'] for t in sl_t]) if sl_t else 0
        eod_avg = np.mean([t['pnl'] for t in eod_t]) if eod_t else 0
        print(f"  {rr:>5.2f} | {tp_pct:>4.1f}% | {sl_pct:>4.1f}% | {eod_pct:>4.1f}% | "
              f"${tp_avg:>+7.2f} | ${sl_avg:>+7.2f} | ${eod_avg:>+7.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 6. FIXED $ TP/SL (not range-relative)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  6. FIXED $ TARGETS (vel filtered)")
    print("     What if TP and SL are fixed dollar amounts instead of range-relative?")
    print("=" * 110)

    trades_base = run_backtest_with_rr(df, 2.0, vel_thresh=VEL_THRESH)
    # Get typical range_size for context
    avg_rs = np.mean([t['range_size'] for t in trades_base])
    med_rs = np.median([t['range_size'] for t in trades_base])
    print(f"  For context: avg range=${avg_rs:.2f}, median range=${med_rs:.2f}")
    print(f"  Current RR=2.0 means: SL~=${med_rs:.2f}, TP~=${2*med_rs:.2f}\n")

    print(f"  {'SL$':>5} | {'TP$':>5} | {'RR_eff':>6} | {'N':>5} | {'Sharpe':>7} | "
          f"{'PF':>5} | {'WR':>5} | {'Total':>10} | {'OOS_Sh':>7}")

    for sl_fixed, tp_fixed in [
        (5, 10), (5, 15), (5, 20),
        (8, 12), (8, 16), (8, 24),
        (10, 15), (10, 20), (10, 30),
        (12, 18), (12, 24), (12, 36),
        (15, 22), (15, 30), (15, 45),
    ]:
        trades = _run_fixed_targets(df, sl_fixed, tp_fixed, VEL_THRESH)
        if not trades:
            continue
        s = trades_stats(trades)
        oos = [t for t in trades if t['date'] >= OOS_START]
        so = trades_stats(oos)
        rr_eff = tp_fixed / sl_fixed
        print(f"  ${sl_fixed:>4} | ${tp_fixed:>4} | {rr_eff:>5.1f}x | {s['n']:>5} | "
              f"{s['sharpe']:>7.2f} | {s['pf']:>5.2f} | {s['wr']:>4.1f}% | "
              f"${s['total']:>+9.2f} | {so['sharpe']:>7.2f}")

    print(f"\n{'='*110}")
    print("  DONE")
    print("=" * 110)


def _run_fixed_targets(df, sl_dollars, tp_dollars, vel_thresh):
    """Backtest with fixed $ SL and TP instead of range-relative."""
    trades = []
    skip_wd = [2]

    for day, day_df in df.groupby('date'):
        wd = day_df['weekday'].iloc[0]
        if wd >= 5 or wd in skip_wd:
            continue

        asian = day_df[(day_df['hour'] >= 0) & (day_df['hour'] < 6)]
        if len(asian) < 10:
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

        window = day_df[(day_df['hour'] >= 8) & (day_df['hour'] < 16)]
        if len(window) < 5:
            continue

        bars = list(window.iterrows())
        n = len(bars)

        for i in range(n):
            ts, bar = bars[i]
            hs = bar['avg_spread'] / 2

            direction = None
            entry_px = None

            if bar['high'] >= rh:
                direction = 'LONG'
                entry_px = (bar['open'] + hs) if bar['open'] >= rh else (rh + hs)
            elif bar['low'] <= rl:
                direction = 'SHORT'
                entry_px = (bar['open'] - hs) if bar['open'] <= rl else (rl - hs)

            if direction is None:
                continue

            # Velocity filter
            if vel_thresh > 0:
                vel = compute_velocity(day_df, ts, 3)
                if vel < vel_thresh:
                    break

            # Fixed $ targets
            if direction == 'LONG':
                sl = entry_px - sl_dollars
                tp = entry_px + tp_dollars
            else:
                sl = entry_px + sl_dollars
                tp = entry_px - tp_dollars

            exit_px = None
            exit_type = 'EOD'

            for j in range(i + 1, n):
                ts_j, bar_j = bars[j]
                hs_j = bar_j['avg_spread'] / 2

                if direction == 'LONG':
                    if bar_j['low'] <= sl:
                        exit_px = sl - hs_j
                        exit_type = 'SL'
                        break
                    if bar_j['high'] >= tp:
                        exit_px = tp - hs_j
                        exit_type = 'TP'
                        break
                else:
                    if bar_j['high'] >= sl:
                        exit_px = sl + hs_j
                        exit_type = 'SL'
                        break
                    if bar_j['low'] <= tp:
                        exit_px = tp + hs_j
                        exit_type = 'TP'
                        break

            if exit_px is None:
                last_ts, last_bar = bars[-1]
                hs_l = last_bar['avg_spread'] / 2
                exit_px = last_bar['close'] - hs_l if direction == 'LONG' else last_bar['close'] + hs_l

            pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)

            trades.append({
                'date': day,
                'direction': direction,
                'pnl': round(pnl, 3),
                'exit_type': exit_type,
                'range_size': rs,
                'velocity': vel if vel_thresh > 0 else 0,
            })
            break

    return trades


if __name__ == "__main__":
    main()
