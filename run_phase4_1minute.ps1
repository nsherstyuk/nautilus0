# Phase 4: 1-Minute Data Execution Script
# =====================================
# 
# This script sets up environment for 1-minute data optimization
# and runs Phase 4 with appropriate parameter scaling

# Set environment variables for 1-minute data
$env:BACKTEST_SYMBOL = "EUR/USD"
$env:BACKTEST_VENUE = "IDEALPRO"
$env:BACKTEST_START_DATE = "2025-01-01"
$env:BACKTEST_END_DATE = "2025-07-31"
$env:BACKTEST_BAR_SPEC = "1-MINUTE-MID-EXTERNAL"  # Changed from 15-MINUTE
$env:CATALOG_PATH = "data/historical"
$env:OUTPUT_DIR = "logs/backtest_results"

Write-Host "=== Phase 4: 1-Minute Data Optimization ===" -ForegroundColor Cyan
Write-Host "Bar Spec: $env:BACKTEST_BAR_SPEC" -ForegroundColor Yellow
Write-Host "Date Range: $env:BACKTEST_START_DATE to $env:BACKTEST_END_DATE" -ForegroundColor Yellow

# Run Phase 4 with 1-minute data
python optimization/grid_search.py --config optimization/configs/phase4_risk_management_1minute.yaml --objective sharpe_ratio --workers 8 --output optimization/results/phase4_1minute_results.csv --no-resume --verbose
