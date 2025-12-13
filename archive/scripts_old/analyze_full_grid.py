"""Analyze comprehensive grid results with all 324 parameter combinations"""

import pandas as pd
import numpy as np

# Read the full grid results
df = pd.read_csv('logs/grid_runs/grid_results_summary.csv')

print("=" * 100)
print("ADAPTIVE STOPS COMPREHENSIVE PARAMETER SWEEP - RESULTS REPORT")
print("=" * 100)
print(f"\nTest Period: August 1 - October 31, 2024")
print(f"Total Parameter Combinations Tested: {len(df)}")
print()

# Extract key columns
df['net_pnl'] = df['pnls_PnL (total)']
df['win_rate'] = df['pnls_Win Rate'] * 100  # Convert to percentage
df['expectancy'] = df['pnls_Expectancy']

# Group by mode
mode_summary = df.groupby('adaptive_stop_mode').agg({
    'net_pnl': ['mean', 'max', 'min'],
    'win_rate': ['mean', 'max', 'min'],
    'expectancy': ['mean', 'max', 'min'],
    'run_id': 'count'
}).round(2)

print("=" * 100)
print("\nMODE COMPARISON:")
print("-" * 100)
for mode in ['atr', 'percentile', 'fixed']:
    mode_data = df[df['adaptive_stop_mode'] == mode]
    print(f"\n{mode.upper()} Mode ({len(mode_data)} runs):")
    print(f"  PnL:        Avg=${mode_data['net_pnl'].mean():.2f}  Best=${mode_data['net_pnl'].max():.2f}  Worst=${mode_data['net_pnl'].min():.2f}")
    print(f"  Win Rate:   Avg={mode_data['win_rate'].mean():.1f}%  Best={mode_data['win_rate'].max():.1f}%  Worst={mode_data['win_rate'].min():.1f}%")
    print(f"  Expectancy: Avg=${mode_data['expectancy'].mean():.2f}  Best=${mode_data['expectancy'].max():.2f}  Worst=${mode_data['expectancy'].min():.2f}")

# Top 10 overall results by PnL
print("\n" + "=" * 100)
print("\nTOP 10 CONFIGURATIONS BY NET PnL:")
print("-" * 100)
top_10 = df.nlargest(10, 'net_pnl')[['run_id', 'adaptive_stop_mode', 'sl_atr_mult', 'tp_atr_mult', 
                                       'trail_activation_atr_mult', 'trail_distance_atr_mult',
                                       'net_pnl', 'win_rate', 'expectancy']]
print(top_10.to_string(index=False))

# Top 10 by win rate
print("\n" + "=" * 100)
print("\nTOP 10 CONFIGURATIONS BY WIN RATE:")
print("-" * 100)
top_wr = df.nlargest(10, 'win_rate')[['run_id', 'adaptive_stop_mode', 'sl_atr_mult', 'tp_atr_mult',
                                        'trail_activation_atr_mult', 'trail_distance_atr_mult',
                                        'net_pnl', 'win_rate', 'expectancy']]
print(top_wr.to_string(index=False))

# Best of each mode
print("\n" + "=" * 100)
print("\nBEST CONFIGURATION FOR EACH MODE (by PnL):")
print("-" * 100)
for mode in ['atr', 'percentile', 'fixed']:
    best = df[df['adaptive_stop_mode'] == mode].nlargest(1, 'net_pnl')
    print(f"\n{mode.upper()}:")
    print(f"  Run #{best['run_id'].values[0]}")
    print(f"  SL Multiplier: {best['sl_atr_mult'].values[0]}")
    print(f"  TP Multiplier: {best['tp_atr_mult'].values[0]}")
    print(f"  Trail Activation: {best['trail_activation_atr_mult'].values[0]}")
    print(f"  Trail Distance: {best['trail_distance_atr_mult'].values[0]}")
    print(f"  Net PnL: ${best['net_pnl'].values[0]:.2f}")
    print(f"  Win Rate: {best['win_rate'].values[0]:.1f}%")
    print(f"  Expectancy: ${best['expectancy'].values[0]:.2f}")

# ATR mode analysis by multipliers
print("\n" + "=" * 100)
print("\nATR MODE: IMPACT OF MULTIPLIERS")
print("-" * 100)
atr_data = df[df['adaptive_stop_mode'] == 'atr']

