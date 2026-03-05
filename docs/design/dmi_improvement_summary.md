# DMI Filter Improvement - Relative Comparison

## Problem Identified

The current DMI meta-filter only checks **absolute thresholds** without considering **relative directional strength**:

**Current Logic (Original):**
- LONG: Requires `DI+ >= 0.19` (ignores DI-)
- SHORT: Requires `DI- >= 0.19` (ignores DI+)

**Problem Scenario:**
```
DI+ = 0.20 (20%)
DI- = 0.35 (35%)

Current filter: ALLOWS LONG (DI+ >= 0.19) ✓
Reality: Downward momentum is STRONGER (DI- > DI+)
Result: Taking LONG into bearish momentum = likely loss
```

## Solution Implemented

**Improved Logic (New):**
- LONG: Requires `DI+ > DI-` **AND** `DI+ >= 0.19`
- SHORT: Requires `DI- > DI+` **AND** `DI- >= 0.19`

This ensures trades only occur in the direction of **dominant momentum**.

## Files Created

1. **Strategy File:**
   - `strategies/ml_strategy_mtf_v2_entry_confirmed_dmi_relative.py`
   - Based on: `ml_strategy_mtf_v2_entry_confirmed.py`
   - Changes: Improved `_check_meta_filters()` method with relative DMI comparison

2. **Backtest Runner:**
   - `run_backtest_mtf_v2_entry_confirmed_dmi_relative.py`
   - Based on: `run_backtest_mtf_v2_entry_confirmed.py`
   - Changes: Points to new strategy file

## Key Code Changes

### Before (Original):
```python
if self._meta_filter_params.get('dmi_enabled', False):
    min_dmp = float(self._meta_filter_params.get('dmi_min_dmp', 0.0))
    if dmp_30m < min_dmp:
        _py_logger.info(f"[FILTERED] DMI+ {dmp_30m:.4f} < {min_dmp}")
        return False
    _py_logger.info(f"[META_FILTER] DMI+ {dmp_30m:.4f} >= {min_dmp} PASS")
```

### After (Improved):
```python
if self._meta_filter_params.get('dmi_enabled', False):
    min_dmp = float(self._meta_filter_params.get('dmi_min_dmp', 0.0))
    
    if prediction == 1:  # LONG
        # DI+ must dominate DI-
        if dmp_30m <= dmn_30m:
            _py_logger.info(f"[FILTERED] LONG rejected: DI+ {dmp_30m:.4f} <= DI- {dmn_30m:.4f}")
            return False
        if dmp_30m < min_dmp:
            _py_logger.info(f"[FILTERED] LONG rejected: DI+ {dmp_30m:.4f} < {min_dmp}")
            return False
        _py_logger.info(f"[META_FILTER] LONG: DI+ {dmp_30m:.4f} > DI- {dmn_30m:.4f} PASS")
    
    elif prediction == 0:  # SHORT
        # DI- must dominate DI+
        if dmn_30m <= dmp_30m:
            _py_logger.info(f"[FILTERED] SHORT rejected: DI- {dmn_30m:.4f} <= DI+ {dmp_30m:.4f}")
            return False
        if dmn_30m < min_dmp:
            _py_logger.info(f"[FILTERED] SHORT rejected: DI- {dmn_30m:.4f} < {min_dmp}")
            return False
        _py_logger.info(f"[META_FILTER] SHORT: DI- {dmn_30m:.4f} > DI+ {dmp_30m:.4f} PASS")
```

## Expected Impact

**Positive:**
- Fewer false signals when momentum contradicts trade direction
- Higher win rate by avoiding counter-trend trades
- Better alignment with actual market momentum

**Potential Trade-offs:**
- Slightly fewer total trades (more selective)
- May miss some reversal trades (but those are typically lower probability)

## Next Steps

1. **Run Backtest:**
   ```bash
   python run_backtest_mtf_v2_entry_confirmed_dmi_relative.py
   ```

2. **Compare Results:**
   - Original: `backtest_results/MTF_V2_ENTRY_CONFIRMED_20260111_203814/`
   - Improved: `backtest_results/MTF_V2_ENTRY_CONFIRMED_[new_timestamp]/`

3. **Key Metrics to Compare:**
   - Total P&L
   - Win Rate
   - Number of trades
   - Drawdown
   - Sharpe Ratio
   - Number of losing trades

4. **If Improved:**
   - Update live trading to use new strategy
   - Monitor performance in paper trading first
   - Deploy to live account after validation

## Configuration

### New Configurable Parameters in `.env.mtf_v2`:

```bash
# DMI Filter Settings
MTF2_META_FILTER_DMI_ENABLED=true                    # Enable/disable DMI filter
MTF2_META_FILTER_DMI_MIN_DMP=0.19                    # Absolute minimum threshold (e.g., DI+ >= 0.19 for LONG)
MTF2_META_FILTER_DMI_CHECK_ABSOLUTE=true             # Enable/disable absolute threshold check
MTF2_META_FILTER_DMI_MIN_DIVERGENCE=0.0              # Minimum divergence between DI+ and DI- (e.g., 0.05 = 5% difference required)
```

### Parameter Explanations:

**MTF2_META_FILTER_DMI_CHECK_ABSOLUTE** (true/false)
- `true`: Enforces absolute threshold (DI+ >= 0.19 for LONG, DI- >= 0.19 for SHORT)
- `false`: Only checks relative strength (DI+ > DI- for LONG, DI- > DI+ for SHORT)
- **Use case:** Set to `false` if you want to allow trades with weak momentum as long as direction is correct

**MTF2_META_FILTER_DMI_MIN_DIVERGENCE** (0.0 to 1.0)
- Minimum difference required between DI+ and DI-
- `0.0`: Any divergence allowed (DI+ just needs to be > DI-)
- `0.05`: Requires 5% divergence (e.g., DI+ = 0.25, DI- = 0.20 or less)
- **Use case:** Higher values = more selective, only trades with strong directional bias

### Configuration Examples:

**Example 1: Current Default (Strict)**
```bash
MTF2_META_FILTER_DMI_CHECK_ABSOLUTE=true
MTF2_META_FILTER_DMI_MIN_DIVERGENCE=0.0
```
- LONG requires: DI+ > DI- AND DI+ >= 0.19
- SHORT requires: DI- > DI+ AND DI- >= 0.19

**Example 2: Relative Only (No Absolute Threshold)**
```bash
MTF2_META_FILTER_DMI_CHECK_ABSOLUTE=false
MTF2_META_FILTER_DMI_MIN_DIVERGENCE=0.0
```
- LONG requires: DI+ > DI- (any amount)
- SHORT requires: DI- > DI+ (any amount)
- More permissive, allows weak momentum trades

**Example 3: Strong Divergence Required**
```bash
MTF2_META_FILTER_DMI_CHECK_ABSOLUTE=true
MTF2_META_FILTER_DMI_MIN_DIVERGENCE=0.05
```
- LONG requires: DI+ > DI- by at least 5% AND DI+ >= 0.19
- SHORT requires: DI- > DI+ by at least 5% AND DI- >= 0.19
- Most selective, only strong directional moves
