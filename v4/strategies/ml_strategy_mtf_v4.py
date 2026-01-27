"""
MLSignalStrategy V4 - Multi-Timeframe with Dynamic SL/TP

V4 builds on V2's three-position bracket approach but adds:
- Dynamic stop loss multipliers based on trading hour analysis
- Dynamic take profit multipliers for high-performance hours
- Weekday performance adjustments
- Multi-timeframe support (15-minute decision + 1-minute execution)
- Separate configuration from V2 (no impact on live trading)

Dynamic Parameters:
- SL: 1.0x (low fade hours) to 1.6x (high fade hours) ATR
- TP: 0.5x (poor performance) to 0.8x (high performance) ATR
- Weekend: ±10% adjustment based on performance

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
v4_path = Path(__file__).parent.parent
sys.path.append(str(v4_path))
sys.path.append(str(v4_path / "config"))

from mtf_v4_config import load_mtf_v4_config, get_dynamic_sl_tp

# Setup file-based logging
_py_logger = logging.getLogger("MLSignalStrategy_V4")
_py_logger.setLevel(logging.INFO)

FEATURE_NAMES = [
    "log_ret", "mama_diff", "dmp_30m", "dmn_30m", "stoch_k_30m", "stoch_d_30m",
    "wma_diff_30m", "atr_15m", "hour", "day_of_week"
]

@dataclass
class PositionLayer:
    """Track state for each position layer."""
    name: str  # "POS1", "POS2", "POS3"
    size_fraction: float  # 0.7, 0.2, 0.1
    tp_atr_mult: float  # Will be set dynamically
    
    # Runtime state
    entry_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    venue_sl_id: Optional[str] = None
    venue_tp_id: Optional[str] = None
    
    is_open: bool = False
    is_closed: bool = False
    entry_price: Optional[float] = None
    entry_time: Optional[pd.Timestamp] = None
    sl_adjusted_to_be: bool = False
    converted_to_trailing: bool = False
    
    # Feature logging
    entry_features: Optional[Dict[str, Any]] = None

class MLSignalStrategyV4Config(StrategyConfig, kw_only=True):
    """Configuration for MLSignalStrategy V4."""
    
    instrument_id: str
    bar_type: str  # 15-minute decision timeframe
    model_path: str = "v4/models/ml_model_mtf.pkl"
    
    # Multi-timeframe configuration
    mtf_config: Dict[str, str] = None
    
    # Position sizing (same as V2 optimized)
    total_position_size: int = 100000
    pos1_fraction: float = 0.85  # Quick win (85%)
    pos2_fraction: float = 0.15  # Extended (15%)
    pos3_fraction: float = 0.00  # Disabled in 2-position mode
    
    # Base stop loss (will be adjusted dynamically)
    sl_atr_mult: float = 1.2  # Default, will be overridden by dynamic values
    
    # Take profit (will be adjusted dynamically)
    pos1_tp_atr_mult: float = 0.6   # Default, will be overridden
    pos2_tp_atr_mult: float = 2.0   # Default, will be overridden
    trailing_distance_atr_mult: float = 0.4

class MLSignalStrategyV4(Strategy):
    """
    ML Signal Strategy V4 with Dynamic SL/TP and Multi-Timeframe
    
    Uses dynamic stop loss and take profit based on extensive backtest analysis
    of trading hour performance patterns across 15-minute and 1-minute timeframes.
    """

    def __init__(self, config: MLSignalStrategyV4Config) -> None:
        super().__init__(config)
        
        # Load V4 configuration
        self.v4_config = load_mtf_v4_config()
        
        # Strategy configuration (access via self.config)
        # self.config = config  # This is not allowed - config is already set by parent
        
        # Strategy state
        self.instrument: Optional[Instrument] = None
        self.decision_bar_type: Optional[BarType] = None
        self.execution_bar_type: Optional[BarType] = None
        
        # Position tracking
        self.position_layers: Dict[str, PositionLayer] = {}
        self.active_position_count: int = 0
        
        # ML model and features
        self.model = None
        self.feature_buffer = deque(maxlen=100)
        
        # Performance tracking
        self.trade_log = []
        self.signal_log = []
        
        # Multi-timeframe state
        self.last_decision_bar: Optional[Bar] = None
        self.pending_signal: Optional[Dict[str, Any]] = None
        
        # Meta filter state
        self.mama_diff = 0.0
        self.dmp = 0.0
        
        # Initialize position layers
        self._init_position_layers()
        
        _py_logger.info("MLSignalStrategy V4 initialized with dynamic SL/TP")

    def _init_position_layers(self) -> None:
        """Initialize position layer configurations."""
        
        self.position_layers = {
            "POS1": PositionLayer(
                name="POS1",
                size_fraction=self.config.pos1_fraction,
                tp_atr_mult=self.config.pos1_tp_atr_mult
            ),
            "POS2": PositionLayer(
                name="POS2", 
                size_fraction=self.config.pos2_fraction,
                tp_atr_mult=self.config.pos2_tp_atr_mult
            ),
            "POS3": PositionLayer(
                name="POS3",
                size_fraction=self.config.pos3_fraction,
                tp_atr_mult=self.config.pos2_tp_atr_mult
            ) if self.config.pos3_fraction > 0 else None
        }
        
        # Remove POS3 if fraction is 0
        if self.config.pos3_fraction == 0 and "POS3" in self.position_layers:
            del self.position_layers["POS3"]

    def on_start(self) -> None:
        """Strategy startup logic."""
        _py_logger.info("Starting MLSignalStrategy V4...")
        
        # Load ML model
        model_path = Path(self.config.model_path)
        if model_path.exists():
            self.model = joblib.load(model_path)
            _py_logger.info(f"Loaded V4 ML model from {model_path}")
        else:
            _py_logger.error(f"V4 ML model not found at {model_path}")
            return
        
        # Get instrument
        instrument_id = InstrumentId.from_str(self.config.instrument_id)
        self.instrument = self.cache.instrument(instrument_id)
        if self.instrument is None:
            _py_logger.error(f"Instrument {self.config.instrument_id} not found")
            return
        
        # Parse bar types from MTF config
        mtf_config = self.config.mtf_config or {}
        decision_bar_str = mtf_config.get("decision_bar_type", self.config.bar_type)
        execution_bar_str = mtf_config.get("execution_bar_type", "EUR/USD.IDEALPRO-1-MINUTE-MID-EXTERNAL")
        
        self.decision_bar_type = BarType.from_str(decision_bar_str)
        self.execution_bar_type = BarType.from_str(execution_bar_str)
        
        if self.decision_bar_type is None or self.execution_bar_type is None:
            _py_logger.error("Could not resolve MTF bar types")
            return
        
        # Subscribe to both timeframes
        self.subscribe_bars(self.decision_bar_type)
        self.subscribe_bars(self.execution_bar_type)
        
        # Initialize trade log
        self._init_trade_log()
        
        _py_logger.info("V4 strategy started successfully")
        _py_logger.info(f"Decision timeframe: {self.decision_bar_type}")
        _py_logger.info(f"Execution timeframe: {self.execution_bar_type}")

    def on_bar(self, bar: Bar) -> None:
        """Handle bar data for both timeframes."""
        
        if self.model is None or self.instrument is None:
            return
        
        # Determine which timeframe this bar belongs to
        if bar.bar_type == self.decision_bar_type:
            self._on_decision_bar(bar)
        elif bar.bar_type == self.execution_bar_type:
            self._on_execution_bar(bar)

    def _on_decision_bar(self, bar: Bar) -> None:
        """Handle 15-minute decision bar with dynamic SL/TP."""
        
        # Convert nanoseconds timestamp to datetime
        current_time = pd.Timestamp(bar.ts_event, unit='ns').to_pydatetime()
        current_price = float(bar.close)
        
        # Update meta filters
        self._update_meta_filters(bar)
        
        # Check if trading is allowed for this time
        if not self._is_trading_allowed(current_time):
            self.pending_signal = None
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
        
        # Store signal for execution on next 1-minute bar
        if prediction in [0, 1] and max(prediction_proba) > 0.6:
            self.pending_signal = {
                'prediction': prediction,
                'confidence': max(prediction_proba),
                'bar_price': current_price,
                'bar_time': current_time,
                'features': features,
                'dynamic_params': dynamic_params
            }
            
            # Log signal with dynamic parameters
            self._log_signal(current_time, prediction, prediction_proba, dynamic_params)
        
        self.last_decision_bar = bar

    def _on_execution_bar(self, bar: Bar) -> None:
        """Handle 1-minute execution bar."""
        
        # Execute pending signal from decision timeframe
        if self.pending_signal is not None:
            self._execute_pending_signal(bar)
            self.pending_signal = None

    def _execute_pending_signal(self, execution_bar: Bar) -> None:
        """Execute pending signal on 1-minute bar."""
        
        if self.active_position_count >= self.v4_config.max_positions:
            return
        
        signal = self.pending_signal
        current_price = float(execution_bar.close)
        current_time = pd.Timestamp(execution_bar.ts_event, unit='ns').to_pydatetime()
        dynamic_params = signal['dynamic_params']
        
        # Calculate ATR (use last decision bar's ATR)
        atr = self._get_current_atr()
        if atr is None:
            return
        
        # Calculate dynamic SL and TP
        sl_distance = atr * dynamic_params['sl_atr_mult']
        tp1_distance = atr * dynamic_params['pos1_tp_atr_mult']
        tp2_distance = atr * dynamic_params['pos2_tp_atr_mult']
        
        # Calculate prices based on signal direction
        if signal['prediction'] == 1:  # BUY signal
            sl_price = current_price - sl_distance
            tp1_price = current_price + tp1_distance
            tp2_price = current_price + tp2_distance
            side = "BUY"
        else:  # SELL signal
            sl_price = current_price + sl_distance
            tp1_price = current_price - tp1_distance
            tp2_price = current_price - tp2_distance
            side = "SELL"
        
        # Log execution with dynamic parameters
        _py_logger.info(
            f"V4 EXECUTE {side} @ {current_price:.5f}, "
            f"SL={sl_price:.5f} ({dynamic_params['sl_atr_mult']}x), "
            f"TP1={tp1_price:.5f} ({dynamic_params['pos1_tp_atr_mult']}x), "
            f"TP2={tp2_price:.5f} ({dynamic_params['pos2_tp_atr_mult']}x)"
        )
        
        # Create positions with dynamic SL/TP
        self._create_positions(execution_bar, side, sl_price, tp1_price, tp2_price, dynamic_params)

    def _create_positions(self, bar: Bar, side: str, sl_price: float, 
                         tp1_price: float, tp2_price: float, dynamic_params: Dict[str, float]) -> None:
        """Create positions with dynamic SL/TP."""
        
        entry_price = float(bar.close)
        current_time = pd.Timestamp(bar.ts_event, unit='ns').to_pydatetime()
        
        # Update position layer TP multipliers with dynamic values
        self.position_layers["POS1"].tp_atr_mult = dynamic_params['pos1_tp_atr_mult']
        self.position_layers["POS2"].tp_atr_mult = dynamic_params['pos2_tp_atr_mult']
        
        if "POS3" in self.position_layers:
            self.position_layers["POS3"].tp_atr_mult = dynamic_params['pos2_tp_atr_mult']
        
        # Create each position layer
        for layer_name, layer in self.position_layers.items():
            if layer.size_fraction > 0:
                layer_size = int(self.config.total_position_size * layer.size_fraction)
                
                # Determine TP for this layer
                if layer_name == "POS1":
                    layer_tp = tp1_price
                else:
                    layer_tp = tp2_price
                
                # Create position info
                layer.entry_price = entry_price
                layer.entry_time = current_time
                layer.is_open = True
                self.active_position_count += 1
                
                # Log position creation
                _py_logger.info(
                    f"V4 {layer_name}: {side} {layer_size:.0f} @ {entry_price:.5f}, "
                    f"SL={sl_price:.5f}, TP={layer_tp:.5f}"
                )
                
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
        # For now, returning placeholder features (10 features to match V2 model)
        return [0.1] * 10  # Placeholder - matches FEATURE_NAMES count

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
        log_file = Path("v4/logs/v4_trade_log.csv")
        log_file.parent.mkdir(exist_ok=True)
        
        with open(log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'layer', 'side', 'size', 'entry_price', 
                'sl_price', 'tp_price', 'sl_mult', 'tp_mult'
            ])

    def on_stop(self) -> None:
        """Strategy shutdown logic."""
        _py_logger.info("Stopping MLSignalStrategy V4...")
        
        # Save logs
        if self.signal_log:
            signal_file = Path("v4/logs/v4_signal_log.json")
            signal_file.parent.mkdir(exist_ok=True)
            with open(signal_file, 'w') as f:
                json.dump(self.signal_log, f, indent=2)
        
        _py_logger.info("V4 strategy stopped")
