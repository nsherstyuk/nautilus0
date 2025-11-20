#!/usr/bin/env python3
"""
Grid Optimization Script for NautilusTrader Strategy Parameters

Reads a JSON grid file and runs backtests for all parameter combinations.
Based on optimize_trailing_stops.py pattern but generalized for any parameters.
"""
import subprocess
import sys
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import time
import itertools
import shutil
import os

def load_grid_config(grid_file: str) -> Dict[str, Any]:
    """Load grid configuration from JSON file"""
    with open(grid_file, 'r') as f:
        return json.load(f)

def generate_parameter_combinations(grid_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate all parameter combinations from grid config"""
    # Extract parameters (skip description and comment)
    param_keys = [k for k in grid_config.keys() if not k.startswith(('description', 'comment'))]
    param_values = [grid_config[k] for k in param_keys]
    
    # Generate all combinations
    combinations = []
    for combo in itertools.product(*param_values):
        param_dict = dict(zip(param_keys, combo))
        combinations.append(param_dict)
    
    return combinations

def backup_env_file():
    """Backup current .env file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f".env.backup_{timestamp}"
    shutil.copy(".env", backup_path)
    return backup_path

def update_env_file(parameters: Dict[str, Any]):
    """Update .env file with new parameters"""
    # Read current .env
    with open(".env", 'r') as f:
        lines = f.readlines()
    
    # Update parameters
    updated_lines = []
    for line in lines:
        if '=' in line and not line.strip().startswith('#'):
            key = line.split('=')[0].strip()
            if key in parameters:
                # Update this parameter
                updated_lines.append(f"{key}={parameters[key]}\n")
                continue
        updated_lines.append(line)
    
    # Write updated .env
    with open(".env", 'w') as f:
        f.writelines(updated_lines)

def run_single_backtest(combo_id: int, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Run a single backtest with given parameters"""
    print(f"\n🔄 Running combination {combo_id}: {parameters}")
    
    try:
        # Update .env file
        update_env_file(parameters)
        
        # Run backtest
        result = subprocess.run(
            [sys.executable, "backtest/run_backtest.py"],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout per backtest
        )
        
        if result.returncode != 0:
            return {
                'combo_id': combo_id,
                'parameters': parameters,
                'success': False,
                'error': f"Backtest failed: {result.stderr[:200]}..."
            }
        
        # Find latest results
        results_dir = Path("logs/backtest_results")
        if not results_dir.exists():
            return {
                'combo_id': combo_id,
                'parameters': parameters,
                'success': False,
                'error': "Results directory not found"
            }
        
        # Get most recent folder
        folders = sorted(results_dir.glob("EUR-USD_*"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not folders:
            return {
                'combo_id': combo_id,
                'parameters': parameters,
                'success': False,
                'error': "No results folder found"
            }
        
        latest_folder = folders[0]
        
        # Read performance stats
        stats_file = latest_folder / "performance_stats.json"
        if stats_file.exists():
            with open(stats_file, 'r') as f:
                stats = json.load(f)
        else:
            stats = {}
        
        # Read positions for additional metrics
        positions_file = latest_folder / "positions.csv"
        trade_count = 0
        if positions_file.exists():
            positions_df = pd.read_csv(positions_file)
            trade_count = len(positions_df)
        
        return {
            'combo_id': combo_id,
            'parameters': parameters,
            'success': True,
            'pnl_total': stats.get('pnls', {}).get('PnL (total)', 0),
            'pnl_percent': stats.get('pnls', {}).get('PnL% (total)', 0),
            'win_rate': stats.get('pnls', {}).get('Win Rate', 0),
            'expectancy': stats.get('pnls', {}).get('Expectancy', 0),
            'max_winner': stats.get('pnls', {}).get('Max Winner', 0),
            'max_loser': stats.get('pnls', {}).get('Max Loser', 0),
            'trade_count': trade_count,
            'results_folder': str(latest_folder)
        }
        
    except subprocess.TimeoutExpired:
        return {
            'combo_id': combo_id,
            'parameters': parameters,
            'success': False,
            'error': "Timeout after 5 minutes"
        }
    except Exception as e:
        return {
            'combo_id': combo_id,
            'parameters': parameters,
            'success': False,
            'error': str(e)
        }

def run_grid_optimization(grid_file: str):
    """Main optimization function"""
    print("🚀 GRID OPTIMIZATION STARTING")
    print("=" * 60)
    
    # Load configuration
    grid_config = load_grid_config(grid_file)
    combinations = generate_parameter_combinations(grid_config)
    
    print(f"📊 Grid: {grid_file}")
    print(f"📈 Total combinations: {len(combinations)}")
    print(f"⏱️  Estimated time: {len(combinations) * 0.75:.1f} minutes")
    
    if 'description' in grid_config:
        print(f"📝 Description: {grid_config['description']}")
    
    # Backup current .env
    backup_path = backup_env_file()
    print(f"💾 Backed up .env to: {backup_path}")
    
    # Create results directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path(f"optimization_results_{timestamp}")
    results_dir.mkdir(exist_ok=True)
    
    # Run optimizations
    results = []
    start_time = time.time()
    
    for i, combo in enumerate(combinations, 1):
        print(f"\n📊 Progress: {i}/{len(combinations)} ({i/len(combinations)*100:.1f}%)")
        
        result = run_single_backtest(i, combo)
        results.append(result)
        
        # Save intermediate results every 10 combinations
        if i % 10 == 0 or i == len(combinations):
            results_df = pd.DataFrame(results)
            results_df.to_csv(results_dir / "optimization_results.csv", index=False)
            
        # Show progress
        if result['success']:
            print(f"✅ PnL: ${result['pnl_total']:.2f}, Win Rate: {result['win_rate']:.3f}")
        else:
            print(f"❌ FAILED: {result['error']}")
        
        # Estimated time remaining
        elapsed = time.time() - start_time
        avg_time = elapsed / i
        remaining = (len(combinations) - i) * avg_time
        print(f"⏱️  ETA: {remaining/60:.1f} minutes")
    
    # Restore original .env
    shutil.copy(backup_path, ".env")
    print(f"\n💾 Restored original .env from backup")
    
    # Analyze results
    print("\n" + "=" * 60)
    print("📊 OPTIMIZATION RESULTS SUMMARY")
    print("=" * 60)
    
    successful_results = [r for r in results if r['success']]
    failed_results = [r for r in results if not r['success']]
    
    print(f"✅ Successful: {len(successful_results)}")
    print(f"❌ Failed: {len(failed_results)}")
    
    if successful_results:
        # Sort by PnL
        successful_results.sort(key=lambda x: x['pnl_total'], reverse=True)
        
        print(f"\n🏆 TOP 5 PERFORMERS:")
        for i, result in enumerate(successful_results[:5], 1):
            params_str = ", ".join([f"{k}={v}" for k, v in result['parameters'].items()])
            print(f"  {i}. PnL: ${result['pnl_total']:.2f} | Win Rate: {result['win_rate']:.3f} | {params_str}")
        
        # Save detailed results
        results_df = pd.DataFrame(successful_results)
        results_df.to_csv(results_dir / "optimization_results_final.csv", index=False)
        
        # Save best parameters
        best_params = successful_results[0]['parameters']
        with open(results_dir / "best_parameters.json", 'w') as f:
            json.dump(best_params, f, indent=2)
        
        print(f"\n📁 Results saved in: {results_dir}")
        print(f"🎯 Best parameters: {results_dir}/best_parameters.json")
        
    else:
        print("❌ No successful backtests!")
    
    total_time = time.time() - start_time
    print(f"\n⏱️  Total time: {total_time/60:.1f} minutes")
    print("🏁 OPTIMIZATION COMPLETE!")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python optimize_grid.py <grid_file.json>")
        sys.exit(1)
    
    grid_file = sys.argv[1]
    if not Path(grid_file).exists():
        print(f"Error: Grid file '{grid_file}' not found")
        sys.exit(1)
    
    run_grid_optimization(grid_file)