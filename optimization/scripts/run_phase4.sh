#!/bin/bash
# Phase 4: Risk Management Parameter Optimization - Bash Execution Script
# ======================================================================
#
# This script automates Phase 4 risk management optimization execution with
# environment setup, validation, and error handling for Linux/Mac/WSL.
#
# Purpose: Optimize risk management parameters (stop loss, take profit, trailing stops)
#          using Phase 3 best MA parameters (fast=42, slow=270, threshold=0.35)
#
# Prerequisites: bash, Python 3.8+, Phase 3 results available
# Expected runtime: 8-10 hours with 8 workers (500 combinations)
#
# Usage:
#   bash optimization/scripts/run_phase4.sh
#   ./optimization/scripts/run_phase4.sh
#   bash optimization/scripts/run_phase4.sh -w 12
#   bash optimization/scripts/run_phase4.sh --workers 16
#   WORKERS=16 bash optimization/scripts/run_phase4.sh
#   chmod +x optimization/scripts/run_phase4.sh && ./optimization/scripts/run_phase4.sh
#
# Exit codes:
#   0: Success
#   1: Configuration error
#   2: Validation error  
#   3: Execution error
#   4: Post-validation error

set -e  # Exit on any error

# Parse command line arguments
WORKERS=${WORKERS:-8}  # Default to 8 workers, can be overridden by env var

