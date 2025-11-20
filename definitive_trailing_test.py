#!/usr/bin/env python3
"""
DEFINITIVE TRAILING STOP DIAGNOSTIC

This will determine once and for all why trailing stops aren't working.
We'll run a single test with maximum debugging and analyze every aspect.
"""
import subprocess
import sys
import pandas as pd
import json
from pathlib import Path

def run_definitive_trailing_test():
    """Run comprehensive trailing stop diagnostic"""
    
    print("🔬 DEFINITIVE TRAILING STOP DIAGNOSTIC")
    print("=" * 60)
    
    # Set extremely favorable conditions for trailing
    print("📝 Setting ultra-favorable trailing conditions...")
    configure_optimal_trailing()
    
    # Run single backtest with maximum detail
    print("🚀 Running diagnostic backtest...")
    try:
        result = subprocess.run(
            [sys.executable, "backtest/run_backtest.py"],
            capture_output=True,
            text=True,
            timeout=300,
            encoding='utf-8',
            errors='replace'
        )
        
        print(f"📊 Backtest result: {result.returncode}")
        
        if result.returncode == 0:
            analyze_comprehensive_results()
        else:
            print(f"❌ Backtest failed: {result.stderr[:500]}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

def configure_optimal_trailing():
    """Configure parameters that should guarantee trailing activation"""
    
    # Ultra-aggressive trailing that should definitely trigger
    optimal_config = {
        # Basic parameters
        "BACKTEST_STOP_LOSS_PIPS": 50,          # High SL to give room
        "BACKTEST_TAKE_PROFIT_PIPS": 200,       # Very high TP to let trailing work
        "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": 8,  # Very low activation
        "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": 3,     # Very tight trailing
        
        # Disable complications
        "STRATEGY_REGIME_DETECTION_ENABLED": "false",
        "STRATEGY_TRAILING_DURATION_ENABLED": "false",
        "STRATEGY_ADAPTIVE_STOPS_ENABLED": "false",
        "BACKTEST_TIME_FILTER_ENABLED": "true",
        "STRATEGY_TIME_MULTIPLIER_ENABLED": "true",
        
        # Enable maximum logging 
        "LOG_LEVEL": "DEBUG"
    }
    
    # Update .env
    with open(".env", 'r') as f:
        lines = f.readlines()
    
    updated_lines = []
    for line in lines:
        if '=' in line and not line.strip().startswith('#'):
            key = line.split('=')[0].strip()
            if key in optimal_config:
                updated_lines.append(f"{key}={optimal_config[key]}\n")
                print(f"   Set: {key}={optimal_config[key]}")
                continue
        updated_lines.append(line)
    
    with open(".env", 'w') as f:
        f.writelines(updated_lines)

def analyze_comprehensive_results():
    """Comprehensive analysis of all result aspects"""
    
    print(f"\n📊 COMPREHENSIVE RESULTS ANALYSIS")
    print("=" * 60)
    
    # Find latest results
    results_dir = Path("logs/backtest_results")
    folders = sorted(results_dir.glob("EUR-USD_*"), key=lambda x: x.stat().st_mtime, reverse=True)
    
    if not folders:
        print("❌ No results folder found")
        return
    
    latest = folders[0]
    print(f"📁 Latest results: {latest.name}")
    
    # 1. Performance Analysis
    print(f"\n1️⃣  PERFORMANCE METRICS:")
    stats_file = latest / "performance_stats.json"
    if stats_file.exists():
        with open(stats_file, 'r') as f:
            stats = json.load(f)
        
        pnl = stats.get('pnls', {}).get('PnL (total)', 0)
        win_rate = stats.get('pnls', {}).get('Win Rate', 0)
        trades = 0
        
        # Count positions
        pos_file = latest / "positions.csv"
        if pos_file.exists():
            pos_df = pd.read_csv(pos_file)
            trades = len(pos_df)
        
        print(f"   💰 Total PnL: ${pnl:.2f}")
        print(f"   📈 Win Rate: {win_rate:.3f}")
        print(f"   🔄 Total Trades: {trades}")
        
        # Check if this is the "standard" result
        is_standard = abs(pnl - 4037.0) < 0.01 and abs(win_rate - 0.548) < 0.001
        if is_standard:
            print("   🚨 IDENTICAL TO STANDARD RESULT - No trailing effect!")
        else:
            print("   ✅ DIFFERENT FROM STANDARD - Trailing may be working!")
    
    # 2. Orders Analysis  
    print(f"\n2️⃣  ORDER ANALYSIS:")
    orders_file = latest / "orders.csv"
    if orders_file.exists():
        orders_df = pd.read_csv(orders_file)
        
        print(f"   📋 Total orders: {len(orders_df)}")
        
        # Order type breakdown
        if 'type' in orders_df.columns:
            order_types = orders_df['type'].value_counts()
            for otype, count in order_types.items():
                print(f"   📦 {otype}: {count}")
            
            # Focus on STOP orders
            stop_orders = orders_df[orders_df['type'] == 'STOP']
            print(f"\n   🛑 STOP Orders Details:")
            print(f"      Total STOP orders: {len(stop_orders)}")
            
            if len(stop_orders) > 0:
                # Check for multiple stops per position (trailing evidence)
                if 'position_id' in stop_orders.columns:
                    stop_groups = stop_orders.groupby('position_id').size()
                    multi_stop_positions = stop_groups[stop_groups > 1]
                    
                    print(f"      Positions with >1 STOP: {len(multi_stop_positions)}")
                    if len(multi_stop_positions) > 0:
                        print(f"      🎯 TRAILING DETECTED! Max stops/position: {stop_groups.max()}")
                        
                        # Show trigger price evidence
                        if 'trigger_price' in stop_orders.columns:
                            example_pos = multi_stop_positions.index[0]
                            example_stops = stop_orders[stop_orders['position_id'] == example_pos]
                            triggers = example_stops['trigger_price'].values
                            print(f"      Example triggers: {triggers[:5]}...")
                            print(f"      Price range: {min(triggers):.5f} - {max(triggers):.5f}")
                    else:
                        print("      ⚠️  Each position has only 1 STOP - no trailing")
            else:
                print("      ❌ NO STOP ORDERS FOUND!")
        else:
            print("   ❌ No 'type' column in orders data")
    
    # 3. Position Analysis
    print(f"\n3️⃣  POSITION ANALYSIS:")
    if pos_file.exists():
        positions_df = pd.read_csv(pos_file)
        
        if len(positions_df) > 0:
            # Analyze position outcomes
            if 'pnl' in positions_df.columns:
                avg_pnl = positions_df['pnl'].mean()
                print(f"   💰 Average PnL per position: ${avg_pnl:.2f}")
            
            # Check duration if available
            if 'ts_opened' in positions_df.columns and 'ts_closed' in positions_df.columns:
                positions_df['ts_opened'] = pd.to_datetime(positions_df['ts_opened'])
                positions_df['ts_closed'] = pd.to_datetime(positions_df['ts_closed'])
                positions_df['duration_hours'] = (positions_df['ts_closed'] - positions_df['ts_opened']).dt.total_seconds() / 3600
                avg_duration = positions_df['duration_hours'].mean()
                print(f"   ⏰ Average position duration: {avg_duration:.1f} hours")
                
                # Look for very long positions (where trailing should activate)
                long_positions = positions_df[positions_df['duration_hours'] > 8]
                print(f"   📏 Positions >8 hours: {len(long_positions)} ({len(long_positions)/len(positions_df)*100:.1f}%)")
        else:
            print("   ❌ No positions found")
    
    # 4. Configuration Verification
    print(f"\n4️⃣  CONFIGURATION VERIFICATION:")
    env_file = latest / ".env.full"
    if env_file.exists():
        with open(env_file, 'r') as f:
            env_content = f.read()
        
        # Extract key trailing parameters
        for param in ["BACKTEST_TRAILING_STOP_ACTIVATION_PIPS", "BACKTEST_TRAILING_STOP_DISTANCE_PIPS"]:
            if param in env_content:
                line = [l for l in env_content.split('\n') if param in l and not l.strip().startswith('#')]
                if line:
                    print(f"   🔧 {param}: {line[0].split('=')[1] if '=' in line[0] else 'NOT SET'}")
    
    # 5. Final Verdict
    print(f"\n5️⃣  FINAL VERDICT:")
    
    # Determine if trailing is working based on evidence
    has_multiple_stops = False
    if orders_file.exists():
        orders_df = pd.read_csv(orders_file)
        if 'type' in orders_df.columns and 'position_id' in orders_df.columns:
            stop_orders = orders_df[orders_df['type'] == 'STOP']
            if len(stop_orders) > 0:
                stop_groups = stop_orders.groupby('position_id').size()
                has_multiple_stops = any(stop_groups > 1)
    
    if has_multiple_stops:
        print("   ✅ TRAILING IS WORKING: Multiple STOP orders per position detected")
        print("   🎯 Problem may be elsewhere (parameter tuning, market conditions, etc.)")
    else:
        print("   ❌ TRAILING IS NOT WORKING: No evidence of stop order modifications")
        print("   🔍 Possible causes:")
        print("      • Trailing logic never executes")
        print("      • Positions close before trailing activates") 
        print("      • Configuration/parameter issues")
        print("      • Strategy logic conflicts")

if __name__ == "__main__":
    run_definitive_trailing_test()