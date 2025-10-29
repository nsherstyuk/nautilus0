#!/usr/bin/env python3
"""
PnL-Ranked CSV Update Utility

This script regenerates the phase2_coarse_grid_ranked_by_pnl.csv file using the 
corrected data from phase2_coarse_grid (which has valid Sharpe ratios).

Usage:
    # Regenerate PnL-ranked CSV with correct Sharpe ratios
    python optimization/tools/update_pnl_ranked_csv.py

    # Compare before overwriting
    python optimization/tools/update_pnl_ranked_csv.py --compare
"""

import pandas as pd
import argparse
import sys
from pathlib import Path
def _resolve_csv_path(path: str) -> str:
    """
    Resolve input path to a .csv file. If no suffix and a .csv exists, use it.
    """
    p = Path(path)
    if p.suffix.lower() != '.csv':
        candidate = Path(str(p) + '.csv')
        if candidate.exists():
            return str(candidate)
    return str(p)



def regenerate_pnl_ranked_csv(input_csv: str, output_csv: str) -> dict:
    """
    Regenerate PnL-ranked CSV with correct Sharpe ratios.
    
    Args:
        input_csv: Path to corrected CSV file
        output_csv: Path to output PnL-ranked CSV
        
    Returns:
        Dictionary with statistics
    """
    try:
        # Read the corrected CSV file
        df = pd.read_csv(input_csv)
        print(f"Loaded {len(df)} rows from {input_csv}")
        
        # Sort by total_pnl descending
        df = df.sort_values('total_pnl', ascending=False)
        
        # Reset index to get clean row numbers
        df = df.reset_index(drop=True)
        
        # Add pnl_rank column
        df['pnl_rank'] = range(1, len(df) + 1)
        
        # Reorder columns to put pnl_rank at the end
        columns = [col for col in df.columns if col != 'pnl_rank'] + ['pnl_rank']
        df = df[columns]
        
        # Write to output CSV
        df.to_csv(output_csv, index=False)
        print(f"✓ Generated: {output_csv}")
        
        # Calculate statistics
        stats = {
            'total_rows': len(df),
            'best_pnl': df['total_pnl'].max(),
            'worst_pnl': df['total_pnl'].min(),
            'avg_pnl': df['total_pnl'].mean(),
            'best_sharpe': df.iloc[0]['sharpe_ratio'] if 'sharpe_ratio' in df.columns else None
        }
        
        return stats
        
    except Exception as e:
        print(f"Error regenerating PnL-ranked CSV: {e}")
        sys.exit(1)


def print_comparison(old_csv: str, new_csv: str):
    """
    Compare old and new CSV files to show improvements.
    
    Args:
        old_csv: Path to existing PnL-ranked CSV
        new_csv: Path to new PnL-ranked CSV
    """
    try:
        old_df = pd.read_csv(old_csv)
        new_df = pd.read_csv(new_csv)
        
        print(f"\n=== Comparison: {old_csv} vs {new_csv} ===")
        print(f"Old file rows: {len(old_df)}")
        print(f"New file rows: {len(new_df)}")
        
        if 'sharpe_ratio' in old_df.columns and 'sharpe_ratio' in new_df.columns:
            # Count zero Sharpe ratios in old file
            zero_sharpe_old = (old_df['sharpe_ratio'] == 0.0).sum()
            zero_sharpe_new = (new_df['sharpe_ratio'] == 0.0).sum()
            
            print(f"Zero Sharpe ratios in old file: {zero_sharpe_old}")
            print(f"Zero Sharpe ratios in new file: {zero_sharpe_new}")
            
            if zero_sharpe_old > zero_sharpe_new:
                print(f"✓ Sharpe ratios updated from 0.0 to calculated values")
                print(f"  Improvement: {zero_sharpe_old - zero_sharpe_new} rows now have valid Sharpe ratios")
            else:
                print("ℹ No change in zero Sharpe ratio count")
        
        # Show top 5 results comparison (ranked by total_pnl desc)
        old_sorted = old_df.sort_values('total_pnl', ascending=False).reset_index(drop=True)
        new_sorted = new_df.sort_values('total_pnl', ascending=False).reset_index(drop=True)
        print(f"\nTop 5 by PnL ranked (old vs new):")
        print(f"{'Rank':<4} {'Old PnL':<10} {'Old Sharpe':<10} {'New PnL':<10} {'New Sharpe':<10}")
        print("-" * 50)
        
        for i in range(min(5, len(old_sorted), len(new_sorted))):
            old_pnl = old_sorted.iloc[i]['total_pnl']
            new_pnl = new_sorted.iloc[i]['total_pnl']
            old_sharpe = old_sorted.iloc[i]['sharpe_ratio'] if 'sharpe_ratio' in old_sorted.columns else 'N/A'
            new_sharpe = new_sorted.iloc[i]['sharpe_ratio'] if 'sharpe_ratio' in new_sorted.columns else 'N/A'
            
            old_sharpe_str = f"{old_sharpe:.3f}" if isinstance(old_sharpe, (int, float)) else "N/A"
            new_sharpe_str = f"{new_sharpe:.3f}" if isinstance(new_sharpe, (int, float)) else "N/A"
            print(f"{i+1:<4} ${old_pnl:<9.2f} {old_sharpe_str:<10} ${new_pnl:<9.2f} {new_sharpe_str:<10}")
        
    except Exception as e:
        print(f"Error comparing files: {e}")


