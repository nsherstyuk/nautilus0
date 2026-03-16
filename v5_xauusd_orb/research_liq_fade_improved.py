"""
Liquidity Grab Fade — Improved Version
Addresses all 5 critiques:
  1. Fix execution: enter at NEXT bar open + slippage
  2. Fix risk: ATR-based SL/TP
  3. Add rejection confirmation: pierce bar must close back inside level
  4. Test on EURUSD alongside XAUUSD
  5. Compare original vs improved

Run: python -u -m v5_xauusd_orb.research_liq_fade_improved
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
import datetime as dt

ROOT = Path(__file__).resolve().parents[1]
XAUUSD_FILE = ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv'
EURUSD_FILE = ROOT / 'data' / '1m_csv' / 'eurusd_1m_tick.csv'

def p(msg): print(msg, flush=True)

def load(path):
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    df['br3'] = df['buy_ratio'].rolling(3, min_periods=3).mean()
    df['range'] = df['high'] - df['low']
    df['atr20'] = df['range'].rolling(20, min_periods=20).mean()
    return df

@dataclass
class Trade:
    date: object
    direction: str
    entry_price: float
    exit_price: float
    entry_time: object
    exit_time: object
    exit_type: str
    pnl: float
    hold_minutes: float
    entry_buy_ratio: float
    level_type: str
    hour: int = 0
    version: str = ''  # 'original' or 'improved'

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
    if s['n'] == 0: p(f"  {s['label']:>40}: NO TRADES"); return
    p(f"  {s['label']:>40}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | PF {s['pf']:>5.2f} | "
      f"WR {s['wr']:>5.1f}% | Mean ${s['mean']:>+7.2f} | Total ${s['total']:>+10.2f} | "
      f"DD ${s['max_dd']:>+9.2f} | MCL {s['mcl']:>2}")


def monitor_atr(wdf, start, direction, entry_px, sl_px, tp_px, max_hold,
                entry_ts, day, br, lt, hour, version):
    """Trade monitor with ATR-based SL/TP."""
    n = len(wdf)
    for j in range(start, min(start + max_hold, n)):
        r = wdf.iloc[j]
        ts = r['timestamp']
        hs = r['avg_spread'] / 2
        if direction == 'LONG':
            if r['low'] <= sl_px:
                px = sl_px - hs
                return Trade(day,'LONG',round(entry_px,4),round(px,4),entry_ts,ts,'SL',
                             round(px-entry_px,4),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour,version)
            if r['high'] >= tp_px:
                px = tp_px - hs
                return Trade(day,'LONG',round(entry_px,4),round(px,4),entry_ts,ts,'TP',
                             round(px-entry_px,4),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour,version)
        else:
            if r['high'] >= sl_px:
                px = sl_px + hs
                return Trade(day,'SHORT',round(entry_px,4),round(px,4),entry_ts,ts,'SL',
                             round(entry_px-px,4),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour,version)
            if r['low'] <= tp_px:
                px = tp_px + hs
                return Trade(day,'SHORT',round(entry_px,4),round(px,4),entry_ts,ts,'TP',
                             round(entry_px-px,4),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour,version)
    end = min(start + max_hold, n) - 1
    if end >= start:
        r = wdf.iloc[end]; ts = r['timestamp']; hs = r['avg_spread'] / 2
        px = r['close'] - hs if direction == 'LONG' else r['close'] + hs
        raw = (px - entry_px) if direction == 'LONG' else (entry_px - px)
        return Trade(day,direction,round(entry_px,4),round(px,4),entry_ts,ts,'TIME',
                     round(raw,4),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour,version)
    return None


def precompute(df):
    """Precompute prev-day levels and grouped data."""
    daily = df.groupby('date').agg(
        day_high=('high','max'), day_low=('low','min'), wd=('weekday','first'))
    prev_levels = {}
    dates = daily.index.tolist()
    for i in range(1, len(dates)):
        prev_levels[dates[i]] = (daily.iloc[i-1]['day_high'], daily.iloc[i-1]['day_low'])
    grouped = list(df.groupby('date'))
    return grouped, prev_levels


# ═══════════════════════════════════════════════════════════════════
# STRATEGY A: ORIGINAL (for comparison baseline)
# Entry: bar close of pierce bar + half spread
# Risk: spread-based SL/TP
# No rejection confirmation
# ═══════════════════════════════════════════════════════════════════
def run_original(grouped, prev_levels, div_thr=0.35, sl_m=30, tp_m=15,
                 max_hold=45, level_buffer=0.5, min_ticks=0):
    trades = []
    for day, gdf in grouped:
        if gdf['weekday'].iloc[0] >= 5:
            continue
        window = gdf[(gdf['hour'] >= 8) & (gdf['hour'] < 16)]
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
            br = row['br3']
            if np.isnan(br):
                continue
            if min_ticks > 0 and row['tick_count'] < min_ticks:
                continue
            hs = row['avg_spread'] / 2
            hr = int(row['hour'])
            entered = False

            for lt, level in levels:
                if row['high'] >= level + level_buffer and row['open'] < level and br < div_thr:
                    entry_px = row['close'] + hs
                    sl_px = entry_px + sl_m * row['avg_spread']
                    tp_px = entry_px - tp_m * row['avg_spread']
                    t = monitor_atr(wa, i+1, 'SHORT', entry_px, sl_px, tp_px,
                                    max_hold, ts, day, br, lt, hr, 'original')
                    if t: trades.append(t)
                    entered = True; break
                if row['low'] <= level - level_buffer and row['open'] > level and br > (1-div_thr):
                    entry_px = row['close'] - hs
                    sl_px = entry_px - sl_m * row['avg_spread']
                    tp_px = entry_px + tp_m * row['avg_spread']
                    t = monitor_atr(wa, i+1, 'LONG', entry_px, sl_px, tp_px,
                                    max_hold, ts, day, br, lt, hr, 'original')
                    if t: trades.append(t)
                    entered = True; break
            if entered:
                break
    return trades


# ═══════════════════════════════════════════════════════════════════
# STRATEGY B: IMPROVED
# 1. Entry: NEXT bar open + slippage
# 2. Risk: ATR-based SL/TP
# 3. Rejection: pierce bar must close back inside level
# 4. Min tick_count filter
# ═══════════════════════════════════════════════════════════════════
def run_improved(grouped, prev_levels, div_thr=0.35,
                 sl_atr=1.5, tp_atr=1.0, max_hold=45,
                 level_buffer=0.5, slippage=0.0,
                 min_ticks=50, require_rejection=True):
    trades = []
    for day, gdf in grouped:
        if gdf['weekday'].iloc[0] >= 5:
            continue
        window = gdf[(gdf['hour'] >= 8) & (gdf['hour'] < 16)]
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

        for i in range(3, n - 1):  # n-1 because we need next bar
            row = wa.iloc[i]
            br = row['br3']
            atr = row['atr20']
            if np.isnan(br) or np.isnan(atr) or atr <= 0:
                continue
            if min_ticks > 0 and row['tick_count'] < min_ticks:
                continue
            hr = int(row['hour'])
            entered = False

            for lt, level in levels:
                # UP PIERCE on seller flow -> SHORT fade
                if (row['high'] >= level + level_buffer and
                    row['open'] < level and
                    br < div_thr):

                    # Rejection check: pierce bar must close back BELOW level
                    if require_rejection and row['close'] > level:
                        continue

                    # Enter at NEXT bar open + slippage
                    next_bar = wa.iloc[i + 1]
                    entry_px = next_bar['open'] + slippage
                    entry_ts = next_bar['timestamp']

                    sl_px = entry_px + sl_atr * atr
                    tp_px = entry_px - tp_atr * atr

                    t = monitor_atr(wa, i+2, 'SHORT', entry_px, sl_px, tp_px,
                                    max_hold, entry_ts, day, br, lt, hr, 'improved')
                    if t: trades.append(t)
                    entered = True; break

                # DOWN PIERCE on buyer flow -> LONG fade
                if (row['low'] <= level - level_buffer and
                    row['open'] > level and
                    br > (1 - div_thr)):

                    # Rejection check: pierce bar must close back ABOVE level
                    if require_rejection and row['close'] < level:
                        continue

                    # Enter at NEXT bar open - slippage (adverse)
                    next_bar = wa.iloc[i + 1]
                    entry_px = next_bar['open'] - slippage
                    entry_ts = next_bar['timestamp']

                    sl_px = entry_px - sl_atr * atr
                    tp_px = entry_px + tp_atr * atr

                    t = monitor_atr(wa, i+2, 'LONG', entry_px, sl_px, tp_px,
                                    max_hold, entry_ts, day, br, lt, hr, 'improved')
                    if t: trades.append(t)
                    entered = True; break
            if entered:
                break
    return trades


def print_annual(trades):
    by_yr = {}
    for t in trades: by_yr.setdefault(t.date.year, []).append(t)
    p(f"    {'Year':>6} | {'N':>4} | {'Sharpe':>7} | {'WR':>5} | {'Mean':>8} | {'Total':>10}")
    for yr in sorted(by_yr):
        s = stats(by_yr[yr],'')
        p(f"    {yr:>6} | {s['n']:>4} | {s['sharpe']:>7.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f}")
    return by_yr


def print_breakdown(trades):
    # Direction
    for d in ['LONG','SHORT']:
        sub = [t for t in trades if t.direction == d]
        if sub:
            s = stats(sub,'')
            p(f"    {d}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} WR={s['wr']:>4.1f}% Mean=${s['mean']:>+.2f}")

    # Level type
    for lt in sorted(set(t.level_type for t in trades)):
        sub = [t for t in trades if t.level_type == lt]
        if sub:
            s = stats(sub,'')
            p(f"    {lt}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} WR={s['wr']:>4.1f}% Mean=${s['mean']:>+.2f}")

    # Exit type
    for et in sorted(set(t.exit_type for t in trades)):
        sub = [t for t in trades if t.exit_type == et]
        if sub:
            p(f"    {et}: N={len(sub)}, mean=${np.mean([t.pnl for t in sub]):+.4f}, WR={stats(sub,'')['wr']:.0f}%")


def run_instrument(name, path, slippage):
    p(f"\n{'#'*110}")
    p(f"  INSTRUMENT: {name}")
    p(f"  Data: {path}")
    p(f"  Slippage: {slippage}")
    p(f"{'#'*110}")

    df = load(path)
    p(f"  Loaded {len(df):,} bars ({df.index.min().date()} to {df.index.max().date()})")
    grouped, prev_levels = precompute(df)
    oos = dt.date(2021, 1, 1)

    # ═══════════════════════════════════════════════════════════════
    # A) ORIGINAL STRATEGY (baseline)
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p(f"  A) ORIGINAL: bar-close entry, spread-based SL/TP, no rejection, no tick filter")
    p(f"     (div=0.35, SL=30x spread, TP=15x spread, hold=45m, buf=0.5, window 08-16)")
    p("=" * 110)

    t_orig = run_original(grouped, prev_levels)
    ps(stats(t_orig, f"{name} Original (full)"))
    t_orig_oos = [t for t in t_orig if t.date >= oos]
    ps(stats(t_orig_oos, f"{name} Original (OOS 2021+)"))
    if t_orig:
        print_breakdown(t_orig)
        p("  Annual:")
        print_annual(t_orig)

    # ═══════════════════════════════════════════════════════════════
    # B) IMPROVED: next-bar entry + ATR SL/TP + rejection + tick filter
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p(f"  B) IMPROVED: next-bar-open entry + slippage, ATR SL/TP, rejection, min_ticks=50")
    p(f"     (div=0.35, SL=1.5xATR, TP=1.0xATR, hold=45m, buf=0.5, window 08-16)")
    p("=" * 110)

    t_imp = run_improved(grouped, prev_levels, slippage=slippage)
    ps(stats(t_imp, f"{name} Improved (full)"))
    t_imp_oos = [t for t in t_imp if t.date >= oos]
    ps(stats(t_imp_oos, f"{name} Improved (OOS 2021+)"))
    if t_imp:
        print_breakdown(t_imp)
        p("  Annual:")
        print_annual(t_imp)

    # ═══════════════════════════════════════════════════════════════
    # C) ABLATION: test each improvement individually
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p(f"  C) ABLATION: isolate each improvement")
    p("=" * 110)

    # C1: Just next-bar entry (no rejection, no tick filter, spread SL/TP)
    p(f"\n  C1: Next-bar entry only (spread SL/TP, no rejection, no tick filter)")
    t = run_improved(grouped, prev_levels, sl_atr=0, tp_atr=0, slippage=slippage,
                     min_ticks=0, require_rejection=False)
    # Actually, ATR=0 won't work. Let me use original with next-bar twist differently.
    # Better: run improved with SL/TP set large enough they never hit, then compare.
    # Simplest: just test combos systematically.

    configs = [
        ("Next-bar + spread SL/TP",
         dict(sl_atr=0, tp_atr=0, slippage=slippage, min_ticks=0, require_rejection=False)),
        ("Next-bar + ATR SL/TP",
         dict(slippage=slippage, min_ticks=0, require_rejection=False)),
        ("Next-bar + ATR + rejection",
         dict(slippage=slippage, min_ticks=0, require_rejection=True)),
        ("Next-bar + ATR + rejection + ticks>=50",
         dict(slippage=slippage, min_ticks=50, require_rejection=True)),
        ("Next-bar + ATR + rejection + ticks>=30",
         dict(slippage=slippage, min_ticks=30, require_rejection=True)),
    ]

    # We can't easily do spread SL/TP in the improved function. Let's just skip that combo
    # and focus on what matters.
    configs_clean = [
        ("Improved: no rejection, no tick filt",
         dict(slippage=slippage, min_ticks=0, require_rejection=False)),
        ("Improved: + rejection",
         dict(slippage=slippage, min_ticks=0, require_rejection=True)),
        ("Improved: + rejection + ticks>=30",
         dict(slippage=slippage, min_ticks=30, require_rejection=True)),
        ("Improved: + rejection + ticks>=50",
         dict(slippage=slippage, min_ticks=50, require_rejection=True)),
        ("Improved: + rejection + ticks>=80",
         dict(slippage=slippage, min_ticks=80, require_rejection=True)),
    ]

    p(f"\n  {'Config':>45} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for label, kw in configs_clean:
        t = run_improved(grouped, prev_levels, **kw)
        s = stats(t, '')
        to = [x for x in t if x.date >= oos]
        so = stats(to, '')
        p(f"  {label:>45} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.4f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════
    # D) ATR SL/TP SWEEP
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p(f"  D) ATR SL/TP SWEEP (improved base: next-bar, rejection, ticks>=50)")
    p("=" * 110)

    p(f"  {'SL_ATR':>6} {'TP_ATR':>6} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for sl_a, tp_a in [(1.0,0.5),(1.0,0.75),(1.0,1.0),(1.5,0.5),(1.5,0.75),(1.5,1.0),(1.5,1.5),
                        (2.0,0.75),(2.0,1.0),(2.0,1.5),(2.0,2.0),(2.5,1.0),(2.5,1.5),(3.0,1.5),(3.0,2.0)]:
        t = run_improved(grouped, prev_levels, sl_atr=sl_a, tp_atr=tp_a,
                         slippage=slippage, min_ticks=50)
        s = stats(t,'')
        to = [x for x in t if x.date >= oos]
        so = stats(to,'')
        p(f"  {sl_a:>6.1f} {tp_a:>6.1f} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.4f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════
    # E) DIVERGENCE THRESHOLD SWEEP (improved)
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p(f"  E) DIVERGENCE THRESHOLD SWEEP (improved)")
    p("=" * 110)

    p(f"  {'div':>6} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for div in [0.25, 0.30, 0.33, 0.35, 0.37, 0.40, 0.42, 0.45]:
        t = run_improved(grouped, prev_levels, div_thr=div, slippage=slippage, min_ticks=50)
        s = stats(t,'')
        to = [x for x in t if x.date >= oos]
        so = stats(to,'')
        p(f"  {div:>6.2f} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.4f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════
    # F) LEVEL BUFFER SWEEP (improved)
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p(f"  F) LEVEL BUFFER SWEEP (improved)")
    p("=" * 110)

    p(f"  {'buf':>6} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for buf in [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]:
        # For EURUSD, buffers are in pips (0.0001 units), so scale appropriately
        # Actually, both instruments use price units directly. EURUSD levels are ~1.0-1.2
        # A buffer of 0.5 is huge for EURUSD. Need instrument-specific buffers.
        t = run_improved(grouped, prev_levels, level_buffer=buf, slippage=slippage, min_ticks=50)
        s = stats(t,'')
        to = [x for x in t if x.date >= oos]
        so = stats(to,'')
        p(f"  {buf:>6.2f} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.4f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    return t_orig, t_imp


def main():
    p("=" * 110)
    p("  LIQUIDITY GRAB FADE: ORIGINAL vs IMPROVED")
    p("  Improvements: next-bar entry, ATR SL/TP, rejection confirmation, tick filter")
    p("=" * 110)

    # ═══════════════════════════════════════════════════════════════
    # XAUUSD (primary instrument)
    # Slippage: $0.15 (typical for gold)
    # ═══════════════════════════════════════════════════════════════
    xau_orig, xau_imp = run_instrument("XAUUSD", XAUUSD_FILE, slippage=0.15)

    # ═══════════════════════════════════════════════════════════════
    # EURUSD (validation instrument)
    # Slippage: 0.00005 (0.5 pips, typical for EURUSD)
    # Level buffer needs to be much smaller for EURUSD
    # ═══════════════════════════════════════════════════════════════
    p(f"\n\n{'#'*110}")
    p(f"  LOADING EURUSD...")
    p(f"{'#'*110}")

    df_eur = load(EURUSD_FILE)
    p(f"  Loaded {len(df_eur):,} bars ({df_eur.index.min().date()} to {df_eur.index.max().date()})")
    grouped_eur, prev_eur = precompute(df_eur)
    oos = dt.date(2021, 1, 1)

    # EURUSD-specific: buffer in price units (1 pip = 0.0001)
    # prev-day range for EURUSD is typically 50-100 pips = 0.005-0.01
    # A buffer of 0.0005 (5 pips) is reasonable for EURUSD
    p(f"\n{'='*110}")
    p(f"  EURUSD: ORIGINAL (spread-based, buf=0.0005)")
    p("=" * 110)

    t_eur_orig = run_original(grouped_eur, prev_eur, level_buffer=0.0005)
    ps(stats(t_eur_orig, "EURUSD Original (full)"))
    eur_orig_oos = [t for t in t_eur_orig if t.date >= oos]
    ps(stats(eur_orig_oos, "EURUSD Original (OOS)"))
    if t_eur_orig:
        print_breakdown(t_eur_orig)
        p("  Annual:")
        print_annual(t_eur_orig)

    p(f"\n{'='*110}")
    p(f"  EURUSD: IMPROVED (next-bar, ATR SL/TP, rejection, ticks>=50, buf=0.0005)")
    p("=" * 110)

    t_eur_imp = run_improved(grouped_eur, prev_eur, level_buffer=0.0005,
                             slippage=0.00005, min_ticks=50)
    ps(stats(t_eur_imp, "EURUSD Improved (full)"))
    eur_imp_oos = [t for t in t_eur_imp if t.date >= oos]
    ps(stats(eur_imp_oos, "EURUSD Improved (OOS)"))
    if t_eur_imp:
        print_breakdown(t_eur_imp)
        p("  Annual:")
        print_annual(t_eur_imp)

    # EURUSD buffer sweep
    p(f"\n  --- EURUSD buffer sweep ---")
    p(f"  {'buf':>10} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>10} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for buf in [0.0, 0.0001, 0.0003, 0.0005, 0.001, 0.002, 0.003]:
        t = run_improved(grouped_eur, prev_eur, level_buffer=buf,
                         slippage=0.00005, min_ticks=50)
        s = stats(t,'')
        to = [x for x in t if x.date >= oos]
        so = stats(to,'')
        p(f"  {buf:>10.4f} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+9.6f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # EURUSD div threshold sweep
    p(f"\n  --- EURUSD div threshold sweep ---")
    p(f"  {'div':>6} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>10} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for div in [0.25, 0.30, 0.35, 0.40, 0.45]:
        t = run_improved(grouped_eur, prev_eur, div_thr=div, level_buffer=0.0005,
                         slippage=0.00005, min_ticks=50)
        s = stats(t,'')
        to = [x for x in t if x.date >= oos]
        so = stats(to,'')
        p(f"  {div:>6.2f} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+9.6f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════
    # FINAL COMPARISON
    # ═══════════════════════════════════════════════════════════════
    p(f"\n\n{'='*110}")
    p("  FINAL COMPARISON SUMMARY")
    p("=" * 110)

    ps(stats(xau_orig, "XAUUSD Original"))
    ps(stats(xau_imp, "XAUUSD Improved"))
    ps(stats([t for t in xau_orig if t.date >= oos], "XAUUSD Original (OOS)"))
    ps(stats([t for t in xau_imp if t.date >= oos], "XAUUSD Improved (OOS)"))
    ps(stats(t_eur_orig, "EURUSD Original"))
    ps(stats(t_eur_imp, "EURUSD Improved"))
    ps(stats([t for t in t_eur_orig if t.date >= oos], "EURUSD Original (OOS)"))
    ps(stats([t for t in t_eur_imp if t.date >= oos], "EURUSD Improved (OOS)"))

    p(f"\n{'='*110}")
    p("  DONE")
    p("=" * 110)


if __name__ == "__main__":
    main()
