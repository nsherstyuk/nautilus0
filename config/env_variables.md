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

## Strategy Filters & Enhancements

The strategy filters and enhancements provide advanced signal filtering capabilities to improve trade quality and reduce false signals. All filters are optional and can be enabled/disabled independently. Filters are checked in sequence (Circuit Breaker → Threshold → ATR → Time → ADX → DMI → Stochastic), with the first rejection stopping evaluation for efficiency.

**Recommended approach**: Start with basic filters (DMI, Stochastic), then add others based on backtest analysis. All filters default to disabled except DMI and Stochastic for backward compatibility.

### MA Crossover Threshold

Ensures crossover has sufficient magnitude to avoid noise by requiring the distance between fast MA and slow MA to exceed a threshold.

**Variable**: `BACKTEST_CROSSOVER_THRESHOLD_PIPS`

**Examples**:
- Conservative (fewer signals): `BACKTEST_CROSSOVER_THRESHOLD_PIPS=1.5`
- Moderate (balanced): `BACKTEST_CROSSOVER_THRESHOLD_PIPS=0.7` (default)
- Aggressive (more signals): `BACKTEST_CROSSOVER_THRESHOLD_PIPS=0.3`

```bash
# MA Crossover Threshold
BACKTEST_CROSSOVER_THRESHOLD_PIPS=0.7
```

**Impact**: Higher values reduce false signals but may miss valid crossovers.

### Limit Order Configuration

Use limit orders at next bar open instead of market orders for better price control.

**Variables**:
- `BACKTEST_USE_LIMIT_ORDERS`: Enable/disable limit orders
- `BACKTEST_LIMIT_ORDER_TIMEOUT_BARS`: Timeout for unfilled orders

**Execution Flow**:
- Bar N: Signal confirmed, pending signal stored
- Bar N+1: Limit order placed at bar.open
- Bar N+2: Order cancelled if unfilled (with timeout=1)

**Examples**:
- Quick timeout: `BACKTEST_LIMIT_ORDER_TIMEOUT_BARS=1` (default)
- Patient timeout: `BACKTEST_LIMIT_ORDER_TIMEOUT_BARS=5`
- Market orders: `BACKTEST_USE_LIMIT_ORDERS=false`

```bash
# Limit Order Configuration
BACKTEST_USE_LIMIT_ORDERS=true
BACKTEST_LIMIT_ORDER_TIMEOUT_BARS=1
```

**Trade-offs**: Limit orders reduce slippage but may not fill in fast markets.

### DMI (Directional Movement Index) Trend Filter

Validates that trend direction aligns with signal direction using multi-timeframe bars.

**Variables**:
- `BACKTEST_DMI_ENABLED`: Enable/disable DMI filter
- `BACKTEST_DMI_PERIOD`: DMI calculation period
- `BACKTEST_DMI_BAR_SPEC`: Bar timeframe for DMI calculation

**Filter Logic**:
- For BUY signals: requires +DI > -DI (uptrend)
- For SELL signals: requires -DI > +DI (downtrend)

**Examples**:
- Standard: `DMI_ENABLED=true, DMI_PERIOD=14, DMI_BAR_SPEC=2-MINUTE-MID-EXTERNAL`
- Faster response: `DMI_BAR_SPEC=1-MINUTE-MID-EXTERNAL`
- Smoother trend: `DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL`

```bash
# DMI Trend Filter
BACKTEST_DMI_ENABLED=true
BACKTEST_DMI_PERIOD=14
BACKTEST_DMI_BAR_SPEC=2-MINUTE-MID-EXTERNAL
```

**Note**: DMI is enabled by default in current implementation.

### Stochastic Momentum Filter

Validates momentum alignment and ensures signals occur near recent Stochastic crossings.

