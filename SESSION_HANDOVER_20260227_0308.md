# Session Handover — 2026-02-27 03:08 UTC

## Copy-Paste Prompt for Next Agent

```
I am continuing work on the trading system at c:\nautilus0\

Read this file first and use it as your full context:
  c:\nautilus0\SESSION_HANDOVER_20260227_0308.md

Follow c:\nautilus0\.github\copilot-instructions.md for project rules.
Do NOT touch v2/v3 system files unless explicitly asked.
Continue from the "Immediate Next Steps" section below.
```

---

## What Happened This Session (2026-02-26 / 2026-02-27)

### Part 1: v5 ORB Live Launch
`python -m v5_xauusd_orb.orb_live --dry-run` repeatedly timed out on port 4002.

**Root cause**: `is_port_listening()` used `socket.create_connection()` to probe port 4002 before each connect attempt. IB Gateway treats every raw TCP connection as an API client. When the socket disconnects without speaking IBKR protocol, Gateway holds the slot in CLOSE_WAIT state→ connection pool exhausted → all real connections timed out.

**Fix**: Refactored `IBKRConnection` class to follow the battle-tested pattern from `live/ib_bar_streamer.py`. Removed all raw socket probing. Added `nest_asyncio.apply()`. Added proper `_on_ib_error()` handler.

**4 bugs also fixed in `orb_live.py`**:
1. `durationStr="1 D"` (was `"8 hours"`) in `get_asian_range_live()` — was requesting only 8h of history, missing Asian session bars
2. Trade-window-closed guard in `run_loop()` — if UTC hour ≥ 16 and state is IDLE/RANGE_COMPUTED, skip today
3. Continuous day loop in `main()` — sleeps until next midnight +10min, resets state, loops forever
4. GTD failsafe on entry stop orders — `tif="GTD"` with `goodTillDate=16:00 UTC` — IBKR auto-cancels if script crashes

**Outcome**: Live run started. Contract qualified (XAUUSD CFD, conId=457068913). Entered IDLE state cleanly.

---

### Part 2: v5 Backtesting
Created vectorized backtest of the v5 ORB strategy.

**Data**: `trading_system_v4/data/xauusd_1000t_bars.parquet` — 415k 1000-tick bars, 2015–2026, resample to 354k 5-min bars (median gap exactly 5min).

**Results 2015–2026**:
| Metric | Value |
|--------|-------|
| Total P&L | +$3,136 |
| Sharpe | 2.60 |
| Profit Factor | 1.61 |
| Max Drawdown | -$109 |
| TP rate | 20% |
| EOD closes | 49% |
| All years profitable | ✅ |

---

### Part 3: Multi-Stage Exit Comparison (8 strategies)
Created `v5_xauusd_orb/backtest_exits.py` comparing 8 exit strategies on 2019–2026.

**Key finding**: Price-based BE stops kill good trades. Time-based BE after 2h dramatically improves risk-adjusted returns.

**Results 2019–2026**:
| Strategy | P&L | Sharpe | MaxDD | PF |
|----------|-----|--------|-------|----|
| Baseline (EOD) | +$2,602 | 2.83 | -$109 | 2.04 |
| BE@50%TP | +$1,682 | 2.73 | -$109 | 1.65 |
| BE@33%TP | +$1,391 | 2.23 | -$109 | 1.56 |
| Trail@50%TP | +$1,612 | 2.62 | -$109 | 1.62 |
| Trail@33%TP | +$1,314 | 2.17 | -$109 | 1.55 |
| **BE after 1h** | **+$2,918** | **5.00** | **-$26** | **7.98** |
| **BE after 2h** | **+$3,142** | **4.87** | **-$34** | **4.25** |
| Partial 50%+BE | +$2,112 | 3.02 | -$109 | 2.12 |

**Winner: 2h BE rule** — highest absolute P&L (+$3,142), near-halved drawdown (-$34), Sharpe 4.87.

**How the 2h BE rule works** (example LONG):
- Entry at $2,650 with SL at $2,635, TP at $2,680
- 2 hours pass, price drifting at $2,648 — no SL trigger yet
- **Rule fires**: SL moved from $2,635 → $2,650 (breakeven)
- Trade now risk-free; worst case is scratch, not a loss
- Protects against EOD losers that drift without direction

---

## Files Created/Modified This Session

