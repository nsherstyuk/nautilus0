"""
Backtest configuration management.

Provides a typed configuration object and loader for backtest parameters
sourced from environment variables.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from ._utils import validate_timezone, _parse_excluded_hours


@dataclass
class BacktestConfig:
    symbol: str
    venue: str = "SMART"
    start_date: str = ""
    end_date: str = ""
    bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    fast_period: int = 10
    slow_period: int = 20
    trade_size: int = 100
    starting_capital: float = 100_000.0
    catalog_path: str = "data/historical"
    output_dir: str = "logs/backtest_results"
    enforce_position_limit: bool = True
    allow_position_reversal: bool = False
    stop_loss_pips: int = 25
    take_profit_pips: int = 50
    trailing_stop_activation_pips: int = 20
    trailing_stop_distance_pips: int = 15
    crossover_threshold_pips: float = 0.7
    pre_crossover_separation_pips: float = 0.0
    pre_crossover_lookback_bars: int = 1
    dmi_enabled: bool = True
    dmi_bar_spec: str = "2-MINUTE-MID-EXTERNAL"
    dmi_period: int = 14
    stoch_enabled: bool = True
    stoch_bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    stoch_period_k: int = 14
    stoch_period_d: int = 3
    stoch_bullish_threshold: int = 30
    stoch_bearish_threshold: int = 70
    stoch_max_bars_since_crossing: int = 9
    use_limit_orders: bool = False
    limit_order_timeout_bars: int = 5

    # Time filter parameters
    time_filter_enabled: bool = False
    trading_hours_start: int = 0
    trading_hours_end: int = 23
    trading_hours_timezone: str = "UTC"
    excluded_hours: list[int] = field(default_factory=list)  # List of hours (0-23) to exclude from trading


def _require(name: str, value: Optional[str]) -> str:
    if not value:
        raise ValueError(f"Environment variable {name} is required for backtesting")
    return value


def _get_env_with_fallback(primary: str, fallback: str) -> Optional[str]:
    """Get environment variable with fallback to alternative name."""
    value = os.getenv(primary)
    if value is None:
        value = os.getenv(fallback)
    return value


def _parse_int(name: str, value: Optional[str], default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got: {value}")


def _parse_float(name: str, value: Optional[str], default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{name} must be a float, got: {value}")


def _validate_date(name: str, value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{name} must be in YYYY-MM-DD format, got: {value}")


 


def get_backtest_config() -> BacktestConfig:
    """Load backtest configuration from environment variables.

    Required env vars: BACKTEST_SYMBOL, BACKTEST_START_DATE, BACKTEST_END_DATE
    Optional with defaults: BACKTEST_VENUE, BACKTEST_BAR_SPEC, BACKTEST_FAST_PERIOD,
    BACKTEST_SLOW_PERIOD, BACKTEST_TRADE_SIZE, BACKTEST_STARTING_CAPITAL,
    CATALOG_PATH, OUTPUT_DIR, ENFORCE_POSITION_LIMIT, ALLOW_POSITION_REVERSAL,
    BACKTEST_STOP_LOSS_PIPS, BACKTEST_TAKE_PROFIT_PIPS, BACKTEST_TRAILING_STOP_ACTIVATION_PIPS,
    BACKTEST_TRAILING_STOP_DISTANCE_PIPS, STRATEGY_CROSSOVER_THRESHOLD_PIPS,
    STRATEGY_DMI_ENABLED, STRATEGY_DMI_BAR_SPEC, STRATEGY_DMI_PERIOD,
    STRATEGY_STOCH_ENABLED, STRATEGY_STOCH_BAR_SPEC, STRATEGY_STOCH_PERIOD_K,
    STRATEGY_STOCH_PERIOD_D, STRATEGY_STOCH_BULLISH_THRESHOLD, STRATEGY_STOCH_BEARISH_THRESHOLD,
    BACKTEST_TIME_FILTER_ENABLED, BACKTEST_TRADING_HOURS_START, BACKTEST_TRADING_HOURS_END,
    BACKTEST_TRADING_HOURS_TIMEZONE, BACKTEST_EXCLUDED_HOURS
    """
    load_dotenv()

    symbol = _require("BACKTEST_SYMBOL", os.getenv("BACKTEST_SYMBOL"))
    start_date = _require("BACKTEST_START_DATE", os.getenv("BACKTEST_START_DATE"))
    end_date = _require("BACKTEST_END_DATE", os.getenv("BACKTEST_END_DATE"))

    _validate_date("BACKTEST_START_DATE", start_date)
    _validate_date("BACKTEST_END_DATE", end_date)

    venue = os.getenv("BACKTEST_VENUE", "SMART")
    bar_spec = os.getenv("BACKTEST_BAR_SPEC", "15-MINUTE-MID-EXTERNAL")

    fast_period = _parse_int("BACKTEST_FAST_PERIOD", os.getenv("BACKTEST_FAST_PERIOD"), 10)
    slow_period = _parse_int("BACKTEST_SLOW_PERIOD", os.getenv("BACKTEST_SLOW_PERIOD"), 20)
    trade_size = _parse_int("BACKTEST_TRADE_SIZE", os.getenv("BACKTEST_TRADE_SIZE"), 100)
    starting_capital = _parse_float(
        "BACKTEST_STARTING_CAPITAL",
        os.getenv("BACKTEST_STARTING_CAPITAL"),
        100_000.0,
    )

    if fast_period >= slow_period:
        raise ValueError("BACKTEST_FAST_PERIOD must be less than BACKTEST_SLOW_PERIOD")

    stop_loss_pips = _parse_int("BACKTEST_STOP_LOSS_PIPS", os.getenv("BACKTEST_STOP_LOSS_PIPS"), 25)
    take_profit_pips = _parse_int("BACKTEST_TAKE_PROFIT_PIPS", os.getenv("BACKTEST_TAKE_PROFIT_PIPS"), 50)
    trailing_stop_activation_pips = _parse_int("BACKTEST_TRAILING_STOP_ACTIVATION_PIPS", os.getenv("BACKTEST_TRAILING_STOP_ACTIVATION_PIPS"), 20)
    trailing_stop_distance_pips = _parse_int("BACKTEST_TRAILING_STOP_DISTANCE_PIPS", os.getenv("BACKTEST_TRAILING_STOP_DISTANCE_PIPS"), 15)
    crossover_threshold_pips = _parse_float(
        "STRATEGY_CROSSOVER_THRESHOLD_PIPS",
        os.getenv("STRATEGY_CROSSOVER_THRESHOLD_PIPS"),
        0.7,
    )
    pre_crossover_separation_pips = _parse_float(
        "STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS",
        _get_env_with_fallback("STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS", "BACKTEST_PRE_CROSSOVER_SEPARATION_PIPS"),
        0.0,
    )
    pre_crossover_lookback_bars = _parse_int(
        "STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS",
        _get_env_with_fallback("STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS", "BACKTEST_PRE_CROSSOVER_LOOKBACK_BARS"),
        1,
    )

    dmi_enabled = os.getenv("STRATEGY_DMI_ENABLED", "true").lower() in ("true", "1", "yes")
    dmi_bar_spec = os.getenv("STRATEGY_DMI_BAR_SPEC", "2-MINUTE-MID-EXTERNAL")
    dmi_period = _parse_int("STRATEGY_DMI_PERIOD", os.getenv("STRATEGY_DMI_PERIOD"), 14)
    
    stoch_enabled = os.getenv("STRATEGY_STOCH_ENABLED", "true").lower() in ("true", "1", "yes")
    stoch_bar_spec = os.getenv("STRATEGY_STOCH_BAR_SPEC", "15-MINUTE-MID-EXTERNAL")
    stoch_period_k = _parse_int("STRATEGY_STOCH_PERIOD_K", os.getenv("STRATEGY_STOCH_PERIOD_K"), 14)
    stoch_period_d = _parse_int("STRATEGY_STOCH_PERIOD_D", os.getenv("STRATEGY_STOCH_PERIOD_D"), 3)
    stoch_bullish_threshold = _parse_int("STRATEGY_STOCH_BULLISH_THRESHOLD", os.getenv("STRATEGY_STOCH_BULLISH_THRESHOLD"), 30)
    stoch_bearish_threshold = _parse_int("STRATEGY_STOCH_BEARISH_THRESHOLD", os.getenv("STRATEGY_STOCH_BEARISH_THRESHOLD"), 70)
    stoch_max_bars_since_crossing = _parse_int("STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING", os.getenv("STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING"), 9)
    
    use_limit_orders = os.getenv("USE_LIMIT_ORDERS", "false").lower() in ("true", "1", "yes")
    limit_order_timeout_bars = _parse_int("LIMIT_ORDER_TIMEOUT_BARS", os.getenv("LIMIT_ORDER_TIMEOUT_BARS"), 5)
    
    # Time filter parameters
    time_filter_enabled = os.getenv("BACKTEST_TIME_FILTER_ENABLED", "false").lower() in ("true", "1", "yes")
    trading_hours_start = _parse_int("BACKTEST_TRADING_HOURS_START", os.getenv("BACKTEST_TRADING_HOURS_START"), 0)
    trading_hours_end = _parse_int("BACKTEST_TRADING_HOURS_END", os.getenv("BACKTEST_TRADING_HOURS_END"), 23)
    trading_hours_timezone = os.getenv("BACKTEST_TRADING_HOURS_TIMEZONE", "UTC")
    excluded_hours = _parse_excluded_hours("BACKTEST_EXCLUDED_HOURS", os.getenv("BACKTEST_EXCLUDED_HOURS"))
    
    # Normalize DMI bar_spec for FX instruments (similar to primary bar_spec normalization)
    if dmi_enabled and "/" in symbol:
        original_dmi_bar_spec = dmi_bar_spec
        if "-LAST-EXTERNAL" in dmi_bar_spec:
            dmi_bar_spec = dmi_bar_spec.replace("-LAST-EXTERNAL", "-MID-EXTERNAL")
        elif "-LAST-INTERNAL" in dmi_bar_spec:
            dmi_bar_spec = dmi_bar_spec.replace("-LAST-INTERNAL", "-MID-INTERNAL")
        elif dmi_bar_spec.endswith("-LAST"):
            # Legacy format without aggregation source
            dmi_bar_spec = dmi_bar_spec[:-4] + "MID-EXTERNAL"
        elif "-MID" not in dmi_bar_spec and "-LAST" not in dmi_bar_spec:
            # Missing price side entirely (e.g., "2-MINUTE"), default to MID for FX
            if dmi_bar_spec.endswith("-EXTERNAL") or dmi_bar_spec.endswith("-INTERNAL"):
                suffix = "-EXTERNAL" if dmi_bar_spec.endswith("-EXTERNAL") else "-INTERNAL"
                dmi_bar_spec = dmi_bar_spec[: -len(suffix)] + "-MID" + suffix
            else:
                dmi_bar_spec = f"{dmi_bar_spec}-MID"

        # Ensure aggregation suffix present for FX DMI bars (e.g., 2-MINUTE-MID -> 2-MINUTE-MID-EXTERNAL)
        if not dmi_bar_spec.endswith("-EXTERNAL") and not dmi_bar_spec.endswith("-INTERNAL"):
            dmi_bar_spec = f"{dmi_bar_spec}-EXTERNAL"
            
        if dmi_bar_spec != original_dmi_bar_spec:
            logger = logging.getLogger(__name__)
            logger.info(
                "Normalized DMI bar_spec for %s: %s -> %s",
                symbol,
                original_dmi_bar_spec,
                dmi_bar_spec,
            )
    
    # Normalize Stochastic bar_spec for FX instruments (similar to DMI normalization)
    if stoch_enabled and "/" in symbol:
        original_stoch_bar_spec = stoch_bar_spec
        if "-LAST-EXTERNAL" in stoch_bar_spec:
            stoch_bar_spec = stoch_bar_spec.replace("-LAST-EXTERNAL", "-MID-EXTERNAL")
        elif "-LAST-INTERNAL" in stoch_bar_spec:
            stoch_bar_spec = stoch_bar_spec.replace("-LAST-INTERNAL", "-MID-INTERNAL")
        elif stoch_bar_spec.endswith("-LAST"):
            # Legacy format without aggregation source
            stoch_bar_spec = stoch_bar_spec[:-4] + "MID-EXTERNAL"
        elif "-MID" not in stoch_bar_spec and "-LAST" not in stoch_bar_spec:
            # Missing price side entirely (e.g., "15-MINUTE"), default to MID for FX
            if stoch_bar_spec.endswith("-EXTERNAL") or stoch_bar_spec.endswith("-INTERNAL"):
                suffix = "-EXTERNAL" if stoch_bar_spec.endswith("-EXTERNAL") else "-INTERNAL"
                stoch_bar_spec = stoch_bar_spec[: -len(suffix)] + "-MID" + suffix
            else:
                stoch_bar_spec = f"{stoch_bar_spec}-MID"

        # Ensure aggregation suffix present for FX Stochastic bars (e.g., 15-MINUTE-MID -> 15-MINUTE-MID-EXTERNAL)
        if not stoch_bar_spec.endswith("-EXTERNAL") and not stoch_bar_spec.endswith("-INTERNAL"):
            stoch_bar_spec = f"{stoch_bar_spec}-EXTERNAL"
            
        if stoch_bar_spec != original_stoch_bar_spec:
            logger = logging.getLogger(__name__)
            logger.info(
                "Normalized Stochastic bar_spec for %s: %s -> %s",
                symbol,
                original_stoch_bar_spec,
                stoch_bar_spec,
            )

    if take_profit_pips <= stop_loss_pips:
        raise ValueError("BACKTEST_TAKE_PROFIT_PIPS must be greater than BACKTEST_STOP_LOSS_PIPS")
    
    if trailing_stop_activation_pips <= trailing_stop_distance_pips:
        raise ValueError("BACKTEST_TRAILING_STOP_ACTIVATION_PIPS must be greater than BACKTEST_TRAILING_STOP_DISTANCE_PIPS")
    
    if trailing_stop_activation_pips > take_profit_pips:
        logger = logging.getLogger(__name__)
        logger.warning("Trailing stop activation (%d pips) is greater than take profit (%d pips). Trailing may not activate before TP hit.", 
                      trailing_stop_activation_pips, take_profit_pips)

    if crossover_threshold_pips < 0:
        raise ValueError("STRATEGY_CROSSOVER_THRESHOLD_PIPS must be >= 0")

    if pre_crossover_separation_pips < 0:
        raise ValueError("STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS must be >= 0")
    
    if pre_crossover_lookback_bars < 1:
        raise ValueError("STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS must be >= 1")
    
    if pre_crossover_lookback_bars > 50:
        logger = logging.getLogger(__name__)
        logger.warning(
            "STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS (%d) is very large and may impact performance and memory usage",
            pre_crossover_lookback_bars
        )

    if crossover_threshold_pips > stop_loss_pips:
        logger = logging.getLogger(__name__)
        logger.warning(
            "Crossover threshold (%s pips) is greater than stop loss (%s pips). "
            "This may result in very few or no signals being generated.",
            crossover_threshold_pips,
            stop_loss_pips
        )

    if dmi_period <= 0:
        raise ValueError("STRATEGY_DMI_PERIOD must be > 0")

    if dmi_enabled:
        # Validate bar spec format
        if not dmi_bar_spec.upper().endswith("-EXTERNAL") and not dmi_bar_spec.upper().endswith("-INTERNAL"):
            logger = logging.getLogger(__name__)
            logger.warning(
                "STRATEGY_DMI_BAR_SPEC '%s' missing aggregation suffix, will be normalized to '%s-EXTERNAL'",
                dmi_bar_spec,
                dmi_bar_spec
            )
    
    # Validate Stochastic parameters
    if stoch_period_k <= 0:
        raise ValueError("STRATEGY_STOCH_PERIOD_K must be > 0")
    
    if stoch_period_d <= 0:
        raise ValueError("STRATEGY_STOCH_PERIOD_D must be > 0")
    
    if not (0 <= stoch_bullish_threshold <= 100):
        raise ValueError("STRATEGY_STOCH_BULLISH_THRESHOLD must be between 0 and 100")
    
    if not (0 <= stoch_bearish_threshold <= 100):
        raise ValueError("STRATEGY_STOCH_BEARISH_THRESHOLD must be between 0 and 100")
    
    if stoch_bullish_threshold >= stoch_bearish_threshold:
        raise ValueError("STRATEGY_STOCH_BULLISH_THRESHOLD must be less than STRATEGY_STOCH_BEARISH_THRESHOLD")
    
    if stoch_enabled:
        # Warn about potentially restrictive thresholds
        if stoch_bullish_threshold > 50:
            logger = logging.getLogger(__name__)
            logger.warning(
                "STRATEGY_STOCH_BULLISH_THRESHOLD (%d) > 50 may reject many valid bullish signals",
                stoch_bullish_threshold
            )
        
        if stoch_bearish_threshold < 50:
            logger = logging.getLogger(__name__)
            logger.warning(
                "STRATEGY_STOCH_BEARISH_THRESHOLD (%d) < 50 may reject many valid bearish signals",
                stoch_bearish_threshold
            )

    # Time filter validation
    if time_filter_enabled:
        if not (0 <= trading_hours_start <= 23):
            raise ValueError("BACKTEST_TRADING_HOURS_START must be between 0 and 23")
        if not (0 <= trading_hours_end <= 23):
            raise ValueError("BACKTEST_TRADING_HOURS_END must be between 0 and 23")
        if trading_hours_start >= trading_hours_end:
            raise ValueError(
                "BACKTEST_TRADING_HOURS_START must be less than BACKTEST_TRADING_HOURS_END (overnight windows not supported)"
            )
        validate_timezone("BACKTEST_TRADING_HOURS_TIMEZONE", trading_hours_timezone)
        if trading_hours_start == 0 and trading_hours_end == 23:
            logger = logging.getLogger(__name__)
            logger.warning(
                "Time filter is enabled but covers entire day (00-23); filter has no effect."
            )
        if excluded_hours:
            logger = logging.getLogger(__name__)
            logger.info("Excluded hours configured: %s", excluded_hours)
            window_hours = set(range(trading_hours_start, trading_hours_end + 1))
            if window_hours.issubset(set(excluded_hours)):
                raise ValueError(
                    f"BACKTEST_EXCLUDED_HOURS excludes all hours in the trading window ({trading_hours_start}-{trading_hours_end}), no trades possible"
                )

    catalog_path = os.getenv("CATALOG_PATH", "data/historical")
    output_dir = _get_env_with_fallback("OUTPUT_DIR", "BACKTEST_OUTPUT_DIR") or "logs/backtest_results"
    enforce_position_limit = os.getenv("ENFORCE_POSITION_LIMIT", "true").lower() in ("true", "1", "yes")
    allow_position_reversal = os.getenv("ALLOW_POSITION_REVERSAL", "false").lower() in ("true", "1", "yes")

    # Normalize FX bar_spec for backtesting (Nautilus v1.220.0 format):
    # - Convert LAST->MID for forex pairs while preserving aggregation source.
    # - Ensure aggregation suffix present (default to -EXTERNAL for historical files).
    original_bar_spec = bar_spec
    if "/" in symbol:
        if "-LAST-EXTERNAL" in bar_spec:
            bar_spec = bar_spec.replace("-LAST-EXTERNAL", "-MID-EXTERNAL")
        elif "-LAST-INTERNAL" in bar_spec:
            bar_spec = bar_spec.replace("-LAST-INTERNAL", "-MID-INTERNAL")
        elif bar_spec.endswith("-LAST"):
            # Legacy format without aggregation source
            bar_spec = bar_spec[:-4] + "MID-EXTERNAL"
        elif "-MID" not in bar_spec and "-LAST" not in bar_spec:
            # Missing price side entirely (e.g., "1-MINUTE"), default to MID for FX
            if bar_spec.endswith("-EXTERNAL") or bar_spec.endswith("-INTERNAL"):
                suffix = "-EXTERNAL" if bar_spec.endswith("-EXTERNAL") else "-INTERNAL"
                bar_spec = bar_spec[: -len(suffix)] + "-MID" + suffix
            else:
                bar_spec = f"{bar_spec}-MID"

        # Ensure aggregation suffix present for FX bars (e.g., 1-MINUTE-MID -> 1-MINUTE-MID-EXTERNAL)
        if not bar_spec.endswith("-EXTERNAL") and not bar_spec.endswith("-INTERNAL"):
            bar_spec = f"{bar_spec}-EXTERNAL"

    logger = logging.getLogger(__name__)
    if bar_spec != original_bar_spec:
        logger.info(
            "Normalized bar_spec for %s: %s -> %s",
            symbol,
            original_bar_spec,
            bar_spec,
        )
    else:
        logger.debug("Bar_spec for %s already normalized: %s", symbol, bar_spec)

    return BacktestConfig(
        symbol=symbol,
        venue=venue,
        start_date=start_date,
        end_date=end_date,
        bar_spec=bar_spec,
        fast_period=fast_period,
        slow_period=slow_period,
        trade_size=trade_size,
        starting_capital=starting_capital,
        catalog_path=catalog_path,
        output_dir=output_dir,
        enforce_position_limit=enforce_position_limit,
        allow_position_reversal=allow_position_reversal,
        stop_loss_pips=stop_loss_pips,
        take_profit_pips=take_profit_pips,
        trailing_stop_activation_pips=trailing_stop_activation_pips,
        trailing_stop_distance_pips=trailing_stop_distance_pips,
        crossover_threshold_pips=crossover_threshold_pips,
        pre_crossover_separation_pips=pre_crossover_separation_pips,
        pre_crossover_lookback_bars=pre_crossover_lookback_bars,
        dmi_enabled=dmi_enabled,
        dmi_bar_spec=dmi_bar_spec,
        dmi_period=dmi_period,
        stoch_enabled=stoch_enabled,
        stoch_bar_spec=stoch_bar_spec,
        stoch_period_k=stoch_period_k,
        stoch_period_d=stoch_period_d,
        stoch_bullish_threshold=stoch_bullish_threshold,
        stoch_bearish_threshold=stoch_bearish_threshold,
        stoch_max_bars_since_crossing=stoch_max_bars_since_crossing,
        use_limit_orders=use_limit_orders,
        limit_order_timeout_bars=limit_order_timeout_bars,
        time_filter_enabled=time_filter_enabled,
        trading_hours_start=trading_hours_start,
        trading_hours_end=trading_hours_end,
        trading_hours_timezone=trading_hours_timezone,
        excluded_hours=excluded_hours,
    )


def validate_backtest_config(config: BacktestConfig) -> bool:
    """Validate backtest configuration and warn about potential issues."""
    ok = True

    # Date ordering
    sd = datetime.strptime(config.start_date, "%Y-%m-%d")
    ed = datetime.strptime(config.end_date, "%Y-%m-%d")
    if sd >= ed:
        ok = False

    # Periods
    if config.fast_period >= config.slow_period:
        ok = False

    # Catalog presence
    if not Path(config.catalog_path).exists():
        ok = False

    return ok
