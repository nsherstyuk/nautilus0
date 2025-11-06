# Quick Reference: Comparing Optimization Results

## TL;DR

**To find the best results:**

```bash
# View top results from a single optimization
python scripts/analyze_optimization_results.py \
    --results optimization/results/YOUR_RESULTS.csv \
    --top 20

# Compare multiple optimization runs
python scripts/analyze_optimization_results.py \
    --compare \
    --results optimization/results/run1.csv \
    --results optimization/results/run2.csv \
    --results optimization/results/run3.csv
```

## What Makes a Result "Best"?

Results are automatically ranked by your **objective function** (default: Sharpe Ratio). 

**Key metrics to consider:**
- ✅ **Sharpe Ratio** - Risk-adjusted returns (higher is better)
- ✅ **Total PnL** - Total profit/loss
- ✅ **Win Rate** - Percentage of winning trades
- ✅ **Trade Count** - Number of trades (need 30+ for significance)
- ✅ **Max Drawdown** - Maximum loss from peak (lower is better)

## Output Files

After running optimization, you get:

1. **`{config}_results.csv`** - All results, ranked by objective
   - Column `rank` = 1 is the best
   - Already sorted by objective value

2. **`{config}_results_summary.json`** - Quick summary
   - Best result with all parameters
   - Worst result
   - Average metrics

3. **`{config}_results_top_10.json`** - Top 10 results
   - Easy to read JSON format
   - Includes all parameters and metrics

## Quick Comparison Methods

### Method 1: Use the Analysis Script (Easiest)

```bash
# Single run analysis
python scripts/analyze_optimization_results.py \
    --results optimization/results/multi_tf_primary_bar_spec_results.csv \
    --top 20

# Compare multiple runs
python scripts/analyze_optimization_results.py \
    --compare \
    --results optimization/results/run1.csv \
    --results optimization/results/run2.csv
```

### Method 2: Check Summary JSON

```bash
# View best result quickly
cat optimization/results/YOUR_RESULTS_summary.json | python -m json.tool
```

### Method 3: Open CSV in Excel/Spreadsheet

- Open `{config}_results.csv`
- Results are already sorted by `rank` column
- Filter/sort by any metric you want
- Column `rank` = 1 is the best

## Decision Criteria

**✅ Good Result:**
- Sharpe Ratio > 0.5
- Trade Count > 30
- Win Rate 50-70%
- Positive Expectancy
- Consistent with similar parameter sets

**⚠️ Warning Signs:**
- Very few trades (< 10)
- Extreme parameter values
- High max drawdown
- Negative expectancy

## Example Workflow

```bash
# 1. Run optimization
python optimization/grid_search.py \
    --config optimization/configs/multi_tf_primary_bar_spec.yaml

# 2. View top results
python scripts/analyze_optimization_results.py \
    --results optimization/results/multi_tf_primary_bar_spec_results.csv \
    --top 10

# 3. Check best parameters
cat optimization/results/multi_tf_primary_bar_spec_results_summary.json | \
    python -m json.tool | grep -A 30 "best"

# 4. Compare with other runs
python scripts/analyze_optimization_results.py \
    --compare \
    --results optimization/results/multi_tf_trend_filter_results.csv \
    --results optimization/results/multi_tf_primary_bar_spec_results.csv
```

## Finding Best Parameters

The best parameters are in:
- **CSV file**: Row where `rank` = 1
- **Summary JSON**: `best.parameters` section
- **Top 10 JSON**: First entry (`rank` = 1)

All parameter values are listed, ready to copy into your `.env` file for live trading or backtesting.

