# Multi-Phase Optimization Summary

## ✅ Completed Phases

### Phase 0: Fixed TP/SL Grid (`tp_sl_phase0_fixed_v2`)
**Status**: ✅ Complete  
**Config**: `optimize_tp_sl_phase0_fixed.json`  
**Runs**: 54 combinations  

**Best Result**:
- Run: Multiple runs (20, 24, 30, etc.) with identical performance
- SL: 25 pips
- TP: 70 pips  
- Trailing Activation: 25-30 pips
- Trailing Distance: 15-20 pips
- **Net PnL**: ~8,636
- **Win Rate**: ~42-43%

### Phase 1: ATR Adaptive Grid (`atr_phase1`)
**Status**: ✅ Complete  
**Config**: `optimize_adaptive_atr_phase1.json`  
**Runs**: 36 combinations  

**Best Result** (run_0029):
- Base: SL=25 pips, TP=70 pips
- `BACKTEST_SL_ATR_MULT`: **2.0**
- `BACKTEST_TP_ATR_MULT`: **2.5**
- `BACKTEST_TRAIL_ACTIVATION_ATR_MULT`: **0.8**
- `BACKTEST_TRAIL_DISTANCE_ATR_MULT`: **0.5**
- **Net PnL**: **$8,526.44**
- **Win Rate**: **51.66%**
- **Expectancy**: 40.41

**Key Insight**: ATR-based adaptive stops with 2.0×SL and 2.5×TP significantly improved win rate from ~42% to ~52% while maintaining strong PnL.

---

## 🔄 Phase 2: Regime Multipliers (Ready to Run)

**Config**: `optimize_regime_phase2.json`  
**Status**: Ready to execute  
**Runs**: 16 combinations (2×2×2×2)

**Parameters**:
- Locks best ATR config from Phase 1
- Sweeps:
  - `STRATEGY_REGIME_TP_MULTIPLIER_TRENDING`: [1.0, 1.2]
  - `STRATEGY_REGIME_TP_MULTIPLIER_RANGING`: [1.0, 0.8]
  - `STRATEGY_REGIME_SL_MULTIPLIER_TRENDING`: [1.0, 0.8]
  - `STRATEGY_REGIME_SL_MULTIPLIER_RANGING`: [1.0, 1.2]

**To Run**:
```powershell
python scripts/run_grid_backtest.py --config optimize_regime_phase2.json --output-dir logs/regime_phase2
```

**Expected Runtime**: ~16 runs × 50 sec = 13-15 minutes

---

## 🔄 Phase 3: Time-of-Day Multipliers (Run After Phase 2)

**Config**: `optimize_time_phase3.json`  
**Status**: Config ready, implementation complete  
**Runs**: 64 combinations (2^6)

**New Features Implemented**:

### Code Changes:
1. **`config/backtest_config.py`**:
   - Added `time_multiplier_enabled: bool`
   - Added 6 time multiplier fields:
     - `time_tp_multiplier_eu_morning` (7-11 UTC)
     - `time_tp_multiplier_us_session` (13-17 UTC)
     - `time_tp_multiplier_other`
     - `time_sl_multiplier_eu_morning`
     - `time_sl_multiplier_us_session`
     - `time_sl_multiplier_other`
   - Added parsing logic in `get_backtest_config()`

2. **`strategies/moving_average_crossover.py`**:
   - Added time multiplier config fields to `MovingAverageCrossoverConfig`
   - Implemented `_get_time_profile_multipliers(timestamp)` method:
     - Returns (tp_mult, sl_mult) tuple based on UTC hour
     - EU morning: 7-11 UTC (London open)
     - US session: 13-17 UTC (NY overlap)
     - Other: all other hours
   - Integrated time multipliers into TP/SL calculation:
     - Applied **after** regime multipliers
     - Uses bar.ts_event timestamp

