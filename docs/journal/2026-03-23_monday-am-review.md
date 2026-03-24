# Monday AM Review -- 2026-03-23

*Author: Cascade*

## Overnight Paper Trading Results (Sat night session)

### V8 XAUUSD (client_id=70)
- **1 trade:** SHORT @ 20:32 UTC, exit TIME_STOP @ 21:32 UTC, PnL **+$2.45**
- Gold dropped from 4425 to below 4100 overnight -- massive move, but V8 only caught first hour
- SL order rejected by IBKR: "price does not conform to minimum price variation" (4498.34)
- IBKR disconnected at 00:23, auto-reconnected in 8 seconds

### V8 EURUSD (client_id=71)
- **0 trades** -- BROKEN
- Root cause: `min_ticks=75` but EURUSD only gets ~59-60 ticks per 1-min bar
- `buy_ratio` was always NaN, so no signal could ever fire
- **Fix:** lowered `min_ticks` to 45

### V6 XAUUSD (client_id=60)
- **0 trades** -- Asian range too wide (170.97 pts, 3.90%) due to extreme overnight volatility
- Correctly skipped per gap filter logic

## Bugs Fixed

1. **V8 EURUSD min_ticks** (75 -> 45): EURUSD tick density is ~60/bar, so 75 was an impossible threshold. Changed in `launch_paper_trading.ps1`.

2. **V8 SL tick-size rounding**: Added `tick_size` parameter to `LiveConfig` and `--tick-size` CLI arg. `submit_stop_order` now rounds `stop_price` to nearest tick before submitting. Per-instrument tick sizes:
   - XAUUSD: 0.01
   - EURUSD: 0.00005
   - USDJPY: 0.005

## New Deployment: USDJPY

Added V8 Rebreak on USDJPY as Process 4:
- client_id=72, symbol=USD, secType=CASH, exchange=IDEALPRO, currency=JPY
- pw=120, min_ticks=45, tick_size=0.005, qty=20000
- Claude's research: Sharpe +2.91, strongest next pair after XAUUSD and EURUSD

## Relaunch

All processes killed and relaunched at 08:27 EST with fixes:
- V6 XAUUSD (client_id=60) -- unchanged
- V8 XAUUSD (client_id=70) -- added tick_size=0.01
- V8 EURUSD (client_id=71) -- min_ticks=45, tick_size=0.00005
- V8 USDJPY (client_id=72) -- NEW

All 4 connected and seeded (481 bars each).

## Files Changed

- `v8_confirmed_rebreak/live/live_config.py` -- added `tick_size` field
- `v8_confirmed_rebreak/live/run_live.py` -- added `--tick-size` CLI arg, SL rounding in `submit_stop_order`
- `launch_paper_trading.ps1` -- EURUSD min_ticks=45, USDJPY process, tick-size params, em-dash encoding fix

## Midday Update: spread_cost Bug (12:52 EST)

### Bug Discovery

After the morning relaunch, EURUSD and USDJPY both produced bad trades:

**EURUSD -- 2 trades, both CATASTROPHE_SL after 1 bar:**
```
SIGNAL long @ 1.16 (adj 1.31) pivot=1.16 ATR=0.00 SL=1.31
```
- `spread_cost=0.30` (XAUUSD default) inflated entry from 1.16 to 1.31
- ATR ~0.0003 for FX, so SL = 1.31 - 0.003 = 1.307
- Actual price at 1.16 is far below 1.307 -- instant CATASTROPHE_SL

**USDJPY -- 1 trade, CATASTROPHE_SL after 29 bars:**
```
SIGNAL short @ 158.30 (adj 158.15) ATR=0.05 SL=158.64
```
- Spread inflated entry by 0.15 (should be ~0.005)
- SL was legitimate hit (price moved to 158.64) but PnL calculation was wrong

### Root Cause

`spread_cost` in `LiveConfig` defaults to 0.30, which is correct for XAUUSD gold (typical spread ~$0.30). This value was being applied to ALL instruments including FX pairs where spreads are ~0.0001 (EUR) or ~0.01 (JPY).

### Fix

- Added `--spread-cost` CLI arg to `run_live.py`
- Per-instrument values in `launch_paper_trading.ps1`:
  - XAUUSD: 0.30
  - EURUSD: 0.00010
  - USDJPY: 0.01

### Status Script

