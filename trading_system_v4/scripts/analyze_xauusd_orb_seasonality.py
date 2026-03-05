"""
analyze_xauusd_orb_seasonality.py

Investigates weekday and seasonal (monthly) variations in the
XAUUSD Asian Range -> London Breakout strategy.

Questions answered:
  1. Which weekdays are best/worst?
  2. Which months are best/worst?
  3. Does optimal RR ratio differ by weekday or month?
  4. Should any days/months be skipped entirely?
  5. Is range size a useful filter per season?

Uses the same fast_session_breakout logic as the validated backtest.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"

COST_XAUUSD = 0.0003  # round-trip cost as fraction
ANN = 252
DOW_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
SEASON_MAP = {12: 'Winter', 1: 'Winter', 2: 'Winter',
              3: 'Spring', 4: 'Spring', 5: 'Spring',
              6: 'Summer', 7: 'Summer', 8: 'Summer',
              9: 'Autumn', 10: 'Autumn', 11: 'Autumn'}


def load_tick_bars():
    path = DATA_DIR / "xauusd_1000t_bars.parquet"
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


def session_breakout_detailed(df, range_start_h=0, range_end_h=6,
                               trade_start_h=8, trade_end_h=16,
                               rr_ratio=2.0, cost_rt=COST_XAUUSD):
    """
    Like fast_session_breakout but returns richer per-trade data
    including weekday, month, range size in dollars, dollar PnL.
    """
    range_mask = (df['hour'] >= range_start_h) & (df['hour'] < range_end_h)
    trade_mask = (df['hour'] >= trade_start_h) & (df['hour'] < trade_end_h)

    range_df = df[range_mask]
    trade_df = df[trade_mask]

    range_agg = range_df.groupby('date').agg(
        range_high=('high', 'max'),
        range_low=('low', 'min'),
        n_bars=('high', 'count')
    )
    range_agg = range_agg[range_agg['n_bars'] >= 3]
    range_agg['range_size'] = range_agg['range_high'] - range_agg['range_low']
    range_agg = range_agg[range_agg['range_size'] > 0]

    trade_groups = {dt: grp for dt, grp in trade_df.groupby('date')}

    trades = []

    for dt, rng in range_agg.iterrows():
        rh = rng['range_high']
        rl = rng['range_low']
        rsize = rng['range_size']
        mid_price = (rh + rl) / 2
        range_pct = rsize / mid_price

        if range_pct < 0.0001 or range_pct > 0.02:
            continue

        day_bars = trade_groups.get(dt)
        if day_bars is None or len(day_bars) < 2:
            continue

        dt_date = pd.Timestamp(dt)
        dow = dt_date.dayofweek
        month = dt_date.month
        year = dt_date.year

        position = 0
        entry_price = sl_price = tp_price = 0

        for _, bar in day_bars.iterrows():
            if position == 0:
                if bar['high'] > rh:
                    position = 1
                    entry_price = rh
                    sl_price = rl
                    tp_price = entry_price + rr_ratio * rsize
                elif bar['low'] < rl:
                    position = -1
                    entry_price = rl
                    sl_price = rh
                    tp_price = entry_price - rr_ratio * rsize
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
                    pnl_dollar = abs(tp_price - entry_price)
                    trades.append({
                        'date': dt, 'year': year, 'month': month, 'dow': dow,
                        'direction': 'L' if position == 1 else 'S',
                        'result': 'TP',
                        'entry': entry_price,
                        'exit': tp_price if position == 1 else tp_price,
                        'range_high': rh, 'range_low': rl,
                        'range_size': rsize,
                        'gross_ret': pnl_pct,
                        'net_ret': pnl_pct - cost_rt,
                        'pnl_dollar': pnl_dollar,
                    })
                    position = 0; break
                elif hit_sl:
                    pnl_pct = -abs(sl_price - entry_price) / entry_price
                    pnl_dollar = -abs(sl_price - entry_price)
                    trades.append({
                        'date': dt, 'year': year, 'month': month, 'dow': dow,
                        'direction': 'L' if position == 1 else 'S',
                        'result': 'SL',
                        'entry': entry_price, 'exit': sl_price,
                        'range_high': rh, 'range_low': rl,
                        'range_size': rsize,
                        'gross_ret': pnl_pct,
                        'net_ret': pnl_pct - cost_rt,
                        'pnl_dollar': pnl_dollar,
                    })
                    position = 0; break

        if position != 0:
            last = day_bars['close'].iloc[-1]
            pnl_pct = position * (last - entry_price) / entry_price
            pnl_dollar = position * (last - entry_price)
            trades.append({
                'date': dt, 'year': year, 'month': month, 'dow': dow,
                'direction': 'L' if position == 1 else 'S',
                'result': 'TIME',
                'entry': entry_price, 'exit': last,
                'range_high': rh, 'range_low': rl,
                'range_size': rsize,
                'gross_ret': pnl_pct,
                'net_ret': pnl_pct - cost_rt,
                'pnl_dollar': pnl_dollar,
            })

    return pd.DataFrame(trades) if trades else pd.DataFrame()


def stats_for_group(tdf):
    """Compute summary stats for a group of trades."""
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
        'sharpe': net.mean() / net.std() * np.sqrt(ANN) if net.std() > 0 else 0,
        'tp_pct': (tdf['result'] == 'TP').mean() * 100,
        'sl_pct': (tdf['result'] == 'SL').mean() * 100,
        'time_pct': (tdf['result'] == 'TIME').mean() * 100,
        'avg_range': tdf['range_size'].mean(),
    }


def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def main():
    print("Loading XAUUSD tick bars...")
    df = load_tick_bars()
    print(f"  {len(df):,} bars, {df['timestamp'].iloc[0].date()} to {df['timestamp'].iloc[-1].date()}")

    rr_ratios = [1.0, 1.5, 2.0, 2.5, 3.0]

    # ── 1. Generate trades for each RR ratio ──────────────────────────────────
    print("\nRunning backtests for RR ratios:", rr_ratios)
    all_trades = {}
    for rr in rr_ratios:
        tdf = session_breakout_detailed(df, rr_ratio=rr)
        all_trades[rr] = tdf
        n = len(tdf)
        avg = tdf['net_ret'].mean() * 10000 if n > 0 else 0
        print(f"  RR={rr:.1f}: {n} trades, avg {avg:+.1f} bps")

    # Use RR=2.0 as baseline for the weekday/month analysis
    baseline_rr = 2.0
    trades = all_trades[baseline_rr]
    n_years = trades['year'].nunique()

    # ── 2. WEEKDAY ANALYSIS (RR=2.0) ─────────────────────────────────────────
    print_section("WEEKDAY ANALYSIS (RR=2.0, Asian->London)")

    print(f"\n  {'Day':>5s}  {'N':>5s}  {'Win%':>5s}  {'AvgBps':>7s}  {'TotBps':>8s}"
          f"  {'$/oz':>7s}  {'Sharpe':>6s}  {'TP%':>5s}  {'SL%':>5s}  {'Time%':>5s}  {'AvgRng':>7s}")
    print(f"  {'---':>5s}  {'---':>5s}  {'---':>5s}  {'---':>7s}  {'---':>8s}"
          f"  {'---':>7s}  {'---':>6s}  {'---':>5s}  {'---':>5s}  {'---':>5s}  {'---':>7s}")

    for dow in range(5):
        subset = trades[trades['dow'] == dow]
        s = stats_for_group(subset)
        if s:
            print(f"  {DOW_NAMES[dow]:>5s}  {s['n']:>5d}  {s['win_rate']:>5.1f}  {s['avg_bps']:>+7.1f}"
                  f"  {s['total_bps']:>+8.1f}  {s['avg_dollar']:>+7.2f}  {s['sharpe']:>6.2f}"
                  f"  {s['tp_pct']:>5.1f}  {s['sl_pct']:>5.1f}  {s['time_pct']:>5.1f}"
                  f"  ${s['avg_range']:>6.1f}")

    # Overall
    s_all = stats_for_group(trades)
    print(f"  {'ALL':>5s}  {s_all['n']:>5d}  {s_all['win_rate']:>5.1f}  {s_all['avg_bps']:>+7.1f}"
          f"  {s_all['total_bps']:>+8.1f}  {s_all['avg_dollar']:>+7.2f}  {s_all['sharpe']:>6.2f}"
          f"  {s_all['tp_pct']:>5.1f}  {s_all['sl_pct']:>5.1f}  {s_all['time_pct']:>5.1f}"
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
        print(f"  {yt['net_ret'].sum()*10000:>+7.1f}")

    # ── 3. MONTHLY / SEASONAL ANALYSIS (RR=2.0) ──────────────────────────────
    print_section("MONTHLY ANALYSIS (RR=2.0, Asian->London)")

    print(f"\n  {'Month':>5s}  {'N':>5s}  {'Win%':>5s}  {'AvgBps':>7s}  {'TotBps':>8s}"
          f"  {'$/oz':>7s}  {'Sharpe':>6s}  {'TP%':>5s}  {'SL%':>5s}  {'AvgRng':>7s}")
    print(f"  {'---':>5s}  {'---':>5s}  {'---':>5s}  {'---':>7s}  {'---':>8s}"
          f"  {'---':>7s}  {'---':>6s}  {'---':>5s}  {'---':>5s}  {'---':>7s}")

    for m in range(1, 13):
        subset = trades[trades['month'] == m]
        s = stats_for_group(subset)
        if s:
            print(f"  {MONTH_NAMES[m-1]:>5s}  {s['n']:>5d}  {s['win_rate']:>5.1f}  {s['avg_bps']:>+7.1f}"
                  f"  {s['total_bps']:>+8.1f}  {s['avg_dollar']:>+7.2f}  {s['sharpe']:>6.2f}"
                  f"  {s['tp_pct']:>5.1f}  {s['sl_pct']:>5.1f}  ${s['avg_range']:>6.1f}")

    # Seasonal (quarter)
    trades_c = trades.copy()
    trades_c['season'] = trades_c['month'].map(SEASON_MAP)

    print(f"\n  Seasonal summary:")
    print(f"  {'Season':>8s}  {'N':>5s}  {'Win%':>5s}  {'AvgBps':>7s}  {'$/oz':>7s}  {'Sharpe':>6s}")
    for season in ['Winter', 'Spring', 'Summer', 'Autumn']:
        subset = trades_c[trades_c['season'] == season]
        s = stats_for_group(subset)
        if s:
            print(f"  {season:>8s}  {s['n']:>5d}  {s['win_rate']:>5.1f}  {s['avg_bps']:>+7.1f}"
                  f"  {s['avg_dollar']:>+7.2f}  {s['sharpe']:>6.2f}")

    # Per-year monthly heatmap
    print(f"\n  Monthly consistency (net bps per year):")
    print(f"  {'Year':>6s}", end="")
    for m in range(1, 13):
        print(f"  {MONTH_NAMES[m-1]:>5s}", end="")
    print(f"  {'Total':>7s}")

    for year in sorted(trades['year'].unique()):
        yt = trades[trades['year'] == year]
        print(f"  {year:>6d}", end="")
        for m in range(1, 13):
            sub = yt[yt['month'] == m]
            bps = sub['net_ret'].sum() * 10000 if len(sub) > 0 else 0
            print(f"  {bps:>+5.0f}", end="")
        print(f"  {yt['net_ret'].sum()*10000:>+7.1f}")

    # ── 4. OPTIMAL RR BY WEEKDAY ──────────────────────────────────────────────
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

    # ── 5. OPTIMAL RR BY MONTH ────────────────────────────────────────────────
    print_section("OPTIMAL RR RATIO BY MONTH")

    print(f"\n  RR sweep across months (avg net bps per trade):")
    print(f"  {'RR':>5s}", end="")
    for m in range(1, 13):
        print(f"  {MONTH_NAMES[m-1]:>5s}", end="")
    print()

    best_rr_by_month = {}
    for rr in rr_ratios:
        tdf = all_trades[rr]
        print(f"  {rr:>5.1f}", end="")
        for m in range(1, 13):
            sub = tdf[tdf['month'] == m]
            avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
            print(f"  {avg:>+5.1f}", end="")
            key = MONTH_NAMES[m-1]
            if key not in best_rr_by_month or avg > best_rr_by_month[key][1]:
                best_rr_by_month[key] = (rr, avg)
        print()

    print(f"\n  Best RR per month:")
    for m in range(1, 13):
        key = MONTH_NAMES[m-1]
        rr, bps = best_rr_by_month[key]
        print(f"    {key}: RR={rr:.1f} ({bps:+.1f} bps)")

    # ── 6. RANGE SIZE ANALYSIS ────────────────────────────────────────────────
    print_section("RANGE SIZE ANALYSIS (RR=2.0)")

    trades_c = trades.copy()
    trades_c['range_q'] = pd.qcut(trades_c['range_size'], 5,
                                    labels=['Q1(tiny)', 'Q2', 'Q3', 'Q4', 'Q5(wide)'])

    print(f"\n  Performance by Asian range size quintile:")
    print(f"  {'Quintile':>10s}  {'Range$':>8s}  {'N':>5s}  {'Win%':>5s}  {'AvgBps':>7s}"
          f"  {'$/oz':>7s}  {'Sharpe':>6s}")
    for q in ['Q1(tiny)', 'Q2', 'Q3', 'Q4', 'Q5(wide)']:
        sub = trades_c[trades_c['range_q'] == q]
        rng_lo = sub['range_size'].min()
        rng_hi = sub['range_size'].max()
        s = stats_for_group(sub)
        if s:
            print(f"  {q:>10s}  ${rng_lo:.0f}-{rng_hi:.0f}  {s['n']:>5d}  {s['win_rate']:>5.1f}"
                  f"  {s['avg_bps']:>+7.1f}  {s['avg_dollar']:>+7.2f}  {s['sharpe']:>6.2f}")

    # Range size by month
    print(f"\n  Average Asian range size ($) by month:")
    for m in range(1, 13):
        sub = trades[trades['month'] == m]
        if len(sub) > 0:
            print(f"    {MONTH_NAMES[m-1]:>5s}: ${sub['range_size'].mean():>6.1f}"
                  f"  (median ${sub['range_size'].median():>6.1f})")

    # ── 7. DIRECTION SPLITS ──────────────────────────────────────────────────
    print_section("LONG vs SHORT BY WEEKDAY AND MONTH (RR=2.0)")

    print(f"\n  By weekday:")
    print(f"  {'Day':>5s}  {'L_bps':>7s}  {'S_bps':>7s}  {'L_win':>6s}  {'S_win':>6s}"
          f"  {'L_n':>5s}  {'S_n':>5s}")
    for dow in range(5):
        longs = trades[(trades['dow'] == dow) & (trades['direction'] == 'L')]
        shorts = trades[(trades['dow'] == dow) & (trades['direction'] == 'S')]
        l_bps = longs['net_ret'].mean() * 10000 if len(longs) > 0 else 0
        s_bps = shorts['net_ret'].mean() * 10000 if len(shorts) > 0 else 0
        l_win = (longs['net_ret'] > 0).mean() * 100 if len(longs) > 0 else 0
        s_win = (shorts['net_ret'] > 0).mean() * 100 if len(shorts) > 0 else 0
        print(f"  {DOW_NAMES[dow]:>5s}  {l_bps:>+7.1f}  {s_bps:>+7.1f}  {l_win:>5.1f}%"
              f"  {s_win:>5.1f}%  {len(longs):>5d}  {len(shorts):>5d}")

    print(f"\n  By month:")
    print(f"  {'Mon':>5s}  {'L_bps':>7s}  {'S_bps':>7s}  {'L_win':>6s}  {'S_win':>6s}"
          f"  {'L_n':>5s}  {'S_n':>5s}")
    for m in range(1, 13):
        longs = trades[(trades['month'] == m) & (trades['direction'] == 'L')]
        shorts = trades[(trades['month'] == m) & (trades['direction'] == 'S')]
        l_bps = longs['net_ret'].mean() * 10000 if len(longs) > 0 else 0
        s_bps = shorts['net_ret'].mean() * 10000 if len(shorts) > 0 else 0
        l_win = (longs['net_ret'] > 0).mean() * 100 if len(longs) > 0 else 0
        s_win = (shorts['net_ret'] > 0).mean() * 100 if len(shorts) > 0 else 0
        print(f"  {MONTH_NAMES[m-1]:>5s}  {l_bps:>+7.1f}  {s_bps:>+7.1f}  {l_win:>5.1f}%"
              f"  {s_win:>5.1f}%  {len(longs):>5d}  {len(shorts):>5d}")

    # ── 8. ADAPTIVE STRATEGY TEST ─────────────────────────────────────────────
    print_section("ADAPTIVE STRATEGY TEST: Best-RR-per-day vs Fixed RR=2.0")

    # Build adaptive trades: for each day, use the best RR from the sweep
    # BUT this is in-sample! So also do walk-forward version
    print("\n  NOTE: In-sample fit. Cross-checking with walk-forward below.\n")

    # In-sample adaptive
    adaptive_trades = []
    for _, row in trades.iterrows():
        dow = row['dow']
        best_rr = best_rr_by_dow[DOW_NAMES[dow]][0]
        # Get the trade for this date from the best-RR set
        best_tdf = all_trades[best_rr]
        date_match = best_tdf[best_tdf['date'] == row['date']]
        if len(date_match) > 0:
            adaptive_trades.append(date_match.iloc[0].to_dict())

    adaptive_df = pd.DataFrame(adaptive_trades)
    if len(adaptive_df) > 0:
        s_fixed = stats_for_group(trades)
        s_adapt = stats_for_group(adaptive_df)
        print(f"  {'Strategy':>20s}  {'N':>5s}  {'Win%':>5s}  {'AvgBps':>7s}  {'TotBps':>8s}  {'Sharpe':>6s}")
        print(f"  {'Fixed RR=2.0':>20s}  {s_fixed['n']:>5d}  {s_fixed['win_rate']:>5.1f}"
              f"  {s_fixed['avg_bps']:>+7.1f}  {s_fixed['total_bps']:>+8.1f}  {s_fixed['sharpe']:>6.2f}")
        print(f"  {'Adaptive RR/weekday':>20s}  {s_adapt['n']:>5d}  {s_adapt['win_rate']:>5.1f}"
              f"  {s_adapt['avg_bps']:>+7.1f}  {s_adapt['total_bps']:>+8.1f}  {s_adapt['sharpe']:>6.2f}")

    # ── 9. WALK-FORWARD: does day-of-week optimization hold OOS? ──────────────
    print_section("WALK-FORWARD: weekday RR optimization (1yr train / 1yr test)")

    years = sorted(trades['year'].unique())
    wf_results = []
    for i in range(len(years) - 1):
        train_year = years[i]
        test_year = years[i + 1]

        # Find best RR per weekday in training year
        dw_best = {}
        for dow in range(5):
            best_score = -9999
            best_r = 2.0
            for rr in rr_ratios:
                tdf = all_trades[rr]
                sub = tdf[(tdf['year'] == train_year) & (tdf['dow'] == dow)]
                avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
                if avg > best_score:
                    best_score = avg
                    best_r = rr
            dw_best[dow] = best_r

        # Apply to test year
        adaptive_oos = []
        for dow in range(5):
            rr = dw_best[dow]
            tdf = all_trades[rr]
            sub = tdf[(tdf['year'] == test_year) & (tdf['dow'] == dow)]
            for _, row in sub.iterrows():
                adaptive_oos.append(row.to_dict())

        # Fixed RR=2.0 test year
        fixed_oos = trades[trades['year'] == test_year]

        if len(adaptive_oos) > 0 and len(fixed_oos) > 0:
            adapt_avg = np.mean([t['net_ret'] for t in adaptive_oos]) * 10000
            fixed_avg = fixed_oos['net_ret'].mean() * 10000
            wf_results.append({
                'train': train_year, 'test': test_year,
                'fixed_bps': fixed_avg, 'adapt_bps': adapt_avg,
                'rr_used': dw_best,
            })

    if wf_results:
        print(f"\n  {'Train':>6s}  {'Test':>6s}  {'Fixed':>7s}  {'Adapt':>7s}  {'Diff':>6s}  RR used [Mon-Fri]")
        adapt_wins = 0
        for r in wf_results:
            diff = r['adapt_bps'] - r['fixed_bps']
            rr_str = ",".join(f"{r['rr_used'][d]:.1f}" for d in range(5))
            marker = " <" if diff > 0 else ""
            print(f"  {r['train']:>6d}  {r['test']:>6d}  {r['fixed_bps']:>+7.1f}"
                  f"  {r['adapt_bps']:>+7.1f}  {diff:>+6.1f}  [{rr_str}]{marker}")
            if diff > 0:
                adapt_wins += 1

        adapt_avg = np.mean([r['adapt_bps'] for r in wf_results])
        fixed_avg = np.mean([r['fixed_bps'] for r in wf_results])
        print(f"\n  Adaptive beats fixed in {adapt_wins}/{len(wf_results)} OOS years")
        print(f"  OOS average: Fixed={fixed_avg:+.1f} bps, Adaptive={adapt_avg:+.1f} bps")

    # ── 10. WALK-FORWARD: monthly RR optimization ────────────────────────────
    print_section("WALK-FORWARD: monthly RR optimization (1yr train / 1yr test)")

    wf_month_results = []
    for i in range(len(years) - 1):
        train_year = years[i]
        test_year = years[i + 1]

        # Find best RR per month in training year
        m_best = {}
        for m in range(1, 13):
            best_score = -9999
            best_r = 2.0
            for rr in rr_ratios:
                tdf = all_trades[rr]
                sub = tdf[(tdf['year'] == train_year) & (tdf['month'] == m)]
                avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
                if avg > best_score:
                    best_score = avg
                    best_r = rr
            m_best[m] = best_r

        # Apply to test year
        adaptive_oos = []
        for m in range(1, 13):
            rr = m_best[m]
            tdf = all_trades[rr]
            sub = tdf[(tdf['year'] == test_year) & (tdf['month'] == m)]
            for _, row in sub.iterrows():
                adaptive_oos.append(row.to_dict())

        fixed_oos = trades[trades['year'] == test_year]

        if len(adaptive_oos) > 0 and len(fixed_oos) > 0:
            adapt_avg = np.mean([t['net_ret'] for t in adaptive_oos]) * 10000
            fixed_avg = fixed_oos['net_ret'].mean() * 10000
            wf_month_results.append({
                'train': train_year, 'test': test_year,
                'fixed_bps': fixed_avg, 'adapt_bps': adapt_avg,
            })

    if wf_month_results:
        print(f"\n  {'Train':>6s}  {'Test':>6s}  {'Fixed':>7s}  {'Adapt':>7s}  {'Diff':>6s}")
        adapt_wins = 0
        for r in wf_month_results:
            diff = r['adapt_bps'] - r['fixed_bps']
            marker = " <" if diff > 0 else ""
            print(f"  {r['train']:>6d}  {r['test']:>6d}  {r['fixed_bps']:>+7.1f}"
                  f"  {r['adapt_bps']:>+7.1f}  {diff:>+6.1f}{marker}")
            if diff > 0:
                adapt_wins += 1

        adapt_avg = np.mean([r['adapt_bps'] for r in wf_month_results])
        fixed_avg = np.mean([r['fixed_bps'] for r in wf_month_results])
        print(f"\n  Monthly adaptive beats fixed in {adapt_wins}/{len(wf_month_results)} OOS years")
        print(f"  OOS average: Fixed={fixed_avg:+.1f} bps, Adaptive={adapt_avg:+.1f} bps")

    # ── 11. SKIP-DAY/MONTH ANALYSIS ───────────────────────────────────────────
    print_section("SKIP-DAY / SKIP-MONTH ANALYSIS (RR=2.0)")

    print("\n  What if we skip the worst weekday?")
    dow_avgs = []
    for dow in range(5):
        sub = trades[trades['dow'] == dow]
        avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
        dow_avgs.append((DOW_NAMES[dow], avg, dow))
    dow_avgs.sort(key=lambda x: x[1])

    worst_dow = dow_avgs[0]
    filtered = trades[trades['dow'] != worst_dow[2]]
    s_filt = stats_for_group(filtered)
    print(f"  Worst day: {worst_dow[0]} ({worst_dow[1]:+.1f} bps avg)")
    print(f"  Skipping {worst_dow[0]}:  {s_filt['n']} trades, "
          f"avg {s_filt['avg_bps']:+.1f} bps, Sharpe {s_filt['sharpe']:.2f}")
    print(f"  Including all days: {s_all['n']} trades, "
          f"avg {s_all['avg_bps']:+.1f} bps, Sharpe {s_all['sharpe']:.2f}")

    print("\n  What if we skip the worst month?")
    month_avgs = []
    for m in range(1, 13):
        sub = trades[trades['month'] == m]
        avg = sub['net_ret'].mean() * 10000 if len(sub) > 0 else 0
        month_avgs.append((MONTH_NAMES[m-1], avg, m))
    month_avgs.sort(key=lambda x: x[1])

    worst_month = month_avgs[0]
    filtered_m = trades[trades['month'] != worst_month[2]]
    s_filt_m = stats_for_group(filtered_m)
    print(f"  Worst month: {worst_month[0]} ({worst_month[1]:+.1f} bps avg)")
    print(f"  Skipping {worst_month[0]}:  {s_filt_m['n']} trades, "
          f"avg {s_filt_m['avg_bps']:+.1f} bps, Sharpe {s_filt_m['sharpe']:.2f}")
    print(f"  Including all months: {s_all['n']} trades, "
          f"avg {s_all['avg_bps']:+.1f} bps, Sharpe {s_all['sharpe']:.2f}")

    # ── CONCLUSION ────────────────────────────────────────────────────────────
    print_section("CONCLUSION")
    print("""
  Key question: do weekday/seasonal patterns survive out-of-sample?

  If adaptive OOS < fixed OOS: the variations are noise, stick with
  fixed RR=2.0 every day. Adding complexity without OOS improvement
  just increases the chance of overfitting.

  If a specific day/month is consistently negative across most years,
  skipping it may be defensible even without formal optimization.
""")


if __name__ == "__main__":
    main()
