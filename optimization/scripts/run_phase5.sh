#!/bin/bash
# Phase 5: Filter Parameter Optimization (DMI and Stochastic) - Bash Execution Script
# ===================================================================================
#
# This script automates Phase 5 filter optimization execution with
# environment setup, validation, and error handling for Linux/Mac/WSL.
#
# Purpose: Optimize DMI and Stochastic filter parameters using Phase 3 best MA 
#          and Phase 4 best risk management parameters
#
# Prerequisites: bash, Python 3.8+, Phase 3 and Phase 4 results available
# Expected runtime: ~40 hours with 8 workers (2,400 combinations) or ~2 hours (108 combinations)
#
# Usage:
#   bash optimization/scripts/run_phase5.sh
#   ./optimization/scripts/run_phase5.sh
#   bash optimization/scripts/run_phase5.sh --workers 12
#   bash optimization/scripts/run_phase5.sh --use-reduced
#   bash optimization/scripts/run_phase5.sh --workers 16 --use-reduced
#   chmod +x optimization/scripts/run_phase5.sh && ./optimization/scripts/run_phase5.sh
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
USE_REDUCED=false
USE_MEDIUM=false
DRY_RUN=false
NO_ARCHIVE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -w|--workers)
            WORKERS="$2"
            shift 2
            ;;
        --use-reduced)
            USE_REDUCED=true
            shift
            ;;
        --use-medium)
            USE_MEDIUM=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-archive)
            NO_ARCHIVE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [-w|--workers NUM] [--use-reduced] [--use-medium] [--dry-run] [--no-archive]"
            echo "  -w, --workers NUM  Number of parallel workers (default: 8)"
            echo "  --use-reduced      Use reduced configuration (108 combinations, ~2 hours)"
            echo "  --use-medium       Use medium configuration (324 combinations, ~6 hours)"
            echo "  --dry-run          Validate only, don't execute"
            echo "  --no-archive       Skip archiving old results"
            echo "  -h, --help         Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  WORKERS            Number of parallel workers (overrides -w/--workers)"
            echo ""
            echo "Examples:"
            echo "  $0 --use-reduced                    # Run reduced version (2 hours)"
            echo "  $0 --use-medium                     # Run medium version (6 hours)"
            echo "  $0 --workers 12                     # Run full version with 12 workers"
            echo "  $0 --use-reduced --workers 16        # Run reduced version with 16 workers"
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
echo "Phase 5: Filter Parameter Optimization (DMI and Stochastic)"
echo "========================================================="
echo "Date: $(date)"
echo "User: $(whoami)"
echo "Working directory: $(pwd)"
echo "Workers: $WORKERS"
echo "Use Reduced: $USE_REDUCED"
echo "Use Medium: $USE_MEDIUM"
echo "Dry Run: $DRY_RUN"
echo "No Archive: $NO_ARCHIVE"
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

# Verify Phase 5 config file exists (check all versions)
if [ "$USE_REDUCED" = true ]; then
    CONFIG_FILE="optimization/configs/phase5_filters_reduced.yaml"
    OUTPUT_FILE="optimization/results/phase5_filters_reduced_results.csv"
    CHECKPOINT_FILE="optimization/checkpoints/phase5_filters_reduced_checkpoint.csv"
    EXPECTED_COMBINATIONS=108
    EXPECTED_RUNTIME="~2 hours"
elif [ "$USE_MEDIUM" = true ]; then
    CONFIG_FILE="optimization/configs/phase5_filters_medium.yaml"
    OUTPUT_FILE="optimization/results/phase5_filters_medium_results.csv"
    CHECKPOINT_FILE="optimization/checkpoints/phase5_filters_medium_checkpoint.csv"
    EXPECTED_COMBINATIONS=324
    EXPECTED_RUNTIME="~6 hours"
else
    CONFIG_FILE="optimization/configs/phase5_filters.yaml"
    OUTPUT_FILE="optimization/results/phase5_filters_results.csv"
    CHECKPOINT_FILE="optimization/checkpoints/phase5_filters_checkpoint.csv"
    EXPECTED_COMBINATIONS=2400
    EXPECTED_RUNTIME="~40 hours"
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "✗ Phase 5 config file not found: $CONFIG_FILE"
    exit 2
