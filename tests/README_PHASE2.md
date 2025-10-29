# Phase 2: Basic MA Crossover Tests

## Overview
Phase 2 tests the fundamental MA crossover detection logic without any filters enabled. This establishes a baseline to verify the strategy correctly identifies crossovers before testing individual filters in subsequent phases.

## Test Scenarios

### 1. Simple Bullish Crossover (TEST-BULL/USD)
- **Expected Outcome**: 1 BUY trade
- **Data Pattern**: Fast MA crosses above Slow MA at bar 100 of 200
- **Separation**: 20 pips before and after crossover (well above any threshold)
- **Purpose**: Verify strategy detects bullish crossovers and opens BUY positions

### 2. Simple Bearish Crossover (TEST-BEAR/USD)
- **Expected Outcome**: 1 SELL trade
- **Data Pattern**: Fast MA crosses below Slow MA at bar 100 of 200
- **Separation**: 20 pips before and after crossover
- **Purpose**: Verify strategy detects bearish crossovers and opens SELL positions

### 3. Multiple Alternating Crossovers (TEST-MULTI/USD)
- **Expected Outcome**: 5 trades (alternating BUY/SELL)
- **Data Pattern**: 5 crossovers with 30-bar spacing between each
- **Purpose**: Verify strategy handles multiple consecutive crossovers and position reversals

### 4. No Crossover (TEST-NONE/USD)
- **Expected Outcome**: 0 trades
- **Data Pattern**: Parallel MAs that never cross (constant separation)
- **Purpose**: Verify strategy does not generate false signals when no crossover occurs

## Prerequisites

### 1. Generate Test Data
```bash
python tests/generate_phase2_data.py
```
This creates synthetic bar data for all 4 scenarios and writes to `data/test_catalog/phase2_basic/`.

### 2. Verify Data Generation
Check that the catalog directory exists and contains data:
```bash
ls -la data/test_catalog/phase2_basic/data/bar/
```
You should see 4 subdirectories: `TEST-BULL-USD.IDEALPRO/`, `TEST-BEAR-USD.IDEALPRO/`, `TEST-MULTI-USD.IDEALPRO/`, `TEST-NONE-USD.IDEALPRO/`.

## Running Tests

### Run All Phase 2 Tests
```bash
pytest tests/test_basic_crossovers.py -v
```

### Run Individual Test
```bash
pytest tests/test_basic_crossovers.py::test_basic_crossover_scenarios[simple_bullish] -v
```

### Run with Detailed Output
```bash
pytest tests/test_basic_crossovers.py -v -s
```

## Expected Results

All 4 tests should PASS:
- ✅ `test_basic_crossover_scenarios[simple_bullish]` - 1 BUY trade
- ✅ `test_basic_crossover_scenarios[simple_bearish]` - 1 SELL trade
- ✅ `test_basic_crossover_scenarios[multiple_crossovers]` - 5 trades
- ✅ `test_basic_crossover_scenarios[no_crossover]` - 0 trades

## Troubleshooting

### Test Fails: "Catalog does not exist"
- **Solution**: Run `python tests/generate_phase2_data.py` to generate test data

### Test Fails: "Expected X trades, got Y"
- **Check**: Review backtest output in `logs/test_results/phase2_basic/<scenario>/`
- **Check**: Verify `performance_stats.json` for actual trade count
- **Check**: Review `rejected_signals.csv` to see if signals were rejected (should be empty in Phase 2)
- **Debug**: Inspect `orders.csv` and `fills.csv` for trade details

### Test Fails: "Backtest script failed"
- **Check**: Review stderr output in test failure message
- **Check**: Verify .env file exists in `tests/env_configs/`
- **Check**: Verify all required parameters are set in .env file
- **Debug**: Run backtest manually: `cp tests/env_configs/.env.test_simple_bullish .env && python backtest/run_backtest.py`

### Data Generation Fails
- **Check**: Verify `synthetic_data_generator.py` is present and functional
- **Check**: Ensure `data/test_catalog/phase2_basic/` directory can be created (permissions)
- **Debug**: Run with verbose logging: `python tests/generate_phase2_data.py` and review output

## Output Files

Each test generates output in `logs/test_results/phase2_basic/<scenario>/<timestamp>/`:
- `performance_stats.json` - Trade statistics and performance metrics
- `orders.csv` - All orders generated
- `fills.csv` - All order fills
- `positions.csv` - Position history
- `account.csv` - Account balance history
- `rejected_signals.csv` - Rejected signals (should be empty in Phase 2)
- `equity_curve.png` - Equity curve visualization

## Configuration Details

### Common Settings (All Tests)
- **MA Periods**: Fast=10, Slow=20
- **Bar Spec**: 1-MINUTE-MID-EXTERNAL
- **Trade Size**: 100,000 units (1 standard lot)
- **Starting Capital**: $100,000
- **Position Limit**: Enabled (max 1 position)
- **Position Reversal**: Disabled
- **All Filters**: Disabled (crossover threshold, pre-crossover separation, DMI, Stochastic, ATR, ADX, time filter, circuit breaker)

### Why All Filters Are Disabled
Phase 2 tests the **core crossover detection logic** in isolation. Filters are tested individually in Phase 3 and combined in Phase 4. This approach ensures:
1. Baseline functionality is verified first
2. Filter-related failures don't mask core logic issues
3. Each filter can be tested independently in subsequent phases

## Next Steps

After Phase 2 passes:
1. **Phase 3.1-3.2**: Test crossover threshold and pre-crossover separation filters
2. **Phase 3.3-3.4**: Test DMI and Stochastic momentum filters
3. **Phase 3.5-3.7**: Test time-of-day, ATR, and ADX filters
4. **Phase 4**: Test circuit breaker and combined filter scenarios
5. **Phase 5**: Test edge cases and create automated test runner

## Maintenance

### Regenerating Test Data
If synthetic data generation logic changes, regenerate test data:
```bash
rm -rf data/test_catalog/phase2_basic/
python tests/generate_phase2_data.py
```

### Updating Test Expectations
If strategy logic changes (e.g., MA calculation method), update expected trade counts in `TEST_SCENARIOS` configuration in `test_basic_crossovers.py`.

### Adding New Scenarios
1. Add generator function to `generate_phase2_data.py`
2. Create corresponding .env file in `tests/env_configs/`
3. Add scenario to `TEST_SCENARIOS` list in `test_basic_crossovers.py`
4. Update this README with new scenario details
