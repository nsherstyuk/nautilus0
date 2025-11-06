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
from nautilus_trader.model.events.order import (
    OrderEvent,
    OrderAccepted,
    OrderFilled,
    OrderRejected,
    OrderCanceled,
    OrderCancelRejected,
    OrderExpired,
    OrderTriggered,
    OrderPendingUpdate,
    OrderUpdated,
)
from nautilus_trader.model.events.position import (
    PositionEvent,
    PositionOpened,
    PositionChanged,
    PositionClosed,
)
from indicators.dmi import DMI
import logging


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
    dmi_minimum_difference: float = 0.0  # Minimum DI difference for valid trend (0.0 = disabled, backward compatible)
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
    # Multi-timeframe trend filter (disabled by default for zero impact)
    trend_filter_enabled: bool = False
    trend_bar_spec: str = "1-HOUR-MID-EXTERNAL"
    trend_fast_period: int = 20
    trend_slow_period: int = 50
    # Entry timing refinement (disabled by default for zero impact)
    entry_timing_enabled: bool = False
    entry_timing_bar_spec: str = "5-MINUTE-MID-EXTERNAL"
    entry_timing_method: str = "pullback"  # Options: "pullback", "rsi", "stochastic", "breakout"
    entry_timing_timeout_bars: int = 10
    # Dormant mode (disabled by default for zero impact)
    dormant_mode_enabled: bool = False  # Activate lower timeframe trading when crossings are rare
    dormant_threshold_hours: float = 14.0  # Hours without crossover before activating dormant mode
    dormant_bar_spec: str = "1-MINUTE-MID-EXTERNAL"  # Lower timeframe for signal detection
    dormant_fast_period: int = 5  # Fast MA period for dormant mode
    dormant_slow_period: int = 10  # Slow MA period for dormant mode
    dormant_stop_loss_pips: int = 20  # Tighter SL for dormant mode trades
    dormant_take_profit_pips: int = 30  # Smaller TP for dormant mode trades
    dormant_trailing_activation_pips: int = 15  # Lower activation threshold for trailing
    dormant_trailing_distance_pips: int = 8  # Tighter trailing distance
    dormant_dmi_enabled: bool = False  # Use DMI filter in dormant mode
    dormant_stoch_enabled: bool = False  # Use Stochastic filter in dormant mode


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
        # Stochastic crossing tracking (measured in Stochastic bars, not primary bars)
        self._stoch_bar_count: int = 0
        self._stoch_last_cross_bar: Optional[int] = None
        self._stoch_last_cross_direction: Optional[str] = None  # "BULLISH" or "BEARISH"
        self._stoch_prev_k: Optional[float] = None
        self._stoch_prev_d: Optional[float] = None
        if config.stoch_enabled:
            self.stoch = Stochastics(period_k=config.stoch_period_k, period_d=config.stoch_period_d)
            # Construct 15-minute bar type with same instrument
            stoch_bar_spec = config.stoch_bar_spec
            if not stoch_bar_spec.upper().endswith("-EXTERNAL") and not stoch_bar_spec.upper().endswith("-INTERNAL"):
                stoch_bar_spec = f"{stoch_bar_spec}-EXTERNAL"
            self.stoch_bar_type = BarType.from_str(f"{config.instrument_id}-{stoch_bar_spec}")
        
        # Multi-timeframe trend filter (optional, higher timeframe bars)
        self.trend_bar_type: Optional[BarType] = None
        self.trend_fast_sma: Optional[SimpleMovingAverage] = None
        self.trend_slow_sma: Optional[SimpleMovingAverage] = None
        if config.trend_filter_enabled:
            trend_bar_spec = config.trend_bar_spec
            if not trend_bar_spec.upper().endswith("-EXTERNAL") and not trend_bar_spec.upper().endswith("-INTERNAL"):
                trend_bar_spec = f"{trend_bar_spec}-EXTERNAL"
            self.trend_bar_type = BarType.from_str(f"{config.instrument_id}-{trend_bar_spec}")
            self.trend_fast_sma = SimpleMovingAverage(period=config.trend_fast_period)
            self.trend_slow_sma = SimpleMovingAverage(period=config.trend_slow_period)
        
        # Entry timing state (optional, lower timeframe bars)
        self.entry_timing_bar_type: Optional[BarType] = None
        self._pending_signal: Optional[str] = None  # "BUY" or "SELL"
        self._pending_signal_timestamp: Optional[int] = None
        self._pending_signal_timeout_bars: int = 0
        self._entry_timing_fast_sma: Optional[SimpleMovingAverage] = None
        self._entry_timing_slow_sma: Optional[SimpleMovingAverage] = None
        if config.entry_timing_enabled:
            entry_timing_bar_spec = config.entry_timing_bar_spec
            if not entry_timing_bar_spec.upper().endswith("-EXTERNAL") and not entry_timing_bar_spec.upper().endswith("-INTERNAL"):
                entry_timing_bar_spec = f"{entry_timing_bar_spec}-EXTERNAL"
            self.entry_timing_bar_type = BarType.from_str(f"{config.instrument_id}-{entry_timing_bar_spec}")
            # Initialize entry timing indicators (using pullback method)
            if config.entry_timing_method == "pullback":
                # Use fast/slow SMAs on lower timeframe for pullback detection
                self._entry_timing_fast_sma = SimpleMovingAverage(period=5)  # Fast period for lower TF
                self._entry_timing_slow_sma = SimpleMovingAverage(period=10)  # Slow period for lower TF
        self._current_stop_order: Optional[StopMarketOrder] = None
        self._position_entry_price: Optional[Decimal] = None
        self._trailing_active: bool = False
        self._last_stop_price: Optional[Decimal] = None
        self._excluded_hours_set: Set[int] = set()
        
        # Dormant mode state (optional, only initialized if enabled)
        self._dormant_mode_active: bool = False
        self._last_crossover_timestamp: Optional[int] = None
        self._primary_trend_direction: Optional[str] = None  # "BULLISH" or "BEARISH"
        self._dormant_bar_type: Optional[BarType] = None
        self._dormant_fast_sma: Optional[SimpleMovingAverage] = None
        self._dormant_slow_sma: Optional[SimpleMovingAverage] = None
        self._dormant_prev_fast: Optional[Decimal] = None
        self._dormant_prev_slow: Optional[Decimal] = None
        self._position_opened_in_dormant_mode: bool = False
        if config.dormant_mode_enabled:
            dormant_bar_spec = config.dormant_bar_spec
            if not dormant_bar_spec.upper().endswith("-EXTERNAL") and not dormant_bar_spec.upper().endswith("-INTERNAL"):
                dormant_bar_spec = f"{dormant_bar_spec}-EXTERNAL"
            self._dormant_bar_type = BarType.from_str(f"{config.instrument_id}-{dormant_bar_spec}")
            self._dormant_fast_sma = SimpleMovingAverage(period=config.dormant_fast_period)
            self._dormant_slow_sma = SimpleMovingAverage(period=config.dormant_slow_period)

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
        # Check multiple ways: raw_symbol, instrument_id, and instrument type
        raw_symbol_str = str(self.instrument.raw_symbol.value) if hasattr(self.instrument.raw_symbol, 'value') else str(self.instrument.raw_symbol)
        instrument_id_str = str(self.instrument_id)
        
        # Check if it's a CurrencyPair type
        from nautilus_trader.model.instruments import CurrencyPair
        is_currency_pair = isinstance(self.instrument, CurrencyPair)
        
        # Check symbol formats (with/without slash)
        has_slash_in_symbol = "/" in raw_symbol_str
        has_slash_in_id = "/" in instrument_id_str
        
        # FX detection: either CurrencyPair type, or symbol contains "/", or instrument_id contains "/"
        self._is_fx = is_currency_pair or has_slash_in_symbol or has_slash_in_id
        
        # Enhanced logging for diagnosis
        self.log.info(
            f"Instrument detection - Type: {type(self.instrument).__name__}, "
            f"raw_symbol: {raw_symbol_str}, instrument_id: {instrument_id_str}, "
            f"is_currency_pair: {is_currency_pair}, has_slash_symbol: {has_slash_in_symbol}, "
            f"has_slash_id: {has_slash_in_id}, _is_fx: {self._is_fx}"
        )
        
        if self._is_fx:
            self.log.info(f"FX instrument detected - pip-based SL/TP ENABLED")
            self.log.info(f"SL/TP configuration: stop_loss={self.cfg.stop_loss_pips} pips, take_profit={self.cfg.take_profit_pips} pips")
        else:
            self.log.warning(
                f"Non-FX instrument detected: {raw_symbol_str} - pip-based SL/TP DISABLED. "
                f"Orders will be submitted WITHOUT stop loss and take profit!"
            )

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
        
        # Subscribe to dormant mode bars if enabled
        if self.cfg.dormant_mode_enabled and self._dormant_bar_type is not None:
            self.register_indicator_for_bars(self._dormant_bar_type, self._dormant_fast_sma)
            self.register_indicator_for_bars(self._dormant_bar_type, self._dormant_slow_sma)
            self.subscribe_bars(self._dormant_bar_type)
            self.log.info(f"Dormant mode enabled: subscribed to {self._dormant_bar_type} "
                         f"(fast={self.cfg.dormant_fast_period}, slow={self.cfg.dormant_slow_period}, "
                         f"threshold={self.cfg.dormant_threshold_hours}h)")
        else:
            self.log.info("Dormant mode disabled")
        
        # Subscribe to higher timeframe bars for trend filter if enabled
        if self.trend_bar_type is not None and self.trend_fast_sma is not None and self.trend_slow_sma is not None:
            self.register_indicator_for_bars(self.trend_bar_type, self.trend_fast_sma)
            self.register_indicator_for_bars(self.trend_bar_type, self.trend_slow_sma)
            self.subscribe_bars(self.trend_bar_type)
            self.log.info(f"Trend filter enabled: subscribed to {self.trend_bar_type} (fast_period={self.cfg.trend_fast_period}, slow_period={self.cfg.trend_slow_period})")
        else:
            self.log.info("Trend filter disabled")
        
        # Subscribe to lower timeframe bars for entry timing if enabled
        if self.entry_timing_bar_type is not None:
            self.subscribe_bars(self.entry_timing_bar_type)
            if self._entry_timing_fast_sma is not None and self._entry_timing_slow_sma is not None:
                self.register_indicator_for_bars(self.entry_timing_bar_type, self._entry_timing_fast_sma)
                self.register_indicator_for_bars(self.entry_timing_bar_type, self._entry_timing_slow_sma)
            self.log.info(f"Entry timing enabled: subscribed to {self.entry_timing_bar_type} (method={self.cfg.entry_timing_method})")
        else:
            self.log.info("Entry timing disabled")
        
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
        """
        Check if a new position can be opened.
        
        Returns False if any position is already open, regardless of direction.
        Positions should only be closed by TP/SL orders, not by opposite signals.
        """
        if not self._enforce_position_limit:
            return True, ""

        # Evaluate the net position for this instrument; NETTING OMS ensures a single net side.
        position: Optional[Position] = self._current_position()

        if position is None:
            return True, ""

        # If any position is open, reject all signals
        # Position will be closed only by TP/SL orders, not by opposite signals
        side = getattr(position, "side", "unknown")
        side_str = side.name if hasattr(side, "name") else str(side)
        return False, f"Position already open ({side_str}) - signals ignored until TP/SL closes position"

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

    def _log_rejected_signal(self, signal_type: str, reason: str, bar: Bar, extra_info: str | None = None) -> None:
        full_reason = reason if extra_info is None else f"{reason} ({extra_info})"
        self._record_signal_event(signal_type, "rejected", full_reason, bar)
        self.log.info(
            f"REJECTED {signal_type} signal: {full_reason} | Fast SMA: {self.fast_sma.value}, Slow SMA: {self.slow_sma.value}"
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
            True if DMI check passes or is disabled/not ready, False if trend mismatch or too weak
        """
        # Skip check if DMI is disabled
        if self.dmi is None:
            return True
        
        # Skip check if DMI not initialized yet (not enough 2-minute bars)
        if not self.dmi.initialized:
            self.log.debug("DMI not initialized yet, skipping DMI check")
            return True
        
        # Get DI values
        plus_di = self.dmi.plus_di
        minus_di = self.dmi.minus_di
        
        # Check trend alignment
        if direction == "BUY":
            # Bullish crossover requires +DI > -DI (bullish trend)
            di_difference = plus_di - minus_di
            
            # Check for opposite trend (bearish)
            if di_difference <= 0:
                self._log_rejected_signal(
                    "BUY",
                    f"dmi_trend_mismatch (+DI={plus_di:.2f} <= -DI={minus_di:.2f}, bearish trend)",
                    bar
                )
                return False
            
            # Check minimum difference threshold (if enabled)
            if self.cfg.dmi_minimum_difference > 0 and di_difference < self.cfg.dmi_minimum_difference:
                self._log_rejected_signal(
                    "BUY",
                    f"dmi_trend_too_weak (+DI={plus_di:.2f} - -DI={minus_di:.2f} = {di_difference:.2f} < threshold={self.cfg.dmi_minimum_difference})",
                    bar
                )
                return False
            
            # DMI confirms bullish trend
            self.log.debug(
                f"DMI trend confirmed for {direction}: +DI={plus_di:.2f}, -DI={minus_di:.2f}, "
                f"difference={di_difference:.2f}"
            )
            
        elif direction == "SELL":
            # Bearish crossover requires -DI > +DI (bearish trend)
            di_difference = minus_di - plus_di
            
            # Check for opposite trend (bullish)
            if di_difference <= 0:
                self._log_rejected_signal(
                    "SELL",
                    f"dmi_trend_mismatch (-DI={minus_di:.2f} <= +DI={plus_di:.2f}, bullish trend)",
                    bar
                )
                return False
            
            # Check minimum difference threshold (if enabled)
            if self.cfg.dmi_minimum_difference > 0 and di_difference < self.cfg.dmi_minimum_difference:
                self._log_rejected_signal(
                    "SELL",
                    f"dmi_trend_too_weak (-DI={minus_di:.2f} - +DI={plus_di:.2f} = {di_difference:.2f} < threshold={self.cfg.dmi_minimum_difference})",
                    bar
                )
                return False
            
            # DMI confirms bearish trend
            self.log.debug(
                f"DMI trend confirmed for {direction}: +DI={plus_di:.2f}, -DI={minus_di:.2f}, "
                f"difference={di_difference:.2f}"
            )
        
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
        
        # Check if Stochastic crossing is recent enough (if max_bars_since_crossing is configured)
        if self.cfg.stoch_max_bars_since_crossing > 0 and self._stoch_last_cross_bar is not None:
            bars_since_crossing = self._stoch_bar_count - self._stoch_last_cross_bar
            
            # Check if crossing is too old
            if bars_since_crossing > self.cfg.stoch_max_bars_since_crossing:
                self._log_rejected_signal(
                    direction,
                    "stochastic_crossing_too_old",
                    bar,
                    extra_info=f"crossing was {bars_since_crossing} bars ago (max={self.cfg.stoch_max_bars_since_crossing})"
                )
                return False
            
            # Check if crossing direction matches signal direction
            if direction == "BUY" and self._stoch_last_cross_direction != "BULLISH":
                self._log_rejected_signal(
                    direction,
                    "stochastic_crossing_direction_mismatch",
                    bar,
                    extra_info=f"last crossing was {self._stoch_last_cross_direction}, need BULLISH"
                )
                return False
            
            if direction == "SELL" and self._stoch_last_cross_direction != "BEARISH":
                self._log_rejected_signal(
                    direction,
                    "stochastic_crossing_direction_mismatch",
                    bar,
                    extra_info=f"last crossing was {self._stoch_last_cross_direction}, need BEARISH"
                )
                return False
        
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
    
    def _check_trend_alignment(self, signal_direction: str) -> bool:
        """Check if signal aligns with higher timeframe trend.
        
        Args:
            signal_direction: "BUY" or "SELL"
        
        Returns:
            True if trend filter passes or is disabled; False when trend doesn't align.
            Returns True if disabled (no filtering) to ensure zero impact on current behavior.
        """
        # Early return if disabled - NO IMPACT on existing logic
        if not self.cfg.trend_filter_enabled:
            return True  # Pass through - no filtering
        
        # Ensure indicators are initialized
        if self.trend_fast_sma is None or self.trend_slow_sma is None:
            return True  # Not ready yet, pass through
        
        trend_fast = self.trend_fast_sma.value
        trend_slow = self.trend_slow_sma.value
        
        # If indicators not ready, pass through
        if trend_fast is None or trend_slow is None:
            return True  # Not ready yet, pass through
        
        # Check trend alignment
        if signal_direction == "BUY":
            # For BUY signals, require bullish trend (fast > slow)
            aligned = trend_fast > trend_slow
            if not aligned:
                self.log.debug(
                    f"Trend filter rejected BUY signal: trend_fast={trend_fast} <= trend_slow={trend_slow} "
                    f"(bearish trend on {self.trend_bar_type})"
                )
            return aligned
        elif signal_direction == "SELL":
            # For SELL signals, require bearish trend (fast < slow)
            aligned = trend_fast < trend_slow
            if not aligned:
                self.log.debug(
                    f"Trend filter rejected SELL signal: trend_fast={trend_fast} >= trend_slow={trend_slow} "
                    f"(bullish trend on {self.trend_bar_type})"
                )
            return aligned
        
        # Unknown direction, pass through
        return True
    
    def _check_entry_timing(self, signal_direction: str, bar: Bar) -> bool:
        """Check entry timing using lower timeframe.
        
        Args:
            signal_direction: "BUY" or "SELL"
            bar: Current bar
        
        Returns:
            True if entry timing passes or is disabled; False when should wait for better entry.
            Returns True if disabled (immediate execution) to ensure zero impact on current behavior.
        """
        # Early return if disabled - NO IMPACT on existing logic
        if not self.cfg.entry_timing_enabled:
            return True  # Execute immediately (current behavior)
        
        # If entry timing is enabled, check if we should wait for better entry
        # For now, we'll use a simple pullback strategy on the lower timeframe
        
        if self._entry_timing_fast_sma is None or self._entry_timing_slow_sma is None:
            # Indicators not ready, execute immediately
            return True
        
        fast_value = self._entry_timing_fast_sma.value
        slow_value = self._entry_timing_slow_sma.value
        
        if fast_value is None or slow_value is None:
            # Indicators not ready, execute immediately
            return True
        
        current_price = Decimal(str(bar.close))
        
        if signal_direction == "BUY":
            # For BUY signals, look for pullback: fast MA should be below slow MA (oversold)
            # or at least close to it (not too extended)
            if fast_value < slow_value:
                # Pullback detected, good entry
                self.log.debug(
                    f"Entry timing: BUY pullback detected on {self.entry_timing_bar_type} "
                    f"(fast={fast_value} < slow={slow_value})"
                )
                # Clear pending signal if we're executing
                if self._pending_signal == "BUY":
                    self._pending_signal = None
                    self._pending_signal_timestamp = None
                    self._pending_signal_timeout_bars = 0
                return True
            else:
                # No pullback yet, wait
                if self._pending_signal != "BUY":
                    self._pending_signal = "BUY"
                    self._pending_signal_timestamp = bar.ts_init
                    self._pending_signal_timeout_bars = 0
                    self.log.debug(
                        f"Entry timing: BUY signal pending, waiting for pullback on {self.entry_timing_bar_type} "
                        f"(fast={fast_value} >= slow={slow_value})"
                    )
                return False
        elif signal_direction == "SELL":
            # For SELL signals, look for pullback: fast MA should be above slow MA (overbought)
            # or at least close to it (not too extended)
            if fast_value > slow_value:
                # Pullback detected, good entry
                self.log.debug(
                    f"Entry timing: SELL pullback detected on {self.entry_timing_bar_type} "
                    f"(fast={fast_value} > slow={slow_value})"
                )
                # Clear pending signal if we're executing
                if self._pending_signal == "SELL":
                    self._pending_signal = None
                    self._pending_signal_timestamp = None
                    self._pending_signal_timeout_bars = 0
                return True
            else:
                # No pullback yet, wait
                if self._pending_signal != "SELL":
                    self._pending_signal = "SELL"
                    self._pending_signal_timestamp = bar.ts_init
                    self._pending_signal_timeout_bars = 0
                    self.log.debug(
                        f"Entry timing: SELL signal pending, waiting for pullback on {self.entry_timing_bar_type} "
                        f"(fast={fast_value} <= slow={slow_value})"
                    )
                return False
        
        # Unknown direction, execute immediately
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

    def _calculate_sl_tp_prices(self, entry_price: Decimal, order_side: OrderSide, dormant_mode: bool = False) -> Tuple[Price, Price]:
        """Calculate stop loss and take profit prices based on entry price and order side."""
        pip_value = self._calculate_pip_value()
        if dormant_mode:
            sl_pips = Decimal(str(self.cfg.dormant_stop_loss_pips))
            tp_pips = Decimal(str(self.cfg.dormant_take_profit_pips))
        else:
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
        
        # Use dormant mode parameters if position was opened in dormant mode
        if self._position_opened_in_dormant_mode:
            activation_threshold = Decimal(str(self.cfg.dormant_trailing_activation_pips))
            trailing_distance = Decimal(str(self.cfg.dormant_trailing_distance_pips))
        else:
            activation_threshold = Decimal(str(self.cfg.trailing_stop_activation_pips))
            trailing_distance = Decimal(str(self.cfg.trailing_stop_distance_pips))
        
        # Check if we should activate trailing
        if profit_pips >= activation_threshold and not self._trailing_active:
            self._trailing_active = True
            self.log.info(f"Trailing stop activated at +{profit_pips:.1f} pips profit")
        
        # Update trailing stop if active
        if self._trailing_active:
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

    def _check_dormant_mode_activation(self, bar: Bar) -> None:
        """Check if dormant mode should activate or deactivate."""
        if not self.cfg.dormant_mode_enabled:
            return
        
        # Update primary trend direction from primary timeframe MAs
        if self.fast_sma.initialized and self.slow_sma.initialized:
            fast = self.fast_sma.value
            slow = self.slow_sma.value
            if fast is not None and slow is not None:
                if fast > slow:
                    self._primary_trend_direction = "BULLISH"
                elif fast < slow:
                    self._primary_trend_direction = "BEARISH"
                # else: neutral, keep current direction
        
        # Check if we have an open position
        position = self._current_position()
        if position is not None:
            # Don't switch modes while position is open
            return
        
        # Check time since last crossover
        if self._last_crossover_timestamp is None:
            # No crossovers yet, don't activate
            return
        
        hours_since_crossover = (bar.ts_event - self._last_crossover_timestamp) / 3_600_000_000_000.0
        
        if hours_since_crossover >= self.cfg.dormant_threshold_hours:
            if not self._dormant_mode_active:
                self._dormant_mode_active = True
                self.log.info(
                    f"Dormant mode ACTIVATED: {hours_since_crossover:.1f} hours since last crossover, "
                    f"primary trend: {self._primary_trend_direction}"
                )
        else:
            if self._dormant_mode_active:
                self._dormant_mode_active = False
                self.log.info("Dormant mode DEACTIVATED: Threshold not met")

    def _process_dormant_mode_bar(self, bar: Bar) -> None:
        """Process bars in dormant mode for signal generation."""
        if not self._dormant_mode_active:
            return
        
        # Update indicators
        if self._dormant_fast_sma is None or self._dormant_slow_sma is None:
            return
        
        if not self._dormant_fast_sma.initialized or not self._dormant_slow_sma.initialized:
            return
        
        fast = self._dormant_fast_sma.value
        slow = self._dormant_slow_sma.value
        
        if fast is None or slow is None:
            return
        
        # Get previous values for crossover detection
        prev_fast = self._dormant_prev_fast
        prev_slow = self._dormant_prev_slow
        
        # Initialize previous values if needed
        if prev_fast is None:
            self._dormant_prev_fast = fast
            return
        if prev_slow is None:
            self._dormant_prev_slow = slow
            return
        
        # Detect crossover
        bullish = fast > slow and prev_fast <= prev_slow
        bearish = fast < slow and prev_fast >= prev_slow
        
        signal_direction = None
        if bullish:
            signal_direction = "BUY"
        elif bearish:
            signal_direction = "SELL"
        
        if signal_direction is None:
            # Update previous values
            self._dormant_prev_fast = fast
            self._dormant_prev_slow = slow
            return
        
        # Filter by primary trend direction
        if self._primary_trend_direction == "BULLISH" and signal_direction != "BUY":
            self._dormant_prev_fast = fast
            self._dormant_prev_slow = slow
            return  # Only take BUY signals in bullish trend
        elif self._primary_trend_direction == "BEARISH" and signal_direction != "SELL":
            self._dormant_prev_fast = fast
            self._dormant_prev_slow = slow
            return  # Only take SELL signals in bearish trend
        
        # Check if we can open a position
        can_trade, reason = self._check_can_open_position(signal_direction)
        if not can_trade:
            self._log_rejected_signal(signal_direction, f"dormant_mode_{reason}", bar)
            self._dormant_prev_fast = fast
            self._dormant_prev_slow = slow
            return
        
        # Check crossover threshold
        if not self._check_crossover_threshold(signal_direction, fast, slow, bar):
            self._dormant_prev_fast = fast
            self._dormant_prev_slow = slow
            return
        
        # Check time filter
        if not self._check_time_filter(signal_direction, bar):
            self._dormant_prev_fast = fast
            self._dormant_prev_slow = slow
            return
        
        # Check DMI filter (if enabled for dormant mode)
        if self.cfg.dormant_dmi_enabled and not self._check_dmi_trend(signal_direction, bar):
            self._dormant_prev_fast = fast
            self._dormant_prev_slow = slow
            return
        
        # Check Stochastic filter (if enabled for dormant mode)
        if self.cfg.dormant_stoch_enabled and not self._check_stochastic_momentum(signal_direction, bar):
            self._dormant_prev_fast = fast
            self._dormant_prev_slow = slow
            return
        
        # Execute trade with dormant mode risk parameters
        position: Optional[Position] = self._current_position()
        if position is not None:
            self.log.warning(f"Unexpected position found during dormant mode {signal_direction} signal: {position}. Skipping entry.")
            self._dormant_prev_fast = fast
            self._dormant_prev_slow = slow
            return
        
        if self._is_fx:
            entry_price = Decimal(str(bar.close))
            order_side = OrderSide.BUY if signal_direction == "BUY" else OrderSide.SELL
            sl_price, tp_price = self._calculate_sl_tp_prices(entry_price, order_side, dormant_mode=True)
            
            self.log.info(
                f"DORMANT MODE {signal_direction} order - Entry: {entry_price}, SL: {sl_price}, TP: {tp_price}, "
                f"Risk: {self.cfg.dormant_stop_loss_pips} pips, Reward: {self.cfg.dormant_take_profit_pips} pips"
            )
            
            try:
                bracket_orders = self.order_factory.bracket(
                    instrument_id=self.instrument_id,
                    order_side=order_side,
                    quantity=Quantity.from_str(f"{int(self.trade_size)}.00"),
                    entry_price=Price.from_str(str(entry_price)),
                    sl_trigger_price=sl_price,
                    sl_trigger_type=TriggerType.DEFAULT,
                    tp_price=tp_price,
                    entry_tags=[f"{self.cfg.order_id_tag}_DORMANT"],
                    sl_tags=[f"{self.cfg.order_id_tag}_DORMANT_SL"],
                    tp_tags=[f"{self.cfg.order_id_tag}_DORMANT_TP"],
                )
                
                self.submit_order_list(bracket_orders)
                
                # Extract stop loss order for trailing functionality
                stop_orders = [o for o in bracket_orders.orders if "SL" in o.tags or o.order_type.name == "STOP_MARKET"]
                if stop_orders:
                    self._current_stop_order = stop_orders[0]
                    self._trailing_active = False
                    self._last_stop_price = Decimal(str(self._current_stop_order.trigger_price))
                    self._position_opened_in_dormant_mode = True
                    self.log.info(f"Dormant mode: Tracking stop loss order at {self._last_stop_price}")
                
                self._position_entry_price = Decimal(str(bar.close))
                self.log.info(f"Dormant mode - {signal_direction} {self.trade_size} with SL/TP bracket order submitted")
            except Exception as exc:
                self.log.error(f"Failed to create/submit dormant mode bracket order: {exc}", exc_info=True)
                raise
        else:
            self.log.warning(f"Dormant mode: Non-FX instrument - submitting market order without SL/TP")
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.BUY if signal_direction == "BUY" else OrderSide.SELL,
                quantity=Quantity.from_str(f"{int(self.trade_size)}.00"),
                tags=[f"{self.cfg.order_id_tag}_DORMANT"],
            )
            self.submit_order(order)
            self._position_opened_in_dormant_mode = True
            self.log.info(f"Dormant mode - {signal_direction} {self.trade_size} (no SL/TP for non-FX instrument)")
        
        # Update previous values
        self._dormant_prev_fast = fast
        self._dormant_prev_slow = slow

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
            # Track Stochastic bars for crossing detection
            self._stoch_bar_count += 1
            
            # Check for Stochastic crossing if indicator is initialized
            if self.stoch is not None and self.stoch.initialized:
                k_value = self.stoch.value_k
                d_value = self.stoch.value_d
                
                # Detect crossing: %K crosses above or below %D
                if self._stoch_prev_k is not None and self._stoch_prev_d is not None:
                    # Bullish crossing: %K was <= %D, now %K > %D
                    if self._stoch_prev_k <= self._stoch_prev_d and k_value > d_value:
                        self._stoch_last_cross_bar = self._stoch_bar_count
                        self._stoch_last_cross_direction = "BULLISH"
                        self.log.debug(
                            f"Stochastic bullish crossing detected on bar {self._stoch_bar_count}: "
                            f"%K crossed from {self._stoch_prev_k:.2f} to {k_value:.2f}, "
                            f"%D from {self._stoch_prev_d:.2f} to {d_value:.2f}"
                        )
                    # Bearish crossing: %K was >= %D, now %K < %D
                    elif self._stoch_prev_k >= self._stoch_prev_d and k_value < d_value:
                        self._stoch_last_cross_bar = self._stoch_bar_count
                        self._stoch_last_cross_direction = "BEARISH"
                        self.log.debug(
                            f"Stochastic bearish crossing detected on bar {self._stoch_bar_count}: "
                            f"%K crossed from {self._stoch_prev_k:.2f} to {k_value:.2f}, "
                            f"%D from {self._stoch_prev_d:.2f} to {d_value:.2f}"
                        )
                
                # Update previous values for next bar
                self._stoch_prev_k = k_value
                self._stoch_prev_d = d_value
            
            self.log.debug(f"Received Stochastic bar: close={bar.close}, bar_count={self._stoch_bar_count}")
            return
        
        # Route trend filter bars (higher timeframe) only if they are not the primary bar type
        if (
            self.cfg.trend_filter_enabled
            and self.trend_bar_type is not None
            and bar.bar_type == self.trend_bar_type
            and bar.bar_type != self.bar_type
        ):
            self.log.debug(f"Received trend bar: close={bar.close}, fast_sma={self.trend_fast_sma.value if self.trend_fast_sma else None}, slow_sma={self.trend_slow_sma.value if self.trend_slow_sma else None}")
            return  # Indicators update automatically
        
        # Route entry timing bars (lower timeframe) only if they are not the primary bar type
        if (
            self.cfg.entry_timing_enabled
            and self.entry_timing_bar_type is not None
            and bar.bar_type == self.entry_timing_bar_type
            and bar.bar_type != self.bar_type
        ):
            self.log.debug(f"Received entry timing bar: close={bar.close}")
            # Check if we have a pending signal and if entry timing conditions are met
            if self._pending_signal is not None:
                self._pending_signal_timeout_bars += 1
                # Check if timeout exceeded
                if self._pending_signal_timeout_bars >= self.cfg.entry_timing_timeout_bars:
                    self.log.debug(f"Entry timing timeout reached ({self._pending_signal_timeout_bars} bars), clearing pending {self._pending_signal} signal")
                    self._pending_signal = None
                    self._pending_signal_timestamp = None
                    self._pending_signal_timeout_bars = 0
                    return
                # Entry timing logic will be checked in _check_entry_timing when primary bar arrives
            return  # Indicators update automatically if registered
        
        # Route dormant mode bars (lower timeframe) only if they are not the primary bar type
        if (
            self.cfg.dormant_mode_enabled
            and self._dormant_bar_type is not None
            and bar.bar_type == self._dormant_bar_type
            and bar.bar_type != self.bar_type
        ):
            self._process_dormant_mode_bar(bar)
            return
        
        # Process primary bars for MA crossover logic
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
        
        # Determine if we have enough bars for proper warmup
        # We need at least slow_period bars for the slow SMA to be reliable
        bars_for_warmup = self.cfg.slow_period
        has_enough_bars = self._bar_count >= bars_for_warmup
        
        # Log warmup status periodically
        if self._bar_count % 50 == 0 or (self._bar_count < bars_for_warmup and self._bar_count % 10 == 0):
            remaining_bars = max(0, bars_for_warmup - self._bar_count)
            self.log.info(
                f"Warmup status: bars={self._bar_count}/{bars_for_warmup}, "
                f"remaining={remaining_bars}, "
                f"fast_ready={fast_ready}, slow_ready={slow_ready}, "
                f"warmup_complete={self._warmup_complete}"
            )
        
        self.log.debug(
            f"Indicator readiness -> fast_initialized={fast_ready}, slow_initialized={slow_ready}"
        )

        # Warmup is complete when:
        # 1. Both indicators have values (fast_ready and slow_ready)
        # 2. We have processed at least slow_period bars
        # 3. We have previous values set (needed for crossover detection)
        if not self._warmup_complete and fast_ready and slow_ready and has_enough_bars and self._prev_fast is not None and self._prev_slow is not None:
            self._warmup_complete = True
            self.log.info(
                f"[STRATEGY READY] Warmup complete after {self._bar_count} bars "
                f"(slow_period={self.cfg.slow_period}). Strategy is now ACTIVE and will generate signals."
            )

        if self._bar_count % 10 == 0:
            self.log.debug(
                f"Processed {self._bar_count} bars: fast_sma={fast} slow_sma={slow}"
            )

        # Initialize previous values if needed
        if self._prev_fast is None:
            self._prev_fast = fast
        if self._prev_slow is None:
            self._prev_slow = slow
        
        # Append MA values to history if both are not None
        if fast is not None and slow is not None:
            self._ma_history.append((fast, slow))
        
        # If indicators are not ready or warmup not complete, return early
        if fast is None or slow is None or not self._warmup_complete:
            # Update previous values even during warmup (for next bar comparison)
            self._prev_fast = fast
            self._prev_slow = slow
            return

        # Detect crossovers (only if warmup is complete)
        self.log.debug(
            f"SMA comparison -> prev_fast={self._prev_fast} prev_slow={self._prev_slow} current_fast={fast} current_slow={slow}"
        )
        
        bullish = fast > slow and (self._prev_fast is not None and self._prev_slow is not None) and self._prev_fast <= self._prev_slow
        bearish = fast < slow and (self._prev_fast is not None and self._prev_slow is not None) and self._prev_fast >= self._prev_slow

        if bullish:
            self.log.info(
                f"Bullish crossover detected (prev_fast={self._prev_fast}, prev_slow={self._prev_slow}, current_fast={fast}, current_slow={slow})"
            )
            
            # Track crossover timestamp for dormant mode detection
            if self.cfg.dormant_mode_enabled:
                self._last_crossover_timestamp = bar.ts_event
                # If dormant mode was active, deactivate it
                if self._dormant_mode_active:
                    self._dormant_mode_active = False
                    self.log.info("Dormant mode deactivated: Primary timeframe crossover detected")
            
            # Check crossover magnitude against threshold
            if not self._check_crossover_threshold("BUY", fast, slow, bar):
                # Do NOT update prev_* here; just return
                return
            # Check higher timeframe trend alignment (if enabled)
            if not self._check_trend_alignment("BUY"):
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
            
            # Check entry timing (if enabled)
            if not self._check_entry_timing("BUY", bar):
                return
            
            can_trade, reason = self._check_can_open_position("BUY")
            if not can_trade:
                self._log_rejected_signal("BUY", reason, bar)
                return  # Reject signal - position already open, will only close via TP/SL
            else:
                # No position open, proceed with entry
                position: Optional[Position] = self._current_position()
                has_position = position is not None
                
                # Safety check: ensure no position exists (should not happen)
                if has_position:
                    self.log.warning(f"Unexpected position found during BUY signal: {position}. Skipping entry.")
                    self._log_rejected_signal("BUY", "Unexpected position found", bar)
                    return
                
                self.log.debug(f"Current net position before BUY: {position}")
                
                if self._is_fx:
                    # Calculate SL/TP prices using bar close as entry reference for FX instruments
                    entry_price = Decimal(str(bar.close))
                    sl_price, tp_price = self._calculate_sl_tp_prices(entry_price, OrderSide.BUY)
                    
                    # Log SL/TP calculations
                    self.log.info(
                        f"BUY order - Entry: {entry_price}, SL: {sl_price}, TP: {tp_price}, "
                        f"Risk: {self.cfg.stop_loss_pips} pips, Reward: {self.cfg.take_profit_pips} pips"
                    )
                    
                    # Create bracket order with entry + SL + TP
                    try:
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
                        
                        # Log bracket order details for verification
                        self.log.info(
                            f"Created bracket order with {len(bracket_orders.orders)} orders: "
                            f"{[o.order_type.name for o in bracket_orders.orders]}"
                        )
                        
                        self.submit_order_list(bracket_orders)
                        
                        # Clear pending signal after submitting order
                        if self._pending_signal:
                            self._pending_signal = None
                            self._pending_signal_timestamp = None
                            self._pending_signal_timeout_bars = 0
                        
                        # Extract stop loss order from bracket for trailing functionality
                        stop_orders = [o for o in bracket_orders.orders if "SL" in o.tags or o.order_type.name == "STOP_MARKET"]
                        if stop_orders:
                            self._current_stop_order = stop_orders[0]
                            self._trailing_active = False
                            self._last_stop_price = Decimal(str(self._current_stop_order.trigger_price))
                            self.log.info(f"Tracking stop loss order: {self._current_stop_order.client_order_id} at {self._last_stop_price}")
                        else:
                            self.log.warning("No stop loss order found in bracket orders!")
                        
                        # Store entry price for trailing stop calculations (will be updated on fill)
                        self._position_entry_price = Decimal(str(bar.close))
                        self.log.info(f"Bullish crossover - BUY {self.trade_size} with SL/TP bracket order submitted")
                    except Exception as exc:
                        self.log.error(f"Failed to create/submit bracket order: {exc}", exc_info=True)
                        raise
                else:
                    # For non-FX instruments, create market order without SL/TP
                    self.log.warning(
                        f"⚠️ NON-FX INSTRUMENT DETECTED - Submitting market order WITHOUT SL/TP! "
                        f"Instrument: {self.instrument_id}, raw_symbol: {self.instrument.raw_symbol if self.instrument else 'N/A'}"
                    )
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
            
            # Track crossover timestamp for dormant mode detection
            if self.cfg.dormant_mode_enabled:
                self._last_crossover_timestamp = bar.ts_event
                # If dormant mode was active, deactivate it
                if self._dormant_mode_active:
                    self._dormant_mode_active = False
                    self.log.info("Dormant mode deactivated: Primary timeframe crossover detected")
            
            # Check crossover magnitude against threshold
            if not self._check_crossover_threshold("SELL", fast, slow, bar):
                # Do NOT update prev_* here; just return
                return
            # Check higher timeframe trend alignment (if enabled)
            if not self._check_trend_alignment("SELL"):
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
            
            # Check entry timing (if enabled)
            if not self._check_entry_timing("SELL", bar):
                return
            
            can_trade, reason = self._check_can_open_position("SELL")
            if not can_trade:
                self._log_rejected_signal("SELL", reason, bar)
                return  # Reject signal - position already open, will only close via TP/SL
            else:
                # No position open, proceed with entry
                position: Optional[Position] = self._current_position()
                has_position = position is not None
                
                # Safety check: ensure no position exists (should not happen)
                if has_position:
                    self.log.warning(f"Unexpected position found during SELL signal: {position}. Skipping entry.")
                    self._log_rejected_signal("SELL", "Unexpected position found", bar)
                    return
                
                self.log.debug(f"Current net position before SELL: {position}")
                
                if self._is_fx:
                    # Calculate SL/TP prices using bar close as entry reference for FX instruments
                    entry_price = Decimal(str(bar.close))
                    sl_price, tp_price = self._calculate_sl_tp_prices(entry_price, OrderSide.SELL)
                    
                    # Log SL/TP calculations
                    self.log.info(
                        f"SELL order - Entry: {entry_price}, SL: {sl_price}, TP: {tp_price}, "
                        f"Risk: {self.cfg.stop_loss_pips} pips, Reward: {self.cfg.take_profit_pips} pips"
                    )
                    
                    # Create bracket order with entry + SL + TP
                    try:
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
                        
                        # Log bracket order details for verification
                        self.log.info(
                            f"Created bracket order with {len(bracket_orders.orders)} orders: "
                            f"{[o.order_type.name for o in bracket_orders.orders]}"
                        )
                        
                        self.submit_order_list(bracket_orders)
                        
                        # Clear pending signal after submitting order
                        if self._pending_signal:
                            self._pending_signal = None
                            self._pending_signal_timestamp = None
                            self._pending_signal_timeout_bars = 0
                        
                        # Extract stop loss order from bracket for trailing functionality
                        stop_orders = [o for o in bracket_orders.orders if "SL" in o.tags or o.order_type.name == "STOP_MARKET"]
                        if stop_orders:
                            self._current_stop_order = stop_orders[0]
                            self._trailing_active = False
                            self._last_stop_price = Decimal(str(self._current_stop_order.trigger_price))
                            self.log.info(f"Tracking stop loss order: {self._current_stop_order.client_order_id} at {self._last_stop_price}")
                        else:
                            self.log.warning("No stop loss order found in bracket orders!")
                        
                        # Store entry price for trailing stop calculations (will be updated on fill)
                        self._position_entry_price = Decimal(str(bar.close))
                        self.log.info(f"Bearish crossover - SELL {self.trade_size} with SL/TP bracket order submitted")
                    except Exception as exc:
                        self.log.error(f"Failed to create/submit bracket order: {exc}", exc_info=True)
                        raise
                else:
                    # For non-FX instruments, create market order without SL/TP
                    self.log.warning(
                        f"⚠️ NON-FX INSTRUMENT DETECTED - Submitting market order WITHOUT SL/TP! "
                        f"Instrument: {self.instrument_id}, raw_symbol: {self.instrument.raw_symbol if self.instrument else 'N/A'}"
                    )
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
        
        # Check dormant mode activation/deactivation (only if enabled)
        if self.cfg.dormant_mode_enabled:
            self._check_dormant_mode_activation(bar)
        
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
        
        # Reset Stochastic tracking
        if self.stoch is not None:
            self.stoch.reset()
        self._stoch_bar_count = 0
        self._stoch_last_cross_bar = None
        self._stoch_last_cross_direction = None
        self._stoch_prev_k = None
        self._stoch_prev_d = None
        
        # Reset DMI if enabled
        if self.dmi is not None:
            self.dmi.reset()
        
        # Reset multi-timeframe indicators if enabled
        if self.trend_fast_sma is not None:
            self.trend_fast_sma.reset()
        if self.trend_slow_sma is not None:
            self.trend_slow_sma.reset()
        if self._entry_timing_fast_sma is not None:
            self._entry_timing_fast_sma.reset()
        if self._entry_timing_slow_sma is not None:
            self._entry_timing_slow_sma.reset()
        
        self._bar_count = 0
        self._warmup_complete = False
        
        # Reset trailing stop state
        self._current_stop_order = None
        self._position_entry_price = None
        self._trailing_active = False
        self._last_stop_price = None
    
    # Order lifecycle event handlers for comprehensive logging
    def on_order_event(self, event: OrderEvent) -> None:
        """Handle all order events with detailed logging."""
        order_logger = logging.getLogger("orders")
        
        if isinstance(event, OrderAccepted):
            order = self.cache.order(event.client_order_id)
            if order:
                order_logger.info(
                    f"ORDER ACCEPTED - client_order_id={event.client_order_id}, "
                    f"venue_order_id={event.venue_order_id or 'N/A'}, "
                    f"instrument_id={order.instrument_id}, "
                    f"side={order.side}, quantity={order.quantity}, "
                    f"order_type={order.order_type}, "
                    f"tags={order.tags}, ts_event={event.ts_event}"
                )
        elif isinstance(event, OrderFilled):
            order = self.cache.order(event.client_order_id)
            if order:
                # OrderFilled event has fill info directly on the event
                # Calculate quote quantity (value) from last_qty * last_px
                instrument = self.cache.instrument(event.instrument_id)
                quote_value = instrument.notional_value(event.last_qty, event.last_px) if instrument else None
                
                order_logger.info(
                    f"ORDER FILLED - client_order_id={event.client_order_id}, "
                    f"venue_order_id={event.venue_order_id or 'N/A'}, "
                    f"instrument_id={order.instrument_id}, "
                    f"side={order.side}, quantity={event.last_qty}, "
                    f"price={event.last_px}, value={quote_value or 'N/A'}, "
                    f"filled_qty={order.filled_qty}/{order.quantity}, "
                    f"order_type={order.order_type}, "
                    f"tags={order.tags}, ts_event={event.ts_event}"
                )
                # Also log to trades logger
                trade_logger = logging.getLogger("trades")
                trade_logger.info(
                    f"TRADE EXECUTED - client_order_id={event.client_order_id}, "
                    f"instrument_id={order.instrument_id}, "
                    f"side={order.side}, quantity={event.last_qty}, "
                    f"price={event.last_px}, value={quote_value or 'N/A'}, "
                    f"commission={event.commission}, "
                    f"ts_event={event.ts_event}"
                )
        elif isinstance(event, OrderRejected):
            order = self.cache.order(event.client_order_id)
            if order:
                order_logger.error(
                    f"ORDER REJECTED - client_order_id={event.client_order_id}, "
                    f"instrument_id={order.instrument_id}, "
                    f"side={order.side}, quantity={order.quantity}, "
                    f"order_type={order.order_type}, "
                    f"reason={event.reason}, "
                    f"tags={order.tags}, ts_event={event.ts_event}"
                )
        elif isinstance(event, OrderCanceled):
            order = self.cache.order(event.client_order_id)
            if order:
                order_logger.info(
                    f"ORDER CANCELED - client_order_id={event.client_order_id}, "
                    f"venue_order_id={event.venue_order_id or 'N/A'}, "
                    f"instrument_id={order.instrument_id}, "
                    f"side={order.side}, quantity={order.quantity}, "
                    f"filled_qty={order.filled_qty}, "
                    f"order_type={order.order_type}, "
                    f"tags={order.tags}, ts_event={event.ts_event}"
                )
        elif isinstance(event, OrderCancelRejected):
            order = self.cache.order(event.client_order_id)
            if order:
                order_logger.warning(
                    f"ORDER CANCEL REJECTED - client_order_id={event.client_order_id}, "
                    f"instrument_id={order.instrument_id}, "
                    f"reason={event.reason}, "
                    f"ts_event={event.ts_event}"
                )
        elif isinstance(event, OrderExpired):
            order = self.cache.order(event.client_order_id)
            if order:
                order_logger.info(
                    f"ORDER EXPIRED - client_order_id={event.client_order_id}, "
                    f"instrument_id={order.instrument_id}, "
                    f"side={order.side}, quantity={order.quantity}, "
                    f"order_type={order.order_type}, "
                    f"tags={order.tags}, ts_event={event.ts_event}"
                )
        elif isinstance(event, OrderTriggered):
            order = self.cache.order(event.client_order_id)
            if order:
                order_logger.info(
                    f"ORDER TRIGGERED - client_order_id={event.client_order_id}, "
                    f"venue_order_id={event.venue_order_id or 'N/A'}, "
                    f"instrument_id={order.instrument_id}, "
                    f"side={order.side}, quantity={order.quantity}, "
                    f"order_type={order.order_type}, "
                    f"tags={order.tags}, ts_event={event.ts_event}"
                )
        elif isinstance(event, OrderUpdated):
            order = self.cache.order(event.client_order_id)
            if order:
                order_logger.info(
                    f"ORDER UPDATED - client_order_id={event.client_order_id}, "
                    f"venue_order_id={event.venue_order_id or 'N/A'}, "
                    f"instrument_id={order.instrument_id}, "
                    f"side={order.side}, quantity={order.quantity}, "
                    f"filled_qty={order.filled_qty}, "
                    f"order_type={order.order_type}, "
                    f"tags={order.tags}, ts_event={event.ts_event}"
                )
        elif isinstance(event, OrderPendingUpdate):
            order = self.cache.order(event.client_order_id)
            if order:
                order_logger.debug(
                    f"ORDER PENDING UPDATE - client_order_id={event.client_order_id}, "
                    f"instrument_id={order.instrument_id}, "
                    f"ts_event={event.ts_event}"
                )
        else:
            # Log any other order events
            order_logger.debug(
                f"ORDER EVENT - type={type(event).__name__}, "
                f"client_order_id={event.client_order_id}, "
                f"ts_event={event.ts_event}"
            )
    
    def on_position_event(self, event: PositionEvent) -> None:
        """Handle all position events with detailed logging."""
        trade_logger = logging.getLogger("trades")
        
        if isinstance(event, PositionOpened):
            # PositionOpened event has position info directly on the event
            trade_logger.info(
                f"POSITION OPENED - position_id={event.position_id}, "
                f"instrument_id={event.instrument_id}, "
                f"side={event.side}, entry={event.entry}, "
                f"quantity={event.quantity}, "
                f"avg_px_open={event.avg_px_open}, "
                f"unrealized_pnl={event.unrealized_pnl}, "
                f"ts_event={event.ts_event}"
            )
        elif isinstance(event, PositionChanged):
            # PositionChanged event has position info directly on the event
            trade_logger.info(
                f"POSITION CHANGED - position_id={event.position_id}, "
                f"instrument_id={event.instrument_id}, "
                f"side={event.side}, quantity={event.quantity}, "
                f"avg_px_open={event.avg_px_open}, "
                f"unrealized_pnl={event.unrealized_pnl}, "
                f"ts_event={event.ts_event}"
            )
        elif isinstance(event, PositionClosed):
            # PositionClosed event has position info directly on the event
            trade_logger.info(
                f"POSITION CLOSED - position_id={event.position_id}, "
                f"instrument_id={event.instrument_id}, "
                f"side={event.side}, entry={event.entry}, "
                f"quantity={event.quantity}, "
                f"avg_px_open={event.avg_px_open}, "
                f"avg_px_close={event.avg_px_close}, "
                f"realized_pnl={event.realized_pnl}, "
                f"ts_event={event.ts_event}"
            )
            # Reset dormant mode position flag when position closes
            self._position_opened_in_dormant_mode = False
            # Reset trailing stop state when position closes (via TP/SL)
            self._current_stop_order = None
            self._position_entry_price = None
            self._trailing_active = False
            self._last_stop_price = None
            self.log.debug("Trailing stop state reset after position closed")
        else:
            trade_logger.debug(
                f"POSITION EVENT - type={type(event).__name__}, "
                f"position_id={getattr(event, 'position_id', 'N/A')}, "
                f"ts_event={event.ts_event}"
            )
