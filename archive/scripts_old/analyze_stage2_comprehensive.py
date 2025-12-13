"""
Comprehensive Stage 2 Analysis
Find best compromises between P&L, drawdown, negative months, and negative days
"""
import pandas as pd

df = pd.read_csv('stage2_results.csv')

print("="*80)
print("STAGE 2 COMPREHENSIVE ANALYSIS")
print("="*80)

# Calculate composite scores
df['smoothness_score'] = df['negative_months'] * 1000 + abs(df['max_drawdown'])
df['pnl_score'] = (df['total_pnl'] - df['total_pnl'].min()) / (df['total_pnl'].max() - df['total_pnl'].min())
df['smooth_score'] = 1 - ((df['smoothness_score'] - df['smoothness_score'].min()) / (df['smoothness_score'].max() - df['smoothness_score'].min()))
df['balanced_score'] = df['pnl_score'] * 0.6 + df['smooth_score'] * 0.4

print(f"\nTotal configurations tested: {len(df)}")
print(f"Configurations with 0 negative months: {len(df[df['negative_months'] == 0])}")
print(f"Configurations with 1 negative month: {len(df[df['negative_months'] == 1])}")

# OPTION 1: Best Overall Balance (60% P&L, 40% Smoothness)
print("\n" + "="*80)
print("OPTION 1: BEST OVERALL BALANCE")
print("="*80)
best_balanced = df.loc[df['balanced_score'].idxmax()]
print(f"\nConfig: {best_balanced['config_name']}")
print(f"  SL: {best_balanced['sl_atr']} ATR")
print(f"  TP: {best_balanced['tp_atr']} ATR")
print(f"  Trailing Activation: {best_balanced['trailing_activation']} ATR")
print(f"  Trailing Distance: {best_balanced['trailing_distance']} ATR")
print(f"\nPerformance:")
print(f"  Total P&L: ${best_balanced['total_pnl']:,.0f}")
print(f"  2025 P&L: ${best_balanced['pnl_2025']:,.0f}")
print(f"  Oct-Nov 2025: ${best_balanced['pnl_oct_nov']:,.0f}")
print(f"  Negative Months: {int(best_balanced['negative_months'])}")
print(f"  Max Drawdown: ${best_balanced['max_drawdown']:,.0f}")
print(f"  Negative Days: {best_balanced['negative_days_pct']:.1f}%")

# OPTION 2: Zero Negative Months + Highest P&L
print("\n" + "="*80)
print("OPTION 2: ZERO NEGATIVE MONTHS + HIGHEST P&L")
print("="*80)
zero_neg_months = df[df['negative_months'] == 0]
if len(zero_neg_months) > 0:
    best_zero_neg = zero_neg_months.loc[zero_neg_months['total_pnl'].idxmax()]
    print(f"\nConfig: {best_zero_neg['config_name']}")
    print(f"  SL: {best_zero_neg['sl_atr']} ATR")
    print(f"  TP: {best_zero_neg['tp_atr']} ATR")
    print(f"  Trailing Activation: {best_zero_neg['trailing_activation']} ATR")
    print(f"  Trailing Distance: {best_zero_neg['trailing_distance']} ATR")
    print(f"\nPerformance:")
    print(f"  Total P&L: ${best_zero_neg['total_pnl']:,.0f}")
    print(f"  2025 P&L: ${best_zero_neg['pnl_2025']:,.0f}")
    print(f"  Oct-Nov 2025: ${best_zero_neg['pnl_oct_nov']:,.0f}")
    print(f"  Negative Months: {int(best_zero_neg['negative_months'])}")
    print(f"  Max Drawdown: ${best_zero_neg['max_drawdown']:,.0f}")
    print(f"  Negative Days: {best_zero_neg['negative_days_pct']:.1f}%")
else:
    print("\nNo configurations with 0 negative months")

