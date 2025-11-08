"""Live trading runner for the Moving Average Crossover strategy."""
from __future__ import annotations

import asyncio
import logging
import logging.config
import signal
import sys
from pathlib import Path
from typing import Tuple

import yaml

from nautilus_trader.adapters.interactive_brokers.common import IB, IB_VENUE
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
from nautilus_trader.adapters.interactive_brokers.data import InteractiveBrokersDataClient
from nautilus_trader.config import (
    ImportableStrategyConfig,
    LiveDataEngineConfig,
    LoggingConfig,
    RoutingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode

from config.ibkr_config import get_ibkr_config
from config.live_config import LiveConfig, get_live_config, validate_live_config
<<<<<<< HEAD
from live.performance_monitor import create_performance_monitor, PerformanceMonitor
from live.historical_backfill import (
    backfill_historical_data,
    feed_historical_bars_to_strategy,
    calculate_required_duration_days,
)
from nautilus_trader.model.identifiers import InstrumentId, ClientId
from nautilus_trader.model.data import BarType
=======
>>>>>>> parent of b3beacaa4 (final, live mode works)


def setup_logging(log_dir: Path) -> logging.Logger:
    """Configure logging for live trading."""
    config_path = Path("config/logging.live.yaml")
    with config_path.open("r", encoding="utf-8") as stream:
        logging_config = yaml.safe_load(stream)

    log_dir.mkdir(parents=True, exist_ok=True)

    # Redirect all file handlers to live log directory
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
    logger = logging.getLogger("live")
    logger.info("Live logging configured. Logs directory: %s", log_dir)
    logger.info("Log files initialized: %s", ", ".join(handler_mappings.values()))
    return logger


def _resolve_market_data_type(value: str) -> IBMarketDataTypeEnum:
    mapping = {
        "REALTIME": IBMarketDataTypeEnum.REALTIME,
        "DELAYED": IBMarketDataTypeEnum.DELAYED,
        "DELAYED_FROZEN": IBMarketDataTypeEnum.DELAYED_FROZEN,
    }
    if not value:
        return IBMarketDataTypeEnum.DELAYED_FROZEN
    return mapping.get(value.upper(), IBMarketDataTypeEnum.DELAYED_FROZEN)


async def validate_ibkr_connection(ibkr_config) -> bool:
    """Log IBKR connection details prior to node startup."""
    logger = logging.getLogger("live")
    logger.info(
        "Validating IBKR connection parameters host=%s port=%s client_id=%s",
        ibkr_config.host,
        ibkr_config.port,
        ibkr_config.client_id,
    )
    logger.warning(
        "Ensure IBKR TWS/Gateway is running with API enabled before starting live trading."
    )
    return True


def create_trading_node_config(
    live_config: LiveConfig,
    ibkr_config,
) -> Tuple[TradingNodeConfig, ImportableStrategyConfig]:
    """Create trading node configuration for live trading."""
    instrument_id = f"{live_config.symbol}.{live_config.venue}"
    market_data_type = _resolve_market_data_type(ibkr_config.market_data_type)
    instrument_provider_config = InteractiveBrokersInstrumentProviderConfig(
        symbology_method=SymbologyMethod.IB,
        load_ids=frozenset({instrument_id}),
    )

    data_client_config = InteractiveBrokersDataClientConfig(
        instrument_provider=instrument_provider_config,
        ibg_host=ibkr_config.host,
        ibg_port=ibkr_config.port,
        ibg_client_id=ibkr_config.client_id,
        market_data_type=market_data_type,
        use_regular_trading_hours=True,
    )

    exec_client_config = InteractiveBrokersExecClientConfig(
        instrument_provider=instrument_provider_config,
        ibg_host=ibkr_config.host,
        ibg_port=ibkr_config.port,
        ibg_client_id=ibkr_config.client_id + 1,
        account_id=ibkr_config.account_id,
        routing=RoutingConfig(default=True),
    )

    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.moving_average_crossover:MovingAverageCrossover",
        config_path="strategies.moving_average_crossover:MovingAverageCrossoverConfig",
        config={
            "instrument_id": instrument_id,
            "bar_spec": live_config.bar_spec,
            "fast_period": live_config.fast_period,
            "slow_period": live_config.slow_period,
            "trade_size": str(live_config.trade_size),
            "enforce_position_limit": live_config.enforce_position_limit,
            "allow_position_reversal": live_config.allow_position_reversal,
<<<<<<< HEAD
            "stop_loss_pips": live_config.stop_loss_pips,
            "take_profit_pips": live_config.take_profit_pips,
            "trailing_stop_activation_pips": live_config.trailing_stop_activation_pips,
            "trailing_stop_distance_pips": live_config.trailing_stop_distance_pips,
            "crossover_threshold_pips": live_config.crossover_threshold_pips,
            "dmi_enabled": live_config.dmi_enabled,
            "dmi_period": live_config.dmi_period,
            "dmi_bar_spec": live_config.dmi_bar_spec,
            "dmi_minimum_difference": live_config.dmi_minimum_difference,
            "stoch_enabled": live_config.stoch_enabled,
            "stoch_period_k": live_config.stoch_period_k,
            "stoch_period_d": live_config.stoch_period_d,
            "stoch_bullish_threshold": live_config.stoch_bullish_threshold,
            "stoch_bearish_threshold": live_config.stoch_bearish_threshold,
            "stoch_bar_spec": live_config.stoch_bar_spec,
            "stoch_max_bars_since_crossing": live_config.stoch_max_bars_since_crossing,
            "time_filter_enabled": live_config.time_filter_enabled,
            "trading_hours_start": live_config.trading_hours_start,
            "trading_hours_end": live_config.trading_hours_end,
            "trading_hours_timezone": live_config.trading_hours_timezone,
                "excluded_hours": live_config.excluded_hours,
            "trend_filter_enabled": live_config.trend_filter_enabled,
            "trend_bar_spec": live_config.trend_bar_spec,
            "trend_fast_period": live_config.trend_fast_period,
            "trend_slow_period": live_config.trend_slow_period,
            "entry_timing_enabled": live_config.entry_timing_enabled,
            "entry_timing_bar_spec": live_config.entry_timing_bar_spec,
            "entry_timing_method": live_config.entry_timing_method,
            "entry_timing_timeout_bars": live_config.entry_timing_timeout_bars,
            "dormant_mode_enabled": live_config.dormant_mode_enabled,
            "dormant_threshold_hours": live_config.dormant_threshold_hours,
            "dormant_bar_spec": live_config.dormant_bar_spec,
            "dormant_fast_period": live_config.dormant_fast_period,
            "dormant_slow_period": live_config.dormant_slow_period,
            "dormant_stop_loss_pips": live_config.dormant_stop_loss_pips,
            "dormant_take_profit_pips": live_config.dormant_take_profit_pips,
            "dormant_trailing_activation_pips": live_config.dormant_trailing_activation_pips,
            "dormant_trailing_distance_pips": live_config.dormant_trailing_distance_pips,
            "dormant_dmi_enabled": live_config.dormant_dmi_enabled,
            "dormant_stoch_enabled": live_config.dormant_stoch_enabled,
=======
>>>>>>> parent of b3beacaa4 (final, live mode works)
        },
    )

    trading_node_config = TradingNodeConfig(
        trader_id=live_config.trader_id,
        logging=LoggingConfig(log_level="INFO"),
        data_clients={IB: data_client_config},
        exec_clients={IB: exec_client_config},
        data_engine=LiveDataEngineConfig(
            time_bars_timestamp_on_close=False,
            validate_data_sequence=True,
        ),
        timeout_connection=90.0,
        timeout_reconciliation=5.0,
        timeout_portfolio=5.0,
        timeout_disconnection=5.0,
        timeout_post_stop=2.0,
    )

    return trading_node_config, strategy_config


