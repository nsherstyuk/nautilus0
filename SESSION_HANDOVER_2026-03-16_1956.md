# Session Handover — 2026-03-16 19:56 EDT

## Session Focus
V5 ORB orphaned position incident investigation and architectural fix.

---

## 1. Incident: Orphaned LONG Position at IBKR

### What happened
On 2026-03-16 at 05:05 UTC, V5 ORB entered a SHORT at 4981.96 on XAUUSD (London open breakout). Two seconds later, the script falsely declared "Position vanished" due to IBKR `ib.positions()` cache lag. The script logged the trade as CLOSED and went to sleep — but **did not cancel the SL/TP bracket orders** still active at IBKR.

Hours later, gold rallied to ~5030.88. The orphaned BUY STP orders (SL from the SHORT bracket + likely a stale BUY entry from a previous velocity cycle) triggered, creating an **unmanaged LONG position at 5033.3 with no stop loss**.

### Resolution
- Detected the orphan at ~23:30 UTC (LONG 1 @ 5033.3, zero orders)
- Closed at market: SELL 1 @ 5010.91 (paper account loss: -$22.39)
- Root cause: V5's pre-attached bracket architecture

---

## 2. Root Cause Analysis: V5 vs V6 vs V8 Order Architecture

### V5 (before fix) — Pre-attached brackets (BROKEN)
- Placed 6 orders simultaneously: 2 entry stops + 4 SL/TP children
- SL/TP attached as `parentId` children before any fill
- If script loses track of position, children become "ticking time bombs" — they open NEW positions when triggered because IBKR doesn't know they're closing orders
- Velocity cycling created new OCA groups each cycle, risking stale orders from previous cycles
- Fill detection by polling `ib.trades()` + `ib.positions()` — prone to cache lag

### V6 (correct design) — Two-phase brackets
- Phase 1: Place ONLY 2 entry stops (OCA pair, no children)
- Phase 2: Place SL/TP AFTER fill confirmed via `execDetailsEvent` callback
- SL/TP are independent OCA orders, not bracket children
- Cancel by Trade object reference, not saved order ID
- Never implemented to production (development shifted to V7/V8)

### V8 — No resting orders at all
- Enters at market when PatternDetector fires signal
- Only 1 order ever at IBKR (catastrophe SL stop)
- Exit managed by engine (time-based), not by resting orders
- Simplest architecture, no orphan risk

---

## 3. Fix Applied: Two-Phase Bracket Refactor

**Commit `adf31871e`** — Ported V6 architecture into V5.

### Changes to `v5_xauusd_orb/orb_multi_live.py` (+127/-64):

1. **`_place_bracket_orders`** — Now places only 2 entry stop orders (OCA pair). No SL/TP children. Reduced from 6 orders to 2.

2. **New `_place_sl_tp`** — Called from `_check_fills` AFTER fill is confirmed. Places SL + TP as independent OCA pair. Stores order IDs in existing state fields so `_apply_breakeven` still works unchanged.

3. **`_cancel_and_close`** — Cancel by contract conId match (not saved order ID). Catches ALL orders regardless of which velocity cycle created them.

4. **`_record_exit`** — Calls `_cancel_all_for_contract()` before logging trade. This is the specific missing cleanup that caused today's orphan.

5. **New `_cancel_all_for_contract`** — Lightweight conId-based cancel helper.

### What this eliminates
- Orphaned SL/TP children that can open unwanted positions
- Stale orders from velocity cycling (conId cancel catches all)
- "Position vanished" path leaving active orders at IBKR

---

## 4. Other Work This Session

### Logs copied to Claude folder (`c:\Users\nsher\nautilus0-claude\`)
- `v8_logs/` — V8 live logs (Mar 15-16, zero trades, normal per backtest frequency)
- `v5_logs/` — V5 live log + trade CSV + velocity CSV
- `v6_velocity_logs/` — Velocity logger data (2 sessions)

### WINDSURF_RESPONSE_10.md written
- Describes 6 V5 bug fixes from previous session
- Documents today's V5 trade and the "position vanished" bug
- V8 live status (zero trades, explained as normal variance)
- Velocity threshold calibration (168→200)
- 4 questions for Claude

### Git commits pushed to `v6-refactor`:
1. `3705317` — V5 ORB: 6 live bug fixes + velocity threshold calibration
2. `841f181` — V6, V7, V8 strategy code, session handovers, journal docs, research scripts (91 files)
3. `adf3187` — V5 ORB: two-phase bracket refactor (V6 architecture port)

---

## 5. Current State

### V5 ORB (XAUUSD)
- **Code fixed but process needs restart** to pick up changes
- Last trade: Mar 16 SHORT @ 4981.96 → CLOSED (bug) → orphaned LONG → manually closed
- Running on paper account, port 4002, clientId 60
- Velocity threshold: 200 ticks/min (IBKR-calibrated)

### V8 Confirmed Rebreak (XAUUSD)
- Running live on paper via watchdog
- Zero trades so far (normal — backtest shows 28% of days have no trades)
- No code changes this session
- Command: `c:\nautilus0\.venv\Scripts\python.exe -m v8_confirmed_rebreak.live.run_live_watchdog`

### V6 Velocity Logger
- Collecting IBKR tick data continuously
- Latest session: `velocity_realtime_XAUUSD_20260315_202800.csv`

### IBKR
- Paper account connected, port 4002
- No open positions (orphan was closed)
- No open orders (all cleaned up)

---

## 6. Pending / Next Steps

1. **Restart V5** with new code to activate the two-phase bracket fix
2. **Monitor next V5 trade** to verify:
   - Only 2 entry stops placed (not 6)
   - SL/TP placed AFTER fill confirmed
   - Velocity pull/re-place doesn't leave orphans
3. **V8 monitoring** — continue watching for first live trade
4. **Consider event-driven fill detection** — current V5 still polls `ib.trades()`. V6 uses `execDetailsEvent` callback which is more reliable. Could be a future improvement.
5. **V5 recent performance**: +$151, +$44.50, -$80.53, -$10.08, -$0.82 (bug) = net +$104.07 over 5 trades

---

## 7. Key Files Modified

| File | Change |
|---|---|
| `v5_xauusd_orb/orb_multi_live.py` | Two-phase bracket refactor (main fix) |
| `v5_xauusd_orb/config.yaml` | velocity_threshold 168→200, close_orphans=true (previous session) |
| `v5_xauusd_orb/guardrails.py` | Minor fix (previous session) |
| `c:\Users\nsher\nautilus0-claude\WINDSURF_RESPONSE_10.md` | Message to Claude |

## 8. Commands

```powershell
# Start V5 ORB (after restart)
c:\nautilus0\.venv\Scripts\python.exe -m v5_xauusd_orb.orb_multi_live

# Start V8 watchdog
c:\nautilus0\.venv\Scripts\python.exe -m v8_confirmed_rebreak.live.run_live_watchdog

# Check IBKR positions
c:\nautilus0\.venv\Scripts\python.exe -c "from ib_insync import IB; ib = IB(); ib.connect('127.0.0.1', 4002, clientId=98); print(ib.positions()); print(len(ib.openOrders()), 'orders'); ib.disconnect()"
```
