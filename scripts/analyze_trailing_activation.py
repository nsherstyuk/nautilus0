"""
Comprehensive analysis of trailing stop behavior:
1. Verify trailing activates ONLY after reaching threshold
2. Understand how trailing stops can cause losses
3. Check if trailing stop logic is working correctly
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
print("TRAILING STOP COMPREHENSIVE ANALYSIS")
print("=" * 100)
print()

# Current Phase 6 settings
TP_PIPS = 50
SL_PIPS = 35
TRAILING_ACTIVATION_PIPS = 22
TRAILING_DISTANCE_PIPS = 12

print(f"Configuration:")
print(f"  Initial Stop Loss: {SL_PIPS} pips")
print(f"  Trailing Activation Threshold: {TRAILING_ACTIVATION_PIPS} pips profit")
print(f"  Trailing Distance: {TRAILING_DISTANCE_PIPS} pips")
print()
print(f"Expected Behavior:")
print(f"  - Trailing activates ONLY after +{TRAILING_ACTIVATION_PIPS} pips profit")
print(f"  - Once activated, trailing stop follows price by {TRAILING_DISTANCE_PIPS} pips")
print(f"  - Minimum profit if trailing activated: +{TRAILING_ACTIVATION_PIPS - TRAILING_DISTANCE_PIPS} pips")
print()

# Load data
positions_file = backtest_dir / "positions.csv"
orders_file = backtest_dir / "orders.csv"

df_positions = pd.read_csv(positions_file)
df_orders = pd.read_csv(orders_file)

df_positions["ts_opened"] = pd.to_datetime(df_positions["ts_opened"])
df_positions["ts_closed"] = pd.to_datetime(df_positions["ts_closed"])
df_orders["ts_init"] = pd.to_datetime(df_orders["ts_init"])
df_orders["ts_last"] = pd.to_datetime(df_orders["ts_last"])

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

def calculate_pips(row):
    entry = float(row["avg_px_open"])
    exit_px = float(row["avg_px_close"])
    if row["entry"] == "BUY":
        pips = (exit_px - entry) * 10000
    else:
        pips = (entry - exit_px) * 10000
    return pips

df_positions["pips"] = df_positions.apply(calculate_pips, axis=1)

# Find SL closes
def get_close_reason(row):
    closing_order_id = row["closing_order_id"]
    closing_order = df_orders[df_orders["venue_order_id"].astype(str).str.contains(closing_order_id.split('-')[-1])]
    if len(closing_order) == 0:
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
sl_closes = df_positions[df_positions["close_reason"] == "SL"].copy()

print("=" * 100)
print("TRAILING STOP ACTIVATION VERIFICATION")
print("=" * 100)
print()

print("Key Question: Does trailing activate immediately or only after threshold?")
print()
print("From code analysis:")
print("  Line 929-932: `if profit_pips >= activation_threshold and not self._trailing_active:`")
print(f"  -> Trailing activates ONLY when profit >= {TRAILING_ACTIVATION_PIPS} pips")
print()
print("  Line 935: `if self._trailing_active:`")
print("  -> Trailing stop updates ONLY if already activated")
print()
print("CONCLUSION: Trailing does NOT activate immediately - only after threshold!")
print()

print("=" * 100)
print("CAN TRAILING STOP CAUSE LOSSES AFTER ACTIVATION?")
print("=" * 100)
print()

print("Theoretical Scenario:")
print(f"  1. Entry at price X")
print(f"  2. Price moves to X + {TRAILING_ACTIVATION_PIPS} pips -> Trailing activates")
print(f"  3. Trailing stop moves to X + ({TRAILING_ACTIVATION_PIPS} - {TRAILING_DISTANCE_PIPS}) = X + {TRAILING_ACTIVATION_PIPS - TRAILING_DISTANCE_PIPS} pips")
print(f"  4. Price continues to X + 50 pips")
print(f"  5. Trailing stop follows to X + (50 - {TRAILING_DISTANCE_PIPS}) = X + {50 - TRAILING_DISTANCE_PIPS} pips")
print(f"  6. Price reverses to X + {50 - TRAILING_DISTANCE_PIPS} pips")
print(f"  7. Trailing stop hit at X + {50 - TRAILING_DISTANCE_PIPS} pips = +{50 - TRAILING_DISTANCE_PIPS} pips PROFIT")
print()
print("So trailing stop should LOCK IN profit, not cause losses!")
print()
print("HOWEVER, if price reverses MORE than trailing can follow:")
print(f"  - Price moves to X + {TRAILING_ACTIVATION_PIPS} pips (trailing activates)")
print(f"  - Trailing stop at X + {TRAILING_ACTIVATION_PIPS - TRAILING_DISTANCE_PIPS} pips")
print(f"  - Price gaps DOWN to X - 10 pips (gap = {TRAILING_ACTIVATION_PIPS + TRAILING_DISTANCE_PIPS + 10} pips)")
print(f"  - Trailing stop hit at X + {TRAILING_ACTIVATION_PIPS - TRAILING_DISTANCE_PIPS} pips")
print(f"  - Result: +{TRAILING_ACTIVATION_PIPS - TRAILING_DISTANCE_PIPS} pips (still profit!)")
print()
print("CONCLUSION: Trailing stop should NEVER cause losses after activation!")
print("             It should lock in at least +10 pips profit.")
print()

print("=" * 100)
print("WHAT THE DATA SHOWS")
print("=" * 100)
print()

print(f"Analyzing {len(sl_closes)} SL closes:")
print()

# Check if trailing activated for each SL close
trailing_activated_count = 0
trailing_never_activated_count = 0
unclear_count = 0

for idx, row in sl_closes.iterrows():
    entry_price = float(row["avg_px_open"])
    exit_price = float(row["avg_px_close"])
    entry_side = row["entry"]
    pips = row["pips"]
    
    closing_order_id = row["closing_order_id"]
    closing_order = df_orders[df_orders["venue_order_id"].astype(str).str.contains(closing_order_id.split('-')[-1])]
    
    if len(closing_order) == 0:
        unclear_count += 1
        continue
    
    closing_order = closing_order.iloc[0]
    trigger_price = closing_order.get("trigger_price")
    was_updated = closing_order["ts_init"] != closing_order["ts_last"]
    
    # Calculate expected prices
    if entry_side == "BUY":
        initial_sl_price = entry_price - (SL_PIPS / 10000)
        # If trailing activated and moved favorably, stop would be ABOVE entry
        trailing_stop_price_if_activated = entry_price + ((TRAILING_ACTIVATION_PIPS - TRAILING_DISTANCE_PIPS) / 10000)
    else:  # SELL
        initial_sl_price = entry_price + (SL_PIPS / 10000)
        trailing_stop_price_if_activated = entry_price - ((TRAILING_ACTIVATION_PIPS - TRAILING_DISTANCE_PIPS) / 10000)
    
    # If exit price matches initial SL, trailing never activated
    # If exit price is better than initial SL, trailing activated
    if pd.notna(trigger_price):
        trigger_price = float(trigger_price)
        if entry_side == "BUY":
            # Trailing activated if trigger > entry (or at least > initial_sl)
            if trigger_price > entry_price:
                trailing_activated_count += 1
            elif abs(trigger_price - initial_sl_price) < 0.0001:  # Within 1 pip
                trailing_never_activated_count += 1
            else:
                unclear_count += 1
        else:  # SELL
            if trigger_price < entry_price:
                trailing_activated_count += 1
            elif abs(trigger_price - initial_sl_price) < 0.0001:
                trailing_never_activated_count += 1
            else:
                unclear_count += 1
    else:
        unclear_count += 1

print(f"SL Close Classification:")
print(f"  Trailing Activated (trigger price better than entry): {trailing_activated_count}")
print(f"  Trailing Never Activated (trigger = initial SL): {trailing_never_activated_count}")
print(f"  Unclear: {unclear_count}")
print()

print("=" * 100)
print("EXPLANATION")
print("=" * 100)
print()

print("Why orders show 'updated' but trigger prices match initial SL:")
print()
print("Possible reasons:")
print("  1. Order updates happen even when trailing isn't activated (system checks)")
print("  2. Trailing activated but price reversed immediately before trailing moved")
print("  3. Trailing stop logic checks position every bar but doesn't update if not activated")
print()
print("From code (line 935): Trailing updates ONLY if `self._trailing_active` is True")
print("So if orders were updated, trailing WAS activated at some point.")
print()
print("BUT: If trailing activated and price reversed immediately, trailing stop")
print("     might not have moved much before reversal.")
print()

print("=" * 100)
print("FINAL ANSWER")
print("=" * 100)
print()

print("Question 1: Does trailing activate immediately or only after threshold?")
print(f"ANSWER: Only AFTER reaching {TRAILING_ACTIVATION_PIPS} pips profit")
print()
print("Question 2: Can trailing stop cause losses after activation?")
print("ANSWER: NO - Trailing stop should lock in at least +10 pips profit")
print("         after activation. If it causes losses, something is wrong.")
print()
print("Question 3: Why do SL closes show -35 pips if trailing activated?")
print("ANSWER: Trailing likely NEVER activated for these positions.")
print("         Price went straight to initial SL without reaching +22 pips profit.")
print("         Order updates may be from system checks, not trailing movement.")
print()
