# Development Guidelines: Preserving Working Code

## How the Regression Happened

### Evolution of Position Tracking

**Classic V2 (working)** → **Entry Confirmed** → **Fail-Safe (broken)** → **Fail-Safe (fixed)**

1. **Classic V2** had dual-check + auto-reset (lines 960-978)
2. **Entry Confirmed** simplified to cache-only check (lost auto-reset)
3. **Fail-Safe** removed cache entirely (lost both checks)
4. **Fail-Safe Fixed** restored Classic V2's dual-check + auto-reset

**Lesson:** Each modification removed proven working logic without understanding why it existed.

---

## Code Hierarchy (Source of Truth)

```
Classic V2 (ml_strategy_mtf_v2.py)
    ↓ (proven working implementation)
    ↓
Entry Confirmed (ml_strategy_mtf_v2_entry_confirmed.py)
    = Classic V2 + entry confirmation logic
    ↓
Fail-Safe (ml_strategy_mtf_v2_entry_confirmed_failsafe.py)
    = Entry Confirmed + fail-safe protection
```

**Rule:** Each level must PRESERVE all logic from previous levels.

---

## Critical Code Patterns (Never Change These)

### 1. Position Tracking (Classic V2 lines 960-978)

**Always use dual-check + auto-reset:**

```python
# Check BOTH internal state AND cache
has_internal = len(self.active_positions) > 0
positions = list(self.cache.positions_open(instrument_id=self.instrument_id))
orders = list(self.cache.orders_open(instrument_id=self.instrument_id))

# Auto-reset if mismatch
if not positions and not orders and has_internal:
    _py_logger.warning("[AUTO-RESET] Stale state - clearing")
    self.active_positions.clear()
    # Continue to trading
elif positions or orders or has_internal:
    return  # Skip new signals
```

**Why:** Prevents getting stuck with stale position state.

### 2. Bracket Order Submission

**Always use atomic submission:**

```python
# Track IDs
for order in bracket.orders:
    if isinstance(order, MarketOrder):
        entry_order_id = order.client_order_id
    elif isinstance(order, StopMarketOrder):
        sl_order_id = order.client_order_id
    elif isinstance(order, LimitOrder):
        tp_order_id = order.client_order_id

# Submit atomically
self.submit_order_list(bracket)

# Verify
open_orders = list(self.cache.orders_open(...))
_py_logger.info(f"[VERIFICATION] {len(open_orders)} orders")
```

**Why:** Ensures SL/TP are linked to entry order.

---

## How to Request Changes (Templates)

### Template 1: Adding New Feature

**Bad Request:**
> "Add feature X to the strategy"

**Good Request:**
> "Add feature X to the fail-safe strategy. First show me how Classic V2 handles [related functionality]. Then add feature X while preserving all existing logic from Classic V2, especially position tracking (lines 960-978) and bracket order submission."

### Template 2: Fixing Bug

**Bad Request:**
> "Fix the position tracking bug"

**Good Request:**
> "Fix the position tracking bug. First show me how Classic V2 handles position tracking (ml_strategy_mtf_v2.py lines 960-978). Then apply the same approach to fail-safe without changing any other functionality."

### Template 3: Modifying Existing Feature

**Bad Request:**
> "Change the entry confirmation logic"

**Good Request:**
> "Modify the entry confirmation logic to [specific change]. Only modify code in the _check_entry_confirmation method. Do not change position tracking, order submission, or fail-safe protection logic."

---

## Key Phrases to Use

### Preservation Phrases
- ✅ "Preserve all working logic from Classic V2"
- ✅ "Only modify code related to [specific feature]"
- ✅ "Do not change [specific functionality]"
- ✅ "Base on [file] but add [feature] without removing existing logic"

### Verification Phrases
- ✅ "First show me how Classic V2 does this"
- ✅ "Compare with Classic V2 implementation"
- ✅ "Verify that [existing functionality] still works"

### Scope Limiting Phrases
- ✅ "Only modify the [specific method/section]"
- ✅ "Add new methods without changing existing ones"
- ✅ "Implement as a separate module/class"

---

## Development Workflow (3-Step Process)

### Step 1: Reference Check
**Before implementing anything:**
```
You: "Show me how Classic V2 handles [related functionality]"
AI: Shows exact code from ml_strategy_mtf_v2.py
```

### Step 2: Scoped Implementation
**During implementation:**
```
You: "Now add [feature] while preserving that exact logic"
AI: Implements with explicit preservation
```

### Step 3: Regression Verification
**After implementation:**
```
You: "Verify that [existing functionality] still works the same way"
AI: Confirms no changes to unrelated code
```

---

## Common Mistakes to Avoid

### ❌ Mistake 1: Assuming "Better" Without Verification
**Wrong:** "The cache is unreliable, let's remove it"
**Right:** "The cache has issues. How does Classic V2 handle this? Let's use that approach."

### ❌ Mistake 2: Rewriting Instead of Adding
**Wrong:** "Replace the position check with a new implementation"
**Right:** "Add fail-safe checks while keeping Classic V2's position tracking logic"

### ❌ Mistake 3: Not Checking Existing Solutions
**Wrong:** "Implement position tracking from scratch"
**Right:** "Show me Classic V2's position tracking, then apply the same pattern"

### ❌ Mistake 4: Vague Scope
**Wrong:** "Improve the strategy"
**Right:** "Add [specific feature] to [specific method] without changing [specific existing logic]"

---

## File Reference Guide

### Classic V2 (Source of Truth)
**File:** `strategies/ml_strategy_mtf_v2.py`

**Key sections:**
- Position tracking: lines 960-978
- Order submission: lines 1100-1200 (approximate)
- Layer management: throughout

### Entry Confirmed
**File:** `strategies/ml_strategy_mtf_v2_entry_confirmed.py`

**Additions to Classic V2:**
- Entry confirmation logic: _check_entry_confirmation method
- 1m bar subscription and handling
- Pending signal tracking

**Must preserve from Classic V2:**
- Position tracking with dual-check + auto-reset
- Bracket order submission
- Risk management

### Fail-Safe
**File:** `strategies/ml_strategy_mtf_v2_entry_confirmed_failsafe.py`

**Additions to Entry Confirmed:**
- Fail-safe protection: _is_position_protected, _check_position_protection
- Grace period tracking
- Emergency flatten logic

**Must preserve from Classic V2 + Entry Confirmed:**
- Position tracking with dual-check + auto-reset (NOW FIXED)
- Bracket order submission
- Entry confirmation logic
- Risk management

---

## Quick Checklist Before Requesting Changes

Before asking for any modification, ask yourself:

- [ ] Do I know which file is the source of truth for this functionality?
- [ ] Have I asked to see how Classic V2 handles this?
- [ ] Have I specified which code should NOT be changed?
- [ ] Have I limited the scope to specific methods/sections?
- [ ] Have I asked for verification that existing features still work?

If you answered "No" to any of these, refine your request using the templates above.

---

## Emergency Recovery

**If you notice a regression (something that worked before is now broken):**

1. **Stop immediately** - Don't make more changes
2. **Identify what broke** - Compare with Classic V2
3. **Request restoration** - "Restore [functionality] to match Classic V2 implementation at [file:lines]"
4. **Verify fix** - Check that both old and new features work

---

## Summary

**Golden Rule:** When in doubt, check Classic V2 first.

**Development Mantra:** Add, don't replace. Preserve, don't rewrite.

**Request Format:** Reference → Scope → Preserve → Verify
