"""
research_poc_walkforward.py -- Walk-forward validation of POC misalignment filter.

This is the critical validation step. POC misalignment (breakouts against the Asian
session's volume-weighted consensus) is the only cross-instrument signal found.

Tests:
  1. Walk-forward POC misalignment on XAUUSD (train 3yr, test 1yr)
  2. Walk-forward POC misalignment on EURUSD
  3. Combined Cat B + POC misalignment (orthogonality test) on XAUUSD
  4. Combined Cat B + POC misalignment on EURUSD
  5. Annual breakdown of the combined filter
  6. Trade count analysis (can we sustain 2-3/week?)

Usage:
  python -m v5_xauusd_orb.research_poc_walkforward
"""
from __future__ import annotations
import datetime as dt
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OOS_START = dt.date(2021, 1, 1)


# ── Data Loading ────────────────────────────────────────────────────────

def load_1m_bars(path):
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    return df


# ── Backtest ────────────────────────────────────────────────────────────

def run_backtest(df):
    trades = []
    for day, day_df in df.groupby('date'):
        wd = day_df['weekday'].iloc[0]
        if wd >= 5 or wd == 2:
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
        tp_long = rh + 2.0 * rs
        tp_short = rl - 2.0 * rs

        window = day_df[(day_df['hour'] >= 8) & (day_df['hour'] < 16)]
        if len(window) < 5:
            continue

        direction = None
        entry_idx = None
        entry_px = None
        for i, (ts, bar) in enumerate(window.iterrows()):
            hs = bar['avg_spread'] / 2
            if bar['high'] >= rh:
                direction = 'LONG'
                entry_idx = i
                entry_px = (bar['open'] + hs) if bar['open'] >= rh else (rh + hs)
                break
            elif bar['low'] <= rl:
                direction = 'SHORT'
                entry_idx = i
                entry_px = (bar['open'] - hs) if bar['open'] <= rl else (rl - hs)
                break
        if direction is None:
            continue

        sl = rl if direction == 'LONG' else rh
        tp = tp_long if direction == 'LONG' else tp_short
        exit_px = None
        exit_type = 'EOD'
        monitor = window.iloc[entry_idx + 1:]
        for ts, bar in monitor.iterrows():
            hs = bar['avg_spread'] / 2
            if direction == 'LONG':
                if bar['low'] <= sl:
                    exit_px = sl - hs; exit_type = 'SL'; break
                if bar['high'] >= tp:
                    exit_px = tp - hs; exit_type = 'TP'; break
            else:
                if bar['high'] >= sl:
                    exit_px = sl + hs; exit_type = 'SL'; break
                if bar['low'] <= tp:
                    exit_px = tp + hs; exit_type = 'TP'; break
        if exit_px is None:
            last_bar = window.iloc[-1]
            hs = last_bar['avg_spread'] / 2
            exit_px = last_bar['close'] - hs if direction == 'LONG' else last_bar['close'] + hs

        pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)
        trades.append({
            'date': day, 'direction': direction, 'pnl': pnl,
            'range_high': rh, 'range_low': rl, 'range_size': rs,
            'exit_type': exit_type,
        })
    return trades


# ── Feature computation ─────────────────────────────────────────────────