Created `scripts/trading_status.ps1` -- run anytime to see:
- Running processes
- Trade count and PnL per pair (today + total)
- Last trade details
- Latest log lines

Usage: `.\scripts\trading_status.ps1`

### Relaunch (12:52 EST)

All processes killed and relaunched with spread_cost fix. GBPUSD download also restarted (resumed from 2023-03).

## Afternoon: Claude Code Review Fixes (13:18 EST)

### Claude's V8 Live Code Review

Claude completed a full audit of ~1,400 lines across 9 files. Overall architecture sound, but order management not production-ready. 5 must-fix items identified.

### Fixes Implemented (all 5)

1. **reqMarketDataType(3) -> 1**: Was trading on delayed/frozen prices. Now defaults to live (1), configurable via `--market-data-type` CLI flag.

2. **Fill verification on all orders**: `submit_market_order()`, `submit_stop_order()`, `close_position()` now poll `trade.orderStatus.status` with 3s timeout. If not Filled/Submitted/PreSubmitted, return `None` with error log. Entry rollback: if market order fails, `engine.in_trade = False`. SL failure: logs warning, position stays open without stop.

3. **max_daily_loss enforced**: `safety_check()` now checks `daily_pnl <= -max_daily_loss`. On trigger: cancels SL, closes position at market, halts trading for the day.

