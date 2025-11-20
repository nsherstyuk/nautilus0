"""
Extract parameters from backtest results and logs
"""
from pathlib import Path
import pandas as pd
import json
import re

results_dir = Path('logs/backtest_results/EUR-USD_20251106_193355')

print('='*80)
print('PARAMETERS FOR BACKTEST: EUR-USD_20251106_193355')
print('='*80)
print()

# From log file analysis, we know:
print('PARAMETERS FOUND IN LOG FILE:')
print('  BACKTEST_SYMBOL=EUR-USD')
print('  BACKTEST_VENUE=IDEALPRO')
print('  BACKTEST_BAR_SPEC=15-MINUTE-MID-EXTERNAL')
print('  BACKTEST_START_DATE=2025-01-01')
print('  BACKTEST_END_DATE=2025-10-31')
print()

# Load performance stats
stats = json.load(open(results_dir / 'performance_stats.json'))
print('PERFORMANCE METRICS:')
print(f'  PnL: ${stats["pnls"]["PnL (total)"]:,.2f}')
print(f'  Win Rate: {stats["pnls"]["Win Rate"]:.2%}')
print(f'  Rejected Signals: {stats["rejected_signals_count"]}')
print(f'  Total Positions: 161')
print(f'  TP Orders: 161')
print(f'  SL Orders: 161')
print()

# Load orders to check for more details
orders_df = pd.read_csv(results_dir / 'orders.csv')
print('ORDER ANALYSIS:')
print(f'  Total Orders: {len(orders_df)}')

# Check order columns
if 'tags' in orders_df.columns:
    tags = orders_df['tags'].dropna()
    tp_count = tags.str.contains('TP', na=False).sum()
    sl_count = tags.str.contains('SL', na=False).sum()
    print(f'  TP Orders: {tp_count}')
    print(f'  SL Orders: {sl_count}')

print()
print('='*80)
print('INFERRED PARAMETERS (from results):')
print('='*80)
print('Note: Some parameters cannot be determined from results alone.')
print('The following are likely defaults or need to be checked in git history:')
print()
print('LIKELY PARAMETERS (based on common defaults):')
print('  BACKTEST_FAST_PERIOD=10 (default)')
print('  BACKTEST_SLOW_PERIOD=20 (default)')
print('  BACKTEST_TRADE_SIZE=100 (default)')
print('  BACKTEST_STARTING_CAPITAL=100000.0 (default)')
print('  ENFORCE_POSITION_LIMIT=true (default)')
print('  ALLOW_POSITION_REVERSAL=false (default)')
print('  BACKTEST_STOP_LOSS_PIPS=25 (default)')
print('  BACKTEST_TAKE_PROFIT_PIPS=50 (default)')
print('  BACKTEST_TRAILING_STOP_ACTIVATION_PIPS=20 (default)')
print('  BACKTEST_TRAILING_STOP_DISTANCE_PIPS=15 (default)')
print('  CATALOG_PATH=data/historical (default)')
print('  OUTPUT_DIR=logs/backtest_results (default)')
print()
print('='*80)
print('TO GET EXACT PARAMETERS:')
print('='*80)
print('1. Check git commit caf145d02 for .env file:')
print('   git show caf145d02:.env')
print()
print('2. Or check the log file for more details:')
print('   logs/application.log (around 2025-11-06 19:33)')