fi
echo "✓ Phase 5 config file found: $CONFIG_FILE"

# Verify Phase 3 results exist
if [ ! -f "optimization/results/phase3_fine_grid_results_top_10.json" ]; then
    echo "✗ Phase 3 results not found. Please complete Phase 3 first."
    echo "  Expected: optimization/results/phase3_fine_grid_results_top_10.json"
    exit 2
fi
echo "✓ Phase 3 results found"

# Verify Phase 4 results exist
if [ ! -f "optimization/results/phase4_risk_management_results_top_10.json" ]; then
    echo "✗ Phase 4 results not found. Please complete Phase 4 first."
    echo "  Expected: optimization/results/phase4_risk_management_results_top_10.json"
    exit 2
fi
echo "✓ Phase 4 results found"

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

# Archive Old Results (unless --no-archive flag set)
# =================================================
if [ "$NO_ARCHIVE" = false ]; then
    echo "Checking for existing Phase 5 results..."
    
    if [ "$USE_REDUCED" = true ]; then
        result_files=(
            "optimization/results/phase5_filters_reduced_results.csv"
            "optimization/results/phase5_filters_reduced_results_top_10.json"
            "optimization/results/phase5_filters_reduced_results_summary.json"
        )
    elif [ "$USE_MEDIUM" = true ]; then
        result_files=(
            "optimization/results/phase5_filters_medium_results.csv"
            "optimization/results/phase5_filters_medium_results_top_10.json"
            "optimization/results/phase5_filters_medium_results_summary.json"
        )
    else
        result_files=(
            "optimization/results/phase5_filters_results.csv"
            "optimization/results/phase5_filters_results_top_10.json"
            "optimization/results/phase5_filters_results_summary.json"
        )
    fi
    
    files_exist=false
    for file in "${result_files[@]}"; do
        if [ -f "$file" ]; then
            files_exist=true
            break
        fi
    done
    
    if [ "$files_exist" = true ]; then
        timestamp=$(date +%Y%m%d_%H%M%S)
        archive_dir="optimization/results/archive/phase5"
        
        # Create archive directory if it doesn't exist
        mkdir -p "$archive_dir"
        
        echo "Archiving old Phase 5 results..."
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
        echo "✓ No existing Phase 5 results to archive"
    fi
    echo ""
fi

# Display Execution Summary
# =========================
echo "Phase 5 Configuration Summary:"
echo "============================="

if [ "$USE_REDUCED" = true ]; then
    echo "Configuration: REDUCED VERSION"
    echo "Total combinations: 108 (1×3×3×3×2×2)"
    echo "Expected runtime: $EXPECTED_RUNTIME with $WORKERS workers"
    echo ""
    echo "Parameters being optimized:"
    echo "  - dmi_enabled: [true] (1 value - keep enabled)"
    echo "  - dmi_period: [10, 14, 18] (3 values - fast, baseline, slow)"
    echo "  - stoch_period_k: [10, 14, 18] (3 values - fast, baseline, slow)"
    echo "  - stoch_period_d: [3, 5, 7] (3 values - keep all)"
    echo "  - stoch_bullish_threshold: [20, 30] (2 values - aggressive vs baseline)"
    echo "  - stoch_bearish_threshold: [70, 80] (2 values - baseline vs aggressive)"
elif [ "$USE_MEDIUM" = true ]; then
    echo "Configuration: MEDIUM VERSION"
    echo "Total combinations: 324 (2×3×3×2×3×3)"
    echo "Expected runtime: $EXPECTED_RUNTIME with $WORKERS workers"
    echo ""
    echo "Parameters being optimized:"
    echo "  - dmi_enabled: [true, false] (2 values - test DMI filter value)"
    echo "  - dmi_period: [10, 14, 18] (3 values - fast, baseline, slow)"
    echo "  - stoch_period_k: [10, 14, 18] (3 values - fast, baseline, slow)"
    echo "  - stoch_period_d: [3, 5] (2 values - minimal vs moderate smoothing)"
    echo "  - stoch_bullish_threshold: [20, 30, 35] (3 values - aggressive to conservative)"
    echo "  - stoch_bearish_threshold: [70, 75, 80] (3 values - baseline to aggressive)"
