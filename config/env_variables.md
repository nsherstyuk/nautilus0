# Environment Variables Documentation

This document describes the environment variables used by the NautilusTrader system.

## Backtesting Parameters

### Required Variables
- `BACKTEST_SYMBOL`: Trading symbol (e.g., EUR-USD, AAPL)
- `BACKTEST_START_DATE`: Start date in YYYY-MM-DD format
- `BACKTEST_END_DATE`: End date in YYYY-MM-DD format

### Optional Variables with Defaults
- `BACKTEST_VENUE`: Trading venue (default: SMART)
- `BACKTEST_BAR_SPEC`: Bar specification (default: 1-MINUTE-LAST-EXTERNAL)
- `BACKTEST_FAST_PERIOD`: Fast moving average period (default: 10)
- `BACKTEST_SLOW_PERIOD`: Slow moving average period (default: 20)
- `BACKTEST_TRADE_SIZE`: Trade size in units (default: 100)
- `BACKTEST_STARTING_CAPITAL`: Starting capital (default: 100000.0)
- `CATALOG_PATH`: Path to historical data catalog (default: data/historical)
- `OUTPUT_DIR`: Output directory for results (default: logs/backtest_results)
- `ENFORCE_POSITION_LIMIT`: Enforce position limits (default: true)
- `ALLOW_POSITION_REVERSAL`: Allow position reversal (default: false)
- `BACKTEST_STOP_LOSS_PIPS`: Stop loss distance in pips (default: 25)
- `BACKTEST_TAKE_PROFIT_PIPS`: Take profit distance in pips (default: 50)
- `BACKTEST_TRAILING_STOP_ACTIVATION_PIPS`: Activate trailing stop after this many pips of profit (default: 20)
- `BACKTEST_TRAILING_STOP_DISTANCE_PIPS`: Trail stop loss by this many pips behind current price (default: 15)

## Stop Loss and Take Profit Configuration

The `BACKTEST_STOP_LOSS_PIPS` and `BACKTEST_TAKE_PROFIT_PIPS` variables are specifically designed for forex trading:

- **EUR/USD Example**: 25 pips = 0.0025, 50 pips = 0.0050
- **USD/JPY Example**: 25 pips = 0.25, 50 pips = 0.50

## Trailing Stop Configuration

Trailing stop functionality activates when position profit reaches the activation threshold, then dynamically moves stop loss to lock in profits as price moves favorably.

### Example Configuration
```
# Trailing Stop Configuration
# Trailing stop activates when position profit reaches activation threshold,
# then dynamically moves stop loss to lock in profits as price moves favorably.
# Example: With activation=20 and distance=15:
#   - Position opens at 1.1000
#   - Price moves to 1.1020 (+20 pips) → trailing activates
#   - Stop loss moves to 1.1005 (current price - 15 pips)
#   - Price moves to 1.1030 → stop moves to 1.1015
#   - Stop only moves in favorable direction (never widens)
```

### Parameters
- `BACKTEST_TRAILING_STOP_ACTIVATION_PIPS`: Profit threshold to activate trailing (default: 20 pips)
- `BACKTEST_TRAILING_STOP_DISTANCE_PIPS`: Distance to trail behind current price (default: 15 pips)

### Notes
- For higher timeframes (4H, Daily) users may want larger values (e.g., activation=50, distance=30)
- Trailing only moves in favorable direction (never widens the stop)
- Only applicable to FX instruments with pip-based SL/TP logic

### Example .env Configuration

```bash
# Forex backtesting
BACKTEST_SYMBOL=EUR-USD
BACKTEST_START_DATE=2024-01-01
BACKTEST_END_DATE=2024-12-31
BACKTEST_VENUE=IDEALPRO
BACKTEST_BAR_SPEC=1-MINUTE-MID-EXTERNAL
BACKTEST_STOP_LOSS_PIPS=25     # Stop loss distance in pips (EUR/USD: 25 pips = 0.0025)
BACKTEST_TAKE_PROFIT_PIPS=50   # Take profit distance in pips (EUR/USD: 50 pips = 0.0050)
BACKTEST_TRAILING_STOP_ACTIVATION_PIPS=20  # Activate trailing stop after this many pips of profit (default: 20 pips = $200 profit per standard lot for EUR/USD)
BACKTEST_TRAILING_STOP_DISTANCE_PIPS=15    # Trail stop loss by this many pips behind current price (default: 15 pips = $150 buffer)

# Stock backtesting (SL/TP pips not applicable)
BACKTEST_SYMBOL=AAPL
BACKTEST_VENUE=SMART
BACKTEST_BAR_SPEC=1-MINUTE-LAST-EXTERNAL
# Note: For stocks, use percentage-based or tick-based stops instead of pips

# Crypto backtesting (SL/TP pips not applicable)
BACKTEST_SYMBOL=BTC-USD
BACKTEST_VENUE=COINBASE
BACKTEST_BAR_SPEC=1-MINUTE-LAST-EXTERNAL
# Note: For crypto, use percentage-based or tick-based stops instead of pips
```

## Live Trading Parameters

- `IBKR_HOST`: Interactive Brokers host (default: 127.0.0.1)
- `IBKR_PORT`: Interactive Brokers port (default: 7497)
- `IBKR_CLIENT_ID`: Interactive Brokers client ID (default: 1)
