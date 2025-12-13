import pandas as pd

df = pd.read_csv('stage1_results.csv')

# Calculate scores
df['smoothness_score'] = df['negative_months'] * 1000 + abs(df['max_drawdown'])
df['pnl_score'] = (df['total_pnl'] - df['total_pnl'].min()) / (df['total_pnl'].max() - df['total_pnl'].min())
df['smooth_score'] = 1 - ((df['smoothness_score'] - df['smoothness_score'].min()) / (df['smoothness_score'].max() - df['smoothness_score'].min()))
df['balanced_score'] = df['pnl_score'] * 0.6 + df['smooth_score'] * 0.4

best = df.loc[df['balanced_score'].idxmax()]

print("="*80)
print("STAGE 1 RESULTS ANALYSIS")
print("="*80)

print("\nBEST BALANCED CONFIG:")
print(f"  {best['config_name']}")
print(f"  Layer: {best['layer_config']}")
print(f"  First Trigger: {best['first_trigger']} ATR")
print(f"  Second Trigger: {best['second_trigger']} ATR")
print(f"  Total P&L: ${best['total_pnl']:,.0f}")
print(f"  2025 P&L: ${best['pnl_2025']:,.0f}")
print(f"  Oct-Nov: ${best['pnl_oct_nov']:,.0f}")
print(f"  Negative Months: {int(best['negative_months'])}")
print(f"  Max Drawdown: ${best['max_drawdown']:,.0f}")

print("\n" + "="*80)
print("TOP 5 BY TOTAL P&L")
print("="*80)
top_pnl = df.nlargest(5, 'total_pnl')
print(top_pnl[['config_name', 'total_pnl', 'pnl_oct_nov', 'negative_months', 'max_drawdown']].to_string(index=False))

print("\n" + "="*80)
print("TOP 5 BY SMOOTHNESS (Fewest Negative Months)")
print("="*80)
top_smooth = df.nsmallest(5, 'smoothness_score')
print(top_smooth[['config_name', 'total_pnl', 'pnl_oct_nov', 'negative_months', 'max_drawdown']].to_string(index=False))

print("\n" + "="*80)
print("RECOMMENDATION FOR STAGE 2")
print("="*80)
print(f"\nProceed with: {best['layer_config']}")
print(f"  Sizes: {best['layer_config']}")
print(f"  First trigger: {best['first_trigger']} ATR")
print(f"  Second trigger: {best['second_trigger']} ATR")
