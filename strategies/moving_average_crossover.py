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
from nautilus_trader.indicators import SimpleMovingAverage, Stochastics, RelativeStrengthIndex, AverageTrueRange
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
    trend_bar_spec: str = "1-HOUR-MID-EXTERNAL"
    trend_fast_period: int = 20
    trend_slow_period: int = 50

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

    # Entry timing improvements
    entry_timing_enabled: bool = False
    entry_timing_bar_spec: str = "2-MINUTE-MID-EXTERNAL"
    entry_timing_method: str = "pullback"  # "pullback", "breakout", "momentum"
    entry_timing_timeout_bars: int = 10

    # Market regime detection
    regime_detection_enabled: bool = False
    regime_atr_period: int = 14
    regime_volatility_threshold: float = 1.5


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

        # Higher timeframe trend filter (optional, 1-hour bars)
        self.trend_filter_enabled = config.trend_filter_enabled
        self.trend_fast_sma: Optional[SimpleMovingAverage] = None
        self.trend_slow_sma: Optional[SimpleMovingAverage] = None
        self.trend_bar_type: Optional[BarType] = None
        if config.trend_filter_enabled:
            self.trend_fast_sma = SimpleMovingAverage(period=config.trend_fast_period)
            self.trend_slow_sma = SimpleMovingAverage(period=config.trend_slow_period)
            trend_bar_spec = config.trend_bar_spec
            if not trend_bar_spec.upper().endswith("-EXTERNAL") and not trend_bar_spec.upper().endswith("-INTERNAL"):
                trend_bar_spec = f"{trend_bar_spec}-EXTERNAL"
            self.trend_bar_type = BarType.from_str(f"{config.instrument_id}-{trend_bar_spec}")

        # RSI divergence filter (optional, primary timeframe bars)
        self.rsi_enabled = config.rsi_enabled
        self.rsi: Optional[RSI] = None
        if config.rsi_enabled:
            self.rsi = RSI(period=config.rsi_period)

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

        # Subscribe to 1-hour bars for trend filter if enabled
        if self.trend_filter_enabled and self.trend_bar_type is not None:
            self.register_indicator_for_bars(self.trend_bar_type, self.trend_fast_sma)
            self.register_indicator_for_bars(self.trend_bar_type, self.trend_slow_sma)
            self.subscribe_bars(self.trend_bar_type)
            self.log.info(f"Trend filter enabled: subscribed to {self.trend_bar_type} (fast={self.cfg.trend_fast_period}, slow={self.cfg.trend_slow_period})")
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
        """Check if higher timeframe trend aligns with crossover direction.

        Args:
            direction: "BUY" or "SELL"
            bar: Current bar for logging

        Returns:
            True if trend check passes or is disabled/not ready, False if trend mismatch
        """
        # Skip check if trend filter is disabled
        if not self.trend_filter_enabled or self.trend_fast_sma is None or self.trend_slow_sma is None:
            return True

        # Get current trend EMA values
        trend_fast = self.trend_fast_sma.value
        trend_slow = self.trend_slow_sma.value

        # Skip check if trend EMAs not ready yet
        if trend_fast is None or trend_slow is None:
            self.log.debug("Trend filter EMAs not ready yet, skipping trend check")
            return True

        trend_direction = "BULLISH" if trend_fast > trend_slow else "BEARISH"

        if direction == "BUY":
            # Bullish crossover requires bullish higher timeframe trend
            if trend_direction != "BULLISH":
                self._log_rejected_signal(
                    "BUY",
                    f"trend_filter_mismatch (higher timeframe is {trend_direction}, need BULLISH for BUY signals)",
                    bar
                )
                return False
        elif direction == "SELL":
            # Bearish crossover requires bearish higher timeframe trend
            if trend_direction != "BEARISH":
                self._log_rejected_signal(
                    "SELL",
                    f"trend_filter_mismatch (higher timeframe is {trend_direction}, need BEARISH for SELL signals)",
                    bar
                )
                return False

        # Trend aligns
        self.log.debug(f"Higher timeframe trend confirmed for {direction}: fast={trend_fast:.5f}, slow={trend_slow:.5f} ({trend_direction})")
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
                        
                        # Extract stop loss order from bracket for trailing functionality
                        stop_orders = [o for o in bracket_orders.orders if "SL" in o.tags or o.order_type.name == "STOP_MARKET"]
                        if stop_orders:
                            self._current_stop_order = stop_orders[0]
                            self._trailing_active = False
                            self._last_stop_price = Decimal(str(self._current_stop_order.trigger_price))
                            self.log.debug(f"Tracking stop loss order: {self._current_stop_order.client_order_id} at {self._last_stop_price}")
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
                        
                        # Extract stop loss order from bracket for trailing functionality
                        stop_orders = [o for o in bracket_orders.orders if "SL" in o.tags or o.order_type.name == "STOP_MARKET"]
                        if stop_orders:
                            self._current_stop_order = stop_orders[0]
                            self._trailing_active = False
                            self._last_stop_price = Decimal(str(self._current_stop_order.trigger_price))
                            self.log.debug(f"Tracking stop loss order: {self._current_stop_order.client_order_id} at {self._last_stop_price}")
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
        if self.dmi is not None:
            self.dmi.reset()
        if self.stoch is not None:
            self.stoch.reset()
