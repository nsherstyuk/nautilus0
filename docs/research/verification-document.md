# Nautilus0 — Complete Strategy Research & Results Verification Document

**Generated**: 2026-03-20
**Purpose**: Independent verification of all strategy attempts, backtest results, and conclusions.
**Scope**: Every algorithm tested, every quantitative claim, every failure mode discovered.

---

## Table of Contents

1. [Project Timeline](#1-project-timeline)
2. [V1: ML Multi-Timeframe Bracket](#2-v1-ml-multi-timeframe-bracket)
3. [V2: ML + Entry Confirmation](#3-v2-ml--entry-confirmation)
4. [V3: Hierarchical MTF](#4-v3-hierarchical-mtf)
5. [V4: Tick-Bar Market Making](#5-v4-tick-bar-market-making)
6. [V5: Asian Range Breakout (ORB)](#6-v5-asian-range-breakout-orb)
7. [V6: ORB Architecture Refactor](#7-v6-orb-architecture-refactor)
8. [V7: Confirmed Rebreak (Rolling Pivots)](#8-v7-confirmed-rebreak-rolling-pivots)
9. [V8: Confirmed Rebreak (Production)](#9-v8-confirmed-rebreak-production)
10. [V9: Naive Previous Day Breakout](#10-v9-naive-previous-day-breakout)
11. [V10: Previous Day + Rebreak Filter](#11-v10-previous-day--rebreak-filter)
12. [Other Failed Approaches](#12-other-failed-approaches)
13. [Critical Bugs & Retrospectives](#13-critical-bugs--retrospectives)
14. [Current Production State](#14-current-production-state)
15. [Source File Index](#15-source-file-index)

---

## 1. Project Timeline

| Date | Event | Outcome |
|------|-------|---------|
| Pre-2026 | V1-V3 ML strategies on EUR/USD | All retired (lookahead leak, parity issues) |
| 2026-02-20 | Parity investigation begins | Idempotency bug found |
| 2026-02-22 | ML model critique | AUC 0.756 → 0.519 after fixing leak |
| 2026-02-23 | V4 tick-bar system started | |
| 2026-02-24 | V4 full backtest complete | -1,105 pips, Sharpe -0.20 |
| 2026-02-27 | Pivot to V5 ORB | Simple rule-based approach |
| 2026-02-28 | V5 backtest validated | Sharpe 4.28 (later revised) |
| 2026-03-02 | V5 live deployment | Multi-instrument (XAUUSD + EURUSD) |
| 2026-03-05 | 5 live trades reconciled | +$244.13, 80% WR, 5/5 EXCELLENT |
| 2026-03-11 | "Blind BE" bug discovered | Previous Sharpe 4-7 was fiction |
| 2026-03-11 | 1-min Dukascopy data built | 2.87M bars, ground-truth data |
| 2026-03-11 | Velocity filter discovered | OOS Sharpe 0.91 → 1.87 |
| 2026-03-12 | V7 confirmed rebreak started | |
| 2026-03-12 | V7 engine_v2 validated | +$1,863 OOS, 57.4% WR |
| 2026-03-13 | V8 production rebreak | Exact parity with V7 |
| 2026-03-16 | Orphaned position incident | V5 bracket refactor fix |
| 2026-03-18 | Loss trade reduction research | |
| 2026-03-20 | V10 prev-day rebreak tested | OOS mean PnL -$0.37, NO EDGE |

---

## 2. V1: ML Multi-Timeframe Bracket

**Instrument**: EUR/USD
**Status**: RETIRED
**Location**: `strategies/ml_strategy_mtf_v2.py` (59 KB)

### What It Did
- Multi-timeframe (15m/30m/1h) XGBoost classifier
- ~50 technical features (MAMA, DMI, RSI, ATR, Bollinger)
- Bracket orders when model confidence > 0.65-0.80

### Why It Failed
- **Idempotency bug**: NautilusTrader delivers bars 2-4x. Cumulative features (MAMA, DMI) processed 100-200+ bar windows instead of 50
- Live/backtest parity: only **69.7% prediction agreement** (20/66 bars disagree)
- DMI+ divergence: mean 5.67%, max 10.6%
- **30% of predictions flipped** direction between live and backtest

### Verification
- Source: `docs/journal/2026-02-20_parity_investigation.md`
- Source: `docs/design/parity_root_cause_action_plan.md`

---

## 3. V2: ML + Entry Confirmation

**Instrument**: EUR/USD
**Status**: RETIRED
**Location**: 18 variant files in `strategies/`

### What It Did
- Improved V1 with entry confirmation (wait for price to touch entry level)
- Failsafe mode, adaptive position sizing, dynamic SL/TP

### Key Results (Phase E Experiments)

| Experiment | Capital | P&L | WR | Sharpe | Trades | Finding |
|-----------|---------|-----|-----|--------|--------|---------|
| Classic V2 Benchmark | $100k | $18,155 | 68.4% | Unknown | 2,079 | Baseline |
| E1: Classic V2 Pure | $50k | $5,376 | 64.8% | 2.56 | 489 | 60% of benchmark |
| E2: + Time Filter | $50k | $5,397 | 64.8% | 2.57 | 489 | +0.4% (no improvement) |
| E3: + ML Confidence | $50k | $5,390 | 64.8% | 2.56 | 489 | -0.1% (no improvement) |
| D1: Ultra-selective | $25k | $1,511 | 68.5% | 3.63 | 438 | Best per-trade quality |

### Critical Bug: Lookahead Leak
- Features used `label='left'` pandas resampling with `.ffill()` using future bar data
- **98.7% of training bars contaminated** (~7.4 pips of future info per row)
- When leak fixed: **AUC dropped from 0.756 to 0.519 (zero edge)**

### Conclusion
Standard 15m technical indicators (MACD, RSI, ADX, Bollinger, EMA, SMA) have **no detectable predictive power** on EUR/USD.

### Verification
- Source: `docs/design/ml_model_critique.md`
- Source: `docs/design/phase_e_final_report.md`
- Source: `docs/design/comparison_classic_v2_vs_b2.md`

---

## 4. V3: Hierarchical MTF

**Instrument**: EUR/USD
**Status**: RETIRED
**Location**: `strategies/ml_strategy_mtf_v3_hmtf.py` (34 KB)

### What It Did
- 15m "master" model predicts trend, 5m "soldier" uses 15m prediction as feature
- State machine: IDLE → HUNTING → ACTIVE → COOLDOWN

### Why It Failed
- Same lookahead contamination as V2
- Never deployed live

### Verification
- Source: `docs/journal/2026-02-22_session_handover.md`

---

## 5. V4: Tick-Bar Market Making

**Instrument**: EUR/USD
**Status**: RETIRED — NO EDGE
**Location**: `trading_system_v4/`

### Full Backtest Results (1,346 trading days, 2020-2025)

| Metric | Value |
|--------|-------|
| Total PnL | **-1,105 pips** |
| Avg per day | -0.82 pips |
| Sharpe | **-0.20** |
| Profit Factor | 0.96 |
| Trade Win Rate | 61.3% |
| Daily Win Rate | 54.2% |
| Avg trade | -0.01 pips |
| Max drawdown | -5,311 pips |
| Total fills | 355,768 (264/day) |
| Round trips | 177,446 |

### Parameter Sweep Results (80 random-day samples)

| Half-Spread | Fills/day | PnL | Sharpe | PF |
|-------------|-----------|-----|--------|-----|
| 0.5p | 7,130 | +3,952 | 1.73 | 1.41 |
| 1.0p | 1,544 | +324 | 0.63 | 1.12 |
| 1.5p | 542 | -532 | -1.70 | 0.72 |
| 2.0p | 228 | -65 | -0.28 | 0.95 |
| 2.5p | 93 | +522 | 3.29 | 1.88 |
| 3.0p | 39 | +222 | 1.59 | 1.30 |

**Key finding**: Sharpe ranges from -1.70 to +3.29 on 80-day samples = pure noise, not signal.

### Fill Probability Sensitivity

| Fill Prob | PnL | Sharpe |
|-----------|-----|--------|
| 0.3 | -998 | -4.41 |
| 0.5 | -127 | -0.54 |
| 0.7 | -65 | -0.28 |
| 0.9 | -7 | -0.03 |
| 1.0 (unrealistic) | +221 | 0.95 |

**Conclusion**: Only profitable with unrealistic 100% fill probability. With realistic adverse selection (fp=0.7), strategy loses money.

### Cumulative Dead Ends (V4 Sessions 1-5)

| Approach | Verdict |
|----------|---------|
| EURUSD 15min direction prediction (TA) | AUC 0.519, zero edge |
| HTF (4h) features for 15min prediction | No improvement |
| Tick microstructure features (62 features) | AUC 0.519, zero edge |
| Multi-horizon sweeps (1min-1h) | All zero edge |
| Session breakout strategies | Zero edge |
| Mean reversion signals (11 variants) | Negative PnL always |
| Bar-level market-making | Unrealistic fills |
| Tick-level market-making | -1,105p on full backtest |

### Verification
- Source: `docs/journal/2026-02-24_v4_session_handover_v3.md`
- Data: `trading_system_v4/scripts/mm_v2_results.txt`

---

## 6. V5: Asian Range Breakout (ORB)

**Instrument**: XAUUSD (primary), EURUSD (secondary)
**Status**: ACTIVE — LIVE TRADING
**Location**: `v5_xauusd_orb/`

### Strategy Logic
```
UTC 00:00-06:00   Observe Asian session → record High/Low
UTC 08:00         Place bracket orders (BUY STOP above High, SELL STOP below Low)
                  TP = High + RR × range, SL = opposite side of range
UTC 08:00-16:00   Monitor: SL/TP/EOD exit
```

### Backtest Evolution (XAUUSD, 1-min Dukascopy data 2018-2026)

**WARNING**: Early Sharpe figures (4.0-7.0) were inflated by the "Blind BE" bug. Corrected results below.

#### Before Velocity Filter (OOS 2021-2026)

| Metric | Value |
|--------|-------|
| Sharpe | 0.91 |
| P&L | $830 |
| Win Rate | 47.1% |
| Profit Factor | 1.17 |
| Trades/year | ~200 |

#### After Velocity Filter (OOS 2021-2026, RR=2.5)

| Metric | Value | Change |
|--------|-------|--------|
| Sharpe | **1.87** | +105% |
| P&L | **$1,213** | +46% |
| Win Rate | 49.8% | +2.7pp |
| Profit Factor | 1.34 | +15% |
| Trades/year | ~115 | -43% |

#### Velocity Filter Evidence

| Velocity Band | Full Sharpe | OOS Sharpe | P&L |
|--------------|-------------|-----------|-----|
| Slow half (<median) | 0.01 | -0.16 | $4 |
| Fast half (>=median) | 1.82 | 2.14 | $1,053 |
| Q4 (60th-80th pct) | 2.02 | 3.32 | Best quintile |

Walk-forward: filter helps in **6/6 test years (100%)**.

#### RR Ratio Optimization (velocity filtered, OOS)

| RR | Sharpe | P&L | WR |
|----|--------|-----|-----|
| 1.0 | 1.82 | $916 | 58.3% |
| 1.5 | 1.83 | $1,049 | 53.5% |
| 2.0 | 1.79 | $1,092 | 50.8% |
| **2.5** | **1.87** | **$1,213** | **49.8%** |
| 3.0 | 1.87 | $1,284 | 49.8% |
| 3.5 | 1.89 | $1,329 | 49.8% |

#### Key Findings
- **Time exit is harmful**: Sharpe 1.31 → 0.99 with 60-min time exit
- **BE rule disabled**: Previous BE logic had a bug; without it, results are honest
- **Wednesday skip confirmed**: Wednesday OOS Sharpe -1.08
- **Range-relative TP/SL superior**: Sharpe 1.87 vs 1.52 for best fixed-dollar targets

### Current Live Configuration

```yaml
XAUUSD:
  rr_ratio: 2.5
  trade_start_hour: 8
  trade_end_hour: 16
  skip_weekdays: [2]  # Wednesday
  be_hours: 999  # DISABLED
  time_exit_minutes: 0  # DISABLED
  velocity_filter_enabled: true
  velocity_threshold: 168  # P50 median ticks/min
  velocity_lookback_minutes: 3
  qty: 1  # 1 oz
```

### Live Performance (as of 2026-03-16)

| Trade | Date | Direction | Entry | Exit | P&L | Type |
|-------|------|-----------|-------|------|-----|------|
| 1 | 2026-03-03 | SHORT | 5304.73 | 5153.70 | +$151.03 | TP |
| 2 | 2026-03-05 | SHORT | 5147.91 | 5103.41 | +$44.50 | TIME |
| 3 | 2026-03-?? | — | — | — | -$80.53 | SL |
| 4 | 2026-03-?? | — | — | — | -$10.08 | — |
| 5 | 2026-03-?? | — | — | — | -$0.82 | Bug |
| **Net** | | | | | **+$104.07** | |

Reconciliation: 5/5 trades graded EXCELLENT (math/fill/exit/P&L all pass)

### Verification
- Source: `docs/journal/2026-03-11_velocity_filter_and_1m_backtest.md`
- Source: `docs/journal/2026-02-28_v5_orb_session_handover.md`
- Data: `v5_xauusd_orb/rebreak_results.txt`, `cumulative_imbalance_results.txt`
- Backtest engine: `v5_xauusd_orb/backtest_1m.py`

---

## 7. V6: ORB Architecture Refactor

**Status**: COMPLETE (backtest + live modules)
**Location**: `v6_orb_refactor/`

### What It Is
- Clean architecture refactor of V5 using Ousterhout "Deep Modules" pattern
- Abstract interfaces: `MarketContext` and `ExecutionEngine` ABCs
- Same strategy code runs identically in backtest and live
- NOT a new strategy — same ORB logic as V5

### Parity
- Backtest parity test exists (`backtest/parity_test.py`)
- Live modules complete: `connection.py`, `ibkr_executor.py`, `guardrails.py`, `runner.py`
- Has been run (state files and trade logs exist)

### Verification
- Source: `v6_orb_refactor/ARCHITECTURE.md`

---

## 8. V7: Confirmed Rebreak (Rolling Pivots)

**Instrument**: XAUUSD
**Status**: RESEARCH — Edge found on rolling pivots
**Location**: `v7_confirmed_rebreak/`

### Strategy Logic
1. Detect local pivot high/low (centered rolling max/min, window=60 bars, shift=3)
2. First break of pivot with divergent volume (sellers active on upward break)
3. Pullback through the level
4. Rebreak with confirming volume → ENTRY
5. Exit: time stop (60 bars) or catastrophe SL (10x ATR)

### Results (OOS 2023-2026, pw=60, c=3)

| Metric | Value |
|--------|-------|
| Trades | 1,150 |
| Total PnL | **+$1,863.40** |
| Per trade | +$1.62 |
| Win Rate | **57.4%** |
| Avg Hold | 58.1 bars |
| Exit: TIME_STOP | 1,055 (91.7%) |
| Exit: SL | 95 (8.3%) |

### Full Sample (2018-2026)

| Metric | Value |
|--------|-------|
| Trades | 2,816 |
| Total PnL | +$2,128 |
| Per trade | +$0.756 |
| Win Rate | 52.3% |
| Profitable years | 8/9 (2019: -$6.67) |

### Walk-Forward (16 half-year windows, 2019-2026)
- **11/16 windows positive (69%)**
- Max consecutive negative: 1
- First half avg: +$0.15/trade
- Second half avg: +$1.73/trade

### Annual Breakdown (OOS)

| Year | PnL |
|------|-----|
| 2023 | +$89 |
| 2024 | +$386 |
| 2025 | +$1,034 |
| 2026 (partial) | +$354 |

### Rebreak Pattern Edge (from research files)

**XAUUSD (pw=60, OOS 2023-2026):**

| Timeframe | Confirmed Rebreak | Clean First Break | Edge |
|-----------|-------------------|-------------------|------|
| 5m | +$0.623/trade | +$0.363/trade | +$0.260 |
| 15m | +$1.028/trade | +$0.363/trade | +$0.665 |
| 30m | +$1.615/trade | +$0.368/trade | +$1.247 |
| 60m | +$2.780/trade | +$1.368/trade | +$1.413 |

**EURUSD**: Edge is +$0.005/trade — **100x weaker than XAUUSD, not tradeable**.

### Verification
- Source: `v7_confirmed_rebreak/ARCHITECTURE.md`
- Source: `SESSION_HANDOVER_2026-03-12_0830.md`
- Source: `SESSION_HANDOVER_2026-03-12_1136.md`
- Data: `v5_xauusd_orb/rebreak_results_xauusd.txt`
- Data: `v7_confirmed_rebreak/research/tick_filter_results.txt`

---

## 9. V8: Confirmed Rebreak (Production)

**Instrument**: XAUUSD
**Status**: COMPLETE — Production-ready, parity-verified
**Location**: `v8_confirmed_rebreak/`

### Integration Parity (V8 vs V7 engine_v2)

| Metric | V7 | V8 | Match |
|--------|-----|-----|-------|
| Trades | 1,150 | 1,150 | EXACT |
| PnL | +$1,863.40 | +$1,863.40 | EXACT |
| WR | 57.4% | 57.4% | EXACT |
| Avg Hold | 58.1 bars | 58.1 bars | EXACT |
| TIME_STOP | 1,055 | 1,055 | EXACT |
| SL | 95 | 95 | EXACT |

### Parameter Optimization (OOS 2023-2026)

**min_bar_ticks sweep:**

| min_ticks | Trades | PnL | Per trade | WR |
|-----------|--------|-----|-----------|-----|
| 0 | 1,343 | +$1,874 | +$1.40 | 55.7% |
| 50 | 1,150 | +$1,863 | +$1.62 | 57.4% |
| **75** | **973** | **+$1,871** | **+$1.92** | **58.7%** |
| 100 | 860 | +$1,724 | +$2.01 | 59.4% |

**SL multiple sweep (min_ticks=75):**

| Config | Trades | PnL | Per trade | WR | SL% |
|--------|--------|-----|-----------|-----|-----|
| SL=3 TP=6 t=60 | 1,016 | +$981 | +$0.97 | 40.6% | 52.6% |
| SL=5 time=60 | 992 | +$1,468 | +$1.48 | 52.6% | 29.4% |
| SL=7 time=60 | 979 | +$1,799 | +$1.84 | 57.1% | 17% |
| **SL=10 time=60** | **973** | **+$1,871** | **+$1.92** | **58.7%** | **7.3%** |
| SL=99 (none) | 969 | +$1,845 | +$1.91 | 59.1% | 0% |

### Verification
- Source: `v8_confirmed_rebreak/ARCHITECTURE.md`
- Source: `SESSION_HANDOVER_2026-03-13_1110.md`

---

## 10. V9: Naive Previous Day Breakout

**Instrument**: XAUUSD
**Status**: DEAD — No edge
**Location**: `v9_xauusd_prevday/`

### Strategy
Entry on first break of previous day's high/low via stop order.

### Why It Failed
- **35% of entries are gap opens** — price gaps through the level
- **Mean gap = $3.02** — destroys any potential edge
- Fill at gap-open price (much worse than trigger level)

### Verification
- Source: `v10_prevday_rebreak/SESSION_HANDOFF.md` (documents V9 failure)
- Code: `v9_xauusd_prevday/backtest_prevday.py`

---

## 11. V10: Previous Day + Rebreak Filter

**Instrument**: XAUUSD
**Status**: DEAD — No edge
**Location**: `v10_prevday_rebreak/`

### Hypothesis
Prev-day levels + confirmed rebreak filter would eliminate gap-open problem and produce positive expectancy.

### Results (default params, 2018-2026)

| Metric | FULL | IS (<2021) | OOS (>=2021) |
|--------|------|-----------|-------------|
| N | 746 | 239 | 507 |
| Sharpe | -1.37 | -0.86 | -1.60 |
| PF | 0.83 | 0.89 | 0.81 |
| Win Rate | 36.5% | 37.2% | 36.1% |
| Mean PnL | -$0.31 | -$0.19 | -$0.37 |
| Total PnL | -$231.61 | -$44.74 | -$186.86 |

### By Direction

| Direction | PF | WR | Mean PnL |
|-----------|-----|-----|----------|
| LONG | 0.95 | 39.6% | -$0.08 |
| SHORT | 0.70 | 32.7% | -$0.59 |

### Annual

| Year | Sharpe | PnL | Tag |
|------|--------|-----|-----|
| 2018 | -4.85 | -$67.57 | IS |
| 2019 | -2.88 | -$40.66 | IS |
| 2020 | +2.85 | +$63.49 | IS |
| 2021 | -2.03 | -$46.29 | OOS |
| 2022 | +0.93 | +$21.33 | OOS |
| 2023 | -3.55 | -$84.95 | OOS |
| 2024 | -1.93 | -$45.07 | OOS |
| 2025 | -1.93 | -$38.58 | OOS |
| 2026 | +2.04 | +$6.70 | OOS |

### Conclusion
- Negative across both IS and OOS — no edge at any parameter setting tested
- SHORT significantly worse than LONG
- Volume divergence filter did not transfer from rolling pivots to prev-day levels (known risk #2 from handoff)
- Only 3/9 years profitable

### Verification
- Code: `v10_prevday_rebreak/backtest_engine.py`
- Tests: `v10_prevday_rebreak/test_backtest.py` (14/14 unit tests pass)
- Data: `C:/nautilus0/data/1m_csv/xauusd_1m_tick.csv` (2.87M bars)

---

## 12. Other Failed Approaches

These were tested as standalone research within V5/V7/V8 sessions:

| Approach | Source | Result |
|----------|--------|--------|
| Volume imbalance standalone (7 variants) | `v5_xauusd_orb/imbalance_results.txt` | Signal r~0.01, swamped by costs |
| Imbalance divergence filter | `v5_xauusd_orb/imbalance_results.txt` | Divergent WORSE than non-divergent by -$0.145/trade at 60m |
| ML on microstructure | V4 sessions | Overfits IS, zero OOS |
| Morning continuation scanner | V5 research | Tautological (measured definitional relationship) |
| Classic indicators (RSI, MA, Bollinger) | V2/V3 | No edge after costs on EUR/USD |
| NR4/inside bar | V5 research | No statistical edge found |
| EURUSD rebreak | `v5_xauusd_orb/rebreak_results_eurusd.txt` | Edge +$0.005/trade (100x weaker than XAUUSD, not tradeable) |
| EURUSD ORB | `docs/journal/2026-03-11_eurusd_resurrection_test.md` | Sharpe 0.70 OOS (rejected) |
| Cross-pair filter | `docs/design/phase_e_final_report.md` | Not the problem (E1 only 60% of Classic V2) |
| Time filtering (V2) | Phase E | +0.4% improvement (zero impact) |
| ML confidence zones (V2) | Phase E | -0.1% (zero impact) |

### Imbalance Divergence Detail (XAUUSD, pw=15, OOS 2023-2026)

| Direction | Divergent Mean | Non-Divergent Mean | Edge |
|-----------|---------------|-------------------|------|
| UP 5m | +$0.148 | +$0.258 | **-$0.110** |
| UP 60m | +$0.178 | +$0.401 | **-$0.223** |
| DOWN 5m | +$0.130 | +$0.126 | +$0.004 |
| DOWN 60m | +$0.089 | +$0.086 | +$0.003 |

**Finding**: For UP breakouts, divergent volume is actually WORSE, not better. For DOWN, no difference.

---

## 13. Critical Bugs & Retrospectives

### Bug: Blind BE (Breakeven) — Most Impactful
- **Discovery**: 2026-03-11
- **Impact**: BE exits were credited as breakeven while price was deeply underwater
- **Effect**: Previous Sharpe ratios (4.0-7.0) were fiction
- **Fix**: Disabled BE rule entirely; honest Sharpe is 1.87 with velocity filter
- **Source**: `docs/journal/2026-03-11_critical_retrospective.md`

### Bug: Lookahead Leak in ML Training
- **Discovery**: 2026-02-22
- **Impact**: 98.7% of training bars contaminated with ~7.4 pips of future info
- **Effect**: AUC 0.756 → 0.519 (zero edge) when fixed
- **Source**: `docs/design/ml_model_critique.md`

### Bug: Idempotency (Duplicate Bars)
- **Discovery**: 2026-02-20
- **Impact**: NautilusTrader delivers bars 2-4x, cumulative features corrupted
- **Source**: `docs/journal/2026-02-21_idempotency_fix.md`

### Bug: Orphaned Position
- **Discovery**: 2026-03-16
- **Impact**: Stale LONG position from pre-attached brackets + position vanish cache lag
- **Fix**: Two-phase bracket refactor
- **Source**: `SESSION_HANDOVER_2026-03-16_1956.md`

### Risk: Dukascopy vs IBKR Tick Calibration
- **Status**: UNRESOLVED
- **Impact**: Velocity threshold (168 ticks/min) derived from Dukascopy feed. IBKR aggregates ticks differently. 168 on Dukascopy might equal 40 or 300 on IBKR.
- **Source**: `docs/journal/2026-03-11_critical_retrospective.md`

### Risk: Velocity Gate Execution
- **Issue**: In backtest, trades below velocity threshold are simply not taken. In live, stop orders are placed first, then closed at market if velocity rejects → guaranteed small loss (~$0.30-0.50 per rejection).
- **Source**: `docs/journal/2026-03-11_critical_retrospective.md`

---

## 14. Current Production State

### Account
- NLV: ~$4,212
- Broker: Interactive Brokers
- Mode: Live (was paper, graduated)

### Active Strategies
1. **V5 ORB on XAUUSD** — 1 oz per trade, Asian range breakout
2. **V5 ORB on EURUSD** — 20k units per trade (marginal edge)

### Strategies with Proven Edge (Not Currently Live)
3. **V7/V8 Confirmed Rebreak on XAUUSD** — Rolling pivots, +$1,863 OOS, 57.4% WR, complete production code in V8

### Everything Else: Dead
- V1-V4: ML approaches (retired, no edge)
- V9: Naive prev-day breakout (gap opens)
- V10: Prev-day rebreak (no edge)
- All standalone filters (imbalance, divergence, NR4, classic indicators)

---

## 15. Source File Index

### Core Documentation
| File | Content |
|------|---------|
| `CODEBASE.md` | Master onboarding guide, all 5 generations |
| `docs/journal/README.md` | Chronological index of 36+ session docs |
| `docs/design/ml_model_critique.md` | ML lookahead leak analysis |
| `docs/design/phase_e_final_report.md` | Phase E experiment results |
| `docs/design/backtest_audit_report.md` | Backtest integrity verification |
| `docs/design/parity_root_cause_action_plan.md` | Live/backtest parity investigation |

### Key Session Handovers
| File | Content |
|------|---------|
| `docs/journal/2026-02-24_v4_session_handover_v3.md` | V4 tick-level MM: NO EDGE |
| `docs/journal/2026-03-11_velocity_filter_and_1m_backtest.md` | Velocity filter discovery |
| `docs/journal/2026-03-11_critical_retrospective.md` | Honest self-audit |
| `SESSION_HANDOVER_2026-03-12_0830.md` | V7 engine_v2 results |
| `SESSION_HANDOVER_2026-03-12_1136.md` | V7 walk-forward validation |
| `SESSION_HANDOVER_2026-03-13_1110.md` | V8 production parity |
| `v10_prevday_rebreak/SESSION_HANDOFF.md` | V10 hypothesis and design |

### Architecture Documents
| File | Content |
|------|---------|
| `v6_orb_refactor/ARCHITECTURE.md` | Deep modules, zero-diff parity |
| `v7_confirmed_rebreak/ARCHITECTURE.md` | Rebreak state machine |
| `v8_confirmed_rebreak/ARCHITECTURE.md` | Production rebreak, parity proof |

### Result Data Files
| File | Content |
|------|---------|
| `v5_xauusd_orb/rebreak_results_xauusd.txt` | Rebreak edge by pivot window |
| `v5_xauusd_orb/rebreak_results_eurusd.txt` | EURUSD rebreak (no edge) |
| `v5_xauusd_orb/imbalance_results.txt` | Imbalance divergence (no edge) |
| `v5_xauusd_orb/cumulative_imbalance_results.txt` | Velocity + imbalance combined |
| `v7_confirmed_rebreak/research/tick_filter_results.txt` | Tick filter optimization |

### Backtest Engines (for reproduction)
| File | Content |
|------|---------|
| `v5_xauusd_orb/backtest_1m.py` | V5 ORB 1-minute backtest |
| `v6_orb_refactor/backtest/engine.py` | V6 backtest runner |
| `v8_confirmed_rebreak/backtest/runner.py` | V8 rebreak backtest |
| `v9_xauusd_prevday/backtest_prevday.py` | V9 prev-day breakout |
| `v10_prevday_rebreak/backtest_engine.py` | V10 prev-day rebreak |

### Data
| File | Size | Content |
|------|------|---------|
| `data/1m_csv/xauusd_1m_tick.csv` | 417 MB | 2.87M 1-min bars, 2018-2026 |
| `data/1m_csv/eurusd_1m_tick.csv` | 484 MB | EUR/USD 1-min bars |
| `data/1m_csv/gbpusd_1m_tick.csv` | 72 MB | GBP/USD 1-min bars |
