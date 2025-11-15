"""
Grid-run wrapper that runs backtest runner with environment overrides for adaptive parameters.

This script executes multiple backtests with different adaptive stop configurations
to find optimal parameter combinations. It invokes the existing backtest runner via 
subprocess and writes per-run metadata into a results folder.

Usage:
    python scripts/run_grid_backtest.py [--output-dir logs/grid_runs] [--symbol EUR/USD]
    
    Or use with a JSON config file:
    python scripts/run_grid_backtest.py --config configs/grid.json

The script performs a parameter sweep across:
- Adaptive stop modes ('atr', 'percentile', 'fixed')
- ATR multipliers for SL, TP, trailing activation, and trailing distance
- Volatility window and sensitivity (for percentile mode)

Results are saved to individual folders for each run, with a summary CSV
containing key performance metrics.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd


# Default grid parameters (coarse grid)
DEFAULT_GRID = {
    'adaptive_stop_mode': ['atr', 'percentile', 'fixed'],
    'sl_atr_mult': [1.0, 1.5, 2.0],
    'tp_atr_mult': [2.0, 2.5, 3.0, 3.5],
    'trail_activation_atr_mult': [0.8, 1.0, 1.2],
    'trail_distance_atr_mult': [0.6, 0.8, 1.0],
    'volatility_window': [200],
    'volatility_sensitivity': [0.6],
}

# Fine grid (for refinement after coarse results)
FINE_GRID = {
    'adaptive_stop_mode': ['atr'],
    'sl_atr_mult': [1.25, 1.5, 1.75],
    'tp_atr_mult': [2.25, 2.5, 2.75],
    'trail_activation_atr_mult': [0.9, 1.0, 1.1],
    'trail_distance_atr_mult': [0.7, 0.8, 0.9],
    'volatility_window': [200],
    'volatility_sensitivity': [0.6],
}


def setup_logging(output_dir: Path) -> logging.Logger:
    """Setup logging for the grid runner."""
    log_file = output_dir / 'grid_runner.log'
    
    logger = logging.getLogger('grid_runner')
    logger.setLevel(logging.INFO)
    
    # File handler
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


def format_env_value(value: Any) -> str:
    """Format parameter values for environment variables."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def generate_parameter_combinations(grid: Dict[str, List]) -> List[Dict[str, Any]]:
    """Generate all combinations of parameters from the grid."""
    keys = list(grid.keys())
    values = list(grid.values())
    
    combinations = []
    for combo in product(*values):
        param_dict = dict(zip(keys, combo))
        combinations.append(param_dict)
    
    return combinations


