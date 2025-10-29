#!/bin/bash

# Phase 6 Analysis Orchestration Script
# Orchestrates the execution of all three Phase 6 analysis tools in sequence:
# 1. Parameter sensitivity analysis
# 2. Pareto frontier top 5 selection  
# 3. Comprehensive analysis report generation
#
# This script automates the post-execution analysis workflow for Phase 6,
# generating 6 output files required for Phase 7 preparation.
#
# Prerequisites: Phase 6 grid search must be completed
# Expected Outputs: 6 files (sensitivity analysis, Pareto selection, comprehensive report)
# Estimated Runtime: < 5 minutes

set -e  # Exit on error
set -u  # Exit on undefined variable
set -o pipefail  # Exit on pipe failure

# Default parameters
RESULTS_DIR="optimization/results"
VERBOSE=false
CONTINUE_ON_ERROR=false

# Color definitions for terminal output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RESET='\033[0m'

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --results-dir)
            RESULTS_DIR="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --continue-on-error)
            CONTINUE_ON_ERROR=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --results-dir DIR     Results directory (default: optimization/results)"
            echo "  --verbose             Enable verbose logging"
            echo "  --continue-on-error   Continue execution if individual tools fail"
            echo "  --help                Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0"
            echo "  $0 --verbose --continue-on-error"
            echo "  $0 --results-dir custom/results"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Helper function to print colored output
print_color() {
    local message="$1"
    local color="$2"
    echo -e "${color}${message}${RESET}"
}

# Helper function to print step headers
print_step_header() {
    local step_number="$1"
    local step_name="$2"
    echo ""
    print_color "============================================================" "$CYAN"
    print_color "Step $step_number/3: $step_name" "$CYAN"
    print_color "============================================================" "$CYAN"
    echo ""
}

# Helper function to test file existence
test_file_exists() {
    local path="$1"
    local description="$2"
    
    if [[ ! -f "$path" ]]; then
        print_color "ERROR: $description not found at: $path" "$RED"
        return 1
    fi
    
    if [[ ! -s "$path" ]]; then
        print_color "ERROR: $description is empty at: $path" "$RED"
        return 1
    fi
    
    return 0
}

# Validate prerequisites function
validate_prerequisites() {
    print_color "Validating Phase 6 execution prerequisites..." "$CYAN"
    
    local prerequisites=(
        "$RESULTS_DIR/phase6_refinement_results.csv:Phase 6 results CSV"
        "$RESULTS_DIR/phase6_refinement_results_pareto_frontier.json:Pareto frontier JSON"
        "$RESULTS_DIR/phase6_refinement_results_top_10.json:Top 10 results JSON"
        "$RESULTS_DIR/phase6_refinement_results_summary.json:Summary JSON"
    )
    
    local all_valid=true
    for prereq in "${prerequisites[@]}"; do
        local path="${prereq%%:*}"
        local description="${prereq##*:}"
        
        if ! test_file_exists "$path" "$description"; then
            all_valid=false
        fi
    done
    
    if [[ "$all_valid" != "true" ]]; then
        echo ""
        print_color "Prerequisites validation failed!" "$RED"
        print_color "Please run Phase 6 grid search first using: bash optimization/scripts/run_phase6.sh" "$YELLOW"
        print_color "Then verify all result files are generated before running analysis." "$YELLOW"
        return 1
    fi
    
    print_color "All prerequisites validated successfully!" "$GREEN"
    return 0
}

