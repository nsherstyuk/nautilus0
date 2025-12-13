#!/usr/bin/env python3
"""
Phase 0 Results Analysis - Trailing ON vs OFF Comparison
Analyzes the impact of trailing stops on strategy performance
"""
import json
import pandas as pd
from pathlib import Path

def analyze_phase0_results():
    print("=" * 60)
    print("PHASE 0 RESULTS ANALYSIS")
    print("=" * 60)
    
    results_dir = Path("re_optimization_results")
    disabled_dir = results_dir / "trailing_DISABLED"
    enabled_dir = results_dir / "trailing_ENABLED"
    
    # Load performance stats
    with open(disabled_dir / "performance_stats.json", 'r') as f:
        disabled_stats = json.load(f)
    
    with open(enabled_dir / "performance_stats.json", 'r') as f:
        enabled_stats = json.load(f)
    
    print("\n📊 PERFORMANCE COMPARISON:")
    print(f"{'Metric':<25} {'Trailing OFF':<15} {'Trailing ON':<15} {'Difference':<15}")
    print("-" * 70)
    
    # Compare key metrics
    disabled_pnl = disabled_stats["pnls"]["PnL (total)"]
    enabled_pnl = enabled_stats["pnls"]["PnL (total)"]
    pnl_diff = enabled_pnl - disabled_pnl
    
    disabled_win_rate = disabled_stats["pnls"]["Win Rate"]
    enabled_win_rate = enabled_stats["pnls"]["Win Rate"]
    win_rate_diff = enabled_win_rate - disabled_win_rate
    
    disabled_expectancy = disabled_stats["pnls"]["Expectancy"]
    enabled_expectancy = enabled_stats["pnls"]["Expectancy"]
    expectancy_diff = enabled_expectancy - disabled_expectancy
    
    print(f"{'Total PnL':<25} ${disabled_pnl:<14.2f} ${enabled_pnl:<14.2f} ${pnl_diff:<14.2f}")
    print(f"{'Win Rate':<25} {disabled_win_rate:<14.3f} {enabled_win_rate:<14.3f} {win_rate_diff:<14.3f}")
    print(f"{'Expectancy':<25} ${disabled_expectancy:<14.2f} ${enabled_expectancy:<14.2f} ${expectancy_diff:<14.2f}")
    
    # Load and compare orders
    disabled_orders = pd.read_csv(disabled_dir / "orders.csv")
    enabled_orders = pd.read_csv(enabled_dir / "orders.csv")
    
    print(f"\n📈 TRADING ACTIVITY:")
    print(f"{'Orders (Disabled)':<20}: {len(disabled_orders):,}")
    print(f"{'Orders (Enabled)':<20}: {len(enabled_orders):,}")
    print(f"{'Order Difference':<20}: {len(enabled_orders) - len(disabled_orders):,}")
    
    # Analyze order types
    disabled_stop_orders = disabled_orders[disabled_orders['type'] == 'STOP'].copy()
    enabled_stop_orders = enabled_orders[enabled_orders['type'] == 'STOP'].copy()
    
    print(f"\n🛑 STOP ORDERS:")
    print(f"{'STOP orders (Disabled)':<25}: {len(disabled_stop_orders):,}")
    print(f"{'STOP orders (Enabled)':<25}: {len(enabled_stop_orders):,}")
    
    # Look for trailing evidence in enabled configuration
    if len(enabled_stop_orders) > 0:
        # Group by position_id to see multiple stop orders per position (evidence of trailing)
        stop_groups = enabled_stop_orders.groupby('position_id').size()
        multiple_stops = stop_groups[stop_groups > 1]
        
        print(f"{'Positions with >1 STOP':<25}: {len(multiple_stops):,}")
        if len(multiple_stops) > 0:
            print(f"{'Max STOPs per position':<25}: {stop_groups.max():,}")
            print(f"{'Avg STOPs per position':<25}: {stop_groups.mean():.1f}")
            
            # Show examples of trailing activity
            example_pos = multiple_stops.index[0]
            example_stops = enabled_stop_orders[enabled_stop_orders['position_id'] == example_pos]
            
            print(f"\n🔍 EXAMPLE TRAILING ACTIVITY (Position {example_pos}):")
            if 'trigger_price' in example_stops.columns:
                trigger_prices = example_stops['trigger_price'].unique()
                print(f"   Unique trigger prices: {len(trigger_prices)}")
                print(f"   Price range: {min(trigger_prices):.5f} - {max(trigger_prices):.5f}")
            else:
                print("   No trigger_price column found in orders")
    
    # Load and compare positions
    disabled_positions = pd.read_csv(disabled_dir / "positions.csv")
    enabled_positions = pd.read_csv(enabled_dir / "positions.csv")
    
    print(f"\n📊 POSITIONS:")
    print(f"{'Positions (Disabled)':<20}: {len(disabled_positions):,}")
    print(f"{'Positions (Enabled)':<20}: {len(enabled_positions):,}")
    
    print(f"\n🎯 CONCLUSION:")
    if abs(pnl_diff) < 0.01:
        print("   ⚠️  IDENTICAL RESULTS - Possible Issues:")
        print("   • Trailing stops may not be activating due to price movements")
        print("   • Current configuration may have trailing activation too high")
        print("   • Strategy may be hitting SL/TP before trailing activates")
        print(f"   • Current trailing activation: {get_trailing_config()}")
        
        # Recommend Phase 1 optimization
        print(f"\n📋 RECOMMENDATION:")
        print("   ✅ Proceed with Phase 1 optimization")
        print("   ✅ Test lower trailing activation thresholds")
        print("   ✅ Focus on trailing distance optimization")
        print("   ✅ Grid includes 400 combinations of SL/TP/trailing parameters")
        
    else:
        impact_pct = (pnl_diff / disabled_pnl) * 100
        print(f"   📈 Trailing stops impact: {impact_pct:.2f}%")
        if pnl_diff > 0:
            print("   ✅ Trailing stops IMPROVE performance")
        else:
            print("   ❌ Trailing stops REDUCE performance")
        
        print(f"\n📋 RECOMMENDATION:")
        print("   ✅ Proceed with full re-optimization")
        print("   ✅ All previous parameters are potentially sub-optimal")
        
    print(f"\n📁 Results saved in: {results_dir}")
    print("=" * 60)

def get_trailing_config():
    """Get current trailing configuration"""
    try:
        with open('.env', 'r') as f:
            lines = f.readlines()
        
        activation = None
        distance = None
        
        for line in lines:
            if 'BACKTEST_TRAILING_STOP_ACTIVATION_PIPS' in line and not line.startswith('#'):
                activation = line.split('=')[1].strip()
            elif 'BACKTEST_TRAILING_STOP_DISTANCE_PIPS' in line and not line.startswith('#'):
                distance = line.split('=')[1].strip()
        
        return f"Activation={activation}, Distance={distance}"
    except:
        return "Unknown"

if __name__ == "__main__":
    analyze_phase0_results()