def main():
    """Main function to update PnL-ranked CSV."""
    parser = argparse.ArgumentParser(description='Update PnL-ranked CSV with correct Sharpe ratios')
    parser.add_argument('--input', default='optimization/results/phase2_coarse_grid.csv',
                       help='Path to corrected CSV file')
    parser.add_argument('--output', default='optimization/results/phase2_coarse_grid_ranked_by_pnl.csv',
                       help='Path to output PnL-ranked CSV')
    parser.add_argument('--compare', action='store_true',
                       help='Compare with existing PnL-ranked CSV before overwriting')
    
    args = parser.parse_args()
    
    # Check if input file exists
    resolved_input = _resolve_csv_path(args.input)
    if not Path(resolved_input).exists():
        print(f"Error: Input file not found: {resolved_input}")
        sys.exit(1)
    
    # Check if output file exists for comparison
    if args.compare and Path(args.output).exists():
        print(f"Existing PnL-ranked CSV found: {args.output}")
        print("Comparing with corrected data...")
        print_comparison(args.output, resolved_input)
        
        # Prompt for confirmation
        response = input("\nProceed with overwriting? (y/N): ").strip().lower()
        if response not in ['y', 'yes']:
            print("Operation cancelled.")
            return
    
    # Regenerate PnL-ranked CSV
    print(f"Regenerating PnL-ranked CSV from: {resolved_input}")
    stats = regenerate_pnl_ranked_csv(resolved_input, args.output)
    
    # Print success message
    print(f"\n✓ Successfully updated: {args.output}")
    print(f"Total rows: {stats['total_rows']}")
    print(f"Best PnL: ${stats['best_pnl']:,.2f}")
    print(f"Worst PnL: ${stats['worst_pnl']:,.2f}")
    print(f"Average PnL: ${stats['avg_pnl']:,.2f}")
    
    if stats['best_sharpe'] is not None:
        print(f"Best Sharpe ratio: {stats['best_sharpe']:.3f}")
    
    # Show top 5 results
    try:
        df = pd.read_csv(args.output)
        df = df.sort_values('total_pnl', ascending=False).reset_index(drop=True)
        print(f"\nTop 5 results by PnL (ranked):")
        print(f"{'Rank':<4} {'Run ID':<6} {'Fast':<4} {'Slow':<4} {'Thresh':<6} {'PnL':<10} {'Sharpe':<7}")
        print("-" * 50)
        
        for i in range(min(5, len(df))):
            row = df.iloc[i]
            fast = row.get('fast_period', 'N/A')
            slow = row.get('slow_period', 'N/A')
            thresh = row.get('crossover_threshold_pips', None)
            thresh_str = f"{thresh:.1f}" if isinstance(thresh, (int, float)) else "N/A"
            sharpe = row.get('sharpe_ratio', 'N/A')
            sharpe_str = f"{sharpe:.3f}" if isinstance(sharpe, (int, float)) else "N/A"
            print(f"{row['pnl_rank']:<4} {row['run_id']:<6} "
                  f"{fast!s:<4} "
                  f"{slow!s:<4} "
                  f"{thresh_str:<6} "
                  f"${row['total_pnl']:<9.2f} "
                  f"{sharpe_str:<7}")
        
    except Exception as e:
        print(f"Warning: Could not display top 5 results: {e}")


if __name__ == '__main__':
    main()
