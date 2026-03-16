"""
V7 Walk-Forward Validation

Since the confirmed rebreak strategy is rule-based (no fitted parameters),
walk-forward here verifies edge stability across sequential non-overlapping
time windows. Reports per-window stats and detects regime degradation.

Also runs a multi-instrument test if EURUSD data is available.

Usage:
    python -m v7_confirmed_rebreak.backtest.walk_forward [--pw 60] [--confirm 3]
    python -m v7_confirmed_rebreak.backtest.walk_forward --multi
"""
import argparse
import io
import contextlib
import logging
import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional, Dict

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v7_confirmed_rebreak.config.strategy_config import StrategyConfig
from v7_confirmed_rebreak.backtest.engine_v2 import BacktestEngineV2, TradeRecord

DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")

# Spread costs per instrument (half-turn each side)
SPREAD_MAP = {
    "XAUUSD": 0.30,
    "EURUSD": 0.00010,  # ~1 pip
}


@dataclass
class WindowResult:
    label: str
    start: str
    end: str
    trades: int
    pnl: float
    avg_pnl: float
    win_rate: float
    max_win: float
    max_loss: float
    sharpe: float
    long_trades: int
    short_trades: int
    long_pnl: float
    short_pnl: float
    sl_exits: int
    time_exits: int


def compute_sharpe(pnls: list, periods_per_year: float = 252.0) -> float:
    """Annualized Sharpe from trade PnLs (daily approx)."""
    if len(pnls) < 5:
        return 0.0
    arr = np.array(pnls)
    if arr.std() == 0:
        return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(periods_per_year))


def run_window(symbol: str, start: str, end: str, pw: int, confirm: int,
               hold: int, sl: float, min_ticks: int, spread: float,
               label: str = "",
               preloaded_df=None) -> Optional[WindowResult]:
    """Run backtest on a single time window."""
    data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")
    if preloaded_df is None and not Path(data_path).exists():
        print(f"  [SKIP] No data for {symbol}")
        return None

    config = StrategyConfig(
        instrument=symbol,
        pivot_window=pw,
        confirm_bars=confirm,
        sl_atr_multiple=sl,
        tp_atr_multiple=99.0,
        max_hold_bars=hold,
        min_bar_ticks=min_ticks,
        spread_cost=spread,
    )
    logger = logging.getLogger("wf")
    logger.setLevel(logging.CRITICAL)

    runner = BacktestEngineV2(
        data_path=data_path,
        config=config,
        start_date=start,
        end_date=end,
        logger=logger,
        preloaded_df=preloaded_df,
    )
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        trades = runner.run()

    if not trades:
        return WindowResult(
            label=label, start=start, end=end, trades=0, pnl=0, avg_pnl=0,
            win_rate=0, max_win=0, max_loss=0, sharpe=0,
            long_trades=0, short_trades=0, long_pnl=0, short_pnl=0,
            sl_exits=0, time_exits=0,
        )

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    longs = [t for t in trades if t.direction == "long"]
    shorts = [t for t in trades if t.direction == "short"]

    return WindowResult(
        label=label,
        start=start,
        end=end,
        trades=len(trades),
        pnl=sum(pnls),
        avg_pnl=sum(pnls) / len(pnls),
        win_rate=len(wins) / len(pnls) * 100,
        max_win=max(pnls),
        max_loss=min(pnls),
        sharpe=compute_sharpe(pnls),
        long_trades=len(longs),
        short_trades=len(shorts),
        long_pnl=sum(t.pnl for t in longs),
        short_pnl=sum(t.pnl for t in shorts),
        sl_exits=sum(1 for t in trades if t.exit_reason == "CATASTROPHE_SL"),
        time_exits=sum(1 for t in trades if t.exit_reason == "TIME_STOP"),
    )


