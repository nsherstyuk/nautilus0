# Market Regime Detection Guide

## Overview

Market regime detection identifies whether the market is in a **trending** or **ranging** state. This allows you to adapt TP/SL and trailing stop settings accordingly.

---

## Why Market Regime Detection Matters

### Trending Markets
- **Characteristics**: Strong directional movement, momentum
- **Best Settings**: 
  - Wider TP (70-100 pips) - let trends run
  - Tighter trailing stops (10-15 pips) - protect profits quickly
  - Lower activation threshold (10-15 pips) - activate sooner

### Ranging Markets
- **Characteristics**: Sideways movement, choppy price action
- **Best Settings**:
  - Tighter TP (30-50 pips) - take profits quickly
  - Wider trailing stops (20-25 pips) - give more room
  - Higher activation threshold (20-25 pips) - wait for confirmation

---

## Detection Methods

### Method 1: ADX (Average Directional Index) - **RECOMMENDED**

**What it measures**: Strength of trend (not direction)

**How it works**:
- ADX > 25: Strong trend (trending market)
- ADX 20-25: Moderate trend
- ADX < 20: Weak/no trend (ranging market)

**Advantages**:
- Already available in your codebase (DMI indicator)
- Well-established indicator
- Works across timeframes
- Clear thresholds

**Implementation**:
```python
def detect_regime_adx(dmi_indicator, threshold_strong=25, threshold_weak=20):
    """
    Detect market regime using ADX from DMI indicator.
    
    Returns:
        'trending': ADX > threshold_strong
        'ranging': ADX < threshold_weak
        'moderate': threshold_weak <= ADX <= threshold_strong
    """
    if not dmi_indicator or not dmi_indicator.adx.initialized:
        return 'unknown'
    
    adx_value = dmi_indicator.adx.value
    
    if adx_value > threshold_strong:
        return 'trending'
    elif adx_value < threshold_weak:
        return 'ranging'
    else:
        return 'moderate'
```

---

### Method 2: Moving Average Slope

**What it measures**: Direction and strength of trend

**How it works**:
- Calculate slope of EMA/SMA over N periods
- Steep slope = trending
- Flat slope = ranging

**Advantages**:
- Simple to understand
- Already have moving averages in strategy
- Can detect trend direction

**Implementation**:
```python
def detect_regime_ma_slope(ema_indicator, lookback_periods=20, threshold=0.0001):
    """
    Detect regime by measuring EMA slope.
    
    Returns:
        'trending': Slope exceeds threshold
        'ranging': Slope below threshold
    """
    if not ema_indicator or not ema_indicator.initialized:
        return 'unknown'
    
    # Need to store previous EMA values
    # Calculate slope: (current_ema - ema_N_periods_ago) / N
    # For EUR/USD, threshold ~0.0001 = ~1 pip per period
    
    current_ema = ema_indicator.value
    # Would need to track historical values
    # slope = (current_ema - ema_N_periods_ago) / lookback_periods
    
    if abs(slope) > threshold:
        return 'trending'
    else:
        return 'ranging'
```

---

### Method 3: Price Range Analysis

**What it measures**: Volatility and price movement patterns

**How it works**:
- Calculate price range over N periods
- High range = trending (directional movement)
- Low range = ranging (sideways movement)
- Compare to ATR for normalization

**Advantages**:
- Uses price action directly
- Can combine with ATR
- Works well for volatility-based detection

**Implementation**:
```python
def detect_regime_price_range(bars, lookback_periods=20, atr_indicator=None):
    """
    Detect regime by analyzing price range vs ATR.
    
    Returns:
        'trending': Range significantly exceeds ATR
        'ranging': Range similar to or below ATR
    """
    if len(bars) < lookback_periods:
        return 'unknown'
    
    # Calculate high-low range over lookback
    recent_bars = bars[-lookback_periods:]
    price_range = max(b.close for b in recent_bars) - min(b.close for b in recent_bars)
    
    if atr_indicator and atr_indicator.initialized:
        atr_value = atr_indicator.value
        # If range is much larger than ATR, likely trending
        if price_range > atr_value * 1.5:
            return 'trending'
        elif price_range < atr_value * 0.8:
            return 'ranging'
        else:
            return 'moderate'
    else:
        # Fallback: use absolute threshold
        # For EUR/USD, ~0.0020 (20 pips) might indicate ranging
        if price_range < 0.0020:
            return 'ranging'
        else:
            return 'trending'
```

