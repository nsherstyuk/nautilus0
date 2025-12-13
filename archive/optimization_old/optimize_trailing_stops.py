"""
Script to run multiple backtests with different trailing stop settings and compare results.

This script:
1. Tests different trailing stop activation/distance combinations
2. Runs backtests for each combination
3. Compares results by hour, weekday, and month
4. Generates a comparison report with recommendations
"""
import subprocess
import sys
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Dict
import time

def get_trailing_stop_combinations() -> List[Tuple[int, int]]:
    """
    Get list of trailing stop combinations to test.
    Returns list of (activation_pips, distance_pips) tuples.
    """
    combinations = []
    
    # Early activation, tight distance (scalping style)
    combinations.extend([
        (10, 5), (10, 10), (15, 5), (15, 10), (15, 15)
    ])
    
    # Standard activation, various distances
    combinations.extend([
        (20, 10), (20, 15), (20, 20), (20, 25),
        (25, 15), (25, 20), (25, 25)
    ])
    
    # Late activation, wider distance (let winners run)
    combinations.extend([
        (30, 20), (30, 25), (30, 30),
        (40, 25), (40, 30)
    ])
    
    # Current default
    combinations.append((20, 15))  # Make sure we test current settings
    
    # Remove duplicates and sort
    combinations = sorted(list(set(combinations)), key=lambda x: (x[0], x[1]))
    
    return combinations

def update_env_file(env_file: Path, activation_pips: int, distance_pips: int) -> None:
    """
    Update .env file with new trailing stop settings.
    """
    if not env_file.exists():
        print(f"Warning: {env_file} not found, using defaults")
        return
    
    # Read current env file
    lines = env_file.read_text(encoding="utf-8").splitlines()
    
    # Update trailing stop settings
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
    
    # Add if not found
    if not activation_found:
        updated_lines.append(f"BACKTEST_TRAILING_STOP_ACTIVATION_PIPS={activation_pips}")
    if not distance_found:
        updated_lines.append(f"BACKTEST_TRAILING_STOP_DISTANCE_PIPS={distance_pips}")
    
    # Write back
    env_file.write_text("\n".join(updated_lines), encoding="utf-8")

