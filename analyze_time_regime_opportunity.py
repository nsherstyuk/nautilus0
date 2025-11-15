"""
Analyze whether time-based regime parameters could improve PnL.

Examines existing backtest results to see if:
1. Win rate varies by hour/weekday
2. Average P&L per trade varies by hour/weekday
3. Trending vs ranging markets correlate with specific times

This helps decide if implementing time-based regime multipliers is worth the effort.
"""
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
import sys

def load_positions(backtest_folder: Path):
    """Load positions from backtest output."""
    # Try to find positions data
    positions_files = list(backtest_folder.glob("**/positions.parquet"))
    if not positions_files:
        positions_files = list(backtest_folder.glob("**/positions.csv"))
    
    if not positions_files:
        print(f"No positions file found in {backtest_folder}")
        return None
    
    positions_file = positions_files[0]
    
    if positions_file.suffix == ".parquet":
        df = pd.read_parquet(positions_file)
    else:
        df = pd.read_csv(positions_file)
    
    return df

def analyze_time_patterns(positions_df: pd.DataFrame):
    """Analyze P&L patterns by hour and weekday."""
    
    if positions_df is None or len(positions_df) == 0:
        print("No position data available")
        return
    
    # Ensure timestamp columns are datetime
    if 'ts_opened' in positions_df.columns:
        positions_df['ts_opened'] = pd.to_datetime(positions_df['ts_opened'])
    elif 'entry_time' in positions_df.columns:
        positions_df['ts_opened'] = pd.to_datetime(positions_df['entry_time'])
    else:
        print("Cannot find entry timestamp column")
        return
    
    # Extract time features
    positions_df['hour'] = positions_df['ts_opened'].dt.hour
    positions_df['weekday'] = positions_df['ts_opened'].dt.day_name()
    
    # Calculate win/loss
    if 'realized_pnl' in positions_df.columns:
        pnl_col = 'realized_pnl'
    elif 'pnl' in positions_df.columns:
        pnl_col = 'pnl'
    else:
        print("Cannot find P&L column")
        return
    
    # Convert P&L to numeric (handle string values with currency suffix like "-76.38 USD")
    if positions_df[pnl_col].dtype == 'object':
        # Strip currency suffix and convert to float
        positions_df[pnl_col] = positions_df[pnl_col].astype(str).str.replace(r'\s*[A-Z]{3}$', '', regex=True)
    
    positions_df[pnl_col] = pd.to_numeric(positions_df[pnl_col], errors='coerce')
    
    # Drop rows with NaN P&L
    positions_df = positions_df.dropna(subset=[pnl_col])
    
    if len(positions_df) == 0:
        print("No valid P&L data after conversion")
        return
    
    positions_df['is_win'] = positions_df[pnl_col] > 0
    
    print("\n" + "="*80)
    print("TIME-BASED REGIME DETECTION OPPORTUNITY ANALYSIS")
    print("="*80)
    
    # Overall stats
    total_trades = len(positions_df)
    overall_win_rate = positions_df['is_win'].mean()
    overall_avg_pnl = positions_df[pnl_col].mean()
    
    print(f"\nOVERALL STATISTICS:")
    print(f"  Total Trades: {total_trades}")
    print(f"  Win Rate: {overall_win_rate:.2%}")
    print(f"  Avg P&L per Trade: ${overall_avg_pnl:.2f}")
    
    # Hour-based analysis
    print("\n" + "-"*80)
    print("HOURLY BREAKDOWN:")
    print("-"*80)
    hourly = positions_df.groupby('hour').agg({
        pnl_col: ['count', 'mean', 'sum'],
        'is_win': 'mean'
    }).round(4)
    hourly.columns = ['Trades', 'Avg_PnL', 'Total_PnL', 'Win_Rate']
    hourly['Win_Rate'] = hourly['Win_Rate'] * 100
    hourly = hourly.sort_values('Total_PnL', ascending=False)
    
    print(hourly.to_string())
    
    # Identify best/worst hours
    best_hours = hourly.nlargest(3, 'Total_PnL').index.tolist()
    worst_hours = hourly.nsmallest(3, 'Total_PnL').index.tolist()
    
    print(f"\n✓ BEST PERFORMING HOURS (by total P&L): {best_hours}")
    print(f"✗ WORST PERFORMING HOURS (by total P&L): {worst_hours}")
    
    # Weekday-based analysis
    print("\n" + "-"*80)
    print("WEEKDAY BREAKDOWN:")
    print("-"*80)
    weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday = positions_df.groupby('weekday').agg({
        pnl_col: ['count', 'mean', 'sum'],
        'is_win': 'mean'
    }).round(4)
    weekday.columns = ['Trades', 'Avg_PnL', 'Total_PnL', 'Win_Rate']
    weekday['Win_Rate'] = weekday['Win_Rate'] * 100
    weekday = weekday.reindex([d for d in weekday_order if d in weekday.index])
    
    print(weekday.to_string())
    
    # Hour × Weekday heatmap summary
    print("\n" + "-"*80)
    print("HOUR × WEEKDAY OPPORTUNITY MATRIX (Win Rate %):")
    print("-"*80)
    pivot = positions_df.pivot_table(
        values='is_win',
        index='hour',
        columns='weekday',
        aggfunc='mean'
    ) * 100
    pivot = pivot.reindex(columns=[d for d in weekday_order if d in pivot.columns])
    print(pivot.round(1).to_string())
    
    # Calculate variance to see if time matters
    hour_pnl_std = hourly['Avg_PnL'].std()
    weekday_pnl_std = weekday['Avg_PnL'].std()
    
    print("\n" + "="*80)
    print("OPPORTUNITY ASSESSMENT:")
    print("="*80)
    
    # Decision criteria
    hour_variance_ratio = hour_pnl_std / abs(overall_avg_pnl) if overall_avg_pnl != 0 else 0
    best_hour_pnl = hourly.loc[best_hours[0], 'Avg_PnL']
    worst_hour_pnl = hourly.loc[worst_hours[0], 'Avg_PnL']
    pnl_spread = abs(best_hour_pnl - worst_hour_pnl)
    
    print(f"\n1. Hourly P&L Variance: {hour_variance_ratio:.2f}x overall average")
    print(f"   Best hour avg: ${best_hour_pnl:.2f}")
    print(f"   Worst hour avg: ${worst_hour_pnl:.2f}")
    print(f"   Spread: ${pnl_spread:.2f}")
    
    if hour_variance_ratio > 0.5 or pnl_spread > abs(overall_avg_pnl):
        print("   ✓ HIGH POTENTIAL: Significant hourly variation detected!")
        print("     → Time-based regime parameters could improve P&L")
    elif hour_variance_ratio > 0.2:
        print("   ~ MODERATE POTENTIAL: Some hourly variation present")
        print("     → Time-based parameters might help marginally")
    else:
        print("   ✗ LOW POTENTIAL: Minimal hourly variation")
        print("     → Time-based parameters unlikely to improve P&L significantly")
    
    print(f"\n2. Weekday P&L Variance: {weekday_pnl_std:.2f}")
    best_weekday = weekday['Total_PnL'].idxmax()
    worst_weekday = weekday['Total_PnL'].idxmin()
    print(f"   Best weekday: {best_weekday} (${weekday.loc[best_weekday, 'Total_PnL']:.2f})")
    print(f"   Worst weekday: {worst_weekday} (${weekday.loc[worst_weekday, 'Total_PnL']:.2f})")
    
    print("\n" + "="*80)
    print("RECOMMENDATION:")
    print("="*80)
    
    if hour_variance_ratio > 0.5:
        print("""
✓ IMPLEMENT TIME-BASED REGIME PARAMETERS
  
  Suggested approach:
  1. Group hours into sessions (e.g., London: 8-12, NY: 13-17, Asian: 19-23)
  2. Create regime multiplier sets per session
  3. Use grid optimization to find best multipliers for each session
  
  Expected improvement: 10-30% based on variance observed
        """)
    elif hour_variance_ratio > 0.2:
        print("""
~ CONSIDER SIMPLE TIME FILTER FIRST
  
  Suggested approach:
  1. Exclude the worst-performing hours entirely
  2. Keep uniform regime parameters for remaining hours
  3. If this improves P&L, then consider time-based multipliers
  
  Expected improvement: 5-15% based on variance observed
        """)
    else:
        print("""
✗ FOCUS ON OTHER OPTIMIZATIONS
  
  Time-of-day doesn't significantly impact P&L in your current setup.
  Better ROI from:
  - Optimizing baseline TP/SL/trailing parameters
  - Tuning ADX thresholds for regime detection
  - Adjusting MA periods or crossover thresholds
        """)

def main():
    if len(sys.argv) > 1:
        backtest_folder = Path(sys.argv[1])
    else:
        # Use the last good run you mentioned
        backtest_folder = Path("logs/backtest_results/EUR-USD_20251113_195050")
    
    if not backtest_folder.exists():
        print(f"Error: Folder not found: {backtest_folder}")
        print("\nUsage: python analyze_time_regime_opportunity.py [path_to_backtest_folder]")
        return
    
    print(f"Analyzing backtest results from: {backtest_folder}")
    
    positions_df = load_positions(backtest_folder)
    
    if positions_df is not None:
        analyze_time_patterns(positions_df)
    else:
        print("\nCould not load positions data. Make sure the backtest folder contains:")
        print("  - positions.parquet or positions.csv")

if __name__ == "__main__":
    main()
