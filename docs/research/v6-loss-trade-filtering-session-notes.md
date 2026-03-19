# v6 Research: Eliminating Non-Follow-Through Breakout Trades

**Status:** exploring → converging on initial findings
**Started:** 2026-03-17
**Research standards:** governed by `docs/standards/layer1-research-standards.md`
**Codebase context:** v5 ORB (Asian session range breakout) is the foundation — see `v5_xauusd_orb/`

---

## Problem Statement

The v5 ORB strategy defines a range during the Asian session (00:00–06:00 UTC), then trades breakouts of that range during the London session (08:00–16:00 UTC). There is a ~2-hour gap (06:00–08:00 UTC) between range definition and trade execution.

**The specific failure mode:** A subset of trades break through the Asian range at London open but lack follow-through — price stalls beyond the level and returns into the range. These are not catastrophic (the breakeven stop at 2h converts many to small wins/losses), but they drag on performance and represent trades where the edge was absent.

**Goal:** Find a reliable, validatable filter or management technique to reduce exposure to these non-follow-through trades.

---

## Baseline Performance (v5 ORB, for reference)

| Metric | XAUUSD | EURUSD | GBPUSD | USDJPY |
|--------|--------|--------|--------|--------|
| Trades (2015/2019–2026) | ~1,122 | ~1,274 | ~1,460 | ~1,402 |
| Win rate (TP) | ~17% | ~27% | — | — |
| Sharpe (annualized) | 4.28 | 3.04 | 2.82 | 4.50 |
| Profit factor | 3.31 | 1.95 | 1.80 | 4.55 |
| All passed 6/6 validation checks (OOS Sharpe, randomization, walk-forward, etc.) |

Key structural detail: low win rate, high reward-to-risk ratio (~2:1 RR). Profitable despite majority of trades losing. The BE stop (2h, $2 offset) converts ~57–69% of trades to breakeven exits.

---

## Available Data

1-minute bars built from Dukascopy tick data (2018–2026, ~2.9M bars for XAUUSD).

**Key columns:** `timestamp`, `open`, `high`, `low`, `close`, `tick_count`, `avg_spread`, `max_spread`, `vol_imbalance`, `buy_volume`, `sell_volume`, `total_volume`, `buy_ratio`

The buy_volume/sell_volume breakdown per 1-minute bar is the core data asset for volume imbalance research.

**Location:** `data/1m_csv/xauusd_1m_tick.csv` (1-min), `data/5m_csv/xauusd_5m.csv` (5-min)

---

## Existing Research Results (Reviewed This Session)

### Pre-Crossing Volume Imbalance — NULL RESULT

**Source:** `v5_xauusd_orb/precross_results.txt` (output of `research_precross_imbalance.py`)

- **Correlation test:** All Pearson correlations near 0.00 (range: -0.011 to +0.006) across all 6 lookback windows. p-values all >0.66. **Zero predictive power.**
- **Matching vs Divergent:** Counterintuitively, divergent flow (opposing trade direction) often *outperforms* matching flow. At 5-bar window: Divergent OOS Sharpe 1.39 vs Matching 0.48. At 10-bar: Divergent 1.09 vs Matching 0.76.
- **Quintile analysis:** Q1 (strongest opposing flow) consistently has highest Sharpe across most windows. This is the opposite of the naive hypothesis.
- **Walk-forward:** Helps only 29–57% of years depending on window. Not deployable.
- **Combined velocity + imbalance:** Velocity alone (Sh 1.49 OOS) does most of the work. Adding imbalance is unstable — the optimal direction flips between windows, suggesting noise.

**Conclusion:** Pre-crossing buy/sell volume imbalance is not a usable signal for filtering false breakouts on XAUUSD. The counterintuitive divergent-beats-matching pattern may indicate mean-reversion dynamics (opposing flow = price stretched, snapback creates the breakout) but is not reliable enough to trade on.

