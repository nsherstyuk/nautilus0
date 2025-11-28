# MTF ML Strategy - Quick Start Guide

## ✅ What's Been Created

Your MTF ML live trading system is ready! Here's what we built:

### **New Files (Your old system is untouched)**
```
✅ live/run_live_mtf.py          - MTF live trading runner
✅ config/live_config_mtf.py     - MTF configuration
✅ strategies/ml_strategy_mtf.py - MTF strategy (already existed)
✅ models/ml_model_mtf.pkl       - Trained model (already existed)
✅ DEPLOYMENT_GUIDE.md           - Full deployment guide
✅ MTF_LIVE_TRADING_SETUP.md     - Technical setup guide
```

### **Existing Files (Unchanged)**
```
✅ live/run_live.py              - Your old MA strategy (UNTOUCHED)
✅ config/live_config.py         - Old config (UNTOUCHED)
✅ patches/                      - IBKR connector (SHARED by both)
```

---

## 🚀 Quick Start (Paper Trading)

### Step 1: Verify Prerequisites

```bash
# 1. Check model exists
dir models\ml_model_mtf.pkl

# 2. Check TWS/Gateway is running (paper trading mode)
# Port 7497 for paper trading
```

### Step 2: Test IBKR Connection

```bash
python scripts\test_ibkr_connection.py
```

**Expected output**:
```
✅ Connected to IBKR
✅ Account: DU1234567 (paper account)
✅ EUR/USD contract found
```

### Step 3: Run MTF Strategy (Paper Trading)

```bash
python live\run_live_mtf.py
```

**What will happen**:
1. ✅ Connects to IBKR (using your proven patched connector)
2. ✅ Loads MTF ML model
3. ✅ Subscribes to 15-minute EUR/USD bars
4. ✅ Attempts historical backfill (100 bars)
5. ✅ Starts calculating features and making predictions
6. ✅ Executes trades when confidence > 0.55

---

## 📊 What to Monitor

### First 5 Minutes
Watch the logs for:
```
[INFO] Starting MTF ML live trading system...
[INFO] ML Model: models/ml_model_mtf.pkl
[INFO] Prediction threshold: 0.55
[INFO] Connected to IBKR
[INFO] MTF strategy requires 100 bars (25.0 hours ≈ 1.0 days) to warm up
[INFO] Backfill successful: retrieved 100 bars
[INFO] Historical bars fed to strategy successfully
```

### During Warmup (if backfill fails)
```
[INFO] Bar received: EUR/USD 15m close=1.1500
[INFO] Warmup: 45/100 bars collected
```

### When Ready
```
[INFO] Features calculated: 10 features
[INFO] Signal: BUY (confidence=0.58 > 0.55)
[INFO] Order placed: BUY 100000 EUR/USD @ 1.1500
```

---

## 🎯 Expected Performance (from backtest)

| Metric | Target |
|--------|--------|
| **Win Rate** | ~45% |
| **R/R Ratio** | ~1.38 |
| **Trades/Day** | ~5 |
| **Monthly Return** | ~1.5% |
| **Partial Closes** | ~44% of trades |

---

## 🔍 Monitoring Commands

### View Live Logs
```bash
# Main strategy log
tail -f logs\live_mtf\strategy.log

# All logs
tail -f logs\live_mtf\live_trading.log
```

### Check Paper Trading Performance (after a few days)
```bash
python scripts\monitor_paper_trading.py
```

---

## ⚠️ Important Notes

### 1. Paper Trading First!
- **DO NOT** run live trading until paper trading is successful for 2-4 weeks
- Paper account uses port 7497
- Live account uses port 7496

### 2. Warmup Period
- Strategy needs **100 bars** (25 hours ≈ 1 day)
- If backfill works: Ready immediately
- If backfill fails: Wait 1 day for natural warmup
- **No trades** will execute during warmup

### 3. Client ID
- MTF strategy uses client_id from your `.env` file
- If running both strategies simultaneously, they need different client IDs
- Edit `.env` or config to use client_id=3 for MTF (if old system uses 1)

