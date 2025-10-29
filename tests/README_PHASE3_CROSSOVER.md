# Phase 3.1-3.2: Crossover Filter Tests

## Overview
Phase 3.1-3.2 tests the crossover threshold and pre-crossover separation filters in isolation. These filters control signal quality by ensuring crossovers are significant (threshold) and preceded by sufficient MA separation (pre-crossover separation).

## Test Scenarios

### Phase 3.1: Crossover Threshold Filter

#### 1. Threshold Fail (TEST-THRESH-FAIL/USD)
- **Expected Outcome**: 0 trades, 1 rejection
- **Data Pattern**: Bullish crossover with 0.5 pip separation (below 1.0 pip threshold)
- **Filter Config**: `STRATEGY_CROSSOVER_THRESHOLD_PIPS=1.0`
- **Expected Rejection**: `"crossover_threshold_not_met (diff=0.50 pips < 1.0 pips threshold)"`
- **Purpose**: Verify strategy rejects crossovers with insufficient separation

#### 2. Threshold Pass (TEST-THRESH-PASS/USD)
- **Expected Outcome**: 1 BUY trade, 0 rejections
- **Data Pattern**: Bullish crossover with 1.5 pip separation (above 1.0 pip threshold)
- **Filter Config**: `STRATEGY_CROSSOVER_THRESHOLD_PIPS=1.0`
- **Purpose**: Verify strategy accepts crossovers with sufficient separation

### Phase 3.2: Pre-Crossover Separation Filter

#### 3. Separation Once (TEST-SEP-ONCE/USD)
- **Expected Outcome**: 1 BUY trade, 0 rejections
- **Data Pattern**: MAs separated by 2.5 pips at bar N-3 (within 5-bar lookback)
- **Filter Config**: `STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS=2.0`, `STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS=5`
- **Purpose**: Verify strategy accepts crossovers when separation threshold was met at ANY point in lookback window

#### 4. Separation Never (TEST-SEP-NEVER/USD)
- **Expected Outcome**: 0 trades, 1 rejection
- **Data Pattern**: MAs never separated by 2.0 pips in 5-bar lookback (max 1.5 pips)
- **Filter Config**: `STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS=2.0`, `STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS=5`
- **Expected Rejection**: `"pre_crossover_separation_insufficient (max separation=1.50 pips < 2.0 pips threshold in 5 bars)"`
- **Purpose**: Verify strategy rejects crossovers when separation threshold was never met in lookback window

#### 5. Separation Recent (TEST-SEP-RECENT/USD)
- **Expected Outcome**: 1 BUY trade, 0 rejections
- **Data Pattern**: MAs separated by 2.5 pips at bar N-1 (immediate previous bar)
- **Filter Config**: `STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS=2.0`, `STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS=5`
- **Purpose**: Verify strategy accepts crossovers when separation threshold was met at most recent bar

## Prerequisites

### 1. Generate Test Data
```bash
python tests/generate_phase3_crossover_data.py
```
This creates synthetic bar data for all 5 scenarios and writes to `data/test_catalog/phase3_crossover_filters/`.

### 2. Verify Data Generation
```bash
ls -la data/test_catalog/phase3_crossover_filters/data/bar/
```
You should see 5 subdirectories for each test symbol.

## Running Tests

### Run All Phase 3.1-3.2 Tests
```bash
pytest tests/test_crossover_filters.py -v
```

### Run Individual Filter Tests
```bash
# Crossover threshold tests only
pytest tests/test_crossover_filters.py::test_crossover_filter_scenarios[threshold_fail] -v
pytest tests/test_crossover_filters.py::test_crossover_filter_scenarios[threshold_pass] -v

# Pre-crossover separation tests only
pytest tests/test_crossover_filters.py::test_crossover_filter_scenarios[separation_once] -v
pytest tests/test_crossover_filters.py::test_crossover_filter_scenarios[separation_never] -v
pytest tests/test_crossover_filters.py::test_crossover_filter_scenarios[separation_recent] -v
```

### Run with Detailed Output
```bash
pytest tests/test_crossover_filters.py -v -s
```

## Expected Results

