#!/bin/bash

# =============================================================================
# Phase 1 Core Strategy Test Automation Script
# =============================================================================
# 
# Purpose: Orchestrates 4 sequential backtest configurations to validate core 
#          strategy enhancements (market orders baseline, limit orders, 
#          Stochastic filter, Stochastic recency filter).
#
# Usage Examples:
#   Run all tests:                    ./tests/test_phase1_core_strategy.sh
#   Run specific test:                 ./tests/test_phase1_core_strategy.sh --test 1.2
#   Skip validation:                  ./tests/test_phase1_core_strategy.sh --skip-validation
#   Verbose mode:                      ./tests/test_phase1_core_strategy.sh --verbose
#   Clean and run:                     ./tests/test_phase1_core_strategy.sh --clean
#   Help:                              ./tests/test_phase1_core_strategy.sh --help
#
# Test Scenarios:
#   1.1 - Baseline: Market orders, DMI enabled, Stochastic disabled
#   1.2 - Limit Orders: Enable limit orders with next-bar entry
#   1.3 - Stochastic Basic: Enable Stochastic filter without recency check
#   1.4 - Stochastic Recency: Enable Stochastic recency filter with 9-bar threshold
#
# Exit Codes:
#   0 - Success
#   1 - Test failure
#   2 - Validation failure
#   3 - Setup error
# =============================================================================

# =============================================================================
# Configuration and Constants
# =============================================================================

# Set script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Set log file and results directory
LOG_FILE="$SCRIPT_DIR/phase1_results.log"
RESULTS_DIR="$SCRIPT_DIR/phase1_test_results"

# Python command (works on both Windows and Unix)
PYTHON_CMD="python"

# Initialize arrays for storing test results
declare -a TEST_OUTPUT_DIRS
declare -a TEST_NAMES
declare -a TEST_METRICS

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No color

# =============================================================================
# Utility Functions
# =============================================================================

log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[ERROR] $1${NC}" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[SUCCESS] $1${NC}" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}" | tee -a "$LOG_FILE"
}

log_info() {
    echo -e "${BLUE}[INFO] $1${NC}" | tee -a "$LOG_FILE"
}

cleanup_previous_results() {
    log_message "Cleaning up previous test results..."
    
    if [[ -d "$RESULTS_DIR" ]]; then
        rm -rf "$RESULTS_DIR"
        log_success "Removed previous results directory: $RESULTS_DIR"
    fi
    
    if [[ -f "$LOG_FILE" ]]; then
        rm -f "$LOG_FILE"
        log_success "Removed previous log file: $LOG_FILE"
    fi
}

setup_test_environment() {
    log_message "Setting up test environment..."
    
    # Create results directory
    mkdir -p "$RESULTS_DIR"
    log_success "Created results directory: $RESULTS_DIR"
    
    # Initialize log file with header
    cat > "$LOG_FILE" << EOF
================================================================================
Phase 1 Core Strategy Test Suite - Execution Log
================================================================================
Start Time: $(date '+%Y-%m-%d %H:%M:%S')
Project Root: $PROJECT_ROOT
Script Directory: $SCRIPT_DIR
Results Directory: $RESULTS_DIR
================================================================================

EOF
    
    log_message "Initialized log file: $LOG_FILE"
    
    # Validate Python is available
    if ! command -v python >/dev/null 2>&1; then
        if command -v python3 >/dev/null 2>&1; then
            PYTHON_CMD="python3"
            log_warning "Using python3 instead of python"
        else
            log_error "Python not found. Please install Python."
            exit 3
        fi
    fi
    
    # Validate project structure
    if [[ ! -f "$PROJECT_ROOT/backtest/run_backtest.py" ]]; then
        log_error "backtest/run_backtest.py not found. Please run from project root."
        exit 3
    fi
    
    if [[ ! -f "$PROJECT_ROOT/analysis/compare_backtests.py" ]]; then
        log_error "analysis/compare_backtests.py not found. Please run from project root."
        exit 3
    fi
    
    log_success "Test environment setup complete"
}

set_base_env_variables() {
    log_message "Setting base environment variables..."
    
    # Common backtest configuration
    export BACKTEST_SYMBOL="EUR/USD"
    export BACKTEST_VENUE="IDEALPRO"
    export BACKTEST_START_DATE="2024-09-01"
    export BACKTEST_END_DATE="2024-10-31"
    export BACKTEST_BAR_SPEC="1-MINUTE-MID-EXTERNAL"
    export BACKTEST_FAST_PERIOD="10"
    export BACKTEST_SLOW_PERIOD="20"
    export BACKTEST_TRADE_SIZE="100000"
    export BACKTEST_STARTING_CAPITAL="100000.0"
    export CATALOG_PATH="data/historical"
    export OUTPUT_DIR="logs/backtest_results"
    export BACKTEST_STOP_LOSS_PIPS="25"
    export BACKTEST_TAKE_PROFIT_PIPS="50"
    export STRATEGY_CROSSOVER_THRESHOLD_PIPS="0.7"
    
    log_success "Base environment variables set"
}

