"""
Moving Average Crossover strategy for NautilusTrader.

This strategy uses two Simple Moving Averages (SMA) to generate
buy/sell signals on crossovers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple, cast
from dataclasses import field
import re

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.indicators import SimpleMovingAverage, ExponentialMovingAverage, Stochastics, RelativeStrengthIndex, AverageTrueRange
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
    # Adaptive stops configuration
    adaptive_stop_mode: str = "atr"  # 'fixed' | 'atr' | 'percentile'
    adaptive_atr_period: int = 14
    tp_atr_mult: float = 2.5
    sl_atr_mult: float = 1.5
    trail_activation_atr_mult: float = 1.0
    trail_distance_atr_mult: float = 0.8
    volatility_window: int = 200
    volatility_sensitivity: float = 0.6
    min_stop_distance_pips: float = 5.0
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
    stoch_max_bars_since_crossing: int = 18

    # Higher timeframe trend confirmation
    trend_filter_enabled: bool = False
    trend_bar_spec: str = "1-MINUTE-MID-EXTERNAL"
    trend_ema_period: int = 150
    trend_ema_threshold_pips: float = 0.0  # Minimum distance in pips above/below EMA (default: 0.0 = no threshold)

    # RSI divergence filter
    rsi_enabled: bool = False
    rsi_period: int = 14
    rsi_overbought: int = 70
    rsi_oversold: int = 30
    rsi_divergence_lookback: int = 5

    # Volume confirmation
    volume_enabled: bool = False
    volume_avg_period: int = 20
    volume_min_multiplier: float = 1.2

    # ATR trend strength filter (using volatility as trend strength proxy)
    atr_enabled: bool = False
    atr_period: int = 14
    atr_min_strength: float = 0.001

    # Time filter
    time_filter_enabled: bool = False
    excluded_hours: list[int] = field(default_factory=list)  # List of hours (0-23) to exclude from trading
    excluded_hours_mode: str = "flat"  # "flat" | "weekday" - whether to use same exclusion for all days or weekday-specific
    excluded_hours_by_weekday: dict[str, list[int]] = field(default_factory=dict)  # Weekday-specific exclusions

    # Entry timing improvements
    entry_timing_enabled: bool = False
    entry_timing_bar_spec: str = "2-MINUTE-MID-EXTERNAL"
    entry_timing_method: str = "pullback"  # "pullback", "breakout", "momentum"
    entry_timing_timeout_bars: int = 10

    # Market regime detection
    regime_detection_enabled: bool = False
    regime_adx_trending_threshold: float = 25.0  # ADX > 25 = trending
    regime_adx_ranging_threshold: float = 20.0   # ADX < 20 = ranging
    # TP multipliers (applied to base TP)
    regime_tp_multiplier_trending: float = 1.5   # 50 pips -> 75 pips
    regime_tp_multiplier_ranging: float = 0.8    # 50 pips -> 40 pips
    # SL multipliers (optional - currently kept same)
    regime_sl_multiplier_trending: float = 1.0   # Keep SL same
    regime_sl_multiplier_ranging: float = 1.0    # Keep SL same
    # Trailing stop multipliers
    regime_trailing_activation_multiplier_trending: float = 0.75  # 20 -> 15 pips
    regime_trailing_activation_multiplier_ranging: float = 1.25   # 20 -> 25 pips
    regime_trailing_distance_multiplier_trending: float = 0.67    # 15 -> 10 pips
    regime_trailing_distance_multiplier_ranging: float = 1.33     # 15 -> 20 pips


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
            self.dmi = DMI(period=config.dmi_period)
            # Construct 2-minute bar type with same instrument
            dmi_bar_spec = config.dmi_bar_spec
            if not dmi_bar_spec.upper().endswith("-EXTERNAL") and not dmi_bar_spec.upper().endswith("-INTERNAL"):
                dmi_bar_spec = f"{dmi_bar_spec}-EXTERNAL"
            self.dmi_bar_type = BarType.from_str(f"{config.instrument_id}-{dmi_bar_spec}")

        # Higher timeframe trend filter (optional, default 1-minute bars)
        self.trend_filter_enabled = config.trend_filter_enabled
        self.trend_ema: Optional[ExponentialMovingAverage] = None
        self.trend_bar_type: Optional[BarType] = None
        if config.trend_filter_enabled:
            self.trend_ema = ExponentialMovingAverage(period=config.trend_ema_period)
            trend_bar_spec = config.trend_bar_spec
            if not trend_bar_spec.upper().endswith("-EXTERNAL") and not trend_bar_spec.upper().endswith("-INTERNAL"):
                trend_bar_spec = f"{trend_bar_spec}-EXTERNAL"
            self.trend_bar_type = BarType.from_str(f"{config.instrument_id}-{trend_bar_spec}")

        # RSI divergence filter (optional, primary timeframe bars)
        self.rsi_enabled = config.rsi_enabled
        self.rsi: Optional[RelativeStrengthIndex] = None
        if config.rsi_enabled:
            self.rsi = RelativeStrengthIndex(period=config.rsi_period)

        # Volume confirmation filter (optional, primary timeframe bars)
        self.volume_enabled = config.volume_enabled
        self.volume_sma: Optional[SimpleMovingAverage] = None
        if config.volume_enabled:
            self.volume_sma = SimpleMovingAverage(period=config.volume_avg_period)

        # ATR trend strength filter (optional, primary timeframe bars)
        self.atr_enabled = config.atr_enabled
        self.atr: Optional[AverageTrueRange] = None
        if config.atr_enabled:
            self.atr = AverageTrueRange(period=config.atr_period)

        # Time filter (optional)
        self.time_filter_enabled = config.time_filter_enabled
        self.excluded_hours: set[int] = set(config.excluded_hours) if config.excluded_hours else set()
        self.excluded_hours_mode = config.excluded_hours_mode
        self.excluded_hours_by_weekday = config.excluded_hours_by_weekday

        # Stochastic indicator for momentum confirmation (optional, 15-minute bars)
        self.stoch: Optional[Stochastics] = None
        self.stoch_bar_type: Optional[BarType] = None
        # Track stochastic crossing state for max_bars_since_crossing feature
        self._stoch_bullish_cross_bar_count: Optional[int] = None  # Bars since %K crossed above %D
        self._stoch_bearish_cross_bar_count: Optional[int] = None  # Bars since %K crossed below %D
        self._stoch_prev_k: Optional[float] = None
        self._stoch_prev_d: Optional[float] = None
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
        self._last_regime: Optional[str] = None  # Track regime changes for logging
        
        # Entry timing state (for pullback/breakout/momentum entry)
        self.entry_timing_enabled = config.entry_timing_enabled
        self.entry_timing_bar_type: Optional[BarType] = None
        self._pending_signal: Optional[Dict[str, Any]] = None  # {'direction': 'BUY'/'SELL', 'bar_count': 0, 'signal_price': 1.0850}
        if config.entry_timing_enabled:
            entry_bar_spec = config.entry_timing_bar_spec
            if not entry_bar_spec.upper().endswith("-EXTERNAL") and not entry_bar_spec.upper().endswith("-INTERNAL"):
                entry_bar_spec = f"{entry_bar_spec}-EXTERNAL"
            self.entry_timing_bar_type = BarType.from_str(f"{config.instrument_id}-{entry_bar_spec}")

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

        # Register primary timeframe indicators
        if self.rsi is not None:
            self.register_indicator_for_bars(self.bar_type, self.rsi)
        if self.volume_sma is not None:
            self.register_indicator_for_bars(self.bar_type, self.volume_sma)
        if self.atr is not None:
            self.register_indicator_for_bars(self.bar_type, self.atr)

        # Subscribe to bars; backtest engine streams bars from catalog
        self.subscribe_bars(self.bar_type)
        self.log.info(f"Strategy initialized for {self.instrument_id} @ {self.bar_type}")
        self.log.debug(
            f"Indicator configuration: fast_period={self.cfg.fast_period}, slow_period={self.cfg.slow_period}"
        )
        self.log.debug(
            f"Position limits enforced={self._enforce_position_limit}, allow_reversal={self._allow_reversal}"
        )

        # Subscribe to trend bars for trend filter if enabled
        if self.trend_filter_enabled and self.trend_bar_type is not None:
            self.register_indicator_for_bars(self.trend_bar_type, self.trend_ema)
            self.subscribe_bars(self.trend_bar_type)
            self.log.info(f"Trend filter enabled: subscribed to {self.trend_bar_type} (EMA period={self.cfg.trend_ema_period})")
        else:
            self.log.info("Trend filter disabled")

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
        
        # Subscribe to entry timing bars if enabled
        if self.entry_timing_enabled and self.entry_timing_bar_type is not None:
            self.subscribe_bars(self.entry_timing_bar_type)
            self.log.info(f"Entry timing enabled: subscribed to {self.entry_timing_bar_type} (method={self.cfg.entry_timing_method}, timeout={self.cfg.entry_timing_timeout_bars} bars)")

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

    def _check_trend_filter(self, direction: str, bar: Bar) -> bool:
        """Check if bar closing price is above/below trend EMA by threshold amount.

        Args:
            direction: "BUY" or "SELL"
            bar: Current bar for logging (primary bar for signal generation)

        Returns:
            True if trend check passes or is disabled/not ready, False if trend mismatch
        """
        # Skip check if trend filter is disabled
        if not self.trend_filter_enabled or self.trend_ema is None:
            return True

        # Get current trend EMA value (updated from trend bars)
        trend_ema_value = self.trend_ema.value

        # Skip check if trend EMA not ready yet
        if trend_ema_value is None:
            self.log.debug("Trend filter EMA not ready yet, skipping trend check")
            return True

        # Get bar closing price (from primary bar)
        bar_close = Decimal(str(bar.close))
        ema_value = Decimal(str(trend_ema_value))

        # Calculate pip value for threshold check
        pip_value = self._calculate_pip_value()
        threshold_pips = Decimal(str(self.cfg.trend_ema_threshold_pips))
        threshold_decimal = threshold_pips * pip_value

        if direction == "BUY":
            # BUY requires closing price above EMA by at least threshold
            price_diff = bar_close - ema_value
            if price_diff <= threshold_decimal:
                diff_pips = price_diff / pip_value
                self._log_rejected_signal(
                    "BUY",
                    f"trend_filter_price_below_ema_threshold (close={bar_close}, EMA={ema_value}, diff={diff_pips:.2f} pips < {threshold_pips} pips threshold)",
                    bar
                )
                return False
        elif direction == "SELL":
            # SELL requires closing price below EMA by at least threshold
            price_diff = ema_value - bar_close
            if price_diff <= threshold_decimal:
                diff_pips = price_diff / pip_value
                self._log_rejected_signal(
                    "SELL",
                    f"trend_filter_price_above_ema_threshold (close={bar_close}, EMA={ema_value}, diff={diff_pips:.2f} pips < {threshold_pips} pips threshold)",
                    bar
                )
                return False

        diff_pips = abs(bar_close - ema_value) / pip_value
        self.log.debug(f"Trend filter confirmed {direction} signal: close={bar_close}, EMA={ema_value}, diff={diff_pips:.2f} pips")
        return True

    def _check_rsi_filter(self, direction: str, bar: Bar) -> bool:
        """Check RSI conditions for signal confirmation."""
        if not self.rsi_enabled or self.rsi is None:
            return True

        rsi_value = self.rsi.value
        if rsi_value is None:
            self.log.debug("RSI not ready yet, skipping RSI check")
            return True

        if direction == "BUY":
            # For BUY signals, avoid overbought conditions
            if rsi_value > self.cfg.rsi_overbought:
                self._log_rejected_signal(
                    "BUY",
                    f"rsi_overbought (RSI={rsi_value:.2f} > {self.cfg.rsi_overbought})",
                    bar
                )
                return False
        elif direction == "SELL":
            # For SELL signals, avoid oversold conditions
            if rsi_value < self.cfg.rsi_oversold:
                self._log_rejected_signal(
                    "SELL",
                    f"rsi_oversold (RSI={rsi_value:.2f} < {self.cfg.rsi_oversold})",
                    bar
                )
                return False

        self.log.debug(f"RSI confirmed for {direction}: RSI={rsi_value:.2f}")
        return True

    def _check_volume_filter(self, direction: str, bar: Bar) -> bool:
        """Check volume confirmation for signal."""
        if not self.volume_enabled or self.volume_sma is None or bar.volume is None:
            return True

        avg_volume = self.volume_sma.value
        if avg_volume is None:
            self.log.debug("Volume SMA not ready yet, skipping volume check")
            return True

        if bar.volume < (avg_volume * self.cfg.volume_min_multiplier):
            self._log_rejected_signal(
                direction,
                f"volume_too_low (volume={bar.volume} < {avg_volume * self.cfg.volume_min_multiplier:.0f} required)",
                bar
            )
            return False

        self.log.debug(f"Volume confirmed for {direction}: volume={bar.volume}, avg={avg_volume:.0f}")
        return True

    def _check_atr_filter(self, direction: str, bar: Bar) -> bool:
        """Check ATR trend strength for signal confirmation."""
        if not self.atr_enabled or self.atr is None:
            return True

        atr_value = self.atr.value
        if atr_value is None:
            self.log.debug("ATR not ready yet, skipping ATR check")
            return True

        if atr_value < self.cfg.atr_min_strength:
            self._log_rejected_signal(
                direction,
                f"atr_weak_trend (ATR={atr_value:.5f} < {self.cfg.atr_min_strength} minimum)",
                bar
            )
            return False

        self.log.debug(f"ATR trend strength confirmed for {direction}: ATR={atr_value:.5f}")
        return True

    def _check_time_filter(self, bar: Bar) -> bool:
        """Check if current bar time is within allowed trading hours."""
        if not self.time_filter_enabled:
            return True

        # Get hour from bar timestamp (UTC)
        # bar.ts_event represents the bar close time (end of bar period)
        # For aggregated bars, ts_event might be the last minute bar's timestamp,
        # so we need to calculate the actual bar close time based on bar type
        bar_time = datetime.fromtimestamp(bar.ts_event / 1e9, tz=timezone.utc)
        
        # For aggregated bars, calculate the actual bar close time
        # Parse bar type to get aggregation period (e.g., "15-MINUTE" -> 15 minutes)
        bar_spec = bar.bar_type.spec.value if hasattr(bar.bar_type.spec, 'value') else str(bar.bar_type.spec)
        bar_close_time = bar_time
        
        if 'MINUTE' in bar_spec.upper():
            try:
                # Extract minutes from bar spec (e.g., "15-MINUTE-MID-EXTERNAL" -> 15)
                # Handle different formats: "15-MINUTE", "15M", etc.
                bar_spec_upper = bar_spec.upper()
                if '-MINUTE' in bar_spec_upper:
                    minutes_str = bar_spec.split('-')[0]
                elif 'M' in bar_spec_upper and not 'MINUTE' in bar_spec_upper:
                    # Handle "15M" format
                    minutes_str = bar_spec_upper.split('M')[0]
                else:
                    # Try to extract number from beginning
                    match = re.match(r'(\d+)', bar_spec)
                    if match:
                        minutes_str = match.group(1)
                    else:
                        raise ValueError(f"Cannot parse bar minutes from: {bar_spec}")
                
                bar_minutes = int(minutes_str)
                
                # For aggregated bars, ts_event might be the last 1-minute bar's timestamp
                # (e.g., 13:59:00 for a bar covering 13:45-14:00)
                # We need to round up to the bar boundary (14:00:00)
                current_minute = bar_time.minute
                current_second = bar_time.second
                
                # Calculate the bar close time: round up to next bar boundary
                # For a 15-minute bar, boundaries are at :00, :15, :30, :45
                if current_minute % bar_minutes != 0 or current_second > 0:
                    # Not aligned - round up to next boundary
                    next_boundary_minute = ((current_minute // bar_minutes) + 1) * bar_minutes
                    if next_boundary_minute >= 60:
                        bar_close_time = bar_time.replace(hour=bar_time.hour + 1, minute=0, second=0, microsecond=0)
                    else:
                        bar_close_time = bar_time.replace(minute=next_boundary_minute, second=0, microsecond=0)
                else:
                    # Already aligned at bar boundary - ts_event is correct
                    bar_close_time = bar_time.replace(second=0, microsecond=0)
                    
                # Log for debugging if we're adjusting the time
                if bar_close_time.hour != bar_time.hour:
                    self.log.debug(
                        f"Time filter adjusted bar time: ts_event={bar_time.isoformat()} "
                        f"-> bar_close={bar_close_time.isoformat()} (bar_minutes={bar_minutes})"
                    )
            except (ValueError, IndexError, AttributeError) as e:
                # If parsing fails, use ts_event as-is but log warning
                self.log.warning(f"Failed to parse bar spec '{bar_spec}' for time filter: {e}, using ts_event as-is")
                bar_close_time = bar_time
        
        current_hour = bar_close_time.hour
        
        # Determine which excluded hours to use based on mode
        if self.excluded_hours_mode == "weekday":
            # Get weekday name (Monday, Tuesday, etc.)
            weekday_name = bar_close_time.strftime("%A")
            excluded_hours_for_check = set(self.excluded_hours_by_weekday.get(weekday_name, []))
            
            # If no specific exclusion for this weekday, fall back to flat exclusion
            if not excluded_hours_for_check:
                excluded_hours_for_check = self.excluded_hours
        else:
            # Use flat exclusion for all days
            excluded_hours_for_check = self.excluded_hours
        
        # Skip check if no hours are excluded
        if not excluded_hours_for_check:
            return True

        if current_hour in excluded_hours_for_check:
            self._log_rejected_signal(
                "BUY",  # Direction doesn't matter for time filter
                f"time_filter_excluded_hour (hour={current_hour:02d}:00 UTC is excluded, bar_close={bar_close_time.isoformat()}, ts_event={bar_time.isoformat()})",
                bar
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
        self.log.debug(
            f"Stoch check: dir={direction} K={k_value:.2f} D={d_value:.2f} "
            f"bull_count={self._stoch_bullish_cross_bar_count} "
            f"bear_count={self._stoch_bearish_cross_bar_count} "
            f"max_bars={self.cfg.stoch_max_bars_since_crossing}"
        )
        
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
            
            # Check max_bars_since_crossing AFTER confirming %K > %D
            if self.cfg.stoch_max_bars_since_crossing > 0:
                # For BUY signals, require recent bullish crossing (%K crossed above %D)
                # If no crossing detected yet, allow the signal (crossing tracking may not have started)
                if self._stoch_bullish_cross_bar_count is not None:
                    self.log.debug(f"BUY signal: checking crossing age - bullish_cross_bar_count={self._stoch_bullish_cross_bar_count}, max={self.cfg.stoch_max_bars_since_crossing}")
                    if self._stoch_bullish_cross_bar_count > self.cfg.stoch_max_bars_since_crossing:
                        self._log_rejected_signal(
                            direction,
                            f"stochastic_crossing_too_old (bullish crossing was {self._stoch_bullish_cross_bar_count} bars ago, max={self.cfg.stoch_max_bars_since_crossing})",
                            bar
                        )
                        return False
                    else:
                        self.log.debug(
                            f"BUY signal: crossing age OK ({self._stoch_bullish_cross_bar_count} <= {self.cfg.stoch_max_bars_since_crossing})"
                        )
                else:
                    self.log.debug(f"BUY signal: no bullish crossing tracked yet, allowing signal")
            else:
                self.log.debug("BUY signal: max_bars_since_crossing disabled (0)")
            
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
            
            # Check max_bars_since_crossing AFTER confirming %K < %D
            if self.cfg.stoch_max_bars_since_crossing > 0:
                # For SELL signals, require recent bearish crossing (%K crossed below %D)
                # If no crossing detected yet, allow the signal (crossing tracking may not have started)
                if self._stoch_bearish_cross_bar_count is not None:
                    self.log.debug(f"SELL signal: checking crossing age - bearish_cross_bar_count={self._stoch_bearish_cross_bar_count}, max={self.cfg.stoch_max_bars_since_crossing}")
                    if self._stoch_bearish_cross_bar_count > self.cfg.stoch_max_bars_since_crossing:
                        self._log_rejected_signal(
                            direction,
                            f"stochastic_crossing_too_old (bearish crossing was {self._stoch_bearish_cross_bar_count} bars ago, max={self.cfg.stoch_max_bars_since_crossing})",
                            bar
                        )
                        return False
                    else:
                        self.log.debug(
                            f"SELL signal: crossing age OK ({self._stoch_bearish_cross_bar_count} <= {self.cfg.stoch_max_bars_since_crossing})"
                        )
                else:
                    self.log.debug(f"SELL signal: no bearish crossing tracked yet, allowing signal")
            else:
                self.log.debug("SELL signal: max_bars_since_crossing disabled (0)")
            
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

    def _execute_entry(self, direction: str, entry_bar: Bar) -> None:
        """
        Execute entry order for BUY or SELL direction.
        Extracted to common method for use by both immediate and delayed entries.
        """
        # Safety check: ensure no position exists
        position: Optional[Position] = self._current_position()
        if position is not None:
            self.log.warning(f"Unexpected position found during {direction} entry: {position}. Skipping entry.")
            return
        
        if not self._is_fx:
            # For non-FX instruments, create market order without SL/TP
            order_side = OrderSide.BUY if direction == "BUY" else OrderSide.SELL
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=order_side,
                quantity=Quantity.from_str(f"{int(self.trade_size)}.00"),
                tags=[self.cfg.order_id_tag],
            )
            self.submit_order(order)
            self.log.info(f"{direction} order submitted (no SL/TP for non-FX instrument)")
            return
        
        # FX instrument - create bracket order with SL/TP
        entry_price = Decimal(str(entry_bar.close))
        order_side = OrderSide.BUY if direction == "BUY" else OrderSide.SELL
        sl_price, tp_price = self._calculate_sl_tp_prices(entry_price, order_side, entry_bar)
        
        # Log SL/TP calculations
        self.log.info(
            f"{direction} order - Entry: {entry_price}, SL: {sl_price}, TP: {tp_price}"
        )
        
        # Create bracket order with entry + SL + TP
        try:
            bracket_orders = self.order_factory.bracket(
                instrument_id=self.instrument_id,
                order_side=order_side,
                quantity=Quantity.from_str(f"{int(self.trade_size)}.00"),
                sl_trigger_price=sl_price,
                sl_trigger_type=TriggerType.DEFAULT,
                tp_price=tp_price,
                entry_tags=[self.cfg.order_id_tag],
                sl_tags=[f"{self.cfg.order_id_tag}_SL"],
                tp_tags=[f"{self.cfg.order_id_tag}_TP"],
            )
            
            # Submit all orders in the bracket
            self.submit_order_list(bracket_orders)
            
            # Track the stop order for trailing stops
            for order in bracket_orders.orders:
                if isinstance(order, StopMarketOrder):
                    self._current_stop_order = order
                    self._position_entry_price = entry_price
                    break
            
            self.log.info(f"{direction} bracket order submitted successfully")
            
        except Exception as exc:
            self.log.error(f"Failed to create {direction} bracket order: {exc}")
    
    def _calculate_pip_value(self) -> Decimal:
        """Calculate pip value based on instrument precision."""
        if self.instrument.price_precision == 5:
            return Decimal('0.0001')  # 1 pip for 5 decimal places (EUR/USD)
        elif self.instrument.price_precision == 3:
            return Decimal('0.01')     # 1 pip for 3 decimal places (USD/JPY)
        else:
            # For non-FX or other precisions, use the instrument's minimum tick/price increment
            return Decimal(str(self.instrument.price_increment))
    
    def _check_pullback_entry(self, bar: Bar, direction: str) -> bool:
        """
        Check if current 2-min bar meets pullback entry criteria.
        
        Pullback logic:
        - For BUY: Wait for price to pull back near fast EMA, then bounce up
        - For SELL: Wait for price to rally near fast EMA, then reject down
        
        Returns True if entry condition is met.
        """
        if not self._pending_signal:
            return False
        
        current_price = Decimal(str(bar.close))
        pip_value = self._calculate_pip_value()
        pullback_buffer = Decimal('3') * pip_value  # 3 pips buffer
        
        # Get current fast EMA value (from primary timeframe)
        fast_ema = self.fast_sma.value
        if fast_ema is None:
            return False
        
        fast_ema_decimal = Decimal(str(fast_ema))
        
        if direction == "BUY":
            # Looking for pullback to near fast EMA, then bounce
            # Entry when price is within 3 pips above fast EMA and showing strength
            target_level = fast_ema_decimal + pullback_buffer
            
            if current_price <= target_level and current_price >= fast_ema_decimal:
                # Check if bar closed higher than it opened (bullish candle)
                bar_open = Decimal(str(bar.open))
                if current_price > bar_open:
                    self.log.info(f"[ENTRY_TIMING] BUY pullback confirmed: price={current_price}, fast_EMA={fast_ema_decimal}, bounce detected")
                    return True
        
        elif direction == "SELL":
            # Looking for rally to near fast EMA, then rejection
            # Entry when price is within 3 pips below fast EMA and showing weakness
            target_level = fast_ema_decimal - pullback_buffer
            
            if current_price >= target_level and current_price <= fast_ema_decimal:
                # Check if bar closed lower than it opened (bearish candle)
                bar_open = Decimal(str(bar.open))
                if current_price < bar_open:
                    self.log.info(f"[ENTRY_TIMING] SELL pullback confirmed: price={current_price}, fast_EMA={fast_ema_decimal}, rejection detected")
                    return True
        
        return False

    def _detect_market_regime(self, bar: Bar) -> str:
        """
        Detect current market regime using ADX from DMI indicator.
        
        Returns:
            'trending': Strong trend (ADX > threshold_strong)
            'ranging': Weak/no trend (ADX < threshold_weak)
            'moderate': Moderate trend (between thresholds)
            'moderate': Default if DMI not initialized or regime detection disabled
        """
        if not self.cfg.regime_detection_enabled:
            return 'moderate'  # Default if disabled
        
        if not self.dmi or not self.dmi.initialized:
            return 'moderate'  # Default if DMI not ready
        
        # Get ADX value
        adx_value = self.dmi.adx
        
        # Get thresholds from config
        threshold_strong = self.cfg.regime_adx_trending_threshold
        threshold_weak = self.cfg.regime_adx_ranging_threshold
        
        # Determine regime
        if adx_value > threshold_strong:
            regime = 'trending'
        elif adx_value < threshold_weak:
            regime = 'ranging'
        else:
            regime = 'moderate'
        
        # Log regime changes
        if regime != self._last_regime:
            self.log.info(
                f"Market regime: {regime} (ADX={adx_value:.2f}, "
                f"thresholds: strong>{threshold_strong}, weak<{threshold_weak})"
            )
            self._last_regime = regime
        
        return regime

    def _calculate_sl_tp_prices(self, entry_price: Decimal, order_side: OrderSide, bar: Bar) -> Tuple[Price, Price]:
        """
        Calculate stop loss and take profit prices based on entry price and order side.
        Uses adaptive stops (ATR-based) if enabled, otherwise falls back to fixed pips.
        Also adjusts TP/SL based on detected market regime if regime detection is enabled.
        """
        from strategies.adaptive_stops import compute_adaptive_levels, get_bars_dataframe
        
        pip_value = self._calculate_pip_value()
        
        # Determine if we should use adaptive stops
        use_adaptive = self.cfg.adaptive_stop_mode in ('atr', 'percentile')
        
        self.log.info(f"[ADAPTIVE_DEBUG] Mode: {self.cfg.adaptive_stop_mode}, use_adaptive: {use_adaptive}")
        
        if use_adaptive:
            # Try to compute adaptive levels
            # Get historical bars for ATR calculation
            bars_list = self.cache.bars(self.bar_type)
            self.log.info(f"[ADAPTIVE_DEBUG] Retrieved {len(list(bars_list)) if bars_list else 0} bars from cache")
            bars_df = get_bars_dataframe(list(bars_list) if bars_list else [], 
                                         lookback=max(300, self.cfg.volatility_window + 50))
            
            if bars_df is not None and len(bars_df) >= self.cfg.adaptive_atr_period + 1:
                # Prepare config for adaptive calculation
                adaptive_cfg = {
                    'mode': self.cfg.adaptive_stop_mode,
                    'atr_period': self.cfg.adaptive_atr_period,
                    'tp_atr_mult': self.cfg.tp_atr_mult,
                    'sl_atr_mult': self.cfg.sl_atr_mult,
                    'trail_activation_atr_mult': self.cfg.trail_activation_atr_mult,
                    'trail_distance_atr_mult': self.cfg.trail_distance_atr_mult,
                    'volatility_window': self.cfg.volatility_window,
                    'volatility_sensitivity': self.cfg.volatility_sensitivity,
                    'min_distance_pips': self.cfg.min_stop_distance_pips
                }
                
                # Compute adaptive levels
                self.log.info(f"[ADAPTIVE_DEBUG] Calling compute_adaptive_levels with mode={adaptive_cfg['mode']}")
                levels = compute_adaptive_levels(bars_df, entry_price, adaptive_cfg, fallback_pips=None)
                self.log.info(f"[ADAPTIVE_DEBUG] Returned mode={levels['mode']}, sl_distance={levels['sl_distance']}, atr={levels.get('atr')}")
                
                if levels['mode'] != 'fixed' and levels['sl_distance'] is not None:
                    # Successfully computed adaptive levels
                    sl_distance = levels['sl_distance']
                    tp_distance = levels['tp_distance']
                    
                    # Log adaptive calculation details
                    if levels.get('atr'):
                        atr_pips = levels['atr'] / pip_value
                        self.log.info(
                            f"[ADAPTIVE_APPLIED] ATR={atr_pips:.2f} pips, mode={levels['mode']}, "
                            f"SL={sl_distance/pip_value:.1f} pips, TP={tp_distance/pip_value:.1f} pips"
                        )
                        if levels.get('volatility_percentile'):
                            self.log.debug(
                                f"Volatility: percentile={levels['volatility_percentile']:.1f}%, "
                                f"scale={levels['volatility_scale']:.2f}"
                            )
                else:
                    # Adaptive calculation failed, use fixed fallback
                    use_adaptive = False
                    self.log.warning(f"[ADAPTIVE_FALLBACK] Calculation returned fixed mode, using fallback")
            else:
                # Not enough bars for ATR, use fixed fallback
                use_adaptive = False
                self.log.warning(f"[ADAPTIVE_FALLBACK] Insufficient bars (have {len(bars_df) if bars_df is not None else 0}, need {self.cfg.adaptive_atr_period}+)")
        
        # Fallback to fixed pip-based calculation
        if not use_adaptive:
            self.log.info(f"[ADAPTIVE_FALLBACK] Using fixed pips: SL={self.cfg.stop_loss_pips}, TP={self.cfg.take_profit_pips}")
            # Get base TP/SL from config
            base_sl_pips = Decimal(str(self.cfg.stop_loss_pips))
            base_tp_pips = Decimal(str(self.cfg.take_profit_pips))
            
            # Apply regime-based adjustments if enabled
            if self.cfg.regime_detection_enabled:
                regime = self._detect_market_regime(bar)
                
                if regime == 'trending':
                    # Trending: Wider TP to let trends run
                    tp_pips = base_tp_pips * Decimal(str(self.cfg.regime_tp_multiplier_trending))
                    sl_pips = base_sl_pips * Decimal(str(self.cfg.regime_sl_multiplier_trending))
                elif regime == 'ranging':
                    # Ranging: Tighter TP to take profits quickly
                    tp_pips = base_tp_pips * Decimal(str(self.cfg.regime_tp_multiplier_ranging))
                    sl_pips = base_sl_pips * Decimal(str(self.cfg.regime_sl_multiplier_ranging))
                else:
                    # Moderate: Use base values (no adjustment)
                    tp_pips = base_tp_pips
                    sl_pips = base_sl_pips
            else:
                # No regime detection: use base values
                tp_pips = base_tp_pips
                sl_pips = base_sl_pips
            
            # Convert pips to price distances
            sl_distance = sl_pips * pip_value
            tp_distance = tp_pips * pip_value
        
        # Calculate actual SL/TP prices based on order side
        if order_side == OrderSide.BUY:
            # For BUY orders: SL below entry, TP above entry
            sl_price = entry_price - sl_distance
            tp_price = entry_price + tp_distance
        else:
            # For SELL orders: SL above entry, TP below entry
            sl_price = entry_price + sl_distance
            tp_price = entry_price - tp_distance
        
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
        
        # Determine trailing parameters (adaptive or fixed)
        use_adaptive = self.cfg.adaptive_stop_mode in ('atr', 'percentile')
        self.log.info(f"[ADAPTIVE_TRAIL] Mode: {self.cfg.adaptive_stop_mode}, use_adaptive: {use_adaptive}")
        
        if use_adaptive:
            # Try to get adaptive trailing levels
            from strategies.adaptive_stops import compute_adaptive_levels, get_bars_dataframe
            
            bars_list = self.cache.bars(self.bar_type)
            bars_df = get_bars_dataframe(list(bars_list) if bars_list else [], 
                                         lookback=max(300, self.cfg.volatility_window + 50))
            
            self.log.info(f"[ADAPTIVE_TRAIL] Retrieved {len(bars_df) if bars_df is not None else 0} bars from cache")
            
            if bars_df is not None and len(bars_df) >= self.cfg.adaptive_atr_period + 1:
                adaptive_cfg = {
                    'mode': self.cfg.adaptive_stop_mode,
                    'atr_period': self.cfg.adaptive_atr_period,
                    'tp_atr_mult': self.cfg.tp_atr_mult,
                    'sl_atr_mult': self.cfg.sl_atr_mult,
                    'trail_activation_atr_mult': self.cfg.trail_activation_atr_mult,
                    'trail_distance_atr_mult': self.cfg.trail_distance_atr_mult,
                    'volatility_window': self.cfg.volatility_window,
                    'volatility_sensitivity': self.cfg.volatility_sensitivity,
                    'min_distance_pips': self.cfg.min_stop_distance_pips
                }
                
                self.log.info(f"[ADAPTIVE_TRAIL] Calling compute_adaptive_levels with mode={adaptive_cfg['mode']}")
                levels = compute_adaptive_levels(bars_df, current_price, adaptive_cfg, fallback_pips=None)
                self.log.info(f"[ADAPTIVE_TRAIL] Returned mode={levels['mode']}, trail_activation={levels.get('trail_activation')}, trail_distance={levels.get('trail_distance')}")
                
                if levels['mode'] != 'fixed' and levels['trail_activation'] is not None:
                    # Use adaptive trailing distances (in price units, convert to pips for threshold)
                    activation_threshold = levels['trail_activation'] / pip_value
                    trailing_distance_price = levels['trail_distance']
                    use_adaptive = True
                    self.log.info(f"[ADAPTIVE_TRAIL_APPLIED] ATR-based activation={activation_threshold:.1f} pips, distance={trailing_distance_price/pip_value:.1f} pips")
                else:
                    use_adaptive = False
                    self.log.warning(f"[ADAPTIVE_TRAIL_FALLBACK] Calculation returned fixed mode")
            else:
                use_adaptive = False
                self.log.warning(f"[ADAPTIVE_TRAIL_FALLBACK] Insufficient bars (have {len(bars_df) if bars_df is not None else 0}, need {self.cfg.adaptive_atr_period}+)")
        
        # Fallback to fixed/regime-based trailing parameters
        if not use_adaptive:
            # Get regime-adjusted trailing parameters if enabled
            if self.cfg.regime_detection_enabled:
                regime = self._detect_market_regime(bar)
                
                if regime == 'trending':
                    # Trending: Lower activation (activate sooner), tighter distance
                    activation_threshold = Decimal(str(self.cfg.trailing_stop_activation_pips)) * Decimal(str(self.cfg.regime_trailing_activation_multiplier_trending))
                    trailing_distance_pips = Decimal(str(self.cfg.trailing_stop_distance_pips)) * Decimal(str(self.cfg.regime_trailing_distance_multiplier_trending))
                elif regime == 'ranging':
                    # Ranging: Higher activation (wait for confirmation), wider distance
                    activation_threshold = Decimal(str(self.cfg.trailing_stop_activation_pips)) * Decimal(str(self.cfg.regime_trailing_activation_multiplier_ranging))
                    trailing_distance_pips = Decimal(str(self.cfg.trailing_stop_distance_pips)) * Decimal(str(self.cfg.regime_trailing_distance_multiplier_ranging))
                else:
                    # Moderate: Use base values
                    activation_threshold = Decimal(str(self.cfg.trailing_stop_activation_pips))
                    trailing_distance_pips = Decimal(str(self.cfg.trailing_stop_distance_pips))
            else:
                # No regime detection: use base values
                activation_threshold = Decimal(str(self.cfg.trailing_stop_activation_pips))
                trailing_distance_pips = Decimal(str(self.cfg.trailing_stop_distance_pips))
            
            # Convert pips to price distance
            trailing_distance_price = trailing_distance_pips * pip_value
        
        # Check if we should activate trailing
        if profit_pips >= activation_threshold and not self._trailing_active:
            self._trailing_active = True
            self.log.info(f"Trailing stop activated at +{profit_pips:.1f} pips profit (threshold={activation_threshold:.1f} pips)")
        
        # Update trailing stop if active
        if self._trailing_active:
            
            if position.side.name == "LONG":
                new_stop = current_price - trailing_distance_price
                # For LONG: new stop must be higher (tighter) than last stop
                is_better = self._last_stop_price is None or new_stop > self._last_stop_price
            else:  # SHORT
                new_stop = current_price + trailing_distance_price
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
        
        # Debug: Log all bar types received (first few only)
        if self._bar_count < 5:
            self.log.debug(f"Bar #{self._bar_count}: type={bar.bar_type}, stoch_bar_type={self.stoch_bar_type}, match={bar.bar_type == self.stoch_bar_type if self.stoch_bar_type else False}")
        
        # Route DMI bars only if they are not the primary bar type
        if (
            self.dmi_bar_type is not None
            and bar.bar_type == self.dmi_bar_type
            and bar.bar_type != self.bar_type
        ):
            self.log.debug(f"Received DMI bar: close={bar.close}")
            return

        # Route trend bars - update EMA but don't generate signals
        if (
            self.trend_bar_type is not None
            and bar.bar_type == self.trend_bar_type
            and bar.bar_type != self.bar_type
        ):
            self.log.debug(f"Received trend bar: close={bar.close}, EMA={self.trend_ema.value if self.trend_ema else None}")
            return  # Trend EMA updates automatically via registration, no signal generation
        
        # Process entry timing bars (2-min bars for pullback detection)
        if (
            self.entry_timing_bar_type is not None
            and bar.bar_type == self.entry_timing_bar_type
        ):
            # Check if we have a pending signal waiting for entry
            if self._pending_signal is not None:
                direction = self._pending_signal['direction']
                self._pending_signal['bar_count'] += 1
                
                # Check for timeout
                if self._pending_signal['bar_count'] > self.cfg.entry_timing_timeout_bars:
                    self.log.info(f"[ENTRY_TIMING] {direction} signal timed out after {self._pending_signal['bar_count']} bars, cancelling")
                    self._pending_signal = None
                    if bar.bar_type != self.bar_type:
                        return
                else:
                    # Check if pullback entry condition is met
                    if self._check_pullback_entry(bar, direction):
                        # Execute the trade immediately
                        signal_bar = self._pending_signal['signal_bar']
                        self.log.info(f"[ENTRY_TIMING] Pullback entry triggered for {direction}, executing trade")
                        
                        # Call the entry execution with the original signal bar
                        self._execute_entry(direction, bar)
                        
                        # Clear pending signal
                        self._pending_signal = None
                    
                    # If entry timing bars are not the same as primary bars, return
                    if bar.bar_type != self.bar_type:
                        return
            elif bar.bar_type != self.bar_type:
                # No pending signal and not primary bar, just return
                return
        
        # Process stochastic crossing detection for all stochastic bars
        if (
            self.stoch_bar_type is not None
            and bar.bar_type == self.stoch_bar_type
        ):
            self.log.info(f"Received Stochastic bar: close={bar.close}, stoch exists={self.stoch is not None}, initialized={self.stoch.initialized if self.stoch else False}")
            # Track stochastic crossings for max_bars_since_crossing feature
            if self.stoch is not None:
                if not self.stoch.initialized:
                    self.log.debug(f"Stochastic indicator not yet initialized (needs {self.cfg.stoch_period_k} bars)")
                else:
                    k_value = self.stoch.value_k
                    d_value = self.stoch.value_d
                    
                    # Initialize previous values on first stochastic bar after initialization
                    if self._stoch_prev_k is None or self._stoch_prev_d is None:
                        self._stoch_prev_k = k_value
                        self._stoch_prev_d = d_value
                        self.log.debug(f"Stochastic values initialized: %K={k_value:.2f}, %D={d_value:.2f}")
                        # Initialize crossing counts based on initial state
                        if k_value > d_value:
                            # %K is already above %D - initialize bullish crossing count to 0
                            self._stoch_bullish_cross_bar_count = 0
                            self.log.info(f"Stochastic initial state: %K={k_value:.2f} > %D={d_value:.2f} (bullish), initializing bullish crossing count")
                        elif k_value < d_value:
                            # %K is already below %D - initialize bearish crossing count to 0
                            self._stoch_bearish_cross_bar_count = 0
                            self.log.info(f"Stochastic initial state: %K={k_value:.2f} < %D={d_value:.2f} (bearish), initializing bearish crossing count")
                        return  # Skip crossing detection on first bar
                    
                    # Track if a crossing happened on this bar (to avoid incrementing count on crossing bar)
                    bullish_cross_this_bar = False
                    bearish_cross_this_bar = False
                    
                    # Check for bullish crossing (%K crosses above %D)
                    if self._stoch_prev_k <= self._stoch_prev_d and k_value > d_value:
                        self._stoch_bullish_cross_bar_count = 0
                        bullish_cross_this_bar = True
                        self.log.info(f"Stochastic bullish crossing detected: %K={k_value:.2f} crossed above %D={d_value:.2f}")
                    
                    # Check for bearish crossing (%K crosses below %D)
                    if self._stoch_prev_k >= self._stoch_prev_d and k_value < d_value:
                        self._stoch_bearish_cross_bar_count = 0
                        bearish_cross_this_bar = True
                        self.log.info(f"Stochastic bearish crossing detected: %K={k_value:.2f} crossed below %D={d_value:.2f}")
                    
                    # Reset counts when crossing back (if %K crosses below %D, reset bullish count; if above %D, reset bearish count)
                    if self._stoch_prev_k > self._stoch_prev_d and k_value <= d_value:
                        # %K was above %D, now crossed below - reset bullish count
                        self._stoch_bullish_cross_bar_count = None
                        self.log.debug(f"Stochastic bullish state ended: %K={k_value:.2f} <= %D={d_value:.2f}, resetting bullish crossing count")
                    elif self._stoch_prev_k < self._stoch_prev_d and k_value >= d_value:
                        # %K was below %D, now crossed above - reset bearish count
                        self._stoch_bearish_cross_bar_count = None
                        self.log.debug(f"Stochastic bearish state ended: %K={k_value:.2f} >= %D={d_value:.2f}, resetting bearish crossing count")
                    
                    # Increment bar counts if crossings have occurred and we're still in the same state
                    # Only increment if a crossing did NOT happen on this bar (to keep count at 0 on crossing bar)
                    if self._stoch_bullish_cross_bar_count is not None and k_value > d_value and not bullish_cross_this_bar:
                        self._stoch_bullish_cross_bar_count += 1
                        self.log.debug(f"Stochastic bullish crossing age incremented: {self._stoch_bullish_cross_bar_count} bars")
                    if self._stoch_bearish_cross_bar_count is not None and k_value < d_value and not bearish_cross_this_bar:
                        self._stoch_bearish_cross_bar_count += 1
                        self.log.debug(f"Stochastic bearish crossing age incremented: {self._stoch_bearish_cross_bar_count} bars")
                    
                    # Update previous values
                    self._stoch_prev_k = k_value
                    self._stoch_prev_d = d_value
            
            # If stochastic timeframe is different from primary timeframe, return early
            # Otherwise, continue to process primary signals on this bar as well
            if bar.bar_type != self.bar_type:
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

            # Check higher timeframe trend alignment
            if not self._check_trend_filter("BUY", bar):
                return

            # Check RSI conditions
            if not self._check_rsi_filter("BUY", bar):
                return

            # Check volume confirmation
            if not self._check_volume_filter("BUY", bar):
                return

            # Check ATR trend strength
            if not self._check_atr_filter("BUY", bar):
                return

            # Check time filter (excluded hours)
            if not self._check_time_filter(bar):
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
                return  # Reject signal - position already open, will only close via TP/SL
            else:
                # Check if entry timing is enabled
                if self.entry_timing_enabled and self.cfg.entry_timing_method == "pullback":
                    # Set up pending signal - wait for pullback entry on 2-min bars
                    self._pending_signal = {
                        'direction': 'BUY',
                        'bar_count': 0,
                        'signal_price': Decimal(str(bar.close)),
                        'signal_bar': bar
                    }
                    self.log.info(f"[ENTRY_TIMING] BUY signal detected at {bar.close}, waiting for pullback entry (timeout: {self.cfg.entry_timing_timeout_bars} bars)")
                    return  # Don't enter immediately, wait for timing signal
                
                # No entry timing or immediate entry - use common entry method
                self._execute_entry("BUY", bar)
        elif bearish:
            self.log.info(
                f"Bearish crossover detected (prev_fast={self._prev_fast}, prev_slow={self._prev_slow}, current_fast={fast}, current_slow={slow})"
            )
            
            # Check crossover magnitude against threshold
            if not self._check_crossover_threshold("SELL", fast, slow, bar):
                # Do NOT update prev_* here; just return
                return

            # Check higher timeframe trend alignment
            if not self._check_trend_filter("SELL", bar):
                return

            # Check RSI conditions
            if not self._check_rsi_filter("SELL", bar):
                return

            # Check volume confirmation
            if not self._check_volume_filter("SELL", bar):
                return

            # Check ATR trend strength
            if not self._check_atr_filter("SELL", bar):
                return

            # Check time filter (excluded hours)
            if not self._check_time_filter(bar):
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
                return  # Reject signal - position already open, will only close via TP/SL
            else:
                # Check if entry timing is enabled
                if self.entry_timing_enabled and self.cfg.entry_timing_method == "pullback":
                    # Set up pending signal - wait for pullback entry on 2-min bars
                    self._pending_signal = {
                        'direction': 'SELL',
                        'bar_count': 0,
                        'signal_price': Decimal(str(bar.close)),
                        'signal_bar': bar
                    }
                    self.log.info(f"[ENTRY_TIMING] SELL signal detected at {bar.close}, waiting for pullback entry (timeout: {self.cfg.entry_timing_timeout_bars} bars)")
                    return  # Don't enter immediately, wait for timing signal
                
                # No entry timing or immediate entry - use common entry method
                self._execute_entry("SELL", bar)

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
        self._last_regime = None
        if self.dmi is not None:
            self.dmi.reset()
        if self.stoch is not None:
            self.stoch.reset()
