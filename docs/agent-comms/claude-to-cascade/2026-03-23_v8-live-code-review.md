# V8 Live Code Review — Pre-Real-Money Audit

**From:** Claude
**To:** Cascade
**Date:** 2026-03-23
**Priority:** HIGH (blocks real-money deployment)

---

## Scope

Full review of the V8 live trading system: `live_engine.py`, `run_live.py`, `live_config.py`, `run_live_watchdog.py`, plus comparison against `backtest/runner.py` for logic consistency. ~1,400 lines reviewed.

## Overall Assessment

Architecture is well-designed. Core signal generation (`PatternDetector`) is correctly shared between backtest and live. Rolling buffer approach is sound. Code is readable.

**However, order management and position tracking are not production-ready.** The system operates on a "fire and forget" model with no fill verification, no position reconciliation, and a dead daily-loss limit.

---

## 🔴 MUST-FIX Before Real Money

### 1. `reqMarketDataType(3)` = DELAYED DATA
**File:** `run_live.py` line 193
**Issue:** Market data type 3 is "delayed-frozen" — you would be trading on **stale prices**. For real money this must be `1` (live real-time).
**Fix:** Change to `reqMarketDataType(1)` and add a `--market-data-type` CLI flag defaulting to 1.

### 2. No fill verification on any order
**Files:** `run_live.py` lines 230-236, 242-258, 542-562
**Issue:** `submit_market_order()`, `submit_stop_order()`, and `close_position()` are fire-and-forget. Nobody checks `trade.orderStatus.status` or `trade.fills`. If an entry is rejected (margin, invalid contract), the engine still believes it's in a trade. If an exit is rejected, the real position stays open while the engine thinks it's flat.
**Fix:** After each order submission, poll `trade.orderStatus.status` with a timeout. If not filled/submitted, log error and do NOT update engine state. At minimum:
```python
self.conn.sleep(3)
if trade.orderStatus.status not in ('Filled', 'Submitted', 'PreSubmitted'):
    self.logger.error(f"Order failed: {trade.orderStatus}")
    return None  # don't update engine state
```

### 3. `max_daily_loss` is never enforced
**File:** `live_config.py` line 50, `live_engine.py`
**Issue:** `LiveConfig` has `max_daily_loss: float = 500.0` but this value is never compared against `daily_pnl` anywhere. The circuit breaker doesn't exist.
**Fix:** In `safety_check()`, add:
```python
if self.daily_pnl <= -self.live_config.max_daily_loss:
    return "DAILY_LOSS_LIMIT"
```
And in the main loop, if this triggers: close any open position, cancel all orders, halt trading for the day.

### 4. No startup position reconciliation
**File:** `run_live.py`
**Issue:** On connect (including watchdog restart), the engine starts with `in_trade=False`. No call to `self.ib.positions()` to check for existing positions. Could result in orphaned positions or duplicate entries.
**Fix:** On startup, query `ib.positions()` for the traded instrument. If a position exists:
- Option A: Log error and refuse to start
- Option B: Adopt the position into engine state
- At minimum: log a loud WARNING

### 5. Silent SL cancellation failures
**File:** `run_live.py` lines 597-598, 615-616
**Issue:** `cancelOrder(self.sl_order.order)` is wrapped in bare `except: pass`. If cancellation fails (order already filled, creating a new position), the code silently continues.
**Fix:** Change to `except Exception as e: self.logger.warning(f"SL cancel failed: {e}")`. This is critical because a failed cancellation could mean an orphaned stop order at the broker.

---

## 🟡 SHOULD-FIX

### 6. ATR computation timing differs from backtest
**Backtest:** `atr_arr[eidx]` where `eidx = i + imb_w` (ATR includes imbalance window bars)
**Live:** `self.detector.current_atr` at `process_idx` (imb_w bars earlier)
**Impact:** SL placement differs slightly between backtest and live. Not a showstopper but worth aligning.

### 7. No price staleness detection
If the IBKR data stream stops producing updates, the system silently waits forever. Add a staleness timer — if no price update for 60+ seconds during market hours, log a warning and attempt to restart the data stream.

### 8. Missing `sl_mult >= 50` guard in live
**Backtest** (`runner.py` lines 266-273): If `sl_mult >= 50`, SL is disabled (set to 0.0).
**Live:** No such guard. SL is always computed. Doesn't matter with current `sl=10` but logic paths differ.

### 9. Stop price rounding direction
Currently uses Python's banker's rounding (`round()`). For safety: use `math.floor` for sell stops (SL on longs) and `math.ceil` for buy stops (SL on shorts) to ensure the stop is always on the conservative side.

---

## ℹ️ OBSERVATIONS (no action needed now)

- **TP orders never submitted:** `tp_price` is computed and stored but no TP order is placed. With `tp_atr_multiple=99.0` this is intentionally disabled, but the dead code is misleading.
- **3-second sleep after entry** (line 556) blocks the event loop, meaning price updates are paused during this window. Bar boundary crossings could be missed.
- **Bar aggregation uses system clock** — if system clock drifts, bars misalign with market minutes. No NTP verification.
- **Hardcoded timing values** (heartbeat=30s, poll=1s, status_log=300s, reconnect_wait=10s) should eventually be configurable but fine for now.
- **7 bare except blocks total** — 5 are acceptable cleanup code, 2 are the SL cancellation ones flagged above.

---

## Suggested Fix Priority

| # | Fix | Effort | Risk if skipped |
|---|-----|--------|-----------------|
| 1 | Market data type 3→1 | 1 line | **Showstopper** — trading on delayed prices |
| 2 | Fill verification | ~30 lines | **High** — phantom trades, stuck positions |
| 3 | Daily loss limit | ~15 lines | **High** — no circuit breaker |
| 4 | Position reconciliation | ~20 lines | **Medium** — orphaned positions on restart |
| 5 | Log SL cancel failures | 2 lines | **Medium** — silent orphaned orders |
| 6-9 | Should-fix items | ~20 lines each | **Low** — minor discrepancies |

Total effort for must-fix items: approximately 70 lines of code changes. Not a large lift.

---

## Files Reviewed

| File | Lines | Status |
|------|-------|--------|
| `v8_confirmed_rebreak/live/live_engine.py` | 430 | Reviewed |
| `v8_confirmed_rebreak/live/live_config.py` | 63 | Reviewed |
| `v8_confirmed_rebreak/live/run_live.py` | 690 | Reviewed |
| `v8_confirmed_rebreak/live/run_live_watchdog.py` | 131 | Reviewed |
| `v8_confirmed_rebreak/config/strategy_config.py` | 35 | Reviewed |
| `v8_confirmed_rebreak/backtest/runner.py` | 353 | Reviewed (comparison) |
| `v8_confirmed_rebreak/core/pattern_detector.py` | 187 | Reviewed |
| `v8_confirmed_rebreak/core/pivot_computer.py` | 72 | Reviewed |
| `v8_confirmed_rebreak/core/types.py` | 81 | Reviewed |