def setup_signal_handlers(node: TradingNode) -> None:
    """Register signal handlers for graceful shutdown."""
    logger = logging.getLogger("live")

    def handler(signum, frame):  # pragma: no cover - runtime behaviour
        logger.warning("Signal %s received. Initiating shutdown...", signum)
        node.shutdown_system(reason=f"Signal {signum} received")

    signal.signal(signal.SIGINT, handler)
    logger.info("SIGINT handler registered for graceful shutdown.")
    try:
        signal.signal(signal.SIGTERM, handler)
        logger.info("SIGTERM handler registered for graceful shutdown.")
    except AttributeError:  # Windows may not support SIGTERM
        logger.info("SIGTERM not supported on this platform; skipping handler registration.")


async def main() -> int:
    """Entry point for live trading."""
    try:
        live_config = get_live_config()
    except ValueError as exc:
        print(f"Live configuration error: {exc}", file=sys.stderr)
        return 1

    logger = setup_logging(Path(live_config.log_dir))
    logger.info("Starting live trading system...")

    ibkr_config = get_ibkr_config()

    if not validate_live_config(live_config):
        logger.error("Live configuration validation failed. Aborting startup.")
        return 1

    logger.info(
        "Live configuration loaded: symbol=%s venue=%s bar_spec=%s fast=%s slow=%s trade_size=%s",
        live_config.symbol,
        live_config.venue,
        live_config.bar_spec,
        live_config.fast_period,
        live_config.slow_period,
        live_config.trade_size,
    )
    logger.info(
        "IBKR connection details: host=%s port=%s client_id=%s account=%s market_data_type=%s",
        ibkr_config.host,
        ibkr_config.port,
        ibkr_config.client_id,
        ibkr_config.account_id or "<not set>",
        ibkr_config.market_data_type,
    )
    logger.info(
        "Resolved IBKR market data type enum: %s",
        _resolve_market_data_type(ibkr_config.market_data_type).name,
    )

    await validate_ibkr_connection(ibkr_config)

    trading_node_config, strategy_config = create_trading_node_config(live_config, ibkr_config)
    node = TradingNode(config=trading_node_config)

    node.add_data_client_factory(IB, InteractiveBrokersLiveDataClientFactory)
    node.add_exec_client_factory(IB, InteractiveBrokersLiveExecClientFactory)

    node.build()
    node.portfolio.set_specific_venue(IB_VENUE)
    node.trader.add_strategy(strategy_config)
    setup_signal_handlers(node)