while [[ $# -gt 0 ]]; do
    case $1 in
        -w|--workers)
            WORKERS="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [-w|--workers NUM]"
            echo "  -w, --workers NUM  Number of parallel workers (default: 8)"
            echo "  -h, --help         Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  WORKERS            Number of parallel workers (overrides -w/--workers)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Script header
echo "Phase 4: Risk Management Parameter Optimization"
echo "==============================================="
echo "Date: $(date)"
echo "User: $(whoami)"
echo "Working directory: $(pwd)"
echo "Workers: $WORKERS"
echo ""

# Environment Variable Setup
# ==========================
echo "Setting up environment variables..."

# Backtest configuration
export BACKTEST_SYMBOL="EUR/USD"
export BACKTEST_VENUE="IDEALPRO"
export BACKTEST_START_DATE="2025-01-01"
export BACKTEST_END_DATE="2025-07-31"
export BACKTEST_BAR_SPEC="15-MINUTE-MID-EXTERNAL"

# Data and output configuration
export CATALOG_PATH="data/historical"
export OUTPUT_DIR="logs/backtest_results"

# Display environment configuration
echo "Environment Configuration:"
echo "  Symbol: $BACKTEST_SYMBOL"
echo "  Venue: $BACKTEST_VENUE"
echo "  Date Range: $BACKTEST_START_DATE to $BACKTEST_END_DATE"
echo "  Bar Spec: $BACKTEST_BAR_SPEC"
echo "  Catalog: $CATALOG_PATH"
echo "  Output: $OUTPUT_DIR"
echo ""

# Pre-flight Validation
# ====================
echo "Performing pre-flight validation..."

# Check Python availability
if ! command -v python >/dev/null 2>&1; then
    echo "✗ Python not found. Please install Python 3.8+ and ensure it's in PATH."
    exit 2
fi
echo "✓ Python found: $(which python)"

# Verify Phase 4 config file exists
if [ ! -f "optimization/configs/phase4_risk_management.yaml" ]; then
    echo "✗ Phase 4 config file not found: optimization/configs/phase4_risk_management.yaml"
    exit 2
fi
echo "✓ Phase 4 config file found"

# Verify Phase 3 results exist
if [ ! -f "optimization/results/phase3_fine_grid_results_top_10.json" ]; then
    echo "✗ Phase 3 results not found. Please complete Phase 3 first."
    echo "  Expected: optimization/results/phase3_fine_grid_results_top_10.json"
    exit 2
fi
echo "✓ Phase 3 results found"

# Verify catalog path exists
if [ ! -d "$CATALOG_PATH" ]; then
    echo "✗ Catalog path not found: $CATALOG_PATH"
    exit 2
fi
echo "✓ Catalog path found"

# Validate date range
if ! python -c "
import datetime
start = datetime.datetime.strptime('$BACKTEST_START_DATE', '%Y-%m-%d')
end = datetime.datetime.strptime('$BACKTEST_END_DATE', '%Y-%m-%d')
if start >= end:
    print('✗ Invalid date range: START_DATE must be before END_DATE')
    exit(1)
print('✓ Date range valid: $BACKTEST_START_DATE to $BACKTEST_END_DATE')
" 2>/dev/null; then
    echo "✗ Invalid date format. Use YYYY-MM-DD format."
    exit 2
fi

# Check required Python packages
echo "Checking Python packages..."
if ! python -c "import pandas, yaml" 2>/dev/null; then
    echo "✗ Required Python packages not found (pandas, pyyaml)"
    echo "  Install with: pip install pandas pyyaml"
    exit 2
fi
echo "✓ Required Python packages found"

echo "✓ All pre-flight checks passed"
echo ""

# Archive Old Results
# ===================
echo "Checking for existing Phase 4 results..."

result_files=(
    "optimization/results/phase4_risk_management_results.csv"
    "optimization/results/phase4_risk_management_results_top_10.json"
    "optimization/results/phase4_risk_management_results_summary.json"
)

files_exist=false
for file in "${result_files[@]}"; do
    if [ -f "$file" ]; then
        files_exist=true
        break
    fi
done

if [ "$files_exist" = true ]; then
    timestamp=$(date +%Y%m%d_%H%M%S)
    archive_dir="optimization/results/archive/phase4"
    
    # Create archive directory if it doesn't exist
    mkdir -p "$archive_dir"
    
    echo "Archiving old Phase 4 results..."
    for file in "${result_files[@]}"; do
        if [ -f "$file" ]; then
            filename=$(basename "$file")
            new_name="${filename}.old.${timestamp}"
            destination_path="${archive_dir}/${new_name}"
            mv "$file" "$destination_path"
            echo "  Archived: $file -> $destination_path"
        fi
    done
    echo "✓ Old results archived"
else
    echo "✓ No existing Phase 4 results to archive"
fi
echo ""

# Display Execution Summary
# =========================
echo "Phase 4 Configuration Summary:"
echo "============================="
echo "Total combinations: 500 (5×5×4×5)"
echo "Parameters being optimized:"
echo "  - stop_loss_pips: [15, 20, 25, 30, 35]"
echo "  - take_profit_pips: [30, 40, 50, 60, 75]"
echo "  - trailing_stop_activation_pips: [22, 25, 28, 32]"
echo "  - trailing_stop_distance_pips: [10, 12, 14, 16, 18]"
echo ""
echo "Fixed MA parameters (from Phase 3 best):"
echo "  - fast_period: 42"
echo "  - slow_period: 270"
echo "  - crossover_threshold_pips: 0.35"
echo ""
echo "Expected runtime: 8-10 hours with $WORKERS workers"
echo ""

# Display Phase 3 baseline for comparison
echo "Loading Phase 3 baseline..."
if command -v jq >/dev/null 2>&1; then
    echo "Phase 3 Baseline (for comparison):"
    echo "  Best Sharpe: $(jq -r '.[0].objective_value' optimization/results/phase3_fine_grid_results_top_10.json)"
    echo "  Best PnL: \$$(jq -r '.[0].parameters.total_pnl' optimization/results/phase3_fine_grid_results_top_10.json)"
    echo "  Win Rate: $(jq -r '.[0].parameters.win_rate' optimization/results/phase3_fine_grid_results_top_10.json)%"
    echo "  Trade Count: $(jq -r '.[0].parameters.trade_count' optimization/results/phase3_fine_grid_results_top_10.json)"
else
    echo "Phase 3 Baseline (jq not available, using Python):"
    python -c "
import json
with open('optimization/results/phase3_fine_grid_results_top_10.json') as f:
    data = json.load(f)
best = data[0]
print(f'  Best Sharpe: {best[\"objective_value\"]}')
print(f'  Best PnL: \${best[\"parameters\"][\"total_pnl\"]}')
print(f'  Win Rate: {best[\"parameters\"][\"win_rate\"]}%')
print(f'  Trade Count: {best[\"parameters\"][\"trade_count\"]}')
"
fi
echo "  Target: Improve Sharpe ratio to 0.28-0.35 range"
echo ""

# Prompt for confirmation
read -p "Continue with Phase 4 execution? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Phase 4 execution cancelled by user."
    exit 0
fi

# Execute Grid Search
# ===================
echo "Starting Phase 4 optimization..."
START_TIME=$(date +%s)
echo "Start time: $(date)"

# Set up interrupt trap
trap 'echo ""; echo "Interrupted. Checkpoint saved at optimization/checkpoints/phase4_risk_management_checkpoint.csv"; exit 130' INT

echo "Executing command:"
echo "python optimization/grid_search.py \\"
echo "  --config optimization/configs/phase4_risk_management.yaml \\"
echo "  --objective sharpe_ratio \\"
echo "  --workers $WORKERS \\"
echo "  --output optimization/results/phase4_risk_management_results.csv \\"
echo "  --no-resume \\"
echo "  --verbose"
echo ""

# Execute the command
python optimization/grid_search.py \
    --config optimization/configs/phase4_risk_management.yaml \
    --objective sharpe_ratio \
    --workers $WORKERS \
    --output optimization/results/phase4_risk_management_results.csv \
    --no-resume \
    --verbose

EXIT_CODE=$?
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "Execution completed at: $(date)"
echo "Total duration: $((DURATION / 3600))h $(((DURATION % 3600) / 60))m $((DURATION % 60))s"
echo ""

# Post-execution Validation
# ========================
if [ $EXIT_CODE -eq 0 ]; then
    echo "Validating Phase 4 results..."
    
    # Check if output files exist
    output_files=(
        "optimization/results/phase4_risk_management_results.csv"
        "optimization/results/phase4_risk_management_results_top_10.json"
        "optimization/results/phase4_risk_management_results_summary.json"
    )
    
    all_files_exist=true
    for file in "${output_files[@]}"; do
        if [ -f "$file" ]; then
            echo "✓ $file exists"
        else
            echo "✗ $file missing"
            all_files_exist=false
        fi
    done
    
    if [ "$all_files_exist" = true ]; then
        # Count CSV rows (should be ~500)
        if command -v wc >/dev/null 2>&1; then
            row_count=$(wc -l < optimization/results/phase4_risk_management_results.csv)
            # Subtract 1 for header row
            row_count=$((row_count - 1))
            echo "✓ CSV contains $row_count results (expected: ~500)"
        else
            echo "✓ CSV file exists (wc not available for row count)"
        fi
        
        # Load and display top 3 results
        echo ""
        echo "Top 3 Phase 4 Results:"
        if command -v jq >/dev/null 2>&1; then
            for i in {0..2}; do
                result=$(jq -r ".[$i]" optimization/results/phase4_risk_management_results_top_10.json 2>/dev/null)
                if [ "$result" != "null" ] && [ "$result" != "" ]; then
                    sharpe=$(echo "$result" | jq -r '.objective_value')
                    sl=$(echo "$result" | jq -r '.parameters.stop_loss_pips')
                    tp=$(echo "$result" | jq -r '.parameters.take_profit_pips')
                    ta=$(echo "$result" | jq -r '.parameters.trailing_stop_activation_pips')
                    td=$(echo "$result" | jq -r '.parameters.trailing_stop_distance_pips')
                    echo "  Rank $((i + 1)): Sharpe=$sharpe, SL=$sl, TP=$tp, TA=$ta, TD=$td"
                fi
            done
        else
            echo "  (jq not available, using Python to display results)"
            python -c "
import json
with open('optimization/results/phase4_risk_management_results_top_10.json') as f:
    data = json.load(f)
for i in range(min(3, len(data))):
    result = data[i]
    print(f'  Rank {i+1}: Sharpe={result[\"objective_value\"]}, SL={result[\"parameters\"][\"stop_loss_pips\"]}, TP={result[\"parameters\"][\"take_profit_pips\"]}, TA={result[\"parameters\"][\"trailing_stop_activation_pips\"]}, TD={result[\"parameters\"][\"trailing_stop_distance_pips\"]}')
"
        fi
        
        # Compare with Phase 3 baseline
        echo ""
        echo "Improvement over Phase 3:"
        if command -v jq >/dev/null 2>&1; then
            phase4_sharpe=$(jq -r '.[0].objective_value' optimization/results/phase4_risk_management_results_top_10.json)
            phase3_sharpe=$(jq -r '.[0].objective_value' optimization/results/phase3_fine_grid_results_top_10.json)
            improvement=$(python -c "print(f'{($phase4_sharpe - $phase3_sharpe) / $phase3_sharpe * 100:.2f}%')")
            echo "  Sharpe ratio: $phase3_sharpe -> $phase4_sharpe ($improvement)"
        else
            python -c "
import json
with open('optimization/results/phase4_risk_management_results_top_10.json') as f:
    phase4_data = json.load(f)
with open('optimization/results/phase3_fine_grid_results_top_10.json') as f:
    phase3_data = json.load(f)
phase4_sharpe = phase4_data[0]['objective_value']
phase3_sharpe = phase3_data[0]['objective_value']
improvement = (phase4_sharpe - phase3_sharpe) / phase3_sharpe * 100
print(f'  Sharpe ratio: {phase3_sharpe} -> {phase4_sharpe} ({improvement:.2f}%)')
"
        fi
        
        # Display execution statistics
        echo ""
        echo "Execution Statistics:"
        echo "  Total duration: $((DURATION / 3600))h $(((DURATION % 3600) / 60))m $((DURATION % 60))s"
        echo "  Average time per backtest: $((DURATION / 500)) seconds"
        if [ -n "$row_count" ]; then
            success_rate=$(python -c "print(f'{($row_count / 500 * 100):.1f}%')")
            echo "  Success rate: $row_count/500 ($success_rate)"
        fi
    fi
    
    echo ""
    echo "✅ Phase 4 Complete!"
    if command -v jq >/dev/null 2>&1; then
        best_sharpe=$(jq -r '.[0].objective_value' optimization/results/phase4_risk_management_results_top_10.json)
        best_sl=$(jq -r '.[0].parameters.stop_loss_pips' optimization/results/phase4_risk_management_results_top_10.json)
        best_tp=$(jq -r '.[0].parameters.take_profit_pips' optimization/results/phase4_risk_management_results_top_10.json)
        best_ta=$(jq -r '.[0].parameters.trailing_stop_activation_pips' optimization/results/phase4_risk_management_results_top_10.json)
        best_td=$(jq -r '.[0].parameters.trailing_stop_distance_pips' optimization/results/phase4_risk_management_results_top_10.json)
        echo "Best Sharpe: $best_sharpe"
        echo "Best params: SL=$best_sl, TP=$best_tp, TA=$best_ta, TD=$best_td"
    fi
    
else
    echo "❌ Phase 4 execution failed with exit code: $EXIT_CODE"
    echo "Check the logs above for error details."
    echo "Checkpoint file may contain partial results: optimization/checkpoints/phase4_risk_management_checkpoint.csv"
    exit 3
fi

# Success Message and Next Steps
# ==============================
echo ""
echo "Next Steps:"
echo "1. Review results: cat optimization/results/phase4_risk_management_results_top_10.json | jq"
echo "2. Run validation: python optimization/scripts/validate_phase4_results.py"
echo "3. Update Phase 5 config with Phase 4 best parameters"
echo "4. Document findings in PHASE4_EXECUTION_LOG.md"
echo ""
echo "Output files:"
echo "  - optimization/results/phase4_risk_management_results.csv"
echo "  - optimization/results/phase4_risk_management_results_top_10.json"
echo "  - optimization/results/phase4_risk_management_results_summary.json"

exit 0
