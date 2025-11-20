import pandas as pd

# Load data
results_dir = r"logs\backtest_results\EUR-USD_20251116_171347"
positions = pd.read_csv(f"{results_dir}\\positions.csv")
orders = pd.read_csv(f"{results_dir}\\orders.csv")

# Convert timestamps
positions['ts_opened'] = pd.to_datetime(positions['ts_opened'], unit='ns', utc=True)
positions['ts_closed'] = pd.to_datetime(positions['ts_closed'], unit='ns', utc=True)
positions['duration_hours'] = (positions['ts_closed'] - positions['ts_opened']).dt.total_seconds() / 3600
orders['ts_init'] = pd.to_datetime(orders['ts_init'], unit='ns', utc=True)

# Find a position >= 2h
long_positions = positions[positions['duration_hours'] >= 2.0].copy()
print(f"Found {len(long_positions)} positions >= 2h")

# Pick the FIRST one (row 0)
pos = long_positions.iloc[0]
print(f"\n=== Position #{0} ===")
print(f"Opened: {pos['ts_opened']}")
print(f"Closed: {pos['ts_closed']}")
print(f"Duration: {pos['duration_hours']:.2f}h")
print(f"Side: {pos['side']}")
print(f"Entry: {pos['avg_px_open']}")
print(f"Exit: {pos['avg_px_close']}")
print(f"PnL: {pos['realized_pnl']}")

# Get orders in a tight window around JUST this position
pos_start = pos['ts_opened']
pos_end = pos['ts_closed']
buffer = pd.Timedelta(minutes=1)

orders_for_position = orders[
    (orders['ts_init'] >= pos_start - buffer) &
    (orders['ts_init'] <= pos_end + buffer)
].copy()

print(f"\n=== Orders for this specific position (within 1min of open/close) ===\n")
for _, order in orders_for_position.iterrows():
    print(f"{order['ts_init']} | {order['side']:4s} | {order['type']:12s} | {order['status']:8s} | Price: {order.get('price', 'N/A')} | Trigger: {order.get('trigger_price', 'N/A')}")
    
# Count cancelled vs filled TPs
tp_orders = orders_for_position[orders_for_position['type'] == 'LIMIT']
print(f"\n=== TP Analysis ===")
print(f"Total LIMIT orders: {len(tp_orders)}")
print(f"Cancelled: {len(tp_orders[tp_orders['status'] == 'CANCELED'])}")
print(f"Filled: {len(tp_orders[tp_orders['status'] == 'FILLED'])}")

# Show what closed the position
closing_orders = orders_for_position[
    (orders_for_position['status'] == 'FILLED') &
    ((orders_for_position['side'] == 'BUY') if pos['side'] == 'LONG' else (orders_for_position['side'] == 'SELL'))
]

if len(closing_orders) > 0:
    close_order = closing_orders.iloc[-1]
    print(f"\n=== Position closed by ===")
    print(f"Type: {close_order['type']}")
    print(f"Price: {close_order.get('avg_px', 'N/A')}")
    if close_order['type'] == 'STOP_MARKET':
        print(f"Trigger: {close_order.get('trigger_price', 'N/A')}")
        print("→ STOP LOSS / TRAILING STOP")
    elif close_order['type'] == 'LIMIT':
        print(f"Limit: {close_order.get('price', 'N/A')}")
        print("→ TAKE PROFIT")
