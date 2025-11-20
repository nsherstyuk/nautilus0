"""Check if duration-based trailing is actually being used in the strategy."""
import pandas as pd
from pathlib import Path

# Get latest backtest
results_dir = Path("logs/backtest_results")
latest = sorted(results_dir.glob("EUR-USD_*"), key=lambda x: x.stat().st_mtime, reverse=True)[0]

print(f"Analyzing: {latest.name}")
print("=" * 80)

# Check config
env_file = latest / ".env"
if env_file.exists():
    print("\n📋 CONFIG FROM .env:")
    with open(env_file) as f:
        for line in f:
            if "TRAILING_DURATION" in line:
                print(f"  {line.strip()}")

# Check positions for duration
positions = pd.read_csv(latest / "positions.csv")
print(f"\n📊 POSITIONS ANALYSIS:")
print(f"  Total trades: {len(positions)}")

# Calculate duration for each position
positions['ts_opened'] = pd.to_datetime(positions['ts_opened'])
positions['ts_closed'] = pd.to_datetime(positions['ts_closed'])
positions['duration_hours'] = (positions['ts_closed'] - positions['ts_opened']).dt.total_seconds() / 3600

# Count positions by duration
over_2h = (positions['duration_hours'] >= 2.0).sum()
over_8h = (positions['duration_hours'] >= 8.0).sum()
over_12h = (positions['duration_hours'] >= 12.0).sum()

print(f"  Positions >= 2h:  {over_2h} ({over_2h/len(positions)*100:.1f}%)")
print(f"  Positions >= 8h:  {over_8h} ({over_8h/len(positions)*100:.1f}%)")
print(f"  Positions >= 12h: {over_12h} ({over_12h/len(positions)*100:.1f}%)")

# Check orders for TP cancellations
orders = pd.read_csv(latest / "orders.csv")
print(f"\n📦 ORDER COLUMNS: {orders.columns.tolist()}")

# Find the status column (might be 'status' or 'order_status')
status_col = 'status' if 'status' in orders.columns else 'order_status' if 'order_status' in orders.columns else None
if status_col:
    cancelled_tp = orders[(orders[status_col] == 'CANCELED') & (orders['tags'].str.contains('TP', na=False))]
else:
    cancelled_tp = pd.DataFrame()  # Empty if can't find status column

print(f"\n🚫 CANCELLED TP ORDERS:")
print(f"  Count: {len(cancelled_tp)}")
print(f"  Expected for 2h threshold: ~{over_2h} (all positions >= 2h)")

if len(cancelled_tp) == 0:
    print("\n❌ NO TP ORDERS CANCELLED - FEATURE NOT WORKING!")
    print("   The duration-based trailing code is NOT executing.")
elif len(cancelled_tp) < over_2h * 0.5:
    print(f"\n⚠️  ONLY {len(cancelled_tp)} TPs CANCELLED (expected ~{over_2h})")
    print("   Feature may be partially working or starting late.")
else:
    print(f"\n✅ Feature appears to be working ({len(cancelled_tp)} TPs cancelled)")

# Check PnL
positions['pnl'] = positions['realized_pnl'].str.replace(' USD','').astype(float)
total_pnl = positions['pnl'].sum()

print(f"\n💰 PNL RESULT:")
print(f"  Total: ${total_pnl:.2f}")
print(f"  Expected baseline: $9,517.35")
print(f"  Difference: ${total_pnl - 9517.35:.2f}")

if abs(total_pnl - 9517.35) < 1.0:
    print("\n⚠️  PNL IDENTICAL TO BASELINE!")
    print("   This suggests:")
    print("   1. Feature is not executing at all, OR")
    print("   2. Feature executes but positions close at same prices anyway")