**Parameters**:
- Locks best ATR + regime config (once regime phase completes)
- Sweeps:
  - `STRATEGY_TIME_TP_MULTIPLIER_EU_MORNING`: [1.0, 1.2]
  - `STRATEGY_TIME_TP_MULTIPLIER_US_SESSION`: [1.0, 1.2]
  - `STRATEGY_TIME_TP_MULTIPLIER_OTHER`: [0.8, 1.0]
  - `STRATEGY_TIME_SL_MULTIPLIER_EU_MORNING`: [0.8, 1.0]
  - `STRATEGY_TIME_SL_MULTIPLIER_US_SESSION`: [0.8, 1.0]
  - `STRATEGY_TIME_SL_MULTIPLIER_OTHER`: [1.0, 1.2]

**To Run** (after Phase 2 completes):
```powershell
python scripts/run_grid_backtest.py --config optimize_time_phase3.json --output-dir logs/time_phase3
```

**Expected Runtime**: ~64 runs × 50 sec = 53 minutes

**NOTE**: Before running Phase 3, update `optimize_time_phase3.json` to include the best regime multipliers from Phase 2.

---

## 📊 Optimization Flow

```
Phase 0: Fixed TP/SL
    ↓ (Best: SL=25, TP=70, PnL=8.6k, WR=42%)
Phase 1: ATR Adaptive
    ↓ (Best: SL_ATR=2.0, TP_ATR=2.5, PnL=8.5k, WR=52%)
Phase 2: Regime Multipliers ← YOU ARE HERE
    ↓ (Pending: Find best trending/ranging adjustments)
Phase 3: Time-of-Day Multipliers
    ↓ (Pending: Optimize by trading session)
Final Config: Best overall combination
```

---

## 🎯 Next Steps

1. **Wait for Regime Grid to Complete** (if running):
   - Check progress: `Get-ChildItem logs\regime_phase2 -Directory | Measure-Object`
   - Extract best run:
     ```powershell
     python -c "import json, pathlib; base = pathlib.Path('logs/regime_phase2'); best=None
for run_dir in sorted(base.glob('run_*')):
 p=run_dir/'params.json'; s=run_dir/'stats.json'
 if not p.exists() or not s.exists():
  continue
 params=json.load(open(p)); stats=json.load(open(s)); pnl=stats.get('net_pnl', stats.get('Net PnL', 0))
 if best is None or pnl>best['pnl']:
  best={'run': run_dir.name, 'pnl': pnl, 'params': params}
print(json.dumps(best, indent=2))"
     ```

2. **Update Time-of-Day Config**:
   - Add best regime multipliers to `optimize_time_phase3.json`
   - Example:
     ```json
     "STRATEGY_REGIME_DETECTION_ENABLED": ["true"],
     "STRATEGY_REGIME_TP_MULTIPLIER_TRENDING": [1.2],  // from best regime run
     "STRATEGY_REGIME_TP_MULTIPLIER_RANGING": [0.8],
     ...
     ```

3. **Run Time-of-Day Grid**:
   ```powershell
   python scripts/run_grid_backtest.py --config optimize_time_phase3.json --output-dir logs/time_phase3
   ```

4. **Extract Final Best Config**:
   - Combine best parameters from all phases
   - Update main `.env` with optimal settings
   - Run final validation backtest

---

## 📈 Expected Improvements

- **Phase 1 → Phase 2**: Regime detection should improve expectancy in different market conditions
- **Phase 2 → Phase 3**: Time-of-day filters should reduce losses during low-liquidity hours and optimize for high-volatility sessions
- **Overall Target**: Maintain or improve PnL while increasing win rate and reducing drawdown

---

## 🔧 Configuration Files

- `optimize_adaptive_atr_phase1.json` ✅ (Complete)
- `optimize_regime_phase2.json` ✅ (Ready)
- `optimize_time_phase3.json` ✅ (Ready, needs regime params after Phase 2)

All grid configs and code changes are committed and ready for execution.
