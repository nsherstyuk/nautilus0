"""
Fast version: Liquidity Grab Fade + Flow Momentum on XAUUSD 1-min data.
Uses groupby for speed, minimal sweeps.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
import numpy as np
import pandas as pd
import sys, datetime as dt

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
    # Rolling buy_ratio averages (precompute)
    df['br3'] = df['buy_ratio'].rolling(3, min_periods=3).mean()
    df['br5'] = df['buy_ratio'].rolling(5, min_periods=5).mean()
    df['range'] = df['high'] - df['low']
    df['atr20'] = df['range'].rolling(20, min_periods=20).mean()
    return df

@dataclass
class Trade:
    date: object; direction: str; entry_price: float; exit_price: float
    entry_time: object; exit_time: object; exit_type: str; pnl: float
    hold_minutes: float; entry_buy_ratio: float; level_type: str = ''

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
    if s['n'] == 0: p(f"  {s['label']:>30}: NO TRADES"); return
    p(f"  {s['label']:>30}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | PF {s['pf']:>5.2f} | "
      f"WR {s['wr']:>5.1f}% | Mean ${s['mean']:>+7.2f} | Total ${s['total']:>+10.2f} | "
      f"DD ${s['max_dd']:>+9.2f} | MCL {s['mcl']:>2}")

def monitor(wdf, start, direction, entry_px, sl_px, tp_px, max_hold, entry_ts, day, br, lt):
    """wdf: DataFrame (reset_index with 'timestamp' column)."""
    n = len(wdf)
    for j in range(start, min(start + max_hold, n)):
        r = wdf.iloc[j]
        ts = r['timestamp']
        hs = r['avg_spread'] / 2
        if direction == 'LONG':
            if r['low'] <= sl_px:
                px = sl_px - hs; return Trade(day,'LONG',round(entry_px,2),round(px,2),entry_ts,ts,'SL',round(px-entry_px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt)
            if r['high'] >= tp_px:
                px = tp_px - hs; return Trade(day,'LONG',round(entry_px,2),round(px,2),entry_ts,ts,'TP',round(px-entry_px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt)
        else:
            if r['high'] >= sl_px:
                px = sl_px + hs; return Trade(day,'SHORT',round(entry_px,2),round(px,2),entry_ts,ts,'SL',round(entry_px-px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt)
            if r['low'] <= tp_px:
                px = tp_px + hs; return Trade(day,'SHORT',round(entry_px,2),round(px,2),entry_ts,ts,'TP',round(entry_px-px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt)
    end = min(start + max_hold, n) - 1
    if end >= start:
        r = wdf.iloc[end]; ts = r['timestamp']; hs = r['avg_spread'] / 2
        px = r['close'] - hs if direction == 'LONG' else r['close'] + hs
        raw = (px - entry_px) if direction == 'LONG' else (entry_px - px)
        return Trade(day,direction,round(entry_px,2),round(px,2),entry_ts,ts,'TIME',round(raw,2),round((ts-entry_ts).total_seconds()/60,1),br,lt)
    return None


def run_liq_fade(grouped, prev_levels, div_thr=0.40, sl_m=30, tp_m=20, max_hold=60, round_step=50.0):
    trades = []
    for day, gdf in grouped:
        if gdf['weekday'].iloc[0] >= 5:
            continue
        window = gdf[(gdf['hour'] >= 8) & (gdf['hour'] < 20)]
        if len(window) < 10:
            continue
        rows = list(window.itertuples(index=True, name=None))
        # Convert to list of row dicts for speed
        cols = window.columns.tolist()
        idx_map = {c: i+1 for i, c in enumerate(cols)}  # +1 because index is at 0

        # Key levels
        levels = []
        if day in prev_levels:
            levels.append(('prev_high', prev_levels[day][0]))
            levels.append(('prev_low', prev_levels[day][1]))
        mid_price = window.iloc[0]['close']
        base = round(mid_price / round_step) * round_step
        for rl in [base - round_step, base, base + round_step]:
            levels.append(('round', rl))

        if not levels:
            continue

        n = len(window)
        window_arr = window.reset_index()
        for i in range(3, n):
            row = window_arr.iloc[i]
            ts = row['timestamp']
            br3 = row['br3']
            if np.isnan(br3):
                continue
            hs = row['avg_spread'] / 2
            entered = False

            for lt, level in levels:
                # Up pierce on seller flow -> SHORT fade
                if row['high'] >= level + 0.5 and row['open'] < level and br3 < div_thr:
                    entry_px = row['close'] + hs
                    sl_px = entry_px + sl_m * row['avg_spread']
                    tp_px = entry_px - tp_m * row['avg_spread']
                    t = monitor(window_arr, i+1, 'SHORT', entry_px, sl_px, tp_px,
                                max_hold, ts, day, br3, lt)
                    if t: trades.append(t)
                    entered = True; break
                # Down pierce on buyer flow -> LONG fade
                if row['low'] <= level - 0.5 and row['open'] > level and br3 > (1-div_thr):
                    entry_px = row['close'] - hs
                    sl_px = entry_px - sl_m * row['avg_spread']
                    tp_px = entry_px + tp_m * row['avg_spread']
                    t = monitor(window_arr, i+1, 'LONG', entry_px, sl_px, tp_px,
                                max_hold, ts, day, br3, lt)
                    if t: trades.append(t)
                    entered = True; break
            if entered:
                break
    return trades


def run_flow_mom(grouped, streak=5, long_thr=0.60, short_thr=0.40,
                 sl_atr=2.0, tp_atr=3.0, max_hold=60):
    trades = []
    for day, gdf in grouped:
        if gdf['weekday'].iloc[0] >= 5:
            continue
        window = gdf[(gdf['hour'] >= 8) & (gdf['hour'] < 20)]
        if len(window) < 30:
            continue
        n = len(window)
        window_arr = window.reset_index()
        day_trades = 0; last_exit = -20

        for i in range(max(20, streak), n):
            if day_trades >= 2 or i - last_exit < 10:
                continue
            row = window_arr.iloc[i]
            atr = row['atr20']
            if np.isnan(atr) or atr <= 0:
                continue
            ts = row['timestamp']
            hs = row['avg_spread'] / 2

            # Check streak of extreme buy_ratio
            brs = window_arr.iloc[i-streak+1:i+1]['buy_ratio'].values
            if len(brs) < streak:
                continue

            direction = None
            if np.all(brs > long_thr):
                direction = 'LONG'
                entry_px = row['close'] + hs
                sl_px = entry_px - sl_atr * atr
                tp_px = entry_px + tp_atr * atr
            elif np.all(brs < short_thr):
                direction = 'SHORT'
                entry_px = row['close'] - hs
                sl_px = entry_px + sl_atr * atr
                tp_px = entry_px - tp_atr * atr

            if direction:
                t = monitor(window_arr, i+1, direction, entry_px, sl_px, tp_px,
                            max_hold, ts, day, float(np.mean(brs)), 'flow_mom')
                if t:
                    trades.append(t)
                    last_exit = i + max(1, int(t.hold_minutes))
                    day_trades += 1
    return trades


def main():
    df = load()
    p(f"Loaded {len(df):,} bars ({df.index.min().date()} to {df.index.max().date()})")
    oos = dt.date(2021, 1, 1)

    # Precompute prev-day levels using groupby
    p("Computing prev-day levels...")
    daily = df.groupby('date').agg(
        day_high=('high','max'), day_low=('low','min'),
        day_close=('close','last'), wd=('weekday','first')
    )
    prev_levels = {}
    dates = daily.index.tolist()
    for i in range(1, len(dates)):
        prev_levels[dates[i]] = (daily.iloc[i-1]['day_high'], daily.iloc[i-1]['day_low'])

    grouped = list(df.groupby('date'))
    p(f"  {len(grouped)} days, {len(prev_levels)} with prev-day levels")

    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  STRATEGY 1: LIQUIDITY GRAB FADE")
    p("=" * 110)

    for label, div, sl, tp, hold in [
        ('Conservative', 0.35, 30, 15, 45),
        ('Baseline',     0.40, 30, 20, 60),
        ('Aggressive',   0.45, 20, 25, 90),
    ]:
        p(f"\n  {label}: div={div}, SL={sl}x, TP={tp}x, hold={hold}m")
        t = run_liq_fade(grouped, prev_levels, div_thr=div, sl_m=sl, tp_m=tp, max_hold=hold)
        ps(stats(t, f"{label} (full)"))
        ps(stats([x for x in t if x.date >= oos], f"{label} (OOS)"))

        if t:
            for lt in sorted(set(x.level_type for x in t)):
                sub = [x for x in t if x.level_type == lt]
                s = stats(sub, '')
                p(f"    {lt:>12}: N={len(sub):>4} Sh={s['sharpe']:>5.2f} Mean=${s['mean']:>+6.2f}")

            by_yr = {}
            for x in t: by_yr.setdefault(x.date.year, []).append(x)
            p(f"    Annual: " + " | ".join(f"{yr}:{stats(v,'')['sharpe']:>+5.2f}" for yr,v in sorted(by_yr.items())))

            for et in sorted(set(x.exit_type for x in t)):
                sub = [x for x in t if x.exit_type == et]
                p(f"    {et}: N={len(sub)}, mean=${np.mean([x.pnl for x in sub]):+.2f}")

    # Quick sweep
    p(f"\n  --- div_threshold sweep ---")
    for div in [0.30, 0.35, 0.38, 0.40, 0.42, 0.45]:
        t = run_liq_fade(grouped, prev_levels, div_thr=div)
        s = stats(t,''); so = stats([x for x in t if x.date >= oos],'')
        p(f"    div={div:.2f}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  STRATEGY 2: FLOW MOMENTUM")
    p("=" * 110)

    for label, streak, thr, sl, tp, hold in [
        ('Tight',    3, 0.60, 1.5, 2.0, 30),
        ('Baseline', 5, 0.60, 2.0, 3.0, 60),
        ('Extreme',  5, 0.65, 2.0, 4.0, 90),
        ('Wide',     3, 0.55, 2.0, 3.0, 60),
    ]:
        p(f"\n  {label}: streak={streak}, thr={thr}, SL={sl}xATR, TP={tp}xATR, hold={hold}m")
        t = run_flow_mom(grouped, streak=streak, long_thr=thr, short_thr=1-thr,
                         sl_atr=sl, tp_atr=tp, max_hold=hold)
        ps(stats(t, f"{label} (full)"))
        ps(stats([x for x in t if x.date >= oos], f"{label} (OOS)"))

        if t:
            longs = [x for x in t if x.direction == 'LONG']
            shorts = [x for x in t if x.direction == 'SHORT']
            p(f"    LONG: N={len(longs):>4} Sh={stats(longs,'')['sharpe']:>5.2f} | "
              f"SHORT: N={len(shorts):>4} Sh={stats(shorts,'')['sharpe']:>5.2f}")

            by_yr = {}
            for x in t: by_yr.setdefault(x.date.year, []).append(x)
            p(f"    Annual: " + " | ".join(f"{yr}:{stats(v,'')['sharpe']:>+5.2f}" for yr,v in sorted(by_yr.items())))

            for et in sorted(set(x.exit_type for x in t)):
                sub = [x for x in t if x.exit_type == et]
                p(f"    {et}: N={len(sub)}, mean=${np.mean([x.pnl for x in sub]):+.2f}")

    # Quick sweeps
    p(f"\n  --- threshold sweep (streak=5) ---")
    for thr in [0.55, 0.58, 0.60, 0.62, 0.65, 0.70]:
        t = run_flow_mom(grouped, long_thr=thr, short_thr=1-thr)
        s = stats(t,''); so = stats([x for x in t if x.date >= oos],'')
        p(f"    thr={thr:.2f}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    p(f"\n  --- streak sweep (thr=0.60) ---")
    for streak in [3, 4, 5, 7, 10]:
        t = run_flow_mom(grouped, streak=streak)
        s = stats(t,''); so = stats([x for x in t if x.date >= oos],'')
        p(f"    streak={streak}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    p(f"\n{'='*110}")
    p("  DONE")
    p("=" * 110)


if __name__ == "__main__":
    main()
