# MTF ML Strategy - Deployment Guide

## Overview
This guide covers deploying the optimized MTF (Multi-Timeframe) ML trading strategy to production.

**Strategy Performance (Backtested Jan-Oct 2025)**:
- Total P&L: $14,555.68 on $100k account (14.6% return)
- Win Rate: 45.1%
- Profit Factor: 1.13
- R/R Ratio: 1.38
- Trade Frequency: ~5 trades/day

---

## Pre-Deployment Checklist

### ✅ 1. Model & Configuration
- [x] MTF model trained (`models/ml_model_mtf.pkl`)
- [x] Optimal configuration set (confidence=0.55, partial close enabled)
- [x] Feature calculation verified against TradingView
- [ ] Model file backed up to safe location
- [ ] Configuration documented

### ✅ 2. Infrastructure
- [ ] IBKR account funded and active
- [ ] TWS or IB Gateway installed and configured
- [ ] API permissions enabled in IBKR account settings
- [ ] Stable internet connection (consider backup)
- [ ] Dedicated machine for trading (not your personal laptop)

### ✅ 3. Data & Connectivity
- [ ] Historical 15-minute EUR/USD data available
- [ ] Real-time data subscription active (IBKR)
- [ ] Network latency acceptable (<100ms to IBKR servers)
- [ ] Firewall configured to allow IBKR connections

### ✅ 4. Risk Management
- [ ] Position sizing configured (default: $100k per trade)
- [ ] Maximum daily loss limit set
- [ ] Maximum number of concurrent positions (default: 1)
- [ ] Emergency stop mechanism in place

### ✅ 5. Monitoring & Logging
- [ ] Log files directory created and writable
- [ ] Alert system configured (email/SMS for critical events)
- [ ] Performance dashboard accessible
- [ ] Trade journal/database ready

---

## Step 1: IBKR Connection Setup

### A. IBKR Account Configuration

1. **Enable API Access**:
   ```
   TWS/IB Gateway → File → Global Configuration → API → Settings
   - ✅ Enable ActiveX and Socket Clients
   - ✅ Read-Only API: NO (we need to place orders)
   - ✅ Download open orders on connection: YES
   - Socket Port: 7497 (paper) or 7496 (live)
   - Master API client ID: Leave blank
   ```

2. **Trusted IP Addresses**:
   ```
   Add your machine's IP address to the trusted list
   (or use 127.0.0.1 for localhost)
   ```

3. **Market Data Subscriptions**:
   ```
   Ensure you have real-time forex data subscription
   EUR/USD is typically included in basic forex package
   ```

### B. Environment Configuration

Create/update `.env` file:
```bash
# IBKR Connection
IB_HOST=127.0.0.1
IB_PORT=7497  # Paper trading (use 7496 for live)
IB_CLIENT_ID=1
IB_ACCOUNT=DU1234567  # Your paper/live account number

# Strategy Settings
STRATEGY_INSTRUMENT=EUR/USD.IDEALPRO
STRATEGY_POSITION_SIZE=100000
STRATEGY_MAX_POSITIONS=1

# Risk Limits
MAX_DAILY_LOSS=5000  # Stop trading if daily loss exceeds this
MAX_POSITION_SIZE=100000

# Logging
LOG_LEVEL=INFO
LOG_TO_FILE=true
```

### C. Test Connection

Run connection test:
```bash
python scripts/test_ibkr_connection.py
```

Expected output:
```
✅ Connected to IBKR
✅ Account: DU1234567
✅ Available funds: $100,000.00
✅ Market data subscription: Active
✅ EUR/USD contract found
```

---

## Step 2: Paper Trading (CRITICAL STEP)

**DO NOT skip this step!** Paper trading validates everything works before risking real money.

### A. Paper Trading Checklist

- [ ] TWS/IB Gateway running in **PAPER TRADING** mode
- [ ] Strategy configured with paper account credentials
- [ ] All monitoring systems active
- [ ] Trade log being recorded

### B. Paper Trading Duration

**Minimum: 2 weeks** (preferably 1 month)

**What to verify**:
1. **Connectivity**: No disconnections or data gaps
2. **Order Execution**: Orders placed and filled correctly
3. **Partial Closes**: 50% closes executed at 1.5× ATR profit
4. **Stop Loss**: SL orders triggered correctly
5. **Take Profit**: TP orders executed as expected
6. **Trailing Stop**: Trailing logic working (if enabled)
7. **Performance**: Returns match backtest expectations (~1.5% per month)

### C. Paper Trading Monitoring Script

Run this daily during paper trading:
```bash
python scripts/monitor_paper_trading.py
```

This will check:
- Number of trades executed
- Win rate vs expected (45%)
- P&L vs expected
- Any errors or warnings in logs
- Order rejection rate

### D. Red Flags to Watch For

**STOP immediately if you see**:
- ❌ Win rate < 35% (significantly below 45%)
- ❌ Frequent order rejections
- ❌ Trades not matching backtest logic
- ❌ Partial closes not executing
- ❌ Data feed interruptions
- ❌ Unexpected position sizes

