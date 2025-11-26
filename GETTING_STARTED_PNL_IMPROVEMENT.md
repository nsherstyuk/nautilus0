# PnL Improvement: Getting Started

## Current Situation

You asked about improving PnL based on suggestions from other LLMs. I've analyzed their proposals and your codebase. Here's what you need to know:

## The Core Issue

**You don't have enough data yet.**

- Your "best" config ($10.9k PnL) was optimized on 2024-2025
- You're missing 2022 and most of 2023
- With only 200 trades, complex multi-factor analysis will produce noise, not signal
- Your aggressive time filter (excluding 19/24 hours some days) is almost certainly overfit

## My Plan vs Other LLMs

### What They Got Right
✅ Logging-driven approach (better than blind grid search)
✅ Using existing indicators first
✅ Focus on trailing 35/15 as baseline

### What They Got Wrong
❌ No train/test separation (will overfit)
❌ Too many features logged at once (200 trades can't support it)
❌ Assuming current results are valid (they're not tested forward)
❌ Complex bucket analysis with insufficient sample size

### What I'm Proposing

**Phase 0: Download Missing Data (DO THIS FIRST)**
- Need 2022-2023 for discovery period
- ~70,000 bars, 15-20 minutes to download
- Already configured in your .env file

**Phase 1: Honest Validation**
- Test your "best" config on 2022-2023 (discovery)
- Compare against simpler baselines
- Prediction: Your aggressive time filter will fail

**Phase 2-5: Systematic Improvement**
- Only AFTER you have honest baseline
- Minimal logging (10 features, not 20+)
- Single-factor analysis with strict statistics
- Accept limits of 200-trade sample size

## Quick Start

### Step 1: Download Data (15-20 minutes)

```powershell
# Option A: Automated script
python phase0_download_data.py

# Option B: Manual
# 1. Ensure IB Gateway/TWS is running
# 2. Run: python data/ingest_historical.py
# 3. Verify: python check_data_coverage_for_validation.py
```

### Step 2: Read the Full Plan

Open `plan_pnl_improvement.md` for complete details.

### Step 3: Test Your Current Config Honestly

Once you have 2022-2023 data:
```powershell
# Test on discovery period (will likely underperform)
python backtest/run_backtest.py --start 2022-01-01 --end 2023-12-31

# Compare to simpler baseline (no aggressive time filter)
# Edit .env: BACKTEST_TIME_FILTER_ENABLED=false
python backtest/run_backtest.py --start 2022-01-01 --end 2023-12-31
```

## Key Files

1. **`plan_pnl_improvement.md`** - Complete implementation plan
2. **`phase0_download_data.py`** - Automated data download
3. **`check_data_coverage_for_validation.py`** - Verify what data you have
4. **`.env`** - Updated with DATA_* configuration

## My Strongest Recommendations

### Do This:
1. ✅ Download 2022-2023 data first
2. ✅ Test current config on 2022-2023 (expect it to fail)
3. ✅ Simplify to robust baseline (trailing 35/15, moderate time filter)
4. ✅ Accept that 200 trades limits what you can validate
5. ✅ Consider multi-instrument if you want real analysis (4× instruments = 800 trades)

### Don't Do This:
1. ❌ Trust your $10.9k result until tested out-of-sample
2. ❌ Run complex bucket analysis with 200 trades
3. ❌ Add more indicators before validating what you have
4. ❌ Optimize on the same period you're testing
5. ❌ Keep aggressive time filter without forward validation

## Expected Outcomes

**Phase 0 (Data Download):**
- ✅ Complete 2022-2025 coverage
- Ready for proper validation

**Phase 1 (Honest Testing):**
- Your current config will likely show <$5k PnL on 2022-2023
- Simpler baseline (less aggressive time filter) will be more stable
- You'll identify a TRUE baseline that works across periods

**Phase 2-5 (Improvement):**
- Find 1-2 simple, robust improvements
- Expect modest gains (10-20%), not 2× jumps
- Higher confidence these gains are real, not overfit

## Bottom Line

**Stop optimizing on 2024-2025 and calling it validated.**

Your path forward:
1. Download 2022-2023 data (Phase 0)
2. Test everything honestly (Phase 1)
3. Simplify to what actually works (Phase 1)
4. Only then look for incremental improvements (Phase 2-5)

This is less exciting than "add magic indicator and double PnL," but it's what actually works with the data you have.

---

Questions? Start with `phase0_download_data.py` and work through the plan.
