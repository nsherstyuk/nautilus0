"""
MLSignalStrategy V2 - Two-Position Variant

Simplified version with only 2 positions instead of 3:
- POS1 (70-75%): Quick win at 0.9x ATR, SL=1.4 ATR
- POS2 (25-30%): Extended runner at 1.75-2.0x ATR, converts to trailing after POS1 TP

Progression:
1. Both positions open with independent brackets
2. When POS1 TP hits -> Move POS2 SL to breakeven+1pip AND convert to trailing

Benefits over 3-position:
- Simpler state management
- POS2 gets trailing immediately (doesn't wait for intermediate TP)
- Larger POS2 size makes trailing more impactful
"""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional, Dict, List
import logging
import numpy as np
import pandas as pd
import pandas_ta as ta
import joblib

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

# Setup file-based logging
_py_logger = logging.getLogger("MLSignalStrategy_V2_2POS")
_py_logger.setLevel(logging.INFO)


@dataclass
class PositionLayer:
    """Track state for each position layer."""
    name: str  # "POS1", "POS2"
    size_fraction: float
    tp_atr_mult: float
    
    # Runtime state
    entry_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    venue_sl_id: Optional[str] = None
    venue_tp_id: Optional[str] = None
    
    is_open: bool = False
    is_closed: bool = False
    entry_price: Optional[float] = None
    sl_adjusted_to_be: bool = False
    converted_to_trailing: bool = False


class MLSignalStrategyV2_2PosConfig(StrategyConfig, kw_only=True):
    """Configuration for 2-Position V2 Strategy."""
    
    instrument_id: str
    bar_type: str
    model_path: str = "models/ml_model_mtf.pkl"
    
    # Position sizing (total = 100k, split into 2)
    total_position_size: int = 100000
    pos1_fraction: float = 0.70  # Quick win (70%)
    pos2_fraction: float = 0.30  # Extended runner (30%)
    
    # Stop loss (same for both initially)
    sl_atr_mult: float = 1.4
    
    # Take profit
    pos1_tp_atr_mult: float = 0.9   # Quick win target
    pos2_tp_atr_mult: float = 1.75  # Extended target (can go higher with trailing)
    
    # Trailing stop for POS2 (activates after POS1 TP)
    trailing_distance_atr_mult: float = 0.5
    
    # Prediction settings
    prediction_threshold: float = 0.55
    
    # Session filtering
    trade_start_hour: int = 7
    trade_end_hour: int = 20
    
    # Risk management
    min_atr: float = 0.0003
    max_atr: float = 0.005
    max_positions: int = 2
    
    # Order identification
    order_id_tag: str = "V2_2P"


