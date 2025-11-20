import pandas as pd
from pathlib import Path

results_dir = Path("logs/backtest_results")

# Find latest results folder
folders = sorted([f for f in results_dir.iterdir() if f.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
if not folders:
    print("[ERROR] No backtest results found")
else:
    latest = folders[0]
    orders_file = latest / "orders.csv"
    print(f"[INFO] Latest folder: {latest.name}")

    if orders_file.exists():
        orders = pd.read_csv(orders_file)
        print(f"Columns: {list(orders.columns)}")
        print(f"Total orders: {len(orders)}")

        # Identify stop orders
        stops = orders[orders['type'].astype(str).str.contains('STOP', case=False, na=False)]

        # Prefer SL-tagged stops if tags column present
        if 'tags' in stops.columns:
            has_sl = stops['tags'].astype(str).str.contains('SL', case=False, na=False)
            stops = stops[has_sl]

        print(f"Total stop orders (SL-filtered when possible): {len(stops)}")

        # Group by parent_order_id (entry) to detect multiple stop replacements per entry
        if 'parent_order_id' in stops.columns:
            by_parent = stops.groupby('parent_order_id').size().sort_values(ascending=False)
            multi = (by_parent > 1).sum()
            print(f"Entries with multiple stop orders: {multi}")
            if len(by_parent) > 0:
                print("Top entries by stop count:")
                print(by_parent.head(10).to_string())
        else:
            print("[WARN] 'parent_order_id' column not found; cannot attribute stops to entries reliably")

        # Fallback: group by order_list_id if available
        if 'order_list_id' in stops.columns:
            by_list = stops.groupby('order_list_id').size().sort_values(ascending=False)
            multi_list = (by_list > 1).sum()
            print(f"Order lists with multiple stop orders: {multi_list}")
            if len(by_list) > 0:
                print("Top order lists by stop count:")
                print(by_list.head(10).to_string())
    else:
        print(f"[ERROR] Orders file not found: {orders_file}")
