"""Live trading configuration management.

Provides a typed configuration object and loader for live trading parameters
sourced from environment variables.
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from ._utils import validate_timezone, _parse_excluded_hours


@dataclass
class LiveConfig:
    symbol: str
    venue: str = "SMART"
    bar_spec: str = "1-MINUTE-LAST"
    fast_period: int = 10
    slow_period: int = 20
    trade_size: int = 100
    enforce_position_limit: bool = True
    allow_position_reversal: bool = False
    log_dir: str = "logs/live"
    trader_id: str = "LIVE-TRADER-001"
    # Risk Management Parameters
    stop_loss_pips: int = 25
    take_profit_pips: int = 50
    trailing_stop_activation_pips: int = 20
    trailing_stop_distance_pips: int = 15
    # Signal Filter Parameters
    crossover_threshold_pips: float = 0.7
    # DMI Indicator Parameters
    dmi_enabled: bool = True
    dmi_period: int = 14
    dmi_bar_spec: str = "2-MINUTE-MID-EXTERNAL"
    dmi_minimum_difference: float = 0.0  # Minimum DI difference for valid trend (0.0 = disabled, backward compatible)
    # Stochastic Indicator Parameters
    stoch_enabled: bool = True
    stoch_period_k: int = 14
    stoch_period_d: int = 3
    stoch_bullish_threshold: int = 30
    stoch_bearish_threshold: int = 70
    stoch_bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    stoch_max_bars_since_crossing: int = 9

    # Time filter parameters
    time_filter_enabled: bool = False
    trading_hours_start: int = 0
    trading_hours_end: int = 23
    trading_hours_timezone: str = "UTC"
    excluded_hours: list[int] = field(default_factory=list)  # List of hours (0-23) to exclude from trading
    # Multi-timeframe trend filter (disabled by default for zero impact)
    trend_filter_enabled: bool = False
    trend_bar_spec: str = "1-HOUR-MID-EXTERNAL"
    trend_fast_period: int = 20
    trend_slow_period: int = 50
    # Entry timing refinement (disabled by default for zero impact)
    entry_timing_enabled: bool = False
    entry_timing_bar_spec: str = "5-MINUTE-MID-EXTERNAL"
    entry_timing_method: str = "pullback"  # Options: "pullback", "rsi", "stochastic", "breakout"
    entry_timing_timeout_bars: int = 10
    # Dormant mode (disabled by default for zero impact)
    dormant_mode_enabled: bool = False  # Activate lower timeframe trading when crossings are rare
    dormant_threshold_hours: float = 14.0  # Hours without crossover before activating dormant mode
    dormant_bar_spec: str = "1-MINUTE-MID-EXTERNAL"  # Lower timeframe for signal detection
    dormant_fast_period: int = 5  # Fast MA period for dormant mode
    dormant_slow_period: int = 10  # Slow MA period for dormant mode
    dormant_stop_loss_pips: int = 20  # Tighter SL for dormant mode trades
    dormant_take_profit_pips: int = 30  # Smaller TP for dormant mode trades
    dormant_trailing_activation_pips: int = 15  # Lower activation threshold for trailing
    dormant_trailing_distance_pips: int = 8  # Tighter trailing distance
    dormant_dmi_enabled: bool = False  # Use DMI filter in dormant mode
    dormant_stoch_enabled: bool = False  # Use Stochastic filter in dormant mode


def _require(name: str, value: Optional[str]) -> str:
    if not value:
        raise ValueError(f"Environment variable {name} is required for live trading")
    return value


def _parse_int(name: str, value: Optional[str], default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - validation
        raise ValueError(f"{name} must be an integer, got: {value}") from exc


def _parse_float(name: str, value: Optional[str], default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:  # pragma: no cover - validation
        raise ValueError(f"{name} must be a float, got: {value}") from exc


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.lower() in ("true", "1", "yes")


 


def get_live_config() -> LiveConfig:
    """Load live trading configuration from environment variables.

    Optional env vars additionally supported:
    LIVE_TIME_FILTER_ENABLED, LIVE_TRADING_HOURS_START, LIVE_TRADING_HOURS_END,
    LIVE_TRADING_HOURS_TIMEZONE, LIVE_EXCLUDED_HOURS
    """
    load_dotenv()

    symbol = _require("LIVE_SYMBOL", os.getenv("LIVE_SYMBOL"))
    venue = os.getenv("LIVE_VENUE", "SMART")
    bar_spec = os.getenv("LIVE_BAR_SPEC", "1-MINUTE-LAST")

    fast_period = _parse_int("LIVE_FAST_PERIOD", os.getenv("LIVE_FAST_PERIOD"), 10)
    slow_period = _parse_int("LIVE_SLOW_PERIOD", os.getenv("LIVE_SLOW_PERIOD"), 20)
    trade_size = _parse_int("LIVE_TRADE_SIZE", os.getenv("LIVE_TRADE_SIZE"), 100)

    if fast_period >= slow_period:
        raise ValueError("LIVE_FAST_PERIOD must be less than LIVE_SLOW_PERIOD")

    enforce_position_limit = _parse_bool(os.getenv("LIVE_ENFORCE_POSITION_LIMIT"), True)
    allow_position_reversal = _parse_bool(os.getenv("LIVE_ALLOW_POSITION_REVERSAL"), False)
    log_dir = os.getenv("LIVE_LOG_DIR", "logs/live")
    trader_id = os.getenv("LIVE_TRADER_ID", "LIVE-TRADER-001")

    # Phase 6 Risk Management Parameters
    stop_loss_pips = _parse_int("LIVE_STOP_LOSS_PIPS", os.getenv("LIVE_STOP_LOSS_PIPS"), 25)
    take_profit_pips = _parse_int("LIVE_TAKE_PROFIT_PIPS", os.getenv("LIVE_TAKE_PROFIT_PIPS"), 50)
    trailing_stop_activation_pips = _parse_int(
        "LIVE_TRAILING_STOP_ACTIVATION_PIPS", os.getenv("LIVE_TRAILING_STOP_ACTIVATION_PIPS"), 20
    )
    trailing_stop_distance_pips = _parse_int(
        "LIVE_TRAILING_STOP_DISTANCE_PIPS", os.getenv("LIVE_TRAILING_STOP_DISTANCE_PIPS"), 15
    )

    # Phase 6 Signal Filter Parameters
    crossover_threshold_pips = _parse_float(
        "LIVE_CROSSOVER_THRESHOLD_PIPS", os.getenv("LIVE_CROSSOVER_THRESHOLD_PIPS"), 0.7
    )

    # Phase 6 DMI Parameters
    dmi_enabled = _parse_bool(os.getenv("LIVE_DMI_ENABLED"), True)
    dmi_period = _parse_int("LIVE_DMI_PERIOD", os.getenv("LIVE_DMI_PERIOD"), 14)
    dmi_bar_spec = os.getenv("LIVE_DMI_BAR_SPEC", "2-MINUTE-MID-EXTERNAL")
    dmi_minimum_difference = _parse_float("LIVE_DMI_MINIMUM_DIFFERENCE", os.getenv("LIVE_DMI_MINIMUM_DIFFERENCE"), 0.0)

    # Phase 6 Stochastic Parameters
    stoch_enabled = _parse_bool(os.getenv("LIVE_STOCH_ENABLED"), True)
    stoch_period_k = _parse_int("LIVE_STOCH_PERIOD_K", os.getenv("LIVE_STOCH_PERIOD_K"), 14)
    stoch_period_d = _parse_int("LIVE_STOCH_PERIOD_D", os.getenv("LIVE_STOCH_PERIOD_D"), 3)
    stoch_bullish_threshold = _parse_int(
        "LIVE_STOCH_BULLISH_THRESHOLD", os.getenv("LIVE_STOCH_BULLISH_THRESHOLD"), 30
    )
    stoch_bearish_threshold = _parse_int(
        "LIVE_STOCH_BEARISH_THRESHOLD", os.getenv("LIVE_STOCH_BEARISH_THRESHOLD"), 70
    )
    stoch_bar_spec = os.getenv("LIVE_STOCH_BAR_SPEC", "15-MINUTE-MID-EXTERNAL")
    stoch_max_bars_since_crossing = _parse_int(
        "LIVE_STOCH_MAX_BARS_SINCE_CROSSING", os.getenv("LIVE_STOCH_MAX_BARS_SINCE_CROSSING"), 9
    )

    # Time filter parameters
    time_filter_enabled = _parse_bool(os.getenv("LIVE_TIME_FILTER_ENABLED"), False)
    trading_hours_start = _parse_int("LIVE_TRADING_HOURS_START", os.getenv("LIVE_TRADING_HOURS_START"), 0)
    trading_hours_end = _parse_int("LIVE_TRADING_HOURS_END", os.getenv("LIVE_TRADING_HOURS_END"), 23)
    trading_hours_timezone = os.getenv("LIVE_TRADING_HOURS_TIMEZONE", "UTC")
    excluded_hours = _parse_excluded_hours("LIVE_EXCLUDED_HOURS", os.getenv("LIVE_EXCLUDED_HOURS"))

    # Multi-timeframe trend filter parameters (disabled by default)
    trend_filter_enabled = _parse_bool(os.getenv("LIVE_TREND_FILTER_ENABLED"), False)
    trend_bar_spec = os.getenv("LIVE_TREND_BAR_SPEC", "1-HOUR-MID-EXTERNAL")
    trend_fast_period = _parse_int("LIVE_TREND_FAST_PERIOD", os.getenv("LIVE_TREND_FAST_PERIOD"), 20)
    trend_slow_period = _parse_int("LIVE_TREND_SLOW_PERIOD", os.getenv("LIVE_TREND_SLOW_PERIOD"), 50)
    
    # Entry timing refinement parameters (disabled by default)
    entry_timing_enabled = _parse_bool(os.getenv("LIVE_ENTRY_TIMING_ENABLED"), False)
    entry_timing_bar_spec = os.getenv("LIVE_ENTRY_TIMING_BAR_SPEC", "5-MINUTE-MID-EXTERNAL")
    entry_timing_method = os.getenv("LIVE_ENTRY_TIMING_METHOD", "pullback")
    entry_timing_timeout_bars = _parse_int("LIVE_ENTRY_TIMING_TIMEOUT_BARS", os.getenv("LIVE_ENTRY_TIMING_TIMEOUT_BARS"), 10)
    
    # Dormant mode parameters (disabled by default)
    dormant_mode_enabled = _parse_bool(os.getenv("LIVE_DORMANT_MODE_ENABLED"), False)
    dormant_threshold_hours = _parse_float("LIVE_DORMANT_THRESHOLD_HOURS", os.getenv("LIVE_DORMANT_THRESHOLD_HOURS"), 14.0)
    dormant_bar_spec = os.getenv("LIVE_DORMANT_BAR_SPEC", "1-MINUTE-MID-EXTERNAL")
    dormant_fast_period = _parse_int("LIVE_DORMANT_FAST_PERIOD", os.getenv("LIVE_DORMANT_FAST_PERIOD"), 5)
    dormant_slow_period = _parse_int("LIVE_DORMANT_SLOW_PERIOD", os.getenv("LIVE_DORMANT_SLOW_PERIOD"), 10)
    dormant_stop_loss_pips = _parse_int("LIVE_DORMANT_STOP_LOSS_PIPS", os.getenv("LIVE_DORMANT_STOP_LOSS_PIPS"), 20)
    dormant_take_profit_pips = _parse_int("LIVE_DORMANT_TAKE_PROFIT_PIPS", os.getenv("LIVE_DORMANT_TAKE_PROFIT_PIPS"), 30)
    dormant_trailing_activation_pips = _parse_int("LIVE_DORMANT_TRAILING_ACTIVATION_PIPS", os.getenv("LIVE_DORMANT_TRAILING_ACTIVATION_PIPS"), 15)
    dormant_trailing_distance_pips = _parse_int("LIVE_DORMANT_TRAILING_DISTANCE_PIPS", os.getenv("LIVE_DORMANT_TRAILING_DISTANCE_PIPS"), 8)
    dormant_dmi_enabled = _parse_bool(os.getenv("LIVE_DORMANT_DMI_ENABLED"), False)
    dormant_stoch_enabled = _parse_bool(os.getenv("LIVE_DORMANT_STOCH_ENABLED"), False)

    # Validation (Phase 6)
    if take_profit_pips <= stop_loss_pips:
        raise ValueError("LIVE_TAKE_PROFIT_PIPS must be greater than LIVE_STOP_LOSS_PIPS")

    if trailing_stop_activation_pips <= trailing_stop_distance_pips:
        raise ValueError(
            "LIVE_TRAILING_STOP_ACTIVATION_PIPS must be greater than LIVE_TRAILING_STOP_DISTANCE_PIPS"
        )

    if crossover_threshold_pips < 0:
        raise ValueError("LIVE_CROSSOVER_THRESHOLD_PIPS must be >= 0")

    if dmi_enabled:
        if dmi_period <= 0:
            raise ValueError("LIVE_DMI_PERIOD must be > 0")
        
        if dmi_minimum_difference < 0:
            raise ValueError("LIVE_DMI_MINIMUM_DIFFERENCE must be >= 0")

    if stoch_enabled:
        if stoch_period_k <= 0:
            raise ValueError("LIVE_STOCH_PERIOD_K must be > 0")

        if stoch_period_d <= 0:
            raise ValueError("LIVE_STOCH_PERIOD_D must be > 0")

        if not (0 <= stoch_bullish_threshold <= 100):
            raise ValueError("LIVE_STOCH_BULLISH_THRESHOLD must be between 0 and 100")

        if not (0 <= stoch_bearish_threshold <= 100):
            raise ValueError("LIVE_STOCH_BEARISH_THRESHOLD must be between 0 and 100")

        if stoch_bullish_threshold >= stoch_bearish_threshold:
            raise ValueError(
                "LIVE_STOCH_BULLISH_THRESHOLD must be less than LIVE_STOCH_BEARISH_THRESHOLD"
            )

    # Time filter validation
    if time_filter_enabled:
        if not (0 <= trading_hours_start <= 23):
            raise ValueError("LIVE_TRADING_HOURS_START must be between 0 and 23")
        if not (0 <= trading_hours_end <= 23):
            raise ValueError("LIVE_TRADING_HOURS_END must be between 0 and 23")
        if trading_hours_start >= trading_hours_end:
            raise ValueError(
                "LIVE_TRADING_HOURS_START must be less than LIVE_TRADING_HOURS_END (overnight windows not supported)"
            )
        validate_timezone("LIVE_TRADING_HOURS_TIMEZONE", trading_hours_timezone)
        if excluded_hours:
            logger = logging.getLogger(__name__)
            logger.info("Excluded hours configured: %s", excluded_hours)
            window_hours = set(range(trading_hours_start, trading_hours_end + 1))
            if window_hours.issubset(set(excluded_hours)):
                raise ValueError(
                    f"LIVE_EXCLUDED_HOURS excludes all hours in the trading window ({trading_hours_start}-{trading_hours_end}), no trades possible"
                )

    logger = logging.getLogger(__name__)
    if trailing_stop_activation_pips > take_profit_pips:
        logger.warning(
            "Trailing stop activation (%d pips) is greater than take profit (%d pips). Trailing may not activate before TP hit.",
            trailing_stop_activation_pips,
            take_profit_pips,
        )

    if crossover_threshold_pips > stop_loss_pips:
        logger.warning(
            "Crossover threshold (%s pips) is greater than stop loss (%s pips). This may result in very few or no signals being generated.",
            crossover_threshold_pips,
            stop_loss_pips,
        )

    if time_filter_enabled:
        if trading_hours_start == 0 and trading_hours_end == 23:
            logger.warning(
                "Time filter is enabled but covers entire day (00-23); filter has no effect."
            )
    else:
        if excluded_hours:
            logger.warning(
                "Excluded hours configured but time filter is disabled; excluded_hours will have no effect"
            )

    # Normalize FX bar specs (convert LAST->MID and ensure aggregation suffix) for forex instruments
    # Primary bar_spec normalization
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

    if bar_spec != original_bar_spec:
        logger.info("Normalized bar_spec for %s: %s -> %s", symbol, original_bar_spec, bar_spec)

    # DMI bar_spec normalization for FX
    if dmi_enabled and "/" in symbol:
        original_dmi_bar_spec = dmi_bar_spec
        if "-LAST-EXTERNAL" in dmi_bar_spec:
            dmi_bar_spec = dmi_bar_spec.replace("-LAST-EXTERNAL", "-MID-EXTERNAL")
        elif "-LAST-INTERNAL" in dmi_bar_spec:
            dmi_bar_spec = dmi_bar_spec.replace("-LAST-INTERNAL", "-MID-INTERNAL")
        elif dmi_bar_spec.endswith("-LAST"):
            dmi_bar_spec = dmi_bar_spec[:-4] + "MID-EXTERNAL"
        elif "-MID" not in dmi_bar_spec and "-LAST" not in dmi_bar_spec:
            if dmi_bar_spec.endswith("-EXTERNAL") or dmi_bar_spec.endswith("-INTERNAL"):
                suffix = "-EXTERNAL" if dmi_bar_spec.endswith("-EXTERNAL") else "-INTERNAL"
                dmi_bar_spec = dmi_bar_spec[: -len(suffix)] + "-MID" + suffix
            else:
                dmi_bar_spec = f"{dmi_bar_spec}-MID"

        if not dmi_bar_spec.endswith("-EXTERNAL") and not dmi_bar_spec.endswith("-INTERNAL"):
            dmi_bar_spec = f"{dmi_bar_spec}-EXTERNAL"

        if dmi_bar_spec != original_dmi_bar_spec:
            logger.info(
                "Normalized DMI bar_spec for %s: %s -> %s",
                symbol,
                original_dmi_bar_spec,
                dmi_bar_spec,
            )

    # Stochastic bar_spec normalization for FX
    if stoch_enabled and "/" in symbol:
        original_stoch_bar_spec = stoch_bar_spec
        if "-LAST-EXTERNAL" in stoch_bar_spec:
            stoch_bar_spec = stoch_bar_spec.replace("-LAST-EXTERNAL", "-MID-EXTERNAL")
        elif "-LAST-INTERNAL" in stoch_bar_spec:
            stoch_bar_spec = stoch_bar_spec.replace("-LAST-INTERNAL", "-MID-INTERNAL")
        elif stoch_bar_spec.endswith("-LAST"):
            stoch_bar_spec = stoch_bar_spec[:-4] + "MID-EXTERNAL"
        elif "-MID" not in stoch_bar_spec and "-LAST" not in stoch_bar_spec:
            if stoch_bar_spec.endswith("-EXTERNAL") or stoch_bar_spec.endswith("-INTERNAL"):
                suffix = "-EXTERNAL" if stoch_bar_spec.endswith("-EXTERNAL") else "-INTERNAL"
                stoch_bar_spec = stoch_bar_spec[: -len(suffix)] + "-MID" + suffix
            else:
                stoch_bar_spec = f"{stoch_bar_spec}-MID"

        if not stoch_bar_spec.endswith("-EXTERNAL") and not stoch_bar_spec.endswith("-INTERNAL"):
            stoch_bar_spec = f"{stoch_bar_spec}-EXTERNAL"

        if stoch_bar_spec != original_stoch_bar_spec:
            logger.info(
                "Normalized Stochastic bar_spec for %s: %s -> %s",
                symbol,
                original_stoch_bar_spec,
                stoch_bar_spec,
            )

    return LiveConfig(
        symbol=symbol,
        venue=venue,
        bar_spec=bar_spec,
        fast_period=fast_period,
        slow_period=slow_period,
        trade_size=trade_size,
        enforce_position_limit=enforce_position_limit,
        allow_position_reversal=allow_position_reversal,
        log_dir=log_dir,
        trader_id=trader_id,
        stop_loss_pips=stop_loss_pips,
        take_profit_pips=take_profit_pips,
        trailing_stop_activation_pips=trailing_stop_activation_pips,
        trailing_stop_distance_pips=trailing_stop_distance_pips,
        crossover_threshold_pips=crossover_threshold_pips,
        dmi_enabled=dmi_enabled,
        dmi_period=dmi_period,
        dmi_bar_spec=dmi_bar_spec,
        dmi_minimum_difference=dmi_minimum_difference,
        stoch_enabled=stoch_enabled,
        stoch_period_k=stoch_period_k,
        stoch_period_d=stoch_period_d,
        stoch_bullish_threshold=stoch_bullish_threshold,
        stoch_bearish_threshold=stoch_bearish_threshold,
        stoch_bar_spec=stoch_bar_spec,
        stoch_max_bars_since_crossing=stoch_max_bars_since_crossing,
        time_filter_enabled=time_filter_enabled,
        trading_hours_start=trading_hours_start,
        trading_hours_end=trading_hours_end,
        trading_hours_timezone=trading_hours_timezone,
        excluded_hours=excluded_hours,
        trend_filter_enabled=trend_filter_enabled,
        trend_bar_spec=trend_bar_spec,
        trend_fast_period=trend_fast_period,
        trend_slow_period=trend_slow_period,
        entry_timing_enabled=entry_timing_enabled,
        entry_timing_bar_spec=entry_timing_bar_spec,
        entry_timing_method=entry_timing_method,
        entry_timing_timeout_bars=entry_timing_timeout_bars,
        dormant_mode_enabled=dormant_mode_enabled,
        dormant_threshold_hours=dormant_threshold_hours,
        dormant_bar_spec=dormant_bar_spec,
        dormant_fast_period=dormant_fast_period,
        dormant_slow_period=dormant_slow_period,
        dormant_stop_loss_pips=dormant_stop_loss_pips,
        dormant_take_profit_pips=dormant_take_profit_pips,
        dormant_trailing_activation_pips=dormant_trailing_activation_pips,
        dormant_trailing_distance_pips=dormant_trailing_distance_pips,
        dormant_dmi_enabled=dormant_dmi_enabled,
        dormant_stoch_enabled=dormant_stoch_enabled,
    )


def validate_live_config(config: LiveConfig) -> bool:
    """Validate live trading configuration."""
    ok = True

    if not config.symbol:
        ok = False

    if config.fast_period >= config.slow_period:
        ok = False

    # Phase 6 validations
    if config.stop_loss_pips <= 0:
        ok = False

    if config.take_profit_pips <= config.stop_loss_pips:
        ok = False

    if config.trailing_stop_activation_pips <= config.trailing_stop_distance_pips:
        ok = False

    if config.crossover_threshold_pips < 0:
        ok = False

    if config.dmi_period <= 0:
        ok = False

    if config.stoch_period_k <= 0 or config.stoch_period_d <= 0:
        ok = False

    if not (0 <= config.stoch_bullish_threshold <= 100):
        ok = False

    if not (0 <= config.stoch_bearish_threshold <= 100):
        ok = False

    if config.stoch_bullish_threshold >= config.stoch_bearish_threshold:
        ok = False

    try:
        Path(config.log_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        ok = False

    return ok
