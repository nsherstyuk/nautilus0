"""Analyze hourly PnL from backtest results."""
import pandas as pd
from pathlib import Path

# Read positions
pos_file = Path("logs/backtest_results/EUR-USD_20251107_203601/positions.csv")
pos = pd.read_csv(pos_file)

# Parse timestamps and extract hour
pos['ts_opened'] = pd.to_datetime(pos['ts_opened'])
pos['hour'] = pos['ts_opened'].dt.hour

# Extract PnL value (remove " USD" suffix)
pos['pnl_value'] = pos['realized_pnl'].str.replace(' USD', '').astype(float)

# Group by hour
hourly_stats = pos.groupby('hour').agg({
    'pnl_value': ['sum', 'mean', 'count'],
}).reset_index()
hourly_stats.columns = ['hour', 'total_pnl', 'avg_pnl', 'trade_count']

# Sort by hour
hourly_stats = hourly_stats.sort_values('hour')

# Calculate win rate
hourly_wins = pos[pos['pnl_value'] > 0].groupby('hour').size()
hourly_total = pos.groupby('hour').size()
hourly_stats['win_rate'] = (hourly_wins / hourly_total * 100).fillna(0)

# Sort by total PnL to see best/worst hours
print("=" * 80)
print("HOURLY PROFITABILITY ANALYSIS")
print("=" * 80)
print("\nSorted by Hour (0-23):")
print(hourly_stats.to_string(index=False))

print("\n" + "=" * 80)
print("SORTED BY TOTAL PnL (Best to Worst):")
print("=" * 80)
hourly_stats_sorted = hourly_stats.sort_values('total_pnl', ascending=False)
print(hourly_stats_sorted.to_string(index=False))

print("\n" + "=" * 80)
print("RECOMMENDATIONS:")
print("=" * 80)
print("\nMost Profitable Hours (should NOT be excluded):")
profitable = hourly_stats_sorted[hourly_stats_sorted['total_pnl'] > 0]
if len(profitable) > 0:
    print(profitable[['hour', 'total_pnl', 'trade_count', 'win_rate']].to_string(index=False))
else:
    print("No profitable hours found")

print("\nMost Unprofitable Hours (should be excluded):")
unprofitable = hourly_stats_sorted[hourly_stats_sorted['total_pnl'] < 0]
if len(unprofitable) > 0:
    print(unprofitable[['hour', 'total_pnl', 'trade_count', 'win_rate']].to_string(index=False))
else:
    print("No unprofitable hours found")

print("\nCurrently Excluded Hours: 0,4,6,8,9,15,18,20,22")
current_excluded = {0, 4, 6, 8, 9, 15, 18, 20, 22}
profitable_hours = set(profitable['hour'].tolist()) if len(profitable) > 0 else set()
unprofitable_hours = set(unprofitable['hour'].tolist()) if len(unprofitable) > 0 else set()

print(f"\nHours that are profitable but currently excluded: {sorted(profitable_hours & current_excluded)}")
print(f"Hours that are unprofitable but NOT excluded: {sorted(unprofitable_hours - current_excluded)}")

