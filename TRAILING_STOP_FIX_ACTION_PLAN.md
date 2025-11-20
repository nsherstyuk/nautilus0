# Trailing Stop Fix - Action Plan

## Critical Discovery (Nov 16, 2025)

**ALL trailing stops were non-functional during backtesting**
- Root cause: Stale order reference (`self._current_stop_order`)
- When NautilusTrader modifies orders, it creates NEW orders with different IDs
- Strategy held reference to OLD (cancelled) order → early return on every bar
- Result: Every position used **static stop loss only** (no trailing)

## Impact Assessment

### What's Invalidated
1. ✗ All trailing stop parameter optimization (activation threshold, distance)
2. ✗ Duration-based trailing optimization (12h threshold, 30 pip distance)
3. ✗ Any PnL improvements attributed to trailing stop tuning
4. ✗ Comparison between "trailing enabled" vs "trailing disabled" configs

### What's Still Valid
✓ Entry signal optimization (MA periods, crossover threshold)
✓ Time-based filters (excluded hours, weekdays)
✓ Take profit levels (these worked as LIMIT orders)
✓ Initial stop loss distances
✓ Position sizing and risk management

## Immediate Action Items

### Phase 1: Verify the Fix (Priority: CRITICAL)
**Goal**: Confirm trailing stops now work with the fixed code

1. **Run Baseline Comparison**
   ```bash
   # 1-month test: Jan 2024
   python backtest/run_backtest.py --start-date 2024-01-01 --end-date 2024-01-31
   ```
   - Check logs for actual trailing stop modifications
   - Verify stop orders are being updated (multiple stop orders per position)
   - Compare PnL with/without trailing enabled

2. **Add Comprehensive Trailing Diagnostics**
   - Log every trailing stop modification with:
     - Old stop price → New stop price
     - Profit at modification time
     - Distance moved
   - Track trailing statistics:
     - How many positions had trailing activated?
     - Average number of trailing modifications per position
     - Positions closed by trailing stop vs TP vs initial SL

3. **Test Duration-Based Feature Specifically**
   - Run with duration threshold = 2h, distance = 100 pips
   - Verify duration-based logic executes
   - Check TP cancellation logs
   - Confirm wider trailing distance applied

### Phase 2: Comprehensive Filter Verification (Priority: HIGH)
**Goal**: Ensure ALL filters have proper logging and work correctly

#### Current Filter Status

| Filter Type | Location | Logging | Verified Working? |
|------------|----------|---------|-------------------|
| Time exclusion (hours) | `on_bar()` line ~1589 | ✓ Yes (shows in logs) | ✓ Yes |
| Weekday exclusion | `on_bar()` line ~1596 | ⚠️ Minimal | ❓ Unknown |
| Crossover threshold | `on_bar()` line ~1631 | ✓ Yes | ✓ Yes |
| ADX filter | ❌ **NOT IMPLEMENTED** | N/A | N/A |
| Regime detection | ❓ Unclear status | ❓ Unknown | ❓ Unknown |
| Min hold time | `_check_exit_conditions()` | ⚠️ Minimal | ❓ Unknown |
| Dormant mode | Various places | ⚠️ Minimal | ❓ Unknown |
| Trailing stops | `_update_trailing_stop()` | ✓ Added now | ❌ **WAS BROKEN** |

#### Filter Logging Enhancement Tasks

```python
# Template for comprehensive filter logging:
def _check_filter(self, filter_name, condition, details):
    if not condition:
        self.log.info(f"[FILTER_{filter_name}] BLOCKED: {details}")
        self._track_rejection(filter_name)
        return False
    return True
```

**Add logging for:**

1. **Weekday Filter** (line ~1596):
   ```python
   if bar_time.weekday() in self.excluded_weekdays:
       self.log.info(f"[FILTER_WEEKDAY] Excluded weekday={bar_time.strftime('%A')}, bar_close={bar_time}")
       return
   ```

2. **Min Hold Time** (`_check_exit_conditions`):
   ```python
   if hold_time < self.cfg.min_hold_time_hours:
       self.log.info(f"[FILTER_MIN_HOLD] Position held {hold_time:.1f}h < {self.cfg.min_hold_time_hours}h minimum")
       return False
   ```

3. **Dormant Mode Entry** (wherever checked):
   ```python
   if self._dormant_mode_active:
       self.log.info(f"[FILTER_DORMANT] Strategy in dormant mode, no new entries")
       return
   ```

4. **ADX Filter** (IF implemented):
   ```python
   if adx_value < self.cfg.adx_threshold:
       self.log.info(f"[FILTER_ADX] ADX {adx_value:.2f} < {self.cfg.adx_threshold} threshold")
       return
   ```

### Phase 3: Re-Run Critical Backtests (Priority: HIGH)
**Goal**: Get accurate performance metrics with working trailing stops

1. **Baseline Comparison (Full Period)**
   ```bash
   # Run THREE configs:
   # 1. Original baseline (no trailing)
   # 2. Basic trailing (20 pips, 5 pip activation)
   # 3. Duration-based trailing (2h threshold, 100 pips distance)
   
   python backtest/run_backtest.py --start-date 2024-01-01 --end-date 2025-10-30
   ```

2. **Expected Outcomes**
   - Basic trailing should IMPROVE PnL vs no trailing (lets winners run)
   - Duration-based should show DIFFERENT results than basic
   - Should see positions with 10+ stop modifications (trailing worked)
   - Some positions should close via trailing stop (not just TP/initial SL)

