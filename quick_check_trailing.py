"""Quick check: Did the trailing stop fix work?"""

import pandas as pd
import sys

# Latest results directory
RESULTS_DIR = r"logs\backtest_results\EUR-USD_20251116_183839"

print("\n" + "="*70)
print("TRAILING STOP FIX VERIFICATION")
print("="*70)

# Load data
try:
    positions = pd.read_csv(f"{RESULTS_DIR}/positions.csv")
    orders = pd.read_csv(f"{RESULTS_DIR}/orders.csv")
    stats = pd.read_csv(f"{RESULTS_DIR}/account.csv")
    
    # Get PnL from positions - handle USD suffix
    positions['pnl_clean'] = positions['realized_pnl'].astype(str).str.replace(' USD', '').astype(float)
    final_pnl = positions['pnl_clean'].sum()
except Exception as e:
    print(f"❌ Error loading data: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"\n📊 BACKTEST RESULTS (Jan 2024 - Oct 2025)")
print(f"─"*70)
print(f"Final PnL: ${final_pnl:,.2f}")
print(f"Total positions: {len(positions)}")

# Analyze stop orders
stop_orders = orders[orders['order_type'] == 'STOP_MARKET'].copy()
filled_stops = stop_orders[stop_orders['status'] == 'FILLED']
cancelled_stops = stop_orders[stop_orders['status'] == 'CANCELED']

print(f"\n📋 STOP ORDER ANALYSIS")
print(f"─"*70)
print(f"Total STOP_MARKET orders: {len(stop_orders)}")
print(f"  - FILLED: {len(filled_stops)}")
print(f"  - CANCELED: {len(cancelled_stops)}")

# Check if trailing happened
# If trailing works, we should see:
# 1. Multiple stop orders per position
# 2. Cancelled stops (old ones being replaced)
if 'position_id' in stop_orders.columns and len(stop_orders) > 0:
    # Count stops per position
    stops_per_position = stop_orders.groupby('position_id').size()
    
    positions_with_multiple_stops = (stops_per_position > 1).sum()
    max_stops = stops_per_position.max() if len(stops_per_position) > 0 else 0
    avg_stops = stops_per_position.mean() if len(stops_per_position) > 0 else 0
    
    print(f"\n🔍 TRAILING EVIDENCE")
    print(f"─"*70)
    print(f"Positions with multiple stops: {positions_with_multiple_stops} / {len(positions)}")
    print(f"Average stops per position: {avg_stops:.2f}")
    print(f"Max stops for one position: {max_stops}")
    
    if positions_with_multiple_stops > 0:
        print(f"\n✅ TRAILING STOPS ARE WORKING!")
        print(f"   {positions_with_multiple_stops} positions had their stops modified")
        
        # Show a sample position with trailing
        sample_pos = stops_per_position[stops_per_position > 1].index[0]
        sample_stops = stop_orders[stop_orders['position_id'] == sample_pos].sort_values('ts_init')
        print(f"\n   Example position {sample_pos}:")
        for idx, row in sample_stops.iterrows():
            print(f"      {row['ts_init']}: {row['status']} order @ {row['price']}")
    else:
        print(f"\n⚠️  NO EVIDENCE OF TRAILING")
        print(f"   Every position still has exactly 1 stop order")
        print(f"   (This is the same as the broken version)")
else:
    print("\n⚠️  Cannot analyze stops per position (missing position_id column)")

# Compare with baseline
BASELINE_PNL = 9517.35  # From broken trailing version (full period)
print(f"\n📈 COMPARISON WITH BROKEN VERSION")
print(f"─"*70)
print(f"This backtest (with fix):  ${final_pnl:,.2f}")
print(f"Broken trailing baseline:  ${BASELINE_PNL:,.2f}")
print(f"Difference:                ${final_pnl - BASELINE_PNL:,.2f}")

if abs(final_pnl - BASELINE_PNL) < 100:
    print(f"\n⚠️  WARNING: PnL is nearly identical to broken version!")
    print(f"   This suggests trailing may still not be working.")
else:
    print(f"\n✓ PnL is different - parameters are having an effect")

print("\n" + "="*70)
