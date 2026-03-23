# 2026-03-22 V6+V8 Paper Deployment & Agent Collaboration Setup

## Author
Cascade

## What Was Done
- Added multi-instrument CLI args to V8 live code (`--symbol`, `--sec-type`, `--exchange`, `--currency`)
- Added per-symbol trade log paths to V8 to avoid collision when running multiple instances
- Added auto buffer sizing for larger pivot windows in V8
- Updated V6 config with USDJPY params (later switched to XAUUSD based on Claude's walk-forward)
- Created `launch_paper_trading.ps1` for 3-process launch
- Verified V6 USDJPY contract qualification (conId=15016059), then switched to XAUUSD
- Verified V8 XAUUSD connection and contract qualification (conId=69067924)
- Verified V8 EURUSD connection and contract qualification (conId=12087792)
- First V8 XAUUSD paper trade: short, +$2.45, TIME_STOP exit at 60 bars
- Wrote response to Claude's multi-pair research findings (`RESPONSE_TO_OTHER_AGENT.md`)
- Established agent collaboration protocol (`docs/COLLABORATION_PROTOCOL.md`)
- Created shared progress file (`docs/PROGRESS.md`)
- Created agent-comms folder structure with first message to Claude

## What Was Tried (and failed/changed)
- **V6 USDJPY deployment** — initially configured and tested. Contract qualified successfully. But Claude's walk-forward showed V6 USDJPY edge is only +0.66 Sharpe (not +3.08 as originally claimed). Switched to V6 XAUUSD (+0.71 Sharpe, better validated).
- **V6+BE on multiple pairs** — my original Phase 8 research claimed Sharpe +2-4 on all 7 pairs. Claude ran proper walk-forward and proved this was look-ahead bias. BE duration was selected on full sample including OOS data. Real V6 numbers: only XAUUSD and USDJPY positive, and BE=OFF is IS-preferred for XAUUSD.
- **V8 XAUUSD pw=60** — initially configured based on my single-split OOS. Claude's 6-window rolling walk-forward showed pw=120 is IS-optimal in 5/6 windows. Changed to pw=120.
- **USDJPY IBKR contract** — initially used symbol=JPY, currency=USD (wrong). Fixed to symbol=USD, currency=JPY (base/quote order matters for CASH contracts).

## Key Decisions & Rationale
1. **V6 on XAUUSD only (not USDJPY)** — Claude's walk-forward shows XAUUSD is V6's best pair. USDJPY edge is modest and BE is unreliable.
2. **V6 BE=OFF** — IS optimizer picks BE=OFF 5/6 windows for XAUUSD. The V5 production config already had `be_hours: 999`.
3. **V8 pw=120 for both XAUUSD and EURUSD** — Claude's rolling walk-forward validated. IS-optimal 5/6 and 4/6 windows respectively.
4. **V8 min_ticks=15 (gold) / 75 (EUR)** — from Claude's walk-forward validated configs.
5. **LIVE mode (no dry-run) on paper** — paper account costs nothing, want real order flow data.
6. **max_hold_bars=60 kept as-is** — not yet optimized, flagged as HIGH priority research for Claude.

## Code Changes
- `v8_confirmed_rebreak/live/run_live.py` — CLI args for instrument, auto buffer sizing, per-symbol trade logs
- `v5_xauusd_orb/config.yaml` — USDJPY section added (symbol=USD, currency=JPY)
- `launch_paper_trading.ps1` — NEW: 3-process launcher with WF-validated params
- `RESPONSE_TO_OTHER_AGENT.md` — NEW: cross-agent research reconciliation
- `SESSION_HANDOVER_2026-03-22.md` — NEW: deployment handover doc
- `docs/COLLABORATION_PROTOCOL.md` — NEW: agent roles, comms, journal rules
- `docs/PROGRESS.md` — NEW: shared progress tracker
- `docs/agent-comms/cascade-to-claude/2026-03-22_collaboration-proposal-and-research-tasks.md` — NEW: first message to Claude

## Current State
- **V8 XAUUSD** — RUNNING on paper, pw=120, min_ticks=15, client_id=70
- **V8 EURUSD** — RUNNING on paper, pw=120, min_ticks=75, client_id=71
- **V6 XAUUSD** — NOT YET LAUNCHED (need to kill sleeping USDJPY process first)
- First paper trade completed: V8 XAUUSD short +$2.45

## Next Steps
- **Cascade:** Launch V6 XAUUSD, monitor all 3 processes overnight
- **Claude:** Review `docs/COLLABORATION_PROTOCOL.md` and agree/modify
- **Claude (HIGH):** Run `max_hold_bars` walk-forward sweep for XAUUSD and EURUSD
- **Claude (MED):** Sweep remaining V8 params after max_hold settled
- **Claude (MED):** Code review V8 live code before real money
- **Cascade:** Clean up root-level RESPONSE_TO_*.md and SESSION_HANDOVER_*.md into docs/
