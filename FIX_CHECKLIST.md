# Quick Fix Checklist - IBKR Connection

## Current Situation
✗ TWS API is not responding to connection requests  
✓ Port 7497 is open (TWS is listening)  
✗ All connection libraries fail (ibapi, ib_insync, NautilusTrader)

**This is a TWS configuration issue, NOT a code issue.**

---

## Fix Steps (Do in Order)

### ☐ Step 1: Check TWS API Settings

Open TWS, then:
1. Go to: **File → Global Configuration → API → Settings**
2. Verify these settings:
   - ☑ **"Enable ActiveX and Socket Clients"** - Must be CHECKED
   - ☐ **"Read-Only API"** - Must be UNCHECKED (if visible)
   - **Socket Port:** `7497`
   - **Trusted IPs:** Includes `127.0.0.1`

3. Click **OK** to save

### ☐ Step 2: Restart TWS (REQUIRED)

API changes need a restart:
1. **File → Exit** (close TWS completely)
2. Wait 10 seconds
3. Launch TWS again
4. Log into paper trading account
5. Verify title bar shows: **DU1558484**

### ☐ Step 3: Verify Connection Works

Open PowerShell in `C:\nautilus0`:

```powershell
# Test 1: Check port (should pass)
python scripts\check_port.py

# Test 2: Test ib_insync (your old working library)
python scripts\test_ib_insync.py

# Test 3: If #2 passes, test the minimal script
python scripts\minimal_ib_test.py
```

**Expected result:** Tests 2 and 3 should show "✓ SUCCESS"

### ☐ Step 4: If Still Failing - Check TWS Logs

1. Open: `C:\Users\<YourUsername>\Jts\<account>\log\`
2. Find: `api.<date>.log`
3. Look for: Connection rejections or errors
4. Share the error messages for further diagnosis

### ☐ Step 5: Try Different Client ID

If tests still fail, edit `.env`:

```ini
IB_CLIENT_ID=10  # or 5, 15, 20 - avoid 1 if in use
```

Then rerun tests.

---

## Success Indicators

When working, `test_ib_insync.py` should show:
```
✓ Connection established!
✓ Connected to TWS
✓ Managed accounts: DU1558484
✓ Contract qualified: EUR USD
✓ SUCCESS - ib_insync connection works!
```

---

## If Everything Works

Once connection tests pass, NautilusTrader should work too:

```powershell
python live\run_live.py
```

Expected logs:
```
[INFO] Connected to Interactive Brokers (v176)
[INFO] Waiting for IBKR clients to connect...
```

---

## Most Likely Issue

**"Enable ActiveX and Socket Clients" is not checked in TWS.**

This is the #1 cause of API connection failures. Even if you checked it before, TWS sometimes unchecks it after updates or restarts.

---

## Common Mistakes

1. ✗ Not restarting TWS after changing settings
2. ✗ "Read-Only API" is enabled (blocks connections)
3. ✗ Checking settings in IB Gateway instead of TWS (or vice versa)
4. ✗ TWS is running but not fully logged in
5. ✗ Firewall blocking localhost connections (rare but possible)

---

## Emergency Alternative

If TWS Paper keeps failing, try **IB Gateway** instead:
- Download: https://www.interactivebrokers.com/en/trading/ibgateway-stable.php
- Port: Use 4002 for paper trading
- Update `.env`: `IB_PORT=4002`
- Gateway has simpler API configuration

---

## Your Old Working Setup

Your `olderCode/live_ibkr_trader.py` successfully connected using:
```python
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)
```

This **proves** your system CAN connect to TWS. You just need to restore the working configuration.

---

## Contact Support (Last Resort)

If nothing works:
- **IBKR Support:** https://www.interactivebrokers.com/en/support/
- **Live Chat:** Available in TWS (Help → Chat with Support)
- Tell them: "TWS API port is open but not responding to handshake"