else
    echo "Configuration: FULL VERSION"
    echo "Total combinations: 2,400 (2×5×5×3×4×4)"
    echo "Expected runtime: $EXPECTED_RUNTIME with $WORKERS workers"
    echo ""
    echo "Parameters being optimized:"
    echo "  - dmi_enabled: [true, false] (2 values - test DMI filter value)"
    echo "  - dmi_period: [10, 12, 14, 16, 18] (5 values - fast to slow)"
    echo "  - stoch_period_k: [10, 12, 14, 16, 18] (5 values - fast to slow)"
    echo "  - stoch_period_d: [3, 5, 7] (3 values - minimal to high smoothing)"
    echo "  - stoch_bullish_threshold: [20, 25, 30, 35] (4 values - aggressive to conservative)"
    echo "  - stoch_bearish_threshold: [65, 70, 75, 80] (4 values - conservative to aggressive)"
fi

echo ""
echo "Fixed MA parameters (from Phase 3 best):"
echo "  - fast_period: 42"
echo "  - slow_period: 270"
echo "  - crossover_threshold_pips: 0.35"
echo ""
echo "Fixed risk parameters (from Phase 4 best):"
echo "  - stop_loss_pips: 35"
echo "  - take_profit_pips: 50"
echo "  - trailing_stop_activation_pips: 22"
echo "  - trailing_stop_distance_pips: 12"
echo ""

# Display Phase 3 and Phase 4 baselines for comparison
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

echo ""
echo "Loading Phase 4 baseline..."
if command -v jq >/dev/null 2>&1; then
    echo "Phase 4 Baseline (for comparison):"
    echo "  Best Sharpe: $(jq -r '.[0].objective_value' optimization/results/phase4_risk_management_results_top_10.json)"
    echo "  Best PnL: \$$(jq -r '.[0].parameters.total_pnl' optimization/results/phase4_risk_management_results_top_10.json)"
    echo "  Win Rate: $(jq -r '.[0].parameters.win_rate' optimization/results/phase4_risk_management_results_top_10.json)%"
    echo "  Trade Count: $(jq -r '.[0].parameters.trade_count' optimization/results/phase4_risk_management_results_top_10.json)"
    echo "  Target: Maintain or improve Phase 4 Sharpe ratio of $(jq -r '.[0].objective_value' optimization/results/phase4_risk_management_results_top_10.json)"
else
    echo "Phase 4 Baseline (jq not available, using Python):"
    python -c "
import json
with open('optimization/results/phase4_risk_management_results_top_10.json') as f:
    data = json.load(f)
best = data[0]
print(f'  Best Sharpe: {best[\"objective_value\"]}')
print(f'  Best PnL: \${best[\"parameters\"][\"total_pnl\"]}')
print(f'  Win Rate: {best[\"parameters\"][\"win_rate\"]}%')
print(f'  Trade Count: {best[\"parameters\"][\"trade_count\"]}')
print(f'  Target: Maintain or improve Phase 4 Sharpe ratio of {best[\"objective_value\"]}')
"
fi
echo ""

# Important warning for full version
if [ "$USE_REDUCED" = false ]; then
    echo "⚠️  WARNING: Full version will take ~40 hours!"
    echo "Consider using --use-reduced flag for faster iteration (~2 hours)"
    echo ""
fi

# Dry run check
if [ "$DRY_RUN" = true ]; then
    echo "Dry run completed. Configuration validated successfully."
    echo "Remove --dry-run flag to execute Phase 5 optimization."
    exit 0
fi

# Prompt for confirmation
read -p "Continue with Phase 5 execution? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Phase 5 execution cancelled by user."
    exit 0
