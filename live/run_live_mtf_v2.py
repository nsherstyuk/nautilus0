"""
Live MTF V2 Trading - Three-Position Bracket Approach.

This uses the V2 strategy that opens 3 separate positions instead of partial closes:
- POS1 (70%): Quick win at 0.9x ATR
- POS2 (25%): Extended at 1.75x ATR, SL->BE after POS1 TP
- POS3 (5%):  Runner at 1.75x ATR, converts to trailing after POS2 TP

Uses ib_insync for bar data and NautilusTrader for execution.
"""
from __future__ import annotations

import logging
import logging.config
import signal
import sys
from datetime import datetime
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
from config.mtf_v2_config import load_mtf_v2_config, print_mtf_v2_config
from live.ib_bar_streamer import IBBarStreamer
from utils.run_metadata import log_and_write_run_metadata

logger = logging.getLogger("live_v2")


class PortfolioFilter(logging.Filter):
    """Filter out noisy Portfolio/Cache/RiskEngine messages from console."""
    def filter(self, record):
        # Block Portfolio AccountState updates - these are extremely noisy
        if 'Portfolio' in record.name and 'Updated AccountState' in record.getMessage():
            return False
        # Block other noisy update messages
        if any(x in record.name for x in ['Cache', 'RiskEngine', 'DataEngine']):
            if 'Updated' in record.getMessage():
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
    
    # Add filter to console handler to block noisy messages
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
            handler.addFilter(PortfolioFilter())
    
    # Add timestamped console log file (unique per run)
    console_log_file = log_dir / f"console_{start_time}.log"
    console_handler = logging.FileHandler(console_log_file, mode='w')
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    
    # Add to root logger to capture ALL output
    root_logger = logging.getLogger()
    root_logger.addHandler(console_handler)
    
    # Suppress noisy loggers that clutter console output
    # These still log to files but not to console
    logging.getLogger("nautilus_trader.portfolio").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.cache").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.common").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.execution").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.risk").setLevel(logging.WARNING)
    
    # Suppress trader-specific loggers (these use trader_id prefix)
    logging.getLogger("TRADER-V2-001.Portfolio").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-001.Cache").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-001.RiskEngine").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-001.ExecEngine").setLevel(logging.WARNING)
    
    # Keep ib_insync at INFO for connection monitoring - we need to see disconnects/reconnects
    # logging.getLogger("ib_insync.wrapper").setLevel(logging.WARNING)
    # logging.getLogger("ib_insync.client").setLevel(logging.WARNING)
    
    log = logging.getLogger("live_v2")
    log.info("V2 Live logging configured. Logs directory: %s", log_dir)
    log.info("Console log (this run): %s", console_log_file)
    log.info("Strategy log: %s", log_dir / "strategy.log")

    log_and_write_run_metadata(
        log,
        output_dir=log_dir,
        run_kind="live",
        run_id=start_time,
        entrypoint=__file__,
        extra={"logger": "live_v2", "log_dir": str(log_dir)},
    )
    return log


def _resolve_market_data_type(value: str) -> IBMarketDataTypeEnum:
    mapping = {
        "REALTIME": IBMarketDataTypeEnum.REALTIME,
        "DELAYED": IBMarketDataTypeEnum.DELAYED,
        "DELAYED_FROZEN": IBMarketDataTypeEnum.DELAYED_FROZEN,
    }
    return mapping.get(value.upper(), IBMarketDataTypeEnum.DELAYED_FROZEN)