### Cumulative Volume Imbalance — NULL RESULT

**Source:** `v5_xauusd_orb/cumulative_imbalance_results.txt` (output of `analyze_cumulative_imbalance.py`)

- Cumulative buy_ratio distributions center at exactly 0.50 for both LONG and SHORT trades — no natural bias.
- "Disagrees" group (flow opposes direction) slightly outperforms "Agrees" — same counterintuitive pattern as pre-crossing.
- Walk-forward: helps 43% of years. Not reliable.
- Best combined result (Vel + 10bar > 0.54): OOS Sharpe 2.88, N=173, WR 56.6%. But direction flips vs. standalone imbalance tests → velocity is doing the work, imbalance is noise.

### Gap Entry Categories — KEY FINDING

**Source:** `v5_xauusd_orb/research_gap_output.txt` (output of `research_gap_entry.py`)

**This directly identifies the failure mode:**

| Category | % of Trades | Mean P&L | Sharpe | Win Rate | Description |
|----------|------------|----------|--------|----------|-------------|
| **A: Gap-open** | 32.6% | +$3.32 | 6.55 | 68% | Crossed range in gap, still past at 08:00 |
| **B: Returned** | **26.7%** | **+$0.05** | **0.13** | **50%** | **Crossed range in gap, came BACK by 08:00** |
| **C: Clean breakout** | 40.6% | +$1.32 | 2.61 | 54% | Never crossed before 08:00 |

