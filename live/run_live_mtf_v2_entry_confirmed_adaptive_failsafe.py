"""
Live MTF V2 Trading - Entry Confirmed ADAPTIVE with FAIL-SAFE version.

This live runner combines:
- ADAPTIVE entry confirmation (volatility-based, confidence-based adjustments)
- FAIL-SAFE position protection (bracket order verification, emergency flatten)
- Matches backtest performance from run_backtest_mtf_v2_entry_confirmed_adaptive.py
- Ensures NO positions exist without SL/TP bracket orders

Key features:
- Adaptive confirmation logic (high confidence bypass, volatility adjustment)
- 30-second grace period after order submission
- Periodic protection checks every 5 seconds
- Emergency flatten after 3 failed protection checks
- Hour exclusions (weekday-specific)

Execution via NautilusTrader IBKR adapter; bar streaming uses ib_insync (IBBarStreamer).
"""

from __future__ import annotations

import logging
import logging.config
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patches import apply_ib_connection_patch

apply_ib_connection_patch()

from nautilus_trader.adapters.interactive_brokers.config import (
    IBMarketDataTypeEnum,
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecClientConfig,
    InteractiveBrokersInstrumentProviderConfig,
)
from nautilus_trader.adapters.interactive_brokers.factories import (
    InteractiveBrokersLiveDataClientFactory,
    InteractiveBrokersLiveExecClientFactory,
)
from nautilus_trader.config import (
    ImportableStrategyConfig,
    LiveDataEngineConfig,
    LoggingConfig,
    RoutingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.trading.config import StrategyFactory

from config.ibkr_config import get_ibkr_config
from config.mtf_v2_config import load_mtf_v2_config, print_mtf_v2_config
from live.ib_bar_streamer import IBBarStreamer
from utils.run_metadata import log_and_write_run_metadata

logger = logging.getLogger("live_v2_adaptive_failsafe")


class PortfolioFilter(logging.Filter):
    """Filter to suppress noisy portfolio update messages."""
    
    def filter(self, record):
        if "Portfolio" in record.name and "Updated AccountState" in record.getMessage():
            return False
        if any(x in record.name for x in ["Cache", "RiskEngine", "DataEngine"]):
            if "Updated" in record.getMessage():
                return False
        if record.levelno == logging.DEBUG:
            if record.name.startswith("TRADER-V2-ADAPTIVE-FS.InteractiveBrokersClient-"):
                return False
            if record.name.startswith("TRADER-V2-ADAPTIVE-FS.ExecEngine"):
                return False

            noisy_names = (
                "InteractiveBrokersClient",
                "InteractiveBrokersInstrumentProvider",
                "DataClient-INTERACTIVE_BROKERS",
                "ExecEngine",
                "MessageBus",
            )
            if any(n in record.name for n in noisy_names):
                return False
            msg = record.getMessage()
            if any(x in msg for x in ["Msg received", "Msg handled", "Msg buffer", "TWS API", "Checking in-flight orders status"]):
                return False
        return True


def setup_logging(log_dir: Path, start_time: str) -> logging.Logger:
    """Configure logging for live trading."""
    config_path = Path("config/logging.live.yaml")
    with config_path.open("r", encoding="utf-8") as stream:
        logging_config = yaml.safe_load(stream)

    log_dir.mkdir(parents=True, exist_ok=True)

    handler_mappings = {
        "file": "application.log",
        "live_file": "live_trading.log",
        "strategy_file": "strategy.log",
        "orders_file": "orders.log",
        "trades_file": "trades.log",
        "errors_file": "errors.log",
    }

    for handler_name, filename in handler_mappings.items():
        if handler_name in logging_config.get("handlers", {}):
            logging_config["handlers"][handler_name]["filename"] = str(log_dir / filename)

    logging.config.dictConfig(logging_config)

    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.addFilter(PortfolioFilter())
            if handler.level == logging.DEBUG:
                handler.setLevel(logging.INFO)

    console_log_file = log_dir / f"console_adaptive_failsafe_{start_time}.log"
    console_handler = logging.FileHandler(console_log_file, mode="w")
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(console_handler)

    logging.getLogger("nautilus_trader.portfolio").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.cache").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.common").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.execution").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.risk").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.adapters.interactive_brokers").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-ADAPTIVE-FS.InteractiveBrokersClient-018").setLevel(logging.INFO)
    logging.getLogger("TRADER-V2-ADAPTIVE-FS.InteractiveBrokersClient-019").setLevel(logging.INFO)
    logging.getLogger("TRADER-V2-ADAPTIVE-FS.ExecEngine").setLevel(logging.INFO)

    log = logging.getLogger("live_v2_adaptive_failsafe")
    log.info("V2 ADAPTIVE FAIL-SAFE live logging configured. Logs directory: %s", log_dir)
    log.info("Console log (this run): %s", console_log_file)
    log.info("Strategy log: %s", log_dir / "strategy.log")

    log_and_write_run_metadata(
        log,
        output_dir=log_dir,
        run_kind="live",
        run_id=start_time,
        entrypoint=__file__,
        extra={"logger": "live_v2_adaptive_failsafe", "log_dir": str(log_dir)},
    )
    return log


