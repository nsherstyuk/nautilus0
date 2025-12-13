import pandas as pd
from pathlib import Path

p = Path('logs/backtest_results/MTF_ML_20251127_202724')
df_pnl = pd.read_csv(p / 'hour_weekday_pnl_matrix.csv', index_col=0)
df_trades = pd.read_csv(p / 'hour_weekday_trades_matrix.csv', index_col=0)

print('\n03:00 UTC Performance by Weekday (2-Year Data):')
print('='*70)
print(f"{'Weekday':<12} {'Trades':<10} {'P&L':<15} {'Status'}")
print('-'*70)

weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
total_pnl = 0
total_trades = 0

for day in weekdays:
    trades = int(df_trades.loc[3, day])
    pnl = float(df_pnl.loc[3, day])
    total_pnl += pnl
    total_trades += trades
    
    status = "✅ KEEP" if pnl > 0 else "❌ EXCLUDE" if pnl < -100 and trades >= 5 else "⚠️  MARGINAL"
    print(f"{day:<12} {trades:<10} ${pnl:>12,.2f}  {status}")

print('-'*70)
print(f"{'TOTAL':<12} {total_trades:<10} ${total_pnl:>12,.2f}")

print('\n' + '='*70)
print('CURRENT EXCLUSIONS FOR 03:00:')
print('='*70)

# Check current exclusions
excluded_days = []
if 3 in [1,6,11,16,17,18]:  # Monday
    excluded_days.append('Monday')
if 3 in [1,2,5,6,14,15,18]:  # Tuesday
    excluded_days.append('Tuesday')
if 3 in [4,5,8,9,10]:  # Wednesday
    excluded_days.append('Wednesday')
if 3 in [2,4,7,9,10,11,15,17,18,20,23]:  # Thursday
    excluded_days.append('Thursday')
if 3 in [1,11,14,17]:  # Friday
    excluded_days.append('Friday')

if excluded_days:
    print(f"Currently excluded on: {', '.join(excluded_days)}")
else:
    print("Currently NOT excluded on any day")

print('\n' + '='*70)
print('RECOMMENDATION:')
print('='*70)

# Find days where it's significantly losing
bad_days = []
for day in weekdays:
    pnl = float(df_pnl.loc[3, day])
    trades = int(df_trades.loc[3, day])
    if pnl < -100 and trades >= 5:
        bad_days.append(day)

if bad_days:
    print(f"Exclude 03:00 on: {', '.join(bad_days)}")
    print(f"\nThese days have significant losses (>$100) with enough trades (>=5)")
else:
    print("Keep 03:00 on all days")
    print("No day has significant losses")

# Show what should be added
print('\n' + '='*70)
print('SUGGESTED .env.mtf CHANGES:')
print('='*70)

if 'Tuesday' in bad_days and 3 not in [1,2,5,6,14,15,18]:
    print("Add 3 to Tuesday exclusions:")
    print("MTF_EXCLUDED_HOURS_TUESDAY=1,2,3,5,6,14,15,18")

if 'Thursday' in bad_days and 3 not in [2,4,7,9,10,11,15,17,18,20,23]:
    print("Add 3 to Thursday exclusions:")
    print("MTF_EXCLUDED_HOURS_THURSDAY=2,3,4,7,9,10,11,15,17,18,20,23")

if 'Wednesday' in bad_days and 3 not in [4,5,8,9,10]:
    print("Add 3 to Wednesday exclusions:")
    print("MTF_EXCLUDED_HOURS_WEDNESDAY=3,4,5,8,9,10")
