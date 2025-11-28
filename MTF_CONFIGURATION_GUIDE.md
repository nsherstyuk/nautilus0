# MTF ML Strategy - Configuration Guide

## Overview

The MTF ML strategy uses a **separate configuration file** (`.env.mtf`) independent from your old strategy's `.env` file.

---

## Configuration Files

| File | Purpose | Used By |
|------|---------|---------|
| **`.env`** | Old MA strategy config | Old backtest & live scripts |
| **`.env.mtf`** | MTF ML strategy config | MTF backtest & live scripts |

**Both files coexist** - no conflicts!

---

## Quick Start

### 1. Test Configuration
```bash
python test_mtf_config.py
```

### 2. Edit Configuration
Open `.env.mtf` and modify any parameters:
```bash
notepad .env.mtf
```

### 3. Run Backtest
```bash
python run_mtf_backtest_detailed.py
```

### 4. Run Live Trading
```bash
python live\run_live_mtf.py
```

---

## Configuration Parameters

### 📡 IBKR Connection
```bash
MTF_IB_HOST=127.0.0.1
MTF_IB_PORT=7497              # 7497=paper, 7496=live
MTF_IB_CLIENT_ID=19           # Different from old strategy (17)
MTF_IB_ACCOUNT=DU1558484
```

### 📊 Backtest Dates
```bash
MTF_BACKTEST_START_DATE=2025-01-01
MTF_BACKTEST_END_DATE=2025-12-31
```

**Examples**:
- Q1 2025: `2025-01-01` to `2025-03-31`
- Q2 2025: `2025-04-01` to `2025-06-30`
- Full 2024: `2024-01-01` to `2024-12-31`

### 🤖 Strategy Parameters
```bash
MTF_MODEL_PATH=models/ml_model_mtf.pkl
MTF_PREDICTION_THRESHOLD=0.55    # Confidence threshold
MTF_POSITION_SIZE=100000         # Position size in base currency
```

### ⚠️ Risk Management
```bash
MTF_SL_ATR_MULT=1.5              # Stop loss = 1.5 × ATR
MTF_TP_ATR_MULT=2.5              # Take profit = 2.5 × ATR
```

### 🎯 Partial Close (Optimized)
```bash
MTF_PARTIAL_CLOSE_ENABLED=true
MTF_PARTIAL_CLOSE_FRACTION=0.5   # Close 50%
MTF_PARTIAL_CLOSE_ATR_MULT=1.5   # At 1.5 × ATR profit
```

### 🕐 Trading Hours
```bash
MTF_SESSION_START=02:00          # UTC time
MTF_SESSION_END=16:00            # UTC time
MTF_EXCLUDED_HOURS=              # Empty = trade all hours
```

**To exclude hours**:
```bash
# Exclude Asian session (0-5 UTC)
MTF_EXCLUDED_HOURS=0,1,2,3,4,5

# Exclude specific hours
MTF_EXCLUDED_HOURS=0,1,23
```

---

## Common Scenarios

### Scenario 1: Test Different Periods

**Q1 2025 Only**:
```bash
MTF_BACKTEST_START_DATE=2025-01-01
MTF_BACKTEST_END_DATE=2025-03-31
```

**Second Half 2025**:
```bash
MTF_BACKTEST_START_DATE=2025-07-01
MTF_BACKTEST_END_DATE=2025-12-31
```

### Scenario 2: More Conservative Settings

```bash
MTF_PREDICTION_THRESHOLD=0.60    # Higher confidence
MTF_POSITION_SIZE=50000          # Smaller size
MTF_SL_ATR_MULT=1.8              # Wider stop loss
```

### Scenario 3: Exclude Low-Profit Hours

After running backtest and analyzing hour performance:
```bash
# Example: Exclude hours 0-5 and 23 (low profit)
MTF_EXCLUDED_HOURS=0,1,2,3,4,5,23
```

### Scenario 4: Paper vs Live Trading

**Paper Trading**:
```bash
MTF_IB_PORT=7497
MTF_IB_ACCOUNT=DU1558484
MTF_POSITION_SIZE=100000
```

**Live Trading** (after successful paper trading):
```bash
MTF_IB_PORT=7496
MTF_IB_ACCOUNT=U1234567
MTF_POSITION_SIZE=50000          # Start smaller
```

