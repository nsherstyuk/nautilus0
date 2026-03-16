"""
Deep dive: Liquidity Grab Fade strategy on XAUUSD 1-min data.
Focus on prev-day H/L levels (strongest edge), drop round numbers.

Tests:
1. Prev-day H/L only, baseline + level-type breakdown
2. TP/SL optimization (spread multiples and ATR-based)
3. Time-of-day analysis
4. Divergence strength quintiles
5. Walk-forward validation (train 3yr, test 1yr)
6. Combination with ORB (non-overlapping)
7. Robustness: hold time, imbalance window, level buffer
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
import numpy as np
import pandas as pd
import datetime as dt

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv'

def p(msg): print(msg, flush=True)

def load():
    df = pd.read_csv(DATA_FILE)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    df['br3'] = df['buy_ratio'].rolling(3, min_periods=3).mean()
    df['br5'] = df['buy_ratio'].rolling(5, min_periods=5).mean()
    df['range'] = df['high'] - df['low']
    df['atr20'] = df['range'].rolling(20, min_periods=20).mean()
    return df

@dataclass
class Trade:
    date: object; direction: str; entry_price: float; exit_price: float
    entry_time: object; exit_time: object; exit_type: str; pnl: float
    hold_minutes: float; entry_buy_ratio: float; level_type: str
    hour: int = 0

def stats(trades, label=''):
    if not trades:
        return {'label': label, 'n': 0, 'sharpe': 0, 'pf': 0, 'wr': 0,
                'mean': 0, 'total': 0, 'max_dd': 0, 'mcl': 0}
    pnl = pd.Series([t.pnl for t in trades])
    n = len(pnl); mean = pnl.mean(); std = pnl.std()
    sharpe = mean / std * np.sqrt(252) if std > 0 else 0
    wr = (pnl > 0).mean() * 100
    gp = pnl[pnl > 0].sum(); gl = abs(pnl[pnl < 0].sum())
    pf = gp / gl if gl > 0 else float('inf')
    eq = pnl.cumsum(); dd = (eq - eq.cummax()).min()
    streak = 0; mcl = 0
    for v in pnl:
        if v < 0: streak += 1; mcl = max(mcl, streak)
        else: streak = 0
    return {'label': label, 'n': n, 'sharpe': round(sharpe,2), 'pf': round(pf,2),
            'wr': round(wr,1), 'mean': round(mean,2), 'total': round(pnl.sum(),2),
            'max_dd': round(dd,2), 'mcl': mcl}

def ps(s):
    if s['n'] == 0: p(f"  {s['label']:>35}: NO TRADES"); return
    p(f"  {s['label']:>35}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | PF {s['pf']:>5.2f} | "
      f"WR {s['wr']:>5.1f}% | Mean ${s['mean']:>+7.2f} | Total ${s['total']:>+10.2f} | "
      f"DD ${s['max_dd']:>+9.2f} | MCL {s['mcl']:>2}")

def monitor(wdf, start, direction, entry_px, sl_px, tp_px, max_hold, entry_ts, day, br, lt, hour):
    n = len(wdf)
    for j in range(start, min(start + max_hold, n)):
        r = wdf.iloc[j]
        ts = r['timestamp']
        hs = r['avg_spread'] / 2
        if direction == 'LONG':
            if r['low'] <= sl_px:
                px = sl_px - hs
                return Trade(day,'LONG',round(entry_px,2),round(px,2),entry_ts,ts,'SL',round(px-entry_px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour)
            if r['high'] >= tp_px:
                px = tp_px - hs
                return Trade(day,'LONG',round(entry_px,2),round(px,2),entry_ts,ts,'TP',round(px-entry_px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour)
        else:
            if r['high'] >= sl_px:
                px = sl_px + hs
                return Trade(day,'SHORT',round(entry_px,2),round(px,2),entry_ts,ts,'SL',round(entry_px-px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour)
            if r['low'] <= tp_px:
                px = tp_px + hs
                return Trade(day,'SHORT',round(entry_px,2),round(px,2),entry_ts,ts,'TP',round(entry_px-px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour)
    end = min(start + max_hold, n) - 1
    if end >= start:
        r = wdf.iloc[end]; ts = r['timestamp']; hs = r['avg_spread'] / 2
        px = r['close'] - hs if direction == 'LONG' else r['close'] + hs
        raw = (px - entry_px) if direction == 'LONG' else (entry_px - px)
        return Trade(day,direction,round(entry_px,2),round(px,2),entry_ts,ts,'TIME',round(raw,2),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour)
    return None


def run_liq_fade(grouped, prev_levels, div_thr=0.35, br_col='br3',
                 sl_m=30, tp_m=20, max_hold=60, level_buffer=0.5,
                 trade_start=8, trade_end=20, level_types=('prev_high','prev_low'),
                 max_trades_per_day=1):
    """
    Core strategy: fade level pierce on divergent flow.
    Uses spread-multiple SL/TP by default.
    """
    trades = []
    for day, gdf in grouped:
        if gdf['weekday'].iloc[0] >= 5:
            continue
        window = gdf[(gdf['hour'] >= trade_start) & (gdf['hour'] < trade_end)]
        if len(window) < 10:
            continue

        levels = []
        if day in prev_levels:
            ph, pl = prev_levels[day]
            if 'prev_high' in level_types:
                levels.append(('prev_high', ph))
            if 'prev_low' in level_types:
                levels.append(('prev_low', pl))
        if not levels:
            continue

        n = len(window)
        wa = window.reset_index()
        day_trades = 0

        for i in range(3, n):
            if day_trades >= max_trades_per_day:
                break
            row = wa.iloc[i]
            ts = row['timestamp']
            br = row[br_col]
            if np.isnan(br):
                continue
            hs = row['avg_spread'] / 2
            entered = False
            hr = int(row['hour'])

            for lt, level in levels:
                # Up pierce on seller flow -> SHORT fade
                if row['high'] >= level + level_buffer and row['open'] < level and br < div_thr:
                    entry_px = row['close'] + hs
                    sl_px = entry_px + sl_m * row['avg_spread']
                    tp_px = entry_px - tp_m * row['avg_spread']
                    t = monitor(wa, i+1, 'SHORT', entry_px, sl_px, tp_px,
                                max_hold, ts, day, br, lt, hr)
                    if t: trades.append(t); day_trades += 1
                    entered = True; break
                # Down pierce on buyer flow -> LONG fade
                if row['low'] <= level - level_buffer and row['open'] > level and br > (1-div_thr):
                    entry_px = row['close'] - hs
                    sl_px = entry_px - sl_m * row['avg_spread']
                    tp_px = entry_px + tp_m * row['avg_spread']
                    t = monitor(wa, i+1, 'LONG', entry_px, sl_px, tp_px,
                                max_hold, ts, day, br, lt, hr)
                    if t: trades.append(t); day_trades += 1
                    entered = True; break
            if entered and max_trades_per_day == 1:
                break
    return trades


def run_liq_fade_atr(grouped, prev_levels, div_thr=0.35, br_col='br3',
                     sl_atr=1.5, tp_atr=1.0, max_hold=60, level_buffer=0.5,
                     trade_start=8, trade_end=20):
    """ATR-based SL/TP version."""
    trades = []
    for day, gdf in grouped:
        if gdf['weekday'].iloc[0] >= 5:
            continue
        window = gdf[(gdf['hour'] >= trade_start) & (gdf['hour'] < trade_end)]
        if len(window) < 10:
            continue
        levels = []
        if day in prev_levels:
            ph, pl = prev_levels[day]
            levels.append(('prev_high', ph))
            levels.append(('prev_low', pl))
        if not levels:
            continue
        n = len(window)
        wa = window.reset_index()

        for i in range(3, n):
            row = wa.iloc[i]
            ts = row['timestamp']
            br = row[br_col]
            atr = row['atr20']
            if np.isnan(br) or np.isnan(atr) or atr <= 0:
                continue
            hs = row['avg_spread'] / 2
            hr = int(row['hour'])

            for lt, level in levels:
                if row['high'] >= level + level_buffer and row['open'] < level and br < div_thr:
                    entry_px = row['close'] + hs
                    t = monitor(wa, i+1, 'SHORT', entry_px, entry_px + sl_atr*atr,
                                entry_px - tp_atr*atr, max_hold, ts, day, br, lt, hr)
                    if t: trades.append(t)
                    return  # next day -- wrong, need to break
                if row['low'] <= level - level_buffer and row['open'] > level and br > (1-div_thr):
                    entry_px = row['close'] - hs
                    t = monitor(wa, i+1, 'LONG', entry_px, entry_px - sl_atr*atr,
                                entry_px + tp_atr*atr, max_hold, ts, day, br, lt, hr)
                    if t: trades.append(t)
                    return  # next day -- wrong
            # Only want first trade per day
            # Fixed below
    return trades


def run_liq_fade_atr_fixed(grouped, prev_levels, div_thr=0.35, br_col='br3',
                           sl_atr=1.5, tp_atr=1.0, max_hold=60, level_buffer=0.5,
                           trade_start=8, trade_end=20):
    """ATR-based SL/TP version (fixed)."""
    trades = []
    for day, gdf in grouped:
        if gdf['weekday'].iloc[0] >= 5:
            continue
        window = gdf[(gdf['hour'] >= trade_start) & (gdf['hour'] < trade_end)]
        if len(window) < 10:
            continue
        levels = []
        if day in prev_levels:
            ph, pl = prev_levels[day]
            levels.append(('prev_high', ph))
            levels.append(('prev_low', pl))
        if not levels:
            continue
        n = len(window)
        wa = window.reset_index()
        traded = False

        for i in range(3, n):
            if traded:
                break
            row = wa.iloc[i]
            ts = row['timestamp']
            br = row[br_col]
            atr = row['atr20']
            if np.isnan(br) or np.isnan(atr) or atr <= 0:
                continue
            hs = row['avg_spread'] / 2
            hr = int(row['hour'])

            for lt, level in levels:
                if row['high'] >= level + level_buffer and row['open'] < level and br < div_thr:
                    entry_px = row['close'] + hs
                    t = monitor(wa, i+1, 'SHORT', entry_px, entry_px + sl_atr*atr,
                                entry_px - tp_atr*atr, max_hold, ts, day, br, lt, hr)
                    if t: trades.append(t)
                    traded = True; break
                if row['low'] <= level - level_buffer and row['open'] > level and br > (1-div_thr):
                    entry_px = row['close'] - hs
                    t = monitor(wa, i+1, 'LONG', entry_px, entry_px - sl_atr*atr,
                                entry_px + tp_atr*atr, max_hold, ts, day, br, lt, hr)
                    if t: trades.append(t)
                    traded = True; break
    return trades


def main():
    df = load()
    p(f"Loaded {len(df):,} bars ({df.index.min().date()} to {df.index.max().date()})")
    oos = dt.date(2021, 1, 1)

    # Precompute prev-day levels
    daily = df.groupby('date').agg(
        day_high=('high','max'), day_low=('low','min'), wd=('weekday','first'))
    prev_levels = {}
    dates = daily.index.tolist()
    for i in range(1, len(dates)):
        prev_levels[dates[i]] = (daily.iloc[i-1]['day_high'], daily.iloc[i-1]['day_low'])

    grouped = list(df.groupby('date'))
    p(f"  {len(grouped)} days")

    # ═══════════════════════════════════════════════════════════════
    # TEST 1: PREV-DAY H/L ONLY (drop round numbers)
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 1: PREV-DAY H/L ONLY -- Baseline (div=0.35, SL=30x, TP=15x, hold=45)")
    p("=" * 110)

    t = run_liq_fade(grouped, prev_levels, div_thr=0.35, sl_m=30, tp_m=15, max_hold=45)
    ps(stats(t, "PrevHL (full)"))
    t_oos = [x for x in t if x.date >= oos]
    ps(stats(t_oos, "PrevHL (OOS 2021+)"))

    # Level type
    for lt in sorted(set(x.level_type for x in t)):
        sub = [x for x in t if x.level_type == lt]
        sub_oos = [x for x in sub if x.date >= oos]
        p(f"    {lt}: full N={len(sub)} Sh={stats(sub,'')['sharpe']:>5.2f} | OOS N={len(sub_oos)} Sh={stats(sub_oos,'')['sharpe']:>5.2f}")

    # Direction
    for d in ['LONG','SHORT']:
        sub = [x for x in t if x.direction == d]
        sub_oos = [x for x in sub if x.date >= oos]
        p(f"    {d}: full N={len(sub)} Sh={stats(sub,'')['sharpe']:>5.2f} | OOS N={len(sub_oos)} Sh={stats(sub_oos,'')['sharpe']:>5.2f}")

    # Exit type
    for et in sorted(set(x.exit_type for x in t)):
        sub = [x for x in t if x.exit_type == et]
        p(f"    {et}: N={len(sub)}, mean=${np.mean([x.pnl for x in sub]):+.2f}, WR={stats(sub,'')['wr']:.0f}%")

    # Annual
    by_yr = {}
    for x in t: by_yr.setdefault(x.date.year, []).append(x)
    p(f"\n  Annual breakdown:")
    p(f"  {'Year':>6} | {'N':>4} | {'Sharpe':>7} | {'WR':>5} | {'Mean':>8} | {'Total':>10} | {'MCL':>3}")
    for yr in sorted(by_yr):
        s = stats(by_yr[yr],'')
        p(f"  {yr:>6} | {s['n']:>4} | {s['sharpe']:>7.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f} | {s['mcl']:>3}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 2: TP/SL OPTIMIZATION (spread-based)
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 2: TP/SL SPREAD-MULTIPLE SWEEP (div=0.35)")
    p("=" * 110)

    p(f"  {'TP':>4} {'SL':>4} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'Total':>10} | {'N_OOS':>5} | {'Sh_OOS':>6} | {'Mean_OOS':>8}")
    for tp_m, sl_m in [(10,20),(10,30),(15,20),(15,30),(15,40),(20,20),(20,30),(20,40),
                        (25,30),(25,40),(30,30),(30,40),(30,50)]:
        tr = run_liq_fade(grouped, prev_levels, div_thr=0.35, sl_m=sl_m, tp_m=tp_m, max_hold=45)
        s = stats(tr,'')
        to = [x for x in tr if x.date >= oos]
        so = stats(to,'')
        p(f"  {tp_m:>4} {sl_m:>4} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f} | {so['n']:>5} | {so['sharpe']:>6.2f} | ${so['mean']:>+7.2f}")

    # ATR-based TP/SL
    p(f"\n  --- ATR-based TP/SL sweep ---")
    p(f"  {'TP_ATR':>6} {'SL_ATR':>6} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for tp_a, sl_a in [(0.5,1.0),(0.5,1.5),(0.75,1.0),(0.75,1.5),(1.0,1.0),(1.0,1.5),
                        (1.0,2.0),(1.5,1.5),(1.5,2.0),(2.0,2.0),(2.0,3.0)]:
        tr = run_liq_fade_atr_fixed(grouped, prev_levels, div_thr=0.35, sl_atr=sl_a, tp_atr=tp_a, max_hold=45)
        s = stats(tr,'')
        to = [x for x in tr if x.date >= oos]
        so = stats(to,'')
        p(f"  {tp_a:>6.1f} {sl_a:>6.1f} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 3: TIME-OF-DAY ANALYSIS
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 3: TIME-OF-DAY BREAKDOWN")
    p("=" * 110)

    best_t = run_liq_fade(grouped, prev_levels, div_thr=0.35, sl_m=30, tp_m=15, max_hold=45)
    by_hour = {}
    for x in best_t:
        by_hour.setdefault(x.hour, []).append(x)
    p(f"  {'Hour':>6} | {'N':>4} | {'Sharpe':>7} | {'WR':>5} | {'Mean':>8} | {'Total':>10}")
    for hr in sorted(by_hour):
        s = stats(by_hour[hr],'')
        p(f"  {hr:>5}h | {s['n']:>4} | {s['sharpe']:>7.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f}")

    # Test restricted windows
    p(f"\n  --- Window restrictions ---")
    for ts, te in [(8,14),(8,16),(8,18),(10,16),(10,18),(10,20),(12,20)]:
        tr = run_liq_fade(grouped, prev_levels, div_thr=0.35, sl_m=30, tp_m=15,
                          max_hold=45, trade_start=ts, trade_end=te)
        s = stats(tr,'')
        to = [x for x in tr if x.date >= oos]
        so = stats(to,'')
        p(f"    {ts:02d}-{te:02d}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 4: DIVERGENCE STRENGTH QUINTILES
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 4: DIVERGENCE STRENGTH QUINTILES")
    p("=" * 110)

    # Run with loose threshold to get all trades, then quintile
    all_t = run_liq_fade(grouped, prev_levels, div_thr=0.50, sl_m=30, tp_m=15, max_hold=45)
    if all_t:
        brs = pd.Series([x.entry_buy_ratio for x in all_t])
        # For SHORT trades, low br = strong divergence. For LONG, high br = strong divergence.
        # Normalize: compute "divergence strength" = |br - 0.5|
        div_strengths = []
        for x in all_t:
            if x.direction == 'SHORT':
                div_strengths.append(0.5 - x.entry_buy_ratio)  # higher = more divergent
            else:
                div_strengths.append(x.entry_buy_ratio - 0.5)
        ds = pd.Series(div_strengths)
        q_edges = ds.quantile([0, 0.2, 0.4, 0.6, 0.8, 1.0]).values
        p(f"  Divergence strength quintile edges: {[f'{v:.3f}' for v in q_edges]}")
        p(f"  {'Quintile':>10} | {'Range':>18} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'N_OOS':>5} | {'Sh_OOS':>6}")
        for qi in range(5):
            lo, hi = q_edges[qi], q_edges[qi+1]
            sub = [all_t[j] for j in range(len(all_t)) if lo <= div_strengths[j] <= (hi + 0.001)]
            s = stats(sub,'')
            sub_oos = [x for x in sub if x.date >= oos]
            so = stats(sub_oos,'')
            label = f"Q{qi+1}" if qi > 0 else "Q1 (weak)"
            if qi == 4: label = "Q5 (strong)"
            p(f"  {label:>10} | {lo:>+.3f} to {hi:>+.3f} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 5: DIVERGENCE THRESHOLD FINE SWEEP
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 5: DIVERGENCE THRESHOLD FINE SWEEP")
    p("=" * 110)

    p(f"  {'div_thr':>8} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'Total':>10} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for div in [0.25, 0.28, 0.30, 0.32, 0.33, 0.34, 0.35, 0.36, 0.37, 0.38, 0.40, 0.42, 0.45]:
        tr = run_liq_fade(grouped, prev_levels, div_thr=div, sl_m=30, tp_m=15, max_hold=45)
        s = stats(tr,'')
        to = [x for x in tr if x.date >= oos]
        so = stats(to,'')
        p(f"  {div:>8.2f} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 6: HOLD TIME SWEEP
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 6: HOLD TIME SWEEP (div=0.35)")
    p("=" * 110)

    p(f"  {'hold':>6} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for hold in [15, 20, 30, 45, 60, 90, 120]:
        tr = run_liq_fade(grouped, prev_levels, div_thr=0.35, sl_m=30, tp_m=15, max_hold=hold)
        s = stats(tr,'')
        to = [x for x in tr if x.date >= oos]
        so = stats(to,'')
        p(f"  {hold:>5}m | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 7: IMBALANCE WINDOW (br3 vs br5)
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 7: IMBALANCE WINDOW (br3 vs br5)")
    p("=" * 110)

    for col_label, col in [('3-bar avg', 'br3'), ('5-bar avg', 'br5'), ('single bar', 'buy_ratio')]:
        tr = run_liq_fade(grouped, prev_levels, div_thr=0.35, br_col=col, sl_m=30, tp_m=15, max_hold=45)
        s = stats(tr,'')
        to = [x for x in tr if x.date >= oos]
        so = stats(to,'')
        p(f"    {col_label:>12}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 8: LEVEL BUFFER SWEEP
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 8: LEVEL BUFFER SWEEP (how far price must pierce level)")
    p("=" * 110)

    for buf in [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]:
        tr = run_liq_fade(grouped, prev_levels, div_thr=0.35, sl_m=30, tp_m=15, max_hold=45, level_buffer=buf)
        s = stats(tr,'')
        to = [x for x in tr if x.date >= oos]
        so = stats(to,'')
        p(f"    buf={buf:>4.1f}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 9: WALK-FORWARD VALIDATION (train 3yr, test 1yr)
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 9: WALK-FORWARD VALIDATION")
    p("=" * 110)

    # Test with fixed best params first
    p(f"\n  A) Fixed params: div=0.35, SL=30x, TP=15x, hold=45")
    p(f"  {'Test':>6} | {'N_all':>5} | {'Sh_all':>6} | {'N_filt':>5} | {'Sh_filt':>7}")
    years = sorted(by_yr.keys())
    for yr in years:
        yr_trades = by_yr[yr]
        s = stats(yr_trades,'')
        p(f"  {yr:>6} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['n']:>5} | {s['sharpe']:>7.2f}")

    # Walk-forward: optimize div_threshold on train, test on next year
    p(f"\n  B) Walk-forward: optimize div_thr on 3yr train, test on next year")
    p(f"  {'Test':>6} | {'Train':>12} | {'Best_div':>8} | {'N_test':>6} | {'Sh_test':>7}")

    all_years = sorted(by_yr.keys())
    for test_idx in range(3, len(all_years)):
        test_yr = all_years[test_idx]
        train_yrs = all_years[test_idx-3:test_idx]

        # Optimize on train years
        best_sh = -999
        best_div = 0.35
        for div in [0.28, 0.30, 0.32, 0.34, 0.35, 0.36, 0.38, 0.40]:
            train_t = []
            for yr in train_yrs:
                if yr in by_yr:
                    # Re-filter by div threshold from full trades is tricky
                    # Just run the strategy restricted to train years
                    pass
            # Simpler: run once per div on train subset
            train_start = dt.date(train_yrs[0], 1, 1)
            train_end = dt.date(test_yr, 1, 1)
            tr = run_liq_fade(grouped, prev_levels, div_thr=div, sl_m=30, tp_m=15, max_hold=45)
            train_tr = [x for x in tr if train_start <= x.date < train_end]
            s = stats(train_tr,'')
            if s['sharpe'] > best_sh:
                best_sh = s['sharpe']
                best_div = div

        # Test on test year
        test_start = dt.date(test_yr, 1, 1)
        test_end = dt.date(test_yr + 1, 1, 1) if test_yr < 2026 else dt.date(2027, 1, 1)
        tr = run_liq_fade(grouped, prev_levels, div_thr=best_div, sl_m=30, tp_m=15, max_hold=45)
        test_tr = [x for x in tr if test_start <= x.date < test_end]
        s = stats(test_tr,'')
        p(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {best_div:>8.2f} | {s['n']:>6} | {s['sharpe']:>7.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 10: PREV-HIGH vs PREV-LOW only
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 10: PREV-HIGH ONLY vs PREV-LOW ONLY")
    p("=" * 110)

    for types, label in [
        (('prev_high',), 'prev_high only'),
        (('prev_low',), 'prev_low only'),
        (('prev_high','prev_low'), 'both'),
    ]:
        tr = run_liq_fade(grouped, prev_levels, div_thr=0.35, sl_m=30, tp_m=15,
                          max_hold=45, level_types=types)
        s = stats(tr,'')
        to = [x for x in tr if x.date >= oos]
        so = stats(to,'')
        p(f"    {label:>16}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 11: 2 TRADES PER DAY
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  TEST 11: MAX TRADES PER DAY")
    p("=" * 110)

    for mtpd in [1, 2]:
        tr = run_liq_fade(grouped, prev_levels, div_thr=0.35, sl_m=30, tp_m=15,
                          max_hold=45, max_trades_per_day=mtpd)
        s = stats(tr,'')
        to = [x for x in tr if x.date >= oos]
        so = stats(to,'')
        p(f"    max={mtpd}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    p(f"\n{'='*110}")
    p("  DONE")
    p("=" * 110)


if __name__ == "__main__":
    main()
