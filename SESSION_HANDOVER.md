# Session Handover — 2026-02-26

## Copy-Paste Prompt for Next Agent

```
I am continuing work on the trading system at c:\nautilus0\

Read this file first and use it as your full context:
  c:\nautilus0\SESSION_HANDOVER.md

Follow c:\nautilus0\.github\copilot-instructions.md for project rules.
Do NOT touch v2/v3 system files unless explicitly asked.
Continue from the "Immediate Next Steps" section below.
```

---

## What Happened This Session (2026-02-26)

### Problem: v5 ORB dry-run could not connect to IB Gateway
`python -m v5_xauusd_orb.orb_live --dry-run` repeatedly timed out on port 4002.

### Root cause
`is_port_listening()` used `socket.create_connection()` to probe port 4002 before each connect attempt. IB Gateway treats every raw TCP connection as an API client. When the socket disconnects without speaking IBKR protocol, Gateway holds the slot in **CLOSE_WAIT** state indefinitely. After several probes + retries, Gateway's connection pool was exhausted → all real connections timed out. Required ~5 Gateway restarts during debugging.

### Fix applied
Refactored `v5_xauusd_orb/orb_live.py` `IBKRConnection` class to follow the **battle-tested pattern** from `live/ib_bar_streamer.py` (runs MTF v2 live system 24/5):

1. Added `nest_asyncio.apply()` at module top — required for ib_insync in nested event loops.
2. Removed `is_port_listening()`, `is_gateway_running()`, `start_gateway()` — all zombie socket creators.
3. New `IBKRConnection.connect()` — simple `ib.connect()` with retry + exponential backoff.
4. Added `_on_ib_error()` handler — mirrors IBBarStreamer critical error codes (`{504, 502, 1100, 2110, 10182}`) and warning suppression (`{2103–2108, 2157, 2158}`).
5. Secondary fix in `trading_system_v4/scripts/xauusd_orb_live.py` — replaced raw socket with netstat-based port check.

### Result
Dry-run connected instantly, contract qualified (XAUUSD CFD, conId=457068913), entered main loop in IDLE state.

---

## Files Modified This Session

| File | Change |
|------|--------|
| `v5_xauusd_orb/orb_live.py` | Rewrote `IBKRConnection` class; added `nest_asyncio`; removed port-probing helpers |
| `trading_system_v4/scripts/xauusd_orb_live.py` | Fixed `is_port_listening()` from raw socket to netstat-based |

---

## Current Infrastructure State (as of 2026-02-26 17:42 UTC-5)

| Component | Status | Details |
|-----------|--------|---------|
| IB Gateway | **Running** | PID 25564, port 4002 (paper), account DU1558484 |
| v5 dry-run | **Stopped** | Ran successfully; shut down when terminal closed |
| MTF v2 live | **Not running** | No Python processes active |
| Gateway path | — | `C:\Jts\ibgateway\1041\ibgateway.exe` |

---

## v5 XAUUSD ORB Strategy Overview

- **Asian Range**: 00:00–06:00 UTC — record session high/low
- **London Breakout**: 08:00–16:00 UTC — bracket orders at range high+buffer / low-buffer
- **Risk/Reward**: 2.0 (SL = range opposite side, TP = 2× distance)
- **Skip**: Wednesdays (weekday=2)
- **State machine**: `IDLE → RANGE_COMPUTED → ORDERS_PLACED → IN_TRADE → DONE_TODAY`
- **IBKR**: host `127.0.0.1`, port `4002`, clientId `60`
- **Contract**: XAUUSD CFD, SMART exchange, USD

### v5 Key Files

| File | Purpose |
|------|---------|
| `v5_xauusd_orb/orb_live.py` | Live execution script (refactored this session) |
| `v5_xauusd_orb/config.yaml` | Strategy parameters |
| `v5_xauusd_orb/config.py` | Typed dataclass config loader |

### Run command
```powershell
cd c:\nautilus0
python -m v5_xauusd_orb.orb_live --dry-run   # paper mode
python -m v5_xauusd_orb.orb_live              # live (removes dry-run guard)
```

---

## Proven Live Infrastructure (Reference)

These files are battle-tested and should be reused/referenced for any new IBKR integration:

| File | Purpose |
|------|---------|
| `live/ib_bar_streamer.py` | Bar streamer — runs 24/5, composite sub keys, reconnect logic |
| `live/run_live_mtf_v2_entry_confirmed_v2_failsafe.py` | Working MTF v2 live runner |
| `config/ibkr_config.py` | Env-based IBKR config |
| `patches/ib_connection_patch.py` | NautilusTrader connection patch |

---

## trading_system_v4 Status (from prior session 2026-02-22)

### Modules Built

| Module | File | Status |
|---|---|---|
| Data adapter | `trading_system_v4/data/nautilus_adapter.py` | Working (mock stream) |
| Feature engineering | `trading_system_v4/features/feature_engineering.py` | Working (35 features) |
| Execution engine | `trading_system_v4/execution/execution_engine.py` | Working (stub broker) |
| Risk manager | `trading_system_v4/risk/risk_manager.py` | Working |
| Logger | `trading_system_v4/monitoring/logger.py` | Working |
| Live runner | `trading_system_v4/scripts/run_live_hybrid.py` | Working (test mode) |

### Test Command
```powershell
python -m trading_system_v4.scripts.run_live_hybrid test
```

---

## Immediate Next Steps (Priority Order)

### v5 ORB
1. **Full-day dry-run validation** — run through Asian → London session to confirm range computation, bracket order placement, fill checking, EOD cleanup.
2. **Bracket order testing** — `place_bracket_orders()`, `check_fills()`, `check_trade_exit()` have not been live-tested. Validate that IBKR accepts the bracket structure.
3. **Consider reusing MTF v2 order management** — user suggested further reuse from proven live system beyond just connection code.

### trading_system_v4
4. **Training data pipeline** — build `training_features.parquet` from historical data using `add_features(df)`.
5. **Label engineering** — SL/TP-aware labels (ATR-based forward lookout).
6. **Train model** — XGBoost/LightGBM, walk-forward CV, save to `model/`.
7. **Connect real NautilusTrader feed** — replace mock `stream_loop()`.
8. **HTF feature injection** — 15m/30m features per 5m bar, no lookahead.

---

## Known Gaps / Risks

| Issue | Severity | Notes |
|---|---|---|
| v5 bracket orders untested | High | Need full-day paper trade run |
| Mock data adapter (v4) | High | Must replace before real trading |
| No trained model (v4) | High | Pipeline not built yet |
| v5 order management is custom | Medium | Not yet reusing proven MTF v2 patterns |
| HTF features missing (v4) | Medium | 5m model lacks multi-timeframe context |

---

## Do Not Touch

- `strategies/` — v2/v3 live system
- `models/` — v3 production model files
- `.env.mtf_v2`, `.env.mtf_v3` — live config
- Do not change v2/v3 behavior unless explicitly requested
