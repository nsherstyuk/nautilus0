"""
Lightweight walk-forward for Liquidity Grab Fade.
Runs strategy ONCE with loose div_thr, then filters trades by date & threshold.
This avoids re-running the full strategy 48 times.
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
    return df

@dataclass
class Trade:
    date: object; direction: str; entry_price: float; exit_price: float
    entry_time: object; exit_time: object; exit_type: str; pnl: float
    hold_minutes: float; entry_buy_ratio: float; level_type: str
    hour: int = 0
    # Store the raw divergence strength for post-hoc filtering
    div_strength: float = 0.0

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

def monitor(wdf, start, direction, entry_px, sl_px, tp_px, max_hold, entry_ts, day, br, lt, hour, ds):
    n = len(wdf)
    for j in range(start, min(start + max_hold, n)):
        r = wdf.iloc[j]; ts = r['timestamp']; hs = r['avg_spread'] / 2
        if direction == 'LONG':
            if r['low'] <= sl_px:
                px = sl_px - hs; return Trade(day,'LONG',round(entry_px,2),round(px,2),entry_ts,ts,'SL',round(px-entry_px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour,ds)
            if r['high'] >= tp_px:
                px = tp_px - hs; return Trade(day,'LONG',round(entry_px,2),round(px,2),entry_ts,ts,'TP',round(px-entry_px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour,ds)
        else:
            if r['high'] >= sl_px:
                px = sl_px + hs; return Trade(day,'SHORT',round(entry_px,2),round(px,2),entry_ts,ts,'SL',round(entry_px-px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour,ds)
            if r['low'] <= tp_px:
                px = tp_px + hs; return Trade(day,'SHORT',round(entry_px,2),round(px,2),entry_ts,ts,'TP',round(entry_px-px,2),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour,ds)
    end = min(start + max_hold, n) - 1
    if end >= start:
        r = wdf.iloc[end]; ts = r['timestamp']; hs = r['avg_spread'] / 2
        px = r['close'] - hs if direction == 'LONG' else r['close'] + hs
        raw = (px - entry_px) if direction == 'LONG' else (entry_px - px)
        return Trade(day,direction,round(entry_px,2),round(px,2),entry_ts,ts,'TIME',round(raw,2),round((ts-entry_ts).total_seconds()/60,1),br,lt,hour,ds)
    return None


def run_all_pierces(grouped, prev_levels, max_hold=45):
    """
    Run with NO divergence filter -- capture ALL level pierces.
    Store div_strength on each trade for post-hoc filtering.
    """
    trades = []
    for day, gdf in grouped:
        if gdf['weekday'].iloc[0] >= 5:
            continue
        window = gdf[(gdf['hour'] >= 8) & (gdf['hour'] < 20)]
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
            hs = row['avg_spread'] / 2
            hr = int(row['hour'])
            entered = False

            for lt, level in levels:
                # Up pierce -> SHORT fade
                if row['high'] >= level + 0.5 and row['open'] < level:
                    ds = 0.5 - br  # positive = sellers dominate (divergent for up-pierce)
                    entry_px = row['close'] + hs
                    sl_px = entry_px + 30 * row['avg_spread']
                    tp_px = entry_px - 15 * row['avg_spread']
                    t = monitor(wa, i+1, 'SHORT', entry_px, sl_px, tp_px,
                                max_hold, ts, day, br, lt, hr, ds)
                    if t: trades.append(t)
                    entered = True; break

                # Down pierce -> LONG fade
                if row['low'] <= level - 0.5 and row['open'] > level:
                    ds = br - 0.5  # positive = buyers dominate (divergent for down-pierce)
                    entry_px = row['close'] - hs
                    sl_px = entry_px - 30 * row['avg_spread']
                    tp_px = entry_px + 15 * row['avg_spread']
                    t = monitor(wa, i+1, 'LONG', entry_px, sl_px, tp_px,
                                max_hold, ts, day, br, lt, hr, ds)
                    if t: trades.append(t)
                    entered = True; break
            if entered:
                break
    return trades


def main():
    df = load()
    p(f"Loaded {len(df):,} bars ({df.index.min().date()} to {df.index.max().date()})")

    daily = df.groupby('date').agg(
        day_high=('high','max'), day_low=('low','min'), wd=('weekday','first'))
    prev_levels = {}
    dates = daily.index.tolist()
    for i in range(1, len(dates)):
        prev_levels[dates[i]] = (daily.iloc[i-1]['day_high'], daily.iloc[i-1]['day_low'])

    grouped = list(df.groupby('date'))
    p(f"  {len(grouped)} days")

    # Run ONCE with no div filter to get all pierces
    p("Running all pierces (no divergence filter)...")
    all_trades = run_all_pierces(grouped, prev_levels)
    p(f"  Total pierce trades: {len(all_trades)}")

    # ═══════════════════════════════════════════════════════════════
    # WALK-FORWARD: optimize div_strength threshold on train, test on next year
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  WALK-FORWARD VALIDATION (train 3yr, test 1yr)")
    p("  Filter: keep trades where div_strength > threshold (divergent flow)")
    p("=" * 110)

    by_yr = {}
    for t in all_trades:
        by_yr.setdefault(t.date.year, []).append(t)

    # First show unfiltered annual
    p(f"\n  Unfiltered annual:")
    p(f"  {'Year':>6} | {'N':>4} | {'Sharpe':>7} | {'WR':>5} | {'Mean':>8} | {'Total':>10}")
    for yr in sorted(by_yr):
        s = stats(by_yr[yr],'')
        p(f"  {yr:>6} | {s['n']:>4} | {s['sharpe']:>7.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f}")

    # Walk-forward
    p(f"\n  Walk-forward with optimized div_strength threshold:")
    p(f"  {'Test':>6} | {'Train':>12} | {'Best_thr':>8} | {'N_unfilt':>8} | {'Sh_unfilt':>9} | {'N_filt':>6} | {'Sh_filt':>7} | {'Better':>6}")

    all_years = sorted(by_yr.keys())
    wf_results = []

    for test_idx in range(3, len(all_years)):
        test_yr = all_years[test_idx]
        train_yrs = all_years[test_idx-3:test_idx]

        # Get train trades
        train_trades = []
        for yr in train_yrs:
            if yr in by_yr:
                train_trades.extend(by_yr[yr])

        # Optimize threshold on train
        best_sh = -999
        best_thr = 0.10
        for thr in [0.0, 0.02, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25]:
            filtered = [t for t in train_trades if t.div_strength > thr]
            s = stats(filtered, '')
            if s['sharpe'] > best_sh:
                best_sh = s['sharpe']
                best_thr = thr

        # Test on test year
        test_all = by_yr.get(test_yr, [])
        test_filt = [t for t in test_all if t.div_strength > best_thr]
        s_all = stats(test_all, '')
        s_filt = stats(test_filt, '')
        better = 'YES' if s_filt['sharpe'] > s_all['sharpe'] else 'no'
        wf_results.append((test_yr, s_all['sharpe'], s_filt['sharpe'], better))

        p(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {best_thr:>8.2f} | {s_all['n']:>8} | {s_all['sharpe']:>9.2f} | {s_filt['n']:>6} | {s_filt['sharpe']:>7.2f} | {better:>6}")

    n_better = sum(1 for _, _, _, b in wf_results if b == 'YES')
    p(f"\n  Walk-forward improves {n_better}/{len(wf_results)} test years ({100*n_better/max(1,len(wf_results)):.0f}%)")

    # ═══════════════════════════════════════════════════════════════
    # FIXED THRESHOLD WALK-FORWARD (div_strength > 0.15 = div_thr < 0.35)
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  FIXED THRESHOLD: div_strength > 0.15 (= buy_ratio < 0.35 for SHORT, > 0.65 for LONG)")
    p("=" * 110)

    p(f"  {'Year':>6} | {'N_all':>5} | {'Sh_all':>6} | {'N_filt':>5} | {'Sh_filt':>7} | {'WR_filt':>6} | {'Mean_filt':>9} | {'Better':>6}")
    for yr in sorted(by_yr):
        yr_all = by_yr[yr]
        yr_filt = [t for t in yr_all if t.div_strength > 0.15]
        sa = stats(yr_all, '')
        sf = stats(yr_filt, '')
        better = 'YES' if sf['sharpe'] > sa['sharpe'] else 'no'
        p(f"  {yr:>6} | {sa['n']:>5} | {sa['sharpe']:>6.2f} | {sf['n']:>5} | {sf['sharpe']:>7.2f} | {sf['wr']:>5.1f}% | ${sf['mean']:>+8.2f} | {better:>6}")

    # Overall fixed filter
    filt_all = [t for t in all_trades if t.div_strength > 0.15]
    ps(stats(all_trades, "Unfiltered"))
    ps(stats(filt_all, "div_strength > 0.15"))
    filt_oos = [t for t in filt_all if t.date >= dt.date(2021,1,1)]
    ps(stats(filt_oos, "div>0.15 OOS 2021+"))

    # ═══════════════════════════════════════════════════════════════
    # MULTIPLE FIXED THRESHOLDS
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  FIXED THRESHOLD SWEEP (no optimization)")
    p("=" * 110)

    p(f"  {'thr':>6} | {'~div_thr':>8} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'N_OOS':>5} | {'Sh_OOS':>6} | {'Yrs_pos':>7}")
    for thr in [0.0, 0.02, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30]:
        filt = [t for t in all_trades if t.div_strength > thr]
        s = stats(filt, '')
        filt_oos = [t for t in filt if t.date >= dt.date(2021,1,1)]
        so = stats(filt_oos, '')
        # Count positive years
        by_y = {}
        for t in filt: by_y.setdefault(t.date.year, []).append(t)
        yrs_pos = sum(1 for yr, trades in by_y.items() if stats(trades,'')['sharpe'] > 0)
        approx_div = f"<{0.5-thr:.2f}"
        p(f"  {thr:>6.2f} | {approx_div:>8} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | {so['n']:>5} | {so['sharpe']:>6.2f} | {yrs_pos}/{len(by_y)}")

    # ═══════════════════════════════════════════════════════════════
    # COMPARISON WITH ORB
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  OVERLAP WITH ORB TRADING HOURS")
    p("=" * 110)

    # Check what hours ORB trades happen (Asian close ~08:00, trade window 08-20)
    # LiqFade also uses 08-20. But ORB is 1 trade/day, LiqFade is 1 trade/day
    # They CAN co-exist if they trigger on different days
    filt_best = [t for t in all_trades if t.div_strength > 0.15]
    filt_dates = set(t.date for t in filt_best)
    p(f"  LiqFade (div>0.15) trades on {len(filt_dates)} unique days")
    p(f"  Total trading days in dataset: ~{len(grouped)}")
    p(f"  LiqFade trade frequency: {len(filt_dates)/len(grouped)*100:.1f}% of days")

    # Hour distribution
    hr_dist = {}
    for t in filt_best:
        hr_dist[t.hour] = hr_dist.get(t.hour, 0) + 1
    p(f"  Hour distribution:")
    for hr in sorted(hr_dist):
        p(f"    {hr:02d}h: {hr_dist[hr]:>4} trades ({hr_dist[hr]/len(filt_best)*100:.1f}%)")

    # ═══════════════════════════════════════════════════════════════
    # DIRECTION ANALYSIS (which works better: fading prev_high or prev_low?)
    # ═══════════════════════════════════════════════════════════════
    p(f"\n{'='*110}")
    p("  DETAILED DIRECTION + LEVEL ANALYSIS (div>0.15)")
    p("=" * 110)

    for lt in ['prev_high', 'prev_low']:
        for d in ['LONG', 'SHORT']:
            sub = [t for t in filt_best if t.level_type == lt and t.direction == d]
            if sub:
                s = stats(sub, f"{lt}/{d}")
                ps(s)
            else:
                p(f"  {lt}/{d}: no trades (logically correct -- up pierce=SHORT fade, down pierce=LONG fade)")

    # Sanity check: up pierce of prev_high -> SHORT, down pierce of prev_low -> LONG
    ph_short = [t for t in filt_best if t.level_type == 'prev_high' and t.direction == 'SHORT']
    pl_long = [t for t in filt_best if t.level_type == 'prev_low' and t.direction == 'LONG']
    p(f"\n  Prev_high SHORT fade (stop hunt above): N={len(ph_short)}")
    if ph_short:
        ps(stats(ph_short, "PrevHigh SHORT"))
        ph_oos = [t for t in ph_short if t.date >= dt.date(2021,1,1)]
        ps(stats(ph_oos, "PrevHigh SHORT OOS"))
    p(f"  Prev_low LONG fade (stop hunt below): N={len(pl_long)}")
    if pl_long:
        ps(stats(pl_long, "PrevLow LONG"))
        pl_oos = [t for t in pl_long if t.date >= dt.date(2021,1,1)]
        ps(stats(pl_oos, "PrevLow LONG OOS"))

    # Any cross-level trades? (e.g., down pierce of prev_high)
    ph_long = [t for t in filt_best if t.level_type == 'prev_high' and t.direction == 'LONG']
    pl_short = [t for t in filt_best if t.level_type == 'prev_low' and t.direction == 'SHORT']
    if ph_long:
        p(f"  Prev_high LONG (down pierce of prev_high?): N={len(ph_long)}")
        ps(stats(ph_long, "PrevHigh LONG"))
    if pl_short:
        p(f"  Prev_low SHORT (up pierce of prev_low?): N={len(pl_short)}")
        ps(stats(pl_short, "PrevLow SHORT"))

    p(f"\n{'='*110}")
    p("  DONE")
    p("=" * 110)


if __name__ == "__main__":
    main()