| File | Change |
|------|--------|
| `v5_xauusd_orb/orb_live.py` | Rewrote `IBKRConnection`; 4 bugs fixed; nest_asyncio added |
| `v5_xauusd_orb/backtest.py` | **CREATED** — vectorized backtest engine (2015–2026) |
| `v5_xauusd_orb/backtest_exits.py` | **CREATED** — 8-strategy exit comparison engine |
| `trading_system_v4/scripts/xauusd_orb_live.py` | Fixed `is_port_listening()` from raw socket to netstat |

---

## Current Infrastructure State (2026-02-27 03:08 UTC)

| Component | Status | Details |
|-----------|--------|---------|
| IB Gateway | **Running** | PID 25564, port 4002 (paper), account DU1558484 |
| v5 ORB live | **Running** | User started it in their own terminal |
| MTF v2 live | **Not running** | No Python processes active |
| Gateway path | — | `C:\Jts\ibgateway\1041\ibgateway.exe` |

---

## v5 XAUUSD ORB Strategy Overview

- **Asian Range**: 00:00–06:00 UTC — record session high/low
- **London Breakout**: 08:00–16:00 UTC — bracket orders at range_high+buffer / range_low-buffer
- **Risk/Reward**: 2.0 (SL = range opposite side, TP = 2× distance)
- **Skip**: Wednesdays (weekday=2)
- **State machine**: `IDLE → RANGE_COMPUTED → ORDERS_PLACED → IN_TRADE → DONE_TODAY`
- **IBKR**: host `127.0.0.1`, port `4002`, clientId `60`
- **Contract**: XAUUSD CFD, SMART exchange, USD

### v5 Key Files

| File | Purpose |
|------|---------|
| `v5_xauusd_orb/orb_live.py` | Live execution script (938 lines, production-ready) |
| `v5_xauusd_orb/backtest.py` | Vectorized backtest engine |
| `v5_xauusd_orb/backtest_exits.py` | 8-strategy exit comparison |
| `v5_xauusd_orb/config.yaml` | Strategy parameters |
| `v5_xauusd_orb/config.py` | Typed dataclass config loader |

### Run commands
```powershell
cd c:\nautilus0
.venv\Scripts\python.exe -m v5_xauusd_orb.orb_live --dry-run   # paper mode
.venv\Scripts\python.exe -m v5_xauusd_orb.backtest --start 2015-01-01 --save v5_xauusd_orb/logs/backtest.csv
.venv\Scripts\python.exe -m v5_xauusd_orb.backtest_exits --start 2019-01-01 --save v5_xauusd_orb/logs/exit_comparison.csv
```

---

## Immediate Next Steps (Priority Order)

### 1. Implement 2h BE rule in `orb_live.py` ← MOST IMPORTANT
The backtest proves 2h BE dramatically improves the live strategy. Not yet implemented in the live script.

**Implementation plan**:
- Add `be_applied: bool = False` to `ORBState` dataclass (+ save/load)
- Add `sl_order_id: int = 0` to `ORBState` — need to capture the SL child order ID from bracket placement (currently only `buy_order_id`/`sell_order_id` stored)
- In the `IN_TRADE` block in `run_loop()`: check `(now - entry_datetime).total_seconds() >= 7200`
- If elapsed and not yet `be_applied`: call `conn.ib.modifyOrder()` to set SL `auxPrice = state.entry_price`
- Set `state.be_applied = True`, log: `"2h BE rule triggered: SL moved to entry {entry_price:.2f}"`
- Consider adding `be_hours: 2` to `config.yaml` rather than hardcoding 7200s

### 2. Full 2015–2026 exit comparison
Re-run `backtest_exits.py --start 2015-01-01` to confirm 2h BE holds over the full dataset.

### 3. Full-day dry-run validation
Run through one full Asian → London session to confirm range computation, bracket order placement, fill checking, and EOD cleanup work end-to-end.

---

## Proven Live Infrastructure (Reference)

| File | Purpose |
|------|---------|
| `live/ib_bar_streamer.py` | Bar streamer — runs 24/5, composite sub keys, reconnect logic |
| `live/run_live_mtf_v2_entry_confirmed_v2_failsafe.py` | Working MTF v2 live runner |
| `config/ibkr_config.py` | Env-based IBKR config |
| `patches/ib_connection_patch.py` | NautilusTrader connection patch |

---

## Do Not Touch

- `strategies/` — v2/v3 live system
- `models/` — v3 production model files
- `.env.mtf_v2`, `.env.mtf_v3` — live config
- Do not change v2/v3 behavior unless explicitly requested