---

## Step 3: Live Trading Deployment

**Only proceed if paper trading was successful for 2+ weeks**

### A. Pre-Live Checklist

- [ ] Paper trading results reviewed and acceptable
- [ ] All systems tested and working
- [ ] Risk limits configured and tested
- [ ] Emergency stop procedure documented
- [ ] Monitoring alerts configured
- [ ] Initial capital allocated ($100k recommended minimum)

### B. Gradual Rollout Plan

**Week 1: Reduced Size**
```python
position_size = 50000  # 50% of normal size
max_positions = 1
```

**Week 2-4: Normal Size (if Week 1 successful)**
```python
position_size = 100000  # Full size
max_positions = 1
```

**Month 2+: Consider scaling**
```python
# Only if consistently profitable
position_size = 150000  # 1.5x size
max_positions = 1  # Still keep at 1 for safety
```

### C. Live Trading Startup

1. **Start TWS/IB Gateway** (LIVE mode)
2. **Verify account balance** and available funds
3. **Start strategy**:
   ```bash
   python run_live_mtf_strategy.py
   ```
4. **Monitor first trade closely**
5. **Verify all order types execute correctly**

### D. Daily Monitoring Routine

**Morning (before market open)**:
- [ ] Check overnight positions
- [ ] Review previous day's trades
- [ ] Verify system health
- [ ] Check for any alerts/errors

**During trading hours**:
- [ ] Monitor open positions
- [ ] Watch for unusual behavior
- [ ] Check execution quality
- [ ] Verify partial closes executing

**Evening (after market close)**:
- [ ] Review day's performance
- [ ] Check logs for errors
- [ ] Update trade journal
- [ ] Calculate daily P&L

---

## Step 4: Monitoring & Logging Setup

### A. Real-Time Monitoring Dashboard

Create a simple dashboard that shows:
```
Current Status:
- Strategy: RUNNING / STOPPED
- Open Positions: 1 LONG EUR/USD @ 1.1500
- Unrealized P&L: +$150.00
- Daily P&L: +$450.00
- Total Trades Today: 3
- Win Rate Today: 66.7%

Recent Trades:
- 14:30 LONG EUR/USD @ 1.1500 → OPEN
- 12:15 SHORT EUR/USD @ 1.1520 → CLOSED +$180 (TP)
- 09:45 LONG EUR/USD @ 1.1480 → CLOSED +$270 (TP)

System Health:
- IBKR Connection: ✅ CONNECTED
- Data Feed: ✅ ACTIVE
- Last Bar: 15:45 (15m)
- Model Loaded: ✅ ml_model_mtf.pkl
```

### B. Logging Configuration

Logs should capture:
```python
# logs/strategy_YYYYMMDD.log
[2025-11-27 14:30:15] INFO: Bar received: EUR/USD 15m close=1.1500
[2025-11-27 14:30:15] INFO: Features calculated: confidence=0.58
[2025-11-27 14:30:15] INFO: Signal: BUY (confidence=0.58 > 0.55)
[2025-11-27 14:30:16] INFO: Order placed: BUY 100000 EUR/USD @ 1.1500
[2025-11-27 14:30:16] INFO: SL=1.1485, TP=1.1525
[2025-11-27 14:30:17] INFO: Order filled: BUY 100000 @ 1.1500
```

### C. Alert System

Configure alerts for:
```python
CRITICAL_ALERTS = [
    "IBKR connection lost",
    "Order rejected",
    "Daily loss limit exceeded",
    "Position size exceeded limit",
    "Model prediction error",
    "Data feed interrupted"
]

WARNING_ALERTS = [
    "Win rate below 40% (last 20 trades)",
    "Unusual market volatility",
    "Partial close failed",
    "Trailing stop not updating"
]
```

---

## Step 5: How to Verify Live Trading is Working

### A. First Trade Verification

**When the first trade executes, verify**:

1. **Entry**:
   ```
   ✅ Trade opened at correct price
   ✅ Position size = 100,000 units
   ✅ Stop loss order placed at entry - (1.5 × ATR)
   ✅ Take profit order placed at entry + (2.5 × ATR)
   ✅ Logged correctly
   ```

2. **Partial Close** (when profit reaches 1.5× ATR):
   ```
   ✅ 50% of position closed automatically
   ✅ Remaining 50% still open
   ✅ Stop loss moved to breakeven (if configured)
   ✅ Logged correctly
   ```

3. **Exit**:
   ```
   ✅ Position closed at SL or TP
   ✅ P&L calculated correctly
   ✅ Cooldown period activated (30 minutes)
   ✅ Logged correctly
   ```

### B. Comparison with Backtest

**After 1 week of live trading, compare**:

