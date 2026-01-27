# Position Sizing Strategy - Action Plan

**Created:** January 26, 2026
**Status:** Implementation Phase
**Goal:** Implement month-based hour×weekday exclusions and position size multipliers based on 2-year cross-validated patterns

---

## Background

Analysis of 25 months (2024-01 through 2026-01) with 3,605 trades revealed:
- **2 consistently negative patterns** (2+ years negative, WR<45%, ≥5 trades, PnL<-$30):
  - October hour 4 (4am EST) Friday: 5 trades, 20% WR, -$67.79
  - November hour 20 (8pm EST) Thursday: 6 trades, 16.7% WR, -$66.49
- **13 consistently positive patterns** (2+ years positive, WR>60%, ≥5 trades, PnL>$50)
- **10 exceptional gems** (100% WR in single year, 5+ trades - not cross-validated)

**Key Insight:** Positive patterns significantly outnumber negative patterns, suggesting position sizing (increasing size during proven profitable times) is more valuable than pure exclusions.

---

## Phase 1: Code Implementation (1-2 hours)

### Step 1.1: Extend Config System ✅
Add month-based exclusion and position sizing multiplier support to config:
- `MTF2_MONTH_01_EXCLUDED_HOUR_WEEKDAY_PAIRS` through `MTF2_MONTH_12_EXCLUDED_HOUR_WEEKDAY_PAIRS`
- `MTF2_MONTH_01_BOOSTED_HOUR_WEEKDAY_PAIRS` through `MTF2_MONTH_12_BOOSTED_HOUR_WEEKDAY_PAIRS`
- `MTF2_POSITIVE_PATTERN_SIZE_MULTIPLIER` (default 1.3)

Files to modify:
- `config/config_loader_mtf_v2.py` - add parsing logic
- `.env.mtf_v2` - add new variables with defaults

### Step 1.2: Modify Strategy Sizing Logic ✅
Update `strategies/ml_strategy_mtf_v2_entry_confirmed.py`:
- Add month-based hour×weekday checking (not season-based)
- Implement 3-tier sizing: 0x (excluded), 1.0x (normal), 1.3x-1.5x (boosted)
- Log sizing decisions for audit trail

Key changes:
```python
def _should_exclude_trade(self, bar_timestamp):
    """Check if current hour×weekday×month is excluded"""
    month_num = bar_timestamp.month
    hour = bar_timestamp.hour
    weekday = bar_timestamp.weekday()
    # Check month-specific exclusion pairs
    
def _get_position_size_multiplier(self, bar_timestamp):
    """Get multiplier for position sizing (0x, 1.0x, or 1.3x-1.5x)"""
    if self._should_exclude_trade(bar_timestamp):
        return 0.0
    # Check if in boosted patterns
    # Return configured multiplier or 1.0
```

### Step 1.3: Create Config Profiles ✅
Create 4 config files for testing:
- `.env.mtf_v2_baseline` - no exclusions, no boosting (control)
- `.env.mtf_v2_exclusions_only` - 2 negative patterns excluded, no boosting
- `.env.mtf_v2_conservative` - 2 excluded + top 5 positive boosted at 1.3x
- `.env.mtf_v2_aggressive` - 2 excluded + all 13 positive boosted at 1.5x

---

## Phase 2: Validation Testing (3-4 hours)

### Step 2.1: Single-Month Deep Dive ✅
**Target:** November 2024 (has negative pattern: hour 20 Thursday)

Run 4 parallel backtests:
```powershell
# Baseline (control)
$env:MTF2_BACKTEST_START='2024-11-01'
$env:MTF2_BACKTEST_END='2024-11-30'
$env:MTF2_SEASONAL_HOUR_EXCLUSIONS_ENABLED='false'

# Exclusions only
$env:MTF2_MONTH_11_EXCLUDED_HOUR_WEEKDAY_PAIRS='20-3'
$env:MTF2_POSITIVE_PATTERN_SIZE_MULTIPLIER='1.0'

# Conservative (top 5 positive patterns for November)
$env:MTF2_MONTH_11_EXCLUDED_HOUR_WEEKDAY_PAIRS='20-3'
$env:MTF2_MONTH_11_BOOSTED_HOUR_WEEKDAY_PAIRS='3-2,4-3,20-6,...'
$env:MTF2_POSITIVE_PATTERN_SIZE_MULTIPLIER='1.3'

# Aggressive (all 13 positive)
$env:MTF2_POSITIVE_PATTERN_SIZE_MULTIPLIER='1.5'
```

**Expected Results:**
- Exclusions only: +$37.64 improvement (avoid 4 losing trades)
- Conservative: Additional +5-10% on winning trades during boosted hours
- Aggressive: Higher variance but potentially +15-20% improvement

