#!/usr/bin/env python3
"""
Generate optimal weekday-specific hour exclusions based on backtest results.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

def load_hour_weekday_matrix():
    """Load the hour-weekday P&L matrix."""
    results_dir = PROJECT_ROOT / "logs" / "backtest_results"
    mtf_folders = sorted(results_dir.glob("MTF_ML_*"), reverse=True)
    
    if not mtf_folders:
        print("❌ No backtest results found!")
        return None, None
    
    latest = mtf_folders[0]
    pnl_file = latest / "hour_weekday_pnl_matrix.csv"
    trades_file = latest / "hour_weekday_trades_matrix.csv"
    
    if not pnl_file.exists():
        print(f"❌ Matrix files not found. Run analyze_hour_weekday_matrix.py first!")
        return None, None
    
    df_pnl = pd.read_csv(pnl_file, index_col=0)
    df_trades = pd.read_csv(trades_file, index_col=0)
    
    return df_pnl, df_trades

def generate_exclusions(df_pnl, df_trades, min_trades=5, pnl_threshold=-200):
    """
    Generate weekday-specific hour exclusions.
    
    Args:
        df_pnl: P&L matrix (hours x weekdays)
        df_trades: Trade count matrix (hours x weekdays)
        min_trades: Minimum trades required to consider excluding
        pnl_threshold: Exclude if P&L below this threshold
    """
    weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    exclusions = {day: [] for day in weekday_names}
    
    for day in weekday_names:
        for hour in range(24):
            pnl = float(df_pnl.loc[hour, day])
            trades = float(df_trades.loc[hour, day])
            
            # Exclude if: enough trades AND losing money
            if trades >= min_trades and pnl < pnl_threshold:
                exclusions[day].append(hour)
    
    return exclusions

def print_exclusions(exclusions):
    """Print exclusions in readable format."""
    print("\n" + "="*80)
    print("WEEKDAY-SPECIFIC HOUR EXCLUSIONS")
    print("="*80)
    
    for day, hours in exclusions.items():
        if hours:
            hours_str = ','.join(map(str, sorted(hours)))
            print(f"{day:<12}: {hours_str}")
        else:
            print(f"{day:<12}: (no exclusions)")

def generate_config_format(exclusions):
    """Generate configuration format for .env.mtf."""
    print("\n" + "="*80)
    print("ADD TO .env.mtf")
    print("="*80)
    print()
    
    for day, hours in exclusions.items():
        day_upper = day.upper()
        hours_str = ','.join(map(str, sorted(hours))) if hours else ''
        print(f"MTF_EXCLUDED_HOURS_{day_upper}={hours_str}")

def calculate_impact(df_pnl, df_trades, exclusions):
    """Calculate the impact of excluding these hours."""
    total_excluded_pnl = 0
    total_excluded_trades = 0
    
    weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    for day in weekday_names:
        for hour in exclusions[day]:
            pnl = float(df_pnl.loc[hour, day])
            trades = float(df_trades.loc[hour, day])
            total_excluded_pnl += pnl
            total_excluded_trades += trades
    
    print("\n" + "="*80)
    print("IMPACT ANALYSIS")
    print("="*80)
    print(f"\nTotal P&L from excluded hours: ${total_excluded_pnl:,.2f}")
    print(f"Total trades excluded: {int(total_excluded_trades)}")
    print(f"\nIf these hours were excluded:")
    print(f"  New P&L would be: ${14555.68 - total_excluded_pnl:,.2f}")
    print(f"  Improvement: ${-total_excluded_pnl:,.2f}")
    print(f"  Remaining trades: {1512 - int(total_excluded_trades)}")

def main():
    """Generate weekday-specific exclusions."""
    print("="*80)
    print("WEEKDAY-SPECIFIC HOUR EXCLUSION GENERATOR")
    print("="*80)
    
    # Load matrices
    df_pnl, df_trades = load_hour_weekday_matrix()
    if df_pnl is None:
        return 1
    
    print("\nGenerating exclusions...")
    print("Criteria: min 5 trades AND P&L < -$200\n")
    
    # Generate exclusions
    exclusions = generate_exclusions(df_pnl, df_trades, min_trades=5, pnl_threshold=-200)
    
    # Print results
    print_exclusions(exclusions)
    generate_config_format(exclusions)
    calculate_impact(df_pnl, df_trades, exclusions)
    
    print("\n" + "="*80)
    print("NEXT STEPS")
    print("="*80)
    print("\n1. Copy the MTF_EXCLUDED_HOURS_* lines above to .env.mtf")
    print("2. The strategy code will automatically use these exclusions")
    print("3. Re-run backtest to verify improvement")
    print("4. Use in live trading")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