| Metric | Backtest | Live | Status |
|--------|----------|------|--------|
| Trades/Day | ~5 | ? | ✅/❌ |
| Win Rate | 45% | ? | ✅/❌ |
| Avg Win | $182 | ? | ✅/❌ |
| Avg Loss | -$132 | ? | ✅/❌ |
| Long/Short | 53%/47% | ? | ✅/❌ |

**Acceptable deviation**: ±10% for first week

### C. Common Issues & Solutions

**Issue 1: No trades executing**
```
Possible causes:
- Confidence threshold too high
- ATR threshold not met
- Cooldown period active
- Data feed issue

Solution:
- Check logs for "Skipping trade" messages
- Verify bar data is being received
- Check feature calculation
```

**Issue 2: Orders rejected**
```
Possible causes:
- Insufficient margin
- Invalid order size
- Market closed
- API permissions

Solution:
- Check IBKR account status
- Verify order parameters
- Check trading hours
```

**Issue 3: Partial closes not executing**
```
Possible causes:
- Profit target not reached
- Order modification failed
- Position tracking error

Solution:
- Check position monitoring logic
- Verify ATR calculation
- Review order modification code
```

---

## Step 6: Emergency Procedures

### A. Emergency Stop

**If something goes wrong, immediately**:

1. **Stop the strategy**:
   ```bash
   # Press Ctrl+C in terminal
   # Or run:
   python scripts/emergency_stop.py
   ```

2. **Close all positions manually** in TWS

3. **Review logs** to understand what happened

4. **Do NOT restart** until issue is identified and fixed

### B. Circuit Breakers

**Auto-stop triggers** (implement these):
```python
# Daily loss limit
if daily_pnl < -5000:
    stop_strategy()
    send_alert("Daily loss limit exceeded")

# Win rate degradation
if win_rate_last_20_trades < 0.30:
    stop_strategy()
    send_alert("Win rate below 30%")

# Connection issues
if connection_lost_count > 3:
    stop_strategy()
    send_alert("Multiple connection failures")
```

---

## Step 7: Ongoing Maintenance

### A. Weekly Tasks
- [ ] Review performance vs backtest
- [ ] Check for any errors/warnings
- [ ] Verify model is still performing
- [ ] Update trade journal

### B. Monthly Tasks
- [ ] Full performance analysis
- [ ] Compare live vs backtest metrics
- [ ] Check for model drift
- [ ] Review risk parameters
- [ ] Update documentation

### C. Quarterly Tasks
- [ ] **Retrain model** on latest data
- [ ] Re-run optimization tests
- [ ] Update strategy if needed
- [ ] Review and adjust position sizing

### D. Model Retraining

**When to retrain**:
- Every 3 months (scheduled)
- If win rate drops below 40% for 2+ weeks
- After major market regime change
- If Sharpe ratio degrades significantly

**Retraining process**:
```bash
# 1. Download latest data
python data/ingest_historical.py

# 2. Retrain model
python research/train_model_mtf.py

# 3. Backtest new model
python run_ml_backtest_mtf_simple.py

# 4. If performance acceptable, deploy
cp models/ml_model_mtf.pkl models/ml_model_mtf_backup.pkl
# Restart strategy with new model
```

---

## Appendix A: File Structure

```
nautilus0/
├── models/
│   ├── ml_model_mtf.pkl          # Current production model
│   └── ml_model_mtf_backup.pkl   # Previous version
├── strategies/
│   ├── ml_strategy_mtf.py        # MTF strategy implementation
│   └── ml_strategy_config.py     # Configuration
├── config/
│   └── ml_strategy_mtf_config.py # Optimized config
├── logs/
│   ├── strategy_20251127.log     # Daily strategy logs
│   └── trades_20251127.csv       # Trade journal
├── scripts/
│   ├── test_ibkr_connection.py   # Connection test
│   ├── monitor_paper_trading.py  # Paper trading monitor
│   └── emergency_stop.py         # Emergency stop script
└── .env                          # Environment variables
```

---

## Appendix B: Support & Resources

**NautilusTrader Documentation**:
- https://nautilustrader.io/docs/

**IBKR API Documentation**:
- https://interactivebrokers.github.io/tws-api/

**Emergency Contacts**:
- Your broker support
- System administrator
- Strategy developer (you!)

---

## Final Checklist Before Going Live

- [ ] Backtested successfully (✅ Done - 14.6% return)
- [ ] Paper traded for 2+ weeks
- [ ] All monitoring systems working
- [ ] Emergency procedures documented
- [ ] Risk limits configured
- [ ] IBKR connection stable
- [ ] Model file backed up
- [ ] Configuration documented
- [ ] Trade journal ready
- [ ] Alert system configured
- [ ] **You understand the risks**
- [ ] **You're comfortable with potential losses**
- [ ] **You have a plan to handle drawdowns**

---

**Remember**: 
- Start small (50% position size)
- Monitor closely for first month
- Don't panic on first losing streak
- Trust the process (45% win rate means 55% losses!)
- Keep detailed records
- Review and adjust as needed

**Good luck! 🚀**
