"""
analyze_seasonality.py -- Weekday / seasonal analysis  (v5)

Investigates weekday and monthly variations in the XAUUSD ORB strategy.
All parameters from config.yaml.

Usage:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.analyze_seasonality
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.analyze_seasonality --config alt.yaml
"""
import warnings; warnings.filterwarnings("ignore")

import argparse
import numpy as np
import pandas as pd
from pathlib import Path

from v5_xauusd_orb.config import load_config, Config

COST_XAUUSD = 0.0003
ANN = 252
DOW_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
SEASON_MAP = {12: 'Winter', 1: 'Winter', 2: 'Winter',
              3: 'Spring', 4: 'Spring', 5: 'Spring',
              6: 'Summer', 7: 'Summer', 8: 'Summer',
              9: 'Autumn', 10: 'Autumn', 11: 'Autumn'}


def load_tick_bars(cfg: Config) -> pd.DataFrame:
    path = Path(cfg.paths.tick_bar_file)
    df = pd.read_parquet(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    if df['timestamp'].dt.tz is None:
        df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
    else:
        df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
    df['hour'] = df['timestamp'].dt.hour
    df['date'] = df['timestamp'].dt.date
    df['dow'] = df['timestamp'].dt.dayofweek
    df = df[df['dow'] < 5]
    return df


def session_breakout_detailed(df: pd.DataFrame, cfg: Config,
                               rr_ratio: float = 2.0,
                               cost_rt: float = COST_XAUUSD) -> pd.DataFrame:
    strat = cfg.strategy
    range_mask = ((df['hour'] >= strat.asian_start_hour)
                  & (df['hour'] < strat.asian_end_hour))
    trade_mask = ((df['hour'] >= strat.trade_start_hour)
                  & (df['hour'] < strat.trade_end_hour))

    range_df = df[range_mask]
    trade_df = df[trade_mask]

    range_agg = range_df.groupby('date').agg(
        range_high=('high', 'max'),
        range_low=('low', 'min'),
        n_bars=('high', 'count'),
    )
    range_agg = range_agg[range_agg['n_bars'] >= 3]
    range_agg['range_size'] = range_agg['range_high'] - range_agg['range_low']
    range_agg = range_agg[range_agg['range_size'] > 0]

    trade_groups = {dt: grp for dt, grp in trade_df.groupby('date')}
    trades = []

    for dt, rng in range_agg.iterrows():
        rh, rl = rng['range_high'], rng['range_low']
        rsize = rng['range_size']
        mid_price = (rh + rl) / 2
        range_pct = rsize / mid_price
        if range_pct < strat.min_range_pct / 100 or range_pct > strat.max_range_pct / 100:
            continue

        day_bars = trade_groups.get(dt)
        if day_bars is None or len(day_bars) < 2:
            continue

        dt_date = pd.Timestamp(dt)
        dow, month, year = dt_date.dayofweek, dt_date.month, dt_date.year

        position = 0
        entry_price = sl_price = tp_price = 0.0

        for _, bar in day_bars.iterrows():
            if position == 0:
                if bar['high'] > rh:
                    position = 1; entry_price = rh
                    sl_price = rl; tp_price = rh + rr_ratio * rsize
                elif bar['low'] < rl:
                    position = -1; entry_price = rl
                    sl_price = rh; tp_price = rl - rr_ratio * rsize
            else:
                hit_tp = hit_sl = False
                if position == 1:
                    if bar['low'] <= sl_price: hit_sl = True
                    if bar['high'] >= tp_price: hit_tp = True
                else:
                    if bar['high'] >= sl_price: hit_sl = True
                    if bar['low'] <= tp_price: hit_tp = True

                if hit_sl and hit_tp:
                    hit_tp = False

                if hit_tp:
                    pnl_pct = abs(tp_price - entry_price) / entry_price
                    trades.append({
                        'date': dt, 'year': year, 'month': month, 'dow': dow,
                        'direction': 'L' if position == 1 else 'S',
                        'result': 'TP', 'entry': entry_price,
                        'exit': tp_price, 'range_high': rh, 'range_low': rl,
                        'range_size': rsize,
                        'gross_ret': pnl_pct, 'net_ret': pnl_pct - cost_rt,
                        'pnl_dollar': abs(tp_price - entry_price),
                    })
                    position = 0; break
                elif hit_sl:
                    pnl_pct = -abs(sl_price - entry_price) / entry_price
                    trades.append({
                        'date': dt, 'year': year, 'month': month, 'dow': dow,
                        'direction': 'L' if position == 1 else 'S',
                        'result': 'SL', 'entry': entry_price,
                        'exit': sl_price, 'range_high': rh, 'range_low': rl,
                        'range_size': rsize,
                        'gross_ret': pnl_pct, 'net_ret': pnl_pct - cost_rt,
                        'pnl_dollar': -abs(sl_price - entry_price),
                    })
                    position = 0; break

        if position != 0:
            last = day_bars['close'].iloc[-1]
            pnl_pct = position * (last - entry_price) / entry_price
            trades.append({
                'date': dt, 'year': year, 'month': month, 'dow': dow,
                'direction': 'L' if position == 1 else 'S',
                'result': 'TIME', 'entry': entry_price, 'exit': last,
                'range_high': rh, 'range_low': rl, 'range_size': rsize,
                'gross_ret': pnl_pct, 'net_ret': pnl_pct - cost_rt,
                'pnl_dollar': position * (last - entry_price),
            })

    return pd.DataFrame(trades) if trades else pd.DataFrame()


def stats_for_group(tdf):
    if len(tdf) == 0:
        return {}
    net = tdf['net_ret']
    wins = (net > 0).sum()
    n = len(tdf)
    return {
        'n': n,
        'win_rate': wins / n * 100,
        'avg_bps': net.mean() * 10000,
        'total_bps': net.sum() * 10000,
        'total_dollar': tdf['pnl_dollar'].sum(),
        'avg_dollar': tdf['pnl_dollar'].mean(),
        'sharpe': (net.mean() / net.std() * np.sqrt(ANN)
                   if net.std() > 0 else 0),
        'tp_pct': (tdf['result'] == 'TP').mean() * 100,
        'sl_pct': (tdf['result'] == 'SL').mean() * 100,
        'time_pct': (tdf['result'] == 'TIME').mean() * 100,
        'avg_range': tdf['range_size'].mean(),
    }


def print_section(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def main():
    parser = argparse.ArgumentParser(
        description='XAUUSD ORB seasonality analysis (v5)')
    parser.add_argument('--config', type=str, default=None,
                        help='Path to alternative config.yaml')
    args = parser.parse_args()

    cfg = load_config(args.config)
    strat = cfg.strategy

    print("Loading XAUUSD tick bars...")
    df = load_tick_bars(cfg)
    print(f"  {len(df):,} bars, {df['timestamp'].iloc[0].date()} "
          f"to {df['timestamp'].iloc[-1].date()}")

    rr_ratios = [1.0, 1.5, 2.0, 2.5, 3.0]
    baseline_rr = strat.rr_ratio

    print(f"\nRunning backtests for RR ratios: {rr_ratios}")
    all_trades = {}
    for rr in rr_ratios:
        tdf = session_breakout_detailed(df, cfg, rr_ratio=rr)
        all_trades[rr] = tdf
        n = len(tdf)
        avg = tdf['net_ret'].mean() * 10000 if n > 0 else 0
        print(f"  RR={rr:.1f}: {n} trades, avg {avg:+.1f} bps")

    trades = all_trades[baseline_rr]

    # 1. WEEKDAY
    print_section(f"WEEKDAY ANALYSIS (RR={baseline_rr}, Asian->London)")
    header = (f"  {'Day':>5s}  {'N':>5s}  {'Win%':>5s}  {'AvgBps':>7s}"
              f"  {'TotBps':>8s}  {'$/oz':>7s}  {'Sharpe':>6s}"
              f"  {'TP%':>5s}  {'SL%':>5s}  {'Time%':>5s}  {'AvgRng':>7s}")
    print(f"\n{header}")

    for dow in range(5):
        sub = trades[trades['dow'] == dow]
        s = stats_for_group(sub)
        if s:
            print(f"  {DOW_NAMES[dow]:>5s}  {s['n']:>5d}  "
                  f"{s['win_rate']:>5.1f}  {s['avg_bps']:>+7.1f}"
                  f"  {s['total_bps']:>+8.1f}  {s['avg_dollar']:>+7.2f}"
                  f"  {s['sharpe']:>6.2f}  {s['tp_pct']:>5.1f}"
                  f"  {s['sl_pct']:>5.1f}  {s['time_pct']:>5.1f}"
                  f"  ${s['avg_range']:>6.1f}")

    s_all = stats_for_group(trades)
    print(f"  {'ALL':>5s}  {s_all['n']:>5d}  "
          f"{s_all['win_rate']:>5.1f}  {s_all['avg_bps']:>+7.1f}"
          f"  {s_all['total_bps']:>+8.1f}  {s_all['avg_dollar']:>+7.2f}"
          f"  {s_all['sharpe']:>6.2f}  {s_all['tp_pct']:>5.1f}"
          f"  {s_all['sl_pct']:>5.1f}  {s_all['time_pct']:>5.1f}"
          f"  ${s_all['avg_range']:>6.1f}")

    # Per-year weekday heatmap
    print(f"\n  Weekday consistency (net bps per year):")
    print(f"  {'Year':>6s}", end="")
    for dow in range(5):
        print(f"  {DOW_NAMES[dow]:>7s}", end="")
    print(f"  {'Total':>7s}")
    for year in sorted(trades['year'].unique()):
        yt = trades[trades['year'] == year]
        print(f"  {year:>6d}", end="")
        for dow in range(5):
            sub = yt[yt['dow'] == dow]
            bps = sub['net_ret'].sum() * 10000 if len(sub) > 0 else 0
            print(f"  {bps:>+7.1f}", end="")
        print(f"  {yt['net_ret'].sum() * 10000:>+7.1f}")

    # 2. MONTHLY
    print_section(f"MONTHLY ANALYSIS (RR={baseline_rr}, Asian->London)")
    print(f"\n  {'Month':>5s}  {'N':>5s}  {'Win%':>5s}  {'AvgBps':>7s}"
          f"  {'TotBps':>8s}  {'$/oz':>7s}  {'Sharpe':>6s}"
          f"  {'TP%':>5s}  {'SL%':>5s}  {'AvgRng':>7s}")
    for m in range(1, 13):
        sub = trades[trades['month'] == m]
        s = stats_for_group(sub)
        if s:
            print(f"  {MONTH_NAMES[m - 1]:>5s}  {s['n']:>5d}  "
                  f"{s['win_rate']:>5.1f}  {s['avg_bps']:>+7.1f}"
                  f"  {s['total_bps']:>+8.1f}  {s['avg_dollar']:>+7.2f}"
                  f"  {s['sharpe']:>6.2f}  {s['tp_pct']:>5.1f}"
                  f"  {s['sl_pct']:>5.1f}  ${s['avg_range']:>6.1f}")

    trades_c = trades.copy()
    trades_c['season'] = trades_c['month'].map(SEASON_MAP)
    print(f"\n  Seasonal summary:")
    print(f"  {'Season':>8s}  {'N':>5s}  {'Win%':>5s}  {'AvgBps':>7s}"
          f"  {'$/oz':>7s}  {'Sharpe':>6s}")
    for season in ['Winter', 'Spring', 'Summer', 'Autumn']:
        sub = trades_c[trades_c['season'] == season]
        s = stats_for_group(sub)
        if s:
            print(f"  {season:>8s}  {s['n']:>5d}  {s['win_rate']:>5.1f}"
                  f"  {s['avg_bps']:>+7.1f}  {s['avg_dollar']:>+7.2f}"
                  f"  {s['sharpe']:>6.2f}")

    # 3. OPTIMAL RR BY WEEKDAY
    print_section("OPTIMAL RR RATIO BY WEEKDAY")
    print(f"\n  RR sweep across weekdays (avg net bps per trade):")
    print(f"  {'RR':>5s}", end="")
    for dow in range(5):
        print(f"  {DOW_NAMES[dow]:>7s}", end="")
    print(f"  {'ALL':>7s}")

    best_rr_by_dow = {}
    for rr in rr_ratios:
        tdf = all_trades[rr]
        print(f"  {rr:>5.1f}", end="")
        for dow in range(5):
            sub = tdf[tdf['dow'] == dow]
            avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
            print(f"  {avg:>+7.1f}", end="")
            key = DOW_NAMES[dow]
            if key not in best_rr_by_dow or avg > best_rr_by_dow[key][1]:
                best_rr_by_dow[key] = (rr, avg)
        avg_all = tdf['net_ret'].mean() * 10000 if len(tdf) > 0 else 0
        print(f"  {avg_all:>+7.1f}")

    print(f"\n  Best RR per weekday:")
    for dow in range(5):
        key = DOW_NAMES[dow]
        rr, bps = best_rr_by_dow[key]
        print(f"    {key}: RR={rr:.1f} ({bps:+.1f} bps)")

    # 4. OPTIMAL RR BY MONTH
    print_section("OPTIMAL RR RATIO BY MONTH")
    print(f"\n  RR sweep across months (avg net bps per trade):")
    print(f"  {'RR':>5s}", end="")
    for m in range(1, 13):
        print(f"  {MONTH_NAMES[m - 1]:>5s}", end="")
    print()

    best_rr_by_month = {}
    for rr in rr_ratios:
        tdf = all_trades[rr]
        print(f"  {rr:>5.1f}", end="")
        for m in range(1, 13):
            sub = tdf[tdf['month'] == m]
            avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
            print(f"  {avg:>+5.1f}", end="")
            key = MONTH_NAMES[m - 1]
            if key not in best_rr_by_month or avg > best_rr_by_month[key][1]:
                best_rr_by_month[key] = (rr, avg)
        print()

    print(f"\n  Best RR per month:")
    for m in range(1, 13):
        key = MONTH_NAMES[m - 1]
        rr, bps = best_rr_by_month[key]
        print(f"    {key}: RR={rr:.1f} ({bps:+.1f} bps)")

    # 5. RANGE SIZE
    print_section(f"RANGE SIZE ANALYSIS (RR={baseline_rr})")
    tc = trades.copy()
    tc['range_q'] = pd.qcut(tc['range_size'], 5,
                              labels=['Q1(tiny)', 'Q2', 'Q3', 'Q4', 'Q5(wide)'])
    print(f"\n  Performance by Asian range size quintile:")
    print(f"  {'Quintile':>10s}  {'Range$':>8s}  {'N':>5s}  {'Win%':>5s}"
          f"  {'AvgBps':>7s}  {'$/oz':>7s}  {'Sharpe':>6s}")
    for q in ['Q1(tiny)', 'Q2', 'Q3', 'Q4', 'Q5(wide)']:
        sub = tc[tc['range_q'] == q]
        lo, hi = sub['range_size'].min(), sub['range_size'].max()
        s = stats_for_group(sub)
        if s:
            print(f"  {q:>10s}  ${lo:.0f}-{hi:.0f}  {s['n']:>5d}"
                  f"  {s['win_rate']:>5.1f}  {s['avg_bps']:>+7.1f}"
                  f"  {s['avg_dollar']:>+7.2f}  {s['sharpe']:>6.2f}")

    # 6. LONG vs SHORT
    print_section(f"LONG vs SHORT BY WEEKDAY AND MONTH (RR={baseline_rr})")
    print(f"\n  By weekday:")
    print(f"  {'Day':>5s}  {'L_bps':>7s}  {'S_bps':>7s}  {'L_win':>6s}"
          f"  {'S_win':>6s}  {'L_n':>5s}  {'S_n':>5s}")
    for dow in range(5):
        lo = trades[(trades['dow'] == dow) & (trades['direction'] == 'L')]
        sh = trades[(trades['dow'] == dow) & (trades['direction'] == 'S')]
        lb = lo['net_ret'].mean() * 10000 if len(lo) > 0 else 0
        sb = sh['net_ret'].mean() * 10000 if len(sh) > 0 else 0
        lw = (lo['net_ret'] > 0).mean() * 100 if len(lo) > 0 else 0
        sw = (sh['net_ret'] > 0).mean() * 100 if len(sh) > 0 else 0
        print(f"  {DOW_NAMES[dow]:>5s}  {lb:>+7.1f}  {sb:>+7.1f}"
              f"  {lw:>5.1f}%  {sw:>5.1f}%  {len(lo):>5d}  {len(sh):>5d}")

    # 7. WALK-FORWARD: weekday RR
    print_section("WALK-FORWARD: weekday RR optimization "
                  "(1yr train / 1yr test)")
    years = sorted(trades['year'].unique())
    wf = []
    for i in range(len(years) - 1):
        trn, tst = years[i], years[i + 1]
        dw_best = {}
        for dow in range(5):
            best_s, best_r = -9999, baseline_rr
            for rr in rr_ratios:
                sub = all_trades[rr]
                sub = sub[(sub['year'] == trn) & (sub['dow'] == dow)]
                avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
                if avg > best_s: best_s = avg; best_r = rr
            dw_best[dow] = best_r

        adapt_oos = []
        for dow in range(5):
            sub = all_trades[dw_best[dow]]
            sub = sub[(sub['year'] == tst) & (sub['dow'] == dow)]
            for _, r in sub.iterrows():
                adapt_oos.append(r.to_dict())

        fixed_oos = trades[trades['year'] == tst]
        if adapt_oos and len(fixed_oos) > 0:
            aa = np.mean([t['net_ret'] for t in adapt_oos]) * 10000
            fa = fixed_oos['net_ret'].mean() * 10000
            wf.append({'train': trn, 'test': tst,
                       'fixed': fa, 'adapt': aa, 'rr': dw_best})

    if wf:
        print(f"\n  {'Train':>6s}  {'Test':>6s}  {'Fixed':>7s}"
              f"  {'Adapt':>7s}  {'Diff':>6s}  RR [Mon-Fri]")
        aw = 0
        for r in wf:
            d = r['adapt'] - r['fixed']
            rrs = ",".join(f"{r['rr'][i]:.1f}" for i in range(5))
            m = " <" if d > 0 else ""
            print(f"  {r['train']:>6d}  {r['test']:>6d}  {r['fixed']:>+7.1f}"
                  f"  {r['adapt']:>+7.1f}  {d:>+6.1f}  [{rrs}]{m}")
            if d > 0: aw += 1
        aa = np.mean([r['adapt'] for r in wf])
        fa = np.mean([r['fixed'] for r in wf])
        print(f"\n  Adaptive beats fixed in {aw}/{len(wf)} OOS years")
        print(f"  OOS avg: Fixed={fa:+.1f} bps, Adaptive={aa:+.1f} bps")

    # 8. WALK-FORWARD: monthly RR
    print_section("WALK-FORWARD: monthly RR optimization "
                  "(1yr train / 1yr test)")
    wfm = []
    for i in range(len(years) - 1):
        trn, tst = years[i], years[i + 1]
        mb = {}
        for m in range(1, 13):
            best_s, best_r = -9999, baseline_rr
            for rr in rr_ratios:
                sub = all_trades[rr]
                sub = sub[(sub['year'] == trn) & (sub['month'] == m)]
                avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
                if avg > best_s: best_s = avg; best_r = rr
            mb[m] = best_r

        adapt_oos = []
        for m in range(1, 13):
            sub = all_trades[mb[m]]
            sub = sub[(sub['year'] == tst) & (sub['month'] == m)]
            for _, r in sub.iterrows():
                adapt_oos.append(r.to_dict())

        fixed_oos = trades[trades['year'] == tst]
        if adapt_oos and len(fixed_oos) > 0:
            aa = np.mean([t['net_ret'] for t in adapt_oos]) * 10000
            fa = fixed_oos['net_ret'].mean() * 10000
            wfm.append({'train': trn, 'test': tst,
                        'fixed': fa, 'adapt': aa})

    if wfm:
        print(f"\n  {'Train':>6s}  {'Test':>6s}  {'Fixed':>7s}"
              f"  {'Adapt':>7s}  {'Diff':>6s}")
        aw = 0
        for r in wfm:
            d = r['adapt'] - r['fixed']
            m = " <" if d > 0 else ""
            print(f"  {r['train']:>6d}  {r['test']:>6d}  {r['fixed']:>+7.1f}"
                  f"  {r['adapt']:>+7.1f}  {d:>+6.1f}{m}")
            if d > 0: aw += 1
        aa = np.mean([r['adapt'] for r in wfm])
        fa = np.mean([r['fixed'] for r in wfm])
        print(f"\n  Monthly adaptive beats fixed "
              f"in {aw}/{len(wfm)} OOS years")
        print(f"  OOS avg: Fixed={fa:+.1f} bps, Adaptive={aa:+.1f} bps")

    # 9. SKIP-DAY/MONTH
    print_section(f"SKIP-DAY / SKIP-MONTH ANALYSIS (RR={baseline_rr})")
    print("\n  What if we skip the worst weekday?")
    dow_avgs = []
    for dow in range(5):
        sub = trades[trades['dow'] == dow]
        avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
        dow_avgs.append((DOW_NAMES[dow], avg, dow))
    dow_avgs.sort(key=lambda x: x[1])
    worst = dow_avgs[0]
    filt = trades[trades['dow'] != worst[2]]
    sf = stats_for_group(filt)
    print(f"  Worst day: {worst[0]} ({worst[1]:+.1f} bps avg)")
    print(f"  Skipping {worst[0]}:  {sf['n']} trades, "
          f"avg {sf['avg_bps']:+.1f} bps, Sharpe {sf['sharpe']:.2f}")
    print(f"  All days: {s_all['n']} trades, "
          f"avg {s_all['avg_bps']:+.1f} bps, Sharpe {s_all['sharpe']:.2f}")

    print(f"\n  Current skip_weekdays in config: {strat.skip_weekdays}")
    if worst[2] not in strat.skip_weekdays:
        print(f"  --> Consider adding {worst[2]} ({worst[0]}) "
              f"to skip_weekdays in config.yaml")

    print("\n  What if we skip the worst month?")
    m_avgs = []
    for m in range(1, 13):
        sub = trades[trades['month'] == m]
        avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
        m_avgs.append((MONTH_NAMES[m - 1], avg, m))
    m_avgs.sort(key=lambda x: x[1])
    worst_m = m_avgs[0]
    filt_m = trades[trades['month'] != worst_m[2]]
    sfm = stats_for_group(filt_m)
    print(f"  Worst month: {worst_m[0]} ({worst_m[1]:+.1f} bps avg)")
    print(f"  Skipping {worst_m[0]}:  {sfm['n']} trades, "
          f"avg {sfm['avg_bps']:+.1f} bps, Sharpe {sfm['sharpe']:.2f}")
    print(f"  All months: {s_all['n']} trades, "
          f"avg {s_all['avg_bps']:+.1f} bps, Sharpe {s_all['sharpe']:.2f}")

    print_section("CONCLUSION")
    print("""
  Key question: do weekday/seasonal patterns survive out-of-sample?

  If adaptive OOS < fixed OOS: the variations are noise, stick with
  fixed RR every day. Adding complexity without OOS improvement
  just increases the chance of overfitting.

  If a specific day/month is consistently negative across most years,
  skipping it may be defensible even without formal optimization.
""")


if __name__ == "__main__":
    main()
