"""
Machine Learning-based trading strategy using trained Random Forest model.
Ensures feature calculation parity with research/train_model.py.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Optional, Deque, Dict, Any

import numpy as np
import pandas as pd
import pandas_ta as ta
from joblib import load
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, PositionSide, TriggerType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.orders import StopMarketOrder, LimitOrder
from nautilus_trader.model.position import Position
from nautilus_trader.trading.strategy import Strategy

from strategies.ml_strategy_config import MLSignalStrategyConfig

# Python logger for additional debugging (works alongside NautilusTrader's self.log)
_py_logger = logging.getLogger("strategies.ml_strategy_mtf")

class MLSignalStrategy(Strategy):
    def __init__(self, config: MLSignalStrategyConfig) -> None:
        super().__init__(config)
        
        # Core settings
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(f"{config.instrument_id}-{config.bar_spec}")
        # For forex, use precision=2 (e.g., 100000.00 units)
        self.position_size = Quantity.from_str(f"{float(config.position_size):.2f}")
        self._order_id_tag = config.order_id_tag
        
        # Model settings
        self.model_path = config.model_path
        self.prediction_threshold = config.prediction_threshold
        
        # Risk management
        self.enforce_position_limit = config.enforce_position_limit
        self.max_positions = config.max_positions
        
        # Stop Loss / Take Profit
        self.sl_atr_mult = config.sl_atr_mult
        self.tp_atr_mult = config.tp_atr_mult
        
        # Trailing stop settings
        self.trailing_stop_enabled = config.trailing_stop_enabled
        self.trailing_activation_atr_mult = config.trailing_activation_atr_mult
        self.trailing_distance_atr_mult = config.trailing_distance_atr_mult
        
        # Partial close settings
        self.partial_close_enabled = config.partial_close_enabled
        self.partial_close_fraction = config.partial_close_fraction
        self.partial_close_move_sl_to_be = config.partial_close_move_sl_to_be
        
        # Multi-layer exit settings (OPTIMIZED)
        self.multi_layer_enabled = config.multi_layer_enabled
        self.multi_layer_count = config.multi_layer_count
        self.multi_layer_sizes = config.multi_layer_sizes
        self.multi_layer_triggers = config.multi_layer_triggers
        self.multi_layer_move_sl_to_be = config.multi_layer_move_sl_to_be
        
        # Trading session
        self.session_start = datetime.strptime(config.session_start, "%H:%M").time()
        self.session_end = datetime.strptime(config.session_end, "%H:%M").time()
        self.excluded_hours = config.excluded_hours
        self.excluded_hours_by_weekday = config.excluded_hours_by_weekday
        
        # Debug mode - bypass all filters
        self.debug_mode = config.debug_mode
        
        # Initialize state
        self.model = None
        self.bars_buffer_15m: Deque[Bar] = deque(maxlen=config.feature_warmup_bars)  # 15m bars
        self.bars_buffer_30m: Deque[Bar] = deque(maxlen=config.feature_warmup_bars // 2)  # 30m bars
        
        # Minimum bars needed for indicators (ATR=14, ADX=14, Stoch=17, WMA=23)
        # Using 30 as minimum (enough for all indicators to be valid)
        self._min_warmup_bars_15m = 30
        self._min_warmup_bars_30m = 15
        self._warmup_stalled_count = 0  # Track if warmup is stalled (no new bars)
        self._warmup_mode = True  # Skip session filters during historical backfill
        
        # Order management state
        self._current_stop_order = None
        self._last_stop_price = None
        self._position_entry_price = None
        self._position_atr = None  # ATR at entry for trailing calculations
        self._trailing_active = False
        self._partial_close_done = False
        
        # Multi-layer state tracking
        self._multi_layer_closed = []  # Track which layers have been closed
        self._initial_position_size = None  # Track original position size
        self._current_tp_order = None  # Track TP order for quantity adjustment
        self._tp_price = None  # Store TP price for recreating order
        
        # Order verification tracking
        self._sl_order_verified = False  # True when SL order confirmed at IBKR
        self._tp_order_verified = False  # True when TP order confirmed at IBKR
        self._pending_sl_order_id = None  # Track SL order ID awaiting verification
        self._pending_tp_order_id = None  # Track TP order ID awaiting verification
        
        # Trade management
        self._last_trade_time = None
        self._trade_cooldown = pd.Timedelta(minutes=30)  # Wait 30 minutes between trades
        self._min_atr = 0.0003  # Minimum ATR to trade (30 pips)
        
        # Load model immediately in __init__ so it's available during backfill
        self._load_model()
        _py_logger.info(f"MLSignalStrategy initialized: model_loaded={self.model is not None}, bar_type={self.bar_type}")
        
    def _load_model(self) -> None:
        """Load the ML model from file."""
        try:
            model_path = Path(self.model_path)
            if not model_path.is_absolute():
                # Use project root to resolve relative paths
                project_root = Path(__file__).parent.parent
                model_path = project_root / model_path
            
            _py_logger.info(f"Loading ML model from: {model_path}")
            
            if not model_path.exists():
                # Log will be available later, store error for on_start
                self._model_load_error = f"Model file not found: {model_path}"
                _py_logger.error(self._model_load_error)
                return
                
            self.model = load(model_path)
            self._model_load_error = None
            _py_logger.info(f"ML model loaded successfully: {type(self.model).__name__}")
        except Exception as e:
            self._model_load_error = f"Failed to load model: {e}"
            _py_logger.error(self._model_load_error)
        
    def on_start(self) -> None:
        """Initialize strategy and register data streams."""
        _py_logger.info("on_start() called - initializing strategy")
        
        # Log model load status
        if hasattr(self, '_model_load_error') and self._model_load_error:
            self.log.error(self._model_load_error)
            _py_logger.error(self._model_load_error)
            return
        elif self.model is not None:
            self.log.info(f"Model loaded successfully from {self.model_path}")
            _py_logger.info(f"Model loaded successfully from {self.model_path}")
        else:
            self.log.error("Model is None - loading failed silently")
            _py_logger.error("Model is None - loading failed silently")
            return
            
        # Get instrument
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Unknown instrument {self.instrument_id}")
            _py_logger.error(f"Unknown instrument {self.instrument_id}")
            return
        
        # Restore position state if restarting with open position
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        if positions:
            position = positions[0]
            self._position_entry_price = float(position.avg_px_open)
            self._initial_position_size = position.quantity  # Restore for multi-layer
            self._multi_layer_closed = []  # Reset layer tracking
            # Estimate ATR (will be recalculated on next bar)
            self._position_atr = 0.0003  # Default ATR for 15-minute bars
            self.log.info(
                f"Restored position state: entry_price={self._position_entry_price:.5f}, "
                f"size={position.quantity}, side={position.side.name}"
            )
            _py_logger.info(f"Restored position: entry={self._position_entry_price}, atr={self._position_atr}, size={self._initial_position_size}")
            
        # Subscribe to live bars (no historical backfill via subscribe_bars)
        # Historical backfill is handled by run_live_mtf.py before strategy starts
        _py_logger.info(f"Subscribing to live bars: {self.bar_type}")
        
        self.subscribe_bars(self.bar_type)
        
        _py_logger.info(f"Subscribed to live bars: {self.bar_type}")
        self.log.info("Strategy initialized successfully - subscribed to live bars")
    
    def on_order_filled(self, event) -> None:
        """Handle order filled event."""
        self.log.info(f"Order filled: {event}")
    
    def on_order_accepted(self, event) -> None:
        """Handle order accepted event - verify SL/TP orders are working."""
        order_id = str(event.client_order_id)
        venue_id = event.venue_order_id
        
        # Check if this is our SL order
        if self._pending_sl_order_id and order_id == str(self._pending_sl_order_id):
            self._sl_order_verified = True
            self.log.info(f"[VERIFIED] SL order accepted at IBKR: {order_id} -> venue_id={venue_id}")
            _py_logger.info(f"[VERIFIED] SL order confirmed: venue_id={venue_id}")
        
        # Check if this is our TP order
        if self._pending_tp_order_id and order_id == str(self._pending_tp_order_id):
            self._tp_order_verified = True
            self.log.info(f"[VERIFIED] TP order accepted at IBKR: {order_id} -> venue_id={venue_id}")
            _py_logger.info(f"[VERIFIED] TP order confirmed: venue_id={venue_id}")
        
        # Log overall protection status
        if self._sl_order_verified and self._tp_order_verified:
            self.log.info("[PROTECTED] Position has verified SL and TP orders")
            _py_logger.info("[PROTECTED] Both SL and TP orders verified at IBKR")
    
    def on_order_rejected(self, event) -> None:
        """Handle order rejected event - CRITICAL for detecting failed protection."""
        order_id = str(event.client_order_id)
        reason = getattr(event, 'reason', 'Unknown')
        
        self.log.error(f"[REJECTED] Order rejected: {order_id}, reason: {reason}")
        _py_logger.error(f"[REJECTED] Order {order_id} rejected: {reason}")
        
        # Check if SL or TP was rejected
        if self._pending_sl_order_id and order_id == str(self._pending_sl_order_id):
            self.log.error(f"[CRITICAL] SL ORDER REJECTED - Position is UNPROTECTED!")
            _py_logger.error(f"[CRITICAL] SL ORDER REJECTED - UNPROTECTED POSITION!")
            self._sl_order_verified = False
        
        if self._pending_tp_order_id and order_id == str(self._pending_tp_order_id):
            self.log.error(f"[CRITICAL] TP ORDER REJECTED - Position has no take profit!")
            _py_logger.error(f"[CRITICAL] TP ORDER REJECTED!")
            self._tp_order_verified = False
    
    def on_order_canceled(self, event) -> None:
        """Handle order canceled event - detect unexpected cancellations."""
        order_id = str(event.client_order_id)
        
        # Check if our protection orders were unexpectedly canceled
        if self._pending_sl_order_id and order_id == str(self._pending_sl_order_id):
            # Check if we still have a position
            position = self.cache.position(self.instrument_id)
            if position and position.quantity > 0:
                self.log.error(f"[CRITICAL] SL ORDER CANCELED while position open - UNPROTECTED!")
                _py_logger.error(f"[CRITICAL] SL canceled - position UNPROTECTED!")
                self._sl_order_verified = False
        
        if self._pending_tp_order_id and order_id == str(self._pending_tp_order_id):
            position = self.cache.position(self.instrument_id)
            if position and position.quantity > 0:
                self.log.warning(f"[WARNING] TP ORDER CANCELED while position open")
                _py_logger.warning(f"[WARNING] TP canceled while position open")
                self._tp_order_verified = False
        
    def on_position_opened(self, event) -> None:
        """Handle position opened event."""
        self.log.info(f"Position opened: {event}")
    
    def on_position_closed(self, event) -> None:
        """Handle position closed event - cancel any orphaned SL/TP orders."""
        self.log.info(f"Position closed: {event}")
        
        # CRITICAL: Cancel any remaining SL/TP orders to prevent orphan orders
        # from opening unwanted positions
        try:
            open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
            sl_tag = f"{self._order_id_tag}_SL"
            tp_tag = f"{self._order_id_tag}_TP"
            
            for order in open_orders:
                tags = getattr(order, "tags", []) or []
                tag_str = str(tags)
                
                if sl_tag in tag_str or tp_tag in tag_str:
                    self.cancel_order(order)
                    self.log.info(f"Cancelled orphan order on position close: {order.client_order_id}")
            
            # Reset state
            self._current_stop_order = None
            self._current_tp_order = None
            self._position_entry_price = None
            self._position_atr = None
            self._trailing_active = False
            self._multi_layer_closed = []
            self._initial_position_size = None
            self._tp_price = None
            self._sl_order_verified = False
            self._tp_order_verified = False
            self._pending_sl_order_id = None
            self._pending_tp_order_id = None
            
        except Exception as e:
            self.log.error(f"Failed to cancel orphan orders on position close: {e}")
        
    def _calculate_features(self) -> Optional[np.ndarray]:
        """
        Calculate MTF features using pandas-ta.
        MUST match train_model_mtf.py features.
        
        Features (10 total):
        1. log_ret (15m)
        2. mama_diff (15m, hl2 source)
        3. dmp_30m
        4. dmn_30m
        5. stoch_k_30m
        6. stoch_d_30m
        7. wma_diff_30m
        8. atr (15m)
        9. hour
        10. day_of_week
        """
        # Need enough bars for both timeframes
        # Use minimum thresholds instead of full buffer requirement
        if len(self.bars_buffer_15m) < self._min_warmup_bars_15m:
            return None
        if len(self.bars_buffer_30m) < self._min_warmup_bars_30m:
            return None
            
        # Create 15m DataFrame
        data_15m = {
            'close': [float(b.close) for b in self.bars_buffer_15m],
            'high': [float(b.high) for b in self.bars_buffer_15m],
            'low': [float(b.low) for b in self.bars_buffer_15m],
            'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer_15m]
        }
        df_15m = pd.DataFrame(data_15m)
        df_15m = df_15m.loc[~df_15m.index.duplicated(keep='first')]
        df_15m.set_index('timestamp', inplace=True)
        
        # Create 30m DataFrame
        data_30m = {
            'close': [float(b.close) for b in self.bars_buffer_30m],
            'high': [float(b.high) for b in self.bars_buffer_30m],
            'low': [float(b.low) for b in self.bars_buffer_30m],
            'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer_30m]
        }
        df_30m = pd.DataFrame(data_30m)
        df_30m = df_30m.loc[~df_30m.index.duplicated(keep='first')]
        df_30m.set_index('timestamp', inplace=True)
        
        try:
            # === 15m Features ===
            # 1. Log Returns
            df_15m['log_ret'] = np.log(df_15m['close'] / df_15m['close'].shift(1)) * 100
            
            # 2. HL2 (LazyBear MAMA source)
            df_15m['hl2'] = (df_15m['high'] + df_15m['low']) / 2
            
            # 3. Ehlers MAMA using hl2
            mama_fama = ta.mama(df_15m['hl2'], fast=0.5, slow=0.05)
            if mama_fama is None:
                self.log.warning(f"MAMA returned None with {len(df_15m)} bars")
                return None
            df_15m['mama'] = mama_fama.iloc[:, 0]
            df_15m['fama'] = mama_fama.iloc[:, 1]
            df_15m['mama_diff'] = (df_15m['mama'] - df_15m['fama']) / df_15m['close']
            
            # 4. ATR (15m)
            df_15m['atr'] = ta.atr(df_15m['high'], df_15m['low'], df_15m['close'], length=14) / df_15m['close']
            
            # 5. Time Features
            df_15m['hour'] = df_15m.index.hour
            df_15m['day_of_week'] = df_15m.index.dayofweek
            
            # === 30m Features ===
            # 1. DMI
            dmi_30m = ta.adx(df_30m['high'], df_30m['low'], df_30m['close'], length=14)
            if dmi_30m is None:
                self.log.warning(f"DMI returned None with {len(df_30m)} bars")
                return None
            df_30m['dmp'] = dmi_30m.iloc[:, 1] / 100.0
            df_30m['dmn'] = dmi_30m.iloc[:, 2] / 100.0
            
            # 2. Stochastic (30m)
            stoch_30m = ta.stoch(df_30m['high'], df_30m['low'], df_30m['close'], k=14, d=3, smooth_k=3)
            if stoch_30m is None:
                self.log.warning(f"Stochastic returned None with {len(df_30m)} bars")
                return None
            df_30m['stoch_k'] = stoch_30m.iloc[:, 0] / 100.0
            df_30m['stoch_d'] = stoch_30m.iloc[:, 1] / 100.0
            
            # 3. WMA Difference (30m)
            wma_short = ta.wma(df_30m['close'], length=8)
            wma_long = ta.wma(df_30m['close'], length=23)
            if wma_short is not None and wma_long is not None:
                df_30m['wma_diff'] = 100 * (wma_short - wma_long) / wma_long
            else:
                self.log.warning("WMA calculation failed")
                return None
            
            # Get latest values
            latest_15m = df_15m.iloc[-1]
            latest_30m = df_30m.iloc[-1]
            
            # Feature order MUST match training:
            # ['log_ret', 'mama_diff', 'dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m', 'atr', 'hour', 'day_of_week']
            features = np.array([
                latest_15m['log_ret'],
                latest_15m['mama_diff'],
                latest_30m['dmp'],
                latest_30m['dmn'],
                latest_30m['stoch_k'],
                latest_30m['stoch_d'],
                latest_30m['wma_diff'],
                latest_15m['atr'],
                latest_15m['hour'],
                latest_15m['day_of_week']
            ]).reshape(1, -1)
            
            # Check for NaNs
            if np.isnan(features).any():
                self.log.warning("NaN values in calculated features")
                return None
                
            return features
            
        except Exception as e:
            self.log.error(f"Feature calculation error: {str(e)}")
            return None
        
    def _is_trading_session(self, bar_timestamp: int) -> tuple[bool, str]:
        """Check if we're in valid trading hours.
        
        Returns:
            tuple: (is_valid, reason) - reason is empty string if valid
        """
        # Convert nanosecond timestamp to datetime
        bar_time = pd.Timestamp(bar_timestamp, unit='ns', tz='UTC')
        
        # Get time object
        time_obj = bar_time.time()
        
        # Session window check removed - now trading 24/7
        # Only using excluded hours for time filtering
        
        # Check general excluded hours
        if self.excluded_hours and bar_time.hour in self.excluded_hours:
            return False, f"Hour {bar_time.hour} in general exclusion list"
        
        # Check weekday-specific excluded hours
        weekday = bar_time.dayofweek  # Monday=0, Sunday=6
        if weekday in self.excluded_hours_by_weekday:
            excluded_for_day = self.excluded_hours_by_weekday[weekday]
            if bar_time.hour in excluded_for_day:
                weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                return False, f"Hour {bar_time.hour} excluded for {weekday_names[weekday]}"
            
        return True, ""
        
    def _resample_to_30m(self) -> None:
        """Resample 15m bars to 30m bars."""
        if len(self.bars_buffer_15m) < 2:
            return
        
        # Convert to DataFrame
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
        
        # Resample to 30m
        df_30m = df.resample('30min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        # Clear 30m buffer and repopulate (simplified approach)
        # In production, you'd want to only add new 30m bars
        old_30m_count = len(self.bars_buffer_30m)
        self.bars_buffer_30m.clear()
        for idx, row in df_30m.iterrows():
            # Create a pseudo-bar object (we only need OHLC values)
            class SimpleBar:
                def __init__(self, o, h, l, c, ts):
                    self.open = o
                    self.high = h
                    self.low = l
                    self.close = c
                    self.volume = 0
                    self.ts_init = ts
            
            bar_30m = SimpleBar(row['open'], row['high'], row['low'], row['close'], int(idx.value))
            self.bars_buffer_30m.append(bar_30m)
        
        # Log resampling result every 10 bars or when count changes significantly
        new_30m_count = len(self.bars_buffer_30m)
        if new_30m_count != old_30m_count or len(self.bars_buffer_15m) <= 10:
            print(f"[RESAMPLE] 15m bars: {len(self.bars_buffer_15m)} -> 30m bars: {new_30m_count}")
    
    def on_bar(self, bar: Bar) -> None:
        """Process incoming 15m bar data and generate trading signals."""
        # DIAGNOSTIC: Log every bar received
        bar_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        print(f"[BAR] {bar_time.strftime('%Y-%m-%d %H:%M')} | close={bar.close} | 15m_buf={len(self.bars_buffer_15m)} | 30m_buf={len(self.bars_buffer_30m)}")
        _py_logger.info(f"[BAR] {bar_time} close={bar.close} 15m={len(self.bars_buffer_15m)} 30m={len(self.bars_buffer_30m)}")
        
        # Skip if model not loaded yet (but allow warmup mode for historical backfill)
        if self.model is None and not self._warmup_mode:
            _py_logger.warning(f"Skipping bar: model is None and warmup mode is False")
            return
            
        # Log first few bars with buffer status
        if len(self.bars_buffer_15m) < 5:
            self.log.info(
                f"Received {bar.bar_type.spec} bar: {bar.ts_init}, close={bar.close} "
                f"[Buffer: {len(self.bars_buffer_15m)}/{self.bars_buffer_15m.maxlen}, "
                f"30m: {len(self.bars_buffer_30m)}/{self.bars_buffer_30m.maxlen}]"
            )
        
        # Skip if outside trading session (but not during warmup)
        if not self._warmup_mode:
            is_valid, exclusion_reason = self._is_trading_session(bar.ts_init)
            if not is_valid:
                # Log exclusion reason (but not too frequently)
                if len(self.bars_buffer_15m) % 10 == 0:  # Log every 10th bar
                    self.log.info(f"Bar excluded: {exclusion_reason}")
                return
            
        # Update 15m buffer
        self.bars_buffer_15m.append(bar)
        
        # Resample to 30m
        self._resample_to_30m()
        
        # Wait for enough bars in both timeframes
        # Check if we have minimum viable bars (for weekends/gaps) or full warmup
        bars_15m_count = len(self.bars_buffer_15m)
        bars_30m_count = len(self.bars_buffer_30m)
        
        has_min_bars = (bars_15m_count >= self._min_warmup_bars_15m and 
                        bars_30m_count >= self._min_warmup_bars_30m)
        has_full_bars = (bars_15m_count >= self.bars_buffer_15m.maxlen and 
                         bars_30m_count >= self.bars_buffer_30m.maxlen)
        
        if not has_min_bars:
            # Not even minimum bars - definitely need to wait
            # Log EVERY bar during warmup so user can see progress
            need_15m = max(0, self._min_warmup_bars_15m - bars_15m_count)
            need_30m = max(0, self._min_warmup_bars_30m - bars_30m_count)
            self.log.info(
                f"[WARMUP] 15m: {bars_15m_count}/{self._min_warmup_bars_15m}, "
                f"30m: {bars_30m_count}/{self._min_warmup_bars_30m} "
                f"(need {need_15m} more 15m, {need_30m} more 30m)"
            )
            _py_logger.info(
                f"[WARMUP] 15m: {bars_15m_count}/{self._min_warmup_bars_15m}, "
                f"30m: {bars_30m_count}/{self._min_warmup_bars_30m}"
            )
            return
        
        # We have minimum bars - check if we should wait for full warmup or proceed
        if not has_full_bars and self._warmup_mode:
            # We have minimum but not full bars
            # After receiving all historical bars, IBKR switches to live streaming
            # Live bars come every 15 minutes, so we shouldn't wait if historical is done
            # Proceed with trading using available bars
            self.log.info(
                f"Partial warmup ready: {bars_15m_count}/{self.bars_buffer_15m.maxlen} bars "
                f"(min {self._min_warmup_bars_15m} met). Starting with available data."
            )
            _py_logger.info(
                f"Partial warmup: {bars_15m_count} bars available (min: {self._min_warmup_bars_15m}). "
                f"Proceeding with trading."
            )
        
        # Exit warmup mode once we have at least minimum bars
        if self._warmup_mode:
            self._warmup_mode = False
            warmup_status = "FULL" if has_full_bars else "PARTIAL"
            self.log.info("=" * 80)
            self.log.info(f"WARMUP COMPLETE ({warmup_status}) - Strategy ready to trade")
            self.log.info(f"Buffers: {bars_15m_count} bars (15m), {bars_30m_count} bars (30m)")
            self.log.info("Session filters now active")
            self.log.info("=" * 80)
            _py_logger.info(f"WARMUP COMPLETE ({warmup_status}) - Strategy ready to trade")
            
        # Check position limit before opening new positions
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        
        # Enforce position limit if configured
        if self.enforce_position_limit and len(positions) >= self.max_positions:
            if len(positions) == self.max_positions:
                # Log only when exactly at limit (avoid spam)
                if len(self.bars_buffer_15m) % 100 == 0:  # Log every 100 bars
                    self.log.debug(f"Position limit reached: {len(positions)}/{self.max_positions}")
        
        if positions:
            position = positions[0]
            
            # CRITICAL: Verify position has protection (SL/TP orders)
            if not self._sl_order_verified or not self._tp_order_verified:
                # Check if enough time has passed for orders to be confirmed
                # (give 30 seconds for order confirmation)
                open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
                sl_exists = any(f"{self._order_id_tag}_SL" in str(getattr(o, "tags", [])) for o in open_orders)
                tp_exists = any(f"{self._order_id_tag}_TP" in str(getattr(o, "tags", [])) for o in open_orders)
                
                if not sl_exists:
                    self.log.error(f"[UNPROTECTED] Position {position.side} {position.quantity} has NO SL ORDER!")
                    _py_logger.error(f"[UNPROTECTED] NO SL ORDER for {position.side} {position.quantity}!")
                if not tp_exists:
                    self.log.warning(f"[WARNING] Position {position.side} {position.quantity} has NO TP ORDER!")
                    _py_logger.warning(f"[WARNING] NO TP ORDER for {position.side} {position.quantity}!")
            
            # Check multi-layer exits on every bar
            if self.multi_layer_enabled:
                self._execute_multi_layer_close(position, bar)
            
            # Update trailing stop if enabled
            if self.trailing_stop_enabled:
                try:
                    self._update_trailing_stop(bar)
                except Exception as e:
                    self.log.error(f"Failed to update trailing stop: {e}")
            return
            
        # Skip predictions if model not loaded yet (during warmup)
        if self.model is None:
            return
        
        # Calculate features
        try:
            features = self._calculate_features()
            if features is None:
                if len(self.bars_buffer_15m) == self.bars_buffer_15m.maxlen:
                    self.log.warning(f"Feature calculation returned None despite having {len(self.bars_buffer_15m)} 15m bars")
                return
        except Exception as e:
            self.log.error(f"Feature calculation failed: {e}")
            return
        
        # Log successful feature calculation (first time only)
        if len(self.bars_buffer_15m) == self.bars_buffer_15m.maxlen:
            self.log.info("MTF features calculated successfully, starting predictions")
            
        # Update trailing stop if we have an open position
        if self.trailing_stop_enabled:
            self._update_trailing_stop(bar)
            
        # Get prediction probabilities
        try:
            probs = self.model.predict_proba(features.reshape(1, -1))[0]
            prediction = self.model.predict(features.reshape(1, -1))[0]
        except Exception as e:
            self.log.error(f"Model prediction failed: {e}")
            return
            
        # Get confidence (probability of predicted class)
        confidence = float(probs[1] if prediction == 1 else probs[0])
            
        # Get ATR (index 7 in MTF features)
        atr_normalized = float(features[0, 7])
        
        # Feature names for MTF
        feature_names = ['log_ret', 'mama_diff', 'dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m', 'atr', 'hour', 'day_of_week']
        
        # Log state (both NautilusTrader and Python logger for file capture)
        prediction_msg = (
            f"Bar {bar.ts_init}: prediction={prediction}, confidence={confidence:.3f}, "
            f"ATR={atr_normalized:.5f}, mama_diff={features[0,1]:.5f}, stoch_k_30m={features[0,4]:.3f}"
        )
        self.log.info(prediction_msg)
        _py_logger.info(f"[PREDICTION] {prediction_msg}")
        
        # SIGNAL FILTERING (log all filter reasons)
        bar_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        
        # DEBUG MODE: Skip all filters
        if self.debug_mode:
            self.log.warning(
                f"[DEBUG MODE] Bypassing all filters - forcing trade: prediction={prediction}, "
                f"confidence={confidence:.3f}, ATR={atr_normalized:.5f}"
            )
        else:
            # Filter 1: Confidence threshold
            if confidence < self.prediction_threshold:
                filter_msg = (
                    f"[FILTERED] Confidence too low: {confidence:.3f} < {self.prediction_threshold} "
                    f"(prediction={prediction}, time={bar_time.strftime('%Y-%m-%d %H:%M')})"
                )
                self.log.info(filter_msg)
                _py_logger.info(filter_msg)
                return
                
            # Filter 2: Minimum ATR (volatility)
            if atr_normalized < self._min_atr:
                filter_msg = (
                    f"[FILTERED] ATR too low: {atr_normalized:.5f} < {self._min_atr:.5f} "
                    f"(prediction={prediction}, confidence={confidence:.3f}, time={bar_time.strftime('%Y-%m-%d %H:%M')})"
                )
                self.log.info(filter_msg)
                _py_logger.info(filter_msg)
                return
                
            # Filter 3: Cooldown period (prevent overtrading)
            if self._last_trade_time is not None:
                current_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
                time_since_last = current_time - self._last_trade_time
                if time_since_last < self._trade_cooldown:
                    filter_msg = (
                        f"[FILTERED] Cooldown active: {time_since_last} < {self._trade_cooldown} "
                        f"(prediction={prediction}, confidence={confidence:.3f}, time={bar_time.strftime('%Y-%m-%d %H:%M')})"
                    )
                    self.log.info(filter_msg)
                    _py_logger.info(filter_msg)
                    return
        
        # NO TREND FILTERS - Let ML handle whipsaws via 30m context
        
        # CRITICAL: Check if we already have a position (prevent multiple entries)
        if not self.portfolio.is_flat(self.instrument_id):
            # We already have a position - don't open another
            positions = self.cache.positions_open(instrument_id=self.instrument_id)
            if positions:
                pos = positions[0]
                filter_msg = (
                    f"[FILTERED] Already in position: {pos.side.name} {pos.quantity} @ {pos.avg_px_open:.5f} "
                    f"(prediction={prediction}, confidence={confidence:.3f}, time={bar_time.strftime('%Y-%m-%d %H:%M')})"
                )
                self.log.info(filter_msg)
                _py_logger.info(filter_msg)
            return
        
        # CRITICAL: Check if we have ANY pending orders (prevent multiple order submissions)
        # This checks actual order state from cache, not a flag that can become stale
        open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
        if open_orders:
            self.log.info(
                f"[FILTERED] Already have {len(open_orders)} pending order(s) - waiting for fill "
                f"(prediction={prediction}, confidence={confidence:.3f}, time={bar_time.strftime('%Y-%m-%d %H:%M')})"
            )
            return
        
        # Execute trades based on prediction
        if prediction == 1:  # Buy signal
            _py_logger.info(f"[SIGNAL PASSED] LONG signal - prediction={prediction}, confidence={confidence:.3f}, ATR={atr_normalized:.5f}")
            self._execute_long(bar, atr_normalized, confidence)
            self._last_trade_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        else:  # prediction == 0, Sell signal
            _py_logger.info(f"[SIGNAL PASSED] SHORT signal - prediction={prediction}, confidence={confidence:.3f}, ATR={atr_normalized:.5f}")
            self._execute_short(bar, atr_normalized, confidence)
            self._last_trade_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
            
    def _execute_long(self, bar: Bar, atr_normalized: float, confidence: float) -> None:
        """Execute a long position with dynamic SL/TP based on ATR and confidence.
        
        Args:
            bar: Current bar
            atr_normalized: Normalized ATR value
            confidence: Model prediction confidence (0.0-1.0)
        """
        entry_price = Decimal(str(bar.close))
        
        # Use configured SL/TP multipliers (from optimized config)
        sl_mult = self.sl_atr_mult
        tp_mult = self.tp_atr_mult
        
        # Calculate ATR-based stops using normalized ATR
        sl_price = round(float(entry_price - Decimal(str(float(bar.close) * atr_normalized * sl_mult))), 5)
        tp_price = round(float(entry_price + Decimal(str(float(bar.close) * atr_normalized * tp_mult))), 5)
        
        # Create bracket order
        bracket_orders = self.order_factory.bracket(
            instrument_id=self.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self.position_size,
            sl_trigger_price=Price.from_str(str(sl_price)),
            tp_price=Price.from_str(str(tp_price)),
            tp_post_only=False,  # IBKR doesn't support post_only
            entry_tags=[self._order_id_tag],
            sl_tags=[f"{self._order_id_tag}_SL"],
            tp_tags=[f"{self._order_id_tag}_TP"]
        )
        
        # Submit orders
        self.submit_order_list(bracket_orders)
        
        # Track stop and TP orders for trailing/partial close management
        self._position_entry_price = entry_price
        self._position_atr = atr_normalized  # Store normalized ATR for trailing calculations
        self._trailing_active = False  # Reset trailing state
        self._initial_position_size = self.position_size  # Track initial size for multi-layer
        self._multi_layer_closed = []  # Reset multi-layer tracking
        self._tp_price = tp_price  # Store TP price for order recreation
        
        # Track orders for verification
        self._sl_order_verified = False
        self._tp_order_verified = False
        
        for order in bracket_orders.orders:
            if isinstance(order, StopMarketOrder):
                self._current_stop_order = order
                self._pending_sl_order_id = order.client_order_id
            elif isinstance(order, LimitOrder):
                self._current_tp_order = order
                self._pending_tp_order_id = order.client_order_id
                
        order_msg = (
            f"[ORDER] Long entry at {entry_price}, confidence={confidence:.3f}, "
            f"SL: {sl_price} ({self.sl_atr_mult}xATR), "
            f"TP: {tp_price} ({tp_mult:.2f}xATR), "
            f"Trailing: {'Enabled' if self.trailing_stop_enabled else 'Disabled'}"
        )
        self.log.info(order_msg)
        _py_logger.info(order_msg)
        _py_logger.info(f"[PENDING] SL order: {self._pending_sl_order_id}, TP order: {self._pending_tp_order_id}")
        
    def _execute_short(self, bar: Bar, atr_normalized: float, confidence: float) -> None:
        """Execute a short position with dynamic SL/TP based on ATR and confidence.
        
        Args:
            bar: Current bar
            atr_normalized: Normalized ATR value
            confidence: Model prediction confidence (0.0-1.0)
        """
        entry_price = float(bar.close)
        
        # Use configured SL/TP multipliers (from optimized config)
        sl_mult = self.sl_atr_mult
        tp_mult = self.tp_atr_mult
        
        # Calculate ATR-based stops using normalized ATR
        sl_price = round(entry_price + (entry_price * atr_normalized * sl_mult), 5)
        tp_price = round(entry_price - (entry_price * atr_normalized * tp_mult), 5)
        
        # Create bracket order
        bracket_orders = self.order_factory.bracket(
            instrument_id=self.instrument_id,
            order_side=OrderSide.SELL,
            quantity=self.position_size,
            sl_trigger_price=Price.from_str(f"{sl_price:.5f}"),
            tp_price=Price.from_str(f"{tp_price:.5f}"),
            tp_post_only=False,  # IBKR doesn't support post_only
            entry_tags=[self._order_id_tag],
            sl_tags=[f"{self._order_id_tag}_SL"],
            tp_tags=[f"{self._order_id_tag}_TP"]
        )
        
        # Submit orders
        self.submit_order_list(bracket_orders)
        
        # Track stop and TP orders for trailing/partial close management
        self._position_entry_price = entry_price
        self._position_atr = atr_normalized  # Store normalized ATR for trailing calculations
        self._trailing_active = False  # Reset trailing state
        self._initial_position_size = self.position_size  # Track initial size for multi-layer
        self._multi_layer_closed = []  # Reset multi-layer tracking
        self._tp_price = tp_price  # Store TP price for order recreation
        
        # Track orders for verification
        self._sl_order_verified = False
        self._tp_order_verified = False
        
        for order in bracket_orders.orders:
            if isinstance(order, StopMarketOrder):
                self._current_stop_order = order
                self._pending_sl_order_id = order.client_order_id
            elif isinstance(order, LimitOrder):
                self._current_tp_order = order
                self._pending_tp_order_id = order.client_order_id
                
        order_msg = (
            f"[ORDER] Short entry at {entry_price}, confidence={confidence:.3f}, "
            f"SL: {sl_price} ({self.sl_atr_mult}xATR), "
            f"TP: {tp_price} ({tp_mult:.2f}xATR), "
            f"Trailing: {'Enabled' if self.trailing_stop_enabled else 'Disabled'}"
        )
        self.log.info(order_msg)
        _py_logger.info(order_msg)
        _py_logger.info(f"[PENDING] SL order: {self._pending_sl_order_id}, TP order: {self._pending_tp_order_id}")
        
    def _execute_partial_close(self, position: Position, bar: Bar) -> None:
        """Execute partial position close."""
        if not self.partial_close_enabled or self._partial_close_done:
            return
            
        try:
            # Calculate quantity to close
            qty_to_close = position.quantity * Decimal(str(self.partial_close_fraction))
            
            # Create market order
            close_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
            reduce_order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=close_side,
                quantity=qty_to_close,
                tags=[f"{self._order_id_tag}_PARTIAL"]
            )
            
            # Submit order
            self.submit_order(reduce_order)
            self._partial_close_done = True
            
            # Move stop to breakeven if configured
            if self.partial_close_move_sl_to_be and self._current_stop_order:
                pip_value = Decimal("0.0001")  # For FX
                if position.side == OrderSide.BUY:
                    be_price = self._position_entry_price + pip_value
                else:
                    be_price = self._position_entry_price - pip_value
                    
                self.modify_order(
                    self._current_stop_order,
                    trigger_price=Price.from_str(str(be_price))
                )
                self._last_stop_price = be_price
                
            self.log.info(
                f"Partial close executed: {qty_to_close} units at {bar.close}, "
                f"moved SL to breakeven: {be_price}"
            )
            
        except Exception as e:
            self.log.error(f"Partial close failed: {e}")

    def _execute_multi_layer_close(self, position: Position, bar: Bar) -> None:
        """Execute multi-layer partial closes based on configured triggers."""
        if not self.multi_layer_enabled or not self._initial_position_size:
            return
        
        # Safety check - ensure entry price is set
        if self._position_entry_price is None:
            # Try to restore from position
            self._position_entry_price = float(position.avg_px_open)
            self._position_atr = 0.0003  # Default estimate
            self.log.warning(f"Restored missing entry_price from position: {self._position_entry_price}")
            return  # Wait for next bar to execute
        
        # CRITICAL: Only process ONE layer per bar to prevent race conditions
        # When multiple layers trigger simultaneously, position.quantity is stale
        layer_closed_this_bar = False
        
        # Check each layer
        for layer_idx in range(self.multi_layer_count):
            # Skip if already closed
            if layer_idx in self._multi_layer_closed:
                continue
            
            # CRITICAL: Only one layer per bar
            if layer_closed_this_bar:
                self.log.info(f"Layer {layer_idx+1} deferred - only one layer per bar allowed")
                break
            
            # Get trigger for this layer
            trigger = self.multi_layer_triggers[layer_idx]
            
            # Skip "final" layers (exit via SL/TP/trailing)
            if trigger == "final":
                continue
            
            # Check if trigger condition is met
            should_close = False
            trigger_price = None
            
            if position.side == PositionSide.LONG:
                current_price = float(bar.close)
                entry_price = float(self._position_entry_price)
                
                if trigger == 0.0:
                    # Breakeven trigger
                    should_close = current_price >= entry_price
                    trigger_price = entry_price
                else:
                    # ATR-based profit trigger (ATR in price terms = price × normalized_atr)
                    atr_distance = entry_price * self._position_atr * trigger
                    target_price = entry_price + atr_distance
                    should_close = current_price >= target_price
                    trigger_price = target_price
                    
            else:  # SHORT
                current_price = float(bar.close)
                entry_price = float(self._position_entry_price)
                
                if trigger == 0.0:
                    # Breakeven trigger
                    should_close = current_price <= entry_price
                    trigger_price = entry_price
                else:
                    # ATR-based profit trigger (ATR in price terms = price × normalized_atr)
                    atr_distance = entry_price * self._position_atr * trigger
                    target_price = entry_price - atr_distance
                    should_close = current_price <= target_price
                    trigger_price = target_price
            
            # Execute layer close if triggered
            if should_close:
                try:
                    # Calculate layer size
                    layer_fraction = self.multi_layer_sizes[layer_idx]
                    qty_decimal = self._initial_position_size * Decimal(str(layer_fraction))
                    
                    # Ensure we don't close more than current position
                    if qty_decimal > Decimal(str(position.quantity)):
                        qty_decimal = Decimal(str(position.quantity))
                    
                    # Convert to Quantity object (required by NautilusTrader)
                    qty_to_close = Quantity.from_str(str(int(qty_decimal)))
                    
                    # Create market order
                    close_side = OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
                    reduce_order = self.order_factory.market(
                        instrument_id=self.instrument_id,
                        order_side=close_side,
                        quantity=qty_to_close,
                        tags=[f"{self._order_id_tag}_LAYER{layer_idx+1}"]
                    )
                    
                    # Submit order
                    self.submit_order(reduce_order)
                    self._multi_layer_closed.append(layer_idx)
                    layer_closed_this_bar = True  # Prevent multiple layers on same bar
                    
                    self.log.info(
                        f"Multi-layer close executed: Layer {layer_idx+1}/{self.multi_layer_count}, "
                        f"{qty_decimal:.0f} units ({layer_fraction*100:.0f}%) at {bar.close}, "
                        f"trigger={trigger} ATR (target={trigger_price:.5f})"
                    )
                    
                    # CRITICAL: Cancel and recreate TP and SL orders with reduced quantity
                    # Use OCA (One-Cancels-All) group to maintain OCO behavior
                    # Calculate remaining based on INITIAL size minus ALL closed layers (not stale position.quantity)
                    total_closed = sum(self.multi_layer_sizes[i] for i in self._multi_layer_closed)
                    remaining_fraction = Decimal(str(1.0 - total_closed))
                    remaining_qty = self._initial_position_size * remaining_fraction
                    if remaining_qty > 0 and self._current_tp_order and self._current_stop_order and self._tp_price:
                        try:
                            # Generate unique OCA group name for this layer
                            import time as time_module
                            oca_group = f"{self._order_id_tag}_OCA_{int(time_module.time())}"
                            
                            # Get current SL price (and adjust to breakeven if needed)
                            current_sl_price = float(self._current_stop_order.trigger_price)
                            if layer_idx == 0 and self.multi_layer_move_sl_to_be:
                                pip_value = 0.0001  # For FX
                                if position.side == PositionSide.LONG:
                                    current_sl_price = float(self._position_entry_price) + pip_value
                                else:
                                    current_sl_price = float(self._position_entry_price) - pip_value
                                self.log.info(f"Moving SL to breakeven: {current_sl_price:.5f}")
                            
                            # Cancel current TP and SL orders
                            self.cancel_order(self._current_tp_order)
                            self.cancel_order(self._current_stop_order)
                            self.log.info(f"Cancelled old TP and SL orders for OCA recreation")
                            
                            # Create new TP order with OCA group
                            tp_side = OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
                            new_tp_qty = Quantity.from_str(str(int(remaining_qty)))
                            new_tp_order = self.order_factory.limit(
                                instrument_id=self.instrument_id,
                                order_side=tp_side,
                                quantity=new_tp_qty,
                                price=Price.from_str(f"{self._tp_price:.5f}"),
                                reduce_only=True,
                                tags=[f"{self._order_id_tag}_TP", f"ocaGroup:{oca_group}", "ocaType:1"]
                            )
                            
                            # Create new SL order with same OCA group
                            sl_side = OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
                            new_sl_qty = Quantity.from_str(str(int(remaining_qty)))
                            new_sl_order = self.order_factory.stop_market(
                                instrument_id=self.instrument_id,
                                order_side=sl_side,
                                quantity=new_sl_qty,
                                trigger_price=Price.from_str(f"{current_sl_price:.5f}"),
                                reduce_only=True,
                                tags=[f"{self._order_id_tag}_SL", f"ocaGroup:{oca_group}", "ocaType:1"]
                            )
                            
                            # Submit both orders
                            self.submit_order(new_tp_order)
                            self.submit_order(new_sl_order)
                            
                            self._current_tp_order = new_tp_order
                            self._current_stop_order = new_sl_order
                            self._last_stop_price = current_sl_price
                            
                            self.log.info(
                                f"Created OCA group {oca_group}: "
                                f"TP={new_tp_qty}@{self._tp_price:.5f}, SL={new_sl_qty}@{current_sl_price:.5f}"
                            )
                        except Exception as oca_err:
                            self.log.error(f"Failed to create OCA orders: {oca_err}")
                    
                except Exception as e:
                    self.log.error(f"Multi-layer close failed for layer {layer_idx+1}: {e}")

    def _update_trailing_stop(self, bar: Bar) -> None:
        """Update trailing stop loss based on current price movement.
        
        Activation: When profit >= trailing_activation_atr_mult × ATR
        Distance: Trail at trailing_distance_atr_mult × ATR behind price
        """
        # Check if we have an open position for this instrument
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        if not positions:
            # Reset state when no position
            self._trailing_active = False
            self._position_entry_price = None
            self._position_atr = None
            self._last_stop_price = None
            return
        
        # Get the first position (we only allow 1 position per instrument)
        position = positions[0]
        
        # Need entry price and ATR to calculate trailing
        if self._position_entry_price is None or self._position_atr is None:
            return
        
        current_price = float(bar.close)
        entry_price = float(self._position_entry_price)
        # Convert normalized ATR to price terms
        atr_price = entry_price * self._position_atr
        
        # Calculate current profit in ATR units
        if position.side == PositionSide.LONG:
            profit_atr = (current_price - entry_price) / atr_price
        else:  # SHORT
            profit_atr = (entry_price - current_price) / atr_price
        
        # Check if we should activate trailing
        if not self._trailing_active and profit_atr >= self.trailing_activation_atr_mult:
            self._trailing_active = True
            self.log.info(
                f"Trailing stop activated: profit={profit_atr:.2f}×ATR "
                f"(threshold={self.trailing_activation_atr_mult}×ATR)"
            )
        
        # Update trailing stop if active
        if self._trailing_active:
            # Find current active stop order
            sl_tag = f"{self._order_id_tag}_SL"
            active_statuses = {"PENDING_SUBMIT", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"}
            
            # First try orders_open()
            open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
            current_stop_order = None
            
            for order in open_orders:
                if not isinstance(order, StopMarketOrder):
                    continue
                    
                tags = getattr(order, "tags", []) or []
                has_sl_tag = any(sl_tag in str(tag) for tag in tags)
                status_name = getattr(order.status, "name", str(order.status))
                
                if has_sl_tag and status_name in active_statuses:
                    current_stop_order = order
                    break
            
            if not current_stop_order:
                self.log.warning("No active stop order found, skipping trailing update")
                return
            
            # Update tracked order reference
            self._current_stop_order = current_stop_order
            
            # Calculate trail distance using normalized ATR and current price
            trail_distance = current_price * self._position_atr * self.trailing_distance_atr_mult
            
            if position.side == PositionSide.LONG:
                # For long: trail below current price
                new_stop_price = current_price - trail_distance
                
                # Only move stop up, never down
                current_stop = float(current_stop_order.trigger_price)
                
                if new_stop_price > current_stop:
                    try:
                        self.modify_order(
                            current_stop_order,
                            trigger_price=Price.from_str(f"{new_stop_price:.5f}")
                        )
                        self._last_stop_price = new_stop_price
                        self.log.info(
                            f"Trailing stop updated: {current_stop:.5f} → {new_stop_price:.5f} "
                            f"(trailing {self.trailing_distance_atr_mult}×ATR behind price)"
                        )
                    except Exception as e:
                        self.log.error(f"Failed to update trailing stop: {e}")
            
            else:  # SHORT
                # For short: trail above current price
                new_stop_price = current_price + trail_distance
                
                # Only move stop down, never up
                current_stop = float(current_stop_order.trigger_price)
                
                if new_stop_price < current_stop:
                    try:
                        self.modify_order(
                            current_stop_order,
                            trigger_price=Price.from_str(f"{new_stop_price:.5f}")
                        )
                        self._last_stop_price = new_stop_price
                        self.log.info(
                            f"Trailing stop updated: {current_stop:.5f} → {new_stop_price:.5f} "
                            f"(trailing {self.trailing_distance_atr_mult}×ATR behind price)"
                        )
                    except Exception as e:
                        self.log.error(f"Failed to update trailing stop: {e}")
