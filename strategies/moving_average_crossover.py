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
    dmi_adx_min_strength: float = 0.0  # Minimum ADX to confirm trend (0 = disabled, 20+ recommended to filter choppy markets)
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
    
    # Time-of-day multipliers (applied after regime adjustments)
    time_multiplier_enabled: bool = False
    time_tp_multiplier_eu_morning: float = 1.0  # 7-11 UTC (EU session start)
    time_tp_multiplier_us_session: float = 1.0  # 13-17 UTC (US session overlap)
    time_tp_multiplier_other: float = 1.0       # All other hours
    time_sl_multiplier_eu_morning: float = 1.0
    time_sl_multiplier_us_session: float = 1.0
    time_sl_multiplier_other: float = 1.0
    
    # Minimum hold time feature (wider initial stops)
    min_hold_time_enabled: bool = False
    min_hold_time_hours: float = 4.0            # Minimum hours before normal stop applies
    min_hold_time_stop_multiplier: float = 1.5  # Initial stop width multiplier (e.g., 1.5 = 50% wider)
    
    # Duration-based trailing stop optimization (for >12h trades)
    trailing_duration_enabled: bool = False
    trailing_duration_threshold_hours: float = 12.0    # Activate enhanced trailing after this duration
    trailing_duration_distance_pips: int = 30          # Wider trailing distance for long-duration trades
    trailing_duration_remove_tp: bool = True           # Remove TP limit to let winners run
    trailing_duration_activate_if_not_active: bool = True  # Force activation after threshold
    
    # Partial close on first trailing activation
    partial_close_enabled: bool = False
    partial_close_fraction: float = 0.5                 # Fraction of position to close on first activation (0 < f < 1)
    partial_close_move_sl_to_be: bool = True            # Move SL to breakeven (+1 pip) for remainder
    partial_close_remainder_trail_multiplier: float = 1.0  # Multiply trailing distance for remainder (e.g., 1.3 widens)
    
    # First partial close BEFORE trailing activation (fixed profit threshold)
    partial1_enabled: bool = False
    partial1_fraction: float = 0.3                      # Fraction to close at fixed profit threshold (0 < f < 1)
    partial1_threshold_pips: float = 10.0               # Profit threshold in pips to trigger first partial
    partial1_move_sl_to_be: bool = False                # Optionally move SL to BE (+1 pip) after first partial
    
    # Market structure filter (avoid trading into nearby extremes)
    structure_filter_enabled: bool = False
    structure_lookback_bars: int = 100
    structure_buffer_pips: float = 3.0
    structure_mode: str = "avoid"  # "avoid" | (placeholders for future modes)
    structure_extreme_left_bars: int = 2
    structure_extreme_right_bars: int = 2
    structure_extreme_lookback_bars: int = 200


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
        self._position_opened_time: Optional[int] = None  # Timestamp when position opened (for duration tracking)
        # Partial close state
        self._partial_close_done: bool = False
        self._partial_remainder_trail_multiplier: Decimal = Decimal("1.0")
        self._partial1_done: bool = False
        
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
        
        # PHASE 1 VERIFICATION: Log strategy initialization with fix version
        self.log.warning("=" * 80)
        self.log.warning("🔧 STRATEGY INITIALIZED WITH TRAILING STOP FIX v2.6")
        self.log.warning("   FIX: Tag-based SL lookup, active status filter, _last_stop_price init")
        self.log.warning("   CRITICAL: Clear stale order reference after modify_order()")
        self.log.warning(f"   Trailing activation: {self.cfg.trailing_stop_activation_pips} pips")
        self.log.warning(f"   Trailing distance: {self.cfg.trailing_stop_distance_pips} pips")
        self.log.warning(f"   Duration-based: {'ENABLED' if self.cfg.trailing_duration_enabled else 'DISABLED'}")
        if self.cfg.trailing_duration_enabled:
            self.log.warning(f"   Duration threshold: {self.cfg.trailing_duration_threshold_hours}h")
            self.log.warning(f"   Duration distance: {self.cfg.trailing_duration_distance_pips} pips")
        self.log.warning("=" * 80)

    def _current_position(self) -> Optional[Position]:
        """Get the current open position for this instrument."""
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        position = positions[0] if positions else None
        
        # Phase 1 diagnostic logging
        if positions:
            self.log.warning(f"[DIAGNOSTIC] _current_position found {len(positions)} positions")
        
        return position

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
    
    def _check_structure_filter(self, direction: str, bar: Bar) -> bool:
        """Avoid entries when price is too close to confirmed swing extremes."""
        if not self.cfg.structure_filter_enabled:
            return True
        if str(self.cfg.structure_mode).lower() != "avoid":
            return True  # Only 'avoid' implemented
        
        try:
            # Recent extremes settings (backward compatible defaults)
            recent_window_bars = int(self.cfg.structure_lookback_bars)
            buffer_pips = Decimal(str(self.cfg.structure_buffer_pips))
            left_bars = max(1, int(getattr(self.cfg, "structure_extreme_left_bars", 2)))
            right_bars = max(1, int(getattr(self.cfg, "structure_extreme_right_bars", 2)))
            extreme_lookback = max(left_bars + right_bars + 1, int(getattr(self.cfg, "structure_extreme_lookback_bars", 200)))
        except Exception:
            return True
        if recent_window_bars <= 0 or buffer_pips <= 0:
            return True
        
        bars_list = self.cache.bars(self.bar_type)
        if not bars_list:
            return True
        bars = list(bars_list)
        if len(bars) < 2:
            return True
        # Use completed bars only (exclude the current processing bar)
        completed = bars[:-1] if len(bars) > 1 else bars
        if not completed:
            return True
        # Limit the scan window for extremes
        window = completed[-extreme_lookback:] if len(completed) > extreme_lookback else completed
        if len(window) < (left_bars + right_bars + 1):
            return True
        
        # Find last confirmed swing high/low in the window
        last_swing_high: Optional[Decimal] = None
        last_swing_low: Optional[Decimal] = None
        
        # Candidate indices are from left_bars to len(window) - right_bars - 1
        start_idx = left_bars
        end_idx = len(window) - right_bars - 1
        if end_idx < start_idx:
            return True
        
        # Scan from newest to oldest to get the most recent confirmed swing
        for i in range(end_idx, start_idx - 1, -1):
            hi = Decimal(str(window[i].high))
            lo = Decimal(str(window[i].low))
            is_swing_high = True
            is_swing_low = True
            # Check left side
            for l in range(1, left_bars + 1):
                if Decimal(str(window[i - l].high)) >= hi:
                    is_swing_high = False
                if Decimal(str(window[i - l].low)) <= lo:
                    is_swing_low = False
                if not is_swing_high and not is_swing_low:
                    break
            # Check right side
            if is_swing_high or is_swing_low:
                for r in range(1, right_bars + 1):
                    if Decimal(str(window[i + r].high)) >= hi:
                        is_swing_high = False
                    if Decimal(str(window[i + r].low)) <= lo:
                        is_swing_low = False
                    if not is_swing_high and not is_swing_low:
                        break
            if last_swing_high is None and is_swing_high:
                last_swing_high = hi
            if last_swing_low is None and is_swing_low:
                last_swing_low = lo
            if last_swing_high is not None and last_swing_low is not None:
                break
        
        current_price = Decimal(str(bar.close))
        pip_value = self._calculate_pip_value()
        
        if direction == "BUY" and last_swing_high is not None:
            distance_to_high_pips = (last_swing_high - current_price) / pip_value
            if distance_to_high_pips <= buffer_pips:
                self._log_rejected_signal(
                    "BUY",
                    f"structure_near_swing_high (dist={distance_to_high_pips:.2f} pips <= buffer={buffer_pips}, "
                    f"left={left_bars}, right={right_bars}, window={extreme_lookback})",
                    bar,
                )
                return False
        if direction == "SELL" and last_swing_low is not None:
            distance_to_low_pips = (current_price - last_swing_low) / pip_value
            if distance_to_low_pips <= buffer_pips:
                self._log_rejected_signal(
                    "SELL",
                    f"structure_near_swing_low (dist={distance_to_low_pips:.2f} pips <= buffer={buffer_pips}, "
                    f"left={left_bars}, right={right_bars}, window={extreme_lookback})",
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
        
        # Check ADX strength if threshold is set (filters choppy/ranging markets)
        if self.cfg.dmi_adx_min_strength > 0:
            adx_value = self.dmi.adx
            if adx_value < self.cfg.dmi_adx_min_strength:
                self._log_rejected_signal(
                    direction,
                    f"dmi_adx_too_weak (ADX={adx_value:.2f} < {self.cfg.dmi_adx_min_strength:.2f}, choppy market)",
                    bar
                )
                return False
        
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
        self.log.debug(f"DMI trend confirmed for {direction}: +DI={self.dmi.plus_di:.2f}, -DI={self.dmi.minus_di:.2f}, ADX={self.dmi.adx:.2f}")
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
                    self._position_opened_time = self.clock.timestamp_ns()  # Track opening time for duration-based trailing
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

    def _get_time_profile_multipliers(self, timestamp) -> tuple[float, float]:
        """
        Get TP and SL multipliers based on time of day (UTC hour).
        
        Args:
            timestamp: Event timestamp from the bar
            
        Returns:
            (tp_mult, sl_mult): Tuple of TP and SL multipliers for current time
        """
        if not self.cfg.time_multiplier_enabled:
            return (1.0, 1.0)
        
        # Extract hour in UTC from nanosecond timestamp
        # NautilusTrader timestamps are in nanoseconds since epoch
        dt_utc = datetime.fromtimestamp(timestamp / 1_000_000_000, tz=timezone.utc)
        hour = dt_utc.hour
        
        # Define time profiles
        # EU morning: 7-11 UTC (London open, early volatility)
        # US session: 13-17 UTC (NY open, overlap with EU close)
        # Other: all other hours
        
        if 7 <= hour < 11:
            profile = "EU_MORNING"
            result = (self.cfg.time_tp_multiplier_eu_morning, self.cfg.time_sl_multiplier_eu_morning)
        elif 13 <= hour < 17:
            profile = "US_SESSION"
            result = (self.cfg.time_tp_multiplier_us_session, self.cfg.time_sl_multiplier_us_session)
        else:
            profile = "OTHER"
            result = (self.cfg.time_tp_multiplier_other, self.cfg.time_sl_multiplier_other)
        
        self.log.debug(f"[TIME_PROFILE] Hour={hour} UTC -> {profile}, multipliers=(TP={result[0]}, SL={result[1]})")
        return result

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
                    
                    # Apply time-of-day multipliers to adaptive stops
                    time_tp_mult, time_sl_mult = self._get_time_profile_multipliers(bar.ts_event)
                    if time_tp_mult != 1.0 or time_sl_mult != 1.0:
                        sl_distance = sl_distance * Decimal(str(time_sl_mult))
                        tp_distance = tp_distance * Decimal(str(time_tp_mult))
                        self.log.info(
                            f"[TIME_MULTIPLIER] Applied: TP={time_tp_mult}, SL={time_sl_mult} "
                            f"-> SL={sl_distance/pip_value:.1f} pips, TP={tp_distance/pip_value:.1f} pips"
                        )
                    
                    # Apply minimum hold time multiplier (wider initial stop) for adaptive mode
                    if self.cfg.min_hold_time_enabled:
                        current_position = self._current_position()
                        if current_position is not None:
                            time_held_ns = bar.ts_event - current_position.ts_opened
                            time_held_hours = time_held_ns / 1e9 / 3600
                            
                            if time_held_hours < self.cfg.min_hold_time_hours:
                                original_sl_pips = float(sl_distance / pip_value)
                                sl_distance = sl_distance * Decimal(str(self.cfg.min_hold_time_stop_multiplier))
                                self.log.info(
                                    f"[MIN_HOLD_TIME] Position held {time_held_hours:.2f}h < {self.cfg.min_hold_time_hours}h: "
                                    f"Widening SL from {original_sl_pips:.1f} to {float(sl_distance/pip_value):.1f} pips "
                                    f"(multiplier={self.cfg.min_hold_time_stop_multiplier})"
                                )
                    
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
            
            # Apply time-of-day multipliers (after regime adjustments)
            time_tp_mult, time_sl_mult = self._get_time_profile_multipliers(bar.ts_event)
            tp_pips = tp_pips * Decimal(str(time_tp_mult))
            sl_pips = sl_pips * Decimal(str(time_sl_mult))
            
            # Apply minimum hold time multiplier (wider initial stop)
            if self.cfg.min_hold_time_enabled:
                # Check if we have an existing position that's still within min hold time
                current_position = self._current_position()
                if current_position is not None:
                    time_held_ns = bar.ts_event - current_position.ts_opened
                    time_held_hours = time_held_ns / 1e9 / 3600
                    
                    if time_held_hours < self.cfg.min_hold_time_hours:
                        # Position still in initial period - use wider stop
                        original_sl_pips = float(sl_pips)
                        sl_pips = sl_pips * Decimal(str(self.cfg.min_hold_time_stop_multiplier))
                        self.log.info(
                            f"[MIN_HOLD_TIME] Position held {time_held_hours:.2f}h < {self.cfg.min_hold_time_hours}h: "
                            f"Widening SL from {original_sl_pips:.1f} to {float(sl_pips):.1f} pips "
                            f"(multiplier={self.cfg.min_hold_time_stop_multiplier})"
                        )
            
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
        # PHASE 1 VERIFICATION: Version marker to confirm this code is executing
        self.log.warning("[TRAILING_FIX_v2.1] ⚡ Method called")
        
        # Get current open position (NETTING ensures at most one)
        position: Optional[Position] = self._current_position()
        if position is None:
            if any([self._current_stop_order, self._trailing_active, self._last_stop_price, self._position_entry_price]):
                self.log.debug("No open position; resetting trailing stop state.")
            self._current_stop_order = None
            self._position_entry_price = None
            self._trailing_active = False
            self._last_stop_price = None
            self._position_opened_time = None
            self._partial_close_done = False
            self._partial_remainder_trail_multiplier = Decimal("1.0")
            return
        
        self.log.warning(f"[TRAILING_FIX_v2.1] 📍 Position exists: {position.id}, side={position.side}")
        
        # FIX v2.1: Query ALL orders (not just open) to find current stop
        # NautilusTrader bracket orders might have different lifecycle than expected
        all_orders = list(self.cache.orders(instrument_id=self.instrument_id))
        self.log.warning(f"[TRAILING_FIX_v2.1] 🔍 Found {len(all_orders)} total orders for position")
        
        current_stop_order = None
        sl_tag = f"{self.cfg.order_id_tag}_SL"
        active_statuses = {"PENDING_SUBMIT", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"}
        
        for order in all_orders:
            if not isinstance(order, StopMarketOrder):
                continue

            tags = getattr(order, "tags", []) or []
            has_sl_tag = any(sl_tag in str(tag) for tag in tags)
            status_name = getattr(order.status, "name", str(order.status))

            self.log.warning(
                f"[TRAILING_FIX_v2.5] 📋 StopMarketOrder: {order.client_order_id}, "
                f"status={status_name}, trigger={order.trigger_price}, tags={tags}, has_sl_tag={has_sl_tag}"
            )

            if has_sl_tag and status_name in active_statuses:
                current_stop_order = order
                self.log.warning(f"[TRAILING_FIX_v2.5] ✅ Using this stop order (status={status_name}, tags={tags})")
                break
        
        if not current_stop_order:
            self.log.warning("[TRAILING_FIX_v2.1] ⚠️ No suitable STOP_MARKET order found - trying orders_open()")
            open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
            self.log.warning(f"[TRAILING_FIX_v2.1] Found {len(open_orders)} open orders")
            for order in open_orders:
                self.log.warning(
                    f"[TRAILING_FIX_v2.1] Open order type: {type(order).__name__}, "
                    f"id={order.client_order_id}, tags={getattr(order, 'tags', None)}"
                )
                if isinstance(order, StopMarketOrder):
                    tags = getattr(order, "tags", []) or []
                    if any(sl_tag in str(tag) for tag in tags):
                        current_stop_order = order
                        self.log.warning(f"[TRAILING_FIX_v2.5] ✅ Found stop in open orders with SL tag!")
                        break
        
        if not current_stop_order:
            self.log.warning("[TRAILING_FIX_v2.1] ❌ STILL no stop order - ABORTING trailing")
            return
            
        # Update the tracked order reference
        self._current_stop_order = current_stop_order
        self.log.warning(f"[TRAILING_FIX_v2.1] 🎯 Current stop trigger: {current_stop_order.trigger_price}")
        
        # Initialize last stop price from the current SL if we don't have it yet
        if self._last_stop_price is None and current_stop_order.trigger_price is not None:
            try:
                self._last_stop_price = current_stop_order.trigger_price.as_decimal()
            except AttributeError:
                # In case trigger_price is already a Decimal-like
                self._last_stop_price = Decimal(str(current_stop_order.trigger_price))
            self.log.warning(f"[TRAILING_FIX_v2.5] 🧭 Initialized _last_stop_price from order: {self._last_stop_price}")
        
        # Skip if not FX
        self.log.warning(f"[TRAILING_FIX_v2.1] 🔍 Checking _is_fx: {self._is_fx}")
        if not self._is_fx:
            self.log.warning("[TRAILING_FIX_v2.1] ❌ EARLY EXIT: Not FX instrument")
            return
            
        # Skip if no entry price
        self.log.warning(f"[TRAILING_FIX_v2.1] 🔍 Checking _position_entry_price: {self._position_entry_price}")
        if not self._position_entry_price:
            # FIX v2.2: Get entry price from the position if we don't have it tracked
            self._position_entry_price = Decimal(str(position.avg_px_open))
            self.log.warning(f"[TRAILING_FIX_v2.2] 🔧 Retrieved entry price from position: {self._position_entry_price}")
        
        self.log.warning("[TRAILING_FIX_v2.1] ✅ PASSED ALL CHECKS - ENTERING TRAILING LOGIC!")
        
        # Keep entry price in sync but avoid thrashing on every bar
        current_entry = Decimal(str(position.avg_px_open))
        if self._position_entry_price is None or self._position_entry_price != current_entry:
            self._position_entry_price = current_entry
            self.log.debug(f"[TRAILING_FIX_v2.5] Synced _position_entry_price from position: {self._position_entry_price}")
        
        # Calculate current profit in pips
        current_price = Decimal(str(bar.close))
        pip_value = self._calculate_pip_value()
        
        if position.side.name == "LONG":
            profit_pips = (current_price - self._position_entry_price) / pip_value
        else:  # SHORT
            profit_pips = (self._position_entry_price - current_price) / pip_value
        
        # --------------------------------------------------------------------
        # FIRST PARTIAL CLOSE (before trailing activation) at fixed profit
        # --------------------------------------------------------------------
        if (
            self.cfg.partial1_enabled
            and not self._partial1_done
            and not self._trailing_active
        ):
            try:
                threshold = Decimal(str(self.cfg.partial1_threshold_pips))
            except Exception:
                threshold = Decimal("0")
            if threshold > 0 and profit_pips >= threshold:
                try:
                    frac = Decimal(str(self.cfg.partial1_fraction))
                    if frac > Decimal("0") and frac < Decimal("1"):
                        # Determine base quantity to reduce (prefer position.quantity)
                        pos_qty_attr = None
                        try:
                            pos_qty_attr = getattr(position, "quantity", None)
                        except Exception:
                            pos_qty_attr = None
                        if pos_qty_attr is None:
                            base_qty = Decimal(str(self.trade_size))
                        else:
                            base_qty = Decimal(str(pos_qty_attr))
                        qty_to_close = (base_qty * frac)
                        if qty_to_close > Decimal("0"):
                            qty_str = f"{qty_to_close.quantize(Decimal('1.00'))}"
                            opp_side = OrderSide.SELL if position.side.name == "LONG" else OrderSide.BUY
                            reduce_order = self.order_factory.market(
                                instrument_id=self.instrument_id,
                                order_side=opp_side,
                                quantity=Quantity.from_str(qty_str),
                                tags=[f"{self.cfg.order_id_tag}_PARTIAL1"],
                            )
                            self.submit_order(reduce_order)
                            self._partial1_done = True
                            self.log.info(f"[PARTIAL1] Submitted {opp_side.name} market to reduce by {qty_str} ({float(frac)*100:.0f}%) at +{profit_pips:.1f} pips (threshold={threshold})")
                            
                            # Optionally move SL to breakeven (+1 pip) for the remainder
                            if self.cfg.partial1_move_sl_to_be and self._current_stop_order is not None:
                                be_offset = pip_value  # +1 pip
                                if position.side.name == "LONG":
                                    be_price = self._position_entry_price + be_offset  # type: ignore
                                else:
                                    be_price = self._position_entry_price - be_offset  # type: ignore
                                price_increment = self.instrument.price_increment
                                new_trigger = (be_price / price_increment).quantize(Decimal('1')) * price_increment
                                
                                status_name = getattr(self._current_stop_order.status, "name", str(self._current_stop_order.status))
                                if status_name in {"PENDING_SUBMIT", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"}:
                                    old_tr = self._current_stop_order.trigger_price
                                    self.modify_order(self._current_stop_order, trigger_price=Price.from_str(str(new_trigger)))
                                    # Clear stale reference per v2.6
                                    self._current_stop_order = None
                                    self._last_stop_price = new_trigger
                                    self.log.info(f"[PARTIAL1] Moved SL to BE+1 pip: {old_tr} -> {new_trigger}")
                                else:
                                    self.log.warning(f"[PARTIAL1] Skip BE move; SL status non-active: {status_name}")
                            # Defer further trailing logic to next bar to avoid stale references
                            return
                        else:
                            self.log.warning(f"[PARTIAL1] Computed qty_to_close <= 0 from base={base_qty}, frac={frac}")
                    else:
                        self.log.warning(f"[PARTIAL1] Skipping - invalid fraction={frac} (must be 0<f<1)")
                except Exception as exc:
                    self.log.error(f"[PARTIAL1] Failed during first partial close handling: {exc}")
        
        # ====================================================================
        # DURATION-BASED TRAILING OPTIMIZATION (Phase 1)
        # ====================================================================
        # For trades >12h with 66% win rate, use optimized trailing:
        # - Wider trailing distance (30 pips vs 20 pips)
        # - Remove TP limit to let winners run
        # - Force trailing activation after threshold duration
        # ====================================================================
        duration_hours = None
        apply_duration_trailing = False
        
        if self.cfg.trailing_duration_enabled and self._position_opened_time is not None:
            # Calculate position duration in hours
            current_time_ns = self.clock.timestamp_ns()
            duration_ns = current_time_ns - self._position_opened_time
            duration_hours = duration_ns / (1_000_000_000 * 3600)  # Convert nanoseconds to hours
            
            # Check if duration threshold is met
            if duration_hours >= self.cfg.trailing_duration_threshold_hours:
                apply_duration_trailing = True
                
                # Log once when threshold is first crossed
                if not self._trailing_active or duration_hours < self.cfg.trailing_duration_threshold_hours + 0.25:  # Within 15 min of threshold
                    print(f"[DURATION_TRAIL] Position held for {duration_hours:.1f}h (>= {self.cfg.trailing_duration_threshold_hours}h threshold)")
                    print(f"[DURATION_TRAIL] Current price: {current_price}, Entry: {self._position_entry_price}, Profit: {profit_pips:.2f} pips")
                    print(f"[DURATION_TRAIL] Applying optimized trailing: distance={self.cfg.trailing_duration_distance_pips} pips")
                    print(f"[DURATION_TRAIL] Trailing active before: {self._trailing_active}")
                    self.log.info(f"[DURATION_TRAIL] Position held for {duration_hours:.1f}h (>= {self.cfg.trailing_duration_threshold_hours}h threshold)")
                    self.log.info(f"[DURATION_TRAIL] Current price: {current_price}, Entry: {self._position_entry_price}, Profit: {profit_pips:.2f} pips")
                    self.log.info(f"[DURATION_TRAIL] Applying optimized trailing: distance={self.cfg.trailing_duration_distance_pips} pips")
                
                # Remove TP order if configured to let winners run
                if self.cfg.trailing_duration_remove_tp:
                    # Find and cancel TP order
                    open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
                    print(f"[DURATION_TRAIL] Checking {len(open_orders)} open orders for TP cancellation")
                    for order in open_orders:
                        print(f"[DURATION_TRAIL]   Order: {order.client_order_id}, Type: {order.order_type}, Tags: {order.tags if hasattr(order, 'tags') else 'NO TAGS'}")
                        if hasattr(order, 'tags') and any('TP' in tag for tag in order.tags):
                            print(f"[DURATION_TRAIL] CANCELLING TP order: {order.client_order_id}")
                            self.cancel_order(order)
                            self.log.info(f"[DURATION_TRAIL] Cancelled TP order to let winner run: {order.client_order_id}")
                
                # Force trailing activation if configured
                if self.cfg.trailing_duration_activate_if_not_active and not self._trailing_active:
                    print(f"[DURATION_TRAIL] Force-activating trailing stop after {duration_hours:.1f}h (was inactive)")
                    self._trailing_active = True
                    self.log.info(f"[DURATION_TRAIL] Force-activated trailing stop after {duration_hours:.1f}h")
        
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
                    # Also keep a pips representation for diagnostics and consistency with fixed-mode logic
                    trailing_distance_pips = trailing_distance_price / pip_value
                    use_adaptive = True
                    self.log.info(
                        f"[ADAPTIVE_TRAIL_APPLIED] ATR-based activation={activation_threshold:.1f} pips, "
                        f"distance={trailing_distance_pips:.1f} pips"
                    )
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
            
            # Override with duration-based trailing if applicable (Phase 1 optimization)
            if apply_duration_trailing:
                old_distance = trailing_distance_pips
                trailing_distance_pips = Decimal(str(self.cfg.trailing_duration_distance_pips))
                print(f"[DURATION_TRAIL] Overriding trailing distance: {old_distance} -> {trailing_distance_pips} pips")
                self.log.debug(f"[DURATION_TRAIL] Using optimized trailing distance: {trailing_distance_pips} pips")
            
            # Convert pips to price distance
            trailing_distance_price = trailing_distance_pips * pip_value
        
        # Apply remainder trailing multiplier after partial close (applies to both adaptive and fixed modes)
        try:
            if self._partial_close_done and float(self.cfg.partial_close_remainder_trail_multiplier) != 1.0:
                mult = Decimal(str(self.cfg.partial_close_remainder_trail_multiplier))
                trailing_distance_price = trailing_distance_price * mult
                try:
                    # Only present in non-adaptive branch; safe to best-effort multiply
                    trailing_distance_pips = trailing_distance_pips * mult  # type: ignore
                except Exception:
                    pass
                self.log.info(f"[PARTIAL_CLOSE] Applied remainder trailing multiplier {mult}x")
        except Exception as _e:
            # Defensive: never break trailing due to multiplier issues
            self.log.warning(f"[PARTIAL_CLOSE] Remainder multiplier application failed: {_e}")
        
        # v2.3 DIAGNOSTICS: Log activation check details
        self.log.warning("=" * 70)
        self.log.warning(f"[TRAILING_FIX_v2.3] 🎯 ACTIVATION CHECK:")
        self.log.warning(f"   Profit pips: {profit_pips:.2f}")
        self.log.warning(f"   Activation threshold: {activation_threshold:.2f}")
        self.log.warning(f"   Comparison: {profit_pips:.2f} >= {activation_threshold:.2f} = {profit_pips >= activation_threshold}")
        self.log.warning(f"   Currently trailing active: {self._trailing_active}")
        self.log.warning(f"   Will activate: {profit_pips >= activation_threshold and not self._trailing_active}")
        self.log.warning("=" * 70)
        
        # Check if we should activate trailing
        if profit_pips >= activation_threshold and not self._trailing_active:
            self._trailing_active = True
            self.log.warning(f"[TRAILING_FIX_v2.3] ✅ TRAILING ACTIVATED at +{profit_pips:.1f} pips (threshold={activation_threshold:.1f})")
            print(f"[TRAILING] Activated at +{profit_pips:.1f} pips profit (threshold={activation_threshold:.1f} pips)")
            self.log.info(f"Trailing stop activated at +{profit_pips:.1f} pips profit (threshold={activation_threshold:.1f} pips)")
            
            # Perform partial close once on first activation (if enabled)
            if self.cfg.partial_close_enabled and not self._partial_close_done:
                try:
                    frac = Decimal(str(self.cfg.partial_close_fraction))
                    if frac <= Decimal("0") or frac >= Decimal("1"):
                        self.log.warning(f"[PARTIAL_CLOSE] Skipping - invalid fraction={frac} (must be 0<f<1)")
                    else:
                        # Determine base quantity to reduce (prefer position.quantity if available)
                        base_qty: Decimal
                        pos_qty_attr = None
                        try:
                            pos_qty_attr = getattr(position, "quantity", None)
                        except Exception:
                            pos_qty_attr = None
                        if pos_qty_attr is None:
                            base_qty = Decimal(str(self.trade_size))
                        else:
                            base_qty = Decimal(str(pos_qty_attr))
                        qty_to_close = (base_qty * frac)
                        # Ensure at least minimum increment by flooring to 2 decimal places (strategy uses two decimals)
                        # Avoid over-reducing which could reverse the position
                        if qty_to_close <= Decimal("0"):
                            self.log.warning(f"[PARTIAL_CLOSE] Computed qty_to_close <= 0 from base={base_qty}, frac={frac}")
                        else:
                            # Format quantity string with two decimals to match instrument size precision
                            qty_str = f"{qty_to_close.quantize(Decimal('1.00'))}"
                            opp_side = OrderSide.SELL if position.side.name == "LONG" else OrderSide.BUY
                            reduce_order = self.order_factory.market(
                                instrument_id=self.instrument_id,
                                order_side=opp_side,
                                quantity=Quantity.from_str(qty_str),
                                tags=[f"{self.cfg.order_id_tag}_PARTIAL_CLOSE"],
                            )
                            self.submit_order(reduce_order)
                            self._partial_close_done = True
                            self._partial_remainder_trail_multiplier = Decimal(str(self.cfg.partial_close_remainder_trail_multiplier))
                            self.log.info(f"[PARTIAL_CLOSE] Submitted {opp_side.name} market to reduce by {qty_str} ({float(frac)*100:.0f}%) on activation")
                            
                            # Optionally move SL to breakeven (+1 pip) for the remainder
                            if self.cfg.partial_close_move_sl_to_be and self._current_stop_order is not None:
                                be_offset = pip_value  # +1 pip
                                if position.side.name == "LONG":
                                    be_price = self._position_entry_price + be_offset  # type: ignore
                                else:
                                    be_price = self._position_entry_price - be_offset  # type: ignore
                                price_increment = self.instrument.price_increment
                                new_trigger = (be_price / price_increment).quantize(Decimal('1')) * price_increment
                                
                                status_name = getattr(self._current_stop_order.status, "name", str(self._current_stop_order.status))
                                if status_name in {"PENDING_SUBMIT", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"}:
                                    old_tr = self._current_stop_order.trigger_price
                                    self.modify_order(self._current_stop_order, trigger_price=Price.from_str(str(new_trigger)))
                                    self._current_stop_order = None  # Clear stale reference per v2.6
                                    self._last_stop_price = new_trigger
                                    self.log.info(f"[PARTIAL_CLOSE] Moved SL to BE+1 pip: {old_tr} -> {new_trigger}")
                                else:
                                    self.log.warning(f"[PARTIAL_CLOSE] Skip BE move; SL status non-active: {status_name}")
                        # After partial-close handling (and optional BE move), defer trailing adjustments to next bar
                        return
                except Exception as exc:
                    self.log.error(f"[PARTIAL_CLOSE] Failed during partial close handling: {exc}")
        
        # Update trailing stop if active
        if self._trailing_active:
            self.log.warning(f"[TRAILING_FIX_v2.3] 🔄 TRAILING IS ACTIVE - Checking if stop should move")
        else:
            self.log.warning(f"[TRAILING_FIX_v2.3] ⏸️  TRAILING NOT ACTIVE - Skipping stop modification (need {activation_threshold - profit_pips:.2f} more pips)")
            
        if self._trailing_active:
            self.log.warning(f"[TRAILING_FIX_v2.3] 🔄 Current price: {current_price}, Profit: {profit_pips:.2f} pips")
            print(f"[TRAILING] Active - Current price: {current_price}, Profit: {profit_pips:.2f} pips, Distance: {trailing_distance_pips} pips")
            
            if position.side.name == "LONG":
                new_stop = current_price - trailing_distance_price
                # For LONG: new stop must be higher (tighter) than last stop
                is_better = self._last_stop_price is None or new_stop > self._last_stop_price
                self.log.warning(f"[TRAILING_FIX_v2.3] LONG: new_stop={new_stop:.5f}, last_stop={self._last_stop_price}, is_better={is_better}")
            else:  # SHORT
                new_stop = current_price + trailing_distance_price
                # For SHORT: new stop must be lower (tighter) than last stop
                is_better = self._last_stop_price is None or new_stop < self._last_stop_price
                self.log.warning(f"[TRAILING_FIX_v2.3] SHORT: new_stop={new_stop:.5f}, last_stop={self._last_stop_price}, is_better={is_better}")
            
            if is_better:
                # Round to instrument's price increment
                price_increment = self.instrument.price_increment
                new_stop_rounded = (new_stop / price_increment).quantize(Decimal('1')) * price_increment
                
                old_stop = self._current_stop_order.trigger_price
                
                self.log.warning("=" * 70)
                self.log.warning(f"[TRAILING_FIX_v2.3] 🚀 MODIFYING ORDER!")
                self.log.warning(f"   Order ID: {self._current_stop_order.client_order_id}")
                self.log.warning(f"   Old trigger: {old_stop}")
                self.log.warning(f"   New trigger: {new_stop_rounded}")
                self.log.warning(f"   Change: {float(new_stop_rounded - old_stop.as_decimal()):.5f}")
                self.log.warning(f"   Position side: {position.side.name}")
                self.log.warning(f"   Trailing distance: {trailing_distance_pips} pips")
                self.log.warning("=" * 70)
                
                # Sanity check: ensure order is still in active status before modify
                status_name = getattr(self._current_stop_order.status, "name", str(self._current_stop_order.status))
                if status_name not in active_statuses:
                    self.log.warning(
                        f"[TRAILING_FIX_v2.5] ⏹️  Stop order status became non-active ({status_name}) "
                        "just before modify_order; skipping modification."
                    )
                    return
                
                print(f"[TRAILING] Moving stop: {old_stop} -> {new_stop_rounded} (distance={trailing_distance_pips} pips)")
                # Modify the stop order
                self.modify_order(self._current_stop_order, trigger_price=Price.from_str(str(new_stop_rounded)))
                
                self.log.warning(f"[TRAILING_FIX_v2.6] ✅ modify_order() CALLED!")
                
                # CRITICAL FIX: Clear stale order reference after modification
                # NautilusTrader creates a NEW order when modifying, so we must re-discover it next bar
                self._current_stop_order = None
                self._last_stop_price = new_stop_rounded
                self.log.info(f"Trailing stop moved from {old_stop} to {new_stop_rounded} (order reference cleared for re-discovery)")
            else:
                self.log.warning(f"[TRAILING_FIX_v2.3] ⏸️  Stop NOT better - not moving (current best: {self._last_stop_price})")

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
            
            # Check market structure 'avoid' filter (resistance proximity)
            if not self._check_structure_filter("BUY", bar):
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
            
            # Check market structure 'avoid' filter (support proximity)
            if not self._check_structure_filter("SELL", bar):
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
