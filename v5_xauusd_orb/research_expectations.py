"""
research_expectations.py -- Detailed performance expectations for ORB strategy
with velocity filter (3-min lookback, P50 threshold, no time exit).

Answers: win rate, P&L distribution, loss days/months, drawdowns, streaks.
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from v5_xauusd_orb.backtest_1m import load_1m_bars, backtest, Config, stats, Trade


def enrich_with_3min_tc(trades, df):
    """Add 3-min avg tick count to each trade."""
    enriched = []
    for t in trades:
        entry_ts = t.entry_time
        start_ts = entry_ts - pd.Timedelta(minutes=3)
        mask = (df.index > start_ts) & (df.index <= entry_ts)
        window_bars = df.loc[mask]
        avg_tc = window_bars['tick_count'].mean() if len(window_bars) > 0 else t.entry_tick_count
        enriched.append((t, avg_tc))
    return enriched


def main():
    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars\n")

    oos_start = dt.date(2021, 1, 1)
    cfg = Config(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest(df, cfg)

    # Enrich with 3-min lookback
    enriched = enrich_with_3min_tc(all_trades, df)
    avg_tcs = np.array([e[1] for e in enriched])
    med = np.median(avg_tcs)

    # Split into filtered (fast) and show both
    fast_trades = [e[0] for e in enriched if e[1] >= med]
    all_oos = [t for t in all_trades if t.date >= oos_start]
    fast_oos = [t for t in fast_trades if t.date >= oos_start]

    for label, trades in [("UNFILTERED (all trades)", all_trades),
                          ("UNFILTERED OOS (2021+)", all_oos),
                          ("VELOCITY FILTERED (3min avg >= median)", fast_trades),
                          ("VELOCITY FILTERED OOS (2021+)", fast_oos)]:
        print(f"\n{'='*90}")
        print(f"  {label}")
        print(f"  N = {len(trades)} trades")
        print(f"{'='*90}")
        _detailed_stats(trades, label)

    print(f"\n{'='*90}")
    print(f"  DONE")
    print(f"{'='*90}")


def _detailed_stats(trades, label):
    if not trades:
        print("  NO TRADES")
        return

    pnl = np.array([t.pnl for t in trades])
    dates = [t.date for t in trades]
    n = len(pnl)

    # ── Basic Stats ──
    wins = pnl > 0
    losses = pnl < 0
    flat = pnl == 0
    wr = wins.sum() / n * 100
    lr = losses.sum() / n * 100

    print(f"\n  --- BASIC ---")
    print(f"  Win rate:       {wr:.1f}%")
    print(f"  Loss rate:      {lr:.1f}%")
    print(f"  Flat:           {flat.sum()} ({flat.sum()/n*100:.1f}%)")
    print(f"  Avg win:        ${pnl[wins].mean():+.2f}" if wins.any() else "")
    print(f"  Avg loss:       ${pnl[losses].mean():+.2f}" if losses.any() else "")
    print(f"  Avg trade:      ${pnl.mean():+.2f}")
    print(f"  Median trade:   ${np.median(pnl):+.2f}")
    print(f"  Std per trade:  ${pnl.std():.2f}")

    total = pnl.sum()
    eq = np.cumsum(pnl)
    dd = (eq - np.maximum.accumulate(eq)).min()
    sharpe = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
    gp = pnl[wins].sum() if wins.any() else 0
    gl = abs(pnl[losses].sum()) if losses.any() else 0
    pf = gp / gl if gl > 0 else float('inf')

    print(f"\n  --- P&L ---")
    print(f"  Total P&L:      ${total:+.2f}")
    print(f"  Sharpe:         {sharpe:.2f}")
    print(f"  Profit Factor:  {pf:.2f}")
    print(f"  Max Drawdown:   ${dd:+.2f}")
    print(f"  Best trade:     ${pnl.max():+.2f}")
    print(f"  Worst trade:    ${pnl.min():+.2f}")

    # ── P&L Distribution ──
    print(f"\n  --- P&L DISTRIBUTION ---")
    pcts = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    for p in pcts:
        print(f"    P{p:>2}: ${np.percentile(pnl, p):+.2f}")

    # ── Streaks ──
    streak_w = 0; max_w = 0
    streak_l = 0; max_l = 0
    for v in pnl:
        if v > 0:
            streak_w += 1; max_w = max(max_w, streak_w); streak_l = 0
        elif v < 0:
            streak_l += 1; max_l = max(max_l, streak_l); streak_w = 0
        else:
            streak_w = 0; streak_l = 0

    print(f"\n  --- STREAKS ---")
    print(f"  Max consecutive wins:   {max_w}")
    print(f"  Max consecutive losses: {max_l}")

    # ── Daily aggregation ──
    daily_pnl = defaultdict(float)
    daily_count = defaultdict(int)
    for t in trades:
        daily_pnl[t.date] += t.pnl
        daily_count[t.date] += 1

    day_pnls = np.array(list(daily_pnl.values()))
    win_days = (day_pnls > 0).sum()
    loss_days = (day_pnls < 0).sum()
    flat_days = (day_pnls == 0).sum()
    total_days = len(day_pnls)

    print(f"\n  --- DAILY ---")
    print(f"  Trading days:   {total_days}")
    print(f"  Win days:       {win_days} ({win_days/total_days*100:.1f}%)")
    print(f"  Loss days:      {loss_days} ({loss_days/total_days*100:.1f}%)")
    print(f"  Flat days:      {flat_days}")
    print(f"  Avg daily P&L:  ${day_pnls.mean():+.2f}")
    print(f"  Worst day:      ${day_pnls.min():+.2f}")
    print(f"  Best day:       ${day_pnls.max():+.2f}")

    # ── Monthly aggregation ──
    monthly_pnl = defaultdict(float)
    monthly_count = defaultdict(int)
    for t in trades:
        ym = (t.date.year, t.date.month)
        monthly_pnl[ym] += t.pnl
        monthly_count[ym] += 1

    month_pnls = np.array(list(monthly_pnl.values()))
    win_months = (month_pnls > 0).sum()
    loss_months = (month_pnls < 0).sum()
    flat_months = (month_pnls == 0).sum()
    total_months = len(month_pnls)

    print(f"\n  --- MONTHLY ---")
    print(f"  Total months:   {total_months}")
    print(f"  Win months:     {win_months} ({win_months/total_months*100:.1f}%)")
    print(f"  Loss months:    {loss_months} ({loss_months/total_months*100:.1f}%)")
    print(f"  Avg loss months/year: {loss_months / (total_months/12):.1f}")
    print(f"  Avg monthly P&L: ${month_pnls.mean():+.2f}")
    print(f"  Worst month:    ${month_pnls.min():+.2f}")
    print(f"  Best month:     ${month_pnls.max():+.2f}")

    # Loss days per month
    loss_days_by_month = defaultdict(int)
    for d, p in daily_pnl.items():
        if p < 0:
            ym = (d.year, d.month)
            loss_days_by_month[ym] += 1
    all_loss_days_per_month = list(loss_days_by_month.values())
    if all_loss_days_per_month:
        print(f"  Avg loss days/month: {np.mean(all_loss_days_per_month):.1f}")
        print(f"  Max loss days in one month: {max(all_loss_days_per_month)}")

    # ── Yearly aggregation ──
    yearly_pnl = defaultdict(float)
    yearly_count = defaultdict(int)
    yearly_losses = defaultdict(int)
    for t in trades:
        yr = t.date.year
        yearly_pnl[yr] += t.pnl
        yearly_count[yr] += 1
        if t.pnl < 0:
            yearly_losses[yr] += 1

    print(f"\n  --- YEARLY BREAKDOWN ---")
    print(f"  {'Year':>6} | {'N':>5} | {'Wins':>5} | {'Loss':>5} | {'WR':>5} | "
          f"{'P&L':>10} | {'Worst Mo':>10} | {'Loss Mo':>8}")

    for yr in sorted(yearly_pnl.keys()):
        yr_trades = [t for t in trades if t.date.year == yr]
        yr_wins = sum(1 for t in yr_trades if t.pnl > 0)
        yr_losses_n = sum(1 for t in yr_trades if t.pnl < 0)
        yr_wr = yr_wins / len(yr_trades) * 100 if yr_trades else 0

        yr_months = {(t.date.year, t.date.month) for t in yr_trades}
        yr_month_pnls = {ym: monthly_pnl[ym] for ym in yr_months}
        worst_mo = min(yr_month_pnls.values()) if yr_month_pnls else 0
        loss_mo = sum(1 for v in yr_month_pnls.values() if v < 0)

        print(f"  {yr:>6} | {len(yr_trades):>5} | {yr_wins:>5} | {yr_losses_n:>5} | "
              f"{yr_wr:>4.1f}% | ${yearly_pnl[yr]:>+9.2f} | ${worst_mo:>+9.2f} | {loss_mo:>8}")

    # ── Drawdown analysis ──
    eq_series = np.cumsum(pnl)
    running_max = np.maximum.accumulate(eq_series)
    drawdowns = eq_series - running_max

    # Find top 5 drawdowns
    print(f"\n  --- TOP DRAWDOWNS ---")

    # Simple approach: find deepest points
    dd_depths = []
    in_dd = False
    dd_start = 0
    for i in range(len(drawdowns)):
        if drawdowns[i] < 0:
            if not in_dd:
                dd_start = i
                in_dd = True
        else:
            if in_dd:
                depth = drawdowns[dd_start:i].min()
                dd_depths.append((depth, dd_start, i, dates[dd_start], dates[i-1]))
                in_dd = False
    if in_dd:
        depth = drawdowns[dd_start:].min()
        dd_depths.append((depth, dd_start, len(drawdowns), dates[dd_start], dates[-1]))

    dd_depths.sort(key=lambda x: x[0])
    for i, (depth, start, end, d1, d2) in enumerate(dd_depths[:5]):
        duration = (d2 - d1).days if hasattr(d2 - d1, 'days') else 0
        n_trades = end - start
        print(f"    #{i+1}: ${depth:+.2f} over {n_trades} trades ({d1} to {d2}, {duration} days)")

    # ── What to expect per month (average) ──
    trades_per_month = len(trades) / total_months
    wins_per_month = sum(1 for t in trades if t.pnl > 0) / total_months
    losses_per_month = sum(1 for t in trades if t.pnl < 0) / total_months

    print(f"\n  --- MONTHLY EXPECTATIONS ---")
    print(f"  Trades/month:      {trades_per_month:.1f}")
    print(f"  Wins/month:        {wins_per_month:.1f}")
    print(f"  Losses/month:      {losses_per_month:.1f}")
    print(f"  Expected P&L/mo:   ${month_pnls.mean():+.2f}")
    print(f"  Std P&L/mo:        ${month_pnls.std():.2f}")
    print(f"  P(losing month):   {loss_months/total_months*100:.0f}%")


if __name__ == "__main__":
    main()