### Step 2.2: Full 25-Month Validation ✅
Run complete batch tests (2024-01 through 2026-01) for each config profile:
- Baseline (already have from Jan 26 batch)
- Exclusions only (new run)
- Conservative (new run)
- Aggressive (new run)

Use `scripts/run_monthly_backtests_mtf_v2_entry_confirmed.py` with different config profiles.

**Comparison Metrics:**
- **Total PnL** - must improve vs baseline
- **Win Rate** - should stay stable or improve
- **Max Drawdown** - critical: should NOT increase significantly
- **Sharpe Ratio** - risk-adjusted returns must improve
- **Trade Count** - exclusions reduce by ~11 trades, boosting doesn't change count
- **Profit Factor** - should improve (fewer/smaller losses, bigger/more wins)

---

## Phase 3: Statistical Validation (1 hour)

### Step 3.1: Pattern Stability Check ✅
Create audit script `scripts/validate_position_sizing_results.py`:
- Compare excluded pattern performance in test runs
- Compare boosted pattern performance in test runs
- Verify trade count reductions match expectations
- Confirm boosted trades occurred during specified hours

### Step 3.2: Walk-Forward Analysis ✅
Split data into train/test:
- **Train:** 2024-01 through 2025-06 (18 months)
- **Test:** 2025-07 through 2026-01 (7 months)

Patterns identified on train set should validate on test set.

Create script `scripts/walk_forward_pattern_validation.py`.

---

## Phase 4: Decision Criteria

**Proceed to Live if ALL conditions met:**

1. ✅ **Exclusions only** improves PnL by ≥$100 over baseline (covering the -$134 from 2 patterns)
2. ✅ **Conservative** improves PnL by ≥$200 AND Sharpe ≥ baseline AND Max DD < baseline * 1.1
3. ✅ **Aggressive** improves PnL by ≥$500 BUT only if Max DD < baseline * 1.2 (acceptable risk trade-off)
4. ✅ Pattern stability holds in walk-forward test (positive patterns stay positive, negative stay negative)
5. ✅ No new failure modes introduced (check for edge cases in logs)

**Rollback triggers:**
- ❌ Any config REDUCES total PnL vs baseline
- ❌ Max Drawdown increases by >20%
- ❌ Win rate drops by >3 percentage points
- ❌ New patterns emerge contradicting our findings

---

## Phase 5: Implementation Timeline

### Conservative Path (Recommended)
- **Week 1:** Implement code + config system
- **Week 2:** Run validation backtests (single-month + full 25-month)
- **Week 3:** Analyze results, decide go/no-go
- **Week 4:** Deploy exclusions only to live (paper trading)
- **Month 2-3:** Monitor, if stable add conservative boosting
- **Month 4+:** Evaluate aggressive boosting if conservative performing well

### Aggressive Path (Higher Risk)
- **Week 1-2:** Implement + validate
- **Week 3:** Deploy conservative config directly to live
- **Month 2:** Evaluate aggressive if performing well

---

## Phase 6: Live Trading Monitoring

### KPIs to Track (Weekly)
- PnL during excluded hours (should be $0 - no trades)
- PnL during boosted hours vs normal hours (boosted should outperform)
- Trade count distribution (verify exclusions working)
- Pattern correlation (are patterns still predictive?)

### Auto-Disable Trigger
If 2 consecutive months show negative alpha from strategy adjustments, revert to baseline.

---

## Time Investment Estimate
- Implementation: 2 hours
- Validation backtests: 3-4 hours runtime (mostly automated)
- Analysis: 2 hours
- **Total: ~8 hours to validated decision point**

---

## Data Reference

### Consistently Negative Patterns (2 total)
| Month | Hour (EST) | Day | Years | Trades | Total PnL | Avg WR% |
|-------|-----------|-----|-------|--------|-----------|---------|
| October | 4am | Friday | 2/2 | 5 | -$67.79 | 20.0% |
| November | 8pm | Thursday | 2/2 | 6 | -$66.49 | 16.7% |

### Consistently Positive Patterns (Top 5 for Conservative)
| Month | Hour (EST) | Day | Years | Trades | Total PnL | Avg WR% |
|-------|-----------|-----|-------|--------|-----------|---------|
| April | 4am | Thursday | 2/2 | 6 | $178.92 | 100.0% |
| November | 3am | Wednesday | 2/2 | 12 | $173.96 | 91.7% |
| April | 8pm | Sunday | 2/2 | 9 | $134.06 | 100.0% |
| July | 4am | Thursday | 2/2 | 6 | $130.56 | 100.0% |
| August | 8am | Wednesday | 2/2 | 11 | $125.66 | 72.7% |

### All 13 Positive Patterns (for Aggressive)
See full output from `scripts/analyze_hour_weekday_consistency.py`

---

## Git Branch
**Branch name:** `feature/position-sizing-month-patterns`
**Based on:** main
**Created:** January 26, 2026
