"""Live trading configuration management.

Provides a typed configuration object and loader for live trading parameters
sourced from environment variables. Now with full feature parity to backtest configuration.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class LiveConfig:
    """Live trading configuration with full backtest feature parity."""
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
    
    # Adaptive stops configuration (NEW - from backtest)
    adaptive_stop_mode: str = "atr"  # 'fixed' | 'atr' | 'percentile'
    adaptive_atr_period: int = 14
    tp_atr_mult: float = 2.5
    sl_atr_mult: float = 1.5
    trail_activation_atr_mult: float = 1.0
    trail_distance_atr_mult: float = 0.8
    volatility_window: int = 200
    volatility_sensitivity: float = 0.6
    min_stop_distance_pips: float = 5.0
    
    # Market regime detection (NEW - from backtest)
    regime_detection_enabled: bool = False
    regime_adx_trending_threshold: float = 25.0
    regime_adx_ranging_threshold: float = 20.0
    regime_tp_multiplier_trending: float = 1.5
    regime_tp_multiplier_ranging: float = 0.8
    regime_sl_multiplier_trending: float = 1.0
    regime_sl_multiplier_ranging: float = 1.0
    regime_trailing_activation_multiplier_trending: float = 0.75
    regime_trailing_activation_multiplier_ranging: float = 1.25
    regime_trailing_distance_multiplier_trending: float = 0.67
    regime_trailing_distance_multiplier_ranging: float = 1.33
    
    # Signal Filter Parameters
    crossover_threshold_pips: float = 0.7
    
    # DMI Indicator Parameters
    dmi_enabled: bool = True
    dmi_period: int = 14
    dmi_bar_spec: str = "2-MINUTE-MID-EXTERNAL"
    
    # Stochastic Indicator Parameters
    stoch_enabled: bool = True
    stoch_period_k: int = 14
    stoch_period_d: int = 3
    stoch_bullish_threshold: int = 30
    stoch_bearish_threshold: int = 70
    stoch_bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    stoch_max_bars_since_crossing: int = 18
    
    # Time filter parameters
    time_filter_enabled: bool = False
    excluded_hours: list[int] = field(default_factory=list)  # List of hours (0-23) to exclude from trading
    excluded_hours_mode: str = "flat"  # "flat" | "weekday" - NEW from backtest
    excluded_hours_by_weekday: dict[str, list[int]] = field(default_factory=dict)  # NEW from backtest
    
    # Trend filter (aligned with backtest)
    trend_filter_enabled: bool = False
    trend_bar_spec: str = "1-MINUTE-MID-EXTERNAL"
    trend_ema_period: int = 150
    trend_ema_threshold_pips: float = 0.0
    
    # RSI filter (NEW - from backtest)
    rsi_enabled: bool = False
    rsi_period: int = 14
    rsi_overbought: int = 70
    rsi_oversold: int = 30
    rsi_divergence_lookback: int = 5
    
    # Volume filter (NEW - from backtest)
    volume_enabled: bool = False
    volume_avg_period: int = 20
    volume_min_multiplier: float = 1.2
    
    # ATR filter (NEW - from backtest)
    atr_enabled: bool = False
    atr_period: int = 14
    atr_min_strength: float = 0.001
    
    # Entry timing refinement
    entry_timing_enabled: bool = False
    entry_timing_bar_spec: str = "2-MINUTE-MID-EXTERNAL"
    entry_timing_method: str = "pullback"  # pullback | breakout | momentum
    entry_timing_timeout_bars: int = 10


def _require(name: str, value: Optional[str]) -> str:
    """Require an environment variable to be set."""
    if not value:
        raise ValueError(f"Environment variable {name} is required for live trading")
    return value


def _parse_int(name: str, value: Optional[str], default: int) -> int:
    """Parse integer environment variable."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got: {value}") from exc


