"""
research_2021_investigation.py -- Investigate why POC misalignment failed on XAUUSD in 2021.

The POC misalignment filter produced Sharpe -2.86 in 2021 (vs baseline 0.31).
This was catastrophic and XAUUSD-specific (EURUSD was fine: +1.02).

Investigation axes:
  1. Monthly breakdown — where did losses concentrate?
  2. Direction breakdown — LONG misaligned vs SHORT misaligned
  3. Range characteristics — size, POC distribution, volatility
  4. Exit type breakdown — SL/TP/EOD patterns
  5. Gold price regime — trending vs ranging
  6. Comparison with adjacent years (2020, 2022) that worked

Usage:
  python -m v5_xauusd_orb.research_2021_investigation
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

        # Intra-range volatility
        returns = asian['close'].pct_change().dropna()
        range_pct = rs / ((rh + rl) / 2)
        if len(returns) > 5 and range_pct > 0:
            t['intra_vol'] = returns.std() / range_pct
        else:
            t['intra_vol'] = np.nan

        # Asian session volume
        if 'total_volume' in asian.columns:
            t['asian_volume'] = asian['total_volume'].sum()
        else:
            t['asian_volume'] = np.nan

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

        # Gold price level (mid of range as proxy)
        t['price_level'] = (rh + rl) / 2

    # POC alignment
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
    filepath = ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv'
    print("Loading XAUUSD 1-min data...")
    df = load_1m_bars(filepath)
    print(f"Loaded {len(df):,} bars ({df.index.min().date()} to {df.index.max().date()})")

    trades = run_backtest(df)
    trades = enrich_trades(df, trades)
    print(f"Total trades: {len(trades)}")

    # Split by year
    by_year = defaultdict(list)
    for t in trades:
        by_year[t['date'].year].append(t)

    focus_years = [2020, 2021, 2022]  # before, failure, after

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 1: Monthly breakdown of 2021
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 1: MONTHLY BREAKDOWN — 2021 XAUUSD")
    print("  Where exactly did the misaligned losses concentrate?\n")

    print(f"  {'Month':>7} | {'N_all':>5} | {'N_mis':>5} | {'N_al':>4} | "
          f"{'Sh_all':>7} | {'Sh_mis':>7} | {'Sh_al':>7} | "
          f"{'WR_mis':>6} | {'WR_al':>6} | "
          f"{'PnL_mis':>10} | {'PnL_al':>10}")
    print(f"  {'-'*7}-+-{'-'*5}-+-{'-'*5}-+-{'-'*4}-+-"
          f"{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-"
          f"{'-'*6}-+-{'-'*6}-+-"
          f"{'-'*10}-+-{'-'*10}")

    for month in range(1, 13):
        mt = [t for t in by_year[2021] if t['date'].month == month]
        if not mt:
            continue
        mis = [t for t in mt if t['poc_misaligned']]
        al = [t for t in mt if t['poc_aligned']]
        sa = calc_stats(mt)
        sm = calc_stats(mis)
        sal = calc_stats(al)
        print(f"  {month:>4}-21 | {sa['n']:>5} | {sm['n']:>5} | {len(al):>4} | "
              f"{sa['sharpe']:>7.2f} | {sm['sharpe']:>7.2f} | {sal['sharpe']:>7.2f} | "
              f"{sm['wr']:>5.1f}% | {sal['wr']:>5.1f}% | "
              f"{sm['total']:>10.2f} | {sal['total']:>10.2f}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 2: Direction breakdown — LONG vs SHORT misaligned
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 2: DIRECTION × POC ALIGNMENT — 2020 vs 2021 vs 2022")
    print("  Did LONG misaligned fail, SHORT misaligned, or both?\n")

    for yr in focus_years:
        print(f"  --- {yr} ---")
        for dir_label in ['LONG', 'SHORT']:
            for align_label, align_fn in [('Misaligned', lambda t: t['poc_misaligned']),
                                           ('Aligned', lambda t: t['poc_aligned'])]:
                sub = [t for t in by_year[yr] if t['direction'] == dir_label and align_fn(t)]
                s = calc_stats(sub)
                print(f"    {dir_label:>5} {align_label:<11}: N={s['n']:>4} Sh={s['sharpe']:>6.2f} "
                      f"WR={s['wr']:>5.1f}% SL={s['sl_pct']:>5.1f}% TP={s['tp_pct']:>5.1f}% "
                      f"PnL={s['total']:>8.2f}")
        print()

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 3: Exit type breakdown
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 3: EXIT TYPE BREAKDOWN — Misaligned trades by year")
    print("  Are misaligned trades in 2021 hitting SL more? Fewer TPs?\n")

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
              f"{s['mean']:>10.4f}")

    # Same for aligned
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
              f"{s['mean']:>10.4f}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 4: Range characteristics by year
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 4: RANGE CHARACTERISTICS BY YEAR")
    print("  Was 2021 structurally different? (range size, POC distribution, volume)\n")

    print(f"  {'Year':>6} | {'N':>4} | {'Median RS':>10} | {'Mean RS':>10} | "
          f"{'POC mean':>8} | {'POC std':>8} | {'POC<0.4':>7} | {'POC>0.6':>7} | "
          f"{'AvgVol':>10} | {'Price':>8}")
    print(f"  {'-'*6}-+-{'-'*4}-+-{'-'*10}-+-{'-'*10}-+-"
          f"{'-'*8}-+-{'-'*8}-+-{'-'*7}-+-{'-'*7}-+-"
          f"{'-'*10}-+-{'-'*8}")

    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        if len(yt) < 10:
            continue
        rs_vals = [t['range_size'] for t in yt]
        poc_vals = [t['poc_position'] for t in yt]
        vol_vals = [t['asian_volume'] for t in yt if not np.isnan(t.get('asian_volume', np.nan))]
        price_vals = [t['price_level'] for t in yt]
        poc_extreme_low = sum(1 for p in poc_vals if p < 0.4) / len(poc_vals) * 100
        poc_extreme_high = sum(1 for p in poc_vals if p > 0.6) / len(poc_vals) * 100
        print(f"  {yr:>6} | {len(yt):>4} | {np.median(rs_vals):>10.2f} | {np.mean(rs_vals):>10.2f} | "
              f"{np.mean(poc_vals):>8.3f} | {np.std(poc_vals):>8.3f} | "
              f"{poc_extreme_low:>6.1f}% | {poc_extreme_high:>6.1f}% | "
              f"{np.mean(vol_vals):>10.0f} | ${np.mean(price_vals):>7.0f}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 5: Gold price trend analysis
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 5: GOLD PRICE REGIME BY YEAR")
    print("  Was 2021 a choppy/ranging year where breakouts failed generally?\n")

    for yr in focus_years:
        yt = by_year[yr]
        prices = [t['price_level'] for t in yt]
        pnls = [t['pnl'] for t in yt]
        # Direction bias
        long_count = sum(1 for t in yt if t['direction'] == 'LONG')
        short_count = sum(1 for t in yt if t['direction'] == 'SHORT')
        # Price trend: start vs end
        first_price = prices[0] if prices else 0
        last_price = prices[-1] if prices else 0
        price_change_pct = (last_price - first_price) / first_price * 100 if first_price else 0
        # Range of prices
        price_min = min(prices) if prices else 0
        price_max = max(prices) if prices else 0

        print(f"  {yr}: Price ${first_price:.0f} -> ${last_price:.0f} ({price_change_pct:+.1f}%) "
              f"  Range: ${price_min:.0f}-${price_max:.0f}"
              f"  Longs: {long_count} Shorts: {short_count} ({long_count/(long_count+short_count)*100:.0f}%L)")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 6: POC position vs outcome — 2021 scatter view
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 6: POC POSITION DISTRIBUTION — Misaligned trades")
    print("  How extreme was the misalignment? Does degree matter?\n")

    for yr in focus_years:
        mis = [t for t in by_year[yr] if t['poc_misaligned']]
        if not mis:
            continue
        poc_vals = [t['poc_position'] for t in mis]
        pnls = [t['pnl'] for t in mis]

        # Split misaligned into mild (0.3-0.5 for LONG / 0.5-0.7 for SHORT) vs extreme
        mild = [t for t in mis if 0.3 <= t['poc_position'] <= 0.7]
        extreme = [t for t in mis if t['poc_position'] < 0.3 or t['poc_position'] > 0.7]

        sm = calc_stats(mild)
        se = calc_stats(extreme)

        print(f"  {yr}: Mild misalignment (POC 0.3-0.7):   N={sm['n']:>3} Sh={sm['sharpe']:>6.2f} WR={sm['wr']:>5.1f}%")
        print(f"  {yr}: Extreme misalignment (POC <0.3/>0.7): N={se['n']:>3} Sh={se['sharpe']:>6.2f} WR={se['wr']:>5.1f}%")
        print()

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 7: Quarterly deep-dive of 2021
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 7: QUARTERLY DEEP-DIVE — 2021")
    print("  Q-by-Q with direction and exit breakdown\n")

    for q in range(1, 5):
        months = list(range((q-1)*3 + 1, q*3 + 1))
        qt = [t for t in by_year[2021] if t['date'].month in months]
        mis = [t for t in qt if t['poc_misaligned']]
        al = [t for t in qt if t['poc_aligned']]

        print(f"  --- Q{q} 2021 (months {months}) ---")
        for label, group in [('ALL', qt), ('Misaligned', mis), ('Aligned', al)]:
            if not group:
                continue
            s = calc_stats(group)
            long_n = sum(1 for t in group if t['direction'] == 'LONG')
            short_n = sum(1 for t in group if t['direction'] == 'SHORT')
            avg_rs = np.mean([t['range_size'] for t in group])
            avg_price = np.mean([t['price_level'] for t in group])
            print(f"    {label:>11}: N={s['n']:>3} Sh={s['sharpe']:>6.2f} WR={s['wr']:>5.1f}% "
                  f"SL={s['sl_pct']:>5.1f}% TP={s['tp_pct']:>5.1f}% "
                  f"L/S={long_n}/{short_n} AvgRS=${avg_rs:.2f} Price~${avg_price:.0f}")
        print()

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 8: Worst individual misaligned trades in 2021
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 8: WORST 15 MISALIGNED TRADES IN 2021")
    print("  Examining individual losers for patterns\n")

    mis_2021 = sorted([t for t in by_year[2021] if t['poc_misaligned']], key=lambda t: t['pnl'])

    print(f"  {'Date':>12} | {'Dir':>5} | {'PnL':>10} | {'Exit':>4} | "
          f"{'POC':>5} | {'RS':>8} | {'Cat':>3} | {'Price':>8}")
    print(f"  {'-'*12}-+-{'-'*5}-+-{'-'*10}-+-{'-'*4}-+-"
          f"{'-'*5}-+-{'-'*8}-+-{'-'*3}-+-{'-'*8}")

    for t in mis_2021[:15]:
        print(f"  {t['date']} | {t['direction']:>5} | {t['pnl']:>10.2f} | {t['exit_type']:>4} | "
              f"{t['poc_position']:>5.3f} | {t['range_size']:>8.2f} | {t['category']:>3} | "
              f"${t['price_level']:>7.0f}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 9: Did ALIGNED trades outperform in 2021? Why?
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 9: ALIGNED PERFORMANCE IN 2021 — What worked?")

    al_2021 = by_year[2021]
    al_only = [t for t in al_2021 if t['poc_aligned']]

    # Best aligned trades
    best = sorted(al_only, key=lambda t: t['pnl'], reverse=True)[:10]
    print(f"\n  Top 10 aligned winners:")
    print(f"  {'Date':>12} | {'Dir':>5} | {'PnL':>10} | {'Exit':>4} | "
          f"{'POC':>5} | {'RS':>8} | {'Cat':>3}")
    print(f"  {'-'*12}-+-{'-'*5}-+-{'-'*10}-+-{'-'*4}-+-"
          f"{'-'*5}-+-{'-'*8}-+-{'-'*3}")
    for t in best:
        print(f"  {t['date']} | {t['direction']:>5} | {t['pnl']:>10.2f} | {t['exit_type']:>4} | "
              f"{t['poc_position']:>5.3f} | {t['range_size']:>8.2f} | {t['category']:>3}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 10: Cross-year consistency — which years had aligned > misaligned?
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 10: DIRECTION BIAS × ALIGNMENT BY YEAR")
    print("  Was 2021's long/short mix unusual?\n")

    print(f"  {'Year':>6} | {'%LONG':>6} | {'L_mis_Sh':>8} | {'L_al_Sh':>8} | "
          f"{'S_mis_Sh':>8} | {'S_al_Sh':>8} | {'Regime':>12}")
    print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*8}-+-{'-'*8}-+-"
          f"{'-'*8}-+-{'-'*8}-+-{'-'*12}")

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

        regime = "UP" if pchange > 5 else "DOWN" if pchange < -5 else "FLAT"

        print(f"  {yr:>6} | {long_pct:>5.1f}% | {l_mis['sharpe']:>8.2f} | {l_al['sharpe']:>8.2f} | "
              f"{s_mis['sharpe']:>8.2f} | {s_al['sharpe']:>8.2f} | {regime:>8} ({pchange:+.0f}%)")

    print(f"\n{'='*110}")
    print("  INVESTIGATION COMPLETE")
    print('='*110)


if __name__ == "__main__":
    main()
