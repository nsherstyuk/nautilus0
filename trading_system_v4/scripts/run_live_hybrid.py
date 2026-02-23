"""
Hybrid live trading runner: v4 ML model gates entry signals from live 5m bars.

Architecture:
  1. Three FeatureEngineer instances maintain rolling windows for 5m, 15m, 1D.
  2. On each completed 15m / 1D bar: update HTF feature cache (thread-safe).
  3. On each completed 5m bar:
       a. Compute 36 base features (5m).
       b. Fetch latest HTF feature dicts from cache, apply htf_ / d1_ prefixes.
       c. Compute cross-frame feature close_vs_htf_midpoint.
       d. Merge into one flat dict; call V4ModelInference.should_trade().
       e. Gate orders: only trade when model prob >= EV-optimal threshold.

Configuration (env / constructor args):
  V4_MODEL_STEM  — model artifact stem, default "hybrid_model_eurusd_v4"
  V4_SYMBOL      — e.g. "EUR/USD", default "EUR/USD"
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path for imports
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from trading_system_v4.data.nautilus_adapter import NautilusDataAdapter
from trading_system_v4.features.feature_engineering import FeatureEngineer
from trading_system_v4.model.model_inference import V4ModelInference
from trading_system_v4.execution.execution_engine import ExecutionEngine
from trading_system_v4.risk.risk_manager import RiskManager
from trading_system_v4.monitoring.logger import setup_logger

# Session / time columns that are NOT included in the HTF feature vectors
# (matches _HTF_REMOVE_TIME_COLS in add_htf_features.py)
_HTF_REMOVE_TIME_COLS = frozenset({
    "is_london", "is_ny", "is_overlap", "is_session_open",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
})


# ── health check ──────────────────────────────────────────────────────────────

def start_health_check(logger, interval: int = 60) -> None:
    def _loop():
        while True:
            logger.info("HEALTHCHECK: System alive and running.")
            time.sleep(interval)
    threading.Thread(target=_loop, daemon=True).start()


# ── HTF feature cache (thread-safe last-value store) ─────────────────────────

class _HtfCache:
    """
    Thread-safe container that stores the most recently completed 15m and 1D
    feature dicts (with prefixes applied) plus the raw last bar midpoints.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._htf_features: dict = {}   # htf_* keys
        self._d1_features:  dict = {}   # d1_* keys
        self._htf_midpoint: Optional[float] = None   # (open+close)/2 of last 15m bar

    def update_htf(self, features_dict: dict, raw_bar: dict) -> None:
        prefixed = {
            f"htf_{k}": v
            for k, v in features_dict.items()
            if k not in _HTF_REMOVE_TIME_COLS
        }
        try:
            midpoint = (float(raw_bar["open"]) + float(raw_bar["close"])) / 2
        except (KeyError, TypeError, ValueError):
            midpoint = None
        with self._lock:
            self._htf_features = prefixed
            self._htf_midpoint = midpoint

    def update_d1(self, features_dict: dict) -> None:
        prefixed = {
            f"d1_{k}": v
            for k, v in features_dict.items()
            if k not in _HTF_REMOVE_TIME_COLS
        }
        with self._lock:
            self._d1_features = prefixed

    def get_merged(self, close_5m: float) -> dict:
        """Return {htf_*, d1_*, close_vs_htf_midpoint} snapshot."""
        with self._lock:
            merged: dict = {}
            merged.update(self._htf_features)
            merged.update(self._d1_features)
            if self._htf_midpoint is not None:
                merged["close_vs_htf_midpoint"] = (
                    (close_5m - self._htf_midpoint) / (abs(close_5m) + 1e-10)
                )
        return merged

    @property
    def is_ready(self) -> bool:
        with self._lock:
            return bool(self._htf_features) and bool(self._d1_features)


# ── bar handler factory ───────────────────────────────────────────────────────

def make_pipeline(
    model_long: V4ModelInference,
    model_short: V4ModelInference,
    exec_engine: ExecutionEngine,
    risk_mgr: RiskManager,
    htf_cache: _HtfCache,
    logger,
):
    """
    Return the on_5m_bar callback that gates orders behind the ML model.
    This is called for every completed 5m bar.
    """
    fe_5m = FeatureEngineer(window=250)

    def on_5m_bar(bar: dict) -> None:
        try:
            features_5m = fe_5m.add_bar(bar)
            if not features_5m:
                return   # still warming up

            if not htf_cache.is_ready:
                logger.debug("HTF cache not yet populated — skipping bar.")
                return

            close_5m = float(bar.get("close", 0.0))
            htf_features = htf_cache.get_merged(close_5m)

            # Merge all features into one flat dict
            all_features: dict = {}
            all_features.update(features_5m)
            all_features.update(htf_features)

            should_trade_long, prob_long = model_long.should_trade(all_features)
            should_trade_short, prob_short = model_short.should_trade(all_features)
            
            logger.debug(
                f"5m bar {bar.get('timestamp')}  "
                f"long_prob={prob_long:.4f} (thresh={model_long.threshold:.4f})  "
                f"short_prob={prob_short:.4f} (thresh={model_short.threshold:.4f})"
            )

            if not should_trade_long and not should_trade_short:
                return

            portfolio = exec_engine.portfolio
            
            if should_trade_long:
                if risk_mgr.check_risk(portfolio, signal=1):
                    exec_engine.send_order(bar["symbol"], "buy", qty=1)
                    logger.info(
                        f"LONG ORDER SENT  symbol={bar['symbol']}  prob={prob_long:.4f}  "
                        f"bar_close={close_5m:.5f}"
                    )
                else:
                    logger.warning(f"Risk check blocked long order  prob={prob_long:.4f}")
                    
            if should_trade_short:
                if risk_mgr.check_risk(portfolio, signal=-1):
                    exec_engine.send_order(bar["symbol"], "sell", qty=1)
                    logger.info(
                        f"SHORT ORDER SENT  symbol={bar['symbol']}  prob={prob_short:.4f}  "
                        f"bar_close={close_5m:.5f}"
                    )
                else:
                    logger.warning(f"Risk check blocked short order  prob={prob_short:.4f}")

        except Exception as exc:
            logger.error(f"on_5m_bar error: {exc}", exc_info=True)

    return on_5m_bar


