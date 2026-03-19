# Session Notes: Loss Trade Reduction Research
**Date:** 2026-03-18
**Status:** Paused — walk-forward complete, decision point reached, awaiting GBPUSD/USDCHF data
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

## Next Steps (Updated)

1. **Human decision needed:** Which deployment approach? (see options above)
2. **Investigate 2021 XAUUSD regime** — what made POC misalignment fail that year?
3. **Broader FX validation** — can we approximate POC on 5-min data (using OHLC proxy)?

---

## Key Decisions Made

1. **Prevention > Management:** Focus on pre-entry filtering rather than in-trade management
2. **Trade count tradeoff accepted:** OK with 2-3 trades/week if win rate improves significantly
3. **Volume imbalance deprioritized:** Empirical null result outweighs theoretical appeal
4. **Cat B filter is moderate, not a slam-dunk:** 1-min data shows Cat B has small positive edge (Sharpe 0.44), not zero as 5-min suggested
5. **Literature predictions inverted empirically:** NR4, POC alignment, VWAP alignment all show opposite effects. Empirical data takes priority over literature predictions (per authority order: primary data > expert synthesis).

---

## Mismatches Surfaced (per research standards)

1. **5-min vs 1-min Cat A/B performance:** 5-min overstated Cat A (ideal fills) and understated Cat B. 1-min is more trustworthy. Classification: **evidential** — resolved in favor of 1-min data.
2. **Crabel NR4 vs empirical NR4:** Literature says narrow ranges → better breakouts. Data says opposite for XAUUSD. Classification: **evidential** — needs multi-instrument check before concluding.
3. **Market Profile POC theory vs empirical POC:** Literature says aligned POC → better breakouts. Data says opposite. Classification: **evidential** — same resolution needed.

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

## Open Questions

1. ~~Does the Category B filter hold on 1-min data?~~ → Partially. Moderate, not definitive.
2. ~~Do any range quality features show predictive power?~~ → YES, POC/VWAP misalignment cross-validated.
3. ~~Are the inversions XAUUSD-specific or universal?~~ → NR4 is XAUUSD-specific. POC misalignment is cross-instrument.
4. ~~Walk-forward POC misalignment~~ → EURUSD robust (78%), XAUUSD borderline (44%).
5. ~~Cat B + POC orthogonal?~~ → Partially. Cat B behavior differs by instrument.
6. ~~Trade count feasible?~~ → YES. Portfolio combined filter = 2.4/wk, right on target.
7. **DECISION NEEDED:** Deployment approach — EURUSD-only POC vs. both instruments
8. **Why did 2021 fail on XAUUSD?** Regime investigation needed.
9. **Causal question:** WHY does POC misalignment predict better breakouts?

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

## Pending Work for Next Session

1. **GBPUSD and USDCHF tick data** being downloaded. When ready, place in `C:/nautilus0/data/1m_csv/` as `gbpusd_1m_tick.csv` and `usdchf_1m_tick.csv` with same column format as existing files.
2. Run `research_range_quality_multi.py` on each new pair to verify POC misalignment cross-validates:
   ```
   cd C:/nautilus0
   "C:\Users\nsher\AppData\Local\Programs\Python\Python313\python.exe" -m v5_xauusd_orb.research_range_quality_multi gbpusd
   ```
   Note: you must first add the instrument to `INSTRUMENT_CONFIG` dict in `research_range_quality_multi.py` with appropriate pip_size and spread_cost.
3. If POC misalignment confirms on 3+ instruments, run `research_poc_walkforward.py` extended to include the new pairs.
4. **Human decision needed:** deployment approach (see Tension to Resolve section above).
5. **Investigate XAUUSD 2021** — what made POC misalignment catastrophically fail that year? Was there a gold-specific regime (e.g., post-COVID inflation trade, unusual Asian session behavior)?

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