def _resolve_market_data_type(value: str) -> IBMarketDataTypeEnum:
    mapping = {
        "REALTIME": IBMarketDataTypeEnum.REALTIME,
        "DELAYED": IBMarketDataTypeEnum.DELAYED,
        "DELAYED_FROZEN": IBMarketDataTypeEnum.DELAYED_FROZEN,
    }
    return mapping.get(value.upper(), IBMarketDataTypeEnum.DELAYED_FROZEN)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def main() -> int:
    """Entry point for V2 ADAPTIVE FAIL-SAFE live trading."""

    # Load V2 configuration
    live_config = load_mtf_v2_config()

    # Entry confirmation env knobs (basic)
    entry_confirmation_enabled = _env_bool("MTF2_ENTRY_CONFIRM_ENABLED", True)
    entry_confirmation_bars = _env_int("MTF2_ENTRY_CONFIRM_BARS", 2)
    entry_confirmation_threshold = _env_float("MTF2_ENTRY_CONFIRM_THRESHOLD", 0.22)
    entry_max_wait_bars = _env_int("MTF2_ENTRY_CONFIRM_MAX_WAIT_BARS", 8)

    # ADAPTIVE parameters (match backtest)
    high_confidence_bypass_threshold = _env_float("MTF2_HIGH_CONFIDENCE_BYPASS_THRESHOLD", 0.8)
    volatility_adjustment_enabled = _env_bool("MTF2_VOLATILITY_ADJUSTMENT_ENABLED", True)
    volatility_high_threshold = _env_float("MTF2_VOLATILITY_HIGH_THRESHOLD", 0.003)
    volatility_low_threshold = _env_float("MTF2_VOLATILITY_LOW_THRESHOLD", 0.001)
    volatility_high_bars = _env_int("MTF2_VOLATILITY_HIGH_BARS", 2)
    volatility_low_threshold_reduction = _env_float("MTF2_VOLATILITY_LOW_THRESHOLD_REDUCTION", 0.05)

    # Optional: confidence-tiered SL
    confidence_sl_enabled = _env_bool("MTF2_CONF_SL_ENABLED", False)
    confidence_sl_tiers = (os.getenv("MTF2_CONF_SL_TIERS") or "").strip()
    confidence_sl_interpolate = _env_bool("MTF2_CONF_SL_INTERPOLATE", False)

    # Setup logging with timestamp
    start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("logs/live_mtf")
    setup_logging(log_dir, start_time)

    logger.info("=" * 80)
    logger.info("MTF V2 LIVE TRADING - ADAPTIVE + FAIL-SAFE VERSION")
    logger.info("=" * 80)
    print_mtf_v2_config(live_config)

    logger.info(
        "Entry Confirmation: enabled=%s bars=%s threshold=%s max_wait=%s",
        entry_confirmation_enabled,
        entry_confirmation_bars,
        entry_confirmation_threshold,
        entry_max_wait_bars,
    )

    logger.info(
        "ADAPTIVE Parameters: high_conf_bypass=%s volatility_adj=%s",
        high_confidence_bypass_threshold,
        volatility_adjustment_enabled,
    )
    
    if volatility_adjustment_enabled:
        logger.info(
            "Volatility Thresholds: high=%s low=%s high_bars=%s reduction=%s",
            volatility_high_threshold,
            volatility_low_threshold,
            volatility_high_bars,
            volatility_low_threshold_reduction,
        )

    logger.info("FAIL-SAFE Protection: ENABLED (30s grace, 3 checks, 5s interval)")

    logger.info(
        "Confidence SL: enabled=%s tiers=%s interpolate=%s",
        confidence_sl_enabled,
        confidence_sl_tiers if confidence_sl_tiers else "<empty>",
        confidence_sl_interpolate,
    )

    # Get IBKR config
    _ = get_ibkr_config()

    logger.info(
        "IBKR connection: host=%s port=%s client_id=%s account=%s",
        live_config.ib_host,
        live_config.ib_port,
        live_config.ib_client_id,
        live_config.ib_account,
    )

    instrument_provider_config = InteractiveBrokersInstrumentProviderConfig(
        load_ids=frozenset([live_config.instrument]),
        min_expiry_days=10,
        build_futures_chain=False,
        build_options_chain=False,
    )

    market_data_type = _resolve_market_data_type(live_config.ib_market_data_type)

    data_client_config = InteractiveBrokersDataClientConfig(
        ibg_host=live_config.ib_host,
        ibg_port=live_config.ib_port,
        ibg_client_id=live_config.ib_client_id,
        use_regular_trading_hours=False,
        market_data_type=market_data_type,
        instrument_provider=instrument_provider_config,
    )

    exec_client_config = InteractiveBrokersExecClientConfig(
        ibg_host=live_config.ib_host,
        ibg_port=live_config.ib_port,
        ibg_client_id=live_config.ib_client_id + 1,
        account_id=live_config.ib_account,
        instrument_provider=instrument_provider_config,
        routing=RoutingConfig(default=True),
    )

    # Strategy config: USE COMBINED ADAPTIVE + FAIL-SAFE STRATEGY
    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe:MLSignalStrategyV2EntryConfirmedAdaptiveFailSafe",
        config_path="strategies.ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe:MLSignalStrategyV2EntryConfirmedAdaptiveConfig",
        config={
            "instrument_id": live_config.instrument,
            "bar_type": live_config.bar_type,
            "model_path": str(Path(live_config.model_path).resolve()),
            # Position sizing
            "total_position_size": live_config.total_position_size,
            "pos1_fraction": live_config.pos1_fraction,
            "pos2_fraction": live_config.pos2_fraction,
            "pos3_fraction": live_config.pos3_fraction,
            # SL/TP
            "sl_atr_mult": live_config.sl_atr_mult,
            "pos1_tp_atr_mult": live_config.pos1_tp_atr_mult,
            "pos2_tp_atr_mult": live_config.pos2_tp_atr_mult,
            "pos3_tp_atr_mult": live_config.pos3_tp_atr_mult,
            "trailing_distance_atr_mult": live_config.trailing_distance_atr_mult,
            # Filters
            "prediction_threshold": live_config.prediction_threshold,
            "prediction_threshold_long": live_config.prediction_threshold_long,
            "prediction_threshold_short": live_config.prediction_threshold_short,
            "trade_start_hour": live_config.trade_start_hour,
            "trade_end_hour": live_config.trade_end_hour,
            "entry_cooldown_bars": live_config.entry_cooldown_bars,
            "min_atr": live_config.min_atr,
            "max_atr": live_config.max_atr,
            "excluded_hours_mode": live_config.excluded_hours_mode,
            "config_timezone": live_config.config_timezone,
            "excluded_hours_monday": live_config.excluded_hours_monday,
            "excluded_hours_tuesday": live_config.excluded_hours_tuesday,
            "excluded_hours_wednesday": live_config.excluded_hours_wednesday,
            "excluded_hours_thursday": live_config.excluded_hours_thursday,
            "excluded_hours_friday": live_config.excluded_hours_friday,
            "excluded_hours_saturday": live_config.excluded_hours_saturday,
            "excluded_hours_sunday": live_config.excluded_hours_sunday,
            # Entry confirmation (basic)
            "entry_confirmation_enabled": entry_confirmation_enabled,
            "entry_confirmation_bars": entry_confirmation_bars,
            "entry_confirmation_threshold": entry_confirmation_threshold,
            "entry_max_wait_bars": entry_max_wait_bars,
            # ADAPTIVE parameters
            "high_confidence_bypass_threshold": high_confidence_bypass_threshold,
            "volatility_adjustment_enabled": volatility_adjustment_enabled,
            "volatility_high_threshold": volatility_high_threshold,
            "volatility_low_threshold": volatility_low_threshold,
            "volatility_high_bars": volatility_high_bars,
            "volatility_low_threshold_reduction": volatility_low_threshold_reduction,
            # Confidence-tiered SL
            "confidence_sl_enabled": confidence_sl_enabled,
            "confidence_sl_tiers": confidence_sl_tiers,
            "confidence_sl_interpolate": confidence_sl_interpolate,
        },
    )

    log_dir = Path("logs/trader_logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    node_config = TradingNodeConfig(
        trader_id="TRADER-V2-ADAPTIVE-FS",
        logging=LoggingConfig(
            log_level="INFO",
            log_level_file="DEBUG",
            log_directory=str(log_dir.resolve()),
            log_component_levels={
                "Portfolio": "WARNING",
                "Cache": "WARNING",
                "RiskEngine": "WARNING",
                "DataEngine": "WARNING",
                "MessageBus": "WARNING",
                "ExecEngine": "WARNING",
                "InteractiveBrokersClient": "WARNING",
            },
        ),
        data_engine=LiveDataEngineConfig(
            time_bars_build_with_no_updates=True,
            time_bars_timestamp_on_close=True,
            validate_data_sequence=False,
        ),
        data_clients={"INTERACTIVE_BROKERS": data_client_config},
        exec_clients={"INTERACTIVE_BROKERS": exec_client_config},
        timeout_connection=60.0,
        timeout_reconciliation=30.0,
        timeout_portfolio=30.0,
        timeout_disconnection=10.0,
    )

    node = TradingNode(config=node_config)
    node.add_data_client_factory("INTERACTIVE_BROKERS", InteractiveBrokersLiveDataClientFactory)
    node.add_exec_client_factory("INTERACTIVE_BROKERS", InteractiveBrokersLiveExecClientFactory)
    node.build()

    # Create strategy instance
    strategy_instance = StrategyFactory.create(strategy_config)
    node.trader.add_strategy(strategy_instance)

    logger.info("=" * 80)
    logger.info("V2 ADAPTIVE FAIL-SAFE STRATEGY")
    logger.info("=" * 80)
    logger.info("Instrument: %s", live_config.instrument)
    logger.info("Bar Type (signal): %s", live_config.bar_type)
    logger.info("Bar data: ib_insync (keepUpToDate=True)")
    logger.info("Execution: NautilusTrader IBKR adapter")
    logger.info("Strategy: MLSignalStrategyV2EntryConfirmedAdaptiveFailSafe (ADAPTIVE + FAIL-SAFE)")
    logger.info("Adaptive: High-confidence bypass, volatility adjustment")
    logger.info("Fail-Safe: 30s grace period, 5s check interval, 3 max failures")
    logger.info("=" * 80)

    # Create ib_insync bar streamer with different client ID
    bar_streamer = IBBarStreamer(
        host=live_config.ib_host,
        port=live_config.ib_port,
        client_id=live_config.ib_client_id + 2,
    )

    logger.info("Connecting ib_insync bar streamer...")
    if not bar_streamer.connect():
        logger.error("Failed to connect bar streamer")
        return 1

    # Parse bar size from bar_type
    bar_spec = live_config.bar_type.split("-", 1)[1]
    parts = bar_spec.split("-")
    step = int(parts[0])
    unit = parts[1].upper()

    if unit == "MINUTE":
        bar_size_15m = f"{step} mins" if step > 1 else "1 min"
    elif unit == "HOUR":
        bar_size_15m = f"{step} hour" if step == 1 else f"{step} hours"
    else:
        bar_size_15m = f"{step} mins"

    price_type = parts[2].upper() if len(parts) > 2 else "MID"
    if price_type == "MID":
        what_to_show = "MIDPOINT"
    elif price_type == "BID":
        what_to_show = "BID"
    elif price_type == "ASK":
        what_to_show = "ASK"
    else:
        what_to_show = "TRADES"

    symbol = live_config.symbol

    bar_type_str_15m = live_config.bar_type
    if unit == "MINUTE":
        bar_type_str_1m = live_config.bar_type.replace(f"{step}-MINUTE", "1-MINUTE")
    elif unit == "HOUR":
        bar_type_str_1m = live_config.bar_type.replace(f"{step}-HOUR", "1-MINUTE")
    else:
        bar_type_str_1m = live_config.bar_type.replace(f"{step}-{unit}", "1-MINUTE")

    logger.info("Subscribing to %s %s bars via ib_insync...", symbol, bar_size_15m)
    ok_15m = bar_streamer.subscribe_bars_sync(
        symbol=symbol,
        bar_size=bar_size_15m,
        what_to_show=what_to_show,
        callback=strategy_instance.on_bar,
        use_rth=False,
        duration="8 D",
        bar_type_str=bar_type_str_15m,
    )

    logger.info("Subscribing to %s 1 min bars via ib_insync...", symbol)
    ok_1m = bar_streamer.subscribe_bars_sync(
        symbol=symbol,
        bar_size="1 min",
        what_to_show=what_to_show,
        callback=strategy_instance.on_bar,
        use_rth=False,
        duration="2 D",
        bar_type_str=bar_type_str_1m,
    )

    if not ok_15m or not ok_1m:
        logger.error("Failed to subscribe to required bar streams (15m=%s, 1m=%s)", ok_15m, ok_1m)
        bar_streamer.disconnect()
        return 1

    logger.info("Bar subscriptions active (15m + 1m) - historical bars delivered for warmup")
    logger.info("Starting NautilusTrader node...")

    import threading
    import time

    return_code = 0

    def _handle_signal(_sig, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handle_signal)

    try:
        node_thread = threading.Thread(target=node.run, daemon=True)
        node_thread.start()
        logger.info("NautilusTrader node started in background thread")

        logger.info("Waiting for instrument to load into cache...")
        for i in range(15):
            time.sleep(1)
            instrument = strategy_instance.cache.instrument(strategy_instance.instrument_id)
            if instrument:
                logger.info("Instrument loaded after %ss: %s", i + 1, instrument.id)
                break
        else:
            logger.warning("Instrument still not loaded after 15s - strategy will wait for it")

        logger.info("V2 ADAPTIVE FAIL-SAFE live trading active. Press Ctrl+C to stop.")

        bar_streamer._running = True

        health_check_interval = 60
        status_report_interval = 1800
        last_health_check = time.time()
        last_status_report = time.time()

        logger.info("Health check enabled: every %ss, max bar age 20 mins", health_check_interval)
        logger.info("Status report: every %s minutes", status_report_interval // 60)

        while True:
            time.sleep(1)

            if bar_streamer.needs_reconnect():
                logger.info("Executing reconnection from main thread...")
                bar_streamer._reconnect()
                continue

            if bar_streamer.is_reconnecting():
                continue

            now = time.time()

            if now - last_status_report >= status_report_interval:
                last_status_report = now
                try:
                    portfolio = node.trader.portfolio
                    account = portfolio.account(node.trader.account_ids[0]) if node.trader.account_ids else None
                    if account:
                        logger.info("=" * 60)
                        logger.info("STATUS REPORT")
                        logger.info("Account Balance: %s", account.balance_total())
                        logger.info("Unrealized PnL: %s", account.unrealized_pnl())
                        logger.info("Open Positions: %s", len(portfolio.positions_open()))
                        bar_age = bar_streamer.get_last_bar_age_seconds()
                        if bar_age is not None:
                            logger.info("Last bar received: %ss ago", int(bar_age))
                        logger.info("IB Connected: %s", bar_streamer.is_connected())
                        logger.info("=" * 60)
                except Exception as e:
                    logger.warning("Could not generate status report: %s", e)

            if now - last_health_check >= health_check_interval:
                last_health_check = now
                healthy = bar_streamer.check_health(max_bar_age_minutes=20)
                if not healthy:
                    logger.warning("Health check failed - reconnection scheduled")

    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt received")
    except Exception as exc:
        logger.exception("V2 ADAPTIVE FAIL-SAFE live trading error: %s", exc)
        return_code = 1
    finally:
        logger.info("Shutting down V2 ADAPTIVE FAIL-SAFE...")
        bar_streamer.disconnect()
        try:
            node.dispose()
        except Exception as e:
            logger.warning("Error disposing node: %s", e)
        logger.info("V2 ADAPTIVE FAIL-SAFE live trading system stopped.")

    return return_code


if __name__ == "__main__":
    sys.exit(main())
