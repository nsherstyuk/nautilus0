# Project Progress

*Last updated: 2026-03-24 11:10 EST by Cascade (pivot=nan fix, trade log update, process restart)*

## Active Deployments

| Process | Strategy | Pair | Params | Status | Since |
|---------|----------|------|--------|--------|-------|
| V6 ORB | v6_orb_refactor | XAUUSD | BE=OFF, skip Wed, vel=200, RR=2.5, qty=1, client_id=60 | **RUNNING** (paper) | 2026-03-24 11:10 |
| V8 Rebreak | v8_confirmed_rebreak | XAUUSD | pw=120, min_ticks=50, sl=10x, tick_size=0.01, spread=0.30, mdt=1, client_id=70 | **RUNNING** (paper) | 2026-03-24 11:10 |
| V8 Rebreak | v8_confirmed_rebreak | EURUSD | pw=120, min_ticks=30, sl=10x, tick_size=0.00005, spread=0.00010, mdt=1, qty=20k, client_id=71 | **RUNNING** (paper) | 2026-03-24 11:10 |
| V8 Rebreak | v8_confirmed_rebreak | USDJPY | pw=120, min_ticks=30, sl=10x, tick_size=0.005, spread=0.015, mdt=1, qty=20k, client_id=72 | **RUNNING** (paper) | 2026-03-24 11:10 |
| V8 Rebreak | v8_confirmed_rebreak | GBPUSD | pw=120, min_ticks=30, sl=10x, tick_size=0.00005, spread=0.00012, mdt=1, qty=20k, client_id=73 | **RUNNING** (paper) | 2026-03-24 11:10 |

## Research Queue

| Task | Priority | Owner | Status | Notes |
|------|----------|-------|--------|-------|
| Decide V6 keep/cut | MED | Nick | Deferred | V8 alone Sharpe 3.14 > V6+V8 combined 1.83. Keeping V6 running for more data |
| Add AUDUSD to paper? | LOW | Claude | **REJECTED** | Spread kills it: PnL/spread +1.03 at pw=120. Edge exists but too thin after costs. Same for NZDUSD (+0.56) and USDCHF (+0.64) |
| Session filter full WF (USDCAD, USDCHF) | MED | Claude | **COMPLETE** | USDCHF: VALIDATED, deploy London 07-12 (+1.34 lift). USDCAD: marginal (+0.65 lift), London+NY 08-16 best fixed session |
| V8 live code review | MED | Claude | **COMPLETE** | 5 must-fix items found (delayed data, no fill verification, dead loss limit, no position reconciliation, silent SL cancel). ~70 lines to fix. Safe for paper, NOT for real money |
| Implement code review fixes | HIGH | Cascade | **COMPLETE** | All 5 must-fix + 4 edge case + log collision fix. 12 changes total deployed 14:06 EST |
| Light review of fix implementation | LOW | Claude | **COMPLETE** | 5 edge case fixes recommended (~45 lines). 4/5 implemented, #5 (refuse-to-start) deferred to real money |
| Full GBPUSD data acquisition | LOW | Cascade | **IN PROGRESS** | Downloading via tick_vault. Have 2018-01 to ~2023-03, resuming to 2025-12 |
| Multi-scale analysis (smaller pw) | LOW | Claude | **COMPLETE** | Tested pw=10-120 on 8 pairs. Smaller scales strictly worse. Multi-scale portfolio dilutes Sharpe. No benefit to running multiple pw on same pair |
| New pair validation (GBPUSD, AUDUSD, NZDUSD, USDCHF) | MED | Claude | **COMPLETE** | Only GBPUSD viable (Sharpe +2.11, PnL/spread +1.79). Other 3 fail spread test. GBPUSD WF: avg OOS Sharpe +1.84, 6/6 positive |
| Hour/day exclusion analysis | LOW | Claude | **COMPLETE** | No systematic exclusions needed. No day is negative for any pair. 3 hours flagged but inconsistent across pairs (2/4 neg, 2/4 pos). pw=120 self-selects for liquid sessions |
| Confirm Cascade's param alignment | MED | Claude | **COMPLETE** | All 5 questions answered. See `claude-to-cascade/2026-03-23_param-confirmation.md` |