fi

# Execute Grid Search
# ===================
echo "Starting Phase 5 optimization..."
START_TIME=$(date +%s)
echo "Start time: $(date)"

# Set up interrupt trap
trap 'echo ""; echo "Interrupted. Checkpoint saved at $CHECKPOINT_FILE"; exit 130' INT

echo "Executing command:"
echo "python optimization/grid_search.py \\"
echo "  --config $CONFIG_FILE \\"
echo "  --objective sharpe_ratio \\"
echo "  --workers $WORKERS \\"
echo "  --output $OUTPUT_FILE \\"
echo "  --no-resume \\"
echo "  --verbose"
echo ""

# Execute the command
python optimization/grid_search.py \
    --config "$CONFIG_FILE" \
    --objective sharpe_ratio \
    --workers $WORKERS \
    --output "$OUTPUT_FILE" \
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
    echo "Validating Phase 5 results..."
    
    # Check if output files exist
    if [ "$USE_REDUCED" = true ]; then
        output_files=(
            "optimization/results/phase5_filters_reduced_results.csv"
            "optimization/results/phase5_filters_reduced_results_top_10.json"
            "optimization/results/phase5_filters_reduced_results_summary.json"
        )
    elif [ "$USE_MEDIUM" = true ]; then
        output_files=(
            "optimization/results/phase5_filters_medium_results.csv"
            "optimization/results/phase5_filters_medium_results_top_10.json"
            "optimization/results/phase5_filters_medium_results_summary.json"
        )
    else
        output_files=(
            "optimization/results/phase5_filters_results.csv"
            "optimization/results/phase5_filters_results_top_10.json"
            "optimization/results/phase5_filters_results_summary.json"
        )
    fi
    
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
        # Count CSV rows
        if command -v wc >/dev/null 2>&1; then
            row_count=$(wc -l < "$OUTPUT_FILE")
            # Subtract 1 for header row
            row_count=$((row_count - 1))
            echo "✓ CSV contains $row_count results (expected: ~$EXPECTED_COMBINATIONS)"
        else
            echo "✓ CSV file exists (wc not available for row count)"
        fi
        
        # Load and display top 3 results
        echo ""
        echo "Top 3 Phase 5 Results:"
        if command -v jq >/dev/null 2>&1; then
            for i in {0..2}; do
                result=$(jq -r ".[$i]" "${output_files[1]}" 2>/dev/null)
                if [ "$result" != "null" ] && [ "$result" != "" ]; then
                    sharpe=$(echo "$result" | jq -r '.objective_value')
                    dmi_enabled=$(echo "$result" | jq -r '.parameters.dmi_enabled')
                    dmi_period=$(echo "$result" | jq -r '.parameters.dmi_period')
                    stoch_k=$(echo "$result" | jq -r '.parameters.stoch_period_k')
                    stoch_d=$(echo "$result" | jq -r '.parameters.stoch_period_d')
                    echo "  Rank $((i + 1)): Sharpe=$sharpe, DMI=$dmi_enabled, DMI_Period=$dmi_period, Stoch_K=$stoch_k, Stoch_D=$stoch_d"
                fi
            done
        else
            echo "  (jq not available, using Python to display results)"
            python -c "
import json
with open('${output_files[1]}') as f:
    data = json.load(f)
for i in range(min(3, len(data))):
    result = data[i]
    print(f'  Rank {i+1}: Sharpe={result[\"objective_value\"]}, DMI={result[\"parameters\"][\"dmi_enabled\"]}, DMI_Period={result[\"parameters\"][\"dmi_period\"]}, Stoch_K={result[\"parameters\"][\"stoch_period_k\"]}, Stoch_D={result[\"parameters\"][\"stoch_period_d\"]}')
