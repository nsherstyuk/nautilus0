import pandas as pd
from pathlib import Path

pos = pd.read_csv('logs/backtest_results/EUR-USD_20251107_203601/positions.csv')
pos['ts_opened'] = pd.to_datetime(pos['ts_opened'])
pos['pnl_value'] = pos['realized_pnl'].str.replace(' USD', '').astype(float)
pos['date'] = pos['ts_opened'].dt.date
pos['month'] = pos['ts_opened'].dt.to_period('M')

start = pos['date'].min()
end = pos['date'].max()
all_dates = pd.date_range(start, end, freq='D')

daily = pos.groupby('date').agg({'pnl_value': ['sum', 'count']}).reset_index()
daily.columns = ['date', 'pnl', 'trades']
daily_full = pd.DataFrame({'date': all_dates.date}).merge(daily, on='date', how='left')
daily_full['trades'] = daily_full['trades'].fillna(0).astype(int)
daily_full['pnl'] = daily_full['pnl'].fillna(0.0)

no_trade = daily_full[daily_full['trades'] == 0]

print("="*80)
print("BACKTEST TRADING CONSISTENCY ANALYSIS")
print("="*80)
print(f"\nPeriod: {start} to {end}")
print(f"Total Days: {len(daily_full)}")
print(f"Days WITH trades: {len(daily_full[daily_full['trades'] > 0])} ({len(daily_full[daily_full['trades'] > 0])/len(daily_full)*100:.1f}%)")
print(f"Days with NO trades: {len(no_trade)} ({len(no_trade)/len(daily_full)*100:.1f}%)")
print(f"Total Trades: {len(pos)}")
print(f"Average trades per trading day: {daily_full[daily_full['trades'] > 0]['trades'].mean():.2f}")

print(f"\n\nFirst 30 days with NO trades:")
print(no_trade[['date', 'trades']].head(30).to_string(index=False))

monthly = pos.groupby('month').agg({'pnl_value': ['sum', 'mean', 'count']}).reset_index()
monthly.columns = ['month', 'total_pnl', 'avg_pnl', 'trades']
monthly['wins'] = pos[pos['pnl_value'] > 0].groupby('month').size()
monthly['win_rate'] = (monthly['wins'] / monthly['trades'] * 100).fillna(0)

print(f"\n\nMONTHLY PERFORMANCE:")
print(monthly[['month', 'trades', 'total_pnl', 'avg_pnl', 'win_rate']].to_string(index=False))

# Save
daily_full.to_csv('logs/backtest_results/EUR-USD_20251107_203601/daily_analysis.csv', index=False)
monthly.to_csv('logs/backtest_results/EUR-USD_20251107_203601/monthly_analysis.csv', index=False)
print("\n\nFiles saved: daily_analysis.csv and monthly_analysis.csv")

