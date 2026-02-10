"""
Live MTF V2 Trading - Entry Confirmed Dynamic version with Confidence-Based TP/SL.

This live runner uses the MLSignalStrategyV2EntryConfirmedDynamic strategy with:
- DMI relative filtering
- Dynamic position sizing
- Confidence-based TP/SL multipliers
- Entry confirmation logic

Key points:
- Uses MLSignalStrategyV2EntryConfirmedDynamic.
- Subscribes to BOTH 15m bars (signals/features) and 1m bars (entry confirmation).
- Confidence-based SL/TP controlled by .env.mtf_v2 variables:
  MTF2_CONF_HIGH_THRESH, MTF2_CONF_MED_THRESH
  MTF2_SL_HIGH/TP1_HIGH/TP2_HIGH, MTF2_SL_MED/TP1_MED/TP2_MED, MTF2_SL_LOW/TP1_LOW/TP2_LOW

Execution remains via NautilusTrader IBKR adapter; bar streaming uses ib_insync (IBBarStreamer).
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
    LiveExecEngineConfig,
    LiveRiskEngineConfig,
    LoggingConfig,
    RoutingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode

from ib_bar_streamer import IBBarStreamer
from utils.run_metadata import log_and_write_run_metadata


def _setup_logging(start_time: str) -> logging.Logger:
    """Setup logging for live trading."""
    log_dir = Path("logs/trader_logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    console_log_file = log_dir / f"console_{start_time}.log"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "console": {
                    "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
                    "datefmt": "%H:%M:%S",
                },
                "file": {
                    "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "console",
                    "level": "INFO",
                },
                "file": {
                    "class": "logging.FileHandler",
                    "filename": str(console_log_file),
                    "formatter": "file",
                    "level": "DEBUG",
                },
            },
            "loggers": {
                "live_v2_entry_confirmed_dynamic": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                },
            },
        }
    )

    # Set specific log levels for noisy components
    logging.getLogger("TRADER-V2-EC-DYN-001.ExecEngine").setLevel(logging.INFO)

    log = logging.getLogger("live_v2_entry_confirmed_dynamic")
    log.info("V2 Entry Confirmed Dynamic live logging configured. Logs directory: %s", log_dir)
    log.info("Console log (this run): %s", console_log_file)

    log_and_write_run_metadata(
        log,
        output_dir=log_dir,
        run_kind="live",
        run_id=start_time,
        entrypoint=__file__,
        extra={"logger": "live_v2_entry_confirmed_dynamic", "log_dir": str(log_dir)},
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


@dataclass
class LiveConfig:
    """Live trading configuration loaded from environment."""

    # IBKR connection
    ib_host: str = "127.0.0.1"
    ib_port: int = 7497
    ib_client_id: int = 18
    ib_account: str = "DU1558484"
    ib_market_data_type: str = "REALTIME"

    # Instrument
    instrument: str = "EUR/USD.IDEALPRO"
    bar_type: str = "EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    model_path: str = "models/ml_model_mtf_backup.pkl"

    # Position sizing
    total_position_size: int = 25000
    pos1_fraction: float = 1.0
    pos2_fraction: float = 0.0
    pos3_fraction: float = 0.0

    # Default SL/TP (fallback values)
    sl_atr_mult: float = 1.4
    pos1_tp_atr_mult: float = 0.6
    pos2_tp_atr_mult: float = 1.5
    pos3_tp_atr_mult: float = 2.0
    trailing_distance_atr_mult: float = 0.4

    # Prediction settings
    prediction_threshold: float = 0.50
    prediction_threshold_long: float = 0.0
    prediction_threshold_short: float = 0.0

    # Session filtering
    trade_start_hour: int = 7
    trade_end_hour: int = 20
    entry_cooldown_bars: int = 0

    # Excluded hours (simplified)
    excluded_hours_mode: str = "disabled"
    config_timezone: str = "EST"
    excluded_hours_monday: list[int] = []
    excluded_hours_tuesday: list[int] = []
    excluded_hours_wednesday: list[int] = []
    excluded_hours_thursday: list[int] = []
    excluded_hours_friday: list[int] = []
    excluded_hours_saturday: list[int] = []
    excluded_hours_sunday: list[int] = []

    # Risk management
    min_atr: float = 0.00022
    max_atr: float = 0.004

    # Entry confirmation
    entry_confirmation_enabled: bool = True
    entry_confirmation_bars: int = 1
    entry_confirmation_threshold: float = 0.1
    entry_max_wait_bars: int = 5

    # Dynamic sizing
    dynamic_sizing_enabled: bool = True
    starting_equity_usd: float = 37000.0
    lot_size_units: int = 100000
    margin_per_100k_usd: float = 3200.0
    target_margin_usage: float = 0.5
    risk_per_trade_pct: float = 0.015
    min_lots: int = 1
    max_lots: int = 500

    @classmethod
    def from_env(cls) -> "LiveConfig":
        """Load configuration from environment variables."""
        return cls(
            # IBKR connection
            ib_host=os.getenv("MTF2_IBKR_HOST", "127.0.0.1"),
            ib_port=int(os.getenv("MTF2_IBKR_PORT", "7497")),
            ib_client_id=int(os.getenv("MTF2_IBKR_CLIENT_ID", "18")),
            ib_account=os.getenv("MTF2_IBKR_ACCOUNT", "DU1558484"),
            ib_market_data_type=os.getenv("MTF2_IBKR_MARKET_DATA_TYPE", "REALTIME"),
            # Instrument
            instrument=os.getenv("MTF2_INSTRUMENT", "EUR/USD.IDEALPRO"),
            bar_type=os.getenv("MTF2_BAR_TYPE", "EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL"),
            model_path=os.getenv("MTF2_MODEL_PATH", "models/ml_model_mtf_backup.pkl"),
            # Position sizing
            total_position_size=int(os.getenv("MTF2_TOTAL_POSITION_SIZE", "25000")),
            pos1_fraction=float(os.getenv("MTF2_POS1_FRACTION", "1.0")),
            pos2_fraction=float(os.getenv("MTF2_POS2_FRACTION", "0.0")),
            pos3_fraction=float(os.getenv("MTF2_POS3_FRACTION", "0.0")),
            # Default SL/TP
            sl_atr_mult=float(os.getenv("MTF2_SL_ATR_MULT", "1.4")),
            pos1_tp_atr_mult=float(os.getenv("MTF2_POS1_TP_ATR_MULT", "0.6")),
            pos2_tp_atr_mult=float(os.getenv("MTF2_POS2_TP_ATR_MULT", "1.5")),
            pos3_tp_atr_mult=float(os.getenv("MTF2_POS3_TP_ATR_MULT", "2.0")),
            trailing_distance_atr_mult=float(os.getenv("MTF2_TRAILING_ACTIVATION_ATR_MULT", "0.4")),
            # Prediction
            prediction_threshold=float(os.getenv("MTF2_PREDICTION_THRESHOLD", "0.50")),
            prediction_threshold_long=float(os.getenv("MTF2_PREDICTION_THRESHOLD_LONG", "0")),
            prediction_threshold_short=float(os.getenv("MTF2_PREDICTION_THRESHOLD_SHORT", "0")),
            # Session
            trade_start_hour=int(os.getenv("MTF2_TRADE_START_HOUR", "7")),
            trade_end_hour=int(os.getenv("MTF2_TRADE_END_HOUR", "20")),
            entry_cooldown_bars=int(os.getenv("MTF2_ENTRY_COOLDOWN_BARS", "0")),
            # Excluded hours
            excluded_hours_mode=os.getenv("MTF2_EXCLUDED_HOURS_MODE", "disabled"),
            config_timezone=os.getenv("MTF2_CONFIG_TIMEZONE", "EST"),
            # Risk management
            min_atr=float(os.getenv("MTF2_MIN_ATR", "0.00022")),
            max_atr=float(os.getenv("MTF2_MAX_ATR", "0.004")),
            # Entry confirmation
            entry_confirmation_enabled=_env_bool("MTF2_ENTRY_CONFIRM_ENABLED", True),
            entry_confirmation_bars=_env_int("MTF2_ENTRY_CONFIRM_BARS", 1),
            entry_confirmation_threshold=_env_float("MTF2_ENTRY_CONFIRM_THRESHOLD", 0.1),
            entry_max_wait_bars=_env_int("MTF2_ENTRY_MAX_WAIT_BARS", 5),
            # Dynamic sizing
            dynamic_sizing_enabled=_env_bool("MTF2_DYNAMIC_SIZING_ENABLED", True),
            starting_equity_usd=_env_float("MTF2_STARTING_EQUITY_USD", 37000.0),
            lot_size_units=_env_int("MTF2_LOT_SIZE_UNITS", 100000),
            margin_per_100k_usd=_env_float("MTF2_MARGIN_PER_100K_USD", 3200.0),
            target_margin_usage=_env_float("MTF2_TARGET_MARGIN_USAGE", 0.5),
            risk_per_trade_pct=_env_float("MTF2_RISK_PER_TRADE_PCT", 0.015),
            min_lots=_env_int("MTF2_MIN_LOTS", 1),
            max_lots=_env_int("MTF2_MAX_LOTS", 500),
        )


def main() -> int:
    """Main entry point for live trading."""
    start_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Setup logging
    logger = _setup_logging(start_time)

    # Load configuration
    live_config = LiveConfig.from_env()

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

    # Strategy config for dynamic strategy with confidence-based TP/SL
    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf_v2_entry_confirmed_dmi_relative_dynamic:MLSignalStrategyV2EntryConfirmedDynamic",
        config_path="strategies.ml_strategy_mtf_v2_entry_confirmed_dmi_relative_dynamic:MLSignalStrategyV2EntryConfirmedDynamicConfig",
        config={
            "instrument_id": live_config.instrument,
            "bar_type": live_config.bar_type,
            "model_path": str(Path(live_config.model_path).resolve()),
            # Position sizing
            "total_position_size": live_config.total_position_size,
            "pos1_fraction": live_config.pos1_fraction,
            "pos2_fraction": live_config.pos2_fraction,
            "pos3_fraction": live_config.pos3_fraction,
            # Default SL/TP (fallback)
            "sl_atr_mult": live_config.sl_atr_mult,
            "pos1_tp_atr_mult": live_config.pos1_tp_atr_mult,
            "pos2_tp_atr_mult": live_config.pos2_tp_atr_mult,
            "pos3_tp_atr_mult": live_config.pos3_tp_atr_mult,
            "trailing_distance_atr_mult": live_config.trailing_distance_atr_mult,
            # Prediction
            "prediction_threshold": live_config.prediction_threshold,
            "prediction_threshold_long": live_config.prediction_threshold_long,
            "prediction_threshold_short": live_config.prediction_threshold_short,
            # Session
            "trade_start_hour": live_config.trade_start_hour,
            "trade_end_hour": live_config.trade_end_hour,
            "entry_cooldown_bars": live_config.entry_cooldown_bars,
            # Excluded hours
            "excluded_hours_mode": live_config.excluded_hours_mode,
            "config_timezone": live_config.config_timezone,
            "excluded_hours_monday": live_config.excluded_hours_monday,
            "excluded_hours_tuesday": live_config.excluded_hours_tuesday,
            "excluded_hours_wednesday": live_config.excluded_hours_wednesday,
            "excluded_hours_thursday": live_config.excluded_hours_thursday,
            "excluded_hours_friday": live_config.excluded_hours_friday,
            "excluded_hours_saturday": live_config.excluded_hours_saturday,
            "excluded_hours_sunday": live_config.excluded_hours_sunday,
            # Risk management
            "min_atr": live_config.min_atr,
            "max_atr": live_config.max_atr,
            # Entry confirmation
            "entry_confirmation_enabled": live_config.entry_confirmation_enabled,
            "entry_confirmation_bars": live_config.entry_confirmation_bars,
            "entry_confirmation_threshold": live_config.entry_confirmation_threshold,
            "entry_max_wait_bars": live_config.entry_max_wait_bars,
            # Dynamic sizing
            "dynamic_sizing_enabled": live_config.dynamic_sizing_enabled,
            "starting_equity_usd": live_config.starting_equity_usd,
            "lot_size_units": live_config.lot_size_units,
            "margin_per_100k_usd": live_config.margin_per_100k_usd,
            "target_margin_usage": live_config.target_margin_usage,
            "risk_per_trade_pct": live_config.risk_per_trade_pct,
            "min_lots": live_config.min_lots,
            "max_lots": live_config.max_lots,
        },
    )

    log_dir = Path("logs/trader_logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    node_config = TradingNodeConfig(
        trader_id="TRADER-V2-EC-DYN-001",
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

    # Import and create strategy
    from strategies.ml_strategy_mtf_v2_entry_confirmed_dmi_relative_dynamic import MLSignalStrategyV2EntryConfirmedDynamic
    strategy_instance = MLSignalStrategyV2EntryConfirmedDynamic(strategy_config.config)
    node.trader.add_strategy(strategy_instance)

    logger.info("=" * 80)
    logger.info("V2 ENTRY CONFIRMED DYNAMIC STRATEGY")
    logger.info("=" * 80)
    logger.info("Instrument: %s", live_config.instrument)
    logger.info("Bar Type (signal): %s", live_config.bar_type)
    logger.info("Bar data: ib_insync (keepUpToDate=True)")
    logger.info("Execution: NautilusTrader IBKR adapter")
    logger.info("Confidence-based TP/SL: ENABLED")
    logger.info("Dynamic sizing: ENABLED")
    logger.info("Entry confirmation: %s", "ENABLED" if live_config.entry_confirmation_enabled else "DISABLED")
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

    # Parse bar size from bar_type (e.g., "EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL")
    bar_spec = live_config.bar_type.split("-", 1)[1]
    parts = bar_spec.split("-")
    step = int(parts[0])
    unit = parts[1].upper()

    if unit == "MINUTE":
        bar_size_15m = f"{step} mins" if step > 1 else "1 min"
        bar_size_1m = "1 min"
    else:
        logger.error("Unsupported bar unit: %s", unit)
        return 1

    # Subscribe to bars
    logger.info("Subscribing to %s bars for signals...", bar_size_15m)
    bar_streamer.subscribe_bars(
        contract=bar_streamer.create_fx_contract(live_config.instrument.split('.')[0]),
        bar_size=bar_size_15m,
        what_to_show="MIDPOINT",
        use_rth=False,
        callback=lambda bars, has_new_bar: node.trader.strategy.handle_bar_data(bars, has_new_bar, bar_size_15m)
    )

    if live_config.entry_confirmation_enabled:
        logger.info("Subscribing to %s bars for entry confirmation...", bar_size_1m)
        bar_streamer.subscribe_bars(
            contract=bar_streamer.create_fx_contract(live_config.instrument.split('.')[0]),
            bar_size=bar_size_1m,
            what_to_show="MIDPOINT",
            use_rth=False,
            callback=lambda bars, has_new_bar: node.trader.strategy.handle_bar_data(bars, has_new_bar, bar_size_1m)
        )

    # Start the node
    logger.info("Starting trading node...")
    try:
        node.start()
    except Exception as e:
        logger.error("Failed to start trading node: %s", e)
        return 1

    # Keep running
    logger.info("Live trading started. Press Ctrl+C to stop.")
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal...")
    finally:
        logger.info("Stopping trading node...")
        node.stop()
        logger.info("Disconnecting bar streamer...")
        bar_streamer.disconnect()
        logger.info("Shutdown complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())