#!/usr/bin/env python3
"""
Phase 2 JSON Regeneration Utility

This script reads the corrected Phase 2 CSV file and regenerates the JSON artifacts
in the exact format expected by the optimization pipeline.

Usage:
    # Regenerate JSON files from corrected CSV
    python optimization/tools/regenerate_phase2_json.py --input optimization/results/phase2_coarse_grid.csv --objective sharpe_ratio

    # Verify existing JSON files match CSV data
    python optimization/tools/regenerate_phase2_json.py --verify-only

    # Rank by PnL instead of Sharpe ratio
    python optimization/tools/regenerate_phase2_json.py --objective total_pnl
"""

import pandas as pd
import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional


def _resolve_csv_path(path: str) -> str:
    """
    Resolve input path to a .csv file. If the provided path has no suffix and
    a corresponding .csv exists, use that. Otherwise return the path as-is.
    """
    p = Path(path)
    if p.suffix.lower() != '.csv':
        candidate = Path(str(p) + '.csv')
        if candidate.exists():
            return str(candidate)
    return str(p)


def load_csv_results(csv_path: str, objective: str) -> pd.DataFrame:
    """
    Load and validate CSV results file.
    
    Args:
        csv_path: Path to the CSV file
        
    Returns:
        Sorted DataFrame with completed runs only
    """
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        sys.exit(1)
    
    # Filter to only completed runs
    if 'status' in df.columns:
        df = df[df['status'] == 'completed']
        print(f"Loaded {len(df)} completed runs from {len(pd.read_csv(csv_path))} total runs")
    else:
        print(f"Warning: No 'status' column found, using all {len(df)} rows")
    
    # Validate required columns
    required_columns = ['run_id', 'sharpe_ratio', 'total_pnl', 'win_rate', 'max_drawdown', 'trade_count']
    parameter_columns = ['fast_period', 'slow_period', 'crossover_threshold_pips', 'stop_loss_pips', 
                        'take_profit_pips', 'trailing_stop_activation_pips', 'trailing_stop_distance_pips',
                        'dmi_enabled', 'dmi_period', 'stoch_enabled', 'stoch_period_k', 'stoch_period_d',
                        'stoch_bullish_threshold', 'stoch_bearish_threshold']
    
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        print(f"Error: Missing required columns: {missing_columns}")
        sys.exit(1)
    
    # Check for parameter columns (some may be missing in older data)
    missing_params = [col for col in parameter_columns if col not in df.columns]
    if missing_params:
        print(f"Warning: Missing parameter columns: {missing_params}")
    
    # Validate objective column exists
    if objective not in df.columns:
        print(f"Error: Objective column '{objective}' not found in CSV. Available columns: {list(df.columns)}")
        sys.exit(1)

    # Sort by objective descending
    df = df.sort_values(objective, ascending=False)
    
    return df


def generate_top_10_json(df: pd.DataFrame, objective: str = 'sharpe_ratio') -> List[Dict[str, Any]]:
    """
    Generate top 10 results JSON structure.
    
    Args:
        df: Sorted DataFrame
        objective: Objective column to use for ranking
        
    Returns:
        List of dictionaries for top 10 results
    """
    top_10 = df.head(10)
    results = []
    
    for idx, (_, row) in enumerate(top_10.iterrows(), 1):
        # Extract parameters
        parameters = {}
        param_columns = ['fast_period', 'slow_period', 'crossover_threshold_pips', 'stop_loss_pips',
                        'take_profit_pips', 'trailing_stop_activation_pips', 'trailing_stop_distance_pips',
                        'dmi_enabled', 'dmi_period', 'stoch_enabled', 'stoch_period_k', 'stoch_period_d',
                        'stoch_bullish_threshold', 'stoch_bearish_threshold']
        
        for col in param_columns:
            if col in row:
                parameters[col] = row[col]
        
        result = {
            'rank': idx,
            'run_id': row['run_id'],
            'parameters': parameters,
            'objective_value': row[objective]
        }
        results.append(result)
    
    return results


