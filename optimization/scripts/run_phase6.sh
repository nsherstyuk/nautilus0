#!/bin/bash
# Phase 6: Parameter Refinement and Sensitivity Analysis
# Automated Phase 6 execution for Linux/Mac/WSL with multi-objective Pareto analysis
# Selective refinement of most sensitive parameters from Phases 3-5 using Pareto optimization

# Script metadata
SCRIPT_NAME="Phase 6: Parameter Refinement and Sensitivity Analysis"
SCRIPT_VERSION="1.0"
CONFIG_FILE="optimization/configs/phase6_refinement.yaml"
EXPECTED_RUNTIME="4-6 hours"

# Default parameters
WORKERS=8
NO_ARCHIVE=false
DRY_RUN=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}$1${NC}"
}

print_warning() {
    echo -e "${YELLOW}$1${NC}"
}

print_error() {
    echo -e "${RED}$1${NC}"
}

print_info() {
    echo -e "${CYAN}$1${NC}"
}

print_gray() {
    echo -e "${GRAY}$1${NC}"
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -w, --workers <int>    Number of parallel workers (default: 8)"
    echo "  -n, --no-archive       Skip archiving old results"
    echo "  -d, --dry-run          Show what would be executed without running"
    echo "  -h, --help             Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0"
    echo "  $0 --workers 12"
    echo "  $0 --dry-run"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -w|--workers)
            WORKERS="$2"
            shift 2
            ;;
        -n|--no-archive)
            NO_ARCHIVE=true
            shift
            ;;
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Script header
echo "================================================"
print_info "  $SCRIPT_NAME"
print_info "  Version: $SCRIPT_VERSION"
echo "================================================"
echo ""

# Environment Variable Setup
print_status "Setting up environment variables..."

export BACKTEST_SYMBOL="EUR/USD"
export BACKTEST_VENUE="IDEALPRO"
export BACKTEST_START_DATE="2025-01-01"
export BACKTEST_END_DATE="2025-07-31"
export BACKTEST_BAR_SPEC="15-MINUTE-MID-EXTERNAL"
export CATALOG_PATH="data/historical"
export OUTPUT_DIR="logs/backtest_results"

print_gray "  BACKTEST_SYMBOL: $BACKTEST_SYMBOL"
print_gray "  BACKTEST_VENUE: $BACKTEST_VENUE"
print_gray "  BACKTEST_START_DATE: $BACKTEST_START_DATE"
print_gray "  BACKTEST_END_DATE: $BACKTEST_END_DATE"
print_gray "  BACKTEST_BAR_SPEC: $BACKTEST_BAR_SPEC"
print_gray "  CATALOG_PATH: $CATALOG_PATH"
print_gray "  OUTPUT_DIR: $OUTPUT_DIR"
echo ""

# Pre-flight Validation
print_status "Performing pre-flight validation..."

# Check Python availability
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    print_error "  ✗ Python not found"
    print_error "    Please install Python 3.8+ and ensure it's in your PATH"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1)
print_status "  ✓ Python found: $PYTHON_VERSION"

# Verify Phase 6 config exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    print_error "  ✗ Phase 6 config not found: $CONFIG_FILE"
    print_error "    Please ensure the configuration file exists"
    exit 1
fi
print_status "  ✓ Phase 6 config found: $CONFIG_FILE"

# Verify Phase 5 results exist
PHASE5_RESULTS="optimization/results/phase5_filters_results_top_10.json"
if [[ ! -f "$PHASE5_RESULTS" ]]; then
    print_error "  ✗ Phase 5 results not found: $PHASE5_RESULTS"
    print_error "    Phase 5 must be completed before running Phase 6"
    exit 1
fi
print_status "  ✓ Phase 5 results found: $PHASE5_RESULTS"

# Verify catalog path exists
if [[ ! -d "$CATALOG_PATH" ]]; then
    print_error "  ✗ Catalog path not found: $CATALOG_PATH"
    print_error "    Please ensure the data catalog exists"
    exit 1
fi
print_status "  ✓ Catalog path found: $CATALOG_PATH"

# Validate date range
START_DATE=$(date -d "$BACKTEST_START_DATE" +%s 2>/dev/null || date -j -f "%Y-%m-%d" "$BACKTEST_START_DATE" +%s 2>/dev/null)
END_DATE=$(date -d "$BACKTEST_END_DATE" +%s 2>/dev/null || date -j -f "%Y-%m-%d" "$BACKTEST_END_DATE" +%s 2>/dev/null)

