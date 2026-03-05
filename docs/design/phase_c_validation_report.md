# Phase C Validation Report - B2 Candidate

**Generated:** 2026-02-13 16:01:20

**Candidate:** B2 (XPair Threshold = 0.00040, TP1 = 0.9x ATR, SL = 1.2x ATR)

**Backtest Period:** 2025-02-01 to 2026-02-01 (1 year)

---

## Executive Summary

- **Total Trades:** 240
- **Total P&L:** $1,059.38
- **Win Rate:** 72.9%
- **Max Drawdown:** -17.8%
- **Sharpe Ratio:** 3.63
- **Profit Factor:** 1.61

---

## Risk Metrics

- Max Consecutive Losses: 4
- Max Consecutive Wins: 21
- Sortino Ratio: 5.57
- Average Win: $15.97
- Average Loss: $-26.69

---

## Trade Distribution

- Clustering Score: 0.51
- Gap Weeks: 3 / 54

---

## Directional Performance

- Long Trades: 98 (WR: 78.6%, P&L: $854.07)
- Short Trades: 142 (WR: 69.0%, P&L: $205.31)

---

## Final Decision

### 🟢 GO FOR LIVE DEPLOYMENT

**Criteria Passed:** 4/5

**Recommendation:**
B2 passes validation. Recommend deployment with conservative sizing (start at 50% target position size).

---

## Next Steps

If GO:
1. Deploy to IBKR paper account for 1-week live validation
2. Start with 25-50% of target position size
3. Monitor for regime changes (volatility spikes, news events)
4. Compare live vs backtest performance daily

If NO-GO:
1. Initiate Phase D: Test intermediate thresholds (0.000375, 0.000385)
2. Consider additional filters (ATR bands, hour exclusions)
3. Explore 2-position TP/SL strategy (currently using 1-position)