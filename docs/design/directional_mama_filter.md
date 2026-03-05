# Directional MAMA Filter Implementation

## Overview

This document explains the new direction-aware MAMA/FAMA filter implementation in `ml_strategy_mtf_v2_entry_confirmed_directional_mama.py`.

## Problem with Original Implementation

The original MAMA filter in `ml_strategy_mtf_v2_entry_confirmed.py` was **direction-agnostic**:

```python
# Original filter
mama_diff = (mama - fama) / close
if mama_diff < min_diff:  # e.g., min_diff = 0.0001
    return False  # Block signal
```

**Issues:**
- Only allowed signals when `MAMA > FAMA` (bullish trend)
- **Blocked ALL signals when `MAMA < FAMA`**, regardless of prediction direction
- This meant SHORT signals during bearish trends were filtered out
- Result: 0 trades when market was in bearish MAMA regime

## New Direction-Aware Implementation

The new implementation considers the ML model's prediction direction:

```python
# New directional filter
if prediction == 1:  # LONG signal
    # Require MAMA > FAMA (bullish trend alignment)
    if mama_diff < min_diff:
        return False
else:  # SHORT signal (prediction == 0)
    # Require MAMA < FAMA (bearish trend alignment)
    if mama_diff > -min_diff:
        return False
```

**Logic:**
- **LONG signals** (prediction=1): Require `mama_diff >= +0.0001` (MAMA above FAMA)
- **SHORT signals** (prediction=0): Require `mama_diff <= -0.0001` (MAMA below FAMA)

## Symmetric Threshold Logic

With `min_diff = 0.0001` (0.01%):

| Signal Type | MAMA Condition | mama_diff Requirement | Interpretation |
|-------------|----------------|----------------------|----------------|
| LONG | MAMA > FAMA | `mama_diff >= +0.0001` | Bullish trend alignment |
| SHORT | MAMA < FAMA | `mama_diff <= -0.0001` | Bearish trend alignment |

## Example Scenarios

### Scenario 1: Bullish MAMA Regime
- `mama_diff = +0.00025` (MAMA 0.025% above FAMA)
- LONG signal: ✅ **PASS** (0.00025 >= 0.0001)
- SHORT signal: ❌ **FILTERED** (0.00025 > -0.0001, not bearish enough)

### Scenario 2: Bearish MAMA Regime
- `mama_diff = -0.00035` (MAMA 0.035% below FAMA)
- LONG signal: ❌ **FILTERED** (-0.00035 < 0.0001, not bullish enough)
- SHORT signal: ✅ **PASS** (-0.00035 <= -0.0001)

### Scenario 3: Neutral MAMA Regime
- `mama_diff = +0.00005` (MAMA 0.005% above FAMA, below threshold)
- LONG signal: ❌ **FILTERED** (0.00005 < 0.0001)
- SHORT signal: ❌ **FILTERED** (0.00005 > -0.0001)

## Files Modified

### New Strategy File
- **`strategies/ml_strategy_mtf_v2_entry_confirmed_directional_mama.py`**
  - Copy of original with directional MAMA filter
  - Modified `_check_meta_filters()` to accept `prediction` parameter
  - Implements symmetric threshold logic

### New Backtest Runner
- **`run_backtest_mtf_v2_entry_confirmed_directional_mama.py`**
  - Copy of original backtest runner
  - Updated to use new strategy file
  - Output directory: `MTF_V2_DIRECTIONAL_MAMA_{timestamp}`

## Running the New Version

```bash
# Run backtest with directional MAMA filter
python run_backtest_mtf_v2_entry_confirmed_directional_mama.py
```

The backtest will use the same configuration from `.env.mtf_v2` but with the new directional MAMA logic.

## Configuration

The MAMA filter is controlled by these config parameters:

```python
meta_filter_mama_enabled: bool = True/False
meta_filter_mama_min_diff: float = 0.0001  # 0.01% threshold
```

To enable/disable in config:
- Set `meta_filter_mama_enabled = True` to use directional MAMA filter
- Set `meta_filter_mama_min_diff` to adjust the threshold (e.g., 0.0001 = 0.01%)

## Expected Impact

### Before (Original Filter)
- Only LONG signals in bullish MAMA regimes
- All signals filtered when MAMA < FAMA
- Result: 0 trades in bearish periods

### After (Directional Filter)
- LONG signals in bullish MAMA regimes
- SHORT signals in bearish MAMA regimes
- Both directions can trade with trend alignment
- Expected: More trades, balanced long/short exposure

## Comparison Testing

To compare the two versions:

1. **Original version:**
   ```bash
   python run_backtest_mtf_v2_entry_confirmed.py
   ```

2. **Directional MAMA version:**
   ```bash
   python run_backtest_mtf_v2_entry_confirmed_directional_mama.py
   ```

Compare the results in:
- `backtest_results/MTF_V2_ENTRY_CONFIRMED_{timestamp}/`
- `backtest_results/MTF_V2_DIRECTIONAL_MAMA_{timestamp}/`

## Key Metrics to Compare

- **Total Trades**: Should increase with directional filter
- **Win Rate**: May change depending on SHORT signal quality
- **PnL**: Overall profitability comparison
- **Long vs Short**: Balance of directional trades
- **Sharpe Ratio**: Risk-adjusted returns

## Rollback

If the new version doesn't perform well, simply use the original files:
- `strategies/ml_strategy_mtf_v2_entry_confirmed.py`
- `run_backtest_mtf_v2_entry_confirmed.py`

The original implementation is preserved and unchanged.
