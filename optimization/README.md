# Grid Search Optimization

This module provides parallelized grid search optimization for NautilusTrader backtest parameter tuning.

## Overview

The grid search optimizer systematically tests different parameter combinations to find optimal strategy configuration. It supports:

- **Parallel execution** with configurable worker count
- **Checkpoint/resume** capability for long-running optimizations
- **Multiple objective functions** (PnL, Sharpe ratio, win rate, etc.)
- **Comprehensive result analysis** with ranking and sensitivity analysis
- **Flexible configuration** via YAML files

## Quick Start

1. **Create a configuration file** (see `grid_config.yaml` for examples):
   ```yaml
   optimization:
     objective: total_pnl
     workers: 8
   
   parameters:
     fast_period:
       values: [20, 40, 60]
     slow_period:
       values: [100, 150, 200]
   ```

2. **Run the optimization**:
   ```bash
   python optimization/grid_search.py --config optimization/grid_config.yaml
   ```

3. **Review results**:
   - CSV file with all results: `grid_search_results.csv`
   - Top 10 parameters: `grid_search_results_top_10.json`
   - Summary statistics: `grid_search_results_summary.json`

## Configuration

### Optimization Settings

```yaml
optimization:
  objective: total_pnl          # Metric to maximize
  workers: 8                    # Parallel workers
  checkpoint_interval: 10       # Save progress every N runs
  timeout_seconds: 300         # Max time per backtest
```

### Parameter Ranges

```yaml
parameters:
  fast_period:
    values: [20, 40, 60, 80, 100]
  slow_period:
    values: [100, 150, 200, 250, 300]
  crossover_threshold_pips:
    values: [0.0, 0.5, 1.0, 1.5, 2.0]
  stop_loss_pips:
    values: [15, 20, 25, 30, 40]
  take_profit_pips:
    values: [30, 40, 50, 75, 100]
```

### Fixed Parameters

```yaml
fixed:
  dmi_enabled: true
  stoch_enabled: true
  trade_size: 100000
```

## Usage Examples

### Basic Grid Search
```bash
python optimization/grid_search.py --config optimization/grid_config.yaml
```

### Custom Workers and Objective
```bash
python optimization/grid_search.py \
  --config optimization/grid_config.yaml \
  --workers 4 \
  --objective sharpe_ratio
```

### Resume from Checkpoint
```bash
python optimization/grid_search.py \
  --config optimization/grid_config.yaml \
  --resume
```

### Start Fresh (Ignore Checkpoint)
```bash
python optimization/grid_search.py \
  --config optimization/grid_config.yaml \
  --no-resume
```

## Best Practices

### 1. Coarse-to-Fine Approach
- **Step 1**: Run coarse grid (3-5 values per parameter, 100-500 combinations)
- **Step 2**: Zoom into best region with fine grid (5-7 values, 100-300 combinations)

### 2. Sequential Optimization
- **Phase 1**: Optimize MA periods (fast, slow)
- **Phase 2**: Optimize risk management (SL, TP)
- **Phase 3**: Optimize filters (DMI, Stochastic)

### 3. Resource Management
- Use 50-75% of CPU cores for workers
- Monitor memory usage for large grids
- Use checkpoints for long-running optimizations

### 4. Result Validation
- Run walk-forward validation on top parameters
- Check parameter sensitivity analysis
- Avoid overfitting to specific market conditions

## Output Files

### CSV Results (`grid_search_results.csv`)
Contains all backtest results with parameters and metrics:
- Parameter values for each combination
- Performance metrics (PnL, Sharpe, win rate, etc.)
- Status and error messages
- Execution timing

### Top 10 Parameters (`grid_search_results_top_10.json`)
JSON file with top 10 parameter sets for further validation:
```json
[
  {
    "rank": 1,
    "run_id": 42,
    "parameters": {
      "fast_period": 40,
      "slow_period": 200,
      "crossover_threshold_pips": 1.0
    },
    "objective_value": 12500.0
  }
]
```

### Summary Statistics (`grid_search_results_summary.json`)
Aggregate statistics across all runs:
- Best and worst results
- Average metrics
- Parameter sensitivity analysis
- Success rates

## Performance Expectations

| Grid Size | Workers | Runtime | Memory |
|-----------|---------|---------|--------|
| 100 combinations | 8 | ~30 minutes | ~2GB |
| 1,000 combinations | 8 | ~3 hours | ~4GB |
| 10,000 combinations | 8 | ~30 hours | ~8GB |

## Troubleshooting

### Common Issues

1. **"No valid parameter combinations"**
   - Check parameter relationships (fast < slow, tp > sl)
   - Verify YAML syntax

2. **"Missing environment variables"**
   - Ensure `.env` file is configured
   - Check required variables: `BACKTEST_SYMBOL`, `BACKTEST_START_DATE`, `BACKTEST_END_DATE`

3. **"All backtests failed"**
   - Check data availability in catalog
   - Verify backtest configuration
   - Review error messages in results

4. **Memory issues with large grids**
   - Reduce worker count
   - Use sequential optimization approach
   - Increase checkpoint frequency

### Debug Mode
```bash
python optimization/grid_search.py \
  --config optimization/grid_config.yaml \
  --verbose
```

## Advanced Usage

### Custom Output Location
```bash
python optimization/grid_search.py \
  --config optimization/grid_config.yaml \
  --output optimization/results/my_optimization.csv
```

### Override Configuration
```bash
python optimization/grid_search.py \
  --config optimization/grid_config.yaml \
  --workers 4 \
  --objective sharpe_ratio
```

## Integration with Walk-Forward Validation

After finding optimal parameters, validate them with walk-forward testing:

```bash
python optimization/walk_forward.py \
  --params optimization/results/grid_search_results_top_10.json \
  --periods 12 \
  --retrain_interval 3
```

This prevents overfitting and ensures robustness across different market conditions.
