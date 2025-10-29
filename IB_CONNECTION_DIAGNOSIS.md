# IB Connection Diagnosis Results

## Summary
**ROOT CAUSE IDENTIFIED:** TWS API is not enabled or not responding to API handshake requests.

## Test Results

### ✅ Test 1: Port Connectivity (PASSED)
- Port 7497 is **OPEN** and accepting TCP connections
- TWS/IB Gateway is running and listening correctly
- No firewall or network issues

### ❌ Test 2: IB API Handshake (FAILED)
- TCP connection succeeds
- API version handshake sent successfully
- **TWS does not respond to API handshake** (timeout after 5 seconds)

## Diagnosis
TWS is running but configured to **reject API connections**.

## Required Fix

### Step 1: Enable API Access in TWS
1. Open **Trader Workstation (TWS)** or **IB Gateway**
2. Navigate to: **File → Global Configuration → API → Settings**
3. Verify the following settings:

   #### Required Settings:
   - ☑ **"Enable ActiveX and Socket Clients"** — MUST be checked
   - **Socket Port:** Should show `7497` (matches your .env setting)
   - **Master API client ID:** Leave at default or note the value
   - ☐ **"Read-Only API"** — Should be UNCHECKED (unless you only want market data)

   #### Trusted IPs:
   - Ensure `127.0.0.1` is in the **Trusted IPs** list
   - For paper trading, you may need to add it manually

4. Click **OK** to save changes
5. **Restart TWS/Gateway** (important!)

### Step 2: Verify the Fix
After restarting TWS with API enabled, run:
```powershell
python scripts/test_ib_handshake.py
```

Expected output:
```
✓ IB API handshake completed successfully!
```

### Step 3: Run Live Trading
Once handshake succeeds, try:
```powershell
python live/run_live.py
```

## Additional Notes

### Common Mistakes:
- ❌ Forgetting to click "OK" after changing settings
- ❌ Not restarting TWS after enabling API
- ❌ Having "Read-Only API" checked (blocks order submission)
- ❌ Not adding 127.0.0.1 to trusted IPs

### Client ID Conflicts:
Your configuration uses client IDs `10` and `11` (data + execution).
If another application is already using these IDs:
- Change `IB_CLIENT_ID=10` to a different number in `.env`
- TWS supports multiple concurrent connections with unique IDs

### Paper Trading:
Your account `DU123456` is a paper trading account. Ensure TWS is logged into the **paper trading** environment, not live.

## Diagnostic Tools Created

Three diagnostic scripts were created in `scripts/`:

1. **`check_port.py`** - Verifies TCP port is open
2. **`test_ib_handshake.py`** - Tests IB API protocol handshake
3. **`test_ib_connection.py`** - Full connection test with callbacks

Run these in order to diagnose connection issues.

## Next Steps

1. ✅ Enable API in TWS (see Step 1 above)
2. ✅ Restart TWS
3. ✅ Run `python scripts/test_ib_handshake.py`
4. ✅ If successful, run `python live/run_live.py`

## Support

If issues persist after enabling API:
- Check TWS API logs (usually in TWS installation directory)
- Verify no firewall/antivirus blocking connections
- Try different client IDs
- Ensure paper trading account is logged in
