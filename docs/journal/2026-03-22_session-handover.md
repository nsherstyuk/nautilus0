# Session Handover — 2026-03-22

## Objective
Prepare V6 and V8 strategies for live paper trading Sunday night. Two agents (Windsurf + Cascade) independently researched multi-pair viability; this session reconciled findings and configured deployment.

---

## Key Research Outcome: V6+BE Look-Ahead Bias Discovered

**My (Cascade's) original claim:** V6+BE transforms all 7 pairs to Sharpe +2-4 OOS.

**Windsurf's walk-forward rebuttal:** Proper IS/OOS separation (2yr IS → 1yr OOS, 6 rolling windows, 504 backtests) showed:
- V6+BE per-pair Sharpe numbers inflated 3-5x due to look-ahead in BE duration selection
- Only XAUUSD (+0.71) and USDJPY (+0.66) show real V6 OOS edge — both modest
- EURUSD, AUDUSD, NZDUSD, USDCAD, USDCHF are negative OOS under V6
- BE=OFF is IS-preferred for XAUUSD (5/6 windows)

**V8 walk-forward (Windsurf ran this too):** V8 with pw=90-120 is walk-forward validated on ALL 7 pairs (avg Sharpe +2.31, 5/7 pairs 100% consistent across 6 windows). pw=120 IS-optimal for 5/7 pairs.

**Conclusion:** V8 is the real multi-pair strategy. V6 is a modest single-pair supplement on XAUUSD.

### Response Documents
- `RESPONSE_TO_OTHER_AGENT.md` — My initial response + follow-up conceding BE look-ahead
- `RESPONSE_TO_WINDSURF.md` — Windsurf's walk-forward validation (read-only, their file)

---

## Code Changes Made This Session

### 1. `v8_confirmed_rebreak/live/run_live.py`
- **Added CLI args:** `--symbol`, `--sec-type`, `--exchange`, `--currency` (was hardcoded XAUUSD)
- **Auto-sizes buffer** for larger pivot windows: `buffer_size = max(500, 2*pw + 51)`
- **Per-symbol trade log paths:** `trades_{symbol}.csv` to avoid collision when running multiple V8 instances

### 2. `v5_xauusd_orb/config.yaml`
- **USDJPY section updated:** `enabled=true`, `symbol=USD`, `currency=JPY`, `be_hours=2.0`, `velocity_filter_enabled=false`, `skip_weekdays=[2]`
- Note: USDJPY was initially configured for V6 live but we switched to XAUUSD after Windsurf's walk-forward showed V6 USDJPY edge is modest (+0.66) and BE is unreliable

### 3. `launch_paper_trading.ps1` (NEW)
- Launches 3 processes with walk-forward validated params
- LIVE mode (no dry-run) on paper account
- Final config:
  - V6 XAUUSD: `--instrument XAUUSD` (BE=OFF, skip Wed, vel=200 from config.yaml)
  - V8 XAUUSD: `--client-id 70 --pw 120 --min-ticks 15`
  - V8 EURUSD: `--client-id 71 --symbol EUR --sec-type CASH --exchange IDEALPRO --pw 120 --min-ticks 75 --qty 20000`

### 4. `RESPONSE_TO_OTHER_AGENT.md` (NEW)
- Point-by-point response to Windsurf's investigation findings
- Follow-up section conceding BE look-ahead bias and V6 correlation concerns

---

## Final Live Deployment Config

| Process | Strategy | Pair | Key Params | Client ID | Source |
|---------|----------|------|-----------|-----------|--------|
| V6 ORB | v6_orb_refactor | XAUUSD | BE=OFF, skip Wed, vel=200, RR=2.5, qty=1 | 60 | V5 production config |
| V8 Rebreak | v8_confirmed_rebreak | XAUUSD | pw=120, min_ticks=15, max_hold=60 | 70 | WF-validated |
| V8 Rebreak | v8_confirmed_rebreak | EURUSD | pw=120, min_ticks=75, max_hold=60, qty=20k | 71 | WF-validated |

---

## Launch Commands (manual, 3 terminals)

```powershell
# Terminal 1: V6 XAUUSD
.venv312\Scripts\python.exe -m v6_orb_refactor.live.run_live --instrument XAUUSD

# Terminal 2: V8 XAUUSD
.venv312\Scripts\python.exe -m v8_confirmed_rebreak.live.run_live --client-id 70 --pw 120 --min-ticks 15

# Terminal 3: V8 EURUSD
.venv312\Scripts\python.exe -m v8_confirmed_rebreak.live.run_live --client-id 71 --symbol EUR --sec-type CASH --exchange IDEALPRO --pw 120 --min-ticks 75 --qty 20000
```

Prerequisites: IB Gateway running on port 4002 (paper account). Kill any sleeping USDJPY V6 process first.

---

## Verification Done

- V6 XAUUSD config.yaml: BE=OFF (`be_hours: 999`), skip Wed (`skip_weekdays: [2]`), velocity on — confirmed
- V6 USDJPY contract: tested live, qualified successfully (`conId=15016059`) — but we switched to XAUUSD
- V8 import check: `from v8_confirmed_rebreak.live.run_live import main` — passes
- V6 live code: fully contract-agnostic, no XAUUSD hardcoding in connection/executor/runner
- V8 reconnection logic: `ensure_connected()` with heartbeat, auto-reconnect, contract re-qualification — unchanged

---

## Pending

- [ ] Test V8 XAUUSD and V8 EURUSD connections when IBKR opens Sunday night
- [ ] Monitor first trading session Monday for signal generation and order placement
- [ ] Consider building proper daily_launcher.ps1 (like V5's) if paper test goes well