## Completed Research (last 30 days)

| Date | Task | Result | Journal Entry |
|------|------|--------|---------------|
| 2026-03-22 | V6+BE walk-forward (Claude) | BE look-ahead confirmed. V6 only works on XAUUSD (+0.71) and USDJPY (+0.66). 5/7 pairs negative | `RESPONSE_TO_WINDSURF.md` |
| 2026-03-22 | V8 pivot_window walk-forward (Claude) | pw=120 IS-optimal 5/7 pairs. ALL 7 pairs profitable OOS (avg Sharpe +2.31) | `RESPONSE_TO_WINDSURF.md` |
| 2026-03-22 | Multi-instrument V6/V8 research (Cascade) | 12-phase analysis. V6+BE claims debunked by Claude's WF. V8 multi-pair confirmed | `docs/research/multi-instrument-v6-v8-findings.md` |
| 2026-03-22 | GBPUSD V8 test (Claude) | V8 works: pw=90 OOS Sharpe +1.69. Need full data for proper validation | `docs/journal/2026-03-22_claude-research-session.md` |
| 2026-03-22 | Session filtering test (Claude) | USDCAD +1.28 lift, USDCHF +1.46 lift with London+NY. EURUSD/USDJPY marginal | `docs/journal/2026-03-22_claude-research-session.md` |
| 2026-03-23 | Session filter full 6-window WF (Claude) | USDCHF VALIDATED: London 07-12 avg OOS +3.69 vs 24hr +1.41 (+1.34 lift, 5/6 beat 24hr). USDCAD marginal: London+NY 08-16 avg OOS +3.04 vs 24hr +1.73 (+0.65 lift, 4/6 beat 24hr) | `docs/journal/2026-03-23_session-filter-walkforward.md` |
| 2026-03-22 | V6+V8 portfolio on XAUUSD (Claude) | V8 alone (Sharpe 3.14, DD 67) beats combined (1.83, DD 230). Correlation +0.17 | `docs/journal/2026-03-22_claude-research-session.md` |
| 2026-03-22 | Cross-pair correlation (Claude) | Avg correlation +0.042. Portfolio Sharpe +5.90. 2.44x diversification ratio | `docs/journal/2026-03-22_claude-research-session.md` |
| 2026-03-23 | Multi-scale analysis pw=10-120 (Claude) | Larger pw strictly better. pw=10-30 negative Sharpe everywhere. Fixed hold=60 beats proportional hold. Multi-scale portfolio never beats best single pw | `docs/v8_pw120_upgrade_brief.md` |
| 2026-03-23 | 4 new pair validation (Claude) | GBPUSD: Sharpe +2.11 at pw=120, WF avg OOS +1.84, 6/6 positive. AUDUSD/NZDUSD/USDCHF all fail spread viability | `docs/v8_pw120_upgrade_brief.md` |
| 2026-03-23 | GBPUSD walk-forward (Claude) | pw=120 IS-optimal 5/6 windows. Avg OOS Sharpe +1.84. 100% positive. STRONG verdict | `docs/v8_pw120_upgrade_brief.md` |
| 2026-03-23 | Full WF re-validation all 4 pairs (Claude) | EURUSD +3.96, XAUUSD +3.08, USDJPY +2.91, GBPUSD +1.84. All 100% positive OOS. All STRONG | `docs/v8_pw120_upgrade_brief.md` |
| 2026-03-23 | Hour/day exclusion analysis (Claude) | No toxic days (all positive). No consistent toxic hours. pw=120 naturally concentrates in liquid sessions | inline |
| 2026-03-23 | Portfolio stats pw=120 (Claude) | ~4.2 trades/day, ~1,067/yr. 32/32 pair-years profitable. EURUSD 60.8% WR, XAUUSD 56.1%, USDJPY 55.6%, GBPUSD 55.4% | `docs/v8_pw120_upgrade_brief.md` |