def _parse_float(name: str, value: Optional[str], default: float) -> float:
    """Parse float environment variable."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float, got: {value}") from exc


def _parse_bool(value: Optional[str], default: bool) -> bool:
    """Parse boolean environment variable."""
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes")


def _parse_excluded_hours(name: str, value: Optional[str]) -> list[int]:
    """Parse comma-separated list of hours (0-23) to exclude from trading."""
    if value is None or value == "":
        return []
    try:
        hours = [int(h.strip()) for h in value.split(",") if h.strip()]
        # Validate hours are in range 0-23
        for hour in hours:
            if not (0 <= hour <= 23):
                raise ValueError(f"invalid hour {hour}")
        return sorted(set(hours))  # Remove duplicates and sort
    except ValueError as e:
        if "invalid hour" in str(e):
            raise
        raise ValueError(f"{name} must be comma-separated integers (0-23), got: {value}") from e


def get_live_config() -> LiveConfig:
    """Load live trading configuration from environment variables with full backtest feature parity."""
    # Load .env.live file if it exists, otherwise fall back to .env
    env_file = Path(".env.live")
    if not env_file.exists():
        env_file = Path(".env")
    load_dotenv(env_file)

    # Required parameters
    symbol = _require("LIVE_SYMBOL", os.getenv("LIVE_SYMBOL"))
    venue = os.getenv("LIVE_VENUE", "SMART")
    bar_spec = os.getenv("LIVE_BAR_SPEC", "1-MINUTE-LAST")

    # Basic strategy parameters
    fast_period = _parse_int("LIVE_FAST_PERIOD", os.getenv("LIVE_FAST_PERIOD"), 10)
    slow_period = _parse_int("LIVE_SLOW_PERIOD", os.getenv("LIVE_SLOW_PERIOD"), 20)
    trade_size = _parse_int("LIVE_TRADE_SIZE", os.getenv("LIVE_TRADE_SIZE"), 100)

    if fast_period >= slow_period:
        raise ValueError("LIVE_FAST_PERIOD must be less than LIVE_SLOW_PERIOD")

    enforce_position_limit = _parse_bool(os.getenv("LIVE_ENFORCE_POSITION_LIMIT"), True)
    allow_position_reversal = _parse_bool(os.getenv("LIVE_ALLOW_POSITION_REVERSAL"), False)
    log_dir = os.getenv("LIVE_LOG_DIR", "logs/live")
    trader_id = os.getenv("LIVE_TRADER_ID", "LIVE-TRADER-001")

    # Risk Management Parameters
    stop_loss_pips = _parse_int("LIVE_STOP_LOSS_PIPS", os.getenv("LIVE_STOP_LOSS_PIPS"), 25)
    take_profit_pips = _parse_int("LIVE_TAKE_PROFIT_PIPS", os.getenv("LIVE_TAKE_PROFIT_PIPS"), 50)
    trailing_stop_activation_pips = _parse_int(
        "LIVE_TRAILING_STOP_ACTIVATION_PIPS", os.getenv("LIVE_TRAILING_STOP_ACTIVATION_PIPS"), 20
    )
    trailing_stop_distance_pips = _parse_int(
        "LIVE_TRAILING_STOP_DISTANCE_PIPS", os.getenv("LIVE_TRAILING_STOP_DISTANCE_PIPS"), 15
    )

    # Adaptive stops configuration (NEW)
    adaptive_stop_mode = os.getenv("LIVE_ADAPTIVE_STOP_MODE", "atr")
    adaptive_atr_period = _parse_int("LIVE_ADAPTIVE_ATR_PERIOD", os.getenv("LIVE_ADAPTIVE_ATR_PERIOD"), 14)
    tp_atr_mult = _parse_float("LIVE_TP_ATR_MULT", os.getenv("LIVE_TP_ATR_MULT"), 2.5)
    sl_atr_mult = _parse_float("LIVE_SL_ATR_MULT", os.getenv("LIVE_SL_ATR_MULT"), 1.5)
    trail_activation_atr_mult = _parse_float("LIVE_TRAIL_ACTIVATION_ATR_MULT", os.getenv("LIVE_TRAIL_ACTIVATION_ATR_MULT"), 1.0)
    trail_distance_atr_mult = _parse_float("LIVE_TRAIL_DISTANCE_ATR_MULT", os.getenv("LIVE_TRAIL_DISTANCE_ATR_MULT"), 0.8)
    volatility_window = _parse_int("LIVE_VOLATILITY_WINDOW", os.getenv("LIVE_VOLATILITY_WINDOW"), 200)
    volatility_sensitivity = _parse_float("LIVE_VOLATILITY_SENSITIVITY", os.getenv("LIVE_VOLATILITY_SENSITIVITY"), 0.6)
    min_stop_distance_pips = _parse_float("LIVE_MIN_STOP_DISTANCE_PIPS", os.getenv("LIVE_MIN_STOP_DISTANCE_PIPS"), 5.0)

    # Market regime detection (NEW)
    regime_detection_enabled = _parse_bool(os.getenv("LIVE_REGIME_DETECTION_ENABLED"), False)
    regime_adx_trending_threshold = _parse_float("LIVE_REGIME_ADX_TRENDING_THRESHOLD", os.getenv("LIVE_REGIME_ADX_TRENDING_THRESHOLD"), 25.0)
    regime_adx_ranging_threshold = _parse_float("LIVE_REGIME_ADX_RANGING_THRESHOLD", os.getenv("LIVE_REGIME_ADX_RANGING_THRESHOLD"), 20.0)
    regime_tp_multiplier_trending = _parse_float("LIVE_REGIME_TP_MULTIPLIER_TRENDING", os.getenv("LIVE_REGIME_TP_MULTIPLIER_TRENDING"), 1.5)
    regime_tp_multiplier_ranging = _parse_float("LIVE_REGIME_TP_MULTIPLIER_RANGING", os.getenv("LIVE_REGIME_TP_MULTIPLIER_RANGING"), 0.8)
    regime_sl_multiplier_trending = _parse_float("LIVE_REGIME_SL_MULTIPLIER_TRENDING", os.getenv("LIVE_REGIME_SL_MULTIPLIER_TRENDING"), 1.0)
    regime_sl_multiplier_ranging = _parse_float("LIVE_REGIME_SL_MULTIPLIER_RANGING", os.getenv("LIVE_REGIME_SL_MULTIPLIER_RANGING"), 1.0)
    regime_trailing_activation_multiplier_trending = _parse_float("LIVE_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING", os.getenv("LIVE_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING"), 0.75)
    regime_trailing_activation_multiplier_ranging = _parse_float("LIVE_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING", os.getenv("LIVE_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING"), 1.25)
    regime_trailing_distance_multiplier_trending = _parse_float("LIVE_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING", os.getenv("LIVE_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING"), 0.67)
    regime_trailing_distance_multiplier_ranging = _parse_float("LIVE_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING", os.getenv("LIVE_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING"), 1.33)

    # Signal Filter Parameters
    crossover_threshold_pips = _parse_float(
        "LIVE_CROSSOVER_THRESHOLD_PIPS", os.getenv("LIVE_CROSSOVER_THRESHOLD_PIPS"), 0.7
    )

    # DMI Parameters
    dmi_enabled = _parse_bool(os.getenv("LIVE_DMI_ENABLED"), True)
    dmi_period = _parse_int("LIVE_DMI_PERIOD", os.getenv("LIVE_DMI_PERIOD"), 14)
    dmi_bar_spec = os.getenv("LIVE_DMI_BAR_SPEC", "2-MINUTE-MID-EXTERNAL")

    # Stochastic Parameters
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
        "LIVE_STOCH_MAX_BARS_SINCE_CROSSING", os.getenv("LIVE_STOCH_MAX_BARS_SINCE_CROSSING"), 18
    )

    # Time filter parameters
    time_filter_enabled = _parse_bool(os.getenv("LIVE_TIME_FILTER_ENABLED"), False)
    excluded_hours = _parse_excluded_hours("LIVE_EXCLUDED_HOURS", os.getenv("LIVE_EXCLUDED_HOURS"))
    excluded_hours_mode = os.getenv("LIVE_EXCLUDED_HOURS_MODE", "flat").lower()
    
    # Parse weekday-specific exclusions if mode is "weekday" (NEW)
    excluded_hours_by_weekday = {}
    if excluded_hours_mode == "weekday":
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for weekday in weekdays:
            env_var = f"LIVE_EXCLUDED_HOURS_{weekday.upper()}"
            weekday_hours = _parse_excluded_hours(env_var, os.getenv(env_var))
            if weekday_hours:
                excluded_hours_by_weekday[weekday] = weekday_hours

    # Trend filter parameters (aligned with backtest)
    trend_filter_enabled = _parse_bool(os.getenv("LIVE_TREND_FILTER_ENABLED"), False)
    trend_bar_spec = os.getenv("LIVE_TREND_BAR_SPEC", "1-MINUTE-MID-EXTERNAL")
    trend_ema_period = _parse_int("LIVE_TREND_EMA_PERIOD", os.getenv("LIVE_TREND_EMA_PERIOD"), 150)
    trend_ema_threshold_pips = _parse_float("LIVE_TREND_EMA_THRESHOLD_PIPS", os.getenv("LIVE_TREND_EMA_THRESHOLD_PIPS"), 0.0)

    # RSI filter (NEW)
    rsi_enabled = _parse_bool(os.getenv("LIVE_RSI_ENABLED"), False)
    rsi_period = _parse_int("LIVE_RSI_PERIOD", os.getenv("LIVE_RSI_PERIOD"), 14)
    rsi_overbought = _parse_int("LIVE_RSI_OVERBOUGHT", os.getenv("LIVE_RSI_OVERBOUGHT"), 70)
    rsi_oversold = _parse_int("LIVE_RSI_OVERSOLD", os.getenv("LIVE_RSI_OVERSOLD"), 30)
    rsi_divergence_lookback = _parse_int("LIVE_RSI_DIVERGENCE_LOOKBACK", os.getenv("LIVE_RSI_DIVERGENCE_LOOKBACK"), 5)

    # Volume filter (NEW)
    volume_enabled = _parse_bool(os.getenv("LIVE_VOLUME_ENABLED"), False)
    volume_avg_period = _parse_int("LIVE_VOLUME_AVG_PERIOD", os.getenv("LIVE_VOLUME_AVG_PERIOD"), 20)
    volume_min_multiplier = _parse_float("LIVE_VOLUME_MIN_MULTIPLIER", os.getenv("LIVE_VOLUME_MIN_MULTIPLIER"), 1.2)

    # ATR filter (NEW)
    atr_enabled = _parse_bool(os.getenv("LIVE_ATR_ENABLED"), False)
    atr_period = _parse_int("LIVE_ATR_PERIOD", os.getenv("LIVE_ATR_PERIOD"), 14)
    atr_min_strength = _parse_float("LIVE_ATR_MIN_STRENGTH", os.getenv("LIVE_ATR_MIN_STRENGTH"), 0.001)

    # Entry timing parameters
    entry_timing_enabled = _parse_bool(os.getenv("LIVE_ENTRY_TIMING_ENABLED"), False)
    entry_timing_bar_spec = os.getenv("LIVE_ENTRY_TIMING_BAR_SPEC", "2-MINUTE-MID-EXTERNAL")
    entry_timing_method = os.getenv("LIVE_ENTRY_TIMING_METHOD", "pullback")
    entry_timing_timeout_bars = _parse_int("LIVE_ENTRY_TIMING_TIMEOUT_BARS", os.getenv("LIVE_ENTRY_TIMING_TIMEOUT_BARS"), 10)

    # Validation
    if take_profit_pips <= stop_loss_pips:
        raise ValueError("LIVE_TAKE_PROFIT_PIPS must be greater than LIVE_STOP_LOSS_PIPS")

    if trailing_stop_activation_pips <= trailing_stop_distance_pips:
        raise ValueError(
            "LIVE_TRAILING_STOP_ACTIVATION_PIPS must be greater than LIVE_TRAILING_STOP_DISTANCE_PIPS"
        )

    if crossover_threshold_pips < 0:
        raise ValueError("LIVE_CROSSOVER_THRESHOLD_PIPS must be >= 0")

    if dmi_enabled and dmi_period <= 0:
        raise ValueError("LIVE_DMI_PERIOD must be > 0")

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

    # Normalize FX bar specs for forex instruments
    logger = logging.getLogger(__name__)
    original_bar_spec = bar_spec
    if "/" in symbol:
        if "-LAST-EXTERNAL" in bar_spec:
            bar_spec = bar_spec.replace("-LAST-EXTERNAL", "-MID-EXTERNAL")
        elif "-LAST-INTERNAL" in bar_spec:
            bar_spec = bar_spec.replace("-LAST-INTERNAL", "-MID-INTERNAL")
        elif bar_spec.endswith("-LAST"):
            bar_spec = bar_spec[:-4] + "MID-EXTERNAL"
        elif "-MID" not in bar_spec and "-LAST" not in bar_spec:
            if bar_spec.endswith("-EXTERNAL") or bar_spec.endswith("-INTERNAL"):
                suffix = "-EXTERNAL" if bar_spec.endswith("-EXTERNAL") else "-INTERNAL"
                bar_spec = bar_spec[: -len(suffix)] + "-MID" + suffix
            else:
                bar_spec = f"{bar_spec}-MID"

        if not bar_spec.endswith("-EXTERNAL") and not bar_spec.endswith("-INTERNAL"):
            bar_spec = f"{bar_spec}-EXTERNAL"

    if bar_spec != original_bar_spec:
        logger.info("Normalized bar_spec for %s: %s -> %s", symbol, original_bar_spec, bar_spec)

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
        adaptive_stop_mode=adaptive_stop_mode,
        adaptive_atr_period=adaptive_atr_period,
        tp_atr_mult=tp_atr_mult,
        sl_atr_mult=sl_atr_mult,
        trail_activation_atr_mult=trail_activation_atr_mult,
        trail_distance_atr_mult=trail_distance_atr_mult,
        volatility_window=volatility_window,
        volatility_sensitivity=volatility_sensitivity,
        min_stop_distance_pips=min_stop_distance_pips,
        regime_detection_enabled=regime_detection_enabled,
        regime_adx_trending_threshold=regime_adx_trending_threshold,
        regime_adx_ranging_threshold=regime_adx_ranging_threshold,
        regime_tp_multiplier_trending=regime_tp_multiplier_trending,
        regime_tp_multiplier_ranging=regime_tp_multiplier_ranging,
        regime_sl_multiplier_trending=regime_sl_multiplier_trending,
        regime_sl_multiplier_ranging=regime_sl_multiplier_ranging,
        regime_trailing_activation_multiplier_trending=regime_trailing_activation_multiplier_trending,
        regime_trailing_activation_multiplier_ranging=regime_trailing_activation_multiplier_ranging,
        regime_trailing_distance_multiplier_trending=regime_trailing_distance_multiplier_trending,
        regime_trailing_distance_multiplier_ranging=regime_trailing_distance_multiplier_ranging,
        crossover_threshold_pips=crossover_threshold_pips,
        dmi_enabled=dmi_enabled,
        dmi_period=dmi_period,
        dmi_bar_spec=dmi_bar_spec,
        stoch_enabled=stoch_enabled,
        stoch_period_k=stoch_period_k,
        stoch_period_d=stoch_period_d,
        stoch_bullish_threshold=stoch_bullish_threshold,
        stoch_bearish_threshold=stoch_bearish_threshold,
        stoch_bar_spec=stoch_bar_spec,
        stoch_max_bars_since_crossing=stoch_max_bars_since_crossing,
        time_filter_enabled=time_filter_enabled,
        excluded_hours=excluded_hours,
        excluded_hours_mode=excluded_hours_mode,
        excluded_hours_by_weekday=excluded_hours_by_weekday,
        trend_filter_enabled=trend_filter_enabled,
        trend_bar_spec=trend_bar_spec,
        trend_ema_period=trend_ema_period,
        trend_ema_threshold_pips=trend_ema_threshold_pips,
        rsi_enabled=rsi_enabled,
        rsi_period=rsi_period,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        rsi_divergence_lookback=rsi_divergence_lookback,
        volume_enabled=volume_enabled,
        volume_avg_period=volume_avg_period,
        volume_min_multiplier=volume_min_multiplier,
        atr_enabled=atr_enabled,
        atr_period=atr_period,
        atr_min_strength=atr_min_strength,
        entry_timing_enabled=entry_timing_enabled,
        entry_timing_bar_spec=entry_timing_bar_spec,
        entry_timing_method=entry_timing_method,
        entry_timing_timeout_bars=entry_timing_timeout_bars,
    )


def validate_live_config(config: LiveConfig) -> bool:
    """Validate live trading configuration."""
    ok = True

    if not config.symbol:
        ok = False

    if config.fast_period >= config.slow_period:
        ok = False

    try:
        Path(config.log_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        ok = False

    return ok
