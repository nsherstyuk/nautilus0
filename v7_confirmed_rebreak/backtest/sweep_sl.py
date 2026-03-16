"""Sweep catastrophe SL levels for the winning config (pw=60, c=3, h=60)."""
import sys
import logging
import io
import contextlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v7_confirmed_rebreak.config.strategy_config import StrategyConfig
from v7_confirmed_rebreak.backtest.engine_v2 import BacktestEngineV2

DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")


def run_one(pw, confirm, hold, min_ticks, sl):
    data_path = str(DATA_DIR / "xauusd_1m_tick.csv")
    config = StrategyConfig(
        instrument="XAUUSD",
        pivot_window=pw,
        confirm_bars=confirm,
        sl_atr_multiple=sl,
        tp_atr_multiple=99.0,
        max_hold_bars=hold,
        min_bar_ticks=min_ticks,
    )
    logging.basicConfig(level=logging.CRITICAL)
    logger = logging.getLogger("sweep_sl")
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

    # Exit reason counts
    reasons = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

    # Yearly
    yearly = {}
    for t in trades:
        yr = t.entry_time.strftime("%Y")
        yearly[yr] = yearly.get(yr, 0) + t.pnl

    # Max drawdown per trade
    max_loss = min(pnls)

    return {
        "trades": len(trades), "pnl": total, "avg": avg,
        "wr": wr, "yearly": yearly, "reasons": reasons,
        "max_loss": max_loss,
    }


def main():
    pw, confirm, hold = 60, 3, 60
    print(f"Config: pw={pw} confirm={confirm} hold={hold} min_ticks=50")
    print(f"{'SL (xATR)':<12} {'Trades':>6} {'PnL':>10} {'Avg':>8} "
          f"{'WR%':>6} {'SL_hits':>7} {'MaxLoss':>8} "
          f"{'2023':>8} {'2024':>8} {'2025':>8} {'2026':>8}")
    print("-" * 110)

    for sl in [99.0, 20.0, 15.0, 12.0, 10.0, 8.0, 6.0, 5.0, 4.0, 3.0]:
        r = run_one(pw, confirm, hold, 50, sl)
        if r is None:
            print(f"{'SL='+str(sl):<12} {'0':>6}")
            continue
        yr = r["yearly"]
        sl_hits = r["reasons"].get("CATASTROPHE_SL", 0)
        label = "none" if sl >= 50 else f"{sl:.0f}x"
        print(f"{label:<12} {r['trades']:>6} {r['pnl']:>+10.2f} "
              f"{r['avg']:>+8.3f} {r['wr']:>5.1f}% {sl_hits:>7} "
              f"{r['max_loss']:>+8.2f} "
              f"{yr.get('2023',0):>+8.2f} {yr.get('2024',0):>+8.2f} "
              f"{yr.get('2025',0):>+8.2f} {yr.get('2026',0):>+8.2f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
