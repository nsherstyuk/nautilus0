"""
Trailing stop update method for MLSignalStrategy.
This will be integrated into ml_strategy.py.
"""

def _update_trailing_stop(self, bar: Bar) -> None:
    """Update trailing stop loss based on current price movement.
    
    Activation: When profit >= trailing_activation_atr_mult × ATR
    Distance: Trail at trailing_distance_atr_mult × ATR behind price
    """
    # Check if we have an open position
    position = self.portfolio.position(self.instrument_id)
    if position is None or not position.is_open:
        # Reset state when no position
        self._trailing_active = False
        self._position_entry_price = None
        self._position_atr = None
        self._last_stop_price = None
        return
    
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
    if self._trailing_active and self._current_stop_order is not None:
        trail_distance = atr_price * self.trailing_distance_atr_mult
        
        if position.side == PositionSide.LONG:
            # For long: trail below current price
            new_stop_price = current_price - trail_distance
            
            # Only move stop up, never down
            current_stop = float(self._current_stop_order.trigger_price) if self._current_stop_order.trigger_price else entry_price - (atr_price * self.sl_atr_mult)
            
            if new_stop_price > current_stop:
                try:
                    self.modify_order(
                        self._current_stop_order,
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
            current_stop = float(self._current_stop_order.trigger_price) if self._current_stop_order.trigger_price else entry_price + (atr_price * self.sl_atr_mult)
            
            if new_stop_price < current_stop:
                try:
                    self.modify_order(
                        self._current_stop_order,
                        trigger_price=Price.from_str(f"{new_stop_price:.5f}")
                    )
                    self._last_stop_price = new_stop_price
                    self.log.info(
                        f"Trailing stop updated: {current_stop:.5f} → {new_stop_price:.5f} "
                        f"(trailing {self.trailing_distance_atr_mult}×ATR behind price)"
                    )
                except Exception as e:
                    self.log.error(f"Failed to update trailing stop: {e}")
