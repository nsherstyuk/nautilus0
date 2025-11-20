# Trailing Stop Issue Analysis

## Problem Identified

After reviewing the codebase and documentation, I found the **critical issue** preventing trailing stops from working:

### Root Cause

**After `modify_order()` is called, NautilusTrader cancels the old order and creates a NEW order with a different ID. However, the strategy keeps a reference to the OLD (cancelled) order.**

### Current Code Flow (BROKEN)

1. **Line 1267**: `self._current_stop_order = current_stop_order` - Sets reference to stop order
2. **Line 1506**: `self.modify_order(...)` - Modifies the order
3. **Line 1509**: `self._last_stop_price = new_stop_rounded` - Updates stop price
4. **BUT**: `self._current_stop_order` is **NOT cleared** - still points to old order
5. **Next bar**: Code tries to re-discover order (lines 1224-1264), but:
   - Old order reference might still be in cache (stale)
   - New order might not be found immediately
   - Code might pick wrong order or fail to find any

### Why This Breaks Trailing

- On the next bar, when `_update_trailing_stop()` is called:
  - It tries to find the stop order again
  - But `self._current_stop_order` still points to the OLD cancelled order
  - The order discovery logic might find the old order first (if still in cache)
  - Or fail to find the new order (timing issue)
  - Result: Trailing stops stop working after first modification

### Evidence from Documentation

From `TRAILING_STOP_FIX_ACTION_PLAN.md`:
> **Root cause: Stale order reference (`self._current_stop_order`)**
> - When NautilusTrader modifies orders, it creates NEW orders with different IDs
> - Strategy held reference to OLD (cancelled) order → early return on every bar
> - Result: Every position used **static stop loss only** (no trailing)

## Solution

### Fix Required

**After calling `modify_order()`, clear `self._current_stop_order` so it will be re-discovered on the next bar:**

```python
# After line 1506 (modify_order call):
self.modify_order(self._current_stop_order, trigger_price=Price.from_str(str(new_stop_rounded)))

# ADD THIS:
self._current_stop_order = None  # Clear reference - will be re-discovered next bar
self._last_stop_price = new_stop_rounded
```

### Why This Works

1. **Clear stale reference**: Setting `self._current_stop_order = None` ensures we don't use the old cancelled order
2. **Re-discovery on next bar**: The order discovery logic (lines 1224-1264) will find the NEW order created by `modify_order()`
3. **Maintain state**: `self._last_stop_price` is still updated, so trailing logic continues to work

### Additional Improvements

1. **Add order update callback**: Listen for order update events to immediately update the reference
2. **Better order matching**: Use order tags + position ID to ensure we find the correct order
3. **Validation**: After modify_order(), verify the new order exists before continuing

## Testing

After applying the fix:

1. **Run short backtest** (1 month)
2. **Check logs** for:
   - Multiple "MODIFYING ORDER" messages
   - Order IDs changing after modifications
   - Trailing stops continuing to work after first modification
3. **Verify** positions have multiple stop order updates
4. **Compare PnL** - should be different from broken version

## Files to Modify

- `strategies/moving_average_crossover.py` - Line ~1506-1510

