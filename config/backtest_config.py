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
    # Adaptive stops configuration
    adaptive_stop_mode: str = "atr"  # 'fixed' | 'atr' | 'percentile'
    adaptive_atr_period: int = 14
    tp_atr_mult: float = 2.5
    sl_atr_mult: float = 1.5
    trail_activation_atr_mult: float = 1.0
    trail_distance_atr_mult: float = 0.8
    volatility_window: int = 200
    volatility_sensitivity: float = 0.6
    min_stop_distance_pips: float = 5.0  # Minimum stop distance to avoid spread/noise
    # Market regime detection
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
    crossover_threshold_pips: float = 0.7
    # Time-of-day multipliers (applied after regime multipliers)
    time_multiplier_enabled: bool = False
    time_tp_multiplier_eu_morning: float = 1.0  # 7-11 UTC (EU session start)
    time_tp_multiplier_us_session: float = 1.0  # 13-17 UTC (US session overlap)
    time_tp_multiplier_other: float = 1.0       # All other hours
    time_sl_multiplier_eu_morning: float = 1.0
    time_sl_multiplier_us_session: float = 1.0
    time_sl_multiplier_other: float = 1.0
    # Trend filter
    trend_filter_enabled: bool = False
    trend_bar_spec: str = "1-MINUTE-MID-EXTERNAL"
    trend_ema_period: int = 150
    trend_ema_threshold_pips: float = 0.0  # Minimum distance in pips above/below EMA
    # RSI filter
    rsi_enabled: bool = False
    rsi_period: int = 14
    rsi_overbought: int = 70
    rsi_oversold: int = 30
    rsi_divergence_lookback: int = 5
    # Volume filter
    volume_enabled: bool = False
    volume_avg_period: int = 20
    volume_min_multiplier: float = 1.2
    # ATR filter
    atr_enabled: bool = False
    atr_period: int = 14
    atr_min_strength: float = 0.001
    dmi_enabled: bool = True
    dmi_bar_spec: str = "2-MINUTE-MID-EXTERNAL"
    dmi_period: int = 14
    stoch_enabled: bool = True
    stoch_bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    stoch_period_k: int = 14
    stoch_period_d: int = 3
    stoch_bullish_threshold: int = 30
    stoch_bearish_threshold: int = 70
    stoch_max_bars_since_crossing: int = 18
    # Time filter
    time_filter_enabled: bool = False
    excluded_hours: list[int] = field(default_factory=list)  # List of hours (0-23) to exclude from trading
    excluded_hours_mode: str = "flat"  # "flat" | "weekday" - whether to use same exclusion for all days or weekday-specific
    excluded_hours_by_weekday: dict[str, list[int]] = field(default_factory=dict)  # Weekday-specific exclusions (Monday, Tuesday, etc.)
    # Entry timing (pullback/breakout)
    entry_timing_enabled: bool = False
    entry_timing_bar_spec: str = "2-MINUTE-MID-EXTERNAL"
    entry_timing_method: str = "pullback"  # pullback | breakout | momentum
    entry_timing_timeout_bars: int = 10  # Max bars to wait for entry (e.g., 10 × 2min = 20 minutes)
    # Duration-based trailing stop optimization
    trailing_duration_enabled: bool = False
    trailing_duration_threshold_hours: float = 12.0
    trailing_duration_distance_pips: int = 30
    trailing_duration_remove_tp: bool = True
    trailing_duration_activate_if_not_active: bool = True
    # Partial close on trailing activation
    partial_close_enabled: bool = False
    partial_close_fraction: float = 0.5
    partial_close_move_sl_to_be: bool = True
    partial_close_remainder_trail_multiplier: float = 1.0
    # First partial close before trailing activation
    partial1_enabled: bool = False
    partial1_fraction: float = 0.3
    partial1_threshold_pips: float = 10.0
    partial1_move_sl_to_be: bool = False
    # Market structure filter (avoid recent extremes)
    structure_filter_enabled: bool = False
    structure_lookback_bars: int = 100
    structure_buffer_pips: float = 3.0
    structure_mode: str = "avoid"
    # Minimum hold time feature (wider initial stops)
    min_hold_time_enabled: bool = False
    min_hold_time_hours: float = 4.0
    min_hold_time_stop_multiplier: float = 1.5

    # (Note: Additional strategy toggles can be appended here)

def _require(name: str, value: Optional[str]) -> str:
    if not value:
        raise ValueError(f"Environment variable {name} is required for backtesting")
    return value


