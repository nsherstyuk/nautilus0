#!/usr/bin/env python
"""
Quick visualization launcher - finds the most recent backtest/optimization results.

Usage:
    python viz.py                    # Show menu of recent results
    python viz.py --summary          # Create summary of most recent
    python viz.py --detailed --days 7  # Detailed chart of last 7 days
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta
import subprocess

PROJECT_ROOT = Path(__file__).parent


def find_recent_results(limit=10):
    """Find most recent backtest/optimization result folders."""
    results = []
    
    # Check backtest_results
    backtest_dir = PROJECT_ROOT / "backtest_results"
    if backtest_dir.exists():
        for folder in backtest_dir.iterdir():
            if folder.is_dir() and (folder / "trades.csv").exists():
                results.append({
                    'path': folder,
                    'name': folder.name,
                    'mtime': folder.stat().st_mtime,
                    'type': 'backtest'
                })
    
    # Check optimization_results
    opt_dir = PROJECT_ROOT / "optimization_results"
    if opt_dir.exists():
        for opt_run in opt_dir.iterdir():
            if opt_run.is_dir():
                for folder in opt_run.iterdir():
                    if folder.is_dir() and (folder / "trades.csv").exists():
                        results.append({
                            'path': folder,
                            'name': f"{opt_run.name}/{folder.name}",
                            'mtime': folder.stat().st_mtime,
                            'type': 'optimization'
                        })
    
    # Sort by modification time
    results.sort(key=lambda x: x['mtime'], reverse=True)
    return results[:limit]


def show_menu(results):
    """Show interactive menu of results."""
    print("\n=== Recent Backtest Results ===\n")
    for i, result in enumerate(results, 1):
        mtime = datetime.fromtimestamp(result['mtime'])
        print(f"{i:2d}. [{result['type']:12s}] {result['name'][:60]}")
        print(f"     Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    print("Enter number to visualize (or 'q' to quit): ", end='')


def main():
    parser = argparse.ArgumentParser(description='Quick visualization launcher')
    parser.add_argument('--summary', action='store_true', help='Create summary visualization')
    parser.add_argument('--detailed', action='store_true', help='Create detailed price chart')
    parser.add_argument('--days', type=int, help='Number of days to visualize (for detailed)')
    parser.add_argument('--folder', type=str, help='Specific folder path to visualize')
    parser.add_argument('--list', action='store_true', help='Just list recent results')
    
    args = parser.parse_args()
    
    # Find recent results
    results = find_recent_results(limit=20)
    
    if not results:
        print("No backtest results found.")
        sys.exit(1)
    
    # If just listing
    if args.list:
        show_menu(results)
        sys.exit(0)
    
    # Determine which folder to use
    if args.folder:
        folder_path = PROJECT_ROOT / args.folder
        if not folder_path.exists():
            print(f"Error: Folder not found: {folder_path}")
            sys.exit(1)
    else:
        # Show menu if not specified
        show_menu(results)
        try:
            choice = input().strip()
            if choice.lower() == 'q':
                sys.exit(0)
            
            idx = int(choice) - 1
            if idx < 0 or idx >= len(results):
                print("Invalid choice")
                sys.exit(1)
            
            folder_path = results[idx]['path']
        except (ValueError, KeyboardInterrupt):
            print("\nCancelled")
            sys.exit(0)
    
    # Determine visualization type
    if not args.summary and not args.detailed:
        print("\nVisualization type:")
        print("1. Summary dashboard (fast, entire backtest)")
        print("2. Detailed price chart (slow, specific dates)")
        try:
            choice = input("Choose (1/2): ").strip()
            if choice == '1':
                args.summary = True
            elif choice == '2':
                args.detailed = True
            else:
                print("Invalid choice")
                sys.exit(1)
        except KeyboardInterrupt:
            print("\nCancelled")
            sys.exit(0)
    
    # Get relative path
    try:
        rel_path = folder_path.relative_to(PROJECT_ROOT)
    except ValueError:
        rel_path = folder_path
    
    # Build command
    if args.summary:
        cmd = [sys.executable, "visualize_replay_summary.py", str(rel_path)]
        print(f"\nCreating summary visualization for: {folder_path.name}")
    else:
        cmd = [sys.executable, "visualize_replay_backtest.py", str(rel_path)]
        
        if args.days:
            # Calculate date range
            import pandas as pd
            trades_df = pd.read_csv(folder_path / "trades.csv")
            trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])
            max_date = trades_df['exit_time'].max()
            start_date = max_date - timedelta(days=args.days)
            
            cmd.extend([
                "--start", start_date.strftime("%Y-%m-%d"),
                "--end", max_date.strftime("%Y-%m-%d")
            ])
            print(f"\nCreating detailed chart for last {args.days} days: {folder_path.name}")
        else:
            print(f"\nCreating detailed chart for: {folder_path.name}")
            print("(This may take a while for large date ranges...)")
    
    # Run visualization
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"\nError running visualization: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(0)


if __name__ == "__main__":
    main()
