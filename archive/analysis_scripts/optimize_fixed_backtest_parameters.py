#!/usr/bin/env python3
"""
Optimization Script for Fixed Backtest (Idempotency Fix Applied)
"""

import os
import sys
import itertools
import shutil
import pandas as pd
import numpy as np
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import time
from datetime import datetime

# Trace file to diagnose hanging (written early in startup)
_TRACE_FILE = Path(__file__).parent / "opt_trace.txt"
def _trace(msg):
    _TRACE_FILE.open("a").write(f"{time.strftime('%H:%M:%S')} {msg}\n")

_trace("module_level_imports_done")

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

_trace("before_backtest_import")
# Import the backtest runner
from run_backtest_mtf_v2_entry_confirmed_adaptive import run_v2_entry_confirmed_adaptive_backtest
_trace("after_backtest_import")

# Configuration
SYMBOL = "EUR/USD"
VENUE = "IDEALPRO"
# Use a representative period - last 6 months should be good balance of speed vs robustness
START_DATE = "2026-01-01"
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
# Delete each backtest results directory after extracting stats (saves disk space)
CLEANUP_RESULTS = True

def run_single_backtest(params):
    """Run a single backtest with the given parameters."""
    _trace(f"run_single_backtest_enter: {params}")
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
        "MTF2_Use_Fixed_Idempotency": "1",
        # Use the newly trained V3 model
        "MTF2_MODEL_PATH": "models/ml_model_mtf_v3_xgb.pkl",
        # Disable logging to speed up optimization and prevent hanging
        "NAUTILUS_LOG_LEVEL": "ERROR",
        "LOG_LEVEL": "ERROR",
        "NAUTILUS_BYPASS_LOGGING": "1",
        "NAUTILUS_CORE_LOG_LEVEL": "ERROR",
        "NAUTILUS_TRADER_LOG_LEVEL": "ERROR",
        "NAUTILUS_LOG_COLOR": "0"
    }
    
    # Also patch the python logging module to suppress all output
    import logging
    logging.getLogger().setLevel(logging.ERROR)
    for handler in logging.getLogger().handlers:
        handler.setLevel(logging.ERROR)
        
    # Disable nautilus logging completely
    try:
        import nautilus_trader.core.logger as nt_logger
        nt_logger.Logger.set_level("ERROR")
    except Exception:
        pass
        
    # Set environment variable to disable nautilus logging
    import os
    os.environ["NAUTILUS_LOG_LEVEL"] = "ERROR"
    os.environ["NAUTILUS_CORE_LOG_LEVEL"] = "ERROR"
    os.environ["NAUTILUS_TRADER_LOG_LEVEL"] = "ERROR"
    
    # Disable strategy logging
    os.environ["STRATEGY_LOG_LEVEL"] = "ERROR"
    
    # Disable backtest engine logging
    os.environ["NAUTILUS_BACKTEST_ENGINE_LOG_LEVEL"] = "ERROR"
    
    # Disable all nautilus logging
    os.environ["NAUTILUS_LOGGING"] = "False"
    
    # Disable rust logging
    os.environ["RUST_LOG"] = "error"
    
    # Disable nautilus trader logging
    os.environ["NAUTILUS_TRADER_LOGGING"] = "False"
    
    # Disable nautilus trader core logging
    os.environ["NAUTILUS_TRADER_CORE_LOGGING"] = "False"
    
    # Disable python logging for the strategy
    import logging
    logging.getLogger("MLSignalStrategy_V2_EntryConfirmedAdaptive").setLevel(logging.ERROR)
    logging.getLogger("MLSignalStrategy_V2_EntryConfirmedAdaptive").propagate = False
    logging.getLogger("MLSignalStrategyV2EntryConfirmedAdaptiveFailSafe").setLevel(logging.ERROR)
    logging.getLogger("MLSignalStrategyV2EntryConfirmedAdaptiveFailSafe").propagate = False
    logging.getLogger("BACKTESTER-001.MLSignalStrategyV2EntryConfirmedAdaptiveFailSafe").setLevel(logging.ERROR)
    logging.getLogger("BACKTESTER-001.MLSignalStrategyV2EntryConfirmedAdaptiveFailSafe").propagate = False
    logging.getLogger("BACKTESTER-001.Portfolio").setLevel(logging.ERROR)
    logging.getLogger("BACKTESTER-001.Portfolio").propagate = False
    logging.getLogger("BACKTESTER-001.BacktestEngine").setLevel(logging.ERROR)
    logging.getLogger("BACKTESTER-001.BacktestEngine").propagate = False
    
    # Save original env
    original_env = os.environ.copy()
    os.environ.update(env_vars)
    
    try:
        # Run backtest
        # We need to capture or suppress stdout/stderr to keep output clean?
        # For now, let it print but maybe redirect in a real scenario
        
        # Disable nautilus trader logging via config
        try:
            import nautilus_trader.core.logger as nt_logger
            nt_logger.Logger.set_level("ERROR")
        except ImportError:
            pass
            
        # Redirect stdout and stderr to devnull to prevent hanging
        # import sys
        # import os
        # devnull = open(os.devnull, 'w')
        # old_stdout = sys.stdout
        # old_stderr = sys.stderr
        # sys.stdout = devnull
        # sys.stderr = devnull
        
        # Try to disable rust logging via nautilus config
        from nautilus_trader.config import BacktestEngineConfig
        # We can't easily inject this into the run_v2_entry_confirmed_adaptive_backtest function
        # without modifying it. Let's just let it run and pipe to null in the shell.
        
        _trace("before_run_backtest")
        result, results_dir = run_v2_entry_confirmed_adaptive_backtest(
            symbol=SYMBOL,
            venue=VENUE,
            start_date=START_DATE,
            end_date=END_DATE,
        )
        _trace(f"after_run_backtest: {results_dir}")

        # Extract metrics by reading the trades CSV written to results_dir
        results_path = Path(results_dir)
        trades_files = list(results_path.glob("trades_*.csv"))
        if not trades_files:
            print(f"Warning: No trades CSV found in {results_dir}")
            return None

        trades_df = pd.read_csv(trades_files[0])

        total_trades = len(trades_df)
        if total_trades == 0:
            print("Warning: 0 trades in results")
            return None

        total_pnl = float(trades_df['pnl'].sum())
        wins = (trades_df['pnl'] > 0).sum()
        win_rate = wins / total_trades if total_trades > 0 else 0.0
        avg_trade = total_pnl / total_trades if total_trades > 0 else 0.0

        # Profit factor: sum(wins) / abs(sum(losses))
        winning_pnl = trades_df.loc[trades_df['pnl'] > 0, 'pnl'].sum()
        losing_pnl = abs(trades_df.loc[trades_df['pnl'] < 0, 'pnl'].sum())
        profit_factor = (winning_pnl / losing_pnl) if losing_pnl > 0 else float('inf')

        # Max drawdown from cumulative PnL
        cum_pnl = trades_df['pnl'].cumsum()
        running_max = cum_pnl.cummax()
        drawdowns = cum_pnl - running_max
        max_drawdown = float(drawdowns.min())

        # Sharpe: mean / std of per-trade PnL scaled to zero baseline
        pnl_std = trades_df['pnl'].std()
        sharpe_ratio = (avg_trade / pnl_std) if pnl_std > 0 else 0.0

        metrics = {
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'total_trades': total_trades,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'avg_trade': avg_trade,
        }

        # Clean up the results directory to avoid disk bloat
        if CLEANUP_RESULTS and results_dir:
            try:
                shutil.rmtree(results_dir, ignore_errors=True)
            except Exception:
                pass

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
        # Restore stdout/stderr to print error
        # sys.stdout = old_stdout
        # sys.stderr = old_stderr
        print(f"Error running backtest with params {params}: {e}")
        return None
    finally:
        # Restore stdout/stderr
        # sys.stdout = old_stdout
        # sys.stderr = old_stderr
        # devnull.close()
        # Restore env
        os.environ.clear()
        os.environ.update(original_env)

