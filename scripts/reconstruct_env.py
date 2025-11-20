"""
Create a .env file reconstruction for backtest EUR-USD_20251106_193355
"""
from pathlib import Path
import pandas as pd

results_dir = Path('logs/backtest_results/EUR-USD_20251106_193355')

print('='*80)
print('RECONSTRUCTED PARAMETERS FOR: EUR-USD_20251106_193355')
print('='*80)
print()

# Parameters confirmed from log file
confirmed = {
    'BACKTEST_SYMBOL': 'EUR-USD',
    'BACKTEST_VENUE': 'IDEALPRO',
    'BACKTEST_BAR_SPEC': '15-MINUTE-MID-EXTERNAL',
    'BACKTEST_START_DATE': '2025-01-01',
    'BACKTEST_END_DATE': '2025-10-31',
}

# Analyze orders to infer trade size and TP/SL
orders_df = pd.read_csv(results_dir / 'orders.csv')
market_orders = orders_df[orders_df['type'] == 'MARKET']
if len(market_orders) > 0:
    # Get trade size from MARKET orders (entry orders)
    trade_size = int(market_orders.iloc[0]['quantity'])
    confirmed['BACKTEST_TRADE_SIZE'] = str(int(trade_size / 1000))  # Convert to lots (100000 = 100 lots)

# Analyze TP/SL from orders
tp_orders = orders_df[orders_df['tags'].str.contains('TP', na=False)]
sl_orders = orders_df[orders_df['tags'].str.contains('SL', na=False)]

if len(tp_orders) > 0 and len(sl_orders) > 0:
    # Get a sample position with TP/SL
    sample_tp = tp_orders.iloc[0]
    sample_sl = sl_orders.iloc[0]
    
    # Find corresponding entry order
    if 'parent_order_id' in sample_tp and pd.notna(sample_tp['parent_order_id']):
        parent_id = sample_tp['parent_order_id']
        entry_order = orders_df[orders_df['init_id'] == parent_id]
        if len(entry_order) == 0:
            # Try finding by order_list_id
            order_list_id = sample_tp.get('order_list_id', '')
            entry_order = orders_df[orders_df['order_list_id'] == order_list_id]
        
        if len(entry_order) > 0:
            entry = entry_order.iloc[0]
            entry_price = entry['avg_px']
            tp_price = sample_tp['price']
            sl_trigger = sample_sl['trigger_price']
            
            if pd.notna(entry_price) and pd.notna(tp_price) and pd.notna(sl_trigger):
                if entry['side'] == 'SELL':
                    # For SELL: TP is below entry, SL is above entry
                    tp_pips = (entry_price - tp_price) * 10000
                    sl_pips = (sl_trigger - entry_price) * 10000
                else:  # BUY
                    # For BUY: TP is above entry, SL is below entry
                    tp_pips = (tp_price - entry_price) * 10000
                    sl_pips = (entry_price - sl_trigger) * 10000
                
                confirmed['BACKTEST_TAKE_PROFIT_PIPS'] = str(int(round(tp_pips)))
                confirmed['BACKTEST_STOP_LOSS_PIPS'] = str(int(round(sl_pips)))

# Default parameters (likely used)
defaults = {
    'BACKTEST_FAST_PERIOD': '10',
    'BACKTEST_SLOW_PERIOD': '20',
    'BACKTEST_STARTING_CAPITAL': '100000.0',
    'ENFORCE_POSITION_LIMIT': 'true',
    'ALLOW_POSITION_REVERSAL': 'false',
    'BACKTEST_TRAILING_STOP_ACTIVATION_PIPS': '20',
    'BACKTEST_TRAILING_STOP_DISTANCE_PIPS': '15',
    'CATALOG_PATH': 'data/historical',
    'OUTPUT_DIR': 'logs/backtest_results',
}

print('CONFIRMED PARAMETERS (from log file and order analysis):')
for key, value in confirmed.items():
    print(f'  {key}={value}')

print()
print('LIKELY PARAMETERS (defaults - not confirmed):')
for key, value in defaults.items():
    print(f'  {key}={value}')

print()
print('='*80)
print('RECONSTRUCTED .env FILE:')
print('='*80)
print()

# Create .env format
all_params = {**confirmed, **defaults}
for key, value in sorted(all_params.items()):
    print(f'{key}={value}')

print()
print('='*80)
print('NOTE:')
print('='*80)
print('Some parameters (like FAST_PERIOD, SLOW_PERIOD) are inferred from defaults.')
print('To get exact values, you would need:')
print('1. The original .env file (if it was saved elsewhere)')
print('2. Or check if there are more detailed logs')
print('3. Or re-run with these parameters and compare results')






