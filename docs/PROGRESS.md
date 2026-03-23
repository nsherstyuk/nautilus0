# Project Progress

*Last updated: 2026-03-22 by Cascade*

## Active Deployments

| Process | Strategy | Pair | Params | Status | Since |
|---------|----------|------|--------|--------|-------|
| V6 ORB | v6_orb_refactor | XAUUSD | BE=OFF, skip Wed, vel=200, RR=2.5, qty=1, client_id=60 | Pending launch | — |
| V8 Rebreak | v8_confirmed_rebreak | XAUUSD | pw=120, min_ticks=15, max_hold=60, sl=10x, client_id=70 | **RUNNING** (paper) | 2026-03-22 20:19 |
| V8 Rebreak | v8_confirmed_rebreak | EURUSD | pw=120, min_ticks=75, max_hold=60, sl=10x, qty=20k, client_id=71 | **RUNNING** (paper) | 2026-03-22 20:19 |

## Research Queue

| Task | Priority | Owner | Status | Notes |
|------|----------|-------|--------|-------|
| max_hold_bars walk-forward sweep (XAUUSD, EURUSD) | HIGH | Claude | Not started | Values: 30,60,90,120,180,240. Fix pw=120. First trade left $35 on table with hold=60 |
| imbalance_window sweep | MED | Claude | Not started | After max_hold is settled |
| sl_atr_multiple sweep | MED | Claude | Not started | After max_hold is settled |
| divergence_threshold sweep | LOW | Claude | Not started | After other params settled |
| Full GBPUSD data + V8 test | LOW | Claude | Not started | V8 should work on GBPUSD based on universal pattern |
| Combined V6+V8 portfolio on XAUUSD | LOW | Cascade | Not started | Diversification test |
| V8 live code review | MED | Claude | Not started | Before real money deployment |

## Completed Research (last 30 days)

| Date | Task | Result | Journal Entry |
|------|------|--------|---------------|
| 2026-03-22 | V6+BE walk-forward (Claude) | BE look-ahead confirmed. V6 only works on XAUUSD (+0.71) and USDJPY (+0.66). 5/7 pairs negative | `RESPONSE_TO_WINDSURF.md` |
| 2026-03-22 | V8 pivot_window walk-forward (Claude) | pw=120 IS-optimal 5/7 pairs. ALL 7 pairs profitable OOS (avg Sharpe +2.31) | `RESPONSE_TO_WINDSURF.md` |
| 2026-03-22 | Multi-instrument V6/V8 research (Cascade) | 12-phase analysis. V6+BE claims debunked by Claude's WF. V8 multi-pair confirmed | `docs/research/multi-instrument-v6-v8-findings.md` |

## Known Issues

- [ ] `max_hold_bars=60` never optimized — may leave PnL on table for XAUUSD (Cascade, 2026-03-22)
- [ ] IB error 10147 "OrderId not found" on V8 exit — harmless race condition but should investigate (Cascade, 2026-03-22)
- [ ] `.venv312/` not in `.gitignore` — must stage files explicitly (Cascade, 2026-03-22)
- [ ] Old RESPONSE_TO_*.md and SESSION_HANDOVER_*.md files in repo root — need cleanup into docs/ (Cascade, 2026-03-22)

## Parameter History

| Date | Param | Old Value | New Value | Reason | Validated? |
|------|-------|-----------|-----------|--------|------------|
| 2026-03-22 | V8 XAUUSD pivot_window | 60 | 120 | Claude's WF: IS picks pw=120 in 5/6 windows, OOS +3.08 | Yes (WF) |
| 2026-03-22 | V8 XAUUSD min_ticks | 50 | 15 | Claude's WF-validated config | Yes (WF) |
| 2026-03-22 | V8 EURUSD min_ticks | 50 | 75 | Claude's WF-validated config | Yes (WF) |
| 2026-03-22 | V6 target pair | USDJPY | XAUUSD | Claude's WF showed V6 USDJPY edge modest (+0.66), XAUUSD better (+0.71) | Yes (WF) |
| 2026-03-22 | V6 XAUUSD be_hours | 2.0 | 999 (OFF) | Claude's WF: IS picks BE=OFF 5/6 windows for XAUUSD | Yes (WF) |

## Live Trade Log

| Date | Time | Strategy | Pair | Direction | Entry | Exit | PnL | Exit Reason | Notes |
|------|------|----------|------|-----------|-------|------|-----|-------------|-------|
| 2026-03-22 | ~20:32 | V8 | XAUUSD | Short | ~4425 | 4421.05 | +$2.45 | TIME_STOP (60 bars) | First paper trade. Gold dropped $35 more after exit |
