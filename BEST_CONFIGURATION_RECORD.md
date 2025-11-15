# Best Configuration Record - 14k PnL Achievement

## Summary
This document records the optimal configuration that achieved **$14,203.91 PnL** with **60% win rate** and **85 trades**.

**Source:** `optimization/results/multi_tf_combined_results_summary.json` (run_id: 28)

## Performance Metrics
- **Total PnL:** $14,203.91
- **Sharpe Ratio:** 0.453
- **Win Rate:** 60%
- **Trade Count:** 85
- **Max Drawdown:** 0.0

## Complete Configuration

### Basic Parameters
```
BACKTEST_SYMBOL=EUR-USD
BACKTEST_START_DATE=2024-01-01
BACKTEST_END_DATE=2024-12-31
BACKTEST_VENUE=IDEALPRO
BACKTEST_BAR_SPEC=1-MINUTE-MID-EXTERNAL
BACKTEST_FAST_PERIOD=42
BACKTEST_SLOW_PERIOD=270
BACKTEST_TRADE_SIZE=100
BACKTEST_STARTING_CAPITAL=100000.0
```

### Risk Management
```
BACKTEST_STOP_LOSS_PIPS=35
BACKTEST_TAKE_PROFIT_PIPS=50
BACKTEST_TRAILING_STOP_ACTIVATION_PIPS=22
BACKTEST_TRAILING_STOP_DISTANCE_PIPS=12
```

### Strategy Filters
```
# Crossover threshold
STRATEGY_CROSSOVER_THRESHOLD_PIPS=0.35

# DMI Filter (ENABLED)
STRATEGY_DMI_ENABLED=true
STRATEGY_DMI_BAR_SPEC=2-MINUTE-MID-EXTERNAL
STRATEGY_DMI_PERIOD=10

# Stochastic Filter (ENABLED)
STRATEGY_STOCH_ENABLED=true
STRATEGY_STOCH_BAR_SPEC=15-MINUTE-MID-EXTERNAL
STRATEGY_STOCH_PERIOD_K=18
STRATEGY_STOCH_PERIOD_D=3
STRATEGY_STOCH_BULLISH_THRESHOLD=30
STRATEGY_STOCH_BEARISH_THRESHOLD=65

# Trend Filter (DISABLED)
STRATEGY_TREND_FILTER_ENABLED=false

# Entry Timing (DISABLED)
STRATEGY_ENTRY_TIMING_ENABLED=false

# Other Filters (DISABLED)
STRATEGY_RSI_ENABLED=false
STRATEGY_VOLUME_ENABLED=false
STRATEGY_ATR_ENABLED=false
```

### Market Regime Detection
```
STRATEGY_REGIME_DETECTION_ENABLED=false
```
**Note:** Regime detection was NOT used in the best result.

### Time Filter
```
BACKTEST_TIME_FILTER_ENABLED=false
BACKTEST_EXCLUDED_HOURS=1,2,12,18,21,23
```
**Note:** Time filter was NOT used in the optimization, but these hours are recommended for exclusion based on analysis.

## Key Insights

### What Made This Configuration Successful

1. **Long Slow MA Period (270)**: Captures longer-term trends
2. **Moderate Fast MA Period (42)**: Balances responsiveness vs noise
3. **Tight Crossover Threshold (0.35 pips)**: Filters out micro-movements
4. **Wider Stop Loss (35 pips)**: Gives trades more room vs default 25 pips
5. **Standard Take Profit (50 pips)**: Balanced risk/reward (1.43:1 ratio)
6. **Early Trailing Activation (22 pips)**: Locks in profits sooner
7. **Tight Trailing Distance (12 pips)**: Keeps stops close to price
8. **DMI Enabled**: Confirms trend direction
9. **Stochastic Enabled**: Prevents buying tops/selling bottoms
10. **Custom Stochastic Settings**: K=18, D=3, thresholds 30/65 (more aggressive than default)

### What Was Disabled

- **Trend Filter**: Not needed when DMI already confirms trend
- **Entry Timing**: Simple crossover entry was sufficient
- **RSI/Volume/ATR Filters**: Additional filters didn't improve results
- **Regime Detection**: Not tested in this optimization

## Comparison to Defaults

| Parameter | Default | Best | Change |
|-----------|---------|------|--------|
| Fast Period | 10 | 42 | +320% |
| Slow Period | 20 | 270 | +1250% |
| Stop Loss | 25 | 35 | +40% |
| Take Profit | 50 | 50 | Same |
| Trailing Activation | 20 | 22 | +10% |
| Trailing Distance | 15 | 12 | -20% |
| Crossover Threshold | 0.7 | 0.35 | -50% |
| DMI Period | 14 | 10 | -29% |
| Stoch Period K | 14 | 18 | +29% |
| Stoch Thresholds | 30/70 | 30/65 | Bearish tighter |

## How to Recreate This Configuration

1. **Run the reconstruction script:**
   ```bash
   python reconstruct_best_env.py
   ```

2. **Copy the generated file:**
   ```bash
   copy .env.best .env
   ```

3. **Verify settings match the above configuration**

4. **Run backtest:**
   ```bash
   python -m backtest.run_backtest
   ```

## Optimization Context

This configuration was found through a **multi-timeframe optimization** that tested:
- 48 different parameter combinations
- Various MA periods, TP/SL values, trailing stop settings
- Different filter combinations (DMI, Stochastic, Trend, Entry Timing)
- Multiple timeframes

**Best Result:** Run ID 28 achieved the highest Sharpe ratio (0.453) and highest PnL ($14,203.91).

## Next Steps for Further Optimization

1. **Test with Time Filter Enabled**: Exclude hours 1,2,12,18,21,23 to see if PnL improves
2. **Test Regime Detection**: Enable regime detection to see if it improves results
3. **Fine-tune Around Best**: Test small variations (±5-10%) around these parameters
4. **Walk-Forward Testing**: Validate on out-of-sample data
5. **Different Date Ranges**: Test on different market conditions

## Files Reference

- **Optimization Results:** `optimization/results/multi_tf_combined_results_summary.json`
- **Reconstruction Script:** `reconstruct_best_env.py`
- **This Document:** `BEST_CONFIGURATION_RECORD.md`

