"""
backtest_multi_fx.py -- Multi-instrument session-range breakout backtest.

Applies the Asian Range -> London Breakout (ORB) concept to multiple
FX pairs and Gold, with per-instrument cost and session parameters.

Supports downloading missing data from IBKR for GBPUSD, USDJPY, etc.

Usage:
  python -m v5_xauusd_orb.backtest_multi_fx
  python -m v5_xauusd_orb.backtest_multi_fx --pairs EURUSD GBPUSD USDJPY
  python -m v5_xauusd_orb.backtest_multi_fx --start 2019-01-01
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from v5_xauusd_orb.config import ROOT


# ── Instrument definitions ────────────────────────────────────────────────────

@dataclass
class InstrumentConfig:
    symbol: str
    data_file: str              # relative to ROOT
    pip_size: float             # 1 pip in price terms
    spread_per_side: float      # typical half-spread in price terms
    slippage: float             # stop/market order slippage in price terms
    point_value: float          # P&L per 1.0 price move per lot
    lot_label: str              # display label
    # Session times (UTC hours)
    range_start: int            # quiet session start
    range_end: int              # quiet session end
    trade_start: int            # breakout session start
    trade_end: int              # breakout session end
    # Filters
    min_range_pct: float = 0.01
    max_range_pct: float = 2.0
    skip_weekdays: list = None

    def __post_init__(self):
        if self.skip_weekdays is None:
            self.skip_weekdays = [2]  # skip Wednesday by default


# Per-instrument configs
# Spread/slippage in price terms (not pips)
INSTRUMENTS = {
    'XAUUSD': InstrumentConfig(
        symbol='XAUUSD',
        data_file='trading_system_v4/data/xauusd_1000t_bars.parquet',
        pip_size=0.01,           # Gold: 1 cent
        spread_per_side=0.10,    # $0.10 per side
        slippage=0.15,           # $0.15 per stop fill
        point_value=1.0,         # $1 per $1 move per oz
        lot_label='1 oz',
        range_start=0, range_end=6,
        trade_start=8, trade_end=16,
        min_range_pct=0.05, max_range_pct=2.0,
    ),
    'EURUSD': InstrumentConfig(
        symbol='EURUSD',
        data_file='trading_system_v4/data/eurusd_1000t_bars.parquet',
        pip_size=0.0001,
        spread_per_side=0.00003,  # ~0.3 pips per side
        slippage=0.00005,         # ~0.5 pips per stop fill
        point_value=100000.0,     # $1 per 0.00001 move per standard lot -> $100k per 1.0
        lot_label='100k units',
        range_start=0, range_end=6,
        trade_start=7, trade_end=16,
        min_range_pct=0.01, max_range_pct=2.0,
    ),
    'GBPUSD': InstrumentConfig(
        symbol='GBPUSD',
        data_file='trading_system_v4/data/gbpusd_1000t_bars.parquet',
        pip_size=0.0001,
        spread_per_side=0.00004,  # ~0.4 pips per side
        slippage=0.00006,         # ~0.6 pips per stop fill
        point_value=100000.0,
        lot_label='100k units',
        range_start=0, range_end=6,
        trade_start=7, trade_end=16,
        min_range_pct=0.01, max_range_pct=2.0,
    ),
    'USDJPY': InstrumentConfig(
        symbol='USDJPY',
        data_file='trading_system_v4/data/usdjpy_1000t_bars.parquet',
        pip_size=0.01,
        spread_per_side=0.005,    # ~0.5 pips per side
        slippage=0.008,           # ~0.8 pips per stop fill
        point_value=1000.0,       # ~$1000 per 1.0 move per standard lot at ~100 JPY/USD
        lot_label='100k units',
        # USDJPY: Tokyo range -> London breakout
        range_start=0, range_end=6,
        trade_start=7, trade_end=16,
        min_range_pct=0.01, max_range_pct=2.0,
    ),
}


# ── Data loading ──────────────────────────────────────────────────────────────

def build_5min_bars(parquet_path: str) -> pd.DataFrame:
    """Load tick bars and resample to 5-minute OHLCV."""
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


# ── Core backtest ─────────────────────────────────────────────────────────────

def backtest_orb(
    ohlcv: pd.DataFrame,
    inst: InstrumentConfig,
    rr: float = 2.0,
    be_bars: int | None = 24,
    be_offset: float = 0.0,
    qty: int = 1,
) -> pd.DataFrame:
    """
    Run ORB backtest for a single instrument.
    Returns one row per trade.
    """
    results = []
    ohlcv = ohlcv.copy()
    ohlcv['date'] = ohlcv.index.date
    ohlcv['hour'] = ohlcv.index.hour
    ohlcv['weekday'] = pd.to_datetime(ohlcv['date']).dt.weekday

    spread = inst.spread_per_side
    slip = inst.slippage

    for day, day_df in ohlcv.groupby('date'):
        weekday = day_df['weekday'].iloc[0]
        if weekday >= 5:
            continue
        if weekday in inst.skip_weekdays:
            continue

        # Range session
        asian = day_df[(day_df['hour'] >= inst.range_start) &
                       (day_df['hour'] < inst.range_end)]
        if len(asian) < 3:
            continue

        range_high = asian['high'].max()
        range_low = asian['low'].min()
        range_size = range_high - range_low
        if range_size <= 0:
            continue

        mid_price = (range_high + range_low) / 2
        range_pct = range_size / mid_price * 100
        if range_pct < inst.min_range_pct or range_pct > inst.max_range_pct:
            continue

        # Trade window
        window = day_df[(day_df['hour'] >= inst.trade_start) &
                        (day_df['hour'] < inst.trade_end)]
        if len(window) == 0:
            continue

        # Entry levels (with slippage on stop entries)
        long_entry = range_high + slip
        long_sl = range_low
        long_tp = range_high + rr * range_size

        short_entry = range_low - slip
        short_sl = range_high
        short_tp = range_low - rr * range_size

        # Find entry
        direction = None
        entry_px = None
        entry_bar_i = None

        for i, (idx, bar) in enumerate(window.iterrows()):
            if bar['high'] >= range_high:
                direction, entry_px, entry_bar_i = 'LONG', long_entry, i
                sl_px, tp_px = long_sl, long_tp
                break
            if bar['low'] <= range_low:
                direction, entry_px, entry_bar_i = 'SHORT', short_entry, i
                sl_px, tp_px = short_sl, short_tp
                break

        if direction is None:
            continue

        # Monitor trade
        monitor = window.iloc[entry_bar_i + 1:]
        current_sl = sl_px
        be_triggered = False
        result = 'EOD'
        exit_px = None
        hold_bars = len(monitor)

        for j, (idx, bar) in enumerate(monitor.iterrows()):
            # Time-based BE trigger
            if not be_triggered and be_bars is not None and j >= be_bars:
                be_triggered = True
                if direction == 'LONG':
                    current_sl = entry_px + be_offset
                else:
                    current_sl = entry_px - be_offset

            # Check SL / TP
            if direction == 'LONG':
                sl_hit = bar['low'] <= current_sl
                tp_hit = bar['high'] >= tp_px
            else:
                sl_hit = bar['high'] >= current_sl
                tp_hit = bar['low'] <= tp_px

            if sl_hit:
                if direction == 'LONG':
                    exit_px = current_sl - slip
                else:
                    exit_px = current_sl + slip
                result = 'BE' if be_triggered else 'SL'
                hold_bars = j + 1
                break

            if tp_hit:
                exit_px = tp_px  # limit order, no slippage
                result = 'TP'
                hold_bars = j + 1
                break

        if exit_px is None:
            # EOD close (market order with slippage)
            if len(monitor) > 0:
                exit_px = monitor['close'].iloc[-1]
                if direction == 'LONG':
                    exit_px -= slip
                else:
                    exit_px += slip
            else:
                exit_px = entry_px

        # P&L
        if direction == 'LONG':
            raw_pnl = (exit_px - entry_px)
        else:
            raw_pnl = (entry_px - exit_px)

        pnl_price = raw_pnl - (spread * 2)  # spread cost in price terms
        pnl_usd = pnl_price * inst.point_value * qty

        results.append({
            'date': day,
            'direction': direction,
            'result': result,
            'entry': round(entry_px, 6),
            'exit': round(exit_px, 6),
            'sl': round(sl_px, 6),
            'tp': round(tp_px, 6),
            'range_size': round(range_size, 6),
            'range_pips': round(range_size / inst.pip_size, 1),
            'pnl_price': round(pnl_price, 6),
            'pnl_usd': round(pnl_usd, 2),
            'hold_bars': hold_bars,
        })

    return pd.DataFrame(results)


# ── Stats ─────────────────────────────────────────────────────────────────────

def compute_stats(df: pd.DataFrame, symbol: str) -> dict:
    if len(df) == 0:
        return {'symbol': symbol, 'trades': 0}

    n = len(df)
    tp_n = (df['result'] == 'TP').sum()
    sl_n = (df['result'] == 'SL').sum()
    be_n = (df['result'] == 'BE').sum()
    eod_n = (df['result'] == 'EOD').sum()

    eq = df['pnl_usd'].cumsum()
    dd = (eq - eq.cummax()).min()
    sharpe = (df['pnl_usd'].mean() / df['pnl_usd'].std() * np.sqrt(252)
              if df['pnl_usd'].std() > 0 else 0)

    gp = df.loc[df['pnl_usd'] > 0, 'pnl_usd'].sum()
    gl = df.loc[df['pnl_usd'] < 0, 'pnl_usd'].abs().sum()
    pf = gp / gl if gl > 0 else float('inf')

    return {
        'symbol': symbol,
        'trades': n,
        'TP%': round(tp_n / n * 100, 1),
        'SL%': round(sl_n / n * 100, 1),
        'BE%': round(be_n / n * 100, 1),
        'EOD%': round(eod_n / n * 100, 1),
        'total_pnl': round(df['pnl_usd'].sum(), 2),
        'avg_pnl': round(df['pnl_usd'].mean(), 2),
        'max_dd': round(dd, 2),
        'sharpe': round(sharpe, 2),
        'pf': round(pf, 2),
        'avg_range_pips': round(df['range_pips'].mean(), 1),
    }


def print_annual_breakdown(df: pd.DataFrame, symbol: str):
    if len(df) == 0:
        return
    df2 = df.copy()
    df2['year'] = pd.to_datetime(df2['date']).dt.year
    print(f"\n  {symbol} Annual Breakdown:")
    print(f"  {'Year':>6}  {'Trades':>7}  {'TP%':>6}  {'P&L':>12}  {'MaxDD':>10}  {'Sharpe':>7}")
    for yr, g in df2.groupby('year'):
        wr = (g['result'] == 'TP').sum() / len(g) * 100
        pnl_yr = g['pnl_usd'].sum()
        eq_yr = g['pnl_usd'].cumsum()
        dd_yr = (eq_yr - eq_yr.cummax()).min()
        sh_yr = (g['pnl_usd'].mean() / g['pnl_usd'].std() * np.sqrt(252)
                 if g['pnl_usd'].std() > 0 else 0)
        print(f"  {yr:>6}  {len(g):>7}  {wr:>5.1f}%  ${pnl_yr:>+10,.2f}  ${dd_yr:>+9,.2f}  {sh_yr:>7.2f}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Multi-instrument ORB session breakout backtest")
    parser.add_argument("--pairs", nargs='+',
                        default=None,
                        help="Pairs to test (default: all available)")
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--rr", type=float, default=2.0)
    parser.add_argument("--be-bars", type=int, default=24,
                        help="BE trigger in 5-min bars (24=120min, None=disabled)")
    parser.add_argument("--be-offset-pips", type=float, default=0.0,
                        help="BE offset in pips (converted to price per instrument)")
    parser.add_argument("--no-be", action="store_true",
                        help="Disable BE rule entirely")
    parser.add_argument("--save", default=None)
    args = parser.parse_args()

    # Determine which pairs to test
    if args.pairs:
        pairs = [p.upper() for p in args.pairs]
    else:
        # Test all pairs that have data files
        pairs = []
        for sym, inst in INSTRUMENTS.items():
            path = ROOT / inst.data_file
            if path.exists():
                pairs.append(sym)
            else:
                print(f"  SKIP {sym}: data file not found ({inst.data_file})")

    if not pairs:
        print("No pairs with available data. Download data first.")
        return

    print(f"Testing {len(pairs)} pairs: {', '.join(pairs)}")
    print(f"RR={args.rr}  BE={'OFF' if args.no_be else f'{args.be_bars*5}min'}  "
          f"BE offset={args.be_offset_pips} pips")
    print(f"Period: {args.start} -> {args.end or 'latest'}")
    print()

    all_stats = []
    all_trades = {}

    for sym in pairs:
        inst = INSTRUMENTS[sym]
        path = ROOT / inst.data_file

        if not path.exists():
            print(f"  SKIP {sym}: {path} not found")
            continue

        print(f"Loading {sym}...", end=' ', flush=True)
        ohlcv = build_5min_bars(str(path))

        start = pd.Timestamp(args.start, tz='UTC')
        end = pd.Timestamp(args.end, tz='UTC') if args.end else ohlcv.index.max()
        ohlcv = ohlcv.loc[start:end]
        print(f"{len(ohlcv):,} bars  ({ohlcv.index.min().date()} -> {ohlcv.index.max().date()})")

        be_bars_val = None if args.no_be else args.be_bars
        be_offset_price = args.be_offset_pips * inst.pip_size

        trades = backtest_orb(
            ohlcv, inst,
            rr=args.rr,
            be_bars=be_bars_val,
            be_offset=be_offset_price,
        )

        s = compute_stats(trades, sym)
        all_stats.append(s)
        all_trades[sym] = trades

        print(f"  -> {s['trades']} trades  P&L=${s['total_pnl']:+,.2f}  "
              f"Sharpe={s['sharpe']}  PF={s['pf']}")

    # Summary table
    results_df = pd.DataFrame(all_stats).set_index('symbol')
    print("\n" + "=" * 130)
    print(f"  MULTI-INSTRUMENT ORB BACKTEST  "
          f"(RR={args.rr}, BE={'OFF' if args.no_be else f'{args.be_bars*5}min'}, "
          f"{args.start} -> {args.end or 'latest'})")
    print("=" * 130)
    header = (f"  {'Symbol':<10}  {'Trades':>6}  {'TP%':>5}  {'SL%':>5}  "
              f"{'BE%':>5}  {'EOD%':>5}  {'Avg Range':>10}  {'P&L (USD)':>12}  "
              f"{'Avg P&L':>8}  {'MaxDD':>10}  {'Sharpe':>7}  {'PF':>5}")
    print(header)
    print("-" * 130)

    for sym, row in results_df.iterrows():
        if row['trades'] == 0:
            print(f"  {sym:<10}  {'NO TRADES':>6}")
            continue
        marker = " << BEST" if row['total_pnl'] == results_df['total_pnl'].max() else ""
        print(f"  {sym:<10}  {row['trades']:>6}  {row['TP%']:>4.1f}%  "
              f"{row['SL%']:>4.1f}%  {row['BE%']:>4.1f}%  {row['EOD%']:>4.1f}%  "
              f"{row['avg_range_pips']:>8.1f}p  ${row['total_pnl']:>+11,.2f}  "
              f"${row['avg_pnl']:>+7.2f}  ${row['max_dd']:>+9,.2f}  "
              f"{row['sharpe']:>7.2f}  {row['pf']:>5.2f}{marker}")

    print("=" * 130)

    # Portfolio stats (if multiple pairs)
    if len(all_trades) > 1:
        print("\n  PORTFOLIO ANALYSIS (equal weight, 1 lot each):")
        # Combine daily P&L
        daily_pnls = {}
        for sym, trades in all_trades.items():
            if len(trades) > 0:
                daily = trades.groupby('date')['pnl_usd'].sum()
                daily_pnls[sym] = daily

        if daily_pnls:
            combined = pd.DataFrame(daily_pnls).fillna(0)
            portfolio_daily = combined.sum(axis=1)
            total_pnl = portfolio_daily.sum()
            sharpe = (portfolio_daily.mean() / portfolio_daily.std() * np.sqrt(252)
                      if portfolio_daily.std() > 0 else 0)
            eq = portfolio_daily.cumsum()
            max_dd = (eq - eq.cummax()).min()
            
            gp = portfolio_daily[portfolio_daily > 0].sum()
            gl = portfolio_daily[portfolio_daily < 0].abs().sum()
            pf = gp / gl if gl > 0 else float('inf')

            print(f"  Total P&L:     ${total_pnl:+,.2f}")
            print(f"  Sharpe:        {sharpe:.2f}")
            print(f"  Max Drawdown:  ${max_dd:+,.2f}")
            print(f"  Profit Factor: {pf:.2f}")
            print(f"  Trading days:  {len(portfolio_daily)}")

            # Correlation matrix
            if len(combined.columns) > 1:
                print(f"\n  Daily P&L Correlation:")
                corr = combined.corr()
                print(f"  {'':>10}", end='')
                for c in corr.columns:
                    print(f"  {c:>10}", end='')
                print()
                for idx_name, row in corr.iterrows():
                    print(f"  {idx_name:>10}", end='')
                    for v in row:
                        print(f"  {v:>10.3f}", end='')
                    print()

    # Annual breakdowns
    for sym, trades in all_trades.items():
        print_annual_breakdown(trades, sym)

    if args.save:
        results_df.to_csv(args.save)
        print(f"\nSaved to {args.save}")


if __name__ == "__main__":
    main()
