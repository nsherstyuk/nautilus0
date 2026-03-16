from dataclasses import dataclass
from typing import List

@dataclass(frozen=True)
class StrategyConfig:
    """Pure strategy parameters. 
    This config is environment-agnostic. It does not contain file paths, API keys, or broker settings.
    """
    instrument: str
    
    # Time Windows (in UTC)
    range_start_hour: int
    range_end_hour: int
    trade_start_hour: int
    trade_end_hour: int
    
    # Days to avoid trading (0 = Monday, 6 = Sunday)
    skip_weekdays: List[int]
    
    # Velocity Filter
    velocity_filter_enabled: bool
    velocity_lookback_minutes: int
    velocity_threshold: float  # minimum ticks/min required
    
    # Trade Management
    rr_ratio: float
    
    # Range validity
    min_range_size: float
    max_range_size: float
