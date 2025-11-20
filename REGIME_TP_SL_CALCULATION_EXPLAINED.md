# How TP/SL Calculation Works for Different Regimes

## Overview

When regime detection is enabled, TP/SL values are **multiplied** by configurable factors based on the detected market regime. The base values come from your config, then get adjusted.

---

## Calculation Flow

### Step 1: Get Base Values from Config

```python
base_tp_pips = Decimal(str(self.cfg.take_profit_pips))  # e.g., 50 pips
base_sl_pips = Decimal(str(self.cfg.stop_loss_pips))     # e.g., 25 pips
```

These are your **default TP/SL settings** from `.env` or config defaults.

---

### Step 2: Detect Current Market Regime

```python
regime = self._detect_market_regime(bar)
# Returns: 'trending', 'ranging', or 'moderate'
```

The regime is detected using ADX (or other method) on each bar.

---

### Step 3: Apply Regime-Specific Multipliers

```python
if regime == 'trending':
    # Trending: Wider TP to let trends run
    tp_pips = base_tp_pips * Decimal(str(self.cfg.regime_tp_multiplier_trending))
    sl_pips = base_sl_pips  # Keep SL same
    
elif regime == 'ranging':
    # Ranging: Tighter TP to take profits quickly
    tp_pips = base_tp_pips * Decimal(str(self.cfg.regime_tp_multiplier_ranging))
    sl_pips = base_sl_pips  # Keep SL same
    
else:  # 'moderate'
    # Moderate: Use base values unchanged
    tp_pips = base_tp_pips
    sl_pips = base_sl_pips
```

---

## Example Calculations

### Scenario: Base TP = 50 pips, Base SL = 25 pips

#### Trending Market (ADX > 25)
- **Multiplier**: 1.5 (from config)
- **Calculated TP**: 50 × 1.5 = **75 pips**
- **Calculated SL**: 25 × 1.0 = **25 pips** (unchanged)

**Why**: In trending markets, you want to let profits run, so wider TP helps capture more of the trend.

---

#### Ranging Market (ADX < 20)
- **Multiplier**: 0.8 (from config)
- **Calculated TP**: 50 × 0.8 = **40 pips**
- **Calculated SL**: 25 × 1.0 = **25 pips** (unchanged)

**Why**: In ranging markets, price often reverses, so tighter TP helps lock in profits before reversal.

---

#### Moderate Market (ADX 20-25)
- **Multiplier**: 1.0 (no change)
- **Calculated TP**: 50 × 1.0 = **50 pips**
- **Calculated SL**: 25 × 1.0 = **25 pips**

**Why**: Use default settings when trend strength is unclear.

---

## Complete Code Implementation

Here's how it fits into the existing `_calculate_sl_tp_prices` method:

```python
def _calculate_sl_tp_prices(self, entry_price: Decimal, side: OrderSide, bar: Bar) -> Tuple[Decimal, Decimal]:
    """
    Calculate SL/TP prices, adjusted for market regime.
    
    Args:
        entry_price: Entry price for the trade
        side: OrderSide.BUY or OrderSide.SELL
        bar: Current bar (used for regime detection)
    
    Returns:
        Tuple of (sl_price, tp_price) as Decimal
    """
    # Step 1: Get base TP/SL from config
    base_tp_pips = Decimal(str(self.cfg.take_profit_pips))
    base_sl_pips = Decimal(str(self.cfg.stop_loss_pips))
    
    # Step 2: Detect market regime
    regime = self._detect_market_regime(bar)
    
    # Step 3: Apply regime-specific multipliers
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
    
    # Step 4: Convert pips to price increments
    pip_value = self._calculate_pip_value()
    tp_decimal = tp_pips * pip_value
    sl_decimal = sl_pips * pip_value
    
    # Step 5: Calculate actual prices based on order side
    if side == OrderSide.BUY:
        tp_price = entry_price + tp_decimal
        sl_price = entry_price - sl_decimal
    else:  # SELL
        tp_price = entry_price - tp_decimal
        sl_price = entry_price + sl_decimal
    
    # Step 6: Round to instrument's price increment
    price_increment = self.instrument.price_increment
    tp_price = (tp_price / price_increment).quantize(Decimal('1')) * price_increment
    sl_price = (sl_price / price_increment).quantize(Decimal('1')) * price_increment
    
    return sl_price, tp_price
```

---

## Configuration Parameters

Add to `MovingAverageCrossoverConfig`:

