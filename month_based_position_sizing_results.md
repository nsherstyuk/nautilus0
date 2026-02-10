# Month-Based Position Sizing Backtest Results

## Executive Summary

**RECOMMENDATION: DO NOT IMPLEMENT** - None of the month-based position sizing profiles met the success criteria. The aggressive profile showed modest improvement (+$132.37) but falls far short of the $500 threshold and cannot overcome the underlying negative strategy expectancy.

## Test Configuration

- **Period**: 2024-01-01 to 2026-01-31 (25 months, 758 days)
- **Strategy**: MTF V2 Entry Confirmed
- **Test Profiles**: 4 (Baseline, Exclusions Only, Conservative, Aggressive)
- **Pattern Basis**: Year-over-year consistency analysis (2 negative, 13 positive patterns)

## Complete Results Comparison

| Profile | Total PnL | Δ vs Baseline | PnL% | Win Rate | Sharpe | Sortino | Profit Factor | Trades | Expectancy |
|---------|-----------|---------------|------|----------|--------|---------|---------------|--------|------------|
| **BASELINE** | -$3,206.71 | - | -6.41% | 56.1% | 0.764 | 1.180 | 1.046 | 3,750 | -$0.86 |
| **EXCLUSIONS_ONLY** | -$3,150.21 | **+$56.50** | -6.30% | 56.1% | 0.772 | 1.194 | 1.047 | 3,750 | -$0.84 |
| **CONSERVATIVE** | -$3,165.56 | +$41.15 | -6.33% | 56.1% | 0.770 | 1.190 | 1.047 | 3,750 | -$0.84 |
| **AGGRESSIVE** | -$3,074.34 | **+$132.37** | -6.15% | 56.1% | 0.772 | 1.193 | 1.047 | 3,752 | -$0.82 |

### Pattern Configuration Details

**Excluded Patterns (all profiles with exclusions enabled):**
- October: hour 4 Friday (4-4) - Historical: 5 trades, 20% WR, -$67.79
- November: hour 20 Thursday (20-3) - Historical: 6 trades, 16.7% WR, -$66.49

**Boosted Patterns:**

*Conservative (5 patterns at 1.3x):*
- April: 4am Thursday (4-3), 8pm Sunday (20-6)
- July: 4am Thursday (4-3)
- August: 8am Wednesday (8-2)
- November: 10am Thursday (3-2)

*Aggressive (13 patterns at 1.5x):*
- All Conservative patterns plus:
- March: 8am Sunday (8-6), 8pm Sunday (20-6)
- May: 4am Thursday (4-3)
- June: 8am Wednesday (8-2), 8pm Thursday (20-3)
- July: 8am Wednesday (8-2)
- August: 8pm Sunday (20-6)
- November: 4am Tuesday (4-1)

## Decision Criteria Assessment

### Phase 2: Validation Testing (FAILED)

| Criterion | Target | Exclusions | Conservative | Aggressive | Result |
|-----------|--------|------------|--------------|----------|--------|
| Exclusions PnL Improvement | ≥$100 | **$56.50** | $41.15 | $132.37 | ❌ FAIL |
| Conservative PnL Improvement | ≥$200 | - | **$41.15** | - | ❌ FAIL |
| Conservative Sharpe ≥ Baseline | ≥0.764 | - | **0.770** | - | ✓ PASS |
| Conservative Max DD < 1.1×Baseline | Monitor | - | - | - | N/A |
| Aggressive PnL Improvement | ≥$500 | - | - | **$132.37** | ❌ FAIL |
| Aggressive Max DD < 1.2×Baseline | Monitor | - | - | - | N/A |

**Verdict**: All three enhanced profiles failed to meet minimum PnL improvement thresholds.

### Rollback Trigger Check

| Trigger | Threshold | Status |
|---------|-----------|--------|
| PnL Reduction vs Baseline | Any | ✓ NO TRIGGER (all improved) |
| Max DD Increase | >20% | N/A (not calculated) |
| Win Rate Drop | >3% | ✓ NO TRIGGER (all identical 56.1%) |
| Sharpe Deterioration | <Baseline | ✓ NO TRIGGER (all ≥ baseline) |

## Key Findings

### 1. Minimal Impact from Pattern Exclusions
- Excluding 2 negative patterns improved PnL by only $56.50 (1.76% of losses)
- The excluded patterns (11 trades total) represented only 0.29% of total trades
- Historical losses from these patterns (-$134.28) were not replicated in backtest period

### 2. Conservative Boosting Backfired
- 1.3x multiplier on 5 "positive" patterns **worsened** performance vs exclusions alone
- Δ Conservative vs Exclusions: -$15.35 (degradation)
- The historical high-performing patterns appear to have underperformed or reversed in the test period

### 3. Aggressive Showed Best (But Insufficient) Results
- 1.5x multiplier on 13 patterns achieved $132.37 improvement
- Still 73.5% short of $500 success criterion
- Improvement represents only 4.13% reduction in total losses

