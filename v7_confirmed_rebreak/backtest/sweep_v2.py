"""Parameter sweep for Engine V2 with pre-computed shifted pivots."""
import sys
import logging
import io
import contextlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v7_confirmed_rebreak.config.strategy_config import StrategyConfig
from v7_confirmed_rebreak.backtest.engine_v2 import BacktestEngineV2

DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")


def run_one(symbol, pw, confirm, hold, min_ticks, sl=99.0, tp=99.0, cat_sl=None):
    data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")
    config = StrategyConfig(
        instrument=symbol,
        pivot_window=pw,
        confirm_bars=confirm,
        sl_atr_multiple=sl,
        tp_atr_multiple=tp,
        max_hold_bars=hold,
        min_bar_ticks=min_ticks,
    )
    logging.basicConfig(level=logging.CRITICAL)
    logger = logging.getLogger("sweep")
    logger.setLevel(logging.CRITICAL)
    runner = BacktestEngineV2(
        data_path=data_path,
        config=config,
        start_date="2023-01-01",
        logger=logger,
    )
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        trades = runner.run()

    if not trades:
        return None

    pnls = [t.pnl for t in trades]
    total = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = len(wins) / len(pnls) * 100
    avg = total / len(pnls)
    avg_w = sum(wins) / len(wins) if wins else 0
    avg_l = sum(losses) / len(losses) if losses else 0

    # Yearly
    yearly = {}
    for t in trades:
        yr = t.entry_time.strftime("%Y")
        yearly[yr] = yearly.get(yr, 0) + t.pnl

    return {
        "trades": len(trades), "pnl": total, "avg": avg,
        "wr": wr, "avg_w": avg_w, "avg_l": avg_l, "yearly": yearly,
    }


def main():
    print(f"{'Config':<35} {'Trades':>6} {'PnL':>10} {'Avg':>8} "
          f"{'WR%':>6} {'2023':>8} {'2024':>8} {'2025':>8} {'2026':>8}")
    print("-" * 115)

    configs = [
        # (pw, confirm, hold, label)
        (30, 5, 45, "pw30 c5 h45"),
        (30, 5, 60, "pw30 c5 h60"),
        (60, 5, 45, "pw60 c5 h45"),
        (60, 5, 60, "pw60 c5 h60"),
        (60, 5, 90, "pw60 c5 h90"),
        (60, 10, 60, "pw60 c10 h60"),
        (60, 3, 60, "pw60 c3 h60"),
        (90, 5, 60, "pw90 c5 h60"),
        (90, 5, 90, "pw90 c5 h90"),
        (45, 5, 60, "pw45 c5 h60"),
        (60, 5, 30, "pw60 c5 h30"),
    ]

    for pw, confirm, hold, label in configs:
        r = run_one("XAUUSD", pw, confirm, hold, 50)
        if r is None:
            print(f"{label:<35} {'0':>6}")
            continue
        yr = r["yearly"]
        print(f"{label:<35} {r['trades']:>6} {r['pnl']:>+10.2f} "
              f"{r['avg']:>+8.3f} {r['wr']:>5.1f}% "
              f"{yr.get('2023',0):>+8.2f} {yr.get('2024',0):>+8.2f} "
              f"{yr.get('2025',0):>+8.2f} {yr.get('2026',0):>+8.2f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