## Known Issues

- [x] ~~V8 EURUSD min_ticks=75 too high -- EURUSD gets ~60 ticks/bar, buy_ratio always NaN, zero trades~~ Fixed to 45 (Cascade, 2026-03-23)
- [x] ~~V8 XAUUSD SL order rejected: "price does not conform to minimum price variation"~~ Fixed: added tick_size rounding in submit_stop_order (Cascade, 2026-03-23)
- [x] ~~spread_cost=0.30 applied to ALL pairs -- EURUSD entry inflated from 1.16 to 1.31, instant CATASTROPHE_SL. USDJPY PnL also wrong~~ Fixed: added --spread-cost CLI arg, per-instrument values (Cascade, 2026-03-23)
- [x] ~~reqMarketDataType(3) = delayed data~~ Fixed: now defaults to 1 (live), configurable via --market-data-type (Cascade, 2026-03-23)
- [x] ~~No fill verification on orders (fire-and-forget)~~ Fixed: all 3 order methods check status, entry rolls back on failure (Cascade, 2026-03-23)
- [x] ~~max_daily_loss=500 never enforced~~ Fixed: safety_check() now checks daily_pnl, auto-closes position on breach (Cascade, 2026-03-23)
- [x] ~~No startup position reconciliation~~ Fixed: queries ib.positions() on startup, logs WARNING if orphaned position found (Cascade, 2026-03-23)
- [x] ~~Silent SL cancel failures (except:pass)~~ Fixed: now logs warning with error details (Cascade, 2026-03-23)
- [x] ~~Log file collision: all V8 processes shared logger name "v8_live" and timestamp-only filenames~~ Fixed: logger and filename now include pair_name (XAUUSD/EURUSD/USDJPY) (Cascade, 2026-03-23)
- [x] ~~`max_hold_bars=60` never optimized~~ Claude multi-scale sweep confirms: fixed hold=60 is optimal. Proportional hold (hold=pw) is worse for pw>=60. hold=60 gives larger-scale pivots time to develop (2026-03-23)
- [x] ~~pivot=nan in USDJPY signal log (Mar 24 09:00 UTC)~~ Display bug: live_engine read pivot from rolling array (can be NaN) instead of detector's internal state (always valid). One-line fix (Cascade, 2026-03-24)
- [ ] IB error 10147 "OrderId not found" on V8 exit -- harmless race condition but should investigate (Cascade, 2026-03-22)
- [ ] `.venv312/` not in `.gitignore` -- must stage files explicitly (Cascade, 2026-03-22)
- [x] ~~Old RESPONSE_TO_*.md and SESSION_HANDOVER_*.md files in repo root~~ -- cleaned up by Cascade (40 files moved to docs/)

## Parameter History