3. **Key Metrics to Compare**
   - **Total PnL**: Should increase with trailing
   - **Average Win Size**: Should increase (trailing lets winners run)
   - **Max Adverse Excursion**: Should decrease (trailing protects profits)
   - **Win Rate**: May decrease slightly (some winners trail out early)
   - **Profit Factor**: Should improve

### Phase 4: Re-Optimize Trailing Parameters (Priority: MEDIUM)
**Goal**: Find optimal trailing stop configuration now that it actually works

Only proceed after Phase 1-3 complete successfully.

#### Parameters to Grid Search

```json
{
  "trailing_activation_threshold_pips": [3, 5, 10, 15],
  "trailing_distance_pips": [10, 15, 20, 30],
  "trailing_duration_enabled": [true, false],
  "trailing_duration_threshold_hours": [1, 2, 4, 8, 12],
  "trailing_duration_distance_pips": [30, 50, 100, 150]
}
```

#### Optimization Approach

1. **Step 1**: Optimize basic trailing (activation + distance)
2. **Step 2**: With optimal basic trailing, test duration-based feature
3. **Step 3**: Optimize duration threshold and distance
4. **Step 4**: Validate on out-of-sample period (2025 data)

### Phase 5: Verify Other Features (Priority: LOW)
**Once trailing is confirmed working:**

1. **Min Hold Time**: Does it actually prevent early exits?
2. **Dormant Mode**: Does it properly pause trading after drawdowns?
3. **Regime Detection**: Is it functioning? Does it improve results?
4. **ADX Filter**: If implemented, does it filter false signals?

## Testing Checklist

### Quick Verification Test (15 minutes)
Run 1-month backtest with enhanced logging:

```bash
# Edit .env to enable max logging
STRATEGY_TRAILING_ENABLED=true
STRATEGY_TRAILING_ACTIVATION_THRESHOLD_PIPS=5.0
STRATEGY_TRAILING_DISTANCE_PIPS=20.0

# Run short backtest
python backtest/run_backtest.py --start-date 2024-01-01 --end-date 2024-01-31 > test_trailing_fix.log 2>&1

# Check for trailing activity
Select-String -Path test_trailing_fix.log -Pattern "TRAILING|modifying stop"
```

**Success Criteria:**
- ✓ See log messages about stop modifications
- ✓ See positions with multiple stop orders in orders.csv
- ✓ PnL DIFFERENT from broken version (likely higher)
- ✓ Some positions closed by trailing stop (not just TP/initial SL)

### Full Validation Test (2 hours)
Run complete 22-month backtest with working trailing:

```bash
python backtest/run_backtest.py --start-date 2024-01-01 --end-date 2025-10-30
```

Compare with historical baseline ($9,517.35 PnL with broken trailing).

**Success Criteria:**
- ✓ PnL significantly different (expect 10-30% improvement if trailing works)
- ✓ Average win size increased
- ✓ Max favorable excursion captured better
- ✓ Trailing stop modifications logged for 50%+ of winning trades

## Next Steps Priority Order

1. **[IMMEDIATE]** Verify the fix works (Phase 1, Item 1-2)
2. **[TODAY]** Add comprehensive filter logging (Phase 2)
3. **[TODAY]** Run baseline comparison (Phase 3, Item 1)
4. **[WEEK]** Re-optimize trailing parameters (Phase 4)
5. **[WEEK]** Verify other features (Phase 5)

## Expected Timeline

- **Today (4 hours)**:
  - Verify trailing fix works ✓
  - Add filter logging ✓
  - Run 1-month validation test ✓
  
- **This Week (12 hours)**:
  - Run full 22-month comparison ✓
  - Re-optimize trailing parameters ✓
  - Document accurate performance metrics ✓
  
- **Next Week (8 hours)**:
  - Verify min hold time, dormant mode, regime detection
  - Final validation on out-of-sample data
  - Update optimization results with corrected data

## Risk Assessment

**High Risk**: Other features may also be broken but not discovered yet
- Mitigation: Systematic logging verification (Phase 2)
- Add unit tests for each filter

**Medium Risk**: New trailing code may have bugs
- Mitigation: Extensive testing with various parameter combinations
- Compare with manual calculation of expected trailing behavior

**Low Risk**: Re-optimization may not improve results
- Possible outcome: Static stops were already optimal
- Still valuable to know trailing doesn't help vs it being broken

## Questions for Consideration

1. **Should we halt live trading?**
   - If live trading uses trailing stops, they weren't working
   - But if live uses static stops, results may still be valid

2. **How much optimization work is invalidated?**
   - Anything related to trailing: 100% invalid
   - Entry signals, filters, TP levels: Still valid
   - Need to re-baseline everything

3. **Are there other broken features?**
   - Min hold time: Unknown
   - Dormant mode: Unknown
   - Regime detection: Unknown
   - Need systematic verification

## Success Metrics

### Short Term (Today)
- [ ] Trailing stop modifications appear in logs
- [ ] PnL changes when trailing parameters change
- [ ] Can trace one position with multiple stop updates

### Medium Term (This Week)
- [ ] Full backtest shows improved PnL vs broken version
- [ ] All filters verified with comprehensive logging
- [ ] Re-optimized trailing parameters documented

### Long Term (Next Week)
- [ ] All features verified working correctly
- [ ] Accurate performance metrics established
- [ ] Confidence in backtest validity restored
- [ ] Live trading alignment verified

---

**Author**: AI Assistant  
**Date**: November 16, 2025  
**Status**: Draft - Awaiting validation testing
