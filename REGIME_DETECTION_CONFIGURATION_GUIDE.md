# Regime Detection Configuration Guide

## Quick Setup

### Step 1: Enable Required Components

```bash
# Enable DMI (REQUIRED - regime detection uses ADX from DMI)
STRATEGY_DMI_ENABLED=true

# Enable regime detection
STRATEGY_REGIME_DETECTION_ENABLED=true
```

### Step 2: Configure DMI Timeframe (Affects Regime Detection)

```bash
# Choose timeframe for regime detection (recommended: 5-minute)
STRATEGY_DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL

# DMI period (default: 14)
STRATEGY_DMI_PERIOD=14
```

### Step 3: Configure Regime Detection Parameters

```bash
# ADX Thresholds
STRATEGY_REGIME_ADX_TRENDING_THRESHOLD=25.0   # ADX > 25 = trending
STRATEGY_REGIME_ADX_RANGING_THRESHOLD=20.0    # ADX < 20 = ranging

# TP Multipliers
STRATEGY_REGIME_TP_MULTIPLIER_TRENDING=1.5    # Trending: TP × 1.5 (wider)
STRATEGY_REGIME_TP_MULTIPLIER_RANGING=0.8     # Ranging: TP × 0.8 (tighter)

# SL Multipliers (usually keep at 1.0)
STRATEGY_REGIME_SL_MULTIPLIER_TRENDING=1.0    # Trending: SL unchanged
STRATEGY_REGIME_SL_MULTIPLIER_RANGING=1.0      # Ranging: SL unchanged

# Trailing Stop Multipliers
STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING=0.75   # Trending: activate sooner (20 → 15 pips)
STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING=1.25    # Ranging: wait longer (20 → 25 pips)
STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING=0.67     # Trending: tighter (15 → 10 pips)
STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING=1.33       # Ranging: wider (15 → 20 pips)
```

---

## Complete Parameter Reference

### 1. Enable/Disable Regime Detection

```bash
STRATEGY_REGIME_DETECTION_ENABLED=true
```
- **Type**: boolean (true/false)
- **Default**: false
- **Description**: Master switch for regime detection
- **Required**: Yes (set to true to enable)

---

### 2. ADX Thresholds

#### Trending Threshold
```bash
STRATEGY_REGIME_ADX_TRENDING_THRESHOLD=25.0
```
- **Type**: float
- **Default**: 25.0
- **Description**: ADX value above which market is considered "trending"
- **Range**: 0-100 (typical: 20-30)
- **Example**: ADX = 28 → Regime = "trending"

#### Ranging Threshold
```bash
STRATEGY_REGIME_ADX_RANGING_THRESHOLD=20.0
```
- **Type**: float
- **Default**: 20.0
- **Description**: ADX value below which market is considered "ranging"
- **Range**: 0-100 (typical: 15-25)
- **Example**: ADX = 15 → Regime = "ranging"

**Note**: If ADX is between these thresholds, regime = "moderate" (no adjustments)

---

### 3. TP Multipliers

#### Trending TP Multiplier
```bash
STRATEGY_REGIME_TP_MULTIPLIER_TRENDING=1.5
```
- **Type**: float
- **Default**: 1.5
- **Description**: Multiplier applied to base TP when regime is "trending"
- **Effect**: Wider TP to let trends run
- **Example**: Base TP = 50 pips → Adjusted TP = 50 × 1.5 = 75 pips

#### Ranging TP Multiplier
```bash
STRATEGY_REGIME_TP_MULTIPLIER_RANGING=0.8
```
- **Type**: float
- **Default**: 0.8
- **Description**: Multiplier applied to base TP when regime is "ranging"
- **Effect**: Tighter TP to lock profits quickly
- **Example**: Base TP = 50 pips → Adjusted TP = 50 × 0.8 = 40 pips

---

### 4. SL Multipliers

#### Trending SL Multiplier
```bash
STRATEGY_REGIME_SL_MULTIPLIER_TRENDING=1.0
```
- **Type**: float
- **Default**: 1.0
- **Description**: Multiplier applied to base SL when regime is "trending"
- **Effect**: Usually kept at 1.0 (unchanged) for consistent risk
- **Example**: Base SL = 25 pips → Adjusted SL = 25 × 1.0 = 25 pips

