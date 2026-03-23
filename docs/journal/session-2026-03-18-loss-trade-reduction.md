# Session Notes: Loss Trade Reduction Research
**Date:** 2026-03-18
**Status:** CONCLUDED — all candidate filters investigated, research question answered
**Research Standards:** layer1-research-standards.md governs this work

---

## Research Question

**How can we reduce or eliminate loss trades in the v5 ORB (Asian Range Breakout) strategy?**

The strategy defines a range during the Asian session (00:00-06:00 UTC), waits through a 2-hour gap (06:00-08:00 UTC), then trades breakouts during the London session (08:00-16:00 UTC). The core problem: ~27-30% of trades break the range but fail to follow through — price gets stuck and returns to the range.

**Scope boundaries:** XAUUSD on 1-minute tick-derived bars (2018-2026). Filters must be knowable BEFORE trade entry (no lookahead). Target: fewer but higher-quality trades. Human is comfortable with 2-3 trades/week if win rate is high.

**Priority:** Prevention of loss trades (pre-entry filtering) over management of open positions.

---

## Baseline Performance (1-min data)

- **Trades:** 1,613 (2018-2026), ~3.1/week
- **Sharpe:** 0.76 | PF: 1.14 | WR: 47.2%
- **Mean P&L:** +$0.59/trade | Total: +$949.72
- **Max DD:** -$210.16
- **OOS (2021+):** Sharpe 0.91, N=1,013

---

## Completed Research & Findings

### Direction 1: Category B Filter — MODERATE SIGNAL
**Script:** `research_category_b_filter.py` → `category_b_filter_results.txt`

**1-min results (1,613 trades):**

| Category | N | % | Sharpe IS | Sharpe OOS | WR | SL% | TP% |
|----------|---|---|-----------|-----------|-----|-----|-----|
| A (gap-open) | 623 | 38.6% | 0.63 | 1.18 | 49.9% | 26.5% | 27.6% |
| **B (returned)** | **432** | **26.8%** | **0.44** | **0.43** | **42.6%** | **40.0%** | **14.4%** |
| C (clean) | 558 | 34.6% | 1.16 | 1.07 | 47.8% | 29.4% | 13.1% |

**Filter impact:** Removing Cat B → OOS Sharpe 0.91 → 1.12, WR 47.1% → 49.9%
**Walk-forward:** Helps 5/9 years (56%) — better than chance but not robust
**Problem:** Max DD worsened (-210 → -308), total P&L dropped ($950 → $794)

**⚠️ MISMATCH (evidential):** The 5-min data showed Cat A with Sharpe 6.55 and Cat B with Sharpe 0.13 (zero edge). The 1-min data shows Cat A at 0.63 and Cat B at 0.44 — very different picture. Root cause: the 5-min analysis used ideal fills at the range level for gap-opens, massively inflating Cat A performance. The 1-min engine models realistic gap fills. **The 1-min results are more trustworthy.** Cat B is weak but has a small positive edge, not zero.

**Decision:** Cat B filter alone is not a strong enough standalone signal. Should be combined with other filters.

### Direction 2: Range Quality Features — MAJOR FINDINGS (Counter-Intuitive)
**Script:** `research_range_quality.py` → `range_quality_results.txt`

**⚠️ CORE FINDING: Multiple features showed the OPPOSITE of what published literature predicted.**

#### Finding 2a: NR4 Inversion (CONTRADICTS Crabel)
| Group | N | Sharpe IS | Sharpe OOS | WR |
|-------|---|-----------|-----------|-----|
| NR4 days (narrowest of 4) | 331 | -0.37 | **-0.42** | 43.5% |
| Non-NR4 days | 1,279 | 1.02 | **1.22** | 48.2% |

Crabel's NR4 concept predicts narrow ranges → better breakouts. **Our data shows the opposite.** Filtering OUT NR4 days removes 20% of trades and improves OOS Sharpe to 1.22. This is the **strongest single filter found**.

**Interpretation:** In XAUUSD, a very narrow Asian range likely reflects low participation (low liquidity, holidays) rather than volatility coiling. Low-participation ranges produce false breakouts.

**Confidence:** `context_complete`: UNFAVORABLE (XAUUSD only). `no_unstated_assumptions`: UNFAVORABLE (Crabel studied daily bars on futures, not intra-session FX). `evaluator_agreement`: FAVORABLE (data is unambiguous). **Status: converging. Needs multi-instrument validation.**