**Variables**:
- `BACKTEST_STOCH_ENABLED`: Enable/disable Stochastic filter
- `BACKTEST_STOCH_PERIOD`: %K period (fast line)
- `BACKTEST_STOCH_SMOOTH_PERIOD`: %D period (slow line, smoothing)
- `BACKTEST_STOCH_BAR_SPEC`: Bar timeframe for Stochastic calculation
- `BACKTEST_STOCH_BULLISH_THRESHOLD`: Minimum %K for BUY signals
- `BACKTEST_STOCH_BEARISH_THRESHOLD`: Maximum %K for SELL signals
- `BACKTEST_STOCH_MAX_BARS_SINCE_CROSSING`: Maximum 1-minute bars since %K/%D crossing

**Filter Logic**:
- For BUY: %K > %D, %K > bullish_threshold, bullish crossing within N bars
- For SELL: %K < %D, %K < bearish_threshold, bearish crossing within N bars

**Crossing Recency**: Tracks when %K crosses above/below %D and validates MA signal occurs within N 1-minute bars of crossing to ensure momentum shift is fresh.

**Examples**:
- Standard: `STOCH_ENABLED=true, PERIOD=14, SMOOTH_PERIOD=3, BAR_SPEC=15-MINUTE, MAX_BARS_SINCE_CROSSING=9`
- Faster response: `STOCH_BAR_SPEC=2-MINUTE-MID-EXTERNAL, MAX_BARS_SINCE_CROSSING=5`
- Looser recency: `STOCH_MAX_BARS_SINCE_CROSSING=15`
- Disable recency: `STOCH_MAX_BARS_SINCE_CROSSING=999`

```bash
# Stochastic Momentum Filter
BACKTEST_STOCH_ENABLED=true
BACKTEST_STOCH_PERIOD=14
BACKTEST_STOCH_SMOOTH_PERIOD=3
BACKTEST_STOCH_BAR_SPEC=15-MINUTE-MID-EXTERNAL
BACKTEST_STOCH_BULLISH_THRESHOLD=30
BACKTEST_STOCH_BEARISH_THRESHOLD=70
BACKTEST_STOCH_MAX_BARS_SINCE_CROSSING=9
```

**Note**: Stochastic is enabled by default in current implementation.

### ATR (Average True Range) Volatility Filter

Rejects trades during choppy (low volatility) or extreme (high volatility) market conditions.

**Variables**:
- `BACKTEST_ATR_ENABLED`: Enable/disable ATR filter
- `BACKTEST_ATR_PERIOD`: ATR calculation period
- `BACKTEST_ATR_MIN_THRESHOLD`: Minimum ATR threshold
- `BACKTEST_ATR_MAX_THRESHOLD`: Maximum ATR threshold

**Filter Logic**:
- Reject if ATR < min_threshold (choppy market, whipsaw risk)
- Reject if ATR > max_threshold (extreme volatility, high risk)
- ATR calculated on primary bar type (1-minute bars)

**Threshold Units**: Absolute price units (not pips) for flexibility across instruments.

**Examples**:
- EUR/USD conservative: `ATR_MIN=0.0005, ATR_MAX=0.002` (5-20 pips)
- EUR/USD moderate: `ATR_MIN=0.0003, ATR_MAX=0.003` (3-30 pips, default)
- EUR/USD aggressive: `ATR_MIN=0.0001, ATR_MAX=0.005` (1-50 pips)

```bash
# ATR Volatility Filter
BACKTEST_ATR_ENABLED=false
BACKTEST_ATR_PERIOD=14
BACKTEST_ATR_MIN_THRESHOLD=0.0003
BACKTEST_ATR_MAX_THRESHOLD=0.003
```

**Conversion Guide**: For EUR/USD, 1 pip = 0.0001, so 3 pips = 0.0003.

**Note**: Disabled by default, enable based on backtest analysis.

### ADX (Average Directional Index) Trend Strength Filter

Rejects trades when trend is too weak (choppy/ranging market).

