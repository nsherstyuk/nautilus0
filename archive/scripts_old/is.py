warning: in the working copy of 'strategies/moving_average_crossover.py', LF will be replaced by CRLF the next time Git touches it
[1mdiff --git a/strategies/moving_average_crossover.py b/strategies/moving_average_crossover.py[m
[1mindex 58b484e89..1eb85e807 100644[m
[1m--- a/strategies/moving_average_crossover.py[m
[1m+++ b/strategies/moving_average_crossover.py[m
[36m@@ -14,7 +14,7 @@[m [mfrom nautilus_trader.config import StrategyConfig[m
 from nautilus_trader.trading.strategy import Strategy[m
 from nautilus_trader.model.identifiers import InstrumentId[m
 from nautilus_trader.model.data import Bar, BarType[m
[31m-from nautilus_trader.indicators import SimpleMovingAverage, Stochastics[m
[32m+[m[32mfrom nautilus_trader.indicators import SimpleMovingAverage, Stochastics, RelativeStrengthIndex, AverageTrueRange[m
 from nautilus_trader.model.position import Position[m
 from nautilus_trader.model.objects import Quantity, Price[m
 from nautilus_trader.model.enums import OrderSide, TriggerType[m
[36m@@ -56,6 +56,41 @@[m [mclass MovingAverageCrossoverConfig(StrategyConfig, kw_only=True):[m
     stoch_period_d: int = 3[m
     stoch_bullish_threshold: int = 30[m
     stoch_bearish_threshold: int = 70[m
[32m+[m[32m    stoch_max_bars_since_crossing: int = 18[m
[32m+[m
[32m+[m[32m    # Higher timeframe trend confirmation[m
[32m+[m[32m    trend_filter_enabled: bool = False[m
[32m+[m[32m    trend_bar_spec: str = "1-HOUR-MID-EXTERNAL"[m
[32m+[m[32m    trend_fast_period: int = 20[m
[32m+[m[32m    trend_slow_period: int = 50[m
[32m+[m
[32m+[m[32m    # RSI divergence filter[m
[32m+[m[32m    rsi_enabled: bool = False[m
[32m+[m[32m    rsi_period: int = 14[m
[32m+[m[32m    rsi_overbought: int = 70[m
[32m+[m[32m    rsi_oversold: int = 30[m
[32m+[m[32m    rsi_divergence_lookback: int = 5[m
[32m+[m
[32m+[m[32m    # Volume confirmation[m
[32m+[m[32m    volume_enabled: bool = False[m
[32m+[m[32m    volume_avg_period: int = 20[m
[32m+[m[32m    volume_min_multiplier: float = 1.2[m
[32m+[m
[32m+[m[32m    # ATR trend strength filter (using volatility as trend strength proxy)[m
[32m+[m[32m    atr_enabled: bool = False[m
[32m+[m[32m    atr_period: int = 14[m
[32m+[m[32m    atr_min_strength: float = 0.001[m
[32m+[m
[32m+[m[32m    # Entry timing improvements[m
[32m+[m[32m    entry_timing_enabled: bool = False[m
[32m+[m[32m    entry_timing_bar_spec: str = "2-MINUTE-MID-EXTERNAL"[m
[32m+[m[32m    entry_timing_method: str = "pullback"  # "pullback", "breakout", "momentum"[m
[32m+[m[32m    entry_timing_timeout_bars: int = 10[m
[32m+[m
[32m+[m[32m    # Market regime detection[m
[32m+[m[32m    regime_detection_enabled: bool = False[m
[32m+[m[32m    regime_atr_period: int = 14[m
[32m+[m[32m    regime_volatility_threshold: float = 1.5[m
 [m
 [m
 class MovingAverageCrossover(Strategy):[m
[36m@@ -95,10 +130,46 @@[m [mclass MovingAverageCrossover(Strategy):[m
             if not dmi_bar_spec.upper().endswith("-EXTERNAL") and not dmi_bar_spec.upper().endswith("-INTERNAL"):[m
                 dmi_bar_spec = f"{dmi_bar_spec}-EXTERNAL"[m
             self.dmi_bar_type = BarType.from_str(f"{config.instrument_id}-{dmi_bar_spec}")[m
[31m-        [m
[32m+[m
[32m+[m[32m        # Higher timeframe trend filter (optional, 1-hour bars)[m
[32m+[m[32m        self.trend_filter_enabled = config.trend_filter_enabled[m
[32m+[m[32m        self.trend_fast_sma: Optional[SimpleMovingAverage] = None[m
[32m+[m[32m        self.trend_slow_sma: Optional[SimpleMovingAverage] = None[m
[32m+[m[32m        self.trend_bar_type: Optional[BarType] = None[m
[32m+[m[32m        if config.trend_filter_enabled:[m
[32m+[m[32m            self.trend_fast_sma = SimpleMovingAverage(period=config.trend_fast_period)[m
[32m+[m[32m            self.trend_slow_sma = SimpleMovingAverage(period=config.trend_slow_period)[m
[32m+[m[32m            trend_bar_spec = config.trend_bar_spec[m
[32m+[m[32m            if not trend_bar_spec.upper().endswith("-EXTERNAL") and not trend_bar_spec.upper().endswith("-INTERNAL"):[m
[32m+[m[32m                trend_bar_spec = f"{trend_bar_spec}-EXTERNAL"[m
[32m+[m[32m            self.trend_bar_type = BarType.from_str(f"{config.instrument_id}-{trend_bar_spec}")[m
[32m+[m
[32m+[m[32m        # RSI divergence filter (optional, primary timeframe bars)[m
[32m+[m[32m        self.rsi_enabled = config.rsi_enabled[m
[32m+[m[32m        self.rsi: Optional[RSI] = None[m
[32m+[m[32m        if config.rsi_enabled:[m
[32m+[m[32m            self.rsi = RSI(period=config.rsi_period)[m
[32m+[m
[32m+[m[32m        # Volume confirmation filter (optional, primary timeframe bars)[m
[32m+[m[32m        self.volume_enabled = config.volume_enabled[m
[32m+[m[32m        self.volume_sma: Optional[SimpleMovingAverage] = None[m
[32m+[m[32m        if config.volume_enabled:[m
[32m+[m[32m            self.volume_sma = SimpleMovingAverage(period=config.volume_avg_period)[m
[32m+[m
[32m+[m[32m        # ATR trend strength filter (optional, primary timeframe bars)[m
[32m+[m[32m        self.atr_enabled = config.atr_enabled[m
[32m+[m[32m        self.atr: Optional[AverageTrueRange] = None[m
[32m+[m[32m        if config.atr_enabled:[m
[32m+[m[32m            self.atr = AverageTrueRange(period=config.atr_period)[m
[32m+[m
         # Stochastic indicator for momentum confirmation (optional, 15-minute bars)[m
         self.stoch: Optional[Stochastics] = None[m
         self.stoch_bar_type: Optional[BarType] = None[m
[32m+[m[32m        # Track stochastic crossing state for max_bars_since_crossing feature[m
[32m+[m[32m        self._stoch_bullish_cross_bar_count: Optional[int] = None  # Bars since %K crossed above %D[m
[32m+[m[32m        self._stoch_bearish_cross_bar_count: Optional[int] = None  # Bars since %K crossed below %D[m
[32m+[m[32m        self._stoch_prev_k: Optional[float] = None[m
[32m+[m[32m        self._stoch_prev_d: Optional[float] = None[m
         if config.stoch_enabled:[m
             self.stoch = Stochastics(period_k=config.stoch_period_k, period_d=config.stoch_period_d)[m
             # Construct 15-minute bar type with same instrument[m
[36m@@ -134,6 +205,14 @@[m [mclass MovingAverageCrossover(Strategy):[m
         self.register_indicator_for_bars(self.bar_type, self.fast_sma)[m
         self.register_indicator_for_bars(self.bar_type, self.slow_sma)[m
 [m
[32m+[m[32m        # Register primary timeframe indicators[m
[32m+[m[32m        if self.rsi is not None:[m
[32m+[m[32m            self.register_indicator_for_bars(self.bar_type, self.rsi)[m
[32m+[m[32m        if self.volume_sma is not None:[m
[32m+[m[32m            self.register_indicator_for_bars(self.bar_type, self.volume_sma)[m
[32m+[m[32m        if self.atr is not None:[m
[32m+[m[32m            self.register_indicator_for_bars(self.bar_type, self.atr)[m
[32m+[m
         # Subscribe to bars; backtest engine streams bars from catalog[m
         self.subscribe_bars(self.bar_type)[m
         self.log.info(f"Strategy initialized for {self.instrument_id} @ {self.bar_type}")[m
[36m@@ -143,6 +222,16 @@[m [mclass MovingAverageCrossover(Strategy):[m
         self.log.debug([m
             f"Position limits enforced={self._enforce_position_limit}, allow_reversal={self._allow_reversal}"[m
         )[m
[32m+[m
[32m+[m[32m        # Subscribe to 1-hour bars for trend filter if enabled[m
[32m+[m[32m        if self.trend_filter_enabled and self.trend_bar_type is not None:[m
[32m+[m[32m            self.register_indicator_for_bars(self.trend_bar_type, self.trend_fast_sma)[m
[32m+[m[32m            self.register_indicator_for_bars(self.trend_bar_type, self.trend_slow_sma)[m
[32m+[m[32m            self.subscribe_bars(self.trend_bar_type)[m
[32m+[m[32m            self.log.info(f"Trend filter enabled: subscribed to {self.trend_bar_type} (fast={self.cfg.trend_fast_period}, slow={self.cfg.trend_slow_period})")[m
[32m+[m[32m        else:[m
[32m+[m[32m            self.log.info("Trend filter disabled")[m
[32m+[m
         # Subscribe to 2-minute bars for DMI if enabled[m
         if self.dmi is not None and self.dmi_bar_type is not None:[m
             self.register_indicator_for_bars(self.dmi_bar_type, self.dmi)[m
[36m@@ -150,12 +239,12 @@[m [mclass MovingAverageCrossover(Strategy):[m
             self.log.info(f"DMI filter enabled: subscribed to {self.dmi_bar_type} (period={self.cfg.dmi_period})")[m
         else:[m
             self.log.info("DMI filter disabled")[m
[31m-        [m
[32m+[m
         # Subscribe to 15-minute bars for Stochastic if enabled[m
         if self.stoch is not None and self.stoch_bar_type is not None:[m
             self.register_indicator_for_bars(self.stoch_bar_type, self.stoch)[m
             self.subscribe_bars(self.stoch_bar_type)[m
[31m-            self.log.info(f"Stochastic filter enabled: subscribed to {self.stoch_bar_type} (period_k={self.cfg.stoch_period_k}, period_d={self.cfg.stoch_period_d}, bullish_threshold={self.cfg.stoch_bullish_threshold}, bearish_threshold={self.cfg.stoch_bearish_threshold})")[m
[32m+[m[32m            self.log.info(f"Stochastic filter enabled: subscribed to {self.stoch_bar_type} (period_k={self.cfg.stoch_period_k}, period_d={self.cfg.stoch_period_d}, bullish_threshold={self.cfg.stoch_bullish_threshold}, bearish_threshold={self.cfg.stoch_bearish_threshold}, max_bars_since_crossing={self.cfg.stoch_max_bars_since_crossing})")[m
         else:[m
             self.log.info("Stochastic filter disabled")[m
 [m
[36m@@ -165,6 +254,12 @@[m [mclass MovingAverageCrossover(Strategy):[m
         return positions[0] if positions else None[m
 [m
     def _check_can_open_position(self, signal_type: str) -> Tuple[bool, str]:[m
[32m+[m[32m        """[m
[32m+[m[32m        Check if a new position can be opened.[m
[32m+[m[41m        [m
[32m+[m[32m        Returns False if any position is already open, regardless of direction.[m
[32m+[m[32m        Positions should only be closed by TP/SL orders, not by opposite signals.[m
[32m+[m[32m        """[m
         if not self._enforce_position_limit:[m
             return True, ""[m
 [m
[36m@@ -174,20 +269,11 @@[m [mclass MovingAverageCrossover(Strategy):[m
         if position is None:[m
             return True, ""[m
 [m
[31m-        current = position[m
[31m-        if self._allow_reversal:[m
[31m-            if signal_type == "BUY" and getattr(current, "is_short", False):[m
[31m-                return True, "reversal_allowed"[m
[31m-            if signal_type == "SELL" and getattr(current, "is_long", False):[m
[31m-                return True, "reversal_allowed"[m
[31m-[m
[31m-        if signal_type == "BUY" and getattr(current, "is_short", False):[m
[31m-            return True, "close_only"[m
[31m-        if signal_type == "SELL" and getattr(current, "is_long", False):[m
[31m-            return True, "close_only"[m
[31m-[m
[31m-        side = getattr(current, "side", "unknown")[m
[31m-        return False, f"Position already open: {side}"[m
[32m+[m[32m        # If any position is open, reject all signals[m
[32m+[m[32m        # Position will be closed only by TP/SL orders, not by opposite signals[m
[32m+[m[32m        side = getattr(position, "side", "unknown")[m
[32m+[m[32m        side_str = side.name if hasattr(side, "name") else str(side)[m
[32m+[m[32m        return False, f"Position already open ({side_str}) - signals ignored until TP/SL closes position"[m
 [m
     def _record_signal_event(self, signal_type: str, action: str, reason: str, bar: Bar) -> None:[m
         record = {[m
[36m@@ -232,6 +318,128 @@[m [mclass MovingAverageCrossover(Strategy):[m
             return False[m
         return True[m
 [m
[32m+[m[32m    def _check_trend_filter(self, direction: str, bar: Bar) -> bool:[m
[32m+[m[32m        """Check if higher timeframe trend aligns with crossover direction.[m
[32m+[m
[32m+[m[32m        Args:[m
[32m+[m[32m            direction: "BUY" or "SELL"[m
[32m+[m[32m            bar: Current bar for logging[m
[32m+[m
[32m+[m[32m        Returns:[m
[32m+[m[32m            True if trend check passes or is disabled/not ready, False if trend mismatch[m
[32m+[m[32m        """[m
[32m+[m[32m        # Skip check if trend filter is disabled[m
[32m+[m[32m        if not self.trend_filter_enabled or self.trend_fast_sma is None or self.trend_slow_sma is None:[m
[32m+[m[32m            return True[m
[32m+[m
[32m+[m[32m        # Get current trend EMA values[m
[32m+[m[32m        trend_fast = self.trend_fast_sma.value[m
[32m+[m[32m        trend_slow = self.trend_slow_sma.value[m
[32m+[m
[32m+[m[32m        # Skip check if trend EMAs not ready yet[m
[32m+[m[32m        if trend_fast is None or trend_slow is None:[m
[32m+[m[32m            self.log.debug("Trend filter EMAs not ready yet, skipping trend check")[m
[32m+[m[32m            return True[m
[32m+[m
[32m+[m[32m        trend_direction = "BULLISH" if trend_fast > trend_slow else "BEARISH"[m
[32m+[m
[32m+[m[32m        if direction == "BUY":[m
[32m+[m[32m            # Bullish crossover requires bullish higher timeframe trend[m
[32m+[m[32m            if trend_direction != "BULLISH":[m
[32m+[m[32m                self._log_rejected_signal([m
[32m+[m[32m                    "BUY",[m
[32m+[m[32m                    f"trend_filter_mismatch (higher timeframe is {trend_direction}, need BULLISH for BUY signals)",[m
[32m+[m[32m                    bar[m
[32m+[m[32m                )[m
[32m+[m[32m                return False[m
[32m+[m[32m        elif direction == "SELL":[m
[32m+[m[32m            # Bearish crossover requires bearish higher timeframe trend[m
[32m+[m[32m            if trend_direction != "BEARISH":[m
[32m+[m[32m                self._log_rejected_signal([m
[32m+[m[32m                    "SELL",[m
[32m+[m[32m                    f"trend_filter_mismatch (higher timeframe is {trend_direction}, need BEARISH for SELL signals)",[m
[32m+[m[32m                    bar[m
[32m+[m[32m                )[m
[32m+[m[32m                return False[m
[32m+[m
[32m+[m[32m        # Trend aligns[m
[32m+[m[32m        self.log.debug(f"Higher timeframe trend confirmed for {direction}: fast={trend_fast:.5f}, slow={trend_slow:.5f} ({trend_direction})")[m
[32m+[m[32m        return True[m
[32m+[m
[32m+[m[32m    def _check_rsi_filter(self, direction: str, bar: Bar) -> bool:[m
[32m+[m[32m        """Check RSI conditions for signal confirmation."""[m
[32m+[m[32m        if not self.rsi_enabled or self.rsi is None:[m
[32m+[m[32m            return True[m
[32m+[m
[32m+[m[32m        rsi_value = self.rsi.value[m
[32m+[m[32m        if rsi_value is None:[m
[32m+[m[32m            self.log.debug("RSI not ready yet, skipping RSI check")[m
[32m+[m[32m            return True[m
[32m+[m
[32m+[m[32m        if direction == "BUY":[m
[32m+[m[32m            # For BUY signals, avoid overbought conditions[m
[32m+[m[32m            if rsi_value > self.cfg.rsi_overbought:[m
[32m+[m[32m                self._log_rejected_signal([m
[32m+[m[32m                    "BUY",[m
[32m+[m[32m                    f"rsi_overbought (RSI={rsi_value:.2f} > {self.cfg.rsi_overbought})",[m
[32m+[m[32m                    bar[m
[32m+[m[32m                )[m
[32m+[m[32m                return False[m
[32m+[m[32m        elif direction == "SELL":[m
[32m+[m[32m            # For SELL signals, avoid oversold conditions[m
[32m+[m[32m            if rsi_value < self.cfg.rsi_oversold:[m
[32m+[m[32m                self._log_rejected_signal([m
[32m+[m[32m                    "SELL",[m
[32m+[m[32m                    f"rsi_oversold (RSI={rsi_value:.2f} < {self.cfg.rsi_oversold})",[m
[32m+[m[32m                    bar[m
[32m+[m[32m                )[m
[32m+[m[32m                return False[m
[32m+[m
[32m+[m[32m        self.log.debug(f"RSI confirmed for {direction}: RSI={rsi_value:.2f}")[m
[32m+[m[32m        return True[m
[32m+[m
[32m+[m[32m  