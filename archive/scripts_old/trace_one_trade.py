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

# Find a position >= 2h that had TP cancelled
long_positions = positions[positions['duration_hours'] >= 2.0].copy()
print(f"\n=== Found {len(long_positions)} positions >= 2h ===\n")

# Pick the first one
pos = long_positions.iloc[0]
print(f"Opening Order ID: {pos['opening_order_id']}")
print(f"Closing Order ID: {pos['closing_order_id']}")
print(f"Side: {pos['side']}")
print(f"Opened: {pos['ts_opened']}")
print(f"Closed: {pos['ts_closed']}")
print(f"Duration: {pos['duration_hours']:.2f} hours")
print(f"Realized PnL: {pos['realized_pnl']}")
print(f"Avg Open: {pos['avg_px_open']}")
print(f"Avg Close: {pos['avg_px_close']}")

# Find orders around this position's timeframe
pos_start_ns = positions.iloc[0]['ts_opened'].value  # First position's open time
pos_end_ns = positions.iloc[0]['ts_closed'].value
time_window = pd.Timedelta(minutes=5).value  # 5 min buffer

# Get orders in timeframe (ts_init is already tz-aware)
orders_in_range = orders[
    (orders['ts_init'].astype('int64') >= pos_start_ns - time_window) &
    (orders['ts_init'].astype('int64') <= pos_end_ns + time_window)
].copy()

print(f"\n=== {len(orders_in_range)} Orders in timeframe ===\n")

# Group by position_id to find which group matches
if len(orders_in_range) > 0:
    # Use the first unique position_id
    position_ids = orders_in_range['position_id'].unique()
    print(f"Found {len(position_ids)} position(s) in timeframe")
    position_id = position_ids[0]
    print(f"Using position_id: {position_id}\n")
    
    pos_orders = orders[orders['position_id'] == position_id].copy()
    pos_orders = pos_orders.sort_values('ts_init')
else:
    print("ERROR: No orders found in timeframe!")
    exit(1)

print(f"\n=== {len(pos_orders)} Orders for this position ===\n")

for _, order in pos_orders.iterrows():
    status_str = f"{order['status']}"
    if order['status'] == 'CANCELED':
        status_str = f"**{status_str}**"  # Highlight cancelled
    
    print(f"{order['ts_init']}")
    print(f"  Order ID: {order['init_id']}")
    print(f"  Side: {order['side']}")
    print(f"  Type: {order['type']}")
    print(f"  Status: {status_str}")
    print(f"  Price: {order.get('price', 'MARKET')}")
    if pd.notna(order.get('trigger_price')):
        print(f"  Trigger: {order['trigger_price']}")
    if pd.notna(order.get('filled_qty')):
        print(f"  Filled: {order['filled_qty']}")
    print()

# Check if TP was cancelled
tp_orders = pos_orders[pos_orders['type'] == 'LIMIT']
cancelled_tp = tp_orders[tp_orders['status'] == 'CANCELED']

print(f"\n=== Analysis ===")
print(f"TP orders: {len(tp_orders)}")
print(f"Cancelled TPs: {len(cancelled_tp)}")

if len(cancelled_tp) > 0:
    print("✓ TP WAS CANCELLED (duration trailing should have activated)")
else:
    print("✗ TP was NOT cancelled (duration trailing did not activate)")

# Find the final closing order
filled_orders = pos_orders[pos_orders['status'] == 'FILLED']
if pos['side'] == 'LONG':
    closing_orders = filled_orders[filled_orders['side'] == 'SELL']
else:
    closing_orders = filled_orders[filled_orders['side'] == 'BUY']

if len(closing_orders) > 0:
    final_order = closing_orders.iloc[-1]
    print(f"\nPosition closed by: {final_order['type']}")
    if final_order['type'] == 'STOP_MARKET':
        print(f"  Trigger price: {final_order['trigger_price']}")
        print(f"  Avg fill: {final_order['avg_px']}")
        print("  → Closed by trailing stop!")
    elif final_order['type'] == 'LIMIT':
        print(f"  Limit price: {final_order['price']}")
        print(f"  Avg fill: {final_order['avg_px']}")
        print("  → Closed by take profit!")
else:
    print("\nCouldn't find closing order (data issue?)")

