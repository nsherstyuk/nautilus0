# Phase 6: MA Crossover Diagnostics

## Overview

Phase 6 provides an automated diagnostic system for the Moving Average Crossover strategy. Unlike Phases 2-5 which test individual features with known expected outcomes, Phase 6 uses specialized edge-case scenarios to stress-test the MA crossing algorithm, detect misbehavior, and generate actionable improvement suggestions.

## Key Capabilities

- **Automated Testing**: Generates synthetic data, runs backtests, analyzes results without manual intervention
- **Edge Case Coverage**: Tests choppy markets, whipsaws, threshold boundaries, timing lag, false breakouts
- **Anomaly Detection**: Identifies false positives, false negatives, timing issues, filter failures
- **Improvement Suggestions**: Maps detected issues to specific parameter adjustments
- **Comprehensive Reporting**: HTML report with charts, JSON export, console summary

## Diagnostic Scenarios

### 1. Choppy Market (DIAG-CHOPPY/USD)
- **Purpose**: Test behavior in ranging market with frequent small crossovers
- **Pattern**: 10 rapid alternating crossovers with minimal separation (0.3 pips)
- **Expected**: Many trades (10+), likely poor performance
- **Detects**: Excessive trading in unfavorable conditions, need for filters

### 2. Whipsaw Pattern (DIAG-WHIPSAW/USD)
- **Purpose**: Test handling of immediate signal reversals
- **Pattern**: Bullish crossover followed by bearish crossover 2 bars later
- **Expected**: 2 trades, both likely losers
- **Detects**: Vulnerability to rapid reversals, need for confirmation filters

### 3. Threshold Boundary (DIAG-THRESH-*/USD)
- **Purpose**: Test boundary condition handling for crossover threshold
- **Pattern**: 3 variants with 0.99, 1.00, 1.01 pip separation
- **Expected**: 0, 1, 1 trades respectively (verify >= logic)
- **Detects**: Off-by-one errors, incorrect comparison operators

### 4. Delayed Crossover (DIAG-DELAYED/USD)
- **Purpose**: Test crossover detection timing with slow MA convergence
- **Pattern**: MAs converge gradually over 20 bars before crossing
- **Expected**: 1 trade at correct crossover bar
- **Detects**: Premature or delayed crossover detection

### 5. False Breakout (DIAG-BREAKOUT/USD)
- **Purpose**: Test resilience to price spikes causing temporary crossovers
- **Pattern**: Price spike causes crossover, then reverts within 3 bars
- **Expected**: Ideally 0 trades (filters reject), or 1 losing trade
- **Detects**: Susceptibility to false breakouts, filter effectiveness

### 6. No-Trade Zone (DIAG-NOTRADE/USD)
- **Purpose**: Test that strategy doesn't generate false signals when MAs are close but not crossing
- **Pattern**: MAs maintain constant 0.5 pip separation throughout
- **Expected**: 0 trades
- **Detects**: False positive signals from near-crossover conditions

### 7. Filter Cascade Failure (DIAG-CASCADE/USD)
- **Purpose**: Test filter cascade logic and rejection reason accuracy
- **Pattern**: Crossover passes threshold/separation but fails DMI filter
- **Expected**: 0 trades, DMI-related rejection reason
- **Detects**: Filter order issues, incorrect rejection logging

### 8. MA Lag Test (DIAG-LAG/USD)
- **Purpose**: Quantify inherent MA lag in trending markets
- **Pattern**: Strong uptrend (10 pips/bar) for 30 bars
- **Expected**: 1 trade, measure bars from trend start to crossover
- **Detects**: Excessive lag, need for faster MA periods

## Usage

### Quick Start (Full Automated Run)
```bash
python tests/run_ma_diagnostics.py
```
This will:
1. Generate diagnostic test data
2. Run all 8 backtest scenarios
3. Analyze results
4. Generate HTML and JSON reports

### Step-by-Step Execution

**Step 1: Generate Diagnostic Data**
```bash
python tests/generate_phase6_diagnostic_data.py
```
Creates synthetic data in `data/test_catalog/phase6_diagnostics/`

**Step 2: Run Diagnostics**
```bash
python tests/run_ma_diagnostics.py --skip-data-gen
```
Runs backtests using existing data

**Step 3: Analyze Existing Results**
```bash
python tests/run_ma_diagnostics.py --skip-data-gen --skip-backtests
```
Analyzes previously generated backtest results

### Command-Line Options
- `--skip-data-gen`: Skip data generation (use existing catalog)
- `--skip-backtests`: Skip backtest execution (analyze existing results)
- `--output-dir PATH`: Custom output directory for reports (default: `reports/ma_diagnostics`)
- `--verbose`: Enable debug logging

## Output Files

### Reports Directory (`reports/ma_diagnostics/`)
- `ma_diagnostics_{timestamp}.html` - Comprehensive HTML report with charts
- `ma_diagnostics_{timestamp}.json` - Machine-readable JSON report
- `ma_diagnostics_{timestamp}.log` - Execution log

### Backtest Results (`logs/test_results/phase6_diagnostics/`)
- `{scenario_name}/{timestamp}/` - Individual scenario results
  - `performance_stats.json`
  - `orders.csv`
  - `positions.csv`
  - `rejected_signals.csv`
  - `equity_curve.png`

## Interpreting Results

### Scenario Status
- **✓ PASS**: Scenario behaved as expected (trade count, rejections match expectations)
- **✗ FAIL**: Unexpected behavior detected (see Issues column for details)