def run_backtest(activation_pips: int, distance_pips: int, base_env: Path) -> Dict:
    """
    Run a single backtest with given trailing stop settings.
    Returns results dictionary.
    """
    print(f"\n{'='*80}")
    print(f"Running backtest: Activation={activation_pips} pips, Distance={distance_pips} pips")
    print(f"{'='*80}")
    
    # Update env file
    update_env_file(base_env, activation_pips, distance_pips)
    
    # Run backtest
    try:
        result = subprocess.run(
            [sys.executable, "backtest/run_backtest.py"],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        
        if result.returncode != 0:
            print(f"ERROR: Backtest failed with return code {result.returncode}")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            return {
                'activation_pips': activation_pips,
                'distance_pips': distance_pips,
                'success': False,
                'error': result.stderr
            }
        
        # Find the latest backtest results folder
        results_dir = Path("logs/backtest_results")
        if not results_dir.exists():
            return {
                'activation_pips': activation_pips,
                'distance_pips': distance_pips,
                'success': False,
                'error': "Results directory not found"
            }
        
        # Get most recently modified folder
        folders = sorted(results_dir.glob("EUR-USD_*"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not folders:
            return {
                'activation_pips': activation_pips,
                'distance_pips': distance_pips,
                'success': False,
                'error': "No results folder found"
            }
        
        latest_folder = folders[0]
        
        # Read results
        positions_file = latest_folder / "positions.csv"
        if not positions_file.exists():
            return {
                'activation_pips': activation_pips,
                'distance_pips': distance_pips,
                'success': False,
                'error': "positions.csv not found"
            }
        
        # Parse results
        pos_df = pd.read_csv(positions_file)
        
        # Extract PnL
        if pos_df['realized_pnl'].dtype == 'object':
            pos_df['pnl_value'] = pos_df['realized_pnl'].str.replace(' USD', '', regex=False).str.replace('USD', '', regex=False).str.strip().astype(float)
        else:
            pos_df['pnl_value'] = pos_df['realized_pnl'].astype(float)
        
        # Calculate statistics
        total_pnl = pos_df['pnl_value'].sum()
        avg_pnl = pos_df['pnl_value'].mean()
        win_rate = (pos_df['pnl_value'] > 0).mean() * 100
        total_trades = len(pos_df)
        wins = (pos_df['pnl_value'] > 0).sum()
        losses = (pos_df['pnl_value'] < 0).sum()
        
        # Calculate by hour/weekday/month
        pos_df['ts_opened'] = pd.to_datetime(pos_df['ts_opened'])
        pos_df['hour'] = pos_df['ts_opened'].dt.hour
        pos_df['weekday'] = pos_df['ts_opened'].dt.day_name()
        pos_df['month'] = pos_df['ts_opened'].dt.to_period('M').astype(str)
        
        return {
            'activation_pips': activation_pips,
            'distance_pips': distance_pips,
            'success': True,
            'results_folder': str(latest_folder),
            'total_pnl': float(total_pnl),
            'avg_pnl': float(avg_pnl),
            'win_rate': float(win_rate),
            'total_trades': int(total_trades),
            'wins': int(wins),
            'losses': int(losses),
            'by_hour': pos_df.groupby('hour')['pnl_value'].sum().to_dict(),
            'by_weekday': pos_df.groupby('weekday')['pnl_value'].sum().to_dict(),
            'by_month': pos_df.groupby('month')['pnl_value'].sum().to_dict(),
        }
        
    except subprocess.TimeoutExpired:
        return {
            'activation_pips': activation_pips,
            'distance_pips': distance_pips,
            'success': False,
            'error': "Backtest timed out"
        }
    except Exception as e:
        return {
            'activation_pips': activation_pips,
            'distance_pips': distance_pips,
            'success': False,
            'error': str(e)
        }

def generate_comparison_report(results: List[Dict], output_file: Path):
    """
    Generate a comparison report from all backtest results.
    """
    successful_results = [r for r in results if r.get('success', False)]
    
    if not successful_results:
        print("ERROR: No successful backtests to compare")
        return
    
    report_lines = []
    report_lines.append("=" * 100)
    report_lines.append("TRAILING STOP OPTIMIZATION COMPARISON REPORT")
    report_lines.append("=" * 100)
    report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Total Combinations Tested: {len(results)}")
    report_lines.append(f"Successful Backtests: {len(successful_results)}")
    report_lines.append("")
    
    # Overall comparison
    report_lines.append("=" * 100)
    report_lines.append("OVERALL PERFORMANCE COMPARISON")
    report_lines.append("=" * 100)
    report_lines.append(f"{'Activation':<12} {'Distance':<12} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12} {'Trades':<10}")
    report_lines.append("-" * 100)
    
    # Sort by total PnL
    successful_results_sorted = sorted(successful_results, key=lambda x: x['total_pnl'], reverse=True)
    
    for result in successful_results_sorted:
        report_lines.append(
            f"{result['activation_pips']:<12} {result['distance_pips']:<12} "
            f"${result['total_pnl']:>13.2f}  ${result['avg_pnl']:>13.2f}  "
            f"{result['win_rate']:>10.1f}%  {result['total_trades']:<10}"
        )
    
    # Best performing combinations
    report_lines.append("\n" + "=" * 100)
    report_lines.append("TOP 5 PERFORMING COMBINATIONS")
    report_lines.append("=" * 100)
    for i, result in enumerate(successful_results_sorted[:5], 1):
        report_lines.append(f"\n{i}. Activation: {result['activation_pips']} pips, Distance: {result['distance_pips']} pips")
        report_lines.append(f"   Total PnL: ${result['total_pnl']:.2f}")
        report_lines.append(f"   Avg PnL: ${result['avg_pnl']:.2f}")
        report_lines.append(f"   Win Rate: {result['win_rate']:.1f}%")
        report_lines.append(f"   Trades: {result['total_trades']}")
        report_lines.append(f"   Results Folder: {result['results_folder']}")
    
    # Analysis by hour (best combination for each hour)
    report_lines.append("\n" + "=" * 100)
    report_lines.append("BEST COMBINATION BY HOUR")
    report_lines.append("=" * 100)
    
    # Collect all hours
    all_hours = set()
    for result in successful_results:
        all_hours.update(result.get('by_hour', {}).keys())
    
    for hour in sorted(all_hours):
        hour_results = []
        for result in successful_results:
            hour_pnl = result.get('by_hour', {}).get(hour, 0)
            if hour_pnl != 0:  # Only include hours with trades
                hour_results.append({
                    'activation': result['activation_pips'],
                    'distance': result['distance_pips'],
                    'pnl': hour_pnl
                })
        
        if hour_results:
            best = max(hour_results, key=lambda x: x['pnl'])
            report_lines.append(
                f"Hour {hour:02d}: Activation={best['activation']} pips, "
                f"Distance={best['distance']} pips, PnL=${best['pnl']:.2f}"
            )
    
    # Analysis by weekday
    report_lines.append("\n" + "=" * 100)
    report_lines.append("BEST COMBINATION BY WEEKDAY")
    report_lines.append("=" * 100)
    
    weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    for weekday in weekday_order:
        weekday_results = []
        for result in successful_results:
            weekday_pnl = result.get('by_weekday', {}).get(weekday, 0)
            if weekday_pnl != 0:
                weekday_results.append({
                    'activation': result['activation_pips'],
                    'distance': result['distance_pips'],
                    'pnl': weekday_pnl
                })
        
        if weekday_results:
            best = max(weekday_results, key=lambda x: x['pnl'])
            report_lines.append(
                f"{weekday}: Activation={best['activation']} pips, "
                f"Distance={best['distance']} pips, PnL=${best['pnl']:.2f}"
            )
    
    # Analysis by month
    report_lines.append("\n" + "=" * 100)
    report_lines.append("BEST COMBINATION BY MONTH")
    report_lines.append("=" * 100)
    
    all_months = set()
    for result in successful_results:
        all_months.update(result.get('by_month', {}).keys())
    
    for month in sorted(all_months):
        month_results = []
        for result in successful_results:
            month_pnl = result.get('by_month', {}).get(month, 0)
            if month_pnl != 0:
                month_results.append({
                    'activation': result['activation_pips'],
                    'distance': result['distance_pips'],
                    'pnl': month_pnl
                })
        
        if month_results:
            best = max(month_results, key=lambda x: x['pnl'])
            report_lines.append(
                f"{month}: Activation={best['activation']} pips, "
                f"Distance={best['distance']} pips, PnL=${best['pnl']:.2f}"
            )
    
    # Recommendations
    report_lines.append("\n" + "=" * 100)
    report_lines.append("RECOMMENDATIONS")
    report_lines.append("=" * 100)
    
    best_overall = successful_results_sorted[0]
    report_lines.append(f"\nBest Overall Combination:")
    report_lines.append(f"  Activation: {best_overall['activation_pips']} pips")
    report_lines.append(f"  Distance: {best_overall['distance_pips']} pips")
    report_lines.append(f"  Total PnL: ${best_overall['total_pnl']:.2f}")
    report_lines.append(f"  Win Rate: {best_overall['win_rate']:.1f}%")
    
    report_lines.append(f"\n💡 Next Steps:")
    report_lines.append(f"  1. Review individual backtest results in:")
    for result in successful_results_sorted[:3]:
        report_lines.append(f"     - {result['results_folder']}")
    report_lines.append(f"  2. Consider implementing dynamic trailing stops:")
    report_lines.append(f"     - Different settings for different hours/weekdays/months")
    report_lines.append(f"  3. Validate on out-of-sample data")
    report_lines.append(f"  4. Monitor performance in live trading")
    
    # Write report
    output_file.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n{'='*80}")
    print(f"Comparison report saved to: {output_file}")
    print(f"{'='*80}")
    
    # Also save JSON
    json_file = output_file.with_suffix('.json')
    with open(json_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"JSON data saved to: {json_file}")

def main():
    """
    Main function to run trailing stop optimization.
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="Optimize trailing stop settings")
    parser.add_argument(
        "--env",
        type=str,
        default=".env",
        help="Path to .env file (default: .env)"
    )
    parser.add_argument(
        "--combinations",
        type=int,
        default=None,
        help="Number of combinations to test (default: all)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: logs/trailing_stop_optimization_<timestamp>.txt)"
    )
    args = parser.parse_args()
    
    # Check env file exists
    env_file = Path(args.env)
    if not env_file.exists():
        print(f"ERROR: Environment file not found: {env_file}")
        print("Please specify a valid .env file path")
        sys.exit(1)
    
    # Get combinations to test
    all_combinations = get_trailing_stop_combinations()
    if args.combinations:
        combinations = all_combinations[:args.combinations]
        print(f"Testing {len(combinations)} combinations (limited from {len(all_combinations)})")
    else:
        combinations = all_combinations
        print(f"Testing {len(combinations)} trailing stop combinations")
    
    # Output file
    if args.output:
        output_file = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("logs")
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / f"trailing_stop_optimization_{timestamp}.txt"
    
    # Run backtests
    results = []
    start_time = time.time()
    
    for i, (activation, distance) in enumerate(combinations, 1):
        print(f"\n[{i}/{len(combinations)}] Testing: Activation={activation} pips, Distance={distance} pips")
        
        result = run_backtest(activation, distance, env_file)
        results.append(result)
        
        if result.get('success'):
            print(f"✓ Success: Total PnL=${result['total_pnl']:.2f}, Win Rate={result['win_rate']:.1f}%")
        else:
            print(f"✗ Failed: {result.get('error', 'Unknown error')}")
        
        # Small delay to avoid overwhelming the system
        time.sleep(1)
    
    elapsed_time = time.time() - start_time
    print(f"\n{'='*80}")
    print(f"Completed {len(combinations)} backtests in {elapsed_time/60:.1f} minutes")
    print(f"{'='*80}")
    
    # Generate comparison report
    print("\nGenerating comparison report...")
    generate_comparison_report(results, output_file)
    
    # Summary
    successful = [r for r in results if r.get('success', False)]
    if successful:
        best = max(successful, key=lambda x: x['total_pnl'])
        print(f"\n{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}")
        print(f"Best Combination:")
        print(f"  Activation: {best['activation_pips']} pips")
        print(f"  Distance: {best['distance_pips']} pips")
        print(f"  Total PnL: ${best['total_pnl']:.2f}")
        print(f"  Win Rate: {best['win_rate']:.1f}%")
        print(f"  Trades: {best['total_trades']}")
        print(f"\nFull report: {output_file}")
        print(f"{'='*80}")

if __name__ == "__main__":
    main()

