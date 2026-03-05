"""
Implementation plan for Dormant Mode feature.

This feature adds adaptive timeframe switching when EMA crossings are rare.
"""

# PHASE 1: Configuration (Zero Impact)
# ====================================
# Add to MovingAverageCrossoverConfig:

dormant_mode_enabled: bool = False  # MUST default to False
dormant_threshold_hours: float = 14.0
dormant_bar_spec: str = "1-MINUTE-MID-EXTERNAL"
dormant_fast_period: int = 5
dormant_slow_period: int = 10
dormant_stop_loss_pips: int = 20
dormant_take_profit_pips: int = 30
dormant_trailing_activation_pips: int = 15
dormant_trailing_distance_pips: int = 8
dormant_dmi_enabled: bool = False
dormant_stoch_enabled: bool = False

# PHASE 2: State Tracking
# ========================
# Add to __init__:

self._dormant_mode_active: bool = False
self._last_crossover_timestamp: Optional[int] = None
self._primary_trend_direction: Optional[str] = None  # "BULLISH" or "BEARISH"
self._dormant_bar_type: Optional[BarType] = None
self._dormant_fast_sma: Optional[SimpleMovingAverage] = None
self._dormant_slow_sma: Optional[SimpleMovingAverage] = None

# PHASE 3: Initialization (Conditional)
# =====================================
# In __init__, only if enabled:

if config.dormant_mode_enabled:
    dormant_bar_spec = config.dormant_bar_spec
    if not dormant_bar_spec.upper().endswith("-EXTERNAL") and not dormant_bar_spec.upper().endswith("-INTERNAL"):
        dormant_bar_spec = f"{dormant_bar_spec}-EXTERNAL"
    self._dormant_bar_type = BarType.from_str(f"{config.instrument_id}-{dormant_bar_spec}")
    self._dormant_fast_sma = SimpleMovingAverage(period=config.dormant_fast_period)
    self._dormant_slow_sma = SimpleMovingAverage(period=config.dormant_slow_period)

# PHASE 4: Mode Detection Logic
# ==============================
# In on_bar (primary bars):

def _check_dormant_mode_activation(self, bar: Bar) -> None:
    """Check if dormant mode should activate."""
    if not self.cfg.dormant_mode_enabled:
        return
    
    # Update primary trend direction
    if self.fast_sma.initialized and self.slow_sma.initialized:
        fast = self.fast_sma.value
        slow = self.slow_sma.value
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
            self.log.info(f"Dormant mode activated: {hours_since_crossover:.1f} hours since last crossover, "
                         f"primary trend: {self._primary_trend_direction}")
    else:
        if self._dormant_mode_active:
            self._dormant_mode_active = False
            self.log.info("Dormant mode deactivated: Normal mode resumed")

# PHASE 5: Track Crossovers
# ==========================
# In on_bar, when crossover detected:

# Update last crossover timestamp
self._last_crossover_timestamp = bar.ts_event

# If in dormant mode, deactivate it
if self._dormant_mode_active:
    self._dormant_mode_active = False
    self.log.info("Dormant mode deactivated: Primary timeframe crossover detected")

# PHASE 6: Dormant Mode Signal Generation
# ======================================
# New method for dormant mode bars:

def _process_dormant_mode_bar(self, bar: Bar) -> None:
    """Process bars in dormant mode."""
    if not self._dormant_mode_active:
        return
    
    # Update indicators
    self._dormant_fast_sma.handle_bar(bar)
    self._dormant_slow_sma.handle_bar(bar)
    
    if not self._dormant_fast_sma.initialized or not self._dormant_slow_sma.initialized:
        return
    
    fast = self._dormant_fast_sma.value
    slow = self._dormant_slow_sma.value
    prev_fast = self._dormant_fast_sma.value_before(1)
    prev_slow = self._dormant_slow_sma.value_before(1)
    
    if prev_fast is None or prev_slow is None:
        return
    
    # Detect crossover
    signal_direction = None
    if prev_fast <= prev_slow and fast > slow:
        signal_direction = "BUY"
    elif prev_fast >= prev_slow and fast < slow:
        signal_direction = "SELL"
    
    if signal_direction is None:
        return
    
    # Filter by primary trend direction
    if self._primary_trend_direction == "BULLISH" and signal_direction != "BUY":
        return  # Only take BUY signals in bullish trend
    elif self._primary_trend_direction == "BEARISH" and signal_direction != "SELL":
        return  # Only take SELL signals in bearish trend
    
    # Apply filters (crossover threshold, DMI, Stochastic if enabled)
    if not self._check_crossover_threshold(signal_direction, fast, slow, bar):
        return
    
    if self.cfg.dormant_dmi_enabled and self.dmi and not self._check_dmi_trend(signal_direction, bar):
        return
    
    if self.cfg.dormant_stoch_enabled and self.stoch and not self._check_stochastic_momentum(signal_direction, bar):
        return
    
    # Time filter
    if not self._check_time_filter(signal_direction, bar):
        return
    
    # Execute trade with dormant mode risk parameters
    self._execute_trade(signal_direction, bar, dormant_mode=True)

# PHASE 7: Risk Management Override
# =================================
# Modify _calculate_sl_tp_prices:

def _calculate_sl_tp_prices(self, entry_price: Decimal, order_side: OrderSide, dormant_mode: bool = False) -> Tuple[Price, Price]:
    """Calculate stop loss and take profit prices."""
    if dormant_mode:
        # Use dormant mode parameters
        sl_pips = Decimal(str(self.cfg.dormant_stop_loss_pips))
        tp_pips = Decimal(str(self.cfg.dormant_take_profit_pips))
    else:
        # Use normal parameters
        sl_pips = Decimal(str(self.cfg.stop_loss_pips))
        tp_pips = Decimal(str(self.cfg.take_profit_pips))
    
    # ... rest of calculation logic

# PHASE 8: Bar Routing
# ====================
# In on_bar:

if (
    self.cfg.dormant_mode_enabled
    and self._dormant_bar_type is not None
    and bar.bar_type == self._dormant_bar_type
    and bar.bar_type != self.bar_type
):
    self._process_dormant_mode_bar(bar)
    return

# PHASE 9: Trailing Stop Override
# =================================
# Modify _update_trailing_stop:

def _update_trailing_stop(self, bar: Bar) -> None:
    """Update trailing stop logic."""
    # Check if position was opened in dormant mode
    # (Store this in position metadata or state)
    
    if self._position_opened_in_dormant_mode:
        activation_pips = self.cfg.dormant_trailing_activation_pips
        distance_pips = self.cfg.dormant_trailing_distance_pips
    else:
        activation_pips = self.cfg.trailing_stop_activation_pips
        distance_pips = self.cfg.trailing_stop_distance_pips
    
    # ... rest of trailing logic

# TESTING STRATEGY
# ================
# 1. Unit tests for mode activation/deactivation
# 2. Unit tests for directional filtering
# 3. Backtest with dormant_mode_enabled=False (verify no change)
# 4. Backtest with dormant_mode_enabled=True (verify behavior)
# 5. Compare results: with vs without dormant mode
# 6. Optimize dormant mode parameters separately

# ROLLOUT PLAN
# ============
# 1. Implement configuration (disabled by default)
# 2. Implement state tracking
# 3. Implement mode detection
# 4. Implement dormant signal generation
# 5. Test thoroughly
# 6. Enable in test environment
# 7. Monitor performance
# 8. Optimize parameters
# 9. Enable in production (if beneficial)