| Date | Param | Old Value | New Value | Reason | Validated? |
|------|-------|-----------|-----------|--------|------------|
| 2026-03-22 | V8 XAUUSD pivot_window | 60 | 120 | Claude's WF: IS picks pw=120 in 5/6 windows, OOS +3.08 | Yes (WF) |
| 2026-03-22 | V8 XAUUSD min_ticks | 50 | 15 | Claude's WF-validated config | Yes (WF) |
| 2026-03-22 | V8 EURUSD min_ticks | 50 | 75 | Claude's WF-validated config | Yes (WF) |
| 2026-03-23 | V8 EURUSD min_ticks | 75 | 45 | 75 never met in live (ticks ~60/bar). Lowered to allow signals | Empirical fix |
| 2026-03-23 | V8 EURUSD spread_cost | 0.30 | 0.00010 | 0.30 was XAUUSD default, caused bogus entry prices and instant SL | Bug fix |
| 2026-03-23 | V8 USDJPY spread_cost | 0.30 | 0.01 | Same bug as EURUSD, less severe but PnL was wrong | Bug fix |
| 2026-03-23 | V8 XAUUSD min_ticks | 15 | 50 | Align with brief's WF-validated value. IBKR gets ~60 ticks/bar, both pass | Yes (WF) |
| 2026-03-23 | V8 EURUSD min_ticks | 45 | 30 | Align with brief's WF-validated value | Yes (WF) |
| 2026-03-23 | V8 USDJPY min_ticks | 45 | 30 | Align with brief's WF-validated value | Yes (WF) |
| 2026-03-23 | V8 USDJPY spread_cost | 0.01 | 0.015 | Align with brief's researched value (more conservative) | **Yes (Claude confirmed)** |
| 2026-03-23 | V8 GBPUSD | — | Deployed | Added 4th V8 pair to paper. pw=120, min_ticks=30, spread=0.00012, client_id=73 | **Yes (Claude WF: avg OOS +1.84, 6/6 positive)** |
| 2026-03-22 | V6 target pair | USDJPY | XAUUSD | Claude's WF showed V6 USDJPY edge modest (+0.66), XAUUSD better (+0.71) | Yes (WF) |
| 2026-03-22 | V6 XAUUSD be_hours | 2.0 | 999 (OFF) | Claude's WF: IS picks BE=OFF 5/6 windows for XAUUSD | Yes (WF) |

## Live Trade Log

| Date | Time | Strategy | Pair | Direction | Entry | Exit | PnL | Exit Reason | Notes |
|------|------|----------|------|-----------|-------|------|-----|-------------|-------|
| 2026-03-22 | ~20:32 | V8 | XAUUSD | Short | ~4425 | 4421.05 | +$2.45 | TIME_STOP (60 bars) | First paper trade. Gold dropped $35 more after exit |
| 2026-03-22 | — | V8 | EURUSD | — | — | — | — | — | No trades: min_ticks=75 never met (bug). Fixed 2026-03-23 |
| 2026-03-22 | — | V6 | XAUUSD | — | — | — | — | — | Range too wide (3.90%, 170.97 pts) -- correctly skipped |
| 2026-03-23 | 10:50 | V8 | EURUSD | Long | 1.31 | 1.31 | -$0.16 | CATASTROPHE_SL (1 bar) | **BUG:** spread_cost=0.30 inflated entry. Not a real trade |
| 2026-03-23 | 11:05 | V8 | EURUSD | Long | 1.31 | 1.31 | -$0.16 | CATASTROPHE_SL (1 bar) | **BUG:** same spread_cost issue |
| 2026-03-23 | 11:13 | V8 | USDJPY | Short | 158.15 | 158.64 | -$0.64 | CATASTROPHE_SL (29 bars) | Spread_cost inflated entry by 0.15, SL legitimate but PnL wrong |
| 2026-03-23 | 21:30 | V8 | XAUUSD | Short | 4354.98 | 4337.47 | +$17.36 | TIME_STOP (60 bars) | Sell pressure confirmed (br=0.483). Gold trending down |
| 2026-03-23 | 22:43 | V8 | XAUUSD | Short | 4353.79 | 4342.26 | +$11.38 | TIME_STOP (60 bars) | Second short same pivot (br=0.472, gap=9) |
| 2026-03-23 | 20:59 | V8 | USDJPY | Long | 158.59 | 158.63 | +$0.03 | TIME_STOP (60 bars) | Flat at 20k size. Mechanics clean |
| 2026-03-24 | 09:28 | V8 | EURUSD | Short | ~1.16 | ~1.16 | -$0.00 | TIME_STOP (60 bars) | First EURUSD trade post-fix. Flat at 20k size |
| 2026-03-24 | 09:00 | V8 | USDJPY | Long | 158.83 | 158.83 | -$0.00 | TIME_STOP (60 bars) | pivot=nan display bug (fixed). Trade was legitimate |
| 2026-03-22-24 | — | V6 | XAUUSD | — | — | — | — | — | Range too wide 3 consecutive days (3.90%, ?, 3.22%). Gold vol too high for ORB |
