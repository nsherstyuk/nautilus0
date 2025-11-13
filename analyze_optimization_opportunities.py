"""Analyze grid results to identify optimization opportunities"""

import pandas as pd
import numpy as np

# Read the full grid results
df = pd.read_csv('logs/grid_runs/grid_results_summary.csv')

df['net_pnl'] = df['pnls_PnL (total)']
df['win_rate'] = df['pnls_Win Rate'] * 100
df['expectancy'] = df['pnls_Expectancy']

print("=" * 100)
print("OPTIMIZATION OPPORTUNITIES ANALYSIS")
print("=" * 100)

# 1. Analyze trailing stop impact
print("\n1. TRAILING STOP IMPACT ANALYSIS")
print("-" * 100)

# Focus on best mode (percentile) with best multipliers (sl=1.0, tp=3.5)
best_config = df[(df['adaptive_stop_mode'] == 'percentile') & 
                  (df['sl_atr_mult'] == 1.0) & 
                  (df['tp_atr_mult'] == 3.5)]

print(f"\nBest configuration (percentile, SL=1.0, TP=3.5): {len(best_config)} variations")
print("\nTrailing Stop Activation Impact:")
trail_act_groups = best_config.groupby('trail_activation_atr_mult').agg({
    'net_pnl': 'mean',
    'win_rate': 'mean',
    'expectancy': 'mean',
    'run_id': 'count'
}).round(2)
trail_act_groups.columns = ['Avg PnL', 'Avg Win%', 'Avg Exp', 'Count']
print(trail_act_groups.to_string())

print("\nTrailing Stop Distance Impact:")
trail_dist_groups = best_config.groupby('trail_distance_atr_mult').agg({
    'net_pnl': 'mean',
    'win_rate': 'mean',
    'expectancy': 'mean',
    'run_id': 'count'
}).round(2)
trail_dist_groups.columns = ['Avg PnL', 'Avg Win%', 'Avg Exp', 'Count']
print(trail_dist_groups.to_string())

# 2. Check if trailing stops matter at all
print("\n" + "=" * 100)
print("\n2. DO TRAILING STOPS MATTER?")
print("-" * 100)

# All runs with same SL/TP have identical results - trailing stops don't matter!
variance_by_config = df.groupby(['adaptive_stop_mode', 'sl_atr_mult', 'tp_atr_mult']).agg({
    'net_pnl': ['mean', 'std', 'min', 'max']
}).round(2)

print("\nVariance in PnL for same SL/TP configurations:")
print("(If std=0, trailing stops have NO impact)")
high_variance = variance_by_config[variance_by_config[('net_pnl', 'std')] > 0.01]
if len(high_variance) == 0:
    print("\n⚠️  CRITICAL FINDING: All configurations with same SL/TP have IDENTICAL results!")
    print("    Trailing stop parameters (activation & distance) have ZERO impact.")
    print("    This suggests:")
    print("    • Trailing stops aren't triggering")
    print("    • Most trades hit SL or TP before trailing activates")
    print("    • OR trailing stop logic may not be working correctly")
else:
    print(f"\n✓ Found {len(high_variance)} configs where trailing stops DO matter:")
    print(high_variance.to_string())

# 3. Analyze what ACTUALLY drives performance
print("\n" + "=" * 100)
print("\n3. KEY PERFORMANCE DRIVERS")
print("-" * 100)

# For percentile mode
percentile_data = df[df['adaptive_stop_mode'] == 'percentile']

print("\nPERCENTILE MODE - Performance by SL/TP combinations:")
sl_tp_perf = percentile_data.groupby(['sl_atr_mult', 'tp_atr_mult']).agg({
    'net_pnl': 'mean',
    'win_rate': 'mean',
    'expectancy': 'mean',
    'run_id': 'count'
}).round(2).sort_values('net_pnl', ascending=False)
sl_tp_perf.columns = ['Avg PnL', 'Avg Win%', 'Avg Exp', 'Count']
print(sl_tp_perf.head(10).to_string())

# 4. Optimal TP/SL ratios
print("\n" + "=" * 100)
print("\n4. OPTIMAL RISK/REWARD RATIOS")
print("-" * 100)

percentile_data_copy = percentile_data.copy()
percentile_data_copy['tp_sl_ratio'] = percentile_data_copy['tp_atr_mult'] / percentile_data_copy['sl_atr_mult']

ratio_perf = percentile_data_copy.groupby('tp_sl_ratio').agg({
    'net_pnl': ['mean', 'max'],
    'win_rate': 'mean',
    'expectancy': 'mean',
    'run_id': 'count'
}).round(2).sort_values(('net_pnl', 'mean'), ascending=False)