**Category B = the "stuck and return" trades.** 26.7% of all trades (close to human's 30% intuition). Coin-flip win rate. Zero edge. These are trades where price tested the range boundary during the gap, failed to sustain, returned to the range, and then re-broke at London — but the re-break lacks conviction.

**Additional gap findings:**
- Gap-open distance: mean $2.98 past level, median $1.55. Larger gaps (25-100% of range) are actually the *best* performers.
- **Realistic fill impact is severe:** Ideal Sharpe 3.35 → Realistic 0.87 (gap-opens fill at market, not at level). $783 of the $1,022 total P&L evaporates.
- Pullback re-entry for gap-opens: Sharpe -0.86. Waiting for pullback destroys the edge entirely.
- First level cross timing: 18.6% happen right at 06:00, then roughly uniform through 07:55.

---

## Research Directions — Updated After Evidence Review

### IMMEDIATE OPPORTUNITY: Category B Filter

**What:** During the gap (06:00–08:00), monitor whether price crosses the Asian range. If it crosses but returns to the range by 08:00, skip the trade.

**Impact estimate:** Removes 26.7% of trades (the zero-edge ones). Remaining 73.3% have blended Sharpe well above baseline.

**Confidence:** HIGH. Based directly on backtest data, not a fitted parameter. The filter is binary (did price return or not), not a threshold to optimize. Low overfitting risk.

**Status:** Ready to implement and validate. Needs walk-forward confirmation and multi-instrument testing.

**IMPORTANT CAVEAT:** The gap entry research used 5-min bars (356,726 bars, 625 trades, 2015-2026). The precross imbalance research used 1-min bars (2,876,848 bars, 1,613 trades, 2018-2026). Different datasets, different trade counts. Need to reconcile or re-run Category B filter on the 1-min data for consistency.

### Direction 3: Range Quality Pre-Filter (PRIORITY 1 for new research)

Unchanged from earlier. Now even more relevant: Category B trades (returned) may correlate with specific range characteristics. If the range that produces Category B trades is structurally different (weaker levels, noisier formation), range quality features could catch these AND additional bad trades within Categories A and C.

**Potential features:**
- Intra-range volatility (std of returns within Asian session)
- Number of touches at range extremes during Asia
- Volume distribution within the range (concentrated at edges vs. uniform)
- Range size as % of recent ATR (is this a narrow consolidation or wide chop?)
- Time spent at range extremes vs. mid-range

### Direction 2: Breakout Quality Classification (PRIORITY 2)

Still valuable for filtering failures within Categories A and C. After removing Category B, the remaining losers are clean breakouts or gap-opens that fail. Microstructure at the breakout moment (velocity, spread, initial impulse) could help.

### Direction 1: Gap-Period Volume Imbalance — DEPRIORITIZED

**Evidence against:** Pre-crossing imbalance across 6 windows shows zero correlation with outcomes. Cumulative imbalance centered at 0.50 for both directions. The signal isn't there.

**Remaining angle:** The existing research tested imbalance in bars *immediately before the crossing*. The human's refined idea was to test the aggregate imbalance across the *entire* gap period (or the last 30 min of it) as a measure of net institutional positioning — not just the bars right before the cross. This is a subtly different hypothesis but given two null results already, confidence is low.

**Literature note:** Cont, Kukanov, Stoikov (2014) show OFI explains 50–65% of short-horizon price moves, but requires Level 2 order book data. Tick-derived buy/sell volume is a weaker proxy, which may explain the null results.

### Direction 4: Regime/Macro — LOWEST PRIORITY

Unchanged.

---

## Literature Review (Training Knowledge Synthesis, 2026-03-18)

Web access was denied; this section is synthesized from agent training data. Citation confidence is flagged per item.

### Range Quality — Strong Published Support

| Source | Concept | Applicability | Citation Confidence |
|--------|---------|--------------|-------------------|
| Crabel (1990), "Day Trading with Short-Term Price Patterns and ORB" | NR4/NR7: narrowest range of last 4/7 periods predicts expansion. Narrow opening ranges produce more reliable breakouts. | **Direct.** Asian range IS the opening range. Compute Asian range / trailing N Asian ranges. | HIGH |
| Steidlmayer, Market Profile / TPO | POC (highest-volume price) position within range reveals accepted value. Profile shape (b/P/D) indicates directional bias. | **Direct.** Compute from 1-min volume data during Asian session. POC in upper third → upward breakout is continuation. | HIGH (concept) |
| VWAP position | Asian session VWAP relative to range boundaries. Breakouts aligned with VWAP side have better follow-through. | **Direct.** Computable from existing data. | MEDIUM (synthesis, no specific paper) |
| Osler (2003), Journal of Finance | FX stop-loss orders cluster at round numbers and near recent highs/lows. Creates predictable dynamics around levels. | **Relevant.** Range boundaries near round numbers may attract stop-driven false breakouts. | HIGH |
| Grimes, "Art and Science of Technical Analysis" | Time at a level contributes to significance (diminishing returns). Session spending most time near one boundary suggests pressure. | **Applicable.** Time-at-extremes feature for Asian session. | MEDIUM |

### Breakout Quality — Practitioner Support

| Source | Concept | Applicability | Citation Confidence |
|--------|---------|--------------|-------------------|
| Elder / Murphy | Breakout volume should be ≥1.5–2x recent average. Low-volume breakouts are suspect. | **Direct.** Compare London breakout bar volume to Asian average. | HIGH (concept); no rigorous backtest published |
| Bulkowski, "Encyclopedia of Chart Patterns" | Rectangle breakouts fail ~20–25% of the time. | **Validates base rate.** Your 26.7% Category B is consistent with structural failure rate. | HIGH |
| Brunnermeier & Pedersen (2005) | Predatory trading / stop hunting: institutional players trigger stops then reverse. | **Explains Category B mechanism.** Gap-period crossing may be a stop hunt. | HIGH |
| Carter, "Mastering the Trade" — TTM Squeeze | Bollinger Bands inside Keltner Channels = extreme volatility compression. Release predicts directional expansion. | **Applicable.** Squeeze condition at end of Asian session → higher breakout quality. | HIGH (concept) |

### Key Literature Gap

No landmark academic paper specifically tests Asian-to-London range breakout filtering. The strategy is widely traded by practitioners ("London Breakout", "Asian Box Breakout") but research is fragmented across retail forums. Crabel's ORB work is the closest academic-quality reference.

---

## Open Questions

1. ~~Existing imbalance/gap research conclusions?~~ **RESOLVED:** Results reviewed this session. Volume imbalance = null signal. Gap categories = key finding.
2. ~~Proportion of "stuck and return" trades?~~ **RESOLVED:** 26.7% (Category B). Matches human's ~30% intuition.
3. ~~Filter pre-trade vs manage in-trade?~~ **RESOLVED:** Pre-trade filtering preferred.
4. ~~Acceptable trade count reduction?~~ **RESOLVED:** 2–3 trades/week acceptable.
5. ~~What does "stuck and return" look like quantitatively?~~ **RESOLVED:** Category B = price crossed range during gap, returned by 08:00, then re-breaks at London but with zero edge (Sharpe 0.13, 50% WR).
6. ~~Late-gap volume imbalance window?~~ **DEPRIORITIZED:** Given null results from pre-crossing imbalance, unlikely to yield usable signal.
7. **(NEW)** Does Category B filter hold up in walk-forward and across instruments? Need validation.
8. **(NEW)** Is there overlap between Category B trades and specific range quality characteristics?
9. **(NEW)** Reconciliation needed: gap entry study (5-min, 625 trades) vs imbalance studies (1-min, 1,613 trades) — different baselines.
10. **(NEW — AWAITING HUMAN):** Does the human want to proceed with Category B filter implementation + validation, or pivot to Range Quality research first?

---

## Decisions Made

1. **Priority reordering:** Range Quality (D3) > Breakout Quality (D2) > Gap Imbalance (D1) > Regime (D4)
2. **Pre-trade filtering over in-trade management:** Focus on preventing bad trades, not managing them after entry
3. **Trade frequency tolerance:** 2–3 trades/week acceptable if quality improves
4. **Gap imbalance refinement:** If pursued, focus on tail end of gap — but now deprioritized given null results
5. **Re-run existing research:** DONE — results reviewed, key findings extracted
6. **Volume imbalance direction closed (for now):** Two independent tests (precross + cumulative) both null. Not pursuing further unless new hypothesis emerges.
7. **Category B filter identified as immediate opportunity:** Binary filter, low overfitting risk, removes 26.7% of zero-edge trades. Needs validation.

---

## Session Log

- **2026-03-17 — Session start:** Reviewed research standards, full ORB codebase, existing research. Established problem statement, identified 4 research directions, surfaced existing relevant studies. Awaiting human input on open questions.
- **2026-03-18 — Human input received:** Reordered priorities (D3 > D2 > D1 > D4). Confirmed ~30% stuck trades (intuition). Prefers pre-trade filtering. Comfortable with 2-3 trades/week. Doesn't recall running existing scripts. Refined gap imbalance direction to focus on end-of-gap period.
- **2026-03-18 — Existing research reviewed:** Read saved outputs from all 3 research scripts. KEY FINDINGS: (1) Volume imbalance is a null signal — zero correlation across all windows, counterintuitive divergent-beats-matching pattern, unstable in walk-forward. (2) Category B trades ("returned" — price crossed range in gap, came back by 08:00) are exactly the failure mode — 26.7% of trades with Sharpe 0.13 and 50% WR. (3) Realistic gap fills severely degrade gap-open performance (Sharpe 3.35 → 0.87). Category B filter identified as immediate opportunity.
- **2026-03-18 — Literature review completed:** Training knowledge synthesis (web access denied). Strong published support for Range Quality direction: Crabel NR4/NR7, Market Profile POC position, VWAP, Osler stop clustering. Breakout Quality supported by volume confirmation heuristics (Elder/Murphy) and Bulkowski's ~20-25% structural failure rate for rectangle breakouts (consistent with our 26.7%). No landmark academic paper on Asian-London ORB specifically. Awaiting human decision on next steps: Category B filter validation vs. Range Quality research.
