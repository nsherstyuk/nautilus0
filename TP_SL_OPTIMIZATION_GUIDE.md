# TP/SL Optimization Guide: Hour, Weekday, and Month-Based Settings

## Overview
This guide explains how to investigate and implement optimal Take Profit (TP) and Stop Loss (SL) settings that vary based on trading hours, weekdays, and months.

## Current Implementation
- **Default TP**: 50 pips
- **Default SL**: 25 pips  
- **Trailing Stop Activation**: 20 pips
- **Trailing Stop Distance**: 15 pips

## Investigation Approaches

### 1. **Post-Trade Analysis** (Quick Start)
Use the `analyze_optimal_tp_sl.py` script to analyze existing backtest results:

```bash
python analyze_optimal_tp_sl.py logs/backtest_results/EUR-USD_20251111_185105
```

**What it does:**
- Analyzes actual trade outcomes
- Calculates what TP/SL would have been optimal
- Identifies patterns by hour/weekday/month
- Suggests TP/SL combinations to test

**Limitations:**
- Only analyzes trades that were actually taken
- Doesn't account for trades that would have been taken with different settings
- Assumes same entry timing

### 2. **Grid Search Backtesting** (Most Comprehensive)
Run multiple backtests with different TP/SL combinations and compare results.

**Steps:**
1. Create a parameter grid:
   ```python
   tp_values = [30, 40, 50, 60, 70, 80]
   sl_values = [15, 20, 25, 30, 35]
   ```

2. Run backtests for each combination
3. Analyze results by hour/weekday/month
4. Identify optimal settings for each dimension

**Implementation:**
- Modify `backtest/run_backtest.py` to accept TP/SL parameters
- Create a batch script to run multiple backtests
- Aggregate results for comparison

### 3. **Walk-Forward Optimization** (Most Robust)
Split data into training and testing periods:
- Use training period to find optimal TP/SL
- Test on out-of-sample period
- Roll forward and repeat

**Benefits:**
- Avoids overfitting
- Tests robustness across different market conditions
- More realistic performance expectations

### 4. **Market Regime-Based Optimization**
Different TP/SL settings for different market conditions:
- **Trending markets**: Wider TP, tighter SL
- **Ranging markets**: Tighter TP, wider SL
- **High volatility**: Wider both
- **Low volatility**: Tighter both

**Implementation:**
- Use ATR or volatility indicators to detect regime
- Apply different TP/SL based on regime
- Optimize settings for each regime separately

## Implementation Strategies

### Strategy A: Static Rules Based on Time Dimensions
Create lookup tables for TP/SL by hour/weekday/month:

```python
# Example configuration
TP_SL_RULES = {
    'hour': {
        13: {'tp': 60, 'sl': 20},  # Hour 13: wider TP
        20: {'tp': 50, 'sl': 25},  # Hour 20: default
    },
    'weekday': {
        'Monday': {'tp': 55, 'sl': 22},
        'Friday': {'tp': 45, 'sl': 30},  # Tighter on Fridays
    },
    'month': {
        '2024-01': {'tp': 50, 'sl': 25},
        '2024-07': {'tp': 40, 'sl': 30},  # Different for July
    }
}
```

**Pros:**
- Simple to implement
- Easy to understand and debug
- Fast execution

**Cons:**
- May overfit to historical data
- Doesn't adapt to changing conditions
- Requires manual updates

### Strategy B: Dynamic ATR-Based Settings
Use ATR to adjust TP/SL dynamically:

```python
def calculate_dynamic_tp_sl(entry_price, atr_value, base_tp_pips, base_sl_pips):
    # Convert ATR to pips
    atr_pips = atr_value * 10000  # Assuming 4 decimal places
    
    # Scale TP/SL based on ATR
    tp_pips = base_tp_pips * (atr_pips / 20)  # Normalize to 20 pips ATR
    sl_pips = base_sl_pips * (atr_pips / 20)
    
    # Apply hour/weekday/month multipliers
    hour_multiplier = get_hour_multiplier(current_hour)
    weekday_multiplier = get_weekday_multiplier(current_weekday)
    month_multiplier = get_month_multiplier(current_month)
    
    tp_pips *= hour_multiplier * weekday_multiplier * month_multiplier
    
    return tp_pips, sl_pips
```

**Pros:**
- Adapts to market volatility
- More robust across different conditions
- Combines time-based and volatility-based logic

**Cons:**
- More complex
- Requires ATR calculation
- May need calibration

### Strategy C: Machine Learning Approach
Train a model to predict optimal TP/SL:

**Features:**
- Hour, weekday, month
- ATR, volatility
- Trend strength (DMI)
- Market regime indicators
- Recent performance

**Target:**
- Optimal TP/SL for next trade

**Pros:**
- Can capture complex patterns
- Adapts automatically
- Can incorporate many features

**Cons:**
- Requires large dataset
- Black box - hard to interpret
- Risk of overfitting
- More complex to implement

## Recommended Workflow

### Phase 1: Analysis (Current)
1. Run `analyze_optimal_tp_sl.py` on recent backtest
2. Identify patterns:
   - Which hours have larger price movements?
   - Which weekdays are more volatile?
   - Which months show different behavior?
3. Generate initial hypotheses

### Phase 2: Grid Search
1. Select 3-5 promising TP/SL combinations from analysis
2. Run backtests for each combination
3. Compare results by hour/weekday/month
4. Identify best overall and best per dimension

### Phase 3: Validation
1. Test optimal settings on out-of-sample data
2. Verify improvements hold across different periods
3. Check for overfitting (if results degrade, settings may be too specific)

### Phase 4: Implementation
1. Start with simple static rules (Strategy A)
2. Add ATR-based adjustments (Strategy B) if beneficial
3. Consider ML approach (Strategy C) only if dataset is large enough

## Key Metrics to Track

1. **Total PnL**: Overall profitability
2. **Win Rate**: Percentage of winning trades
3. **Risk/Reward Ratio**: Average win / Average loss
4. **Sharpe Ratio**: Risk-adjusted returns
5. **Maximum Drawdown**: Largest peak-to-trough decline
6. **Profit Factor**: Gross profit / Gross loss

## Important Considerations

### 1. **Sample Size**
- Need sufficient trades per hour/weekday/month combination
- Minimum 20-30 trades per group for statistical significance
- Be cautious with rare combinations

### 2. **Overfitting Risk**
- More granular = higher overfitting risk
- Prefer simpler rules that work across multiple dimensions
- Validate on out-of-sample data

### 3. **Transaction Costs**
- Different TP/SL = different trade frequency
- Account for spreads and commissions
- Net PnL matters more than gross PnL

### 4. **Market Evolution**
- Markets change over time
- Settings that worked in 2024 may not work in 2025
- Regular re-optimization may be needed

### 5. **Implementation Complexity**
- More complex = harder to maintain
- Start simple, add complexity only if beneficial
- Document all rules clearly

## Next Steps

1. **Run the analysis script** on your latest backtest
2. **Review the report** to identify patterns
3. **Select 3-5 TP/SL combinations** to test
4. **Run grid search backtests** (can automate this)
5. **Compare results** and select best approach
6. **Implement** chosen strategy in code
7. **Validate** on new data

## Code Modifications Needed

To implement dynamic TP/SL:

1. **Add configuration** for time-based TP/SL rules
2. **Modify `_calculate_sl_tp_prices`** to accept context (hour, weekday, month)
3. **Add lookup tables** or calculation functions
4. **Update backtest runner** to pass context
5. **Add logging** to track which TP/SL was used

Would you like me to implement any of these approaches?

