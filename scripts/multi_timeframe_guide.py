"""
Multi-Timeframe Optimization Guide

This guide explains how to optimize across different timeframes and find
optimal parameters for each timeframe.

APPROACH:
1. Test multiple timeframes (1-min to 1-hour)
2. Optimize MA periods for each timeframe (shorter timeframes need faster periods)
3. Test risk management parameters per timeframe
4. Compare results to find best timeframe

EXISTING RESULTS:
- Multi-TF Combined: Best Sharpe 0.453 with 1-MINUTE bars, PnL $14,203.91
- Phase 6 (15-MIN): Best Sharpe 0.481, PnL $10,859.43
- Current baseline: 15-MINUTE-MID-EXTERNAL

STRATEGY:
1. Run focused search first (20 combinations, ~20 min)
2. Analyze results to identify promising timeframes
3. Run comprehensive search on best timeframes (378 combinations, ~2 hours)
4. For each promising timeframe, run full parameter optimization

QUICK START:
# Step 1: Quick test across timeframes
python optimization/grid_search.py `
  --config optimization/configs/multi_timeframe_focused.yaml `
  --objective sharpe_ratio `
  --workers 15

# Step 2: Analyze results
python scripts/analyze_optimization_results.py `
  optimization/results/multi_timeframe_focused_results.csv

# Step 3: If promising, run comprehensive
python optimization/grid_search.py `
  --config optimization/configs/multi_timeframe_comprehensive.yaml `
  --objective sharpe_ratio `
  --workers 15

EXPECTED PARAMETER SCALING:
- 1-MINUTE: fast=10-20, slow=50-100 (very fast)
- 5-MINUTE: fast=20-30, slow=100-150 (fast)
- 15-MINUTE: fast=42, slow=270 (baseline)
- 30-MINUTE: fast=50-60, slow=300-400 (slow)
- 1-HOUR: fast=60-80, slow=400-500 (very slow)

RISK MANAGEMENT CONSIDERATIONS:
- Shorter timeframes: May need tighter stops (20-25 pips)
- Longer timeframes: Can use wider stops (35-50 pips)
- Take profit may need scaling too (40-75 pips range)
"""

print(__doc__)

