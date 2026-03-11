# Velocity Gate Critical Fixes — 2026-03-11

After reviewing the Option A (pre-fill monitoring) implementation, identified and fixed 6 critical issues before dry-run data collection.

---

## Fixes Implemented

### 1. Post-Fill Safety Check (Race Condition Protection)
**Problem:** Fill could happen during the milliseconds between velocity dropping and us cancelling orders.

**Fix:** Added velocity check immediately after `_check_fills()` returns true:
- If velocity < threshold → close immediately, log as `FILL_REJECT_RACE`
- If velocity OK → accept fill normally
- Location: `orb_multi_live.py` lines 753-784

**Impact:** Prevents entering trades during dead markets due to race conditions.

---

### 2. Faster Polling (2 seconds vs 10 seconds)
**Problem:** With 10-second polling, market could go dead for 10 seconds before we detect it and pull orders.

**Fix:** Changed `poll_interval` from 10 → 2 seconds in `config.yaml`

**Impact:** Reduces maximum detection lag from 10s to 2s. Tighter velocity monitoring.

---

### 3. Dry-Run Velocity Gate Enforcement
**Problem:** Dry-run accepted all fills regardless of velocity, making it a poor simulation of live behavior.

**Fix:** Dry-run now applies same velocity gate as live:
- If fill + velocity < threshold → reject and close (log as `DRY_REJECT`)
- If fill + velocity OK → accept (log as `DRY_OK`)
- Location: `orb_multi_live.py` lines 786-813

**Impact:** Dry-run now accurately simulates live velocity filtering.

---

### 4. Wednesday Skip Moved Earlier
**Problem:** Wednesday skip happened AFTER velocity checks and potentially after orders were placed, wasting API calls.

**Fix:** Moved weekday skip to startup logic (lines 1655-1663), before any state machine logic runs.

**Impact:** Wednesday is marked `DONE_TODAY` immediately on startup. No wasted checks.

---

### 5. Orders Placed Time Reset
**Problem:** If velocity fluctuates (place → pull → re-place), `max_pending_hours` timer would use the FIRST placement time, not the most recent.

**Fix:** Already correctly resetting `orders_placed_time = None` when reverting to `RANGE_COMPUTED` after velocity drop (line 748). Added clarifying comment.

**Impact:** Timer resets on each re-placement, preventing premature timeout cancellations.

---

### 6. NO LIVE TRADING YET (Critical Warning)
**Not a code fix, but a procedural requirement:**

The velocity threshold of 168 ticks/min comes from **Dukascopy data**. IBKR's tick feed may be completely different (could be 50, could be 400).

**MUST DO BEFORE LIVE:**
1. Run dry-run for 3-5 days
2. Collect `logs/velocity_xauusd.csv`
3. Analyze IBKR's actual tick rate at 08:00 UTC
4. Calibrate threshold in `config.yaml`
5. THEN run paper trading
6. THEN consider live

Running live with uncalibrated threshold = flying blind.

---

## Code Status

- ✅ All fixes implemented
- ✅ Code compiles successfully
- ✅ Ready for dry-run data collection

## Next Steps

1. Start dry-run: `python -m v5_xauusd_orb.orb_multi_live --dry-run`
2. Let run for 3-5 days
3. Analyze `logs/velocity_xauusd.csv`
4. Calibrate threshold
5. Paper trade for 1-2 weeks
6. Go live

## Files Changed

- `v5_xauusd_orb/orb_multi_live.py` (6 edits)
- `v5_xauusd_orb/config.yaml` (poll_interval: 10→2)