#### Finding 2b: POC Misalignment Signal (CONTRADICTS Market Profile theory)
| Group | N | Sharpe IS | Sharpe OOS |
|-------|---|-----------|-----------|
| Aligned (POC supports breakout) | 868 | 0.23 | 0.25 |
| **Misaligned (POC opposes breakout)** | **745** | **1.33** | **1.61** |

Breakouts AGAINST the Asian session's volume-weighted consensus work dramatically better. When POC is in the bottom half of the range and price breaks upward (or vice versa), the breakout represents genuine new information rather than range-boundary noise.

**VWAP shows the same pattern:** Misaligned OOS Sharpe 1.34 vs Aligned 0.48.

**Interpretation:** Breakouts that contradict the Asian session's "accepted value" likely represent institutional order flow at the London open — genuine directional intent, not just stop-hunting.

**Confidence:** `context_complete`: UNFAVORABLE (single instrument). `no_unstated_assumptions`: MIXED (causal story is plausible but unverified). `evaluator_agreement`: FAVORABLE (data is clear). **Status: converging.**

#### Finding 2c: Intra-Range Volatility — Goldilocks Effect
| Quintile | Description | Sharpe IS | Sharpe OOS |
|----------|------------|-----------|-----------|
| Q1 | Very low volatility | -0.31 | -0.19 |
| **Q2-Q3** | **Moderate volatility** | **1.41-1.76** | **2.06-2.08** |
| Q5 | Very high volatility | -0.31 | -0.84 |

Too calm = no energy for breakout. Too wild = already exhausted. Moderate intra-range volatility is the sweet spot.

#### Finding 2d: Touch Count — Fewer Touches = Better
| Quintile | Touches | Sharpe IS | Sharpe OOS |
|----------|---------|-----------|-----------|
| Q1 | 2-8 | 1.57 | 1.54 |
| Q5 | 21-99 | 0.30 | 0.63 |

Supports microstructure view: more touches = more stops consumed = weaker level. Barely-touched boundaries have more pending-order "fuel" for genuine breakouts.

#### Finding 2e: Combination Filters FAILED
- Narrow + POC aligned: Sharpe **-0.60** (terrible)
- Low vol + POC aligned: Sharpe -0.25
- Remove widest 20%: Sharpe 0.45 (worse than baseline)

**Important:** The combinations that were tested combined features in their "literature-predicted" direction (narrow is good, aligned is good). Since the individual features showed INVERSIONS, these combos naturally failed. **Combos using the inverted signals (non-narrow + misaligned) have not been tested yet.**

### Direction 3: Gap-Period Volume Imbalance — NULL RESULT (confirmed)
**Scripts:** `research_precross_imbalance.py`, `analyze_cumulative_imbalance.py`

All correlations near zero. Walk-forward helps <50% of years. Buy ratio distributions center at 0.50 for both directions. **Deprioritized permanently.**

---

## Cross-Instrument Validation (EURUSD)

**Script:** `research_range_quality_multi.py` → `range_quality_eurusd_results.txt`
**EURUSD baseline:** 1,460 trades, Sharpe -0.06 (IS) / 0.19 (OOS)

| Finding | XAUUSD | EURUSD | Cross-Validated? |
|---------|--------|--------|-----------------|
| NR4 worse than Non-NR4 | YES | NO (NR4 OOS 0.89 vs Non-NR4 0.05) | ❌ XAUUSD-specific |
| POC Misaligned > Aligned | YES | YES (Mis OOS 0.50 vs Al -0.09) | ✅ CONFIRMED |
| VWAP Misaligned > Aligned | YES | YES (Mis OOS 0.47 vs Al -0.09) | ✅ CONFIRMED |
| Intra-vol Goldilocks | YES (Q2-Q3) | Partial (Q3-Q4 best, Q5 worst) | ⚠️ Partial |
| Fewer touches = better | YES | NO | ❌ Not confirmed |
| Narrow range = worse | YES | NO | ❌ Not confirmed |

**Conclusion:** POC/VWAP misalignment is the ONLY cross-instrument signal. This is now the primary filter candidate.

**Updated confidence (POC misalignment):**
- `context_complete`: FAVORABLE — validated on 2 instruments (commodity + FX pair)
- `no_unstated_assumptions`: MIXED — causal story plausible but unverified
- `evaluator_agreement`: FAVORABLE — consistent direction on both instruments, IS and OOS
- **Status: approaching defensible. Needs walk-forward validation.**

