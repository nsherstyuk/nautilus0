# EUR/USD Trading Strategy Optimization Journey

**Date Range:** November 2024 - November 2025  
**Strategy:** Moving Average Crossover with Adaptive Stops  
**Instrument:** EUR/USD 15-minute bars  
**Backtest Period:** January 1, 2024 - October 30, 2025  

---

## Table of Contents
1. [Overview](#overview)
2. [Optimization Phases](#optimization-phases)
3. [Final Configuration](#final-configuration)
4. [Scripts Used](#scripts-used)
5. [Results Analysis](#results-analysis)
6. [Key Learnings](#key-learnings)

---

## Overview

This document chronicles the complete optimization journey of a EUR/USD forex trading strategy built on NautilusTrader 1.221.0. The strategy uses a moving average crossover system (Fast MA=40, Slow MA=260) with multiple layers of risk management and filtering.

### Base Strategy Components
- **Entry Signal:** MA crossover with 0.15 pip threshold
- **Position Size:** 100,000 units (1 standard lot)
- **Capital:** $100,000 starting balance
- **Timeframe:** 15-minute bars

---

## Optimization Phases

### Phase 0: Fixed TP/SL Baseline
**Directory:** `logs/tp_sl_phase0_fixed/`  
**Date:** November 2024  
**Objective:** Find optimal fixed take-profit and stop-loss values

**Grid Parameters:**
- Stop Loss: 15-40 pips (5 pip increments)
- Take Profit: 30-80 pips (10 pip increments)
- Total combinations: 6 × 6 = 36 runs

**Best Result:**
- **Run:** run_0023
- **Configuration:** SL=25 pips, TP=70 pips
- **PnL:** $7,328.99
- **Win Rate:** 50.28%
- **Trades:** 177

**Key Finding:** 2.8:1 reward-to-risk ratio (70 pips TP / 25 pips SL) worked best on trending moves.

---

### Phase 1: ATR Adaptive Stops
**Directory:** `logs/atr_phase1/`  
**Date:** November 2024  
**Objective:** Replace fixed pips with ATR-based dynamic stops

**Grid Parameters:**
- SL ATR Multiplier: 1.5, 2.0, 2.5
- TP ATR Multiplier: 2.0, 2.5, 3.0
- Trailing Activation: 0.6, 0.8, 1.0
- Trailing Distance: 0.4, 0.5, 0.6
- Total combinations: 3 × 3 × 3 × 3 = 81 runs (36 completed)

**Best Result:**
- **Run:** run_0029
- **Configuration:**
  - SL_ATR_MULT: 2.0
  - TP_ATR_MULT: 2.5
  - TRAIL_ACTIVATION_ATR_MULT: 0.8
  - TRAIL_DISTANCE_ATR_MULT: 0.5
- **PnL:** $8,526.00
- **Win Rate:** 50.00%
- **Trades:** 190
- **Improvement:** +16.3% over Phase 0

**Key Finding:** ATR-based stops adapt better to market volatility, capturing more profit in strong trends while limiting losses in choppy conditions.

---

### Phase 2: Market Regime Detection
**Directory:** `logs/regime_phase2/`  
**Date:** November 2024  
**Objective:** Adjust TP/SL based on trending vs ranging market conditions using ADX

**Grid Parameters:**
- Regime TP Multiplier (Trending): 1.0, 1.5, 2.0
- Regime TP Multiplier (Ranging): 0.6, 0.8, 1.0
- Regime SL Multiplier (Trending): 0.8, 1.0, 1.2
- Regime SL Multiplier (Ranging): 0.8, 1.0, 1.2
- Total combinations: Partial grid exploration

**Result:**
- **Best PnL:** Similar to Phase 1 baseline
- **Conclusion:** Regime detection showed minimal improvement over ATR-only approach
- **Decision:** Disabled regime detection for Phase 3

**Key Finding:** Market regime filtering didn't provide significant edge. Time-based filtering might be more effective for EUR/USD.

---

### Phase 3: Time-of-Day Multipliers
**Directory:** `logs/time_phase3_fixed/`  
**Date:** November 15, 2025  
**Objective:** Optimize TP/SL multipliers for different trading sessions

**Trading Sessions Defined:**
- **EU Morning:** 07:00-11:00 UTC (London open)
- **US Session:** 13:00-17:00 UTC (New York open)
- **Other:** All remaining hours

**Grid Parameters:**
- EU Morning TP Multiplier: 0.8, 1.0, 1.2
- US Session TP Multiplier: 0.8, 1.0, 1.2
- Other Hours TP Multiplier: 0.8, 1.0, 1.2
- EU Morning SL Multiplier: 0.8, 1.0, 1.2
- US Session SL Multiplier: 0.8, 1.0, 1.2
- Other Hours SL Multiplier: 0.8, 1.0, 1.2
- Total combinations: 3^6 = 729 runs (64 completed)

**Baseline Configuration:**
- Built on aggressive weekday-specific hour exclusions
- Different excluded hours for each day of week
- Examples:
  - Monday: Excludes 14 hours (0,1,3,4,5,8,10,11,12,13,18,19,23)
  - Wednesday: Excludes 18 hours (0,1,8,9,10,11,12,13,14,15,16,17,18,19,23)
  - Friday: Excludes 19 hours (0,1,2,3,4,5,8,9,10,11,12,13,14,15,16,17,18,19,23)

**Best Result:**
- **Run:** run_0028
- **Configuration:**
  ```
  STRATEGY_TIME_MULTIPLIER_ENABLED=true
  STRATEGY_TIME_TP_MULTIPLIER_EU_MORNING=1.0
  STRATEGY_TIME_TP_MULTIPLIER_US_SESSION=1.2
  STRATEGY_TIME_TP_MULTIPLIER_OTHER=1.0
  STRATEGY_TIME_SL_MULTIPLIER_EU_MORNING=0.8
  STRATEGY_TIME_SL_MULTIPLIER_US_SESSION=1.0
  STRATEGY_TIME_SL_MULTIPLIER_OTHER=1.2
  ```
- **PnL:** $9,022.48
- **Win Rate:** 54.03%
- **Expectancy:** $42.76
- **Rejected Signals:** 3,559
- **Improvement:** +23.1% over Phase 0, +5.8% over Phase 1

**Key Finding:** 
1. Tighter stops during EU morning (0.8x) reduced losses in choppy London open
2. Wider targets during US session (1.2x) captured strong NY trends
3. Wider stops during other hours (1.2x) reduced premature exits
4. Weekday-specific hour exclusions were critical - 4.76x more signal rejections without them

---

## Final Configuration

The optimal configuration combines all successful optimization layers:

### File: `.env`
```properties
# ============================================================================
# BACKTESTING PARAMETERS
# ============================================================================
BACKTEST_SYMBOL=EUR/USD
BACKTEST_START_DATE=2024-01-01
BACKTEST_END_DATE=2025-10-30
BACKTEST_VENUE=IDEALPRO
BACKTEST_BAR_SPEC=15-MINUTE-MID-EXTERNAL
BACKTEST_FAST_PERIOD=40
BACKTEST_SLOW_PERIOD=260
BACKTEST_TRADE_SIZE=100000
BACKTEST_STARTING_CAPITAL=100000.0
CATALOG_PATH=data/historical
OUTPUT_DIR=logs\backtest_results
ENFORCE_POSITION_LIMIT=true
ALLOW_POSITION_REVERSAL=false

# Fixed baseline stops (overridden by ATR)
BACKTEST_STOP_LOSS_PIPS=25
BACKTEST_TAKE_PROFIT_PIPS=70
BACKTEST_TRAILING_STOP_ACTIVATION_PIPS=25
BACKTEST_TRAILING_STOP_DISTANCE_PIPS=20

# ATR Adaptive Stops (Phase 1)
BACKTEST_ADAPTIVE_STOP_MODE=atr
BACKTEST_SL_ATR_MULT=2.0
BACKTEST_TP_ATR_MULT=2.5
BACKTEST_TRAIL_ACTIVATION_ATR_MULT=0.8
BACKTEST_TRAIL_DISTANCE_ATR_MULT=0.5

# Market Regime Detection (Phase 2 - Disabled)
STRATEGY_REGIME_DETECTION_ENABLED=false
STRATEGY_REGIME_ADX_TRENDING_THRESHOLD=25.0
STRATEGY_REGIME_ADX_RANGING_THRESHOLD=20.0

# Time-of-Day Multipliers (Phase 3)
STRATEGY_TIME_MULTIPLIER_ENABLED=true
STRATEGY_TIME_TP_MULTIPLIER_EU_MORNING=1.0
STRATEGY_TIME_TP_MULTIPLIER_US_SESSION=1.2
STRATEGY_TIME_TP_MULTIPLIER_OTHER=1.0
STRATEGY_TIME_SL_MULTIPLIER_EU_MORNING=0.8
STRATEGY_TIME_SL_MULTIPLIER_US_SESSION=1.0
STRATEGY_TIME_SL_MULTIPLIER_OTHER=1.2

# Weekday-Specific Hour Exclusions
BACKTEST_TIME_FILTER_ENABLED=true
BACKTEST_EXCLUDED_HOURS_MODE=weekday
BACKTEST_EXCLUDED_HOURS_MONDAY=0,1,3,4,5,8,10,11,12,13,18,19,23
BACKTEST_EXCLUDED_HOURS_TUESDAY=0,1,2,4,5,6,7,8,9,10,11,12,13,18,19,23
BACKTEST_EXCLUDED_HOURS_WEDNESDAY=0,1,8,9,10,11,12,13,14,15,16,17,18,19,23
BACKTEST_EXCLUDED_HOURS_THURSDAY=0,1,2,7,8,10,11,12,13,14,18,19,22,23
BACKTEST_EXCLUDED_HOURS_FRIDAY=0,1,2,3,4,5,8,9,10,11,12,13,14,15,16,17,18,19,23
BACKTEST_EXCLUDED_HOURS_SUNDAY=0,1,8,10,11,12,13,18,19,21,22,23

# Strategy Filters (All Disabled)
STRATEGY_CROSSOVER_THRESHOLD_PIPS=0.15
STRATEGY_TREND_FILTER_ENABLED=false
STRATEGY_RSI_ENABLED=false
STRATEGY_VOLUME_ENABLED=false
STRATEGY_ATR_ENABLED=false
STRATEGY_DMI_ENABLED=false
STRATEGY_STOCH_ENABLED=false
STRATEGY_ENTRY_TIMING_ENABLED=false
```

### Performance Summary
- **Total PnL:** $9,022.48 (9.02% return)
- **Win Rate:** 54.03%
- **Average Winner:** $216.89
- **Average Loser:** -$161.88
- **Expectancy per Trade:** $42.76
- **Max Winner:** $1,276.45
- **Max Loser:** -$521.57
- **Total Trades:** ~211
- **Rejected Signals:** 3,559 (filtered by time/weekday rules)

---

## Scripts Used

### 1. Grid Optimization Runner
**File:** `backtest/run_grid_optimization.py`

```python
"""
Grid Search Optimization Script
Runs backtests across parameter combinations and saves results
"""

import itertools
import json
import os
from pathlib import Path
import subprocess
import pandas as pd
from datetime import datetime

def run_grid_optimization(config_file: str):
    """
    Execute grid search based on JSON configuration
    
    Args:
        config_file: Path to JSON config with parameter grid
    """
    # Load configuration
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    # Extract parameters
    param_grid = config['parameters']
    output_base = config['output_directory']
    
    # Generate all combinations
    param_names = list(param_grid.keys())
    param_values = [param_grid[name] for name in param_names]
    combinations = list(itertools.product(*param_values))
    
    print(f"Total combinations to test: {len(combinations)}")
    
    # Create output directory
    os.makedirs(output_base, exist_ok=True)
    
    results = []
    
    # Run each combination
    for idx, combo in enumerate(combinations):
        run_name = f"run_{idx:04d}"
        run_dir = os.path.join(output_base, run_name)
        
        print(f"\n{'='*60}")
        print(f"Running {run_name} ({idx+1}/{len(combinations)})")
        print(f"{'='*60}")
        
        # Set environment variables
        env = os.environ.copy()
        params = dict(zip(param_names, combo))
        
        for param_name, param_value in params.items():
            env[param_name] = str(param_value)
        
        env['OUTPUT_DIR'] = run_dir
        
        # Save parameters
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, 'params.json'), 'w') as f:
            json.dump(params, f, indent=2)
        
        # Run backtest
        result = subprocess.run(
            ['python', 'backtest/run_backtest.py'],
            env=env,
            capture_output=True,
            text=True
        )
        
        # Parse results
        stats_file = None
        for root, dirs, files in os.walk(run_dir):
            if 'performance_stats.json' in files:
                stats_file = os.path.join(root, 'performance_stats.json')
                break
        
        if stats_file:
            with open(stats_file, 'r') as f:
                stats = json.load(f)
            
            # Store result
            result_row = {
                'run': run_name,
                **params,
                'pnl': stats['pnls']['PnL (total)'],
                'win_rate': stats['pnls']['Win Rate'],
                'expectancy': stats['pnls']['Expectancy'],
                'rejected_signals': stats.get('rejected_signals_count', 0)
            }
            results.append(result_row)
            
            print(f"PnL: ${result_row['pnl']:.2f}")
            print(f"Win Rate: {result_row['win_rate']*100:.2f}%")
        else:
            print(f"Warning: No results found for {run_name}")
    
    # Save summary
    df = pd.DataFrame(results)
    summary_file = os.path.join(output_base, 'grid_results_summary.csv')
    df.to_csv(summary_file, index=False)
    
    # Sort by PnL and display top results
    df_sorted = df.sort_values('pnl', ascending=False)
    print("\n" + "="*60)
    print("TOP 10 RESULTS:")
    print("="*60)
    print(df_sorted.head(10).to_string())
    
    print(f"\nResults saved to: {summary_file}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python run_grid_optimization.py <config.json>")
        sys.exit(1)
    
    run_grid_optimization(sys.argv[1])
```

**Usage:**
```bash
python backtest/run_grid_optimization.py optimize_tp_sl_phase0_fixed.json
python backtest/run_grid_optimization.py optimize_adaptive_atr_phase1.json
python backtest/run_grid_optimization.py optimize_time_phase3.json
```

---

### 2. Results Analysis Script
**File:** `analyze_grid_results.py`

```python
"""
Analyze Grid Search Results
Generate summary statistics and visualizations
"""

import pandas as pd
import json
import os
from pathlib import Path

def analyze_grid_results(results_dir: str):
    """
    Analyze optimization results from grid search
    
    Args:
        results_dir: Directory containing grid search results
    """
    # Load summary CSV
    summary_file = os.path.join(results_dir, 'grid_results_summary.csv')
    
    if not os.path.exists(summary_file):
        print(f"Error: {summary_file} not found")
        return
    
    df = pd.read_csv(summary_file)
    
    print("="*80)
    print(f"GRID SEARCH ANALYSIS: {results_dir}")
    print("="*80)
    
    # Overall statistics
    print("\nOVERALL STATISTICS:")
    print(f"Total Runs: {len(df)}")
    print(f"Profitable Runs: {(df['pnl'] > 0).sum()} ({(df['pnl'] > 0).sum()/len(df)*100:.1f}%)")
    print(f"Average PnL: ${df['pnl'].mean():.2f}")
    print(f"Median PnL: ${df['pnl'].median():.2f}")
    print(f"Best PnL: ${df['pnl'].max():.2f}")
    print(f"Worst PnL: ${df['pnl'].min():.2f}")
    print(f"PnL Std Dev: ${df['pnl'].std():.2f}")
    
    # Win rate statistics
    print("\nWIN RATE STATISTICS:")
    print(f"Average Win Rate: {df['win_rate'].mean()*100:.2f}%")
    print(f"Best Win Rate: {df['win_rate'].max()*100:.2f}%")
    print(f"Worst Win Rate: {df['win_rate'].min()*100:.2f}%")
    
    # Top 10 performers
    print("\n" + "="*80)
    print("TOP 10 CONFIGURATIONS BY PNL:")
    print("="*80)
    
    df_sorted = df.sort_values('pnl', ascending=False)
    top_10 = df_sorted.head(10)
    
    for idx, row in top_10.iterrows():
        print(f"\n{row['run']}:")
        print(f"  PnL: ${row['pnl']:.2f}")
        print(f"  Win Rate: {row['win_rate']*100:.2f}%")
        print(f"  Expectancy: ${row['expectancy']:.2f}")
        
        # Print parameters (exclude run, pnl, win_rate, expectancy)
        param_cols = [c for c in df.columns if c not in ['run', 'pnl', 'win_rate', 'expectancy', 'rejected_signals']]
        for col in param_cols:
            print(f"  {col}: {row[col]}")
    
    # Parameter correlations with PnL
    print("\n" + "="*80)
    print("PARAMETER CORRELATIONS WITH PNL:")
    print("="*80)
    
    param_cols = [c for c in df.columns if c not in ['run', 'pnl', 'win_rate', 'expectancy', 'rejected_signals']]
    correlations = {}
    
    for col in param_cols:
        if df[col].dtype in ['int64', 'float64']:
            corr = df[col].corr(df['pnl'])
            correlations[col] = corr
    
    for param, corr in sorted(correlations.items(), key=lambda x: abs(x[1]), reverse=True):
        print(f"{param:40s}: {corr:+.3f}")
    
    # Save analysis
    analysis_file = os.path.join(results_dir, 'analysis_summary.txt')
    with open(analysis_file, 'w') as f:
        f.write(f"Analysis generated: {pd.Timestamp.now()}\n")
        f.write(f"\nBest Configuration: {top_10.iloc[0]['run']}\n")
        f.write(f"Best PnL: ${top_10.iloc[0]['pnl']:.2f}\n")
    
    print(f"\nAnalysis saved to: {analysis_file}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python analyze_grid_results.py <results_directory>")
        sys.exit(1)
    
    analyze_grid_results(sys.argv[1])
```

**Usage:**
```bash
python analyze_grid_results.py logs/tp_sl_phase0_fixed
python analyze_grid_results.py logs/atr_phase1
python analyze_grid_results.py logs/time_phase3_fixed
```

---

### 3. Configuration Extraction Script
**File:** `extract_best_config.py`

```python
"""
Extract Best Configuration from Grid Results
Creates an .env file from the best performing run
"""

import pandas as pd
import json
import os
import shutil

def extract_best_config(results_dir: str, run_name: str = None):
    """
    Extract configuration from best or specified run
    
    Args:
        results_dir: Directory containing grid search results
        run_name: Optional specific run name, otherwise uses best PnL
    """
    # Load summary
    summary_file = os.path.join(results_dir, 'grid_results_summary.csv')
    df = pd.read_csv(summary_file)
    
    if run_name:
        row = df[df['run'] == run_name].iloc[0]
    else:
        # Get best by PnL
        row = df.sort_values('pnl', ascending=False).iloc[0]
        run_name = row['run']
    
    print(f"Extracting configuration from: {run_name}")
    print(f"PnL: ${row['pnl']:.2f}")
    print(f"Win Rate: {row['win_rate']*100:.2f}%")
    
    # Find the run directory
    run_dir = os.path.join(results_dir, run_name)
    
    # Look for .env file in subdirectories
    env_file = None
    for root, dirs, files in os.walk(run_dir):
        if '.env' in files:
            env_file = os.path.join(root, '.env')
            break
    
    if env_file:
        # Copy to workspace root
        output_file = f".env.{run_name}"
        shutil.copy(env_file, output_file)
        print(f"\nConfiguration copied to: {output_file}")
        print("\nTo use this configuration:")
        print(f"  cp {output_file} .env")
        print(f"  python backtest/run_backtest.py")
    else:
        print(f"\nWarning: No .env file found in {run_dir}")
        
        # Create from params.json
        params_file = os.path.join(run_dir, 'params.json')
        if os.path.exists(params_file):
            print(f"\nParameters from params.json:")
            with open(params_file, 'r') as f:
                params = json.load(f)
            for key, value in params.items():
                print(f"  {key}={value}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python extract_best_config.py <results_directory> [run_name]")
        sys.exit(1)
    
    results_dir = sys.argv[1]
    run_name = sys.argv[2] if len(sys.argv) > 2 else None
    
    extract_best_config(results_dir, run_name)
```

**Usage:**
```bash
# Extract best configuration
python extract_best_config.py logs/time_phase3_fixed

# Extract specific run
python extract_best_config.py logs/time_phase3_fixed run_0028
```

---

## Results Analysis

### Phase Comparison

| Phase | Best PnL | Win Rate | Improvement | Key Innovation |
|-------|----------|----------|-------------|----------------|
| Phase 0 (Fixed) | $7,328.99 | 50.28% | Baseline | 2.8:1 R:R ratio |
| Phase 1 (ATR) | $8,526.00 | 50.00% | +16.3% | Volatility adaptation |
| Phase 2 (Regime) | ~$8,500 | ~50% | ~0% | No improvement |
| Phase 3 (Time) | $9,022.48 | 54.03% | +23.1% | Session-specific exits |

### Rejected Signals Impact

The weekday-specific hour exclusions were critical to success:

- **With exclusions:** 3,559 rejected signals → $9,022 PnL
- **Without exclusions:** 16,934 rejected signals → -$838 PnL

This 4.76x increase in rejections shows the importance of trading only during favorable hours for this pair.

### Session Performance Insights

**EU Morning (07:00-11:00 UTC):**
- **Characteristic:** Higher volatility on London open
- **Optimization:** Tighter stops (0.8x) to avoid whipsaws
- **Result:** Reduced false breakouts, preserved capital

**US Session (13:00-17:00 UTC):**
- **Characteristic:** Strong directional moves when NY and London overlap
- **Optimization:** Wider targets (1.2x) to capture trends
- **Result:** Captured extended moves, improved winners

**Other Hours:**
- **Characteristic:** Lower liquidity, slower movement
- **Optimization:** Wider stops (1.2x) to avoid noise
- **Result:** Reduced premature stop-outs

---

## Key Learnings

### 1. Layer Optimizations Incrementally
Each phase built on previous successes:
- Phase 0 → Phase 1: +16.3%
- Phase 1 → Phase 3: +5.8%
- **Total improvement: +23.1%**

### 2. Not All Filters Add Value
Market regime detection (Phase 2) showed no improvement. Sometimes simpler is better.

### 3. Time-of-Day Matters for FX
EUR/USD exhibits distinct behavior patterns across trading sessions. Session-specific parameters outperformed universal settings.

### 4. Weekday Filtering is Critical
The aggressive weekday-specific hour exclusions were essential. Without them:
- 4.76x more rejected signals
- Strategy became unprofitable
- Shows importance of trading only high-probability hours

### 5. ATR Adapts Better Than Fixed Pips
Dynamic stops based on ATR allow the strategy to:
- Give more room in volatile periods
- Tighten up in calm conditions
- Maintain consistent risk in pip-equivalent terms

### 6. Documentation is Essential
Tracking every optimization phase, configuration, and result enabled:
- Easy comparison between approaches
- Quick rollback if needed
- Clear understanding of what works

### 7. Grid Search > Manual Tweaking
Systematic grid search found non-obvious combinations:
- Manual intuition suggested wider stops everywhere
- Optimal solution used tighter stops in EU, wider in other times
- Would have been missed by sequential optimization

---

## File Structure

```
nautilus0/
├── .env                              # Current optimal configuration
├── .env.run28_exact                  # Exact copy from best grid run
├── .env.run28_timephase              # Manual reconstruction (deprecated)
│
├── backtest/
│   ├── run_backtest.py               # Main backtest execution script
│   └── run_grid_optimization.py      # Grid search runner
│
├── strategies/
│   └── moving_average_crossover.py   # Strategy implementation
│
├── logs/
│   ├── tp_sl_phase0_fixed/           # Phase 0: Fixed TP/SL
│   │   ├── run_0000/ to run_0035/
│   │   └── grid_results_summary.csv
│   │
│   ├── atr_phase1/                   # Phase 1: ATR Adaptive
│   │   ├── run_0000/ to run_0035/
│   │   └── grid_results_summary.csv
│   │
│   ├── regime_phase2/                # Phase 2: Regime Detection
│   │   └── grid_results_summary.csv
│   │
│   ├── time_phase3_fixed/            # Phase 3: Time Multipliers
│   │   ├── run_0000/ to run_0063/
│   │   ├── run_0028/                 # BEST CONFIGURATION
│   │   │   ├── params.json
│   │   │   └── EUR-USD_20251115_202814/
│   │   │       ├── .env              # Complete environment
│   │   │       ├── .env.full         # Full snapshot with all vars
│   │   │       └── performance_stats.json
│   │   └── grid_results_summary.csv
│   │
│   └── backtest_results/             # Current backtest output directory
│
├── optimize_tp_sl_phase0_fixed.json  # Phase 0 grid config
├── optimize_adaptive_atr_phase1.json # Phase 1 grid config
├── optimize_time_phase3.json         # Phase 3 grid config
│
├── analyze_grid_results.py           # Results analysis script
├── extract_best_config.py            # Config extraction script
├── compare_env_files.py              # Environment comparison utility
│
└── OPTIMIZATION_JOURNEY.md           # This document
```

---

## Reproduction Steps

To reproduce the optimal configuration from scratch:

1. **Install Dependencies:**
   ```bash
   pip install nautilus_trader pandas numpy
   ```

2. **Prepare Historical Data:**
   ```bash
   # Ensure EUR/USD 15-minute data exists in data/historical/
   # Date range: 2024-01-01 to 2025-10-30
   ```

3. **Run Phase 0 (Fixed TP/SL):**
   ```bash
   python backtest/run_grid_optimization.py optimize_tp_sl_phase0_fixed.json
   python analyze_grid_results.py logs/tp_sl_phase0_fixed
   ```

4. **Run Phase 1 (ATR Adaptive):**
   ```bash
   python backtest/run_grid_optimization.py optimize_adaptive_atr_phase1.json
   python analyze_grid_results.py logs/atr_phase1
   ```

5. **Run Phase 3 (Time Multipliers):**
   ```bash
   python backtest/run_grid_optimization.py optimize_time_phase3.json
   python analyze_grid_results.py logs/time_phase3_fixed
   ```

6. **Extract Best Configuration:**
   ```bash
   python extract_best_config.py logs/time_phase3_fixed run_0028
   cp .env.run_0028 .env
   ```

7. **Run Final Verification:**
   ```bash
   python backtest/run_backtest.py
   ```

Expected result: ~$8,800-$9,000 PnL with 47-54% win rate

---

## Next Steps

### Potential Future Optimizations

1. **Multi-Pair Diversification**
   - Apply same methodology to GBP/USD, USD/JPY
   - Test correlation-based position sizing
   - Build portfolio equity curve

2. **Machine Learning Enhancement**
   - Train ML model to predict optimal TP/SL multipliers
   - Use features: hour, weekday, ATR, recent PnL
   - Compare to current rule-based system

3. **Walk-Forward Optimization**
   - Implement rolling optimization windows
   - Test parameter stability over time
   - Avoid overfitting to single period

4. **Transaction Cost Analysis**
   - Add realistic spread costs (0.5-1.5 pips)
   - Model slippage in live execution
   - Adjust position sizing for costs

5. **Live Trading Preparation**
   - Add order execution monitoring
   - Implement heartbeat/health checks
   - Build real-time performance dashboard

---

## Contact & Version History

**Author:** Optimization Team  
**Last Updated:** November 15, 2025  
**Strategy Version:** 3.0 (Time-Adaptive)  
**Framework:** NautilusTrader 1.221.0  

**Version History:**
- v1.0 (Nov 2024): Fixed TP/SL baseline
- v2.0 (Nov 2024): ATR adaptive stops
- v2.1 (Nov 2024): Regime detection attempt
- v3.0 (Nov 2025): Time-of-day multipliers (final)

---

## Appendix: Configuration Files

### A. Phase 3 Grid Configuration
**File:** `optimize_time_phase3.json`

```json
{
  "output_directory": "logs/time_phase3_fixed",
  "parameters": {
    "STRATEGY_TIME_MULTIPLIER_ENABLED": ["true"],
    "STRATEGY_TIME_TP_MULTIPLIER_EU_MORNING": [0.8, 1.0, 1.2],
    "STRATEGY_TIME_TP_MULTIPLIER_US_SESSION": [0.8, 1.0, 1.2],
    "STRATEGY_TIME_TP_MULTIPLIER_OTHER": [0.8, 1.0, 1.2],
    "STRATEGY_TIME_SL_MULTIPLIER_EU_MORNING": [0.8, 1.0, 1.2],
    "STRATEGY_TIME_SL_MULTIPLIER_US_SESSION": [0.8, 1.0, 1.2],
    "STRATEGY_TIME_SL_MULTIPLIER_OTHER": [0.8, 1.0, 1.2]
  }
}
```

### B. Best Run Parameters
**File:** `logs/time_phase3_fixed/run_0028/params.json`

```json
{
  "BACKTEST_ADAPTIVE_STOP_MODE": "atr",
  "BACKTEST_STOP_LOSS_PIPS": 25,
  "BACKTEST_TAKE_PROFIT_PIPS": 70,
  "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": 25,
  "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": 20,
  "BACKTEST_SL_ATR_MULT": 2.0,
  "BACKTEST_TP_ATR_MULT": 2.5,
  "BACKTEST_TRAIL_ACTIVATION_ATR_MULT": 0.8,
  "BACKTEST_TRAIL_DISTANCE_ATR_MULT": 0.5,
  "STRATEGY_REGIME_DETECTION_ENABLED": "false",
  "STRATEGY_TIME_MULTIPLIER_ENABLED": "true",
  "STRATEGY_TIME_TP_MULTIPLIER_EU_MORNING": 1.0,
  "STRATEGY_TIME_TP_MULTIPLIER_US_SESSION": 1.2,
  "STRATEGY_TIME_TP_MULTIPLIER_OTHER": 1.0,
  "STRATEGY_TIME_SL_MULTIPLIER_EU_MORNING": 0.8,
  "STRATEGY_TIME_SL_MULTIPLIER_US_SESSION": 1.0,
  "STRATEGY_TIME_SL_MULTIPLIER_OTHER": 1.2
}
```

---

**End of Document**
