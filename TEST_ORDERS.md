# Manual Order Testing Guide

## 🎯 Purpose

Test that orders are properly sent to IBKR and executed without running the full strategy.

## 🚀 Quick Start

### 1. Make Sure TWS/Gateway is Running
- Port 7497 (paper trading)
- API enabled
- Account DU1558484

### 2. Run the Test Script
```bash
python test_manual_trading.py
```

### 3. Wait for Connection
You'll see:
```
✅ Connected to IBKR!
Account: DU1558484
Instrument: EUR/USD.IDEALPRO
```

---

## 📝 Available Commands

### **Buy Order**
```
> buy
```
Places a market buy order for 100,000 EUR/USD

**Custom quantity:**
```
> buy 50000
```

### **Sell Order**
```
> sell
```
Places a market sell order for 100,000 EUR/USD

**Custom quantity:**
```
> sell 50000
```

### **Flatten All Positions**
```
> flatten
```
Closes all open EUR/USD positions

### **Check Status**
```
> status
```
Shows:
- Account balance
- Open positions
- Open orders
- Unrealized P&L

### **Exit**
```
> quit
```

---

## 🧪 Test Sequence

### **Test 1: Basic Order Flow**
```
> status          # Check starting state
> buy 10000       # Small buy order
> status          # Verify position opened
> flatten         # Close position
> status          # Verify position closed
```

### **Test 2: Round Trip**
```
> buy 10000       # Go long
> status          # Check P&L
> sell 20000      # Reverse to short
> status          # Check new position
> flatten         # Close
```

### **Test 3: Multiple Orders**
```
> buy 10000
> buy 10000
> status          # Should show 20,000 position
> flatten
```

---

## ✅ What to Look For

### **In the Script Output:**
- ✅ "Order submitted" messages
- ✅ No error messages
- ✅ Position updates in `status`

### **In TWS/Gateway:**
- ✅ Orders appear in "Orders" tab
- ✅ Fills appear in "Trades" tab
- ✅ Position shows in "Portfolio"

### **In Account:**
- ✅ Balance changes
- ✅ P&L updates
- ✅ Margin usage

---

## ⚠️ Important Notes

### **Paper Trading Only**
- This script uses your `.env` IBKR settings
- Make sure `IB_PORT=7497` (paper account)
- **DO NOT use on live account for testing!**

### **Small Quantities First**
- Start with 10,000 or 20,000
- Verify everything works
- Then test larger sizes

### **Market Hours**
- Forex (EUR/USD) trades 24/5
- Sunday 5pm EST - Friday 5pm EST
- Orders may reject outside hours

### **Order Types**
- This script uses **MARKET orders**
- They execute immediately at current price
- No price control - use small sizes!

---

## 🔍 Troubleshooting

### **"Connection refused"**
- Check TWS/Gateway is running
- Verify port 7497
- Check API is enabled

### **"No open positions to flatten"**
- Normal if no positions open
- Use `status` to check first

### **Orders not filling**
- Check market hours
- Verify instrument is tradeable
- Check TWS error messages

### **"Account not found"**
- Verify account ID in `.env`
- Check TWS is logged into correct account

---

## 📊 Example Session

```bash
$ python test_manual_trading.py

================================================================================
MANUAL TRADING TEST - MTF Strategy
================================================================================

Initializing connection to IBKR...
Starting trading node...

✅ Connected to IBKR!
Account: DU1558484
Instrument: EUR/USD.IDEALPRO

================================================================================
INTERACTIVE MODE
================================================================================

Commands:
  buy [qty]   - Place market buy order (default: 100,000)
  sell [qty]  - Place market sell order (default: 100,000)
  flatten     - Close all positions
  status      - Show account and position status
  quit        - Exit

================================================================================

> status

================================================================================
CURRENT STATUS
================================================================================

💰 Account: INTERACTIVE_BROKERS-DU1558484
   USD: 53679.86 (free: 50180.75)

📊 Open Positions: 0

📝 Open Orders: 0
================================================================================

> buy 10000

📈 Placing BUY order for 10,000 EUR/USD.IDEALPRO...
✅ Order submitted: O-20251127-001-001-1

> status

================================================================================
CURRENT STATUS
================================================================================

💰 Account: INTERACTIVE_BROKERS-DU1558484
   USD: 53679.86 (free: 50170.75)

📊 Open Positions: 1
   P-20251127-001: LONG 10000.0 @ 1.05123
      Unrealized P&L: 2.50 USD

📝 Open Orders: 0
================================================================================

> flatten

🔄 Flattening all positions...
Closing position: P-20251127-001 (side=LONG, qty=10000.0)
✅ Close order submitted: O-20251127-001-001-2

> status

================================================================================
CURRENT STATUS
================================================================================

💰 Account: INTERACTIVE_BROKERS-DU1558484
   USD: 53682.36 (free: 50180.75)

📊 Open Positions: 0

📝 Open Orders: 0
================================================================================

> quit

Exiting...
Stopping trading node...
```

---

## 🎓 What This Tests

✅ **IBKR Connection** - Can connect to TWS/Gateway  
✅ **Order Submission** - Orders reach IBKR  
✅ **Order Execution** - Orders fill correctly  
✅ **Position Tracking** - Positions update in real-time  
✅ **Account Updates** - Balance and P&L update  
✅ **Order Cancellation** - Can close positions  

**If all these work, your live strategy will work too!** 🚀

---

## 🔄 After Testing

Once you've verified orders work:
1. ✅ Flatten all positions
2. ✅ Check account is clean
3. ✅ Exit the script
4. ✅ Ready to run live strategy!

**Your MTF strategy uses the same order execution system!**
