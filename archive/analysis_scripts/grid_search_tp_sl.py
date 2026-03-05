"""
Grid Search for Confidence-Based TP/SL Parameters

Runs multiple backtests with different confidence thresholds and SL/TP multipliers.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Tuple
import pandas as pd

# Grid parameters (reduced for feasibility)
CONF_HIGH_THRESHES = [0.7, 0.75]
CONF_MED_THRESHES = [0.6]

SL_HIGH_OPTIONS = [1.0, 1.2]
TP1_HIGH_OPTIONS = [0.8, 1.0]
TP2_HIGH_OPTIONS = [1.8]

SL_MED_OPTIONS = [1.3]
TP1_MED_OPTIONS = [0.6, 0.7]
TP2_MED_OPTIONS = [1.4]

SL_LOW_OPTIONS = [1.5, 1.7]
TP1_LOW_OPTIONS = [0.4]
TP2_LOW_OPTIONS = [1.0]

def parse_summary(summary_path: Path) -> Dict[str, float]:
    """Parse key metrics from summary.txt"""
    with open(summary_path, 'r') as f:
        content = f.read()
    
    metrics = {}
    
    # Extract Total Trades
    if 'Total Trades:' in content:
        lines = content.split('\n')
        for line in lines:
            if 'Total Trades:' in line:
                metrics['trades'] = int(line.split('Total Trades:')[1].strip())
            elif 'Total P&L:' in line:
                pnl_str = line.split('Total P&L:')[1].strip().replace('$', '').replace(',', '')
                metrics['pnl'] = float(pnl_str)
            elif 'Win Rate:' in line:
                wr_str = line.split('Win Rate:')[1].strip().replace('%', '')
                metrics['win_rate'] = float(wr_str)
    
    return metrics

def run_backtest(params: Dict[str, float]) -> Dict[str, float]:
    """Run a single backtest with given parameters"""
    
    # Set environment variables
    env = os.environ.copy()
    for key, value in params.items():
        env[f'MTF2_{key}'] = str(value)
    
    # Run the backtest
    try:
        result = subprocess.run(
            ['python', 'run_backtest_mtf_v2_entry_confirmed_dmi_relative_dynamic.py'],
            env=env,
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=3600  # 1 hour timeout
        )
        
        if result.returncode == 0:
            # Find the latest backtest directory
            backtest_dirs = list(Path('backtest_results').glob('MTF_V2_DMI_RELATIVE_DYNAMIC_*'))
            if backtest_dirs:
                latest_dir = max(backtest_dirs, key=lambda x: x.stat().st_mtime)
                summary_path = latest_dir / 'summary.txt'
                if summary_path.exists():
                    return parse_summary(summary_path)
    
    except subprocess.TimeoutExpired:
        print(f"Backtest timed out for params: {params}")
    except Exception as e:
        print(f"Error running backtest: {e}")
    
    return {'trades': 0, 'pnl': 0, 'win_rate': 0}

def main():
    results = []
    
    # Load existing results if they exist
    results_file = Path('grid_search_results.csv')
    if results_file.exists():
        existing_df = pd.read_csv(results_file)
        results = existing_df.to_dict('records')
        print(f"Loaded {len(results)} existing results from {results_file}")
    
    # Create set of completed parameter combinations
    completed_params = set()
    for result in results:
        param_tuple = (
            result['CONF_HIGH_THRESH'], result['CONF_MED_THRESH'],
            result['SL_HIGH'], result['TP1_HIGH'], result['TP2_HIGH'],
            result['SL_MED'], result['TP1_MED'], result['TP2_MED'],
            result['SL_LOW'], result['TP1_LOW'], result['TP2_LOW']
        )
        completed_params.add(param_tuple)
    
    total_combinations = (
        len(CONF_HIGH_THRESHES) * len(CONF_MED_THRESHES) *
        len(SL_HIGH_OPTIONS) * len(TP1_HIGH_OPTIONS) * len(TP2_HIGH_OPTIONS) *
        len(SL_MED_OPTIONS) * len(TP1_MED_OPTIONS) * len(TP2_MED_OPTIONS) *
        len(SL_LOW_OPTIONS) * len(TP1_LOW_OPTIONS) * len(TP2_LOW_OPTIONS)
    )
    
    print(f"Running grid search with {total_combinations} combinations...")
    print(f"Already completed: {len(completed_params)}/{total_combinations}")
    
    combination_count = 0
    
    for high_thresh in CONF_HIGH_THRESHES:
        for med_thresh in CONF_MED_THRESHES:
            for sl_high in SL_HIGH_OPTIONS:
                for tp1_high in TP1_HIGH_OPTIONS:
                    for tp2_high in TP2_HIGH_OPTIONS:
                        for sl_med in SL_MED_OPTIONS:
                            for tp1_med in TP1_MED_OPTIONS:
                                for tp2_med in TP2_MED_OPTIONS:
                                    for sl_low in SL_LOW_OPTIONS:
                                        for tp1_low in TP1_LOW_OPTIONS:
                                            for tp2_low in TP2_LOW_OPTIONS:
                                                
                                                params = {
                                                    'CONF_HIGH_THRESH': high_thresh,
                                                    'CONF_MED_THRESH': med_thresh,
                                                    'SL_HIGH': sl_high,
                                                    'TP1_HIGH': tp1_high,
                                                    'TP2_HIGH': tp2_high,
                                                    'SL_MED': sl_med,
                                                    'TP1_MED': tp1_med,
                                                    'TP2_MED': tp2_med,
                                                    'SL_LOW': sl_low,
                                                    'TP1_LOW': tp1_low,
                                                    'TP2_LOW': tp2_low,
                                                }
                                                
                                                param_tuple = (
                                                    high_thresh, med_thresh, sl_high, tp1_high, tp2_high,
                                                    sl_med, tp1_med, tp2_med, sl_low, tp1_low, tp2_low
                                                )
                                                
                                                # Skip if already completed
                                                if param_tuple in completed_params:
                                                    continue
                                                
                                                combination_count += 1
                                                print(f"Running combination {combination_count + len(completed_params)}/{total_combinations}: {params}")
                                                
                                                metrics = run_backtest(params)
                                                
                                                result = {
                                                    **params,
                                                    **metrics
                                                }
                                                results.append(result)
                                                
                                                # Save intermediate results
                                                df = pd.DataFrame(results)
                                                df.to_csv('grid_search_results.csv', index=False)
                                                
                                                # Small delay to avoid overwhelming system
                                                time.sleep(5)

    # Final save
    df = pd.DataFrame(results)
    df.to_csv('grid_search_results_final.csv', index=False)
    
    # Print top results
    df_sorted = df.sort_values('pnl', ascending=False)
    print("\nTop 5 results by P&L:")
    print(df_sorted.head(5))

if __name__ == '__main__':
    main()