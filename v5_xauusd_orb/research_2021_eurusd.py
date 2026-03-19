"""
research_2021_eurusd.py -- Same regime investigation but for EURUSD.
Does POC misalignment show the same regime-dependence on FX?

Usage:
  python -m v5_xauusd_orb.research_2021_eurusd
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_1m_bars(path):
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    return df


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
            'exit_type': exit_type, 'entry_px': entry_px, 'exit_px': exit_px,
        })
    return trades


def enrich_trades(df, trades):
    by_date = {d: g for d, g in df.groupby('date')}
    for t in trades:
        day_df = by_date.get(t['date'])
        if day_df is None:
            t['poc_position'] = 0.5
            t['category'] = 'C'
            continue

        asian = day_df[(day_df['hour'] >= 0) & (day_df['hour'] < 6)]
        rh, rl, rs = t['range_high'], t['range_low'], t['range_size']

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

        # Category B
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

        t['price_level'] = (rh + rl) / 2

    for t in trades:
        poc = t['poc_position']
        if t['direction'] == 'LONG':
            t['poc_aligned'] = poc > 0.5
        else:
            t['poc_aligned'] = poc < 0.5
        t['poc_misaligned'] = not t['poc_aligned']

    return trades


def calc_stats(trades):
    if not trades:
        return {'n': 0, 'sharpe': 0, 'pf': 0, 'wr': 0, 'mean': 0, 'total': 0, 'max_dd': 0,
                'sl_pct': 0, 'tp_pct': 0, 'eod_pct': 0}
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
    exits = [t['exit_type'] for t in trades]
    sl_pct = sum(1 for e in exits if e == 'SL') / n * 100
    tp_pct = sum(1 for e in exits if e == 'TP') / n * 100
    eod_pct = sum(1 for e in exits if e == 'EOD') / n * 100
    return {'n': n, 'sharpe': round(sharpe, 2), 'pf': round(pf, 2),
            'wr': round(wr, 1), 'mean': mean, 'total': pnl.sum(), 'max_dd': dd,
            'sl_pct': round(sl_pct, 1), 'tp_pct': round(tp_pct, 1), 'eod_pct': round(eod_pct, 1)}


def print_header(text):
    print(f"\n{'='*110}")
    print(f"  {text}")
    print('='*110)


def main():
    filepath = ROOT / 'data' / '1m_csv' / 'eurusd_1m_tick.csv'
    print("Loading EURUSD 1-min data...")
    df = load_1m_bars(filepath)
    print(f"Loaded {len(df):,} bars ({df.index.min().date()} to {df.index.max().date()})")

    trades = run_backtest(df)
    trades = enrich_trades(df, trades)
    print(f"Total trades: {len(trades)}")

    by_year = defaultdict(list)
    for t in trades:
        by_year[t['date'].year].append(t)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 1: Direction x Alignment x Regime — THE KEY TABLE
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 1: DIRECTION BIAS x ALIGNMENT BY YEAR (EURUSD)")
    print("  Compare with XAUUSD: does regime-dependence exist here?\n")

    print(f"  {'Year':>6} | {'%LONG':>6} | {'L_mis_Sh':>8} | {'L_al_Sh':>8} | "
          f"{'S_mis_Sh':>8} | {'S_al_Sh':>8} | {'Regime':>16}")
    print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*8}-+-{'-'*8}-+-"
          f"{'-'*8}-+-{'-'*8}-+-{'-'*16}")

    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        if len(yt) < 20:
            continue
        long_pct = sum(1 for t in yt if t['direction'] == 'LONG') / len(yt) * 100
        l_mis = calc_stats([t for t in yt if t['direction'] == 'LONG' and t['poc_misaligned']])
        l_al = calc_stats([t for t in yt if t['direction'] == 'LONG' and t['poc_aligned']])
        s_mis = calc_stats([t for t in yt if t['direction'] == 'SHORT' and t['poc_misaligned']])
        s_al = calc_stats([t for t in yt if t['direction'] == 'SHORT' and t['poc_aligned']])

        prices = [t['price_level'] for t in yt]
        pchange = (prices[-1] - prices[0]) / prices[0] * 100
        regime = "UP" if pchange > 3 else "DOWN" if pchange < -3 else "FLAT"

        print(f"  {yr:>6} | {long_pct:>5.1f}% | {l_mis['sharpe']:>8.2f} | {l_al['sharpe']:>8.2f} | "
              f"{s_mis['sharpe']:>8.2f} | {s_al['sharpe']:>8.2f} | {regime:>8} ({pchange:+.1f}%)")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 2: Annual walk-forward (same as XAUUSD investigation)
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 2: ANNUAL WALK-FORWARD -- POC Misalignment (EURUSD)")

    print(f"\n  {'Year':>6} | {'N_all':>5} | {'N_mis':>5} | {'N_al':>4} | "
          f"{'Sh_all':>7} | {'Sh_mis':>7} | {'Sh_al':>7} | "
          f"{'WR_mis':>6} | {'WR_al':>6} | Better?")
    print(f"  {'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*4}-+-"
          f"{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-"
          f"{'-'*6}-+-{'-'*6}-+-{'-'*8}")

    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        if len(yt) < 15:
            continue
        mis = [t for t in yt if t['poc_misaligned']]
        al = [t for t in yt if t['poc_aligned']]
        sa = calc_stats(yt)
        sm = calc_stats(mis)
        sal = calc_stats(al)
        better = sm['sharpe'] > sa['sharpe']
        print(f"  {yr:>6} | {sa['n']:>5} | {sm['n']:>5} | {len(al):>4} | "
              f"{sa['sharpe']:>7.2f} | {sm['sharpe']:>7.2f} | {sal['sharpe']:>7.2f} | "
              f"{sm['wr']:>5.1f}% | {sal['wr']:>5.1f}% | "
              f"{'YES' if better else 'no':>8}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 3: Exit type breakdown — misaligned by year
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 3: EXIT TYPE BREAKDOWN -- Misaligned trades by year (EURUSD)")

    print(f"  {'Year':>6} | {'N':>4} | {'SL%':>6} | {'TP%':>6} | {'EOD%':>6} | "
          f"{'WR':>5} | {'Sharpe':>7} | {'Mean PnL':>10}")
    print(f"  {'-'*6}-+-{'-'*4}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-"
          f"{'-'*5}-+-{'-'*7}-+-{'-'*10}")

    for yr in sorted(by_year.keys()):
        mis = [t for t in by_year[yr] if t['poc_misaligned']]
        if len(mis) < 10:
            continue
        s = calc_stats(mis)
        print(f"  {yr:>6} | {s['n']:>4} | {s['sl_pct']:>5.1f}% | {s['tp_pct']:>5.1f}% | "
              f"{s['eod_pct']:>5.1f}% | {s['wr']:>4.1f}% | {s['sharpe']:>7.2f} | "
              f"{s['mean']:>10.6f}")

    print(f"\n  Aligned trades for comparison:")
    print(f"  {'Year':>6} | {'N':>4} | {'SL%':>6} | {'TP%':>6} | {'EOD%':>6} | "
          f"{'WR':>5} | {'Sharpe':>7} | {'Mean PnL':>10}")
    print(f"  {'-'*6}-+-{'-'*4}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-"
          f"{'-'*5}-+-{'-'*7}-+-{'-'*10}")

    for yr in sorted(by_year.keys()):
        al = [t for t in by_year[yr] if t['poc_aligned']]
        if len(al) < 10:
            continue
        s = calc_stats(al)
        print(f"  {yr:>6} | {s['n']:>4} | {s['sl_pct']:>5.1f}% | {s['tp_pct']:>5.1f}% | "
              f"{s['eod_pct']:>5.1f}% | {s['wr']:>4.1f}% | {s['sharpe']:>7.2f} | "
              f"{s['mean']:>10.6f}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 4: Range characteristics by year
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 4: RANGE CHARACTERISTICS BY YEAR (EURUSD)")

    print(f"  {'Year':>6} | {'N':>4} | {'Median RS':>10} | {'Mean RS':>10} | "
          f"{'POC mean':>8} | {'POC std':>8} | {'Price':>8}")
    print(f"  {'-'*6}-+-{'-'*4}-+-{'-'*10}-+-{'-'*10}-+-"
          f"{'-'*8}-+-{'-'*8}-+-{'-'*8}")

    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        if len(yt) < 10:
            continue
        rs_vals = [t['range_size'] for t in yt]
        poc_vals = [t['poc_position'] for t in yt]
        price_vals = [t['price_level'] for t in yt]
        print(f"  {yr:>6} | {len(yt):>4} | {np.median(rs_vals):>10.5f} | {np.mean(rs_vals):>10.5f} | "
              f"{np.mean(poc_vals):>8.3f} | {np.std(poc_vals):>8.3f} | "
              f"{np.mean(price_vals):>8.4f}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 5: Price regime
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 5: EURUSD PRICE REGIME BY YEAR")

    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        if len(yt) < 10:
            continue
        prices = [t['price_level'] for t in yt]
        first_price = prices[0]
        last_price = prices[-1]
        pchange = (last_price - first_price) / first_price * 100
        long_count = sum(1 for t in yt if t['direction'] == 'LONG')
        short_count = sum(1 for t in yt if t['direction'] == 'SHORT')
        sa = calc_stats(yt)
        print(f"  {yr}: {first_price:.4f} -> {last_price:.4f} ({pchange:+.1f}%) "
              f"  L/S={long_count}/{short_count} "
              f"  Baseline Sh={sa['sharpe']:>5.2f}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 6: Monthly breakdown for failure years (2019, 2025)
    # ══════════════════════════════════════════════════════════════════════
    # Find which years misalignment DIDN'T help
    print_header("SECTION 6: MONTHLY BREAKDOWN -- Years where misalignment FAILED (EURUSD)")

    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        if len(yt) < 15:
            continue
        sm = calc_stats([t for t in yt if t['poc_misaligned']])
        sa = calc_stats(yt)
        if sm['sharpe'] <= sa['sharpe']:
            print(f"\n  --- {yr} (misaligned Sh={sm['sharpe']:.2f} vs baseline Sh={sa['sharpe']:.2f}) ---")
            print(f"  {'Month':>7} | {'N_mis':>5} | {'N_al':>4} | {'Sh_mis':>7} | {'Sh_al':>7} | "
                  f"{'WR_mis':>6} | {'WR_al':>6} | {'PnL_mis':>10} | {'PnL_al':>10}")
            for month in range(1, 13):
                mt = [t for t in yt if t['date'].month == month]
                if not mt:
                    continue
                mis = [t for t in mt if t['poc_misaligned']]
                al = [t for t in mt if t['poc_aligned']]
                smm = calc_stats(mis)
                sal = calc_stats(al)
                print(f"  {month:>4}-{yr%100:02d} | {smm['n']:>5} | {len(al):>4} | "
                      f"{smm['sharpe']:>7.2f} | {sal['sharpe']:>7.2f} | "
                      f"{smm['wr']:>5.1f}% | {sal['wr']:>5.1f}% | "
                      f"{smm['total']:>10.6f} | {sal['total']:>10.6f}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 7: Side-by-side XAUUSD vs EURUSD regime comparison
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 7: MISALIGNED SHARPE COMPARISON -- XAUUSD vs EURUSD by year")
    print("  (XAUUSD numbers from prior investigation for reference)\n")

    # XAUUSD misaligned Sharpes from the session journal
    xau_mis = {2018: -0.52, 2019: -2.17, 2020: 2.98, 2021: -2.86,
               2022: 1.17, 2023: 3.18, 2024: 2.90, 2025: 3.38}

    print(f"  {'Year':>6} | {'XAU_mis':>8} | {'EUR_mis':>8} | {'Same dir?':>10} | XAU regime  | EUR regime")
    print(f"  {'-'*6}-+-{'-'*8}-+-{'-'*8}-+-{'-'*10}-+-{'-'*12}-+-{'-'*12}")

    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        if len(yt) < 15:
            continue
        sm = calc_stats([t for t in yt if t['poc_misaligned']])
        xau_sh = xau_mis.get(yr, None)
        if xau_sh is None:
            continue
        same = "YES" if (xau_sh > 0) == (sm['sharpe'] > 0) else "NO"

        eur_prices = [t['price_level'] for t in yt]
        eur_chg = (eur_prices[-1] - eur_prices[0]) / eur_prices[0] * 100

        # Rough XAUUSD regimes from prior investigation
        xau_regimes = {2018: "FLAT -2%", 2019: "UP +18%", 2020: "UP +25%", 2021: "DOWN -5%",
                       2022: "FLAT -1%", 2023: "UP +13%", 2024: "UP +26%", 2025: "UP +66%"}

        eur_regime = f"{'UP' if eur_chg > 3 else 'DOWN' if eur_chg < -3 else 'FLAT'} {eur_chg:+.0f}%"

        print(f"  {yr:>6} | {xau_sh:>8.2f} | {sm['sharpe']:>8.2f} | {same:>10} | "
              f"{xau_regimes.get(yr, '?'):>12} | {eur_regime:>12}")

    print(f"\n{'='*110}")
    print("  INVESTIGATION COMPLETE")
    print('='*110)


if __name__ == "__main__":
    main()