<<<<<<< HEAD
    # Optional auto-stop after N seconds (for safe, time-bounded connectivity tests)
    try:
        auto_stop_val = os.getenv("AUTO_STOP_AFTER_SECONDS", "0").strip()
        auto_stop_seconds = int(float(auto_stop_val)) if auto_stop_val else 0
    except Exception:
        auto_stop_seconds = 0
    if auto_stop_seconds > 0:
        logger.info("Auto-stop enabled: stopping node after %s seconds", auto_stop_seconds)

        async def _auto_stop():
            await asyncio.sleep(auto_stop_seconds)
            logger.info("Auto-stop timeout reached; stopping node...")
            # Only stop here; disposal is handled in main() finally block
            node.stop()

        asyncio.create_task(_auto_stop())

    logger.info("Waiting for IBKR clients to connect (up to 30 seconds)...")
    # Give clients time to establish connection before starting main loop
    await asyncio.sleep(30)
    
    # Check if data client is connected and get it
    try:
        # Access clients from data engine's internal dictionary
        # Find the InteractiveBrokersDataClient by type
        data_engine = node.kernel.data_engine
        data_client = None
        
        if hasattr(data_engine, '_clients'):
            # Search for InteractiveBrokersDataClient in registered clients
            for client_id, client in data_engine._clients.items():
                if isinstance(client, InteractiveBrokersDataClient):
                    data_client = client
                    logger.info(f"Found IB data client: {client_id}")
                    break
        
        if not data_client:
            logger.warning("InteractiveBrokers data client not found. Cannot perform historical backfill.")
            logger.debug(f"Available clients: {list(data_engine._clients.keys()) if hasattr(data_engine, '_clients') else 'N/A'}")
    except Exception as e:
        logger.warning(f"Could not access data client: {e}. Skipping historical backfill.", exc_info=True)
        data_client = None
    
    if data_client:
        # Perform historical data backfill if needed
        logger.info("Analyzing historical data requirements...")
        
        instrument_id = InstrumentId.from_str(f"{live_config.symbol}.{live_config.venue}")
        bar_spec = live_config.bar_spec
        if not bar_spec.upper().endswith("-EXTERNAL") and not bar_spec.upper().endswith("-INTERNAL"):
            bar_spec = f"{bar_spec}-EXTERNAL"
        bar_type = BarType.from_str(f"{instrument_id}-{bar_spec}")
        
        is_forex = "/" in live_config.symbol
        
        # Calculate required duration for logging
        duration_days = calculate_required_duration_days(live_config.slow_period, bar_spec)
        logger.info(
            f"Strategy warmup requires {live_config.slow_period} bars of {bar_spec} "
            f"(approximately {duration_days:.2f} days)"
        )
        
        # Perform backfill
        backfill_success, bars_loaded, historical_bars = await backfill_historical_data(
            data_client=data_client,
            instrument_id=instrument_id,
            bar_type=bar_type,
            slow_period=live_config.slow_period,
            bar_spec=bar_spec,
            is_forex=is_forex,
        )
        
        if backfill_success and bars_loaded > 0 and historical_bars:
            # Feed historical bars to strategy
            logger.info("Feeding historical bars to strategy for warmup...")
            await feed_historical_bars_to_strategy(
                strategy_instance=strategy_instance,
                bars=historical_bars,
                bar_type=bar_type,
            )
            logger.info("Historical data backfill completed successfully")
        elif backfill_success:
            logger.info("No historical data backfill needed - sufficient data already available")
        else:
            logger.warning(
                "Historical data backfill failed or incomplete. "
                "Strategy will warm up using live data only (may take significant time)."
            )

=======
>>>>>>> parent of b3beacaa4 (final, live mode works)
    logger.info("Live trading node built successfully. Starting...")

    try:
        await asyncio.to_thread(node.run)
        return_code = 0
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt received. Initiating shutdown...")
        node.shutdown_system(reason="KeyboardInterrupt")
        return_code = 0
    except Exception as exc:  # pragma: no cover
        logger.exception("Live trading encountered an error: %s", exc)
        return_code = 1
    finally:
        try:
            node.stop()
        finally:
            node.dispose()
        logger.info("Live trading system stopped.")

    return return_code


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        exit_code = 0
    sys.exit(exit_code)