class MLSignalStrategyV2_2Pos(Strategy):
    """
    Two-position bracket strategy with trailing stop on POS2.
    
    Simpler than 3-position: POS2 gets trailing immediately after POS1 TP.
    """
    
    def __init__(self, config: MLSignalStrategyV2_2PosConfig):
        super().__init__(config)
        
        # Configuration
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.model_path = config.model_path
        
        # Position sizing
        self.total_size = config.total_position_size
        self._pos1_fraction = config.pos1_fraction
        self._pos2_fraction = config.pos2_fraction
        self.pos1_size = Quantity.from_int(int(self.total_size * config.pos1_fraction))
        self.pos2_size = Quantity.from_int(int(self.total_size * config.pos2_fraction))
        
        # ATR multipliers
        self.sl_atr_mult = config.sl_atr_mult
        self.pos1_tp_mult = config.pos1_tp_atr_mult
        self.pos2_tp_mult = config.pos2_tp_atr_mult
        self.trailing_distance_mult = config.trailing_distance_atr_mult
        
        # Prediction
        self.prediction_threshold = config.prediction_threshold
        self.min_atr = config.min_atr
        self.max_atr = config.max_atr
        
        # Session
        self.trade_start_hour = config.trade_start_hour
        self.trade_end_hour = config.trade_end_hour
        
        # Data buffers
        self.bars_buffer_15m = deque(maxlen=100)
        self.bars_buffer_30m = deque(maxlen=50)
        
        # Model
        self.model = None
        self._load_model()
        
        # Position layers state
        self._layers: Dict[str, PositionLayer] = {}
        self._reset_layers()
        
        # Trade state
        self._trade_direction: Optional[str] = None
        self._entry_atr: Optional[float] = None
        self._entry_price: Optional[float] = None
        self._order_id_tag = config.order_id_tag
        self._max_positions = config.max_positions
        
        # Warmup
        self._warmup_mode = True
        self._min_warmup_bars_15m = 30
        self._min_warmup_bars_30m = 15
        
        _py_logger.info("MLSignalStrategyV2_2Pos initialized - Two-position bracket approach")
        
    def _reset_layers(self):
        """Reset position layer tracking."""
        self._layers = {
            "POS1": PositionLayer(name="POS1", size_fraction=self._pos1_fraction, tp_atr_mult=self.pos1_tp_mult),
            "POS2": PositionLayer(name="POS2", size_fraction=self._pos2_fraction, tp_atr_mult=self.pos2_tp_mult),
        }
        self._trade_direction = None
        self._entry_atr = None
        self._entry_price = None
        
    def _load_model(self):
        """Load ML model."""
        try:
            model_path = Path(self.model_path)
            if not model_path.is_absolute():
                project_root = Path(__file__).parent.parent
                model_path = project_root / model_path
            self.model = joblib.load(model_path)
            _py_logger.info(f"Model loaded from {model_path}")
        except Exception as e:
            _py_logger.error(f"Failed to load model: {e}")
            self.model = None
            
    def on_start(self):
        """Initialize strategy."""
        self.subscribe_bars(self.bar_type)
        _py_logger.info("Strategy started - subscribed to bars")
        
    # =========================================================================
    # ORDER EVENT HANDLERS
    # =========================================================================
    
    def on_order_filled(self, event):
        """Handle order fills."""
        order_id = str(event.client_order_id)
        
        for layer_name, layer in self._layers.items():
            # Entry filled
            if layer.entry_order_id and order_id == str(layer.entry_order_id):
                layer.is_open = True
                layer.entry_price = float(event.last_px)
                self._log_position_state(f"{layer_name} ENTRY FILLED @ {event.last_px}")
                
            # TP filled
            elif layer.tp_order_id and order_id == str(layer.tp_order_id):
                layer.is_open = False
                layer.is_closed = True
                pnl = self._calculate_pnl(layer, float(event.last_px))
                self._log_position_state(f"{layer_name} TP HIT @ {event.last_px} (PnL: ${pnl:.2f})")
                self._on_layer_tp_hit(layer_name)
                
            # SL filled
            elif layer.sl_order_id and order_id == str(layer.sl_order_id):
                layer.is_open = False
                layer.is_closed = True
                pnl = self._calculate_pnl(layer, float(event.last_px))
                self._log_position_state(f"{layer_name} SL HIT @ {event.last_px} (PnL: ${pnl:.2f})")
                
        # Check if all positions closed
        if all(l.is_closed or not l.is_open for l in self._layers.values()):
            if any(l.is_closed for l in self._layers.values()):
                self._log_position_state("ALL POSITIONS CLOSED - Trade complete")
                self._reset_layers()
                
    def on_order_accepted(self, event):
        """Track order acceptance."""
        order_id = str(event.client_order_id)
        venue_id = str(event.venue_order_id)
        
        for layer_name, layer in self._layers.items():
            if layer.sl_order_id and order_id == str(layer.sl_order_id):
                layer.venue_sl_id = venue_id
                _py_logger.info(f"[VERIFIED] {layer_name} SL accepted: venue_id={venue_id}")
            elif layer.tp_order_id and order_id == str(layer.tp_order_id):
                layer.venue_tp_id = venue_id
                _py_logger.info(f"[VERIFIED] {layer_name} TP accepted: venue_id={venue_id}")
                
    def on_order_rejected(self, event):
        """Handle order rejections."""
        order_id = str(event.client_order_id)
        reason = getattr(event, 'reason', 'Unknown')
        _py_logger.error(f"[REJECTED] Order {order_id}: {reason}")
        self._handle_order_failure(order_id, reason)
        
    def on_order_denied(self, event):
        """Handle order denials."""
        order_id = str(event.client_order_id)
        reason = getattr(event, 'reason', 'Unknown')
        _py_logger.error(f"[DENIED] Order {order_id}: {reason}")
        self._handle_order_failure(order_id, reason)
        
    def _handle_order_failure(self, order_id: str, reason: str):
        """Reset state if no positions are actually open."""
        positions = list(self.cache.positions(instrument_id=self.instrument_id))
        open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
        
        if len(positions) == 0 and len(open_orders) == 0:
            if self._trade_direction is not None:
                _py_logger.warning(f"[RESET] No positions/orders - resetting trade state")
                self._reset_layers()
                
    # =========================================================================
    # POSITION PROGRESSION LOGIC (SIMPLIFIED FOR 2 POSITIONS)
    # =========================================================================
    
    def _on_layer_tp_hit(self, layer_name: str):
        """Handle TP hit - POS1 TP triggers POS2 SL->BE + trailing."""
        
        if layer_name == "POS1":
            # POS1 TP hit -> Move POS2 SL to breakeven AND convert to trailing
            self._log_position_state("POS1 TP -> Adjusting POS2 SL to BE + Trailing")
            self._adjust_sl_to_breakeven("POS2")
            self._convert_to_trailing("POS2")
            
    def _adjust_sl_to_breakeven(self, layer_name: str):
        """Move SL to breakeven + 1 pip."""
        layer = self._layers.get(layer_name)
        if not layer or not layer.is_open or layer.sl_adjusted_to_be:
            return
            
        try:
            pip_value = 0.0001
            if self._trade_direction == "LONG":
                new_sl = self._entry_price + pip_value
            else:
                new_sl = self._entry_price - pip_value
                
            self._modify_sl_order(layer, new_sl)
            layer.sl_adjusted_to_be = True
            _py_logger.info(f"[ADJUSTED] {layer_name} SL moved to BE: {new_sl:.5f}")
            
        except Exception as e:
            _py_logger.error(f"Failed to adjust {layer_name} SL: {e}")
            
    def _convert_to_trailing(self, layer_name: str):
        """Convert SL to trailing stop."""
        layer = self._layers.get(layer_name)
        if not layer or not layer.is_open or layer.converted_to_trailing:
            return
            
        try:
            # Start trailing from current profit level
            trail_distance = self._entry_price * self._entry_atr * self.trailing_distance_mult
            
            # Calculate initial trailing SL
            if self._trade_direction == "LONG":
                # Place SL at BE + some profit - trail distance
                new_sl = self._entry_price + (self._entry_price * self._entry_atr * 0.5) - trail_distance
                # Ensure at least at breakeven
                new_sl = max(new_sl, self._entry_price + 0.0001)
            else:
                new_sl = self._entry_price - (self._entry_price * self._entry_atr * 0.5) + trail_distance
                new_sl = min(new_sl, self._entry_price - 0.0001)
                
            self._modify_sl_order(layer, new_sl)
            layer.converted_to_trailing = True
            _py_logger.info(f"[TRAILING] {layer_name} SL converted to trailing: {new_sl:.5f}")
            
        except Exception as e:
            _py_logger.error(f"Failed to convert {layer_name} to trailing: {e}")
            
    def _modify_sl_order(self, layer: PositionLayer, new_price: float):
        """Modify existing SL order."""
        if not layer.sl_order_id:
            return
            
        order = self.cache.order(layer.sl_order_id)
        if order:
            self.modify_order(
                order,
                trigger_price=Price.from_str(f"{new_price:.5f}")
            )
            _py_logger.info(f"Modified {layer.name} SL to {new_price:.5f}")
            
    def _update_trailing_stop(self, layer: PositionLayer, current_price: float):
        """Update trailing stop if price moved favorably."""
        if not layer.converted_to_trailing or not layer.is_open:
            return
            
        trail_distance = self._entry_price * self._entry_atr * self.trailing_distance_mult
        
        if self._trade_direction == "LONG":
            new_sl = current_price - trail_distance
            order = self.cache.order(layer.sl_order_id)
            if order and float(order.trigger_price) < new_sl:
                self._modify_sl_order(layer, new_sl)
        else:
            new_sl = current_price + trail_distance
            order = self.cache.order(layer.sl_order_id)
            if order and float(order.trigger_price) > new_sl:
                self._modify_sl_order(layer, new_sl)
                
    # =========================================================================
    # POSITION MONITORING
    # =========================================================================
    
    def _log_position_state(self, event: str):
        """Log current state."""
        print("\n" + "=" * 60)
        print(f"[2-POS EVENT] {event}")
        print("-" * 60)
        
        for name, layer in self._layers.items():
            status = "CLOSED" if layer.is_closed else ("OPEN" if layer.is_open else "PENDING")
            sl_status = "BE+TRAIL" if layer.converted_to_trailing else ("BE" if layer.sl_adjusted_to_be else "INIT")
            
            print(f"  {name}: {status} | SL: {sl_status} | TP: {layer.tp_atr_mult}x ATR")
            
        print("=" * 60 + "\n")
        
        _py_logger.info(f"[STATE] {event}")
        for name, layer in self._layers.items():
            status = "CLOSED" if layer.is_closed else ("OPEN" if layer.is_open else "PENDING")
            _py_logger.info(f"  {name}: {status}, BE={layer.sl_adjusted_to_be}, TRAIL={layer.converted_to_trailing}")
            
    def _calculate_pnl(self, layer: PositionLayer, exit_price: float) -> float:
        """Calculate PnL for a layer."""
        if not layer.entry_price:
            return 0.0
            
        size = self.total_size * layer.size_fraction
        
        if self._trade_direction == "LONG":
            return (exit_price - layer.entry_price) * size
        else:
            return (layer.entry_price - exit_price) * size
            
    # =========================================================================
    # ENTRY EXECUTION
    # =========================================================================
    
    def _execute_entry(self, bar: Bar, atr_normalized: float, direction: str):
        """Open both positions with brackets."""
        
        entry_price = float(bar.close)
        self._trade_direction = direction
        self._entry_atr = atr_normalized
        self._entry_price = entry_price
        
        sl_distance = entry_price * atr_normalized * self.sl_atr_mult
        
        if direction == "LONG":
            sl_price = entry_price - sl_distance
            order_side = OrderSide.BUY
        else:
            sl_price = entry_price + sl_distance
            order_side = OrderSide.SELL
            
        self._log_position_state(f"OPENING {direction} TRADE @ {entry_price:.5f}")
        
        # Open both positions
        for layer_name, layer in self._layers.items():
            self._open_layer_position(layer, order_side, entry_price, sl_price, atr_normalized)
            
    def _open_layer_position(self, layer: PositionLayer, order_side: OrderSide, 
                             entry_price: float, sl_price: float, atr: float):
        """Open a single position with bracket."""
        
        size = Quantity.from_int(int(self.total_size * layer.size_fraction))
        
        tp_distance = entry_price * atr * layer.tp_atr_mult
        if order_side == OrderSide.BUY:
            tp_price = entry_price + tp_distance
        else:
            tp_price = entry_price - tp_distance
            
        tag_prefix = f"{self._order_id_tag}_{layer.name}"
        
        bracket = self.order_factory.bracket(
            instrument_id=self.instrument_id,
            order_side=order_side,
            quantity=size,
            sl_trigger_price=Price.from_str(f"{sl_price:.5f}"),
            tp_price=Price.from_str(f"{tp_price:.5f}"),
            tp_post_only=False,
            entry_tags=[tag_prefix],
            sl_tags=[f"{tag_prefix}_SL"],
            tp_tags=[f"{tag_prefix}_TP"]
        )
        
        for order in bracket.orders:
            if isinstance(order, MarketOrder):
                layer.entry_order_id = order.client_order_id
            elif isinstance(order, StopMarketOrder):
                layer.sl_order_id = order.client_order_id
            elif isinstance(order, LimitOrder):
                layer.tp_order_id = order.client_order_id
                
        self.submit_order_list(bracket)
        
        _py_logger.info(
            f"[SUBMIT] {layer.name}: {size} units, SL={sl_price:.5f}, TP={tp_price:.5f} ({layer.tp_atr_mult}x ATR)"
        )
        
    # =========================================================================
    # BAR PROCESSING
    # =========================================================================
    
    def on_bar(self, bar: Bar):
        """Process incoming bar."""
        
        bar_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        
        # Update buffers
        self.bars_buffer_15m.append(bar)
        self._resample_to_30m()
        
        # Warmup check
        if len(self.bars_buffer_15m) < self._min_warmup_bars_15m:
            return
        if len(self.bars_buffer_30m) < self._min_warmup_bars_30m:
            return
            
        if self._warmup_mode:
            self._warmup_mode = False
            _py_logger.info("Warmup complete - ready to trade")
            
        # Verify instrument is loaded
        instrument = self.cache.instrument(self.instrument_id)
        if instrument is None:
            return
            
        # Update trailing stop for POS2 if active
        if self._layers["POS2"].converted_to_trailing:
            self._update_trailing_stop(self._layers["POS2"], float(bar.close))
            
        # Check if already in trade
        any_open = any(l.is_open for l in self._layers.values())
        positions = list(self.cache.positions(instrument_id=self.instrument_id))
        has_cache_positions = len(positions) > 0
        open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
        has_pending_orders = len(open_orders) > 0
        
        if any_open or has_cache_positions or has_pending_orders or self._trade_direction is not None:
            return
            
        # Check for new entry signal
        if self.model is None:
            return
            
        # Session filter
        if not (self.trade_start_hour <= bar_time.hour < self.trade_end_hour):
            return
            
        # Calculate features and get prediction
        features = self._calculate_features()
        if features is None:
            return
            
        prediction = self.model.predict([features])[0]
        confidence = self.model.predict_proba([features])[0].max()
        
        if confidence < self.prediction_threshold:
            return
            
        # Get ATR
        atr = self._calculate_atr()
        if atr is None or atr < self.min_atr or atr > self.max_atr:
            return
            
        # Execute entry
        direction = "LONG" if prediction == 1 else "SHORT"
        self._execute_entry(bar, atr, direction)
        
    def _resample_to_30m(self):
        """Resample 15m bars to 30m."""
        if len(self.bars_buffer_15m) < 2:
            return
            
        data = {
            'open': [float(b.open) for b in self.bars_buffer_15m],
            'high': [float(b.high) for b in self.bars_buffer_15m],
            'low': [float(b.low) for b in self.bars_buffer_15m],
            'close': [float(b.close) for b in self.bars_buffer_15m],
            'volume': [float(b.volume) for b in self.bars_buffer_15m],
            'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer_15m]
        }
        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)
        
        df_30m = df.resample('30min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        self.bars_buffer_30m.clear()
        for idx, row in df_30m.iterrows():
            self.bars_buffer_30m.append({
                'timestamp': idx,
                'open': row['open'],
                'high': row['high'],
                'low': row['low'],
                'close': row['close'],
                'volume': row['volume']
            })
            
    def _calculate_features(self) -> Optional[np.ndarray]:
        """Calculate ML features."""
        try:
            if len(self.bars_buffer_15m) < 30 or len(self.bars_buffer_30m) < 15:
                return None
                
            # 15m data
            df_15m = pd.DataFrame({
                'open': [float(b.open) for b in self.bars_buffer_15m],
                'high': [float(b.high) for b in self.bars_buffer_15m],
                'low': [float(b.low) for b in self.bars_buffer_15m],
                'close': [float(b.close) for b in self.bars_buffer_15m],
                'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer_15m]
            })
            
            # 30m data
            df_30m = pd.DataFrame(list(self.bars_buffer_30m))
            
            # Features
            log_ret = np.log(df_15m['close'].iloc[-1] / df_15m['close'].iloc[-2])
            
            hl2 = (df_15m['high'] + df_15m['low']) / 2
            mama = ta.mama(hl2, fastlimit=0.5, slowlimit=0.05)
            mama_diff = (mama.iloc[-1, 0] - mama.iloc[-1, 1]) if mama is not None else 0
            
            adx = ta.adx(df_30m['high'], df_30m['low'], df_30m['close'], length=14)
            dmp_30m = adx['DMP_14'].iloc[-1] if adx is not None else 0
            dmn_30m = adx['DMN_14'].iloc[-1] if adx is not None else 0
            
            stoch = ta.stoch(df_30m['high'], df_30m['low'], df_30m['close'], k=14, d=3, smooth_k=3)
            stoch_k = stoch.iloc[-1, 0] if stoch is not None else 50
            stoch_d = stoch.iloc[-1, 1] if stoch is not None else 50
            
            wma_fast = ta.wma(df_30m['close'], length=9)
            wma_slow = ta.wma(df_30m['close'], length=23)
            wma_diff = ((wma_fast.iloc[-1] - wma_slow.iloc[-1]) / df_30m['close'].iloc[-1]) if wma_fast is not None and wma_slow is not None else 0
            
            atr = ta.atr(df_15m['high'], df_15m['low'], df_15m['close'], length=14)
            atr_norm = (atr.iloc[-1] / df_15m['close'].iloc[-1]) if atr is not None else 0
            
            hour = df_15m['timestamp'].iloc[-1].hour
            dow = df_15m['timestamp'].iloc[-1].dayofweek
            
            features = np.array([
                log_ret, mama_diff, dmp_30m, dmn_30m,
                stoch_k, stoch_d, wma_diff, atr_norm, hour, dow
            ])
            
            return features
            
        except Exception as e:
            _py_logger.error(f"Feature calculation error: {e}")
            return None
        
    def _calculate_atr(self) -> Optional[float]:
        """Calculate normalized ATR."""
        if len(self.bars_buffer_15m) < 14:
            return None
            
        highs = [float(b.high) for b in self.bars_buffer_15m]
        lows = [float(b.low) for b in self.bars_buffer_15m]
        closes = [float(b.close) for b in self.bars_buffer_15m]
        
        df = pd.DataFrame({'high': highs, 'low': lows, 'close': closes})
        atr = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        if atr is None or atr.empty:
            return None
            
        return atr.iloc[-1] / closes[-1]
