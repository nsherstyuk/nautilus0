"""
MLSignalStrategy V4 - Dynamic SL/TP Based on Trading Hours

V4 builds on V2's three-position bracket approach but adds:
- Dynamic stop loss multipliers based on trading hour analysis
- Dynamic take profit multipliers for high-performance hours
- Weekday performance adjustments
- Separate configuration from V2 (no impact on live trading)

Dynamic Parameters:
- SL: 1.0x (low fade hours) to 1.6x (high fade hours) ATR
- TP: 0.5x (poor performance) to 0.8x (high performance) ATR
- Weekday: ±10% adjustment based on performance

This is completely separate from V2 - safe for experimentation.
"""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional, Dict, List, Any
import os
import logging
import json
import csv
import numpy as np
import pandas as pd
import pandas_ta as ta
import joblib
from datetime import datetime

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.data import Data
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.orders import MarketOrder, StopMarketOrder, LimitOrder
from nautilus_trader.model.position import Position
from nautilus_trader.trading.strategy import Strategy

# Import V4 configuration
import sys
sys.path.append(str(Path(__file__).parent.parent))
from config.mtf_v4_config import load_mtf_v4_config, get_dynamic_sl_tp

# Setup file-based logging
_py_logger = logging.getLogger("MLSignalStrategy_V4")
_py_logger.setLevel(logging.INFO)

@dataclass
class PositionInfo:
    """Information about an open position."""
    position_id: str
    entry_time: datetime
    entry_price: float
    side: str
    size: float
    sl_price: float
    tp_price: float
    position_type: int  # 1, 2, or 3
    original_sl_price: float

