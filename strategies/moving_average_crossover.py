"""
Moving Average Crossover strategy for NautilusTrader.

This strategy uses two Simple Moving Averages (SMA) to generate
buy/sell signals on crossovers.
"""
from __future__ import annotations

from dataclasses import field
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover - zoneinfo may be unavailable on some runtimes
    ZoneInfo = None  # type: ignore
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple, Set, cast
from collections import deque

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.indicators import SimpleMovingAverage, Stochastics
from nautilus_trader.model.position import Position
from nautilus_trader.model.objects import Quantity, Price
from nautilus_trader.model.enums import OrderSide, TriggerType
from nautilus_trader.model.orders import MarketOrder, StopMarketOrder, LimitOrder, OrderList
from indicators.dmi import DMI


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
    pre_crossover_separation_pips: float = 0.0  # Minimum separation (pips) required BEFORE crossing for valid signal; 0.0 = disabled
    pre_crossover_lookback_bars: int = 1  # Number of bars to look back for pre-crossover separation check; 1 = immediate previous bar only
    dmi_enabled: bool = True
    dmi_bar_spec: str = "2-MINUTE-MID-EXTERNAL"
    dmi_period: int = 14
    stoch_enabled: bool = True
    stoch_bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    stoch_period_k: int = 14
    stoch_period_d: int = 3
    stoch_bullish_threshold: int = 30
    stoch_bearish_threshold: int = 70
    stoch_max_bars_since_crossing: int = 5
    # Time filter configuration
    time_filter_enabled: bool = False
    trading_hours_start: int = 0
    trading_hours_end: int = 23
    trading_hours_timezone: str = "UTC"
    excluded_hours: List[int] = field(default_factory=list)  # List of hours (0-23) to exclude from trading, checked before start/end range
    use_limit_orders: bool = False
    limit_order_timeout_bars: int = 10


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
        # Initialize MA history buffer for pre-crossover separation check
        self._ma_history: deque = deque(maxlen=config.pre_crossover_lookback_bars)
        self.instrument = None
        self._rejected_signals: List[Dict[str, Any]] = []
        self._enforce_position_limit = config.enforce_position_limit
        self._allow_reversal = config.allow_position_reversal
        self._bar_count = 0
        self._warmup_complete = False
        self._is_fx: bool = False
        
        # DMI indicator for trend confirmation (optional, 2-minute bars)
        self.dmi: Optional[DMI] = None
        self.dmi_bar_type: Optional[BarType] = None
        if config.dmi_enabled:
            self.dmi = DMI(period=config.dmi_period)
            # Construct 2-minute bar type with same instrument
            dmi_bar_spec = config.dmi_bar_spec
            if not dmi_bar_spec.upper().endswith("-EXTERNAL") and not dmi_bar_spec.upper().endswith("-INTERNAL"):
                dmi_bar_spec = f"{dmi_bar_spec}-EXTERNAL"
            self.dmi_bar_type = BarType.from_str(f"{config.instrument_id}-{dmi_bar_spec}")
        
        # Stochastic indicator for momentum confirmation (optional, 15-minute bars)
        self.stoch: Optional[Stochastics] = None
        self.stoch_bar_type: Optional[BarType] = None
        if config.stoch_enabled:
            self.stoch = Stochastics(period_k=config.stoch_period_k, period_d=config.stoch_period_d)
            # Construct 15-minute bar type with same instrument
            stoch_bar_spec = config.stoch_bar_spec
            if not stoch_bar_spec.upper().endswith("-EXTERNAL") and not stoch_bar_spec.upper().endswith("-INTERNAL"):
                stoch_bar_spec = f"{stoch_bar_spec}-EXTERNAL"
            self.stoch_bar_type = BarType.from_str(f"{config.instrument_id}-{stoch_bar_spec}")
        
        # Trailing stop state tracking
        self._current_stop_order: Optional[StopMarketOrder] = None
        self._position_entry_price: Optional[Decimal] = None
        self._trailing_active: bool = False
        self._last_stop_price: Optional[Decimal] = None
        self._excluded_hours_set: Set[int] = set()

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
        # Subscribe to 2-minute bars for DMI if enabled
        if self.dmi is not None and self.dmi_bar_type is not None:
            self.register_indicator_for_bars(self.dmi_bar_type, self.dmi)
            self.subscribe_bars(self.dmi_bar_type)
            self.log.info(f"DMI filter enabled: subscribed to {self.dmi_bar_type} (period={self.cfg.dmi_period})")
        else:
            self.log.info("DMI filter disabled")
        
        # Subscribe to 15-minute bars for Stochastic if enabled
        if self.stoch is not None and self.stoch_bar_type is not None:
            self.register_indicator_for_bars(self.stoch_bar_type, self.stoch)
            self.subscribe_bars(self.stoch_bar_type)
            self.log.info(f"Stochastic filter enabled: subscribed to {self.stoch_bar_type} (period_k={self.cfg.stoch_period_k}, period_d={self.cfg.stoch_period_d}, bullish_threshold={self.cfg.stoch_bullish_threshold}, bearish_threshold={self.cfg.stoch_bearish_threshold})")
        else:
            self.log.info("Stochastic filter disabled")
        
        # Normalize excluded_hours: cast to int, filter to 0-23, remove duplicates
        try:
            raw_excluded = list(self.cfg.excluded_hours or [])
        except Exception:
            raw_excluded = []
        normalized_list: List[int] = []
        seen: Set[int] = set()
        discarded: List[Any] = []
        for item in raw_excluded:
            try:
                hour = int(item)
            except Exception:
                discarded.append(item)
                continue
            if 0 <= hour <= 23:
                if hour not in seen:
                    normalized_list.append(hour)
                    seen.add(hour)
                else:
                    discarded.append(item)
            else:
                discarded.append(hour)
        self._excluded_hours_set = set(normalized_list)
        try:
            self.cfg.excluded_hours = normalized_list
        except Exception:
            # Config may be immutable; proceed with normalized instance state only
            pass
        if discarded:
            self.log.warning(
                f"Excluded hours normalization discarded {len(discarded)} value(s): {discarded}. Using {normalized_list}"
            )

        # Time filter configuration logging
        if self.cfg.time_filter_enabled:
            self.log.info(
                f"Time filter enabled: trading hours {self.cfg.trading_hours_start}-{self.cfg.trading_hours_end} {self.cfg.trading_hours_timezone}"
            )
            if self._excluded_hours_set:
                self.log.info(f"Excluded hours: {sorted(self._excluded_hours_set)} {self.cfg.trading_hours_timezone}")
        else:
            self.log.info("Time filter disabled")

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

    def _check_pre_crossover_separation(self, direction: str, bar: Bar) -> bool:
        """Check if moving averages were sufficiently separated before crossing.
        
        Args:
            direction: "BUY" for bullish crossover, "SELL" for bearish crossover
            bar: Current bar for logging context
            
        Returns:
            True if pre-crossover separation is valid, False otherwise
        """
        # Skip check if disabled (threshold is 0)
        if self.cfg.pre_crossover_separation_pips <= 0:
            return True
            
        pip_value = self._calculate_pip_value()
        threshold_pips = Decimal(str(self.cfg.pre_crossover_separation_pips))
        threshold_price = threshold_pips * pip_value
        
        # Check if we have enough history
        if len(self._ma_history) == 0:
            self._log_rejected_signal(
                direction,
                "pre_crossover_separation_insufficient_history (no MA history available)",
                bar,
            )
            return False
        
        # Iterate through history buffer in reverse order (most recent first)
        max_separation = Decimal('0')
        for fast_ma, slow_ma in reversed(self._ma_history):
            # Check direction validity
            if direction == "BUY":
                # For bullish crossover, fast_ma must be below slow_ma
                if fast_ma >= slow_ma:
                    continue
            elif direction == "SELL":
                # For bearish crossover, fast_ma must be above slow_ma
                if fast_ma <= slow_ma:
                    continue
            
            # Calculate separation
            separation = abs(fast_ma - slow_ma)
            max_separation = max(max_separation, separation)
            
            # Check if separation meets threshold
            if separation >= threshold_price:
                self.log.debug(f"Pre-crossover separation found: {separation} >= {threshold_price} for {direction}")
                return True
        
        # No bar in lookback window met the threshold
        max_separation_pips = max_separation / pip_value
        self._log_rejected_signal(
            direction,
            f"pre_crossover_separation_insufficient (max separation={max_separation_pips:.2f} pips < {threshold_pips} pips threshold in {len(self._ma_history)} bars)",
            bar,
        )
        return False

    def _check_time_filter(self, direction: str, bar: Bar) -> bool:
        """Validate bar time against configured trading hours.
        
        Returns True if filter passes or is disabled; False when outside trading window.
        """
        if not self.cfg.time_filter_enabled:
            return True

        try:
            ts_dt_utc = datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=timezone.utc)

            # Resolve timezone; if ZoneInfo unavailable, fail-open
            if ZoneInfo is None:
                self.log.error("ZoneInfo not available; skipping time filter and allowing trade")
                return True

            local_dt = ts_dt_utc.astimezone(ZoneInfo(self.cfg.trading_hours_timezone))
            bar_hour = local_dt.hour
            # First, check excluded hours (more specific)
            if self._excluded_hours_set and bar_hour in self._excluded_hours_set:
                self._log_rejected_signal(
                    direction,
                    f"time_filter_excluded_hour (bar_hour={bar_hour} in excluded hours {sorted(self._excluded_hours_set)} {self.cfg.trading_hours_timezone})",
                    bar,
                )
                return False
            # Validate trading hour bounds and types; fail-open with warning on invalid
            try:
                start = int(self.cfg.trading_hours_start)
                end = int(self.cfg.trading_hours_end)
            except Exception:
                self.log.warning(
                    f"Invalid trading hours configuration: start={self.cfg.trading_hours_start}, end={self.cfg.trading_hours_end}; allowing trade by default"
                )
                return True

            if not (0 <= start <= 23) or not (0 <= end <= 23):
                self.log.warning(
                    f"Trading hours out of range: start={start}, end={end}; expected 0-23. Allowing trade by default"
                )
                return True

            # Inclusive window check with overnight support (wrap-around when start > end)
            if start <= end:
                in_window = start <= bar_hour <= end
            else:
                # Window spans midnight: valid if hour >= start or hour <= end
                in_window = bar_hour >= start or bar_hour <= end

            if in_window:
                return True

            self._log_rejected_signal(
                direction,
                f"time_filter_outside_hours (bar_hour={bar_hour} outside {start}-{end} {self.cfg.trading_hours_timezone})",
                bar,
            )
            return False
        except Exception as exc:
            # Fail-open on any unexpected error
            self.log.error(f"Time filter error: {exc}; allowing trade by default")
            return True

    def _check_dmi_trend(self, direction: str, bar: Bar) -> bool:
        """Check if DMI trend aligns with crossover direction.
        
        Args:
            direction: "BUY" or "SELL"
            bar: Current bar for logging
            
        Returns:
            True if DMI check passes or is disabled/not ready, False if trend mismatch
        """
        # Skip check if DMI is disabled
        if self.dmi is None:
            return True
        
        # Skip check if DMI not initialized yet (not enough 2-minute bars)
        if not self.dmi.initialized:
            self.log.debug("DMI not initialized yet, skipping DMI check")
            return True
        
        # Check trend alignment
        if direction == "BUY":
            # Bullish crossover requires +DI > -DI (bullish trend)
            if self.dmi.minus_di > self.dmi.plus_di:
                self._log_rejected_signal(
                    "BUY",
                    f"dmi_trend_mismatch (+DI={self.dmi.plus_di:.2f} < -DI={self.dmi.minus_di:.2f}, bearish trend)",
                    bar
                )
                return False
        elif direction == "SELL":
            # Bearish crossover requires -DI > +DI (bearish trend)
            if self.dmi.plus_di > self.dmi.minus_di:
                self._log_rejected_signal(
                    "SELL",
                    f"dmi_trend_mismatch (-DI={self.dmi.minus_di:.2f} < +DI={self.dmi.plus_di:.2f}, bullish trend)",
                    bar
                )
                return False
        
        # DMI confirms the trend
        self.log.debug(f"DMI trend confirmed for {direction}: +DI={self.dmi.plus_di:.2f}, -DI={self.dmi.minus_di:.2f}")
        return True

    def _check_stochastic_momentum(self, direction: str, bar: Bar) -> bool:
        """Check if Stochastic momentum aligns with crossover direction.
        
        Args:
            direction: "BUY" or "SELL"
            bar: Current bar for logging
            
        Returns:
            True if Stochastic check passes or is disabled/not ready, False if momentum unfavorable
        """
        # Skip check if Stochastic is disabled
        if self.stoch is None:
            return True
        
        # Skip check if Stochastic not initialized yet (not enough 15-minute bars)
        if not self.stoch.initialized:
            self.log.debug("Stochastic not initialized yet, skipping Stochastic check")
            return True
        
        # Get current Stochastic values
        k_value = self.stoch.value_k
        d_value = self.stoch.value_d
        
        if direction == "BUY":
            # Bullish crossover requires:
            # 1. %K > %D (fast line above slow line, bullish momentum)
            # 2. %K > bullish_threshold (not oversold)
            # 3. %D > bullish_threshold (not oversold)
            if k_value <= d_value:
                self._log_rejected_signal(
                    "BUY",
                    "stochastic_unfavorable",
                    bar
                )
                return False
            
            if k_value <= self.cfg.stoch_bullish_threshold:
                self._log_rejected_signal(
                    "BUY",
                    "stochastic_unfavorable",
                    bar
                )
                return False
            
            if d_value <= self.cfg.stoch_bullish_threshold:
                self._log_rejected_signal(
                    "BUY",
                    "stochastic_unfavorable",
                    bar
                )
                return False
            
            # Stochastic confirms bullish momentum
            self.log.debug(f"Stochastic momentum confirmed for {direction}: %K={k_value:.2f}, %D={d_value:.2f}")
            
        elif direction == "SELL":
            # Bearish crossover requires:
            # 1. %K < %D (fast line below slow line, bearish momentum)
            # 2. %K < bearish_threshold (not overbought)
            # 3. %D < bearish_threshold (not overbought)
            if k_value >= d_value:
                self._log_rejected_signal(
                    "SELL",
                    "stochastic_unfavorable",
                    bar
                )
                return False
            
            if k_value >= self.cfg.stoch_bearish_threshold:
                self._log_rejected_signal(
                    "SELL",
                    "stochastic_unfavorable",
                    bar
                )
                return False
            
            if d_value >= self.cfg.stoch_bearish_threshold:
                self._log_rejected_signal(
                    "SELL",
                    "stochastic_unfavorable",
                    bar
                )
                return False
            
            # Stochastic confirms bearish momentum
            self.log.debug(f"Stochastic momentum confirmed for {direction}: %K={k_value:.2f}, %D={d_value:.2f}")
        
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
        # Filter by instrument
        if bar.bar_type.instrument_id != self.instrument_id:
            return
        
        # Route DMI bars only if they are not the primary bar type
        if (
            self.dmi_bar_type is not None
            and bar.bar_type == self.dmi_bar_type
            and bar.bar_type != self.bar_type
        ):
            self.log.debug(f"Received DMI bar: close={bar.close}")
            return
        
        # Route Stochastic bars only if they are not the primary bar type
        if (
            self.stoch_bar_type is not None
            and bar.bar_type == self.stoch_bar_type
            and bar.bar_type != self.bar_type
        ):
            self.log.debug(f"Received Stochastic bar: close={bar.close}")
            return
        
        # Process 1-minute bars for MA crossover logic
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
            # Append MA values to history if both are not None so next bar has at least one prior MA sample
            if fast is not None and slow is not None:
                self._ma_history.append((fast, slow))
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
            # Check trading hours window
            if not self._check_time_filter("BUY", bar):
                return
            # Check DMI trend alignment
            if not self._check_dmi_trend("BUY", bar):
                return
            
            # Check Stochastic momentum alignment
            if not self._check_stochastic_momentum("BUY", bar):
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
            # Check trading hours window
            if not self._check_time_filter("SELL", bar):
                return
            # Check DMI trend alignment
            if not self._check_dmi_trend("SELL", bar):
                return
            
            # Check Stochastic momentum alignment
            if not self._check_stochastic_momentum("SELL", bar):
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
        
        # Append MA values to history buffer for pre-crossover separation check
        if fast is not None and slow is not None:
            self._ma_history.append((fast, slow))

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
        
        # Clear MA history buffer
        self._ma_history.clear()
        self.log.debug("MA history buffer cleared")
        
        # Reset trailing stop state
        self._current_stop_order = None
        self._position_entry_price = None
        self._trailing_active = False
        self._last_stop_price = None
        if self.dmi is not None:
            self.dmi.reset()
        if self.stoch is not None:
            self.stoch.reset()
