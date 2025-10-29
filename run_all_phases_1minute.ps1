# Complete 1-Minute Data Optimization Pipeline
# ============================================
# 
# This script runs all optimization phases with 1-minute data
# You MUST run all phases in sequence for 1-minute data

# Set environment variables for 1-minute data
$env:BACKTEST_SYMBOL = "EUR/USD"
$env:BACKTEST_VENUE = "IDEALPRO"
$env:BACKTEST_START_DATE = "2025-01-01"
$env:BACKTEST_END_DATE = "2025-07-31"
$env:BACKTEST_BAR_SPEC = "1-MINUTE-MID-EXTERNAL"
$env:CATALOG_PATH = "data/historical"
$env:OUTPUT_DIR = "logs/backtest_results"

Write-Host "=== COMPLETE 1-MINUTE DATA OPTIMIZATION PIPELINE ===" -ForegroundColor Cyan
Write-Host "WARNING: This will re-run ALL phases with 1-minute data" -ForegroundColor Red
Write-Host "Expected total runtime: 12-16 hours" -ForegroundColor Yellow
Write-Host ""

# Phase 1: MA Period Optimization (1-minute data)
Write-Host "=== PHASE 1: MA Period Optimization (1-Minute) ===" -ForegroundColor Green
Write-Host "Expected runtime: 2-3 hours"
Write-Host "Command: python optimization/grid_search.py --config optimization/configs/phase1_ma_periods_1minute.yaml --objective sharpe_ratio --workers 8 --output optimization/results/phase1_1minute_results.csv --no-resume --verbose"
Write-Host ""

# Phase 2: Coarse Grid Optimization (1-minute data)
Write-Host "=== PHASE 2: Coarse Grid Optimization (1-Minute) ===" -ForegroundColor Green
Write-Host "Expected runtime: 3-4 hours"
Write-Host "Command: python optimization/grid_search.py --config optimization/configs/phase2_coarse_grid_1minute.yaml --objective sharpe_ratio --workers 8 --output optimization/results/phase2_1minute_results.csv --no-resume --verbose"
Write-Host ""

# Phase 3: Fine Grid Optimization (1-minute data)
Write-Host "=== PHASE 3: Fine Grid Optimization (1-Minute) ===" -ForegroundColor Green
Write-Host "Expected runtime: 4-5 hours"
Write-Host "Command: python optimization/grid_search.py --config optimization/configs/phase3_fine_grid_1minute.yaml --objective sharpe_ratio --workers 8 --output optimization/results/phase3_1minute_results.csv --no-resume --verbose"
Write-Host ""

# Phase 4: Risk Management Optimization (1-minute data)
Write-Host "=== PHASE 4: Risk Management Optimization (1-Minute) ===" -ForegroundColor Green
Write-Host "Expected runtime: 3-4 hours"
Write-Host "Command: python optimization/grid_search.py --config optimization/configs/phase4_risk_management_1minute.yaml --objective sharpe_ratio --workers 8 --output optimization/results/phase4_1minute_results.csv --no-resume --verbose"
Write-Host ""

Write-Host "=== EXECUTION INSTRUCTIONS ===" -ForegroundColor Cyan
Write-Host "1. Create 1-minute configurations for Phases 1-3 first"
Write-Host "2. Run each phase in sequence"
Write-Host "3. Update Phase 4 config with Phase 3 results"
Write-Host "4. Run Phase 4 with updated parameters"
Write-Host ""
Write-Host "Total expected runtime: 12-16 hours"
Write-Host "Total combinations across all phases: ~10,000+"
