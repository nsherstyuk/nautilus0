"""
Compare backtest results with and without hour 17 exclusions.
"""
import pandas as pd
from pathlib import Path

# Load both results
no_exclusions = pd.read_csv("logs/backtest_results/MTF_ML_20251128_202046/trades.csv")
with_exclusions = pd.read_csv("logs/backtest_results/MTF_ML_20251128_205214/trades.csv")

print("="*80)
print("COMPARISON: NO EXCLUSIONS vs HOUR 17 EXCLUDED (TUE/WED/FRI)")
print("="*80)

print(f"\nNo exclusions: {len(no_exclusions)} trades, ${no_exclusions['pnl'].sum():.2f}")
print(f"With exclusions: {len(with_exclusions)} trades, ${with_exclusions['pnl'].sum():.2f}")
print(f"Difference: {len(with_exclusions) - len(no_exclusions)} trades, ${with_exclusions['pnl'].sum() - no_exclusions['pnl'].sum():.2f}")

# November comparison
nov_no_excl = no_exclusions[no_exclusions['entry_month'] == '2025-11']
nov_with_excl = with_exclusions[with_exclusions['entry_month'] == '2025-11']

print("\n" + "="*80)
print("NOVEMBER COMPARISON")
print("="*80)
print(f"\nNo exclusions: {len(nov_no_excl)} trades, ${nov_no_excl['pnl'].sum():.2f}")
print(f"With exclusions: {len(nov_with_excl)} trades, ${nov_with_excl['pnl'].sum():.2f}")
print(f"Difference: {len(nov_with_excl) - len(nov_no_excl)} trades, ${nov_with_excl['pnl'].sum() - nov_no_excl['pnl'].sum():.2f}")

# What trades were excluded?
no_exclusions['entry_time'] = pd.to_datetime(no_exclusions['entry_time'])
with_exclusions['entry_time'] = pd.to_datetime(with_exclusions['entry_time'])

# Find hour 17 trades on Tue/Wed/Fri in no_exclusions
weekday_map = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}
excluded_days = ['Tuesday', 'Wednesday', 'Friday']

hour_17_excluded = no_exclusions[
    (no_exclusions['entry_hour'] == 17) & 
    (no_exclusions['entry_weekday'].map(weekday_map).isin(excluded_days))
]

print("\n" + "="*80)
print("HOUR 17 TRADES THAT WERE EXCLUDED (TUE/WED/FRI)")
print("="*80)
print(f"Total excluded: {len(hour_17_excluded)} trades")
print(f"P&L of excluded trades: ${hour_17_excluded['pnl'].sum():.2f}")
print(f"Win rate of excluded: {(hour_17_excluded['pnl'] > 0).sum() / len(hour_17_excluded) * 100:.1f}%")

print("\nBy month:")
monthly = hour_17_excluded.groupby('entry_month').agg({
    'pnl': ['count', 'sum', 'mean']
}).round(2)
monthly.columns = ['Count', 'Total P&L', 'Avg P&L']
print(monthly)

# What new trades appeared?
print("\n" + "="*80)
print("ANALYSIS: WHY DID TOTAL TRADES INCREASE?")
print("="*80)
print("This suggests that excluding hour 17 allowed MORE trades at other hours")
print("(due to cooldown timing differences)")

# Check November hour 17 specifically
nov_hour_17_excl = hour_17_excluded[hour_17_excluded['entry_month'] == '2025-11']
print("\n" + "="*80)
print("NOVEMBER HOUR 17 EXCLUDED TRADES")
print("="*80)
print(f"Count: {len(nov_hour_17_excl)}")
print(f"P&L: ${nov_hour_17_excl['pnl'].sum():.2f}")
print("\nDetails:")
print(nov_hour_17_excl[['entry_time', 'entry_weekday', 'pnl', 'exit_reason']].to_string(index=False))
