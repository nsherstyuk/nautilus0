"""
Configuration for ML Strategy.
Follows the same pattern as MovingAverageCrossoverConfig.
"""
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Optional

from nautilus_trader.config import StrategyConfig


class MLSignalStrategyConfig(StrategyConfig, kw_only=True):
    """Configuration for MLSignalStrategy."""
    
    # Core settings
    instrument_id: str
    bar_spec: str
    position_size: Decimal
    order_id_tag: str
    
    # Model settings
    model_path: str
    prediction_threshold: float
    
    # Risk management
    enforce_position_limit: bool
    max_positions: int
    
    # Stop Loss / Take Profit (ATR-based)
    sl_atr_mult: float
    tp_atr_mult: float
    
    # Trailing stop settings
    trailing_stop_enabled: bool = True  # Now enabled with correct API
    trailing_activation_atr_mult: float = 1.0  # Activate after 1.0×ATR profit
    trailing_distance_atr_mult: float = 0.6    # Trail 0.6×ATR behind price
    
    # Partial close settings (optional)
    partial_close_enabled: bool
    partial_close_fraction: float
    partial_close_move_sl_to_be: bool
    
    # Multi-layer exit settings (OPTIMIZED)
    multi_layer_enabled: bool = False
    multi_layer_count: int = 3
    multi_layer_sizes: list[float] = field(default_factory=lambda: [0.5, 0.3, 0.2])
    multi_layer_triggers: list = field(default_factory=lambda: [2.0, 3.0, "final"])
    multi_layer_move_sl_to_be: bool = True
    
    # Trading session filter
    session_start: str
    session_end: str
    excluded_hours: list[int]
    excluded_hours_by_weekday: dict[int, list[int]] = field(default_factory=dict)
    
    # Debug mode
    debug_mode: bool = False  # Bypass all filters for testing
    
    # Feature calculation
    feature_warmup_bars: int
