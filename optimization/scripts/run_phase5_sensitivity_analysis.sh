#!/bin/bash
# Phase 5 Parameter Sensitivity Analysis Script
# 
# This script executes comprehensive parameter sensitivity analysis on Phase 5 results
# to identify the 4 most sensitive parameters for Phase 6 refinement.
#
# Prerequisites:
# - Phase 5 must be completed (phase5_filters_results.csv exists)
# - Python environment with required packages (pandas, numpy, scipy)
#
# Expected Outputs:
# - phase5_sensitivity_analysis.json (complete analysis data)
# - PHASE5_SENSITIVITY_REPORT.md (human-readable report)
# - phase5_correlation_matrix.csv (correlation data for spreadsheet analysis)
#
# Estimated Runtime: < 1 minute

set -e  # Exit on error
set -u  # Exit on undefined variable
set -o pipefail  # Exit on pipe failure

# Default parameters
CSV_PATH="optimization/results/phase5_filters_results.csv"
OUTPUT_DIR="optimization/results"
VERBOSE=false

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Function to print colored output
print_color() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to validate prerequisites
validate_prerequisites() {
    print_color $YELLOW "Validating prerequisites..."
    
    # Check if CSV file exists
    if [ ! -f "$CSV_PATH" ]; then
        print_color $RED "ERROR: Phase 5 results file not found: $CSV_PATH"
        print_color $RED "Please ensure Phase 5 has been completed successfully."
        exit 1
    fi
    
    # Check if CSV file is not empty
    if [ ! -s "$CSV_PATH" ]; then
        print_color $RED "ERROR: Phase 5 results file is empty: $CSV_PATH"
        print_color $RED "Please ensure Phase 5 has been completed successfully."
        exit 1
    fi
    
    # Check if summary JSON exists (optional validation)
    SUMMARY_PATH="optimization/results/phase5_filters_results_summary.json"
    if [ ! -f "$SUMMARY_PATH" ]; then
        print_color $YELLOW "WARNING: Phase 5 summary file not found: $SUMMARY_PATH"
        print_color $YELLOW "Proceeding with analysis..."
    fi
    
    print_color $GREEN "Prerequisites validated successfully."
}

# Function to execute sensitivity analysis
run_sensitivity_analysis() {
    print_color $WHITE "Starting Phase 5 sensitivity analysis..."
    
    # Build Python command
    PYTHON_CMD="python optimization/tools/analyze_phase5_sensitivity.py --csv \"$CSV_PATH\" --output-dir \"$OUTPUT_DIR\""
    
    if [ "$VERBOSE" = true ]; then
        PYTHON_CMD="$PYTHON_CMD --verbose"
    fi
    
    print_color $WHITE "Executing: $PYTHON_CMD"
    
    # Execute Python script
    if ! eval $PYTHON_CMD; then
        print_color $RED "ERROR: Python script failed"
        print_color $YELLOW "Troubleshooting suggestions:"
        print_color $YELLOW "1. Ensure Python is installed and in PATH"
        print_color $YELLOW "2. Install required packages: pip install pandas numpy scipy"
        print_color $YELLOW "3. Check that the CSV file is valid and not corrupted"
        print_color $YELLOW "4. Run with --verbose flag for detailed error information"
        exit 1
    fi
    
    print_color $GREEN "Phase 5 sensitivity analysis completed successfully."
}

# Function to validate output files
validate_output_files() {
    print_color $YELLOW "Validating output files..."
    
    EXPECTED_FILES=(
        "$OUTPUT_DIR/phase5_sensitivity_analysis.json"
        "$OUTPUT_DIR/PHASE5_SENSITIVITY_REPORT.md"
        "$OUTPUT_DIR/phase5_correlation_matrix.csv"
    )
    
    ALL_FILES_EXIST=true
    
    for file in "${EXPECTED_FILES[@]}"; do
        if [ -f "$file" ]; then
            FILE_SIZE=$(ls -lh "$file" | awk '{print $5}')
            print_color $GREEN "✓ $file ($FILE_SIZE)"
        else
            print_color $RED "✗ Missing: $file"
            ALL_FILES_EXIST=false
        fi
    done
    
    if [ "$ALL_FILES_EXIST" = false ]; then
        print_color $RED "ERROR: Some expected output files are missing."
        print_color $RED "Please check the Python script execution for errors."
        exit 1
    fi
    
    print_color $GREEN "All output files validated successfully."
}

