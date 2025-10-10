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


def setup_logging(log_dir: Path) -> logging.Logger:
    """Configure logging for live trading."""
    config_path = Path("config/logging.yaml")
    with config_path.open("r", encoding="utf-8") as stream:
        logging_config = yaml.safe_load(stream)

    log_dir.mkdir(parents=True, exist_ok=True)

    # Redirect general file handler to live log directory
    if "file" in logging_config.get("handlers", {}):
        logging_config["handlers"]["file"]["filename"] = str(log_dir / "application.log")

    # Ensure live-specific handler writes inside provided directory
    if "live_file" in logging_config.get("handlers", {}):
        logging_config["handlers"]["live_file"]["filename"] = str(log_dir / "live_trading.log")

    logging.config.dictConfig(logging_config)
    logger = logging.getLogger("live")
    logger.info("Live logging configured. Logs directory: %s", log_dir)
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
