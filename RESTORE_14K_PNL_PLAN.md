# Plan to Restore 14k PnL Configuration

## What We Found

### ✅ Actual 14k Backtest Results
- **Folder**: `logs/backtest_results/EUR-USD_20251103_201335_664541` (and 25+ identical folders)
- **Exact PnL**: $14,203.91
- **Win Rate**: 60%
- **Trade Count**: 85
- **Date Range**: 2025-01-08 to 2025-10-03 (actual trades)
- **Optimization Run ID**: 28

### ✅ Exact Parameters (from optimization CSV run_id: 28)
```
fast_period: 42
slow_period: 270
crossover_threshold_pips: 0.35
stop_loss_pips: 35
take_profit_pips: 50
trailing_stop_activation_pips: 22
trailing_stop_distance_pips: 12
dmi_enabled: true
dmi_period: 10
stoch_enabled: true
stoch_period_k: 18
stoch_period_d: 3
stoch_bullish_threshold: 30
stoch_bearish_threshold: 65
trend_filter_enabled: false
entry_timing_enabled: false
```

### ⚠️ Critical Discovery: Date Range Mismatch
- **Optimization config**: Likely used 2025-01-01 to 2025-10-30
- **Actual trades**: Started 2025-01-08 (warmup period for 270-period MA)
- **Your current .env**: Uses 2024-01-01 to 2024-12-31

**This is a MAJOR difference!** The 14k result was achieved on **2025 data**, not 2024 data.

## Code Changes Since 14k Was Achieved

### 🔴 Critical Changes (May Affect Results)

1. **Crossover Persistence Bug Fix**
   - **What changed**: Fixed `prev_fast`/`prev_slow` update logic
   - **Impact**: HIGH - Changes when crossovers are detected
   - **When**: After 14k was achieved
   - **Effect**: May change trade timing/signals

2. **Time Filter Timestamp Fix**
   - **What changed**: Fixed bar timestamp rounding for time filter
   - **Impact**: MEDIUM - Only affects if time filter was enabled
   - **When**: After 14k was achieved
   - **Effect**: Time filter was DISABLED in 14k config, so this shouldn't matter

3. **Regime Detection Implementation**
   - **What changed**: Added regime detection feature
   - **Impact**: LOW - Was disabled in 14k config
   - **When**: After 14k was achieved
   - **Effect**: None if disabled

### 🟢 Non-Critical Changes
- Statistical analysis report fixes
- Various logging improvements
- Documentation updates

## The Problem

Even with the **exact same configuration**, you may not reproduce 14k PnL because:

1. **Code changes**: The crossover bug fix changes signal detection logic
2. **Date range**: 14k was on 2025 data, you're testing on 2024 data
3. **Data differences**: Market conditions may differ between periods

## Restoration Options

### Option 1: Use Exact Config + Current Code (Recommended First Step)
**Steps:**
1. Use `.env.14k_exact` (already created)
2. Update date range to match: `BACKTEST_START_DATE=2025-01-01`, `BACKTEST_END_DATE=2025-10-30`
3. Run backtest
4. Compare results

**Expected Outcome:**
- May get similar PnL if code changes don't affect this config
- May get different PnL due to crossover bug fix

### Option 2: Revert Code Changes (If Git Available)
**Steps:**
1. Find git commit from before crossover bug fix (around Nov 3-4, 2025)
2. Checkout that commit
3. Use exact 14k config
4. Run backtest
5. Verify 14k PnL

**Expected Outcome:**
- Should reproduce 14k exactly if code is reverted

### Option 3: Re-Run Optimization (Most Reliable)
**Steps:**
1. Use current code (with bug fixes)
2. Re-run optimization with same parameter grid
3. Find new optimal configuration
4. May find better or worse results

**Expected Outcome:**
- Finds optimal config for CURRENT code state
- May not reproduce 14k if bug fix changed behavior significantly

## Recommended Action Plan

### Phase 1: Test Current Code with Exact Config (30 min)
1. ✅ Copy `.env.14k_exact` to `.env`
2. ✅ Update date range to 2025-01-01 to 2025-10-30
3. ✅ Run backtest
4. ✅ Compare results:
   - If PnL ≈ $14,203 → Success! Code changes didn't break it
   - If PnL differs → Proceed to Phase 2

### Phase 2: Analyze Differences (1 hour)
1. Compare trade-by-trade:
   - Same number of trades?
   - Same entry/exit times?
   - Same PnL per trade?
2. Identify what changed:
   - Code changes?
   - Data differences?
   - Configuration differences?

### Phase 3: Decision Point
**If PnL is close (±$500):**
- Accept current code state
- Use current optimal config
- Document the difference

**If PnL is very different (>$2000 difference):**
- Option A: Revert code if git available
- Option B: Re-run optimization with current code
- Option C: Investigate specific code changes

## Files Created

1. **`.env.14k_exact`** - Exact configuration from run_id: 28
2. **`RESTORE_14K_PNL_PLAN.md`** - This document
3. **`find_14k_backtest.py`** - Script to find 14k results
4. **`reconstruct_14k_env.py`** - Script to recreate exact config

## Next Steps

1. **Test with exact config:**
   ```bash
   copy .env.14k_exact .env
   # Edit .env: Change dates to 2025-01-01 to 2025-10-30
   python backtest/run_backtest.py
   ```

2. **Compare results:**
   - Check if PnL matches
   - Analyze differences if not

3. **Decide:**
   - Accept current state?
   - Revert code?
   - Re-optimize?

## Critical Questions to Answer

1. **Do you have git history?** → Makes code reversion possible
2. **When was crossover bug fix?** → Determines if it affected 14k
3. **Can you use 2025 data?** → 14k was achieved on 2025 data, not 2024
4. **Is exact reproduction required?** → Or is "close enough" acceptable?

## Summary

**The Good News:**
- ✅ Found exact 14k configuration
- ✅ Found actual backtest results
- ✅ Created exact .env file

**The Challenge:**
- ⚠️ Code has changed since 14k was achieved
- ⚠️ Date range mismatch (2025 vs 2024)
- ⚠️ May not reproduce exactly with current code

**The Solution:**
- Test current code first
- If different, decide: revert code or re-optimize
- Document findings for future reference


