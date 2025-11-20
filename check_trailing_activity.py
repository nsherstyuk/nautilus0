import pandas as pd
from pathlib import Path

# Find latest backtest
results_dir = Path("logs/backtest_results")
latest = max(results_dir.glob("EUR-USD_*"), key=lambda p: p.stat().st_mtime)
print(f"Analyzing: {latest.name}\n")

# Load orders
orders = pd.read_csv(latest / "orders.csv")

# Check STOP_MARKET orders
stop_orders = orders[orders['type'] == 'STOP_MARKET']
print(f"Total STOP_MARKET orders: {len(stop_orders)}")
print(f"  - FILLED: {len(stop_orders[stop_orders['status'] == 'FILLED'])}")
print(f"  - CANCELED: {len(stop_orders[stop_orders['status'] == 'CANCELED'])}")
print(f"  - Other: {len(stop_orders[~stop_orders['status'].isin(['FILLED', 'CANCELED'])])}")

# Group by position to see if any position had multiple stop orders (sign of modifications)
stop_by_position = stop_orders.groupby('position_id').size()
positions_with_multiple_stops = stop_by_position[stop_by_position > 1]

print(f"\nPositions with multiple STOP orders (trailing would create this):")
print(f"  Count: {len(positions_with_multiple_stops)}")

if len(positions_with_multiple_stops) > 0:
    print(f"  Example - Position had {positions_with_multiple_stops.iloc[0]} stop orders")
    print("\n✓ TRAILING STOPS WERE ACTIVE")
else:
    print("\n✗ NO TRAILING STOPS - Each position has exactly 1 stop order")
    print("  This means _manage_trailing_stops() was NEVER called!")