---

## Walk-Forward Results (POC + Cat B Combined)

**Script:** `research_poc_walkforward.py` → `poc_walkforward_results.txt`

### POC Misalignment Walk-Forward (year-by-year stability)
- XAUUSD: helps **4/9 years (44%)** — NOT robust. 2021 catastrophic (Sh -2.86 for misaligned)
- EURUSD: helps **7/9 years (78%)** — robust

### Combined (No Cat B + POC Misaligned) Walk-Forward
- XAUUSD: helps **5/9 years (56%)** — borderline
- EURUSD: helps **6/9 years (67%)** — decent. Dramatic improvement in good years (2021: 0.77→3.87, 2024: 0.48→4.48)

### Orthogonality (2×2 grid) — Critical Finding
| XAUUSD | Misaligned | Aligned |
|--------|-----------|---------|
| A/C | OOS Sh 1.48 ✅ | OOS Sh 0.78 |
| Cat B | OOS Sh 1.86 ✅ | OOS Sh -0.84 ❌ |

| EURUSD | Misaligned | Aligned |
|--------|-----------|---------|
| A/C | OOS Sh 1.99 ✅ | OOS Sh 0.31 |
| Cat B | OOS Sh -3.78 ❌ | OOS Sh -1.15 ❌ |

**Key insight:** On XAUUSD, Cat B + Misaligned is the BEST group (Sh 1.86 OOS), so removing all Cat B hurts. On EURUSD, all Cat B is toxic. The universally safe group is A/C + Misaligned.

### Portfolio (XAUUSD + EURUSD)
| Filter | Trades/wk | Sharpe OOS | WR |
|--------|-----------|-----------|-----|
| Baseline | 7.2 | 0.66 | 46.9% |
| POC misaligned | 3.3 | 1.16 | 48.0% |
| No Cat B + POC mis | 2.4 | 1.10 | 51.0% |

### Tension to Resolve
POC misalignment is robust on EURUSD (78%) but not XAUUSD (44%). Options:
1. Deploy on EURUSD only (robust), keep XAUUSD unfiltered
2. Deploy on both, accept XAUUSD instability
3. Investigate 2021 XAUUSD regime to understand failure mode

---

## Key Decisions Made

1. **Prevention > Management:** Focus on pre-entry filtering rather than in-trade management
2. **Trade count tradeoff accepted:** OK with 2-3 trades/week if win rate improves significantly
3. **Volume imbalance deprioritized:** Empirical null result outweighs theoretical appeal
4. **Cat B filter is moderate, not a slam-dunk:** 1-min data shows Cat B has small positive edge (Sharpe 0.44), not zero as 5-min suggested
5. **Literature predictions inverted empirically:** NR4, POC alignment, VWAP alignment all show opposite effects. Empirical data takes priority over literature predictions (per authority order: primary data > expert synthesis)
6. **Direction-conditional filter rejected:** Neither LONG nor SHORT misaligned is independently stable — both fail in different years. Combined diversification is the source of robustness
7. **Volume-shape features rejected for deployment:** Kurtosis/entropy look great on gold but INVERT on EURUSD. Cross-instrument validation kills them as universal signals
8. **Gap context permanently deprioritized:** 99% of gold trades have prior close inside today's range — no usable signal
9. **Research concluded:** All investigated filter candidates either fail cross-validation or provide marginal benefit. Deployment decision is now a risk-tolerance judgment, not a research question

---

## Mismatches Surfaced (per research standards)

1. **5-min vs 1-min Cat A/B performance:** 5-min overstated Cat A (ideal fills) and understated Cat B. 1-min is more trustworthy. Classification: **evidential** — resolved in favor of 1-min data.
2. **Crabel NR4 vs empirical NR4:** Literature says narrow ranges → better breakouts. Data says opposite for XAUUSD. Classification: **evidential** — resolved: XAUUSD-specific artifact, does not hold on EURUSD. NR4 is not a universal signal for intra-session ORB.
3. **Market Profile POC theory vs empirical POC:** Literature says aligned POC → better breakouts. Data says opposite. Classification: **evidential** — resolved: POC misalignment cross-validates on 2 instruments. The inversion is real and likely reflects that breakouts against consensus represent genuine institutional flow.
4. **XAUUSD vs EURUSD kurtosis direction:** High kurtosis improves gold (Sharpe 1.44) but hurts EURUSD (Sharpe -0.24). The 2×2 grids are inverted. Classification: **evidential** — resolved: kurtosis captures gold-specific microstructure (concentrated Asian physical demand), not a universal volume profile property.
5. **POC misalignment: gold-specific risk vs cross-instrument robustness:** POC misalignment is cross-instrument (both gold and EURUSD show the same direction), but the MAGNITUDE of failure in down-gold regimes is gold-specific. Classification: **structural** — surfaced to human. The deployment decision depends on which property weighs more.

