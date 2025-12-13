"""
Machine Learning-based trading strategy using trained Random Forest model.
Ensures feature calculation parity with research/train_model.py.
"""
from __future__ import annotations

import json
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
from nautilus_trader.model.orders import StopMarketOrder
from nautilus_trader.model.position import Position
from nautilus_trader.trading.strategy import Strategy

from strategies.ml_strategy_config import MLSignalStrategyConfig

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
        
        # Trading session
        self.session_start = datetime.strptime(config.session_start, "%H:%M").time()
        self.session_end = datetime.strptime(config.session_end, "%H:%M").time()
        self.excluded_hours = config.excluded_hours
        
        # Initialize state
        self.model = None
        self.bars_buffer: Deque[Bar] = deque(maxlen=config.feature_warmup_bars)
        
        # Order management state
        self._current_stop_order = None
        self._last_stop_price = None
        self._position_entry_price = None
        self._position_atr = None  # ATR at entry for trailing calculations
        self._trailing_active = False
        self._partial_close_done = False
        
        # Trade management
        self._last_trade_time = None
        self._trade_cooldown = pd.Timedelta(minutes=30)  # Wait 30 minutes between trades
        self._min_atr = 0.0003  # Minimum ATR to trade (30 pips)
        
    def on_start(self) -> None:
        """Initialize strategy and load ML model."""
        # Get instrument
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Unknown instrument {self.instrument_id}")
            return
            
        # Load model
        try:
            model_path = Path(self.model_path)
            if not model_path.is_absolute():
                # Use project root to resolve relative paths
                project_root = Path(__file__).parent.parent
                model_path = project_root / model_path
            
            if not model_path.exists():
                self.log.error(f"Model file not found: {model_path}")
                return
                
            self.model = load(model_path)
            self.log.info(f"Loaded model from {model_path}")
        except Exception as e:
            self.log.error(f"Failed to load model: {e}")
            return
            
        # Register data stream
        self.subscribe_bars(self.bar_type)
        self.log.info("Strategy initialized successfully")
        
    def _calculate_features(self, bar: Bar) -> Optional[np.ndarray]:
        """
        Calculate technical features for the model.
        MUST match the features used in training (train_model.py).
        
        Features:
        1. Log Returns
        2. MAMA Difference (Normalized)
        3. ADX (Normalized)
        4. DMP (Normalized)
        5. DMN (Normalized)
        6. Stochastic K (Normalized)
        7. Stochastic D (Normalized)
        8. ATR (Normalized)
        9. Hour (0-23)
        10. Day of Week (0-6)
        """
        # Note: bar is already added to bars_buffer in on_bar()
        
        # Need enough bars for calculation
        # MAMA needs warmup, ADX needs 14, Stoch needs 14
        if len(self.bars_buffer) < self.bars_buffer.maxlen:
            return None
            
        # Create DataFrame
        data = {
            'close': [float(b.close) for b in self.bars_buffer],
            'high': [float(b.high) for b in self.bars_buffer],
            'low': [float(b.low) for b in self.bars_buffer],
            'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer]
        }
        df = pd.DataFrame(data)
        df = df.loc[~df.index.duplicated(keep='first')]  # Remove duplicate timestamps
        df.set_index('timestamp', inplace=True)
        
        try:
            # 1. Log Returns
            df['log_ret'] = np.log(df['close'] / df['close'].shift(1)) * 100
            
            # 2. Ehlers MAMA (fast=0.5, slow=0.05)
            mama_fama = ta.mama(df['close'], fast=0.5, slow=0.05)
            if mama_fama is None:
                self.log.warning(f"MAMA returned None with {len(df)} bars")
                return None
            # Access by position as names can vary
            df['mama'] = mama_fama.iloc[:, 0]
            df['fama'] = mama_fama.iloc[:, 1]
            df['mama_diff'] = (df['mama'] - df['fama']) / df['close']
            
            # 3. DMI (ADX, DMP, DMN)
            dmi = ta.adx(df['high'], df['low'], df['close'], length=14)
            if dmi is None:
                self.log.warning(f"DMI returned None with {len(df)} bars")
                return None
            # ADX_14, DMP_14, DMN_14
            df['adx'] = dmi.iloc[:, 0] / 100.0
            df['dmp'] = dmi.iloc[:, 1] / 100.0
            df['dmn'] = dmi.iloc[:, 2] / 100.0
            
            # 4. Stochastic (14, 3, 3)
            stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
            if stoch is None:
                self.log.warning(f"Stochastic returned None with {len(df)} bars")
                return None
            # STOCHk_14_3_3, STOCHd_14_3_3
            df['stoch_k'] = stoch.iloc[:, 0] / 100.0
            df['stoch_d'] = stoch.iloc[:, 1] / 100.0
            
            # 5. ATR
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
            
            # 6. Time Features (extract from DatetimeIndex)
            df['hour'] = df.index.hour
            df['day_of_week'] = df.index.dayofweek
            
            # Select features for latest bar
            # Order MUST match training: 
            # ['log_ret', 'mama_diff', 'adx', 'dmp', 'dmn', 'stoch_k', 'stoch_d', 'atr', 'hour', 'day_of_week']
            latest = df.iloc[-1]
            features = np.array([
                latest['log_ret'],
                latest['mama_diff'],
                latest['adx'],
                latest['dmp'],
                latest['dmn'],
                latest['stoch_k'],
                latest['stoch_d'],
                latest['atr'],
                latest['hour'],
                latest['day_of_week']
            ]).reshape(1, -1)
            
            # Check for NaNs
            if np.isnan(features).any():
                self.log.warning("NaN values in calculated features")
                return None
                
            return features
            
        except Exception as e:
            self.log.error(f"Feature calculation error: {str(e)}")
            return None
        
    def _is_trading_session(self, bar_timestamp: int) -> bool:
        """Check if we're in valid trading hours."""
        # Convert nanosecond timestamp to datetime
        bar_time = pd.Timestamp(bar_timestamp, unit='ns', tz='UTC')
        
        # Get time object
        time_obj = bar_time.time()
        
        # Check session window
        in_session = self.session_start <= time_obj <= self.session_end
        
        # Check excluded hours
        if self.excluded_hours and bar_time.hour in self.excluded_hours:
            return False
            
        return in_session
        
    def on_bar(self, bar: Bar) -> None:
        """Process incoming bar data and generate trading signals."""
        # Log first few bars to confirm we're receiving data
        if len(self.bars_buffer) < 5:
            self.log.info(f"Received bar: {bar.ts_init}, close={bar.close}")
        
        # Skip if outside trading session
        if not self._is_trading_session(bar.ts_init):
            return
            
        # Update buffer
        self.bars_buffer.append(bar)
        
        # Wait for enough bars
        if len(self.bars_buffer) < self.bars_buffer.maxlen:
            return
            
        # Don't open new positions if we already have one
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        if positions:
            # Update trailing stop if enabled
            if self.trailing_stop_enabled:
                self._update_trailing_stop(bar)
            return
            
        # Calculate features
        try:
            features = self._calculate_features(bar)
            if features is None:
                if len(self.bars_buffer) == self.bars_buffer.maxlen:
                    self.log.warning(f"Feature calculation returned None despite having {len(self.bars_buffer)} bars")
                return  # Not enough data yet
        except Exception as e:
            self.log.error(f"Feature calculation failed: {e}")
            return
        
        # Log successful feature calculation (first time only)
        if len(self.bars_buffer) == self.bars_buffer.maxlen:
            self.log.info("Features calculated successfully, starting predictions")
            
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
            
        # Get ATR
        atr_normalized = float(features[0, 7])
        
        # Log state
        self.log.info(
            f"Bar {bar.ts_init}: features={dict(zip(['log_ret', 'mama_diff', 'adx', 'dmp', 'dmn', 'stoch_k', 'stoch_d', 'atr', 'hour', 'day_of_week'], features))}, "
            f"prediction={prediction}, confidence={confidence:.3f}, probabilities={dict(zip([0, 1], probs))}"
        )
        
        # Check prediction confidence
        if confidence < self.prediction_threshold:
            return
            
        # Check ATR threshold
        if atr_normalized < self._min_atr:
            self.log.info(f"ATR {atr_normalized:.5f} below minimum {self._min_atr:.5f}, skipping trade")
            return
            
        # Check cooldown period
        if self._last_trade_time is not None:
            current_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
            time_since_last = current_time - self._last_trade_time
            if time_since_last < self._trade_cooldown:
                self.log.info(f"Cooldown active ({time_since_last} < {self._trade_cooldown}), skipping trade")
                return
            
        # Get trend indicators
        adx = float(features[0, 2])  # ADX at index 2
        dmp = float(features[0, 3])  # DM+ at index 3
        dmn = float(features[0, 4])  # DM- at index 4
        
        # Log trend state
        self.log.info(f"Trend indicators: ADX={adx*100:.1f}, DM+={dmp*100:.1f}, DM-={dmn*100:.1f}")
        
        # Calculate trend strength
        trend_strength = dmp - dmn
        
        # Only trade with strong trends
        strong_trend = adx > 0.30  # ADX is normalized (0-1)
        if not strong_trend:
            self.log.info(f"Skipping trade in weak trend (ADX={adx*100:.1f})")
            return
            
        # Get trend direction
        if dmp > dmn * 1.2:  # Bullish trend
            if prediction == 0:  # Sell signal against bullish trend
                self.log.info(f"Skipping short in bullish trend (DM+/DM- ratio: {dmp/dmn:.1f})")
                return
        elif dmn > dmp * 1.2:  # Bearish trend
            if prediction == 1:  # Buy signal against bearish trend
                self.log.info(f"Skipping long in bearish trend (DM-/DM+ ratio: {dmn/dmp:.1f})")
                return
        else:  # No clear trend
            self.log.info(f"Skipping trade in unclear trend (DM+/DM- ratio: {dmp/dmn:.1f})")
            return
            
        # Execute trades based on prediction
        if prediction == 1:  # Buy signal
            self._execute_long(bar, atr_normalized, confidence)
            self._last_trade_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        else:  # prediction == 0, Sell signal
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
        
        # Dynamic SL/TP multipliers based on confidence
        # High confidence: wider stops (2.0x ATR) and higher targets (3.0x ATR)
        # Low confidence: tighter stops (1.5x ATR) and lower targets (2.0x ATR)
        # Linear interpolation between min and max
        sl_mult = 1.5 + (confidence - 0.32) * (2.0 - 1.5) / (1.0 - 0.32)
        tp_mult = 2.0 + (confidence - 0.32) * (3.0 - 2.0) / (1.0 - 0.32)
        
        # Clamp multipliers
        sl_mult = max(1.5, min(2.0, sl_mult))
        tp_mult = max(2.0, min(3.0, tp_mult))
        
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
            entry_tags=[self._order_id_tag],
            sl_tags=[f"{self._order_id_tag}_SL"],
            tp_tags=[f"{self._order_id_tag}_TP"]
        )
        
        # Submit orders
        self.submit_order_list(bracket_orders)
        
        # Track stop order and entry state for trailing/partial close
        for order in bracket_orders.orders:
            if isinstance(order, StopMarketOrder):
                self._current_stop_order = order
                self._position_entry_price = entry_price
                self._position_atr = atr_normalized  # Store normalized ATR for trailing calculations
                self._trailing_active = False  # Reset trailing state
                break
                
        self.log.info(
            f"Long entry at {entry_price}, confidence={confidence:.3f}, "
            f"SL: {sl_price} ({self.sl_atr_mult}×ATR), "
            f"TP: {tp_price} ({tp_mult:.2f}×ATR), "
            f"Trailing: {'Enabled' if self.trailing_stop_enabled else 'Disabled'}"
        )
        
    def _execute_short(self, bar: Bar, atr_normalized: float, confidence: float) -> None:
        """Execute a short position with dynamic SL/TP based on ATR and confidence.
        
        Args:
            bar: Current bar
            atr_normalized: Normalized ATR value
            confidence: Model prediction confidence (0.0-1.0)
        """
        entry_price = float(bar.close)
        
        # Dynamic SL/TP multipliers based on confidence
        # High confidence: wider stops (2.0x ATR) and higher targets (3.0x ATR)
        # Low confidence: tighter stops (1.5x ATR) and lower targets (2.0x ATR)
        # Linear interpolation between min and max
        sl_mult = 1.5 + (confidence - 0.32) * (2.0 - 1.5) / (1.0 - 0.32)
        tp_mult = 2.0 + (confidence - 0.32) * (3.0 - 2.0) / (1.0 - 0.32)
        
        # Clamp multipliers
        sl_mult = max(1.5, min(2.0, sl_mult))
        tp_mult = max(2.0, min(3.0, tp_mult))
        
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
            entry_tags=[self._order_id_tag],
            sl_tags=[f"{self._order_id_tag}_SL"],
            tp_tags=[f"{self._order_id_tag}_TP"]
        )
        
        # Submit orders
        self.submit_order_list(bracket_orders)
        
        # Track stop order and entry state for trailing/partial close
        for order in bracket_orders.orders:
            if isinstance(order, StopMarketOrder):
                self._current_stop_order = order
                self._position_entry_price = entry_price
                self._position_atr = atr_normalized  # Store normalized ATR for trailing calculations
                self._trailing_active = False  # Reset trailing state
                break
                
        self.log.info(
            f"Short entry at {entry_price}, confidence={confidence:.3f}, "
            f"SL: {sl_price} ({self.sl_atr_mult}×ATR), "
            f"TP: {tp_price} ({tp_mult:.2f}×ATR), "
            f"Trailing: {'Enabled' if self.trailing_stop_enabled else 'Disabled'}"
        )
        
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

    def _update_trailing_stop(self, bar: Bar, position: Position, atr_normalized: float) -> None:
        """Update trailing stop and handle partial close."""
        if not self._current_stop_order or not self._position_entry_price:
            return
            
        # Calculate profit in pips
        pip_value = Decimal("0.0001")  # For FX
        current_price = Decimal(str(bar.close))
        entry_price = self._position_entry_price
        
        if position.side == OrderSide.BUY:
            profit_pips = float((current_price - entry_price) / pip_value)
        else:
            profit_pips = float((entry_price - current_price) / pip_value)
            
        # Calculate ATR-based activation threshold (using 1.0 multiplier as default)
        atr_price = atr_normalized * float(bar.close)
        activation_threshold = float(atr_price * 1.0)  # Activate after 1×ATR profit
        
        # Check if trailing should activate
        if not self._trailing_active and profit_pips > activation_threshold:
            self._trailing_active = True
            self.log.info(f"Trailing stop activated at +{profit_pips:.1f} pips")
            
            # Handle partial close on first activation
            if self.partial_close_enabled and not self._partial_close_done:
                self._execute_partial_close(position, bar)
                
        # Update trailing stop if active
        if self._trailing_active:
            trail_distance = float(atr_price * 0.8)  # Trail at 0.8×ATR
            
            if position.side == OrderSide.BUY:
                new_stop = current_price - Decimal(str(trail_distance))
                if self._last_stop_price is None or new_stop > self._last_stop_price:
                    self.modify_order(
                        self._current_stop_order,
                        trigger_price=Price.from_str(str(new_stop))
                    )
                    self._last_stop_price = new_stop
            else:
                new_stop = current_price + Decimal(str(trail_distance))
                if self._last_stop_price is None or new_stop < self._last_stop_price:
                    self.modify_order(
                        self._current_stop_order,
                        trigger_price=Price.from_str(str(new_stop))
                    )
                    self._last_stop_price = new_stop
    
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
        atr_price = self._position_atr
        
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
