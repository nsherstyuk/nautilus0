"""
Moving Average Crossover strategy for NautilusTrader.

This strategy uses two Simple Moving Averages (SMA) to generate
buy/sell signals on crossovers.
"""
from __future__ import annotations

from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo  # type: ignore
    _HAS_ZONEINFO = True
except Exception:
    ZoneInfo = None  # type: ignore
    _HAS_ZONEINFO = False
try:
    import pytz  # type: ignore
    _HAS_PYTZ = True
except Exception:
    pytz = None  # type: ignore
    _HAS_PYTZ = False
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple, cast

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.indicators import SimpleMovingAverage, Stochastics, AverageTrueRange
from nautilus_trader.model.position import Position
from nautilus_trader.model.objects import Quantity, Price
from nautilus_trader.model.enums import OrderSide, TriggerType, OrderType, TimeInForce
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
    dmi_enabled: bool = True
    dmi_bar_spec: str = "2-MINUTE-MID-EXTERNAL"
    dmi_period: int = 14
    stoch_enabled: bool = True
    stoch_bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    stoch_period_k: int = 14
    stoch_period_d: int = 3
    stoch_bullish_threshold: int = 30
    stoch_bearish_threshold: int = 70
    stoch_max_bars_since_crossing: int = 9
    atr_enabled: bool = False
    atr_period: int = 14
    atr_min_threshold: float = 0.0003
    atr_max_threshold: float = 0.003
    # Time-of-day filter configuration
    time_filter_enabled: bool = False
    trading_hours_start: int = 8
    trading_hours_end: int = 16
    market_timezone: str = "America/New_York"
    excluded_hours: List[int] = []
    # ADX trend strength filter configuration
    adx_enabled: bool = False
    adx_period: int = 14
    adx_min_threshold: float = 20.0

    # Circuit breaker configuration
    circuit_breaker_enabled: bool = False
    max_consecutive_losses: int = 3
    cooldown_bars: int = 10
    
    # Limit order configuration
    use_limit_orders: bool = True
    limit_order_timeout_bars: int = 1


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
        
        # DMI indicator for trend confirmation (optional, 2-minute bars)
        self.dmi: Optional[DMI] = None
        self.dmi_bar_type: Optional[BarType] = None
        if config.dmi_enabled:
            # Ensure ADX period alignment when ADX filter is enabled
            if config.adx_enabled and config.adx_period != config.dmi_period:
                self.log.warning(
                    f"ADX period ({config.adx_period}) differs from DMI period ({config.dmi_period}); using DMI period for ADX calculations"
                )
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
        
        # Stochastic crossing tracking state variables
        self._prev_stoch_k: Optional[float] = None
        self._prev_stoch_d: Optional[float] = None
        self._last_stoch_crossing_time: Optional[int] = None
        self._last_stoch_crossing_direction: Optional[str] = None
        
        # ATR indicator for volatility confirmation (optional, primary bar type)
        self.atr: Optional[AverageTrueRange] = None
        if config.atr_enabled:
            self.atr = AverageTrueRange(period=config.atr_period)
        
        # Trailing stop state tracking
        self._current_stop_order: Optional[StopMarketOrder] = None
        self._position_entry_price: Optional[Decimal] = None
        self._trailing_active: bool = False
        self._last_stop_price: Optional[Decimal] = None

        # Circuit breaker state
        self._consecutive_losses: int = 0
        self._circuit_breaker_active: bool = False
        self._cooldown_remaining_bars: int = 0
        # Sanitized circuit breaker config (set on start)
        self._cb_max_losses: int = 1
        self._cb_cooldown_bars: int = 1
        
        # Pending signal state for limit orders
        self._pending_signal: Optional[str] = None
        self._pending_signal_bar_time: Optional[int] = None
        self._pending_limit_orders: List[Tuple[Order, int]] = []

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
            self.log.info(f"Stochastic filter enabled: subscribed to {self.stoch_bar_type} (period_k={self.cfg.stoch_period_k}, period_d={self.cfg.stoch_period_d}, bullish_threshold={self.cfg.stoch_bullish_threshold}, bearish_threshold={self.cfg.stoch_bearish_threshold}, max_bars_since_crossing={self.cfg.stoch_max_bars_since_crossing})")
        else:
            self.log.info("Stochastic filter disabled")
        
        # Register ATR indicator for primary bar type if enabled
        if self.atr is not None:
            self.register_indicator_for_bars(self.bar_type, self.atr)
            self.log.info(f"ATR volatility filter enabled: period={self.cfg.atr_period}, min_threshold={self.cfg.atr_min_threshold}, max_threshold={self.cfg.atr_max_threshold}")
        else:
            self.log.info("ATR volatility filter disabled")
        
        # Time-of-day filter status
        if self.cfg.time_filter_enabled:
            self.log.info(
                f"Time-of-day filter enabled: trading_hours={self.cfg.trading_hours_start:02d}:00-{self.cfg.trading_hours_end:02d}:00 {self.cfg.market_timezone}, excluded_hours={self.cfg.excluded_hours}"
            )
        else:
            self.log.info("Time-of-day filter disabled")
        
        # ADX trend strength filter status (uses DMI indicator)
        if self.dmi is not None and self.cfg.adx_enabled:
            # Reflect the effective period used by ADX (DMI.period)
            self.log.info(
                f"ADX trend strength filter enabled: period={self.dmi.period}, min_threshold={self.cfg.adx_min_threshold} (using DMI indicator on {self.dmi_bar_type})"
            )
        else:
            self.log.info("ADX trend strength filter disabled")

        # Circuit breaker status and validation (sanitize effective values)
        self._cb_max_losses = max(1, int(self.cfg.max_consecutive_losses))
        self._cb_cooldown_bars = max(1, int(self.cfg.cooldown_bars))
        if self.cfg.circuit_breaker_enabled:
            self.log.info(
                f"Circuit breaker enabled: max_consecutive_losses={self._cb_max_losses}, cooldown_bars={self._cb_cooldown_bars}"
            )
        else:
            self.log.info("Circuit breaker disabled")
        
        # Limit order configuration logging
        if self.cfg.use_limit_orders:
            self.log.info(f"Limit orders enabled: entry at next bar open price, timeout={self.cfg.limit_order_timeout_bars} bars")
        else:
            self.log.info("Market orders enabled: immediate execution at bar close")

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
            
            # Check recency of Stochastic crossing for BUY signals
            if self._last_stoch_crossing_time is not None:
                bars_since_crossing = int((bar.ts_event - self._last_stoch_crossing_time) / 60_000_000_000)
                
                if bars_since_crossing > self.cfg.stoch_max_bars_since_crossing:
                    self._log_rejected_signal(
                        "BUY",
                        f"stochastic_crossing_too_old (bars_since_stoch_crossing={bars_since_crossing} > max={self.cfg.stoch_max_bars_since_crossing}, stoch_crossing_direction={self._last_stoch_crossing_direction}, required_direction=bullish)",
                        bar
                    )
                    return False
                
                if self._last_stoch_crossing_direction != "bullish":
                    self._log_rejected_signal(
                        "BUY",
                        f"stochastic_crossing_direction_mismatch (required_direction=bullish, actual={self._last_stoch_crossing_direction}, bars_since_stoch_crossing={bars_since_crossing})",
                        bar
                    )
                    return False
                
                self.log.debug(f"Stochastic crossing recency confirmed for BUY: bullish crossing {bars_since_crossing} bars ago (max={self.cfg.stoch_max_bars_since_crossing})")
            else:
                self.log.debug("Stochastic crossing recency check skipped: no crossing detected yet (warmup period)")
            
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
            
            # Check recency of Stochastic crossing for SELL signals
            if self._last_stoch_crossing_time is not None:
                bars_since_crossing = int((bar.ts_event - self._last_stoch_crossing_time) / 60_000_000_000)
                
                if bars_since_crossing > self.cfg.stoch_max_bars_since_crossing:
                    self._log_rejected_signal(
                        "SELL",
                        f"stochastic_crossing_too_old (bars_since_stoch_crossing={bars_since_crossing} > max={self.cfg.stoch_max_bars_since_crossing}, stoch_crossing_direction={self._last_stoch_crossing_direction}, required_direction=bearish)",
                        bar
                    )
                    return False
                
                if self._last_stoch_crossing_direction != "bearish":
                    self._log_rejected_signal(
                        "SELL",
                        f"stochastic_crossing_direction_mismatch (required_direction=bearish, actual={self._last_stoch_crossing_direction}, bars_since_stoch_crossing={bars_since_crossing})",
                        bar
                    )
                    return False
                
                self.log.debug(f"Stochastic crossing recency confirmed for SELL: bearish crossing {bars_since_crossing} bars ago (max={self.cfg.stoch_max_bars_since_crossing})")
            else:
                self.log.debug("Stochastic crossing recency check skipped: no crossing detected yet (warmup period)")
        
        return True
    
    def _check_time_of_day(self, direction: str, bar: Bar) -> bool:
        """Check if current bar time is within allowed trading hours.
        
        Args:
            direction: "BUY" or "SELL"
            bar: Current bar for logging
            
        Returns:
            True if time filter passes or is disabled, False otherwise
        """
        # Skip if disabled
        if not self.cfg.time_filter_enabled:
            return True
        
        # Handle missing timestamp gracefully
        if getattr(bar, "ts_event", None) is None:
            self.log.warning("Bar ts_event is None; skipping time-of-day check")
            return True
        
        bar_dt_utc = datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=timezone.utc)
        # Resolve market timezone with graceful fallback
        if _HAS_ZONEINFO:
            try:
                tz = ZoneInfo(self.cfg.market_timezone)  # type: ignore[arg-type]
                bar_dt_market = bar_dt_utc.astimezone(tz)
            except Exception as exc:
                self.log.warning(
                    f"Invalid timezone '{self.cfg.market_timezone}' ({exc}); falling back to UTC for time-of-day check"
                )
                bar_dt_market = bar_dt_utc
        elif _HAS_PYTZ:
            try:
                tz = pytz.timezone(self.cfg.market_timezone)  # type: ignore[attr-defined]
                bar_dt_market = bar_dt_utc.astimezone(tz)
            except Exception as exc:
                self.log.warning(
                    f"Timezone fallback using pytz failed for '{self.cfg.market_timezone}' ({exc}); using UTC"
                )
                bar_dt_market = bar_dt_utc
        else:
            self.log.warning(
                "ZoneInfo and pytz are unavailable; using UTC for time-of-day check"
            )
            bar_dt_market = bar_dt_utc
        
        bar_hour = bar_dt_market.hour
        bar_time_str = bar_dt_market.strftime("%H:%M:%S %Z")
        
        # Excluded hours take precedence
        if self.cfg.excluded_hours and bar_hour in self.cfg.excluded_hours:
            self._log_rejected_signal(
                direction,
                f"time_filter_excluded_hour (bar_time={bar_time_str}, excluded_hours={self.cfg.excluded_hours})",
                bar,
            )
            return False
        
        start_hour = int(self.cfg.trading_hours_start)
        end_hour = int(self.cfg.trading_hours_end)

        # Validate and normalize trading hour inputs
        invalid_range = not (0 <= start_hour <= 24 and 0 <= end_hour <= 24)
        if invalid_range:
            self.log.warning(
                f"Invalid trading hours ({start_hour}-{end_hour}); defaulting to 00:00-24:00"
            )
            start_hour, end_hour = 0, 24

        # Require explicit 0-24 for full-day trading to avoid accidental all-day when start==end
        if start_hour == 0 and end_hour == 24:
            self.log.debug(
                f"Time-of-day filter passed for {direction}: bar_time={bar_time_str}, window=ALL DAY {getattr(bar_dt_market.tzinfo, 'key', str(bar_dt_market.tzinfo))}"
            )
            return True

        # If start equals end within range but not 0-24, treat as misconfiguration and default to safe window
        if start_hour == end_hour:
            self.log.warning(
                f"Trading hours start equals end ({start_hour}); defaulting to 00:00-24:00 to avoid zero-width window"
            )
            start_hour, end_hour = 0, 24
        
        # Normal daytime window
        if start_hour < end_hour:
            in_window = start_hour <= bar_hour < end_hour
        else:
            # Overnight window (wrap-around)
            in_window = (bar_hour >= start_hour) or (bar_hour < end_hour)
        
        if not in_window:
            tz_label = getattr(bar_dt_market.tzinfo, "key", str(bar_dt_market.tzinfo))
            self._log_rejected_signal(
                direction,
                f"time_filter_outside_hours (bar_time={bar_time_str}, allowed={start_hour:02d}:00-{end_hour:02d}:00 {tz_label})",
                bar,
            )
            return False
        
        tz_label = getattr(bar_dt_market.tzinfo, "key", str(bar_dt_market.tzinfo))
        self.log.debug(
            f"Time-of-day filter passed for {direction}: bar_time={bar_time_str}, window={start_hour:02d}:00-{end_hour:02d}:00 {tz_label}"
        )
        return True
    
    def _check_atr_volatility(self, direction: str, bar: Bar) -> bool:
        """Check if ATR volatility is within acceptable range for trading.
        
        Args:
            direction: "BUY" or "SELL"
            bar: Current bar for logging
            
        Returns:
            True if ATR check passes or is disabled/not ready, False if volatility is outside acceptable range
        """
        # Skip check if ATR is disabled
        if self.atr is None:
            return True
        
        # Skip check if ATR not initialized yet (not enough bars)
        if not self.atr.initialized:
            self.log.debug("ATR not initialized yet, skipping ATR check")
            return True
        
        # Get current ATR value
        atr_value = self.atr.value
        # Convert thresholds to Decimal for consistent comparison with Decimal ATR value
        atr_min = Decimal(str(self.cfg.atr_min_threshold))
        atr_max = Decimal(str(self.cfg.atr_max_threshold))
        
        # Check minimum threshold (too choppy/low volatility)
        if atr_value < atr_min:
            self._log_rejected_signal(
                direction,
                f"atr_too_low (ATR={atr_value:.6f} < min_threshold={atr_min})",
                bar
            )
            return False
        
        # Check maximum threshold (too volatile/extreme risk)
        if atr_value > atr_max:
            self._log_rejected_signal(
                direction,
                f"atr_too_high (ATR={atr_value:.6f} > max_threshold={atr_max})",
                bar
            )
            return False
        
        # ATR volatility is acceptable
        self.log.debug(f"ATR volatility acceptable for {direction}: ATR={atr_value:.6f} (range: {atr_min} - {atr_max})")
        return True

    def _check_adx_trend_strength(self, direction: str, bar: Bar) -> bool:
        """Check if ADX indicates sufficient trend strength for trading.
        
        Args:
            direction: "BUY" or "SELL"
            bar: Current bar for logging
            
        Returns:
            True if ADX check passes or is disabled/not ready, False if trend is too weak
        """
        # Skip if ADX filter disabled
        if not self.cfg.adx_enabled:
            return True
        # ADX depends on DMI
        if self.dmi is None:
            return True
        # Require DMI and ADX initialization (warmup)
        if not self.dmi.initialized or not getattr(self.dmi, "adx_initialized", False):
            self.log.debug("DMI/ADX not initialized yet, skipping ADX check")
            return True
        
        adx_value = float(self.dmi.adx)
        min_threshold = float(self.cfg.adx_min_threshold)
        
        if adx_value < min_threshold:
            self._log_rejected_signal(
                direction,
                f"adx_trend_too_weak (ADX={adx_value:.2f} < min_threshold={min_threshold})",
                bar,
            )
            return False
        
        self.log.debug(
            f"ADX trend strength sufficient for {direction}: ADX={adx_value:.2f} (threshold: {min_threshold})"
        )
        return True

    def _check_circuit_breaker(self, direction: str, bar: Bar) -> bool:
        """Check if circuit breaker is active and reject trades during cooldown period.

        Args:
            direction: "BUY" or "SELL"
            bar: Current bar for logging

        Returns:
            True if circuit breaker is disabled or inactive, False if in cooldown.
        """
        # Skip if disabled
        if not self.cfg.circuit_breaker_enabled:
            return True

        # Reject during active cooldown
        if self._circuit_breaker_active:
            self._log_rejected_signal(
                direction,
                f"circuit_breaker_active (consecutive_losses={self._consecutive_losses}, cooldown_remaining={self._cooldown_remaining_bars} bars)",
                bar,
            )
            return False

        # Passed
        self.log.debug(
            f"Circuit breaker check passed for {direction}: consecutive_losses={self._consecutive_losses}/{self._cb_max_losses}"
        )
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
    
    def _place_pending_limit_order(self, signal_type: str, bar: Bar) -> None:
        """Place limit bracket order at Bar N+1 open price for pending signal from Bar N.
        
        Args:
            signal_type: "BUY" or "SELL"
            bar: Bar N+1 (execution bar)
        """
        # Validate signal type
        if signal_type not in ["BUY", "SELL"]:
            self.log.error(f"Invalid signal type: {signal_type}")
            return
        
        # Re-validate position status (handle edge case where position opened between Bar N and Bar N+1)
        can_trade, reason = self._check_can_open_position(signal_type)
        if not can_trade:
            self._log_rejected_signal(signal_type, f"position_opened_since_signal_confirmation: {reason}", bar)
            return
        
        # Close existing opposite position if needed
        position: Optional[Position] = self._current_position()
        if position is not None:
            if (signal_type == "BUY" and getattr(position, "is_short", False)) or \
               (signal_type == "SELL" and getattr(position, "is_long", False)):
                self.close_all_positions(self.instrument_id)
                # Reset trailing stop state
                self._current_stop_order = None
                self._position_entry_price = None
                self._trailing_active = False
                self._last_stop_price = None
                self.log.info(f"Closed existing {position.side.name} position before {signal_type} limit order")
        
        # Calculate limit price and SL/TP prices
        if bar.open is None:
            self.log.error("Bar open price is None, using bar close as fallback")
            limit_price = Decimal(str(bar.close))
        else:
            limit_price = Decimal(str(bar.open))
        
        # Calculate SL/TP using limit price as reference
        order_side = OrderSide.BUY if signal_type == "BUY" else OrderSide.SELL
        sl_price, tp_price = self._calculate_sl_tp_prices(limit_price, order_side)
        
        self.log.info(f"{signal_type} LIMIT order - Entry: {limit_price} (bar.open), SL: {sl_price}, TP: {tp_price}")
        
        try:
            if self._is_fx:
                # Create limit bracket order for FX instruments
                bracket_orders = self.order_factory.bracket(
                    instrument_id=self.instrument_id,
                    order_side=order_side,
                    quantity=Quantity.from_str(f"{int(self.trade_size)}.00"),
                    entry_order_type=OrderType.LIMIT,
                    entry_price=self.instrument.make_price(str(limit_price)),
                    time_in_force=TimeInForce.GTC,
                    sl_trigger_price=sl_price,
                    sl_trigger_type=TriggerType.DEFAULT,
                    tp_price=tp_price,
                    entry_tags=[self.cfg.order_id_tag],
                    sl_tags=[f"{self.cfg.order_id_tag}_SL"],
                    tp_tags=[f"{self.cfg.order_id_tag}_TP"],
                )
                self.submit_order_list(bracket_orders)
                
                # Extract entry order from bracket (first order is parent entry)
                entry_order = bracket_orders.orders[0]
                self._pending_limit_orders.append((entry_order, self._bar_count))
                
                # Extract stop loss order for trailing functionality
                stop_orders = [o for o in bracket_orders.orders if "SL" in o.tags or o.order_type.name == "STOP_MARKET"]
                if stop_orders:
                    self._current_stop_order = stop_orders[0]
                    self._trailing_active = False
                    self._last_stop_price = Decimal(str(self._current_stop_order.trigger_price))
                    self.log.debug(f"Tracking stop loss order: {self._current_stop_order.client_order_id} at {self._last_stop_price}")
                
                # Store entry price for trailing stop calculations
                self._position_entry_price = limit_price
                self.log.info(f"{signal_type} LIMIT bracket order submitted at {limit_price}")
            else:
                # Create simple limit order for non-FX instruments
                order = self.order_factory.limit(
                    instrument_id=self.instrument_id,
                    order_side=order_side,
                    quantity=Quantity.from_str(f"{int(self.trade_size)}.00"),
                    price=self.instrument.make_price(str(limit_price)),
                    time_in_force=TimeInForce.GTC,
                    tags=[self.cfg.order_id_tag],
                )
                self.submit_order(order)
                self._pending_limit_orders.append((order, self._bar_count))
                self.log.info(f"{signal_type} LIMIT order submitted at {limit_price} (no SL/TP for non-FX instrument)")
                
        except Exception as e:
            self.log.error(f"Failed to create limit order: {e}")
            return

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
        
        # Route Stochastic bars for crossing detection
        if (
            self.stoch_bar_type is not None
            and bar.bar_type == self.stoch_bar_type
        ):
            self.log.debug(f"Received Stochastic bar: close={bar.close}")
            
            # Stochastic crossing detection logic
            if self.stoch is not None and self.stoch.initialized:
                current_k = self.stoch.value_k
                current_d = self.stoch.value_d
                
                # Check for crossings if we have previous values
                if self._prev_stoch_k is not None and self._prev_stoch_d is not None:
                    # Detect bullish crossing: %K crosses above %D
                    if self._prev_stoch_k <= self._prev_stoch_d and current_k > current_d:
                        self._last_stoch_crossing_time = bar.ts_event
                        self._last_stoch_crossing_direction = "bullish"
                        self.log.info(f"Stochastic BULLISH crossing detected: %K crossed above %D (prev_k={self._prev_stoch_k:.2f}, prev_d={self._prev_stoch_d:.2f}, current_k={current_k:.2f}, current_d={current_d:.2f}) at {bar.ts_event}")
                    
                    # Detect bearish crossing: %K crosses below %D
                    elif self._prev_stoch_k >= self._prev_stoch_d and current_k < current_d:
                        self._last_stoch_crossing_time = bar.ts_event
                        self._last_stoch_crossing_direction = "bearish"
                        self.log.info(f"Stochastic BEARISH crossing detected: %K crossed below %D (prev_k={self._prev_stoch_k:.2f}, prev_d={self._prev_stoch_d:.2f}, current_k={current_k:.2f}, current_d={current_d:.2f}) at {bar.ts_event}")
                
                # Update previous values for next crossing detection
                self._prev_stoch_k = current_k
                self._prev_stoch_d = current_d
            
            # Only return if Stochastic bar type is different from primary bar type
            if bar.bar_type != self.bar_type:
                return
        
        # Process 1-minute bars for MA crossover logic
        if _normalize_price_alias(bar.bar_type.spec) != _normalize_price_alias(self.bar_type.spec):
            return

        # Check for limit order timeouts
        if self._pending_limit_orders:
            orders_to_remove = []
            for i, (order, placement_bar_count) in enumerate(self._pending_limit_orders):
                bars_elapsed = self._bar_count - placement_bar_count
                if bars_elapsed >= self.cfg.limit_order_timeout_bars:
                    if order.is_open:
                        self.cancel_order(order)
                        self.log.info(f"Cancelled unfilled limit order {order.client_order_id} after {bars_elapsed} bars (timeout={self.cfg.limit_order_timeout_bars})")
                    orders_to_remove.append(i)
                elif not order.is_open:
                    # Order filled or cancelled, remove from tracking
                    orders_to_remove.append(i)
            
            # Remove processed orders (in reverse order to maintain indices)
            for i in reversed(orders_to_remove):
                self._pending_limit_orders.pop(i)

        # Circuit breaker cooldown countdown (run whenever breaker is active)
        if self.cfg.circuit_breaker_enabled and self._circuit_breaker_active:
            if self._cooldown_remaining_bars > 0:
                self._cooldown_remaining_bars -= 1
                self.log.debug(f"Circuit breaker cooldown: {self._cooldown_remaining_bars} bars remaining")
            if self._cooldown_remaining_bars <= 0:
                self._circuit_breaker_active = False
                self._consecutive_losses = 0
                self.log.info("Circuit breaker cooldown expired - trading resumed (consecutive losses reset to 0)")

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

        # Check for pending signal from previous bar (limit order logic) - moved after crossover detection
        if self._pending_signal is not None:
            # Check for signal reversal before placing limit order
            if self._pending_signal == "BUY" and bearish:
                self.log.info(f"Pending BUY signal cancelled due to bearish crossover reversal")
                self._pending_signal = None
                self._pending_signal_bar_time = None
                self._log_rejected_signal("BUY", "pending_signal_reversed_by_bearish_crossover", bar)
            elif self._pending_signal == "SELL" and bullish:
                self.log.info(f"Pending SELL signal cancelled due to bullish crossover reversal")
                self._pending_signal = None
                self._pending_signal_bar_time = None
                self._log_rejected_signal("SELL", "pending_signal_reversed_by_bullish_crossover", bar)
            else:
                # No reversal, place the pending limit order
                self.log.info(f"Processing pending {self._pending_signal} signal from previous bar - placing LIMIT order at bar.open={bar.open}")
                self._place_pending_limit_order(self._pending_signal, bar)
                self._pending_signal = None
                self._pending_signal_bar_time = None

        if bullish:
            self.log.info(
                f"Bullish crossover detected (prev_fast={self._prev_fast}, prev_slow={self._prev_slow}, current_fast={fast}, current_slow={slow})"
            )
            
            # Circuit breaker first
            if not self._check_circuit_breaker("BUY", bar):
                return

            # Check crossover magnitude against threshold
            if not self._check_crossover_threshold("BUY", fast, slow, bar):
                # Do NOT update prev_* here; just return
                return
            # Check ATR volatility
            if not self._check_atr_volatility("BUY", bar):
                return
            # Check time-of-day
            if not self._check_time_of_day("BUY", bar):
                return
            # Check ADX trend strength
            if not self._check_adx_trend_strength("BUY", bar):
                return
            # Check DMI trend alignment
            if not self._check_dmi_trend("BUY", bar):
                return
            
            # Check Stochastic momentum alignment
            if not self._check_stochastic_momentum("BUY", bar):
                return
            
            # Check for signal reversal (cancel opposite pending signal)
            if self._pending_signal == "SELL":
                self.log.info(f"Pending SELL signal cancelled due to bullish crossover reversal")
                self._pending_signal = None
                self._pending_signal_bar_time = None
                self._log_rejected_signal("SELL", "pending_signal_reversed_by_bullish_crossover", bar)
            
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
                    
                    if self.cfg.use_limit_orders:
                        # Check for existing open entry orders before storing new pending signal
                        if self._pending_limit_orders:
                            # Cancel existing open entry orders
                            for order, _ in self._pending_limit_orders:
                                if order.is_open:
                                    self.cancel_order(order)
                                    self.log.info(f"Cancelled existing open entry order {order.client_order_id} before storing new BUY signal")
                            self._pending_limit_orders.clear()
                        
                        # Store pending signal for next bar
                        self._pending_signal = "BUY"
                        self._pending_signal_bar_time = bar.ts_event
                        self.log.info(f"Bullish crossover confirmed at Bar N - pending BUY signal stored, will place LIMIT order at next bar open")
                    else:
                        # Market order behavior (backward compatibility)
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
            
            # Circuit breaker first
            if not self._check_circuit_breaker("SELL", bar):
                return

            # Check crossover magnitude against threshold
            if not self._check_crossover_threshold("SELL", fast, slow, bar):
                # Do NOT update prev_* here; just return
                return
            # Check ATR volatility
            if not self._check_atr_volatility("SELL", bar):
                return
            # Check time-of-day
            if not self._check_time_of_day("SELL", bar):
                return
            # Check ADX trend strength
            if not self._check_adx_trend_strength("SELL", bar):
                return
            # Check DMI trend alignment
            if not self._check_dmi_trend("SELL", bar):
                return
            
            # Check Stochastic momentum alignment
            if not self._check_stochastic_momentum("SELL", bar):
                return
            
            # Check for signal reversal (cancel opposite pending signal)
            if self._pending_signal == "BUY":
                self.log.info(f"Pending BUY signal cancelled due to bearish crossover reversal")
                self._pending_signal = None
                self._pending_signal_bar_time = None
                self._log_rejected_signal("BUY", "pending_signal_reversed_by_bearish_crossover", bar)
            
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
                    
                    if self.cfg.use_limit_orders:
                        # Check for existing open entry orders before storing new pending signal
                        if self._pending_limit_orders:
                            # Cancel existing open entry orders
                            for order, _ in self._pending_limit_orders:
                                if order.is_open:
                                    self.cancel_order(order)
                                    self.log.info(f"Cancelled existing open entry order {order.client_order_id} before storing new SELL signal")
                            self._pending_limit_orders.clear()
                        
                        # Store pending signal for next bar
                        self._pending_signal = "SELL"
                        self._pending_signal_bar_time = bar.ts_event
                        self.log.info(f"Bearish crossover confirmed at Bar N - pending SELL signal stored, will place LIMIT order at next bar open")
                    else:
                        # Market order behavior (backward compatibility)
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

    def on_position_closed(self, position: Position) -> None:
        """Handle position closure events to track consecutive losses for circuit breaker."""
        # Skip if circuit breaker disabled
        if not self.cfg.circuit_breaker_enabled:
            return
        # Only track for this instrument
        if position.instrument_id != self.instrument_id:
            return

        realized_pnl = Decimal(str(position.realized_pnl)) if getattr(position, "realized_pnl", None) is not None else Decimal("0")
        if realized_pnl <= 0:
            self._consecutive_losses += 1
            self.log.info(
                f"Position closed with loss: PnL={realized_pnl}, consecutive_losses={self._consecutive_losses}/{self._cb_max_losses}"
            )
            if self._consecutive_losses >= self._cb_max_losses:
                # Guard activation by raw config: if non-positive, do not start cooldown
                if int(self.cfg.cooldown_bars) <= 0:
                    self._circuit_breaker_active = False
                    self._cooldown_remaining_bars = 0
                    self.log.warning(
                        "Circuit breaker cooldown not started due to non-positive configured cooldown_bars"
                    )
                else:
                    self._circuit_breaker_active = True
                    self._cooldown_remaining_bars = self._cb_cooldown_bars
                    self.log.warning(
                        f"CIRCUIT BREAKER TRIGGERED: {self._consecutive_losses} consecutive losses - trading paused for {self._cooldown_remaining_bars} bars"
                    )
        else:
            self._consecutive_losses = 0
            self.log.info(
                f"Position closed with profit: PnL={realized_pnl}, consecutive_losses reset to 0"
            )

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
        if self.dmi is not None:
            self.dmi.reset()
        if self.stoch is not None:
            self.stoch.reset()
        if self.atr is not None:
            self.atr.reset()
        # Reset circuit breaker state
        self._consecutive_losses = 0
        self._circuit_breaker_active = False
        self._cooldown_remaining_bars = 0
        self.log.debug("Circuit breaker state reset")
        
        # Reset pending signal state
        self._pending_signal = None
        self._pending_signal_bar_time = None
        self._pending_limit_orders.clear()
        self.log.debug("Pending signal state reset")
        
        # Reset Stochastic crossing state
        self._prev_stoch_k = None
        self._prev_stoch_d = None
        self._last_stoch_crossing_time = None
        self._last_stoch_crossing_direction = None
        self.log.debug("Stochastic crossing state reset")
