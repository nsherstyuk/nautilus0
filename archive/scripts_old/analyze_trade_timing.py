"""Analyze trade distribution and timing from recent backtest."""
import pandas as pd
from pathlib import Path

# Load positions
pos = pd.read_csv('logs/backtest_results/EUR-USD_20251119_221601/positions.csv')
pos['ts_opened'] = pd.to_datetime(pos['ts_opened'])
pos['ts_closed'] = pd.to_datetime(pos['ts_closed'])

# Extract numeric PnL (remove " USD" suffix)
pos['pnl'] = pos['realized_pnl'].str.replace(' USD', '').astype(float)

# Basic stats
print('=' * 80)
print('BACKTEST PERFORMANCE SUMMARY')
print('=' * 80)
total_pnl = pos["pnl"].sum()
print(f'Total PnL: ${total_pnl:,.2f}')
print(f'Total Trades: {len(pos)}')
winners = pos[pos["pnl"] > 0]
losers = pos[pos["pnl"] < 0]
print(f'Winners: {len(winners)} | Losers: {len(losers)}')
print(f'Win Rate: {len(winners) / len(pos) * 100:.2f}%')
print(f'Avg Winner: ${winners["pnl"].mean():.2f}')
print(f'Avg Loser: ${losers["pnl"].mean():.2f}')
print(f'Expectancy: ${pos["pnl"].mean():.2f} per trade')
print(f'\nBacktest Period: {pos["ts_opened"].min().date()} to {pos["ts_closed"].max().date()}')
print(f'Duration: {(pos["ts_closed"].max() - pos["ts_opened"].min()).days} days')
print()

# Trade distribution by month
print('=' * 80)
print('TRADE DISTRIBUTION BY MONTH')
print('=' * 80)
monthly = pos.groupby(pos['ts_opened'].dt.to_period('M')).agg({
    'pnl': ['count', 'sum']
}).round(2)
monthly.columns = ['Trades', 'PnL']
monthly = monthly[monthly['Trades'] > 0]  # Filter out months with no trades
print(monthly)
print()

# Average trades per month
total_days = (pos['ts_closed'].max() - pos['ts_opened'].min()).days
avg_trades_per_month = len(pos) / (total_days / 30.44)
print(f'Average Trades per Month: {avg_trades_per_month:.1f}')
print(f'Average Trades per Week: {len(pos) / (total_days / 7):.1f}')
print()

# Time between trades
pos_sorted = pos.sort_values('ts_opened')
time_diffs = pos_sorted['ts_opened'].diff()
print('=' * 80)
print('TIME BETWEEN TRADES')
print('=' * 80)
print(f'Median: {time_diffs.median().total_seconds() / 3600:.1f} hours')
print(f'Mean: {time_diffs.mean().total_seconds() / 3600:.1f} hours')
print(f'Min: {time_diffs.min().total_seconds() / 3600:.1f} hours')
print(f'Max: {time_diffs.max().total_seconds() / 24:.1f} days')
print()

# Percentiles
print('Time Between Trades (Percentiles):')
for p in [10, 25, 50, 75, 90, 95]:
    hours = time_diffs.quantile(p/100).total_seconds() / 3600
    print(f'  {p}th percentile: {hours:.1f} hours')
print()

# Estimate for live trading
print('=' * 80)
print('LIVE TRADING ESTIMATE')
print('=' * 80)
median_hours = time_diffs.median().total_seconds() / 3600
mean_hours = time_diffs.mean().total_seconds() / 3600
p25_hours = time_diffs.quantile(0.25).total_seconds() / 3600

print(f'Based on backtest trade frequency:')
print(f'  25% chance of trade within: {p25_hours:.1f} hours ({p25_hours/24:.1f} days)')
print(f'  50% chance of trade within: {median_hours:.1f} hours ({median_hours/24:.1f} days)')
print(f'  Expected wait time: {mean_hours:.1f} hours ({mean_hours/24:.1f} days)')
print()

# Recent trades (last 20)
print('=' * 80)
print('LAST 20 TRADES IN BACKTEST')
print('=' * 80)
recent = pos_sorted.tail(20)[['ts_opened', 'entry', 'side', 'avg_px_open', 'avg_px_close', 'pnl']]
recent['pnl_str'] = recent['pnl'].apply(lambda x: f'${x:+.2f}')
recent = recent.drop('pnl', axis=1)
print(recent.to_string(index=False))
