# Instrument Detection Log Analysis

## Status: ❌ **Instrument Detection Logs Not Found**

I've searched through the log files but **cannot find the instrument detection messages** that should appear when the strategy starts. This suggests either:

1. **The strategy hasn't started yet** - Instrument might not be loaded from IBKR
2. **Logs are going to console/stdout** - Strategy logs may not be written to files
3. **Strategy initialization hasn't completed** - Connection issues preventing startup

## What to Check

### 1. Console Output
The strategy logs use the `nautilus_trader` logger which may output to console. **Check your terminal/console window** where you ran `run_live.py` for messages like:

```
Instrument detection - Type: CurrencyPair, raw_symbol: ..., instrument_id: ..., _is_fx: True
FX instrument detected - pip-based SL/TP ENABLED
```

### 2. Most Recent Startup (Nov 2, 2025 19:23:40)
From logs, I can see the most recent startup attempt:
- **Symbol:** EUR/USD
- **Venue:** IDEALPRO  
- **Bar Spec:** 1-MINUTE-MID-EXTERNAL
- **Configuration:** SL=3 TP=8 TrailAct=6 TrailDist=2 CrossThresh=0.2

### 3. Log File Locations
- Strategy logs: `logs/live/application.log` (currently empty - 0 bytes)
- Live trading logs: `logs/live/live_trading.log` (contains startup messages)
- Root logs: `logs/application.log` (may contain strategy logs)

## Next Steps

### Option 1: Check Console Output
If you're running live trading in a terminal, **scroll up** to see if there are any messages after:
```
Live trading node built successfully. Starting...
```

Look for messages containing:
- `Instrument detection`
- `FX instrument detected`
- `CurrencyPair`
- `raw_symbol`
- `Strategy initialized`

### Option 2: Check if Strategy Started
The strategy logs appear when `on_start()` is called. If you don't see these logs, the strategy may not have started yet. Check for:
- Connection errors
- Instrument loading errors
- IBKR connection issues

### Option 3: Enable More Verbose Logging
To see strategy logs in files, you may need to check:
1. **Console output** - where you ran the command
2. **Windows Event Viewer** - if running as a service
3. **STDOUT capture** - if redirected elsewhere

## Expected Log Output

When the strategy starts correctly, you should see:

```
[INFO] Instrument detection - Type: CurrencyPair, raw_symbol: EURUSD (or EUR/USD), instrument_id: EUR/USD.IDEALPRO, is_currency_pair: True, has_slash_symbol: True/False, has_slash_id: True, _is_fx: True
[INFO] FX instrument detected - pip-based SL/TP ENABLED
[INFO] SL/TP configuration: stop_loss=3 pips, take_profit=8 pips
[INFO] Strategy initialized for EUR/USD.IDEALPRO @ EUR/USD.IDEALPRO-1-MINUTE-MID-EXTERNAL
```

## Verification Checklist

- [ ] Check console/terminal output for strategy logs
- [ ] Verify IBKR connection is established
- [ ] Confirm instrument is loaded (check for "Instrument not found" errors)
- [ ] Look for "Strategy initialized" message
- [ ] Check if `_is_fx` is True in logs

## If Logs Still Missing

If you cannot find the instrument detection logs:

1. **Capture console output** - Run with output redirection:
   ```powershell
   python live/run_live.py 2>&1 | Tee-Object -FilePath logs\console_output.log
   ```

2. **Check for errors** - Look for any error messages preventing strategy startup

3. **Verify code changes** - Ensure the updated `strategies/moving_average_crossover.py` is being used

4. **Manual verification** - After a trade is submitted, check the logs for:
   - `Created bracket order with 3 orders` (good - SL/TP included)
   - `⚠️ NON-FX INSTRUMENT DETECTED` (bad - SL/TP missing)

## Current Configuration

Based on the latest logs:
- **Symbol:** EUR/USD ✅
- **Venue:** IDEALPRO ✅  
- **Should be FX:** YES ✅
- **Expected `_is_fx`:** True ✅

If `_is_fx` is correctly detected as `True`, then orders should include SL/TP. If it's `False`, that's the problem.

