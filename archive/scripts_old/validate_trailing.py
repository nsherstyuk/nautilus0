import pandas as pd
from pathlib import Path
import json

# Find latest
results_dir = Path('logs/backtest_results')
latest = max(results_dir.glob('EUR-USD_*'), key=lambda p: p.stat().st_mtime)
print(f'Latest: {latest.name}\n')

# Performance
with open(latest / 'performance_stats.json') as f:
    perf = json.load(f)

print('PERFORMANCE:')
print(f'  PnL: {perf.get("total_pnl", "N/A")}')
print(f'  Win Rate: {perf.get("win_rate", "N/A")}')
print(f'  Total Trades: {perf.get("total_trades", "N/A")}')
print()

# Orders
orders = pd.read_csv(latest / 'orders.csv')
stop_orders = orders[orders['type'] == 'STOP_MARKET']

print(f'STOP ORDERS: {len(stop_orders)}')
if 'trigger_price' in stop_orders.columns:
    unique_triggers = stop_orders['trigger_price'].nunique()
    positions = len(pd.read_csv(latest / 'positions.csv'))
    ratio = unique_triggers / positions if positions > 0 else 0
    print(f'  Unique trigger prices: {unique_triggers}')
    print(f'  Positions: {positions}')
    print(f'  Ratio: {ratio:.2f} triggers per position')
    print()
    if ratio > 1.2:
        print('✅ TRAILING IS WORKING - Multiple SL modifications per position!')
    else:
        print('⚠️  Ratio suggests limited trailing activity')
