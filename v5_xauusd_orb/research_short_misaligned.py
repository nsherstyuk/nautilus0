"""
research_short_misaligned.py -- Isolate SHORT misaligned vs LONG misaligned on XAUUSD.

Question: If we always keep SHORT misaligned trades (which worked in all regimes)
and conditionally filter LONG misaligned, what's the baseline performance?

Usage:
  python -m v5_xauusd_orb.research_short_misaligned
"""
from __future__ import annotations
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
        if rpct < 0.1 or rpct > 3.0:
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


def enrich_with_poc(df, trades):
    by_date = {d: g for d, g in df.groupby('date')}
    for t in trades:
        day_df = by_date.get(t['date'])
        if day_df is None:
            t['poc_position'] = 0.5
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

        t['price_level'] = (rh + rl) / 2

    for t in trades:
        poc = t['poc_position']
        if t['direction'] == 'LONG':
            t['poc_misaligned'] = poc < 0.5  # POC in bottom half, breaking up
        else:
            t['poc_misaligned'] = poc > 0.5  # POC in top half, breaking down
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
            'wr': round(wr, 1), 'mean': round(mean, 2), 'total': round(pnl.sum(), 2),
            'max_dd': round(dd, 2), 'sl_pct': round(sl_pct, 1), 'tp_pct': round(tp_pct, 1),
            'eod_pct': round(eod_pct, 1)}


def print_header(text):
    print(f"\n{'='*120}")
    print(f"  {text}")
    print('='*120)


