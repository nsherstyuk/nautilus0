# How to Implement Market Regime Detection

## Quick Summary

**Market regime detection** identifies whether the market is **trending** (strong directional movement) or **ranging** (sideways/choppy). You can then adjust TP/SL and trailing stops accordingly.

---

## Method 1: ADX-Based Detection (RECOMMENDED)

### Step 1: Add ADX Calculation to DMI Indicator

The DMI indicator currently calculates +DI and -DI but not ADX. Add ADX calculation:

**File: `indicators/dmi.py`**

Add after line 137 (after `_calculate_di_values` method):

```python
    def _calculate_di_values(self) -> None:
        # ... existing code ...
        
        # Calculate ADX
        di_sum = self._plus_di + self._minus_di
        if di_sum > 0:
            self._adx = 100.0 * abs(self._plus_di - self._minus_di) / di_sum
        else:
            self._adx = 0.0
```

Add property after line 189:

```python
    @property
    def adx(self) -> float:
        """Average Directional Index (ADX) - measures trend strength."""
        return self._adx if hasattr(self, '_adx') else 0.0
```

Initialize `_adx` in `__init__`:

```python
        # Outputs
        self._plus_di: float = 0.0
        self._minus_di: float = 0.0
        self._adx: float = 0.0  # ADD THIS LINE
```

### Step 2: Add Regime Detection to Strategy

**File: `strategies/moving_average_crossover.py`**

Add to `MovingAverageCrossoverConfig` (around line 96-99):

```python
    # Market regime detection
    regime_detection_enabled: bool = False
    regime_adx_trending_threshold: float = 25.0  # ADX > 25 = trending
    regime_adx_ranging_threshold: float = 20.0     # ADX < 20 = ranging
    regime_tp_multiplier_trending: float = 1.5    # TP multiplier for trending (50 -> 75 pips)
    regime_tp_multiplier_ranging: float = 0.8     # TP multiplier for ranging (50 -> 40 pips)
    regime_trailing_activation_multiplier_trending: float = 0.75  # 20 -> 15 pips
    regime_trailing_activation_multiplier_ranging: float = 1.25   # 20 -> 25 pips
    regime_trailing_distance_multiplier_trending: float = 0.67   # 15 -> 10 pips
    regime_trailing_distance_multiplier_ranging: float = 1.33    # 15 -> 20 pips
```

Add method to `MovingAverageCrossover` class:

```python
    def _detect_market_regime(self, bar: Bar) -> str:
        """
        Detect current market regime using ADX from DMI indicator.
        
        Returns:
            'trending': Strong trend (ADX > threshold_strong)
            'ranging': Weak/no trend (ADX < threshold_weak)
            'moderate': Moderate trend (between thresholds)
            'unknown': DMI not initialized
        """
        if not self.cfg.regime_detection_enabled:
            return 'moderate'  # Default if disabled
        
        if not self.dmi or not self.dmi.initialized:
            return 'moderate'  # Default if DMI not ready
        
        # Get ADX value (after adding ADX to DMI indicator)
        adx_value = self.dmi.adx
        
        # Get thresholds from config
        threshold_strong = self.cfg.regime_adx_trending_threshold
        threshold_weak = self.cfg.regime_adx_ranging_threshold
        
        # Log regime changes for debugging
        if not hasattr(self, '_last_regime'):
            self._last_regime = None
        
        if adx_value > threshold_strong:
            regime = 'trending'
        elif adx_value < threshold_weak:
            regime = 'ranging'
        else:
            regime = 'moderate'
        
        # Log regime changes
        if regime != self._last_regime:
            self.log.info(
                f"Market regime changed: {self._last_regime} -> {regime} "
                f"(ADX={adx_value:.2f}, thresholds: strong>{threshold_strong}, weak<{threshold_weak})"
            )
            self._last_regime = regime
        
        return regime
```

### Step 3: Adjust TP/SL Based on Regime

Modify `_calculate_sl_tp_prices` method (find it around line 900-950):

```python
    def _calculate_sl_tp_prices(self, entry_price: Decimal, side: OrderSide, bar: Bar) -> Tuple[Decimal, Decimal]:
        """Calculate SL/TP prices, adjusted for market regime."""
        # Base TP/SL from config
        base_tp_pips = Decimal(str(self.cfg.take_profit_pips))
        base_sl_pips = Decimal(str(self.cfg.stop_loss_pips))
        
        # Get regime-adjusted values
        regime = self._detect_market_regime(bar)
        
        if regime == 'trending':
            # Trending: Wider TP to let trends run
            tp_pips = base_tp_pips * Decimal(str(self.cfg.regime_tp_multiplier_trending))
            sl_pips = base_sl_pips  # Keep SL same
        elif regime == 'ranging':
            # Ranging: Tighter TP to take profits quickly
            tp_pips = base_tp_pips * Decimal(str(self.cfg.regime_tp_multiplier_ranging))
            sl_pips = base_sl_pips  # Keep SL same
        else:
            # Moderate: Use base values
            tp_pips = base_tp_pips
            sl_pips = base_sl_pips
        
        # Rest of existing calculation logic...
        pip_value = self._calculate_pip_value()
        # ... continue with existing code ...
```

