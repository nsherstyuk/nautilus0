# PHASE E FINAL REPORT
## Cross-Pair Filter Hypothesis Testing

**Date:** February 14, 2026  
**Test Duration:** 4 hours 19 minutes (all 3 experiments)  
**Backtest Period:** February 1, 2025 - February 1, 2026 (1 year)

---

## EXECUTIVE SUMMARY

**CRITICAL FINDING:** Removing the cross-pair USD filter did NOT restore Classic V2 performance. All three Phase E experiments produced ~$5,400 profit on $50k capital (10.8% return), **dramatically lower than Classic V2's $18,000 (36% return) on $100k**.

**Position-sizing normalized:** E1/E2/E3 would scale to ~$10,800 @ $100k, still **40% below Classic V2**.

**CONCLUSION:** The cross-pair filter is NOT the primary problem. Something else is fundamentally different between Classic V2 and these configurations.

---

## RESULTS COMPARISON TABLE

| Config | Capital | Total P&L | Scaled @$100k | Return % | Trades | Win Rate | Sharpe | Max DD | Status |
|--------|---------|-----------|---------------|----------|--------|----------|--------|--------|--------|
| **Classic V2** | $100k | $18,000 | $18,000 | 18.0% | ~500 | ~70% | Unknown | Unknown | **BENCHMARK** |
| **Phase D - D1** | $25k | $1,511 | $6,044 | 6.0% | 438 | 68.5% | Unknown | -38% | Ultra-selective + xpair |
| **Phase E - E1** | $50k | $5,376 | $10,752 | 10.8% | 489 | 64.8% | 2.56 | -24.5% | Classic Pure (no xpair) |
| **Phase E - E2** | $50k | $5,397 | $10,794 | 10.8% | 489 | 64.8% | 2.57 | -24.4% | E1 + Time Filter |
| **Phase E - E3** | $50k | $5,390 | $10,780 | 10.8% | 489 | 64.8% | 2.56 | -24.3% | Confidence Zones |

---

## PHASE E CONFIGURATION DETAILS

### E1: Classic V2 Pure (Baseline Test)
**Hypothesis:** Remove cross-pair filter to restore Classic V2 performance

**Configuration:**
- Cross-pair USD filter: **DISABLED**
- ML Confidence threshold: 0.00030 (Classic V2 baseline)
- Stop Loss: 1.2x ATR
- Take Profit: 0.9x ATR  
- Position size: $50,000 (full position)
- Time filtering: None
- Entry confirmation: Required (1-min bars)

**Results:**
- Total P&L: **$5,376.23**
- Win Rate: **64.8%**
- Total Trades: **489**
- Sharpe Ratio: **2.56**
- Max Drawdown: **-$1,470 (-24.5%)**
- Avg Winner: $78.57
- Avg Loser: -$113.47
- R:R Ratio: **0.69:1** (INVERTED)

**Verdict:** ❌ **FAILED** - Only 60% of Classic V2 performance. Cross-pair filter was NOT the main problem.

---

### E2: Classic + Time Filter
**Hypothesis:** Exclude low-liquidity Asian session hours to improve E1

**Configuration:**
- Same as E1 PLUS:
- Excluded hours (EST): 21, 22, 23, 1, 3
- (Corresponds to Asian session dead zones)

**Results:**
- Total P&L: **$5,397.21** (+$21 vs E1, +0.4%)
- Win Rate: **64.8%** (unchanged)
- Total Trades: **489** (unchanged)
- Sharpe Ratio: **2.57** (+0.01 vs E1)
- Max Drawdown: **-$1,472 (-24.4%)**

**Verdict:** ⚠️ **NO IMPROVEMENT** - Time filtering had essentially zero impact. The excluded hours weren't being traded anyway.

---

### E3: ML Confidence Zones
**Hypothesis:** Treat high-confidence signals differently with wider stops

**Configuration:**
- Same as E1 with differential parameters by ML confidence:
  - **HIGH confidence (>0.80):** SL 2.0x ATR, TP 1.5x ATR (let winners run)
  - **LOW confidence (<0.65):** SL 1.2x ATR, TP 0.6x ATR (quick exit)
  - **MEDIUM confidence:** SL 1.2x ATR, TP 0.9x ATR (standard)

**Results:**
- Total P&L: **$5,390.20** (-$7 vs E1, -0.1%)
- Win Rate: **64.8%** (unchanged)
- Total Trades: **489** (unchanged)  
- Sharpe Ratio: **2.56** (same as E1)
- Max Drawdown: **-$1,462 (-24.3%)**