class MLSignalStrategyV4(Strategy):
    """
    ML Signal Strategy V4 with Dynamic SL/TP
    
    Uses dynamic stop loss and take profit based on extensive backtest analysis
    of trading hour performance patterns.
    """

    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        
        # Load V4 configuration
        self.v4_config = load_mtf_v4_config()
        
        # Strategy state
        self.instrument: Optional[Instrument] = None
        self.bar_type: Optional[BarType] = None
        
        # Position tracking
        self.open_positions: Dict[str, PositionInfo] = {}
        self.active_brackets: Dict[str, List[str]] = {}  # position_id -> [sl_order_id, tp_order_id]
        
        # ML model and features
        self.model = None
        self.feature_buffer = deque(maxlen=100)
        
        # Performance tracking
        self.trade_log = []
        self.signal_log = []
        
        # Meta filter state
        self.mama_diff = 0.0
        self.dmp = 0.0
        
        _py_logger.info("MLSignalStrategy V4 initialized with dynamic SL/TP")

    def on_start(self) -> None:
        """Strategy startup logic."""
        _py_logger.info("Starting MLSignalStrategy V4...")
        
        # Load ML model
        model_path = Path(os.getenv("MODEL_FILE", "models/ml_model_mtf.pkl"))
        if model_path.exists():
            self.model = joblib.load(model_path)
            _py_logger.info(f"Loaded ML model from {model_path}")
        else:
            _py_logger.error(f"ML model not found at {model_path}")
            return
        
        # Get instrument
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            _py_logger.error(f"Instrument {self.instrument_id} not found")
            return
        
        # Subscribe to data
        self.subscribe_bars(self.bar_type)
        
        # Initialize trade log
        self._init_trade_log()
        
        _py_logger.info("V4 strategy started successfully")

    def on_bar(self, bar: Bar) -> None:
        """Handle bar data with dynamic SL/TP logic."""
        if self.model is None or self.instrument is None:
            return
        
        current_time = bar.ts_event
        current_price = float(bar.close)
        
        # Update meta filters
        self._update_meta_filters(bar)
        
        # Check if trading is allowed for this time
        if not self._is_trading_allowed(current_time):
            return
        
        # Generate features for ML prediction
        features = self._generate_features(bar)
        if features is None:
            return
        
        # Get ML prediction
        prediction = self.model.predict([features])[0]
        prediction_proba = self.model.predict_proba([features])[0]
        
        # Get dynamic SL/TP for current time
        dynamic_params = get_dynamic_sl_tp(current_time, self.v4_config)
        
        # Log signal with dynamic parameters
        self._log_signal(current_time, prediction, prediction_proba, dynamic_params)
        
        # Process prediction
        if prediction == 1 and prediction_proba[1] > 0.6:  # BUY signal
            self._process_buy_signal(bar, dynamic_params)
        elif prediction == 0 and prediction_proba[0] > 0.6:  # SELL signal
            self._process_sell_signal(bar, dynamic_params)

    def _process_buy_signal(self, bar: Bar, dynamic_params: Dict[str, float]) -> None:
        """Process buy signal with dynamic SL/TP."""
        if len(self.open_positions) >= self.v4_config.max_positions:
            return
        
        current_price = float(bar.close)
        atr = self._get_current_atr()
        if atr is None:
            return
        
        # Calculate dynamic SL and TP
        sl_distance = atr * dynamic_params['sl_atr_mult']
        tp1_distance = atr * dynamic_params['pos1_tp_atr_mult']
        tp2_distance = atr * dynamic_params['pos2_tp_atr_mult']
        
        sl_price = current_price - sl_distance
        tp1_price = current_price + tp1_distance
        tp2_price = current_price + tp2_distance
        
        # Position sizes (same as V2)
        total_size = 20000  # 200K units
        pos1_size = int(total_size * 0.70)
        pos2_size = int(total_size * 0.25)
        pos3_size = total_size - pos1_size - pos2_size
        
        # Create three positions with dynamic SL/TP
        self._create_position(bar, "BUY", pos1_size, sl_price, tp1_price, 1, dynamic_params)
        self._create_position(bar, "BUY", pos2_size, sl_price, tp2_price, 2, dynamic_params)
        self._create_position(bar, "BUY", pos3_size, sl_price, tp2_price, 3, dynamic_params)

    def _process_sell_signal(self, bar: Bar, dynamic_params: Dict[str, float]) -> None:
        """Process sell signal with dynamic SL/TP."""
        if len(self.open_positions) >= self.v4_config.max_positions:
            return
        
        current_price = float(bar.close)
        atr = self._get_current_atr()
        if atr is None:
            return
        
        # Calculate dynamic SL and TP
        sl_distance = atr * dynamic_params['sl_atr_mult']
        tp1_distance = atr * dynamic_params['pos1_tp_atr_mult']
        tp2_distance = atr * dynamic_params['pos2_tp_atr_mult']
        
        sl_price = current_price + sl_distance
        tp1_price = current_price - tp1_distance
        tp2_price = current_price - tp2_distance
        
        # Position sizes (same as V2)
        total_size = 20000  # 200K units
        pos1_size = int(total_size * 0.70)
        pos2_size = int(total_size * 0.25)
        pos3_size = total_size - pos1_size - pos2_size
        
        # Create three positions with dynamic SL/TP
        self._create_position(bar, "SELL", pos1_size, sl_price, tp1_price, 1, dynamic_params)
        self._create_position(bar, "SELL", pos2_size, sl_price, tp2_price, 2, dynamic_params)
        self._create_position(bar, "SELL", pos3_size, sl_price, tp2_price, 3, dynamic_params)

    def _create_position(self, bar: Bar, side: str, size: float, sl_price: float, 
                        tp_price: float, position_type: int, dynamic_params: Dict[str, float]) -> None:
        """Create a position with dynamic SL/TP."""
        
        entry_price = float(bar.close)
        current_time = bar.ts_event
        
        # Log position creation with dynamic parameters
        _py_logger.info(
            f"V4 Position {position_type}: {side} {size:.0f} @ {entry_price:.5f}, "
            f"SL={sl_price:.5f} ({dynamic_params['sl_atr_mult']}x), "
            f"TP={tp_price:.5f} ({dynamic_params['pos1_tp_atr_mult'] if position_type == 1 else dynamic_params['pos2_tp_atr_mult']}x)"
        )
        
        # Create position info
        position_info = PositionInfo(
            position_id=f"pos_{position_type}_{current_time.timestamp()}",
            entry_time=current_time,
            entry_price=entry_price,
            side=side,
            size=size,
            sl_price=sl_price,
            tp_price=tp_price,
            position_type=position_type,
            original_sl_price=sl_price
        )
        
        self.open_positions[position_info.position_id] = position_info
        
        # In backtest, positions are managed automatically
        # In live trading, you would submit actual orders here

    def _is_trading_allowed(self, current_time: datetime) -> bool:
        """Check if trading is allowed based on time filters."""
        weekday = current_time.strftime("%A")
        hour = current_time.hour
        
        # Check excluded hours for this weekday
        excluded_hours = getattr(self.v4_config, f"excluded_hours_{weekday.lower()}", [])
        if hour in excluded_hours:
            return False
        
        # Check ATR limits
        atr = self._get_current_atr()
        if atr is None:
            return False
        
        if atr < self.v4_config.min_atr or atr > self.v4_config.max_atr:
            return False
        
        # Check meta filters
        if self.v4_config.meta_filter_mama_enabled and self.mama_diff < self.v4_config.meta_filter_mama_min_diff:
            return False
        
        if self.v4_config.meta_filter_dmi_enabled and self.dmp < self.v4_config.meta_filter_dmi_min_dmp:
            return False
        
        return True

    def _update_meta_filters(self, bar: Bar) -> None:
        """Update meta filter values."""
        # This would implement MAMA and DMI calculations
        # For now, using placeholder values
        self.mama_diff = 0.03  # Placeholder
        self.dmp = 30.0  # Placeholder

    def _get_current_atr(self) -> Optional[float]:
        """Get current ATR value."""
        # This would calculate ATR from recent bars
        # For now, returning a placeholder
        return 0.0010  # Placeholder

    def _generate_features(self, bar: Bar) -> Optional[List[float]]:
        """Generate features for ML prediction."""
        # This would implement the full feature engineering pipeline
        # For now, returning placeholder features
        return [0.1] * 20  # Placeholder

    def _log_signal(self, current_time: datetime, prediction: int, 
                   prediction_proba: np.ndarray, dynamic_params: Dict[str, float]) -> None:
        """Log trading signal with dynamic parameters."""
        signal_data = {
            'timestamp': current_time.isoformat(),
            'prediction': prediction,
            'confidence': max(prediction_proba),
            'sl_mult': dynamic_params['sl_atr_mult'],
            'tp_mult': dynamic_params['pos1_tp_atr_mult']
        }
        
        self.signal_log.append(signal_data)
        
        _py_logger.info(
            f"V4 Signal: {prediction} (conf: {max(prediction_proba):.2f}), "
            f"Dynamic: SL={dynamic_params['sl_atr_mult']}x, TP={dynamic_params['pos1_tp_atr_mult']}x"
        )

    def _init_trade_log(self) -> None:
        """Initialize trade logging."""
        log_file = Path("logs/v4_trade_log.csv")
        log_file.parent.mkdir(exist_ok=True)
        
        with open(log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'position_id', 'side', 'size', 'entry_price', 
                'sl_price', 'tp_price', 'sl_mult', 'tp_mult', 'position_type'
            ])

    def on_stop(self) -> None:
        """Strategy shutdown logic."""
        _py_logger.info("Stopping MLSignalStrategy V4...")
        
        # Save logs
        if self.signal_log:
            signal_file = Path("logs/v4_signal_log.json")
            with open(signal_file, 'w') as f:
                json.dump(self.signal_log, f, indent=2)
        
        _py_logger.info("V4 strategy stopped")
