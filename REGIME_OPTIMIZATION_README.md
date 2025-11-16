# Regime Detection Optimization

This directory contains scripts and configurations for optimizing regime detection parameters.

## Quick Start

### Option 1: Focused Optimization (Recommended First)
**54 combinations, ~1 hour**

```bash
python optimize_regime_detection.py --focused
```

This tests a focused grid to see if regime detection can improve performance before running the full optimization.

### Option 2: Full Optimization
**109,350+ combinations, ~15+ hours**

```bash
python optimize_regime_detection.py --full
```

**Warning:** This will take a very long time! Use `--focused` first to validate the concept.

## What Gets Optimized

### ADX Thresholds (Detection)
- `regime_adx_trending_threshold`: [20.0, 25.0, 30.0] (focused) or [20.0, 25.0, 30.0, 35.0] (full)
- `regime_adx_ranging_threshold`: [15.0, 20.0] (focused) or [10.0, 15.0, 20.0] (full)

### Take Profit Multipliers
- `regime_tp_multiplier_trending`: [1.0, 1.3, 1.6] (focused) or [1.0, 1.2, 1.4, 1.6, 1.8] (full)
- `regime_tp_multiplier_ranging`: [0.7, 0.85, 1.0] (focused) or [0.6, 0.7, 0.8, 0.9, 1.0] (full)

### Stop Loss Multipliers (Focused: Fixed at 1.0)
- `regime_sl_multiplier_trending`: [1.0] (focused) or [0.8, 1.0, 1.2] (full)
- `regime_sl_multiplier_ranging`: [1.0] (focused) or [0.8, 1.0, 1.2] (full)

### Trailing Stop Multipliers (Focused: Fixed at defaults)
- `regime_trailing_activation_multiplier_trending`: Fixed (focused) or [0.5, 0.75, 1.0] (full)
- `regime_trailing_activation_multiplier_ranging`: Fixed (focused) or [1.0, 1.25, 1.5] (full)
- `regime_trailing_distance_multiplier_trending`: Fixed (focused) or [0.5, 0.67, 1.0] (full)
- `regime_trailing_distance_multiplier_ranging`: Fixed (focused) or [1.0, 1.33, 1.67] (full)

## Base Configuration

All optimizations use the **14k PnL configuration** as the base:
- Fast Period: 42
- Slow Period: 270
- Stop Loss: 35 pips
- Take Profit: 50 pips
- Trailing: 22/12 pips
- DMI: Enabled (period 10)
- Stochastic: Enabled (K=18, D=3, thresholds 30/65)
- Time Filter: Disabled
- Regime Detection: **Enabled** (this is what we're optimizing)

## Files

- `optimize_regime_detection.py` - Main optimization script
- `optimization/configs/regime_detection_focused.yaml` - Focused config (54 combinations)
- `optimization/configs/regime_detection_optimization.yaml` - Full config (109k+ combinations)
- `optimization/results/regime_detection_focused_results.csv` - Focused results
- `optimization/results/regime_detection_results.csv` - Full results

## Custom Options

```bash
# Use more workers (faster)
python optimize_regime_detection.py --focused --workers 16

# Optimize for total PnL instead of Sharpe ratio
python optimize_regime_detection.py --focused --objective total_pnl

# Combine options
python optimize_regime_detection.py --focused --workers 16 --objective total_pnl
```

## Analyzing Results

After optimization completes:

```python
import pandas as pd

# Load results
df = pd.read_csv('optimization/results/regime_detection_focused_results.csv')

# Top 10 by Sharpe ratio
print(df.nlargest(10, 'sharpe_ratio')[['regime_adx_trending_threshold', 'regime_adx_ranging_threshold', 
                                        'regime_tp_multiplier_trending', 'regime_tp_multiplier_ranging',
                                        'total_pnl', 'sharpe_ratio', 'win_rate']])
```

## Expected Outcomes

### If Regime Detection Works
- Best result should beat baseline (14k PnL without regime detection)
- Optimal parameters will show clear patterns
- Can expand to full optimization

### If Regime Detection Doesn't Work
- All results worse than baseline
- No clear parameter patterns
- Consider abandoning regime detection or trying different approaches

## Notes

- **DMI must be enabled** for regime detection to work (it uses ADX from DMI)
- Optimization uses the same date range as your `.env` file
- Checkpoints are saved every 10 runs - you can resume if interrupted
- Results are saved to CSV for easy analysis

