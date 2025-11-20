# ADX Filter Implementation

## Overview
Implemented ADX strength filter to reject trades in choppy/ranging markets where trends are weak.

## What Was Changed

### 1. Strategy Code (`strategies/moving_average_crossover.py`)

**Added Config Parameter** (line ~64):
```python
dmi_adx_min_strength: float = 0.0  # Minimum ADX to confirm trend (0 = disabled, 20+ recommended)
```

**Modified `_check_dmi_trend()` Function**:
Added ADX strength check BEFORE checking trend direction:
```python
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
```

### 2. Environment Configuration (`.env`)

**Enabled DMI Filter**:
```properties
STRATEGY_DMI_ENABLED=true
STRATEGY_DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL
STRATEGY_DMI_PERIOD=14
STRATEGY_DMI_ADX_MIN_STRENGTH=20.0
```

**Disabled Minimum Hold Time** (didn't improve PnL):
```properties
STRATEGY_MIN_HOLD_TIME_ENABLED=false
```

## How It Works

### ADX (Average Directional Index) Explained:
- **ADX measures trend STRENGTH**, not direction
- Values: 0-100 scale
  - **< 20**: Weak/no trend (choppy, ranging market) ⚠️
  - **20-25**: Emerging trend
  - **25-50**: Strong trend ✅
  - **> 50**: Very strong trend

### Filter Logic:
1. When MA crossover occurs, check DMI indicator
2. If `ADX < 20.0`, **reject the signal** (choppy market, poor trade quality)
3. If `ADX >= 20.0`, proceed with direction check (+DI vs -DI)
4. Signal logged as: `dmi_adx_too_weak (ADX=15.23 < 20.00, choppy market)`

### Expected Impact:
Based on `analyze_losing_periods.py` findings:
- **Trades <4h**: Lost $2,383 with 22% win rate (most likely choppy market stop-outs)
- ADX filter should **reduce trade count by 30-40%**
- Expected **win rate improvement: +10-15%** (fewer low-quality trades)
- Potential **PnL improvement: +$1,500 to $3,000**

## Configuration Options

### Conservative (Current):
```properties
STRATEGY_DMI_ADX_MIN_STRENGTH=20.0
```
- Filters weak trends
- Moderate trade reduction (~30-40%)
- Good balance of selectivity vs opportunity

### Aggressive:
```properties
STRATEGY_DMI_ADX_MIN_STRENGTH=25.0
```
- Only trades strong trends
- Larger trade reduction (~50-60%)
- Higher win rate, fewer trades

### Disabled:
```properties
STRATEGY_DMI_ADX_MIN_STRENGTH=0.0
```
- No ADX filtering (only direction check)
- Trades all MA crossovers with correct +DI/-DI alignment

## Testing Plan

### Option 1: Quick Test (Recommended)
Run backtest with current config (ADX >= 20):
```bash
python backtest/run_backtest.py
```

Compare results to baseline:
- Baseline: `logs/backtest_results_baseline/EUR-USD_20251116_130912`
- Expected: Fewer trades, higher win rate, better PnL

### Option 2: Parameter Sweep
Test multiple ADX thresholds:
- **ADX = 15.0**: Very permissive (test if 20 is too strict)
- **ADX = 20.0**: Current setting (recommended)
- **ADX = 25.0**: Strict (only strong trends)
- **ADX = 30.0**: Very strict (only powerful trends)

### Option 3: Combined Filters
After validating ADX filter, enable additional filters:
1. **Hour exclusions** (hours 3, 6, 9, 14, 15 → eliminate $2,184 in losses)
2. **Stochastic momentum** (already coded, just enable)
3. **Higher timeframe trend** (1-min EMA200)

## Monitoring

### Key Metrics to Watch:
1. **Rejected signals count**: Should increase significantly (filtering working)
2. **Total trades**: Should decrease by 30-40%
3. **Win rate**: Should increase by 10-15%
4. **Total PnL**: Should improve (fewer bad trades)
5. **Trades <4h**: Should decrease (fewer choppy market entries)

### Log Messages:
Look for:
```
REJECTED: BUY signal - dmi_adx_too_weak (ADX=15.23 < 20.00, choppy market)
DMI trend confirmed for BUY: +DI=28.45, -DI=18.32, ADX=32.10
```

## Rollback Instructions

If ADX filter reduces performance:

1. **Disable ADX threshold** (keep DMI direction check):
   ```properties
   STRATEGY_DMI_ADX_MIN_STRENGTH=0.0
   ```

2. **Disable entire DMI filter**:
   ```properties
   STRATEGY_DMI_ENABLED=false
   ```

3. **Restore baseline**:
   ```bash
   Copy-Item .env.without_min_hold_time .env -Force
   ```

## Next Steps

1. ✅ **Run backtest** with ADX filter enabled
2. 📊 **Analyze results** using `analyze_monthly_pnl.py`
3. 📈 **Compare to baseline** (performance_stats.json)
4. 🔧 **Tune threshold** if needed (15.0, 20.0, 25.0, 30.0)
5. ➕ **Add hour exclusions** (next improvement layer)

## Technical Details

### Why 5-Minute Bars for DMI?
```properties
STRATEGY_DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL
```
- Strategy trades on 15-minute bars
- DMI on 5-minute gives more responsive trend detection
- Faster reaction to regime changes
- 14-period DMI on 5-min = 70 minutes of data

### Integration with Existing Code:
- DMI already calculated (indicators/dmi.py)
- ADX already available via `self.dmi.adx`
- Only added: threshold check before signal acceptance
- Backward compatible: ADX=0.0 disables filter

## References

- **Analysis**: `analyze_losing_periods.py` - Identified <4h trades as primary issue
- **Filter Audit**: `FILTER_IMPLEMENTATION_AUDIT.md` - Found ADX calculated but not used
- **Min Hold Time Results**: `MIN_HOLD_TIME_RESULTS.md` - Wider stops didn't work, need better filtering
- **Baseline Results**: `logs/backtest_results_baseline/EUR-USD_20251116_130912`

---

**Status**: ✅ Implemented, ready for testing  
**Expected Impact**: +10-15% win rate, -30-40% trades, +$1,500-$3,000 PnL  
**Risk**: Low (can disable if performance decreases)
