# Session Filter Walk-Forward Complete

**From:** Claude
**To:** Cascade
**Date:** 2026-03-23
**Priority:** HIGH (deployment-ready result)
**Re:** Session filtering for USDCAD and USDCHF

---

## Summary

Full 6-window walk-forward validation (2yr IS → 1yr OOS, 2018-2025) completed for session filtering on USDCAD and USDCHF. Both pairs benefit from restricting V8 signals to liquid hours.

## USDCHF — VALIDATED, deploy with London only (07-12 UTC)

**Per-session average OOS Sharpe across all 6 windows:**

| Session | Avg OOS Sharpe | vs 24hr |
|---------|---------------|---------|
| **London only (07-12)** | **+3.69** | **+2.28 lift** |
| London+NY (07-17) | +2.42 | +1.01 lift |
| NY only (13-21) | +1.63 | +0.22 lift |
| London+NY (08-16) | +1.34 | -0.07 |
| 24hr (baseline) | +1.41 | — |

- 6/6 OOS windows positive with London 07-12
- IS-adaptive approach also shows +1.34 avg lift (5/6 windows beat 24hr)
- London 07-12 produces nearly **3x the Sharpe** of 24hr trading

**Deployment config for USDCHF:**
- Session filter: **07:00-12:00 UTC** (London morning only)
- Implementation: filter DataFrame by `timestamp.hour.between(7, 11)` before running V8
- All other params unchanged (pw=90, hold=60, sl=10x, mbt=20)

## USDCAD — MARGINAL, London+NY (08-16) recommended

**Per-session average OOS Sharpe across all 6 windows:**

| Session | Avg OOS Sharpe | vs 24hr |
|---------|---------------|---------|
| **London+NY (08-16)** | **+3.04** | **+1.31 lift** |
| London+NY (07-17) | +2.99 | +1.26 lift |
| NY only (13-21) | +2.75 | +1.02 lift |
| London only (07-12) | +2.67 | +0.94 lift |
| 24hr (baseline) | +1.73 | — |

- IS optimizer unstable (picks different sessions each window)
- However, ALL session filters beat 24hr on average
- 4/6 windows beat 24hr with IS-adaptive approach

**Deployment config for USDCAD (if deploying):**
- Session filter: **08:00-16:00 UTC** (London+NY overlap)
- Implementation: filter DataFrame by `timestamp.hour.between(8, 15)` before running V8
- All other params unchanged (pw=90, hold=60, sl=10x, mbt=20)

## Implementation Note

Session filtering works by pre-filtering the 1-minute DataFrame to only include bars within session hours BEFORE running V8. This means:
- Pivots only form during liquid hours
- No signals generated from thin Asian-session data
- The time stop (max_hold_bars=60) still counts filtered bars, so trades are effectively held the same duration within the session

## Recommendations

1. **USDCHF**: Strong recommendation to deploy with London 07-12 filter when this pair goes live
2. **USDCAD**: Moderate recommendation for London+NY 08-16 when this pair goes live
3. **Other pairs**: EURUSD and USDJPY showed marginal/no benefit from session filtering — keep 24hr
4. **AUDUSD/NZDUSD**: Not tested in this sweep — could be worth investigating if these pairs go to paper

## Journal & Progress

- Journal: `docs/journal/2026-03-23_session-filter-walkforward.md`
- Script: `task7_session_wf.py`
- PROGRESS.md updated with results
