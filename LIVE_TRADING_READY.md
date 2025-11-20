# Live Trading Setup - Complete & Verified
**Date:** 2025-11-20  
**Status:** ✅ Ready for Paper Trading

## Summary

Successfully configured live trading system with **full algorithm parity** between backtest and live environments. Both use the identical `MovingAverageCrossover` strategy with the same risk management parameters.

## What Was Fixed

### 1. Numpy Import Error ❌ → ✅
**Problem:** Running `python live/run_live.py` from `.venv312` caused:
```
ImportError: Unable to import required dependencies: numpy
```

**Solution:** Run live trading from base Python environment (outside venv):
```powershell
python live/run_live.py
```

The `.venv312` had a corrupted/incomplete numpy installation. Base Python environment works correctly.

### 2. Missing Live Environment Config ❌ → ✅
**Problem:**
```
Live configuration error: Environment variable LIVE_SYMBOL is required
```

**Solution:** Created `.env.live` with all required parameters copied from validated backtest configuration.

**Location:** `c:\nautilus0\.env.live`

### 3. Config Loader Updated ✅
Modified `config/live_config.py` to automatically load `.env.live` if it exists, otherwise fall back to `.env`:

```python
def get_live_config() -> LiveConfig:
    # Load .env.live file if it exists, otherwise fall back to .env
    env_file = Path(".env.live")
    if not env_file.exists():
        env_file = Path(".env")
    load_dotenv(env_file)
```

## Algorithm Parity Verification ✅

**Backtest uses:** `MovingAverageCrossover-MA_CROSS`  
**Live uses:** `MovingAverageCrossover-MA_CROSS`  
**Confirmed:** Same strategy class, same parameters

### Key Parameters (Backtest = Live)
```
Symbol: EUR/USD
Bar Spec: 15-MINUTE-MID-EXTERNAL
Fast Period: 40
Slow Period: 260
Stop Loss: 25 pips
Take Profit: 70 pips
Trailing Activation: 35 pips
Trailing Distance: 15 pips
```

## Live Configuration File

### Current Settings (`.env.live`)
- **Trade Size:** 10,000 units (reduced from backtest's 100,000 for safety)
- **Venue:** IDEALPRO (Interactive Brokers Forex)
- **Risk Management:** Fixed pips mode (same as backtest)
- **Filters:** All disabled (matching backtest)
- **Time Filter:** Disabled (trades all hours)
- **Adaptive Stops:** Disabled (using fixed pips)
- **Regime Detection:** Disabled (matching backtest)

### IBKR Connection Parameters
```bash
IB_HOST=127.0.0.1
IB_PORT=7497  # TWS Paper Trading
IB_CLIENT_ID=1
IB_ACCOUNT_ID=YOUR_IB_ACCOUNT_ID  # ⚠️ UPDATE THIS
IB_MARKET_DATA_TYPE=DELAYED_FROZEN
```

## Next Steps to Go Live

### 1. Update IBKR Account ID ⚠️
Edit `.env.live` and replace `YOUR_IB_ACCOUNT_ID` with your actual IBKR account:
```bash
IB_ACCOUNT_ID=DU1234567  # Your paper trading account
```

### 2. Start TWS/Gateway
- Launch Interactive Brokers TWS or IB Gateway
- Enable API connections (Configure → API → Settings)
- Enable paper trading mode
- Use Socket Port: **7497** (paper) or **7496** (live)

### 3. Run Live Trading
```powershell
cd C:\nautilus0
python live/run_live.py
```

### 4. Monitor Logs
```
logs/live/application.log     - General application logs
logs/live/live_trading.log    - Trading decisions and signals
logs/live/strategy.log         - Strategy-specific logs
logs/live/orders.log           - Order submissions/fills
logs/live/errors.log           - Errors and warnings
```

### 5. Verify Strategy Behavior
Watch for log messages:
```
[INFO] Strategy MovingAverageCrossover-MA_CROSS
[INFO] [TRAILING] Activated at +X pips
[INFO] [CMD]--> [Risk] SubmitOrderList
```

## Safety Checklist ✅

- [x] Algorithm parity verified (same strategy class)
- [x] Parameters match validated backtest config
- [x] Trade size reduced to 10K units (1/10th of backtest)
- [x] Paper trading port configured (7497)
- [ ] IBKR account ID updated in `.env.live`
- [ ] TWS/Gateway running with API enabled
- [ ] Monitor first few trades manually
- [ ] Verify SL/TP orders are placed correctly
- [ ] Check trailing stop activates as expected

## Known Limitations

### Backtesting Results
**Latest validation (2025-11-19):**
- Trailing stops **hurt** performance (-64% PnL)
- Disabled config: $11,308 PnL
- Enabled config: $4,037 PnL

**Recommendation:** Consider disabling trailing stops in `.env.live`:
```bash
LIVE_TRAILING_STOP_ACTIVATION_PIPS=200  # Effectively disabled
LIVE_TRAILING_STOP_DISTANCE_PIPS=100
```

### Custom IBKR Connector
The system uses a **patched** IBKR connector located in:
```
patches/ib_connection_patch.py
patches/nautilus_trader/adapters/interactive_brokers/client/connection.py
```

This patch prevents premature connection cancellation. The patch is applied automatically on startup:
```python
from patches import apply_ib_connection_patch
apply_ib_connection_patch()
```

## Files Modified

1. **`.env.live`** (created) - Live trading configuration
2. **`config/live_config.py`** - Updated to load `.env.live`
3. All other files unchanged (backtest still works)

## Testing Results

### Backtest ✅
```
Strategy: MovingAverageCrossover-MA_CROSS
Status: Running successfully
Output: logs/backtest_results/EUR-USD_*/
```

### Live Trading ✅
```
Strategy: MovingAverageCrossover-MA_CROSS
Config Loaded: EUR/USD IDEALPRO 15-MINUTE fast=40 slow=260
Status: Ready (waits for TWS connection)
Logs: logs/live/*.log
```

## Troubleshooting

### "numpy import error"
- **Cause:** Running from `.venv312`
- **Fix:** Run from base Python (outside venv)

### "LIVE_SYMBOL is required"
- **Cause:** `.env.live` not loaded
- **Fix:** Verify `.env.live` exists in project root

### "Connection refused"
- **Cause:** TWS/Gateway not running
- **Fix:** Start TWS and enable API

### "Invalid account"
- **Cause:** Wrong account ID in `.env.live`
- **Fix:** Update `IB_ACCOUNT_ID` with your paper trading account

## Contact & Support

- **Strategy Implementation:** `strategies/moving_average_crossover.py`
- **Live Config:** `config/live_config.py`
- **Backtest Config:** `config/backtest_config.py`
- **IBKR Patch:** `patches/ib_connection_patch.py`

## Quick Start Command

```powershell
# 1. Update .env.live with your IBKR account ID
# 2. Start TWS/Gateway (port 7497 for paper trading)
# 3. Run:
cd C:\nautilus0
python live/run_live.py
```

---

**✅ System is ready for paper trading. Verify with small trades before going live!**