---

## Literature Grounding (Updated)

| Source | Concept | Prediction | Empirical Result | Status |
|--------|---------|------------|-----------------|--------|
| Crabel (1990) | NR4/NR7 → better breakouts | Narrow = better | **Narrow = worse** | CONTRADICTED |
| Steidlmayer | POC alignment → breakout support | Aligned = better | **Misaligned = better** | CONTRADICTED |
| Elder, Murphy | Volume confirmation | High vol = real breakout | Volume imbalance = null signal | CONTRADICTED |
| Bulkowski | ~20-25% rectangle failure rate | ~25% failure | ~27% Cat B rate | CONSISTENT |
| Brunnermeier & Pedersen | Predatory trading / stop hunting | Fake breakouts exist | Cat B matches stop-hunt pattern | CONSISTENT |
| Osler (2003) | Stop clusters at key levels | Stops drive initial breakouts | Touch count inversely correlates with quality | CONSISTENT |

---

## Open Questions (Resolved & Remaining)

1. ~~Does the Category B filter hold on 1-min data?~~ → Partially. Moderate, not definitive.
2. ~~Do any range quality features show predictive power?~~ → YES, POC/VWAP misalignment cross-validated.
3. ~~Are the inversions XAUUSD-specific or universal?~~ → NR4 is XAUUSD-specific. POC misalignment is cross-instrument. Kurtosis/entropy are XAUUSD-specific.
4. ~~Walk-forward POC misalignment~~ → EURUSD robust (78%), XAUUSD borderline (44%).
5. ~~Cat B + POC orthogonal?~~ → Partially. Cat B behavior differs by instrument.
6. ~~Trade count feasible?~~ → YES. Portfolio combined filter = 2.4/wk, right on target.
7. ~~Why did 2021 fail on XAUUSD?~~ → Regime-dependent: LONG misaligned fails in down-gold years. N=1.
8. ~~Can direction-splitting fix 2021?~~ → NO. Neither direction is independently stable.
9. ~~Are volume-shape features (kurtosis/entropy) useful?~~ → On gold only. Fail EURUSD cross-validation.
10. ~~Is gap context useful?~~ → NO. Null result, 99% of trades have no true gap.
11. ~~Is time-of-breakout useful?~~ → Pattern exists but not robust enough (56% WF).
12. **REMAINING — Deployment decision:** Deploy POC misalignment on XAUUSD (accept risk), EURUSD only (robust), or both?
13. **REMAINING — Causal question:** WHY does POC misalignment predict better breakouts? (plausible story exists, unverified)
14. **REMAINING — Regime detection:** Can down-gold regimes be detected forward-looking? (not investigated)

---

## Detailed Walk-Forward Numbers (for reference)

### XAUUSD — POC Misalignment Walk-Forward
```
Year | N_all | N_mis | Sh_all | Sh_mis | Sh_al  | Better?
2018 |   203 |    92 |   0.24 |  -0.52 |   0.91 | no
2019 |   200 |    96 |  -1.72 |  -2.17 |  -1.36 | no
2020 |   197 |    91 |   1.58 |   2.98 |   0.48 | YES
2021 |   198 |    78 |   0.31 |  -2.86 |   2.27 | no  ← catastrophic failure year
2022 |   199 |    94 |   1.70 |   1.17 |   2.15 | no
2023 |   202 |    88 |  -0.19 |   3.18 |  -2.88 | YES
2024 |   204 |    94 |   1.64 |   2.90 |   0.61 | YES
2025 |   188 |    97 |   1.58 |   3.38 |  -0.40 | YES
2026 |    22 |    12 |  -2.34 |  -4.04 |   0.78 | no
→ Helps 4/9 years (44%)
```