All 5 tests should PASS:
- ✅ `test_crossover_filter_scenarios[threshold_fail]` - 0 trades, rejection logged
- ✅ `test_crossover_filter_scenarios[threshold_pass]` - 1 trade, no rejection
- ✅ `test_crossover_filter_scenarios[separation_once]` - 1 trade, no rejection
- ✅ `test_crossover_filter_scenarios[separation_never]` - 0 trades, rejection logged
- ✅ `test_crossover_filter_scenarios[separation_recent]` - 1 trade, no rejection

## Troubleshooting

### Test Fails: "Expected rejection reason not found"
- **Check**: Review `rejected_signals.csv` in output directory
- **Check**: Verify rejection reason format matches expected substring
- **Debug**: Look at actual rejection message in CSV and compare with expected pattern
- **Common Issue**: Rejection reason format changed in strategy code

### Test Fails: "Expected X trades, got Y"
- **Check**: Review `performance_stats.json` for actual trade count
- **Check**: Review `rejected_signals.csv` to see if signal was unexpectedly rejected
- **Debug**: Verify filter configuration in .env file matches test expectations
- **Common Issue**: Wrong filter enabled/disabled or threshold value incorrect

### Data Generation Fails
- **Check**: Verify `synthetic_data_generator.py` has required functions
- **Check**: Verify `generate_with_insufficient_separation()` function exists and works correctly
- **Debug**: Run generator script with verbose logging

## Output Files

Each test generates output in `logs/test_results/phase3_crossover_filters/<filter_type>/<timestamp>/`:
- `performance_stats.json` - Trade statistics
- `orders.csv` - All orders generated
- `fills.csv` - All order fills
- `positions.csv` - Position history
- `rejected_signals.csv` - **NEW**: Rejected signals with reasons (key file for Phase 3 verification)
- `equity_curve.png` - Equity curve visualization

## Configuration Details

### Crossover Threshold Tests
- **Enabled**: `STRATEGY_CROSSOVER_THRESHOLD_PIPS=1.0`
- **Disabled**: `STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS=0.0`
- **All other filters**: Disabled (DMI, Stochastic, ATR, ADX, time, circuit breaker)

### Pre-Crossover Separation Tests
- **Enabled**: `STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS=2.0`, `STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS=5`
- **Disabled**: `STRATEGY_CROSSOVER_THRESHOLD_PIPS=0.0`
- **All other filters**: Disabled

## Key Differences from Phase 2

1. **Rejection Verification**: Phase 3 tests verify rejection reasons in `rejected_signals.csv`, not just trade counts
2. **Filter Isolation**: Each test enables only one filter type to isolate behavior
3. **Multiple Scenarios per Filter**: Tests both passing and failing cases for each filter
4. **Symbol Override**: Test runner overrides `BACKTEST_SYMBOL` to run multiple scenarios with same .env file

## Understanding Rejection Messages

### Crossover Threshold Rejection
```
crossover_threshold_not_met (diff=0.50 pips < 1.0 pips threshold)
```
- **Meaning**: Fast and Slow MA separation at crossover (0.50 pips) is below configured threshold (1.0 pips)
- **Fix**: Increase separation in data or decrease threshold in config

### Pre-Crossover Separation Rejection
```
pre_crossover_separation_insufficient (max separation=1.50 pips < 2.0 pips threshold in 5 bars)
```
- **Meaning**: Maximum MA separation in the 5 bars before crossover (1.50 pips) never reached configured threshold (2.0 pips)
- **Fix**: Increase separation in data, decrease threshold, or reduce lookback bars

## Next Steps

After Phase 3.1-3.2 passes:
1. **Phase 3.3-3.4**: Test DMI and Stochastic momentum filters
2. **Phase 3.5-3.7**: Test time-of-day, ATR, and ADX filters
3. **Phase 4**: Test circuit breaker and combined filter scenarios
4. **Phase 5**: Test edge cases and create automated test runner

## Maintenance

### Regenerating Test Data
```bash
rm -rf data/test_catalog/phase3_crossover_filters/
python tests/generate_phase3_crossover_data.py
```

### Updating Test Expectations
If filter logic changes, update:
1. Expected rejection reason substrings in `TEST_SCENARIOS` configuration
2. Expected trade counts if filter behavior changes
3. This README with new rejection message formats