# OPTION 3: Smallest Drawdown
print("\n" + "="*80)
print("OPTION 3: SMALLEST DRAWDOWN")
print("="*80)
best_dd = df.loc[df['max_drawdown'].idxmax()]  # idxmax because drawdown is negative
print(f"\nConfig: {best_dd['config_name']}")
print(f"  SL: {best_dd['sl_atr']} ATR")
print(f"  TP: {best_dd['tp_atr']} ATR")
print(f"  Trailing Activation: {best_dd['trailing_activation']} ATR")
print(f"  Trailing Distance: {best_dd['trailing_distance']} ATR")
print(f"\nPerformance:")
print(f"  Total P&L: ${best_dd['total_pnl']:,.0f}")
print(f"  2025 P&L: ${best_dd['pnl_2025']:,.0f}")
print(f"  Oct-Nov 2025: ${best_dd['pnl_oct_nov']:,.0f}")
print(f"  Negative Months: {int(best_dd['negative_months'])}")
print(f"  Max Drawdown: ${best_dd['max_drawdown']:,.0f}")
print(f"  Negative Days: {best_dd['negative_days_pct']:.1f}%")

# OPTION 4: Fewest Negative Days + Good P&L
print("\n" + "="*80)
print("OPTION 4: FEWEST NEGATIVE DAYS (< 35%) + BEST P&L")
print("="*80)
low_neg_days = df[df['negative_days_pct'] < 35]
if len(low_neg_days) > 0:
    best_neg_days = low_neg_days.loc[low_neg_days['total_pnl'].idxmax()]
    print(f"\nConfig: {best_neg_days['config_name']}")
    print(f"  SL: {best_neg_days['sl_atr']} ATR")
    print(f"  TP: {best_neg_days['tp_atr']} ATR")
    print(f"  Trailing Activation: {best_neg_days['trailing_activation']} ATR")
    print(f"  Trailing Distance: {best_neg_days['trailing_distance']} ATR")
    print(f"\nPerformance:")
    print(f"  Total P&L: ${best_neg_days['total_pnl']:,.0f}")
    print(f"  2025 P&L: ${best_neg_days['pnl_2025']:,.0f}")
    print(f"  Oct-Nov 2025: ${best_neg_days['pnl_oct_nov']:,.0f}")
    print(f"  Negative Months: {int(best_neg_days['negative_months'])}")
    print(f"  Max Drawdown: ${best_neg_days['max_drawdown']:,.0f}")
    print(f"  Negative Days: {best_neg_days['negative_days_pct']:.1f}%")
else:
    print("\nNo configurations with < 35% negative days")

# OPTION 5: Best Oct-Nov Performance
print("\n" + "="*80)
print("OPTION 5: BEST OCT-NOV 2025 PERFORMANCE")
print("="*80)
best_oct_nov = df.loc[df['pnl_oct_nov'].idxmax()]
print(f"\nConfig: {best_oct_nov['config_name']}")
print(f"  SL: {best_oct_nov['sl_atr']} ATR")
print(f"  TP: {best_oct_nov['tp_atr']} ATR")
print(f"  Trailing Activation: {best_oct_nov['trailing_activation']} ATR")
print(f"  Trailing Distance: {best_oct_nov['trailing_distance']} ATR")
print(f"\nPerformance:")
print(f"  Total P&L: ${best_oct_nov['total_pnl']:,.0f}")
print(f"  2025 P&L: ${best_oct_nov['pnl_2025']:,.0f}")
print(f"  Oct-Nov 2025: ${best_oct_nov['pnl_oct_nov']:,.0f}")
print(f"  Negative Months: {int(best_oct_nov['negative_months'])}")
print(f"  Max Drawdown: ${best_oct_nov['max_drawdown']:,.0f}")
print(f"  Negative Days: {best_oct_nov['negative_days_pct']:.1f}%")