def run_backtest(
    params: Dict[str, Any],
    run_id: int,
    output_dir: Path,
    logger: logging.Logger,
    base_env: Dict[str, str]
) -> Dict[str, Any]:
    """
    Run a single backtest with the given parameters.
    
    Returns a dict with run metadata and performance metrics.
    """
    run_output_dir = output_dir / f'run_{run_id:04d}'
    run_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create environment with overrides
    env = os.environ.copy()
    env.update(base_env)
    
    # Override parameters - handle both formats (with/without BACKTEST_ prefix)
    for key, value in params.items():
        formatted_value = format_env_value(value)

        # If key already has a known prefix (BACKTEST_, STRATEGY_, LIVE_, etc.), use it directly
        if key.startswith(('BACKTEST_', 'STRATEGY_', 'LIVE_', 'DATA_', 'CATALOG_')):
            env[key] = formatted_value

            # Also set BACKTEST_ prefixed variant for STRATEGY_ keys for compatibility with legacy parsing
            if key.startswith('STRATEGY_'):
                env[f'BACKTEST_{key}'] = formatted_value
        else:
            # Convert lowercase underscore format to BACKTEST_ prefix format
            env_key = f'BACKTEST_{key.upper()}'
            env[env_key] = formatted_value
    
    # Set output directory for this run
    env['OUTPUT_DIR'] = str(run_output_dir)
    
    logger.info(f"Run {run_id}: Starting backtest with params: {params}")
    
    # Save run parameters
    params_file = run_output_dir / 'params.json'
    with open(params_file, 'w') as f:
        json.dump(params, f, indent=2)
    
    # Execute backtest
    cmd = [sys.executable, 'backtest/run_backtest.py']
    
    stdout_file = run_output_dir / 'stdout.txt'
    stderr_file = run_output_dir / 'stderr.txt'
    
    try:
        with open(stdout_file, 'w') as stdout_f, open(stderr_file, 'w') as stderr_f:
            result = subprocess.run(
                cmd,
                env=env,
                stdout=stdout_f,
                stderr=stderr_f,
                timeout=600  # 10 minute timeout per run
            )
        
        if result.returncode != 0:
            logger.warning(f"Run {run_id}: Backtest exited with code {result.returncode}")
            return None
        
        # Parse performance stats - they're in a timestamped subdirectory
        # Find the most recent subdirectory (backtest output folder)
        subdirs = [d for d in run_output_dir.iterdir() if d.is_dir()]
        if not subdirs:
            logger.warning(f"Run {run_id}: No output subdirectory found")
            return None
        
        # Get the most recent subdirectory
        latest_subdir = max(subdirs, key=lambda d: d.stat().st_mtime)
        stats_file = latest_subdir / 'performance_stats.json'
        
        if stats_file.exists():
            with open(stats_file, 'r') as f:
                stats = json.load(f)
        else:
            logger.warning(f"Run {run_id}: No performance stats found in {latest_subdir}")
            return None
        
        # Flatten nested stats structure
        flattened_stats = {}
        for key, value in stats.items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    flattened_stats[f"{key}_{subkey}"] = subvalue
            else:
                flattened_stats[key] = value
        
        # Compile run results
        result_dict = {
            'run_id': run_id,
            'timestamp': datetime.now().isoformat(),
            **params,
            **flattened_stats
        }
        
        # Extract key metrics for logging
        net_pnl = stats.get('pnls', {}).get('PnL (total)', 'N/A')
        win_rate = stats.get('pnls', {}).get('Win Rate', 'N/A')
        expectancy = stats.get('pnls', {}).get('Expectancy', 'N/A')
        
        logger.info(
            f"Run {run_id}: Complete - "
            f"Net PnL: {net_pnl}, "
            f"Win Rate: {win_rate if win_rate == 'N/A' else f'{win_rate:.2%}'}, "
            f"Expectancy: {expectancy}"
        )
        
        return result_dict
        
    except subprocess.TimeoutExpired:
        logger.error(f"Run {run_id}: Timeout after 10 minutes")
        return None
    except Exception as e:
        logger.error(f"Run {run_id}: Error - {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='Run grid backtest for adaptive stops optimization')
    parser.add_argument('--output-dir', type=str, default='logs/grid_runs',
                       help='Output directory for grid run results')
    parser.add_argument('--config', type=str, default=None,
                       help='JSON config file with grid parameters')
    parser.add_argument('--grid-type', type=str, default='coarse',
                       choices=['coarse', 'fine'],
                       help='Grid type: coarse (wide search) or fine (refinement)')
    parser.add_argument('--symbol', type=str, default=None,
                       help='Override BACKTEST_SYMBOL (optional)')
    parser.add_argument('--start-date', type=str, default=None,
                       help='Override BACKTEST_START_DATE (optional)')
    parser.add_argument('--end-date', type=str, default=None,
                       help='Override BACKTEST_END_DATE (optional)')
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger = setup_logging(output_dir)
    logger.info("Starting grid backtest runner")
    
    # Load grid configuration
    if args.config:
        logger.info(f"Loading grid config from {args.config}")
        with open(args.config, 'r') as f:
            config_data = json.load(f)
            # Handle both formats: direct dict or nested with 'parameters' key
            if 'parameters' in config_data:
                grid = config_data['parameters']
            else:
                grid = config_data
    else:
        grid = FINE_GRID if args.grid_type == 'fine' else DEFAULT_GRID
        logger.info(f"Using default {args.grid_type} grid")
    
    # Prepare base environment overrides
    base_env = {}
    if args.symbol:
        base_env['BACKTEST_SYMBOL'] = args.symbol
    if args.start_date:
        base_env['BACKTEST_START_DATE'] = args.start_date
    if args.end_date:
        base_env['BACKTEST_END_DATE'] = args.end_date
    
    # Generate parameter combinations
    combinations = generate_parameter_combinations(grid)
    logger.info(f"Generated {len(combinations)} parameter combinations")
    
    # Run backtests
    results = []
    for i, params in enumerate(combinations, 1):
        result = run_backtest(params, i, output_dir, logger, base_env)
        if result is not None:
            results.append(result)
    
    # Save summary results
    if results:
        results_df = pd.DataFrame(results)
        summary_file = output_dir / 'grid_results_summary.csv'
        results_df.to_csv(summary_file, index=False)
        logger.info(f"Saved summary results to {summary_file}")
        
        # Print top 10 by net PnL
        if 'net_pnl' in results_df.columns:
            logger.info("\nTop 10 runs by Net PnL:")
            top_pnl = results_df.nlargest(10, 'net_pnl')
            print(top_pnl[['run_id', 'adaptive_stop_mode', 'sl_atr_mult', 'tp_atr_mult', 
                          'net_pnl', 'win_rate', 'sharpe_ratio']].to_string(index=False))
        
        # Print top 10 by Sharpe ratio
        if 'sharpe_ratio' in results_df.columns:
            logger.info("\nTop 10 runs by Sharpe Ratio:")
            top_sharpe = results_df.nlargest(10, 'sharpe_ratio')
            print(top_sharpe[['run_id', 'adaptive_stop_mode', 'sl_atr_mult', 'tp_atr_mult',
                             'net_pnl', 'win_rate', 'sharpe_ratio']].to_string(index=False))
    else:
        logger.warning("No successful backtest runs")
    
    logger.info(f"Grid backtest complete. Results saved to {output_dir}")
    

if __name__ == '__main__':
    main()
