# IB Connection Issue - NautilusTrader Adapter Bug

## Problem Confirmed

The IB API handshake test **succeeds perfectly**:
```
✓ IB API handshake completed successfully!
✓ Server version: 176
```

But NautilusTrader's IB adapter **fails immediately**:
```
[INFO] Connecting to 127.0.0.1:7497 with client id: 1
[INFO] Connection cancelled  ← happens in 1-2ms
[ERROR] Not connected (code: 504)
```

## Root Cause

This is a **bug in NautilusTrader 1.220.0's Interactive Brokers adapter**.

The async connection task is being **cancelled before it completes**. The `asyncio.CancelledError` exception is caught in the adapter's connection code, which logs "Connection cancelled".

### Evidence

1. **Direct IB API works**: `scripts/test_ib_handshake.py` succeeds
2. **Port is open**: `scripts/check_port.py` confirms TWS is listening
3. **TWS API is enabled**: All settings are correct
4. **Account ID is correct**: DU1558484
5. **Connection cancelled immediately**: Within 1-2ms of starting

## Attempted Fixes (All Failed)

- ✗ Changed client ID from 10 to 1
- ✗ Changed account ID to match TWS (DU1558484)
- ✗ Changed market data type to DELAYED_FROZEN
- ✗ Extended pre-connection wait time to 30 seconds
- ✗ Added IB_MAX_CONNECTION_ATTEMPTS environment variable

None of these helped because the issue is in the adapter's async task management.

## Workaround Options

### Option 1: Use Older NautilusTrader Version
Try rolling back to an earlier version where the IB adapter worked:

```powershell
pip install nautilus_trader[ib]==1.210.0
```

### Option 2: File Bug Report
Report this to NautilusTrader team with our diagnostic evidence:
- GitHub: https://github.com/nautechsystems/nautilus_trader/issues

Include:
- Python 3.13.1
- NautilusTrader 1.220.0  
- Windows 11
- TWS version 176
- Our successful handshake test showing IB API works

### Option 3: Patch the Adapter (Advanced)

The issue is in:
```
.venv\Lib\site-packages\nautilus_trader\adapters\interactive_brokers\client\connection.py
```

The `_connect()` async method's task is being cancelled prematurely. A patch would need to:
1. Ensure the task isn't cancelled during initial connection
2. Properly await the connection before returning

### Option 4: Use Different Broker Adapter

NautilusTrader supports other brokers that may have more stable adapters:
- Binance
- Bybit  
- dYdX
- Others

## Recommended Next Steps

1. **Try downgrading NautilusTrader**:
   ```powershell
   pip uninstall nautilus_trader
   pip install nautilus_trader[ib]==1.210.0
   python live/run_live.py
   ```

2. **If downgrade works**: Stay on 1.210.0 until 1.220.0 is fixed

3. **If downgrade doesn't work**: This may be a Python 3.13 compatibility issue
   - Try Python 3.11 or 3.12 instead

4. **Report the bug** to NautilusTrader team with our diagnostic scripts

## Diagnostic Tools Created

We created comprehensive diagnostic tools that prove TWS is working:

- **`scripts/check_port.py`** - ✓ Port is open
- **`scripts/test_ib_handshake.py`** - ✓ IB API handshake succeeds  
- **`scripts/test_ibapi_client.py`** - Test ibapi.client.EClient
- **`scripts/test_ib_connection.py`** - Enhanced connection test

All tests confirm **the problem is in NautilusTrader's adapter, not TWS or IB API**.

## Current Configuration

Your `.env` is correctly configured:
```ini
IB_HOST=127.0.0.1
IB_PORT=7497
IB_CLIENT_ID=1
IB_ACCOUNT_ID=DU1558484
IB_MARKET_DATA_TYPE=DELAYED_FROZEN
IB_MAX_CONNECTION_ATTEMPTS=5
```

TWS API settings are correct (confirmed via screenshot):
- ☑ Enable ActiveX and Socket Clients
- Socket Port: 7497
- Account: DU1558484

## Conclusion

**This is not a configuration issue. It's a bug in NautilusTrader 1.220.0.**

The IB adapter's async connection task management is broken, causing immediate task cancellation.

Try downgrading to 1.210.0 or contact the NautilusTrader team for support.
