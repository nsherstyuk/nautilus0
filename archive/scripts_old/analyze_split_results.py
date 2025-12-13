"""Analyze position split optimization results."""
import pandas as pd
import sys

# Find latest results file
from pathlib import Path
results_files = sorted(Path(".").glob("position_split_results_*.csv"), reverse=True)
if not results_files:
    print("No results files found")
    sys.exit(1)

df = pd.read_csv(results_files[0])
print(f"Loaded: {results_files[0]}")

print("=" * 80)
print("POSITION SPLIT OPTIMIZATION RESULTS")
print("=" * 80)

# Sort by PnL
df = df.sort_values('total_pnl', ascending=False)

print("\n### TOP 10 BY PNL ###")
cols = ['config', 'num_layers', 'total_pnl', 'win_rate', 'negative_days']
print(df[cols].head(10).to_string(index=False))

print("\n### WORST 5 BY PNL ###")
print(df[cols].tail(5).to_string(index=False))

print("\n### BEST BY NUMBER OF POSITIONS ###")
for n in [1, 2, 3]:
    subset = df[df['num_layers'] == n]
    if not subset.empty:
        best = subset.iloc[0]
        print(f"\n{n}-POSITION BEST: {best['config']}")
        print(f"   PnL: ${best['total_pnl']:,.0f}")
        print(f"   Win Rate: {best['win_rate']:.1%}")
        print(f"   Neg Days: {best['negative_days']}")
        print(f"   Neg Months: {best.get('negative_months', 'N/A')}")

print("\n" + "=" * 80)
print("KEY FINDINGS")
print("=" * 80)

# Compare single vs multi-position
single_best = df[df['num_layers'] == 1].iloc[0]['total_pnl']
two_best = df[df['num_layers'] == 2].iloc[0]['total_pnl']
three_best = df[df['num_layers'] == 3].iloc[0]['total_pnl']

print(f"\n1-position best PnL: ${single_best:,.0f}")
print(f"2-position best PnL: ${two_best:,.0f}")
print(f"3-position best PnL: ${three_best:,.0f}")

if single_best > two_best and single_best > three_best:
    print("\n=> SINGLE POSITION performs best in this simulation")
elif two_best > three_best:
    print(f"\n=> 2-POSITION outperforms 3-position by ${two_best - three_best:,.0f}")
else:
    print(f"\n=> 3-POSITION outperforms 2-position by ${three_best - two_best:,.0f}")

# Note about simulation limitations
print("\n" + "-" * 80)
print("NOTE: This simplified simulation does NOT model:")
print("  - SL adjustment to breakeven after POS1 TP")
print("  - Trailing stop conversion for POS3")
print("  - These features significantly improve multi-position performance!")
print("-" * 80)
