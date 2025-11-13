"""
Adaptive stop helper functions (ATR & percentile scaled) for use by strategies.

Provides functionality to compute ATR-based and volatility-percentile-scaled
stop-loss, take-profit, and trailing-stop levels that adapt to market conditions.

Usage (example from strategy):
    from strategies.adaptive_stops import compute_adaptive_levels
    
    cfg = {
        'mode': 'atr',
        'atr_period': 14,
        'tp_atr_mult': 2.5,
        'sl_atr_mult': 1.5,
        'trail_activation_atr_mult': 1.0,
        'trail_distance_atr_mult': 0.8,
        'volatility_window': 200,
        'volatility_sensitivity': 0.6
    }
    
    levels = compute_adaptive_levels(bars_df, current_price, cfg)
    # Returns: {'sl_distance': Decimal, 'tp_distance': Decimal, 
    #           'trail_activation': Decimal, 'trail_distance': Decimal, 
    #           'atr': Decimal, 'mode': str}
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd


def compute_atr_from_bars(bars_df: pd.DataFrame, atr_period: int = 14) -> Optional[Decimal]:
    """
    Compute Average True Range (ATR) from a DataFrame of bars.
    
    Args:
        bars_df: DataFrame with columns ['high', 'low', 'close'] (at minimum)
        atr_period: Period for ATR calculation (default: 14)
    
    Returns:
        ATR value as Decimal, or None if insufficient data
    """
    if bars_df is None or len(bars_df) < atr_period + 1:
        return None
    
    try:
        # Extract price columns
        high = bars_df['high'].values
        low = bars_df['low'].values
        close = bars_df['close'].values
        
        # Calculate True Range components
        # TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
        hl = high - low
        hc = np.abs(high - np.roll(close, 1))
        lc = np.abs(low - np.roll(close, 1))
        
        # Set first TR to high-low (no previous close)
        tr = np.maximum(hl, np.maximum(hc, lc))
        tr[0] = hl[0]
        
        # Calculate ATR using exponential moving average
        # ATR = EMA(TR, period)
        atr_values = pd.Series(tr).ewm(span=atr_period, adjust=False).mean()
        
        # Return the most recent ATR value
        current_atr = float(atr_values.iloc[-1])
        return Decimal(str(current_atr))
        
    except (KeyError, IndexError, ValueError) as e:
        # Handle missing columns or calculation errors
        return None


def compute_volatility_percentile(bars_df: pd.DataFrame, atr: Decimal, 
                                   window: int = 200, atr_period: int = 14) -> Optional[float]:
    """
    Compute percentile ranking of current ATR within a historical window.
    
    Args:
        bars_df: DataFrame with OHLC data
        atr: Current ATR value
        window: Lookback window for percentile calculation (default: 200)
        atr_period: Period used for ATR calculation
    
    Returns:
        Percentile (0-100) or None if insufficient data
    """
    if bars_df is None or len(bars_df) < window + atr_period:
        return None
    
    try:
        # Calculate ATR for the entire window
        high = bars_df['high'].values
        low = bars_df['low'].values
        close = bars_df['close'].values
        
        hl = high - low
        hc = np.abs(high - np.roll(close, 1))
        lc = np.abs(low - np.roll(close, 1))
        
        tr = np.maximum(hl, np.maximum(hc, lc))
        tr[0] = hl[0]
        
        # Calculate rolling ATR
        atr_series = pd.Series(tr).ewm(span=atr_period, adjust=False).mean()
        
        # Get ATR values for the window
        atr_window = atr_series.iloc[-window:].values
        
        # Calculate percentile of current ATR
        current_atr_float = float(atr)
        percentile = (atr_window < current_atr_float).sum() / len(atr_window) * 100.0
        
        return percentile
        
    except (KeyError, IndexError, ValueError, ZeroDivisionError):
        return None


def compute_volatility_scale(percentile: Optional[float], sensitivity: float = 0.6) -> float:
    """
    Compute volatility scaling factor from percentile ranking.
    
    Higher percentiles (high volatility regime) increase the scale,
    lower percentiles (low volatility regime) decrease it.
    
    Args:
        percentile: ATR percentile (0-100)
        sensitivity: How much to scale (0=no scaling, 1=full scaling). Default: 0.6
    
    Returns:
        Scaling factor (typically 0.5 to 1.5)
    """
    if percentile is None:
        return 1.0  # No scaling if percentile unavailable
    
    # Normalize percentile to -0.5 to +0.5 range (50th percentile = 0)
    normalized = (percentile - 50.0) / 100.0
    
    # Apply sensitivity and compute scale
    # scale = 1.0 + (normalized * sensitivity)
    # When percentile = 100: scale = 1.0 + 0.5 * sensitivity
    # When percentile = 50: scale = 1.0
    # When percentile = 0: scale = 1.0 - 0.5 * sensitivity
    scale = 1.0 + (normalized * sensitivity)
    
    # Clamp to reasonable range (0.5x to 2.0x)
    scale = max(0.5, min(2.0, scale))
    
    return scale


def compute_adaptive_levels(
    bars_df: pd.DataFrame,
    current_price: Decimal,
    config: Dict[str, Any],
    fallback_pips: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Compute adaptive SL/TP/trailing levels based on ATR and volatility regime.
    
    Args:
        bars_df: DataFrame with OHLC data (columns: 'high', 'low', 'close')
        current_price: Current market price (for pip calculations if needed)
        config: Configuration dict with keys:
            - mode: 'fixed'|'atr'|'percentile'
            - atr_period: ATR calculation period (default: 14)
            - tp_atr_mult: Take-profit ATR multiplier (default: 2.5)
            - sl_atr_mult: Stop-loss ATR multiplier (default: 1.5)
            - trail_activation_atr_mult: Trailing activation multiplier (default: 1.0)
            - trail_distance_atr_mult: Trailing distance multiplier (default: 0.8)
            - volatility_window: Percentile calculation window (default: 200)
            - volatility_sensitivity: Scaling sensitivity (default: 0.6)
            - min_distance_pips: Minimum distance in pips (optional)
        fallback_pips: Dict with 'sl', 'tp', 'trail_activation', 'trail_distance' 
                       in pips (used if ATR calculation fails or mode='fixed')
    
    Returns:
        Dict with keys:
            - sl_distance: Stop-loss distance in price units (Decimal)
            - tp_distance: Take-profit distance in price units (Decimal)
            - trail_activation: Trailing stop activation distance (Decimal)
            - trail_distance: Trailing stop distance (Decimal)
            - atr: ATR value (Decimal or None)
            - volatility_percentile: Percentile (float or None)
            - volatility_scale: Scale factor (float)
            - mode: Actual mode used ('fixed'|'atr'|'percentile')
    """
    # Extract config values with defaults
    mode = config.get('mode', 'atr')
    atr_period = config.get('atr_period', 14)
    tp_atr_mult = config.get('tp_atr_mult', 2.5)
    sl_atr_mult = config.get('sl_atr_mult', 1.5)
    trail_activation_mult = config.get('trail_activation_atr_mult', 1.0)
    trail_distance_mult = config.get('trail_distance_atr_mult', 0.8)
    volatility_window = config.get('volatility_window', 200)
    volatility_sensitivity = config.get('volatility_sensitivity', 0.6)
    min_distance_pips = config.get('min_distance_pips', None)
    
    # Default result structure
    result = {
        'sl_distance': None,
        'tp_distance': None,
        'trail_activation': None,
        'trail_distance': None,
        'atr': None,
        'volatility_percentile': None,
        'volatility_scale': 1.0,
        'mode': 'fixed'  # Will be updated if adaptive mode succeeds
    }
    
    # Handle fixed mode explicitly
    if mode == 'fixed':
        if fallback_pips is not None:
            # Use pip-based fallback values (assuming 1 pip = 0.0001 for FX)
            # Caller should convert pips to price units based on instrument
            result['sl_distance'] = Decimal(str(fallback_pips.get('sl', 25)))
            result['tp_distance'] = Decimal(str(fallback_pips.get('tp', 50)))
            result['trail_activation'] = Decimal(str(fallback_pips.get('trail_activation', 20)))
            result['trail_distance'] = Decimal(str(fallback_pips.get('trail_distance', 15)))
        result['mode'] = 'fixed'
        return result
    
    # Compute ATR
    atr = compute_atr_from_bars(bars_df, atr_period)
    if atr is None:
        # ATR calculation failed - use fixed fallback
        if fallback_pips is not None:
            result['sl_distance'] = Decimal(str(fallback_pips.get('sl', 25)))
            result['tp_distance'] = Decimal(str(fallback_pips.get('tp', 50)))
            result['trail_activation'] = Decimal(str(fallback_pips.get('trail_activation', 20)))
            result['trail_distance'] = Decimal(str(fallback_pips.get('trail_distance', 15)))
        result['mode'] = 'fixed'
        return result
    
    result['atr'] = atr
    
    # Compute volatility scaling if percentile mode
    volatility_scale = 1.0
    if mode == 'percentile':
        percentile = compute_volatility_percentile(bars_df, atr, volatility_window, atr_period)
        result['volatility_percentile'] = percentile
        volatility_scale = compute_volatility_scale(percentile, volatility_sensitivity)
        result['volatility_scale'] = volatility_scale
    
    # Calculate adaptive distances in price units
    # Distances are ATR * multiplier * volatility_scale
    sl_distance = atr * Decimal(str(sl_atr_mult)) * Decimal(str(volatility_scale))
    tp_distance = atr * Decimal(str(tp_atr_mult)) * Decimal(str(volatility_scale))
    trail_activation = atr * Decimal(str(trail_activation_mult)) * Decimal(str(volatility_scale))
    trail_distance = atr * Decimal(str(trail_distance_mult)) * Decimal(str(volatility_scale))
    
    # Apply minimum distance constraint if specified
    if min_distance_pips is not None:
        # Assume 1 pip = 0.0001 for FX (caller should adjust for other instruments)
        min_distance = Decimal(str(min_distance_pips)) * Decimal('0.0001')
        sl_distance = max(sl_distance, min_distance)
        tp_distance = max(tp_distance, min_distance)
        trail_activation = max(trail_activation, min_distance)
        trail_distance = max(trail_distance, min_distance)
    
    result['sl_distance'] = sl_distance
    result['tp_distance'] = tp_distance
    result['trail_activation'] = trail_activation
    result['trail_distance'] = trail_distance
    result['mode'] = mode
    
    return result


def get_bars_dataframe(bars_list: list, lookback: int = 300) -> Optional[pd.DataFrame]:
    """
    Convert a list of Bar objects to a pandas DataFrame for ATR calculation.
    
    Args:
        bars_list: List of nautilus Bar objects
        lookback: Number of bars to include (most recent)
    
    Returns:
        DataFrame with columns ['high', 'low', 'close'] or None
    """
    if not bars_list or len(bars_list) == 0:
        return None
    
    try:
        # Take most recent bars
        recent_bars = bars_list[-lookback:] if len(bars_list) > lookback else bars_list
        
        # Extract OHLC data
        data = {
            'high': [float(bar.high) for bar in recent_bars],
            'low': [float(bar.low) for bar in recent_bars],
            'close': [float(bar.close) for bar in recent_bars],
        }
        
        return pd.DataFrame(data)
        
    except (AttributeError, ValueError, TypeError):
        return None