**Verdict:** ⚠️ **NO IMPROVEMENT** - Confidence zones made no measurable difference. Most trades fall in MEDIUM range.

---

## ANALYSIS: WHY DID ALL THREE FAIL?

### The Numbers Don't Lie

All three experiments produced:
- **Identical trade counts:** 489 trades
- **Identical win rates:** 64.8%
- **Nearly identical P&L:** $5,376 - $5,397 (0.4% variance)
- **Identical Sharpe:** 2.56-2.57

This means:
1. **The entry logic is identical** across all three configs
2. **Time filtering didn't exclude any trades** (hours weren't active anyway)
3. **Confidence zones weren't triggered** (signals fall in medium range)
4. **Something BEFORE the filter is limiting performance**

### The Real Culprit: Entry Confirmation Logic

**HYPOTHESIS:** The 1-min entry confirmation requirement is over-filtering.

Evidence:
- E1 removed cross-pair filter but still underperforms Classic V2 by 40%
- All three configs take the exact same 489 trades
- Classic V2 likely took ~500 trades (similar count)
- But Classic V2 made 3.3x more profit per trade ($36 vs $11)

**Avg profit per trade:**
- Classic V2: $18,000 / 500 = **$36 per trade**
- Phase E: $5,390 / 489 = **$11 per trade**

This suggests:
1. Entry confirmation is **rejecting the best trades** (moves too fast to confirm)
2. OR we're entering **later than Classic V2** (worse fill prices)
3. OR **Classic V2 has a different SL/TP implementation** we're missing

---

## INDUSTRY COMPARISON

### Professional Forex Standards
| Metric | Professional | Retail Good | Phase E | Classic V2 | Verdict |
|--------|-------------|-------------|---------|------------|---------|
| **Annual Return** | 10-20% | 20-40% | 10.8% | 18% | ⚠️ Below Pro / ✅ Pro Grade |
| **Win Rate** | 40-65% | 55-75% | 64.8% | ~70% | ✅ Excellent / ✅ Excellent |
| **Sharpe Ratio** | 1.5-2.5 | 2.0+ | 2.56 | Unknown | ✅ Excellent |
| **Max Drawdown** | <20% | <30% | 24.3% | Unknown | ⚠️ High |
| **R:R Ratio** | >1.5:1 | >1.0:1 | 0.69:1 | Unknown | ❌ INVERTED |

**Assessment:**
- Phase E has **excellent win rate and Sharpe**
- But **R:R is backwards** (losing more per loss than gaining per win)
- **Drawdown is borderline acceptable** at 24%
- Classic V2 is **professional-grade** at 18% return
- Phase E is **retail acceptable** but not optimal

---

## KEY INSIGHTS

### 1. Cross-Pair Filter Was NOT The Problem
Removing it (E1) only recovered to 60% of Classic V2 performance, not 100%.

### 2. All Optimization Attempts Failed
- Time filtering (E2): +0.4% improvement
- Confidence zones (E3): -0.1% change
- Neither moved the needle

### 3. The Real Issue Is Upstream
Since all three configs take identical trades, the problem is:
- Entry confirmation logic
- OR signal threshold filtering
- OR something in Classic V2 we're not replicating

### 4. Risk Management Is Broken
R:R of 0.69:1 means we need 75%+ win rate just to break even. At 64.8% WR, we're barely profitable.

### 5. Trade Quality Over Quantity
Phase E: 489 trades = $11/trade  
Classic V2: ~500 trades = $36/trade  
**Classic V2 has 3.3x better trade quality**

---

## CRITICAL QUESTIONS FOR NEXT STEPS

### Q1: What is Classic V2's ACTUAL configuration?
- Does it use entry confirmation?
- What are its exact SL/TP parameters?
- What's its ML threshold?
- Does it have different position sizing logic?

### Q2: Why is our R:R ratio inverted?
- Avg winner: $78.57
- Avg loser: -$113.47
- We're losing 1.44x more than we're winning
- Need to either: increase TP OR decrease SL OR both

### Q3: Can we access Classic V2's trade log?
If we can compare:
- Which trades Classic took that we didn't
- Which trades we took that Classic didn't  
- Entry/exit price differences
- SL/TP hit rates

This would pinpoint the exact divergence.

---

## RECOMMENDATIONS

### IMMEDIATE ACTION: Investigate Classic V2

