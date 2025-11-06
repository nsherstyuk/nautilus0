# Multi-Timeframe Optimization Guide

## Overview
Find if better results can be achieved at different timeframes than 15-minute bars, and identify optimal parameter values for each timeframe.

## Existing Results

### Current Baseline (15-MINUTE)
- **Phase 6 Best**: Sharpe 0.481, PnL $10,859.43, Win Rate 62.1%
- **Parameters**: fast=42, slow=270, SL=35, TP=50

### Previous Multi-TF Test
- **Best**: Sharpe 0.453, PnL $14,203.91 (tested trend filters, not primary bar specs)

## Recommended Approach

### Step 1: Quick Test (20 combinations, ~20 minutes)
```powershell
python optimization/grid_search.py `
  --config optimization/configs/multi_timeframe_focused.yaml `
  --objective sharpe_ratio `
  --workers 15
```

### Step 2: Analyze Results
```powershell
python scripts/analyze_timeframe_results.py `
  optimization/results/multi_timeframe_focused_results.csv
```

### Step 3: Comprehensive Test (216 combinations, ~30-45 minutes)
If promising timeframes found:
```powershell
python optimization/grid_search.py `
  --config optimization/configs/multi_timeframe_complete.yaml `
  --objective sharpe_ratio `
  --workers 15
```

## Expected Parameter Scaling

| Timeframe | Fast Period | Slow Period | Risk Settings |
|-----------|-------------|-------------|---------------|
| 1-MINUTE  | 10-20       | 50-100      | SL=20-25, TP=40-50 |
| 5-MINUTE  | 20-30       | 100-150     | SL=25-35, TP=50 |
| 15-MINUTE | 42          | 270         | SL=35, TP=50 (baseline) |
| 30-MINUTE | 50-60       | 300-400     | SL=35, TP=50-75 |
| 1-HOUR    | 60-80       | 400-500     | SL=35-50, TP=75+ |

## Files Created

1. **multi_timeframe_focused.yaml** - Quick test (20 combos, ~20 min)
2. **multi_timeframe_complete.yaml** - Full test (216 combos, ~30-45 min)
3. **multi_timeframe_comprehensive.yaml** - Extended test (378 combos, ~2 hours)
4. **scripts/analyze_timeframe_results.py** - Analysis tool

## Next Steps

1. Set environment variables
2. Run focused test
3. Analyze results by timeframe
4. Run comprehensive test on promising timeframes
5. Optimize filters for best timeframe if found

