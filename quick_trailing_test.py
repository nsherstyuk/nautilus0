"""
Quick trailing stop test - tests a few key configurations with progress updates.
"""

import json
import subprocess
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime

def run_backtest_with_config(activation_pips, distance_pips, test_num, total_tests):
    """Run backtest with specific trailing configuration."""
    
    print(f"\n{'='*70}")
    print(f"TEST {test_num}/{total_tests}: Activation={activation_pips} pips, Distance={distance_pips} pips")
    print(f"{'='*70}")
    print("Running backtest... (this takes ~2 minutes)")
    sys.stdout.flush()
    
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
    start_time = datetime.now()
    result = subprocess.run(
        ['python', 'backtest/run_backtest.py'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore',
        timeout=300
    )
    elapsed = (datetime.now() - start_time).total_seconds()
    
    print(f"Backtest completed in {elapsed:.1f} seconds")
    
    # Check if backtest failed
    if result.returncode != 0:
        print(f"⚠️  Backtest failed with return code {result.returncode}")
        if result.stderr:
            print(f"Error: {result.stderr[-200:]}")
        return None
    
    # Find latest results folder
    results_base = Path('logs/backtest_results')
    folders = sorted([f for f in results_base.glob('EUR-USD_*') if f.is_dir()])
    if not folders:
        print("⚠️  No results folder found")
        return None
    
    latest = folders[-1]
    
    # Read positions.csv
    positions_file = latest / 'positions.csv'
    if not positions_file.exists():
        print("⚠️  No positions.csv found")
        return None
    
    df = pd.read_csv(positions_file)
    
    if df.empty:
        print("⚠️  Empty positions data")
        return None
    
    # Convert realized_pnl to numeric (remove ' USD' suffix if present)
    if df['realized_pnl'].dtype == 'object':
        df['realized_pnl'] = df['realized_pnl'].str.replace(' USD', '', regex=False)
    df['realized_pnl'] = pd.to_numeric(df['realized_pnl'], errors='coerce')
    df = df.dropna(subset=['realized_pnl'])
    
    if df.empty:
        print("⚠️  No valid PnL data")
        return None
    
    total_pnl = float(df['realized_pnl'].sum())
    trade_count = len(df)
    wins = (df['realized_pnl'] > 0).sum()
    win_rate = (wins / trade_count * 100) if trade_count > 0 else 0
    expectancy = total_pnl / trade_count if trade_count > 0 else 0
    
    # Count trailing activations
    trailing_activations = result.stdout.count('[TRAILING] Activated')
    
    result_data = {
        'activation_pips': activation_pips,
        'distance_pips': distance_pips,
        'pnl': total_pnl,
        'trades': trade_count,
        'win_rate': win_rate,
        'expectancy': expectancy,
        'trailing_activations': trailing_activations,
        'results_folder': latest.name
    }
    
    print(f"✅ Result: PnL=${total_pnl:,.2f}, Trades={trade_count}, "
          f"Win Rate={win_rate:.1f}%, Expectancy=${expectancy:.2f}, "
          f"Activations={trailing_activations}")
    
    return result_data

def main():
    """Test key trailing configurations."""
    
    print("=" * 70)
    print("QUICK TRAILING STOP TEST")
    print("=" * 70)
    print("\nTesting 6 key configurations...")
    print("Baseline (disabled) PnL: $11,308")
    print("Previous test (8/5 pips) PnL: $4,037 ❌")
    
    # Test configurations from conservative to aggressive
    configs = [
        (50, 30),   # Very conservative
        (30, 20),   # Conservative
        (20, 15),   # Moderate
        (15, 10),   # Moderate-aggressive
        (10, 6),    # Aggressive
        (5, 3),     # Very aggressive
    ]
    
    total_tests = len(configs)
    results = []
    
    for i, (activation, distance) in enumerate(configs, 1):
        try:
            result = run_backtest_with_config(activation, distance, i, total_tests)
            if result:
                results.append(result)
        except Exception as e:
            print(f"❌ Error: {e}")
            continue
    
    # Save results
    output_file = Path('trailing_quick_test_results.json')
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n{'='*70}")
    print("TEST COMPLETE")
    print(f"{'='*70}")
    print(f"\nResults saved to: {output_file}")
    
    if not results:
        print("\n❌ No successful tests")
        return
    
    # Sort by PnL
    sorted_results = sorted(results, key=lambda x: x['pnl'], reverse=True)
    
    print(f"\n{'='*70}")
    print("RESULTS RANKED BY PNL")
    print(f"{'='*70}")
    print(f"{'Rank':>4} {'Act':>4} {'Dist':>5} {'PnL':>12} {'Trades':>7} {'Win%':>6} {'Expect':>8} {'Trails':>7}")
    print(f"{'-'*70}")
    
    baseline_pnl = 11307.99
    
    for i, r in enumerate(sorted_results, 1):
        diff = r['pnl'] - baseline_pnl
        marker = "🟢" if diff > 0 else "🔴"
        print(f"{i:>4} {r['activation_pips']:>4} {r['distance_pips']:>5} "
              f"${r['pnl']:>10,.2f} {r['trades']:>7} "
              f"{r['win_rate']:>5.1f}% ${r['expectancy']:>7.2f} "
              f"{r['trailing_activations']:>7} {marker}")
    
    # Best vs baseline
    best = sorted_results[0]
    diff = best['pnl'] - baseline_pnl
    pct = (diff / baseline_pnl * 100)
    
    print(f"\n{'='*70}")
    print("BEST CONFIG vs BASELINE")
    print(f"{'='*70}")
    print(f"Best: Activation={best['activation_pips']}, Distance={best['distance_pips']}")
    print(f"PnL: ${best['pnl']:,.2f} vs ${baseline_pnl:,.2f} baseline")
    print(f"Difference: ${diff:,.2f} ({pct:+.1f}%)")
    
    if diff > 0:
        print(f"\n✅ TRAILING IMPROVED PnL!")
    elif diff > -1000:
        print(f"\n⚠️  TRAILING SLIGHTLY HURT PnL")
    else:
        print(f"\n❌ TRAILING SIGNIFICANTLY HURT PnL")

if __name__ == '__main__':
    main()
