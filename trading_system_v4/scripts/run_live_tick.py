"""
run_live_tick.py — Live Tick-Bar Trading System (Meta-Labeling Architecture)

Full live execution loop built on 1000-tick bars + EMA-crossover meta-labeling.

Pipeline:
  IBKR  →  LiveTickAggregator (7,854-tick bars*)  →  LiveFeatureBuilder
        →  EMA crossover detection  →  V4ModelInference (meta_model_ema_eurusd)
        →  ExecutionEngine

  *7,854-tick bars calibrated from Dukascopy/IBKR parity check (2026-02-18).
   Dukascopy 1000-tick ≈ IBKR 7,854-tick for equivalent information content.

Configuration (env vars, all optional):

  TICK_SYMBOL     IBKR contract symbol,  default: EUR
  TICK_CURRENCY   IBKR contract currency, default: USD
  TICK_EXCHANGE   IBKR exchange,          default: IDEALPRO
  TICK_MODEL_STEM Model artifact stem,    default: meta_model_ema_eurusd
  TICK_IB_HOST    IBKR gateway host,      default: 127.0.0.1
  TICK_IB_PORT    IBKR gateway port,      default: 4002 (IB Gateway paper)
  TICK_CLIENT_ID  IBKR client ID,         default: 10

Usage:
  python -m trading_system_v4.scripts.run_live_tick
  python -m trading_system_v4.scripts.run_live_tick --dry-run   # log only, no orders
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import threading
from pathlib import Path

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ib_insync import IB, Forex

from trading_system_v4.execution.live_tick_aggregator import LiveTickAggregator
from trading_system_v4.execution.live_feature_builder import LiveFeatureBuilder
from trading_system_v4.execution.execution_engine import ExecutionEngine
from trading_system_v4.model.model_inference import V4ModelInference
from trading_system_v4.monitoring.logger import setup_logger


# ── trade simulation parameters (must match meta_labeling_ema.py) ─────────────
_TP_ATR = 1.5
_SL_ATR = 1.0
_SPREAD_EST = 0.00010   # 1 pip


# ── IBKR-calibrated tick bar size ─────────────────────────────────────────────
# Dukascopy 1000-tick ≈ IBKR 7854-tick (parity check 2026-02-18, 1 hour sample)
_DEFAULT_TICKS_PER_BAR = 7_854


# ── helpers ───────────────────────────────────────────────────────────────────

def _start_health_check(logger, interval: int = 60) -> None:
    def _loop():
        while True:
            logger.info("HEALTHCHECK: system alive.")
            time.sleep(interval)
    threading.Thread(target=_loop, daemon=True).start()


def _make_on_bar_callback(
    builder: LiveFeatureBuilder,
    model: V4ModelInference,
    exec_engine: ExecutionEngine,
    symbol: str,
    logger,
    dry_run: bool,
):
    """
    Returns the callback wired to LiveTickAggregator.on_bar_complete.

    Flow per bar:
      1. Push raw bar → LiveFeatureBuilder → (signal, features)
      2. If no EMA crossover → skip.
      3. If not warmed up → skip (logged once).
      4. model.should_trade(features) → (trade, prob)
      5. If trade: compute TP/SL, send order (or log in dry-run mode).
    """
    _warmup_logged = [False]

    def on_bar(bar: dict) -> None:
        try:
            # Push bar through feature builder
            signal, features = builder.push_bar(bar)

            if not builder.warmed_up:
                if not _warmup_logged[0]:
                    logger.info(
                        f"[warm-up] {builder.bar_count}/{builder.WARMUP} bars — "
                        "suppressing signals until EMA is stable."
                    )
                    _warmup_logged[0] = True
                return

            if signal == 0 or features is None:
                return   # no EMA crossover this bar

            should_trade, prob = model.should_trade(features)

            direction = "LONG" if signal == 1 else "SHORT"
            bar_ts    = bar.get("timestamp", "?")
            close     = float(bar["close"])

            # Reconstruct ATR from normalised feature for TP/SL logging
            atr_norm = features.get("atr_norm", 0.0)
            atr      = atr_norm * close

            if signal == 1:
                tp_price = (close + _SPREAD_EST) + atr * _TP_ATR
                sl_price = (close + _SPREAD_EST) - atr * _SL_ATR
                side     = "buy"
            else:
                tp_price = (close - _SPREAD_EST) - atr * _TP_ATR
                sl_price = (close - _SPREAD_EST) + atr * _SL_ATR
                side     = "sell"

            if not should_trade:
                logger.debug(
                    f"SIGNAL FILTERED  {direction}  ts={bar_ts}  "
                    f"close={close:.5f}  prob={prob:.4f}  thresh={model.threshold:.4f}"
                )
                return

            logger.info(
                f"TRADE SIGNAL  {direction}  ts={bar_ts}  close={close:.5f}  "
                f"prob={prob:.4f}  thresh={model.threshold:.4f}  "
                f"TP={tp_price:.5f}  SL={sl_price:.5f}  "
                f"{'DRY-RUN — order suppressed' if dry_run else ''}"
            )

            if not dry_run:
                exec_engine.send_order(
                    symbol=symbol,
                    side=side,
                    qty=1,
                    price=close,
                )

        except Exception as exc:
            logger.error(f"on_bar error: {exc}", exc_info=True)

    return on_bar


# ── main ──────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False) -> None:
    logger = setup_logger("live_tick_v4", log_file="logs/live_tick_v4.log")
    _start_health_check(logger)

    # ── config from env ───────────────────────────────────────────────────────
    ib_host       = os.getenv("TICK_IB_HOST",    "127.0.0.1")
    ib_port       = int(os.getenv("TICK_IB_PORT", "4002"))
    client_id     = int(os.getenv("TICK_CLIENT_ID", "10"))
    symbol        = os.getenv("TICK_SYMBOL",   "EUR")
    currency      = os.getenv("TICK_CURRENCY", "USD")
    exchange      = os.getenv("TICK_EXCHANGE", "IDEALPRO")
    model_stem    = os.getenv("TICK_MODEL_STEM", "meta_model_ema_eurusd")
    ticks_per_bar = int(os.getenv("TICK_BAR_SIZE", str(_DEFAULT_TICKS_PER_BAR)))
    model_dir     = _PROJECT_ROOT / "trading_system_v4" / "model"

    logger.info(
        f"Starting run_live_tick  symbol={symbol}/{currency}  "
        f"ticks_per_bar={ticks_per_bar}  model={model_stem}  "
        f"dry_run={dry_run}"
    )

    # ── load model ────────────────────────────────────────────────────────────
    logger.info(f"Loading model: {model_stem}")
    model = V4ModelInference(model_stem=model_stem, model_dir=model_dir)
    logger.info(
        f"Model ready — {model.n_features()} features  threshold={model.threshold:.4f}"
    )

    # ── feature builder ───────────────────────────────────────────────────────
    builder = LiveFeatureBuilder()
    logger.info(f"Feature builder ready — warmup={builder.WARMUP} bars")

    # ── execution engine ──────────────────────────────────────────────────────
    exec_engine = ExecutionEngine(broker_api=None)  # TODO: wire real IB broker API

    # ── IBKR connection ───────────────────────────────────────────────────────
    ib = IB()
    logger.info(f"Connecting to IBKR  {ib_host}:{ib_port}  clientId={client_id}")
    ib.connect(ib_host, ib_port, clientId=client_id)
    logger.info("Connected.")

    # ── qualify contract ──────────────────────────────────────────────────────
    contract = Forex(pair=f"{symbol}{currency}", exchange=exchange)
    ib.qualifyContracts(contract)
    logger.info(f"Contract qualified: {contract}")

    # ── tick aggregator ───────────────────────────────────────────────────────
    aggregator = LiveTickAggregator(
        ib=ib,
        contract=contract,
        ticks_per_bar=ticks_per_bar,
        symbol=f"{symbol}{currency}",
    )

    aggregator.on_bar_complete = _make_on_bar_callback(
        builder=builder,
        model=model,
        exec_engine=exec_engine,
        symbol=f"{symbol}/{currency}",
        logger=logger,
        dry_run=dry_run,
    )

    logger.info(
        f"Tick aggregator running — waiting for {ticks_per_bar} ticks per bar.  "
        "Ctrl-C to stop."
    )

    try:
        ib.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    finally:
        ib.disconnect()
        logger.info("Disconnected from IBKR.")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live tick-bar ML trading system")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log signals but do not send orders to the broker.",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
