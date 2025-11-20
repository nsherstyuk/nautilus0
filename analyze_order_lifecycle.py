#!/usr/bin/env python3
"""
Order Lifecycle Diagnostic

Run a backtest and capture all order state changes to understand
when and how bracket orders transition through different states.
"""
import subprocess
import sys
import pandas as pd
from pathlib import Path

def analyze_order_lifecycle():
    """Analyze the complete order lifecycle in a backtest"""
    
    print("🔍 ORDER LIFECYCLE DIAGNOSTIC")
    print("=" * 50)
    
    # Set simple config to focus on order behavior
    configure_simple_test()
    
    # Run backtest
    print("🚀 Running order lifecycle test...")
    try:
        result = subprocess.run(
            [sys.executable, "backtest/run_backtest.py"],
            capture_output=True,
            text=True,
            timeout=180,
            encoding='utf-8',
            errors='replace'
        )
        
        if result.returncode == 0:
            analyze_orders_and_positions()
        else:
            print(f"❌ Backtest failed: {result.stderr[:300]}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

def configure_simple_test():
    """Configure for order lifecycle analysis"""
    config = {
        "BACKTEST_STOP_LOSS_PIPS": 25,
        "BACKTEST_TAKE_PROFIT_PIPS": 70,
        "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": 15,
        "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": 10,
        "STRATEGY_REGIME_DETECTION_ENABLED": "false",
        "STRATEGY_TRAILING_DURATION_ENABLED": "false",
    }
    
    with open(".env", 'r') as f:
        lines = f.readlines()
    
    updated_lines = []
    for line in lines:
        if '=' in line and not line.strip().startswith('#'):
            key = line.split('=')[0].strip()
            if key in config:
                updated_lines.append(f"{key}={config[key]}\n")
                continue
        updated_lines.append(line)
    
    with open(".env", 'w') as f:
        f.writelines(updated_lines)
    
    print("📝 Configured for order lifecycle analysis")

def analyze_orders_and_positions():
    """Analyze order and position relationships"""
    
    # Find latest results
    results_dir = Path("logs/backtest_results")
    folders = sorted(results_dir.glob("EUR-USD_*"), key=lambda x: x.stat().st_mtime, reverse=True)
    latest = folders[0]
    
    print(f"📁 Analyzing: {latest.name}")
    
    # Load data
    orders_df = pd.read_csv(latest / "orders.csv")
    positions_df = pd.read_csv(latest / "positions.csv")
    
    print(f"\n📊 DATA OVERVIEW:")
    print(f"   Orders: {len(orders_df)}")
    print(f"   Positions: {len(positions_df)}")
    
    # Analyze order types and statuses
    print(f"\n📦 ORDER TYPE BREAKDOWN:")
    order_summary = orders_df.groupby(['type', 'status']).size().reset_index(name='count')
    for _, row in order_summary.iterrows():
        print(f"   {row['type']} - {row['status']}: {row['count']}")
    
    # Focus on STOP_MARKET orders
    stop_orders = orders_df[orders_df['type'] == 'STOP_MARKET']
    print(f"\n🛑 STOP_MARKET ORDER ANALYSIS:")
    print(f"   Total STOP_MARKET orders: {len(stop_orders)}")
    
    if len(stop_orders) > 0:
        # Group by position_id to see order patterns
        if 'position_id' in stop_orders.columns:
            stop_by_position = stop_orders.groupby('position_id').agg({
                'status': lambda x: list(x),
                'trigger_price': lambda x: list(x) if 'trigger_price' in stop_orders.columns else ['N/A']
            }).reset_index()
            
            print(f"\n🔍 STOP ORDERS BY POSITION (first 5):")
            for i, (_, row) in enumerate(stop_by_position.head().iterrows()):
                pos_id = row['position_id']
                statuses = row['status']
                triggers = row['trigger_price']
                
                print(f"   Position {pos_id}:")
                print(f"     Statuses: {statuses}")
                if triggers != ['N/A']:
                    print(f"     Triggers: {triggers}")
                
                # Check if this position has multiple stop orders (evidence of trailing)
                if len(statuses) > 1:
                    print(f"     🎯 MULTIPLE STOPS DETECTED!")
    
    # Analyze timing - when do positions close vs stop orders?
    print(f"\n⏰ TIMING ANALYSIS:")
    
    # Convert timestamps if available
    if 'ts_opened' in positions_df.columns and 'ts_closed' in positions_df.columns:
        positions_df['ts_opened'] = pd.to_datetime(positions_df['ts_opened'])
        positions_df['ts_closed'] = pd.to_datetime(positions_df['ts_closed'])
        
        # Look at position durations
        positions_df['duration_minutes'] = (positions_df['ts_closed'] - positions_df['ts_opened']).dt.total_seconds() / 60
        avg_duration = positions_df['duration_minutes'].mean()
        print(f"   Average position duration: {avg_duration:.1f} minutes")
        
        # Categorize by duration
        short_positions = positions_df[positions_df['duration_minutes'] < 60]  # < 1 hour
        medium_positions = positions_df[(positions_df['duration_minutes'] >= 60) & (positions_df['duration_minutes'] < 480)]  # 1-8 hours
        long_positions = positions_df[positions_df['duration_minutes'] >= 480]  # > 8 hours
        
        print(f"   Short (<1h): {len(short_positions)} ({len(short_positions)/len(positions_df)*100:.1f}%)")
        print(f"   Medium (1-8h): {len(medium_positions)} ({len(medium_positions)/len(positions_df)*100:.1f}%)")  
        print(f"   Long (>8h): {len(long_positions)} ({len(long_positions)/len(positions_df)*100:.1f}%)")
        
        if len(long_positions) > 0:
            print(f"\n📏 LONG POSITIONS (should have trailing opportunity):")
            for i, (_, pos) in enumerate(long_positions.head(3).iterrows()):
                pos_id = pos['id']
                duration_h = pos['duration_minutes'] / 60
                print(f"   {i+1}. Position {pos_id}: {duration_h:.1f} hours")
                
                # Check if this position had trailing activity
                pos_stops = stop_orders[stop_orders['position_id'] == pos_id] if 'position_id' in stop_orders.columns else pd.DataFrame()
                if len(pos_stops) > 1:
                    print(f"      🎯 HAD {len(pos_stops)} STOP ORDERS - TRAILING ACTIVE!")
                elif len(pos_stops) == 1:
                    print(f"      ⚠️  Only 1 stop order - no trailing")
                else:
                    print(f"      ❌ No stop orders found")
    
    print(f"\n🎯 SUMMARY:")
    
    # Count positions with multiple stops
    if 'position_id' in stop_orders.columns:
        stop_counts = stop_orders.groupby('position_id').size()
        multi_stop_positions = stop_counts[stop_counts > 1]
        
        if len(multi_stop_positions) > 0:
            print(f"   ✅ {len(multi_stop_positions)} positions had trailing activity")
            print(f"   📊 Max stops per position: {stop_counts.max()}")
            print(f"   🎯 Trailing stops ARE working!")
        else:
            print(f"   ❌ NO positions had multiple stops")
            print(f"   🔍 Trailing logic issue or conditions not met")
    else:
        print(f"   ❌ Cannot analyze trailing - no position_id in orders")

if __name__ == "__main__":
    analyze_order_lifecycle()