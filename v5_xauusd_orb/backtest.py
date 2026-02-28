"""
backtest.py -- Offline backtest for the v5 XAUUSD Asian Range -> London Breakout strategy.

Data source : trading_system_v4/data/xauusd_1000t_bars.parquet
              (1000-tick bars, resampled to 5-minute OHLCV internally)

Usage:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.backtest
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.backtest --start 2020-01-01 --end 2026-01-01
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.backtest --rr 1.5 --no-skip-wed
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from v5_xauusd_orb.config import load_config, ROOT


# ── Helpers ───────────────────────────────────────────────────────────────────

def build_5min_bars(parquet_path: str) -> pd.DataFrame:
    """Load tick bars and resample to 5-minute OHLCV (UTC-aware index)."""
    df = pd.read_parquet(parquet_path)
    df = df.set_index('timestamp').sort_index()
    df.index = pd.to_datetime(df.index, utc=True)

    ohlcv = pd.DataFrame({
        'open':  df['open'].resample('5min').first(),
        'high':  df['high'].resample('5min').max(),
        'low':   df['low'].resample('5min').min(),
        'close': df['close'].resample('5min').last(),
    }).dropna()
    return ohlcv


def backtest_orb(
    ohlcv: pd.DataFrame,
    asian_start: int = 0,
    asian_end: int = 6,
    trade_start: int = 8,
    trade_end: int = 16,
    rr: float = 2.0,
    skip_weekdays: list[int] | None = None,
    min_range_pct: float = 0.05,
    max_range_pct: float = 2.0,
    qty: int = 1,
    spread_per_side: float = 0.10,   # assumed bid/ask spread per entry in $
    slippage: float = 0.15,          # assumed slippage for stop/market orders in $
) -> pd.DataFrame:
    """
    Vectorized daily loop backtest.

    Fill assumption:
      - Entry: stop order → fills at the bar that FIRST touches the entry
        price (high >= entry for LONG, low <= entry for SHORT).
        Fill price = entry price (conservative stop assumption).
      - SL / TP: checked bar-by-bar within the trade window.
        If both SL and TP are touched in the same 5-min bar, SL wins
        (worst-case assumption).
      - EOD close at 16:00 UTC if position still open: fills at bar close.

    Returns one row per trade day (including no-trade days for diagnostics).
    """
    if skip_weekdays is None:
        skip_weekdays = [2]  # Wednesday default

    results = []

    # Group by UTC date
    ohlcv = ohlcv.copy()
    ohlcv['date'] = ohlcv.index.date
    ohlcv['hour'] = ohlcv.index.hour
    ohlcv['weekday'] = pd.to_datetime(ohlcv['date']).dt.weekday

    for day, day_df in ohlcv.groupby('date'):
        weekday = day_df['weekday'].iloc[0]

        # Skip weekends
        if weekday >= 5:
            continue

        # Skip configured weekdays
        if weekday in skip_weekdays:
            results.append({'date': day, 'result': 'SKIP_WEEKDAY', 'pnl': 0,
                            'direction': None, 'entry': None, 'exit': None,
                            'sl': None, 'tp': None, 'range_size': None,
                            'hold_bars': 0})
            continue

        # ── Asian Range ──────────────────────────────────────────────────────
        asian = day_df[(day_df['hour'] >= asian_start) & (day_df['hour'] < asian_end)]
        if len(asian) < 3:
            results.append({'date': day, 'result': 'NO_ASIAN_DATA', 'pnl': 0,
                            'direction': None, 'entry': None, 'exit': None,
                            'sl': None, 'tp': None, 'range_size': None,
                            'hold_bars': 0})
            continue

        range_high = asian['high'].max()
        range_low  = asian['low'].min()
        range_size = range_high - range_low

        if range_size <= 0:
            continue

        mid_price = (range_high + range_low) / 2
        range_pct = range_size / mid_price * 100

        if range_pct < min_range_pct:
            results.append({'date': day, 'result': 'RANGE_TOO_TIGHT', 'pnl': 0,
                            'direction': None, 'entry': None, 'exit': None,
                            'sl': None, 'tp': None, 'range_size': round(range_size, 2),
                            'hold_bars': 0})
            continue

        if range_pct > max_range_pct:
            results.append({'date': day, 'result': 'RANGE_TOO_WIDE', 'pnl': 0,
                            'direction': None, 'entry': None, 'exit': None,
                            'sl': None, 'tp': None, 'range_size': round(range_size, 2),
                            'hold_bars': 0})
            continue

        # ── London trade window ──────────────────────────────────────────────
        window = day_df[(day_df['hour'] >= trade_start) & (day_df['hour'] < trade_end)]
        if len(window) == 0:
            results.append({'date': day, 'result': 'NO_LONDON_DATA', 'pnl': 0,
                            'direction': None, 'entry': None, 'exit': None,
                            'sl': None, 'tp': None, 'range_size': round(range_size, 2),
                            'hold_bars': 0})
            continue

        long_entry  = range_high
        long_sl     = range_low
        long_tp     = range_high + rr * range_size

        short_entry = range_low
        short_sl    = range_high
        short_tp    = range_low - rr * range_size

        # Track which direction fills first
        direction  = None
        entry_px   = None
        sl_px      = None
        tp_px      = None
        entry_bar_i = None

        for i, (idx, bar) in enumerate(window.iterrows()):
            # Check LONG entry (price breaks above range high)
            if bar['high'] >= long_entry and direction is None:
                direction  = 'LONG'
                entry_px   = long_entry + slippage
                sl_px      = long_sl
                tp_px      = long_tp
                entry_bar_i = i
                break

            # Check SHORT entry (price breaks below range low)
            if bar['low'] <= short_entry and direction is None:
                direction  = 'SHORT'
                entry_px   = short_entry - slippage
                sl_px      = short_sl
                tp_px      = short_tp
                entry_bar_i = i
                break

        if direction is None:
            results.append({'date': day, 'result': 'NO_FILL', 'pnl': 0,
                            'direction': None, 'entry': None, 'exit': None,
                            'sl': None, 'tp': None, 'range_size': round(range_size, 2),
                            'hold_bars': 0})
            continue

        # ── Monitor SL / TP from bar after entry ─────────────────────────────
        monitor = window.iloc[entry_bar_i + 1:]
        result   = 'EOD'
        exit_px  = monitor['close'].iloc[-1] if len(monitor) > 0 else entry_px
        
        if result == 'EOD' and len(monitor) > 0:
            # EOD close is a market order, so it has slippage
            exit_px = exit_px - slippage if direction == 'LONG' else exit_px + slippage
            
        hold_bars = len(monitor)

        for j, (idx, bar) in enumerate(monitor.iterrows()):
            if direction == 'LONG':
                # SL wins if both hit in same bar (worst case)
                if bar['low'] <= sl_px:
                    result   = 'SL'
                    exit_px  = sl_px - slippage
                    hold_bars = j + 1
                    break
                if bar['high'] >= tp_px:
                    result   = 'TP'
                    exit_px  = tp_px
                    hold_bars = j + 1
                    break
            else:  # SHORT
                if bar['high'] >= sl_px:
                    result   = 'SL'
                    exit_px  = sl_px + slippage
                    hold_bars = j + 1
                    break
                if bar['low'] <= tp_px:
                    result   = 'TP'
                    exit_px  = tp_px
                    hold_bars = j + 1
                    break

        # ── P&L ──────────────────────────────────────────────────────────────
        if direction == 'LONG':
            raw_pnl = (exit_px - entry_px) * qty
        else:
            raw_pnl = (entry_px - exit_px) * qty

        pnl = raw_pnl - (spread_per_side * 2 * qty)  # cost per side (entry and exit)

        results.append({
            'date':        day,
            'result':      result,
            'direction':   direction,
            'entry':       round(entry_px, 2),
            'exit':        round(exit_px, 2),
            'sl':          round(sl_px, 2),
            'tp':          round(tp_px, 2),
            'range_size':  round(range_size, 2),
            'range_pct':   round(range_pct, 3),
            'pnl':         round(pnl, 2),
            'hold_bars':   hold_bars,
        })

    return pd.DataFrame(results)


def print_report(trades: pd.DataFrame, rr: float):
    filled = trades[trades['result'].isin(['TP', 'SL', 'EOD'])]
    if len(filled) == 0:
        print("No filled trades.")
        return

    total_days   = len(trades[~trades['result'].isin(['SKIP_WEEKDAY'])])
    fill_days    = len(filled)
    tp_n         = (filled['result'] == 'TP').sum()
    sl_n         = (filled['result'] == 'SL').sum()
    eod_n        = (filled['result'] == 'EOD').sum()
    win_rate     = tp_n / fill_days * 100 if fill_days else 0
    total_pnl    = filled['pnl'].sum()
    avg_pnl      = filled['pnl'].mean()
    max_win      = filled['pnl'].max()
    max_loss     = filled['pnl'].min()

    gross_profit = filled.loc[filled['pnl'] > 0, 'pnl'].sum()
    gross_loss   = filled.loc[filled['pnl'] < 0, 'pnl'].abs().sum()
    pf           = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Drawdown
    eq = filled['pnl'].cumsum()
    dd = (eq - eq.cummax())
    max_dd = dd.min()

    # Sharpe (annualised, ~252 trade-days/yr approximate)
    daily_ret = filled['pnl']
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)
              if daily_ret.std() > 0 else 0)

    skip_wed = trades[trades['result'] == 'SKIP_WEEKDAY'].shape[0]
    no_fill  = trades[trades['result'] == 'NO_FILL'].shape[0]
    filtered = trades[trades['result'].isin(['RANGE_TOO_TIGHT', 'RANGE_TOO_WIDE'])].shape[0]

    print("\n" + "=" * 58)
    print("  XAUUSD ORB Backtest Results")
    print("=" * 58)
    print(f"  Period : {trades['date'].min()} → {trades['date'].max()}")
    print(f"  RR     : {rr}")
    print(f"  Qty    : 1 oz")
    print("-" * 58)
    print(f"  Trade days examined   : {total_days}")
    print(f"  Skip Wed              : {skip_wed}")
    print(f"  Range filtered        : {filtered}")
    print(f"  No fill (no breakout) : {no_fill}")
    print(f"  Filled trades         : {fill_days}")
    print(f"    → TP                : {tp_n}  ({tp_n/fill_days*100:.1f}%)")
    print(f"    → SL                : {sl_n}  ({sl_n/fill_days*100:.1f}%)")
    print(f"    → EOD close         : {eod_n}  ({eod_n/fill_days*100:.1f}%)")
    print("-" * 58)
    print(f"  Win rate (TP only)    : {win_rate:.1f}%")
    print(f"  Total P&L             : ${total_pnl:+,.2f}")
    print(f"  Avg P&L / trade       : ${avg_pnl:+.2f}")
    print(f"  Best trade            : ${max_win:+.2f}")
    print(f"  Worst trade           : ${max_loss:+.2f}")
    print(f"  Profit factor         : {pf:.2f}")
    print(f"  Max drawdown          : ${max_dd:,.2f}")
    print(f"  Sharpe (annualised)   : {sharpe:.2f}")
    print("=" * 58)

    # By year
    filled2 = filled.copy()
    filled2['year'] = pd.to_datetime(filled2['date']).dt.year
    print("\n  Annual breakdown:")
    print(f"  {'Year':>6}  {'Trades':>7}  {'Win%':>6}  {'P&L':>10}  {'MaxDD':>10}")
    for yr, g in filled2.groupby('year'):
        wr = (g['result'] == 'TP').sum() / len(g) * 100
        pnl_yr = g['pnl'].sum()
        eq_yr = g['pnl'].cumsum()
        dd_yr = (eq_yr - eq_yr.cummax()).min()
        print(f"  {yr:>6}  {len(g):>7}  {wr:>5.1f}%  {pnl_yr:>+10,.2f}  {dd_yr:>+10,.2f}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Backtest v5 XAUUSD Asian Range -> London Breakout")
    parser.add_argument("--start",  default="2015-01-01",
                        help="Start date YYYY-MM-DD (default: 2015-01-01)")
    parser.add_argument("--end",    default=None,
                        help="End date YYYY-MM-DD (default: latest)")
    parser.add_argument("--rr",     type=float, default=None,
                        help="Override RR ratio (default: from config.yaml)")
    parser.add_argument("--no-skip-wed", action="store_true",
                        help="Trade Wednesdays too")
    parser.add_argument("--spread", type=float, default=0.10,
                        help="One-way spread per oz in $ (default: 0.10)")
    parser.add_argument("--slippage", type=float, default=0.15,
                        help="Slippage for stop/market orders per oz in $ (default: 0.15)")
    parser.add_argument("--save",   default=None,
                        help="Save trade log to CSV path")
    args = parser.parse_args()

    cfg = load_config()

    rr           = args.rr if args.rr is not None else cfg.strategy.rr_ratio
    skip_weekdays = [] if args.no_skip_wed else cfg.strategy.skip_weekdays

    data_path = cfg.paths.tick_bar_file
    print(f"Loading data from {data_path} ...")
    ohlcv = build_5min_bars(data_path)

    # Filter date range
    start = pd.Timestamp(args.start, tz='UTC')
    end   = pd.Timestamp(args.end, tz='UTC') if args.end else ohlcv.index.max()
    ohlcv = ohlcv.loc[start:end]
    print(f"5-min bars: {len(ohlcv):,}  ({ohlcv.index.min().date()} → {ohlcv.index.max().date()})")

    print("Running backtest...")
    trades = backtest_orb(
        ohlcv,
        asian_start   = cfg.strategy.asian_start_hour,
        asian_end     = cfg.strategy.asian_end_hour,
        trade_start   = cfg.strategy.trade_start_hour,
        trade_end     = cfg.strategy.trade_end_hour,
        rr            = rr,
        skip_weekdays = skip_weekdays,
        min_range_pct = cfg.strategy.min_range_pct,
        max_range_pct = cfg.strategy.max_range_pct,
        qty           = cfg.position.qty,
        spread_per_side = args.spread,
        slippage      = args.slippage,
    )

    print_report(trades, rr)

    if args.save:
        trades.to_csv(args.save, index=False)
        print(f"Trade log saved to {args.save}")


if __name__ == "__main__":
    main()
