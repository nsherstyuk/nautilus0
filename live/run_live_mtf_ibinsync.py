"""
Live MTF Trading with ib_insync Bar Streaming.

This version uses ib_insync directly for bar data instead of NautilusTrader's
IBKR data client. This ensures reliable live bar delivery with keepUpToDate=True.

NautilusTrader is still used for:
- Order execution
- Position management
- Risk management

But bar data comes from ib_insync directly.
"""
from __future__ import annotations

import logging
import logging.config
import signal
import sys
from pathlib import Path
from typing import Optional

import yaml

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patches import apply_ib_connection_patch
apply_ib_connection_patch()

from nautilus_trader.trading.config import StrategyFactory
from nautilus_trader.adapters.interactive_brokers.common import IB_VENUE
from nautilus_trader.adapters.interactive_brokers.config import (
    IBMarketDataTypeEnum,
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecClientConfig,
    InteractiveBrokersInstrumentProviderConfig,
    SymbologyMethod,
)
from nautilus_trader.adapters.interactive_brokers.factories import (
    InteractiveBrokersLiveDataClientFactory,
    InteractiveBrokersLiveExecClientFactory,
)
from nautilus_trader.config import (
    ImportableStrategyConfig,
    LiveDataEngineConfig,
    LiveExecEngineConfig,
    LoggingConfig,
    RoutingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode

from config.ibkr_config import get_ibkr_config
from config.mtf_config import load_mtf_config, validate_mtf_config, print_mtf_config
from live.ib_bar_streamer import IBBarStreamer

logger = logging.getLogger("live")


def setup_logging(log_dir: Path) -> logging.Logger:
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
    
    # Add console output capture to file
    console_handler = logging.FileHandler(log_dir / "console_output.log", mode='a')
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    
    # Add to root logger to capture ALL output
    root_logger = logging.getLogger()
    root_logger.addHandler(console_handler)
    
    log = logging.getLogger("live")
    log.info("Live logging configured. Logs directory: %s", log_dir)
    log.info("Console output will be saved to: %s", log_dir / "console_output.log")
    return log


def _resolve_market_data_type(value: str) -> IBMarketDataTypeEnum:
    mapping = {
        "REALTIME": IBMarketDataTypeEnum.REALTIME,
        "DELAYED": IBMarketDataTypeEnum.DELAYED,
        "DELAYED_FROZEN": IBMarketDataTypeEnum.DELAYED_FROZEN,
    }
    return mapping.get(value.upper(), IBMarketDataTypeEnum.DELAYED_FROZEN)


def main() -> int:
    """Entry point for live trading with ib_insync bar streaming."""
    
    # Load configuration
    live_config = load_mtf_config()
    if not validate_mtf_config(live_config):
        logger.error("MTF configuration validation failed")
        return 1
    
    # Setup logging
    log_dir = Path("logs/live_mtf")
    setup_logging(log_dir)
    
    logger.info("Starting MTF ML live trading system with ib_insync bar streaming...")
    print_mtf_config(live_config)
    
    # Get IBKR config
    ibkr = get_ibkr_config()
    
    logger.info(
        "IBKR connection details: host=%s port=%s client_id=%s account=%s",
        live_config.ib_host,
        live_config.ib_port,
        live_config.ib_client_id,
        live_config.ib_account,
    )
    
    # Build NautilusTrader node (for execution only)
    instrument_provider_config = InteractiveBrokersInstrumentProviderConfig(
        load_ids=frozenset([f"{live_config.symbol}.{live_config.venue}"]),
        min_expiry_days=10,
        build_futures_chain=False,
        build_options_chain=False,
    )
    
    market_data_type = _resolve_market_data_type(live_config.ib_market_data_type)
    
    # NOTE: We still create a data client but won't use it for bar subscriptions
    # It's needed for instrument loading
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
        ibg_client_id=live_config.ib_client_id + 1,  # Different client ID
        account_id=live_config.ib_account,
        instrument_provider=instrument_provider_config,
        routing=RoutingConfig(default=True),  # Route all orders to this client
    )
    
    # Build strategy config
    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf:MLSignalStrategy",
        config_path="strategies.ml_strategy_config:MLSignalStrategyConfig",
        config={
            "order_id_tag": "MTF",
            "instrument_id": f"{live_config.symbol}.{live_config.venue}",
            "bar_spec": live_config.bar_spec,
            "model_path": str(Path(live_config.model_path).resolve()),
            "prediction_threshold": live_config.prediction_threshold,
            "feature_warmup_bars": live_config.feature_warmup_bars,
            "position_size": live_config.position_size,
            "sl_atr_mult": live_config.sl_atr_mult,
            "tp_atr_mult": live_config.tp_atr_mult,
            "trailing_stop_enabled": live_config.trailing_stop_enabled,
            "trailing_activation_atr_mult": live_config.trailing_activation_atr_mult,
            "trailing_distance_atr_mult": live_config.trailing_distance_atr_mult,
            "partial_close_enabled": live_config.partial_close_enabled,
            "partial_close_atr_mult": live_config.partial_close_atr_mult,
            "partial_close_fraction": live_config.partial_close_fraction,
            "partial_close_move_sl_to_be": live_config.partial_close_move_sl_to_be,
            # Multi-layer exits
            "multi_layer_enabled": live_config.multi_layer_enabled,
            "multi_layer_count": live_config.multi_layer_count,
            "multi_layer_sizes": live_config.multi_layer_sizes,
            "multi_layer_triggers": live_config.multi_layer_triggers,
            "multi_layer_move_sl_to_be": live_config.multi_layer_move_sl_to_be,
            "session_start": live_config.session_start,
            "session_end": live_config.session_end,
            "excluded_hours": live_config.excluded_hours,
            "excluded_hours_by_weekday": live_config.excluded_hours_by_weekday,
            "min_atr": live_config.min_atr,
            "cooldown_minutes": live_config.cooldown_minutes,
            "debug_mode": live_config.debug_mode,
            "max_positions": live_config.max_positions,
            "enforce_position_limit": live_config.enforce_position_limit,
        },
    )
    
    node_config = TradingNodeConfig(
        trader_id=f"TRADER-MTF-001",
        logging=LoggingConfig(log_level="INFO", log_level_file="DEBUG"),
        data_engine=LiveDataEngineConfig(
            time_bars_build_with_no_updates=True,
            time_bars_timestamp_on_close=True,
            validate_data_sequence=False,
        ),
        data_clients={"INTERACTIVE_BROKERS": data_client_config},
        exec_clients={"INTERACTIVE_BROKERS": exec_client_config},  # routing=default=True handles venue mapping
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
    logger.info("MTF STRATEGY - IB_INSYNC BAR STREAMING")
    logger.info("=" * 80)
    logger.info(f"Symbol: {live_config.symbol}")
    logger.info(f"Bar Spec: {live_config.bar_spec}")
    logger.info(f"Warmup: {live_config.feature_warmup_bars} bars")
    logger.info("Bar data: ib_insync (keepUpToDate=True)")
    logger.info("Execution: NautilusTrader IBKR adapter")
    logger.info("=" * 80)
    
    # Create ib_insync bar streamer with different client ID
    bar_streamer = IBBarStreamer(
        host=live_config.ib_host,
        port=live_config.ib_port,
        client_id=live_config.ib_client_id + 2,  # Different from data and exec clients
    )
    
    # Connect bar streamer (synchronous - ib_insync handles its own event loop)
    logger.info("Connecting ib_insync bar streamer...")
    if not bar_streamer.connect():
        logger.error("Failed to connect bar streamer")
        return 1
    
    # Parse bar size from bar_spec (e.g., "15-MINUTE-MID-EXTERNAL" -> "15 mins")
    parts = live_config.bar_spec.split('-')
    step = int(parts[0])
    unit = parts[1].upper()
    
    if unit == "MINUTE":
        bar_size = f"{step} mins" if step > 1 else "1 min"
    elif unit == "HOUR":
        bar_size = f"{step} hour" if step == 1 else f"{step} hours"
    else:
        bar_size = f"{step} mins"
    
    # Determine what_to_show from bar_spec
    price_type = parts[2].upper() if len(parts) > 2 else "MID"
    if price_type == "MID":
        what_to_show = "MIDPOINT"
    elif price_type == "BID":
        what_to_show = "BID"
    elif price_type == "ASK":
        what_to_show = "ASK"
    else:
        what_to_show = "TRADES"
    
    # Subscribe to bars via ib_insync (synchronous)
    logger.info(f"Subscribing to {live_config.symbol} {bar_size} bars via ib_insync...")
    
    success = bar_streamer.subscribe_bars_sync(
        symbol=live_config.symbol,
        bar_size=bar_size,
        what_to_show=what_to_show,
        callback=strategy_instance.on_bar,  # Feed bars directly to strategy
        use_rth=False,
        duration="2 D",  # Get 2 days of history for warmup
    )
    
    if not success:
        logger.error("Failed to subscribe to bars")
        bar_streamer.disconnect()
        return 1
    
    logger.info("Bar subscription active - live bars will flow to strategy")
    logger.info("Starting combined ib_insync + NautilusTrader event loop...")
    
    # Run both ib_insync and NautilusTrader together
    return_code = 0
    try:
        # Start NautilusTrader node in a separate thread
        import threading
        import time
        node_thread = threading.Thread(target=node.run, daemon=True)
        node_thread.start()
        logger.info("NautilusTrader node started in background thread")
        
        # Give node time to fully start and load instruments
        time.sleep(5)
        
        # Run simple sleep loop - ib_insync processes events in background
        logger.info("Live trading active. Press Ctrl+C to stop.")
        
        # Keep main thread alive - ib_insync and NautilusTrader run in background
        while True:
            time.sleep(1)  # Simple sleep, no event loop conflicts
            
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt received")
    except Exception as exc:
        logger.exception("Live trading error: %s", exc)
        return_code = 1
    finally:
        logger.info("Shutting down...")
        bar_streamer.disconnect()
        
        try:
            node.dispose()
        except Exception as e:
            logger.warning(f"Error disposing node: {e}")
        
        logger.info("Live trading system stopped.")
    
    return return_code


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        exit_code = 0
    sys.exit(exit_code)
