"""
V7 Confirmed Rebreak Strategy -- Backtest Runner

Usage:
    python -m v7_confirmed_rebreak.backtest.run_backtest [--pw 30] [--min-ticks 50] [--start 2023-01-01]
"""
import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v7_confirmed_rebreak.config.strategy_config import StrategyConfig
from v7_confirmed_rebreak.backtest.engine import BacktestRunner

DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")


def main():
    parser = argparse.ArgumentParser(description="V7 Confirmed Rebreak Backtest")
    parser.add_argument("--symbol", default="XAUUSD", help="Instrument symbol")
    parser.add_argument("--pw", type=int, default=30, help="Pivot window")
    parser.add_argument("--min-ticks", type=int, default=50, help="Min tick count per bar in imbalance window")
    parser.add_argument("--sl", type=float, default=1.5, help="SL ATR multiple")
    parser.add_argument("--tp", type=float, default=3.0, help="TP ATR multiple")
    parser.add_argument("--max-hold", type=int, default=60, help="Max hold bars (time stop)")
    parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--verbose", action="store_true", help="Show trade-by-trade logs")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")

    config = StrategyConfig(
        instrument=symbol,
        pivot_window=args.pw,
        sl_atr_multiple=args.sl,
        tp_atr_multiple=args.tp,
        max_hold_bars=args.max_hold,
        min_bar_ticks=args.min_ticks,
    )

    log_level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M",
    )
    logger = logging.getLogger("v7")
    logger.setLevel(log_level)

    runner = BacktestRunner(
        data_path=data_path,
        config=config,
        start_date=args.start,
        end_date=args.end,
        logger=logger,
    )

    runner.run()
    runner.print_summary()


if __name__ == "__main__":
    main()
