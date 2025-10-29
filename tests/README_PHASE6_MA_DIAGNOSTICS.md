# Phase 6: MA Crossover Detection Diagnostics

Phase 6 MA Diagnostics provides automated verification of MA crossover detection accuracy. Unlike the general Phase 6 diagnostics (edge cases), this focused system verifies that every expected MA crossover is correctly detected and generates a trade, with detailed crossover-by-crossover reporting.

## Key Capabilities

- **Metadata-Driven Testing**: Synthetic data includes metadata documenting expected crossover timestamps and MA values
- **Crossover-Level Verification**: Compares actual trades against expected crossovers with ✅/❌ status for each
- **Algorithm Issue Detection**: Identifies off-by-one errors, timing errors, MA calculation errors, warmup issues
- **Detailed Reporting**: Shows each expected crossover with detection status, timing error, and root cause analysis
- **Isolated Testing**: All filters disabled to test pure MA crossing logic

## Test Scenarios

### 1. Single Crossover (TEST-MA-SINGLE/USD)
- **Purpose**: Baseline verification of single bullish crossover detection
- **Pattern**: 1 bullish crossover at bar 100 of 200
- **Expected**: 1 BUY trade at bar 100
- **Metadata**: Documents expected crossover at bar 100 with fast/slow MA values
- **Detects**: Basic crossover detection failures, warmup issues

### 2. Multiple Crossovers (TEST-MA-MULTI/USD)
- **Purpose**: Verify detection of multiple alternating crossovers
- **Pattern**: 5 crossovers (bullish, bearish, bullish, bearish, bullish) with 30-bar spacing
- **Expected**: 5 trades at bars 100, 130, 160, 190, 220
- **Metadata**: Documents all 5 expected crossovers with timestamps
- **Detects**: Missed crossovers, false positives, systematic detection issues

### 3. Edge Case (TEST-MA-EDGE/USD)
- **Purpose**: Test boundary condition with crossover at exact MA equality
- **Pattern**: 1 bullish crossover with minimal post-crossover separation (0.1 pip)
- **Expected**: 1 BUY trade
- **Metadata**: Documents crossover with near-equal MA values
- **Detects**: Boundary condition failures, comparison operator issues (>= vs >)

### 4. Delayed Crossover (TEST-MA-DELAYED/USD)
- **Purpose**: Verify timing accuracy with slow MA convergence
- **Pattern**: MAs converge gradually over 20 bars before crossing at bar 100
- **Expected**: 1 BUY trade at bar 100 (not earlier)
- **Metadata**: Documents expected crossover timing
- **Detects**: Premature detection, timing errors, off-by-one errors

## Metadata Format

Each scenario has a metadata JSON file stored in `data/test_catalog/phase6_ma_diagnostics/metadata/`:

```json
{
  "scenario_name": "TEST-MA-SINGLE/USD",
  "fast_period": 10,
  "slow_period": 20,
  "total_bars": 200,
  "expected_crossovers": [
    {
      "bar_index": 100,
      "timestamp": "2024-01-01T01:40:00Z",
      "type": "bullish",
      "fast_ma": 1.08015,
      "slow_ma": 1.07985
    }
  ]
}
```

## Usage

### Quick Start
```bash
python tests/run_ma_diagnostics.py
```

### Step-by-Step

**Step 1: Generate Test Data with Metadata**
```bash
python tests/generate_phase6_ma_diagnostic_data.py
```
Creates:
- Bar data in `data/test_catalog/phase6_ma_diagnostics/data/bar/`
- Metadata JSON files in `data/test_catalog/phase6_ma_diagnostics/metadata/`

**Step 2: Run Diagnostics**
```bash
python tests/run_ma_diagnostics.py --skip-data-gen
```

**Step 3: Review Reports**
- HTML report: `reports/ma_diagnostics/ma_diagnostics_{timestamp}.html`
- JSON report: `reports/ma_diagnostics/ma_diagnostics_{timestamp}.json`

## Output Files

### Reports
- **HTML Report**: Includes crossover-level verification table showing ✅/❌ for each expected crossover
- **JSON Report**: Machine-readable format with crossover_verifications array
- **Console Output**: Summary with crossover detection statistics

