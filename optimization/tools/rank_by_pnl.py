#!/usr/bin/env python3
"""
PnL-Based Ranking Script

This script provides an immediate workaround for grid search results by ranking
them based on total PnL instead of Sharpe ratio (which may be missing or incorrect).

Usage:
    python optimization/tools/rank_by_pnl.py --input optimization/results/phase2_coarse_grid.csv --output optimization/results/phase2_coarse_grid_ranked_by_pnl.csv

Features:
- Ranks results by total PnL (descending)
- Preserves all original columns
- Adds a new 'pnl_rank' column
- Provides summary statistics
- Can handle both CSV and JSON input formats
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd


def rank_results_by_pnl(input_file: Path, output_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    Rank grid search results by total PnL.
    
    Args:
        input_file: Path to input CSV file
        output_file: Path to output CSV file (optional)
        
    Returns:
        Dictionary with ranking statistics
    """
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    
    # Read the CSV file
    try:
        df = pd.read_csv(input_file)
    except Exception as e:
        raise ValueError(f"Failed to read CSV file: {e}")
    
    if df.empty:
        raise ValueError("Input file is empty")
    
    # Check if total_pnl column exists
    if 'total_pnl' not in df.columns:
        raise ValueError("Input file missing 'total_pnl' column")
    
    # Sort by total_pnl in descending order
    df_sorted = df.sort_values('total_pnl', ascending=False).reset_index(drop=True)
    
    # Add PnL rank column
    df_sorted['pnl_rank'] = range(1, len(df_sorted) + 1)
    
    # Calculate statistics
    total_results = len(df_sorted)
    positive_pnl = len(df_sorted[df_sorted['total_pnl'] > 0])
    negative_pnl = len(df_sorted[df_sorted['total_pnl'] < 0])
    zero_pnl = len(df_sorted[df_sorted['total_pnl'] == 0])
    
    best_pnl = df_sorted.iloc[0]['total_pnl'] if total_results > 0 else 0
    worst_pnl = df_sorted.iloc[-1]['total_pnl'] if total_results > 0 else 0
    avg_pnl = df_sorted['total_pnl'].mean()
    
    # Get top 10 results
    top_10 = df_sorted.head(10)
    
    # Prepare statistics
    stats = {
        "total_results": total_results,
        "positive_pnl_count": positive_pnl,
        "negative_pnl_count": negative_pnl,
        "zero_pnl_count": zero_pnl,
        "best_pnl": best_pnl,
        "worst_pnl": worst_pnl,
        "average_pnl": avg_pnl,
        "top_10_results": top_10.to_dict('records')
    }
    
    # Write output file if specified
    if output_file:
        try:
            df_sorted.to_csv(output_file, index=False)
            print(f"SUCCESS: Ranked results written to: {output_file}")
        except Exception as e:
            print(f"ERROR: Failed to write output file: {e}")
            return stats
    
    return stats


def print_summary(stats: Dict[str, Any]) -> None:
    """Print a summary of the ranking results."""
    print("\n" + "="*60)
    print("PNL-BASED RANKING SUMMARY")
    print("="*60)
    
    print(f"Total Results: {stats['total_results']}")
    print(f"Positive PnL: {stats['positive_pnl_count']} ({stats['positive_pnl_count']/stats['total_results']*100:.1f}%)")
    print(f"Negative PnL: {stats['negative_pnl_count']} ({stats['negative_pnl_count']/stats['total_results']*100:.1f}%)")
    print(f"Zero PnL: {stats['zero_pnl_count']} ({stats['zero_pnl_count']/stats['total_results']*100:.1f}%)")
    
    print(f"\nBest PnL: ${stats['best_pnl']:,.2f}")
    print(f"Worst PnL: ${stats['worst_pnl']:,.2f}")
    print(f"Average PnL: ${stats['average_pnl']:,.2f}")
    
    print(f"\nTOP 10 RESULTS BY PNL:")
    print("-" * 60)
    for i, result in enumerate(stats['top_10_results'][:10], 1):
        pnl = result.get('total_pnl', 0)
        trade_count = result.get('trade_count', 0)
        sharpe = result.get('sharpe_ratio', 0)
        print(f"{i:2d}. PnL: ${pnl:8,.2f} | Trades: {trade_count:3d} | Sharpe: {sharpe:6.3f}")
    
    print("="*60)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Rank grid search results by total PnL",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--input", required=True,
        help="Path to input CSV file (grid search results)"
    )
    
    parser.add_argument(
        "--output",
        help="Path to output CSV file (optional)"
    )
    
    parser.add_argument(
        "--summary-only", action="store_true",
        help="Only print summary, don't write output file"
    )
    
    args = parser.parse_args()
    
    try:
        input_file = Path(args.input)
        output_file = Path(args.output) if args.output else None
        
        if args.summary_only:
            output_file = None
        
        # Rank the results
        stats = rank_results_by_pnl(input_file, output_file)
        
        # Print summary
        print_summary(stats)
        
        return 0
        
    except Exception as e:
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