# Execute parameter sensitivity analysis
invoke_sensitivity_analysis() {
    print_step_header 1 "Parameter Sensitivity Analysis"
    
    local command="python optimization/tools/analyze_parameter_sensitivity.py --csv \"$RESULTS_DIR/phase6_refinement_results.csv\" --objectives sharpe_ratio total_pnl max_drawdown --output-dir \"$RESULTS_DIR\""
    
    if [[ "$VERBOSE" == "true" ]]; then
        command="$command --verbose"
    fi
    
    print_color "Analyzing parameter correlations..." "$CYAN"
    print_color "Calculating variance contributions..." "$CYAN"
    print_color "Generating sensitivity report..." "$CYAN"
    echo ""
    
    if eval "$command"; then
        # Verify outputs
        local outputs=(
            "$RESULTS_DIR/phase6_sensitivity_analysis.json"
            "$RESULTS_DIR/phase6_sensitivity_summary.md"
            "$RESULTS_DIR/phase6_correlation_matrix.csv"
        )
        
        local all_outputs_exist=true
        for output in "${outputs[@]}"; do
            if [[ ! -f "$output" ]]; then
                print_color "WARNING: Expected output not found: $output" "$YELLOW"
                all_outputs_exist=false
            fi
        done
        
        if [[ "$all_outputs_exist" == "true" ]]; then
            print_color "Sensitivity analysis completed successfully!" "$GREEN"
            print_color "Generated files:" "$GREEN"
            for output in "${outputs[@]}"; do
                print_color "  - $output" "$GREEN"
            done
        else
            print_color "Sensitivity analysis completed with warnings - some outputs missing" "$YELLOW"
        fi
        
        return 0
    else
        local exit_code=$?
        print_color "Sensitivity analysis failed with exit code: $exit_code" "$RED"
        print_color "Check the error messages above for troubleshooting guidance." "$YELLOW"
        return $exit_code
    fi
}

# Execute Pareto frontier top 5 selection
invoke_pareto_top5_selection() {
    print_step_header 2 "Pareto Frontier Top 5 Selection"
    
    local command="python optimization/tools/select_pareto_top5.py --pareto-json \"$RESULTS_DIR/phase6_refinement_results_pareto_frontier.json\" --output \"$RESULTS_DIR/phase6_top_5_parameters.json\" --n 5"
    
    if [[ "$VERBOSE" == "true" ]]; then
        command="$command --verbose"
    fi
    
    print_color "Loading Pareto frontier..." "$CYAN"
    print_color "Normalizing objectives..." "$CYAN"
    print_color "Selecting diverse parameter sets..." "$CYAN"
    print_color "Exporting for Phase 7..." "$CYAN"
    echo ""
    
    if eval "$command"; then
        # Verify outputs
        local outputs=(
            "$RESULTS_DIR/phase6_top_5_parameters.json"
            "$RESULTS_DIR/phase6_pareto_selection_report.md"
        )
        
        local all_outputs_exist=true
        for output in "${outputs[@]}"; do
            if [[ ! -f "$output" ]]; then
                print_color "WARNING: Expected output not found: $output" "$YELLOW"
                all_outputs_exist=false
            fi
        done
        
        if [[ "$all_outputs_exist" == "true" ]]; then
            print_color "Pareto top 5 selection completed successfully!" "$GREEN"
            print_color "Generated files:" "$GREEN"
            for output in "${outputs[@]}"; do
                print_color "  - $output" "$GREEN"
            done
        else
            print_color "Pareto selection completed with warnings - some outputs missing" "$YELLOW"
        fi
        
        return 0
    else
        local exit_code=$?
        print_color "Pareto top 5 selection failed with exit code: $exit_code" "$RED"
        print_color "Check the error messages above for troubleshooting guidance." "$YELLOW"
        return $exit_code
    fi
}

# Execute comprehensive report generation
invoke_comprehensive_report() {
    print_step_header 3 "Comprehensive Analysis Report"
    
    local command="python optimization/tools/generate_phase6_analysis_report.py --results-dir \"$RESULTS_DIR\" --output \"$RESULTS_DIR/PHASE6_ANALYSIS_REPORT.md\""
    
    if [[ "$VERBOSE" == "true" ]]; then
        command="$command --verbose"
    fi
    
    print_color "Loading Phase 6 artifacts..." "$CYAN"
    print_color "Generating executive summary..." "$CYAN"
    print_color "Generating sensitivity section..." "$CYAN"
    print_color "Generating Pareto section..." "$CYAN"
    print_color "Generating recommendations..." "$CYAN"
    echo ""
    
    if eval "$command"; then
        # Verify output
        if [[ -f "$RESULTS_DIR/PHASE6_ANALYSIS_REPORT.md" ]]; then
            print_color "Comprehensive report generation completed successfully!" "$GREEN"
            print_color "Generated file: $RESULTS_DIR/PHASE6_ANALYSIS_REPORT.md" "$GREEN"
        else
            print_color "WARNING: Expected output not found: $RESULTS_DIR/PHASE6_ANALYSIS_REPORT.md" "$YELLOW"
        fi
        
        return 0
    else
        local exit_code=$?
        print_color "Comprehensive report generation failed with exit code: $exit_code" "$RED"
        print_color "Check the error messages above for troubleshooting guidance." "$YELLOW"
        return $exit_code
    fi
}

