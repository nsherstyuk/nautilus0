"""
MTF V4 Configuration with Dynamic SL/TP Parameters

This module extends MTF V2 with dynamic stop loss and take profit
based on trading hours and weekdays analysis.
"""

import os
from dataclasses import dataclass
from typing import Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@dataclass
class MTFV4Config:
    """MTF V4 Configuration with dynamic parameters."""
    
    # Base configuration (inherited from V2)
    stall_detection_enabled: bool
    stall_check_bars: int
    stall_min_profit_atr: float
    stall_sl_atr: float
    
    # Meta filters
    meta_filter_mama_enabled: bool
    meta_filter_mama_min_diff: float
    meta_filter_dmi_enabled: bool
    meta_filter_dmi_min_dmp: float
    
    # Time settings
    excluded_hours_monday: list
    excluded_hours_tuesday: list
    excluded_hours_wednesday: list
    excluded_hours_thursday: list
    excluded_hours_friday: list
    excluded_hours_saturday: list
    excluded_hours_sunday: list
    config_timezone: str
    
    # ATR limits
    min_atr: float
    max_atr: float
    
    # Risk management
    max_positions: int
    enforce_position_limit: bool
    
    # Backtest settings
    backtest_start: str
    backtest_end: str
    initial_balance: float
    
    # V4 Dynamic Parameters
    dynamic_sl_enabled: bool = True
    dynamic_tp_enabled: bool = True
    weekday_adjustment_enabled: bool = True
    
    # Default values (used when no specific rule applies)
    default_sl_atr_mult: float = 1.2
    default_pos1_tp_atr_mult: float = 0.6
    default_pos2_tp_atr_mult: float = 2.0
    default_trailing_distance_atr_mult: float = 0.4

def load_dynamic_parameters() -> Dict:
    """Load dynamic SL/TP parameters based on backtest analysis."""
    
    # Hour-based dynamic SL multipliers
    dynamic_sl_by_hour = {
        # High fade hours - need more room
        20: 1.6, 21: 1.6, 22: 1.4,  # Evening (8PM-10PM)
        17: 1.6, 18: 1.4, 19: 1.6,  # Late afternoon (5PM-7PM)
        10: 1.4, 16: 1.4,           # Mid-day peaks
        
        # Low fade hours - can tighten
        0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0, 6: 1.0, 7: 1.0,
        11: 1.0, 12: 1.0, 13: 1.0, 14: 1.0, 15: 1.0,
        
        # Standard hours
        8: 1.2, 9: 1.2, 23: 1.2
    }
    
    # Hour-based dynamic TP multipliers
    dynamic_tp_by_hour = {
        # High performance hours - can increase TP
        16: 0.8,  # 4PM - Best performance
        15: 0.8,  # 3PM - High profit factor
        17: 0.7,  # 5PM - High win rate
        10: 0.7, 19: 0.7,  # Good performance
        
        # Poor performance hours - reduce TP
        14: 0.5, 6: 0.5,  # Low win rate
        
        # Standard hours
        0: 0.6, 1: 0.6, 2: 0.6, 3: 0.6, 4: 0.6, 5: 0.6, 7: 0.6,
        8: 0.6, 9: 0.6, 11: 0.6, 12: 0.6, 13: 0.6, 18: 0.6,
        20: 0.6, 21: 0.6, 22: 0.6, 23: 0.6
    }
    
    # Weekday performance multipliers
    weekday_multipliers = {
        'Monday': 1.0,
        'Tuesday': 0.95,    # Slightly reduce
        'Wednesday': 1.05,  # Slightly increase
        'Thursday': 1.0,
        'Friday': 1.1,      # Increase - best performance
        'Saturday': 1.0,
        'Sunday': 1.05      # Increase
    }
    
    return {
        'sl_by_hour': dynamic_sl_by_hour,
        'tp_by_hour': dynamic_tp_by_hour,
        'weekday_multipliers': weekday_multipliers
    }

def get_dynamic_sl_tp(current_time: datetime, config: MTFV4Config) -> Dict[str, float]:
    """Get dynamic SL and TP values based on current time."""
    
    if not config.dynamic_sl_enabled and not config.dynamic_tp_enabled:
        return {
            'sl_atr_mult': config.default_sl_atr_mult,
            'pos1_tp_atr_mult': config.default_pos1_tp_atr_mult,
            'pos2_tp_atr_mult': config.default_pos2_tp_atr_mult,
            'trailing_distance_atr_mult': config.default_trailing_distance_atr_mult
        }
    
    # Load dynamic parameters
    dynamic_params = load_dynamic_parameters()
    
    # Get current hour and weekday
    hour = current_time.hour
    weekday = current_time.strftime('%A')
    
    # Get base values
    sl_mult = config.default_sl_atr_mult
    tp1_mult = config.default_pos1_tp_atr_mult
    tp2_mult = config.default_pos2_tp_atr_mult
    
    # Apply hour-based adjustments
    if config.dynamic_sl_enabled and hour in dynamic_params['sl_by_hour']:
        sl_mult = dynamic_params['sl_by_hour'][hour]
    
    if config.dynamic_tp_enabled and hour in dynamic_params['tp_by_hour']:
        tp1_mult = dynamic_params['tp_by_hour'][hour]
        # Keep pos2 TP as standard ratio of pos1
        tp2_mult = tp1_mult * (config.default_pos2_tp_atr_mult / config.default_pos1_tp_atr_mult)
    
    # Apply weekday adjustments
    if config.weekday_adjustment_enabled and weekday in dynamic_params['weekday_multipliers']:
        weekday_mult = dynamic_params['weekday_multipliers'][weekday]
        sl_mult *= weekday_mult
        tp1_mult *= weekday_mult
        tp2_mult *= weekday_mult
    
    # Ensure minimum values
    sl_mult = max(sl_mult, 0.8)  # Minimum 0.8x SL
    tp1_mult = max(tp1_mult, 0.4)  # Minimum 0.4x TP
    
    return {
        'sl_atr_mult': round(sl_mult, 2),
        'pos1_tp_atr_mult': round(tp1_mult, 2),
        'pos2_tp_atr_mult': round(tp2_mult, 2),
        'trailing_distance_atr_mult': round(sl_mult * 0.33, 2)  # 33% of SL
    }

