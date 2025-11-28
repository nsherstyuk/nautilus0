# How to Check Filtered Trading Signals

Your MTF strategy now logs **ALL signals that were filtered out** so you can see what happened!

## 📊 What Gets Logged

### **1. Hour Exclusions (Weekday-Specific)**
```
[INFO] Bar excluded: Hour 9 excluded for Thursday
```
**Meaning:** A bar arrived during an excluded hour for that specific weekday.

---

### **2. Confidence Too Low**
```
[FILTERED] Confidence too low: 0.523 < 0.55 (prediction=1, time=2025-11-28 09:15)
```
**Meaning:** ML model predicted a BUY (1) but confidence was only 52.3%, below your 55% threshold.

---

### **3. ATR Too Low (Low Volatility)**
```
[FILTERED] ATR too low: 0.00025 < 0.00030 (prediction=1, confidence=0.623, time=2025-11-28 09:30)
```
**Meaning:** ML model predicted BUY with 62.3% confidence, but market volatility was too low (25 pips ATR vs 30 pips minimum).

---

### **4. Cooldown Active**
```
[FILTERED] Cooldown active: 0 days 00:15:00 < 0 days 00:30:00 (prediction=1, confidence=0.623, time=2025-11-28 09:45)
```
**Meaning:** ML model predicted BUY with 62.3% confidence, but only 15 minutes passed since last trade (need 30 minutes).

---

## 🔍 How to Check Your Logs

### **Check Strategy Log for Filtered Signals**
```powershell
# See all filtered signals today
Select-String -Path logs\live_mtf\strategy.log -Pattern "\[FILTERED\]"

# See filtered signals with context
Get-Content logs\live_mtf\strategy.log | Select-String -Pattern "\[FILTERED\]" -Context 2,0

# Count how many signals were filtered by each reason
Select-String -Path logs\live_mtf\strategy.log -Pattern "\[FILTERED\]" | Group-Object Line

# See filtered signals in real-time
Get-Content logs\live_mtf\strategy.log -Wait -Tail 50 | Select-String -Pattern "\[FILTERED\]"
```

---

### **Check Hour Exclusions**
```powershell
# See which hours were excluded
Select-String -Path logs\live_mtf\strategy.log -Pattern "Bar excluded"

# Count exclusions by reason
Select-String -Path logs\live_mtf\strategy.log -Pattern "Bar excluded" | Group-Object Line
```

---

## 📈 Example Analysis

### **Scenario: You saw EMAMA signals on TradingView**

**Step 1: Check if bars arrived during those times**
```powershell
# Check strategy log around 9:15 AM
Get-Content logs\live_mtf\strategy.log | Select-String -Pattern "2025-11-28 09:1"
```

**Step 2: Look for predictions and filters**
```
[INFO] Bar 1764213240000000000: prediction=1, confidence=0.623, ATR=0.00045, mama_diff=0.00123
[FILTERED] Confidence too low: 0.523 < 0.55 (prediction=1, time=2025-11-28 09:15)
```

**Interpretation:**
- ✅ ML model detected the signal (prediction=1 = BUY)
- ❌ But confidence was only 52.3% (below 55% threshold)
- ❌ Signal was filtered out

---

### **Step 3: Check if hour was excluded**
```
[INFO] Bar excluded: Hour 9 excluded for Thursday
```

**Interpretation:**
- ❌ Bar was excluded because hour 9 is in Thursday's exclusion list
- Strategy never even calculated features for this bar
- This is by design based on your 2-year backtest optimization

---

## 🎯 What This Tells You

### **If you see `[FILTERED]` messages:**
- ✅ Strategy **detected** the signal
- ✅ ML model **made a prediction**
- ❌ Signal was **filtered out** by risk management rules

### **If you see `Bar excluded` messages:**
- ❌ Bar was **skipped entirely** due to hour exclusions
- Strategy never calculated features or predictions
- This is intentional based on your backtest optimization

---

## 📊 Quick Stats Commands

```powershell
# Count total predictions made today
Select-String -Path logs\live_mtf\strategy.log -Pattern "prediction=" | Measure-Object

# Count filtered signals today
Select-String -Path logs\live_mtf\strategy.log -Pattern "\[FILTERED\]" | Measure-Object

# Count excluded bars today
Select-String -Path logs\live_mtf\strategy.log -Pattern "Bar excluded" | Measure-Object

# Count actual trades today
Select-String -Path logs\live_mtf\orders.log -Pattern "Order submitted" | Measure-Object

# See filter breakdown
Select-String -Path logs\live_mtf\strategy.log -Pattern "\[FILTERED\]" | 
    ForEach-Object { 
        if ($_.Line -match "Confidence too low") { "Low Confidence" }
        elseif ($_.Line -match "ATR too low") { "Low ATR" }
        elseif ($_.Line -match "Cooldown active") { "Cooldown" }
    } | Group-Object | Sort-Object Count -Descending
```

---

## 🔧 Your Current Filters

From your `.env.mtf` config:

1. **Confidence Threshold:** 0.55 (55%)
2. **Minimum ATR:** 0.0003 (30 pips)
3. **Cooldown:** 30 minutes
4. **Session Hours:** 02:00 - 16:00 UTC
5. **Weekday Exclusions:**
   - **Monday:** Hours 1, 6, 11, 16, 17, 18
   - **Tuesday:** Hours 1, 2, 3, 5, 6, 14, 15, 18
   - **Wednesday:** Hours 3, 4, 5, 8, 9, 10
   - **Thursday:** Hours 2, 3, 4, 7, 9, 10, 11, 15, 17, 18, 20, 23
   - **Friday:** Hours 1, 11, 14, 17

---

## 💡 Next Steps

**If you're seeing TradingView signals that your strategy missed:**

1. **Check the logs** using commands above
2. **Identify why** it was filtered (confidence, ATR, cooldown, hour exclusion)
3. **Decide if you want to adjust** the filters (but remember: these were optimized on 2 years of data!)

**Remember:** Your backtest showed **$61,176 profit** with these filters. Loosening them might increase trades but could reduce profitability! 📊
