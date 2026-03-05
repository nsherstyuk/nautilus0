# Live ↔ Backtest Parity Plan
Created: 2026-02-20

## Goal
Establish a proven, auditable pipeline so we can answer:
  1. What signals did live generate today?  (direction, confidence, bar_time)
  2. What trades were actually filled?       (entry price, quantity, commission)
  3. How were trades closed?                 (TP / SL / manual, exit price, PnL)
  4. What is the account balance / session PnL right now?
  5. Do live signals / outcomes match backtest replays on the same bars?

---

## Phase 1 — Structured live trade journal  [PRIORITY: IMMEDIATE]

### What
Add `live/trade_journal.py` — an append-only CSV writer that the LIVE STRATEGY
calls at every significant event.

### File
`logs/live_mtf/trade_journal.csv`

### Columns (one row per event)
  event_type, timestamp_utc, bar_time, order_id, side,
  confidence, threshold, atr, close_px, mama_diff, dmi_plus, meta,
  entry_px, exit_px, sl_px, tp_px, quantity, commission,
  exit_reason, pnl_usd, duration_bars, account_nav

### Event types
  SIGNAL        — ML signal generated (bar_time, side, confidence, filters)
  CONFIRM_WAIT  — signal waiting for entry confirmation
  CONFIRM_FAIL  — confirmation window expired without fill
  ORDER_SUBMIT  — bracket order sent to IB Gateway (entry+SL+TP)
  ORDER_FILL    — entry fill confirmed (price, commission)
  POSITION_CLOSE— trade closed (exit_px, exit_reason, pnl_usd)
  CONFIRM_PASS  — entry confirmed, entry order submitted

### Implementation notes
- Thread-safe write using a lock (same pattern as live_bar_csv_logger.py).
- Called from strategy hooks: on_signal, on_order_filled, on_position_closed.
- Never throws — all writes inside try/except to avoid crashing the strategy.
- Header written once (skip if file already exists with correct header).

---

## Phase 2 — Account snapshot logging  [PRIORITY: IMMEDIATE]

### What
Every live 15-min bar, when minute==0 (i.e. top of hour), request IB account
summary and write it to:
  `logs/live_mtf/account_snapshots.csv`

### Columns
  timestamp_utc, net_liquidation, session_realized_pnl,
  session_unrealized_pnl, full_init_margin, cushion, open_trades

### Implementation notes
- Use ib_insync reqAccountSummary() or the existing portfolio() snapshot.
- Write to CSV append-only AND print a human-readable block to the strategy log.
- The live runner already has an ib object — pass it into the strategy or call
  from the runner's periodic health-check loop.

### Console format (printed to log hourly)
  ═══════════════════════════════════════════════
  ACCOUNT SNAPSHOT  2026-02-20 14:00 UTC
  Net Liquidation:   $3,946.28
  Session Realized:  -$12.50
  Unrealized:        +$8.20
  Open positions:    1 x EUR/USD LONG 50k @ 1.18340
  ═══════════════════════════════════════════════

---

## Phase 3 — Fix backtest double-bar timing shift  [PRIORITY: BEFORE NEXT COMPARISON]

### Problem
NautilusTrader BacktestEngine delivers each 15-min bar TWICE to on_bar()
because both the 15m and 1m data streams are present, and bar_execution=True
triggers on each data event. The second call processes the same OHLCV but
with slightly updated portfolio state.

Result: indicators are recalculated twice per bar, making the effective
indicator state ~1 bar ahead of the live system, which shifts signals by
~15 min. This is why all 11 live signals and 6 replay signals share zero
common bar_times.

### Fix
In `strategies/ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py`,
at the top of `on_bar()`, add a deduplication guard:

  if bar.ts_event == self._last_processed_bar_ts:
      return  # skip duplicate delivery
  self._last_processed_bar_ts = bar.ts_event

Initialize `self._last_processed_bar_ts = 0` in `__init__` or `on_start`.

This is safe in live (bars are unique per real tick) and fixes backtest parity.

### Test
After fix: re-run comparison for Feb 19-20. Signal bar_times in common should
jump from 0 to ~80%+.

---

## Phase 4 — Trade-level parity comparison  [AFTER PHASE 1+3 DONE]

### Script
`scripts/compare_live_vs_backtest_trades.py`

### Logic
Load `logs/live_mtf/trade_journal.csv` (live trades).
Load `backtest_results/<run>/trades_<ts>.csv` (backtest trades).

For each live POSITION_CLOSE event, find the nearest backtest trade by entry_time.
Report:
  - Signal match:  same bar_time ± 15 min, same direction?
  - Entry match:   |live_entry - bt_entry| in pips
  - SL/TP match:   |live_sl - bt_sl| in pips
  - Exit match:    same exit_reason (TP/SL)? |PnL difference|?
  - Missing in BT: live trade not found in backtest
  - Missing in LV: backtest trade not found in live

### Output
Console summary + `analysis_outputs/live_bt_trade_parity_<date>.csv`

---

## Phase 5 — IB execution log reader  [QUALITY-OF-LIFE]

### What
A stand-alone script `scripts/read_ib_executions.py` that connects to
IB Gateway, calls reqExecutions(), and prints/saves a clean table:

  time_utc | symbol | side | qty | fill_px | commission | order_ref

This is the authoritative IB-side record of every fill, independent of
what the strategy logged. Can be compared against trade_journal.csv to
confirm no fills were missed.

---

## Implementation Order

  [x] Write this plan file
  [ ] Phase 1: live/trade_journal.py  +  wire into strategy
  [ ] Phase 2: account snapshot in live runner health-check loop
  [ ] Phase 3: double-bar dedup guard in strategy on_bar()
  [ ] Phase 4: compare_live_vs_backtest_trades.py
  [ ] Phase 5: read_ib_executions.py

---

## Files to modify

  live/trade_journal.py                             (NEW)
  live/run_live_mtf_v2_entry_confirmed_adaptive_failsafe.py  (account snapshots)
  strategies/ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py
    — on_bar dedup guard (Phase 3)
    — call trade_journal on signal/fill/close (Phase 1)
  scripts/compare_live_vs_backtest_trades.py        (NEW)
  scripts/read_ib_executions.py                     (NEW)

---

## Success Criteria

  1. After each live session: trade_journal.csv has one clear row per event.
  2. account_snapshots.csv shows hourly NAV, nobody needs TWS to see balance.
  3. Live ↔ backtest comparison on same bars shows ≥ 85% signal agreement
     after the double-bar fix.
  4. For each live trade closed, a matching backtest trade exists within 1 bar.