def main():
    filepath = ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv'
    print("Loading XAUUSD 1-min data...")
    df = load_1m_bars(filepath)
    print(f"Loaded {len(df):,} bars ({df.index.min().date()} to {df.index.max().date()})")

    trades = run_backtest(df)
    trades = enrich_with_poc(df, trades)
    print(f"Total trades: {len(trades)}")

    by_year = defaultdict(list)
    for t in trades:
        by_year[t['date'].year].append(t)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 1: SHORT misaligned vs LONG misaligned by year
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 1: SHORT MISALIGNED vs LONG MISALIGNED — Year by Year")

    print(f"  {'Year':>6} | {'S_mis_N':>7} | {'S_mis_Sh':>8} | {'S_mis_WR':>8} | "
          f"{'L_mis_N':>7} | {'L_mis_Sh':>8} | {'L_mis_WR':>8} | {'Regime':>12}")
    print(f"  {'-'*6}-+-{'-'*7}-+-{'-'*8}-+-{'-'*8}-+-"
          f"{'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*12}")

    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        if len(yt) < 15:
            continue
        s_mis = [t for t in yt if t['direction'] == 'SHORT' and t['poc_misaligned']]
        l_mis = [t for t in yt if t['direction'] == 'LONG' and t['poc_misaligned']]
        ss = calc_stats(s_mis)
        ls = calc_stats(l_mis)

        prices = [t.get('price_level', 0) for t in yt if 'price_level' in t]
        if len(prices) >= 2:
            pchange = (prices[-1] - prices[0]) / prices[0] * 100
            regime = f"{'UP' if pchange > 3 else 'DOWN' if pchange < -3 else 'FLAT'} {pchange:+.0f}%"
        else:
            regime = "?"

        print(f"  {yr:>6} | {ss['n']:>7} | {ss['sharpe']:>8.2f} | {ss['wr']:>7.1f}% | "
              f"{ls['n']:>7} | {ls['sharpe']:>8.2f} | {ls['wr']:>7.1f}% | {regime:>12}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 2: "Always SHORT misaligned" strategy
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 2: STRATEGY — 'Always keep SHORT misaligned' (all years)")

    all_s_mis = [t for t in trades if t['direction'] == 'SHORT' and t['poc_misaligned']]
    all_l_mis = [t for t in trades if t['direction'] == 'LONG' and t['poc_misaligned']]
    all_mis = [t for t in trades if t['poc_misaligned']]
    baseline = calc_stats(trades)

    print(f"\n  {'Group':<25} | {'N':>5} | {'Sharpe':>7} | {'PF':>5} | {'WR':>6} | "
          f"{'Mean PnL':>9} | {'Total':>10} | {'MaxDD':>9} | {'SL%':>5} | {'TP%':>5}")
    print(f"  {'-'*25}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*6}-+-"
          f"{'-'*9}-+-{'-'*10}-+-{'-'*9}-+-{'-'*5}-+-{'-'*5}")

    for label, group in [
        ("Baseline (all)", trades),
        ("All misaligned", all_mis),
        ("SHORT misaligned only", all_s_mis),
        ("LONG misaligned only", all_l_mis),
    ]:
        s = calc_stats(group)
        print(f"  {label:<25} | {s['n']:>5} | {s['sharpe']:>7.2f} | {s['pf']:>5.2f} | "
              f"{s['wr']:>5.1f}% | {s['mean']:>9.2f} | {s['total']:>10.2f} | "
              f"{s['max_dd']:>9.2f} | {s['sl_pct']:>4.1f}% | {s['tp_pct']:>4.1f}%")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 3: Walk-forward — SHORT misaligned only
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 3: WALK-FORWARD — SHORT misaligned vs baseline by year")

    print(f"  {'Year':>6} | {'N_base':>6} | {'Sh_base':>7} | {'N_Smis':>6} | {'Sh_Smis':>7} | "
          f"{'WR_Smis':>7} | {'PnL_Smis':>10} | Better?")
    print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*7}-+-{'-'*6}-+-{'-'*7}-+-"
          f"{'-'*7}-+-{'-'*10}-+-{'-'*8}")

    helps = 0
    total_years = 0
    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        if len(yt) < 15:
            continue
        total_years += 1
        s_mis = [t for t in yt if t['direction'] == 'SHORT' and t['poc_misaligned']]
        sb = calc_stats(yt)
        ss = calc_stats(s_mis)
        better = ss['sharpe'] > sb['sharpe']
        if better:
            helps += 1
        print(f"  {yr:>6} | {sb['n']:>6} | {sb['sharpe']:>7.2f} | {ss['n']:>6} | {ss['sharpe']:>7.2f} | "
              f"{ss['wr']:>6.1f}% | {ss['total']:>10.2f} | {'YES' if better else 'no':>8}")

    print(f"\n  Walk-forward: helps {helps}/{total_years} years ({helps/total_years*100:.0f}%)")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 4: Walk-forward — LONG misaligned only (for comparison)
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 4: WALK-FORWARD — LONG misaligned vs baseline by year")

    print(f"  {'Year':>6} | {'N_base':>6} | {'Sh_base':>7} | {'N_Lmis':>6} | {'Sh_Lmis':>7} | "
          f"{'WR_Lmis':>7} | {'PnL_Lmis':>10} | Better?")
    print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*7}-+-{'-'*6}-+-{'-'*7}-+-"
          f"{'-'*7}-+-{'-'*10}-+-{'-'*8}")

    helps_l = 0
    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        if len(yt) < 15:
            continue
        l_mis = [t for t in yt if t['direction'] == 'LONG' and t['poc_misaligned']]
        sb = calc_stats(yt)
        ls = calc_stats(l_mis)
        better = ls['sharpe'] > sb['sharpe']
        if better:
            helps_l += 1
        print(f"  {yr:>6} | {sb['n']:>6} | {sb['sharpe']:>7.2f} | {ls['n']:>6} | {ls['sharpe']:>7.2f} | "
              f"{ls['wr']:>6.1f}% | {ls['total']:>10.2f} | {'YES' if better else 'no':>8}")

    print(f"\n  Walk-forward: helps {helps_l}/{total_years} years ({helps_l/total_years*100:.0f}%)")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 5: Combined — SHORT misaligned always + ALL aligned
    # Compare strategies that keep SHORT misaligned as anchor
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 5: COMPOSITE STRATEGIES — SHORT misaligned as anchor")

    strategies = {
        "Baseline (all trades)": lambda t: True,
        "All misaligned": lambda t: t['poc_misaligned'],
        "SHORT mis only": lambda t: t['direction'] == 'SHORT' and t['poc_misaligned'],
        "SHORT mis + all aligned": lambda t: (t['direction'] == 'SHORT' and t['poc_misaligned']) or not t['poc_misaligned'],
        "SHORT mis + LONG mis": lambda t: t['poc_misaligned'],  # same as all misaligned
        "All SHORT + SHORT mis": lambda t: t['direction'] == 'SHORT',  # all shorts
        "SHORT mis + LONG aligned": lambda t: (t['direction'] == 'SHORT' and t['poc_misaligned']) or (t['direction'] == 'LONG' and not t['poc_misaligned']),
    }

    # Remove duplicate
    del strategies["SHORT mis + LONG mis"]

    print(f"\n  {'Strategy':<30} | {'N':>5} | {'N/wk':>5} | {'Sharpe':>7} | {'PF':>5} | "
          f"{'WR':>6} | {'Total':>10} | {'MaxDD':>9}")
    print(f"  {'-'*30}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-"
          f"{'-'*6}-+-{'-'*10}-+-{'-'*9}")

    weeks = len(set(t['date'] for t in trades)) / 5  # approximate trading weeks

    for label, filt in strategies.items():
        group = [t for t in trades if filt(t)]
        s = calc_stats(group)
        nwk = s['n'] / weeks if weeks > 0 else 0
        print(f"  {label:<30} | {s['n']:>5} | {nwk:>5.1f} | {s['sharpe']:>7.2f} | {s['pf']:>5.2f} | "
              f"{s['wr']:>5.1f}% | {s['total']:>10.2f} | {s['max_dd']:>9.2f}")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 6: Walk-forward for composite strategies
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 6: WALK-FORWARD — Composite strategies by year")

    strats = {
        "SHORT mis only": lambda t: t['direction'] == 'SHORT' and t['poc_misaligned'],
        "SHORT mis + LONG al": lambda t: (t['direction'] == 'SHORT' and t['poc_misaligned']) or (t['direction'] == 'LONG' and not t['poc_misaligned']),
    }

    for strat_name, filt in strats.items():
        print(f"\n  --- {strat_name} ---")
        print(f"  {'Year':>6} | {'N_base':>6} | {'Sh_base':>7} | {'N_strat':>7} | {'Sh_strat':>8} | "
              f"{'WR':>6} | {'PnL':>10} | Better?")
        print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}-+-{'-'*8}-+-"
              f"{'-'*6}-+-{'-'*10}-+-{'-'*8}")

        h = 0
        ty = 0
        for yr in sorted(by_year.keys()):
            yt = by_year[yr]
            if len(yt) < 15:
                continue
            ty += 1
            group = [t for t in yt if filt(t)]
            sb = calc_stats(yt)
            sg = calc_stats(group)
            better = sg['sharpe'] > sb['sharpe']
            if better:
                h += 1
            print(f"  {yr:>6} | {sb['n']:>6} | {sb['sharpe']:>7.2f} | {sg['n']:>7} | {sg['sharpe']:>8.2f} | "
                  f"{sg['wr']:>5.1f}% | {sg['total']:>10.2f} | {'YES' if better else 'no':>8}")
        print(f"  Walk-forward: helps {h}/{ty} years ({h/ty*100:.0f}%)")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 7: Exit type detail — SHORT misaligned by year
    # ══════════════════════════════════════════════════════════════════════
    print_header("SECTION 7: EXIT TYPES — SHORT misaligned by year")

    print(f"  {'Year':>6} | {'N':>4} | {'SL%':>6} | {'TP%':>6} | {'EOD%':>6} | "
          f"{'WR':>5} | {'Sharpe':>7} | {'Mean PnL':>9}")
    print(f"  {'-'*6}-+-{'-'*4}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-"
          f"{'-'*5}-+-{'-'*7}-+-{'-'*9}")

    for yr in sorted(by_year.keys()):
        s_mis = [t for t in by_year[yr] if t['direction'] == 'SHORT' and t['poc_misaligned']]
        if len(s_mis) < 5:
            continue
        s = calc_stats(s_mis)
        print(f"  {yr:>6} | {s['n']:>4} | {s['sl_pct']:>5.1f}% | {s['tp_pct']:>5.1f}% | "
              f"{s['eod_pct']:>5.1f}% | {s['wr']:>4.1f}% | {s['sharpe']:>7.2f} | "
              f"{s['mean']:>9.2f}")

    print(f"\n{'='*120}")
    print("  ANALYSIS COMPLETE")
    print('='*120)


if __name__ == "__main__":
    main()
