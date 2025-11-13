# Trailing Stop Optimization - Step-by-Step Guide

## Overview
This guide will help you optimize trailing stop settings by testing different combinations and analyzing results.

## Step 1: Run the Quick Optimization Script

Run the quick optimization script to test 5 key combinations:

```bash
python quick_trailing_optimization.py
```

**What it does:**
- Tests 5 trailing stop combinations:
  - (15, 10) - Early activation, tight distance
  - (20, 15) - Current default
  - (25, 20) - Standard, medium
  - (30, 25) - Late activation, wider
  - (20, 10) - Standard activation, tight distance
- Each backtest takes 2-5 minutes
- Total time: ~10-25 minutes

**Expected output:**
- Progress for each backtest
- Final comparison table
- Best combination recommendation
- JSON file with all results

## Step 2: Review the Results

After the script completes, you'll see:
1. **Comparison table** showing all combinations
2. **Best combination** identified
3. **Results folder** for each backtest

**Key metrics to compare:**
- **Total PnL**: Overall profitability
- **Win Rate**: Percentage of winning trades
- **Avg PnL**: Average profit per trade
- **Total Trades**: Number of trades executed

## Step 3: Analyze Detailed Results

For each backtest result folder, check:

### A. Overall Statistics
```bash
# View the trading hours analysis
cat logs/backtest_results/EUR-USD_<timestamp>/trading_hours_analysis.txt
```

### B. Compare Hourly Performance
```bash
# Compare hourly PnL across different settings
python -c "
import pandas as pd
from pathlib import Path

# List your result folders here
folders = [
    'logs/backtest_results/EUR-USD_<timestamp1>',
    'logs/backtest_results/EUR-USD_<timestamp2>',
    # Add more...
]

for folder in folders:
    df = pd.read_csv(f'{folder}/hourly_pnl_overall.csv')
    print(f'\n{folder}:')
    print(df[['hour', 'total_pnl', 'win_rate']].head(10))
"
```

### C. Run TP/SL Analysis
For each result folder, run:
```bash
python analyze_optimal_tp_sl.py logs/backtest_results/EUR-USD_<timestamp>
```

This will generate:
- `tp_sl_optimization_report.txt` - Analysis of TP/SL settings
- `tp_sl_optimization_report.json` - Machine-readable data

## Step 4: Identify Patterns

Look for patterns in the results:

### By Hour
- Which hours perform best with which trailing stop settings?
- Are there hours where early activation works better?
- Are there hours where late activation works better?

### By Weekday
- Do certain weekdays benefit from different settings?
- Is Friday different from Monday?

### By Month
- Are there seasonal patterns?
- Do certain months need different settings?

## Step 5: Test More Combinations (Optional)

If you want to test more combinations, use the full optimization script:

```bash
# Test first 10 combinations
python optimize_trailing_stops.py --combinations 10

# Test all combinations (takes longer)
python optimize_trailing_stops.py
```

## Step 6: Implement Best Settings

Once you've identified the best combination:

### Option A: Static Settings (Simplest)
Update your `.env` file:
```bash
BACKTEST_TRAILING_STOP_ACTIVATION_PIPS=25
BACKTEST_TRAILING_STOP_DISTANCE_PIPS=20
```

### Option B: Dynamic Settings (Advanced)
Implement time-based trailing stops:
- Different settings for different hours
- Different settings for different weekdays
- Different settings for different months

This requires code changes to the strategy.

## Step 7: Validate on New Data

Run a backtest on a different time period to validate:
- Use out-of-sample data (different months/years)
- Verify the settings still work well
- Check for overfitting

## Troubleshooting

### Unicode Errors
- Fixed in the updated script
- If you still see errors, they're non-critical (script continues)

### Script Takes Too Long
- Use `--combinations` to limit tests
- Start with 3-5 combinations
- Run overnight if testing many combinations

### No Results Generated
- Check that backtest completed successfully
- Verify `positions.csv` exists in results folder
- Check for errors in backtest output

## Next Steps After Optimization

1. **Document findings**: Record which settings work best
2. **Implement changes**: Update strategy code if needed
3. **Monitor performance**: Track results in live trading
4. **Re-optimize periodically**: Markets change, settings may need updates

## Questions to Answer

After running the optimization:

1. **What's the best overall combination?**
   - Check the comparison table
   - Look at Total PnL and Win Rate

2. **Are there time-based patterns?**
   - Compare hourly performance
   - Check weekday differences
   - Look for monthly variations

3. **Should settings be dynamic?**
   - If patterns are strong, consider time-based rules
   - If patterns are weak, use best overall settings

4. **Is the improvement significant?**
   - Compare to current settings
   - Check if improvement is consistent
   - Validate on out-of-sample data

## Example Analysis Workflow

```bash
# 1. Run quick optimization
python quick_trailing_optimization.py

# 2. Note the best combination (e.g., 25, 20)
# 3. Check detailed results for that combination
cat logs/backtest_results/EUR-USD_<best_timestamp>/trading_hours_analysis.txt

# 4. Run TP/SL analysis
python analyze_optimal_tp_sl.py logs/backtest_results/EUR-USD_<best_timestamp>

# 5. Compare with current settings
python analyze_optimal_tp_sl.py logs/backtest_results/EUR-USD_20251111_185105

# 6. Make decision and implement
```

## Need Help?

If you encounter issues or need clarification:
1. Check the error messages
2. Verify your `.env` file has correct settings
3. Ensure you have enough historical data
4. Check that backtest completes successfully

