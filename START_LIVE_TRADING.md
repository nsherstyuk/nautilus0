# MTF ML Strategy - Live Trading Quick Start

## ✅ Pre-Flight Checklist

### 1. Verify Configuration
```bash
python test_mtf_config.py
```

**Expected output:**
- ✅ Configuration is valid
- Shows weekday-specific hour exclusions
- IBKR connection details
- Strategy parameters

### 2. Check IBKR Connection
```bash
python scripts\test_ibkr_connection.py
```

**Requirements:**
- ✅ TWS/Gateway running on port 7497 (paper trading)
- ✅ API enabled in TWS settings
- ✅ Account DU1558484 accessible
- ✅ EUR/USD market data subscription active

### 3. Verify Model Exists
```bash
dir models\ml_model_mtf.pkl
```

---

## 🚀 Start Live Trading

### Paper Trading (Recommended First)
```bash
python live\run_live_mtf.py
```

### What Happens:
1. **Loads configuration** from `.env.mtf`
2. **Connects to IBKR** paper account (port 7497)
3. **Starts strategy** with weekday-specific hour exclusions
4. **Warmup period**: ~100 bars (25 hours) before trading starts
5. **Logs everything** to `logs/live_mtf/`

---

## 📊 Monitor Live Trading

### Real-Time Logs
```bash
# Main log
Get-Content logs\live_mtf\live_trading.log -Wait -Tail 50

# Strategy decisions
Get-Content logs\live_mtf\strategy.log -Wait -Tail 50

# Orders
Get-Content logs\live_mtf\orders.log -Wait -Tail 20

# Trades
Get-Content logs\live_mtf\trades.log -Wait -Tail 20
```

### Check Performance
```bash
python scripts\monitor_paper_trading.py
```

---

## ⚙️ Configuration

All settings are in **`.env.mtf`**:

### Key Settings:
```bash
# IBKR Connection
MTF_IB_PORT=7497              # 7497=paper, 7496=live
MTF_IB_ACCOUNT=DU1558484      # Your account

# Strategy
MTF_PREDICTION_THRESHOLD=0.55  # ML confidence
MTF_POSITION_SIZE=100000       # Position size

# Risk Management
MTF_SL_ATR_MULT=1.5           # Stop loss
MTF_TP_ATR_MULT=2.5           # Take profit

# Weekday-Specific Hour Exclusions (OPTIMIZED)
MTF_EXCLUDED_HOURS_MONDAY=1,6,11,16,17,18
MTF_EXCLUDED_HOURS_TUESDAY=1,2,3,5,6,14,15,18
MTF_EXCLUDED_HOURS_WEDNESDAY=3,4,5,8,9,10
MTF_EXCLUDED_HOURS_THURSDAY=2,3,4,7,9,10,11,15,17,18,20,23
MTF_EXCLUDED_HOURS_FRIDAY=1,11,14,17
```

---

## 🎯 Expected Behavior

### During Warmup (First ~25 hours):
- ✅ Connects to IBKR
- ✅ Subscribes to EUR/USD 15-minute bars
- ✅ Accumulates 100 bars for indicator calculation
- ❌ **NO TRADING** during warmup
- 📝 Logs: "Warming up... X/100 bars"

### After Warmup:
- ✅ Calculates MTF features every 15 minutes
- ✅ Gets ML predictions
- ✅ Checks weekday-specific hour exclusions
- ✅ Enters trades when conditions met
- ✅ Manages positions with partial close & trailing stop

### Trading Hours:
- **Active**: 02:00 - 16:00 UTC
- **Excluded**: Weekday-specific (see config)
- **Example**: On Thursday, hours 2,3,4,7,9,10,11,15,17,18,20,23 are excluded

---

## 🛑 Stop Trading

### Graceful Shutdown:
Press **Ctrl+C** in the terminal

**What happens:**
1. Closes all open positions
2. Cancels pending orders
3. Disconnects from IBKR
4. Saves final state

### Emergency Stop:
If Ctrl+C doesn't work:
1. Close TWS/Gateway
2. Kill Python process
3. Manually close positions in TWS if needed

---

## 📈 Performance Expectations

Based on 2-year backtest with weekday-specific exclusions:

| Metric | Value |
|--------|-------|
| **Total P&L** | $61,176 (22 months) |
| **Win Rate** | 51.5% |
| **Avg Trade** | $22.57 |
| **Profit Factor** | 1.42 |
| **Total Trades** | 2,710 |

**Monthly average**: ~$2,780

---

## ⚠️ Important Notes

### 1. Warmup Period
- Strategy needs **100 bars** (~25 hours) to warm up
- **NO TRADES** will execute during warmup
- Be patient - this is normal and necessary

### 2. Weekday-Specific Exclusions
- Different hours excluded per weekday
- Thursday has most exclusions (11 hours)
- Friday has fewest exclusions (4 hours)
- This is **optimized based on 2-year data**

### 3. Paper Trading First
- **ALWAYS test on paper account first**
- Run for **2-4 weeks** minimum
- Verify performance matches backtest
- Check logs for errors

### 4. Market Data
- Requires **real-time EUR/USD data subscription**
- Check TWS market data permissions
- Delayed data may cause issues

### 5. Connection Stability
- Uses **custom IBKR connector patch**
- More stable than default NautilusTrader adapter
- If connection drops, strategy will attempt reconnect

---

## 🔧 Troubleshooting

### "Connection refused"
- ✅ Check TWS/Gateway is running
- ✅ Verify port 7497 (paper) or 7496 (live)
- ✅ Enable API in TWS settings
- ✅ Check firewall

### "Model file not found"
```bash
# Verify model exists
dir models\ml_model_mtf.pkl

# If missing, train model first
python research\train_model.py
```

### "No market data"
- ✅ Check EUR/USD subscription in TWS
- ✅ Verify market data type in `.env.mtf`
- ✅ Check trading hours (Forex trades 24/5)

### "Strategy not trading"
1. Check warmup status in logs
2. Verify current hour is not excluded
3. Check trading session (02:00-16:00 UTC)
4. Verify ML confidence threshold

### "Validation failed"
```bash
# Test configuration
python test_mtf_config.py

# Check for errors in .env.mtf
notepad .env.mtf
```

---

## 📁 Log Files

All logs in `logs/live_mtf/`:

| File | Content |
|------|---------|
| `application.log` | General application logs |
| `live_trading.log` | Live trading events |
| `strategy.log` | Strategy decisions & signals |
| `orders.log` | Order submissions & fills |
| `trades.log` | Trade executions |
| `errors.log` | Errors only |

---

## 🎓 Next Steps

### After Successful Paper Trading:

1. **Analyze Results**
   ```bash
   python scripts\monitor_paper_trading.py
   ```

2. **Compare to Backtest**
   - Win rate should be ~51%
   - Avg trade ~$22
   - Profit factor ~1.4

3. **Switch to Live** (when confident)
   - Update `.env.mtf`: `MTF_IB_PORT=7496`
   - Update account: `MTF_IB_ACCOUNT=U1234567`
   - Start with smaller position size
   - Monitor closely for first week

---

## 🚨 Risk Warning

- **This is algorithmic trading** - losses can occur
- **Start with paper trading** - test thoroughly
- **Monitor regularly** - don't set and forget
- **Have stop-loss** - always use risk management
- **Past performance ≠ future results**

---

## ✅ Ready to Start?

```bash
# 1. Test config
python test_mtf_config.py

# 2. Test IBKR connection
python scripts\test_ibkr_connection.py

# 3. Start paper trading
python live\run_live_mtf.py
```

**Good luck! 🚀**
