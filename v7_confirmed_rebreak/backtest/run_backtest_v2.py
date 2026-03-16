"""
V7 Confirmed Rebreak Strategy -- Backtest Runner V2

Uses pre-computed shifted-centered pivots for research-quality pivot detection.

Usage:
    python -m v7_confirmed_rebreak.backtest.run_backtest_v2 [--pw 30] [--confirm 5] [--max-hold 60]
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v7_confirmed_rebreak.config.strategy_config import StrategyConfig
from v7_confirmed_rebreak.backtest.engine_v2 import BacktestEngineV2

DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")


def main():
    parser = argparse.ArgumentParser(description="V7 Backtest V2 (pre-computed pivots)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--pw", type=int, default=30, help="Pivot window")
    parser.add_argument("--confirm", type=int, default=5, help="Confirm bars (shift delay)")
    parser.add_argument("--min-ticks", type=int, default=50)
    parser.add_argument("--sl", type=float, default=99.0, help="SL ATR multiple (99=disabled)")
    parser.add_argument("--tp", type=float, default=99.0, help="TP ATR multiple (99=disabled)")
    parser.add_argument("--max-hold", type=int, default=60, help="Max hold bars")
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default=None)
    args = parser.parse_args()

    symbol = args.symbol.upper()
    data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")

    config = StrategyConfig(
        instrument=symbol,
        pivot_window=args.pw,
        confirm_bars=args.confirm,
        sl_atr_multiple=args.sl,
        tp_atr_multiple=args.tp,
        max_hold_bars=args.max_hold,
        min_bar_ticks=args.min_ticks,
    )

    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger("v7_v2")

    runner = BacktestEngineV2(
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
