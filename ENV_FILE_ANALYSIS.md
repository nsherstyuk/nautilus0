# .env File Analysis

## Issue: Backtest Results .env File is Incomplete

You're correct - the `.env` file saved in backtest results folders is **NOT a complete .env file**. It only saves the parameters that were actually used in the backtest, not all possible configuration options.

## What IS Saved in Backtest Results

Looking at `backtest/run_backtest.py` lines 653-760, the saved `.env` file includes:

### ✅ Saved Parameters:
- Basic backtest parameters (symbol, dates, venue, bar_spec, periods, trade size, capital)
- Risk management (stop loss, take profit, trailing stops)
- Market regime detection parameters (if enabled)
- Strategy filters (crossover threshold, DMI, Stochastic, Trend, RSI, Volume, ATR)
- Time filter settings
- Entry timing settings (if enabled)

### ❌ NOT Saved:
- IBKR connection settings (IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID)
- IBKR chunking configuration (IBKR_ENABLE_CHUNKING, IBKR_REQUEST_DELAY_SECONDS, etc.)
- Comments and documentation
- Default values for disabled features
- Other environment variables not directly used by the backtest

## Why This Matters

If you try to restore a backtest by copying its `.env` file, you'll be missing:
1. IBKR connection settings (needed for data ingestion)
2. Other system-level configuration
3. Documentation/comments explaining what each parameter does

## Solution: Use `.env.best` Instead

The `reconstruct_best_env.py` script creates a **complete** `.env` file with:
- ✅ All backtest parameters from the best result
- ✅ All IBKR settings
- ✅ All comments and documentation
- ✅ All default values

**To use it:**
```bash
python reconstruct_best_env.py
copy .env.best .env
```

## Historical Data Coverage

✅ **GOOD NEWS**: Your historical data **fully covers** the backtest period!

**Data Available:**
- **1-MINUTE-MID-EXTERNAL**: 774,348 bars (Dec 27, 2023 - Nov 4, 2025) ✅
- **2-MINUTE-MID-EXTERNAL**: 344,462 bars (Dec 27, 2023 - Nov 4, 2025) ✅
- **15-MINUTE-MID-EXTERNAL**: 51,624 bars (Dec 27, 2023 - Nov 4, 2025) ✅

**Backtest Period Required:** 2024-01-01 to 2024-12-31

**Result:** All required timeframes have complete coverage for the entire backtest period! ✅

## Summary

1. ✅ Historical data covers the full backtest period (2024-01-01 to 2024-12-31)
2. ✅ All required bar types (1-min, 2-min, 15-min) are available
3. ⚠️ Backtest results `.env` files are incomplete (by design)
4. ✅ Use `.env.best` (from `reconstruct_best_env.py`) for a complete configuration