def main() -> int:
    """Entry point for V2 live trading with three-position brackets."""
    
    # Load V2 configuration
    live_config = load_mtf_v2_config()
    
    # Setup logging with timestamp
    start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("logs/live_mtf")  # Use live_mtf directory
    setup_logging(log_dir, start_time)
    
    logger.info("=" * 80)
    logger.info("MTF V2 LIVE TRADING - Three-Position Bracket Strategy")
    logger.info("=" * 80)
    print_mtf_v2_config(live_config)
    
    # Get IBKR config
    ibkr = get_ibkr_config()
    
    logger.info(
        "IBKR connection: host=%s port=%s client_id=%s account=%s",
        live_config.ib_host,
        live_config.ib_port,
        live_config.ib_client_id,
        live_config.ib_account,
    )
    
    # Build NautilusTrader node (for execution only)
    instrument_provider_config = InteractiveBrokersInstrumentProviderConfig(
        load_ids=frozenset([live_config.instrument]),
        min_expiry_days=10,
        build_futures_chain=False,
        build_options_chain=False,
    )
    
    market_data_type = _resolve_market_data_type(live_config.ib_market_data_type)
    
    # Data client (needed for instrument loading)
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
        routing=RoutingConfig(default=True),
    )
    
    # Build V2 strategy config
    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf_v2:MLSignalStrategyV2",
        config_path="strategies.ml_strategy_mtf_v2:MLSignalStrategyV2Config",
        config={
            "order_id_tag": "V2",
            "instrument_id": live_config.instrument,
            "bar_type": live_config.bar_type,
            "model_path": str(Path(live_config.model_path).resolve()),
            # Position sizing
            "total_position_size": live_config.total_position_size,
            "pos1_fraction": live_config.pos1_fraction,
            "pos2_fraction": live_config.pos2_fraction,
            "pos3_fraction": live_config.pos3_fraction,
            # Stop loss / Take profit
            "sl_atr_mult": live_config.sl_atr_mult,
            "pos1_tp_atr_mult": live_config.pos1_tp_atr_mult,
            "pos2_tp_atr_mult": live_config.pos2_tp_atr_mult,
            "pos3_tp_atr_mult": live_config.pos3_tp_atr_mult,
            # Trailing stop for POS3
            "trailing_activation_atr_mult": live_config.trailing_activation_atr_mult,
            "trailing_distance_atr_mult": live_config.trailing_distance_atr_mult,
            # Session filters
            "trade_start_hour": live_config.trade_start_hour,
            "trade_end_hour": live_config.trade_end_hour,
            "entry_cooldown_bars": live_config.entry_cooldown_bars,
            "prediction_threshold": live_config.prediction_threshold,
            "min_atr": live_config.min_atr,
            "max_atr": live_config.max_atr,
            # Weekday-specific excluded hours
            "excluded_hours_mode": live_config.excluded_hours_mode,
            "config_timezone": live_config.config_timezone,  # 'EST' or 'UTC'
            "excluded_hours_monday": ",".join(map(str, live_config.excluded_hours_monday)),
            "excluded_hours_tuesday": ",".join(map(str, live_config.excluded_hours_tuesday)),
            "excluded_hours_wednesday": ",".join(map(str, live_config.excluded_hours_wednesday)),
            "excluded_hours_thursday": ",".join(map(str, live_config.excluded_hours_thursday)),
            "excluded_hours_friday": ",".join(map(str, live_config.excluded_hours_friday)),
            "excluded_hours_saturday": ",".join(map(str, live_config.excluded_hours_saturday)),
            "excluded_hours_sunday": ",".join(map(str, live_config.excluded_hours_sunday)),
            # Risk
            "max_positions": live_config.max_positions,
            # Stall detection
            "stall_detection_enabled": live_config.stall_detection_enabled,
            "stall_check_bars": live_config.stall_check_bars,
            "stall_min_profit_atr": live_config.stall_min_profit_atr,
            "stall_sl_atr": live_config.stall_sl_atr,
            # Meta-Filters
            "meta_filter_mama_enabled": live_config.meta_filter_mama_enabled,
            "meta_filter_mama_min_diff": live_config.meta_filter_mama_min_diff,
            "meta_filter_dmi_enabled": live_config.meta_filter_dmi_enabled,
            "meta_filter_dmi_min_dmp": live_config.meta_filter_dmi_min_dmp,
        },
    )

    log_dir = Path("logs/trader_logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    node_config = TradingNodeConfig(
        trader_id="TRADER-V2-001",
        logging=LoggingConfig(
            log_level="INFO",
            log_level_file="DEBUG",
            log_directory=str(log_dir.resolve()),
            log_component_levels={
                "Portfolio": "WARNING",  # Suppress noisy AccountState updates
                "Cache": "WARNING",
                "RiskEngine": "WARNING",
                "DataEngine": "WARNING",
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
    
    # Apply filter to ALL console handlers after node is built
    portfolio_filter = PortfolioFilter()
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.addFilter(portfolio_filter)
            logger.info(f"Added PortfolioFilter to handler: {handler}")
    
    # Also try setting logger levels (belt and suspenders approach)
    logging.getLogger("TRADER-V2-001.Portfolio").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-001.Cache").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-001.RiskEngine").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-001.ExecEngine").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-001.DataEngine").setLevel(logging.WARNING)
    
    # Create strategy instance
    strategy_instance = StrategyFactory.create(strategy_config)
    node.trader.add_strategy(strategy_instance)
    
    logger.info("=" * 80)
    logger.info("V2 STRATEGY - THREE-POSITION BRACKETS")
    logger.info("=" * 80)
    logger.info(f"Instrument: {live_config.instrument}")
    logger.info(f"Bar Type: {live_config.bar_type}")
    logger.info(f"Position Sizes: POS1={live_config.total_position_size * live_config.pos1_fraction:.0f}, "
                f"POS2={live_config.total_position_size * live_config.pos2_fraction:.0f}, "
                f"POS3={live_config.total_position_size * live_config.pos3_fraction:.0f}")
    logger.info(f"TP Targets: POS1={live_config.pos1_tp_atr_mult}x, POS2={live_config.pos2_tp_atr_mult}x, POS3={live_config.pos3_tp_atr_mult}x ATR")
    logger.info(f"SL: {live_config.sl_atr_mult}x ATR")
    logger.info("Bar data: ib_insync (keepUpToDate=True)")
    logger.info("Execution: NautilusTrader IBKR adapter")
    logger.info("=" * 80)
    
    # Create ib_insync bar streamer with different client ID
    bar_streamer = IBBarStreamer(
        host=live_config.ib_host,
        port=live_config.ib_port,
        client_id=live_config.ib_client_id + 2,
    )
    
    # Connect bar streamer
    logger.info("Connecting ib_insync bar streamer...")
    if not bar_streamer.connect():
        logger.error("Failed to connect bar streamer")
        return 1
    
    # Parse bar size from bar_type (e.g., "EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL")
    bar_spec = live_config.bar_type.split('-', 1)[1]  # "15-MINUTE-MID-EXTERNAL"
    parts = bar_spec.split('-')
    step = int(parts[0])
    unit = parts[1].upper()
    
    if unit == "MINUTE":
        bar_size = f"{step} mins" if step > 1 else "1 min"
    elif unit == "HOUR":
        bar_size = f"{step} hour" if step == 1 else f"{step} hours"
    else:
        bar_size = f"{step} mins"
    
    # Determine what_to_show from bar_type
    price_type = parts[2].upper() if len(parts) > 2 else "MID"
    if price_type == "MID":
        what_to_show = "MIDPOINT"
    elif price_type == "BID":
        what_to_show = "BID"
    elif price_type == "ASK":
        what_to_show = "ASK"
    else:
        what_to_show = "TRADES"
    
    # Subscribe to bars via ib_insync FIRST (before NautilusTrader starts its event loop)
    symbol = live_config.symbol
    logger.info(f"Subscribing to {symbol} {bar_size} bars via ib_insync...")
    
    success = bar_streamer.subscribe_bars_sync(
        symbol=symbol,
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
    
    logger.info("Bar subscription active - historical bars delivered for warmup")
    logger.info("Starting NautilusTrader node...")
    
    # Run both ib_insync and NautilusTrader together
    return_code = 0
    import threading
    import time
    
    try:
        # Start NautilusTrader node in a separate thread
        node_thread = threading.Thread(target=node.run, daemon=True)
        node_thread.start()
        logger.info("NautilusTrader node started in background thread")
        
        # Wait for instrument to load (strategy will buffer bars during this time)
        logger.info("Waiting for instrument to load into cache...")
        for i in range(15):  # Wait up to 15 seconds
            time.sleep(1)
            instrument = strategy_instance.cache.instrument(strategy_instance.instrument_id)
            if instrument:
                logger.info(f"Instrument loaded after {i+1}s: {instrument.id}")
                break
        else:
            logger.warning("Instrument still not loaded after 15s - strategy will wait for it")
        
        # Run main loop - ib_insync processes events via background thread
        logger.info("V2 Live trading active. Press Ctrl+C to stop.")
        
        # Enable auto-reconnect for bar streamer
        bar_streamer._running = True
        
        # Keep main thread alive - ib_insync handles events in background
        # Health check runs every 60 seconds to detect stale connections
        health_check_interval = 60  # seconds
        status_report_interval = 1800  # 30 minutes
        last_health_check = time.time()
        last_status_report = time.time()
        
        logger.info(f"Health check enabled: every {health_check_interval}s, max bar age 20 mins")
        logger.info(f"Status report: every {status_report_interval//60} minutes")
        
        while True:
            time.sleep(1)  # Check every second
            
            # Check if reconnection is needed (execute in main thread!)
            if bar_streamer.needs_reconnect():
                logger.info("Executing reconnection from main thread...")
                bar_streamer._reconnect()
                continue
            
            # Skip other checks if currently reconnecting
            if bar_streamer.is_reconnecting():
                continue
            
            now = time.time()
            
            # Periodic status report (every 30 minutes)
            if now - last_status_report >= status_report_interval:
                last_status_report = now
                try:
                    # Get portfolio state from node
                    portfolio = node.trader.portfolio
                    account = portfolio.account(node.trader.account_ids[0]) if node.trader.account_ids else None
                    
                    if account:
                        logger.info("=" * 60)
                        logger.info("STATUS REPORT")
                        logger.info(f"Account Balance: {account.balance_total()}")
                        logger.info(f"Unrealized PnL: {account.unrealized_pnl()}")
                        logger.info(f"Open Positions: {len(portfolio.positions_open())}")
                        
                        # Bar streaming status
                        bar_age = bar_streamer.get_last_bar_age_seconds()
                        if bar_age is not None:
                            logger.info(f"Last bar received: {bar_age:.0f}s ago")
                        logger.info(f"IB Connected: {bar_streamer.is_connected()}")
                        logger.info("=" * 60)
                except Exception as e:
                    logger.warning(f"Could not generate status report: {e}")
            
            # Periodic health check (ib_insync handles event processing internally)
            if now - last_health_check >= health_check_interval:
                last_health_check = now
                
                # Check connection health and trigger reconnect if needed
                healthy = bar_streamer.check_health(max_bar_age_minutes=20)
                
                if not healthy:
                    logger.warning("Health check failed - reconnection scheduled")
                else:
                    # Log bar age for monitoring
                    bar_age = bar_streamer.get_last_bar_age_seconds()
                    if bar_age is not None:
                        logger.debug(f"Health OK - last bar {bar_age:.0f}s ago")
            
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt received")
    except Exception as exc:
        logger.exception("V2 Live trading error: %s", exc)
        return_code = 1
    finally:
        logger.info("Shutting down V2...")
        bar_streamer.disconnect()
        
        try:
            node.dispose()
        except Exception as e:
            logger.warning(f"Error disposing node: {e}")
        
        logger.info("V2 Live trading system stopped.")
    
    return return_code


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        exit_code = 0
    sys.exit(exit_code)