def generate_summary_json(df: pd.DataFrame, original_df: pd.DataFrame, objective: str = 'sharpe_ratio') -> Dict[str, Any]:
    """
    Generate summary statistics JSON structure.
    
    Args:
        df: Sorted DataFrame with completed runs
        original_df: Original DataFrame with all runs
        objective: Objective column name
        
    Returns:
        Dictionary with summary statistics
    """
    # Overall statistics
    total_runs = len(original_df)
    completed = len(df)
    # Status breakdown if present
    status_counts: Dict[str, int] = {}
    if 'status' in original_df.columns:
        status_counts = original_df['status'].value_counts(dropna=False).to_dict()
    failed = status_counts.get('failed', total_runs - completed)
    timeout = status_counts.get('timeout', 0)
    
    # Calculate success rate
    success_rate = completed / total_runs if total_runs > 0 else 0
    
    # Best run (first row after sorting)
    best_row = df.iloc[0]
    best_parameters = {}
    param_columns = ['fast_period', 'slow_period', 'crossover_threshold_pips', 'stop_loss_pips',
                    'take_profit_pips', 'trailing_stop_activation_pips', 'trailing_stop_distance_pips',
                    'dmi_enabled', 'dmi_period', 'stoch_enabled', 'stoch_period_k', 'stoch_period_d',
                    'stoch_bullish_threshold', 'stoch_bearish_threshold']
    
    for col in param_columns:
        if col in best_row:
            best_parameters[col] = best_row[col]
    
    best_metrics = {
        'total_pnl': best_row['total_pnl'],
        'sharpe_ratio': best_row['sharpe_ratio'],
        'win_rate': best_row['win_rate'],
        'max_drawdown': best_row['max_drawdown'],
        'trade_count': best_row['trade_count']
    }
    
    # Add profit_factor and expectancy if available
    if 'profit_factor' in best_row:
        best_metrics['profit_factor'] = best_row['profit_factor']
    if 'expectancy' in best_row:
        best_metrics['expectancy'] = best_row['expectancy']
    
    best_run = {
        'run_id': best_row['run_id'],
        'objective_value': best_row[objective],
        'parameters': best_parameters,
        'metrics': best_metrics
    }
    
    # Worst run (last row after sorting)
    worst_row = df.iloc[-1]
    worst_parameters = {}
    for col in param_columns:
        if col in worst_row:
            worst_parameters[col] = worst_row[col]
    
    worst_metrics = {
        'total_pnl': worst_row['total_pnl'],
        'sharpe_ratio': worst_row['sharpe_ratio'],
        'win_rate': worst_row['win_rate'],
        'max_drawdown': worst_row['max_drawdown'],
        'trade_count': worst_row['trade_count']
    }
    
    if 'profit_factor' in worst_row:
        worst_metrics['profit_factor'] = worst_row['profit_factor']
    if 'expectancy' in worst_row:
        worst_metrics['expectancy'] = worst_row['expectancy']
    
    worst_run = {
        'run_id': worst_row['run_id'],
        'objective_value': worst_row[objective],
        'parameters': worst_parameters,
        'metrics': worst_metrics
    }
    
    # Calculate averages
    avg_columns = ['total_pnl', 'sharpe_ratio', 'win_rate', 'max_drawdown', 'trade_count']
    if 'profit_factor' in df.columns:
        avg_columns.append('profit_factor')
    if 'expectancy' in df.columns:
        avg_columns.append('expectancy')
    
    averages = {}
    for col in avg_columns:
        if col in df.columns:
            averages[col] = df[col].mean()
    
    # Parameter sensitivity (correlation with objective)
    sensitivity = {}
    numeric_params = ['fast_period', 'slow_period', 'crossover_threshold_pips']
    for param in numeric_params:
        if param in df.columns and objective in df.columns:
            try:
                correlation = df[[param, objective]].corr()[objective][param]
                sensitivity[param] = correlation
            except:
                sensitivity[param] = None
    
    return {
        'overall': {
            'total_runs': total_runs,
            'completed': completed,
            'failed': failed,
            'timeout': timeout,
            'status_counts': status_counts,
            'success_rate': success_rate
        },
        'best': best_run,
        'worst': worst_run,
        'averages': averages,
        'sensitivity': sensitivity,
        'objective': objective
    }