**Variables**:
- `BACKTEST_ADX_ENABLED`: Enable/disable ADX filter
- `BACKTEST_ADX_PERIOD`: ADX calculation period
- `BACKTEST_ADX_MIN_THRESHOLD`: Minimum ADX threshold

**Filter Logic**:
- Reject if ADX < min_threshold (weak/no trend)
- No maximum threshold (higher ADX = stronger trend = better for trend-following)
- ADX is directionally neutral (applies to both BUY and SELL)

**ADX Interpretation**:
- ADX < 20: Weak or no trend (ranging market)
- ADX 20-25: Emerging trend
- ADX > 25: Strong trend
- ADX > 40: Very strong trend

**Examples**:
- Conservative (strong trends only): `ADX_MIN_THRESHOLD=25.0`
- Moderate (emerging trends): `ADX_MIN_THRESHOLD=20.0` (default)
- Aggressive (any trend): `ADX_MIN_THRESHOLD=15.0`

```bash
# ADX Trend Strength Filter
BACKTEST_ADX_ENABLED=false
BACKTEST_ADX_PERIOD=14
BACKTEST_ADX_MIN_THRESHOLD=20.0
```

**Note**: Uses DMI indicator (2-minute bars), requires DMI to be enabled.

### Time-of-Day Filter

Restricts trading to specific hours to avoid low liquidity periods or high-risk times.

**Variables**:
- `BACKTEST_TIME_FILTER_ENABLED`: Enable/disable time filter
- `BACKTEST_TRADING_HOURS_START`: Trading window start hour
- `BACKTEST_TRADING_HOURS_END`: Trading window end hour
- `BACKTEST_MARKET_TIMEZONE`: Timezone for time conversion
- `BACKTEST_EXCLUDED_HOURS`: Specific hours to exclude

**Filter Logic**:
- Converts bar timestamp from UTC to market timezone
- Rejects trades outside trading_hours_start to trading_hours_end window
- Rejects trades during excluded_hours (even if within main window)
- Supports overnight windows (start > end)

**Examples**:
- US market hours: `START=9, END=16, TIMEZONE=America/New_York`
- London session: `START=8, END=16, TIMEZONE=Europe/London`
- Asian session with lunch: `START=9, END=17, TIMEZONE=Asia/Tokyo, EXCLUDED_HOURS=12,13`
- Overnight FX: `START=22, END=6, TIMEZONE=UTC`
- 24-hour trading: `START=0, END=24, TIMEZONE=UTC`

```bash
# Time-of-Day Filter
BACKTEST_TIME_FILTER_ENABLED=false
BACKTEST_TRADING_HOURS_START=8
BACKTEST_TRADING_HOURS_END=16
BACKTEST_MARKET_TIMEZONE=America/New_York
BACKTEST_EXCLUDED_HOURS=
```

**Note**: Disabled by default, enable based on market characteristics.

### Circuit Breaker

Pauses trading after consecutive losses to prevent drawdown spirals and emotional trading.

**Variables**:
- `BACKTEST_CIRCUIT_BREAKER_ENABLED`: Enable/disable circuit breaker
- `BACKTEST_MAX_CONSECUTIVE_LOSSES`: Consecutive loss threshold
- `BACKTEST_COOLDOWN_BARS`: Cooldown period in bars

**Filter Logic**:
- Tracks consecutive losing trades (realized_pnl <= 0)
- Triggers after N consecutive losses
- Pauses all trading for M bars
- Resets counter on winning trade
- Cooldown expires after M bars, trading resumes

**Examples**:
- Conservative (quick trigger): `MAX_CONSECUTIVE_LOSSES=2, COOLDOWN_BARS=20`
- Moderate (standard): `MAX_CONSECUTIVE_LOSSES=3, COOLDOWN_BARS=10` (default)
- Aggressive (slow trigger): `MAX_CONSECUTIVE_LOSSES=5, COOLDOWN_BARS=5`

```bash
# Circuit Breaker
BACKTEST_CIRCUIT_BREAKER_ENABLED=false
BACKTEST_MAX_CONSECUTIVE_LOSSES=3
BACKTEST_COOLDOWN_BARS=10
```

