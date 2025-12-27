# Drawdown Metrics Added to Backtest Summary

## Overview
Comprehensive drawdown analysis has been added to the backtest summary report (`summary.txt`). This provides critical risk assessment metrics beyond just total PnL and win rate.

## Metrics Included

### 1. Max Drawdown
- **Dollar Amount**: Largest peak-to-trough decline in account equity
- **Percentage**: Drawdown as percentage of peak equity
- **Example**: `Max Drawdown: $-1,558.04 (-7.9%)`

### 2. Max Drawdown Period
- **Start Date**: When the peak occurred before the drawdown
- **End Date**: When the maximum drawdown was reached
- **Duration**: Number of days from peak to trough
- **Example**: `Max Drawdown Period: 2025-11-13 to 2025-12-17 (33 days)`

### 3. Average Drawdown
- **Calculation**: Mean of all negative drawdown values
- **Purpose**: Shows typical drawdown magnitude during losing periods
- **Example**: `Average Drawdown: $-245.67`

### 4. Recovery Time
- **Calculation**: Days from max drawdown to full recovery (if recovered)
- **Status**: Shows "Not yet recovered" if still in drawdown
- **Example**: `Recovery Time: 15 days` or `Recovery Time: Not yet recovered`

### 5. Current Drawdown
- **Real-time Status**: Current drawdown at end of backtest period
- **Interpretation**: $0.00 means fully recovered, negative means still in drawdown
- **Example**: `Current Drawdown: $-1,558.04`

## Example Summary Output

```
================================================================================
MTF V2 STRATEGY - DETAILED BACKTEST REPORT
================================================================================

Period: 2025-01-01 to 2025-12-19
Total Trades: 2079
Total P&L: $18,155.01
Win Rate: 68.4%

================================================================================
DRAWDOWN ANALYSIS
================================================================================
Max Drawdown: $-1,558.04 (-7.9%)
Max Drawdown Period: 2025-11-13 to 2025-12-17 (33 days)
Average Drawdown: $-245.67
Recovery Time: Not yet recovered
Current Drawdown: $-1,558.04

================================================================================
TOP 5 HOURS BY P&L (EST)
================================================================================
...
```

## Why This Matters

### Risk Assessment
- **Max Drawdown** shows worst-case scenario
- **Drawdown Duration** indicates how long you might be underwater
- **Recovery Time** shows resilience of the strategy

### Parameter Comparison
When comparing different parameter sets, consider:
1. **Total PnL** - Overall profitability
2. **Win Rate** - Consistency
3. **Max Drawdown** - Risk exposure
4. **Drawdown Duration** - Psychological tolerance

### Example Decision Making

**Strategy A:**
- PnL: $20,000
- Win Rate: 65%
- Max Drawdown: -$5,000 (25%)
- Duration: 60 days

**Strategy B:**
- PnL: $18,000
- Win Rate: 68%
- Max Drawdown: -$1,500 (8%)
- Duration: 30 days

**Strategy B might be preferable** despite lower PnL due to:
- Much lower risk (8% vs 25% drawdown)
- Faster recovery (30 vs 60 days)
- Better psychological sustainability

## Risk-Adjusted Metrics

You can now calculate:
- **Calmar Ratio**: Total PnL / Max Drawdown
- **Risk-Reward**: Expected return per unit of risk
- **Drawdown Recovery**: How quickly strategy bounces back

## Implementation Details

- **File Modified**: `run_backtest_mtf_v2_full.py`
- **Function**: `generate_reports()`
- **Lines**: 492-546
- **Handles**: Invalid exit times, edge cases, recovery detection

## Next Steps

Future backtests will automatically include these metrics in `summary.txt`. Use them to:
1. Compare parameter sets more holistically
2. Assess risk tolerance before live trading
3. Set appropriate position sizing based on max drawdown
4. Understand recovery characteristics of your strategy
