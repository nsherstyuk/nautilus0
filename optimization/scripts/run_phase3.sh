#!/bin/bash

# Phase 3 Fine Grid Optimization Execution Script
# Purpose: Execute Phase 3 optimization with proper environment setup and validation
# Date: $(date)
# Usage: bash optimization/scripts/run_phase3.sh

set -e  # Exit on any error

echo "=== Phase 3 Fine Grid Optimization Execution ==="
echo "Date: $(date)"
echo "Working Directory: $(pwd)"
echo

# Environment Variable Setup
echo "Setting up environment variables..."
export BACKTEST_SYMBOL="EUR/USD"
export BACKTEST_VENUE="IDEALPRO"
export BACKTEST_START_DATE="2025-01-01"
export BACKTEST_END_DATE="2025-07-31"
export BACKTEST_BAR_SPEC="15-MINUTE-MID-EXTERNAL"
export CATALOG_PATH="data/historical"
export OUTPUT_DIR="logs/backtest_results"

echo "Environment variables configured:"
echo "  BACKTEST_SYMBOL: $BACKTEST_SYMBOL"
echo "  BACKTEST_VENUE: $BACKTEST_VENUE"
echo "  BACKTEST_START_DATE: $BACKTEST_START_DATE"
echo "  BACKTEST_END_DATE: $BACKTEST_END_DATE"
echo "  BACKTEST_BAR_SPEC: $BACKTEST_BAR_SPEC"
echo "  CATALOG_PATH: $CATALOG_PATH"
echo "  OUTPUT_DIR: $OUTPUT_DIR"
echo

# Pre-flight Validation
echo "Performing pre-flight validation..."

# Check if Python is available
if ! command -v python &> /dev/null; then
    echo "ERROR: Python is not available. Please install Python and try again."
    exit 1
fi
echo "✓ Python is available"

# Verify config file exists
if [ ! -f "optimization/configs/phase3_fine_grid.yaml" ]; then
    echo "ERROR: Config file not found: optimization/configs/phase3_fine_grid.yaml"
    exit 1
fi
echo "✓ Config file exists"

# Verify catalog path exists
if [ ! -d "$CATALOG_PATH" ]; then
    echo "ERROR: Catalog path not found: $CATALOG_PATH"
    exit 1
fi
echo "✓ Catalog path exists"

# Validate date range using Python for portability
START_DATE_EPOCH=$(python -c "from datetime import datetime; print(int(datetime.strptime('$BACKTEST_START_DATE', '%Y-%m-%d').timestamp()))" 2>/dev/null || echo "0")
END_DATE_EPOCH=$(python -c "from datetime import datetime; print(int(datetime.strptime('$BACKTEST_END_DATE', '%Y-%m-%d').timestamp()))" 2>/dev/null || echo "0")
if [ "$START_DATE_EPOCH" -eq 0 ] || [ "$END_DATE_EPOCH" -eq 0 ]; then
    echo "ERROR: Invalid date format. Use YYYY-MM-DD format."
    exit 1
fi
if [ "$START_DATE_EPOCH" -ge "$END_DATE_EPOCH" ]; then
    echo "ERROR: Start date must be before end date"
    exit 1
fi
echo "✓ Date range is valid"

echo "All pre-flight checks passed!"
echo

# Archive Old Results
echo "Checking for existing Phase 3 results..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if [ -f "optimization/results/phase3_fine_grid_results.csv" ]; then
    echo "Archiving existing CSV results..."
    mv "optimization/results/phase3_fine_grid_results.csv" "optimization/results/phase3_fine_grid_results.csv.old.$TIMESTAMP"
    echo "✓ Archived: phase3_fine_grid_results.csv.old.$TIMESTAMP"
fi

if [ -f "optimization/results/phase3_fine_grid_results_top_10.json" ]; then
    echo "Archiving existing top 10 JSON results..."
    mv "optimization/results/phase3_fine_grid_results_top_10.json" "optimization/results/phase3_fine_grid_results_top_10.json.old.$TIMESTAMP"
    echo "✓ Archived: phase3_fine_grid_results_top_10.json.old.$TIMESTAMP"
fi

if [ -f "optimization/results/phase3_fine_grid_results_summary.json" ]; then
    echo "Archiving existing summary JSON results..."
    mv "optimization/results/phase3_fine_grid_results_summary.json" "optimization/results/phase3_fine_grid_results_summary.json.old.$TIMESTAMP"
    echo "✓ Archived: phase3_fine_grid_results_summary.json.old.$TIMESTAMP"
fi

echo

# Execute Grid Search
echo "Starting Phase 3 optimization..."
echo "Start time: $(date)"
echo "Configuration: 125 combinations (5×5×5)"
echo "Workers: 8"
echo "Expected runtime: 2-3 hours"
echo

python optimization/grid_search.py \
  --config optimization/configs/phase3_fine_grid.yaml \
  --objective sharpe_ratio \
  --workers 8 \
  --no-resume \
  --verbose

EXIT_CODE=$?

echo
echo "Optimization completed at: $(date)"
echo "Exit code: $EXIT_CODE"

# Post-execution Validation
if [ $EXIT_CODE -ne 0 ]; then
    echo "ERROR: Grid search failed with exit code $EXIT_CODE"
    echo "Check the logs for details."
    exit $EXIT_CODE
fi

echo "Performing post-execution validation..."

# Verify output files were created
if [ ! -f "optimization/results/phase3_fine_grid_results.csv" ]; then
    echo "WARNING: Results CSV file not found"
else
    ROW_COUNT=$(wc -l < "optimization/results/phase3_fine_grid_results.csv")
    echo "✓ Results CSV created with $ROW_COUNT rows (expected: ~125)"
fi

if [ ! -f "optimization/results/phase3_fine_grid_results_top_10.json" ]; then
    echo "WARNING: Top 10 JSON file not found"
else
    echo "✓ Top 10 JSON file created"
fi

if [ ! -f "optimization/results/phase3_fine_grid_results_summary.json" ]; then
    echo "WARNING: Summary JSON file not found"
else
    echo "✓ Summary JSON file created"
fi

# Display top 3 results if available
if [ -f "optimization/results/phase3_fine_grid_results_top_10.json" ]; then
    echo
    echo "Top 3 results:"
    python -c "
import json
try:
    with open('optimization/results/phase3_fine_grid_results_top_10.json', 'r') as f:
        data = json.load(f)
    for i, result in enumerate(data[:3], 1):
        print(f'  {i}. Sharpe: {result.get(\"objective_value\", \"N/A\"):.4f}, Fast: {result.get(\"parameters\", {}).get(\"fast_period\", \"N/A\")}, Slow: {result.get(\"parameters\", {}).get(\"slow_period\", \"N/A\")}, Threshold: {result.get(\"parameters\", {}).get(\"crossover_threshold_pips\", \"N/A\")}')
except Exception as e:
    print(f'  Error reading results: {e}')
"
fi

echo
echo "=== Phase 3 Execution Complete ==="
echo "Results available in:"
echo "  - optimization/results/phase3_fine_grid_results.csv"
echo "  - optimization/results/phase3_fine_grid_results_top_10.json"
echo "  - optimization/results/phase3_fine_grid_results_summary.json"
echo
echo "Next steps:"
echo "1. Review results: optimization/results/phase3_fine_grid_results_top_10.json"
echo "2. Update PHASE3_EXECUTION_LOG.md with execution details"
echo "3. Prepare Phase 4 configuration with best MA parameters"
echo
echo "✅ Phase 3 optimization completed successfully!"