### 4. Position Sizing
- Default: 100,000 units ($100k notional)
- Adjust in `config/live_config_mtf.py` if needed
- Start with smaller size for testing (e.g., 50,000)

---

## 🛠️ Configuration

### Default Settings (Optimized from backtest)
```python
# In config/live_config_mtf.py
position_size = 100000
prediction_threshold = 0.55  # Confidence threshold
sl_atr_mult = 1.5            # Stop loss
tp_atr_mult = 2.5            # Take profit
partial_close_enabled = True  # Close 50% at 1.5×ATR
```

### To Modify Settings
Edit `config/live_config_mtf.py`:
```python
# Example: Reduce position size for testing
position_size = 50000  # Half size

# Example: Increase confidence threshold
prediction_threshold = 0.60  # More conservative
```

---

## 🚨 Troubleshooting

### Issue: "Model file not found"
```bash
# Solution: Verify model exists
dir models\ml_model_mtf.pkl

# If missing, retrain:
python research\train_model_mtf.py
```

### Issue: "Connection failed"
```bash
# Solution: Check TWS/Gateway
# 1. Is it running?
# 2. Is API enabled? (File → Global Configuration → API → Settings)
# 3. Is port correct? (7497 for paper, 7496 for live)
# 4. Is your IP trusted?
```

### Issue: "No trades executing"
```
Possible causes:
1. Still in warmup period (wait for 100 bars)
2. Confidence threshold not met (check logs)
3. ATR too low (market too quiet)
4. Cooldown active (30 minutes between trades)

Solution: Check logs for "Skipping trade" messages
```

### Issue: "Feature calculation failed"
```
Possible causes:
1. Not enough bars yet (< 100)
2. Missing indicator data
3. NaN values in features

Solution: Wait for more bars, check logs for specific error
```

---

## 📈 Next Steps

### Week 1: Initial Testing
- [ ] Run MTF strategy in paper trading
- [ ] Verify first trade executes correctly
- [ ] Check partial close works (at 1.5×ATR profit)
- [ ] Monitor logs daily

### Week 2-4: Performance Validation
- [ ] Run `monitor_paper_trading.py` daily
- [ ] Compare with backtest expectations
- [ ] Check win rate (~45%)
- [ ] Verify R/R ratio (~1.38)

### After 2-4 Weeks: Decision Point
If paper trading is successful:
- [ ] Review all trades
- [ ] Confirm performance matches backtest
- [ ] Read DEPLOYMENT_GUIDE.md for live trading steps
- [ ] Start live trading with reduced size (50%)

---

## 📞 Support

### Log Files
```
logs/live_mtf/
├── live_trading.log    # Main log
├── strategy.log        # Strategy decisions
├── orders.log          # Order execution
├── trades.log          # Trade results
└── errors.log          # Errors only
```

### Documentation
- `DEPLOYMENT_GUIDE.md` - Full deployment process
- `MTF_LIVE_TRADING_SETUP.md` - Technical details
- `README.md` - Project overview

---

## ✅ Pre-Flight Checklist

Before running:
- [ ] TWS/Gateway running (paper mode, port 7497)
- [ ] API enabled in TWS settings
- [ ] Model file exists (`models/ml_model_mtf.pkl`)
- [ ] `.env` file configured with IBKR credentials
- [ ] Paper trading account funded
- [ ] Logs directory writable

---

**You're ready to go! Start with:**
```bash
python live\run_live_mtf.py
```

**Good luck! 🚀**

---

## 🔄 Switching Between Strategies

### Run Old Strategy (Moving Average)
```bash
python live\run_live.py
```

### Run New Strategy (MTF ML)
```bash
python live\run_live_mtf.py
```

### Run Both (Advanced - requires different client IDs)
```bash
# Terminal 1
python live\run_live.py

# Terminal 2 (edit config to use client_id=3 first)
python live\run_live_mtf.py
```

---

**Remember**: Your old system is completely untouched. You can always go back to it!
