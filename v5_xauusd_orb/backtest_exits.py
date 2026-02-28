"""
backtest_exits.py -- Compare multi-stage exit strategies for v5 XAUUSD ORB.

Tests several exit regimes on top of the baseline strategy and shows a
side-by-side comparison.

Exit strategies tested
──────────────────────
  baseline       : SL / TP / EOD (current live behaviour)
  be_50pct       : Move SL to breakeven once price reaches 50% of TP distance
  be_33pct       : Move SL to breakeven once price reaches 33% of TP distance
  trail_50pct    : After reaching 50% of TP, trail SL at 0.5 × range_size
  trail_33pct    : After reaching 33% of TP, trail SL at 0.5 × range_size
  time_be_1h     : Move SL to breakeven after 1 hour (12 bars) in trade
  time_be_2h     : Move SL to breakeven after 2 hours (24 bars) in trade
  partial_tp     : Take 50% off at halfway to TP; trail remainder with BE stop

Usage:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.backtest_exits
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.backtest_exits --start 2019-01-01
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.backtest_exits --save results.csv
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from v5_xauusd_orb.config import load_config
from v5_xauusd_orb.backtest import build_5min_bars


# ── Exit strategy definitions ─────────────────────────────────────────────────

@dataclass
class ExitStrategy:
    name: str
    label: str
    # Breakeven trigger: fraction of TP distance at which SL moves to entry
    be_trigger_pct: Optional[float] = None
    # Trail trigger: fraction of TP distance at which trailing starts
    trail_trigger_pct: Optional[float] = None
    # Trail distance as fraction of range_size (for trailing stops)
    trail_dist_pct: float = 0.5
    # Time-based BE: move SL to breakeven after this many bars
    time_be_bars: Optional[int] = None
    # Partial TP: close this fraction of position at partial_pct of TP distance
    partial_close_pct: float = 0.0       # e.g. 0.5 = close half
    partial_trigger_pct: Optional[float] = None  # e.g. 0.5 = halfway to TP


STRATEGIES = [
    ExitStrategy("baseline",    "Baseline (SL/TP/EOD)"),
    ExitStrategy("be_50pct",    "BE stop @ 50% to TP",      be_trigger_pct=0.50),
    ExitStrategy("be_33pct",    "BE stop @ 33% to TP",      be_trigger_pct=0.33),
    ExitStrategy("trail_50pct", "Trail stop @ 50% to TP",   trail_trigger_pct=0.50, trail_dist_pct=0.50),
    ExitStrategy("trail_33pct", "Trail stop @ 33% to TP",   trail_trigger_pct=0.33, trail_dist_pct=0.50),
    ExitStrategy("time_be_1h",  "BE stop after 1h in trade",time_be_bars=12),
    ExitStrategy("time_be_2h",  "BE stop after 2h in trade",time_be_bars=24),
    ExitStrategy(
        "partial_tp",
        "50% close @ midpoint + BE trail",
        partial_close_pct=0.50,
        partial_trigger_pct=0.50,
        be_trigger_pct=0.50,
    ),
]


# ── Core simulation ───────────────────────────────────────────────────────────

def simulate_trade(
    entry_px: float,
    sl_px: float,
    tp_px: float,
    direction: str,
    range_size: float,
    monitor_bars: pd.DataFrame,
    strat: ExitStrategy,
    qty: int = 1,
    spread_per_side: float = 0.10,
    slippage: float = 0.15,
) -> dict:
    """
    Walk bar-by-bar through the trade window and apply the given exit strategy.

    Returns a dict with: result, exit_px, pnl, hold_bars,
                         partial_pnl (if partial close happened)
    """
    current_sl = sl_px
    current_tp = tp_px
    tp_dist    = abs(tp_px - entry_px)

    be_triggered    = False
    trail_triggered = False
    partial_done    = False
    trail_high      = entry_px  # best price seen for trailing (long)

    partial_pnl = 0.0
    remaining_qty = qty

    for i, (idx, bar) in enumerate(monitor_bars.iterrows()):
        bar_high = bar['high']
        bar_low  = bar['low']

        # ── Update trailing high/low ─────────────────────────────────────
        if direction == 'LONG':
            if bar_high > trail_high:
                trail_high = bar_high
        else:
            if bar_low < trail_high:  # reusing trail_high as trail_low for short
                trail_high = bar_low

        # ── Compute MFE (maximum favourable excursion so far) ─────────────
        if direction == 'LONG':
            mfe = trail_high - entry_px
        else:
            mfe = entry_px - trail_high

        # ── Partial close trigger ────────────────────────────────────────
        if (not partial_done
                and strat.partial_trigger_pct is not None
                and strat.partial_close_pct > 0):
            partial_trigger_dist = strat.partial_trigger_pct * tp_dist
            if mfe >= partial_trigger_dist:
                partial_done = True
                closed_qty   = int(remaining_qty * strat.partial_close_pct)
                remaining_qty -= closed_qty
                partial_price = entry_px + partial_trigger_dist if direction == 'LONG' \
                                else entry_px - partial_trigger_dist
                raw = abs(partial_price - entry_px) * closed_qty
                partial_pnl += raw - (spread_per_side * 2 * closed_qty)

        # ── Breakeven stop trigger ───────────────────────────────────────
        if (not be_triggered and strat.be_trigger_pct is not None):
            be_trigger_dist = strat.be_trigger_pct * tp_dist
            if mfe >= be_trigger_dist:
                be_triggered = True
                current_sl   = entry_px   # move SL to entry (breakeven)

        # ── Trailing stop trigger ────────────────────────────────────────
        if (not trail_triggered and strat.trail_trigger_pct is not None):
            trail_trigger_dist = strat.trail_trigger_pct * tp_dist
            if mfe >= trail_trigger_dist:
                trail_triggered = True

        if trail_triggered:
            # Trail SL: highest_seen - trail_dist for long
            trail_dist = strat.trail_dist_pct * range_size
            if direction == 'LONG':
                new_sl = trail_high - trail_dist
                if new_sl > current_sl:
                    current_sl = new_sl
            else:
                new_sl = trail_high + trail_dist
                if new_sl < current_sl:
                    current_sl = new_sl

        # ── Time-based BE ────────────────────────────────────────────────
        if (not be_triggered and strat.time_be_bars is not None
                and i >= strat.time_be_bars):
            be_triggered = True
            current_sl   = entry_px

        # ── Check SL / TP (SL wins if both touched in same bar) ──────────
        if direction == 'LONG':
            sl_hit = bar_low  <= current_sl
            tp_hit = bar_high >= current_tp
        else:
            sl_hit = bar_high >= current_sl
            tp_hit = bar_low  <= current_tp

        if sl_hit:
            # Apply slippage to stop exit (fills at worse price)
            if direction == 'LONG':
                exit_px = current_sl - slippage
            else:
                exit_px = current_sl + slippage
            result  = 'BE' if (be_triggered
                               and abs(current_sl - entry_px) < 0.01) else 'SL'
            raw = (exit_px - entry_px) if direction == 'LONG' \
                  else (entry_px - exit_px)
            pnl = raw * remaining_qty - (spread_per_side * 2 * remaining_qty) + partial_pnl
            return {'result': result, 'exit_px': exit_px, 'pnl': round(pnl, 2),
                    'hold_bars': i + 1}

        if tp_hit:
            exit_px = current_tp  # TP is a limit order, no slippage
            raw = abs(current_tp - entry_px) * remaining_qty
            pnl = raw - (spread_per_side * 2 * remaining_qty) + partial_pnl
            return {'result': 'TP', 'exit_px': exit_px, 'pnl': round(pnl, 2),
                    'hold_bars': i + 1}

    # EOD: close at last bar's close (market order with slippage)
    if len(monitor_bars) > 0:
        exit_px = monitor_bars['close'].iloc[-1]
        if direction == 'LONG':
            exit_px = exit_px - slippage
        else:
            exit_px = exit_px + slippage
    else:
        exit_px = entry_px

    raw = ((exit_px - entry_px) if direction == 'LONG'
           else (entry_px - exit_px)) * remaining_qty
    pnl = raw - (spread_per_side * 2 * remaining_qty) + partial_pnl
    return {'result': 'EOD', 'exit_px': exit_px, 'pnl': round(pnl, 2),
            'hold_bars': len(monitor_bars)}


# ── Full backtest run for a single strategy ───────────────────────────────────

def run_strategy(
    ohlcv: pd.DataFrame,
    strat: ExitStrategy,
    cfg,
    rr: float,
    skip_weekdays: list[int],
    qty: int,
    spread_per_side: float,
    slippage: float = 0.15,
) -> pd.DataFrame:

    results = []
    ohlcv2 = ohlcv.copy()
    ohlcv2['date']    = ohlcv2.index.date
    ohlcv2['hour']    = ohlcv2.index.hour
    ohlcv2['weekday'] = pd.to_datetime(ohlcv2['date']).dt.weekday

    asian_start = cfg.strategy.asian_start_hour
    asian_end   = cfg.strategy.asian_end_hour
    trade_start = cfg.strategy.trade_start_hour
    trade_end   = cfg.strategy.trade_end_hour
    min_rng     = cfg.strategy.min_range_pct
    max_rng     = cfg.strategy.max_range_pct

    for day, day_df in ohlcv2.groupby('date'):
        weekday = day_df['weekday'].iloc[0]
        if weekday >= 5:
            continue
        if weekday in skip_weekdays:
            continue

        asian = day_df[(day_df['hour'] >= asian_start) & (day_df['hour'] < asian_end)]
        if len(asian) < 3:
            continue

        range_high = asian['high'].max()
        range_low  = asian['low'].min()
        range_size = range_high - range_low
        if range_size <= 0:
            continue

        mid_price = (range_high + range_low) / 2
        range_pct = range_size / mid_price * 100
        if range_pct < min_rng or range_pct > max_rng:
            continue

        window = day_df[(day_df['hour'] >= trade_start) & (day_df['hour'] < trade_end)]
        if len(window) == 0:
            continue

        long_entry  = range_high + slippage   # stop order fills with slippage
        long_sl     = range_low
        long_tp     = range_high + rr * range_size  # TP based on range_high, not slipped entry

        short_entry = range_low - slippage    # stop order fills with slippage
        short_sl    = range_high
        short_tp    = range_low - rr * range_size

        direction   = None
        entry_px    = None
        entry_bar_i = None

        for i, (idx, bar) in enumerate(window.iterrows()):
            if bar['high'] >= range_high:  # trigger on range level, fill at slipped price
                direction, entry_px, entry_bar_i = 'LONG',  long_entry,  i
                sl_px, tp_px = long_sl, long_tp
                break
            if bar['low'] <= range_low:    # trigger on range level, fill at slipped price
                direction, entry_px, entry_bar_i = 'SHORT', short_entry, i
                sl_px, tp_px = short_sl, short_tp
                break

        if direction is None:
            continue

        monitor = window.iloc[entry_bar_i + 1:]
        trade   = simulate_trade(
            entry_px, sl_px, tp_px, direction, range_size,
            monitor, strat, qty, spread_per_side, slippage)

        results.append({
            'date':       day,
            'direction':  direction,
            'entry':      round(entry_px, 2),
            'exit':       round(trade['exit_px'], 2),
            'sl_orig':    round(sl_px, 2),
            'tp':         round(tp_px, 2),
            'range_size': round(range_size, 2),
            'result':     trade['result'],
            'pnl':        trade['pnl'],
            'hold_bars':  trade['hold_bars'],
        })

    return pd.DataFrame(results)


# ── Stats helper ──────────────────────────────────────────────────────────────

def stats(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {}
    tp_n  = (df['result'] == 'TP').sum()
    sl_n  = df['result'].isin(['SL', 'BE']).sum()
    be_n  = (df['result'] == 'BE').sum()
    eod_n = (df['result'] == 'EOD').sum()
    n     = len(df)

    eq    = df['pnl'].cumsum()
    dd    = (eq - eq.cummax()).min()
    sharpe = (df['pnl'].mean() / df['pnl'].std() * np.sqrt(252)
              if df['pnl'].std() > 0 else 0)

    gp    = df.loc[df['pnl'] > 0, 'pnl'].sum()
    gl    = df.loc[df['pnl'] < 0, 'pnl'].abs().sum()
    pf    = gp / gl if gl > 0 else float('inf')

    return {
        'trades':    n,
        'TP%':       round(tp_n / n * 100, 1),
        'SL%':       round(sl_n / n * 100, 1),
        'BE%':       round(be_n / n * 100, 1),
        'EOD%':      round(eod_n / n * 100, 1),
        'total_pnl': round(df['pnl'].sum(), 2),
        'avg_pnl':   round(df['pnl'].mean(), 2),
        'max_dd':    round(dd, 2),
        'sharpe':    round(sharpe, 2),
        'pf':        round(pf, 2),
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Compare multi-stage exits for v5 XAUUSD ORB")
    parser.add_argument("--start",  default="2019-01-01")
    parser.add_argument("--end",    default=None)
    parser.add_argument("--rr",     type=float, default=None)
    parser.add_argument("--spread", type=float, default=0.10)
    parser.add_argument("--slippage", type=float, default=0.15,
                        help="Slippage for stop/market orders per oz in $ (default: 0.15)")
    parser.add_argument("--save",   default=None,
                        help="Save comparison CSV to this path")
    args = parser.parse_args()

    cfg  = load_config()
    rr   = args.rr if args.rr is not None else cfg.strategy.rr_ratio
    skip = cfg.strategy.skip_weekdays
    qty  = cfg.position.qty

    print(f"Loading data...")
    ohlcv = build_5min_bars(cfg.paths.tick_bar_file)
    start = pd.Timestamp(args.start, tz='UTC')
    end   = pd.Timestamp(args.end,   tz='UTC') if args.end else ohlcv.index.max()
    ohlcv = ohlcv.loc[start:end]
    print(f"Bars: {len(ohlcv):,}  ({ohlcv.index.min().date()} -> {ohlcv.index.max().date()})")
    print(f"RR={rr}  skip_weekdays={skip}  spread={args.spread}/side  slippage={args.slippage}\n")

    rows = []
    for strat in STRATEGIES:
        print(f"Running: {strat.label} ...", end=' ', flush=True)
        df = run_strategy(ohlcv, strat, cfg, rr, skip, qty, args.spread, args.slippage)
        s  = stats(df)
        s['strategy'] = strat.label
        rows.append(s)
        print(f"  -> {s['total_pnl']:+.2f}  Sharpe={s['sharpe']}  PF={s['pf']}")

    results = pd.DataFrame(rows).set_index('strategy')

    print("\n" + "=" * 110)
    print(f"  EXIT STRATEGY COMPARISON  (RR={rr}, spread={args.spread}/side, {args.start} -> {args.end or 'latest'})")
    print("=" * 110)
    header = f"  {'Strategy':<38}  {'Trades':>6}  {'TP%':>5}  {'SL%':>5}  {'BE%':>5}  {'EOD%':>5}  {'P&L':>10}  {'Avg':>7}  {'MaxDD':>10}  {'Sharpe':>7}  {'PF':>5}"
    print(header)
    print("-" * 110)
    for name, row in results.iterrows():
        marker = " ◄" if row['total_pnl'] == results['total_pnl'].max() else ""
        print(f"  {name:<38}  {row['trades']:>6}  {row['TP%']:>4.1f}%  {row['SL%']:>4.1f}%  {row['BE%']:>4.1f}%  {row['EOD%']:>4.1f}%  {row['total_pnl']:>+10.2f}  {row['avg_pnl']:>+6.2f}  {row['max_dd']:>+10.2f}  {row['sharpe']:>7.2f}  {row['pf']:>5.2f}{marker}")
    print("=" * 110)

    # Per-year breakdown for top 3 by P&L
    top3 = results.nlargest(3, 'total_pnl').index.tolist()
    print(f"\n  Annual P&L for top 3 strategies:")
    print(f"  {'Year':<6}", end='')
    yearly_data = {}
    for strat_name in top3:
        strat = next(s for s in STRATEGIES if s.label == strat_name)
        df = run_strategy(ohlcv, strat, cfg, rr, skip, qty, args.spread, args.slippage)
        df['year'] = pd.to_datetime(df['date']).dt.year
        yearly_data[strat_name] = df
        print(f"  {strat_name[:26]:<28}", end='')
    print()
    print("  " + "-" * 100)
    all_years = sorted(set(
        y for df in yearly_data.values() for y in df['year'].unique()))
    for yr in all_years:
        print(f"  {yr:<6}", end='')
        for sn in top3:
            df = yearly_data[sn]
            yr_pnl = df[df['year'] == yr]['pnl'].sum()
            print(f"  {yr_pnl:>+10.2f}              ", end='')
        print()

    if args.save:
        results.to_csv(args.save)
        print(f"\nSaved to {args.save}")


if __name__ == "__main__":
    main()