def enrich_trades(df, trades):
    by_date = {d: g for d, g in df.groupby('date')}

    for t in trades:
        day_df = by_date.get(t['date'])
        if day_df is None:
            t['poc_position'] = 0.5
            t['vwap_position'] = 0.5
            t['category'] = 'C'
            continue

        asian = day_df[(day_df['hour'] >= 0) & (day_df['hour'] < 6)]
        rh, rl, rs = t['range_high'], t['range_low'], t['range_size']

        # POC
        if 'total_volume' in asian.columns and len(asian) >= 10 and asian['total_volume'].sum() > 0:
            bin_size = rs / 20
            if bin_size > 0:
                bins = np.arange(rl, rh + bin_size, bin_size)
                if len(bins) >= 2:
                    typical = (asian['high'] + asian['low'] + asian['close']) / 3
                    vol = asian['total_volume'].values
                    bi = np.clip(np.digitize(typical.values, bins) - 1, 0, len(bins) - 2)
                    bv = np.zeros(len(bins) - 1)
                    for idx, v in zip(bi, vol):
                        bv[idx] += v
                    poc_bin = np.argmax(bv)
                    poc_price = (bins[poc_bin] + bins[poc_bin + 1]) / 2
                    t['poc_position'] = (poc_price - rl) / rs
                else:
                    t['poc_position'] = 0.5
            else:
                t['poc_position'] = 0.5
        else:
            t['poc_position'] = 0.5

        # VWAP
        if 'total_volume' in asian.columns and len(asian) >= 10 and asian['total_volume'].sum() > 0:
            typical = (asian['high'] + asian['low'] + asian['close']) / 3
            vol = asian['total_volume']
            vwap = (typical * vol).sum() / vol.sum()
            t['vwap_position'] = (vwap - rl) / rs if rs > 0 else 0.5
        else:
            t['vwap_position'] = 0.5

        # Category B (gap-returned)
        gap_bars = day_df[(day_df['hour'] >= 6) & (day_df['hour'] < 8)]
        direction = t['direction']
        crossed = False
        for _, bar in gap_bars.iterrows():
            if direction == 'LONG' and bar['high'] >= rh:
                crossed = True; break
            if direction == 'SHORT' and bar['low'] <= rl:
                crossed = True; break

        if not crossed:
            t['category'] = 'C'
        else:
            window_start = day_df[(day_df['hour'] == 8) & (day_df['minute'] == 0)]
            if len(window_start) > 0:
                open_at_8 = window_start.iloc[0]['open']
            else:
                w = day_df[day_df['hour'] >= 8]
                open_at_8 = w.iloc[0]['open'] if len(w) > 0 else (rh + rl) / 2

            if direction == 'LONG':
                t['category'] = 'A' if open_at_8 >= rh else 'B'
            else:
                t['category'] = 'A' if open_at_8 <= rl else 'B'

    # POC alignment
    for t in trades:
        poc = t['poc_position']
        if t['direction'] == 'LONG':
            t['poc_aligned'] = poc > 0.5
        else:
            t['poc_aligned'] = poc < 0.5
        t['poc_misaligned'] = not t['poc_aligned']

    return trades


# ── Stats ───────────────────────────────────────────────────────────────

def calc_stats(trades):
    if not trades:
        return {'n': 0, 'sharpe': 0, 'pf': 0, 'wr': 0, 'mean': 0, 'total': 0, 'max_dd': 0}
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
    return {'n': n, 'sharpe': round(sharpe, 2), 'pf': round(pf, 2),
            'wr': round(wr, 1), 'mean': mean, 'total': pnl.sum(), 'max_dd': dd}


# ── Main ────────────────────────────────────────────────────────────────