**Behavior**: "After 3 consecutive losses, pause for 10 bars (10 minutes on 1-min timeframe)"

**Note**: Disabled by default, enable for additional risk management.

### Filter Combination Examples

Complete configuration examples for different trading styles:

#### Example 1: Conservative (All Filters Enabled)
```bash
# Conservative configuration - maximum filtering
BACKTEST_CROSSOVER_THRESHOLD_PIPS=1.0
BACKTEST_USE_LIMIT_ORDERS=true
BACKTEST_DMI_ENABLED=true
BACKTEST_STOCH_ENABLED=true
BACKTEST_STOCH_MAX_BARS_SINCE_CROSSING=5
BACKTEST_ATR_ENABLED=true
BACKTEST_ATR_MIN_THRESHOLD=0.0005
BACKTEST_ATR_MAX_THRESHOLD=0.002
BACKTEST_ADX_ENABLED=true
BACKTEST_ADX_MIN_THRESHOLD=25.0
BACKTEST_TIME_FILTER_ENABLED=true
BACKTEST_TRADING_HOURS_START=9
BACKTEST_TRADING_HOURS_END=16
BACKTEST_CIRCUIT_BREAKER_ENABLED=true
BACKTEST_MAX_CONSECUTIVE_LOSSES=2
```

#### Example 2: Moderate (Balanced Filtering)
```bash
# Moderate configuration - balanced signal quality vs quantity
BACKTEST_CROSSOVER_THRESHOLD_PIPS=0.7
BACKTEST_USE_LIMIT_ORDERS=true
BACKTEST_DMI_ENABLED=true
BACKTEST_STOCH_ENABLED=true
BACKTEST_STOCH_MAX_BARS_SINCE_CROSSING=9
BACKTEST_ATR_ENABLED=false
BACKTEST_ADX_ENABLED=false
BACKTEST_TIME_FILTER_ENABLED=false
BACKTEST_CIRCUIT_BREAKER_ENABLED=true
BACKTEST_MAX_CONSECUTIVE_LOSSES=3
```

#### Example 3: Aggressive (Minimal Filtering)
```bash
# Aggressive configuration - maximum signals
BACKTEST_CROSSOVER_THRESHOLD_PIPS=0.3
BACKTEST_USE_LIMIT_ORDERS=false  # Market orders for immediate execution
BACKTEST_DMI_ENABLED=false
BACKTEST_STOCH_ENABLED=false
BACKTEST_ATR_ENABLED=false
BACKTEST_ADX_ENABLED=false
BACKTEST_TIME_FILTER_ENABLED=false
BACKTEST_CIRCUIT_BREAKER_ENABLED=false
```

#### Example 4: Volatility-Focused (ATR + ADX)
```bash
# Volatility-focused configuration - trade only in optimal volatility conditions
BACKTEST_CROSSOVER_THRESHOLD_PIPS=0.7
BACKTEST_USE_LIMIT_ORDERS=true
BACKTEST_DMI_ENABLED=true
BACKTEST_STOCH_ENABLED=true
BACKTEST_ATR_ENABLED=true
BACKTEST_ATR_MIN_THRESHOLD=0.0003
BACKTEST_ATR_MAX_THRESHOLD=0.003
BACKTEST_ADX_ENABLED=true
BACKTEST_ADX_MIN_THRESHOLD=20.0
BACKTEST_TIME_FILTER_ENABLED=false
BACKTEST_CIRCUIT_BREAKER_ENABLED=true
```

### Filter Tuning Guide

Guidance on how to tune each filter based on backtest results:

**If experiencing many false signals:**
- Increase `CROSSOVER_THRESHOLD_PIPS` (0.7 → 1.0 → 1.5)
- Enable ATR filter to avoid choppy markets
- Tighten Stochastic recency: `MAX_BARS_SINCE_CROSSING` (9 → 5)
- Enable ADX filter: `ADX_MIN_THRESHOLD=25.0`

