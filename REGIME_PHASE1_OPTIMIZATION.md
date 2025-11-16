# Regime Detection Optimization - Phase 1

## Overview
Phase 1 optimization to determine if regime detection can improve strategy performance.

## Current Status
- **Start Time**: 2025-11-15 13:40:29
- **Grid Size**: 2,700 runs
- **Output Directory**: `logs/regime_phase1_global`
- **Status**: RUNNING ✓

## Problem Statement
When regime detection was enabled with default parameters, PnL dropped to negative.
This optimization aims to find if regime detection CAN work with different parameters.

## Parameters Being Optimized

### ADX Thresholds (Detection)
- `STRATEGY_REGIME_ADX_TRENDING_THRESHOLD`: [20.0, 25.0, 30.0, 35.0]
  - Determines when market is "trending" (higher ADX = stronger trend)
  - Default: 25.0
  
- `STRATEGY_REGIME_ADX_RANGING_THRESHOLD`: [10.0, 15.0, 20.0]
  - Determines when market is "ranging" (lower ADX = no trend)
  - Default: 20.0

### Take Profit Multipliers
- `STRATEGY_REGIME_TP_MULTIPLIER_TRENDING`: [1.0, 1.2, 1.4, 1.6, 1.8]
  - How much to increase TP in trending markets
  - Default: 1.5 (80 pips → 120 pips)
  - Range: 1.0 (no change) to 1.8 (80 → 144 pips)
  
- `STRATEGY_REGIME_TP_MULTIPLIER_RANGING`: [0.6, 0.7, 0.8, 0.9, 1.0]
  - How much to decrease TP in ranging markets
  - Default: 0.8 (80 pips → 64 pips)
  - Range: 0.6 (48 pips) to 1.0 (no change)

### Stop Loss Multipliers
- `STRATEGY_REGIME_SL_MULTIPLIER_TRENDING`: [0.8, 1.0, 1.2]
  - How much to adjust SL in trending markets
  - Default: 1.0 (25 pips, no change)
  
- `STRATEGY_REGIME_SL_MULTIPLIER_RANGING`: [0.8, 1.0, 1.2]
  - How much to adjust SL in ranging markets
  - Default: 1.0 (25 pips, no change)

## Grid Composition
```
Total Runs: 2,700
= 4 ADX trending thresholds
× 3 ADX ranging thresholds  
× 5 TP trending multipliers
× 5 TP ranging multipliers
× 3 SL trending multipliers
× 3 SL ranging multipliers
```

## Expected Timeline
- **Estimated Duration**: ~13-18 hours
- **Per Run**: ~20-25 seconds
- **Expected Completion**: 2025-11-16 02:40 - 07:40

## Success Criteria

### Phase 1 Success (Proceed to Phase 2)
- At least one configuration shows positive PnL improvement vs baseline
- Best configuration exceeds baseline by >$1,000
- Win rate remains >40%
- Result: ADD weekday-specific regime parameters (Phase 2)

### Phase 1 Failure (Abandon Concept)
- ALL configurations show negative PnL or worse than baseline
- No parameter combination shows promise
- Result: DISABLE regime detection, focus on other filters

## Baseline Comparison
**Without Regime Detection** (from previous runs):
- PnL: ~$5,670 (with current data)
- Win Rate: ~43.4%
- Trades: ~219

**With Regime Detection (Default Parameters)**:
- PnL: NEGATIVE (user reported)
- Cause: Likely poor default parameter choices

## What Happens Next

### If Phase 1 Succeeds
1. Analyze best parameter combinations
2. Identify which parameters matter most
3. Design Phase 2: Weekday-specific optimization
   - Use Phase 1 best params as baseline
   - Add weekday variations (Monday-Friday)
   - Smaller grid: ~250-500 runs

### If Phase 1 Fails
1. Disable regime detection entirely
2. Document why it doesn't work
3. Focus optimization on:
   - Entry timing improvements
   - Additional filters (RSI, Volume, ATR)
   - Time filter refinements

## Monitoring Progress

Check progress with:
```powershell
# Count completed runs
(Get-ChildItem logs\regime_phase1_global -Directory).Count

# View latest results
$latest = Get-ChildItem logs\regime_phase1_global -Directory | Sort-Object Name -Descending | Select-Object -First 1
Get-Content "$($latest.FullName)\summary.json"

# Monitor in real-time
tail -f logs\regime_phase1_global\grid_backtest.log
```

## Notes
- Trailing stop multipliers kept at defaults for Phase 1 (to reduce grid size)
- DMI must be enabled for regime detection to work (ADX comes from DMI)
- Using 15-MINUTE bars for main strategy, 5-MINUTE bars for DMI
- All other strategy parameters remain unchanged from .env