def run_instrument(name, filepath):
    print(f"\n{'#'*110}")
    print(f"  INSTRUMENT: {name}")
    print(f"{'#'*110}")

    df = load_1m_bars(filepath)
    print(f"Loaded {len(df):,} bars ({df.index.min().date()} to {df.index.max().date()})")

    trades = run_backtest(df)
    trades = enrich_trades(df, trades)
    print(f"Trades: {len(trades)}")

    s_all = calc_stats(trades)
    s_oos = calc_stats([t for t in trades if t['date'] >= OOS_START])
    print(f"  Baseline ALL: N={s_all['n']} Sh={s_all['sharpe']} PF={s_all['pf']} WR={s_all['wr']}%")
    print(f"  Baseline OOS: N={s_oos['n']} Sh={s_oos['sharpe']} PF={s_oos['pf']} WR={s_oos['wr']}%")

    by_year = {}
    for t in trades:
        yr = t['date'].year
        by_year.setdefault(yr, []).append(t)
    years = sorted(by_year.keys())

    # ═══════════════════════════════════════════════════════════════════
    # TEST 1: Walk-forward POC misalignment
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print(f"  TEST 1: WALK-FORWARD -- POC Misalignment Filter ({name})")
    print(f"  Note: POC misalignment has NO trainable parameter. Walk-forward tests stability.")
    print("=" * 110)

    print(f"\n  {'Year':>6} | {'N_all':>6} | {'N_mis':>6} | {'N_al':>5} | "
          f"{'Sh_all':>7} | {'Sh_mis':>7} | {'Sh_al':>7} | "
          f"{'WR_all':>6} | {'WR_mis':>6} | {'WR_al':>6} | {'Better?':>8}")
    print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*5}-+-"
          f"{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-"
          f"{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*8}")

    helps = 0
    total_yrs = 0

    for yr in years:
        yr_trades = by_year[yr]
        if len(yr_trades) < 15:
            continue
        total_yrs += 1

        mis = [t for t in yr_trades if t['poc_misaligned']]
        al = [t for t in yr_trades if t['poc_aligned']]

        sa = calc_stats(yr_trades)
        sm = calc_stats(mis)
        sal = calc_stats(al)

        better = sm['sharpe'] > sa['sharpe']
        if better:
            helps += 1

        print(f"  {yr:>6} | {sa['n']:>6} | {sm['n']:>6} | {sal['n']:>5} | "
              f"{sa['sharpe']:>7.2f} | {sm['sharpe']:>7.2f} | {sal['sharpe']:>7.2f} | "
              f"{sa['wr']:>5.1f}% | {sm['wr']:>5.1f}% | {sal['wr']:>5.1f}% | "
              f"{'YES' if better else 'no':>8}")

    print(f"\n  Misaligned filter better in {helps}/{total_yrs} years ({helps/max(total_yrs,1)*100:.0f}%)")

    # ═══════════════════════════════════════════════════════════════════
    # TEST 2: Walk-forward Cat B + POC combined
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print(f"  TEST 2: WALK-FORWARD -- Cat B removal + POC Misalignment ({name})")
    print(f"  Combined filter: keep trades that are (A or C) AND POC-misaligned")
    print("=" * 110)

    print(f"\n  {'Year':>6} | {'N_all':>6} | {'N_comb':>6} | {'N_rej':>5} | "
          f"{'Sh_all':>7} | {'Sh_comb':>7} | {'Sh_rej':>7} | "
          f"{'WR_all':>6} | {'WR_comb':>6} | {'Better?':>8}")
    print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*5}-+-"
          f"{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-"
          f"{'-'*6}-+-{'-'*6}-+-{'-'*8}")

    combo_helps = 0
    combo_total = 0

    for yr in years:
        yr_trades = by_year[yr]
        if len(yr_trades) < 15:
            continue
        combo_total += 1

        combo = [t for t in yr_trades if t['category'] != 'B' and t['poc_misaligned']]
        rejected = [t for t in yr_trades if not (t['category'] != 'B' and t['poc_misaligned'])]

        sa = calc_stats(yr_trades)
        sc = calc_stats(combo)
        sr = calc_stats(rejected)

        better = sc['sharpe'] > sa['sharpe']
        if better:
            combo_helps += 1

        print(f"  {yr:>6} | {sa['n']:>6} | {sc['n']:>6} | {len(rejected):>5} | "
              f"{sa['sharpe']:>7.2f} | {sc['sharpe']:>7.2f} | {sr['sharpe']:>7.2f} | "
              f"{sa['wr']:>5.1f}% | {sc['wr']:>5.1f}% | "
              f"{'YES' if better else 'no':>8}")

    print(f"\n  Combined filter better in {combo_helps}/{combo_total} years ({combo_helps/max(combo_total,1)*100:.0f}%)")

    # ═══════════════════════════════════════════════════════════════════
    # TEST 3: Orthogonality — are Cat B and POC independent?
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print(f"  TEST 3: ORTHOGONALITY -- Cat B vs POC ({name})")
    print("=" * 110)

    groups = {
        'A/C + Misaligned': [t for t in trades if t['category'] != 'B' and t['poc_misaligned']],
        'A/C + Aligned':    [t for t in trades if t['category'] != 'B' and t['poc_aligned']],
        'B + Misaligned':   [t for t in trades if t['category'] == 'B' and t['poc_misaligned']],
        'B + Aligned':      [t for t in trades if t['category'] == 'B' and t['poc_aligned']],
    }

    for label, group in groups.items():
        s = calc_stats(group)
        oos = calc_stats([t for t in group if t['date'] >= OOS_START])
        print(f"  {label:>25}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | WR {s['wr']:>5.1f}% | "
              f"PF {s['pf']:>5.2f} | OOS Sh {oos['sharpe']:>6.2f} OOS N={oos['n']:>4}")

    # ═══════════════════════════════════════════════════════════════════
    # TEST 4: Trade count sustainability
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print(f"  TEST 4: TRADE COUNT ANALYSIS ({name})")
    print("=" * 110)

    for filter_name, filter_fn in [
        ('Baseline (all)', lambda t: True),
        ('POC misaligned only', lambda t: t['poc_misaligned']),
        ('No Cat B', lambda t: t['category'] != 'B'),
        ('No Cat B + POC mis', lambda t: t['category'] != 'B' and t['poc_misaligned']),
    ]:
        filtered = [t for t in trades if filter_fn(t)]
        s = calc_stats(filtered)
        oos = [t for t in filtered if t['date'] >= OOS_START]
        so = calc_stats(oos)

        # Trades per week (approximate: 52 weeks/year, count years with data)
        if filtered:
            first_date = min(t['date'] for t in filtered)
            last_date = max(t['date'] for t in filtered)
            weeks = (last_date - first_date).days / 7
            tpw = len(filtered) / weeks if weeks > 0 else 0
        else:
            tpw = 0

        print(f"  {filter_name:>25}: N={s['n']:>5} ({tpw:.1f}/wk) | "
              f"Sh {s['sharpe']:>6.2f} | WR {s['wr']:>5.1f}% | PF {s['pf']:>5.2f} | "
              f"OOS Sh {so['sharpe']:>6.2f}")

    return trades