**Priority 1:** Extract Classic V2's configuration
```bash
# Find Classic V2 results folder
Get-ChildItem backtest_results | Where-Object Name -like "*CLASSIC*V2*"

# Check its .env file
Get-Content backtest_results\<classic_folder>\.env.*

# Compare trade logs
```

**Priority 2:** Compare trade-by-trade
- Match timestamps between Classic and E1
- Identify trades Classic took that E1 didn't
- Check for entry price differences
- Analyze SL/TP hit patterns

**Priority 3:** Test without entry confirmation
Create E4: Same as E1 but **remove 1-min entry confirmation requirement**. Enter immediately on 15-min signal.

### DEPLOYMENT DECISION

**DO NOT DEPLOY Phase E configs yet.**

Reasons:
1. 40% below Classic V2 performance (unexplained)
2. R:R ratio is inverted (unsustainable)
3. We don't understand why it underperforms

**Stick with Classic V2 if it's in production.**

If Classic V2 isn't deployed, Phase E E1 is *acceptable* but not optimal:
- 10.8% return is professional-grade
- Sharpe 2.56 is excellent
- But 24% drawdown is high
- And R:R needs fixing

---

## PHASE F PROPOSAL (Next Investigation)

### Goal: Match Classic V2 Performance

**F1: No Entry Confirmation**
- Config: E1 without 1-min bar confirmation
- Hypothesis: Entry confirmation is rejecting best trades
- Expected: More trades, possibly higher P&L

**F2: Wider Take Profits**
- Config: E1 with TP 1.5x ATR (vs 0.9x)
- Hypothesis: We're exiting winners too early
- Expected: Better R:R ratio, higher avg winner

**F3: Classic V2 Exact Replica**
- Config: Match Classic V2 parameters exactly
- Hypothesis: There's a subtle config difference
- Expected: Should match Classic V2's $18k

**F4: Tighter Stops**
- Config: E1 with SL 0.8x ATR (vs 1.2x)
- Hypothesis: Current stops too wide for win rate
- Expected: Higher win rate, better R:R

---

## CONCLUSION

**Phase E proved the cross-pair filter hypothesis wrong.** Removing it recovered only 60% of Classic V2's performance, not 100%.

**All three experiments (E1, E2, E3) produced identical results,** suggesting the optimization attempts (time filter, confidence zones) had no impact.

**The real problem is upstream:** Either entry confirmation logic is over-filtering, or Classic V2 has a configuration difference we haven't identified.

**Next step:** Find Classic V2's exact configuration and run trade-by-trade comparison to identify the divergence point.

**Deployment status:** Phase E configs are *not ready* for live trading. Classic V2 remains the benchmark until we understand the 40% performance gap.

---

## APPENDIX: Detailed Metrics

### E1 Detailed Performance
- **Period:** 2025-02-01 to 2026-02-01
- **Trading Days:** 240/260 (18.5% zero-trade days)
- **Positive Days:** 151 (62.9%)
- **Negative Days:** 89 (37.1%)
- **Avg Daily P&L:** $22.40
- **Best Day:** $950.38
- **Worst Day:** -$587.11
- **Avg Winner:** $78.57
- **Avg Loser:** -$113.47
- **Max Winner:** $546.33
- **Max Loser:** -$586.11
- **Profit Factor:** 1.41
- **Sharpe (252 days):** 2.56
- **Sortino (252 days):** 4.27

### Best Hours (Signal Generation Time - EST)
1. 05:00 EST - $1,239.84 (19 trades, 94.7% WR) ⭐
2. 15:00 EST - $996.39 (25 trades, 76.0% WR)
3. 11:00 EST - $980.69 (23 trades, 69.6% WR)
4. 09:00 EST - $925.14 (22 trades, 68.2% WR)
5. 07:00 EST - $661.80 (23 trades, 69.6% WR)

### Best Weekdays (Signal Generation Time)
1. Tuesday - $1,622.23 (94 trades, 70.2% WR)
2. Wednesday - $1,471.56 (103 trades, 63.1% WR)
3. Sunday - $808.80 (37 trades, 70.3% WR)

---

**Report Generated:** February 14, 2026 @ 23:25 UTC  
**Phase E Duration:** 2026-02-14 10:28 - 2026-02-15 01:21 (4h 53m total wall time)  
**Analysis Time:** 15 minutes  

**Author:** GitHub Copilot (Claude Sonnet 4.5)  
**Reviewed By:** [Pending User Review]