#### Ranging SL Multiplier
```bash
STRATEGY_REGIME_SL_MULTIPLIER_RANGING=1.0
```
- **Type**: float
- **Default**: 1.0
- **Description**: Multiplier applied to base SL when regime is "ranging"
- **Effect**: Usually kept at 1.0 (unchanged) for consistent risk
- **Example**: Base SL = 25 pips → Adjusted SL = 25 × 1.0 = 25 pips

**Note**: You can adjust these if you want different SL for different regimes (e.g., 1.2 for trending, 0.8 for ranging)

---

### 5. Trailing Stop Activation Multipliers

#### Trending Activation Multiplier
```bash
STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING=0.75
```
- **Type**: float
- **Default**: 0.75
- **Description**: Multiplier for trailing stop activation threshold when trending
- **Effect**: Activates sooner (lower threshold)
- **Example**: Base activation = 20 pips → Adjusted = 20 × 0.75 = 15 pips

#### Ranging Activation Multiplier
```bash
STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING=1.25
```
- **Type**: float
- **Default**: 1.25
- **Description**: Multiplier for trailing stop activation threshold when ranging
- **Effect**: Waits longer before activating (higher threshold)
- **Example**: Base activation = 20 pips → Adjusted = 20 × 1.25 = 25 pips

---

### 6. Trailing Stop Distance Multipliers

#### Trending Distance Multiplier
```bash
STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING=0.67
```
- **Type**: float
- **Default**: 0.67
- **Description**: Multiplier for trailing stop distance when trending
- **Effect**: Tighter trailing (closer to price)
- **Example**: Base distance = 15 pips → Adjusted = 15 × 0.67 = 10 pips

#### Ranging Distance Multiplier
```bash
STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING=1.33
```
- **Type**: float
- **Default**: 1.33
- **Description**: Multiplier for trailing stop distance when ranging
- **Effect**: Wider trailing (more room)
- **Example**: Base distance = 15 pips → Adjusted = 15 × 1.33 = 20 pips

---

## DMI Configuration (Required for Regime Detection)

### Enable DMI
```bash
STRATEGY_DMI_ENABLED=true
```
- **Required**: Yes (regime detection uses ADX from DMI)
- **Default**: true

### DMI Timeframe
```bash
STRATEGY_DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL
```
- **Required**: Yes
- **Default**: 2-MINUTE-MID-EXTERNAL
- **Recommended**: 5-MINUTE-MID-EXTERNAL (better stability)
- **Options**: 2-MINUTE, 5-MINUTE, 15-MINUTE, etc.

### DMI Period
```bash
STRATEGY_DMI_PERIOD=14
```
- **Required**: No
- **Default**: 14
- **Description**: Smoothing period for DMI calculation
- **Note**: Longer period = smoother ADX, slower response

---

## Example Configurations

### Configuration 1: Conservative (Default)
```bash
# Enable
STRATEGY_DMI_ENABLED=true
STRATEGY_REGIME_DETECTION_ENABLED=true
STRATEGY_DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL

# Thresholds
STRATEGY_REGIME_ADX_TRENDING_THRESHOLD=25.0
STRATEGY_REGIME_ADX_RANGING_THRESHOLD=20.0

# TP adjustments (moderate)
STRATEGY_REGIME_TP_MULTIPLIER_TRENDING=1.5
STRATEGY_REGIME_TP_MULTIPLIER_RANGING=0.8

# SL unchanged
STRATEGY_REGIME_SL_MULTIPLIER_TRENDING=1.0
STRATEGY_REGIME_SL_MULTIPLIER_RANGING=1.0

# Trailing stops
STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING=0.75
STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING=1.25
STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING=0.67
STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING=1.33
```

