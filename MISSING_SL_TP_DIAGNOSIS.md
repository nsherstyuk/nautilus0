# DIAGNOSIS: Missing Stop Loss and Take Profit Orders

## Problem
Orders are being submitted without stop loss and take profit in live trading.

## Root Cause Analysis

### Issue 1: FX Detection Logic
The strategy determines whether to include SL/TP based on `self._is_fx` flag, which is set in `on_start()` by checking:
```python
self._is_fx = "/" in self.instrument.raw_symbol.value
```

**Problem:** Interactive Brokers may return forex instruments with different symbol formats:
- Expected: `"EUR/USD"` (with slash)
- Actual from IBKR: Possibly `"EURUSD"` (without slash) or different format

If IBKR returns the symbol without a slash, `_is_fx` becomes `False`, causing orders to be submitted without SL/TP.

### Issue 2: Instrument Type Detection
The original code only checked for "/" in `raw_symbol.value`, but didn't check:
- If the instrument is actually a `CurrencyPair` type
- If the instrument_id contains "/"

### Issue 3: Data Misalignment
Potential misalignment issues:
1. **Instrument Loading Timing**: Instrument might not be fully loaded when `on_start()` is called
2. **Symbol Format Mismatch**: IBKR symbology method (`IB_SIMPLIFIED` vs `IB_RAW`) affects symbol format
3. **Bar Type Mismatch**: Different bar types (1-minute, 2-minute DMI, 15-minute Stochastic) might have inconsistent instrument IDs

## Fixes Applied

### 1. Enhanced FX Detection (`strategies/moving_average_crossover.py`)
- ✅ Now checks multiple sources:
  - `CurrencyPair` instance type check
  - "/" in `raw_symbol`
  - "/" in `instrument_id`
- ✅ Added comprehensive logging to diagnose detection issues
- ✅ Added warning when non-FX is detected

### 2. Enhanced Order Submission Logging
- ✅ Logs bracket order creation details
- ✅ Logs each order type in bracket
- ✅ Added error handling around bracket order creation
- ✅ Warning when submitting orders without SL/TP

## Diagnostic Steps

When you run live trading, check the logs for:

1. **Instrument Detection Log** (on startup):
   ```
   Instrument detection - Type: ..., raw_symbol: ..., instrument_id: ..., is_currency_pair: ..., has_slash_symbol: ..., has_slash_id: ..., _is_fx: ...
   ```

2. **FX Detection Result**:
   - ✅ Good: `FX instrument detected - pip-based SL/TP ENABLED`
   - ❌ Bad: `Non-FX instrument detected: ... - pip-based SL/TP DISABLED`

3. **Order Submission Log**:
   - ✅ Good: `Created bracket order with 3 orders: ['MARKET', 'STOP_MARKET', 'LIMIT']`
   - ❌ Bad: `⚠️ NON-FX INSTRUMENT DETECTED - Submitting market order WITHOUT SL/TP!`

## Checking for Data Misalignment

### Check 1: Instrument Symbol Format
Look in logs for the instrument detection message. If `raw_symbol` doesn't contain "/" but your config has "EUR/USD", there's a format mismatch.

### Check 2: Bar Type Consistency
Verify that all bar types (1-minute, 2-minute DMI, 15-minute Stochastic) reference the same instrument:
- Check logs for bar subscriptions
- Verify instrument IDs match across all bar types

### Check 3: IBKR Symbology Method
Check your `.env` file:
- `IB_SYMBOLOGY_METHOD=IB_SIMPLIFIED` (default) - may format symbols differently
- `IB_SYMBOLOGY_METHOD=IB_RAW` - uses raw IBKR format

## Recommended Actions

1. **Check Live Trading Logs**:
   - Look for the instrument detection message
   - Check if `_is_fx` is `True` or `False`
   - Verify bracket order creation

2. **If `_is_fx` is False but you're trading FX**:
   - Check `LIVE_SYMBOL` in `.env` - should be "EUR/USD" format
   - Check `LIVE_VENUE` - should be "IDEALPRO" for forex
   - Check IBKR symbology method setting

3. **If Orders Still Missing SL/TP**:
   - Check for bracket order creation errors
   - Verify IBKR account supports bracket orders
   - Check if orders are being rejected by broker

## Testing

After fixes, when you run live trading:
1. Monitor startup logs for FX detection
2. Check first trade submission logs
3. Verify bracket orders contain 3 orders (entry + SL + TP)
4. Confirm in IBKR TWS/Gateway that orders have attached SL/TP