# Function to show summary
show_summary() {
    print_color $WHITE "Reading analysis summary..."
    
    JSON_PATH="$OUTPUT_DIR/phase5_sensitivity_analysis.json"
    
    if [ -f "$JSON_PATH" ]; then
        # Try to use jq if available, otherwise use python
        if command -v jq >/dev/null 2>&1; then
            print_color $WHITE ""
            print_color $WHITE "============================================================"
            print_color $WHITE "PHASE 5 SENSITIVITY ANALYSIS SUMMARY"
            print_color $WHITE "============================================================"
            
            DATASET_SIZE=$(jq -r '.metadata.dataset_size' "$JSON_PATH")
            BEST_SHARPE=$(jq -r '.metadata.best_sharpe_ratio' "$JSON_PATH")
            PARAMS_ANALYZED=$(jq -r '.metadata.parameters_analyzed' "$JSON_PATH")
            
            print_color $WHITE "Dataset Size: $DATASET_SIZE completed runs"
            print_color $WHITE "Best Sharpe Ratio: $BEST_SHARPE"
            print_color $WHITE "Parameters Analyzed: $PARAMS_ANALYZED"
            
            print_color $GREEN ""
            print_color $GREEN "Top 4 Most Sensitive Parameters:"
            jq -r '.top_4_sensitive_parameters[] | "  \(.rank). \(.parameter_name): \(.sensitivity_score)"' "$JSON_PATH" | while read line; do
                print_color $GREEN "$line"
            done
            
            print_color $WHITE ""
            print_color $WHITE "Output Files:"
            print_color $WHITE "  - JSON: $OUTPUT_DIR/phase5_sensitivity_analysis.json"
            print_color $WHITE "  - Report: $OUTPUT_DIR/PHASE5_SENSITIVITY_REPORT.md"
            print_color $WHITE "  - CSV: $OUTPUT_DIR/phase5_correlation_matrix.csv"
            
            print_color $WHITE "============================================================"
        else
            # Fallback to python for JSON parsing
            python3 -c "
import json
import sys
try:
    with open('$JSON_PATH', 'r') as f:
        data = json.load(f)
    
    print('')
    print('=' * 60)
    print('PHASE 5 SENSITIVITY ANALYSIS SUMMARY')
    print('=' * 60)
    print(f'Dataset Size: {data[\"metadata\"][\"dataset_size\"]} completed runs')
    print(f'Best Sharpe Ratio: {data[\"metadata\"][\"best_sharpe_ratio\"]}')
    print(f'Parameters Analyzed: {data[\"metadata\"][\"parameters_analyzed\"]}')
    print('')
    print('Top 4 Most Sensitive Parameters:')
    for param in data['top_4_sensitive_parameters']:
        print(f'  {param[\"rank\"]}. {param[\"parameter_name\"]}: {param[\"sensitivity_score\"]}')
    print('')
    print('Output Files:')
    print(f'  - JSON: $OUTPUT_DIR/phase5_sensitivity_analysis.json')
    print(f'  - Report: $OUTPUT_DIR/PHASE5_SENSITIVITY_REPORT.md')
    print(f'  - CSV: $OUTPUT_DIR/phase5_correlation_matrix.csv')
    print('=' * 60)
except Exception as e:
    print('WARNING: Could not parse JSON summary:', str(e))
" 2>/dev/null || print_color $YELLOW "WARNING: Could not parse JSON summary"
        fi
    else
        print_color $YELLOW "WARNING: Could not find JSON summary file"
    fi
}

# Function to show next steps
show_next_steps() {
    print_color $YELLOW ""
    print_color $YELLOW "Next Steps:"
    print_color $WHITE "1. Review the sensitivity analysis report:"
    print_color $WHITE "   cat \"$OUTPUT_DIR/PHASE5_SENSITIVITY_REPORT.md\""
    print_color $WHITE ""
    print_color $WHITE "2. Update Phase 6 configuration based on findings:"
    print_color $WHITE "   Edit optimization/configs/phase6_refinement.yaml"
    print_color $WHITE "   - Refine only the 4 most sensitive parameters"
    print_color $WHITE "   - Fix remaining 7 parameters at Phase 5 best values"
    print_color $WHITE ""
    print_color $WHITE "3. Run Phase 6 with updated configuration:"
    print_color $WHITE "   ./optimization/scripts/run_phase6.sh"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --csv)
            CSV_PATH="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--csv PATH] [--output-dir DIR] [--verbose]"
            echo ""
            echo "Options:"
            echo "  --csv PATH        Path to phase5_filters_results.csv (default: optimization/results/phase5_filters_results.csv)"
            echo "  --output-dir DIR  Output directory for results (default: optimization/results)"
            echo "  --verbose         Enable verbose logging"
            echo "  -h, --help        Show this help message"
            exit 0
            ;;
        *)
            print_color $RED "Unknown option: $1"
            print_color $YELLOW "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Main execution
main() {
    print_color $GREEN "Phase 5 Parameter Sensitivity Analysis"
    print_color $GREEN "====================================="
    print_color $WHITE "CSV Path: $CSV_PATH"
    print_color $WHITE "Output Dir: $OUTPUT_DIR"
    print_color $WHITE "Verbose: $VERBOSE"
    print_color $WHITE ""
    
    # Validate prerequisites
    validate_prerequisites
    
    # Execute sensitivity analysis
    run_sensitivity_analysis
    
    # Validate output files
    validate_output_files
    
    # Show summary
    show_summary
    
    # Show next steps
    show_next_steps
    
    print_color $GREEN ""
    print_color $GREEN "Phase 5 sensitivity analysis completed successfully!"
}

# Run main function
main "$@"