def make_htf_updater(fe: FeatureEngineer, cache: _HtfCache, update_fn, logger):
    """Return callback for 15m bars that refreshes the HTF cache."""
    def on_htf_bar(bar: dict) -> None:
        try:
            feats = fe.add_bar(bar)
            if feats:
                update_fn(feats, bar)
        except Exception as exc:
            logger.error(f"on_htf_bar error: {exc}", exc_info=True)
    return on_htf_bar


def make_d1_updater(fe: FeatureEngineer, cache: _HtfCache, logger):
    """Return callback for 1D bars that refreshes the D1 cache."""
    def on_d1_bar(bar: dict) -> None:
        try:
            feats = fe.add_bar(bar)
            if feats:
                cache.update_d1(feats)
        except Exception as exc:
            logger.error(f"on_d1_bar error: {exc}", exc_info=True)
    return on_d1_bar


# ── main entry point ──────────────────────────────────────────────────────────

def main() -> None:
    logger = setup_logger("live_hybrid_v4", log_file="logs/live_hybrid_v4.log")
    start_health_check(logger, interval=60)

    symbol     = os.getenv("V4_SYMBOL", "EUR/USD")
    model_stem = os.getenv("V4_MODEL_STEM", "hybrid_model_v4_eurusd")
    model_dir  = _PROJECT_ROOT / "trading_system_v4" / "model"

    logger.info(f"Loading v4 models: {model_stem}_long and {model_stem}_short  symbol={symbol}")
    model_long = V4ModelInference(model_stem=f"{model_stem}_long", model_dir=model_dir)
    model_short = V4ModelInference(model_stem=f"{model_stem}_short", model_dir=model_dir)
    
    logger.info(
        f"Long Model ready — {model_long.n_features()} features, "
        f"threshold={model_long.threshold:.4f}"
    )
    logger.info(
        f"Short Model ready — {model_short.n_features()} features, "
        f"threshold={model_short.threshold:.4f}"
    )

    exec_engine = ExecutionEngine(broker_api=None)   # TODO: wire real broker API
    risk_mgr    = RiskManager(max_position_size=1, max_drawdown=0.1)
    htf_cache   = _HtfCache()

    # 15m feature engineer + subscription
    fe_15m    = FeatureEngineer(window=250)
    adapter_15m = NautilusDataAdapter(symbol=symbol, venue="IDEALPRO", bar_size="15m")
    adapter_15m.subscribe(
        make_htf_updater(fe_15m, htf_cache, htf_cache.update_htf, logger)
    )

    # 1D feature engineer + subscription
    fe_1d    = FeatureEngineer(window=250)
    adapter_1d = NautilusDataAdapter(symbol=symbol, venue="IDEALPRO", bar_size="1d")
    adapter_1d.subscribe(
        make_d1_updater(fe_1d, htf_cache, logger)
    )

    # 5m subscription — main trading callback
    adapter_5m = NautilusDataAdapter(symbol=symbol, venue="IDEALPRO", bar_size="5m")
    adapter_5m.subscribe(
        make_pipeline(model_long, model_short, exec_engine, risk_mgr, htf_cache, logger)
    )

    logger.info("Live pipeline running.  Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
        adapter_5m.stop()
        adapter_15m.stop()
        adapter_1d.stop()


# ── dev/test entry point ──────────────────────────────────────────────────────

def test_live_ingestion() -> None:
    logger = setup_logger("test_live_ingestion")
    adapter = NautilusDataAdapter(symbol="EUR/USD", venue="IDEALPRO", bar_size="5m")
    fe = FeatureEngineer(window=5)

    def print_bar_and_features(bar: dict) -> None:
        logger.info(f"Bar: {bar}")
        feats = fe.add_bar(bar)
        logger.info(f"Features ({len(feats)}): {feats}")

    adapter.subscribe(print_bar_and_features)
    time.sleep(16)
    adapter.stop()
    logger.info("Test complete.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_live_ingestion()
    else:
        main()