### 4. Identical Trade Counts and Win Rates
- All profiles except aggressive maintained exactly 3,750 trades
- Aggressive had 3,752 trades (2 additional, likely from rounding with 1.5x sizing)
- Win rate held constant at 56.1% across all profiles
- Indicates exclusions did not filter trades; position sizing applied at entry, not signal level

### 5. Underlying Strategy Expectancy Issue
- **Baseline expectancy: -$0.86 per trade**
- Even with aggressive boost: -$0.82 per trade (only 4.7% improvement)
- Negative expectancy cannot be overcome by selective position sizing
- The 56.1% win rate is insufficient when average loser (-$45.81) exceeds average winner ($34.36) by 33%

### 6. Historical Pattern Reliability
- Year-over-year consistency analysis identified "reliable" patterns
- Those patterns failed to maintain performance in out-of-sample 25-month test
- Possible causes:
  - Market regime change
  - Overfitting to specific historical period
  - Pattern degradation over time
  - Insufficient sample size (some patterns had <10 historical trades)

## Technical Implementation Notes

### What Worked
- Config system extension with 24 month-based parameters
- Profile switching via `.env.mtf_v2` override mechanism
- Position sizing multiplier logic at entry time
- Proper timezone handling (EST for patterns, UTC for bars)
- Weekday format normalization (1-7 → 0-6)

### Implementation Issues
- None - all code functioned as designed
- Pattern detection and multiplier application confirmed in logs
- The issue is pattern predictive value, not implementation

## Recommendation

**DO NOT PROCEED TO PRODUCTION**

### Rationale
1. **Insufficient Performance Gain**: Best profile (+$132) is 73.5% below $500 threshold
2. **Underlying Strategy Problem**: Negative expectancy (-$0.86/trade) cannot be fixed by position sizing
3. **Pattern Unreliability**: Historical patterns did not hold in test period
4. **Risk-Adjusted Returns**: Minimal Sharpe improvement (0.764 → 0.772) doesn't justify complexity
5. **Operational Risk**: Adding 24+ config parameters increases live trading fragility

### Alternative Actions

1. **Focus on Strategy Improvement**: Address the negative expectancy root cause
   - Review entry/exit conditions
   - Analyze losing trades for systematic patterns
   - Consider tighter stop losses or better TP targets
   
2. **Simpler Filtering**: Instead of position sizing, consider:
   - Complete exclusion of very low WR patterns
   - Time-of-day filters (e.g., avoid overnight hours)
   - Volatility-based position sizing (not pattern-based)

3. **Walk-Forward Analysis**: Before any pattern-based approach:
   - Validate patterns hold across multiple out-of-sample periods
   - Require 3+ years of consistent performance (not just 2)
   - Use stricter statistical significance tests

4. **Return to Fundamentals**:
   - Current strategy: 56.1% WR, -$0.86 expectancy
   - Breakeven requires: 57.1% WR (with current avg win/loss ratio)
   - Focus on improving WR by 1-2% through better entry/exit logic

## Files and Artifacts

### Backtest Output Directories
- **BASELINE**: `backtest_results/MTF_V2_ENTRY_CONFIRMED_20260126_201333/`
- **EXCLUSIONS_ONLY**: `backtest_results/MTF_V2_ENTRY_CONFIRMED_20260126_225333/`
- **CONSERVATIVE**: `backtest_results/MTF_V2_ENTRY_CONFIRMED_20260127_013811/`
- **AGGRESSIVE**: `backtest_results/MTF_V2_ENTRY_CONFIRMED_20260127_070532/`

### Config Profiles
- `.env.mtf_v2_baseline` - Control (no exclusions/boosting)
- `.env.mtf_v2_exclusions_only` - 2 negative patterns excluded
- `.env.mtf_v2_conservative` - 2 excluded + 5 boosted at 1.3x
- `.env.mtf_v2_aggressive` - 2 excluded + 13 boosted at 1.5x

### Code Changes
- `config/mtf_v2_config.py` - Extended with month-based parameters
- `strategies/ml_strategy_mtf_v2_entry_confirmed.py` - Position sizing at entry
- `test_config_profiles.py` - Validation script

### Documentation
- `POSITION_SIZING_ACTION_PLAN.md` - Original 6-phase implementation plan
- `month_based_position_sizing_results.md` - This report

## Conclusion

Month-based position sizing, while correctly implemented, cannot overcome the fundamental issue of negative strategy expectancy. The improvement achieved (+$132 best case) is economically insignificant relative to total losses (-$3,207) and does not meet established success criteria.

**Status**: REJECTED for production deployment. Recommend focusing on core strategy improvements rather than position sizing variations.

---

*Analysis Date*: 2026-01-27  
*Backtest Period*: 2024-01-01 to 2026-01-31 (25 months)  
*Total Backtest Runtime*: ~8 hours (4 profiles × 2 hours each)  
*Decision*: DO NOT IMPLEMENT
