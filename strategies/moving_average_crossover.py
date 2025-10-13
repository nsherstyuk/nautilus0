"""
Moving Average Crossover strategy for NautilusTrader.

This strategy uses two Simple Moving Averages (SMA) to generate
buy/sell signals on crossovers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple, cast

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.indicators import SimpleMovingAverage
from nautilus_trader.model.position import Position
from nautilus_trader.model.objects import Quantity, Price
from nautilus_trader.model.enums import OrderSide, TriggerType
from nautilus_trader.model.orders import MarketOrder, StopMarketOrder, LimitOrder, OrderList


_DEF_PRICE_ALIAS = {"MIDPOINT": "MID"}


def _normalize_price_alias(spec) -> str:
    """Normalize price type aliases (e.g., MIDPOINT -> MID) in bar spec string."""
    spec_str = str(spec)
    for alias, canonical in _DEF_PRICE_ALIAS.items():
        spec_str = spec_str.replace(f"-{alias}-", f"-{canonical}-")
    return spec_str


class MovingAverageCrossoverConfig(StrategyConfig, kw_only=True):
    instrument_id: str
    bar_spec: str
    fast_period: int = 10
    slow_period: int = 20
    trade_size: Decimal = Decimal("100")
    order_id_tag: str = "MA_CROSS"
    enforce_position_limit: bool = True
    allow_position_reversal: bool = False
    stop_loss_pips: int = 25
    take_profit_pips: int = 50
    trailing_stop_activation_pips: int = 20
    trailing_stop_distance_pips: int = 15
    crossover_threshold_pips: float = 0.7


class MovingAverageCrossover(Strategy):
    """A simple moving average crossover strategy."""

    def __init__(self, config: MovingAverageCrossoverConfig) -> None:
        super().__init__(config)

        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        # Ensure BarType string includes aggregation suffix exactly once
        bar_spec = config.bar_spec
        if not bar_spec.upper().endswith("-EXTERNAL") and not bar_spec.upper().endswith("-INTERNAL"):
            bar_spec = f"{bar_spec}-EXTERNAL"
        self.bar_type = BarType.from_str(f"{config.instrument_id}-{bar_spec}")

        self.fast_sma = SimpleMovingAverage(period=config.fast_period)
        self.slow_sma = SimpleMovingAverage(period=config.slow_period)

        self.trade_size: Decimal = Decimal(str(config.trade_size))
        self._prev_fast: Optional[Decimal] = None
        self._prev_slow: Optional[Decimal] = None
        self.instrument = None
        self._rejected_signals: List[Dict[str, Any]] = []
        self._enforce_position_limit = config.enforce_position_limit
        self._allow_reversal = config.allow_position_reversal
        self._bar_count = 0
        self._warmup_complete = False
        self._is_fx: bool = False
        
        # Trailing stop state tracking
        self._current_stop_order: Optional[StopMarketOrder] = None
        self._position_entry_price: Optional[Decimal] = None
        self._trailing_active: bool = False
        self._last_stop_price: Optional[Decimal] = None

    @property
    def cfg(self) -> MovingAverageCrossoverConfig:
        return cast(MovingAverageCrossoverConfig, self.config)

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument not found: {self.instrument_id}")
            self.stop()
            return

        # Detect FX instruments for pip-based SL/TP logic
        self._is_fx = "/" in self.instrument.raw_symbol.value
        if self._is_fx:
            self.log.info(f"FX instrument detected: {self.instrument.raw_symbol.value} - pip-based SL/TP enabled")
        else:
            self.log.info(f"Non-FX instrument detected: {self.instrument.raw_symbol.value} - pip-based SL/TP disabled")

        self.register_indicator_for_bars(self.bar_type, self.fast_sma)
        self.register_indicator_for_bars(self.bar_type, self.slow_sma)

        # Subscribe to bars; backtest engine streams bars from catalog
        self.subscribe_bars(self.bar_type)
        self.log.info(f"Strategy initialized for {self.instrument_id} @ {self.bar_type}")
        self.log.debug(
            f"Indicator configuration: fast_period={self.cfg.fast_period}, slow_period={self.cfg.slow_period}"
        )
        self.log.debug(
            f"Position limits enforced={self._enforce_position_limit}, allow_reversal={self._allow_reversal}"
        )

    def _current_position(self) -> Optional[Position]:
        """Get the current open position for this instrument."""
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        return positions[0] if positions else None

    def _check_can_open_position(self, signal_type: str) -> Tuple[bool, str]:
        if not self._enforce_position_limit:
            return True, ""

        # Evaluate the net position for this instrument; NETTING OMS ensures a single net side.
        position: Optional[Position] = self._current_position()

        if position is None:
            return True, ""

        current = position
        if self._allow_reversal:
            if signal_type == "BUY" and getattr(current, "is_short", False):
                return True, "reversal_allowed"
            if signal_type == "SELL" and getattr(current, "is_long", False):
                return True, "reversal_allowed"

        if signal_type == "BUY" and getattr(current, "is_short", False):
            return True, "close_only"
        if signal_type == "SELL" and getattr(current, "is_long", False):
            return True, "close_only"

        side = getattr(current, "side", "unknown")
        return False, f"Position already open: {side}"

    def _record_signal_event(self, signal_type: str, action: str, reason: str, bar: Bar) -> None:
        record = {
            "timestamp": bar.ts_event,
            "bar_close_time": bar.ts_init,
            "signal_type": signal_type,
            "action": action,
            "reason": reason,
            "fast_sma": self.fast_sma.value,
            "slow_sma": self.slow_sma.value,
        }
        self._rejected_signals.append(record)

    def _log_rejected_signal(self, signal_type: str, reason: str, bar: Bar) -> None:
        self._record_signal_event(signal_type, "rejected", reason, bar)
        self.log.info(
            f"REJECTED {signal_type} signal: {reason} | Fast SMA: {self.fast_sma.value}, Slow SMA: {self.slow_sma.value}"
        )

    def _log_close_only_event(self, signal_type: str, reason: str, bar: Bar) -> None:
        self._record_signal_event(signal_type, "close_only", reason, bar)
        self.log.info(
            f"CLOSE-ONLY {signal_type} signal: {reason} | Fast SMA: {self.fast_sma.value}, Slow SMA: {self.slow_sma.value}"
        )

    def get_rejected_signals(self) -> List[Dict[str, Any]]:
        return list(self._rejected_signals)

    def _check_crossover_threshold(self, direction: str, fast: Decimal, slow: Decimal, bar: Bar) -> bool:
        crossover_diff = abs(fast - slow)
        pip_value = self._calculate_pip_value()
        threshold_pips = Decimal(str(self.cfg.crossover_threshold_pips))
        threshold_price = threshold_pips * pip_value
        if crossover_diff < threshold_price:
            crossover_diff_decimal = Decimal(str(crossover_diff))
            crossover_diff_pips = crossover_diff_decimal / pip_value
            self._log_rejected_signal(
                direction,
                f"crossover_threshold_not_met (diff={crossover_diff_pips:.2f} pips < {threshold_pips} pips threshold)",
                bar,
            )
            return False
        return True

    def _calculate_pip_value(self) -> Decimal:
        """Calculate pip value based on instrument precision."""
        if self.instrument.price_precision == 5:
            return Decimal('0.0001')  # 1 pip for 5 decimal places (EUR/USD)
        elif self.instrument.price_precision == 3:
            return Decimal('0.01')     # 1 pip for 3 decimal places (USD/JPY)
        else:
            # For non-FX or other precisions, use the instrument's minimum tick/price increment
            return Decimal(str(self.instrument.price_increment))

    def _calculate_sl_tp_prices(self, entry_price: Decimal, order_side: OrderSide) -> Tuple[Price, Price]:
        """Calculate stop loss and take profit prices based on entry price and order side."""
        pip_value = self._calculate_pip_value()
        sl_pips = Decimal(str(self.cfg.stop_loss_pips))
        tp_pips = Decimal(str(self.cfg.take_profit_pips))
        
        if order_side == OrderSide.BUY:
            # For BUY orders: SL below entry, TP above entry
            sl_price = entry_price - (sl_pips * pip_value)
            tp_price = entry_price + (tp_pips * pip_value)
        else:
            # For SELL orders: SL above entry, TP below entry
            sl_price = entry_price + (sl_pips * pip_value)
            tp_price = entry_price - (tp_pips * pip_value)
        
        # Round to instrument's price increment and convert to Price objects
        price_increment = self.instrument.price_increment
        sl_price_rounded = (sl_price / price_increment).quantize(Decimal('1')) * price_increment
        tp_price_rounded = (tp_price / price_increment).quantize(Decimal('1')) * price_increment
        
        sl_price_obj = Price.from_str(str(sl_price_rounded))
        tp_price_obj = Price.from_str(str(tp_price_rounded))
        
        return sl_price_obj, tp_price_obj

    def _update_trailing_stop(self, bar: Bar) -> None:
        """Update trailing stop logic for open positions."""
        if not self._is_fx or not self._current_stop_order or not self._position_entry_price:
            return
        
        # Get current open position (NETTING ensures at most one)
        position: Optional[Position] = self._current_position()
        if position is None:
            if any([self._current_stop_order, self._trailing_active, self._last_stop_price, self._position_entry_price]):
                self.log.debug("No open position; resetting trailing stop state.")
            self._current_stop_order = None
            self._position_entry_price = None
            self._trailing_active = False
            self._last_stop_price = None
            return
        
        # Update entry price from the position (ensure it's a Decimal)
        self._position_entry_price = Decimal(str(position.avg_px_open))
        
        # Calculate current profit in pips
        current_price = Decimal(str(bar.close))
        pip_value = self._calculate_pip_value()
        
        if position.side.name == "LONG":
            profit_pips = (current_price - self._position_entry_price) / pip_value
        else:  # SHORT
            profit_pips = (self._position_entry_price - current_price) / pip_value
        
        # Check if we should activate trailing
        activation_threshold = Decimal(str(self.cfg.trailing_stop_activation_pips))
        if profit_pips >= activation_threshold and not self._trailing_active:
            self._trailing_active = True
            self.log.info(f"Trailing stop activated at +{profit_pips:.1f} pips profit")
        
        # Update trailing stop if active
        if self._trailing_active:
            trailing_distance = Decimal(str(self.cfg.trailing_stop_distance_pips))
            
            if position.side.name == "LONG":
                new_stop = current_price - (trailing_distance * pip_value)
                # For LONG: new stop must be higher (tighter) than last stop
                is_better = self._last_stop_price is None or new_stop > self._last_stop_price
            else:  # SHORT
                new_stop = current_price + (trailing_distance * pip_value)
                # For SHORT: new stop must be lower (tighter) than last stop
                is_better = self._last_stop_price is None or new_stop < self._last_stop_price
            
            if is_better:
                # Round to instrument's price increment
                price_increment = self.instrument.price_increment
                new_stop_rounded = (new_stop / price_increment).quantize(Decimal('1')) * price_increment
                
                # Modify the stop order
                self.modify_order(self._current_stop_order, trigger_price=Price.from_str(str(new_stop_rounded)))
                self._last_stop_price = new_stop_rounded
                self.log.info(f"Trailing stop moved from {self._current_stop_order.trigger_price} to {new_stop_rounded}")

    def on_historical_data(self, data) -> None:
        # Indicators update automatically via registration
        pass

    def on_bar(self, bar: Bar) -> None:
        # Tolerate dataset suffix differences and price aliases when matching
        if bar.bar_type.instrument_id != self.instrument_id:
            return
        if _normalize_price_alias(bar.bar_type.spec) != _normalize_price_alias(self.bar_type.spec):
            return

        self._bar_count += 1
        fast = self.fast_sma.value
        slow = self.slow_sma.value

        ts_init_iso = datetime.fromtimestamp(bar.ts_init / 1_000_000_000, tz=timezone.utc).isoformat()
        ts_event_iso = datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=timezone.utc).isoformat()

        self.log.debug(
            f"Bar #{self._bar_count} received: ts_init={ts_init_iso} ts_event={ts_event_iso} close={bar.close} volume={bar.volume} fast={fast} slow={slow}"
        )

        fast_ready = fast is not None
        slow_ready = slow is not None
        self.log.debug(
            f"Indicator readiness -> fast_initialized={fast_ready}, slow_initialized={slow_ready}"
        )

        if not self._warmup_complete and fast_ready and slow_ready and self._prev_fast is not None and self._prev_slow is not None:
            self._warmup_complete = True
            self.log.info(f"Strategy warmup complete after {self._bar_count} bars")

        if self._bar_count % 10 == 0:
            self.log.debug(
                f"Processed {self._bar_count} bars: fast_sma={fast} slow_sma={slow}"
            )

        if fast is None or slow is None or self._prev_fast is None or self._prev_slow is None:
            # Initialize previous values and wait for full warmup
            self._prev_fast = fast
            self._prev_slow = slow
            return

        # Detect crossovers
        self.log.debug(
            f"SMA comparison -> prev_fast={self._prev_fast} prev_slow={self._prev_slow} current_fast={fast} current_slow={slow}"
        )
        bullish = fast > slow and (self._prev_fast is not None and self._prev_slow is not None) and self._prev_fast <= self._prev_slow
        bearish = fast < slow and (self._prev_fast is not None and self._prev_slow is not None) and self._prev_fast >= self._prev_slow

        if bullish:
            self.log.info(
                f"Bullish crossover detected (prev_fast={self._prev_fast}, prev_slow={self._prev_slow}, current_fast={fast}, current_slow={slow})"
            )
            
            # Check crossover magnitude against threshold
            if not self._check_crossover_threshold("BUY", fast, slow, bar):
                # Do NOT update prev_* here; just return
                return
            
            can_trade, reason = self._check_can_open_position("BUY")
            if not can_trade:
                self._log_rejected_signal("BUY", reason, bar)
            else:
                position: Optional[Position] = self._current_position()
                has_position = position is not None
                self.log.debug(f"Current net position before BUY: {position}")
                if has_position:
                    self.close_all_positions(self.instrument_id)
                    # Reset trailing state when closing positions
                    self._current_stop_order = None
                    self._position_entry_price = None
                    self._trailing_active = False
                    self._last_stop_price = None
                if reason == "close_only":
                    self._log_close_only_event("BUY", "Closed existing short position", bar)
                else:
                    if not has_position and not self._allow_reversal:
                        # Nothing to close and strict mode, proceed directly to entry.
                        pass
                    
                    if self._is_fx:
                        # Calculate SL/TP prices using bar close as entry reference for FX instruments
                        entry_price = Decimal(str(bar.close))
                        sl_price, tp_price = self._calculate_sl_tp_prices(entry_price, OrderSide.BUY)
                        
                        # Log SL/TP calculations
                        self.log.debug(
                            f"BUY order - Entry: {entry_price}, SL: {sl_price}, TP: {tp_price}, "
                            f"Risk: {self.cfg.stop_loss_pips} pips, Reward: {self.cfg.take_profit_pips} pips"
                        )
                        
                        # Create bracket order with entry + SL + TP
                        bracket_orders = self.order_factory.bracket(
                            instrument_id=self.instrument_id,
                            order_side=OrderSide.BUY,
                            quantity=Quantity.from_str(f"{int(self.trade_size)}.00"),
                            sl_trigger_price=sl_price,
                            sl_trigger_type=TriggerType.DEFAULT,
                            tp_price=tp_price,
                            entry_tags=[self.cfg.order_id_tag],
                            sl_tags=[f"{self.cfg.order_id_tag}_SL"],
                            tp_tags=[f"{self.cfg.order_id_tag}_TP"],
                        )
                        self.submit_order_list(bracket_orders)
                        
                        # Extract stop loss order from bracket for trailing functionality
                        stop_orders = [o for o in bracket_orders.orders if "SL" in o.tags or o.order_type.name == "STOP_MARKET"]
                        if stop_orders:
                            self._current_stop_order = stop_orders[0]
                            self._trailing_active = False
                            self._last_stop_price = Decimal(str(self._current_stop_order.trigger_price))
                            self.log.debug(f"Tracking stop loss order: {self._current_stop_order.client_order_id} at {self._last_stop_price}")
                        
                        # Store entry price for trailing stop calculations (will be updated on fill)
                        self._position_entry_price = Decimal(str(bar.close))
                        self.log.debug(f"Position entry price set to {self._position_entry_price}")
                        
                        self.log.info(f"Bullish crossover - BUY {self.trade_size} with SL/TP")
                    else:
                        # For non-FX instruments, create market order without SL/TP
                        order = self.order_factory.market(
                            instrument_id=self.instrument_id,
                            order_side=OrderSide.BUY,
                            quantity=Quantity.from_str(f"{int(self.trade_size)}.00"),
                            tags=[self.cfg.order_id_tag],
                        )
                        self.submit_order(order)
                        self.log.info(f"Bullish crossover - BUY {self.trade_size} (no SL/TP for non-FX instrument)")
        elif bearish:
            self.log.info(
                f"Bearish crossover detected (prev_fast={self._prev_fast}, prev_slow={self._prev_slow}, current_fast={fast}, current_slow={slow})"
            )
            
            # Check crossover magnitude against threshold
            if not self._check_crossover_threshold("SELL", fast, slow, bar):
                # Do NOT update prev_* here; just return
                return
            
            can_trade, reason = self._check_can_open_position("SELL")
            if not can_trade:
                self._log_rejected_signal("SELL", reason, bar)
            else:
                position: Optional[Position] = self._current_position()
                has_position = position is not None
                self.log.debug(f"Current net position before SELL: {position}")
                if has_position:
                    self.close_all_positions(self.instrument_id)
                    # Reset trailing state when closing positions
                    self._current_stop_order = None
                    self._position_entry_price = None
                    self._trailing_active = False
                    self._last_stop_price = None
                if reason == "close_only":
                    self._log_close_only_event("SELL", "Closed existing long position", bar)
                else:
                    if not has_position and not self._allow_reversal:
                        pass
                    
                    if self._is_fx:
                        # Calculate SL/TP prices using bar close as entry reference for FX instruments
                        entry_price = Decimal(str(bar.close))
                        sl_price, tp_price = self._calculate_sl_tp_prices(entry_price, OrderSide.SELL)
                        
                        # Log SL/TP calculations
                        self.log.debug(
                            f"SELL order - Entry: {entry_price}, SL: {sl_price}, TP: {tp_price}, "
                            f"Risk: {self.cfg.stop_loss_pips} pips, Reward: {self.cfg.take_profit_pips} pips"
                        )
                        
                        # Create bracket order with entry + SL + TP
                        bracket_orders = self.order_factory.bracket(
                            instrument_id=self.instrument_id,
                            order_side=OrderSide.SELL,
                            quantity=Quantity.from_str(f"{int(self.trade_size)}.00"),
                            sl_trigger_price=sl_price,
                            sl_trigger_type=TriggerType.DEFAULT,
                            tp_price=tp_price,
                            entry_tags=[self.cfg.order_id_tag],
                            sl_tags=[f"{self.cfg.order_id_tag}_SL"],
                            tp_tags=[f"{self.cfg.order_id_tag}_TP"],
                        )
                        self.submit_order_list(bracket_orders)
                        
                        # Extract stop loss order from bracket for trailing functionality
                        stop_orders = [o for o in bracket_orders.orders if "SL" in o.tags or o.order_type.name == "STOP_MARKET"]
                        if stop_orders:
                            self._current_stop_order = stop_orders[0]
                            self._trailing_active = False
                            self._last_stop_price = Decimal(str(self._current_stop_order.trigger_price))
                            self.log.debug(f"Tracking stop loss order: {self._current_stop_order.client_order_id} at {self._last_stop_price}")
                        
                        # Store entry price for trailing stop calculations (will be updated on fill)
                        self._position_entry_price = Decimal(str(bar.close))
                        self.log.debug(f"Position entry price set to {self._position_entry_price}")
                        
                        self.log.info(f"Bearish crossover - SELL {self.trade_size} with SL/TP")
                    else:
                        # For non-FX instruments, create market order without SL/TP
                        order = self.order_factory.market(
                            instrument_id=self.instrument_id,
                            order_side=OrderSide.SELL,
                            quantity=Quantity.from_str(f"{int(self.trade_size)}.00"),
                            tags=[self.cfg.order_id_tag],
                        )
                        self.submit_order(order)
                        self.log.info(f"Bearish crossover - SELL {self.trade_size} (no SL/TP for non-FX instrument)")

        # Update trailing stop if position is open
        self._update_trailing_stop(bar)
        
        # Update previous values
        self._prev_fast = fast
        self._prev_slow = slow

    def on_stop(self) -> None:
        # Cleanup: cancel orders and close positions
        self.cancel_all_orders(self.instrument_id)
        self.close_all_positions(self.instrument_id)
        self.log.info("Strategy stopped and cleaned up.")

    def on_reset(self) -> None:
        self.fast_sma.reset()
        self.slow_sma.reset()
        self._prev_fast = None
        self._prev_slow = None
        self._rejected_signals.clear()
        
        # Reset trailing stop state
        self._current_stop_order = None
        self._position_entry_price = None
        self._trailing_active = False
        self._last_stop_price = None
