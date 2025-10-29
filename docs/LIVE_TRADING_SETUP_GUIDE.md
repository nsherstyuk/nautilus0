# Live Trading Setup Guide - IBKR Connection & Startup

A step-by-step guide for first-time setup of the Interactive Brokers (IBKR) connection and starting live trading with the NautilusTrader system. This guide focuses on getting your environment ready for paper trading before deploying Phase 6 strategies.

**Version:** 1.0  
**Last Updated:** 2025-01-29  
**Estimated Time:** 15-30 minutes  

## Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Start Commands](#quick-start-commands)
- [Detailed Setup Steps](#detailed-setup-steps)
- [TWS API Configuration](#tws-api-configuration)
- [Troubleshooting](#troubleshooting)
- [Expected Log Output](#expected-log-output)
- [Safety Checklist](#safety-checklist)
- [FAQ](#faq)
- [Additional Resources](#additional-resources)

## Overview

This guide covers the essential setup for connecting to Interactive Brokers (IBKR) via TWS or IB Gateway and starting the live trading system. It does not cover strategy configuration or optimization—refer to `docs/PHASE6_DEPLOYMENT_GUIDE.md` for Phase 6 deployment details. This guide is a prerequisite for that document.

By the end of this guide, you will have:
- Installed and configured IBKR TWS or Gateway for API access
- Set up the Python virtual environment
- Configured IBKR connection settings in `.env.phase6`
- Verified the connection using diagnostic tools
- Started the live trading system with Phase 6 parameters

### Workflow Diagram
```
Prerequisites → TWS Setup → Python Setup → Configuration → Diagnostics → Live Trading
```

## Prerequisites

Before starting, ensure you have the following ready.

### IBKR Paper Trading Account

Paper trading accounts are essential for testing without financial risk. Account numbers start with "DU" (e.g., DU1558484).

- [ ] Paper trading account created ([IBKR Paper Trading Documentation](https://www.interactivebrokers.com/en/index.php?f=1286))
- [ ] Forex permissions enabled
- [ ] Market data subscription (or using delayed/frozen data)
- [ ] Account balance adequate ($10,000+ recommended for realistic testing)
- [ ] Account number ready (starts with DU)

**NEVER use a live account for initial testing.**

### IBKR TWS or IB Gateway

TWS is the full trading platform; IB Gateway is lighter for API-only use. Recommend IB Gateway for automated trading.

- Download TWS: [https://www.interactivebrokers.com/en/trading/tws.php](https://www.interactivebrokers.com/en/trading/tws.php)
- Download Gateway: [https://www.interactivebrokers.com/en/trading/ibgateway-stable.php](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php)

Installation:
- Windows: Run installer as administrator
- Default location: `C:\Jts` (TWS) or `C:\IBJts` (Gateway)
- Use latest stable version

- [ ] TWS or Gateway installed
- [ ] Application launches successfully
- [ ] Can log into paper trading account
- [ ] Port ready: 7497 (TWS paper) or 4002 (Gateway paper)

### Python Environment

Requires Python 3.10, 3.11, or 3.12. The project uses `.venv312`.

Verify Python:
```powershell
python --version
# Should show: Python 3.12.x
```

Verify virtual environment:
```powershell
Test-Path .venv312\Scripts\Activate.ps1
# Should show: True
```

- [ ] Python 3.10+ installed
- [ ] Virtual environment `.venv312` exists
- [ ] Can activate virtual environment
- [ ] Dependencies installed (`nautilus_trader`, `ibapi`, etc.)

### Project Files

- [ ] `.env.phase6` exists (Phase 6 optimized parameters)
- [ ] `live/run_live.py` exists (main live trading script)
- [ ] `scripts/diagnose_ibkr_connection.py` exists (diagnostic tool)
- [ ] `live/run_live_with_env.ps1` exists (startup script)

## Quick Start Commands

For experienced users:

```powershell
# 1. Navigate to project directory
cd C:\nautilus0

# 2. Ensure TWS/Gateway is running and logged into paper account

# 3. Update .env.phase6 with IBKR settings
python scripts/update_env_phase6.py

# 4. Run comprehensive diagnostics
python scripts/diagnose_ibkr_connection.py

# 5. If all diagnostics pass, start live trading
.\live\run_live_with_env.ps1

# 6. Monitor logs (in separate PowerShell window)
Get-Content logs/live/live_trading.log -Wait -Tail 50
```

If any diagnostic fails, proceed to Detailed Setup Steps.

## Detailed Setup Steps

### Step 1: Configure TWS/Gateway API Settings

#### Launch TWS/Gateway
- Open TWS or IB Gateway
- Select **Paper Trading** mode
- Log in with paper trading credentials
- Wait for full load ("Connected" status)

#### Enable API Access
- Navigate: **File → Global Configuration → API → Settings**
- Reference: See `IB_CONNECTION_DIAGNOSIS.md` for details

Required settings:
- ☑ **"Enable ActiveX and Socket Clients"** (most common issue)
- **Socket Port:** 7497 (TWS paper) or 4002 (Gateway paper)
- **Master API client ID:** 0 (default)
- ☐ **"Read-Only API"** (unchecked for orders)
- **Trusted IPs:** Include `127.0.0.1`
- **Allow connections from localhost only:** Optional for security

#### Apply Settings
- Click **OK**
- **IMPORTANT:** Restart TWS/Gateway
- Log back in
- Verify settings

Common mistakes:
- ❌ Forgetting "OK"
- ❌ Not restarting
- ❌ "Read-Only API" checked
- ❌ Missing `127.0.0.1` in Trusted IPs
- ❌ Wrong port

### Step 2: Configure IBKR Connection Settings

#### Understand Configuration Files
- `.env` — Active config
- `.env.phase6` — Phase 6 template
- `.env.example` — Reference

Workflow: Edit `.env.phase6` → Copy to `.env`

#### Update .env.phase6
**Option A: Automated (recommended)**
```powershell
python scripts/update_env_phase6.py
```

Expected output:
```
IBKR Settings Update for .env.phase6
============================================================
[1/4] Validating source .env file...
      ✓ Found .env file
      ✓ All required IBKR variables present:
        - IB_HOST=127.0.0.1
        - IB_PORT=7497
        - IB_CLIENT_ID=1
        - IB_ACCOUNT_ID=DU...
        - IB_MARKET_DATA_TYPE=DELAYED_FROZEN

[2/4] Checking target .env.phase6 file...
      ✓ Found .env.phase6 file
      ℹ 5/5 required IBKR settings present

[3/4] Verifying settings...
      ✓ All settings verified correctly

[4/4] Summary
============================================================
ℹ .env.phase6 already contains correct IBKR settings
============================================================
```

**Option B: Manual**
1. Open `.env.phase6` in editor
2. Find `# IBKR Connection Settings` (~line 57)
3. Add/update:
   ```ini
   IB_HOST=127.0.0.1
   IB_PORT=7497
   IB_CLIENT_ID=1
   IB_ACCOUNT_ID=DU1558484  # Replace with your paper account number
   IB_MARKET_DATA_TYPE=DELAYED_FROZEN
   ```
4. Save

#### Configuration Values
- `IB_HOST=127.0.0.1` — Localhost
- `IB_PORT=7497` — TWS paper (4002 Gateway paper)
- `IB_CLIENT_ID=1` — Unique ID (1-999)
- `IB_ACCOUNT_ID=DU1558484` — Paper account
- `IB_MARKET_DATA_TYPE=DELAYED_FROZEN` — Delayed data (free)

### Step 3: Run Diagnostic Tests

#### Comprehensive Diagnostic
```powershell
python scripts/diagnose_ibkr_connection.py
```

Runs:
1. Environment check
2. Port test
3. Handshake test
4. IBAPI client test

#### Expected Output (Pass)
```
======================================================================
IBKR Connection Diagnostic Tool
This script runs all diagnostic checks in sequence
======================================================================

[1/5] Checking .env configuration...
----------------------------------------------------------------------
✓ All required IBKR variables found and valid
  - IB_HOST=127.0.0.1
  - IB_PORT=7497
  - IB_CLIENT_ID=1
  - IB_ACCOUNT_ID=DU...
  - IB_MARKET_DATA_TYPE=DELAYED_FROZEN

[2/5] Port Connectivity Test...
----------------------------------------------------------------------
✓ Port 7497 is OPEN and accepting connections

[3/5] IB API Handshake Test...
----------------------------------------------------------------------
✓ IB API handshake completed successfully!

[4/5] IBAPI Client Test...
----------------------------------------------------------------------
✓ Successfully connected to Interactive Brokers
✓ Received connection confirmation

[5/5] Generating summary report...
======================================================================
IBKR CONNECTION DIAGNOSTIC SUMMARY
======================================================================

Test Results:
  [✓] Environment Variables
  [✓] Port Connectivity
  [✓] IB API Handshake
  [✓] IBAPI Client

✓ ALL CHECKS PASSED - System ready for live trading

======================================================================
Recommendations:
----------------------------------------------------------------------

✓ System is ready for live trading!

Next steps:
  1. Review your trading strategy configuration
  2. Verify .env.phase6 has optimal parameters
  3. Run: .\live\run_live_with_env.ps1
  4. Monitor logs for successful connection

For more help, see:
  - docs/LIVE_TRADING_SETUP_GUIDE.md
  - IB_CONNECTION_DIAGNOSIS.md
======================================================================
```

#### If Fail
See Troubleshooting for solutions based on failed test.

### Step 4: Start Live Trading

#### Automated (Recommended)
```powershell
.\live\run_live_with_env.ps1
```

Does:
1. Activate `.venv312`
2. Backup `.env`
3. Copy `.env.phase6` to `.env`
4. Checklist
5. Run `python live/run_live.py`

Expected:
```
============================================================
Live Trading Startup with Phase 6 Configuration
============================================================

[1/4] Activating virtual environment...
✓ Virtual environment activated (.venv312)

[2/4] Backing up current .env file...
✓ Backup created: .env.backup.20250129_143022

[3/4] Activating Phase 6 configuration...
✓ Phase 6 configuration activated (.env.phase6 → .env)
ℹ Using Phase 6 optimized parameters for live trading.

[4/4] Starting live trading system...
------------------------------------------------------------
Pre-flight checklist:
 ✓ Virtual environment: .venv312
 ✓ Configuration: .env.phase6
 ✓ Backup created: .env.backup.20250129_143022
 ✓ IBKR settings: Loaded from .env

⚠ Ensure IBKR TWS/Gateway is running on port 7497 (paper trading)
⚠ Ensure API is enabled in TWS settings

Executing: python live/run_live.py
------------------------------------------------------------

[Live trading logs will appear here...]
```

#### Manual
```powershell
# 1. Activate
.venv312\Scripts\Activate.ps1

# 2. Backup
Copy-Item .env .env.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')

# 3. Activate Phase 6
Copy-Item .env.phase6 .env -Force

# 4. Start
python live/run_live.py
```

#### Stopping
- Ctrl+C
- Wait 5-10s for close/disconnect

#### Rollback
```powershell
Copy-Item .env.backup.20250129_143022 .env -Force
python live/run_live.py
```

## TWS API Configuration

### Accessing Settings
- File → Global Configuration → API → Settings
- Or right-click tray icon → Global Configuration

### API Settings Panel

**Enable ActiveX and Socket Clients:**
- Master switch for API
- Must check
- Default: Unchecked

**Socket Port:**
- 7497 TWS paper, 4002 Gateway paper
- Match `IB_PORT` in `.env`

**Master API client ID:**
- Default 0

**Read-Only API:**
- Uncheck for orders

**Trusted IPs:**
- Add `127.0.0.1`

**Allow connections from localhost only:**
- Recommended

### Verifying
1. Check API indicator (green)
2. Run:
   ```powershell
   python scripts/check_port.py
   ```
   `✓ Port 7497 is OPEN`

### Common Issues

**Checkbox unchecks:**
- Exit TWS
- Delete `C:\Users\<username>\Jts\<account>\settings`
- Restart, reconfigure

**Port closed:**
- Exit TWS (Task Manager)
- Firewall exception:
  ```powershell
  New-NetFirewallRule -DisplayName "TWS API" -Direction Inbound -Program "C:\Jts\tws.exe" -Action Allow
  ```
- Restart, wait 30s

**Missing 127.0.0.1:**
- Add in settings
- Restart

## Troubleshooting

### Module Import Errors

**ModuleNotFoundError: No module named 'config'**
- Fixed in latest `live/run_live.py`
- Verify:
  ```powershell
  Select-String -Path live/run_live.py -Pattern "PROJECT_ROOT"
  ```
- Run from root: `cd C:\nautilus0; python live/run_live.py`

**ModuleNotFoundError: No module named 'nautilus_trader'**
```powershell
.venv312\Scripts\Activate.ps1
echo $env:VIRTUAL_ENV  # C:\nautilus0\.venv312
pip install -r requirements.txt
```

### IBKR Connection Errors

**Connection refused / Port CLOSED**
1. Verify running:
   ```powershell
   Get-Process | Where-Object {$_.ProcessName -like "*tws*" -or $_.ProcessName -like "*ibgateway*"}
   ```
2. Check port in settings
3. Update `IB_PORT`
4. Restart diagnostic

**API handshake timeout**
1. Enable API (Section 6.2)
2. Restart
3. Firewall:
   ```powershell
   New-NetFirewallRule -DisplayName "TWS API" -Direction Inbound -Program "C:\Jts\tws.exe" -Action Allow
   ```
4. Test:
   ```powershell
   python scripts/test_ib_handshake.py
   ```

**Client ID in use**
- Change `IB_CLIENT_ID=2` in `.env`
- Update `.env.phase6`:
  ```powershell
  python scripts/update_env_phase6.py --force
  ```

**Invalid account ID**
1. Verify in TWS (title bar / Account Window)
2. Update `IB_ACCOUNT_ID=DU1558484`
3. Ensure paper login

### Configuration Errors

**.env not found**
```powershell
Copy-Item .env.phase6 .env -Force
# Or from example
Copy-Item .env.example .env
```

**Missing IB_HOST**
```powershell
python scripts/update_env_phase6.py
# Or manual add
```

**IB_PORT invalid**
```ini
IB_PORT=7497  # TWS paper
IB_PORT=4002  # Gateway paper
```

### Runtime Errors

**No market data**
1. Check hours (forex 24/5)
2. `IB_MARKET_DATA_TYPE=DELAYED_FROZEN`
3. Subscriptions in TWS
4. `LIVE_BAR_SPEC=15-MINUTE-MID-EXTERNAL`

**Orders rejected / Insufficient margin**
1. Check balance
2. `LIVE_TRADE_SIZE=10000`
3. Valid for EUR/USD
4. TWS logs: `C:\Users\<username>\Jts\<account>\log\api.<date>.log`

**No signals**
- Normal (~2/week)
- Check "Strategy initialized"
- Monitor:
  ```powershell
  Get-Content logs/live/live_trading.log -Wait -Tail 50 | Select-String "signal"
  ```

### Performance Issues

**Worse than backtest**
1. `python tools/validate_phase6_oos.py --rank 1`
2. `python live/generate_performance_report.py --period daily`
3. Switch rank
4. TWS execution

**Excessive drawdown**
1. Compare backtest
2. `LIVE_TRADE_SIZE=50000`
3. Stop if >50% backtest

### Diagnostic Errors

**Script not found**
```powershell
cd C:\nautilus0
Test-Path scripts/diagnose_ibkr_connection.py
python scripts/diagnose_ibkr_connection.py
```

**Timeout**
1. API not enabled
2. Restart TWS
3. Individual tests:
   ```powershell
   python scripts/check_port.py
   python scripts/test_ib_handshake.py
   python scripts/test_ibapi_client.py
   ```

## Expected Log Output

### Successful Startup
```
2025-01-29 14:30:15 [INFO] Starting live trading system...
2025-01-29 14:30:15 [INFO] Loading configuration from .env
2025-01-29 14:30:15 [INFO] IBKR connection details: host=127.0.0.1 port=7497 client_id=1 account=DU1558484
2025-01-29 14:30:15 [INFO] Initializing NautilusTrader live trading node...
2025-01-29 14:30:16 [INFO] Creating IBKR data client (client_id=1)...
2025-01-29 14:30:16 [INFO] Creating IBKR execution client (client_id=2)...
2025-01-29 14:30:16 [INFO] Waiting for IBKR clients to connect (up to 30 seconds)...
2025-01-29 14:30:17 [INFO] LIVE-TRADER-001.InteractiveBrokersClient-001: Connected to Interactive Brokers
2025-01-29 14:30:17 [INFO] LIVE-TRADER-001.InteractiveBrokersClient-002: Connected to Interactive Brokers
2025-01-29 14:30:17 [INFO] IBKR clients connected successfully
2025-01-29 14:30:17 [INFO] Subscribing to EUR/USD market data (15-MINUTE-MID-EXTERNAL)...
2025-01-29 14:30:18 [INFO] Market data subscription active
2025-01-29 14:30:18 [INFO] Initializing strategy: MovingAverageCrossStrategy
2025-01-29 14:30:18 [INFO] Strategy parameters: fast_period=42, slow_period=270, stop_loss_pips=30
2025-01-29 14:30:18 [INFO] Live trading node built successfully. Starting...
2025-01-29 14:30:18 [INFO] Live trading system is now running. Press Ctrl+C to stop.
```

### Market Data
```
2025-01-29 14:31:00 [INFO] Received bar: EUR/USD 15-MINUTE-MID-EXTERNAL open=1.08450 high=1.08475 low=1.08425 close=1.08460
2025-01-29 14:46:00 [INFO] Received bar: EUR/USD 15-MINUTE-MID-EXTERNAL open=1.08460 high=1.08490 low=1.08440 close=1.08470
```

### Signal Generation
```
2025-01-29 15:15:00 [INFO] Fast MA (42): 1.08455, Slow MA (270): 1.08420
2025-01-29 15:15:00 [INFO] Crossover detected: Fast MA crossed above Slow MA
2025-01-29 15:15:00 [INFO] DMI filter: ADX=25.3, +DI=28.5, -DI=18.2 (bullish trend confirmed)
2025-01-29 15:15:00 [INFO] Stochastic filter: %K=35.2, %D=32.8 (bullish momentum confirmed)
2025-01-29 15:15:00 [INFO] Signal generated: BUY EUR/USD
```

### Order Execution
```
2025-01-29 15:15:01 [INFO] Submitting order: BUY 100000 EUR/USD @ MARKET
2025-01-29 15:15:01 [INFO] Order submitted: OrderId=1, ClientOrderId=O-20250129-151501-001
2025-01-29 15:15:02 [INFO] Order accepted by broker: OrderId=1
2025-01-29 15:15:02 [INFO] Order filled: OrderId=1, FillPrice=1.08472, Quantity=100000
2025-01-29 15:15:02 [INFO] Position opened: LONG 100000 EUR/USD @ 1.08472
2025-01-29 15:15:02 [INFO] Stop loss order submitted: SELL 100000 EUR/USD @ 1.08172 (30 pips)
2025-01-29 15:15:02 [INFO] Take profit order submitted: SELL 100000 EUR/USD @ 1.08672 (60 pips)
```

### Position Management
```
2025-01-29 15:30:00 [INFO] Position update: LONG 100000 EUR/USD, Unrealized PnL: +$150.00
2025-01-29 15:45:00 [INFO] Trailing stop activated: Price moved 25 pips in favor
2025-01-29 15:45:00 [INFO] Trailing stop updated: New stop @ 1.08297 (18 pips trailing distance)
```

### Position Close
```
2025-01-29 16:30:00 [INFO] Take profit triggered: Price reached 1.08672
2025-01-29 16:30:01 [INFO] Order filled: SELL 100000 EUR/USD @ 1.08670
2025-01-29 16:30:01 [INFO] Position closed: Realized PnL: +$198.00
2025-01-29 16:30:01 [INFO] Trade summary: Entry=1.08472, Exit=1.08670, Pips=+19.8, Duration=1h 15m
```

### Error Examples
```
2025-01-29 14:30:15 [ERROR] Failed to connect to IBKR: Connection refused (port 7497)
2025-01-29 14:30:15 [ERROR] Ensure TWS/Gateway is running and API is enabled

2025-01-29 15:15:02 [WARNING] Order rejected: Insufficient margin
2025-01-29 15:15:02 [WARNING] Order details: BUY 100000 EUR/USD @ MARKET

2025-01-29 16:00:00 [WARNING] Market data delayed: Last update 5 minutes ago
2025-01-29 16:00:00 [WARNING] Check TWS market data subscription
```

### Graceful Shutdown
```
2025-01-29 17:00:00 [INFO] Shutdown signal received (Ctrl+C)
2025-01-29 17:00:00 [INFO] Stopping live trading system...
2025-01-29 17:00:00 [INFO] Closing open positions...
2025-01-29 17:00:01 [INFO] All positions closed
2025-01-29 17:00:01 [INFO] Disconnecting from IBKR...
2025-01-29 17:00:02 [INFO] IBKR clients disconnected
2025-01-29 17:00:02 [INFO] Live trading system stopped successfully
```

## Safety Checklist

### Pre-Trading

**Account:**
- [ ] Paper (DU prefix)
- [ ] Matches TWS
- [ ] "Paper Trading" in title
- [ ] Balance $10k+
- [ ] NOT live (U prefix)

**Configuration:**
- [ ] Phase 6 in `.env`
- [ ] IBKR correct
- [ ] Trade size appropriate
- [ ] Stop loss/take profit
- [ ] Position limits

**System:**
- [ ] Diagnostics pass
- [ ] TWS running/connected
- [ ] API enabled
- [ ] Market data active
- [ ] Logs writable

### During Trading

**Monitoring:**
- [ ] Logs every 15-30 min
- [ ] Errors/warnings
- [ ] Orders expected
- [ ] PnL
- [ ] TWS status

**Risk:**
- [ ] Stop loss active
- [ ] Size within limits
- [ ] No excess drawdown
- [ ] No rejections
- [ ] Data current

### Post-Trading

**Daily:**
- [ ] Review trades
- [ ] Realized PnL
- [ ] No open positions
- [ ] Log errors
- [ ] Performance report

**Weekly:**
- [ ] vs Backtest
- [ ] Win rate/Sharpe
- [ ] Rejected signals
- [ ] Execution
- [ ] Archive logs

**Monthly:**
- [ ] Analysis
- [ ] Validate params
- [ ] Update docs
- [ ] Cleanup
- [ ] Re-optimize if needed

### Emergency

**If Wrong:**
1. Ctrl+C
2. Close positions in TWS
3. Cancel orders
4. Investigate logs
5. Don't restart

**Live Account Accident:**
1. Ctrl+C
2. Close/cancel in TWS
3. Verify DU in `.env`
4. Relog paper
5. Diagnostics
6. Verify before restart

## FAQ

**Q: How long paper trade?**  
A: 2-4 weeks min, 2-3 months ideal. 20+ trades. ~2/week for Phase 6.

**Q: Diagnostics pass but fails?**  
A: Restart TWS, wait 30s, re-diagnostic, check logs, try client ID 2/3/10/11.

**Q: Multiple strategies?**  
A: Yes, unique client IDs. Separate `.env` files.

**Q: Market data not available?**  
A: Hours, subscription, delayed, bar spec.

**Q: Strategy working?**  
A: Initialized, data, MAs, signals, orders.

**Q: No signals days?**  
A: Normal, selective, market dependent. Don't force.

**Q: Modify Phase 6?**  
A: No, optimized set. Use different rank or re-optimize.

**Q: Different symbol?**  
A: Re-optimize, validate, adjust risk. Not recommended.

**Q: Different rank?**  
A:
```powershell
.\scripts\deploy_phase6_to_paper.ps1 -Rank 2
.\live\run_live_with_env.ps1
```

**Q: TWS disconnect?**  
A: Auto-reconnect (5 retries). Logs show. Restart if fails.

**Q: Monitor vs backtest?**  
A:
```powershell
python live/generate_performance_report.py --period daily
cat logs/live/reports/daily_report_<timestamp>.md
```

**Q: Insufficient margin?**  
A: Reduce size `LIVE_TRADE_SIZE=50000`, check balance, close positions, paper ample.

**Q: VPS/cloud?**  
A: TWS on same/VPS, allow remote (risk), update host, firewall.

**Q: Client ID in use?**  
A: Change ID, close apps, restart TWS, diagnostic.

## Additional Resources

### Related Documentation
- `docs/PHASE6_DEPLOYMENT_GUIDE.md`
- `IB_CONNECTION_DIAGNOSIS.md`
- `README.md`
- `optimization/results/phase6_refinement_results_top_10.json`

### Diagnostic Scripts
- `scripts/diagnose_ibkr_connection.py`
- `scripts/check_port.py`
- `scripts/test_ib_handshake.py`
- `scripts/test_ibapi_client.py`
- `scripts/update_env_phase6.py`

### Startup Scripts
- `live/run_live_with_env.ps1`
- `live/run_live.py`

### External
- IBKR API: https://interactivebrokers.github.io/tws-api/
- Paper: https://www.interactivebrokers.com/en/index.php?f=1286
- Nautilus: https://nautilustrader.io/docs/
- TWS Guide: https://www.interactivebrokers.com/en/software/tws/usersguidebook.htm

### Support
1. Docs
2. `diagnostics/ibkr_diagnosis_<timestamp>.txt`
3. TWS API logs: `C:\Users\<username>\Jts\<account>\log\api.<date>.log`
4. IBKR docs error codes
5. Nautilus docs

---

**Document Information:**  
- **Version:** 1.0  
- **Last Updated:** 2025-01-29  
- **Maintained By:** Trading System Team  
- **Related Guides:** PHASE6_DEPLOYMENT_GUIDE.md, IB_CONNECTION_DIAGNOSIS.md  

**Changelog:**  
- 2025-01-29: Initial version created  
- Consolidated setup instructions from multiple sources  
- Added diagnostic tool references  
- Included troubleshooting for common errors  

---

**Note:** Assumes Phase 6 for EUR/USD 15-min. Other configs: main docs.  

**Important:** Paper trade first. No live until 2-4 weeks validation.

---