# Show analysis summary
show_analysis_summary() {
    echo ""
    print_color "============================================================" "$CYAN"
    print_color "Phase 6 Analysis Complete" "$CYAN"
    print_color "============================================================" "$CYAN"
    
    local expected_files=(
        "phase6_sensitivity_analysis.json"
        "phase6_sensitivity_summary.md"
        "phase6_correlation_matrix.csv"
        "phase6_top_5_parameters.json"
        "phase6_pareto_selection_report.md"
        "PHASE6_ANALYSIS_REPORT.md"
    )
    
    local generated_count=0
    print_color "Generated Files:" "$GREEN"
    for file in "${expected_files[@]}"; do
        local full_path="$RESULTS_DIR/$file"
        if [[ -f "$full_path" ]]; then
            local size=$(ls -lh "$full_path" | awk '{print $5}')
            print_color "  ✓ $file ($size)" "$GREEN"
            ((generated_count++))
        else
            print_color "  ✗ $file" "$YELLOW"
        fi
    done
    
    print_color "Total: $generated_count/${#expected_files[@]} files generated" "$GREEN"
}

# Show next steps
show_next_steps() {
    print_color "Next Steps:" "$CYAN"
    print_color "1. Review comprehensive report:" "$RESET"
    print_color "   less \"$RESULTS_DIR/PHASE6_ANALYSIS_REPORT.md\"" "$YELLOW"
    echo ""
    print_color "2. Review top 5 parameter sets:" "$RESET"
    if command -v jq >/dev/null 2>&1; then
        print_color "   cat \"$RESULTS_DIR/phase6_top_5_parameters.json\" | jq" "$YELLOW"
    else
        print_color "   cat \"$RESULTS_DIR/phase6_top_5_parameters.json\" | python -m json.tool" "$YELLOW"
    fi
    echo ""
    print_color "3. Run validation:" "$RESET"
    print_color "   python optimization/scripts/validate_phase6_results.py --verbose" "$YELLOW"
    echo ""
    print_color "4. Phase 7 preparation:" "$RESET"
    print_color "   Top 5 parameter sets are ready for Phase 7 walk-forward validation" "$GREEN"
}

# Main execution
main() {
    print_color "Phase 6 Analysis Orchestration Script" "$CYAN"
    print_color "=====================================" "$CYAN"
    print_color "Results Directory: $RESULTS_DIR" "$RESET"
    print_color "Verbose Mode: $VERBOSE" "$RESET"
    print_color "Continue On Error: $CONTINUE_ON_ERROR" "$RESET"
    echo ""
    
    local start_time=$(date +%s)
    
    # Validate prerequisites
    if ! validate_prerequisites; then
        exit 1
    fi
    
    # Execute sensitivity analysis
    if ! invoke_sensitivity_analysis; then
        if [[ "$CONTINUE_ON_ERROR" != "true" ]]; then
            print_color "Sensitivity analysis failed. Use --continue-on-error to proceed anyway." "$RED"
            exit 2
        fi
    fi
    
    # Execute Pareto top 5 selection
    if ! invoke_pareto_top5_selection; then
        if [[ "$CONTINUE_ON_ERROR" != "true" ]]; then
            print_color "Pareto selection failed. Use --continue-on-error to proceed anyway." "$RED"
            exit 3
        fi
    fi
    
    # Execute comprehensive report generation
    if ! invoke_comprehensive_report; then
        print_color "Comprehensive report generation failed. This is critical for Phase 7." "$RED"
        exit 4
    fi
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))
    
    show_analysis_summary
    show_next_steps
    
    echo ""
    print_color "Total execution time: ${minutes}m ${seconds}s" "$CYAN"
    print_color "Phase 6 analysis completed successfully!" "$GREEN"
    
    exit 0
}

# Run main function
main "$@"
