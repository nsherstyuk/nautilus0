"""
Run comparison backtests: with and without minimum hold time feature.
"""

import subprocess
import shutil
from pathlib import Path
import time
import json


def run_backtest(env_file, label):
    """Run a single backtest with specified env file."""
    print("="*80)
    print(f"Running backtest: {label}")
    print(f"Using config: {env_file}")
    print("="*80)
    
    # Copy env file to .env
    shutil.copy(env_file, '.env')
    print(f"Copied {env_file} to .env")
    
    # Run backtest
    print("Starting backtest...")
    start_time = time.time()
    
    result = subprocess.run(
        ['python', 'backtest/run_backtest.py'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore'  # Ignore encoding errors
    )
    
    elapsed = time.time() - start_time
    
    print(f"\nBacktest completed in {elapsed:.1f} seconds")
    print(f"Exit code: {result.returncode}")
    
    if result.returncode != 0:
        print("ERROR during backtest:")
        if result.stderr:
            print(result.stderr)
        return None
    
    # Extract results directory from output
    if result.stdout:
        output_lines = result.stdout.split('\n')
    else:
        output_lines = []
    results_dir = None
    for line in output_lines:
        if 'Results saved to' in line or 'OUTPUT_DIR' in line:
            # Try to extract directory path
            parts = line.split()
            for part in parts:
                if 'logs' in part or 'backtest' in part:
                    results_dir = part.strip(':,')
                    break
    
    if not results_dir:
        # Try to find latest directory
        baseline_dir = Path('logs/backtest_results_baseline')
        regular_dir = Path('logs/backtest_results')
        
        if baseline_dir.exists():
            dirs = sorted(baseline_dir.glob('EUR-USD_*'), key=lambda p: p.stat().st_mtime)
            if dirs:
                results_dir = str(dirs[-1])
        elif regular_dir.exists():
            dirs = sorted(regular_dir.glob('EUR-USD_*'), key=lambda p: p.stat().st_mtime)
            if dirs:
                results_dir = str(dirs[-1])
    
    print(f"\nResults directory: {results_dir}")
    return results_dir


def analyze_results(results_dir):
    """Analyze backtest results."""
    if not results_dir or not Path(results_dir).exists():
        print(f"Results directory not found: {results_dir}")
        return None
    
    stats_file = Path(results_dir) / 'performance_stats.json'
    if not stats_file.exists():
        print(f"Performance stats not found: {stats_file}")
        return None
    
    with open(stats_file, 'r') as f:
        stats = json.load(f)
    
    return stats


def compare_results(baseline_stats, test_stats):
    """Compare two sets of results."""
    print("\n" + "="*80)
    print("COMPARISON RESULTS")
    print("="*80)
    
    metrics = [
        ('Total PnL', 'total_pnl'),
        ('Total Trades', 'total_trades'),
        ('Win Rate', 'win_rate'),
        ('Profit Factor', 'profit_factor'),
        ('Max Drawdown', 'max_drawdown'),
        ('Sharpe Ratio', 'sharpe_ratio'),
        ('Average Win', 'avg_win'),
        ('Average Loss', 'avg_loss'),
    ]
    
    print(f"\n{'Metric':<20} {'WITHOUT':<15} {'WITH':<15} {'Change':<15}")
    print("-"*65)
    
    for metric_name, key in metrics:
        baseline_val = baseline_stats.get(key, 0)
        test_val = test_stats.get(key, 0)
        
        if isinstance(baseline_val, (int, float)) and baseline_val != 0:
            change_pct = ((test_val - baseline_val) / abs(baseline_val)) * 100
            change_str = f"{change_pct:+.1f}%"
        else:
            change_str = "N/A"
        
        # Format values
        if 'PnL' in metric_name or 'Win' in metric_name or 'Loss' in metric_name or 'Drawdown' in metric_name:
            baseline_fmt = f"${baseline_val:,.2f}"
            test_fmt = f"${test_val:,.2f}"
        elif 'Rate' in metric_name:
            baseline_fmt = f"{baseline_val:.2f}%"
            test_fmt = f"{test_val:.2f}%"
        else:
            baseline_fmt = f"{baseline_val:.2f}"
            test_fmt = f"{test_val:.2f}"
        
        print(f"{metric_name:<20} {baseline_fmt:<15} {test_fmt:<15} {change_str:<15}")
    
    # Highlight key findings
    print("\n" + "="*80)
    print("KEY FINDINGS")
    print("="*80)
    
    pnl_diff = test_stats.get('total_pnl', 0) - baseline_stats.get('total_pnl', 0)
    pnl_change = (pnl_diff / abs(baseline_stats.get('total_pnl', 1))) * 100
    
    print(f"\n✓ Total PnL change: ${pnl_diff:+,.2f} ({pnl_change:+.1f}%)")
    
    if pnl_diff > 0:
        print(f"  → Minimum hold time feature IMPROVED performance")
    else:
        print(f"  → Minimum hold time feature DECREASED performance")
    
    wr_diff = test_stats.get('win_rate', 0) - baseline_stats.get('win_rate', 0)
    print(f"✓ Win rate change: {wr_diff:+.2f}%")
    
    trades_diff = test_stats.get('total_trades', 0) - baseline_stats.get('total_trades', 0)
    print(f"✓ Trade count change: {trades_diff:+d} trades")


def main():
    """Run full comparison test."""
    print("\n" + "="*80)
    print("MINIMUM HOLD TIME FEATURE - COMPARISON TEST")
    print("="*80)
    print("\nThis script will run two backtests:")
    print("1. WITHOUT minimum hold time (baseline)")
    print("2. WITH minimum hold time enabled")
    print("\nThen compare the results.\n")
    
    input("Press Enter to continue...")
    
    # Run baseline (without feature)
    print("\n\nSTEP 1: Running baseline backtest...")
    baseline_dir = run_backtest('.env.without_min_hold_time', 'BASELINE (No Min Hold Time)')
    
    if not baseline_dir:
        print("ERROR: Baseline backtest failed!")
        return
    
    print("\n\nWaiting 5 seconds before next backtest...")
    time.sleep(5)
    
    # Run test (with feature)
    print("\n\nSTEP 2: Running test backtest with minimum hold time...")
    test_dir = run_backtest('.env.with_min_hold_time', 'TEST (With Min Hold Time)')
    
    if not test_dir:
        print("ERROR: Test backtest failed!")
        return
    
    # Analyze both
    print("\n\nSTEP 3: Analyzing results...")
    baseline_stats = analyze_results(baseline_dir)
    test_stats = analyze_results(test_dir)
    
    if not baseline_stats or not test_stats:
        print("ERROR: Could not load results for comparison")
        return
    
    # Compare
    compare_results(baseline_stats, test_stats)
    
    print("\n\n" + "="*80)
    print("COMPARISON COMPLETE")
    print("="*80)
    print(f"\nBaseline results: {baseline_dir}")
    print(f"Test results: {test_dir}")
    print("\nYou can now analyze the detailed results in these directories.")


if __name__ == "__main__":
    main()