### XAUUSD — Combined (No Cat B + POC Misaligned) Walk-Forward
```
Year | N_all | N_comb | Sh_all | Sh_comb | Better?
2018 |   203 |     64 |   0.24 |   -3.22 | no
2019 |   200 |     71 |  -1.72 |   -1.98 | no
2020 |   197 |     68 |   1.58 |    2.71 | YES
2021 |   198 |     57 |   0.31 |   -5.05 | no  ← catastrophic
2022 |   199 |     65 |   1.70 |    1.88 | YES
2023 |   202 |     68 |  -0.19 |    2.69 | YES
2024 |   204 |     71 |   1.64 |    3.65 | YES
2025 |   188 |     73 |   1.58 |    3.64 | YES
2026 |    22 |      8 |  -2.34 |   -9.39 | no
→ Helps 5/9 years (56%)
```

### EURUSD — POC Misalignment Walk-Forward
```
Year | N_all | N_mis | Sh_all | Sh_mis | Sh_al  | Better?
2018 |   188 |    99 |  -1.18 |  -0.84 |  -1.54 | YES
2019 |   173 |    68 |  -1.16 |  -1.81 |  -0.78 | no
2020 |   188 |    81 |   0.44 |   0.77 |   0.20 | YES
2021 |   190 |    88 |   0.77 |   1.02 |   0.55 | YES
2022 |   157 |    67 |   0.63 |   1.09 |   0.31 | YES
2023 |   173 |    79 |   0.20 |   0.98 |  -0.46 | YES
2024 |   173 |    80 |   0.48 |   2.81 |  -1.73 | YES
2025 |   188 |    96 |  -0.80 |  -2.16 |   0.78 | no
2026 |    30 |    10 |  -0.21 |   4.05 |  -3.28 | YES
→ Helps 7/9 years (78%)
```

### EURUSD — Combined (No Cat B + POC Misaligned) Walk-Forward
```
Year | N_all | N_comb | Sh_all | Sh_comb | Better?
2018 |   188 |     70 |  -1.18 |   -1.33 | no
2019 |   173 |     50 |  -1.16 |   -2.12 | no
2020 |   188 |     58 |   0.44 |    1.19 | YES
2021 |   190 |     65 |   0.77 |    3.87 | YES ← dramatic improvement
2022 |   157 |     47 |   0.63 |    2.22 | YES
2023 |   173 |     58 |   0.20 |    3.03 | YES
2024 |   173 |     55 |   0.48 |    4.48 | YES ← dramatic improvement
2025 |   188 |     76 |  -0.80 |   -1.76 | no
2026 |    30 |      8 |  -0.21 |    6.54 | YES
→ Helps 6/9 years (67%)
```

### Trade Count Under Each Filter
```
                    | XAUUSD    | EURUSD    | Portfolio
Baseline            | 3.8/wk    | 3.4/wk    | 7.2/wk
POC misaligned only | 1.7/wk    | 1.6/wk    | 3.3/wk
No Cat B            | 2.8/wk    | 2.5/wk    | 5.3/wk
No Cat B + POC mis  | 1.3/wk    | 1.1/wk    | 2.4/wk  ← target range
```

---

## XAUUSD 2021 Regime Investigation

**Script:** `research_2021_xauusd.py`

The 2021 XAUUSD failure was the critical open question: POC misalignment walk-forward was only 44% on gold, dragged down by 2021 (Sharpe -2.86 for misaligned vs +0.14 baseline).

### Root Cause Found: Regime-Dependent Failure

2021 was gold's only DOWN year (-5.2%) in the dataset. The failure was specifically **LONG misaligned trades in a down market**:

| Year | LONG mis Sharpe | SHORT mis Sharpe | Combined mis Sharpe | Regime |
|------|----------------|-----------------|---------------------|--------|
| 2020 | 3.20 | 2.67 | 2.98 | UP +25% |
| **2021** | **-5.32** | **0.05** | **-2.86** | **DOWN -5%** |
| 2022 | -0.21 | 1.83 | 0.77 | FLAT -1% |
| 2023 | 2.39 | 3.95 | 3.18 | UP +13% |

The causal story: in trending UP markets, Asian POC is "stale" so breakouts against it join the trend (institutional flow). In DOWN/ranging markets, the Asian POC is more informative about true value, so breakouts against it fight real flow and fail.

### Direction-Split Investigation

Tested whether keeping only SHORT misaligned (which appeared regime-stable) would work:
- SHORT misaligned alone: Sharpe 0.99, walk-forward **3/9 years (33%)** — NOT stable
- LONG misaligned alone: Sharpe 1.15, walk-forward **5/9 years (56%)**
- Combined (both directions): Sharpe 1.34 — diversification benefit