### Backtest Results
- `logs/test_results/phase6_ma_diagnostics/{scenario}/`
  - `performance_stats.json`
  - `orders.csv` - Used to match against expected crossovers
  - `rejected_signals.csv` - Should be empty (all filters disabled)

## Interpreting Results

### Crossover Status
- **✅ Detected**: Trade executed at expected bar (±1 bar tolerance)
- **❌ Missed**: No trade for expected crossover
- **⚠️ Timing Error**: Trade executed but >1 bar late/early
- **🔶 False Positive**: Trade without corresponding expected crossover

### Common Issues

#### Missed Crossovers
- **Symptom**: Expected crossover has ❌ status
- **Possible Causes**:
  - Warmup period: Crossover occurs before slow MA is fully initialized
  - MA calculation error: Strategy computes different MA values than expected
  - Crossover detection logic error: Strategy doesn't detect the crossover
- **Debug**: Check `rejected_signals.csv` for rejection reasons (should be empty)

#### Timing Errors
- **Symptom**: Trade executed 2+ bars late or early
- **Possible Causes**:
  - Off-by-one error: Using wrong bar index for comparison
  - MA history buffer issue: Values stored/retrieved incorrectly
  - Timestamp calculation error: Bar timestamps don't match expected
- **Debug**: Compare actual MA values at trade bar vs expected MA values from metadata

#### False Positives
- **Symptom**: Trade without corresponding expected crossover
- **Possible Causes**:
  - Incorrect crossover detection: Strategy detects crossover when MAs didn't actually cross
  - MA calculation error: Strategy computes wrong MA values
- **Debug**: Review strategy logs for MA values at false positive bar

## Algorithm Issue Detection

The analyzer automatically detects:

### Off-by-One Errors
- **Detection**: Consistent ±1 bar timing errors across scenarios
- **Suggestion**: "Review crossover detection logic in on_bar() - check if using current or previous bar values"
- **Priority**: HIGH (this is a bug)

### Warmup Issues
- **Detection**: Missed crossovers in first `slow_period` bars
- **Suggestion**: "Ensure strategy waits for slow_period bars before detecting crossovers"
- **Priority**: HIGH

### MA Calculation Errors
- **Detection**: Detected crossovers at wrong bars (>2 bar error) or false positives
- **Suggestion**: "Verify SMA calculation logic - compare against expected MA values from metadata"
- **Priority**: HIGH

### Buffer Issues
- **Detection**: Systematic misses or timing errors
- **Suggestion**: "Review MA history buffer implementation - ensure values are stored correctly"
- **Priority**: HIGH

## Troubleshooting

### No Metadata Found
- **Check**: Verify `data/test_catalog/phase6_ma_diagnostics/metadata/` contains JSON files
- **Fix**: Re-run `python tests/generate_phase6_ma_diagnostic_data.py`

### All Crossovers Missed
- **Check**: Verify filters are disabled in `.env.test_ma_diagnostics`
- **Check**: Review `rejected_signals.csv` for unexpected rejections
- **Debug**: Run backtest manually with verbose logging

### Timing Errors
- **Check**: Verify bar timestamps in generated data match expected (1-minute intervals)
- **Check**: Compare order timestamps in `orders.csv` against metadata timestamps
- **Debug**: Add logging to strategy to print MA values at each bar

## Next Steps

After Phase 6 MA diagnostics pass:
1. Proceed to Phase 3.3-3.4 (DMI and Stochastic filter tests)
2. Continue with remaining filter tests (Phases 3.5-3.7)
3. Test combined filters (Phase 4)
4. Test edge cases (Phase 5)

## Related Documentation
- Phase 2: Basic Crossover Tests (`README_PHASE2.md`)
- Phase 3: Filter Tests (`README_PHASE3_CROSSOVER.md`)
- General Phase 6 Diagnostics (`README_PHASE6_DIAGNOSTICS.md`) - Edge case testing
- Strategy Implementation: `strategies/moving_average_crossover.py`