### Configuration 2: Aggressive (Larger Adjustments)
```bash
# Enable
STRATEGY_DMI_ENABLED=true
STRATEGY_REGIME_DETECTION_ENABLED=true
STRATEGY_DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL

# Thresholds (same)
STRATEGY_REGIME_ADX_TRENDING_THRESHOLD=25.0
STRATEGY_REGIME_ADX_RANGING_THRESHOLD=20.0

# TP adjustments (more aggressive)
STRATEGY_REGIME_TP_MULTIPLIER_TRENDING=1.8    # Wider TP in trends
STRATEGY_REGIME_TP_MULTIPLIER_RANGING=0.7      # Tighter TP in ranges

# SL unchanged
STRATEGY_REGIME_SL_MULTIPLIER_TRENDING=1.0
STRATEGY_REGIME_SL_MULTIPLIER_RANGING=1.0

# Trailing stops (more aggressive)
STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING=0.6   # Activate even sooner
STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING=1.5    # Wait even longer
STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING=0.5     # Even tighter
STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING=1.5      # Even wider
```

### Configuration 3: Maximum Stability (15-minute bars)
```bash
# Enable
STRATEGY_DMI_ENABLED=true
STRATEGY_REGIME_DETECTION_ENABLED=true
STRATEGY_DMI_BAR_SPEC=15-MINUTE-MID-EXTERNAL  # Longer timeframe

# Thresholds (same)
STRATEGY_REGIME_ADX_TRENDING_THRESHOLD=25.0
STRATEGY_REGIME_ADX_RANGING_THRESHOLD=20.0

# TP adjustments (conservative)
STRATEGY_REGIME_TP_MULTIPLIER_TRENDING=1.3     # Less aggressive
STRATEGY_REGIME_TP_MULTIPLIER_RANGING=0.9      # Less aggressive

# Rest same as Configuration 1
```

---

## How It Works

### Example: Base Settings
- Base TP: 50 pips
- Base SL: 25 pips
- Base Trailing Activation: 20 pips
- Base Trailing Distance: 15 pips

### Trending Market (ADX = 28)
- **TP**: 50 × 1.5 = **75 pips** (wider)
- **SL**: 25 × 1.0 = **25 pips** (unchanged)
- **Trailing Activation**: 20 × 0.75 = **15 pips** (sooner)
- **Trailing Distance**: 15 × 0.67 = **10 pips** (tighter)

### Ranging Market (ADX = 15)
- **TP**: 50 × 0.8 = **40 pips** (tighter)
- **SL**: 25 × 1.0 = **25 pips** (unchanged)
- **Trailing Activation**: 20 × 1.25 = **25 pips** (later)
- **Trailing Distance**: 15 × 1.33 = **20 pips** (wider)

### Moderate Market (ADX = 22)
- **TP**: 50 pips (unchanged)
- **SL**: 25 pips (unchanged)
- **Trailing Activation**: 20 pips (unchanged)
- **Trailing Distance**: 15 pips (unchanged)

---

## Testing Recommendations

1. **Start with defaults** - Test with default multipliers first
2. **Monitor regime changes** - Check logs for how often regime changes
3. **Adjust thresholds** - If regime changes too often/rarely, adjust ADX thresholds
4. **Tune multipliers** - Adjust TP/SL/trailing multipliers based on backtest results
5. **Test different timeframes** - Try 5-minute vs 15-minute bars

---

## Troubleshooting

### Regime Detection Not Working?
- ✅ Check `STRATEGY_DMI_ENABLED=true` (required!)
- ✅ Check `STRATEGY_REGIME_DETECTION_ENABLED=true`
- ✅ Verify DMI bars are available in your data catalog
- ✅ Check logs for "Market regime:" messages

### Regime Changes Too Frequently?
- Increase `STRATEGY_DMI_BAR_SPEC` to longer timeframe (e.g., 15-minute)
- Widen gap between thresholds (e.g., 30/15 instead of 25/20)

### Regime Never Changes?
- Decrease `STRATEGY_DMI_BAR_SPEC` to shorter timeframe (e.g., 2-minute)
- Narrow gap between thresholds (e.g., 25/20)

### TP/SL Adjustments Too Aggressive?
- Reduce multipliers (e.g., 1.3 instead of 1.5 for trending TP)
- Increase multipliers for ranging (e.g., 0.9 instead of 0.8)

---

## Summary

**Minimum Required Configuration:**
```bash
STRATEGY_DMI_ENABLED=true
STRATEGY_REGIME_DETECTION_ENABLED=true
STRATEGY_DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL
```

All other parameters have sensible defaults and can be adjusted based on your testing results.