**Conclusion:** Neither direction is independently stable. The combined filter works because LONG and SHORT fail in different years and complement each other. The direction-conditional approach is a dead end.

### Confidence Assessment (POC Misalignment + 2021 Regime)

- `context_complete`: **FAVORABLE** — full year-by-year regime analysis across 8+ years, two instruments
- `no_unstated_assumptions`: **MIXED** — causal story is plausible but retrospective. Regime classification is trivial after the fact. We have N=1 down year. Detection lag is an open question.
- `evaluator_agreement`: **FAVORABLE** — the pattern in the data is unambiguous
- **Status: converging toward defensible**

---

## New Feature Investigation: Time-of-Breakout, Gap Context, Volume Profile Shape

**Script:** `research_new_features.py`

Investigated three new loss trade reduction features on XAUUSD:

### Feature 1: Time of Breakout — INTERESTING PATTERN, NOT FILTERABLE

| Time Bucket | N | % | Sharpe | SL% | TP% |
|-------------|---|---|--------|-----|-----|
| 08:00-08:30 | 1044 | 64.2% | 0.94 | 32.1% | 23.6% |
| 08:30-09:00 | 124 | 7.6% | -0.56 | 37.9% | 12.9% |
| 09:00-10:00 | 126 | 7.7% | -2.24 | 42.9% | 11.9% |
| 10:00-11:00 | 86 | 5.3% | 1.33 | 23.3% | 15.1% |
| 11:00-12:00 | 63 | 3.9% | 2.88 | 28.6% | 11.1% |
| 12:00+ | 184 | 11.3% | 1.59 | 16.3% | 6.0% |

**Pattern:** Immediate breakouts (first 30 min) and very late breakouts (10:00+) work. The 08:30-10:00 window is toxic (Sharpe -0.56 to -2.24). But as a filter, early-only helps only 5/9 years (56%) walk-forward — not robust enough.

### Feature 2: Gap Context — NULL RESULT

99% of trades have prior close inside today's Asian range. Only 17 trades had a true gap. No usable signal. **Deprioritized permanently.**

### Feature 3: Volume Profile Shape — TWO CANDIDATES EMERGED

**Kurtosis:** Monotonic trend — flat profiles (Q1) Sharpe -0.08, peaked profiles (Q5) Sharpe 1.97. Sessions where volume concentrates in a few bins produce better breakouts.

**Low entropy (bottom 40%):** Sharpe 1.17, walk-forward **6/9 years (67%)**. When Asian session has a clear, concentrated volume structure (not evenly spread), breakouts are better quality.

**Key distinction from POC misalignment:** Entropy/kurtosis measures *how decisive* the Asian session's opinion was (shape), not *where* it was (position). They are nearly orthogonal (correlation -0.06).

---

## Deep Entropy/Kurtosis Investigation

**Script:** `research_entropy_deep.py`

### Orthogonality Confirmed

- Correlation(entropy, poc_position): -0.06
- Low entropy trades that are POC-misaligned: 47.2% vs 45.5% for high entropy
- **They measure different dimensions of the same volume profile**

### 2×2 Grid — Entropy × POC Alignment (XAUUSD)

| | Low Entropy | High Entropy |
|---|---|---|
| **POC Misaligned** | **Sharpe 1.78**, PF 1.51, N=384 | Sharpe 0.74, N=370 |
| **POC Aligned** | Sharpe 0.94, N=430 | **Sharpe -0.45**, N=443 |

Best trades: concentrated Asian volume AND in the wrong place (low entropy + misaligned).
Worst trades: spread-out Asian volume AND in the right place (high entropy + aligned).

### Critical Finding: Entropy Does NOT Have the 2021 Problem

| Filter | 2021 Sharpe | Survives? |
|--------|-------------|-----------|
| POC misaligned | -2.86 | ❌ Catastrophic failure |
| Low entropy 40% | **+0.43** | ✅ Survives |
| Combined (LowEnt+Mis) | -1.14 | ❌ POC component drags it down |

Low entropy is regime-resilient where POC misalignment fails.

### Threshold Sensitivity

| Entropy Percentile | Sharpe | Walk-forward |
|-------------------|--------|-------------|
| 20th | 1.58 | 4/9 (44%) |
| 40th | 1.17 | **6/9 (67%)** |
| 50th | 1.40 | 5/9 (56%) |
| 60th | 1.30 | **6/9 (67%)** |

