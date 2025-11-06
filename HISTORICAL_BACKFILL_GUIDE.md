# Historical Data Backfill Guide

## Overview

The historical data backfill feature automatically calculates the required historical data for strategy warmup, requests it from IBKR API, and feeds it to the strategy before live trading begins. This is essential for Phase 6 configuration which uses long EMAs (e.g., slow_period=270) that require ~3.38 days of 15-minute bars to warm up.

## How It Works

### 1. **Warmup Calculation**
The system calculates:
- **Required bars**: `slow_period * 1.2` (20% buffer for safety)
- **Duration**: Based on bar specification (e.g., 15-minute bars)
- **Example**: Phase 6 with slow_period=270 and 15-minute bars requires:
  - 324 bars (270 * 1.2)
  - 81 hours = **3.38 days** of historical data

### 2. **Backfill Process**
When live trading starts:
1. **Analysis**: System checks if historical data is needed
2. **Request**: If needed, requests historical bars from IBKR API
3. **Feed**: Feeds historical bars to strategy for warmup
4. **Verify**: Confirms strategy warmup completion

### 3. **Logging**
All backfill activity is logged to:
- **Console**: Real-time status messages
- **`logs/live/live_trading.log`**: Comprehensive backfill logs
- **`logs/live/strategy.log`**: Strategy-specific logs

## Quick Test

Test the calculation logic without IBKR connection:

```bash
python live/test_backfill.py
```

Expected output:
```
Required bars: 324
Duration: 81.00 hours (3.38 days)
IBKR duration string: '3 D'
```

## Phase 6 Configuration

### Current Setup
- **Symbol**: EUR/USD
- **Venue**: IDEALPRO
- **Bar spec**: 15-MINUTE-MID-EXTERNAL
- **Fast period**: 42
- **Slow period**: 270
- **Required backfill**: ~3.38 days

### Environment Variables
Ensure your `.env` file has:
```env
LIVE_SYMBOL=EUR/USD
LIVE_VENUE=IDEALPRO
LIVE_BAR_SPEC=15-MINUTE-MID-EXTERNAL
LIVE_FAST_PERIOD=42
LIVE_SLOW_PERIOD=270
# ... other Phase 6 parameters ...
```

## Starting Live Trading with Phase 6

### Step 1: Verify Configuration
Check that your `.env` file has Phase 6 parameters configured correctly.

### Step 2: Ensure IBKR TWS/Gateway is Running
- TWS or IB Gateway must be running
- API must be enabled
- Connection settings match your `.env` file

### Step 3: Start Live Trading
```bash
python live/run_live.py
```

### Step 4: Monitor Backfill Process
Watch the console output for:

**Initial Analysis:**
```
================================================================================
HISTORICAL DATA BACKFILL ANALYSIS
================================================================================
Instrument: EUR/USD.IDEALPRO
Bar specification: 15-MINUTE-MID-EXTERNAL
Slow indicator period: 270
Required bars for warmup: 324
Required duration: 81.00 hours (3.38 days)
```

**Backfill Request:**
```
⚠ Historical data backfill required: 0 bars available (required: 324)
Requesting 81.00 hours (3.38 days) of historical data...
Requesting historical bars: instrument=EUR/USD.IDEALPRO, bar_type=..., duration=81.00 hours
```

**Success:**
```
✓ Successfully retrieved 324 historical bars (required: 324)
✓ Successfully fed 324 historical bars to strategy
✓ Strategy warmup completed after feeding historical data
Historical data backfill completed successfully
```

**If No Backfill Needed:**
```
✓ Sufficient historical data already available: 400 bars (required: 324)
No historical data backfill needed - sufficient data already available
```

## Log Files

### Console Output
Real-time status messages show:
- Backfill analysis
- Data request progress
- Success/failure status

### `logs/live/live_trading.log`
Contains detailed backfill logs including:
- Complete analysis results
- Request parameters
- Bar count retrieved
- Any errors or warnings

### `logs/live/strategy.log`
Contains strategy-specific logs including:
- Warmup completion status
- Indicator initialization
- Bar processing status

