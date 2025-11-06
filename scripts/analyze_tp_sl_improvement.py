"""
Analyze if increasing TP or trailing stop activation would improve PnL.
Examines:
1. How positions closed (TP vs SL vs trailing)
2. Price movement after TP closes - did it continue favorable?
3. Maximum favorable excursion (MFE) vs actual PnL
4. Price trends during periods without EMA crossings
"""
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Phase 6 backtest directory
backtest_dir = Path("logs/backtest_results/EUR-USD_20251024_193923_202202")

print("=" * 100)
print("TP/SL OPTIMIZATION ANALYSIS - PHASE 6")
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

# Determine how each position closed
def get_close_reason(row):
    """Determine if position closed at TP, SL, or trailing stop."""
    closing_order_id = row["closing_order_id"]
    
    # Find closing order by matching closing_order_id with venue_order_id
    closing_order = df_orders[df_orders["venue_order_id"].astype(str).str.contains(closing_order_id.split('-')[-1])]
    
    if len(closing_order) == 0:
        # Try alternative matching
        closing_order = df_orders[df_orders["venue_order_id"].astype(str).str.endswith(closing_order_id.split('-')[-1])]
    
    if len(closing_order) == 0:
        # Check based on pips - if close to TP target, likely TP
        pips = abs(calculate_pips(row))
        if pips >= TP_PIPS - 2:  # Close to TP target
            return "TP_LIKELY"
        elif pips <= SL_PIPS + 2 and row["pnl_value"] < 0:  # Close to SL
            return "SL_LIKELY"
        return "UNKNOWN"
    
    tags = closing_order["tags"].iloc[0]
    if pd.notna(tags):
        if isinstance(tags, str):
            tags = eval(tags) if tags.startswith('[') else [tags]
        elif isinstance(tags, (list, tuple)):
            pass  # Already a list
        else:
            tags = []
    else:
        tags = []
    
    if "MA_CROSS_TP" in tags:
        return "TP"
    elif "MA_CROSS_SL" in tags:
        return "SL"
    else:
        # Fallback to pips-based detection
        pips = abs(calculate_pips(row))
        if pips >= TP_PIPS - 2:
            return "TP_LIKELY"
        elif pips <= SL_PIPS + 2 and row["pnl_value"] < 0:
            return "SL_LIKELY"
        return "OTHER"

df_positions["close_reason"] = df_positions.apply(get_close_reason, axis=1)

print(f"Current Phase 6 Settings:")
print(f"  TP: {TP_PIPS} pips")
print(f"  SL: {SL_PIPS} pips")
print(f"  Trailing Activation: {TRAILING_ACTIVATION_PIPS} pips")
print(f"  Trailing Distance: {TRAILING_DISTANCE_PIPS} pips")
print()

# Analyze close reasons
close_reasons = df_positions["close_reason"].value_counts()
print("Position Close Reasons:")
for reason, count in close_reasons.items():
    pct = 100 * count / len(df_positions)
    avg_pnl = df_positions[df_positions["close_reason"] == reason]["pnl_value"].mean()
    print(f"  {reason}: {count} ({pct:.1f}%) - Avg PnL: ${avg_pnl:.2f}")
print()

# Analyze TP closes
tp_closes = df_positions[df_positions["close_reason"].isin(["TP", "TP_LIKELY"])]
sl_closes = df_positions[df_positions["close_reason"].isin(["SL", "SL_LIKELY"])]

print(f"TP Closes Analysis ({len(tp_closes)} positions):")
if len(tp_closes) > 0:
    print(f"  Average Pips: {tp_closes['pips'].mean():.1f}")
    print(f"  Target TP: {TP_PIPS} pips")
    print(f"  Difference: {tp_closes['pips'].mean() - TP_PIPS:.1f} pips")
    print(f"  Max Pips: {tp_closes['pips'].max():.1f}")
    print(f"  Min Pips: {tp_closes['pips'].min():.1f}")
else:
    print("  No TP closes detected")
print()

print(f"SL Closes Analysis ({len(sl_closes)} positions):")
if len(sl_closes) > 0:
    print(f"  Average Pips: {sl_closes['pips'].mean():.1f}")
    print(f"  Target SL: -{SL_PIPS} pips")
    print(f"  Average PnL: ${sl_closes['pnl_value'].mean():.2f}")
else:
    print("  No SL closes detected")
print()

# Analyze durations
print("Position Duration Analysis:")
winners = df_positions[df_positions["pnl_value"] > 0]
losers = df_positions[df_positions["pnl_value"] < 0]

if len(winners) > 0:
    winner_durations = winners["duration_ns"] / 1e9 / 3600  # Convert to hours
    print(f"Winners ({len(winners)} positions):")
    print(f"  Avg Duration: {winner_durations.mean():.1f} hours")
    print(f"  Max Duration: {winner_durations.max():.1f} hours")
    print(f"  Min Duration: {winner_durations.min():.1f} hours")
    print()

if len(losers) > 0:
    loser_durations = losers["duration_ns"] / 1e9 / 3600
    print(f"Losers ({len(losers)} positions):")
    print(f"  Avg Duration: {loser_durations.mean():.1f} hours")
    print(f"  Max Duration: {loser_durations.max():.1f} hours")
    print(f"  Min Duration: {loser_durations.min():.1f} hours")
    print()

print("=" * 100)
print("RECOMMENDATIONS")
print("=" * 100)
print()

total_trades = len(df_positions)
tp_count = len(tp_closes)
sl_count = len(sl_closes)

print(f"Analysis Summary:")
print(f"  Total Trades: {total_trades}")
print(f"  TP Closes: {tp_count} ({100*tp_count/total_trades:.1f}%)")
print(f"  SL Closes: {sl_count} ({100*sl_count/total_trades:.1f}%)")
print()

# Check if TP closes are at target
if len(tp_closes) > 0:
    tp_at_target = tp_closes[tp_closes["pips"].abs() >= TP_PIPS - 1]  # Allow 1 pip tolerance
    print(f"TP Closes at Target ({TP_PIPS} pips): {len(tp_at_target)}/{len(tp_closes)}")
    print(f"  Average TP Pips: {tp_closes['pips'].mean():.1f}")
    print()
    
    # Positions that closed early
    tp_early = tp_closes[tp_closes["pips"].abs() < TP_PIPS - 5]
    if len(tp_early) > 0:
        print(f"TP Closes EARLY (< {TP_PIPS - 5} pips): {len(tp_early)} positions")
        print(f"  Average Early Close: {tp_early['pips'].abs().mean():.1f} pips")
        print(f"  Potential Additional Pips: {(TP_PIPS - tp_early['pips'].abs().mean()):.1f} pips per trade")
        print()

print("Potential Improvements:")
print(f"1. Increasing TP from {TP_PIPS} to {TP_PIPS + 25} pips:")
print(f"   - Would affect {tp_count} positions that closed at TP")
print(f"   - Need to check if price continued favorable after TP hit")
print()

print(f"2. Increasing Trailing Activation from {TRAILING_ACTIVATION_PIPS} to {TRAILING_ACTIVATION_PIPS + 10} pips:")
print(f"   - Would allow more positions to activate trailing stop")
print(f"   - Could capture more profit in trending moves")
print(f"   - Currently {len(winners)} winners, avg duration {winner_durations.mean():.1f} hours")
print()

print("=" * 100)
print()
print("NOTE: Full analysis requires historical bar data to see:")
print("  - Price movement AFTER TP closes")
print("  - Maximum favorable excursion (MFE) vs actual PnL")
print("  - Whether trends continued during no-crossing periods")
print("  - Whether positions could have captured more profit with higher TP")
print()
