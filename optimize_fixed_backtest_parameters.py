#!/usr/bin/env python3
"""
Optimization Script for Fixed Backtest (Idempotency Fix Applied)

This script re-optimizes key parameters now that the bar delivery bug is fixed.
The previous optimizations were invalid because they were tuned on buggy signals.

Parameters to optimize:
1. Stop Loss ATR Multiplier (SL)
2. Take Profit ATR Multiplier Position 1 (TP1)
3. Take Profit ATR Multiplier Position 2 (TP2)
4. MAMA Filter Threshold (MAMA)

Usage:
    python optimize_fixed_backtest_parameters.py
"""

import os
import sys
import itertools
import pandas as pd
import numpy as np
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import time
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import the backtest runner
from run_backtest_mtf_v2_entry_confirmed_adaptive import run_v2_entry_confirmed_adaptive_backtest

# Configuration
SYMBOL = "EUR/USD"
VENUE = "IDEALPRO"
# Use a representative period - last 6 months should be good balance of speed vs robustness
START_DATE = "2025-08-01"
END_DATE = "2026-02-20"

# Parameter ranges to test - Optimized reduced grid for reasonable runtime in session
# 36 combinations * ~30s = ~18 mins serial, or faster parallel
PARAM_GRID = {
    'sl_atr_mult': [1.5, 2.0, 2.5],
    'tp1_atr_mult': [1.2, 1.5, 1.8],
    'tp2_atr_mult': [2.0, 3.0],
    'mama_min_diff': [0.0001, 0.0002]
}

OUTPUT_FILE = "optimization_results_fixed_20260221.csv"

def run_single_backtest(params):
    """Run a single backtest with the given parameters."""
    start_ts = time.time()
    
    # Set environment variables for this run
    # Note: checks if these env vars are actually used by the config loader
    # The config loader usually reads from .env.mtf_v2, so we might need to override
    # strictly via env vars if the config loader supports it, or modify the .env file.
    # Looking at config/mtf_v2_config.py usually it loads from env vars if present.
    
    # We will assume the config loader respects os.environ overrides
    env_vars = {
        "MTF2_SL_ATR_MULT": str(params['sl_atr_mult']),
        "MTF2_POS1_TP_ATR_MULT": str(params['tp1_atr_mult']),
        "MTF2_POS2_TP_ATR_MULT": str(params['tp2_atr_mult']),
        "MTF2_META_FILTER_MAMA_MIN_DIFF": str(params['mama_min_diff']),
        # Disable parity debug for optimization speed
        "MTF2_DMI_PARITY_DEBUG": "0",
        # Ensure we are using the fixed logic
        "MTF2_Use_Fixed_Idempotency": "1" 
    }
    
    # Save original env
    original_env = os.environ.copy()
    os.environ.update(env_vars)
    
    try:
        # Run backtest
        # We need to capture or suppress stdout/stderr to keep output clean?
        # For now, let it print but maybe redirect in a real scenario
        
        result, results_dir = run_v2_entry_confirmed_adaptive_backtest(
            symbol=SYMBOL,
            venue=VENUE,
            start_date=START_DATE,
            end_date=END_DATE,
        )
        
        # Extract metrics from result object (BacktestResult)
        stats = result.stats_engine.get_stats()
        
        metrics = {
            'total_pnl': stats.get('total_pnl', 0.0),
            'win_rate': stats.get('win_rate', 0.0),
            'total_trades': stats.get('total_trades', 0),
            'profit_factor': stats.get('profit_factor', 0.0),
            'sharpe_ratio': stats.get('sharpe_ratio', 0.0),
            'max_drawdown': stats.get('max_drawdown', 0.0),
            'avg_trade': stats.get('avg_trade', 0.0),
        }
        
        # Calculate custom score
        # Weighted: 40% PnL, 30% WinRate, 30% Drawdown penalty
        pnl_score = (metrics['total_pnl'] / 10000) * 100
        wr_score = (metrics['win_rate'] - 0.50) * 200  # 0.55 -> 10 pts
        dd_penalty = (abs(metrics['max_drawdown']) / 1000) * 100
        
        metrics['score'] = (pnl_score * 0.4) + (wr_score * 0.3) - (dd_penalty * 0.3)
        metrics['duration'] = time.time() - start_ts
        metrics.update(params)
        
        return metrics
        
    except Exception as e:
        print(f"Error running backtest with params {params}: {e}")
        return None
    finally:
        # Restore env
        os.environ.clear()
        os.environ.update(original_env)

def main():
    print(f"Starting optimization for {SYMBOL} covering {START_DATE} to {END_DATE}")
    print(f"Testing {len(list(itertools.product(*PARAM_GRID.values())))} combinations...")
    
    # Generate all combinations
    keys, values = zip(*PARAM_GRID.items())
    param_combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
    
    results = []
    
    # Run in parallel using ProcessPoolExecutor
    max_workers = min(os.cpu_count() or 1, 4)  # Cap at 4 workers to avoid OOM
    print(f"Running optimization with {max_workers} parallel workers...")
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_params = {executor.submit(run_single_backtest, params): params for params in param_combinations}
        
        for i, future in enumerate(as_completed(future_to_params)):
            params = future_to_params[future]
            try:
                metrics = future.result()
                if metrics:
                    print(f"[{i+1}/{len(param_combinations)}] Result: PnL=${metrics['total_pnl']:.2f}, "
                          f"WR={metrics['win_rate']:.2f}, Score={metrics['score']:.2f} "
                          f"(Params: SL={metrics['sl_atr_mult']}, TP1={metrics['tp1_atr_mult']})")
                    results.append(metrics)
                    
                    # Save periodically
                    if (i + 1) % 5 == 0:
                        pd.DataFrame(results).to_csv(OUTPUT_FILE, index=False)
            except Exception as exc:
                print(f"Generated an exception: {exc}")

    # Final save
    if results:
        df = pd.DataFrame(results)
        df = df.sort_values('score', ascending=False)
        
        print("\nOptimization Complete!")
        print(f"Top 5 parameter sets:")
        print(df.head(5)[list(PARAM_GRID.keys()) + ['total_pnl', 'win_rate', 'total_trades', 'score']])
        
        best_params = df.iloc[0]
        print(f"\nBest Parameters:")
        for k in PARAM_GRID.keys():
            print(f"  {k}: {best_params[k]}")
            
        print(f"\nResults saved to {OUTPUT_FILE}")
    else:
        print("No valid results obtained.")

if __name__ == "__main__":
    main()
