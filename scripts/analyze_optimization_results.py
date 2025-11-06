"""
Analysis script for comparing optimization results.

This script helps you:
1. View top results from a single optimization run
2. Compare results across multiple optimization runs
3. Identify best parameters and configurations
4. Generate comparison reports

Usage:
    # View top results from a single run
    python scripts/analyze_optimization_results.py \
        --results optimization/results/multi_tf_primary_bar_spec_results.csv \
        --top 20

    # Compare multiple optimization runs
    python scripts/analyze_optimization_results.py \
        --compare \
        --results optimization/results/multi_tf_trend_filter_results.csv \
        --results optimization/results/multi_tf_entry_timing_results.csv \
        --results optimization/results/multi_tf_combined_results.csv \
        --results optimization/results/multi_tf_primary_bar_spec_results.csv
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_results_csv(csv_path: Path) -> pd.DataFrame:
    """Load optimization results CSV."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Results file not found: {csv_path}")
    
    df = pd.read_csv(csv_path)
    # Filter to completed runs only
    df = df[df['status'] == 'completed'].copy()
    return df


def load_summary_json(csv_path: Path) -> Optional[Dict[str, Any]]:
    """Load summary JSON file."""
    summary_path = csv_path.parent / f"{csv_path.stem}_summary.json"
    if not summary_path.exists():
        return None
    
    with open(summary_path, 'r') as f:
        return json.load(f)


def load_top_10_json(csv_path: Path) -> Optional[List[Dict[str, Any]]]:
    """Load top 10 JSON file."""
    top_10_path = csv_path.parent / f"{csv_path.stem}_top_10.json"
    if not top_10_path.exists():
        return None
    
    with open(top_10_path, 'r') as f:
        return json.load(f)


def print_top_results(df: pd.DataFrame, top_n: int = 20):
    """Print top N results from a dataframe."""
    print(f"\n{'='*80}")
    print(f"TOP {top_n} RESULTS (Ranked by Objective)")
    print(f"{'='*80}\n")
    
    # Select top N and key columns
    top_df = df.head(top_n).copy()
    
    # Key metrics to display
    display_cols = [
        'rank', 'run_id', 'objective_value', 'sharpe_ratio', 'total_pnl', 
        'win_rate', 'trade_count', 'max_drawdown', 'profit_factor', 'expectancy'
    ]
    
    # Add parameter columns if they exist
    param_cols = ['bar_spec', 'fast_period', 'slow_period', 'trend_filter_enabled', 
                  'trend_bar_spec', 'entry_timing_enabled', 'entry_timing_bar_spec']
    
    for col in param_cols:
        if col in top_df.columns:
            display_cols.append(col)
    
    # Filter to existing columns
    display_cols = [col for col in display_cols if col in top_df.columns]
    
    # Format display
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', 30)
    
    print(top_df[display_cols].to_string(index=False))
    print()


def print_summary_stats(summary: Dict[str, Any]):
    """Print summary statistics."""
    print(f"\n{'='*80}")
    print("SUMMARY STATISTICS")
    print(f"{'='*80}\n")
    
    if "overall" in summary:
        overall = summary["overall"]
        print(f"Total Runs: {overall['total_runs']}")
        print(f"Completed: {overall['completed']}")
        print(f"Failed: {overall.get('failed', 0)}")
        print(f"Success Rate: {overall['success_rate']*100:.1f}%")
        print()
    
    if "best" in summary:
        best = summary["best"]
        print("BEST RESULT:")
        print(f"  Run ID: {best['run_id']}")
        print(f"  Objective Value: {best['objective_value']:.4f}")
        print(f"  Sharpe Ratio: {best['metrics']['sharpe_ratio']:.4f}")
        print(f"  Total PnL: ${best['metrics']['total_pnl']:,.2f}")
        print(f"  Win Rate: {best['metrics']['win_rate']*100:.1f}%")
        print(f"  Trade Count: {best['metrics']['trade_count']}")
        print(f"  Max Drawdown: {best['metrics']['max_drawdown']:.2f}%")
        print(f"  Parameters:")
        for key, value in best['parameters'].items():
            if key not in ['run_id']:
                print(f"    {key}: {value}")
        print()
    
    if "averages" in summary:
        avg = summary["averages"]
        print("AVERAGE METRICS:")
        print(f"  Sharpe Ratio: {avg['sharpe_ratio']:.4f}")
        print(f"  Total PnL: ${avg['total_pnl']:,.2f}")
        print(f"  Win Rate: {avg['win_rate']*100:.1f}%")
        print(f"  Trade Count: {avg['trade_count']:.1f}")
        print()


