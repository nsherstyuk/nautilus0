"""Quick parameter sweep for SL/TP/max_hold on OOS data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v7_confirmed_rebreak.config.strategy_config import StrategyConfig
from v7_confirmed_rebreak.backtest.engine import BacktestRunner

DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")

CONFIGS = [
    # (sl_mult, tp_mult, max_hold, label)
    (2.0, 4.0, 60, "SL=2 TP=4 hold=60"),
    (3.0, 6.0, 60, "SL=3 TP=6 hold=60"),
    (5.0, 10.0, 60, "SL=5 TP=10 hold=60"),
    (3.0, 6.0, 30, "SL=3 TP=6 hold=30"),
    (3.0, 6.0, 45, "SL=3 TP=6 hold=45"),
    # Time-stop only (huge SL/TP so they rarely hit)
    (99.0, 99.0, 30, "pure time=30"),
    (99.0, 99.0, 45, "pure time=45"),
    (99.0, 99.0, 60, "pure time=60"),
    # Tighter with shorter hold
    (2.0, 3.0, 30, "SL=2 TP=3 hold=30"),
    (4.0, 6.0, 45, "SL=4 TP=6 hold=45"),
]


def main():
    data_path = str(DATA_DIR / "xauusd_1m_tick.csv")

    print(f"{'Config':<25} {'Trades':>7} {'PnL':>10} {'WR%':>6} "
          f"{'AvgW':>7} {'AvgL':>7} {'SL%':>5} {'TP%':>5} {'TS%':>5}")
    print("-" * 90)

    for sl, tp, hold, label in CONFIGS:
        config = StrategyConfig(
            instrument="XAUUSD",
            pivot_window=30,
            sl_atr_multiple=sl,
            tp_atr_multiple=tp,
            max_hold_bars=hold,
            min_bar_ticks=50,
        )
        import logging
        logging.basicConfig(level=logging.CRITICAL)
        runner = BacktestRunner(
            data_path=data_path,
            config=config,
            start_date="2023-01-01",
            logger=logging.getLogger("sweep"),
        )
        runner.logger.setLevel(logging.CRITICAL)
        # Suppress prints from engine
        import io, contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            trades = runner.run()

        if not trades:
            print(f"{label:<25} {'0':>7}")
            continue

        pnls = [t.pnl for t in trades]
        total = sum(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        wr = len(wins) / len(pnls) * 100
        avg_w = sum(wins) / len(wins) if wins else 0
        avg_l = sum(losses) / len(losses) if losses else 0
        sl_pct = sum(1 for t in trades if t.exit_reason == "SL") / len(trades) * 100
        tp_pct = sum(1 for t in trades if t.exit_reason == "TP") / len(trades) * 100
        ts_pct = sum(1 for t in trades if t.exit_reason == "TIME_STOP") / len(trades) * 100

        print(f"{label:<25} {len(trades):>7} {total:>+10.2f} {wr:>5.1f}% "
              f"{avg_w:>+7.2f} {avg_l:>+7.2f} {sl_pct:>4.0f}% {tp_pct:>4.0f}% {ts_pct:>4.0f}%")


if __name__ == "__main__":
    main()
