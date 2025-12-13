"""Analyze trading consistency from backtest results."""
import pandas as pd
from pathlib import Path

# Read latest backtest positions
folder = Path("logs/backtest_results/EUR-USD_20251107_203601")
pos = pd.read_csv(folder / "positions.csv")

# Parse timestamps and extract PnL
pos['ts_opened'] = pd.to_datetime(pos['ts_opened'])
pos['pnl_value'] = pos['realized_pnl'].str.replace(' USD', '').astype(float)
pos['date'] = pos['ts_opened'].dt.date
pos['month'] = pos['ts_opened'].dt.to_period('M')
pos['week'] = pos['ts_opened'].dt.to_period('W')

# Create full date range
start_date = pos['date'].min()
end_date = pos['date'].max()
all_dates = pd.date_range(start=start_date, end=end_date, freq='D')

# Daily stats
daily = pos.groupby('date').agg({
    'pnl_value': ['sum', 'count'],
}).reset_index()
daily.columns = ['date', 'pnl', 'trades']

# Merge with full date range
daily_full = pd.DataFrame({'date': all_dates.date})
daily_full = daily_full.merge(daily, on='date', how='left')
daily_full['trades'] = daily_full['trades'].fillna(0).astype(int)
daily_full['pnl'] = daily_full['pnl'].fillna(0.0)

# Days with no trades
no_trade = daily_full[daily_full['trades'] == 0]
print(f"Days with NO trades: {len(no_trade)} ({len(no_trade)/len(daily_full)*100:.1f}%)")
print(f"\nFirst 30 days with no trades:")
print(no_trade[['date', 'trades']].head(30).to_string(index=False))

# Monthly stats
monthly = pos.groupby('month').agg({
    'pnl_value': ['sum', 'mean', 'count'],
}).reset_index()
monthly.columns = ['month', 'total_pnl', 'avg_pnl', 'trades']
monthly['wins'] = pos[pos['pnl_value'] > 0].groupby('month').size()
monthly['win_rate'] = (monthly['wins'] / monthly['trades'] * 100).fillna(0)
print(f"\n\nMonthly Performance:")
print(monthly[['month', 'trades', 'total_pnl', 'avg_pnl', 'win_rate']].to_string(index=False))

# Save to file
daily_full.to_csv(folder / "daily_trading_analysis.csv", index=False)
monthly.to_csv(folder / "monthly_trading_analysis.csv", index=False)
print(f"\n\nAnalysis saved to:")
print(f"  - {folder / 'daily_trading_analysis.csv'}")
print(f"  - {folder / 'monthly_trading_analysis.csv'}")