def compare_multiple_results(result_paths: List[Path]):
    """Compare results across multiple optimization runs."""
    print(f"\n{'='*80}")
    print("COMPARING MULTIPLE OPTIMIZATION RUNS")
    print(f"{'='*80}\n")
    
    results = []
    for path in result_paths:
        try:
            df = load_results_csv(path)
            summary = load_summary_json(path)
            
            if df.empty:
                print(f"⚠️  {path.name}: No completed results")
                continue
            
            best = df.iloc[0]  # Top result
            
            results.append({
                'file': path.name,
                'total_runs': len(df),
                'best_sharpe': best['sharpe_ratio'],
                'best_pnl': best['total_pnl'],
                'best_win_rate': best['win_rate'],
                'best_trades': best['trade_count'],
                'best_objective': best.get('objective_value', best['sharpe_ratio']),
                'best_run_id': best['run_id'],
                'summary': summary,
            })
        except Exception as e:
            print(f"❌ Error loading {path.name}: {e}")
            continue
    
    if not results:
        print("No valid results to compare.")
        return
    
    # Create comparison DataFrame
    comp_df = pd.DataFrame(results)
    
    # Sort by objective value (best first)
    comp_df = comp_df.sort_values('best_objective', ascending=False)
    
    print("COMPARISON TABLE:")
    print("-" * 80)
    
    # Display key columns
    display_cols = ['file', 'total_runs', 'best_objective', 'best_sharpe', 
                   'best_pnl', 'best_win_rate', 'best_trades', 'best_run_id']
    
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', 40)
    
    print(comp_df[display_cols].to_string(index=False))
    print()
    
    # Find overall best
    overall_best = comp_df.iloc[0]
    print(f"\n🏆 OVERALL BEST RESULT:")
    print(f"  File: {overall_best['file']}")
    print(f"  Run ID: {overall_best['best_run_id']}")
    print(f"  Sharpe Ratio: {overall_best['best_sharpe']:.4f}")
    print(f"  Total PnL: ${overall_best['best_pnl']:,.2f}")
    print(f"  Win Rate: {overall_best['best_win_rate']*100:.1f}%")
    print(f"  Trade Count: {overall_best['best_trades']}")
    
    # Show best parameters from each run
    print(f"\n{'='*80}")
    print("BEST PARAMETERS FROM EACH RUN:")
    print(f"{'='*80}\n")
    
    for result in results:
        print(f"\n📊 {result['file']}:")
        if result['summary'] and 'best' in result['summary']:
            params = result['summary']['best']['parameters']
            for key, value in params.items():
                if key not in ['run_id']:
                    print(f"  {key}: {value}")


def analyze_parameter_impact(df: pd.DataFrame):
    """Analyze which parameters have the most impact on performance."""
    print(f"\n{'='*80}")
    print("PARAMETER IMPACT ANALYSIS")
    print(f"{'='*80}\n")
    
    # Group by key parameters and calculate average metrics
    param_cols = ['bar_spec', 'trend_filter_enabled', 'trend_bar_spec', 
                  'entry_timing_enabled', 'entry_timing_bar_spec']
    
    available_param_cols = [col for col in param_cols if col in df.columns]
    
    if not available_param_cols:
        print("No parameter columns found for analysis.")
        return
    
    for param in available_param_cols:
        print(f"\n📈 Impact of {param}:")
        print("-" * 80)
        
        grouped = df.groupby(param).agg({
            'sharpe_ratio': ['mean', 'count'],
            'total_pnl': 'mean',
            'win_rate': 'mean',
            'trade_count': 'mean'
        }).round(4)
        
        grouped.columns = ['Avg Sharpe', 'Count', 'Avg PnL', 'Avg Win Rate', 'Avg Trades']
        grouped = grouped.sort_values('Avg Sharpe', ascending=False)
        
        print(grouped.to_string())
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze and compare optimization results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--results',
        type=Path,
        action='append',
        help='Path to results CSV file (can specify multiple for comparison)'
    )
    
    parser.add_argument(
        '--top',
        type=int,
        default=20,
        help='Number of top results to display (default: 20)'
    )
    
    parser.add_argument(
        '--compare',
        action='store_true',
        help='Compare multiple result files'
    )
    
    parser.add_argument(
        '--analyze',
        action='store_true',
        help='Analyze parameter impact'
    )
    
    args = parser.parse_args()
    
    if not args.results:
        parser.error("Must specify at least one --results file")
    
    if args.compare and len(args.results) < 2:
        parser.error("--compare requires at least 2 result files")
    
    if args.compare:
        # Compare multiple runs
        compare_multiple_results(args.results)
    else:
        # Single file analysis
        csv_path = args.results[0]
        
        print(f"Analyzing: {csv_path}")
        
        # Load data
        df = load_results_csv(csv_path)
        summary = load_summary_json(csv_path)
        
        if df.empty:
            print("No completed results found.")
            return
        
        # Print summary
        if summary:
            print_summary_stats(summary)
        
        # Print top results
        print_top_results(df, args.top)
        
        # Parameter impact analysis
        if args.analyze:
            analyze_parameter_impact(df)


if __name__ == "__main__":
    main()

