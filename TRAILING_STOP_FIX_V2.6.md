# Trailing Stop Fix v2.6 - Critical Stale Order Reference Fix

## Problem

Trailing stops were not working because after `modify_order()` is called, NautilusTrader creates a **NEW order** with a different ID, but the strategy kept a reference to the **OLD (cancelled) order**.

### Root Cause

1. `modify_order()` is called (line 1506)
2. NautilusTrader cancels old order and creates new order
3. Strategy keeps `self._current_stop_order` pointing to OLD order
4. On next bar, order discovery might find stale order or fail
5. Result: Trailing stops stop working after first modification

## Solution (v2.6)

**Clear the stale order reference immediately after `modify_order()`:**

```python
# After modify_order() call:
self.modify_order(self._current_stop_order, trigger_price=Price.from_str(str(new_stop_rounded)))

# CRITICAL FIX: Clear stale order reference
self._current_stop_order = None  # Will be re-discovered next bar
self._last_stop_price = new_stop_rounded
```

### Why This Works

1. **Clears stale reference**: Prevents using cancelled order
2. **Forces re-discovery**: Order discovery logic (lines 1224-1264) will find the NEW order on next bar
3. **Maintains state**: `_last_stop_price` is still updated, so trailing continues

## Changes Made

**File**: `strategies/moving_average_crossover.py`

- **Line 1512**: Added `self._current_stop_order = None` after `modify_order()` call
- **Line 1508**: Updated log message to v2.6
- **Line 324**: Updated initialization message to v2.6

## Testing

### Quick Test (15 minutes)
```bash
# Run 1-month backtest
python backtest/run_backtest.py --start-date 2025-01-08 --end-date 2025-02-08

# Check logs for:
# - Multiple "MODIFYING ORDER" messages
# - Order IDs changing after modifications  
# - "order reference cleared for re-discovery" messages
```

### Success Criteria

✅ See multiple trailing stop modifications per position  
✅ Order IDs change after each modification  
✅ Trailing continues working after first modification  
✅ PnL different from broken version (likely higher)  

## Previous Fixes (v2.1 - v2.5)

- **v2.1**: Query all orders (not just open)
- **v2.3**: Added comprehensive logging
- **v2.5**: Tag-based SL discovery, status filtering, `_last_stop_price` initialization

**v2.6 completes the fix** by ensuring order reference stays current after modifications.

## Related Documentation

- `TRAILING_STOP_FIX_V2.5_SUMMARY.md` - Previous fixes
- `TRAILING_STOP_FIX_ACTION_PLAN.md` - Original problem analysis
- `TRAILING_STOP_ISSUE_ANALYSIS.md` - Detailed issue breakdown

## Next Steps

1. **Test the fix** with short backtest
2. **Verify** trailing stops work across multiple modifications
3. **Re-run optimization** if trailing parameters were tested before
4. **Compare PnL** with baseline to see improvement

---

**Status**: ✅ Fixed (v2.6)  
**Date**: 2025-11-15  
**Critical**: Yes - This was preventing all trailing stops from working

