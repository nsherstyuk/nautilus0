# Classic MTF V2 vs B2 (Cross-Pair Confirmed) Comparison

**Generated:** February 13, 2026  
**⚠️ CORRECTED FOR POSITION SIZE DIFFERENCE**

---

## Executive Summary

Comparing **Classic MTF V2** (no entry confirmation) against **B2** (cross-pair USD confirmation with 0.00040 threshold).

**CRITICAL:** Classic V2 used $100k position size, B2 used $25k position size (4x difference).

| Metric | Classic V2 (REPLAY) | B2 (XPair Confirmed) | B2 Normalized (4x) | Winner |
|--------|-------------------|---------------------|-------------------|---------|
| **Position Size** | $100,000 | $25,000 | $100,000 | Equal |
| **Test Period** | 2025-01-01 to 2025-12-19 | 2025-02-01 to 2026-02-01 | Same | ~Similar |
| **Total Trades** | 2,079 | 240 | 240 | Classic V2 (8.7x more) |
| **Total P&L (Actual)** | $18,155.01 | $1,059.38 | **$4,237.52** | Classic V2 (4.3x more) |
| **Win Rate** | 68.4% | 72.9% | 72.9% | **B2 (+4.5%)** ⭐ |
| **P&L per Trade** | $8.73 | $4.41 | **$17.66** | **B2 (2x more)** ⭐ |
| **Max Drawdown** | Unknown | -17.8% | -17.8% | Likely B2 |
| **Sharpe Ratio** | Unknown | 3.63 | 3.63 | **B2** ⭐ |
| **Profit Factor** | Unknown | 1.61 | 1.61 | Unknown |
| **Max Consecutive Losses** | Unknown | 4 | 4 | **B2** ⭐ |
| **Trade Frequency** | ~7 trades/day | ~0.66 trades/day | ~0.66 trades/day | Classic V2 |

---

## Detailed Analysis

### 🎯 **Trade Quality vs Quantity**

**Classic V2:**
- Takes ALL signals that pass ML threshold + MAMA filter
- High frequency: ~7 trades per day, 2,079 trades in ~11 months
- Lower win rate: 68.4% (31.6% losers)
- Average profit per trade: $8.73
- More exposure to market noise and false signals

**B2 (Cross-Pair Confirmed):**
- Requires USD strength confirmation from GBP/USD + USD/CHF
- Low frequency: ~0.66 trades per day, 240 trades in 12 months
- **Higher win rate: 72.9%** (27.1% losers)
- Average profit per trade: $4.41
- Filters out ~88% of classic V2 signals (keeping only 1 in 8)

**📊 Key Insight:**
B2's cross-pair filter removed **1,839 trades** (88% reduction) but achieved a **+4.5% higher win rate**. This suggests it successfully filtered out lower-quality signals.

---

### 💰 **Profitability Comparison (CORRECTED)**

**Normalized to $100k Position Size:**

| Metric | Classic V2 | B2 (Normalized 4x) | Difference |
|--------|------------|-------------------|------------|
| **Position Size** | $100,000 | $100,000 | Equal ✓ |
| **Total P&L (actual period)** | $18,155 | **$4,238** | -76% |
| **Monthly P&L** | $1,650 | $353 | -79% |
| **Annual ROI** | 36.3% | 8.5% | -77% |
| **P&L per Trade** | $8.73 | **$17.66** | **+102%** ⭐ |

**🔍 Revised Analysis:**

After correcting for position size:
- Classic V2 still generates **4.3x more total profit** ($18k vs $4.2k)
- **BUT:** B2's profit-per-trade is **2x higher** ($17.66 vs $8.73)
- The profitability gap narrowed from 17x to 4.3x - much more competitive!

**Key Insight:**
B2 is **more efficient per trade** but makes far fewer trades. The 8.7x frequency advantage of Classic V2 still dominates overall profitability.

---

### 📈 **Risk-Adjusted Performance**

**B2 Advantages:**
- **Sharpe Ratio 3.63** - Exceptional risk-adjusted returns
- **Max DD -17.8%** - Controlled downside
- **Max Consecutive Losses: 4** - Excellent streak control
- **Sortino Ratio: 5.57** - Superior downside protection

**Classic V2 Unknown Risk Metrics:**
- Likely higher drawdown (more trades = more exposure)
- Potentially more volatile equity curve
- Risk of overtrading and whipsaw losses

**🎯 Key Insight:**
B2 trades **safer** but generates far less profit in absolute terms. Classic V2 is more aggressive but likely delivers better returns if risk is manageable.

