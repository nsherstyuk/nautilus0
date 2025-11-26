# PnL Improvement Plan - Statistical Discipline Version

## Executive Summary

**Current State:**
- Best config: Trailing 35/15, $10.9k PnL, 207 trades (2024-2025)
- Sample size: ~200 trades is TOO SMALL for complex multi-factor analysis
- **Data coverage: Missing 2022 and most of 2023** - Need to download first
- Risk: Existing optimizations (time filters, trailing params) likely overfit to 2024-2025

**Core Problem:** 
With 200 trades, you can validate at most 1-2 simple rules. Complex bucket analysis across ADX/ATR/Structure/Time will produce noise, not signal.

**Recommendation:**
Take a hybrid approach: (1) download historical data, (2) minimal logging for simple insights, (3) forward-walk validation, (4) accept that major improvements require more data or simpler strategy.

---

## Phase 0: Data Ingestion (COMPLETED)

### 0.1 Current Data Coverage

**Status:** ✅ Data is already present.
- **Range:** 2021-12-29 to 2025-11-04
- **Total Bars:** 100,973 (15-minute bars)
- **Coverage:** Covers full Discovery (2022-2023), Validation (2024), and Forward (2025) periods.

**Action:** Skipped ingestion. Proceeding to Phase 1.

### 0.2 (Skipped) Download Historical Data
...existing code...

**Step 1: Update .env for data ingestion**

Add these to your `.env` file:
```dotenv
# Data Ingestion Configuration
DATA_SYMBOLS=EUR/USD
DATA_START_DATE=2022-01-01
DATA_END_DATE=2023-12-31
DATA_BAR_SPECS=15-MINUTE-MID
```

**Step 2: Ensure IB Gateway is running**
- Your live trading system can stay running
- Data ingestion uses a different client ID
- Check: IB Gateway/TWS is on, connection works

**Step 3: Run ingestion**
```powershell
python data/ingest_historical.py
```

**What happens:**
- Script automatically chunks 2022-2023 into 60-day chunks (for 15-min bars)
- Downloads ~17,520 bars per chunk
- Total: ~730 days × 96 bars/day ≈ 70,000 bars for 2022-2023
- Time estimate: 15-20 minutes (with IBKR rate limits)

**Step 4: Verify coverage**
```powershell
python check_data_coverage_for_validation.py
```

Should show:
- Discovery (2022-2023): ✅ COMPLETE
- Validation (2024): ✅ COMPLETE  
- Forward (2025): ✅ COMPLETE

### 0.3 Chunking Details (Already Implemented)