def _parse_int(name: str, value: Optional[str], default: int) -> int:
    value = _get_env_value(name, value)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got: {value}")


def _parse_float(name: str, value: Optional[str], default: float) -> float:
    value = _get_env_value(name, value)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{name} must be a float, got: {value}")


def _parse_excluded_hours(name: str, value: Optional[str]) -> list[int]:
    value = _get_env_value(name, value)
    """Parse comma-separated list of hours (0-23) to exclude from trading."""
    if value is None or value == "":
        return []
    try:
        hours = [int(h.strip()) for h in value.split(",") if h.strip()]
        # Validate hours are in range 0-23
        for hour in hours:
            if not (0 <= hour <= 23):
                raise ValueError(f"{name} contains invalid hour: {hour} (must be 0-23)")
        return sorted(set(hours))  # Remove duplicates and sort
    except ValueError as e:
        if "invalid hour" in str(e):
            raise
        raise ValueError(f"{name} must be comma-separated integers (0-23), got: {value}") from e


def _validate_date(name: str, value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{name} must be in YYYY-MM-DD format, got: {value}")


def _get_env_value(name: str, value: Optional[str] = None) -> Optional[str]:
    """Retrieve environment variable with legacy BACKTEST_ fallback for STRATEGY_ keys."""
    if value not in (None, ""):
        return value

    resolved = os.getenv(name)
    if resolved in (None, "") and name.startswith("STRATEGY_"):
        resolved = os.getenv(f"BACKTEST_{name}")

    return resolved


def get_backtest_config() -> BacktestConfig:
    """Load backtest configuration from environment variables.

    Required env vars: BACKTEST_SYMBOL, BACKTEST_START_DATE, BACKTEST_END_DATE
    Optional with defaults: BACKTEST_VENUE, BACKTEST_BAR_SPEC, BACKTEST_FAST_PERIOD,
    BACKTEST_SLOW_PERIOD, BACKTEST_TRADE_SIZE, BACKTEST_STARTING_CAPITAL,
    CATALOG_PATH, OUTPUT_DIR, ENFORCE_POSITION_LIMIT, ALLOW_POSITION_REVERSAL,
    BACKTEST_STOP_LOSS_PIPS, BACKTEST_TAKE_PROFIT_PIPS, BACKTEST_TRAILING_STOP_ACTIVATION_PIPS,
    BACKTEST_TRAILING_STOP_DISTANCE_PIPS,     STRATEGY_CROSSOVER_THRESHOLD_PIPS,
    STRATEGY_DMI_ENABLED, STRATEGY_DMI_BAR_SPEC, STRATEGY_DMI_PERIOD,
    STRATEGY_STOCH_ENABLED, STRATEGY_STOCH_BAR_SPEC, STRATEGY_STOCH_PERIOD_K,
    STRATEGY_STOCH_PERIOD_D, STRATEGY_STOCH_BULLISH_THRESHOLD, STRATEGY_STOCH_BEARISH_THRESHOLD
    """
    # Load .env as fallback, but allow subprocess env vars (from grid runner) to override
    load_dotenv(override=False)  # False = .env doesn't override existing os.environ vars

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
    
    # Debug: Log TP/SL values being used
    print(f"DEBUG CONFIG: SL={stop_loss_pips}, TP={take_profit_pips}, TrailAct={trailing_stop_activation_pips}, TrailDist={trailing_stop_distance_pips}", flush=True)
    
    # Adaptive stops configuration
    adaptive_stop_mode = os.getenv("BACKTEST_ADAPTIVE_STOP_MODE", "atr")  # 'fixed' | 'atr' | 'percentile'
    adaptive_atr_period = _parse_int("BACKTEST_ADAPTIVE_ATR_PERIOD", os.getenv("BACKTEST_ADAPTIVE_ATR_PERIOD"), 14)
    tp_atr_mult = _parse_float("BACKTEST_TP_ATR_MULT", os.getenv("BACKTEST_TP_ATR_MULT"), 2.5)
    sl_atr_mult = _parse_float("BACKTEST_SL_ATR_MULT", os.getenv("BACKTEST_SL_ATR_MULT"), 1.5)
    trail_activation_atr_mult = _parse_float("BACKTEST_TRAIL_ACTIVATION_ATR_MULT", os.getenv("BACKTEST_TRAIL_ACTIVATION_ATR_MULT"), 1.0)
    trail_distance_atr_mult = _parse_float("BACKTEST_TRAIL_DISTANCE_ATR_MULT", os.getenv("BACKTEST_TRAIL_DISTANCE_ATR_MULT"), 0.8)
    volatility_window = _parse_int("BACKTEST_VOLATILITY_WINDOW", os.getenv("BACKTEST_VOLATILITY_WINDOW"), 200)
    volatility_sensitivity = _parse_float("BACKTEST_VOLATILITY_SENSITIVITY", os.getenv("BACKTEST_VOLATILITY_SENSITIVITY"), 0.6)
    min_stop_distance_pips = _parse_float("BACKTEST_MIN_STOP_DISTANCE_PIPS", os.getenv("BACKTEST_MIN_STOP_DISTANCE_PIPS"), 5.0)
    
    # Market regime detection
    regime_detection_enabled = (_get_env_value("STRATEGY_REGIME_DETECTION_ENABLED") or "false").lower() in ("true", "1", "yes")
    regime_adx_trending_threshold = _parse_float("STRATEGY_REGIME_ADX_TRENDING_THRESHOLD", os.getenv("STRATEGY_REGIME_ADX_TRENDING_THRESHOLD"), 25.0)
    regime_adx_ranging_threshold = _parse_float("STRATEGY_REGIME_ADX_RANGING_THRESHOLD", os.getenv("STRATEGY_REGIME_ADX_RANGING_THRESHOLD"), 20.0)
    regime_tp_multiplier_trending = _parse_float("STRATEGY_REGIME_TP_MULTIPLIER_TRENDING", os.getenv("STRATEGY_REGIME_TP_MULTIPLIER_TRENDING"), 1.5)
    regime_tp_multiplier_ranging = _parse_float("STRATEGY_REGIME_TP_MULTIPLIER_RANGING", os.getenv("STRATEGY_REGIME_TP_MULTIPLIER_RANGING"), 0.8)
    regime_sl_multiplier_trending = _parse_float("STRATEGY_REGIME_SL_MULTIPLIER_TRENDING", os.getenv("STRATEGY_REGIME_SL_MULTIPLIER_TRENDING"), 1.0)
    regime_sl_multiplier_ranging = _parse_float("STRATEGY_REGIME_SL_MULTIPLIER_RANGING", os.getenv("STRATEGY_REGIME_SL_MULTIPLIER_RANGING"), 1.0)
    regime_trailing_activation_multiplier_trending = _parse_float("STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING", os.getenv("STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING"), 0.75)
    regime_trailing_activation_multiplier_ranging = _parse_float("STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING", os.getenv("STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING"), 1.25)
    regime_trailing_distance_multiplier_trending = _parse_float("STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING", os.getenv("STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING"), 0.67)
    regime_trailing_distance_multiplier_ranging = _parse_float("STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING", os.getenv("STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING"), 1.33)
    
    # Time-of-day multipliers
    time_multiplier_enabled = (_get_env_value("STRATEGY_TIME_MULTIPLIER_ENABLED") or "false").lower() in ("true", "1", "yes")
    time_tp_multiplier_eu_morning = _parse_float("STRATEGY_TIME_TP_MULTIPLIER_EU_MORNING", None, 1.0)
    time_tp_multiplier_us_session = _parse_float("STRATEGY_TIME_TP_MULTIPLIER_US_SESSION", None, 1.0)
    time_tp_multiplier_other = _parse_float("STRATEGY_TIME_TP_MULTIPLIER_OTHER", None, 1.0)
    time_sl_multiplier_eu_morning = _parse_float("STRATEGY_TIME_SL_MULTIPLIER_EU_MORNING", None, 1.0)
    time_sl_multiplier_us_session = _parse_float("STRATEGY_TIME_SL_MULTIPLIER_US_SESSION", None, 1.0)
    time_sl_multiplier_other = _parse_float("STRATEGY_TIME_SL_MULTIPLIER_OTHER", None, 1.0)
    
    crossover_threshold_pips = _parse_float(
        "STRATEGY_CROSSOVER_THRESHOLD_PIPS",
        os.getenv("STRATEGY_CROSSOVER_THRESHOLD_PIPS"),
        0.7,
    )

    # Trend filter
    trend_filter_enabled = (_get_env_value("STRATEGY_TREND_FILTER_ENABLED") or "false").lower() in ("true", "1", "yes")
    trend_bar_spec = _get_env_value("STRATEGY_TREND_BAR_SPEC") or "1-MINUTE-MID-EXTERNAL"
    trend_ema_period = _parse_int("STRATEGY_TREND_EMA_PERIOD", os.getenv("STRATEGY_TREND_EMA_PERIOD"), 150)
    trend_ema_threshold_pips = _parse_float("STRATEGY_TREND_EMA_THRESHOLD_PIPS", os.getenv("STRATEGY_TREND_EMA_THRESHOLD_PIPS"), 0.0)

    # RSI filter
    rsi_enabled = (_get_env_value("STRATEGY_RSI_ENABLED") or "false").lower() in ("true", "1", "yes")
    rsi_period = _parse_int("STRATEGY_RSI_PERIOD", os.getenv("STRATEGY_RSI_PERIOD"), 14)
    rsi_overbought = _parse_int("STRATEGY_RSI_OVERBOUGHT", os.getenv("STRATEGY_RSI_OVERBOUGHT"), 70)
    rsi_oversold = _parse_int("STRATEGY_RSI_OVERSOLD", os.getenv("STRATEGY_RSI_OVERSOLD"), 30)
    rsi_divergence_lookback = _parse_int("STRATEGY_RSI_DIVERGENCE_LOOKBACK", os.getenv("STRATEGY_RSI_DIVERGENCE_LOOKBACK"), 5)

    # Volume filter
    volume_enabled = (_get_env_value("STRATEGY_VOLUME_ENABLED") or "false").lower() in ("true", "1", "yes")
    volume_avg_period = _parse_int("STRATEGY_VOLUME_AVG_PERIOD", os.getenv("STRATEGY_VOLUME_AVG_PERIOD"), 20)
    volume_min_multiplier = float(_get_env_value("STRATEGY_VOLUME_MIN_MULTIPLIER") or "1.2")

    # ATR filter
    atr_enabled = (_get_env_value("STRATEGY_ATR_ENABLED") or "false").lower() in ("true", "1", "yes")
    atr_period = _parse_int("STRATEGY_ATR_PERIOD", os.getenv("STRATEGY_ATR_PERIOD"), 14)
    atr_min_strength = _parse_float("STRATEGY_ATR_MIN_STRENGTH", os.getenv("STRATEGY_ATR_MIN_STRENGTH"), 0.001)

    dmi_enabled = (_get_env_value("STRATEGY_DMI_ENABLED") or "true").lower() in ("true", "1", "yes")
    dmi_bar_spec = _get_env_value("STRATEGY_DMI_BAR_SPEC") or "2-MINUTE-MID-EXTERNAL"
    dmi_period = _parse_int("STRATEGY_DMI_PERIOD", os.getenv("STRATEGY_DMI_PERIOD"), 14)

    stoch_enabled = (_get_env_value("STRATEGY_STOCH_ENABLED") or "true").lower() in ("true", "1", "yes")
    stoch_bar_spec = _get_env_value("STRATEGY_STOCH_BAR_SPEC") or "15-MINUTE-MID-EXTERNAL"
    stoch_period_k = _parse_int("STRATEGY_STOCH_PERIOD_K", os.getenv("STRATEGY_STOCH_PERIOD_K"), 14)
    stoch_period_d = _parse_int("STRATEGY_STOCH_PERIOD_D", os.getenv("STRATEGY_STOCH_PERIOD_D"), 3)
    stoch_bullish_threshold = _parse_int("STRATEGY_STOCH_BULLISH_THRESHOLD", os.getenv("STRATEGY_STOCH_BULLISH_THRESHOLD"), 30)
    stoch_bearish_threshold = _parse_int("STRATEGY_STOCH_BEARISH_THRESHOLD", os.getenv("STRATEGY_STOCH_BEARISH_THRESHOLD"), 70)
    stoch_max_bars_since_crossing = _parse_int("STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING", os.getenv("STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING"), 18)
    
    # Time filter parameters
    time_filter_enabled = os.getenv("BACKTEST_TIME_FILTER_ENABLED", "false").lower() in ("true", "1", "yes")
    excluded_hours = _parse_excluded_hours("BACKTEST_EXCLUDED_HOURS", os.getenv("BACKTEST_EXCLUDED_HOURS"))
    excluded_hours_mode = os.getenv("BACKTEST_EXCLUDED_HOURS_MODE", "flat").lower()
    
    # Parse weekday-specific exclusions if mode is "weekday"
    excluded_hours_by_weekday = {}
    if excluded_hours_mode == "weekday":
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for weekday in weekdays:
            env_var = f"BACKTEST_EXCLUDED_HOURS_{weekday.upper()}"
            weekday_hours = _parse_excluded_hours(env_var, os.getenv(env_var))
            if weekday_hours:
                excluded_hours_by_weekday[weekday] = weekday_hours
    
    # Entry timing parameters
    entry_timing_enabled = (_get_env_value("STRATEGY_ENTRY_TIMING_ENABLED") or "false").lower() in ("true", "1", "yes")
    entry_timing_bar_spec = _get_env_value("STRATEGY_ENTRY_TIMING_BAR_SPEC") or "2-MINUTE-MID-EXTERNAL"
    entry_timing_method = _get_env_value("STRATEGY_ENTRY_TIMING_METHOD") or "pullback"
    entry_timing_timeout_bars = _parse_int("STRATEGY_ENTRY_TIMING_TIMEOUT_BARS", os.getenv("STRATEGY_ENTRY_TIMING_TIMEOUT_BARS"), 10)
    
    # Duration-based trailing stop optimization
    trailing_duration_enabled = (_get_env_value("STRATEGY_TRAILING_DURATION_ENABLED") or "false").lower() in ("true", "1", "yes")
    trailing_duration_threshold_hours = _parse_float("STRATEGY_TRAILING_DURATION_THRESHOLD_HOURS", os.getenv("STRATEGY_TRAILING_DURATION_THRESHOLD_HOURS"), 12.0)
    trailing_duration_distance_pips = _parse_int("STRATEGY_TRAILING_DURATION_DISTANCE_PIPS", os.getenv("STRATEGY_TRAILING_DURATION_DISTANCE_PIPS"), 30)
    trailing_duration_remove_tp = (_get_env_value("STRATEGY_TRAILING_DURATION_REMOVE_TP") or "true").lower() in ("true", "1", "yes")
    trailing_duration_activate_if_not_active = (_get_env_value("STRATEGY_TRAILING_DURATION_ACTIVATE_IF_NOT_ACTIVE") or "true").lower() in ("true", "1", "yes")
    
    # Minimum hold time feature (wider initial stops)
    min_hold_time_enabled = (_get_env_value("STRATEGY_MIN_HOLD_TIME_ENABLED") or "false").lower() in ("true", "1", "yes")
    min_hold_time_hours = _parse_float("STRATEGY_MIN_HOLD_TIME_HOURS", os.getenv("STRATEGY_MIN_HOLD_TIME_HOURS"), 4.0)
    min_hold_time_stop_multiplier = _parse_float("STRATEGY_MIN_HOLD_TIME_STOP_MULTIPLIER", os.getenv("STRATEGY_MIN_HOLD_TIME_STOP_MULTIPLIER"), 1.5)
    
    # Partial close on trailing activation
    partial_close_enabled = (_get_env_value("STRATEGY_PARTIAL_CLOSE_ENABLED") or "false").lower() in ("true", "1", "yes")
    partial_close_fraction = _parse_float("STRATEGY_PARTIAL_CLOSE_FRACTION", os.getenv("STRATEGY_PARTIAL_CLOSE_FRACTION"), 0.5)
    partial_close_move_sl_to_be = (_get_env_value("STRATEGY_PARTIAL_CLOSE_MOVE_SL_TO_BE") or "true").lower() in ("true", "1", "yes")
    partial_close_remainder_trail_multiplier = _parse_float("STRATEGY_PARTIAL_CLOSE_REMAINDER_TRAIL_MULTIPLIER", os.getenv("STRATEGY_PARTIAL_CLOSE_REMAINDER_TRAIL_MULTIPLIER"), 1.0)
    
    # First partial close BEFORE trailing activation
    partial1_enabled = (_get_env_value("STRATEGY_PARTIAL1_ENABLED") or "false").lower() in ("true", "1", "yes")
    partial1_fraction = _parse_float("STRATEGY_PARTIAL1_FRACTION", os.getenv("STRATEGY_PARTIAL1_FRACTION"), 0.3)
    partial1_threshold_pips = _parse_float("STRATEGY_PARTIAL1_THRESHOLD_PIPS", os.getenv("STRATEGY_PARTIAL1_THRESHOLD_PIPS"), 10.0)
    partial1_move_sl_to_be = (_get_env_value("STRATEGY_PARTIAL1_MOVE_SL_TO_BE") or "false").lower() in ("true", "1", "yes")
    
    # Market structure filter
    structure_filter_enabled = (_get_env_value("STRATEGY_STRUCTURE_FILTER_ENABLED") or "false").lower() in ("true", "1", "yes")
    structure_lookback_bars = _parse_int("STRATEGY_STRUCTURE_LOOKBACK_BARS", os.getenv("STRATEGY_STRUCTURE_LOOKBACK_BARS"), 100)
    structure_buffer_pips = _parse_float("STRATEGY_STRUCTURE_BUFFER_PIPS", os.getenv("STRATEGY_STRUCTURE_BUFFER_PIPS"), 3.0)
    structure_mode = os.getenv("STRATEGY_STRUCTURE_MODE", "avoid")
    
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
    
    if partial_close_fraction <= 0.0 or partial_close_fraction >= 1.0:
        raise ValueError("STRATEGY_PARTIAL_CLOSE_FRACTION must be between 0 and 1 (exclusive)")
    
    if partial_close_remainder_trail_multiplier <= 0.0:
        raise ValueError("STRATEGY_PARTIAL_CLOSE_REMAINDER_TRAIL_MULTIPLIER must be > 0")
    
    if partial1_fraction <= 0.0 or partial1_fraction >= 1.0:
        raise ValueError("STRATEGY_PARTIAL1_FRACTION must be between 0 and 1 (exclusive)")
    
    if partial1_threshold_pips <= 0.0:
        raise ValueError("STRATEGY_PARTIAL1_THRESHOLD_PIPS must be > 0")
    
    if structure_lookback_bars < 1:
        raise ValueError("STRATEGY_STRUCTURE_LOOKBACK_BARS must be >= 1")
    if structure_buffer_pips < 0.0:
        raise ValueError("STRATEGY_STRUCTURE_BUFFER_PIPS must be >= 0")
    
    if trailing_stop_activation_pips > take_profit_pips:
        logger = logging.getLogger(__name__)
        logger.warning("Trailing stop activation (%d pips) is greater than take profit (%d pips). Trailing may not activate before TP hit.", 
                      trailing_stop_activation_pips, take_profit_pips)

    if crossover_threshold_pips < 0:
        raise ValueError("STRATEGY_CROSSOVER_THRESHOLD_PIPS must be >= 0")

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

    catalog_path = os.getenv("CATALOG_PATH", "data/historical")
    output_dir = os.getenv("OUTPUT_DIR", "logs/backtest_results")
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
        time_multiplier_enabled=time_multiplier_enabled,
        time_tp_multiplier_eu_morning=time_tp_multiplier_eu_morning,
        time_tp_multiplier_us_session=time_tp_multiplier_us_session,
        time_tp_multiplier_other=time_tp_multiplier_other,
        time_sl_multiplier_eu_morning=time_sl_multiplier_eu_morning,
        time_sl_multiplier_us_session=time_sl_multiplier_us_session,
        time_sl_multiplier_other=time_sl_multiplier_other,
        crossover_threshold_pips=crossover_threshold_pips,
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
        time_filter_enabled=time_filter_enabled,
        excluded_hours=excluded_hours,
        excluded_hours_mode=excluded_hours_mode,
        excluded_hours_by_weekday=excluded_hours_by_weekday,
        entry_timing_enabled=entry_timing_enabled,
        entry_timing_bar_spec=entry_timing_bar_spec,
        entry_timing_method=entry_timing_method,
        entry_timing_timeout_bars=entry_timing_timeout_bars,
        trailing_duration_enabled=trailing_duration_enabled,
        trailing_duration_threshold_hours=trailing_duration_threshold_hours,
        trailing_duration_distance_pips=trailing_duration_distance_pips,
        trailing_duration_remove_tp=trailing_duration_remove_tp,
        trailing_duration_activate_if_not_active=trailing_duration_activate_if_not_active,
        min_hold_time_enabled=min_hold_time_enabled,
        min_hold_time_hours=min_hold_time_hours,
        min_hold_time_stop_multiplier=min_hold_time_stop_multiplier,
        partial_close_enabled=partial_close_enabled,
        partial_close_fraction=partial_close_fraction,
        partial_close_move_sl_to_be=partial_close_move_sl_to_be,
        partial_close_remainder_trail_multiplier=partial_close_remainder_trail_multiplier,
        partial1_enabled=partial1_enabled,
        partial1_fraction=partial1_fraction,
        partial1_threshold_pips=partial1_threshold_pips,
        partial1_move_sl_to_be=partial1_move_sl_to_be,
        structure_filter_enabled=structure_filter_enabled,
        structure_lookback_bars=structure_lookback_bars,
        structure_buffer_pips=structure_buffer_pips,
        structure_mode=structure_mode,
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
