# Analysis Report

## 1. Logging Fix
The logging mechanism in `strategies/moving_average_crossover.py` has been fixed to correctly handle position quantity during trade exit.
- **Issue**: `position.quantity` was returning 0.0 after the position was closed, leading to `NaN` values for `pnl_pips` and other metrics.
- **Fix**: The trade quantity is now captured at entry and stored in `_trade_features`. The exit logging logic retrieves this stored quantity to calculate PnL correctly.

## 2. Data Quality Verification
- The `trade_features.csv` file now contains valid numerical data for `pnl_pips`.
- `NaN` values have been eliminated from the critical columns used for analysis.

## 3. Statistical Analysis Results
The analysis script `analyze_trade_features_simple.py` was executed on the backtest data.
- **Method**: T-tests were performed to compare the distributions of various features between winning and losing trades.
- **Significance Level**: Alpha = 0.01.
- **Results**:
  - No features showed a statistically significant difference between winning and losing trades (all p-values > 0.01).
  - Features analyzed included: `hour_utc`, `fast_slow_sep_pips`, `adx_value`, `rsi_value`, `atr_value`, `volume_ma_ratio`.

## 4. Configuration Observations
- The current configuration in `.env` has most advanced filters disabled:
  - `STRATEGY_REGIME_DETECTION_ENABLED=false`
  - `STRATEGY_TREND_FILTER_ENABLED=false`
  - `STRATEGY_RSI_ENABLED=false`
  - `STRATEGY_DMI_ENABLED` (likely false/default)
- This explains why features like `adx_value` or `rsi_value` might not be showing significant predictive power—they are not being used to filter trades, so their distribution might be random with respect to PnL in this specific backtest period.

## 5. Recommendations
- **Enable Filters**: To find significant factors, consider enabling specific filters in `.env` (e.g., `STRATEGY_RSI_ENABLED=true`) and re-running the backtest.
- **Expand Analysis**: If filters are enabled, the analysis script can be used to verify if the filtered trades perform significantly better.