Your `ingest_historical.py` already has smart chunking:
- **15-minute bars: 60-day chunks** (safe, won't timeout)
- **Automatic overlap:** Prevents gaps at boundaries
- **Progress logging:** You'll see each chunk download

The script calculates:
```python
_calculate_chunk_size_days('15-MINUTE-MID') → 60 days
```

For 2022-2023 (730 days):
- ~12 chunks of 60 days each
- Each chunk: ~5,760 bars (60 days × 96 bars/day)
- Total: ~70,000 bars

### 0.4 Troubleshooting

**If download fails:**
1. Check IB Gateway connection: `IB_HOST=127.0.0.1`, `IB_PORT=7497`
2. Verify market data subscription (need forex permissions)
3. Check logs: `logs/data_ingestion.log`
4. IBKR rate limits: Script already handles pacing (10 requests/min)

**If data looks incomplete:**
```powershell
python check_data_coverage_for_validation.py
```
Shows exact coverage and gaps.

---

## Phase 1: True Baseline & Forward Walk Setup (Week 2)

### 1.1 Establish Honest Baseline

**Goal:** Find what ACTUALLY works out-of-sample

**Steps:**

1. **Define periods properly:**
   - Discovery: 2022-01-01 → 2023-12-31 (2 years)
   - Validation: 2024-01-01 → 2024-12-31 (1 year)  
   - Forward: 2025-01-01 → 2025-10-30 (10 months, TRUE hold-out)

2. **Test your "best" configs in proper order:**
   ```
   Config A: Trailing 35/15 + aggressive time filter (current best)
   Config B: Trailing 35/15 + MODERATE time filter (only exclude worst 2-3 hours/day)
   Config C: Trailing 35/15 + NO time filter
   ```

3. **Run matrix:**
   - Train each on Discovery period (2022-2023)
   - Pick best on Validation period (2024)
   - Test ONCE on Forward period (2025)

4. **Expected outcome:**
   - Config A (aggressive time filter) will likely FAIL forward
   - Config B or C will be more stable
   - This is your TRUE baseline

**Why this matters:** Your current $10.9k is trained on 2024-2025. It's not a valid baseline until tested forward.

---

## Phase 2: Minimal Feature Logging (Week 2)

### 2.1 Log Only 10 Features (Not 20+)

For each trade, capture:

**Entry Context (6 features):**
1. `hour_utc` - 0-23
2. `adx_value` - Current ADX
3. `atr_pips` - Current ATR in pips
4. `dist_to_swing_high_pips` - For longs (NaN for shorts)
5. `dist_to_swing_low_pips` - For shorts (NaN for longs)
6. `fast_slow_sep_pips` - Fast MA - Slow MA separation

**Exit Result (4 features):**
7. `pnl_pips` - Realized P&L in pips
8. `duration_hours` - Trade duration
9. `exit_reason` - SL/TP/TRAIL/TIME
10. `max_adverse_excursion_pips` - Worst drawdown during trade

### 2.2 Implementation

**File: `strategies/moving_average_crossover.py`**

Add method:
```python
def _log_trade_features(self, position_id, direction, entry_price):
    """Capture feature snapshot at entry"""
    features = {
        'position_id': position_id,
        'timestamp': self.clock.timestamp_ns(),
        'hour_utc': datetime.utcfromtimestamp(...).hour,
        'adx_value': self._adx_value if hasattr(self, '_adx_value') else None,
        'atr_pips': self._current_atr * 10000 if self._current_atr else None,
        'dist_to_swing_high_pips': self._calc_dist_to_swing_high(entry_price),
        'dist_to_swing_low_pips': self._calc_dist_to_swing_low(entry_price),
        'fast_slow_sep_pips': abs(self._current_fast - self._current_slow) * 10000,
        'direction': direction,
    }
    self._trade_features[position_id] = features
```

Call from `on_bar()` when opening position, finalize on exit.

Output: `logs/backtest_results/<run>/trade_features.csv`

---

## Phase 3: Simple Analysis Only (Week 3)

### 3.1 Statistical Discipline Rules

**Rule 1: Minimum 30 trades per bucket**
- Don't trust any pattern with <30 trades
- With 200 total trades, you can test maybe 4-5 buckets maximum

**Rule 2: Single-factor analysis first**
- Test ONE variable at a time (ADX alone, ATR alone, hour alone)
- No multi-way interactions until you have 500+ trades

**Rule 3: Bonferroni correction**
- If testing 5 hypotheses, require p<0.01 (not p<0.05)
- Or use bootstrap resampling for robustness

### 3.2 Analysis Script

Create `analyze_trade_features_simple.py`:

```python
import pandas as pd
import numpy as np
from scipy import stats

def analyze_single_factor(df, feature, thresholds):
    """Test if feature split predicts PnL"""
    results = []
    for threshold in thresholds:
        low = df[df[feature] < threshold]
        high = df[df[feature] >= threshold]
        
        if len(low) < 30 or len(high) < 30:
            continue  # Skip insufficient sample
            
        # T-test
        t_stat, p_value = stats.ttest_ind(low['pnl_pips'], high['pnl_pips'])
        
        results.append({
            'feature': feature,
            'threshold': threshold,
            'low_n': len(low),
            'low_mean_pnl': low['pnl_pips'].mean(),
            'high_n': len(high),
            'high_mean_pnl': high['pnl_pips'].mean(),
            'p_value': p_value,
            'significant': p_value < 0.01  # Bonferroni-adjusted
        })
    
    return pd.DataFrame(results)

# Test each feature
test_features = {
    'adx_value': [15, 20, 25],
    'atr_pips': [5, 10, 15],
    'hour_utc': [2, 6, 10, 14, 18, 22],
    'dist_to_swing_high_pips': [5, 10, 15],
}

for feature, thresholds in test_features.items():
    print(f"\n=== {feature} ===")
    print(analyze_single_factor(df, feature, thresholds))
```

**Key point:** Only trust results with:
- p < 0.01 (strict threshold)
- Both buckets N ≥ 30
- Effect size > 20 pips difference in mean PnL

---

## Phase 4: Implement AT MOST 1-2 Rules (Week 4)

### 4.1 Decision Tree

**IF analysis shows strong, simple pattern:**

Example patterns that might emerge:
- "ADX < 15: mean PnL = -15 pips (N=45), ADX ≥ 15: mean PnL = +25 pips (N=155), p=0.003"
  → Implement: `STRATEGY_ADX_MIN_FILTER_ENABLED=true, MIN_ADX=15`

- "Hour in [0,1,2,23]: mean PnL = -30 pips (N=38), Other hours: +18 pips (N=169), p=0.001"
  → Simplify time filter to just exclude dead hours (not 19/24)

**IF analysis shows NO strong pattern:**
- Accept that 200 trades isn't enough
- Keep current trailing 35/15 baseline (simplest version)
- Focus on increasing sample size (more instruments, longer time, or accept slower learning)

### 4.2 Validation Protocol

For any rule that passes discovery (2022-2023):

1. **Implement as toggle** in config
2. **Run on validation** (2024): Must maintain or improve PnL
3. **Run on forward** (2025): Must not degrade >10%
4. **Only then promote** to baseline

---

## Phase 5: Long-Term Data Strategy (Ongoing)

### 5.1 Options to Get More Data

**Option A: Multi-Instrument (Recommended)**
- Apply same strategy to EUR/USD, GBP/USD, USD/JPY, AUD/USD
- Same parameters, just different instruments
- 4 instruments × 200 trades = 800 trades
- Now you can do serious multi-factor analysis

**Option B: Higher Frequency**
- Move to 5-minute bars (instead of 15-min)
- Will generate 3x more trades, but different dynamics
- Requires re-optimization of all parameters

**Option C: Accept Simplicity**
- With 200 trades, accept you can only validate simple strategies
- Focus on robustness, not complexity
- Simpler = less overfitting = better forward performance

### 5.2 What NOT To Do

❌ **Don't** run 50 backtests looking for patterns in 200 trades
❌ **Don't** trust complex multi-factor rules (ADX AND ATR AND Structure)
❌ **Don't** use the same period for optimization and validation
❌ **Don't** add regime detection / structure filter / min-hold / etc. until you validate simpler baseline forward

---

## My Specific Recommendations for YOU

### Immediate Actions (Next 2 Weeks)

1. **Validate your $10.9k config honestly:**
   ```
   python backtest/run_backtest.py --start 2022-01-01 --end 2023-12-31  # Discovery
   python backtest/run_backtest.py --start 2024-01-01 --end 2024-12-31  # Validation
   python backtest/run_backtest.py --start 2025-01-01 --end 2025-10-30  # Forward
   ```
   
2. **Compare against SIMPLE baseline:**
   - Same periods with ONLY trailing 35/15
   - NO time filter (or just exclude 0-2, 23 UTC)
   - NO partial closes yet
   - See if complexity actually helps

3. **Implement minimal logging** (10 features only)

4. **Run simple single-factor analysis** with strict stats

### Medium Term (1-2 Months)

5. **If current config fails forward:**
   - Simplify drastically
   - Keep trailing, remove aggressive time filters
   - Accept lower backtest PnL for better forward stability

6. **If current config passes forward:**
   - Add minimal logging
   - Look for ONE clear improvement (e.g., ADX filter)
   - Validate it the same way

### Long Term (3-6 Months)

7. **Expand to multi-instrument** if you want complex analysis
8. **Build proper walk-forward testing** framework
9. **Accept that with current data, you're near the limit** of what you can reliably improve

---

## Bottom Line

**The other LLMs' plans are directionally correct but statistically naive.**

With 200 trades:
- ✅ You CAN test 1-2 simple rules
- ❌ You CANNOT do bucket analysis across 5+ features
- ⚠️ Your current "best" config is likely overfit

**My advice:**
1. First validate what you have out-of-sample (2025 data)
2. Simplify if it fails forward
3. Add logging and test ONE factor at a time
4. Don't expect miracles from 200 trades
5. Consider multi-instrument if you want real statistical power

The logging approach is good, but implement it with statistical discipline or you'll fool yourself.