## Troubleshooting

### Issue: Backfill Fails
**Symptoms:**
```
✗ Failed to retrieve historical bars
Error requesting historical bars: ...
```

**Solutions:**
1. Verify IBKR TWS/Gateway is running
2. Check API connection settings
3. Ensure market data permissions are enabled
4. Check IBKR market data subscription status
5. Verify symbol/venue are correct

### Issue: Insufficient Bars Retrieved
**Symptoms:**
```
⚠ Retrieved 200 bars, but 324 bars are required
Strategy may not warm up immediately.
```

**Solutions:**
1. Check if market was closed during requested period
2. Verify IBKR data availability for the symbol
3. Increase duration buffer if needed
4. Strategy will still warm up using live data (takes longer)

### Issue: Data Client Not Available
**Symptoms:**
```
Data client not available. Cannot perform historical backfill.
```

**Solutions:**
1. Wait longer for IBKR connection (increase sleep time)
2. Check IBKR connection logs
3. Verify client_id is not in use by another session

## Expected Behavior

### First Run
- Backfill is **required** (no existing data)
- System requests ~3.38 days of historical data
- Strategy warms up immediately after backfill

### Subsequent Runs
- Backfill may be **skipped** if data exists
- System checks cache first
- If data exists, skips backfill

### Performance
- **Backfill time**: 30-120 seconds (depends on IBKR response)
- **Bar feeding**: ~1-5 seconds for 324 bars
- **Total startup time**: +30-125 seconds with backfill

## Testing Strategy

### Quick Test (No IBKR Connection)
```bash
python live/test_backfill.py
```
Tests calculation logic only.

### Full Test (With IBKR Connection)
1. Start IBKR TWS/Gateway
2. Run `python live/run_live.py`
3. Monitor console for backfill messages
4. Check logs in `logs/live/` directory
5. Verify strategy warmup completion

### Verify Backfill Success
Look for these messages:
```
✓ Successfully retrieved N historical bars
✓ Successfully fed N historical bars to strategy
✓ Strategy warmup completed after feeding historical data
```

## Next Steps

After successful backfill:
1. Strategy is warmed up and ready to trade
2. Live trading begins immediately
3. Monitor strategy logs for signal generation
4. Check order logs for trade execution

## Notes

- Backfill adds ~30-125 seconds to startup time
- Historical data is requested fresh each time (not cached between sessions)
- IBKR API rate limits apply (be patient)
- For FX (EUR/USD), `use_rth=False` is used (24-hour market)
- For stocks, `use_rth=True` is used (regular trading hours only)

## Configuration Reference

### Phase 6 Parameters (from `.env`)
```env
LIVE_SYMBOL=EUR/USD
LIVE_VENUE=IDEALPRO
LIVE_BAR_SPEC=15-MINUTE-MID-EXTERNAL
LIVE_FAST_PERIOD=42
LIVE_SLOW_PERIOD=270
LIVE_STOP_LOSS_PIPS=35
LIVE_TAKE_PROFIT_PIPS=50
LIVE_TRAILING_STOP_ACTIVATION_PIPS=22
LIVE_TRAILING_STOP_DISTANCE_PIPS=12
LIVE_CROSSOVER_THRESHOLD_PIPS=0.35
LIVE_DMI_ENABLED=true
LIVE_DMI_PERIOD=10
LIVE_STOCH_ENABLED=true
LIVE_STOCH_PERIOD_K=19
LIVE_STOCH_PERIOD_D=3
```

### Required Backfill Duration
- **Fast period (42)**: ~0.52 days
- **Slow period (270)**: ~3.38 days (this is what we request)
- **DMI (2-minute bars)**: Handled separately if needed
- **Stochastic (15-minute bars)**: Same as main bars

## Support

If you encounter issues:
1. Check `logs/live/errors.log` for errors
2. Review `logs/live/live_trading.log` for detailed backfill logs
3. Verify IBKR connection and permissions
4. Ensure Phase 6 parameters are correctly configured

