"""
Configuration for ML Strategy with dynamic position sizing and risk management.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass
class MLStrategyConfig:
    # Core Settings
    instrument_id: str
    bar_spec: str = "5-MINUTE-MID-EXTERNAL"
    
    # Risk Management
    account_risk_per_trade: float = 0.01  # 1% account risk per trade
    max_position_size: int = 100000  # Max position size in base currency
    min_position_size: int = 1000    # Min position size in base currency
    
    # ML Model Settings
    model_confidence_threshold: float = 0.60  # Minimum probability for trade entry
    
    # Stop Loss / Take Profit
    sl_atr_mult: float = 1.5        # Stop Loss = ATR * mult
    tp_atr_mult: float = 2.0        # Take Profit = ATR * mult
    min_reward_risk: float = 1.5    # Minimum reward:risk ratio
    
    # Trailing Stop Settings
    trail_activation_atr_mult: float = 1.0  # When to start trailing
    trail_distance_atr_mult: float = 0.8    # How far to trail
    
    # Partial Close Settings
    partial_close_enabled: bool = True
    partial_close_fraction: float = 0.5
    partial_close_move_sl_to_be: bool = True
    partial_close_remainder_trail_multiplier: float = 1.3
    
    # Time Filters
    trading_session_start: str = "02:00"  # London pre-session
    trading_session_end: str = "16:00"    # NY close
    excluded_hours: list[int] = None      # Hours to avoid trading
    
    # Entry Filters
    signal_cooldown_bars: int = 3         # Bars to wait between signals
    min_atr_volatility: float = 0.0001    # Minimum ATR for entry
    
    # Logging Settings
    log_features: bool = True
    log_trade_management: bool = True
    log_position_sizing: bool = True

def get_strategy_config(
    instrument_id: str,
    risk_per_trade: Optional[float] = None,
    **overrides
) -> dict:
    """
    Create strategy configuration with optional overrides.
    
    Args:
        instrument_id: The trading instrument (e.g., "EUR/USD.IBKR")
        risk_per_trade: Override default risk per trade (as decimal)
        **overrides: Any other config parameters to override
    """
    config = MLStrategyConfig(instrument_id=instrument_id)
    
    # Apply overrides
    if risk_per_trade is not None:
        config.account_risk_per_trade = risk_per_trade
        
    for key, value in overrides.items():
        if hasattr(config, key):
            setattr(config, key, value)
        else:
            raise ValueError(f"Unknown config parameter: {key}")
            
    # Convert to dict for Nautilus
    return {
        k: v for k, v in config.__dict__.items() 
        if not k.startswith('_')
    }

def validate_config(config: dict) -> None:
    """Validate strategy configuration parameters."""
    # Risk checks
    assert 0 < config['account_risk_per_trade'] <= 0.02, "Risk per trade must be 0-2%"
    assert config['min_position_size'] <= config['max_position_size'], "Invalid position size range"
    
    # Reward:Risk checks
    assert config['tp_atr_mult'] >= config['sl_atr_mult'] * config['min_reward_risk'], \
        "Take profit must satisfy minimum reward:risk ratio"
    
    # Partial close checks
    if config['partial_close_enabled']:
        assert 0 < config['partial_close_fraction'] < 1, "Invalid partial close fraction"
        
    # Time filter checks
    if config['excluded_hours']:
        assert all(0 <= h <= 23 for h in config['excluded_hours']), "Invalid hours"
        
    return True  # All checks passed
