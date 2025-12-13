"""
Configuration loader for V2 2-Position Strategy.

Loads from .env.mtf_v2_2pos or uses defaults.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


@dataclass
class MTFV2_2PosConfig:
    """Configuration for 2-position V2 strategy."""
    
    # Instrument
    symbol: str = "EUR/USD"
    venue: str = "IDEALPRO"
    bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    
    # Model
    model_path: str = "models/ml_model_mtf.pkl"
    
    # Position sizing - 2 positions only
    total_position_size: int = 100000
    pos1_fraction: float = 0.70  # Quick win
    pos2_fraction: float = 0.30  # Extended runner with trailing
    
    # ATR multipliers
    sl_atr_mult: float = 1.4
    pos1_tp_atr_mult: float = 0.9
    pos2_tp_atr_mult: float = 1.75
    trailing_distance_atr_mult: float = 0.5
    
    # Prediction
    prediction_threshold: float = 0.55
    
    # Session
    trade_start_hour: int = 7
    trade_end_hour: int = 20
    
    # Risk
    min_atr: float = 0.0003
    max_atr: float = 0.005
    
    # IBKR connection
    ib_host: str = "127.0.0.1"
    ib_port: int = 7497
    ib_client_id: int = 22  # Different from V2 3-pos
    ib_account: str = ""
    ib_market_data_type: str = "DELAYED_FROZEN"
    
    @property
    def instrument(self) -> str:
        return f"{self.symbol}.{self.venue}"
    
    @property
    def bar_type(self) -> str:
        return f"{self.symbol.replace('/', '')}.{self.venue}-{self.bar_spec}"


def load_mtf_v2_2pos_config(env_file: Optional[str] = None) -> MTFV2_2PosConfig:
    """Load configuration from environment file."""
    
    # Determine env file path
    if env_file:
        env_path = Path(env_file)
    else:
        env_path = Path(".env.mtf_v2_2pos")
        if not env_path.exists():
            env_path = Path(".env")
    
    if env_path.exists():
        load_dotenv(env_path, override=True)
    
    config = MTFV2_2PosConfig(
        # Instrument
        symbol=os.getenv("MTF_INSTRUMENT", "EUR/USD"),
        venue=os.getenv("MTF_VENUE", "IDEALPRO"),
        bar_spec=os.getenv("MTF_BAR_SPEC", "15-MINUTE-MID-EXTERNAL"),
        
        # Model
        model_path=os.getenv("MTF_MODEL_PATH", "models/ml_model_mtf.pkl"),
        
        # Position sizing
        total_position_size=int(os.getenv("MTF_TOTAL_POSITION_SIZE", "100000")),
        pos1_fraction=float(os.getenv("MTF_POS1_FRACTION", "0.70")),
        pos2_fraction=float(os.getenv("MTF_POS2_FRACTION", "0.30")),
        
        # ATR multipliers
        sl_atr_mult=float(os.getenv("MTF_SL_ATR_MULT", "1.4")),
        pos1_tp_atr_mult=float(os.getenv("MTF_POS1_TP_ATR_MULT", "0.9")),
        pos2_tp_atr_mult=float(os.getenv("MTF_POS2_TP_ATR_MULT", "1.75")),
        trailing_distance_atr_mult=float(os.getenv("MTF_TRAILING_DISTANCE_ATR_MULT", "0.5")),
        
        # Prediction
        prediction_threshold=float(os.getenv("MTF_PREDICTION_THRESHOLD", "0.55")),
        
        # Session
        trade_start_hour=int(os.getenv("MTF_TRADE_START_HOUR", "7")),
        trade_end_hour=int(os.getenv("MTF_TRADE_END_HOUR", "20")),
        
        # Risk
        min_atr=float(os.getenv("MTF_MIN_ATR", "0.0003")),
        max_atr=float(os.getenv("MTF_MAX_ATR", "0.005")),
        
        # IBKR
        ib_host=os.getenv("IB_HOST", "127.0.0.1"),
        ib_port=int(os.getenv("IB_PORT", "7497")),
        ib_client_id=int(os.getenv("IB_CLIENT_ID", "22")),
        ib_account=os.getenv("IB_ACCOUNT", ""),
        ib_market_data_type=os.getenv("IB_MARKET_DATA_TYPE", "DELAYED_FROZEN"),
    )
    
    return config


def print_mtf_v2_2pos_config(config: MTFV2_2PosConfig):
    """Print configuration summary."""
    print("=" * 60)
    print("V2 2-POSITION STRATEGY CONFIGURATION")
    print("=" * 60)
    print(f"  Instrument: {config.instrument}")
    print(f"  Bar Type: {config.bar_type}")
    print(f"  Model: {config.model_path}")
    print("-" * 60)
    print("Position Sizing (2-Position Split):")
    print(f"  Total Size: {config.total_position_size:,}")
    print(f"  POS1 (Quick Win): {config.pos1_fraction*100:.0f}% = {int(config.total_position_size * config.pos1_fraction):,}")
    print(f"  POS2 (Runner):    {config.pos2_fraction*100:.0f}% = {int(config.total_position_size * config.pos2_fraction):,}")
    print("-" * 60)
    print("ATR Multipliers:")
    print(f"  SL: {config.sl_atr_mult}x")
    print(f"  POS1 TP: {config.pos1_tp_atr_mult}x")
    print(f"  POS2 TP: {config.pos2_tp_atr_mult}x")
    print(f"  Trailing Distance: {config.trailing_distance_atr_mult}x")
    print("-" * 60)
    print(f"  Session: {config.trade_start_hour}:00 - {config.trade_end_hour}:00 UTC")
    print(f"  Prediction Threshold: {config.prediction_threshold}")
    print("=" * 60)