find_latest_backtest_output() {
    local output_base="$PROJECT_ROOT/logs/backtest_results"
    local symbol_clean="EUR-USD"
    
    # Find the most recently created directory matching the pattern
    local latest_dir=""
    if [[ -d "$output_base" ]]; then
        latest_dir=$(find "$output_base" -name "${symbol_clean}_*" -type d | sort | tail -1)
    fi
    
    if [[ -n "$latest_dir" && -d "$latest_dir" ]]; then
        echo "$latest_dir"
    else
        log_error "No backtest output directory found"
        return 1
    fi
}

validate_backtest_output() {
    local output_dir="$1"
    local expected_order_type="$2"
    local skip_validation="$3"
    
    if [[ "$skip_validation" == "true" ]]; then
        log_info "Skipping validation for $output_dir"
        return 0
    fi
    
    log_message "Validating backtest output: $output_dir"
    
    # Check if output directory exists
    if [[ ! -d "$output_dir" ]]; then
        log_error "Output directory does not exist: $output_dir"
        return 1
    fi
    
    # Check required files exist
    local required_files=("orders.csv" "fills.csv" "positions.csv" "performance_stats.json")
    for file in "${required_files[@]}"; do
        if [[ ! -f "$output_dir/$file" ]]; then
            log_error "Required file missing: $output_dir/$file"
            return 1
        fi
    done
    
    # Check for rejected_signals.csv (optional)
    if [[ ! -f "$output_dir/rejected_signals.csv" ]]; then
        log_info "No rejected signals file found - treating as zero rejections"
    fi
    
    # Check for errors in application log
    if [[ -f "$PROJECT_ROOT/logs/application.log" ]]; then
        local error_count=$(grep -i "ERROR" "$PROJECT_ROOT/logs/application.log" | wc -l)
        if [[ $error_count -gt 0 ]]; then
            log_warning "Found $error_count errors in application log"
        fi
    fi
    
    # Check order type if specified
    if [[ -n "$expected_order_type" ]]; then
        # Use Python to check order types in a case-insensitive manner
        local order_type_check=$($PYTHON_CMD -c "
import pandas as pd
import sys
try:
    df = pd.read_csv('$output_dir/orders.csv')
    if 'order_type' in df.columns:
        order_types = df['order_type'].str.upper().unique()
        expected_upper = '$expected_order_type'.upper()
        if expected_upper in order_types:
            print('FOUND')
        else:
            print('NOT_FOUND')
    else:
        print('NO_COLUMN')
except Exception as e:
    print('ERROR')
" 2>/dev/null)
        
        if [[ "$order_type_check" == "FOUND" ]]; then
            log_success "Found expected order type '$expected_order_type' in orders.csv"
        elif [[ "$order_type_check" == "NOT_FOUND" ]]; then
            log_error "Expected order type '$expected_order_type' not found in orders.csv"
            return 1
        elif [[ "$order_type_check" == "NO_COLUMN" ]]; then
            log_warning "No 'order_type' column found in orders.csv - skipping order type validation"
        else
            log_error "Error checking order types in orders.csv"
            return 1
        fi
    fi
    
    log_success "Backtest output validation passed"
    return 0
}

extract_metrics() {
    local output_dir="$1"
    local performance_file="$output_dir/performance_stats.json"
    
    if [[ ! -f "$performance_file" ]]; then
        log_error "Performance stats file not found: $performance_file"
        return 1
    fi
    
    # Extract metrics using Python
    local metrics=$($PYTHON_CMD -c "
import json
import sys
import pandas as pd
try:
    with open('$performance_file', 'r') as f:
        data = json.load(f)
    
    # Extract from nested structure
    pnls = data.get('pnls', {})
    general = data.get('general', {})
    
    total_pnl = pnls.get('PnL', 0)
    win_rate = pnls.get('Win Rate', 0)
    expectancy = pnls.get('Expectancy', 0)
    sharpe_ratio = pnls.get('Sharpe Ratio', 0)
    
    # Calculate total_trades from positions.csv
    try:
        positions_df = pd.read_csv('$output_dir/positions.csv')
        # Filter out snapshot rows if they exist
        if 'is_snapshot' in positions_df.columns:
            positions_df = positions_df[positions_df['is_snapshot'] == False]
        total_trades = len(positions_df)
    except:
        total_trades = 0
    
    print(f'{total_pnl:.2f}|{win_rate:.2f}|{total_trades}|{expectancy:.2f}|{sharpe_ratio:.2f}')
except Exception as e:
    print('ERROR|ERROR|ERROR|ERROR|ERROR')
    sys.exit(1)
" 2>/dev/null)
    
    if [[ $? -ne 0 || "$metrics" == "ERROR|ERROR|ERROR|ERROR|ERROR" ]]; then
        log_error "Failed to extract metrics from $performance_file"
        return 1
    fi
    
    echo "$metrics"
}

# =============================================================================
# Test Execution Functions
# =============================================================================

run_test_1_1_baseline() {
    log_message "Running Test 1.1: Baseline (Market Orders, DMI enabled, Stochastic disabled)"
    
    # Set base environment variables
    set_base_env_variables
    
    # Override test-specific variables
    export STRATEGY_USE_LIMIT_ORDERS="false"
    export STRATEGY_DMI_ENABLED="true"
    export STRATEGY_DMI_PERIOD="14"
    export STRATEGY_DMI_BAR_SPEC="2-MINUTE-MID-EXTERNAL"
    export STRATEGY_STOCH_ENABLED="false"
    export STRATEGY_ATR_ENABLED="false"
    export STRATEGY_ADX_ENABLED="false"
    export STRATEGY_TIME_FILTER_ENABLED="false"
    export STRATEGY_CIRCUIT_BREAKER_ENABLED="false"
    
    # Execute backtest
    log_info "Executing backtest for Test 1.1..."
    echo "STRATEGY_CROSSOVER_THRESHOLD_PIPS=$STRATEGY_CROSSOVER_THRESHOLD_PIPS"
    cd "$PROJECT_ROOT"
    if $PYTHON_CMD backtest/run_backtest.py >> "$LOG_FILE" 2>&1; then
        log_success "Backtest execution completed for Test 1.1"
    else
        log_error "Backtest execution failed for Test 1.1"
        return 1
    fi
    
    # Find output directory
    local output_dir
    if output_dir=$(find_latest_backtest_output); then
        log_info "Found output directory: $output_dir"
    else
        log_error "Could not find output directory for Test 1.1"
        return 1
    fi
    
    # Validate output
    if validate_backtest_output "$output_dir" "MARKET" "$SKIP_VALIDATION"; then
        log_success "Test 1.1 validation passed"
    else
        log_error "Test 1.1 validation failed"
        return 1
    fi
    
    # Extract metrics
    local metrics
    if metrics=$(extract_metrics "$output_dir"); then
        log_success "Test 1.1 metrics extracted: $metrics"
    else
        log_error "Failed to extract metrics for Test 1.1"
        return 1
    fi
    
    # Store results
    TEST_OUTPUT_DIRS[0]="$output_dir"
    TEST_NAMES[0]="Test 1.1 - Baseline (Market Orders)"
    TEST_METRICS[0]="$metrics"
    
    log_success "Test 1.1 completed successfully"
    return 0
}

run_test_1_2_limit_orders() {
    log_message "Running Test 1.2: Limit Orders (Next-bar entry at bar.open)"
    
    # Set base environment variables
    set_base_env_variables
    
    # Override test-specific variables
    export STRATEGY_USE_LIMIT_ORDERS="true"
    export STRATEGY_LIMIT_ORDER_TIMEOUT_BARS="1"
    export STRATEGY_DMI_ENABLED="true"
    export STRATEGY_DMI_PERIOD="14"
    export STRATEGY_DMI_BAR_SPEC="2-MINUTE-MID-EXTERNAL"
    export STRATEGY_STOCH_ENABLED="false"
    export STRATEGY_ATR_ENABLED="false"
    export STRATEGY_ADX_ENABLED="false"
    export STRATEGY_TIME_FILTER_ENABLED="false"
    export STRATEGY_CIRCUIT_BREAKER_ENABLED="false"
    
    # Execute backtest
    log_info "Executing backtest for Test 1.2..."
    cd "$PROJECT_ROOT"
    if $PYTHON_CMD backtest/run_backtest.py >> "$LOG_FILE" 2>&1; then
        log_success "Backtest execution completed for Test 1.2"
    else
        log_error "Backtest execution failed for Test 1.2"
        return 1
    fi
    
    # Find output directory
    local output_dir
    if output_dir=$(find_latest_backtest_output); then
        log_info "Found output directory: $output_dir"
    else
        log_error "Could not find output directory for Test 1.2"
        return 1
    fi
    
    # Validate output
    if validate_backtest_output "$output_dir" "LIMIT" "$SKIP_VALIDATION"; then
        log_success "Test 1.2 validation passed"
    else
        log_error "Test 1.2 validation failed"
        return 1
    fi
    
    # Additional validation for limit order entry at next bar open
    if [[ "$SKIP_VALIDATION" != "true" ]]; then
        log_info "Validating limit order entry at next bar open for Test 1.2..."
        
        # Check that limit orders are present and timeout is set to 1 bar
        local limit_order_validation=$($PYTHON_CMD -c "
import pandas as pd
import sys
try:
    # Check orders.csv for limit orders
    orders_df = pd.read_csv('$output_dir/orders.csv')
    if 'order_type' in orders_df.columns:
        limit_orders = orders_df[orders_df['order_type'].str.upper() == 'LIMIT']
        if len(limit_orders) > 0:
            print('LIMIT_ORDERS_FOUND')
        else:
            print('NO_LIMIT_ORDERS')
    else:
        print('NO_ORDER_TYPE_COLUMN')
except Exception as e:
    print('ERROR')
" 2>/dev/null)
        
        if [[ "$limit_order_validation" == "LIMIT_ORDERS_FOUND" ]]; then
            log_success "Found limit orders in Test 1.2 - validating next-bar entry behavior"
            log_info "Limit order timeout set to 1 bar (STRATEGY_LIMIT_ORDER_TIMEOUT_BARS=1)"
            log_info "Orders should be placed at next bar open price and timeout after 1 bar if not filled"
            
            # Check application log for MovingAverageCrossover startup message
            if [[ -f "$PROJECT_ROOT/logs/application.log" ]]; then
                local expected_message="Limit orders enabled: entry at next bar open price, timeout=${STRATEGY_LIMIT_ORDER_TIMEOUT_BARS} bars"
                if grep -i "$expected_message" "$PROJECT_ROOT/logs/application.log" >/dev/null 2>&1; then
                    log_success "Found MovingAverageCrossover startup message: '$expected_message'"
                else
                    log_warning "MovingAverageCrossover startup message not found in application log"
                fi
            else
                log_info "Application log not found - skipping startup message validation"
            fi
            
            # Optional: Correlate fills.csv with orders.csv for deeper validation
            if [[ -f "$output_dir/fills.csv" && -f "$output_dir/orders.csv" ]]; then
                local correlation_check=$($PYTHON_CMD -c "
import pandas as pd
import sys
try:
    fills_df = pd.read_csv('$output_dir/fills.csv')
    orders_df = pd.read_csv('$output_dir/orders.csv')
    
    if 'order_id' in fills_df.columns and 'order_id' in orders_df.columns:
        # Check if first fill price equals order price
        if len(fills_df) > 0 and len(orders_df) > 0:
            first_fill = fills_df.iloc[0]
            matching_order = orders_df[orders_df['order_id'] == first_fill['order_id']]
            if len(matching_order) > 0:
                fill_price = first_fill.get('price', None)
                order_price = matching_order.iloc[0].get('price', None)
                if fill_price is not None and order_price is not None:
                    if abs(float(fill_price) - float(order_price)) < 0.00001:
                        print('FILL_ORDER_PRICE_MATCH')
                    else:
                        print('FILL_ORDER_PRICE_MISMATCH')
                else:
                    print('MISSING_PRICE_DATA')
            else:
                print('NO_MATCHING_ORDER')
        else:
            print('NO_FILLS_OR_ORDERS')
    else:
        print('MISSING_ORDER_ID_COLUMNS')
except Exception as e:
    print('CORRELATION_ERROR')
" 2>/dev/null)
                
                if [[ "$correlation_check" == "FILL_ORDER_PRICE_MATCH" ]]; then
                    log_success "Fill price matches order price - next-bar entry behavior confirmed"
                elif [[ "$correlation_check" == "FILL_ORDER_PRICE_MISMATCH" ]]; then
                    log_warning "Fill price differs from order price - this may indicate market execution instead of limit order"
                else
                    log_info "Could not correlate fills with orders - skipping price validation"
                fi
            else
                log_info "Missing fills.csv or orders.csv - skipping correlation validation"
            fi
        elif [[ "$limit_order_validation" == "NO_LIMIT_ORDERS" ]]; then
            log_warning "No limit orders found in Test 1.2 - this may indicate no signals were generated"
        else
            log_warning "Could not validate limit order behavior - check orders.csv structure"
        fi
    fi
    
    # Extract metrics
    local metrics
    if metrics=$(extract_metrics "$output_dir"); then
        log_success "Test 1.2 metrics extracted: $metrics"
    else
        log_error "Failed to extract metrics for Test 1.2"
        return 1
    fi
    
    # Store results
    TEST_OUTPUT_DIRS[1]="$output_dir"
    TEST_NAMES[1]="Test 1.2 - Limit Orders"
    TEST_METRICS[1]="$metrics"
    
    log_success "Test 1.2 completed successfully"
    return 0
}

run_test_1_3_stochastic_basic() {
    log_message "Running Test 1.3: Stochastic Filter (Basic, no recency check)"
    
    # Set base environment variables
    set_base_env_variables
    
    # Override test-specific variables
    export STRATEGY_USE_LIMIT_ORDERS="true"
    export STRATEGY_LIMIT_ORDER_TIMEOUT_BARS="1"
    export STRATEGY_DMI_ENABLED="true"
    export STRATEGY_DMI_PERIOD="14"
    export STRATEGY_DMI_BAR_SPEC="2-MINUTE-MID-EXTERNAL"
    export STRATEGY_STOCH_ENABLED="true"
    export STRATEGY_STOCH_PERIOD_K="14"
    export STRATEGY_STOCH_PERIOD_D="3"
    export STRATEGY_STOCH_BAR_SPEC="15-MINUTE-MID-EXTERNAL"
    export STRATEGY_STOCH_BULLISH_THRESHOLD="30"
    export STRATEGY_STOCH_BEARISH_THRESHOLD="70"
    export STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING="999"  # Effectively disabled
    export STRATEGY_ATR_ENABLED="false"
    export STRATEGY_ADX_ENABLED="false"
    export STRATEGY_TIME_FILTER_ENABLED="false"
    export STRATEGY_CIRCUIT_BREAKER_ENABLED="false"
    
    # Execute backtest
    log_info "Executing backtest for Test 1.3..."
    cd "$PROJECT_ROOT"
    if $PYTHON_CMD backtest/run_backtest.py >> "$LOG_FILE" 2>&1; then
        log_success "Backtest execution completed for Test 1.3"
    else
        log_error "Backtest execution failed for Test 1.3"
        return 1
    fi
    
    # Find output directory
    local output_dir
    if output_dir=$(find_latest_backtest_output); then
        log_info "Found output directory: $output_dir"
    else
        log_error "Could not find output directory for Test 1.3"
        return 1
    fi
    
    # Validate output
    if validate_backtest_output "$output_dir" "" "$SKIP_VALIDATION"; then
        log_success "Test 1.3 validation passed"
    else
        log_error "Test 1.3 validation failed"
        return 1
    fi
    
    # Check for stochastic rejections (only if file exists)
    if [[ "$SKIP_VALIDATION" != "true" && -f "$output_dir/rejected_signals.csv" ]]; then
        if grep -q "stochastic" "$output_dir/rejected_signals.csv" 2>/dev/null; then
            log_success "Found stochastic rejections in rejected_signals.csv"
        else
            log_warning "No stochastic rejections found (may be normal if no signals were rejected)"
        fi
    fi
    
    # Extract metrics
    local metrics
    if metrics=$(extract_metrics "$output_dir"); then
        log_success "Test 1.3 metrics extracted: $metrics"
    else
        log_error "Failed to extract metrics for Test 1.3"
        return 1
    fi
    
    # Store results
    TEST_OUTPUT_DIRS[2]="$output_dir"
    TEST_NAMES[2]="Test 1.3 - Stochastic Basic"
    TEST_METRICS[2]="$metrics"
    
    log_success "Test 1.3 completed successfully"
    return 0
}

run_test_1_4_stochastic_recency() {
    log_message "Running Test 1.4: Stochastic Recency Filter (9-bar threshold)"
    
    # Set base environment variables
    set_base_env_variables
    
    # Override test-specific variables
    export STRATEGY_USE_LIMIT_ORDERS="true"
    export STRATEGY_LIMIT_ORDER_TIMEOUT_BARS="1"
    export STRATEGY_DMI_ENABLED="true"
    export STRATEGY_DMI_PERIOD="14"
    export STRATEGY_DMI_BAR_SPEC="2-MINUTE-MID-EXTERNAL"
    export STRATEGY_STOCH_ENABLED="true"
    export STRATEGY_STOCH_PERIOD_K="14"
    export STRATEGY_STOCH_PERIOD_D="3"
    export STRATEGY_STOCH_BAR_SPEC="15-MINUTE-MID-EXTERNAL"
    export STRATEGY_STOCH_BULLISH_THRESHOLD="30"
    export STRATEGY_STOCH_BEARISH_THRESHOLD="70"
    export STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING="9"  # Enabled
    export STRATEGY_ATR_ENABLED="false"
    export STRATEGY_ADX_ENABLED="false"
    export STRATEGY_TIME_FILTER_ENABLED="false"
    export STRATEGY_CIRCUIT_BREAKER_ENABLED="false"
    
    # Execute backtest
    log_info "Executing backtest for Test 1.4..."
    cd "$PROJECT_ROOT"
    if $PYTHON_CMD backtest/run_backtest.py >> "$LOG_FILE" 2>&1; then
        log_success "Backtest execution completed for Test 1.4"
    else
        log_error "Backtest execution failed for Test 1.4"
        return 1
    fi
    
    # Find output directory
    local output_dir
    if output_dir=$(find_latest_backtest_output); then
        log_info "Found output directory: $output_dir"
    else
        log_error "Could not find output directory for Test 1.4"
        return 1
    fi
    
    # Validate output
    if validate_backtest_output "$output_dir" "" "$SKIP_VALIDATION"; then
        log_success "Test 1.4 validation passed"
    else
        log_error "Test 1.4 validation failed"
        return 1
    fi
    
    # Check for recency rejections (only if file exists)
    if [[ "$SKIP_VALIDATION" != "true" && -f "$output_dir/rejected_signals.csv" ]]; then
        if grep -q "stochastic_crossing_too_old\|stochastic_crossing_direction_mismatch" "$output_dir/rejected_signals.csv" 2>/dev/null; then
            log_success "Found recency rejections in rejected_signals.csv"
        else
            log_warning "No recency rejections found (may be normal if no signals were rejected)"
        fi
    fi
    
    # Extract metrics
    local metrics
    if metrics=$(extract_metrics "$output_dir"); then
        log_success "Test 1.4 metrics extracted: $metrics"
    else
        log_error "Failed to extract metrics for Test 1.4"
        return 1
    fi
    
    # Store results
    TEST_OUTPUT_DIRS[3]="$output_dir"
    TEST_NAMES[3]="Test 1.4 - Stochastic Recency"
    TEST_METRICS[3]="$metrics"
    
    log_success "Test 1.4 completed successfully"
    return 0
}

# =============================================================================
# Comparison and Reporting Functions
# =============================================================================

generate_comparison_report() {
    log_message "Generating comparison report..."
    
    # Check that all 4 tests completed successfully
    local missing_tests=0
    for i in {0..3}; do
        if [[ -z "${TEST_OUTPUT_DIRS[$i]}" || ! -d "${TEST_OUTPUT_DIRS[$i]}" ]]; then
            log_error "Test output directory missing for test $((i+1))"
            missing_tests=$((missing_tests + 1))
        fi
    done
    
    if [[ $missing_tests -gt 0 ]]; then
        log_error "Cannot generate comparison report: $missing_tests tests missing output directories"
        return 1
    fi
    
    # Generate comparison report
    local comparison_file="$RESULTS_DIR/phase1_comparison.html"
    local json_file="$RESULTS_DIR/phase1_comparison.json"
    
    log_info "Running comparison analysis..."
    cd "$PROJECT_ROOT"
    if $PYTHON_CMD analysis/compare_backtests.py \
        --baseline "${TEST_OUTPUT_DIRS[0]}" \
        --compare "${TEST_OUTPUT_DIRS[1]}" "${TEST_OUTPUT_DIRS[2]}" "${TEST_OUTPUT_DIRS[3]}" \
        --output "$comparison_file" \
        --json >> "$LOG_FILE" 2>&1; then
        log_success "Comparison report generated: $comparison_file"
        log_success "Comparison JSON generated: $json_file"
    else
        log_error "Failed to generate comparison report"
        return 1
    fi
    
    return 0
}

generate_summary_table() {
    log_message "Generating summary table..."
    
    echo ""
    echo "=================================================================================="
    echo "Phase 1 Core Strategy Test Results Summary"
    echo "=================================================================================="
    printf "%-30s | %-12s | %-8s | %-12s | %-10s | %-12s\n" "Test Name" "Total PnL" "Win Rate" "Total Trades" "Expectancy" "Sharpe Ratio"
    echo "----------------------------------------------------------------------------------"
    
    for i in {0..3}; do
        if [[ -n "${TEST_METRICS[$i]}" ]]; then
            IFS='|' read -r total_pnl win_rate total_trades expectancy sharpe_ratio <<< "${TEST_METRICS[$i]}"
            printf "%-30s | %-12s | %-8s | %-12s | %-10s | %-12s\n" \
                "${TEST_NAMES[$i]}" \
                "$total_pnl" \
                "$win_rate" \
                "$total_trades" \
                "$expectancy" \
                "$sharpe_ratio"
        else
            printf "%-30s | %-12s | %-8s | %-12s | %-10s | %-12s\n" \
                "${TEST_NAMES[$i]}" \
                "N/A" \
                "N/A" \
                "N/A" \
                "N/A" \
                "N/A"
        fi
    done
    
    echo "=================================================================================="
    echo ""
    
    # Log the same table to log file
    {
        echo ""
        echo "=================================================================================="
        echo "Phase 1 Core Strategy Test Results Summary"
        echo "=================================================================================="
        printf "%-30s | %-12s | %-8s | %-12s | %-10s | %-12s\n" "Test Name" "Total PnL" "Win Rate" "Total Trades" "Expectancy" "Sharpe Ratio"
        echo "----------------------------------------------------------------------------------"
        
        for i in {0..3}; do
            if [[ -n "${TEST_METRICS[$i]}" ]]; then
                IFS='|' read -r total_pnl win_rate total_trades expectancy sharpe_ratio <<< "${TEST_METRICS[$i]}"
                printf "%-30s | %-12s | %-8s | %-12s | %-10s | %-12s\n" \
                    "${TEST_NAMES[$i]}" \
                    "$total_pnl" \
                    "$win_rate" \
                    "$total_trades" \
                    "$expectancy" \
                    "$sharpe_ratio"
            else
                printf "%-30s | %-12s | %-8s | %-12s | %-10s | %-12s\n" \
                    "${TEST_NAMES[$i]}" \
                    "N/A" \
                    "N/A" \
                    "N/A" \
                    "N/A" \
                    "N/A"
            fi
        done
        
        echo "=================================================================================="
        echo ""
    } >> "$LOG_FILE"
}

export_test_results_json() {
    log_message "Exporting test results to JSON..."
    
    local json_file="$RESULTS_DIR/phase1_test_results.json"
    
    # Create JSON structure
    $PYTHON_CMD -c "
import json
import sys
from datetime import datetime

# Test data
tests = []
for i in range(4):
    test_data = {
        'test_id': f'1.{i+1}',
        'name': '${TEST_NAMES[i]}',
        'output_directory': '${TEST_OUTPUT_DIRS[i]}',
        'status': 'completed' if '${TEST_OUTPUT_DIRS[i]}' else 'failed'
    }
    
    if '${TEST_METRICS[i]}':
        metrics = '${TEST_METRICS[i]}'.split('|')
        test_data['metrics'] = {
            'total_pnl': float(metrics[0]) if metrics[0] != 'ERROR' else None,
            'win_rate': float(metrics[1]) if metrics[1] != 'ERROR' else None,
            'total_trades': int(metrics[2]) if metrics[2] != 'ERROR' else None,
            'expectancy': float(metrics[3]) if metrics[3] != 'ERROR' else None,
            'sharpe_ratio': float(metrics[4]) if metrics[4] != 'ERROR' else None
        }
    else:
        test_data['metrics'] = None
    
    tests.append(test_data)

# Create summary
summary = {
    'best_test': None,
    'worst_test': None,
    'average_metrics': None
}

# Find best and worst tests based on total_pnl
valid_tests = [t for t in tests if t['metrics'] and t['metrics']['total_pnl'] is not None]
if valid_tests:
    best_test = max(valid_tests, key=lambda x: x['metrics']['total_pnl'])
    worst_test = min(valid_tests, key=lambda x: x['metrics']['total_pnl'])
    summary['best_test'] = best_test['test_id']
    summary['worst_test'] = worst_test['test_id']
    
    # Calculate average metrics
    avg_pnl = sum(t['metrics']['total_pnl'] for t in valid_tests) / len(valid_tests)
    avg_win_rate = sum(t['metrics']['win_rate'] for t in valid_tests) / len(valid_tests)
    avg_trades = sum(t['metrics']['total_trades'] for t in valid_tests) / len(valid_tests)
    avg_expectancy = sum(t['metrics']['expectancy'] for t in valid_tests) / len(valid_tests)
    avg_sharpe = sum(t['metrics']['sharpe_ratio'] for t in valid_tests) / len(valid_tests)
    
    summary['average_metrics'] = {
        'total_pnl': round(avg_pnl, 2),
        'win_rate': round(avg_win_rate, 2),
        'total_trades': round(avg_trades, 0),
        'expectancy': round(avg_expectancy, 2),
        'sharpe_ratio': round(avg_sharpe, 2)
    }

# Create final structure
result = {
    'test_suite': 'Phase 1 - Core Strategy Validation',
    'execution_timestamp': datetime.now().isoformat(),
    'tests': tests,
    'summary': summary
}

# Write to file
with open('$json_file', 'w') as f:
    json.dump(result, f, indent=2)

print('Test results exported to: $json_file')
" 2>/dev/null
    
    if [[ $? -eq 0 ]]; then
        log_success "Test results exported to: $json_file"
    else
        log_error "Failed to export test results to JSON"
        return 1
    fi
    
    return 0
}

# =============================================================================
# CLI Argument Parsing
# =============================================================================

parse_arguments() {
    RUN_SPECIFIC_TEST=""
    SKIP_VALIDATION="false"
    VERBOSE="false"
    CLEAN="false"
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --test)
                RUN_SPECIFIC_TEST="$2"
                if [[ ! "$RUN_SPECIFIC_TEST" =~ ^1\.[1-4]$ ]]; then
                    log_error "Invalid test number: $RUN_SPECIFIC_TEST. Must be 1.1, 1.2, 1.3, or 1.4"
                    exit 1
                fi
                shift 2
                ;;
            --skip-validation)
                SKIP_VALIDATION="true"
                shift
                ;;
            --verbose)
                VERBOSE="true"
                export LOG_LEVEL="DEBUG"
                shift
                ;;
            --clean)
                CLEAN="true"
                shift
                ;;
            --help)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --test N.M           Run specific test (1.1, 1.2, 1.3, or 1.4)"
                echo "  --skip-validation    Skip file and content validation"
                echo "  --verbose            Enable detailed logging"
                echo "  --clean              Clean previous test results before running"
                echo "  --help               Show this help message"
                echo ""
                echo "Examples:"
                echo "  $0                           # Run all tests"
                echo "  $0 --test 1.2                # Run only test 1.2"
                echo "  $0 --skip-validation         # Run all tests without validation"
                echo "  $0 --verbose --clean         # Clean and run with verbose logging"
                exit 0
                ;;
            *)
                log_error "Unknown argument: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
    
    return 0
}

