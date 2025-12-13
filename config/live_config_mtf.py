"""Live configuration for MTF ML Strategy."""
from dataclasses import dataclass
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass
class LiveConfigMTF:
    """Configuration for MTF ML live trading."""
    
    # Core settings
    trader_id: str = "TRADER-MTF-001"
    symbol: str = "EUR/USD"
    venue: str = "IDEALPRO"
    bar_spec: str = "15-MINUTE-MID-EXTERNAL"  # Fixed for MTF
    
    # Position sizing
    position_size: int = 100000
    enforce_position_limit: bool = True
    max_positions: int = 1
    
    # ML Model
    model_path: str = "models/ml_model_mtf.pkl"
    prediction_threshold: float = 0.55  # Optimized
    feature_warmup_bars: int = 100
    
    # Risk Management (ATR-based)
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5
    
    # Trailing Stop
    trailing_stop_enabled: bool = True
    trailing_activation_atr_mult: float = 1.0
    trailing_distance_atr_mult: float = 0.8
    
    # Partial Close (OPTIMIZED)
    partial_close_enabled: bool = True
    partial_close_fraction: float = 0.5
    partial_close_atr_mult: float = 1.5
    partial_close_move_sl_to_be: bool = True
    
    # Trading Session
    session_start: str = "02:00"
    session_end: str = "16:00"
    excluded_hours: list = None  # Will be set to empty list if None
    
    # Logging
    log_dir: str = "logs/live_mtf"
    
    # Order ID tag
    order_id_tag: str = "MTF_ML"

def get_live_config_mtf() -> LiveConfigMTF:
    """Get MTF live configuration from environment or defaults."""
    config = LiveConfigMTF()
    
    # Override from environment if available
    if os.getenv("MTF_SYMBOL"):
        config.symbol = os.getenv("MTF_SYMBOL")
    if os.getenv("MTF_POSITION_SIZE"):
        config.position_size = int(os.getenv("MTF_POSITION_SIZE"))
    if os.getenv("MTF_MODEL_PATH"):
        config.model_path = os.getenv("MTF_MODEL_PATH")
    if os.getenv("MTF_LOG_DIR"):
        config.log_dir = os.getenv("MTF_LOG_DIR")
    
    return config

def validate_live_config_mtf(config: LiveConfigMTF) -> bool:
    """Validate MTF live configuration."""
    from pathlib import Path
    
    # Check model file exists
    model_path = Path(config.model_path)
    if not model_path.exists():
        print(f"ERROR: Model file not found: {model_path}")
        return False
    
    # Validate position size
    if config.position_size < 1000:
        print(f"ERROR: Position size too small: {config.position_size}")
        return False
    
    # Validate thresholds
    if not (0 < config.prediction_threshold < 1):
        print(f"ERROR: Invalid prediction threshold: {config.prediction_threshold}")
        return False
    
    return True
