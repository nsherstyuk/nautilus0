"""Analyze backtest results for trading consistency and performance by day."""
import pandas as pd
from pathlib import Path
from datetime import datetime
import json

def find_latest_backtest():
    """Find the most recent backtest results folder."""
    results_dir = Path("logs/backtest_results")
    folders = [f for f in results_dir.iterdir() if f.is_dir() and f.name.startswith("EUR-USD_")]
    if not folders:
        return None
    return max(folders, key=lambda x: x.stat().st_mtime)

def analyze_backtest_results(folder_path: Path):
    """Analyze backtest results for trading patterns."""
    print("=" * 80)
    print(f"ANALYZING BACKTEST RESULTS: {folder_path.name}")
    print("=" * 80)
    
    # Read positions
    positions_file = folder_path / "positions.csv"
    if not positions_file.exists():
        print(f"ERROR: positions.csv not found in {folder_path}")
        return
    
    pos = pd.read_csv(positions_file)
    
    # Parse timestamps
    pos['ts_opened'] = pd.to_datetime(pos['ts_opened'])
    pos['ts_closed'] = pd.to_datetime(pos['ts_closed'])
    
    # Extract PnL value
    pos['pnl_value'] = pos['realized_pnl'].str.replace(' USD', '').astype(float)
    
    # Add date columns
    pos['date_opened'] = pos['ts_opened'].dt.date
    pos['date_closed'] = pos['ts_closed'].dt.date
    pos['month'] = pos['ts_opened'].dt.to_period('M')
    pos['week'] = pos['ts_opened'].dt.to_period('W')
    
    # Get date range
    start_date = pos['date_opened'].min()
    end_date = pos['date_opened'].max()
    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')
    
    print(f"\nBacktest Period: {start_date} to {end_date}")
    print(f"Total Days: {len(all_dates)}")
    print(f"Total Trades: {len(pos)}")
    
    # Daily analysis
    print("\n" + "=" * 80)
    print("DAILY TRADING ANALYSIS")
    print("=" * 80)
    
    daily_stats = pos.groupby('date_opened').agg({
        'pnl_value': ['sum', 'mean', 'count'],
    }).reset_index()
    daily_stats.columns = ['date', 'total_pnl', 'avg_pnl', 'trade_count']
    
    # Create full date range with zeros for days with no trades
    daily_full = pd.DataFrame({'date': all_dates.date})
    daily_full = daily_full.merge(daily_stats, on='date', how='left')
    daily_full['trade_count'] = daily_full['trade_count'].fillna(0).astype(int)
    daily_full['total_pnl'] = daily_full['total_pnl'].fillna(0.0)
    daily_full['avg_pnl'] = daily_full['avg_pnl'].fillna(0.0)
    
    # Days with no trades
    no_trade_days = daily_full[daily_full['trade_count'] == 0]
    print(f"\nDays with NO TRADES: {len(no_trade_days)} out of {len(daily_full)} ({len(no_trade_days)/len(daily_full)*100:.1f}%)")
    
    if len(no_trade_days) > 0:
        print("\nFirst 20 days with no trades:")
        print(no_trade_days[['date', 'trade_count']].head(20).to_string(index=False))
    
    # Days with trades
    trade_days = daily_full[daily_full['trade_count'] > 0]
    print(f"\nDays WITH TRADES: {len(trade_days)} out of {len(daily_full)} ({len(trade_days)/len(daily_full)*100:.1f}%)")
    print(f"Average trades per trading day: {trade_days['trade_count'].mean():.2f}")
    print(f"Max trades in a single day: {trade_days['trade_count'].max()}")
    print(f"Min trades in a single day: {trade_days['trade_count'].min()}")
    
    # Monthly analysis
    print("\n" + "=" * 80)
    print("MONTHLY PERFORMANCE ANALYSIS")
    print("=" * 80)
    
    monthly_stats = pos.groupby('month').agg({
        'pnl_value': ['sum', 'mean', 'count'],
    }).reset_index()
    monthly_stats.columns = ['month', 'total_pnl', 'avg_pnl', 'trade_count']
    monthly_stats['win_rate'] = (pos[pos['pnl_value'] > 0].groupby('month').size() / pos.groupby('month').size() * 100).fillna(0)
    monthly_stats = monthly_stats.sort_values('month')
    
    print(monthly_stats.to_string(index=False))
    
    # Weekly analysis
    print("\n" + "=" * 80)
    print("WEEKLY PERFORMANCE ANALYSIS")
    print("=" * 80)
    
    weekly_stats = pos.groupby('week').agg({
        'pnl_value': ['sum', 'mean', 'count'],
    }).reset_index()
    weekly_stats.columns = ['week', 'total_pnl', 'avg_pnl', 'trade_count']
    weekly_stats['win_rate'] = (pos[pos['pnl_value'] > 0].groupby('week').size() / pos.groupby('week').size() * 100).fillna(0)
    weekly_stats = weekly_stats.sort_values('week')
    
    print(f"\nTotal Weeks: {len(weekly_stats)}")
    print(f"Average trades per week: {weekly_stats['trade_count'].mean():.2f}")
    print(f"Weekly PnL range: ${weekly_stats['total_pnl'].min():.2f} to ${weekly_stats['total_pnl'].max():.2f}")
    
    # Consistency metrics
    print("\n" + "=" * 80)
    print("TRADING CONSISTENCY METRICS")
    print("=" * 80)
    
    # Calculate coefficient of variation for daily trade count
    cv_trades = trade_days['trade_count'].std() / trade_days['trade_count'].mean() if trade_days['trade_count'].mean() > 0 else 0
    print(f"Coefficient of Variation (trade count): {cv_trades:.2f}")
    print(f"  - Lower is more consistent")
    print(f"  - < 0.5 = very consistent, 0.5-1.0 = moderate, > 1.0 = inconsistent")
    
    # Calculate coefficient of variation for daily PnL
    cv_pnl = trade_days['total_pnl'].std() / abs(trade_days['total_pnl'].mean()) if trade_days['total_pnl'].mean() != 0 else 0
    print(f"\nCoefficient of Variation (daily PnL): {cv_pnl:.2f}")
    
    # Streaks
    daily_full['has_trade'] = daily_full['trade_count'] > 0
    daily_full['streak'] = (daily_full['has_trade'] != daily_full['has_trade'].shift()).cumsum()
    
    trade_streaks = daily_full[daily_full['has_trade']].groupby('streak').size()
    no_trade_streaks = daily_full[~daily_full['has_trade']].groupby('streak').size()
    
    if len(trade_streaks) > 0:
        print(f"\nLongest streak of trading days: {trade_streaks.max()} days")
        print(f"Average trading streak: {trade_streaks.mean():.1f} days")
    
    if len(no_trade_streaks) > 0:
        print(f"Longest streak of NO trading days: {no_trade_streaks.max()} days")
        print(f"Average no-trade streak: {no_trade_streaks.mean():.1f} days")
    
    # Period comparison (first half vs second half)
    print("\n" + "=" * 80)
    print("PERIOD COMPARISON (First Half vs Second Half)")
    print("=" * 80)
    
    midpoint = len(all_dates) // 2
    first_half_dates = all_dates[:midpoint].date
    second_half_dates = all_dates[midpoint:].date
    
    first_half_trades = pos[pos['date_opened'].isin(first_half_dates)]
    second_half_trades = pos[pos['date_opened'].isin(second_half_dates)]
    
    print(f"\nFirst Half ({first_half_dates[0]} to {first_half_dates[-1]}):")
    print(f"  Trades: {len(first_half_trades)}")
    print(f"  Total PnL: ${first_half_trades['pnl_value'].sum():.2f}")
    print(f"  Avg PnL: ${first_half_trades['pnl_value'].mean():.2f}")
    print(f"  Win Rate: {(first_half_trades['pnl_value'] > 0).sum() / len(first_half_trades) * 100:.1f}%")
    
    print(f"\nSecond Half ({second_half_dates[0]} to {second_half_dates[-1]}):")
    print(f"  Trades: {len(second_half_trades)}")
    print(f"  Total PnL: ${second_half_trades['pnl_value'].sum():.2f}")
    print(f"  Avg PnL: ${second_half_trades['pnl_value'].mean():.2f}")
    print(f"  Win Rate: {(second_half_trades['pnl_value'] > 0).sum() / len(second_half_trades) * 100:.1f}%")
    
    # Best and worst periods
    print("\n" + "=" * 80)
    print("BEST AND WORST PERFORMING PERIODS")
    print("=" * 80)
    
    print("\nTop 5 Best Weeks:")
    top_weeks = weekly_stats.nlargest(5, 'total_pnl')[['week', 'total_pnl', 'trade_count', 'win_rate']]
    print(top_weeks.to_string(index=False))
    
    print("\nTop 5 Worst Weeks:")
    worst_weeks = weekly_stats.nsmallest(5, 'total_pnl')[['week', 'total_pnl', 'trade_count', 'win_rate']]
    print(worst_weeks.to_string(index=False))
    
    # Save detailed daily report
    output_file = folder_path / "daily_analysis.csv"
    daily_full.to_csv(output_file, index=False)
    print(f"\nDetailed daily analysis saved to: {output_file}")
    
    return daily_full, monthly_stats, weekly_stats

if __name__ == "__main__":
    latest_folder = find_latest_backtest()
    if latest_folder:
        analyze_backtest_results(latest_folder)
    else:
        print("No backtest results found!")

