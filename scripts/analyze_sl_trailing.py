"""
Calculate how many trades were stopped by regular SL vs trailing stop.
"""
import sys
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Phase 6 backtest directory
backtest_dir = Path("logs/backtest_results/EUR-USD_20251024_193923_202202")

print("=" * 100)
print("STOP LOSS vs TRAILING STOP ANALYSIS - PHASE 6")
print("=" * 100)
print()

# Current Phase 6 settings
TP_PIPS = 50
SL_PIPS = 35
TRAILING_ACTIVATION_PIPS = 22
TRAILING_DISTANCE_PIPS = 12

# Load data
positions_file = backtest_dir / "positions.csv"
orders_file = backtest_dir / "orders.csv"

if not positions_file.exists() or not orders_file.exists():
    print("Error: Required files not found")
    sys.exit(1)

df_positions = pd.read_csv(positions_file)
df_orders = pd.read_csv(orders_file)

# Parse dates
df_positions["ts_opened"] = pd.to_datetime(df_positions["ts_opened"])
df_positions["ts_closed"] = pd.to_datetime(df_positions["ts_closed"])
df_orders["ts_init"] = pd.to_datetime(df_orders["ts_init"])
df_orders["ts_last"] = pd.to_datetime(df_orders["ts_last"])

# Extract PnL values
def extract_pnl(value):
    if pd.isna(value):
        return 0.0
    value_str = str(value)
    import re
    cleaned = re.sub(r'\s*[A-Z]{3}\s*$', '', value_str)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

df_positions["pnl_value"] = df_positions["realized_pnl"].apply(extract_pnl)

# Calculate entry/exit prices and pips
def calculate_pips(row):
    """Calculate pips difference."""
    entry = float(row["avg_px_open"])
    exit_px = float(row["avg_px_close"])
    
    if row["entry"] == "BUY":
        pips = (exit_px - entry) * 10000
    else:  # SELL
        pips = (entry - exit_px) * 10000
    
    return pips

df_positions["pips"] = df_positions.apply(calculate_pips, axis=1)

# Function to determine if SL was regular or trailing
def get_sl_type(row):
    """Determine if position closed at regular SL or trailing stop."""
    closing_order_id = row["closing_order_id"]
    entry_price = float(row["avg_px_open"])
    exit_price = float(row["avg_px_close"])
    entry_side = row["entry"]
    
    # Find closing order
    closing_order = df_orders[df_orders["venue_order_id"].astype(str).str.contains(closing_order_id.split('-')[-1])]
    
    if len(closing_order) == 0:
        return "UNKNOWN"
    
    closing_order = closing_order.iloc[0]
    
    # Check if it's a stop order
    tags = closing_order["tags"]
    if pd.notna(tags):
        if isinstance(tags, str):
            tags = eval(tags) if tags.startswith('[') else [tags]
        elif isinstance(tags, (list, tuple)):
            pass
        else:
            tags = []
    else:
        tags = []
    
    if "MA_CROSS_SL" not in tags and closing_order["type"] != "STOP_MARKET":
        return "NOT_SL"
    
    # Calculate expected initial SL price
    if entry_side == "BUY":
        expected_sl_price = entry_price - (SL_PIPS / 10000)
    else:  # SELL
        expected_sl_price = entry_price + (SL_PIPS / 10000)
    
    # Get actual trigger price that closed the position
    trigger_price = closing_order.get("trigger_price")
    if pd.isna(trigger_price):
        # Use exit price as approximation
        trigger_price = exit_price
    else:
        trigger_price = float(trigger_price)
    
    # Calculate pips difference from entry
    if entry_side == "BUY":
        actual_sl_pips = (entry_price - trigger_price) * 10000
    else:  # SELL
        actual_sl_pips = (trigger_price - entry_price) * 10000
    
    # Check if stop was updated (trailing stop indicator)
    # If ts_init != ts_last, the order was updated
    was_updated = closing_order["ts_init"] != closing_order["ts_last"]
    
    # Determine if trailing stop
    # Key insight: Trailing stops activate after TRAILING_ACTIVATION_PIPS (22 pips) profit
    # Once activated, trailing stop moves closer to entry as price moves favorably
    # When price reverses, trailing stop closes at LESS than SL_PIPS from entry
    
    # If order was updated (ts_init != ts_last), it's definitely trailing
    if was_updated:
        return "TRAILING_STOP"
    
    # Check if SL pips is LESS than initial SL (meaning trailing moved it favorably)
    # Regular SL would close at exactly ~SL_PIPS (35 pips)
    # Trailing stop would close at less than SL_PIPS because it moved up/down
    
    # If actual SL pips is significantly less than SL_PIPS, it's trailing
    # (Trailing stop moved favorably, so when reversed, it's closer than initial SL)
    if actual_sl_pips < SL_PIPS - 5:  # More than 5 pips difference suggests trailing
        # But also check: if trigger price is BETTER than expected SL, it's trailing
        if entry_side == "BUY":
            # For BUY, trailing stop moves UP (higher trigger price = better)
            # Better = trigger_price > expected_sl_price
            if trigger_price > expected_sl_price + (TRAILING_DISTANCE_PIPS / 20000):  # Half trailing distance
                return "TRAILING_STOP"
        else:  # SELL
            # For SELL, trailing stop moves DOWN (lower trigger price = better)
            # Better = trigger_price < expected_sl_price
            if trigger_price < expected_sl_price - (TRAILING_DISTANCE_PIPS / 20000):
                return "TRAILING_STOP"
    
    # If SL pips is close to initial SL_PIPS, it's regular SL
    if abs(actual_sl_pips - SL_PIPS) <= 2:  # Within 2 pips of expected SL
        return "REGULAR_SL"
    
    # Otherwise, it's regular SL
    return "REGULAR_SL"

