# Quick Start Commands for Multi-Timeframe Extended Optimization
# ==============================================================

# PowerShell Commands (Windows)
# -----------------------------

# Step 1: Set environment variables (if not already set)
$env:BACKTEST_SYMBOL = 'EUR/USD'
$env:BACKTEST_START_DATE = '2025-01-01'
$env:BACKTEST_END_DATE = '2025-10-30'
$env:BACKTEST_VENUE = 'IDEALPRO'
$env:CATALOG_PATH = 'data/historical'
$env:OUTPUT_DIR = 'logs/backtest_results'

# Step 2: Run extended multi-timeframe optimization
python optimization/grid_search.py `
  --config optimization/configs/multi_timeframe_extended.yaml `
  --objective sharpe_ratio `
  --workers 15 `
  --output optimization/results/multi_timeframe_extended_results.csv `
  --no-resume

# Expected runtime: ~45-60 minutes with 15 workers
# Total combinations: 384 (6 timeframes × 4 fast periods × 4 slow periods × 2 SL × 2 TP)

# After completion, analyze results:
python scripts/analyze_timeframe_results.py optimization/results/multi_timeframe_extended_results.csv