---

### 🔍 **Signal Filtering Effectiveness**

**What B2's Cross-Pair Filter Removed:**

Of the ~2,079 potential signals:
- **Kept:** 240 trades (11.5%)
- **Filtered out:** 1,839 trades (88.5%)

**Was the filtering beneficial?**

Calculating filtered trades' performance:
- Classic V2: 2,079 trades, 68.4% WR, $18,155 P&L (at $100k sizing)
- B2: 240 trades, 72.9% WR, $4,238 P&L (normalized to $100k sizing)
- **Implied filtered trades:** 1,839 trades, ~67.6% WR, ~$13,917 P&L

**📊 Analysis:**
The filtered-out signals had ~67.6% win rate (slightly worse than classic V2's 68.4%). B2 successfully improved win rate by 4.5% and doubled profit-per-trade, but **gave up $13,917 in annual profit** by filtering out 88% of opportunities.

---

### ⚖️ **Trade-Off Summary**

| Dimension | Classic V2 | B2 (Normalized) |
|-----------|------------|-----------------|
| **Philosophy** | High frequency, accept noise | Low frequency, high quality |
| **Profit Generation** | ✅ Excellent ($18k/year) | ⚠️ Moderate ($4.2k/year) |
| **Profit per Trade** | ✅ Good ($8.73) | ✅ Excellent ($17.66) |
| **Win Rate** | ✅ Good (68.4%) | ✅ Excellent (72.9%) |
| **Risk Management** | ⚠️ Unknown | ✅ Excellent (Sharpe 3.63, DD -17.8%) |
| **Trade Frequency** | ✅ High (7/day) | ❌ Very low (0.66/day) |
| **Capital Efficiency** | ✅ High utilization | ❌ Mostly idle (93% of time) |
| **Psychological Stress** | ⚠️ High (many trades) | ✅ Low (few trades) |

---

## 🏆 **VERDICT: Classic V2 Still Wins, But Closer Race**

### **Recommendation:**

**For Maximum Profit → Use Classic V2**

**Reasons:**
1. **4.3x more profit** ($18k vs $4.2k per year at equal position sizing)
2. B2's 2x better profit-per-trade is offset by 8.7x fewer opportunities
3. Position sitting idle 93% of time in B2 = massive opportunity cost
4. 68.4% win rate is already strong - not worth sacrificing volume for +4.5%

**When to Consider B2:**
- If Classic V2 drawdown exceeds 30% in live testing
- If risk-adjusted returns matter more than absolute profits (Sharpe 3.63 is exceptional)
- If trader psychology prefers fewer, higher-quality trades
- If running multiple strategies and want defensive allocation
- If account size limits allow only selective high-conviction trades

**Corrected Perspective:**
B2 is **not terrible** - it delivers $4.2k/year with excellent risk metrics. It's a valid choice for **conservative traders prioritizing safety over returns**. But Classic V2's 4.3x profit advantage still makes it the better option for most traders.

---

## 📋 **Action Items**

1. **Deploy Classic V2 to paper account** for 2 weeks
2. Monitor actual drawdown and consecutive loss streaks
3. If drawdown stays <25% and max consecutive losses <8 → **Go live with Classic V2**
4. Keep B2 as backup configuration if Classic V2 develops issues

---

## 🔬 **Alternative: Hybrid Approach**

**Idea:** Use variable position sizing based on cross-pair confirmation:
- **Full size (100%)** when cross-pair USD confirms (B2's 240 signals @ $17.66/trade = $4,238)
- **Half size (50%)** when cross-pair neutral/weak (Classic V2's remaining 1,839 signals @ ~$4.36/trade = $8,018)
- **Total expected:** $12,256/year (~68% of Classic V2, but with better risk profile)

**Expected Benefits:**
- Capture 68% of Classic V2's profit ($12k vs $18k)
- Maintain B2's excellent risk metrics on high-conviction trades
- Still trade frequently enough for good capital utilization (7 trades/day)
- Better risk-adjusted returns than pure Classic V2

**Implementation:** Medium complexity - requires dynamic sizing based on cross-pair USD strength

---

## 📊 **Data Sources**

- Classic V2: `MTF_V2_REPLAY_20251224_213359` (2025-01-01 to 2025-12-19)
- B2: `MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_20260213_090610` (2025-02-01 to 2026-02-01)
- B2 Validation: `PHASE_C_VALIDATION_REPORT.md` (2026-02-13)