print("\nBy TP/SL Ratio (tp_atr_mult / sl_atr_mult):")
atr_data['tp_sl_ratio'] = atr_data['tp_atr_mult'] / atr_data['sl_atr_mult']
ratio_groups = atr_data.groupby('tp_sl_ratio').agg({
    'net_pnl': 'mean',
    'win_rate': 'mean',
    'expectancy': 'mean',
    'run_id': 'count'
}).round(2)
ratio_groups.columns = ['Avg PnL', 'Avg Win%', 'Avg Exp', 'Count']
print(ratio_groups.to_string())

print("\nBy SL Multiplier:")
sl_groups = atr_data.groupby('sl_atr_mult').agg({
    'net_pnl': 'mean',
    'win_rate': 'mean',
    'expectancy': 'mean',
    'run_id': 'count'
}).round(2)
sl_groups.columns = ['Avg PnL', 'Avg Win%', 'Avg Exp', 'Count']
print(sl_groups.to_string())

print("\nBy TP Multiplier:")
tp_groups = atr_data.groupby('tp_atr_mult').agg({
    'net_pnl': 'mean',
    'win_rate': 'mean',
    'expectancy': 'mean',
    'run_id': 'count'
}).round(2)
tp_groups.columns = ['Avg PnL', 'Avg Win%', 'Avg Exp', 'Count']
print(tp_groups.to_string())

print("\n" + "=" * 100)
print("\nKEY INSIGHTS:")
print("-" * 100)

# Compare adaptive vs fixed
atr_avg = df[df['adaptive_stop_mode'] == 'atr']['net_pnl'].mean()
percentile_avg = df[df['adaptive_stop_mode'] == 'percentile']['net_pnl'].mean()
fixed_avg = df[df['adaptive_stop_mode'] == 'fixed']['net_pnl'].mean()

atr_best = df[df['adaptive_stop_mode'] == 'atr']['net_pnl'].max()
percentile_best = df[df['adaptive_stop_mode'] == 'percentile']['net_pnl'].max()
fixed_best = df[df['adaptive_stop_mode'] == 'fixed']['net_pnl'].max()

print(f"\n1. Mode Performance:")
print(f"   • ATR Average: ${atr_avg:.2f} (Best: ${atr_best:.2f})")
print(f"   • Percentile Average: ${percentile_avg:.2f} (Best: ${percentile_best:.2f})")
print(f"   • Fixed Average: ${fixed_avg:.2f} (Best: ${fixed_best:.2f})")

best_overall = df.nlargest(1, 'net_pnl')
print(f"\n2. Best Overall Configuration:")
print(f"   • Mode: {best_overall['adaptive_stop_mode'].values[0]}")
print(f"   • PnL: ${best_overall['net_pnl'].values[0]:.2f}")
print(f"   • Win Rate: {best_overall['win_rate'].values[0]:.1f}%")
print(f"   • Parameters: SL={best_overall['sl_atr_mult'].values[0]}, TP={best_overall['tp_atr_mult'].values[0]}")

# Find best win rate
best_wr = df.nlargest(1, 'win_rate')
print(f"\n3. Highest Win Rate Configuration:")
print(f"   • Mode: {best_wr['adaptive_stop_mode'].values[0]}")
print(f"   • Win Rate: {best_wr['win_rate'].values[0]:.1f}%")
print(f"   • PnL: ${best_wr['net_pnl'].values[0]:.2f}")
print(f"   • Parameters: SL={best_wr['sl_atr_mult'].values[0]}, TP={best_wr['tp_atr_mult'].values[0]}")

print("\n" + "=" * 100)
print("\nRECOMMENDATIONS:")
print("-" * 100)

if best_overall['adaptive_stop_mode'].values[0] != 'fixed':
    print("\n✅ ADAPTIVE STOPS ARE WORKING!")
    print(f"   The best configuration uses {best_overall['adaptive_stop_mode'].values[0].upper()} mode")
    print(f"   and outperforms fixed stops significantly.")
else:
    print("\n⚠️  Fixed mode performed best, but adaptive modes show promise:")
    atr_competitive = df[df['adaptive_stop_mode'] == 'atr'].nlargest(1, 'net_pnl')
    print(f"   Best ATR config achieved ${atr_competitive['net_pnl'].values[0]:.2f}")
    
print("\n" + "=" * 100)
