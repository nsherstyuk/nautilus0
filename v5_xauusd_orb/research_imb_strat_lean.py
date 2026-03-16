"""
Lean version: test liquidity grab fade + flow momentum on XAUUSD 1-min data.
Runs each strategy ONCE with a few key configs, no heavy sweeps.
Uses flush=True to see output in real-time.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
import numpy as np
import pandas as pd
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv'

def p(msg): print(msg, flush=True)


def load_1m_bars(path=DATA_FILE):
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
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
    level_type: str = ''


def stats(trades, label=''):
    if not trades:
        return {'label': label, 'n': 0, 'sharpe': 0, 'pf': 0, 'wr': 0,
                'mean': 0, 'total': 0, 'max_dd': 0, 'mcl': 0}
    pnl = pd.Series([t.pnl for t in trades])
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
    streak = 0; mcl = 0
    for v in pnl:
        if v < 0: streak += 1; mcl = max(mcl, streak)
        else: streak = 0
    return {'label': label, 'n': n, 'sharpe': round(sharpe, 2),
            'pf': round(pf, 2), 'wr': round(wr, 1),
            'mean': round(mean, 2), 'total': round(pnl.sum(), 2),
            'max_dd': round(dd, 2), 'mcl': mcl}


def ps(s):
    if s['n'] == 0:
        p(f"  {s['label']:>30}: NO TRADES")
        return
    p(f"  {s['label']:>30}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
      f"PF {s['pf']:>5.2f} | WR {s['wr']:>5.1f}% | "
      f"Mean ${s['mean']:>+7.2f} | Total ${s['total']:>+10.2f} | "
      f"DD ${s['max_dd']:>+9.2f} | MCL {s['mcl']:>2}")


def _monitor(bars, start_idx, n, direction, entry_px, sl_px, tp_px,
             max_hold, entry_ts, day, entry_br, level_type):
    exit_px = None
    exit_type = 'EOD'
    exit_ts = entry_ts
    for j in range(start_idx, min(start_idx + max_hold, n)):
        ts, bar = bars[j]
        hs = bar['avg_spread'] / 2
        if direction == 'LONG':
            if bar['low'] <= sl_px:
                return Trade(day, direction, round(entry_px,3), round(sl_px-hs,3),
                             entry_ts, ts, 'SL', round(sl_px-hs-entry_px,3),
                             round((ts-entry_ts).total_seconds()/60,1), entry_br, level_type)
            if bar['high'] >= tp_px:
                return Trade(day, direction, round(entry_px,3), round(tp_px-hs,3),
                             entry_ts, ts, 'TP', round(tp_px-hs-entry_px,3),
                             round((ts-entry_ts).total_seconds()/60,1), entry_br, level_type)
        else:
            if bar['high'] >= sl_px:
                return Trade(day, direction, round(entry_px,3), round(sl_px+hs,3),
                             entry_ts, ts, 'SL', round(entry_px-sl_px-hs,3),
                             round((ts-entry_ts).total_seconds()/60,1), entry_br, level_type)
            if bar['low'] <= tp_px:
                return Trade(day, direction, round(entry_px,3), round(tp_px+hs,3),
                             entry_ts, ts, 'TP', round(entry_px-tp_px-hs,3),
                             round((ts-entry_ts).total_seconds()/60,1), entry_br, level_type)
    # Time/EOD exit
    end_idx = min(start_idx + max_hold, n) - 1
    if end_idx >= start_idx:
        exit_ts, exit_bar = bars[end_idx]
        hs = exit_bar['avg_spread'] / 2
        exit_px = exit_bar['close'] - hs if direction == 'LONG' else exit_bar['close'] + hs
        raw = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)
        return Trade(day, direction, round(entry_px,3), round(exit_px,3),
                     entry_ts, exit_ts, 'TIME', round(raw,3),
                     round((exit_ts-entry_ts).total_seconds()/60,1), entry_br, level_type)
    return None


# ── Precompute daily data structures ──

def precompute_days(df):
    """Precompute prev-day levels and group bars by date once."""
    days = []
    dates = sorted(df['date'].unique())
    prev_high = prev_low = prev_close = None

    for date in dates:
        day_df = df[df['date'] == date]
        wd = day_df['weekday'].iloc[0]
        if wd >= 5:
            prev_high = day_df['high'].max()
            prev_low = day_df['low'].min()
            prev_close = day_df['close'].iloc[-1]
            continue

        window = day_df[(day_df['hour'] >= 8) & (day_df['hour'] < 20)]
        bars = list(window.iterrows())

        levels = []
        if prev_high is not None:
            levels.append(('prev_high', prev_high))
            levels.append(('prev_low', prev_low))

        # Round numbers
        if bars:
            mid = bars[0][1]['close']
            step = 50.0
            base = round(mid / step) * step
            for rl in [base - step, base, base + step]:
                levels.append(('round', rl))

        days.append({
            'date': date,
            'bars': bars,
            'n': len(bars),
            'levels': levels,
        })

        prev_high = day_df['high'].max()
        prev_low = day_df['low'].min()
        prev_close = day_df['close'].iloc[-1]

    return days


# ── Strategy 1: Liquidity Grab Fade ──

def run_liq_fade(days, imb_w=3, div_thr=0.40, sl_mult=30, tp_mult=20, max_hold=60):
    trades = []
    for d in days:
        bars, n, levels = d['bars'], d['n'], d['levels']
        if n < imb_w + 5 or not levels:
            continue
        for i in range(imb_w, n):
            ts, bar = bars[i]
            hs = bar['avg_spread'] / 2
            br_vals = [bars[j][1]['buy_ratio'] for j in range(i - imb_w, i + 1)]
            avg_br = np.mean(br_vals)

            entered = False
            for lt, level in levels:
                # Upward pierce on seller-dominated flow -> SHORT fade
                if bar['high'] >= level + 0.5 and bar['open'] < level and avg_br < div_thr:
                    entry_px = bar['close'] + hs
                    sl_px = entry_px + sl_mult * bar['avg_spread']
                    tp_px = entry_px - tp_mult * bar['avg_spread']
                    t = _monitor(bars, i+1, n, 'SHORT', entry_px, sl_px, tp_px,
                                 max_hold, ts, d['date'], avg_br, lt)
                    if t: trades.append(t)
                    entered = True
                    break
                # Downward pierce on buyer-dominated flow -> LONG fade
                if bar['low'] <= level - 0.5 and bar['open'] > level and avg_br > (1-div_thr):
                    entry_px = bar['close'] - hs
                    sl_px = entry_px - sl_mult * bar['avg_spread']
                    tp_px = entry_px + tp_mult * bar['avg_spread']
                    t = _monitor(bars, i+1, n, 'LONG', entry_px, sl_px, tp_px,
                                 max_hold, ts, d['date'], avg_br, lt)
                    if t: trades.append(t)
                    entered = True
                    break
            if entered:
                break
    return trades


# ── Strategy 2: Flow Momentum ──

def run_flow_mom(days, streak=5, long_thr=0.60, short_thr=0.40,
                 sl_atr=2.0, tp_atr=3.0, max_hold=60, atr_w=20):
    trades = []
    for d in days:
        bars, n = d['bars'], d['n']
        if n < atr_w + streak + 5:
            continue
        ranges = [bars[j][1]['high'] - bars[j][1]['low'] for j in range(n)]
        day_trades = 0
        last_exit = -20

        for i in range(max(atr_w, streak), n):
            if day_trades >= 2 or i - last_exit < 10:
                continue
            atr = np.mean(ranges[i-atr_w:i])
            if atr <= 0:
                continue
            ts, bar = bars[i]
            hs = bar['avg_spread'] / 2
            brs = [bars[j][1]['buy_ratio'] for j in range(i-streak+1, i+1)]

            direction = None
            if all(br > long_thr for br in brs):
                direction = 'LONG'
                entry_px = bar['close'] + hs
                sl_px = entry_px - sl_atr * atr
                tp_px = entry_px + tp_atr * atr
            elif all(br < short_thr for br in brs):
                direction = 'SHORT'
                entry_px = bar['close'] - hs
                sl_px = entry_px + sl_atr * atr
                tp_px = entry_px - tp_atr * atr

            if direction:
                t = _monitor(bars, i+1, n, direction, entry_px, sl_px, tp_px,
                             max_hold, ts, d['date'], np.mean(brs), 'flow_mom')
                if t:
                    trades.append(t)
                    last_exit = i + max(1, int(t.hold_minutes))
                    day_trades += 1
    return trades


def main():
    import datetime as dt
    df = load_1m_bars()
    p(f"Loaded {len(df):,} bars ({df.index.min().date()} to {df.index.max().date()})")

    oos = dt.date(2021, 1, 1)

    p("Precomputing daily structures...")
    days = precompute_days(df)
    p(f"  {len(days)} trading days")

    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  STRATEGY 1: LIQUIDITY GRAB FADE")
    p("=" * 110)

    # 3 key configs instead of full sweep
    configs_1 = [
        {'label': 'Conservative', 'div_thr': 0.35, 'sl_mult': 30, 'tp_mult': 15, 'max_hold': 45},
        {'label': 'Baseline',     'div_thr': 0.40, 'sl_mult': 30, 'tp_mult': 20, 'max_hold': 60},
        {'label': 'Aggressive',   'div_thr': 0.45, 'sl_mult': 20, 'tp_mult': 25, 'max_hold': 90},
    ]

    for cfg in configs_1:
        p(f"\n  Config: {cfg['label']} (div={cfg['div_thr']}, SL={cfg['sl_mult']}x, TP={cfg['tp_mult']}x, hold={cfg['max_hold']}m)")
        t = run_liq_fade(days, div_thr=cfg['div_thr'], sl_mult=cfg['sl_mult'],
                         tp_mult=cfg['tp_mult'], max_hold=cfg['max_hold'])
        ps(stats(t, f"{cfg['label']} (full)"))
        t_oos = [x for x in t if x.date >= oos]
        ps(stats(t_oos, f"{cfg['label']} (OOS)"))

        # Level type breakdown
        for lt in sorted(set(x.level_type for x in t)):
            sub = [x for x in t if x.level_type == lt]
            sub_oos = [x for x in sub if x.date >= oos]
            p(f"    {lt:>12}: N={len(sub):>4} full Sh={stats(sub,'')['sharpe']:>5.2f} | "
              f"N={len(sub_oos):>4} OOS Sh={stats(sub_oos,'')['sharpe']:>5.2f}")

        # Annual
        by_yr = {}
        for x in t: by_yr.setdefault(x.date.year, []).append(x)
        p(f"    Annual: " + " | ".join(
            f"{yr}:{stats(by_yr[yr],'')['sharpe']:>+5.2f}"
            for yr in sorted(by_yr)))

        # Exit type
        for et in sorted(set(x.exit_type for x in t)):
            sub = [x for x in t if x.exit_type == et]
            p(f"    {et}: N={len(sub)}, mean=${np.mean([x.pnl for x in sub]):+.2f}")

    # Quick sweep: divergence threshold only
    p(f"\n  --- Quick div_threshold sweep (SL=30, TP=20, hold=60) ---")
    for div in [0.30, 0.35, 0.38, 0.40, 0.42, 0.45]:
        t = run_liq_fade(days, div_thr=div)
        s = stats(t, '')
        to = [x for x in t if x.date >= oos]
        so = stats(to, '')
        p(f"    div={div:.2f}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} WR={s['wr']:>4.1f}% Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  STRATEGY 2: FLOW MOMENTUM")
    p("=" * 110)

    configs_2 = [
        {'label': 'Tight',    'streak': 3, 'thr': 0.60, 'sl': 1.5, 'tp': 2.0, 'hold': 30},
        {'label': 'Baseline', 'streak': 5, 'thr': 0.60, 'sl': 2.0, 'tp': 3.0, 'hold': 60},
        {'label': 'Extreme',  'streak': 5, 'thr': 0.65, 'sl': 2.0, 'tp': 4.0, 'hold': 90},
        {'label': 'Wide',     'streak': 3, 'thr': 0.55, 'sl': 2.0, 'tp': 3.0, 'hold': 60},
    ]

    for cfg in configs_2:
        p(f"\n  Config: {cfg['label']} (streak={cfg['streak']}, thr={cfg['thr']}, "
          f"SL={cfg['sl']}xATR, TP={cfg['tp']}xATR, hold={cfg['hold']}m)")
        t = run_flow_mom(days, streak=cfg['streak'], long_thr=cfg['thr'],
                         short_thr=1-cfg['thr'], sl_atr=cfg['sl'],
                         tp_atr=cfg['tp'], max_hold=cfg['hold'])
        ps(stats(t, f"{cfg['label']} (full)"))
        t_oos = [x for x in t if x.date >= oos]
        ps(stats(t_oos, f"{cfg['label']} (OOS)"))

        # Direction
        longs = [x for x in t if x.direction == 'LONG']
        shorts = [x for x in t if x.direction == 'SHORT']
        p(f"    LONG:  N={len(longs):>4} Sh={stats(longs,'')['sharpe']:>5.2f} | "
          f"SHORT: N={len(shorts):>4} Sh={stats(shorts,'')['sharpe']:>5.2f}")

        # Annual
        by_yr = {}
        for x in t: by_yr.setdefault(x.date.year, []).append(x)
        p(f"    Annual: " + " | ".join(
            f"{yr}:{stats(by_yr[yr],'')['sharpe']:>+5.2f}"
            for yr in sorted(by_yr)))

        # Exit type
        for et in sorted(set(x.exit_type for x in t)):
            sub = [x for x in t if x.exit_type == et]
            p(f"    {et}: N={len(sub)}, mean=${np.mean([x.pnl for x in sub]):+.2f}")

    # Quick sweep: threshold only
    p(f"\n  --- Quick threshold sweep (streak=5, SL=2xATR, TP=3xATR, hold=60) ---")
    for thr in [0.55, 0.58, 0.60, 0.62, 0.65, 0.70]:
        t = run_flow_mom(days, long_thr=thr, short_thr=1-thr)
        s = stats(t, '')
        to = [x for x in t if x.date >= oos]
        so = stats(to, '')
        p(f"    thr={thr:.2f}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} WR={s['wr']:>4.1f}% Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    # Quick sweep: streak
    p(f"\n  --- Quick streak sweep (thr=0.60, SL=2xATR, TP=3xATR, hold=60) ---")
    for streak in [3, 4, 5, 7, 10]:
        t = run_flow_mom(days, streak=streak)
        s = stats(t, '')
        to = [x for x in t if x.date >= oos]
        so = stats(to, '')
        p(f"    streak={streak}: N={s['n']:>4} Sh={s['sharpe']:>5.2f} WR={s['wr']:>4.1f}% Mean=${s['mean']:>+6.2f} | OOS N={so['n']:>4} Sh={so['sharpe']:>5.2f}")

    p(f"\n{'='*110}")
    p("  DONE")
    p("=" * 110)


if __name__ == "__main__":
    main()