```python
# Market regime detection
regime_detection_enabled: bool = False
regime_adx_trending_threshold: float = 25.0
regime_adx_ranging_threshold: float = 20.0

# TP multipliers (applied to base TP)
regime_tp_multiplier_trending: float = 1.5   # 50 pips -> 75 pips
regime_tp_multiplier_ranging: float = 0.8    # 50 pips -> 40 pips

# SL multipliers (optional - currently kept same)
regime_sl_multiplier_trending: float = 1.0   # Keep SL same
regime_sl_multiplier_ranging: float = 1.0   # Keep SL same
```

---

## Why This Approach?

### 1. **Multiplicative Scaling**
- Uses multipliers (e.g., 1.5x, 0.8x) instead of fixed values
- Works with any base TP/SL settings
- Easy to adjust via config

### 2. **SL Usually Unchanged**
- Stop loss represents risk tolerance
- Usually want consistent risk regardless of regime
- Can be made configurable if needed

### 3. **TP Adjusted for Regime**
- **Trending**: Wider TP captures more of the trend
- **Ranging**: Tighter TP locks profits before reversal
- **Moderate**: Default TP works well

---

## Example: Real Trade Scenario

### Trade Entry: EUR/USD at 1.1000

#### Base Settings (from config):
- TP: 50 pips
- SL: 25 pips

#### Regime: Trending (ADX = 28)
- **Adjusted TP**: 50 × 1.5 = **75 pips**
- **Adjusted SL**: 25 pips (unchanged)
- **TP Price (BUY)**: 1.1000 + 0.0075 = **1.1075**
- **SL Price (BUY)**: 1.1000 - 0.0025 = **1.0975**

#### Regime: Ranging (ADX = 15)
- **Adjusted TP**: 50 × 0.8 = **40 pips**
- **Adjusted SL**: 25 pips (unchanged)
- **TP Price (BUY)**: 1.1000 + 0.0040 = **1.1040**
- **SL Price (BUY)**: 1.1000 - 0.0025 = **1.0975**

---

## Advanced: SL Adjustment (Optional)

If you want to adjust SL too:

```python
if regime == 'trending':
    tp_pips = base_tp_pips * Decimal(str(self.cfg.regime_tp_multiplier_trending))
    sl_pips = base_sl_pips * Decimal(str(self.cfg.regime_sl_multiplier_trending))
elif regime == 'ranging':
    tp_pips = base_tp_pips * Decimal(str(self.cfg.regime_tp_multiplier_ranging))
    sl_pips = base_sl_pips * Decimal(str(self.cfg.regime_sl_multiplier_ranging))
```

**Example multipliers**:
- **Trending SL**: 1.2x (wider stop to avoid whipsaws)
- **Ranging SL**: 0.8x (tighter stop for quick exits)

---

## When Calculation Happens

The TP/SL calculation happens **when a trade signal is generated**:

1. Crossover detected
2. All filters pass
3. `_calculate_sl_tp_prices()` called with current bar
4. Regime detected from current bar
5. TP/SL calculated with regime-adjusted values
6. Orders placed with calculated prices

**Important**: Regime is detected **at entry time**, not continuously updated. This is intentional - you want consistent TP/SL for the entire trade.

---

## Testing Different Multipliers

You can test different multiplier values:

```bash
# Test 1: Conservative (smaller adjustments)
STRATEGY_REGIME_TP_MULTIPLIER_TRENDING=1.3
STRATEGY_REGIME_TP_MULTIPLIER_RANGING=0.9

# Test 2: Aggressive (larger adjustments)
STRATEGY_REGIME_TP_MULTIPLIER_TRENDING=1.8
STRATEGY_REGIME_TP_MULTIPLIER_RANGING=0.7

# Test 3: Moderate (balanced)
STRATEGY_REGIME_TP_MULTIPLIER_TRENDING=1.5
STRATEGY_REGIME_TP_MULTIPLIER_RANGING=0.8
```

Run backtests with each to find optimal multipliers for your data.

---

## Summary

**How TP/SL is calculated for different regimes:**

1. **Base values** come from config (e.g., TP=50, SL=25)
2. **Regime detected** using ADX (or other method)
3. **Multipliers applied**:
   - Trending: TP × 1.5 (wider)
   - Ranging: TP × 0.8 (tighter)
   - Moderate: TP × 1.0 (unchanged)
4. **SL usually unchanged** (consistent risk)
5. **Prices calculated** from adjusted pips
6. **Orders placed** with calculated prices

The key insight: **Multipliers scale your base TP/SL** based on market conditions, allowing the strategy to adapt automatically.



