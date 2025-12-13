#!/usr/bin/env python3
"""
Analyze trailing stop behavior from the latest backtest results.
Check for multiple STOP orders per position as evidence of trailing modifications.
"""

import pandas as pd
from pathlib import Path

def analyze_trailing_stops():
    # Find latest backtest result folder
    results_dir = Path('logs/backtest_results')
    latest_folder = max(results_dir.glob('EUR-USD_*'), key=lambda x: x.stat().st_mtime)
    print(f"Analyzing: {latest_folder}")
    
    # Load data
    orders = pd.read_csv(latest_folder / 'orders.csv')
    positions = pd.read_csv(latest_folder / 'positions.csv')
    
    print(f"\nOrders CSV columns: {list(orders.columns)}")
    print(f"Positions CSV columns: {list(positions.columns)}")
    
    # Analyze STOP orders
    stop_mask = orders['type'].str.contains('STOP', case=False, na=False)
    stop_orders = orders[stop_mask]
    
    print(f"\nTotal orders: {len(orders)}")
    print(f"Total STOP-like orders: {len(stop_orders)}")
    print(f"Total positions: {len(positions)}")
    print(f"Unique positions with STOP orders: {stop_orders['position_id'].nunique()}")
    
    # Count STOP orders per position - use any available ID column
    id_col = 'venue_order_id' if 'venue_order_id' in stop_orders.columns else 'init_id'
    stops_per_position = stop_orders.groupby('position_id')[id_col].count().sort_values(ascending=False)
    print(f"\nSTOP orders per position (top 10):")
    print(stops_per_position.head(10))
    
    # Check if any position has multiple STOP orders (evidence of trailing)
    multiple_stops = stops_per_position[stops_per_position > 1]
    print(f"\nPositions with multiple STOP orders (trailing evidence): {len(multiple_stops)}")
    if len(multiple_stops) > 0:
        print(f"Max STOP orders for a single position: {stops_per_position.max()}")
        
        # Analyze a sample position with multiple stops
        sample_pos = stops_per_position.index[0]
        print(f"\nAnalyzing sample position: {sample_pos}")
        
        # Show position info - check if position_id column exists in positions
        if 'position_id' in positions.columns:
            pos_info = positions[positions['position_id'] == sample_pos]
        else:
            # Use different position identifier
            pos_info = positions  # Show all if we can't filter
        print(f"Position info:")
        pos_cols = ['entry', 'side', 'quantity', 'avg_px_open', 'avg_px_close', 'realized_pnl']
        available_pos_cols = [col for col in pos_cols if col in positions.columns]
        print(pos_info[available_pos_cols].head(3))
        
        # Show all STOP orders for this position
        sample_stops = stop_orders[stop_orders['position_id'] == sample_pos]
        
        # Select relevant columns for analysis
        relevant_cols = []
        for col in orders.columns:
            if any(keyword in col.lower() for keyword in ['venue_order_id', 'init_id', 'position_id', 'status', 'type', 'trigger', 'ts_event', 'price']):
                relevant_cols.append(col)
        
        print(f"\nAll STOP orders for position {sample_pos}:")
        print(sample_stops[relevant_cols])
        
        # Look for trigger price differences (evidence of trailing movement)
        if 'trigger_price' in sample_stops.columns:
            trigger_prices = sample_stops['trigger_price'].dropna().unique()
            print(f"\nUnique trigger prices for this position: {len(trigger_prices)}")
            if len(trigger_prices) > 1:
                print(f"Trigger price range: {min(trigger_prices):.5f} to {max(trigger_prices):.5f}")
                print("✅ TRAILING DETECTED: Multiple different trigger prices indicate stop was moved!")
            else:
                print("No trigger price variation detected")
    else:
        print("❌ NO TRAILING EVIDENCE: All positions have only 1 STOP order each")
    
    # Summary statistics
    print(f"\n" + "="*60)
    print("SUMMARY:")
    print(f"- Total positions: {len(positions)}")
    print(f"- Positions with STOP orders: {stop_orders['position_id'].nunique()}")
    print(f"- Average STOP orders per position: {len(stop_orders) / stop_orders['position_id'].nunique():.2f}")
    print(f"- Positions with multiple STOPs: {len(multiple_stops)}")
    
    if len(multiple_stops) > 0:
        print("✅ CONCLUSION: Trailing stops are ACTIVE and modifying stop orders")
    else:
        print("❌ CONCLUSION: Trailing stops are NOT modifying orders (each position has exactly 1 STOP)")

if __name__ == "__main__":
    analyze_trailing_stops()