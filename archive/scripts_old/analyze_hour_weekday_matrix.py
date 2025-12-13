#!/usr/bin/env python3
"""
Analyze MTF backtest results by hour-weekday combination.
Shows if certain hours are only bad on specific weekdays.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np

def load_latest_backtest_results():
    """Load the most recent backtest results."""
    results_dir = PROJECT_ROOT / "logs" / "backtest_results"
    
    # Find the most recent MTF_ML folder
    mtf_folders = sorted(results_dir.glob("MTF_ML_*"), reverse=True)
    
    if not mtf_folders:
        print("❌ No MTF backtest results found!")
        print(f"   Looking in: {results_dir}")
        return None
    
    latest = mtf_folders[0]
    trades_file = latest / "trades.csv"
    
    if not trades_file.exists():
        print(f"❌ trades.csv not found in {latest}")
        return None
    
    print(f"Loading results from: {latest.name}")
    df = pd.read_csv(trades_file)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    
    return df

def analyze_hour_weekday_matrix(df):
    """Create hour x weekday performance matrix."""
    weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    # Create matrix
    matrix_pnl = pd.DataFrame(index=range(24), columns=weekday_names)
    matrix_trades = pd.DataFrame(index=range(24), columns=weekday_names)
    matrix_winrate = pd.DataFrame(index=range(24), columns=weekday_names)
    
    for hour in range(24):
        for day in range(7):
            day_name = weekday_names[day]
            
            # Filter trades for this hour and weekday
            mask = (df['entry_hour'] == hour) & (df['entry_weekday'] == day)
            trades = df[mask]
            
            if len(trades) == 0:
                matrix_pnl.loc[hour, day_name] = 0
                matrix_trades.loc[hour, day_name] = 0
                matrix_winrate.loc[hour, day_name] = 0
            else:
                total_pnl = trades['pnl'].sum()
                win_rate = len(trades[trades['pnl'] > 0]) / len(trades) * 100
                
                matrix_pnl.loc[hour, day_name] = total_pnl
                matrix_trades.loc[hour, day_name] = len(trades)
                matrix_winrate.loc[hour, day_name] = win_rate
    
    return matrix_pnl, matrix_trades, matrix_winrate

def find_worst_combinations(matrix_pnl, matrix_trades, min_trades=5):
    """Find worst hour-weekday combinations."""
    worst = []
    
    for hour in range(24):
        for day in matrix_pnl.columns:
            pnl = matrix_pnl.loc[hour, day]
            trades = matrix_trades.loc[hour, day]
            
            if trades >= min_trades and pnl < 0:
                worst.append({
                    'hour': hour,
                    'weekday': day,
                    'trades': int(trades),
                    'pnl': float(pnl),
                    'avg_pnl': float(pnl / trades)
                })
    
    df_worst = pd.DataFrame(worst)
    if len(df_worst) > 0:
        df_worst = df_worst.sort_values('pnl')
    
    return df_worst

def find_best_combinations(matrix_pnl, matrix_trades, min_trades=5):
    """Find best hour-weekday combinations."""
    best = []
    
    for hour in range(24):
        for day in matrix_pnl.columns:
            pnl = matrix_pnl.loc[hour, day]
            trades = matrix_trades.loc[hour, day]
            
            if trades >= min_trades and pnl > 0:
                best.append({
                    'hour': hour,
                    'weekday': day,
                    'trades': int(trades),
                    'pnl': float(pnl),
                    'avg_pnl': float(pnl / trades)
                })
    
    df_best = pd.DataFrame(best)
    if len(df_best) > 0:
        df_best = df_best.sort_values('pnl', ascending=False)
    
    return df_best

def analyze_hour_consistency(matrix_pnl, matrix_trades):
    """Analyze which hours are consistently bad across all weekdays."""
    hour_analysis = []
    
    for hour in range(24):
        row_pnl = matrix_pnl.loc[hour]
        row_trades = matrix_trades.loc[hour]
        
        # Count how many days this hour is profitable
        days_with_trades = (row_trades > 0).sum()
        profitable_days = (row_pnl > 0).sum()
        losing_days = (row_pnl < 0).sum()
        
        total_pnl = row_pnl.sum()
        total_trades = row_trades.sum()
        
        if total_trades > 0:
            hour_analysis.append({
                'hour': hour,
                'total_pnl': total_pnl,
                'total_trades': int(total_trades),
                'days_traded': int(days_with_trades),
                'profitable_days': int(profitable_days),
                'losing_days': int(losing_days),
                'consistency': profitable_days / days_with_trades if days_with_trades > 0 else 0
            })
    
    df_hours = pd.DataFrame(hour_analysis)
    return df_hours

def generate_exclusion_recommendations(df_worst, df_hours):
    """Generate hour exclusion recommendations."""
    print("\n" + "="*80)
    print("EXCLUSION RECOMMENDATIONS")
    print("="*80)
    
    # Option 1: Exclude consistently bad hours
    consistently_bad = df_hours[
        (df_hours['total_pnl'] < 0) & 
        (df_hours['losing_days'] >= df_hours['profitable_days'])
    ].sort_values('total_pnl')
    
    if len(consistently_bad) > 0:
        print("\n📊 Option 1: Exclude Consistently Bad Hours (bad on most days)")
        print("-" * 60)
        bad_hours = consistently_bad['hour'].tolist()
        print(f"Hours to exclude: {bad_hours}")
        print(f"Total loss from these hours: ${consistently_bad['total_pnl'].sum():,.2f}")
        print(f"\nAdd to .env.mtf:")
        print(f"MTF_EXCLUDED_HOURS={','.join(map(str, bad_hours))}")
    
    # Option 2: Exclude specific hour-weekday combinations
    print("\n📊 Option 2: Exclude Specific Hour-Weekday Combinations")
    print("-" * 60)
    print("Top 10 worst combinations:")
    print(f"\n{'Hour':<6} {'Weekday':<12} {'Trades':<8} {'Total P&L':<15} {'Avg P&L':<12}")
    print("-" * 60)
    
    for _, row in df_worst.head(10).iterrows():
        print(f"{int(row['hour']):02d}:00  {row['weekday']:<12} {row['trades']:<8} ${row['pnl']:>12,.2f}  ${row['avg_pnl']:>10,.2f}")
    
    print("\n⚠️  Note: NautilusTrader doesn't support weekday-specific hour exclusions natively.")
    print("    You would need to implement this in the strategy code.")
    
    # Option 3: Conservative - exclude worst hours regardless of day
    worst_hours_overall = df_hours[df_hours['total_pnl'] < -500].sort_values('total_pnl')
    
    if len(worst_hours_overall) > 0:
        print("\n📊 Option 3: Exclude Worst Hours Overall (loss > $500)")
        print("-" * 60)
        worst_hours_list = worst_hours_overall['hour'].tolist()
        print(f"Hours to exclude: {worst_hours_list}")
        print(f"Total loss from these hours: ${worst_hours_overall['total_pnl'].sum():,.2f}")
        print(f"\nAdd to .env.mtf:")
        print(f"MTF_EXCLUDED_HOURS={','.join(map(str, worst_hours_list))}")

def main():
    """Main analysis function."""
    print("="*80)
    print("MTF STRATEGY - HOUR × WEEKDAY ANALYSIS")
    print("="*80)
    
    # Load data
    df = load_latest_backtest_results()
    if df is None:
        return 1
    
    print(f"Loaded {len(df)} trades\n")
    
    # Create matrices
    print("Creating hour × weekday performance matrix...")
    matrix_pnl, matrix_trades, matrix_winrate = analyze_hour_weekday_matrix(df)
    
    # Find worst combinations
    df_worst = find_worst_combinations(matrix_pnl, matrix_trades, min_trades=5)
    
    print("\n" + "="*80)
    print("WORST HOUR-WEEKDAY COMBINATIONS (min 5 trades)")
    print("="*80)
    
    if len(df_worst) > 0:
        print(f"\n{'Hour':<6} {'Weekday':<12} {'Trades':<8} {'Total P&L':<15} {'Avg P&L':<12}")
        print("-" * 60)
        for _, row in df_worst.head(20).iterrows():
            print(f"{int(row['hour']):02d}:00  {row['weekday']:<12} {row['trades']:<8} ${row['pnl']:>12,.2f}  ${row['avg_pnl']:>10,.2f}")
    else:
        print("\nNo losing combinations found!")
    
    # Find best combinations
    df_best = find_best_combinations(matrix_pnl, matrix_trades, min_trades=5)
    
    print("\n" + "="*80)
    print("BEST HOUR-WEEKDAY COMBINATIONS (min 5 trades)")
    print("="*80)
    
    if len(df_best) > 0:
        print(f"\n{'Hour':<6} {'Weekday':<12} {'Trades':<8} {'Total P&L':<15} {'Avg P&L':<12}")
        print("-" * 60)
        for _, row in df_best.head(20).iterrows():
            print(f"{int(row['hour']):02d}:00  {row['weekday']:<12} {row['trades']:<8} ${row['pnl']:>12,.2f}  ${row['avg_pnl']:>10,.2f}")
    
    # Analyze hour consistency
    df_hours = analyze_hour_consistency(matrix_pnl, matrix_trades)
    
    print("\n" + "="*80)
    print("HOUR CONSISTENCY ANALYSIS")
    print("="*80)
    print("\nHours that are bad on MOST days:")
    print(f"\n{'Hour':<6} {'Total P&L':<15} {'Trades':<8} {'Profitable Days':<18} {'Losing Days':<15}")
    print("-" * 70)
    
    bad_hours = df_hours[
        (df_hours['total_pnl'] < 0) & 
        (df_hours['losing_days'] >= df_hours['profitable_days'])
    ].sort_values('total_pnl')
    
    for _, row in bad_hours.iterrows():
        print(f"{int(row['hour']):02d}:00  ${row['total_pnl']:>12,.2f}  {row['total_trades']:<8} {row['profitable_days']:<18} {row['losing_days']:<15}")
    
    # Generate recommendations
    generate_exclusion_recommendations(df_worst, df_hours)
    
    # Save detailed matrix
    output_dir = PROJECT_ROOT / "logs" / "backtest_results"
    latest_folder = sorted(output_dir.glob("MTF_ML_*"), reverse=True)[0]
    
    matrix_pnl.to_csv(latest_folder / "hour_weekday_pnl_matrix.csv")
    matrix_trades.to_csv(latest_folder / "hour_weekday_trades_matrix.csv")
    matrix_winrate.to_csv(latest_folder / "hour_weekday_winrate_matrix.csv")
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
    print(f"\nDetailed matrices saved to: {latest_folder}")
    print("  - hour_weekday_pnl_matrix.csv")
    print("  - hour_weekday_trades_matrix.csv")
    print("  - hour_weekday_winrate_matrix.csv")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