print("\nPerformance by TP/SL Ratio:")
print(ratio_perf.head(8).to_string())

# 5. Unexplored parameter space
print("\n" + "=" * 100)
print("\n5. OPTIMIZATION OPPORTUNITIES")
print("-" * 100)

print("\n✅ RECOMMENDED NEXT STEPS:")
print("\n1. FINE-TUNE SL/TP MULTIPLIERS (percentile mode)")
print("   Current best: SL=1.0, TP=3.5 (ratio 3.5:1)")
print("   Explore nearby values:")
print("   • SL: [0.8, 0.9, 1.0, 1.1, 1.2]")
print("   • TP: [3.0, 3.25, 3.5, 3.75, 4.0]")
print("   Grid: 5×5 = 25 combinations (quick run)")
print("   Goal: Find if 3.5:1 is truly optimal or if 4.0:1 or 3.0:1 is better")

print("\n2. TEST EXTREME RATIOS")
print("   Current range: 1.0:1 to 3.5:1")
print("   Extended range: Try up to 5.0:1 or even 6.0:1")
print("   Rationale: Best result uses widest ratio tested (3.5)")
print("   Grid: SL=1.0, TP=[4.0, 4.5, 5.0, 5.5, 6.0]")
print("   Goal: Find the optimal risk/reward ceiling")

print("\n3. VERIFY TRAILING STOPS ARE WORKING")
print("   • Add detailed logging to trailing stop logic")
print("   • Check: How many trades actually trigger trailing?")
print("   • If trailing stops rarely trigger, they're not worth optimizing")

print("\n4. OPTIMIZE VOLATILITY SCALING (percentile mode)")
print("   Current: volatility_sensitivity=0.6, volatility_window=200")
print("   Test combinations:")
print("   • Sensitivity: [0.4, 0.5, 0.6, 0.7, 0.8]")
print("   • Window: [100, 150, 200, 250, 300]")
print("   Grid: 5×5 = 25 combinations")
print("   Goal: Fine-tune how aggressively stops adapt to volatility changes")

# 6. Best quick wins
print("\n" + "=" * 100)
print("\n6. PRIORITIZED ACTION PLAN")
print("-" * 100)

print("\n🎯 PRIORITY 1: Test extreme TP/SL ratios (5 runs, ~2 minutes)")
print("   Keep SL=1.0, test TP=[4.0, 4.5, 5.0, 5.5, 6.0]")
print("   Expected gain: Potentially 10-30% more PnL if trend continues")

print("\n🎯 PRIORITY 2: Fine-tune around best (25 runs, ~10 minutes)")
print("   SL=[0.8, 0.9, 1.0, 1.1, 1.2] × TP=[3.0, 3.25, 3.5, 3.75, 4.0]")
print("   Expected gain: 5-15% optimization around current best")

print("\n🎯 PRIORITY 3: Optimize volatility scaling (25 runs, ~10 minutes)")
print("   Sensitivity=[0.4, 0.5, 0.6, 0.7, 0.8] × Window=[100, 150, 200, 250, 300]")
print("   Expected gain: 5-10% by better volatility adaptation")

print("\n💡 PRIORITY 4: Investigate trailing stops")
print("   Verify if they're actually triggering")
print("   If not working, fix implementation first before optimizing")

print("\n" + "=" * 100)

# Generate specific grid configurations
print("\n7. READY-TO-RUN GRID CONFIGURATIONS")
print("-" * 100)

print("\nPRIORITY 1 Grid (extreme_tp.json):")
grid_1 = {
    "adaptive_stop_mode": ["percentile"],
    "sl_atr_mult": [1.0],
    "tp_atr_mult": [4.0, 4.5, 5.0, 5.5, 6.0],
    "trail_activation_atr_mult": [0.8],
    "trail_distance_atr_mult": [0.6],
    "volatility_window": [200],
    "volatility_sensitivity": [0.6]
}
print(f"Total runs: {1 * 1 * 5 * 1 * 1 * 1 * 1} = 5")
print("Estimated time: 2-3 minutes")

print("\nPRIORITY 2 Grid (fine_tune_sl_tp.json):")
grid_2 = {
    "adaptive_stop_mode": ["percentile"],
    "sl_atr_mult": [0.8, 0.9, 1.0, 1.1, 1.2],
    "tp_atr_mult": [3.0, 3.25, 3.5, 3.75, 4.0],
    "trail_activation_atr_mult": [0.8],
    "trail_distance_atr_mult": [0.6],
    "volatility_window": [200],
    "volatility_sensitivity": [0.6]
}
print(f"Total runs: {1 * 5 * 5 * 1 * 1 * 1 * 1} = 25")
print("Estimated time: 10-12 minutes")

print("\n" + "=" * 100)
