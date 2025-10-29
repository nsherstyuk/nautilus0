# IBKR Connection Diagnosis - Root Cause Identified

**Date:** 2025-10-28  
**Status:** TWS API not responding to connection requests

## Summary

Port 7497 is OPEN and accepting TCP connections, but TWS is NOT responding to IB API handshake messages. This affects ALL connection methods:
- ✗ Low-level socket handshake
- ✗ `ibapi` library (used by NautilusTrader)
- ✗ `ib_insync` library (used by your old working code)

**This is NOT a NautilusTrader bug.** TWS is not processing API requests.

## Test Results

| Test | Library | Result | Details |
|------|---------|--------|---------|
| Port check | socket | ✓ PASS | Port 7497 is open |
| Socket handshake | raw socket | ✗ FAIL | Timeout after sending API version |
| ibapi client | ibapi.client.EClient | ✗ FAIL | Connection timeout |
| ib_insync | ib_insync.IB | ✗ FAIL | `TimeoutError()` |
| NautilusTrader | nautilus_trader | ✗ FAIL | Connection cancelled |

## Root Cause

**TWS API is not enabled or not functioning properly.**

The TCP port is open (TWS is listening), but TWS is not sending the required handshake response when an API client connects. This indicates:

1. API feature is disabled in TWS, OR
2. TWS is partially started/frozen, OR
3. API permissions are blocking the connection, OR
4. TWS needs a restart

## Required Actions

### 1. Verify TWS API Settings (CRITICAL)

Open TWS and check **EVERY** setting:

**File → Global Configuration → API → Settings**

Required settings:
- ☑ **"Enable ActiveX and Socket Clients"** - MUST be checked
- ☐ **"Read-Only API"** - MUST be unchecked (if present)
- Socket Port: `7497`
- Master API Client ID: (leave default)
- Trusted IPs: Must include `127.0.0.1`

**File → Global Configuration → API → Precautions**
- Check if there are any blocking settings here

### 2. Restart TWS (REQUIRED)

API settings changes sometimes don't take effect until restart:

```powershell
# 1. Close TWS completely (File → Exit)
# 2. Wait 10 seconds
# 3. Launch TWS again
# 4. Log into paper trading account (DU1558484)
# 5. Verify "Enable ActiveX and Socket Clients" is still checked
```

### 3. After Restart - Run Verification

```powershell
cd C:\nautilus0

# Test 1: Port still open
python scripts\check_port.py

# Test 2: ib_insync connection (your old working method)
python scripts\test_ib_insync.py

# Test 3: If Test 2 passes, test minimal ibapi
python scripts\minimal_ib_test.py
```

### 4. Check TWS Logs

TWS logs API connection attempts:

**Windows location:**
```
C:\Users\<YourUsername>\Jts\<account>\log\
```

Look for files named `api.<date>.log` - check for rejection messages or errors.

### 5. Try Different Client ID

If another application is using client ID 1, try different values:

Edit `.env`:
```ini
IB_CLIENT_ID=5  # or 10, 15, 20, etc.
```

Then retest.

## Why This Isn't NautilusTrader's Fault

The documentation in `IB_CONNECTION_WORKAROUND.md` incorrectly blamed NautilusTrader because:
- The low-level IB API test (`test_ib_handshake.py`) also times out
- Your old working `ib_insync` code also times out
- Even raw socket connections timeout

All evidence points to TWS not responding to API requests at the protocol level.

## Expected Behavior (When Working)

When TWS API is properly enabled, you should see:

**test_ib_insync.py:**
```
✓ Connection established!
✓ Connected to TWS
✓ Managed accounts: DU1558484
✓ Contract qualified: EUR USD
```

**NautilusTrader:**
```
[INFO] LIVE-TRADER-001.InteractiveBrokersClient-001: Connected to Interactive Brokers (v176)
[INFO] LIVE-TRADER-001.InteractiveBrokersClient-002: Connected to Interactive Brokers (v176)
```

## Previous Working Configuration

Your `olderCode/live_ibkr_trader.py` successfully used:
```python
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)
```

This proves your TWS setup **can** work - it just needs proper configuration and restart.

## Next Steps

1. **VERIFY** API settings in TWS (see section 1 above)
2. **RESTART** TWS completely
3. **RUN** verification tests (section 3)
4. If still failing, check TWS logs and provide error messages

## Contact Points

- **TWS Support:** https://www.interactivebrokers.com/en/support/
- **IB API Documentation:** https://interactivebrokers.github.io/tws-api/
- **IBKR Client Portal:** Check account status and permissions

## Files Created for Diagnosis

- `scripts/check_port.py` - Verify port is open
- `scripts/test_ib_handshake.py` - Low-level protocol test
- `scripts/test_ibapi_client.py` - Test ibapi library
- `scripts/test_ib_connection.py` - Enhanced ibapi test
- `scripts/minimal_ib_test.py` - Clean ibapi test
- `scripts/test_ib_insync.py` - Test ib_insync (old working library)

All tests are currently failing at the TWS API handshake stage.
