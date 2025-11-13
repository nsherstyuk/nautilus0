"""Live trading runner for the Moving Average Crossover strategy with full backtest feature parity."""
from __future__ import annotations

import asyncio
import logging
import logging.config
import signal
import sys
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
from config.live_config import LiveConfig, get_live_config, validate_live_config


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
    live_config: LiveConfig,
    ibkr_config,
) -> Tuple[TradingNodeConfig, ImportableStrategyConfig]:
    """Create trading node configuration for live trading with full backtest feature parity."""
    instrument_id = f"{live_config.symbol}.{live_config.venue}"
    market_data_type = _resolve_market_data_type(ibkr_config.market_data_type)
    # Resolve symbology method from config, defaulting to IB_SIMPLIFIED if invalid
    symbology_method = _resolve_symbology_method(getattr(ibkr_config, "symbology_method", "IB_SIMPLIFIED"))
    instrument_provider_config = InteractiveBrokersInstrumentProviderConfig(
        symbology_method=symbology_method,
        # load_ids=frozenset({instrument_id}),  # Disable pre-loading to avoid instrument resolution issues
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
            # Risk management
            "stop_loss_pips": live_config.stop_loss_pips,
            "take_profit_pips": live_config.take_profit_pips,
            "trailing_stop_activation_pips": live_config.trailing_stop_activation_pips,
            "trailing_stop_distance_pips": live_config.trailing_stop_distance_pips,
            # Adaptive stops (NEW - full backtest parity)
            "adaptive_stop_mode": live_config.adaptive_stop_mode,
            "adaptive_atr_period": live_config.adaptive_atr_period,
            "tp_atr_mult": live_config.tp_atr_mult,
            "sl_atr_mult": live_config.sl_atr_mult,
            "trail_activation_atr_mult": live_config.trail_activation_atr_mult,
            "trail_distance_atr_mult": live_config.trail_distance_atr_mult,
            "volatility_window": live_config.volatility_window,
            "volatility_sensitivity": live_config.volatility_sensitivity,
            "min_stop_distance_pips": live_config.min_stop_distance_pips,
            # Market regime detection (NEW - full backtest parity)
            "regime_detection_enabled": live_config.regime_detection_enabled,
            "regime_adx_trending_threshold": live_config.regime_adx_trending_threshold,
            "regime_adx_ranging_threshold": live_config.regime_adx_ranging_threshold,
            "regime_tp_multiplier_trending": live_config.regime_tp_multiplier_trending,
            "regime_tp_multiplier_ranging": live_config.regime_tp_multiplier_ranging,
            "regime_sl_multiplier_trending": live_config.regime_sl_multiplier_trending,
            "regime_sl_multiplier_ranging": live_config.regime_sl_multiplier_ranging,
            "regime_trailing_activation_multiplier_trending": live_config.regime_trailing_activation_multiplier_trending,
            "regime_trailing_activation_multiplier_ranging": live_config.regime_trailing_activation_multiplier_ranging,
            "regime_trailing_distance_multiplier_trending": live_config.regime_trailing_distance_multiplier_trending,
            "regime_trailing_distance_multiplier_ranging": live_config.regime_trailing_distance_multiplier_ranging,
            # Signal filters
            "crossover_threshold_pips": live_config.crossover_threshold_pips,
            # DMI indicator
            "dmi_enabled": live_config.dmi_enabled,
            "dmi_period": live_config.dmi_period,
            "dmi_bar_spec": live_config.dmi_bar_spec,
            # Stochastic indicator
            "stoch_enabled": live_config.stoch_enabled,
            "stoch_period_k": live_config.stoch_period_k,
            "stoch_period_d": live_config.stoch_period_d,
            "stoch_bullish_threshold": live_config.stoch_bullish_threshold,
            "stoch_bearish_threshold": live_config.stoch_bearish_threshold,
            "stoch_bar_spec": live_config.stoch_bar_spec,
            "stoch_max_bars_since_crossing": live_config.stoch_max_bars_since_crossing,
            # Time filter with weekday-specific exclusions (NEW - full backtest parity)
            "time_filter_enabled": live_config.time_filter_enabled,
            "excluded_hours": live_config.excluded_hours,
            "excluded_hours_mode": live_config.excluded_hours_mode,
            "excluded_hours_by_weekday": live_config.excluded_hours_by_weekday,
            # Trend filter (aligned with backtest)
            "trend_filter_enabled": live_config.trend_filter_enabled,
            "trend_bar_spec": live_config.trend_bar_spec,
            "trend_ema_period": live_config.trend_ema_period,
            "trend_ema_threshold_pips": live_config.trend_ema_threshold_pips,
            # RSI filter (NEW - full backtest parity)
            "rsi_enabled": live_config.rsi_enabled,
            "rsi_period": live_config.rsi_period,
            "rsi_overbought": live_config.rsi_overbought,
            "rsi_oversold": live_config.rsi_oversold,
            "rsi_divergence_lookback": live_config.rsi_divergence_lookback,
            # Volume filter (NEW - full backtest parity)
            "volume_enabled": live_config.volume_enabled,
            "volume_avg_period": live_config.volume_avg_period,
            "volume_min_multiplier": live_config.volume_min_multiplier,
            # ATR filter (NEW - full backtest parity)
            "atr_enabled": live_config.atr_enabled,
            "atr_period": live_config.atr_period,
            "atr_min_strength": live_config.atr_min_strength,
            # Entry timing
            "entry_timing_enabled": live_config.entry_timing_enabled,
            "entry_timing_bar_spec": live_config.entry_timing_bar_spec,
            "entry_timing_method": live_config.entry_timing_method,
            "entry_timing_timeout_bars": live_config.entry_timing_timeout_bars,
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
    logger.info("Starting live trading system with full backtest feature parity...")

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

    # Log new features
    logger.info("Adaptive stops: mode=%s", live_config.adaptive_stop_mode)
    logger.info("Regime detection: enabled=%s", live_config.regime_detection_enabled)
    logger.info("Weekday exclusions: mode=%s", live_config.excluded_hours_mode)
    logger.info("RSI filter: enabled=%s", live_config.rsi_enabled)
    logger.info("Volume filter: enabled=%s", live_config.volume_enabled)
    logger.info("ATR filter: enabled=%s", live_config.atr_enabled)

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

    logger.info("Waiting for IBKR clients to connect (up to 60 seconds)...")
    # Give clients time to establish connection before starting main loop
    await asyncio.sleep(60)

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
