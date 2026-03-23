# Session Handover — 2026-03-22 13:00 EDT

## What Was Done

### Multi-Instrument Research: V6 ORB & V8 Confirmed Rebreak across 8 FX pairs

**Goal:** Determine if V6 (ORB) and V8 (Confirmed Rebreak) strategies work beyond XAUUSD.

**Pairs tested:** XAUUSD, EURUSD, GBPUSD, USDJPY, AUDUSD, NZDUSD, USDCAD, USDCHF  
**Data:** `data/1m_csv/*_1m_tick.csv` (Dukascopy, 2018-2026)  
**Script:** `scripts/research_multi_instrument.py` (4-phase reusable research tool)

### Key Findings

#### V8 Confirmed Rebreak — works on ALL 8 pairs (no changes needed)
| Top pairs | Sharpe |
|-----------|--------|
| EURUSD    | +2.80  |
| XAUUSD    | +2.25  |
| GBPUSD    | +2.25  |
| USDJPY    | +2.14  |
| Weakest (USDCHF) | +0.96 |

#### V6 ORB without BE — only USDJPY viable
- USDJPY: Sharpe +1.11 (the only clearly positive pair)
- XAUUSD: +0.38, GBPUSD: +0.36, EURUSD: +0.01
- AUDUSD, NZDUSD, USDCAD, USDCHF: all negative (-0.22 to -0.60)

#### V6 ORB WITH BE@2h — ALL pairs become strong (Sharpe +2.3 to +4.5)
Breakeven at 120 minutes is the single most impactful parameter. It transforms negative pairs into strong performers. BE is a structural requirement for V6, not an optimization.

#### Critical methodological finding
Initial V6 results on hourly-resampled bars were **dramatically inflated** (Sharpe +1.09 to +3.48). Re-verification on 1-minute bars with per-bar `avg_spread/2` fill simulation (V5 parity) revealed the true picture. **Always verify ORB-type strategies on 1m bars.**

### Files Created/Modified
- **`scripts/research_multi_instrument.py`** — Multi-phase research script (data audit, V6 1m backtest, V8 1m backtest, V6 param sweep). Reusable with `--phase` and `--pairs` args.
- **`docs/research/multi-instrument-v6-v8-findings.md`** — Full findings document with tables, tier classification, confidence assessment, and next steps.

### Files NOT modified (read-only analysis)
- `v6_orb_refactor/` — V6 strategy, engine, config (has BE in live code)
- `v8_confirmed_rebreak/` — V8 strategy, engine, config (NO BE in live code)
- `v5_xauusd_orb/backtest_1m.py` — Reference for fill simulation parity

## Current State

All research phases complete. Findings documented. No code changes to production strategies.

## Open Questions / Next Steps

1. **Implement BE in V8 live engine** — `v8_confirmed_rebreak/live/live_engine.py` `_check_exit()` only has CATASTROPHE_SL and TIME_STOP. Adding `be_bars` config + SL modification would improve V8. Should backtest BE on V8 first.
2. **Complete GBPUSD download** — only has 2018-2019 data (672 trades vs ~2000 for other pairs).
3. **Walk-forward validation** — V6+BE Sharpe values are high (3-4+); need out-of-sample confirmation per pair.
4. **Velocity filter calibration** — tick count varies by pair (XAUUSD=112 vs USDCHF=33); V6 velocity filter needs per-pair thresholds.
5. **Fix EURUSD data scaling** — prices are 100x (Dukascopy pipet issue). Sharpe/WR unaffected but absolute PnL is wrong.

## How to Re-run

```powershell
# Phase 1: Data audit
.venv312\Scripts\python.exe scripts/research_multi_instrument.py --phase 1

# Phase 2: V6 ORB baseline (1m bars)
.venv312\Scripts\python.exe scripts/research_multi_instrument.py --phase 2

# Phase 3: V8 Confirmed Rebreak baseline (1m bars)
.venv312\Scripts\python.exe scripts/research_multi_instrument.py --phase 3

# Phase 4: V6 param sweep (specific pairs)
.venv312\Scripts\python.exe scripts/research_multi_instrument.py --phase 4 --pairs USDJPY XAUUSD EURUSD

# All phases
.venv312\Scripts\python.exe scripts/research_multi_instrument.py --phase all
```
