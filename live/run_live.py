"""Live trading runner for the Moving Average Crossover strategy."""
from __future__ import annotations

import asyncio
import os
import logging
import logging.config
import signal
import sys
from pathlib import Path
from typing import Tuple, Optional

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
from config.live_config import LiveConfig, get_live_config, validate_live_config
from live.performance_monitor import create_performance_monitor, PerformanceMonitor


def setup_logging(log_dir: Path) -> logging.Logger:
    """Configure logging for live trading."""
    config_path = Path("config/logging.live.yaml")
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


def create_trading_node_config(
    live_config: LiveConfig,
    ibkr_config,
) -> Tuple[TradingNodeConfig, ImportableStrategyConfig]:
    """Create trading node configuration for live trading."""
    instrument_id = f"{live_config.symbol}.{live_config.venue}"
    market_data_type = _resolve_market_data_type(ibkr_config.market_data_type)
    # Resolve symbology method from config, defaulting to IB_SIMPLIFIED if invalid
    symbology_method = _resolve_symbology_method(getattr(ibkr_config, "symbology_method", "IB_SIMPLIFIED"))
    instrument_provider_config = InteractiveBrokersInstrumentProviderConfig(
        symbology_method=symbology_method,
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
            "stop_loss_pips": live_config.stop_loss_pips,
            "take_profit_pips": live_config.take_profit_pips,
            "trailing_stop_activation_pips": live_config.trailing_stop_activation_pips,
            "trailing_stop_distance_pips": live_config.trailing_stop_distance_pips,
            "crossover_threshold_pips": live_config.crossover_threshold_pips,
            "dmi_enabled": live_config.dmi_enabled,
            "dmi_period": live_config.dmi_period,
            "dmi_bar_spec": live_config.dmi_bar_spec,
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
        timeout_portfolio=15.0,
        timeout_disconnection=5.0,
        timeout_post_stop=2.0,
    )

    return trading_node_config, strategy_config


def setup_signal_handlers(node: TradingNode) -> None:
    """Register signal handlers for graceful shutdown."""
    logger = logging.getLogger("live")

    def handler(signum, frame):  # pragma: no cover - runtime behaviour
        logger.warning("Signal %s received. Initiating shutdown...", signum)
        # Only stop here; disposal is handled in main() finally block
        node.stop()

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

    # Performance monitoring configuration
    enable_env = os.getenv("ENABLE_PERFORMANCE_MONITORING", "true").strip().lower()
    enable_performance_monitoring = enable_env in {"1", "true", "yes", "on"}
    try:
        monitor_interval = int(float(os.getenv("PERFORMANCE_MONITOR_INTERVAL", "60")))
    except Exception:
        monitor_interval = 60
    logger.info(
        "Performance monitoring: %s (interval=%ss)",
        "enabled" if enable_performance_monitoring else "disabled",
        monitor_interval,
    )

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
        "Phase 6 parameters: SL=%s TP=%s TrailAct=%s TrailDist=%s CrossThresh=%s DMI=%s Stoch=%s",
        live_config.stop_loss_pips,
        live_config.take_profit_pips,
        live_config.trailing_stop_activation_pips,
        live_config.trailing_stop_distance_pips,
        live_config.crossover_threshold_pips,
        f"enabled(period={live_config.dmi_period})" if live_config.dmi_enabled else "disabled",
        f"enabled(K={live_config.stoch_period_k},D={live_config.stoch_period_d})" if live_config.stoch_enabled else "disabled",
    )
    logger.info(
        "Time filter: %s (hours=%s-%s %s)",
        "enabled" if getattr(live_config, "time_filter_enabled", False) else "disabled",
        getattr(live_config, "trading_hours_start", None),
        getattr(live_config, "trading_hours_end", None),
        getattr(live_config, "trading_hours_timezone", None),
    )
    excluded_hours = getattr(live_config, "excluded_hours", [])
    if excluded_hours:
        logger.info(
            "Excluded hours: %s %s",
            excluded_hours,
            getattr(live_config, "trading_hours_timezone", None),
        )
    logger.info(
        "IBKR connection details: host=%s port=%s client_id=%s account=%s market_data_type=%s",
        ibkr_config.host,
        ibkr_config.port,
        ibkr_config.client_id,
        ibkr_config.account_id or "<not set>",
        ibkr_config.market_data_type,
    )
    resolved_market_data_type = _resolve_market_data_type(ibkr_config.market_data_type)
    name = getattr(resolved_market_data_type, "name", str(resolved_market_data_type))
    value = getattr(resolved_market_data_type, "value", str(resolved_market_data_type))
    logger.info(
        "Resolved IBKR market data type: name=%s value=%s",
        name,
        value,
    )

    trading_node_config, strategy_config = create_trading_node_config(live_config, ibkr_config)
    node = TradingNode(config=trading_node_config)

    node.add_data_client_factory(IB, InteractiveBrokersLiveDataClientFactory)
    node.add_exec_client_factory(IB, InteractiveBrokersLiveExecClientFactory)

    node.build()
    # Prefer cache mapping over deprecated portfolio mapping
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

    logger.info("Live trading node built successfully. Starting...")

    # Create performance monitor if enabled
    performance_monitor: Optional[PerformanceMonitor] = None
    if enable_performance_monitoring:
        try:
            metrics_path = Path(live_config.log_dir) / "performance_metrics.json"
            performance_monitor = create_performance_monitor(
                trading_node=node,
                live_config=live_config,
                metrics_file=metrics_path,
                poll_interval=float(monitor_interval),
            )
            # Log actual applied settings
            logger.info(
                "Performance monitor created. Monitoring interval: %.0f seconds",
                performance_monitor.poll_interval,
            )
            logger.info(
                "Performance monitor initialized. Metrics will be saved to: %s",
                metrics_path.as_posix(),
            )
        except Exception as exc:
            logger.warning(
                "Failed to create performance monitor: %s. Continuing without monitoring.",
                exc,
            )
            performance_monitor = None
    else:
        logger.info("Performance monitoring disabled.")

    # Ensure performance monitor queries the correct account venue (IB)
    os.environ.setdefault("ACCOUNT_VENUE", "INTERACTIVE_BROKERS")

    try:
        if performance_monitor is not None:
            # Run trading node and monitor concurrently, but await the node lifecycle
            monitor_task = asyncio.create_task(performance_monitor.monitor_loop(), name="performance_monitor.loop")
            node_task = asyncio.create_task(node.run_async(), name="node.run_async")

            await node_task  # wait for node to complete/stopped

            performance_monitor.stop()
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

            return_code = 0
        else:
            # Run without monitoring
            await node.run_async()
            return_code = 0
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt received. Initiating shutdown...")
        if performance_monitor is not None:
            performance_monitor.stop()
        try:
            node.stop()
        finally:
            node.dispose()
        return_code = 0
    except Exception as exc:  # pragma: no cover
        logger.warning("Performance monitor encountered error: %s", exc)
        logger.exception("Live trading encountered an error: %s", exc)
        return_code = 1
    finally:
        if performance_monitor is not None:
            performance_monitor.stop()
            logger.info("Performance monitor stopped.")
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
    except RuntimeError as exc:
        # Treat loop-stopped as a normal shutdown (can happen when node.stop() halts the loop)
        if "Event loop stopped before Future completed" in str(exc):
            exit_code = 0
        else:
            raise
    sys.exit(exit_code)
