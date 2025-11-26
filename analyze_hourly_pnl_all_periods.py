"""
Analyze hourly PnL across all available data to find toxic trading hours.

This will show which hours consistently lose money across 2022-2025,
not just the hours that happened to be bad in 2024-2025.
"""

import pandas as pd
from pathlib import Path
import sys

def analyze_hourly_pnl_all_periods():
    """Analyze hourly PnL across all available backtest data."""
    
    # Find the most recent backtest result
    backtest_dir = Path("logs/backtest_results")
    if not backtest_dir.exists():
        print("❌ No backtest results found")
        return
    
    # Get most recent run
    runs = sorted([d for d in backtest_dir.iterdir() if d.is_dir()], 
                  key=lambda x: x.stat().st_mtime, reverse=True)
    
    if not runs:
        print("❌ No backtest runs found")
        return
    
    latest_run = runs[0]
    positions_file = latest_run / "positions.csv"
    
    if not positions_file.exists():
        print(f"❌ No positions.csv found in {latest_run}")
        return
    
    print(f"\n{'='*80}")
    print(f"HOURLY PNL ANALYSIS - ALL PERIODS")
    print(f"{'='*80}")
    print(f"Backtest run: {latest_run.name}")
    print()
    
    # Load positions
    pos = pd.read_csv(positions_file)
    
    # Parse PnL
    if 'realized_pnl' in pos.columns:
        pos['pnl'] = pos['realized_pnl'].str.replace(' USD', '').astype(float)
    else:
        print("❌ No realized_pnl column found")
        return
    
    # Parse timestamps
    pos['ts_opened'] = pd.to_datetime(pos['ts_opened'])
    pos['hour'] = pos['ts_opened'].dt.hour
    pos['weekday'] = pos['ts_opened'].dt.day_name()
    pos['year'] = pos['ts_opened'].dt.year
    
    print(f"Total trades: {len(pos)}")
    print(f"Date range: {pos['ts_opened'].min()} to {pos['ts_opened'].max()}")
    print(f"Total PnL: ${pos['pnl'].sum():,.2f}")
    print()
    
    # Hourly analysis
    print(f"{'='*80}")
    print(f"PNL BY HOUR (UTC) - ALL PERIODS COMBINED")
    print(f"{'='*80}")
    
    hourly = pos.groupby('hour').agg({
        'pnl': ['sum', 'mean', 'count'],
    }).round(2)
    
    hourly.columns = ['Total_PnL', 'Avg_PnL', 'Trades']
    hourly = hourly.sort_values('Total_PnL')
    
    # Mark worst hours
    hourly['Status'] = hourly['Total_PnL'].apply(
        lambda x: '❌ TOXIC' if x < -500 else ('⚠️  BAD' if x < 0 else '✅ GOOD')
    )
    
    print(hourly.to_string())
    
    # Summary
    print()
    print(f"{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    
    toxic_hours = hourly[hourly['Total_PnL'] < -500].index.tolist()
    bad_hours = hourly[(hourly['Total_PnL'] < 0) & (hourly['Total_PnL'] >= -500)].index.tolist()
    good_hours = hourly[hourly['Total_PnL'] >= 0].index.tolist()
    
    print(f"\n❌ TOXIC HOURS (should exclude): {sorted(toxic_hours)}")
    print(f"⚠️  BAD HOURS (consider excluding): {sorted(bad_hours)}")
    print(f"✅ GOOD HOURS (keep trading): {sorted(good_hours)}")
    
    # Year-by-year comparison
    print()
    print(f"{'='*80}")
    print(f"PNL BY HOUR AND YEAR (Check consistency)")
    print(f"{'='*80}")
    
    for year in sorted(pos['year'].unique()):
        year_data = pos[pos['year'] == year]
        year_hourly = year_data.groupby('hour')['pnl'].sum().round(2)
        print(f"\n{year} ({len(year_data)} trades):")
        
        # Show only hours with data
        for hour in sorted(year_hourly.index):
            pnl = year_hourly[hour]
            status = '❌' if pnl < -200 else ('⚠️' if pnl < 0 else '✅')
            print(f"  Hour {hour:2d}: {status} ${pnl:8,.2f}")
    
    # Weekday-hour heatmap (text version)
    print()
    print(f"{'='*80}")
    print(f"WORST HOUR-WEEKDAY COMBINATIONS")
    print(f"{'='*80}")
    
    weekday_hour = pos.groupby(['weekday', 'hour'])['pnl'].agg(['sum', 'count'])
    weekday_hour = weekday_hour[weekday_hour['count'] >= 3]  # At least 3 trades
    weekday_hour = weekday_hour.sort_values('sum')
    
    print("\nWorst 20 combinations (at least 3 trades):")
    print(weekday_hour.head(20).to_string())
    
    # Recommended exclusion list
    print()
    print(f"{'='*80}")
    print(f"RECOMMENDED TIME FILTER")
    print(f"{'='*80}")
    print()
    print("Based on ALL periods (2022-2025), exclude these hours:")
    print()
    
    # Conservative: only exclude clearly toxic hours
    recommended_hours = ','.join(map(str, sorted(toxic_hours)))
    print(f"Conservative (toxic only): {recommended_hours}")
    print()
    
    # Moderate: exclude toxic + consistently bad
    moderate_hours = ','.join(map(str, sorted(toxic_hours + bad_hours)))
    print(f"Moderate (toxic + bad): {moderate_hours}")
    print()
    
    print("Update .env with:")
    print(f"BACKTEST_TIME_FILTER_ENABLED=true")
    print(f"BACKTEST_EXCLUDED_HOURS={recommended_hours}")
    print(f"BACKTEST_EXCLUDED_HOURS_MODE=flat")
    print()

if __name__ == "__main__":
    analyze_hourly_pnl_all_periods()