def main():
    """Main function to regenerate Phase 2 JSON files."""
    parser = argparse.ArgumentParser(description='Regenerate Phase 2 JSON files from corrected CSV data')
    parser.add_argument('--input', default='optimization/results/phase2_coarse_grid.csv',
                       help='Path to input CSV file')
    parser.add_argument('--output-dir', default='optimization/results',
                       help='Output directory for JSON files')
    parser.add_argument('--objective', default='sharpe_ratio', choices=['sharpe_ratio', 'total_pnl'],
                       help='Objective to rank by')
    parser.add_argument('--verify-only', action='store_true',
                       help='Only verify existing JSON files without regenerating')
    parser.add_argument('--fallback-input', default='optimization/results/phase2_coarse_grid_ranked_by_pnl.csv',
                       help='Optional fallback CSV ranked by PnL when Sharpe ratios are all zero')
    
    args = parser.parse_args()
    
    # Resolve and load CSV data
    resolved_input = _resolve_csv_path(args.input)
    print(f"Loading CSV data from: {resolved_input}")
    original_df = pd.read_csv(resolved_input)  # Keep original for statistics (unsorted)

    # Automatic fallback when Sharpe ratios are all zeros for completed runs
    used_fallback = False
    fallback_csv_path = None
    if 'sharpe_ratio' in original_df.columns and 'status' in original_df.columns:
        completed_mask = original_df['status'] == 'completed'
        completed_subset = original_df[completed_mask]
        if len(completed_subset) > 0 and (completed_subset['sharpe_ratio'] == 0.0).all():
            candidate = _resolve_csv_path(args.fallback_input) if args.fallback_input else None
            if candidate and Path(candidate).exists():
                print("All completed runs have Sharpe ratio = 0.0; applying fallback CSV ranked by PnL:")
                print(f"  -> {candidate}")
                original_df = pd.read_csv(candidate)
                args.objective = 'total_pnl'
                used_fallback = True
                fallback_csv_path = candidate
            else:
                print("All completed runs have Sharpe ratio = 0.0; switching objective to total_pnl")
                args.objective = 'total_pnl'

    # Now load filtered/sorted df using the (possibly adjusted) objective
    source_for_sorted = fallback_csv_path if used_fallback else resolved_input
    df = load_csv_results(source_for_sorted, args.objective)
    
    if len(df) == 0:
        print("Error: No completed runs found in CSV file")
        sys.exit(1)
    
    # Generate JSON structures
    print(f"Generating top 10 results ranked by {args.objective}")
    top_10_data = generate_top_10_json(df, args.objective)
    
    print("Generating summary statistics")
    summary_data = generate_summary_json(df, original_df, args.objective)
    
    if args.verify_only:
        # Load existing JSON files for comparison
        output_dir = Path(args.output_dir)
        top_10_file = output_dir / f"phase2_coarse_grid_top_10.json"
        summary_file = output_dir / f"phase2_coarse_grid_summary.json"
        
        if not top_10_file.exists() or not summary_file.exists():
            print("Error: Existing JSON files not found for verification")
            sys.exit(1)
        
        try:
            with open(top_10_file, 'r') as f:
                existing_top_10 = json.load(f)
            with open(summary_file, 'r') as f:
                existing_summary = json.load(f)
            
            # Compare top 10
            if existing_top_10 == top_10_data:
                print("✓ Top 10 JSON matches CSV data")
            else:
                print("✗ Top 10 JSON differs from CSV data")
                print("Differences found in top 10 results")
            
            # Compare summary
            if existing_summary == summary_data:
                print("✓ Summary JSON matches CSV data")
            else:
                print("✗ Summary JSON differs from CSV data")
                print("Differences found in summary statistics")
            
            print("\nVerification complete. Use without --verify-only to regenerate files.")
            
        except Exception as e:
            print(f"Error reading existing JSON files: {e}")
            sys.exit(1)
        
        return
    
    # Write JSON files
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    top_10_file = output_dir / f"phase2_coarse_grid_top_10.json"
    summary_file = output_dir / f"phase2_coarse_grid_summary.json"
    
    try:
        with open(top_10_file, 'w') as f:
            json.dump(top_10_data, f, indent=2)
        print(f"✓ Generated: {top_10_file}")
        
        with open(summary_file, 'w') as f:
            json.dump(summary_data, f, indent=2)
        print(f"✓ Generated: {summary_file}")
        
    except Exception as e:
        print(f"Error writing JSON files: {e}")
        sys.exit(1)
    
    # Print summary to console
    print(f"\n=== Phase 2 Results Summary ===")
    print(f"Total runs: {summary_data['overall']['total_runs']}")
    print(f"Completed: {summary_data['overall']['completed']}")
    print(f"Failed: {summary_data['overall']['failed']}")
    if 'timeout' in summary_data['overall']:
        print(f"Timeout: {summary_data['overall']['timeout']}")
    print(f"Success rate: {summary_data['overall']['success_rate']:.1%}")
    
    best = summary_data['best']
    print(f"\nBest parameters:")
    print(f"  Fast: {best['parameters'].get('fast_period', 'N/A')}")
    print(f"  Slow: {best['parameters'].get('slow_period', 'N/A')}")
    thresh_best = best['parameters'].get('crossover_threshold_pips', None)
    if isinstance(thresh_best, (int, float)):
        print(f"  Threshold: {thresh_best:.1f}")
    else:
        print("  Threshold: N/A")
    print(f"  Objective ({args.objective}): {best['objective_value']:.3f}")
    print(f"  PnL: ${best['metrics']['total_pnl']:,.2f}")
    
    print(f"\nTop 10 results by {args.objective}:")
    print(f"{'Rank':<4} {'Run ID':<6} {'Fast':<4} {'Slow':<4} {'Thresh':<6} {'Obj':<7} {'PnL':<10}")
    print("-" * 50)
    
    for result in top_10_data:
        params = result['parameters']
        fast = params.get('fast_period', 'N/A')
        slow = params.get('slow_period', 'N/A')
        thresh = params.get('crossover_threshold_pips', None)
        if isinstance(thresh, (int, float)):
            thresh_str = f"{thresh:.1f}"
        else:
            thresh_str = "N/A"
        pnl_val = df[df['run_id'] == result['run_id']]['total_pnl'].iloc[0]
        print(f"{result['rank']:<4} {result['run_id']:<6} "
              f"{fast!s:<4} "
              f"{slow!s:<4} "
              f"{thresh_str:<6} "
              f"{result['objective_value']:<7.3f} "
              f"${pnl_val:<10,.2f}")
    
    print(f"\nJSON files generated successfully in {output_dir}")


if __name__ == '__main__':
    main()