# TOP 10 Overall
print("\n" + "="*80)
print("TOP 10 CONFIGURATIONS BY BALANCED SCORE")
print("="*80)
top10 = df.nlargest(10, 'balanced_score')
print(f"\n{'Rank':<5} {'Config':<25} {'P&L':>12} {'Oct-Nov':>10} {'NegMo':>6} {'MaxDD':>10} {'NegDays%':>9}")
print("-"*80)
for i, (_, row) in enumerate(top10.iterrows(), 1):
    print(f"{i:<5} {row['config_name']:<25} ${row['total_pnl']:>11,.0f} ${row['pnl_oct_nov']:>9,.0f} {int(row['negative_months']):>6} ${row['max_drawdown']:>9,.0f} {row['negative_days_pct']:>8.1f}%")

# Summary table of key options
print("\n" + "="*80)
print("COMPARISON OF KEY OPTIONS")
print("="*80)
options = pd.DataFrame([
    {
        'Option': '1. Best Balance',
        'Config': best_balanced['config_name'],
        'Total P&L': best_balanced['total_pnl'],
        'Oct-Nov': best_balanced['pnl_oct_nov'],
        'Neg Months': int(best_balanced['negative_months']),
        'Max DD': best_balanced['max_drawdown'],
        'Neg Days %': best_balanced['negative_days_pct']
    },
    {
        'Option': '2. Zero Neg Months',
        'Config': best_zero_neg['config_name'] if len(zero_neg_months) > 0 else 'N/A',
        'Total P&L': best_zero_neg['total_pnl'] if len(zero_neg_months) > 0 else 0,
        'Oct-Nov': best_zero_neg['pnl_oct_nov'] if len(zero_neg_months) > 0 else 0,
        'Neg Months': int(best_zero_neg['negative_months']) if len(zero_neg_months) > 0 else 0,
        'Max DD': best_zero_neg['max_drawdown'] if len(zero_neg_months) > 0 else 0,
        'Neg Days %': best_zero_neg['negative_days_pct'] if len(zero_neg_months) > 0 else 0
    },
    {
        'Option': '3. Smallest DD',
        'Config': best_dd['config_name'],
        'Total P&L': best_dd['total_pnl'],
        'Oct-Nov': best_dd['pnl_oct_nov'],
        'Neg Months': int(best_dd['negative_months']),
        'Max DD': best_dd['max_drawdown'],
        'Neg Days %': best_dd['negative_days_pct']
    },
    {
        'Option': '4. Low Neg Days',
        'Config': best_neg_days['config_name'] if len(low_neg_days) > 0 else 'N/A',
        'Total P&L': best_neg_days['total_pnl'] if len(low_neg_days) > 0 else 0,
        'Oct-Nov': best_neg_days['pnl_oct_nov'] if len(low_neg_days) > 0 else 0,
        'Neg Months': int(best_neg_days['negative_months']) if len(low_neg_days) > 0 else 0,
        'Max DD': best_neg_days['max_drawdown'] if len(low_neg_days) > 0 else 0,
        'Neg Days %': best_neg_days['negative_days_pct'] if len(low_neg_days) > 0 else 0
    },
    {
        'Option': '5. Best Oct-Nov',
        'Config': best_oct_nov['config_name'],
        'Total P&L': best_oct_nov['total_pnl'],
        'Oct-Nov': best_oct_nov['pnl_oct_nov'],
        'Neg Months': int(best_oct_nov['negative_months']),
        'Max DD': best_oct_nov['max_drawdown'],
        'Neg Days %': best_oct_nov['negative_days_pct']
    }
])

print("\n" + options.to_string(index=False))

print("\n" + "="*80)
print("RECOMMENDATION")
print("="*80)
print("\nBased on your priorities (P&L, small drawdown, zero/few negative months, low negative days):")
print("\nI recommend OPTION 2 (Zero Negative Months + Highest P&L) if available,")
print("otherwise OPTION 1 (Best Balance) as the most robust choice.")
