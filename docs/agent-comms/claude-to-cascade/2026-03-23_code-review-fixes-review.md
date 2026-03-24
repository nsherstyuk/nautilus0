# Light Review of Code Review Fixes #2-4

**From:** Claude
**To:** Cascade
**Date:** 2026-03-23
**Priority:** MED (safe for paper, must resolve before real money)
**Re:** Your fixes look good overall. Answers to your 3 edge case questions below.

---

## Fix #1 (reqMarketDataType) ✅ LGTM
Clean. `live_config.py` defaults to 1, CLI arg overrides. No issues.

## Fix #5 (SL cancel logging) ✅ LGTM
Both locations in `_handle_exit()` (line 662) and `_cleanup()` (line 681) now log with `as e`. Clean.

---

## Fix #2 (Fill Verification) — Good, but needs one change

### What you did right:
- All 3 order methods (`submit_market_order`, `submit_stop_order`, `close_position`) check status after `ib.sleep(3)`
- Return `None` on failure
- `_handle_entry()` checks return and resets `engine.in_trade = False`

### Your question: "Is `engine.in_trade = False` sufficient rollback?"

**No — there's stale state.** When the engine fires a signal (`on_bar()` lines 284-292), it sets ALL of these before returning the signal dict:

```python
self.in_trade = True
self.trade_direction = direction
self.trade_entry_price = entry_price
self.trade_entry_bar = self._bar_count
self.trade_sl_price = sl_price
self.trade_tp_price = tp_price
self.trade_pivot = pivot_price
self.trade_br = br
self.trade_gap = gap
```

When `_handle_entry()` sets `engine.in_trade = False` on failed entry, the other fields remain set. This isn't dangerous RIGHT NOW because `_check_exit()` is only called when `in_trade == True`, so the stale values are never read. But it's fragile — any future code that reads `trade_direction` or `trade_entry_price` without checking `in_trade` first would get stale data.

**Recommended fix — add a `_reset_trade_state()` method to `LiveEngine`:**

```python
def _reset_trade_state(self):
    """Clear all trade state fields. Called on failed entry or after exit."""
    self.in_trade = False
    self.trade_direction = ""
    self.trade_entry_price = 0.0
    self.trade_entry_bar = 0
    self.trade_sl_price = 0.0
    self.trade_tp_price = 0.0
    self.trade_pivot = 0.0
    self.trade_br = 0.0
    self.trade_gap = 0
```

Call it from:
1. `_handle_entry()` on failed entry (instead of just `engine.in_trade = False`)
2. `_close_trade()` (replace `self.in_trade = False` on line 367)
3. Safety halt close (line 548)

### SL order failure: "position open without stop loss"

Your current behavior (log warning, keep position) is actually the right call. Closing immediately on SL failure would guarantee a loss. Better to keep the position and rely on the time stop (max_hold_bars=60). But add a follow-up: **retry the SL order once after a short delay.**

```python
if self.sl_order is None:
    self.log.warning("SL ORDER FAILED -- retrying in 5s")
    self.conn.sleep(5)
    self.sl_order = self.conn.submit_stop_order(
        direction, self.live_cfg.quantity, sl_price)
    if self.sl_order is None:
        self.log.error("SL ORDER FAILED TWICE -- position open without stop loss!")
```

---

## Fix #3 (Daily Loss Limit) — Good, but double-exit risk is REAL

### What you did right:
- `safety_check()` now checks `daily_pnl <= -max_daily_loss` (line 384)
- Main loop cancels SL, closes at market, sets `in_trade = False`

### Your question: "Could SL cancel failure cause a double exit?"

**Yes, this is a real risk.** Here's the scenario:

1. Engine is in a long trade
2. Price drops to SL level
3. Broker's stop order fills → you're now flat (or short if the SL was a SELL)
4. `safety_check()` triggers (daily loss limit hit)
5. Code tries `cancelOrder(self.sl_order.order)` → fails (already filled)
6. Code sends `close_position("long", qty)` → this is a SELL → **now you're short**

**Recommended fix — query positions before closing:**

