"""
Test drawdown calculation on existing backtest data.
"""
import pandas as pd
from pathlib import Path

# Load trades from existing backtest
bt_dir = Path('backtest_results/MTF_V2_REPLAY_20251224_213359')
trades_df = pd.read_csv(bt_dir / 'trades.csv')

# Convert exit_time to datetime
trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])

# Sort by exit time and reset index
df_sorted = trades_df.sort_values('exit_time').reset_index(drop=True)

# Calculate cumulative metrics
df_sorted['cumulative_pnl'] = df_sorted['pnl'].cumsum()
df_sorted['running_max'] = df_sorted['cumulative_pnl'].cummax()
df_sorted['drawdown'] = df_sorted['cumulative_pnl'] - df_sorted['running_max']

# Max drawdown
max_drawdown = df_sorted['drawdown'].min()
max_drawdown_pct = (max_drawdown / df_sorted['running_max'].max() * 100) if df_sorted['running_max'].max() > 0 else 0

# Find max drawdown period
max_dd_idx = df_sorted['drawdown'].idxmin()
max_dd_end = df_sorted.loc[max_dd_idx, 'exit_time']

# Find when the peak before drawdown occurred
peak_mask = df_sorted.index <= max_dd_idx
peak_before_dd = df_sorted.loc[peak_mask, 'running_max'].idxmax()
max_dd_start = df_sorted.loc[peak_before_dd, 'exit_time']
max_dd_duration_days = (max_dd_end - max_dd_start).days

# Calculate average drawdown
negative_drawdowns = df_sorted[df_sorted['drawdown'] < 0]['drawdown']
avg_drawdown = negative_drawdowns.mean() if len(negative_drawdowns) > 0 else 0

# Recovery time
if df_sorted['drawdown'].iloc[-1] == 0:
    recovery_idx = df_sorted[df_sorted.index > max_dd_idx][df_sorted['drawdown'] == 0].index[0]
    recovery_time = df_sorted.loc[recovery_idx, 'exit_time']
    recovery_duration_days = (recovery_time - max_dd_end).days
else:
    recovery_duration_days = None

# Print results
print("=" * 80)
print("DRAWDOWN ANALYSIS TEST")
print("=" * 80)
print(f"Total Trades: {len(trades_df)}")
print(f"Total PnL: ${trades_df['pnl'].sum():,.2f}")
print(f"Final Cumulative PnL: ${df_sorted['cumulative_pnl'].iloc[-1]:,.2f}")
print()
print(f"Max Drawdown: ${max_drawdown:,.2f} ({max_drawdown_pct:.1f}%)")
print(f"Max Drawdown Period: {max_dd_start.strftime('%Y-%m-%d')} to {max_dd_end.strftime('%Y-%m-%d')} ({max_dd_duration_days} days)")
print(f"Average Drawdown: ${avg_drawdown:,.2f}")
if recovery_duration_days is not None:
    print(f"Recovery Time: {recovery_duration_days} days")
else:
    print(f"Recovery Time: Not yet recovered")
print(f"Current Drawdown: ${df_sorted['drawdown'].iloc[-1]:,.2f}")
print()

# Show equity curve at key points
print("=" * 80)
print("EQUITY CURVE ANALYSIS")
print("=" * 80)
print(f"Starting Balance: $0.00")
print(f"Peak Balance: ${df_sorted['running_max'].max():,.2f}")
print(f"Ending Balance: ${df_sorted['cumulative_pnl'].iloc[-1]:,.2f}")
print(f"Peak Date: {df_sorted.loc[df_sorted['running_max'].idxmax(), 'exit_time'].strftime('%Y-%m-%d')}")
print()

# Drawdown statistics
print("=" * 80)
print("DRAWDOWN STATISTICS")
print("=" * 80)
print(f"Number of drawdown periods: {(df_sorted['drawdown'] < 0).sum()}")
print(f"Percentage of time in drawdown: {(df_sorted['drawdown'] < 0).mean() * 100:.1f}%")
print(f"Worst 5 drawdowns:")
worst_5 = df_sorted.nsmallest(5, 'drawdown')[['exit_time', 'drawdown', 'cumulative_pnl']]
for idx, row in worst_5.iterrows():
    print(f"  {row['exit_time'].strftime('%Y-%m-%d')}: ${row['drawdown']:,.2f} (Balance: ${row['cumulative_pnl']:,.2f})")