4. **Startup position reconciliation**: New `_check_existing_positions()` queries `ib.positions()` on connect. Logs WARNING if orphaned position found. Currently warning-only (doesn't refuse to start or adopt position -- design decision deferred to pre-real-money review).

5. **SL cancel failures logged**: Replaced 2x `except: pass` with `except Exception as e: log.warning(...)` in `_handle_exit()` and `_cleanup()`.

### Files Changed

- `v8_confirmed_rebreak/live/run_live.py` -- fixes #1-5 (~50 lines added)
- `v8_confirmed_rebreak/live/live_engine.py` -- fix #3 (3 lines in safety_check)
- `v8_confirmed_rebreak/live/live_config.py` -- fix #1 (market_data_type field)

### Edge Cases Flagged for Claude Review

- Fix #2: Is `engine.in_trade = False` sufficient rollback? Stale state in trade_direction etc?
- Fix #3: Double-exit risk if SL cancel fails (broker fills SL) then we send market close
- Fix #4: Before real money, need to decide: refuse to start vs adopt position vs auto-flatten

### Relaunch (13:18 EST)

All processes killed and relaunched. Logs confirm:
- Position reconciliation: OK (no existing positions) on all 3 V8 processes
- Market data type now 1 (live) instead of 3 (delayed)
- GBPUSD download restarted (resumed from ~2023-03)

### Messages Sent to Claude

- `cascade-to-claude/2026-03-23_code-review-fixes-implemented.md` -- full diff summary with 3 design questions

## Afternoon: Claude Edge Case Review + Fixes (13:31 EST)

Claude reviewed fixes #2-4 and identified 5 edge case hardening items. Implemented 4/5 (item #5 deferred to real money).

### Changes

1. **`_reset_trade_state()`**: New method clears all 9 trade fields. Used in `_close_trade()`, failed entry rollback, and safety halt — prevents stale state.

2. **SL retry**: If SL order fails, retry once after 5s. Only give up and log ERROR after second failure.

3. **Position check before safety-halt close**: New `_has_broker_position()` helper queries `ib.positions()`. Safety halt now verifies position exists before sending close order — prevents double-exit if broker SL already filled.

4. **Position check in exit path**: TIME_STOP and other non-CATASTROPHE_SL exits also verify position before closing.

5. **Refuse-to-start (deferred)**: Position recon stays warning-only for paper. Will switch to refuse-to-start for real money.

### Relaunch (13:31 EST)

All processes relaunched with edge case fixes. V8 live system now production-hardened for paper trading. Only remaining item for real money: refuse-to-start on orphaned position.

## Log File Collision Bug (14:06 EST)

### Discovery

After deploying edge case fixes, user reported EURUSD "wasn't running." Investigation showed only 2 log files from the 13:31 launch instead of 3. The file `v8_live_20260323_133152.log` contained interleaved XAUUSD (~4400) and EURUSD (~1.16) prices, with two shutdown sequences at the end. EURUSD was actually running but sharing XAUUSD's log file.

### Root Cause

All V8 processes used logger name `"v8_live"` and timestamp-only filename `v8_live_{ts}.log`. When two processes called `setup_logging()` in the same second, both created FileHandlers to the same file path. Windows allows concurrent writes, so both appended to the same file.

### Fix

1. Added `pair_name` property to `LiveConfig` — returns full pair name (XAUUSD, EURUSD, USDJPY) regardless of IBKR contract naming (where EURUSD = symbol=EUR, currency=USD)
2. Logger name now `v8_live_{pair_name}` (unique per instrument)
3. Log filename now `v8_live_{pair_name}_{ts}.log`

### Relaunch (14:06 EST)

All processes relaunched. Logs now cleanly separated:
- `v8_live_xauusd_20260323_140635.log`
- `v8_live_eurusd_20260323_140639.log`
- `v8_live_usdjpy_20260323_140642.log`

## Day Summary: 12 Fixes Deployed

| # | Fix | Category |
|---|-----|----------|
| 1 | spread_cost per-instrument (was 0.30 for all) | Bug fix |
| 2 | reqMarketDataType 3→1 + CLI flag | Code review |
| 3 | Fill verification on all orders | Code review |
| 4 | max_daily_loss circuit breaker | Code review |
| 5 | Startup position reconciliation | Code review |
| 6 | SL cancel failure logging | Code review |
| 7 | `_reset_trade_state()` method | Edge case |
| 8 | SL order retry on failure | Edge case |
| 9 | Position check before safety-halt close | Edge case |
| 10 | Position check in non-SL exit path | Edge case |
| 11 | Log file collision (pair_name in logger+filename) | Bug fix |
| 12 | `pair_name` property for display (XAUUSD not USD) | UX |

## Evening: Brief Corrections + GBPUSD Deployed (20:29 EST)

### v8_pw120_upgrade_brief.md Corrections

Reviewed Claude's deployment brief. Found and fixed:
1. **USDJPY symbol/currency backwards**: `symbol=JPY, currency=USD` → `symbol=USD, currency=JPY`
2. **Launch commands**: same USDJPY fix in example commands

### Param Alignment with Brief

Checked IBKR live tick counts — all instruments get ~59-60 ticks/bar consistently. Aligned live params with the brief's WF-validated values:

| Change | Old | New |
|--------|-----|-----|
| XAUUSD min_ticks | 15 | 50 |
| EURUSD min_ticks | 45 | 30 |
| USDJPY min_ticks | 45 | 30 |
| USDJPY spread_cost | 0.01 | 0.015 |

Since IBKR gives ~60 ticks/bar, both old and new min_ticks pass virtually all bars. Changed for backtest parity.

### GBPUSD Added to Paper

Added as 5th process (client_id=73): `--symbol GBP --sec-type CASH --exchange IDEALPRO --min-ticks 30 --spread-cost 0.00012 --tick-size 0.00005 --qty 20000`

Note: GBPUSD data download incomplete (~2023-10). Full WF validation still pending. Deployed to paper for observation (zero risk).

### Relaunch (20:29 EST)

All 5 processes running. Logs confirm healthy startup for all 4 V8 pairs + V6 XAUUSD.

### Messages Sent to Claude

- `cascade-to-claude/2026-03-23_brief-corrections-and-gbpusd-deployed.md` — corrections, deployment summary, 5 questions for confirmation

## Code Changes

| File | Change |
|------|--------|
| `v8_confirmed_rebreak/live/run_live.py` | 13 fixes: fill verification, reset_trade_state, SL retry, position checks, pair_name logging, price precision |
| `v8_confirmed_rebreak/live/live_engine.py` | `_reset_trade_state()`, daily loss check in `safety_check()` |
| `v8_confirmed_rebreak/live/live_config.py` | `market_data_type` field, `pair_name` property |
| `launch_paper_trading.ps1` | Corrected params, added GBPUSD (5 processes) |
| `docs/v8_pw120_upgrade_brief.md` | Fixed USDJPY symbol/currency |

## Pending

- Awaiting Claude confirmation on spread_cost, tick_size, min_ticks values
- V6 keep/cut decision deferred -- need more paper data
- USDCAD/USDCHF need session filter implementation before paper trading
- GBPUSD download needs restart (~2023-10 to 2025-12 remaining)
- Switch position recon to refuse-to-start before real money