if [[ $END_DATE -le $START_DATE ]]; then
    print_error "  ✗ Invalid date range: End date must be after start date"
    exit 1
fi

DURATION_DAYS=$(( (END_DATE - START_DATE) / 86400 ))
print_status "  ✓ Date range valid: $DURATION_DAYS days"

# Check required Python packages
print_gray "  Checking required Python packages..."
REQUIRED_PACKAGES=("pandas" "yaml" "numpy" "scipy")
for package in "${REQUIRED_PACKAGES[@]}"; do
    if $PYTHON_CMD -c "import $package" 2>/dev/null; then
        print_status "    ✓ $package"
    else
        print_error "    ✗ $package not found"
        print_error "      Please install: pip install $package"
        exit 1
    fi
done

print_status "  ✓ All pre-flight checks passed"
echo ""

# Archive Old Results
if [[ "$NO_ARCHIVE" == false ]]; then
    print_status "Archiving old Phase 6 results..."
    
    ARCHIVE_DIR="optimization/results/archive/phase6_$(date +%Y%m%d_%H%M%S)"
    PHASE6_FILES=(
        "optimization/results/phase6_refinement_results.csv"
        "optimization/results/phase6_refinement_results_top_10.json"
        "optimization/results/phase6_refinement_results_summary.json"
        "optimization/results/phase6_refinement_results_pareto_frontier.json"
        "optimization/results/phase6_sensitivity_analysis.json"
        "optimization/results/phase6_top_5_parameters.json"
        "optimization/results/PHASE6_ANALYSIS_REPORT.md"
    )
    
    FILES_TO_ARCHIVE=()
    for file in "${PHASE6_FILES[@]}"; do
        if [[ -f "$file" ]]; then
            FILES_TO_ARCHIVE+=("$file")
        fi
    done
    
    if [[ ${#FILES_TO_ARCHIVE[@]} -gt 0 ]]; then
        mkdir -p "$ARCHIVE_DIR"
        for file in "${FILES_TO_ARCHIVE[@]}"; do
            filename=$(basename "$file")
            cp "$file" "$ARCHIVE_DIR/$filename"
            rm "$file"
        done
        print_status "  ✓ Archived ${#FILES_TO_ARCHIVE[@]} files to $ARCHIVE_DIR"
    else
        print_status "  ✓ No old Phase 6 files to archive"
    fi
    echo ""
fi

# Display Execution Summary
print_info "Phase 6 Configuration:"
print_gray "  Total combinations: ~200-300 (selective refinement)"
print_gray "  Parameters being refined: 4 most sensitive parameters"
print_gray "  Fixed parameters: 8-9 at Phase 5 best values"
print_gray "  Multi-objective optimization: sharpe_ratio, total_pnl, max_drawdown"
print_gray "  Workers: $WORKERS"
print_gray "  Expected runtime: $EXPECTED_RUNTIME"
echo ""

# Load Phase 5 baseline
print_status "Loading Phase 5 baseline..."
if command -v jq &> /dev/null; then
    # Read objective_value from Phase 5 top_10 JSON for the best Sharpe
    PHASE5_SHARPE=$(jq -r '.[0].objective_value' "$PHASE5_RESULTS")
    # Access parameters via parameters.fast_period, etc.
    PHASE5_FAST=$(jq -r '.[0].parameters.fast_period' "$PHASE5_RESULTS")
    PHASE5_SLOW=$(jq -r '.[0].parameters.slow_period' "$PHASE5_RESULTS")
    PHASE5_THRESHOLD=$(jq -r '.[0].parameters.crossover_threshold_pips' "$PHASE5_RESULTS")
    print_status "  ✓ Phase 5 best Sharpe: $PHASE5_SHARPE"
    print_status "  ✓ Phase 5 parameters: fast=$PHASE5_FAST, slow=$PHASE5_SLOW, threshold=$PHASE5_THRESHOLD"
else
    print_warning "  jq not found, using Python to parse JSON"
    PHASE5_SHARPE=$($PYTHON_CMD -c "import json; data=json.load(open('$PHASE5_RESULTS')); print(data[0]['objective_value'])")
    PHASE5_FAST=$($PYTHON_CMD -c "import json; data=json.load(open('$PHASE5_RESULTS')); print(data[0]['parameters']['fast_period'])")
    PHASE5_SLOW=$($PYTHON_CMD -c "import json; data=json.load(open('$PHASE5_RESULTS')); print(data[0]['parameters']['slow_period'])")
    PHASE5_THRESHOLD=$($PYTHON_CMD -c "import json; data=json.load(open('$PHASE5_RESULTS')); print(data[0]['parameters']['crossover_threshold_pips'])")
    print_status "  ✓ Phase 5 best Sharpe: $PHASE5_SHARPE"
    print_status "  ✓ Phase 5 parameters: fast=$PHASE5_FAST, slow=$PHASE5_SLOW, threshold=$PHASE5_THRESHOLD"
fi
echo ""

# Target: Maintain or improve Sharpe, generate robust Pareto frontier
print_warning "Target: Maintain or improve Phase 5 Sharpe ($PHASE5_SHARPE), generate robust Pareto frontier"
echo ""

# Important: Highlight that this uses --pareto flag for multi-objective analysis
print_warning "IMPORTANT: This execution uses --pareto flag for multi-objective analysis"
echo ""

if [[ "$DRY_RUN" == true ]]; then
    print_warning "DRY RUN - Would execute the following command:"
    echo ""
    print_gray "python optimization/grid_search.py \\"
    print_gray "  --config optimization/configs/phase6_refinement.yaml \\"
    print_gray "  --objective sharpe_ratio \\"
    print_gray "  --pareto sharpe_ratio total_pnl max_drawdown \\"
    print_gray "  --workers $WORKERS \\"
    print_gray "  --output optimization/results/phase6_refinement_results.csv \\"
    print_gray "  --no-resume \\"
    print_gray "  --verbose"
    echo ""
    print_warning "Analysis tools that would run:"
    print_gray "  - python optimization/tools/analyze_parameter_sensitivity.py"
    print_gray "  - python optimization/tools/select_pareto_top5.py"
    print_gray "  - python optimization/tools/generate_phase6_analysis_report.py"
    echo ""
    print_warning "DRY RUN COMPLETE"
    exit 0
fi

# Execute Grid Search with Pareto Analysis
print_status "Executing Phase 6 parameter refinement with Pareto analysis..."
echo ""

START_TIME=$(date +%s)

# Build command
COMMAND=(
    "$PYTHON_CMD" "optimization/grid_search.py"
    "--config" "optimization/configs/phase6_refinement.yaml"
    "--objective" "sharpe_ratio"
    "--pareto" "sharpe_ratio" "total_pnl" "max_drawdown"
    "--workers" "$WORKERS"
    "--output" "optimization/results/phase6_refinement_results.csv"
    "--no-resume"
    "--verbose"
)

print_gray "Command: ${COMMAND[*]}"
echo ""

if ! "${COMMAND[@]}"; then
    print_error "  ✗ Grid search execution failed"
    exit 1
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
DURATION_FORMATTED=$(printf '%02d:%02d:%02d' $((DURATION/3600)) $((DURATION%3600/60)) $((DURATION%60)))

echo ""
print_status "Grid search completed in $DURATION_FORMATTED"
print_status "  ✓ Grid search completed successfully"
echo ""

# Post-execution Validation
print_status "Validating Phase 6 results..."

# Verify output files exist
REQUIRED_FILES=(
    "optimization/results/phase6_refinement_results.csv"
    "optimization/results/phase6_refinement_results_top_10.json"
    "optimization/results/phase6_refinement_results_summary.json"
    "optimization/results/phase6_refinement_results_pareto_frontier.json"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [[ -f "$file" ]]; then
        print_status "  ✓ $file"
    else
        print_error "  ✗ $file not found"
        exit 1
    fi
done

# Count CSV rows
ROW_COUNT=$(wc -l < "optimization/results/phase6_refinement_results.csv")
ROW_COUNT=$((ROW_COUNT - 1))  # Subtract header row
print_status "  ✓ Results CSV contains $ROW_COUNT rows"

# Load and display Pareto frontier size
if command -v jq &> /dev/null; then
    FRONTIER_SIZE=$(jq -r '.frontier | length' "optimization/results/phase6_refinement_results_pareto_frontier.json")
else
    FRONTIER_SIZE=$($PYTHON_CMD -c "import json; data=json.load(open('optimization/results/phase6_refinement_results_pareto_frontier.json')); print(len(data['frontier']))")
fi
print_status "  ✓ Pareto frontier contains $FRONTIER_SIZE non-dominated solutions"

print_status "  ✓ All Phase 6 results validated"
echo ""

# Run Analysis Tools
print_status "Running Phase 6 analysis tools..."

# Execute sensitivity analysis
print_gray "  Running parameter sensitivity analysis..."
if ! $PYTHON_CMD optimization/tools/analyze_parameter_sensitivity.py --csv optimization/results/phase6_refinement_results.csv --objectives sharpe_ratio total_pnl max_drawdown; then
    print_error "    ✗ Sensitivity analysis failed"
    exit 1
fi
print_status "    ✓ Sensitivity analysis completed"

# Execute Pareto top 5 selection
print_gray "  Running Pareto top 5 selection..."
if ! $PYTHON_CMD optimization/tools/select_pareto_top5.py --pareto-json optimization/results/phase6_refinement_results_pareto_frontier.json --output optimization/results/phase6_top_5_parameters.json; then
    print_error "    ✗ Pareto top 5 selection failed"
    exit 1
fi
print_status "    ✓ Pareto top 5 selection completed"

# Generate comprehensive analysis report
print_gray "  Generating comprehensive analysis report..."
if ! $PYTHON_CMD optimization/tools/generate_phase6_analysis_report.py --results-dir optimization/results --output optimization/results/PHASE6_ANALYSIS_REPORT.md; then
    print_error "    ✗ Report generation failed"
    exit 1
fi
print_status "    ✓ Comprehensive analysis report generated"

print_status "  ✓ All analysis tools completed successfully"
echo ""

# Success Message and Next Steps
echo "================================================"
print_status "  PHASE 6 COMPLETED SUCCESSFULLY!"
echo "================================================"
echo ""

# Show key findings
print_info "Key Findings:"
if command -v jq &> /dev/null; then
    BEST_SHARPE=$(jq -r '.[0].sharpe_ratio' "optimization/results/phase6_refinement_results_top_10.json")
    BEST_PNL=$(jq -r '.[0].total_pnl' "optimization/results/phase6_refinement_results_top_10.json")
    BEST_DRAWDOWN=$(jq -r '.[0].max_drawdown' "optimization/results/phase6_refinement_results_top_10.json")
else
    BEST_SHARPE=$($PYTHON_CMD -c "import json; data=json.load(open('optimization/results/phase6_refinement_results_top_10.json')); print(data[0]['sharpe_ratio'])")
    BEST_PNL=$($PYTHON_CMD -c "import json; data=json.load(open('optimization/results/phase6_refinement_results_top_10.json')); print(data[0]['total_pnl'])")
    BEST_DRAWDOWN=$($PYTHON_CMD -c "import json; data=json.load(open('optimization/results/phase6_refinement_results_top_10.json')); print(data[0]['max_drawdown'])")
fi

print_gray "  Best Sharpe ratio: $BEST_SHARPE"
print_gray "  Best total PnL: $BEST_PNL"
print_gray "  Best max drawdown: $BEST_DRAWDOWN"
print_gray "  Pareto frontier size: $FRONTIER_SIZE non-dominated solutions"
print_gray "  Top 5 parameter sets selected for Phase 7"
print_gray "  Sensitivity analysis completed"
echo ""

# List output files
print_info "Output Files:"
print_gray "  - optimization/results/phase6_refinement_results.csv"
print_gray "  - optimization/results/phase6_refinement_results_top_10.json"
print_gray "  - optimization/results/phase6_refinement_results_summary.json"
print_gray "  - optimization/results/phase6_refinement_results_pareto_frontier.json"
print_gray "  - optimization/results/phase6_sensitivity_analysis.json"
print_gray "  - optimization/results/phase6_top_5_parameters.json"
print_gray "  - optimization/results/PHASE6_ANALYSIS_REPORT.md"
echo ""

# Suggest next steps
print_info "Next Steps:"
print_gray "  - Review PHASE6_ANALYSIS_REPORT.md for comprehensive analysis"
print_gray "  - Review phase6_top_5_parameters.json for Phase 7 walk-forward validation"
print_gray "  - Prepare for Phase 7 walk-forward validation"
print_gray "  - Expected Phase 7 runtime: varies by walk-forward configuration"
echo ""

print_status "Phase 6 execution completed successfully!"