### Step 4: Adjust Trailing Stops Based on Regime

Modify `_update_trailing_stop` method (find it around line 755):

```python
    def _update_trailing_stop(self, bar: Bar) -> None:
        """Update trailing stop logic, adjusted for market regime."""
        # ... existing position checks ...
        
        # Get regime-adjusted trailing parameters
        regime = self._detect_market_regime(bar)
        
        base_activation = Decimal(str(self.cfg.trailing_stop_activation_pips))
        base_distance = Decimal(str(self.cfg.trailing_stop_distance_pips))
        
        if regime == 'trending':
            # Trending: Lower activation (activate sooner), tighter distance
            activation_pips = base_activation * Decimal(str(self.cfg.regime_trailing_activation_multiplier_trending))
            distance_pips = base_distance * Decimal(str(self.cfg.regime_trailing_distance_multiplier_trending))
        elif regime == 'ranging':
            # Ranging: Higher activation (wait for confirmation), wider distance
            activation_pips = base_activation * Decimal(str(self.cfg.regime_trailing_activation_multiplier_ranging))
            distance_pips = base_distance * Decimal(str(self.cfg.regime_trailing_distance_multiplier_ranging))
        else:
            # Moderate: Use base values
            activation_pips = base_activation
            distance_pips = base_distance
        
        # Use adjusted values in trailing stop logic
        # Replace references to self.cfg.trailing_stop_activation_pips with activation_pips
        # Replace references to self.cfg.trailing_stop_distance_pips with distance_pips
        # ... rest of trailing stop calculation ...
```

---

## Method 2: Moving Average Distance (Simpler Alternative)

If you don't want to modify the DMI indicator, use MA distance:

```python
    def _detect_market_regime(self, bar: Bar) -> str:
        """Detect regime using distance between fast and slow MA."""
        if not self.cfg.regime_detection_enabled:
            return 'moderate'
        
        if not self.fast_sma.initialized or not self.slow_sma.initialized:
            return 'moderate'
        
        # Calculate distance between MAs in pips
        distance = abs(self.fast_sma.value - self.slow_sma.value)
        distance_pips = float(distance) * 10000  # Convert to pips
        
        # Threshold: 5 pips separation indicates trending
        if distance_pips > 5.0:
            return 'trending'
        elif distance_pips < 2.0:
            return 'ranging'
        else:
            return 'moderate'
```

---

## Method 3: ATR-Based Volatility Detection

Use ATR to detect volatility regimes:

```python
    def _detect_market_regime(self, bar: Bar) -> str:
        """Detect regime using ATR volatility."""
        if not self.cfg.regime_detection_enabled:
            return 'moderate'
        
        if not self.atr or not self.atr.initialized:
            return 'moderate'
        
        # Compare current ATR to average
        # High ATR = trending (volatile, directional)
        # Low ATR = ranging (calm, sideways)
        
        atr_value = self.atr.value
        # You'd need to track average ATR over longer period
        # For now, use absolute threshold
        if atr_value > 0.0020:  # 20 pips ATR
            return 'trending'
        elif atr_value < 0.0010:  # 10 pips ATR
            return 'ranging'
        else:
            return 'moderate'
```

---

## Testing

### Step 1: Enable Regime Detection

Add to `.env`:

```bash
# Market Regime Detection
STRATEGY_REGIME_DETECTION_ENABLED=true
STRATEGY_REGIME_ADX_TRENDING_THRESHOLD=25.0
STRATEGY_REGIME_ADX_RANGING_THRESHOLD=20.0
STRATEGY_REGIME_TP_MULTIPLIER_TRENDING=1.5
STRATEGY_REGIME_TP_MULTIPLIER_RANGING=0.8
STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING=0.75
STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING=1.25
STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING=0.67
STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING=1.33
```

### Step 2: Run Backtest

```bash
python backtest/run_backtest.py
```

### Step 3: Check Logs

Look for log messages like:
```
Market regime changed: moderate -> trending (ADX=27.45, thresholds: strong>25.0, weak<20.0)
```

### Step 4: Analyze Results

Compare backtests with/without regime detection:
- Check if TP/SL adjustments improved performance
- See how often each regime occurred
- Verify regime changes make sense

---

## Recommended Approach

**Start with ADX-based detection** because:
1. ✅ Uses existing DMI indicator (just need to add ADX calculation)
2. ✅ Well-established indicator
3. ✅ Clear thresholds (ADX > 25 = trending, ADX < 20 = ranging)
4. ✅ Works across timeframes

**Then test different multipliers** to find optimal settings for your data.

---

## Next Steps

1. **Add ADX to DMI indicator** (if using Method 1)
2. **Add regime detection method** to strategy
3. **Modify TP/SL calculation** to use regime
4. **Modify trailing stop** to use regime
5. **Add config parameters** to BacktestConfig
6. **Test on backtest data**
7. **Compare performance** with/without regime detection