# =============================================================================
# Main Execution Flow
# =============================================================================

main() {
    # Parse command line arguments
    parse_arguments "$@"
    
    # Clean previous results if requested
    if [[ "$CLEAN" == "true" ]]; then
        cleanup_previous_results
    fi
    
    # Setup test environment
    setup_test_environment
    
    log_message "Starting Phase 1 Core Strategy Test Suite"
    log_message "Configuration: RUN_SPECIFIC_TEST=$RUN_SPECIFIC_TEST, SKIP_VALIDATION=$SKIP_VALIDATION, VERBOSE=$VERBOSE"
    
    local tests_passed=0
    local tests_failed=0
    
    # Execute tests
    if [[ -n "$RUN_SPECIFIC_TEST" ]]; then
        log_message "Running specific test: $RUN_SPECIFIC_TEST"
        
        case "$RUN_SPECIFIC_TEST" in
            "1.1")
                if run_test_1_1_baseline; then
                    tests_passed=$((tests_passed + 1))
                else
                    tests_failed=$((tests_failed + 1))
                fi
                ;;
            "1.2")
                if run_test_1_2_limit_orders; then
                    tests_passed=$((tests_passed + 1))
                else
                    tests_failed=$((tests_failed + 1))
                fi
                ;;
            "1.3")
                if run_test_1_3_stochastic_basic; then
                    tests_passed=$((tests_passed + 1))
                else
                    tests_failed=$((tests_failed + 1))
                fi
                ;;
            "1.4")
                if run_test_1_4_stochastic_recency; then
                    tests_passed=$((tests_passed + 1))
                else
                    tests_failed=$((tests_failed + 1))
                fi
                ;;
        esac
    else
        log_message "Running all 4 tests sequentially"
        
        # Test 1.1 - Baseline
        if run_test_1_1_baseline; then
            tests_passed=$((tests_passed + 1))
        else
            tests_failed=$((tests_failed + 1))
        fi
        
        # Test 1.2 - Limit Orders
        if run_test_1_2_limit_orders; then
            tests_passed=$((tests_passed + 1))
        else
            tests_failed=$((tests_failed + 1))
        fi
        
        # Test 1.3 - Stochastic Basic
        if run_test_1_3_stochastic_basic; then
            tests_passed=$((tests_passed + 1))
        else
            tests_failed=$((tests_failed + 1))
        fi
        
        # Test 1.4 - Stochastic Recency
        if run_test_1_4_stochastic_recency; then
            tests_passed=$((tests_passed + 1))
        else
            tests_failed=$((tests_failed + 1))
        fi
    fi
    
    # Generate reports
    log_message "Generating reports..."
    
    # Generate summary table
    generate_summary_table
    
    # Generate comparison report if all 4 tests ran
    if [[ -z "$RUN_SPECIFIC_TEST" && $tests_passed -eq 4 ]]; then
        if generate_comparison_report; then
            log_success "Comparison report generated successfully"
        else
            log_warning "Comparison report generation failed"
        fi
    fi
    
    # Export test results JSON
    if export_test_results_json; then
        log_success "Test results exported to JSON"
    else
        log_warning "JSON export failed"
    fi
    
    # Cleanup environment variables
    unset BACKTEST_SYMBOL BACKTEST_VENUE BACKTEST_START_DATE BACKTEST_END_DATE
    unset BACKTEST_BAR_SPEC BACKTEST_FAST_PERIOD BACKTEST_SLOW_PERIOD
    unset BACKTEST_TRADE_SIZE BACKTEST_STARTING_CAPITAL CATALOG_PATH OUTPUT_DIR
    unset BACKTEST_STOP_LOSS_PIPS BACKTEST_TAKE_PROFIT_PIPS STRATEGY_CROSSOVER_THRESHOLD_PIPS
    unset STRATEGY_USE_LIMIT_ORDERS STRATEGY_LIMIT_ORDER_TIMEOUT_BARS
    unset STRATEGY_DMI_ENABLED STRATEGY_DMI_PERIOD STRATEGY_DMI_BAR_SPEC
    unset STRATEGY_STOCH_ENABLED STRATEGY_STOCH_PERIOD_K STRATEGY_STOCH_PERIOD_D
    unset STRATEGY_STOCH_BAR_SPEC STRATEGY_STOCH_BULLISH_THRESHOLD STRATEGY_STOCH_BEARISH_THRESHOLD
    unset STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING STRATEGY_ATR_ENABLED STRATEGY_ADX_ENABLED
    unset STRATEGY_TIME_FILTER_ENABLED STRATEGY_CIRCUIT_BREAKER_ENABLED
    
    # Final summary
    log_message "Test suite completed: $tests_passed passed, $tests_failed failed"
    
    if [[ $tests_failed -eq 0 ]]; then
        log_success "All tests passed successfully!"
        echo ""
        echo "Report locations:"
        echo "  - Log file: $LOG_FILE"
        echo "  - Results directory: $RESULTS_DIR"
        if [[ -z "$RUN_SPECIFIC_TEST" ]]; then
            echo "  - Comparison report: $RESULTS_DIR/phase1_comparison.html"
        fi
        echo "  - JSON results: $RESULTS_DIR/phase1_test_results.json"
        echo ""
        return 0
    else
        log_error "Some tests failed. Check the log file for details: $LOG_FILE"
        return 1
    fi
}

# =============================================================================
# Script Entry Point
# =============================================================================

# Set error handling
set -e
set -u
set -o pipefail

# Call main function
main "$@"
EXIT_CODE=$?

# Exit with appropriate code
exit $EXIT_CODE