40th and 60th percentile both peak at 67% walk-forward.

### Final Scoreboard (XAUUSD)

| Filter | N | Sharpe | WR | PF | Total | MaxDD | WF |
|--------|---|--------|-----|-----|-------|-------|------|
| Baseline | 1627 | 0.81 | 47.3% | 1.17 | $1,138 | -$210 | — |
| POC misaligned | 754 | 1.34 | 47.6% | 1.32 | $998 | -$209 | 5/9 |
| Low entropy 40% | 651 | 1.17 | 48.1% | 1.28 | $746 | -$280 | **6/9** |
| High kurtosis 40% | 651 | 1.44 | 48.2% | 1.36 | $930 | -$177 | 5/9 |
| LowEnt50+POC mis | 384 | **1.78** | 49.2% | 1.51 | $773 | **-$120** | 5/9 |

---

## Kurtosis Cross-Instrument Validation (DECISIVE)

**Script:** `research_kurtosis_deep.py`

### EURUSD Results: Kurtosis FAILS Cross-Validation

| Filter | XAU Sharpe | XAU WF | EUR Sharpe | EUR WF | Cross-validates? |
|--------|-----------|--------|-----------|--------|-----------------|
| POC misaligned | 1.34 | 5/9 | 0.19 | **7/9** | ✅ YES |
| High kurtosis 40% | 1.44 | 5/9 | -0.24 | 6/9 | ❌ NO |
| HiKurt + POC mis | **1.79** | **6/9** | **-1.27** | **2/9** | ❌ NO |
| Low entropy 40% | 1.17 | 6/9 | -0.35 | 5/9 | ❌ NO |
| LowEnt40 + POC mis | 1.53 | 5/9 | -0.38 | 5/9 | ❌ NO |

**The EURUSD 2×2 grid is INVERTED relative to XAUUSD:**

| EURUSD | High Kurtosis | Low Kurtosis |
|--------|--------------|-------------|
| POC Misaligned | **Sharpe -1.27** (worst) | **Sharpe 1.08** (best) |
| POC Aligned | Sharpe 0.54 | Sharpe -0.89 |

On EURUSD, LOW kurtosis + misaligned is the best group — the exact opposite of gold. This means kurtosis is capturing something about gold's specific microstructure (possibly concentrated Asian physical demand) that does not generalize to FX.

### 2021 Deeper: Combined Filter Makes It WORSE

HiKurt + POC misaligned in 2021: Sharpe **-5.16** (vs -2.86 for POC alone). LONG combined in 2021: Sharpe **-12.46**. The kurtosis filter amplifies the failure by concentrating trades into fewer, more leveraged bets that all fail in the same direction.

---

## Research Conclusions

### What Was Established

1. **POC misalignment is the only cross-instrument signal.** Validated on gold and EURUSD. Clear economic interpretation (breakouts against Asian volume consensus = genuine institutional flow). Walk-forward: EURUSD 78%, XAUUSD 56% (POC-only baseline 44% but combined with Cat B removal reaches 56%).

2. **All volume-shape features (entropy, kurtosis, concentration) are gold-specific artifacts.** They look great on XAUUSD but fail or invert on EURUSD. Per Layer 1 standards, they do not meet the evidence bar for deployment.

3. **The 2021 XAUUSD failure is regime-dependent.** POC misalignment fails catastrophically in gold's only down year. Neither direction-splitting nor volume-shape overlays fix it. The regime-dependence claim rests on N=1 down year.

4. **Gap context is a null result.** 99% of gold trades have prior close inside today's range.

5. **Time-of-breakout shows a real pattern** (30-120 min dead zone) but is not robust enough as a filter (56% walk-forward).

### What Was NOT Established

- Whether a regime overlay could pre-detect down-gold years in real time
- Whether POC misalignment works on GBP/CHF pairs (data not yet available)
- Whether the 2021 failure mode would repeat in another down-gold year (N=1)

### Practical Assessment

POC misalignment on XAUUSD: **marginal benefit with a known risk.**
- Sharpe improvement: 0.81 → 1.34 (+65% risk-adjusted)
- PnL cost: $1,138 → $998 (-12% absolute)
- Trade frequency: 5.0/wk → 2.3/wk
- Known failure: catastrophic in down-gold regimes (1 in 8 years historically)

The filter improves risk-adjusted returns but not absolute returns, and introduces a failure mode the baseline doesn't have. Whether this tradeoff is acceptable is a deployment decision, not a research question.

