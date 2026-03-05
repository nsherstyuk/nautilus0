"""
Verify that 1-minute bars were used for execution in the backtest.
Analyzes fill timestamps to confirm minute-level granularity.
"""
import pandas as pd
from pathlib import Path

# Get latest backtest
backtest_dirs = sorted(
    [d for d in Path('backtest_results').iterdir() if d.is_dir() and d.name.startswith('MTF_V2_REPLAY')],
    key=lambda x: x.stat().st_mtime,
    reverse=True
)

latest = backtest_dirs[0]
print(f"Analyzing: {latest.name}")
print("=" * 80)

# Load fills
fills = pd.read_csv(latest / 'fills.csv')
fills['ts_event'] = pd.to_datetime(fills['ts_event'])

# Extract time components
fills['hour'] = fills['ts_event'].dt.hour
fills['minute'] = fills['ts_event'].dt.minute
fills['second'] = fills['ts_event'].dt.second

print("\n1. TIMESTAMP GRANULARITY ANALYSIS")
print("-" * 80)
print(f"Total fills: {len(fills)}")
print(f"Unique minutes: {fills['minute'].nunique()} (out of 60 possible)")
print(f"Unique seconds: {fills['second'].nunique()} (should be 1 if minute-level)")
print(f"All seconds are 0: {(fills['second'] == 0).all()}")

# Check if fills happen at non-15-minute intervals
fills['minute_mod_15'] = fills['minute'] % 15
non_15min_fills = fills[fills['minute_mod_15'] != 0]

print("\n2. NON-15-MINUTE FILLS (Proof of 1-minute execution)")
print("-" * 80)
print(f"Fills at 15-minute marks (0, 15, 30, 45): {len(fills) - len(non_15min_fills)}")
print(f"Fills at OTHER minutes (1-14, 16-29, etc): {len(non_15min_fills)}")
print(f"Percentage of fills using 1-minute granularity: {len(non_15min_fills) / len(fills) * 100:.1f}%")

if len(non_15min_fills) > 0:
    print("\nSample fills at non-15-minute marks:")
    sample = non_15min_fills[['ts_event', 'order_type', 'last_px']].head(10)
    print(sample.to_string(index=False))
    
    print("\nMinute distribution of non-15-minute fills:")
    minute_counts = non_15min_fills['minute'].value_counts().sort_index()
    print(minute_counts.head(20))

# Analyze order types
print("\n3. FILL DISTRIBUTION BY ORDER TYPE")
print("-" * 80)
order_type_analysis = fills.groupby('order_type').agg({
    'client_order_id': 'count',
    'minute_mod_15': lambda x: (x != 0).sum()
}).rename(columns={'client_order_id': 'total_fills', 'minute_mod_15': 'non_15min_fills'})
order_type_analysis['pct_non_15min'] = (
    order_type_analysis['non_15min_fills'] / order_type_analysis['total_fills'] * 100
)
print(order_type_analysis)

print("\n4. EXAMPLE: STOP LOSS FILLS (Most likely to use 1-minute bars)")
print("-" * 80)
stop_fills = fills[fills['order_type'] == 'STOP_MARKET'].copy()
if len(stop_fills) > 0:
    stop_fills_non_15 = stop_fills[stop_fills['minute_mod_15'] != 0]
    print(f"Total SL fills: {len(stop_fills)}")
    print(f"SL fills at non-15-min marks: {len(stop_fills_non_15)} ({len(stop_fills_non_15)/len(stop_fills)*100:.1f}%)")
    print("\nSample SL fills showing minute-level execution:")
    print(stop_fills_non_15[['ts_event', 'last_px']].head(10).to_string(index=False))

print("\n5. CONCLUSION")
print("=" * 80)
if len(non_15min_fills) > 0:
    print("SUCCESS: 1-minute bars ARE being used for execution!")
    print(f"Evidence: {len(non_15min_fills)} fills occurred at non-15-minute timestamps.")
    print("This proves the matching engine is processing 1-minute bars.")
else:
    print("WARNING: All fills are at 15-minute marks.")
    print("This suggests 1-minute bars may not be working as expected.")