"
        fi
        
        # Compare with Phase 4 baseline
        echo ""
        echo "Improvement over Phase 4:"
        if command -v jq >/dev/null 2>&1; then
            phase5_sharpe=$(jq -r '.[0].objective_value' "${output_files[1]}")
            phase4_sharpe=$(jq -r '.[0].objective_value' optimization/results/phase4_risk_management_results_top_10.json)
            improvement=$(python -c "print(f'{($phase5_sharpe - $phase4_sharpe) / $phase4_sharpe * 100:.2f}%')")
            echo "  Sharpe ratio: $phase4_sharpe -> $phase5_sharpe ($improvement)"
        else
            python -c "
import json
with open('${output_files[1]}') as f:
    phase5_data = json.load(f)
with open('optimization/results/phase4_risk_management_results_top_10.json') as f:
    phase4_data = json.load(f)
phase5_sharpe = phase5_data[0]['objective_value']
phase4_sharpe = phase4_data[0]['objective_value']
improvement = (phase5_sharpe - phase4_sharpe) / phase4_sharpe * 100
print(f'  Sharpe ratio: {phase4_sharpe} -> {phase5_sharpe} ({improvement:.2f}%)')
"
        fi
        
        # Display execution statistics
        echo ""
        echo "Execution Statistics:"
        echo "  Total duration: $((DURATION / 3600))h $(((DURATION % 3600) / 60))m $((DURATION % 60))s"
        echo "  Average time per backtest: $((DURATION / EXPECTED_COMBINATIONS)) seconds"
        if [ -n "$row_count" ]; then
            success_rate=$(python -c "print(f'{($row_count / $EXPECTED_COMBINATIONS * 100):.1f}%')")
            echo "  Success rate: $row_count/$EXPECTED_COMBINATIONS ($success_rate)"
        fi
    fi
    
    echo ""
    echo "✅ Phase 5 Complete!"
    if command -v jq >/dev/null 2>&1; then
        best_sharpe=$(jq -r '.[0].objective_value' "${output_files[1]}")
        best_dmi_enabled=$(jq -r '.[0].parameters.dmi_enabled' "${output_files[1]}")
        best_dmi_period=$(jq -r '.[0].parameters.dmi_period' "${output_files[1]}")
        best_stoch_k=$(jq -r '.[0].parameters.stoch_period_k' "${output_files[1]}")
        best_stoch_d=$(jq -r '.[0].parameters.stoch_period_d' "${output_files[1]}")
        echo "Best Sharpe: $best_sharpe"
        echo "Best params: DMI=$best_dmi_enabled, DMI_Period=$best_dmi_period, Stoch_K=$best_stoch_k, Stoch_D=$best_stoch_d"
    fi
    
else
    echo "❌ Phase 5 execution failed with exit code: $EXIT_CODE"
    echo "Check the logs above for error details."
    echo "Checkpoint file may contain partial results: $CHECKPOINT_FILE"
    exit 3
fi

# Success Message and Next Steps
# ==============================
echo ""
echo "Next Steps:"
echo "1. Review results: cat ${output_files[1]} | jq"
if [ "$USE_REDUCED" = true ]; then
    echo "2. Run validation: python optimization/scripts/validate_phase5_results.py --csv optimization/results/phase5_filters_reduced_results.csv --expected-combinations 108"
elif [ "$USE_MEDIUM" = true ]; then
    echo "2. Run validation: python optimization/scripts/validate_phase5_results.py --csv optimization/results/phase5_filters_medium_results.csv --expected-combinations 324"
else
    echo "2. Run validation: python optimization/scripts/validate_phase5_results.py --csv optimization/results/phase5_filters_results.csv --expected-combinations 2400"
fi
if [ "$USE_REDUCED" = true ]; then
    echo "3. If results are promising, run medium version: bash optimization/scripts/run_phase5.sh --use-medium"
elif [ "$USE_MEDIUM" = true ]; then
    echo "3. If results are promising, run full version: bash optimization/scripts/run_phase5.sh"
else
    echo "3. Analyze filter impact on win rate and trade count"
fi
echo "4. Update Phase 6 config with Phase 5 best filter parameters"
echo "5. Document findings in PHASE5_EXECUTION_LOG.md"
echo ""
echo "Output files:"
for file in "${output_files[@]}"; do
    echo "  - $file"
done

exit 0
