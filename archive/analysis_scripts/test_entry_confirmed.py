"""
Test the entry confirmed strategy on March 2025 data.

This script runs both the original V2 and the entry confirmed V2
on the same period to compare results and measure improvement.
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

def run_original_v2():
    """Run original V2 backtest on March 2025."""
    print("=" * 80)
    print("RUNNING ORIGINAL V2 BACKTEST (March 2025)")
    print("=" * 80)
    
    # Set environment for March 2025
    env = os.environ.copy()
    env["MTF2_BACKTEST_START"] = "2025-03-01"
    env["MTF2_BACKTEST_END"] = "2025-03-31"
    
    # Run original V2 backtest
    result = subprocess.run(
        ["python", "run_backtest_mtf_v2_replay.py"],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=env,
        cwd=Path.cwd()
    )
    
    if result.returncode == 0:
        print("Original V2 backtest completed successfully")
        # Find the results directory (most recent)
        results_dirs = list(Path("backtest_results").glob("MTF_V2_REPLAY_*"))
        if results_dirs:
            latest_dir = max(results_dirs, key=lambda x: x.stat().st_mtime)
            print(f"Results saved to: {latest_dir}")
            return latest_dir
    else:
        print(f"Original V2 backtest failed: {result.stderr}")
    
    return None

def run_entry_confirmed_v2():
    """Run entry confirmed V2 backtest on March 2025."""
    print("\n" + "=" * 80)
    print("RUNNING ENTRY CONFIRMED V2 BACKTEST (March 2025)")
    print("=" * 80)
    
    # Set environment for March 2025
    env = os.environ.copy()
    env["MTF2_BACKTEST_START"] = "2025-03-01"
    env["MTF2_BACKTEST_END"] = "2025-03-31"
    
    # Run entry confirmed V2 backtest
    result = subprocess.run(
        ["python", "run_backtest_mtf_v2_entry_confirmed.py"],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=env,
        cwd=Path.cwd()
    )
    
    if result.returncode == 0:
        print("Entry confirmed V2 backtest completed successfully")
        # Find the results directory (most recent)
        results_dirs = list(Path("backtest_results").glob("MTF_V2_ENTRY_CONFIRMED_*"))
        if results_dirs:
            latest_dir = max(results_dirs, key=lambda x: x.stat().st_mtime)
            print(f"Results saved to: {latest_dir}")
            return latest_dir
    else:
        print(f"Entry confirmed V2 backtest failed: {result.stderr}")
    
    return None

def compare_results(original_dir, entry_confirmed_dir):
    """Compare results between original and entry confirmed versions."""
    print("\n" + "=" * 80)
    print("COMPARING RESULTS")
    print("=" * 80)
    
    # Load trade data from both results
    original_trades = Path(original_dir) / "trades.csv"
    entry_confirmed_trades = Path(entry_confirmed_dir) / "trades.csv"
    
    if not original_trades.exists() or not entry_confirmed_trades.exists():
        print("Cannot compare - trade files not found")
        return
    
    import pandas as pd
    
    original_df = pd.read_csv(original_trades)
    entry_confirmed_df = pd.read_csv(entry_confirmed_trades)
    
    print(f"Original V2: {len(original_df)} trades")
    print(f"Entry Confirmed V2: {len(entry_confirmed_df)} trades")
    
    # Calculate basic metrics
    def calculate_metrics(df):
        total_pnl = df['pnl'].sum()
        wins = len(df[df['exit_reason'] == 'TP'])
        losses = len(df[df['exit_reason'] == 'SL'])
        win_rate = wins / len(df) * 100 if len(df) > 0 else 0
        
        return {
            'total_trades': len(df),
            'total_pnl': total_pnl,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate
        }
    
    original_metrics = calculate_metrics(original_df)
    entry_confirmed_metrics = calculate_metrics(entry_confirmed_df)
    
    print("\nPerformance Comparison:")
    print("-" * 80)
    print(f"{'Metric':<20} | {'Original V2':>12} | {'Entry Confirmed':>15} | {'Difference':>12}")
    print("-" * 80)
    
    metrics_to_compare = [
        ('Total Trades', 'total_trades', ''),
        ('Total PnL ($)', 'total_pnl', '${:,.2f}'),
        ('Wins', 'wins', ''),
        ('Losses', 'losses', ''),
        ('Win Rate (%)', 'win_rate', '{:.1f}%'),
    ]
    
    for label, key, fmt in metrics_to_compare:
        orig_val = original_metrics[key]
        conf_val = entry_confirmed_metrics[key]
        
        if fmt:
            orig_str = fmt.format(orig_val)
            conf_str = fmt.format(conf_val)
        else:
            orig_str = str(orig_val)
            conf_str = str(conf_val)
        
        if key == 'total_pnl':
            diff = conf_val - orig_val
            diff_str = f"${diff:+,.2f}"
        elif key == 'win_rate':
            diff = conf_val - orig_val
            diff_str = f"{diff:+.1f}%"
        else:
            diff = conf_val - orig_val
            diff_str = f"{diff:+d}"
        
        print(f"{label:<20} | {orig_str:>12} | {conf_str:>15} | {diff_str:>12}")
    
    print("\nKey Insights:")
    print("-" * 80)
    
    # Analyze trade reduction
    trade_reduction = len(original_df) - len(entry_confirmed_df)
    trade_reduction_pct = (trade_reduction / len(original_df)) * 100 if len(original_df) > 0 else 0
    
    print(f"Trade Reduction: {trade_reduction} trades ({trade_reduction_pct:.1f}%)")
    
    if trade_reduction > 0:
        print("  ✓ Entry confirmation is filtering out trades")
        
        # Check if quality improved
        pnl_improvement = entry_confirmed_metrics['total_pnl'] - original_metrics['total_pnl']
        wr_improvement = entry_confirmed_metrics['win_rate'] - original_metrics['win_rate']
        
        print(f"  PnL Impact: ${pnl_improvement:+,.2f}")
        print(f"  Win Rate Impact: {wr_improvement:+.1f}%")
        
        if pnl_improvement > 0 and wr_improvement > 0:
            print("  ✓ Both PnL and Win Rate improved - Entry confirmation is working!")
        elif pnl_improvement > 0:
            print("  ✓ PnL improved - Entry confirmation is adding value")
        elif wr_improvement > 0:
            print("  ✓ Win Rate improved - Entry confirmation is filtering bad entries")
        else:
            print("  ⚠ Entry confirmation may be too restrictive")
    else:
        print("  ⚠ No trade reduction - Entry confirmation may not be working")
    
    print("\nRecommendations:")
    print("-" * 80)
    
    if trade_reduction_pct > 20:
        print("  • Consider reducing entry confirmation threshold (currently 0.2 ATR)")
        print("  • May be filtering out too many trades")
    elif trade_reduction_pct < 5:
        print("  • Consider increasing entry confirmation threshold")
        print("  • May not be filtering enough premature entries")
    else:
        print("  • Entry confirmation settings appear well-balanced")
    
    if pnl_improvement > 0:
        print("  • Results improved - consider using entry confirmed version for live trading")
    else:
        print("  • Results did not improve - keep original version for now")

def main():
    """Main function."""
    print("Testing Entry Confirmation Strategy")
    print("Comparing Original V2 vs Entry Confirmed V2 on March 2025 data")
    print()
    
    # Run both backtests
    original_dir = run_original_v2()
    entry_confirmed_dir = run_entry_confirmed_v2()
    
    # Compare results
    if original_dir and entry_confirmed_dir:
        compare_results(original_dir, entry_confirmed_dir)
    else:
        print("Could not compare results - one or both backtests failed")
    
    print("\n" + "=" * 80)
    print("TEST COMPLETED")
    print("=" * 80)

if __name__ == "__main__":
    main()
