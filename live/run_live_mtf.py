"""Live trading runner for the MTF ML Strategy (Multi-Timeframe Machine Learning)."""
from __future__ import annotations

import asyncio
import logging
import logging.config
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple

import yaml

# Ensure project root is in sys.path BEFORE importing patches
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patches import apply_ib_connection_patch

# Apply NautilusTrader IB connection patch before importing adapter modules
apply_ib_connection_patch()

from nautilus_trader.trading.config import StrategyFactory
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
from nautilus_trader.config import (
    ImportableStrategyConfig,
    LiveDataEngineConfig,
    LoggingConfig,
    RoutingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode

from config.ibkr_config import get_ibkr_config
from config.mtf_config import load_mtf_config, validate_mtf_config, print_mtf_config
# Historical backfill - now runs AFTER node starts
from live.historical_backfill import backfill_historical_data, feed_historical_bars_to_strategy
from utils.run_metadata import log_and_write_run_metadata


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

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_and_write_run_metadata(
        logger,
        output_dir=log_dir,
        run_kind="live",
        run_id=run_id,
        entrypoint=__file__,
        extra={"logger": "live", "log_dir": str(log_dir)},
    )
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


def _resolve_symbology_method(value: str) -> SymbologyMethod:
    """Resolve string to IB symbology enum, defaulting to IB_SIMPLIFIED if invalid."""
    try:
        v = (value or "").strip().upper()
    except Exception:
        v = ""
    mapping = {
        "IB_SIMPLIFIED": SymbologyMethod.IB_SIMPLIFIED,
        "IB_RAW": SymbologyMethod.IB_RAW,
    }
    return mapping.get(v, SymbologyMethod.IB_SIMPLIFIED)


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
    live_config,  # MTFConfig from .env.mtf
    ibkr_config,
) -> Tuple[TradingNodeConfig, ImportableStrategyConfig]:
    """Create trading node configuration for MTF ML live trading."""
    instrument_id = f"{live_config.symbol}.{live_config.venue}"
    market_data_type = _resolve_market_data_type(ibkr_config.market_data_type)
    # Resolve symbology method from config, defaulting to IB_SIMPLIFIED if invalid
    symbology_method = _resolve_symbology_method(getattr(ibkr_config, "symbology_method", "IB_SIMPLIFIED"))
    instrument_provider_config = InteractiveBrokersInstrumentProviderConfig(
        symbology_method=symbology_method,
        load_ids=frozenset({instrument_id}),  # Pre-load the instrument so it's available in on_start()
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
        strategy_path="strategies.ml_strategy_mtf:MLSignalStrategy",
        config_path="strategies.ml_strategy_config:MLSignalStrategyConfig",
        config={
            "instrument_id": instrument_id,
            "bar_spec": live_config.bar_spec,
            "position_size": live_config.position_size,
            "model_path": live_config.model_path,
            "prediction_threshold": live_config.prediction_threshold,
            "enforce_position_limit": live_config.enforce_position_limit,
            "max_positions": live_config.max_positions,
            # Risk Management (ATR-based)
            "sl_atr_mult": live_config.sl_atr_mult,
            "tp_atr_mult": live_config.tp_atr_mult,
            # Trailing Stop
            "trailing_stop_enabled": live_config.trailing_stop_enabled,
            "trailing_activation_atr_mult": live_config.trailing_activation_atr_mult,
            "trailing_distance_atr_mult": live_config.trailing_distance_atr_mult,
            # Partial Close (OPTIMIZED)
            "partial_close_enabled": live_config.partial_close_enabled,
            "partial_close_fraction": live_config.partial_close_fraction,
            "partial_close_move_sl_to_be": live_config.partial_close_move_sl_to_be,
            # Multi-Layer Exit (OPTIMIZED)
            "multi_layer_enabled": live_config.multi_layer_enabled,
            "multi_layer_count": live_config.multi_layer_count,
            "multi_layer_sizes": live_config.multi_layer_sizes,
            "multi_layer_triggers": live_config.multi_layer_triggers,
            "multi_layer_move_sl_to_be": live_config.multi_layer_move_sl_to_be,
            # Trading Session
            "session_start": live_config.session_start,
            "session_end": live_config.session_end,
            "excluded_hours": live_config.excluded_hours if live_config.excluded_hours else [],
            "excluded_hours_by_weekday": live_config.excluded_hours_by_weekday if live_config.excluded_hours_by_weekday else {},
            # Debug mode
            "debug_mode": live_config.debug_mode,
            # Feature warmup
            "feature_warmup_bars": live_config.feature_warmup_bars,
            # Order ID tag
            "order_id_tag": live_config.order_id_tag,
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
        timeout_connection=120.0,  # Increased for instrument loading
        timeout_reconciliation=30.0,  # Increased for instrument initialization
        timeout_portfolio=30.0,  # Increased for account initialization
        timeout_disconnection=10.0,
        timeout_post_stop=5.0,
    )

    return trading_node_config, strategy_config


def setup_signal_handlers(node: TradingNode) -> None:
    """Register signal handlers for graceful shutdown."""
    logger = logging.getLogger("live")

    def handler(signum, frame):  # pragma: no cover - runtime behaviour
        logger.warning("Signal %s received. Initiating shutdown...", signum)
        if node.is_running():
            asyncio.create_task(node.stop_async())

    signal.signal(signal.SIGINT, handler)
    logger.info("SIGINT handler registered for graceful shutdown.")
    try:
        signal.signal(signal.SIGTERM, handler)
        logger.info("SIGTERM handler registered for graceful shutdown.")
    except AttributeError:  # Windows may not support SIGTERM
        logger.info("SIGTERM not supported on this platform; skipping handler registration.")


async def main() -> int:
    """Entry point for MTF ML live trading."""
    print("="*80)
    print("MTF ML STRATEGY - LIVE TRADING")
    print("="*80)
    
    # Load configuration from .env.mtf
    print("\nLoading configuration from .env.mtf...")
    live_config = load_mtf_config()
    print_mtf_config(live_config)
    
    if not validate_mtf_config(live_config):
        print("\n❌ Configuration validation failed!", file=sys.stderr)
        return 1

    logger = setup_logging(Path(live_config.log_dir))
    logger.info("Starting MTF ML live trading system...")

    ibkr_config = get_ibkr_config()

    logger.info(
        "MTF configuration loaded: symbol=%s venue=%s bar_spec=%s position_size=%s model=%s",
        live_config.symbol,
        live_config.venue,
        live_config.bar_spec,
        live_config.position_size,
        live_config.model_path,
    )
    logger.info(
        "IBKR connection details: host=%s port=%d client_id=%d account=%s market_data_type=%s",
        ibkr_config.host,
        ibkr_config.port,
        ibkr_config.client_id,
        ibkr_config.account_id or "<not set>",
        ibkr_config.market_data_type,
    )
    
    # Resolve and log market data type enum
    market_data_enum = _resolve_market_data_type(ibkr_config.market_data_type)
    logger.info(
        "Resolved IBKR market data type enum: %s (%s)",
        market_data_enum.name if hasattr(market_data_enum, 'name') else str(market_data_enum),
        market_data_enum.value if hasattr(market_data_enum, 'value') else market_data_enum,
    )

    # Log MTF features
    logger.info("ML Model: %s", live_config.model_path)
    logger.info("Prediction threshold: %.2f", live_config.prediction_threshold)
    logger.info("Partial close: enabled=%s (%.0f%% at %.1f×ATR)", 
                live_config.partial_close_enabled,
                live_config.partial_close_fraction * 100,
                live_config.partial_close_atr_mult)
    logger.info("Stop Loss: %.1f×ATR, Take Profit: %.1f×ATR", 
                live_config.sl_atr_mult, live_config.tp_atr_mult)

    await validate_ibkr_connection(ibkr_config)

    trading_node_config, strategy_config = create_trading_node_config(live_config, ibkr_config)
    node = TradingNode(config=trading_node_config)

    node.add_data_client_factory(IB, InteractiveBrokersLiveDataClientFactory)
    node.add_exec_client_factory(IB, InteractiveBrokersLiveExecClientFactory)

    node.build()
    try:
        node.cache.set_specific_venue(IB_VENUE)
    except Exception:
        # Fallback for older versions
        try:
            node.portfolio.set_specific_venue(IB_VENUE)
        except Exception:
            pass
    
    # Create concrete Strategy instance from ImportableStrategyConfig
    strategy_instance = StrategyFactory.create(strategy_config)
    node.trader.add_strategy(strategy_instance)
    setup_signal_handlers(node)

    logger.info("Waiting for IBKR clients to connect (up to 30 seconds)...")
    # Give clients time to establish connection before starting main loop
    await asyncio.sleep(30)

    # =========================================================================
    # HISTORICAL DATA BACKFILL - Matching Live_works_with_optimization branch
    # =========================================================================
    logger.info("=" * 80)
    logger.info("MTF STRATEGY - STARTING LIVE TRADING")
    logger.info("=" * 80)
    logger.info(f"Symbol: {live_config.symbol}")
    logger.info(f"Bar Spec: {live_config.bar_spec}")
    logger.info(f"Warmup: {live_config.feature_warmup_bars} bars")
    logger.info("=" * 80)
    
    logger.info("Starting historical data backfill for indicator warmup...")
    try:
        # Access IBKR data client through kernel's data engine
        from nautilus_trader.adapters.interactive_brokers.data import InteractiveBrokersDataClient
        from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
        from nautilus_trader.model.data import BarType, BarSpecification, BarAggregation
        from nautilus_trader.model.enums import PriceType
        
        ib_data_client = None
        data_engine = getattr(node.kernel, "data_engine", None)
        if data_engine and hasattr(data_engine, "_clients"):
            for client_id, client in data_engine._clients.items():
                if isinstance(client, InteractiveBrokersDataClient):
                    ib_data_client = client
                    logger.info(f"Found IBKR data client: {client_id}")
                    break
        
        if ib_data_client:
            instrument_id = InstrumentId(Symbol(live_config.symbol), Venue(live_config.venue))
            
            # Parse bar specification
            parts = live_config.bar_spec.split('-')
            if len(parts) >= 3:
                step = int(parts[0])
                aggregation = BarAggregation[parts[1].upper()]
                price_type = PriceType[parts[2].upper()]
                bar_spec = BarSpecification(step, aggregation, price_type)
                bar_type = BarType(instrument_id, bar_spec)
                
                logger.info(f"Requesting historical bars for {instrument_id}")
                success, bars_loaded, historical_bars = await backfill_historical_data(
                    data_client=ib_data_client,
                    instrument_id=instrument_id,
                    bar_type=bar_type,
                    slow_period=live_config.feature_warmup_bars,
                    bar_spec=live_config.bar_spec,
                    is_forex=live_config.venue == "IDEALPRO"
                )
                
                if success and historical_bars and len(historical_bars) > 0:
                    logger.info(f"Backfill successful: {bars_loaded} bars")
                    await feed_historical_bars_to_strategy(
                        strategy_instance=strategy_instance,
                        bars=historical_bars,
                        bar_type=bar_type,
                    )
                    logger.info("Historical bars fed to strategy")
                else:
                    logger.warning("Backfill unsuccessful - strategy will warm up naturally")
        else:
            logger.warning("Could not find IBKR data client")
    except Exception as exc:
        logger.error(f"Backfill error: {exc}")
        logger.info("Continuing without backfill")
    
    logger.info("Historical data backfill process completed")
    logger.info("Live trading node built successfully. Starting...")

    return_code = 0
    try:
        # Use node.run_async() - the standard NautilusTrader approach
        await node.run_async()
    except asyncio.CancelledError:
        logger.info("Live trading run cancelled; proceeding with shutdown.")
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt received. Initiating shutdown...")
        return_code = 0
    except Exception as exc:  # pragma: no cover
        logger.exception("Live trading encountered an error: %s", exc)
        return_code = 1
    finally:
        if node.is_running():
            logger.info("Stopping trading node...")
            try:
                await node.stop_async()
            except Exception as stop_exc:
                logger.warning("Error during node shutdown: %s", stop_exc)
        try:
            node.dispose()
        except Exception as dispose_exc:
            logger.warning("Error during node disposal: %s", dispose_exc)
        logger.info("Live trading system stopped.")

    return return_code


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        exit_code = 0
    sys.exit(exit_code)
