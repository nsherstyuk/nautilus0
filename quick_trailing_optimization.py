"""
Quick trailing stop optimization - tests a few key combinations.
"""
import subprocess
import sys
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import time

def update_env_file(env_file: Path, activation_pips: int, distance_pips: int) -> None:
    """Update .env file with new trailing stop settings."""
    if not env_file.exists():
        print(f"Warning: {env_file} not found")
        return
    
    lines = env_file.read_text(encoding="utf-8").splitlines()
    updated_lines = []
    activation_found = False
    distance_found = False
    
    for line in lines:
        if line.startswith("BACKTEST_TRAILING_STOP_ACTIVATION_PIPS="):
            updated_lines.append(f"BACKTEST_TRAILING_STOP_ACTIVATION_PIPS={activation_pips}")
            activation_found = True
        elif line.startswith("BACKTEST_TRAILING_STOP_DISTANCE_PIPS="):
            updated_lines.append(f"BACKTEST_TRAILING_STOP_DISTANCE_PIPS={distance_pips}")
            distance_found = True
        else:
            updated_lines.append(line)
    
    if not activation_found:
        updated_lines.append(f"BACKTEST_TRAILING_STOP_ACTIVATION_PIPS={activation_pips}")
    if not distance_found:
        updated_lines.append(f"BACKTEST_TRAILING_STOP_DISTANCE_PIPS={distance_pips}")
    
    env_file.write_text("\n".join(updated_lines), encoding="utf-8")

def run_backtest(activation_pips: int, distance_pips: int, env_file: Path) -> Dict:
    """Run a single backtest and return results."""
    print(f"\n{'='*80}")
    print(f"Testing: Activation={activation_pips} pips, Distance={distance_pips} pips")
    print(f"{'='*80}")
    
    update_env_file(env_file, activation_pips, distance_pips)
    
    try:
        result = subprocess.run(
            [sys.executable, "backtest/run_backtest.py"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',  # Replace problematic characters instead of failing
            timeout=600
        )
        
        if result.returncode != 0:
            return {
                'activation_pips': activation_pips,
                'distance_pips': distance_pips,
                'success': False,
                'error': result.stderr[:200]
            }
        
        # Find latest results folder
        results_dir = Path("logs/backtest_results")
        folders = sorted(results_dir.glob("EUR-USD_*"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not folders:
            return {'activation_pips': activation_pips, 'distance_pips': distance_pips, 'success': False, 'error': 'No results'}
        
        latest_folder = folders[0]
        positions_file = latest_folder / "positions.csv"
        
        if not positions_file.exists():
            return {'activation_pips': activation_pips, 'distance_pips': distance_pips, 'success': False, 'error': 'No positions.csv'}
        
        # Parse results
        pos_df = pd.read_csv(positions_file)
        if pos_df['realized_pnl'].dtype == 'object':
            pos_df['pnl_value'] = pos_df['realized_pnl'].str.replace(' USD', '', regex=False).str.replace('USD', '', regex=False).str.strip().astype(float)
        else:
            pos_df['pnl_value'] = pos_df['realized_pnl'].astype(float)
        
        total_pnl = pos_df['pnl_value'].sum()
        avg_pnl = pos_df['pnl_value'].mean()
        win_rate = (pos_df['pnl_value'] > 0).mean() * 100
        total_trades = len(pos_df)
        
        pos_df['ts_opened'] = pd.to_datetime(pos_df['ts_opened'], utc=True)
        pos_df['hour'] = pos_df['ts_opened'].dt.hour
        pos_df['weekday'] = pos_df['ts_opened'].dt.day_name()
        # Convert to period without timezone to avoid warning
        pos_df['month'] = pos_df['ts_opened'].dt.tz_localize(None).dt.to_period('M').astype(str)
        
        return {
            'activation_pips': activation_pips,
            'distance_pips': distance_pips,
            'success': True,
            'results_folder': str(latest_folder),
            'total_pnl': float(total_pnl),
            'avg_pnl': float(avg_pnl),
            'win_rate': float(win_rate),
            'total_trades': int(total_trades),
            'by_hour': {int(k): float(v) for k, v in pos_df.groupby('hour')['pnl_value'].sum().items()},
            'by_weekday': {str(k): float(v) for k, v in pos_df.groupby('weekday')['pnl_value'].sum().items()},
            'by_month': {str(k): float(v) for k, v in pos_df.groupby('month')['pnl_value'].sum().items()},
        }
    except Exception as e:
        return {'activation_pips': activation_pips, 'distance_pips': distance_pips, 'success': False, 'error': str(e)[:200]}

def main():
    env_file = Path(".env")
    if not env_file.exists():
        print(f"ERROR: {env_file} not found")
        return
    
    # Test key combinations
    combinations = [
        (15, 10),   # Early activation, tight
        (20, 15),   # Current default
        (25, 20),   # Standard, medium
        (30, 25),   # Late activation, wider
        (20, 10),   # Standard activation, tight distance
    ]
    
    print(f"Testing {len(combinations)} trailing stop combinations...")
    print("This may take several minutes...")
    
    results = []
    for i, (activation, distance) in enumerate(combinations, 1):
        print(f"\n[{i}/{len(combinations)}] Running backtest...")
        result = run_backtest(activation, distance, env_file)
        results.append(result)
        
        if result.get('success'):
            print(f"✓ Success: PnL=${result['total_pnl']:.2f}, Win Rate={result['win_rate']:.1f}%, Trades={result['total_trades']}")
        else:
            print(f"✗ Failed: {result.get('error', 'Unknown')}")
        
        time.sleep(2)  # Brief pause between tests
    
    # Generate report
    successful = [r for r in results if r.get('success', False)]
    if not successful:
        print("\nERROR: No successful backtests")
        return
    
    print(f"\n{'='*80}")
    print("TRAILING STOP OPTIMIZATION RESULTS")
    print(f"{'='*80}")
    print(f"\n{'Activation':<12} {'Distance':<12} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12} {'Trades':<10}")
    print("-" * 80)
    
    successful_sorted = sorted(successful, key=lambda x: x['total_pnl'], reverse=True)
    for r in successful_sorted:
        print(f"{r['activation_pips']:<12} {r['distance_pips']:<12} ${r['total_pnl']:>13.2f}  ${r['avg_pnl']:>13.2f}  {r['win_rate']:>10.1f}%  {r['total_trades']:<10}")
    
    best = successful_sorted[0]
    print(f"\n{'='*80}")
    print("BEST COMBINATION")
    print(f"{'='*80}")
    print(f"Activation: {best['activation_pips']} pips")
    print(f"Distance: {best['distance_pips']} pips")
    print(f"Total PnL: ${best['total_pnl']:.2f}")
    print(f"Avg PnL: ${best['avg_pnl']:.2f}")
    print(f"Win Rate: {best['win_rate']:.1f}%")
    print(f"Trades: {best['total_trades']}")
    print(f"Results Folder: {best['results_folder']}")
    
    # Save JSON
    output_file = Path("logs") / f"trailing_stop_quick_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_file}")

if __name__ == "__main__":
    main()