def load_mtf_v4_config() -> MTFV4Config:
    """Load MTF V4 configuration from environment variables."""
    
    # Load base configuration (similar to V2)
    return MTFV4Config(
        # Stall detection
        stall_detection_enabled=os.getenv("MTF4_STALL_DETECTION_ENABLED", "true").lower() == "true",
        stall_check_bars=int(os.getenv("MTF4_STALL_CHECK_BARS", "2")),
        stall_min_profit_atr=float(os.getenv("MTF4_STALL_MIN_PROFIT_ATR", "0.3")),
        stall_sl_atr=float(os.getenv("MTF4_STALL_SL_ATR", "0.05")),
        
        # Meta filters
        meta_filter_mama_enabled=os.getenv("MTF4_META_FILTER_MAMA_ENABLED", "true").lower() == "true",
        meta_filter_mama_min_diff=float(os.getenv("MTF4_META_FILTER_MAMA_MIN_DIFF", "0.02")),
        meta_filter_dmi_enabled=os.getenv("MTF4_META_FILTER_DMI_ENABLED", "true").lower() == "true",
        meta_filter_dmi_min_dmp=float(os.getenv("MTF4_META_FILTER_DMI_MIN_DMP", "25")),
        
        # Time settings
        excluded_hours_monday=_parse_hours(os.getenv("MTF4_EXCLUDED_HOURS_MONDAY", "")),
        excluded_hours_tuesday=_parse_hours(os.getenv("MTF4_EXCLUDED_HOURS_TUESDAY", "")),
        excluded_hours_wednesday=_parse_hours(os.getenv("MTF4_EXCLUDED_HOURS_WEDNESDAY", "")),
        excluded_hours_thursday=_parse_hours(os.getenv("MTF4_EXCLUDED_HOURS_THURSDAY", "")),
        excluded_hours_friday=_parse_hours(os.getenv("MTF4_EXCLUDED_HOURS_FRIDAY", "")),
        excluded_hours_saturday=_parse_hours(os.getenv("MTF4_EXCLUDED_HOURS_SATURDAY", "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23")),
        excluded_hours_sunday=_parse_hours(os.getenv("MTF4_EXCLUDED_HOURS_SUNDAY", "")),
        config_timezone=os.getenv("MTF4_CONFIG_TIMEZONE", "EST"),
        
        # ATR limits
        min_atr=float(os.getenv("MTF4_MIN_ATR", "0.0005")),
        max_atr=float(os.getenv("MTF4_MAX_ATR", "0.05")),
        
        # Risk management
        max_positions=int(os.getenv("MTF4_MAX_POSITIONS", "1")),
        enforce_position_limit=os.getenv("MTF4_ENFORCE_POSITION_LIMIT", "true").lower() == "true",
        
        # Backtest settings
        backtest_start=os.getenv("MTF4_BACKTEST_START", "2025-01-01"),
        backtest_end=os.getenv("MTF4_BACKTEST_END", "2025-12-31"),
        initial_balance=float(os.getenv("MTF4_INITIAL_BALANCE", "50000")),
        
        # V4 specific settings
        dynamic_sl_enabled=os.getenv("MTF4_DYNAMIC_SL_ENABLED", "true").lower() == "true",
        dynamic_tp_enabled=os.getenv("MTF4_DYNAMIC_TP_ENABLED", "true").lower() == "true",
        weekday_adjustment_enabled=os.getenv("MTF4_WEEKDAY_ADJUSTMENT_ENABLED", "true").lower() == "true",
        
        # Default values
        default_sl_atr_mult=float(os.getenv("MTF4_SL_ATR_MULT", "1.2")),
        default_pos1_tp_atr_mult=float(os.getenv("MTF4_POS1_TP_ATR_MULT", "0.6")),
        default_pos2_tp_atr_mult=float(os.getenv("MTF4_POS2_TP_ATR_MULT", "2.0")),
        default_trailing_distance_atr_mult=float(os.getenv("MTF4_TRAILING_DISTANCE_ATR_MULT", "0.4"))
    )

def _parse_hours(hours_str: str) -> list:
    """Parse comma-separated hours string into list."""
    if not hours_str.strip():
        return []
    return [int(h.strip()) for h in hours_str.split(',') if h.strip().isdigit()]

# Export main functions
__all__ = [
    'MTFV4Config',
    'load_mtf_v4_config', 
    'load_dynamic_parameters',
    'get_dynamic_sl_tp'
]
