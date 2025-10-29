# IB Connection Fix Applied

## Issue Identified

After successful diagnostic tests showing TWS API is working correctly, I identified **two configuration issues**:

### 1. ❌ Wrong Account ID
- **.env had:** `DU123456` (placeholder value)
- **TWS shows:** `DU1558484` (actual paper trading account)
- **Impact:** Account mismatch can cause connection rejection

### 2. ⚠️ High Client ID  
- **.env had:** `IB_CLIENT_ID=10`
- **Risk:** Client IDs 10-11 may conflict with other apps or TWS sessions
- **Best practice:** Use lower client IDs (1-5) for primary connections

## Changes Applied

Updated `c:\nautilus0\.env`:

```ini
# BEFORE:
IB_CLIENT_ID=10
IB_ACCOUNT_ID=DU123456

# AFTER:
IB_CLIENT_ID=1
IB_ACCOUNT_ID=DU1558484
```

**Note:** NautilusTrader creates TWO clients:
- Client ID `1` → Data client
- Client ID `2` → Execution client (automatically +1)

## Test Now

Run the live trading script:

```powershell
python live/run_live.py
```

### Expected Outcome

You should see successful connection logs like:
```
[INFO] LIVE-TRADER-001.InteractiveBrokersClient-001: Connected to Interactive Brokers (v176)
[INFO] LIVE-TRADER-001.InteractiveBrokersClient-002: Connected to Interactive Brokers (v176)
```

Instead of the previous errors:
```
[ERROR] Failed to receive server version information
[ERROR] Connection failed (code: 502)
```

## If Still Failing

If the connection still fails after this fix, check:

### 1. TWS API Settings (verify again)
File → Global Configuration → API → Settings:
- ☑ "Enable ActiveX and Socket Clients" 
- Socket Port: `7497`
- Trusted IPs: includes `127.0.0.1`

### 2. Client ID Conflicts
Check if another application is using client IDs 1-2. If so, change `.env`:
```ini
IB_CLIENT_ID=3  # or 4, 5, etc.
```

### 3. TWS Restart
Sometimes TWS needs a full restart after changing API settings:
1. Close TWS completely
2. Reopen and log into paper trading account
3. Verify account shows DU1558484 in title bar
4. Try connection again

### 4. Check TWS API Logs
TWS logs API connections. Check for rejection messages:
- Windows: `C:\Users\<username>\Jts\<account>\log\`
- Look for files named `api.<date>.log`

## Diagnostic Tools Available

Three diagnostic scripts in `scripts/`:

1. **`check_port.py`** - Verify port 7497 is open
2. **`test_ib_handshake.py`** - Test IB API protocol (✓ PASSED)  
3. **`test_ibapi_client.py`** - Test ibapi.client.EClient library

## Summary

**Root causes fixed:**
1. ✅ Account ID corrected to match TWS (DU1558484)
2. ✅ Client ID changed to standard value (1)

**Next step:** Run `python live/run_live.py` and verify connection succeeds.
