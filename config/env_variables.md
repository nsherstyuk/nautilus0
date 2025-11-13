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

### Adaptive Stop Loss / Take Profit Configuration (New)

The strategy now supports adaptive stops that automatically adjust to market volatility using ATR (Average True Range):

- `BACKTEST_ADAPTIVE_STOP_MODE`: Mode for adaptive stops - `'fixed'` (use static pips), `'atr'` (ATR-based), or `'percentile'` (ATR with volatility regime scaling). Default: `'atr'`
- `BACKTEST_ATR_PERIOD`: Period for ATR calculation (default: 14)
- `BACKTEST_TP_ATR_MULT`: Take-profit distance as multiple of ATR (default: 2.5 - meaning TP = 2.5 × ATR)
- `BACKTEST_SL_ATR_MULT`: Stop-loss distance as multiple of ATR (default: 1.5 - meaning SL = 1.5 × ATR)
- `BACKTEST_TRAIL_ACTIVATION_ATR_MULT`: Trailing stop activation distance as multiple of ATR (default: 1.0)
- `BACKTEST_TRAIL_DISTANCE_ATR_MULT`: Trailing stop distance as multiple of ATR (default: 0.8)
- `BACKTEST_VOLATILITY_WINDOW`: Number of bars for volatility percentile calculation (default: 200, used in 'percentile' mode)
- `BACKTEST_VOLATILITY_SENSITIVITY`: Sensitivity of volatility scaling (default: 0.6, range 0.0-1.0, used in 'percentile' mode)
- `BACKTEST_MIN_STOP_DISTANCE_PIPS`: Minimum stop distance in pips to avoid spread/noise (default: 5.0)

**How Adaptive Stops Work:**

1. **`fixed` mode**: Uses static pip values from `BACKTEST_STOP_LOSS_PIPS`, `BACKTEST_TAKE_PROFIT_PIPS`, etc.

2. **`atr` mode**: Dynamically calculates stop/target distances based on current market volatility (ATR):
   - If ATR = 10 pips and `SL_ATR_MULT=1.5`, then SL = 15 pips
   - If ATR increases to 20 pips, SL automatically widens to 30 pips
   - Adapts to volatile vs quiet markets automatically

3. **`percentile` mode**: Like `atr` mode, but also scales based on volatility regime:
   - Computes ATR percentile rank over last `VOLATILITY_WINDOW` bars
   - When ATR is in top percentiles (high volatility), distances scale up
   - When ATR is in bottom percentiles (low volatility), distances scale down
   - Prevents overly tight stops in volatile periods and overly wide stops in quiet periods

**Example Configuration:**
```bash
# Enable ATR-based adaptive stops
BACKTEST_ADAPTIVE_STOP_MODE=atr
BACKTEST_ATR_PERIOD=14
BACKTEST_SL_ATR_MULT=1.5    # SL = 1.5 × ATR
BACKTEST_TP_ATR_MULT=2.5    # TP = 2.5 × ATR
BACKTEST_TRAIL_ACTIVATION_ATR_MULT=1.0   # Activate trailing at 1 × ATR profit
BACKTEST_TRAIL_DISTANCE_ATR_MULT=0.8     # Trail 0.8 × ATR behind price
BACKTEST_MIN_STOP_DISTANCE_PIPS=5.0      # Never tighter than 5 pips

# Or use percentile mode for volatility regime awareness
BACKTEST_ADAPTIVE_STOP_MODE=percentile
BACKTEST_VOLATILITY_WINDOW=200
BACKTEST_VOLATILITY_SENSITIVITY=0.6
```

**Benefits:**
- Automatically adapts to market conditions without manual adjustment
- Reduces stop-outs during volatile periods
- Tightens stops during quiet periods to improve risk/reward
- Can improve win rate by avoiding premature stops in high-volatility environments

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