**If experiencing many stop-loss hits:**
- Increase `STOP_LOSS_PIPS` (25 → 30 → 35)
- Enable ATR filter to avoid extreme volatility
- Enable time filter to avoid low liquidity hours

**If missing profitable trades:**
- Decrease `CROSSOVER_THRESHOLD_PIPS` (0.7 → 0.5 → 0.3)
- Loosen Stochastic recency: `MAX_BARS_SINCE_CROSSING` (9 → 15)
- Disable or relax ADX filter
- Review rejected_signals.csv to identify which filters are blocking good trades

**If experiencing drawdown spirals:**
- Enable circuit breaker: `CIRCUIT_BREAKER_ENABLED=true, MAX_CONSECUTIVE_LOSSES=3`
- Reduce cooldown for faster recovery: `COOLDOWN_BARS=5`

### Using Analysis Tools to Optimize Filters

How to use the analysis tools to tune filter parameters:

**Step 1: Run baseline backtest**
```bash
python backtest/run_backtest.py
```

**Step 2: Analyze losing trades**
```bash
python analysis/analyze_losing_trades.py --input logs/backtest_results/EUR-USD_LATEST --json
# Review suggestions for parameter adjustments
```

**Step 3: Analyze filter effectiveness**
```bash
python analysis/analyze_filter_effectiveness.py --input logs/backtest_results/EUR-USD_LATEST
# Review which filters are rejecting trades and their effectiveness
```

**Step 4: Run grid search with adjusted parameters**
```bash
python optimization/grid_search.py --config optimization/grid_config.yaml
```

**Step 5: Compare results**
```bash
python analysis/compare_backtests.py --baseline baseline_dir --compare optimized_dir
```

### Performance Impact

Computational impact of each filter:
- **Circuit Breaker**: Negligible (simple state check)
- **Threshold**: Negligible (arithmetic comparison)
- **ATR**: Low (indicator calculation on primary bars)
- **Time**: Negligible (timestamp comparison)
- **ADX**: Low (uses existing DMI indicator)
- **DMI**: Low (separate bar subscription, efficient calculation)
- **Stochastic**: Low (separate bar subscription, efficient calculation)

**Note**: All filters are designed for minimal performance impact. Enable filters based on analysis, not performance concerns.

### Troubleshooting Filter Configuration

Common issues and solutions:

**Issue: No trades generated**
- **Cause**: Filters too restrictive
- **Solution**: Check rejected_signals.csv to see which filters are rejecting all signals
- **Solution**: Disable filters one by one to identify the culprit
- **Solution**: Relax filter thresholds

**Issue: Limit orders not filling**
- **Cause**: Market moving away from limit price
- **Solution**: Increase `LIMIT_ORDER_TIMEOUT_BARS` for more patience
- **Solution**: Switch to market orders: `USE_LIMIT_ORDERS=false`

**Issue: Circuit breaker triggering too frequently**
- **Cause**: `MAX_CONSECUTIVE_LOSSES` too low or strategy not profitable
- **Solution**: Increase `MAX_CONSECUTIVE_LOSSES` (3 → 5)
- **Solution**: Review strategy parameters and filter configuration

**Issue: Stochastic crossing recency rejecting all signals**
- **Cause**: `MAX_BARS_SINCE_CROSSING` too tight or Stochastic timeframe too long
- **Solution**: Increase `MAX_BARS_SINCE_CROSSING` (9 → 15)
- **Solution**: Use faster Stochastic: `STOCH_BAR_SPEC=2-MINUTE-MID-EXTERNAL`

## Live Trading Parameters

- `IBKR_HOST`: Interactive Brokers host (default: 127.0.0.1)
- `IBKR_PORT`: Interactive Brokers port (default: 7497)
- `IBKR_CLIENT_ID`: Interactive Brokers client ID (default: 1)