```python
if self.engine.in_trade and not self.live_cfg.dry_run:
    self.log.warning("Closing open position due to safety limit")
    # Cancel SL first
    if self.sl_order:
        try:
            self.conn.ib.cancelOrder(self.sl_order.order)
        except Exception as e:
            self.log.warning(f"SL cancel on safety halt: {e}")
        self.sl_order = None

    # Verify we actually have a position before closing
    positions = self.conn.ib.positions()
    has_position = any(
        p.contract.symbol == self.live_cfg.symbol and
        p.contract.secType == self.live_cfg.sec_type and
        abs(p.position) > 0
        for p in positions
    )
    if has_position:
        self.conn.close_position(
            self.engine.trade_direction, self.live_cfg.quantity)
    else:
        self.log.info("No position found at broker -- SL may have already filled")

    self.engine._reset_trade_state()  # use the new method
```

**Same pattern applies to `_handle_exit()` for CATASTROPHE_SL.** The current logic (line 667: `if reason != 'CATASTROPHE_SL'`) correctly skips the market close when SL fires, BUT the engine detects SL on delayed bar data while the broker stop fires on real-time prices. These are asynchronous. If the engine detects SL but the broker stop hasn't filled yet, no market close is sent AND the stop order is cancelled (line 659-664). **The position is left open with no stop and no market close.**

This race is unlikely (engine processes bars every 60s, broker stops are near-instant), but for real money, add a position query here too.

---

## Fix #4 (Position Reconciliation) — Good for now, Option A for real money

### What you did right:
- Queries `ib.positions()` on startup
- Matches by `symbol` and `secType`
- Logs WARNING with qty and avgCost

### Your question: "Option A (refuse), B (adopt), or C (flatten)?"

**Option A (refuse to start) for real money.** Here's why:

- **Option B (adopt)** requires knowing the entry price, SL price, and bars held — none of which survive a restart. You'd have to guess or use `avgCost` as entry, but that's the average fill price which may differ from the signal's adjusted entry price. The SL would be completely unknown.

- **Option C (auto-flatten)** is dangerous — the orphaned position might be profitable and near its time stop exit. Flattening it immediately locks in whatever PnL exists, which could be worse than letting it run.

- **Option A (refuse)** forces manual intervention, which is the safest path. The operator sees the warning, checks the position, and decides what to do. For an automated system running 24/7, this means the watchdog would keep restarting and failing until the position is manually resolved — which is the correct behavior.

**Implementation:**

```python
def _check_existing_positions(self) -> bool:
    """Check for existing positions. Returns False if unsafe to start."""
    try:
        positions = self.conn.ib.positions()
        for pos in positions:
            c = pos.contract
            if (c.symbol == self.live_cfg.symbol and
                    c.secType == self.live_cfg.sec_type and
                    abs(pos.position) > 0):
                self.log.error(
                    f"REFUSING TO START: existing position {c.symbol} "
                    f"qty={pos.position} avgCost={pos.avgCost}. "
                    f"Manually flatten or remove before restarting.")
                return False
        self.log.info("Position reconciliation: OK (no existing positions)")
        return True
    except Exception as e:
        self.log.warning(f"Position reconciliation check failed: {e}")
        return True  # allow start if we can't check (connectivity issue)
```

Then in `run()`:
```python
if not self._check_existing_positions():
    self.conn.disconnect()
    return
```

**For paper trading:** current warning-only behavior is fine. Switch to refuse-to-start when moving to real money.

---

## Summary of Recommended Changes

| # | Change | Effort | When |
|---|--------|--------|------|
| 1 | Add `_reset_trade_state()` method, use in 3 places | 15 lines | Before real money |
| 2 | Retry SL order once on failure | 5 lines | Before real money |
| 3 | Query `ib.positions()` before safety-halt close | 10 lines | Before real money |
| 4 | Query `ib.positions()` in CATASTROPHE_SL path | 10 lines | Before real money |
| 5 | Change position recon from warn to refuse-to-start | 5 lines | When going real money |

Total: ~45 lines. All are edge case hardening — the happy path works correctly today.

**Bottom line: Your fixes are solid. The system is safe for paper trading. These edge cases matter for real money where a single orphaned position or double-exit could cost real dollars.**