### Confidence (Final)

**Core claim: POC misalignment is a real structural signal for ORB strategies.**
- `context_complete`: **FAVORABLE** — 8+ years, 2 instruments, multiple feature interactions tested
- `no_unstated_assumptions`: **MIXED** — regime-dependence on N=1. Causal story plausible but retrospective. Volume-shape features inverted cross-instrument, which could mean POC misalignment also has hidden instrument-specificity we haven't detected
- `evaluator_agreement`: **FAVORABLE** — data patterns are unambiguous across all analyses
- **Status: DEFENSIBLE with stated limitations**

**Core claim: Volume-shape features (kurtosis, entropy) are gold-specific, not universal.**
- `context_complete`: **FAVORABLE** — tested on 2 instruments with clear inversion
- `no_unstated_assumptions`: **FAVORABLE** — the EURUSD inversion is strong disconfirming evidence
- `evaluator_agreement`: **FAVORABLE** — no reasonable reading of the data supports cross-instrument validity
- **Status: DEFENSIBLE**

---

## Open Questions (Final)

1. **Deployment decision needed:** Deploy POC misalignment on XAUUSD (accept 2021 risk), EURUSD only (robust but few trades), or both?
2. **Additional FX pairs:** If GBPUSD/USDCHF data becomes available, POC misalignment validation on those pairs would strengthen/weaken the "universal signal" claim
3. **Regime detection:** Is there a forward-looking indicator that could have identified 2021-type conditions before they produced losses? (Not investigated — likely a new research thread)

---

## Architecture Notes for Future Agent

- **Data:** `C:/nautilus0/data/1m_csv/xauusd_1m_tick.csv` — 2.9M 1-min bars, 2018-2026. Columns include buy_volume, sell_volume, total_volume, buy_ratio, tick_count, avg_spread.
- **Backtest engine:** `v5_xauusd_orb/backtest_1m.py` — `load_1m_bars()`, `backtest(df, Config)`, `stats(trades)`, `print_stats()`
- **Config defaults:** Asian 00-06 UTC, Trade 08-16 UTC, RR=2.0, skip Wednesdays, stop entry
- **OOS split:** 2021-01-01
- **Python:** Must use `C:\Users\nsher\AppData\Local\Programs\Python\Python313\python.exe` (has numpy/pandas/scipy). Default `python` is 3.14 without packages.
- **Pattern:** All research scripts follow the same structure — load data, run backtest, enrich trades with features, run tests, print formatted tables to stdout
- **Research standards:** `docs/standards/layer1-research-standards.md` — key principles: confidence is derived from checkable conditions, surface mismatches explicitly, protect center elements

## Results Files

All in `C:/nautilus0/v5_xauusd_orb/`:
- `precross_results.txt` — Pre-crossing imbalance analysis (null result)
- `cumulative_imbalance_results.txt` — Cumulative volume delta (null result)
- `research_gap_output.txt` — Gap entry category analysis (5-min)
- `backtest_1m_output.txt` — Baseline 1-min backtest results
- `category_b_filter_results.txt` — Category B filter validation (1-min)
- `range_quality_results.txt` — Range quality feature exploration (1-min)
- `range_quality_eurusd_results.txt` — EURUSD range quality cross-validation
- `poc_walkforward_results.txt` — Walk-forward + orthogonality + portfolio analysis

## Research Scripts

All in `C:/nautilus0/v5_xauusd_orb/`:
- `research_category_b_filter.py` — Category B filter validation
- `research_range_quality.py` — Range quality feature exploration (NR4, POC, touch count, etc.)
- `research_range_quality_multi.py` — Multi-instrument range quality cross-validation
- `research_poc_walkforward.py` — Walk-forward + orthogonality + portfolio analysis
- `research_precross_imbalance.py` — Pre-crossing volume imbalance (null result)
- `analyze_cumulative_imbalance.py` — Cumulative volume delta (null result)
- `research_2021_xauusd.py` — 2021 XAUUSD regime investigation
- `research_2021_eurusd.py` — EURUSD regime investigation (not run — research pivoted)
- `research_new_features.py` — Time-of-breakout, gap context, volume profile shape
- `research_entropy_deep.py` — Deep entropy/kurtosis investigation + orthogonality with POC
- `research_kurtosis_deep.py` — Kurtosis cross-instrument validation (decisive negative result)