def generate_windows(first_year: int, last_year: int,
                     window_months: int = 6) -> List[tuple]:
    """Generate non-overlapping half-year windows."""
    windows = []
    year = first_year
    half = 1
    while True:
        if half == 1:
            start = f"{year}-01-01"
            end = f"{year}-06-30"
        else:
            start = f"{year}-07-01"
            end = f"{year}-12-31"

        if year > last_year:
            break
        if year == last_year and half == 2:
            end = f"{last_year + 1}-01-01"

        label = f"{year}H{half}"
        windows.append((label, start, end))

        half += 1
        if half > 2:
            half = 1
            year += 1

    return windows


def print_walk_forward_results(results: List[WindowResult], symbol: str,
                               pw: int, confirm: int, hold: int, sl: float):
    """Pretty-print walk-forward table."""
    print(f"\n{'='*100}")
    print(f"WALK-FORWARD VALIDATION: {symbol}")
    print(f"  pw={pw} confirm={confirm} hold={hold} sl={sl}xATR")
    print(f"{'='*100}")

    header = (f"{'Window':<10} {'Start':>10} {'End':>10} {'Trades':>6} "
              f"{'PnL':>10} {'Avg':>8} {'WR%':>6} {'Sharpe':>7} "
              f"{'L/S':>7} {'SL':>4} {'MaxWin':>8} {'MaxLoss':>8}")
    print(header)
    print("-" * 100)

    total_trades = 0
    total_pnl = 0.0
    positive_windows = 0
    all_pnls_flat = []

    for r in results:
        total_trades += r.trades
        total_pnl += r.pnl
        if r.pnl > 0:
            positive_windows += 1

        ls = f"{r.long_trades}/{r.short_trades}"
        sign = "+" if r.pnl >= 0 else ""
        print(f"{r.label:<10} {r.start:>10} {r.end:>10} {r.trades:>6} "
              f"${r.pnl:>+9.2f} ${r.avg_pnl:>+7.3f} {r.win_rate:>5.1f}% "
              f"{r.sharpe:>+7.2f} {ls:>7} {r.sl_exits:>4} "
              f"${r.max_win:>+7.2f} ${r.max_loss:>+7.2f}")

    print("-" * 100)
    avg_pnl_overall = total_pnl / total_trades if total_trades else 0
    print(f"{'TOTAL':<10} {'':>10} {'':>10} {total_trades:>6} "
          f"${total_pnl:>+9.2f} ${avg_pnl_overall:>+7.3f} "
          f"{'':>6} {'':>7} {'':>7} {'':>4}")
    print(f"\n  Positive windows: {positive_windows}/{len(results)} "
          f"({positive_windows/len(results)*100:.0f}%)")

    # Detect regime issues
    neg_streak = 0
    max_neg_streak = 0
    for r in results:
        if r.pnl < 0:
            neg_streak += 1
            max_neg_streak = max(max_neg_streak, neg_streak)
        else:
            neg_streak = 0
    print(f"  Max consecutive negative windows: {max_neg_streak}")

    # Check for trend in edge (is it decaying?)
    if len(results) >= 4:
        first_half = results[:len(results)//2]
        second_half = results[len(results)//2:]
        avg_first = sum(r.avg_pnl for r in first_half) / len(first_half)
        avg_second = sum(r.avg_pnl for r in second_half) / len(second_half)
        print(f"  Avg PnL/trade (first half):  ${avg_first:+.3f}")
        print(f"  Avg PnL/trade (second half): ${avg_second:+.3f}")
        if avg_second > avg_first:
            print(f"  --> Edge IMPROVING over time")
        elif avg_second > 0:
            print(f"  --> Edge stable (still positive)")
        else:
            print(f"  --> WARNING: Edge may be decaying")

    print(f"{'='*100}")


def run_multi_instrument(pw: int, confirm: int, hold: int, sl: float,
                         min_ticks: int, start: str):
    """Run backtest across multiple instruments."""
    symbols = ["XAUUSD", "EURUSD"]

    print(f"\n{'='*100}")
    print(f"MULTI-INSTRUMENT TEST")
    print(f"  pw={pw} confirm={confirm} hold={hold} sl={sl}xATR start={start}")
    print(f"{'='*100}")

    header = (f"{'Symbol':<10} {'Trades':>6} {'PnL':>10} {'Avg':>8} "
              f"{'WR%':>6} {'Sharpe':>7} {'L/S':>7}")
    print(header)
    print("-" * 70)

    for symbol in symbols:
        data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")
        if not Path(data_path).exists():
            print(f"{symbol:<10} [SKIP] no data file")
            continue
        print(f"Loading {symbol} data...", flush=True)
        df = BacktestEngineV2.load_csv(data_path)
        spread = SPREAD_MAP.get(symbol, 0.30)
        r = run_window(symbol, start, None, pw, confirm, hold, sl,
                       min_ticks, spread, label=symbol, preloaded_df=df)
        if r is None:
            continue
        if r.trades == 0:
            print(f"{symbol:<10} {'no trades':>6}")
            continue

        ls = f"{r.long_trades}/{r.short_trades}"
        print(f"{symbol:<10} {r.trades:>6} ${r.pnl:>+9.2f} "
              f"${r.avg_pnl:>+7.3f} {r.win_rate:>5.1f}% "
              f"{r.sharpe:>+7.2f} {ls:>7}")

    print(f"{'='*100}")


def main():
    parser = argparse.ArgumentParser(
        description="V7 Walk-Forward Validation & Multi-Instrument Test")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--pw", type=int, default=60)
    parser.add_argument("--confirm", type=int, default=3)
    parser.add_argument("--max-hold", type=int, default=60)
    parser.add_argument("--sl", type=float, default=10.0)
    parser.add_argument("--min-ticks", type=int, default=50)
    parser.add_argument("--first-year", type=int, default=2019,
                        help="First year for walk-forward windows")
    parser.add_argument("--last-year", type=int, default=2026)
    parser.add_argument("--multi", action="store_true",
                        help="Run multi-instrument test")
    parser.add_argument("--multi-start", default="2023-01-01",
                        help="Start date for multi-instrument test")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    symbol = args.symbol.upper()
    spread = SPREAD_MAP.get(symbol, 0.30)

    if args.multi:
        run_multi_instrument(args.pw, args.confirm, args.max_hold,
                             args.sl, args.min_ticks, args.multi_start)
        return

    # Load data ONCE
    data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")
    print(f"Pre-loading {symbol} data (one-time)...")
    full_df = BacktestEngineV2.load_csv(data_path)

    # Generate walk-forward windows
    windows = generate_windows(args.first_year, args.last_year)

    print(f"Walk-forward: {len(windows)} windows from "
          f"{args.first_year} to {args.last_year}")
    print(f"Config: {symbol} pw={args.pw} confirm={args.confirm} "
          f"hold={args.max_hold} sl={args.sl}x spread={spread}")

    results = []
    for label, start, end in windows:
        print(f"  Running {label} ({start} to {end})...", end=" ", flush=True)
        r = run_window(symbol, start, end, args.pw, args.confirm,
                       args.max_hold, args.sl, args.min_ticks, spread,
                       label=label, preloaded_df=full_df)
        if r:
            print(f"{r.trades} trades, ${r.pnl:+.2f}")
            results.append(r)
        else:
            print("skipped")

    print_walk_forward_results(results, symbol, args.pw, args.confirm,
                               args.max_hold, args.sl)

    # Also run multi-instrument if data exists
    eurusd_path = DATA_DIR / "eurusd_1m_tick.csv"
    if eurusd_path.exists():
        print("\nEURUSD data found -- running multi-instrument comparison...")
        run_multi_instrument(args.pw, args.confirm, args.max_hold,
                             args.sl, args.min_ticks, "2023-01-01")


if __name__ == "__main__":
    main()