# Get positions that closed at SL
def get_close_reason(row):
    """Determine if position closed at TP, SL, or trailing stop."""
    closing_order_id = row["closing_order_id"]
    
    closing_order = df_orders[df_orders["venue_order_id"].astype(str).str.contains(closing_order_id.split('-')[-1])]
    
    if len(closing_order) == 0:
        # Fallback to pips-based detection
        pips = abs(calculate_pips(row))
        if pips >= TP_PIPS - 2:
            return "TP"
        elif pips <= SL_PIPS + 2 and row["pnl_value"] < 0:
            return "SL"
        return "UNKNOWN"
    
    tags = closing_order["tags"].iloc[0]
    if pd.notna(tags):
        if isinstance(tags, str):
            tags = eval(tags) if tags.startswith('[') else [tags]
        elif isinstance(tags, (list, tuple)):
            pass
        else:
            tags = []
    else:
        tags = []
    
    if "MA_CROSS_TP" in tags:
        return "TP"
    elif "MA_CROSS_SL" in tags or closing_order.iloc[0]["type"] == "STOP_MARKET":
        return "SL"
    else:
        pips = abs(calculate_pips(row))
        if pips >= TP_PIPS - 2:
            return "TP"
        elif pips <= SL_PIPS + 2 and row["pnl_value"] < 0:
            return "SL"
        return "OTHER"

df_positions["close_reason"] = df_positions.apply(get_close_reason, axis=1)

# Analyze SL closes
sl_closes = df_positions[df_positions["close_reason"] == "SL"].copy()

if len(sl_closes) == 0:
    print("No positions closed at Stop Loss")
    sys.exit(0)

print(f"Analyzing {len(sl_closes)} positions that closed at Stop Loss...")
print()

# Determine SL type for each
sl_closes["sl_type"] = sl_closes.apply(get_sl_type, axis=1)

# Count by type
sl_counts = sl_closes["sl_type"].value_counts()

print("=" * 100)
print("STOP LOSS BREAKDOWN")
print("=" * 100)
print()

regular_sl_count = sl_counts.get("REGULAR_SL", 0)
trailing_sl_count = sl_counts.get("TRAILING_STOP", 0)
unknown_count = sl_counts.get("UNKNOWN", 0) + sl_counts.get("NOT_SL", 0)

total_sl = len(sl_closes)

print(f"Total SL Closes: {total_sl}")
print()
print(f"Regular Stop Loss: {regular_sl_count} ({100*regular_sl_count/total_sl:.1f}%)")
print(f"Trailing Stop Loss: {trailing_sl_count} ({100*trailing_sl_count/total_sl:.1f}%)")
if unknown_count > 0:
    print(f"Unknown/Other: {unknown_count} ({100*unknown_count/total_sl:.1f}%)")
print()

# Show details
if regular_sl_count > 0:
    regular_sl = sl_closes[sl_closes["sl_type"] == "REGULAR_SL"]
    print(f"Regular SL Details:")
    print(f"  Average PnL: ${regular_sl['pnl_value'].mean():.2f}")
    print(f"  Average Pips: {regular_sl['pips'].mean():.1f}")
    print()

if trailing_sl_count > 0:
    trailing_sl = sl_closes[sl_closes["sl_type"] == "TRAILING_STOP"]
    print(f"Trailing Stop Details:")
    print(f"  Average PnL: ${trailing_sl['pnl_value'].mean():.2f}")
    print(f"  Average Pips: {trailing_sl['pips'].mean():.1f}")
    print()

print("=" * 100)
print("DETAILED SL ANALYSIS")
print("=" * 100)
print()

# Show some examples
print("Sample SL Closes:")
for idx, row in sl_closes.head(10).iterrows():
    entry_price = float(row["avg_px_open"])
    exit_price = float(row["avg_px_close"])
    entry_side = row["entry"]
    sl_type = row["sl_type"]
    
    closing_order_id = row["closing_order_id"]
    closing_order = df_orders[df_orders["venue_order_id"].astype(str).str.contains(closing_order_id.split('-')[-1])]
    
    if len(closing_order) > 0:
        closing_order = closing_order.iloc[0]
        trigger_price = closing_order.get("trigger_price")
        was_updated = closing_order["ts_init"] != closing_order["ts_last"]
        
        if entry_side == "BUY":
            expected_sl = entry_price - (SL_PIPS / 10000)
            sl_pips = (entry_price - exit_price) * 10000
        else:
            expected_sl = entry_price + (SL_PIPS / 10000)
            sl_pips = (exit_price - entry_price) * 10000
        
        print(f"  {entry_side} @ {entry_price:.5f}, Exit: {exit_price:.5f} ({sl_pips:.1f} pips)")
        trigger_str = f"{trigger_price:.5f}" if pd.notna(trigger_price) else "N/A"
        print(f"    Expected SL: {expected_sl:.5f}, Trigger: {trigger_str}")
        print(f"    Order Updated: {was_updated}, Type: {sl_type}")
        print()

