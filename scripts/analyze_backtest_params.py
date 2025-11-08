"""
Extract parameters from backtest results and logs
"""
from pathlib import Path
import pandas as pd
import json
from datetime import datetime

results_dir = Path('logs/backtest_results/EUR-USD_20251106_193355')

print('='*80)
print('ANALYZING BACKTEST: EUR-USD_20251106_193355')
print('='*80)
print()

# Load performance stats
stats = json.load(open(results_dir / 'performance_stats.json'))
print('Performance Stats:')
print(f'  PnL: ${stats["pnls"]["PnL (total)"]:,.2f}')
print(f'  Win Rate: {stats["pnls"]["Win Rate"]:.2%}')
print(f'  Rejected Signals: {stats["rejected_signals_count"]}')
print()

# Load orders to infer parameters
orders_df = pd.read_csv(results_dir / 'orders.csv')
positions_df = pd.read_csv(results_dir / 'positions.csv')

print('Order Analysis:')
print(f'  Total Orders: {len(orders_df)}')
if 'order_type' in orders_df.columns:
    print(f'  Order Types: {orders_df["order_type"].value_counts().to_dict()}')
if 'tags' in orders_df.columns:
    tags = orders_df['tags'].dropna()
    tp_count = tags.str.contains('TP', na=False).sum()
    sl_count = tags.str.contains('SL', na=False).sum()
    print(f'  TP Orders: {tp_count}')
    print(f'  SL Orders: {sl_count}')

print()
print('Position Analysis:')
print(f'  Total Positions: {len(positions_df)}')
# Convert ts_closed to numeric
if 'ts_closed' in positions_df.columns:
    positions_df['ts_closed_num'] = pd.to_numeric(positions_df['ts_closed'], errors='coerce')
    closed_positions = positions_df[positions_df['ts_closed_num'] > 0]
else:
    closed_positions = positions_df
print(f'  Closed Positions: {len(closed_positions)}')

# Try to infer TP/SL from position PnL
if len(closed_positions) > 0 and 'realized_pnl' in closed_positions.columns:
    pnls = closed_positions['realized_pnl'].str.replace(' USD', '').astype(float)
    winners = pnls[pnls > 0]
    losers = pnls[pnls < 0]
    if len(winners) > 0:
        print(f'  Avg Winner: ${winners.mean():.2f}')
        print(f'  Max Winner: ${winners.max():.2f}')
    if len(losers) > 0:
        print(f'  Avg Loser: ${losers.mean():.2f}')
        print(f'  Max Loser: ${losers.min():.2f}')

print()
print('Checking log files for configuration...')
log_file = Path('logs/application.log')
if log_file.exists():
    # Try to find log entries around the backtest time
    target_time = datetime(2025, 11, 6, 19, 33, 55)
    print(f'  Log file exists: {log_file}')
    print(f'  Log file size: {log_file.stat().st_size / 1024:.1f} KB')
    print('  (Log file may contain configuration details)')

print()
print('='*80)
print('INFERRED PARAMETERS (from results data)')
print('='*80)
print('Note: Some parameters cannot be determined from results alone.')
print('Checking git history for .env file at that time...')

