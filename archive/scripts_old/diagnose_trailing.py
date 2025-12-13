#!/usr/bin/env python3
"""
Diagnostic Test: Why is trailing not activating?

Test specific trailing configurations and check if:
1. Trailing stop logic is executing
2. Orders are being placed and modified
3. What activation conditions are preventing triggering
"""
import subprocess
import sys
import pandas as pd
import json
from pathlib import Path

def diagnose_trailing_activation():
    """Run focused tests to diagnose trailing activation issues"""
    
    print("🔍 TRAILING ACTIVATION DIAGNOSTIC")
    print("=" * 50)
    
    # Test configurations that should definitely activate trailing
    test_configs = [
        {
            "name": "Conservative (SL=15, TP=60, Trail=10/5)",
            "BACKTEST_STOP_LOSS_PIPS": 15,
            "BACKTEST_TAKE_PROFIT_PIPS": 60,  # Give more room
            "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": 10,  # Very low activation
            "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": 5,     # Tight distance
        },
        {
            "name": "Ultra-Aggressive (SL=20, TP=80, Trail=5/3)",
            "BACKTEST_STOP_LOSS_PIPS": 20,
            "BACKTEST_TAKE_PROFIT_PIPS": 80,
            "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": 5,   # Extremely low
            "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": 3,     # Very tight
        }
    ]
    
    for i, config in enumerate(test_configs, 1):
        print(f"\n🧪 TEST {i}: {config['name']}")
        print("-" * 30)
        
        # Update .env with test parameters
        update_env_with_params(config)
        
        # Run backtest
        print("Running backtest...")
        try:
            result = subprocess.run(
                [sys.executable, "backtest/run_backtest.py"],
                capture_output=True,
                text=True,
                timeout=180  # 3 minutes
            )
            
            if result.returncode != 0:
                print(f"❌ Backtest failed: {result.stderr[:200]}...")
                continue
                
            # Analyze results
            analyze_trailing_evidence(config['name'])
            
        except subprocess.TimeoutExpired:
            print("⏰ Timeout - backtest took too long")
        except Exception as e:
            print(f"❌ Error: {e}")

def update_env_with_params(config):
    """Update .env file with test parameters"""
    with open(".env", 'r') as f:
        lines = f.readlines()
    
    updated_lines = []
    for line in lines:
        if '=' in line and not line.strip().startswith('#'):
            key = line.split('=')[0].strip()
            if key in config and key != 'name':
                updated_lines.append(f"{key}={config[key]}\n")
                continue
        updated_lines.append(line)
    
    with open(".env", 'w') as f:
        f.writelines(updated_lines)

def analyze_trailing_evidence(test_name):
    """Analyze backtest results for trailing stop evidence"""
    print(f"\n📊 Analyzing {test_name} results...")
    
    # Find latest results
    results_dir = Path("logs/backtest_results")
    folders = sorted(results_dir.glob("EUR-USD_*"), key=lambda x: x.stat().st_mtime, reverse=True)
    
    if not folders:
        print("❌ No results folder found")
        return
    
    latest_folder = folders[0]
    print(f"📁 Results: {latest_folder.name}")
    
    # Check orders for trailing evidence
    orders_file = latest_folder / "orders.csv"
    if orders_file.exists():
        orders_df = pd.read_csv(orders_file)
        
        # Look for STOP orders
        stop_orders = orders_df[orders_df['type'] == 'STOP']
        print(f"🛑 Total STOP orders: {len(stop_orders)}")
        
        if len(stop_orders) > 0:
            # Group by position to see multiple stops per position
            stop_groups = stop_orders.groupby('position_id').size()
            multiple_stops = stop_groups[stop_groups > 1]
            
            print(f"📈 Positions with multiple STOPs: {len(multiple_stops)}")
            
            if len(multiple_stops) > 0:
                print(f"🎯 TRAILING DETECTED! Max stops per position: {stop_groups.max()}")
                
                # Show trigger price ranges for trailing evidence
                if 'trigger_price' in stop_orders.columns:
                    example_pos = multiple_stops.index[0]
                    example_stops = stop_orders[stop_orders['position_id'] == example_pos]
                    trigger_prices = example_stops['trigger_price'].values
                    print(f"🔍 Example position {example_pos}:")
                    print(f"   Trigger prices: {trigger_prices}")
                    print(f"   Price range: {min(trigger_prices):.5f} - {max(trigger_prices):.5f}")
            else:
                print("⚠️  No trailing detected - only 1 STOP per position")
        else:
            print("⚠️  NO STOP orders found at all!")
    else:
        print("❌ No orders.csv file found")
    
    # Check performance
    stats_file = latest_folder / "performance_stats.json"
    if stats_file.exists():
        with open(stats_file, 'r') as f:
            stats = json.load(f)
        
        pnl = stats.get('pnls', {}).get('PnL (total)', 0)
        win_rate = stats.get('pnls', {}).get('Win Rate', 0)
        print(f"💰 PnL: ${pnl:.2f}, Win Rate: {win_rate:.3f}")
        
        # Check if results are identical to our "baseline"
        if abs(pnl - 4037.0) < 0.01 and abs(win_rate - 0.548) < 0.001:
            print("🚨 IDENTICAL to baseline - trailing not working!")
        else:
            print("✅ Different from baseline - trailing may be working!")

if __name__ == "__main__":
    diagnose_trailing_activation()