import pandas as pd

df = pd.read_csv('logs/grid_runs/grid_results_summary.csv')

print("\n" + "="*80)
print("TP/SL OPTIMIZATION RESULTS")
print("="*80)

# Select relevant columns
cols = ['run_id', 'BACKTEST_TP_ATR_MULT', 'BACKTEST_SL_ATR_MULT', 'pnls_PnL (total)', 'pnls_Win Rate']
df_view = df[cols].copy()
df_view.columns = ['Run', 'TP_Mult', 'SL_Mult', 'Net_PnL', 'Win_Rate']
df_view['Win_Rate_Pct'] = (df_view['Win_Rate'] * 100).round(1)
df_view['TP_SL_Ratio'] = (df_view['TP_Mult'] / df_view['SL_Mult']).round(2)

# Sort by PnL
df_sorted = df_view.sort_values('Net_PnL', ascending=False)

print(f"\nTop 10 Best Performers:")
print("-" * 80)
print(df_sorted[['Run', 'TP_Mult', 'SL_Mult', 'TP_SL_Ratio', 'Net_PnL', 'Win_Rate_Pct']].head(10).to_string(index=False))

print(f"\n\nBottom 5 Worst Performers:")
print("-" * 80)
print(df_sorted[['Run', 'TP_Mult', 'SL_Mult', 'TP_SL_Ratio', 'Net_PnL', 'Win_Rate_Pct']].tail(5).to_string(index=False))

print("\n" + "="*80)
print("KEY INSIGHTS:")
print("="*80)

best = df_sorted.iloc[0]
worst = df_sorted.iloc[-1]

print(f"\n🏆 BEST: TP={best['TP_Mult']}, SL={best['SL_Mult']} (ratio {best['TP_SL_Ratio']}:1)")
print(f"   → PnL: ${best['Net_PnL']:.2f}")
print(f"   → Win Rate: {best['Win_Rate_Pct']:.1f}%")

print(f"\n❌ WORST: TP={worst['TP_Mult']}, SL={worst['SL_Mult']} (ratio {worst['TP_SL_Ratio']}:1)")
print(f"   → PnL: ${worst['Net_PnL']:.2f}")
print(f"   → Win Rate: {worst['Win_Rate_Pct']:.1f}%")

# Analyze by TP value
print("\n" + "="*80)
print("PERFORMANCE BY TP MULTIPLIER:")
print("="*80)
tp_analysis = df_view.groupby('TP_Mult').agg({
    'Net_PnL': ['mean', 'max', 'min'],
    'Win_Rate_Pct': 'mean'
}).round(2)
print(tp_analysis)

# Analyze by SL value
print("\n" + "="*80)
print("PERFORMANCE BY SL MULTIPLIER:")
print("="*80)
sl_analysis = df_view.groupby('SL_Mult').agg({
    'Net_PnL': ['mean', 'max', 'min'],
    'Win_Rate_Pct': 'mean'
}).round(2)
print(sl_analysis)

print("\n" + "="*80)
print("RECOMMENDATION:")
print("="*80)
print(f"\n✅ Best single configuration: TP={best['TP_Mult']}, SL={best['SL_Mult']}")
print(f"   - Achieves ${best['Net_PnL']:.2f} PnL with {best['Win_Rate_Pct']:.1f}% win rate")
print(f"   - Risk/Reward ratio: {best['TP_SL_Ratio']}:1")

# Compare with current settings
current_tp = 4.25
current_sl = 1.1
current_match = df_view[(df_view['TP_Mult'] == current_tp) & (df_view['SL_Mult'].between(1.1, 1.2))]
if not current_match.empty:
    current_result = current_match.iloc[0]
    improvement = best['Net_PnL'] - current_result['Net_PnL']
    print(f"\n📊 Comparison with current setting (TP={current_tp}, SL={current_sl}):")
    print(f"   Current PnL: ~${current_result['Net_PnL']:.2f}")
    print(f"   Potential improvement: +${improvement:.2f} ({improvement/current_result['Net_PnL']*100:.1f}%)")
