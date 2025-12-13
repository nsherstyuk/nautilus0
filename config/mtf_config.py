"""
MTF ML Strategy Configuration Loader.
Loads configuration from .env.mtf file (separate from old strategy).
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os

# Load MTF-specific environment file
from dotenv import load_dotenv

# Load .env.mtf instead of .env
env_path = Path(__file__).parent.parent / ".env.mtf"
load_dotenv(env_path)

@dataclass
class MTFConfig:
    """MTF ML Strategy Configuration."""
    
    # IBKR Connection
    ib_host: str = "127.0.0.1"
    ib_port: int = 7497
    ib_client_id: int = 19
    ib_account: str = "DU1558484"
    ib_market_data_type: str = "REALTIME"
    
    # Backtest
    backtest_start_date: str = "2025-01-01"
    backtest_end_date: str = "2025-12-31"
    backtest_symbol: str = "EUR/USD"
    backtest_venue: str = "IDEALPRO"
    backtest_bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    
    # Live Trading (use same symbol/venue as backtest)
    symbol: str = "EUR/USD"
    venue: str = "IDEALPRO"
    bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    trader_id: str = "TRADER-MTF-001"
    order_id_tag: str = "MTF-ML"
    
    # Strategy Parameters
    model_path: str = "models/ml_model_mtf.pkl"
    prediction_threshold: float = 0.55
    feature_warmup_bars: int = 100
    
    # Position Sizing
    position_size: int = 100000
    max_positions: int = 1
    enforce_position_limit: bool = True
    
    # Risk Management
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5
    
    # Trailing Stop
    trailing_stop_enabled: bool = True
    trailing_activation_atr_mult: float = 1.0
    trailing_distance_atr_mult: float = 0.8
    
    # Partial Close
    partial_close_enabled: bool = True
    partial_close_fraction: float = 0.5
    partial_close_atr_mult: float = 1.5
    partial_close_move_sl_to_be: bool = True
    partial_close_at_atr_mult: float = 1.5  # Alias for compatibility
    
    # Multi-Layer Exits (Experimental)
    multi_layer_enabled: bool = False
    multi_layer_count: int = 3
    multi_layer_sizes: list = None  # e.g., [0.5, 0.3, 0.2]
    multi_layer_triggers: list = None  # e.g., [2.5, 0.0, 'final']
    multi_layer_move_sl_to_be: bool = True
    
    # Trading Session
    session_start: str = "02:00"
    session_end: str = "16:00"
    excluded_hours: list = None  # Legacy: global exclusions
    excluded_hours_by_weekday: dict = None  # Weekday-specific exclusions
    
    # Filters
    debug_mode: bool = False  # Bypass all filters for testing
    min_atr: float = 0.0003
    max_atr: float = 0.0008
    cooldown_minutes: int = 30
    
    # Logging
    log_dir: str = "logs/live_mtf"
    log_level: str = "INFO"
    
    # Output
    backtest_output_dir: str = "logs/backtest_results"

def load_mtf_config() -> MTFConfig:
    """Load MTF configuration from .env.mtf file."""
    config = MTFConfig()
    
    # IBKR Connection
    config.ib_host = os.getenv("MTF_IB_HOST", config.ib_host)
    config.ib_port = int(os.getenv("MTF_IB_PORT", config.ib_port))
    config.ib_client_id = int(os.getenv("MTF_IB_CLIENT_ID", config.ib_client_id))
    config.ib_account = os.getenv("MTF_IB_ACCOUNT", config.ib_account)
    config.ib_market_data_type = os.getenv("MTF_IB_MARKET_DATA_TYPE", config.ib_market_data_type)
    
    # Backtest
    config.backtest_start_date = os.getenv("MTF_BACKTEST_START_DATE", config.backtest_start_date)
    config.backtest_end_date = os.getenv("MTF_BACKTEST_END_DATE", config.backtest_end_date)
    config.backtest_symbol = os.getenv("MTF_BACKTEST_SYMBOL", config.backtest_symbol)
    config.backtest_venue = os.getenv("MTF_BACKTEST_VENUE", config.backtest_venue)
    config.backtest_bar_spec = os.getenv("MTF_BACKTEST_BAR_SPEC", config.backtest_bar_spec)
    
    # Live Trading - use backtest bar spec unless overridden
    config.symbol = os.getenv("MTF_SYMBOL", config.backtest_symbol)
    config.venue = os.getenv("MTF_VENUE", config.backtest_venue)
    config.bar_spec = os.getenv("MTF_BAR_SPEC", config.backtest_bar_spec)  # Default to backtest spec
    
    # Strategy Parameters
    config.model_path = os.getenv("MTF_MODEL_PATH", config.model_path)
    config.prediction_threshold = float(os.getenv("MTF_PREDICTION_THRESHOLD", config.prediction_threshold))
    config.feature_warmup_bars = int(os.getenv("MTF_FEATURE_WARMUP_BARS", config.feature_warmup_bars))
    
    # Position Sizing
    config.position_size = int(os.getenv("MTF_POSITION_SIZE", config.position_size))
    config.max_positions = int(os.getenv("MTF_MAX_POSITIONS", config.max_positions))
    
    # Risk Management
    config.sl_atr_mult = float(os.getenv("MTF_SL_ATR_MULT", config.sl_atr_mult))
    config.tp_atr_mult = float(os.getenv("MTF_TP_ATR_MULT", config.tp_atr_mult))
    
    # Trailing Stop
    config.trailing_stop_enabled = os.getenv("MTF_TRAILING_STOP_ENABLED", "true").lower() == "true"
    config.trailing_activation_atr_mult = float(os.getenv("MTF_TRAILING_ACTIVATION_ATR_MULT", config.trailing_activation_atr_mult))
    config.trailing_distance_atr_mult = float(os.getenv("MTF_TRAILING_DISTANCE_ATR_MULT", config.trailing_distance_atr_mult))
    
    # Partial Close
    config.partial_close_enabled = os.getenv("MTF_PARTIAL_CLOSE_ENABLED", "true").lower() == "true"
    config.partial_close_fraction = float(os.getenv("MTF_PARTIAL_CLOSE_FRACTION", config.partial_close_fraction))
    config.partial_close_atr_mult = float(os.getenv("MTF_PARTIAL_CLOSE_ATR_MULT", config.partial_close_atr_mult))
    config.partial_close_move_sl_to_be = os.getenv("MTF_PARTIAL_CLOSE_MOVE_SL_TO_BE", "true").lower() == "true"
    
    # Trading Session
    config.session_start = os.getenv("MTF_SESSION_START", config.session_start)
    config.session_end = os.getenv("MTF_SESSION_END", config.session_end)
    
    # Parse weekday-specific excluded hours
    # Map weekday names to numbers: Monday=0, Tuesday=1, ..., Sunday=6
    weekday_names = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY']
    excluded_by_weekday = {}
    
    for weekday_num, day in enumerate(weekday_names):
        env_var = f"MTF_EXCLUDED_HOURS_{day}"
        hours_str = os.getenv(env_var, "")
        if hours_str and hours_str.strip():
            excluded_by_weekday[weekday_num] = [int(h.strip()) for h in hours_str.split(",")]
        else:
            excluded_by_weekday[weekday_num] = []
    
    config.excluded_hours_by_weekday = excluded_by_weekday
    
    # Parse legacy global excluded hours (fallback)
    excluded_hours_str = os.getenv("MTF_EXCLUDED_HOURS", "")
    if excluded_hours_str and excluded_hours_str.strip():
        config.excluded_hours = [int(h.strip()) for h in excluded_hours_str.split(",")]
    else:
        config.excluded_hours = []
    
    # Filters
    config.debug_mode = os.getenv("MTF_DEBUG_MODE", "false").lower() == "true"
    config.min_atr = float(os.getenv("MTF_MIN_ATR", config.min_atr))
    config.max_atr = float(os.getenv("MTF_MAX_ATR", config.max_atr))
    config.cooldown_minutes = int(os.getenv("MTF_COOLDOWN_MINUTES", config.cooldown_minutes))
    
    # Logging
    config.log_dir = os.getenv("MTF_LOG_DIR", config.log_dir)
    config.log_level = os.getenv("MTF_LOG_LEVEL", config.log_level)
    
    # Output
    config.backtest_output_dir = os.getenv("MTF_BACKTEST_OUTPUT_DIR", config.backtest_output_dir)
    
    # Multi-Layer Exits (Experimental)
    config.multi_layer_enabled = os.getenv("MTF_MULTI_LAYER_ENABLED", "false").lower() == "true"
    config.multi_layer_count = int(os.getenv("MTF_MULTI_LAYER_COUNT", config.multi_layer_count))
    
    # Parse multi-layer sizes
    sizes_str = os.getenv("MTF_MULTI_LAYER_SIZES", "")
    if sizes_str and sizes_str.strip():
        config.multi_layer_sizes = [float(s.strip()) for s in sizes_str.split(",")]
    else:
        config.multi_layer_sizes = [0.5, 0.3, 0.2]  # Default
    
    # Parse multi-layer triggers
    triggers_str = os.getenv("MTF_MULTI_LAYER_TRIGGERS", "")
    if triggers_str and triggers_str.strip():
        triggers = []
        for t in triggers_str.split(","):
            t = t.strip()
            if t.lower() == "final":
                triggers.append("final")
            else:
                triggers.append(float(t))
        config.multi_layer_triggers = triggers
    else:
        config.multi_layer_triggers = [2.5, 0.0, "final"]  # Default
    
    config.multi_layer_move_sl_to_be = os.getenv("MTF_MULTI_LAYER_MOVE_SL_TO_BE", "true").lower() == "true"
    
    return config

def validate_mtf_config(config: MTFConfig) -> bool:
    """Validate MTF configuration."""
    errors = []
    
    # Check model file exists
    model_path = Path(config.model_path)
    if not model_path.exists():
        errors.append(f"Model file not found: {model_path}")
    
    # Validate thresholds
    if not (0 < config.prediction_threshold < 1):
        errors.append(f"Invalid prediction threshold: {config.prediction_threshold}")
    
    # Validate position size
    if config.position_size < 1000:
        errors.append(f"Position size too small: {config.position_size}")
    
    # Validate ATR multipliers
    if config.sl_atr_mult <= 0:
        errors.append(f"Invalid SL ATR multiplier: {config.sl_atr_mult}")
    if config.tp_atr_mult <= 0:
        errors.append(f"Invalid TP ATR multiplier: {config.tp_atr_mult}")
    
    # Validate dates
    try:
        from datetime import datetime
        datetime.strptime(config.backtest_start_date, "%Y-%m-%d")
        datetime.strptime(config.backtest_end_date, "%Y-%m-%d")
    except ValueError as e:
        errors.append(f"Invalid date format: {e}")
    
    if errors:
        print("❌ Configuration validation failed:")
        for error in errors:
            print(f"   - {error}")
        return False
    
    return True

def print_mtf_config(config: MTFConfig):
    """Print MTF configuration for review."""
    print("\n" + "="*80)
    print("MTF ML STRATEGY CONFIGURATION")
    print("="*80)
    
    print("\nIBKR Connection:")
    print(f"   Host: {config.ib_host}:{config.ib_port}")
    print(f"   Client ID: {config.ib_client_id}")
    print(f"   Account: {config.ib_account}")
    
    print("\nBacktest:")
    print(f"   Period: {config.backtest_start_date} to {config.backtest_end_date}")
    print(f"   Symbol: {config.backtest_symbol}")
    print(f"   Bar Spec: {config.backtest_bar_spec}")
    
    print("\nStrategy:")
    print(f"   Model: {config.model_path}")
    print(f"   Confidence: {config.prediction_threshold}")
    print(f"   Position Size: ${config.position_size:,}")
    
    print("\nRisk Management:")
    print(f"   SL: {config.sl_atr_mult}xATR, TP: {config.tp_atr_mult}xATR")
    print(f"   Trailing: {config.trailing_stop_enabled}")
    print(f"   Partial Close: {config.partial_close_enabled} ({config.partial_close_fraction*100:.0f}% @ {config.partial_close_atr_mult}xATR)")
    
    print("\nTrading Session:")
    print(f"   Hours: {config.session_start} - {config.session_end} UTC")
    
    # Show weekday-specific exclusions
    if config.excluded_hours_by_weekday:
        has_exclusions = any(hours for hours in config.excluded_hours_by_weekday.values())
        if has_exclusions:
            print(f"   Weekday-specific exclusions:")
            weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            for weekday_num, day_name in enumerate(weekday_names):
                hours = config.excluded_hours_by_weekday.get(weekday_num, [])
                if hours:
                    print(f"     {day_name}: {hours}")
        else:
            print(f"   Excluded: None (trade all hours)")
    elif config.excluded_hours:
        print(f"   Excluded (all days): {config.excluded_hours}")
    else:
        print(f"   Excluded: None (trade all hours)")
    
    print("\nFilters:")
    print(f"   Min ATR: {config.min_atr}")
    print(f"   Cooldown: {config.cooldown_minutes} minutes")
    
    print("\n" + "="*80)

# Example usage
if __name__ == "__main__":
    config = load_mtf_config()
    print_mtf_config(config)
    
    if validate_mtf_config(config):
        print("\n✅ Configuration is valid!")
    else:
        print("\n❌ Configuration has errors!")