### Detected Issues
- **False Positives**: Trades executed when none expected (choppy market, no-trade zone)
- **False Negatives**: No trades when expected (delayed crossover, threshold boundary)
- **Timing Issues**: Crossover detected at wrong bar (lag or premature detection)
- **Filter Failures**: Incorrect rejection reasons or filter cascade problems
- **Threshold Sensitivity**: Boundary condition failures (off-by-one errors)
- **Performance Issues**: Excessive losses in diagnostic scenarios

### Improvement Suggestions

Suggestions are prioritized and include:
- **Category**: Issue type being addressed
- **Suggestion**: Specific parameter change or code review
- **Rationale**: Why this change should help
- **Priority**: High/Medium/Low based on severity

**Example Suggestions:**
- **[HIGH] Increase crossover_threshold_pips from 1.0 to 2.0**: Reduces false positives in choppy market scenario by requiring larger MA separation
- **[MEDIUM] Enable DMI filter**: Adds trend confirmation to reduce whipsaw trades
- **[LOW] Consider reducing MA periods to 8/15**: Reduces lag but increases noise sensitivity

## Common Issues and Solutions

### Issue: Too Many Trades in Choppy Market
- **Symptom**: DIAG-CHOPPY scenario shows 10+ trades with poor PnL
- **Solutions**:
  1. Increase `STRATEGY_CROSSOVER_THRESHOLD_PIPS` (e.g., 1.0 → 2.0)
  2. Increase `STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS` (e.g., 2.0 → 3.0)
  3. Enable `STRATEGY_DMI_ENABLED=true` for trend confirmation
  4. Enable `STRATEGY_ATR_ENABLED=true` with min threshold to avoid low-volatility periods

### Issue: Whipsaw Losses
- **Symptom**: DIAG-WHIPSAW scenario shows 2 losing trades
- **Solutions**:
  1. Enable Stochastic filter for momentum confirmation
  2. Increase `STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS` (e.g., 5 → 10)
  3. Add time-based confirmation (wait 1-2 bars after crossover before entry)

### Issue: Threshold Boundary Failures
- **Symptom**: DIAG-THRESH-EXACT scenario fails (0 trades instead of 1)
- **Solutions**:
  1. Review code: Verify `>=` comparison in `_check_crossover_threshold()` (line 334)
  2. Check for floating-point precision issues with Decimal comparisons

### Issue: Excessive MA Lag
- **Symptom**: DIAG-LAG scenario shows >5 bar delay from trend start to crossover
- **Solutions**:
  1. Reduce MA periods (e.g., fast=8, slow=15 instead of 10/20)
  2. Consider EMA instead of SMA for faster response
  3. Accept lag as inherent to MA strategies (not a bug)

### Issue: False Breakout Trades
- **Symptom**: DIAG-BREAKOUT scenario shows 1 trade (should be 0 with filters)
- **Solutions**:
  1. Enable ATR filter to detect abnormal volatility spikes
  2. Enable ADX filter to confirm trend strength
  3. Increase pre-crossover separation requirement

## Integration with CI/CD

Add to your CI pipeline:
```yaml
# .github/workflows/diagnostics.yml
name: MA Diagnostics
on:
  schedule:
    - cron: '0 0 * * 0'  # Weekly on Sunday
  workflow_dispatch:

jobs:
  diagnostics:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run MA Diagnostics
        run: python tests/run_ma_diagnostics.py
      - name: Upload Reports
        uses: actions/upload-artifact@v2
        with:
          name: diagnostic-reports
          path: reports/ma_diagnostics/
```

## Maintenance

### Adding New Diagnostic Scenarios
1. Add generator function to `synthetic_data_generator.py`
2. Add scenario to `generate_phase6_diagnostic_data.py`
3. Add `DiagnosticScenario` config to `ma_diagnostics_analyzer.py::DIAGNOSTIC_SCENARIOS_CONFIG`
4. Update this README with scenario description

### Updating Expected Outcomes
If strategy logic changes, update expected outcomes in `DIAGNOSTIC_SCENARIOS_CONFIG`:
```python
DiagnosticScenario(
    name="choppy_market",
    symbol="DIAG-CHOPPY/USD",
    expected_trades=10,  # Update this
    expected_outcome="mixed",
    # ...
)
```

### Regenerating Test Data
```bash
rm -rf data/test_catalog/phase6_diagnostics/
python tests/generate_phase6_diagnostic_data.py
```

## Troubleshooting

### Data Generation Fails
- **Check**: Verify `synthetic_data_generator.py` has all diagnostic generator functions
- **Check**: Ensure catalog directory is writable
- **Debug**: Run with `--verbose` flag for detailed logs

### Backtest Fails
- **Check**: Verify catalog contains data for all scenarios
- **Check**: Review backtest stderr output in diagnostic log
- **Debug**: Run individual backtest manually with scenario-specific .env file

### Analysis Fails
- **Check**: Verify backtest output directories exist and contain required files
- **Check**: Ensure `performance_stats.json` is valid JSON
- **Debug**: Run analyzer standalone on specific output directory

### Report Generation Fails
- **Check**: Verify matplotlib/seaborn are installed
- **Check**: Ensure output directory is writable
- **Debug**: Check for chart generation errors in log

## Next Steps

After reviewing diagnostic results:
1. **Implement suggested parameter changes** in `.env` or `backtest_config.py`
2. **Re-run diagnostics** to verify improvements
3. **Run full backtest** on historical data with updated parameters
4. **Compare performance** before/after using `analysis/compare_backtests.py`
5. **Iterate** based on results

## Related Documentation
- Phase 2: Basic Crossover Tests (`README_PHASE2.md`)
- Phase 3: Filter Tests (`README_PHASE3_CROSSOVER.md`)
- Analysis Tools: `analysis/README.md`
- Strategy Configuration: `config/env_variables.md`
