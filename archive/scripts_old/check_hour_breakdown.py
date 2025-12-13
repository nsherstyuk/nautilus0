#!/usr/bin/env python3
"""Check specific hour performance across all weekdays."""
import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).parent

# Get hour from command line or default to 3
hour = int(sys.argv[1]) if len(sys.argv) > 1 else 3

# Load matrices
results_dir = PROJECT_ROOT / "logs" / "backtest_results"
latest = sorted(results_dir.glob("MTF_ML_*"), reverse=True)[0]

df_pnl = pd.read_csv(latest / "hour_weekday_pnl_matrix.csv", index_col=0)
df_trades = pd.read_csv(latest / "hour_weekday_trades_matrix.csv", index_col=0)

print(f"\n{hour:02d}:00 UTC Performance by Weekday:")
print("="*60)
print(f"{'Weekday':<12} {'Trades':<10} {'P&L':<15}")
print("-"*60)

weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
total_pnl = 0
total_trades = 0

for day in weekdays:
    trades = int(df_trades.loc[hour, day])
    pnl = float(df_pnl.loc[hour, day])
    total_pnl += pnl
    total_trades += trades
    
    status = "✅" if pnl > 0 else "❌" if pnl < 0 else "➖"
    print(f"{day:<12} {trades:<10} ${pnl:>12,.2f}  {status}")

print("-"*60)
print(f"{'TOTAL':<12} {total_trades:<10} ${total_pnl:>12,.2f}")

# Summary
profitable_days = sum(1 for day in weekdays if float(df_pnl.loc[hour, day]) > 0)
losing_days = sum(1 for day in weekdays if float(df_pnl.loc[hour, day]) < 0)

print("\n" + "="*60)
print("SUMMARY")
print("="*60)
print(f"Profitable days: {profitable_days}/7")
print(f"Losing days: {losing_days}/7")

if total_pnl > 0:
    print(f"\n✅ Hour {hour:02d}:00 is PROFITABLE overall (${total_pnl:,.2f})")
else:
    print(f"\n❌ Hour {hour:02d}:00 is LOSING overall (${total_pnl:,.2f})")

if losing_days > profitable_days:
    print(f"⚠️  Bad on MOST days - consider excluding completely")
else:
    print(f"💡 Only bad on specific days:")
    for day in weekdays:
        pnl = float(df_pnl.loc[hour, day])
        trades = int(df_trades.loc[hour, day])
        if pnl < 0 and trades >= 3:
            print(f"   - {day}: ${pnl:,.2f} ({trades} trades)")