def main():
    xau_file = ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv'
    eur_file = ROOT / 'data' / '1m_csv' / 'eurusd_1m_tick.csv'

    xau_trades = run_instrument('XAUUSD', xau_file)
    eur_trades = run_instrument('EURUSD', eur_file)

    # ═══════════════════════════════════════════════════════════════════
    # PORTFOLIO: Combined both instruments
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'#'*110}")
    print(f"  PORTFOLIO: XAUUSD + EURUSD Combined")
    print(f"{'#'*110}")

    for filter_name, filter_fn in [
        ('Baseline (all)', lambda t: True),
        ('POC misaligned only', lambda t: t['poc_misaligned']),
        ('No Cat B + POC mis', lambda t: t['category'] != 'B' and t['poc_misaligned']),
    ]:
        xau_f = [t for t in xau_trades if filter_fn(t)]
        eur_f = [t for t in eur_trades if filter_fn(t)]

        # Combine P&L series by date for portfolio stats
        all_f = xau_f + eur_f
        s = calc_stats(all_f)
        oos = calc_stats([t for t in all_f if t['date'] >= OOS_START])

        if all_f:
            first_date = min(t['date'] for t in all_f)
            last_date = max(t['date'] for t in all_f)
            weeks = (last_date - first_date).days / 7
            tpw = len(all_f) / weeks if weeks > 0 else 0
        else:
            tpw = 0

        print(f"  {filter_name:>25}: N={s['n']:>5} ({tpw:.1f}/wk) | "
              f"Sh {s['sharpe']:>6.2f} | WR {s['wr']:>5.1f}% | PF {s['pf']:>5.2f} | "
              f"OOS Sh {oos['sharpe']:>6.2f}")

    print(f"\n{'='*110}")
    print("  DONE")
    print("=" * 110)


if __name__ == "__main__":
    main()
