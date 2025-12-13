"""
Grid search for optimal trailing stop settings.
Tests various activation and distance combinations to find if any improve PnL.
"""

import json
import subprocess
import shutil
from pathlib import Path
import re
from datetime import datetime

def run_backtest_with_config(activation_pips, distance_pips):
    """Run backtest with specific trailing configuration."""
    
    # Read current .env
    env_path = Path('.env')
    with open(env_path, 'r') as f:
        lines = f.readlines()
    
    # Modify trailing parameters
    new_lines = []
    for line in lines:
        if line.startswith('BACKTEST_TRAILING_STOP_ACTIVATION_PIPS='):
            new_lines.append(f'BACKTEST_TRAILING_STOP_ACTIVATION_PIPS={activation_pips}\n')
        elif line.startswith('BACKTEST_TRAILING_STOP_DISTANCE_PIPS='):
            new_lines.append(f'BACKTEST_TRAILING_STOP_DISTANCE_PIPS={distance_pips}\n')
        else:
            new_lines.append(line)
    
    # Write modified .env
    with open(env_path, 'w') as f:
        f.writelines(new_lines)
    
    # Run backtest
    print(f"\n{'='*70}")
    print(f"Testing: Activation={activation_pips} pips, Distance={distance_pips} pips")
    print(f"{'='*70}")
    
    result = subprocess.run(
        ['python', 'backtest/run_backtest.py'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore',  # Ignore encoding errors
        timeout=300  # 5 minute timeout
    )
    
    # Check if backtest failed
    if result.returncode != 0:
        print(f"⚠️  Backtest failed with return code {result.returncode}")
        print(f"Last 500 chars of stderr: {result.stderr[-500:] if result.stderr else 'N/A'}")
        return None
    
    # Find latest results folder
    results_base = Path('logs/backtest_results')
    folders = sorted([f for f in results_base.glob('EUR-USD_*') if f.is_dir()])
    if not folders:
        return None
    
    latest = folders[-1]
    
    # Read positions.csv to calculate PnL
    positions_file = latest / 'positions.csv'
    if not positions_file.exists():
        return None
    
    import pandas as pd
    df = pd.read_csv(positions_file)
    
    if df.empty:
        return None
    
    # Convert realized_pnl to numeric (handle string values)
    df['realized_pnl'] = pd.to_numeric(df['realized_pnl'], errors='coerce')
    df = df.dropna(subset=['realized_pnl'])
    
    if df.empty:
        return None
    
    total_pnl = float(df['realized_pnl'].sum())
    trade_count = len(df)
    
    # Calculate win rate
    wins = (df['realized_pnl'] > 0).sum()
    win_rate = (wins / trade_count * 100) if trade_count > 0 else 0
    
    # Calculate expectancy
    expectancy = total_pnl / trade_count if trade_count > 0 else 0
    
    # Count trailing activations from log
    trailing_activations = result.stdout.count('[TRAILING] Activated')
    
    return {
        'activation_pips': activation_pips,
        'distance_pips': distance_pips,
        'pnl': total_pnl,
        'trades': trade_count,
        'win_rate': win_rate,
        'expectancy': expectancy,
        'trailing_activations': trailing_activations,
        'results_folder': latest.name
    }

def main():
    """Run grid search over trailing stop parameters."""
    
    print("=" * 70)
    print("TRAILING STOP OPTIMIZATION")
    print("=" * 70)
    print("\nTesting various activation/distance combinations...")
    print("Baseline (disabled): activation=200 pips (effectively disabled)")
    
    # Define grid
    # Strategy: test from conservative (high activation) to aggressive (low activation)
    # Distance should always be < activation
    grid = [
        # Very conservative - only trail on large moves
        (50, 30),   # Trail after +50 pips, keep 30 pips away
        (40, 25),   # Trail after +40 pips, keep 25 pips away
        (30, 20),   # Trail after +30 pips, keep 20 pips away
        
        # Moderate - current failed setting was here
        (20, 15),   # Trail after +20 pips, keep 15 pips away
        (15, 10),   # Trail after +15 pips, keep 10 pips away
        (12, 8),    # Trail after +12 pips, keep 8 pips away
        
        # Aggressive - tested already (failed)
        (8, 5),     # Trail after +8 pips, keep 5 pips away
        
        # Very aggressive - trail quickly but loosely
        (6, 4),     # Trail after +6 pips, keep 4 pips away
        (5, 3),     # Trail after +5 pips, keep 3 pips away
        
        # Ultra aggressive - might catch small winners
        (4, 2),     # Trail after +4 pips, keep 2 pips away
        (3, 2),     # Trail after +3 pips, keep 2 pips away
    ]
    
    results = []
    
    for activation, distance in grid:
        try:
            result = run_backtest_with_config(activation, distance)
            if result:
                results.append(result)
                print(f"\nResult: PnL=${result['pnl']:,.2f}, "
                      f"Trades={result['trades']}, "
                      f"Win Rate={result['win_rate']:.1f}%, "
                      f"Expectancy=${result['expectancy']:.2f}, "
                      f"Activations={result['trailing_activations']}")
        except Exception as e:
            print(f"Error testing activation={activation}, distance={distance}: {e}")
            continue
    
    # Save results
    output_file = Path('trailing_optimization_results.json')
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n{'='*70}")
    print("OPTIMIZATION COMPLETE")
    print(f"{'='*70}")
    print(f"\nResults saved to: {output_file}")
    
    # Sort by PnL
    sorted_results = sorted(results, key=lambda x: x['pnl'], reverse=True)
    
    print(f"\n{'='*70}")
    print("TOP 5 CONFIGURATIONS BY PNL")
    print(f"{'='*70}")
    print(f"{'Activation':>11} {'Distance':>9} {'PnL':>12} {'Trades':>7} {'Win%':>6} {'Expect':>8} {'Trails':>7}")
    print(f"{'-'*70}")
    
    for i, r in enumerate(sorted_results[:5], 1):
        print(f"{r['activation_pips']:>11} {r['distance_pips']:>9} "
              f"${r['pnl']:>10,.2f} {r['trades']:>7} "
              f"{r['win_rate']:>5.1f}% ${r['expectancy']:>7.2f} "
              f"{r['trailing_activations']:>7}")
    
    # Compare to baseline (disabled)
    print(f"\n{'='*70}")
    print("BASELINE COMPARISON (Trailing Disabled: $11,308)")
    print(f"{'='*70}")
    
    best = sorted_results[0] if sorted_results else None
    if best:
        baseline_pnl = 11307.99  # From previous disabled run
        diff = best['pnl'] - baseline_pnl
        pct = (diff / baseline_pnl * 100) if baseline_pnl != 0 else 0
        
        print(f"\nBest trailing config: Activation={best['activation_pips']}, Distance={best['distance_pips']}")
        print(f"PnL: ${best['pnl']:,.2f} vs ${baseline_pnl:,.2f} baseline")
        print(f"Difference: ${diff:,.2f} ({pct:+.1f}%)")
        
        if diff > 0:
            print(f"\n✅ TRAILING IMPROVED PNL by ${diff:,.2f}!")
        else:
            print(f"\n❌ TRAILING HURT PNL by ${-diff:,.2f}")
    
    return results

if __name__ == '__main__':
    main()