---

### Method 4: Moving Average Crossover Distance

**What it measures**: Separation between fast and slow MA

**How it works**:
- Calculate distance between fast and slow MA
- Large distance = strong trend
- Small distance = ranging market

**Advantages**:
- Uses existing indicators in your strategy
- Simple to implement
- Already calculated for crossover detection

**Implementation**:
```python
def detect_regime_ma_distance(fast_ma, slow_ma, threshold_pips=5.0):
    """
    Detect regime by measuring distance between fast and slow MA.
    
    Returns:
        'trending': MA distance > threshold
        'ranging': MA distance < threshold
    """
    if not fast_ma.initialized or not slow_ma.initialized:
        return 'unknown'
    
    distance = abs(fast_ma.value - slow_ma.value)
    distance_pips = distance * 10000  # Convert to pips for EUR/USD
    
    if distance_pips > threshold_pips:
        return 'trending'
    else:
        return 'ranging'
```

---

### Method 5: Combined Approach (Most Robust)

**What it measures**: Multiple indicators combined

**How it works**:
- Use ADX for trend strength
- Use MA slope for trend direction
- Use price range for volatility confirmation
- Combine signals with voting or scoring

**Advantages**:
- Most robust
- Reduces false signals
- Accounts for multiple factors

**Implementation**:
```python
def detect_regime_combined(dmi_indicator, fast_ma, slow_ma, atr_indicator, bars):
    """
    Detect regime using multiple indicators.
    
    Returns:
        'trending': Multiple indicators agree
        'ranging': Multiple indicators agree
        'moderate': Mixed signals
    """
    signals = []
    
    # ADX signal
    if dmi_indicator and dmi_indicator.adx.initialized:
        adx = dmi_indicator.adx.value
        if adx > 25:
            signals.append('trending')
        elif adx < 20:
            signals.append('ranging')
    
    # MA distance signal
    if fast_ma.initialized and slow_ma.initialized:
        distance = abs(fast_ma.value - slow_ma.value) * 10000
        if distance > 5.0:
            signals.append('trending')
        elif distance < 2.0:
            signals.append('ranging')
    
    # Count signals
    trending_count = signals.count('trending')
    ranging_count = signals.count('ranging')
    
    if trending_count >= 2:
        return 'trending'
    elif ranging_count >= 2:
        return 'ranging'
    else:
        return 'moderate'
```

---

## Implementation in Your Strategy

### Step 1: Add Regime Detection Method

Add to `MovingAverageCrossover` class:

```python
def _detect_market_regime(self, bar: Bar) -> str:
    """
    Detect current market regime: 'trending', 'ranging', or 'moderate'.
    
    Uses ADX from DMI indicator (already available in your strategy).
    """
    if not self.dmi or not self.dmi.adx.initialized:
        return 'moderate'  # Default to moderate if not initialized
    
    adx_value = self.dmi.adx.value
    
    # Thresholds (can be made configurable)
    TRENDING_THRESHOLD = 25
    RANGING_THRESHOLD = 20
    
    if adx_value > TRENDING_THRESHOLD:
        return 'trending'
    elif adx_value < RANGING_THRESHOLD:
        return 'ranging'
    else:
        return 'moderate'
```

### Step 2: Adjust TP/SL Based on Regime

Modify `_calculate_sl_tp_prices` method:

```python
def _calculate_sl_tp_prices(self, entry_price: Decimal, side: OrderSide, bar: Bar) -> Tuple[Decimal, Decimal]:
    """
    Calculate SL/TP prices, adjusted for market regime.
    """
    # Detect current regime
    regime = self._detect_market_regime(bar)
    
    # Base TP/SL from config
    base_tp_pips = Decimal(str(self.cfg.take_profit_pips))
    base_sl_pips = Decimal(str(self.cfg.stop_loss_pips))
    
    # Adjust based on regime
    if regime == 'trending':
        # Trending: Wider TP, same SL
        tp_pips = base_tp_pips * Decimal('1.5')  # 50 -> 75 pips
        sl_pips = base_sl_pips  # Keep SL same
    elif regime == 'ranging':
        # Ranging: Tighter TP, same SL
        tp_pips = base_tp_pips * Decimal('0.8')  # 50 -> 40 pips
        sl_pips = base_sl_pips  # Keep SL same
    else:
        # Moderate: Use base values
        tp_pips = base_tp_pips
        sl_pips = base_sl_pips
    
    # Calculate prices (existing logic)
    pip_value = self._calculate_pip_value()
    # ... rest of calculation
```