---

## Workflow

### 1. Configure
```bash
# Edit .env.mtf
notepad .env.mtf

# Test configuration
python test_mtf_config.py
```

### 2. Backtest
```bash
# Run backtest with current config
python run_mtf_backtest_detailed.py

# Review results in logs/backtest_results/MTF_ML_*/
```

### 3. Analyze
```bash
# Check hour performance
type logs\backtest_results\MTF_ML_*\performance_by_hour.csv

# Check weekday performance
type logs\backtest_results\MTF_ML_*\performance_by_weekday.csv
```

### 4. Optimize
```bash
# Edit .env.mtf based on analysis
# Example: Exclude unprofitable hours
MTF_EXCLUDED_HOURS=0,1,2,23

# Re-run backtest
python run_mtf_backtest_detailed.py
```

### 5. Deploy
```bash
# After successful backtesting, run live
python live\run_live_mtf.py
```

---

## Configuration Validation

The system automatically validates:
- ✅ Model file exists
- ✅ Thresholds are valid (0-1)
- ✅ Position size is reasonable (>1000)
- ✅ ATR multipliers are positive
- ✅ Dates are valid format

**If validation fails**, you'll see specific error messages.

---

## Tips

### 1. Keep Old Config Separate
Your old `.env` file is **untouched**. Both strategies can run independently.

### 2. Version Control
Consider creating multiple config files:
```bash
.env.mtf.conservative  # Conservative settings
.env.mtf.aggressive    # Aggressive settings
.env.mtf.paper         # Paper trading
.env.mtf.live          # Live trading
```

Then copy the one you want:
```bash
copy .env.mtf.paper .env.mtf
```

### 3. Document Changes
Add comments in `.env.mtf`:
```bash
# 2025-11-27: Increased confidence to 0.60 after backtest analysis
MTF_PREDICTION_THRESHOLD=0.60
```

### 4. Test Before Live
**Always**:
1. Test config: `python test_mtf_config.py`
2. Run backtest: `python run_mtf_backtest_detailed.py`
3. Analyze results
4. Paper trade 2-4 weeks
5. Then go live

---

## Troubleshooting

### "Model file not found"
```bash
# Check model path in .env.mtf
MTF_MODEL_PATH=models/ml_model_mtf.pkl

# Verify file exists
dir models\ml_model_mtf.pkl
```

### "Invalid date format"
```bash
# Use YYYY-MM-DD format
MTF_BACKTEST_START_DATE=2025-01-01  # ✅ Correct
MTF_BACKTEST_START_DATE=01/01/2025  # ❌ Wrong
```

### "Configuration not loading"
```bash
# Make sure .env.mtf exists in project root
dir .env.mtf

# Test loading
python test_mtf_config.py
```

---

## Example Configurations

### Conservative (Lower Risk)
```bash
MTF_PREDICTION_THRESHOLD=0.60
MTF_POSITION_SIZE=50000
MTF_SL_ATR_MULT=2.0
MTF_TP_ATR_MULT=3.0
MTF_EXCLUDED_HOURS=0,1,2,3,4,5,23
```

### Aggressive (Higher Risk)
```bash
MTF_PREDICTION_THRESHOLD=0.50
MTF_POSITION_SIZE=150000
MTF_SL_ATR_MULT=1.2
MTF_TP_ATR_MULT=2.0
MTF_EXCLUDED_HOURS=
```

### Optimized (From Backtest)
```bash
MTF_PREDICTION_THRESHOLD=0.55
MTF_POSITION_SIZE=100000
MTF_SL_ATR_MULT=1.5
MTF_TP_ATR_MULT=2.5
MTF_PARTIAL_CLOSE_ENABLED=true
MTF_PARTIAL_CLOSE_FRACTION=0.5
MTF_PARTIAL_CLOSE_ATR_MULT=1.5
```

---

## Summary

✅ **Separate config** - No conflicts with old strategy  
✅ **Easy to modify** - Edit `.env.mtf` file  
✅ **Validated** - Automatic validation on load  
✅ **Flexible** - Test different settings easily  
✅ **Safe** - Test before deploying  

**Start with**: `python test_mtf_config.py`