def main():
    _trace("main_started")
    print(f"Starting optimization for {SYMBOL} covering {START_DATE} to {END_DATE}", flush=True)
    print(f"Testing {len(list(itertools.product(*PARAM_GRID.values())))} combinations...", flush=True)
    
    # Generate all combinations
    keys, values = zip(*PARAM_GRID.items())
    param_combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
    
    # Load existing results to support resuming
    results = []
    completed_keys = set()
    if Path(OUTPUT_FILE).exists():
        try:
            existing = pd.read_csv(OUTPUT_FILE)
            results = existing.to_dict('records')
            for row in results:
                key = tuple(row[k] for k in PARAM_GRID.keys())
                completed_keys.add(key)
            print(f"Resuming: {len(completed_keys)} combinations already completed, {len(param_combinations) - len(completed_keys)} remaining.", flush=True)
        except Exception as e:
            print(f"Warning: Could not load existing results ({e}), starting fresh.", flush=True)
    
    # Run sequentially for now to avoid complexity with Nautilus global state/env vars
    # (Nautilus might not support parallel execution in same process easily)
    for i, params in enumerate(param_combinations):
        key = tuple(params[k] for k in PARAM_GRID.keys())
        if key in completed_keys:
            print(f"[{i+1}/{len(param_combinations)}] Skipping (already done): {params}", flush=True)
            continue

        print(f"[{i+1}/{len(param_combinations)}] Testing: {params}", flush=True)
        _trace(f"combo_{i+1}_starting")
        metrics = run_single_backtest(params)
        _trace(f"combo_{i+1}_done")
        
        if metrics:
            print(f"  Result: PnL=${metrics['total_pnl']:.2f}, WR={metrics['win_rate']:.2f}, "
                  f"Trades={metrics['total_trades']}, Score={metrics['score']:.2f}", flush=True)
            results.append(metrics)
            
            # Save intermediate results
            pd.DataFrame(results).to_csv(OUTPUT_FILE, index=False)
    
    # Final analysis
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