### Step 3: Adjust Trailing Stops Based on Regime

Modify `_update_trailing_stop` method:

```python
def _update_trailing_stop(self, bar: Bar) -> None:
    """Update trailing stop logic, adjusted for market regime."""
    # ... existing position checks ...
    
    # Detect regime
    regime = self._detect_market_regime(bar)
    
    # Adjust trailing parameters based on regime
    if regime == 'trending':
        # Trending: Lower activation, tighter distance
        activation_pips = Decimal(str(self.cfg.trailing_stop_activation_pips)) * Decimal('0.75')  # 20 -> 15
        distance_pips = Decimal(str(self.cfg.trailing_stop_distance_pips)) * Decimal('0.67')  # 15 -> 10
    elif regime == 'ranging':
        # Ranging: Higher activation, wider distance
        activation_pips = Decimal(str(self.cfg.trailing_stop_activation_pips)) * Decimal('1.25')  # 20 -> 25
        distance_pips = Decimal(str(self.cfg.trailing_stop_distance_pips)) * Decimal('1.33')  # 15 -> 20
    else:
        # Moderate: Use base values
        activation_pips = Decimal(str(self.cfg.trailing_stop_activation_pips))
        distance_pips = Decimal(str(self.cfg.trailing_stop_distance_pips))
    
    # Use adjusted values in trailing stop logic
    # ... rest of trailing stop calculation ...
```

---

## Configuration Options

Add to `MovingAverageCrossoverConfig`:

```python
# Market regime detection
regime_detection_enabled: bool = False
regime_adx_trending_threshold: float = 25.0
regime_adx_ranging_threshold: float = 20.0
regime_tp_multiplier_trending: float = 1.5  # TP multiplier for trending
regime_tp_multiplier_ranging: float = 0.8   # TP multiplier for ranging
regime_trailing_activation_multiplier_trending: float = 0.75
regime_trailing_activation_multiplier_ranging: float = 1.25
regime_trailing_distance_multiplier_trending: float = 0.67
regime_trailing_distance_multiplier_ranging: float = 1.33
```

---

## Testing Regime Detection

### Step 1: Add Logging

```python
def _detect_market_regime(self, bar: Bar) -> str:
    regime = self._detect_market_regime_internal(bar)
    
    # Log regime changes
    if not hasattr(self, '_last_regime'):
        self._last_regime = None
    
    if regime != self._last_regime:
        self.log.info(f"Market regime changed: {self._last_regime} -> {regime} (ADX={self.dmi.adx.value:.2f})")
        self._last_regime = regime
    
    return regime
```

### Step 2: Analyze Regime Distribution

Create analysis script:

```python
# analyze_regime_distribution.py
import pandas as pd
from pathlib import Path

def analyze_regime_distribution(positions_file: Path):
    """Analyze how often each regime occurred."""
    pos_df = pd.read_csv(positions_file)
    
    # Would need to add regime column during backtest
    # Or calculate post-hoc using ADX values
    
    regime_counts = pos_df['regime'].value_counts()
    print("Regime Distribution:")
    print(regime_counts)
    print(f"\nTrending: {regime_counts.get('trending', 0)} trades")
    print(f"Ranging: {regime_counts.get('ranging', 0)} trades")
    print(f"Moderate: {regime_counts.get('moderate', 0)} trades")
```

---

## Recommended Approach

**Start with ADX-based detection** because:
1. ✅ Already have DMI indicator in your codebase
2. ✅ Well-established and reliable
3. ✅ Simple to implement
4. ✅ Clear thresholds
5. ✅ Works across timeframes

**Then add combined approach** if needed:
- Combine ADX with MA distance
- Add price range analysis
- Use voting system for robustness

---

## Next Steps

1. **Implement ADX-based regime detection** in your strategy
2. **Add regime-based TP/SL adjustment**
3. **Add regime-based trailing stop adjustment**
4. **Test on backtest data** - compare performance with/without regime detection
5. **Analyze regime distribution** - see how often each regime occurs
6. **Fine-tune thresholds** based on your data

---

## Example: Complete Implementation

See `REGIME_DETECTION_IMPLEMENTATION.py` for a complete example that can be integrated into your strategy.



