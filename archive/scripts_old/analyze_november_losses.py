"""
Analyze November losses and hour 17 performance by weekday.
"""
import pandas as pd
import numpy as np
from pathlib import Path

# Load latest backtest results
results_dir = Path("logs/backtest_results/MTF_ML_20251128_202046")
trades_df = pd.read_csv(results_dir / "trades.csv")

# Convert to datetime
trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])

print("="*80)
print("NOVEMBER 2025 ANALYSIS")
print("="*80)

# Filter November trades
nov_trades = trades_df[trades_df['entry_month'] == '2025-11'].copy()
print(f"\nTotal November trades: {len(nov_trades)}")
print(f"November P&L: ${nov_trades['pnl'].sum():.2f}")
print(f"Win rate: {(nov_trades['pnl'] > 0).sum() / len(nov_trades) * 100:.1f}%")

# Analyze by exit reason
print("\n" + "-"*80)
print("NOVEMBER TRADES BY EXIT REASON")
print("-"*80)
exit_analysis = nov_trades.groupby('exit_reason').agg({
    'pnl': ['count', 'sum', 'mean'],
}).round(2)
exit_analysis.columns = ['Count', 'Total P&L', 'Avg P&L']
print(exit_analysis)

# Analyze by hour
print("\n" + "-"*80)
print("NOVEMBER TRADES BY HOUR")
print("-"*80)
hour_analysis = nov_trades.groupby('entry_hour').agg({
    'pnl': ['count', 'sum', 'mean'],
}).round(2)
hour_analysis.columns = ['Count', 'Total P&L', 'Avg P&L']
hour_analysis = hour_analysis.sort_values('Total P&L', ascending=False)
print(hour_analysis.head(10))
print("\nWorst hours:")
print(hour_analysis.tail(5))

# Analyze by weekday
print("\n" + "-"*80)
print("NOVEMBER TRADES BY WEEKDAY")
print("-"*80)
weekday_names = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}
nov_trades['weekday_name'] = nov_trades['entry_weekday'].map(weekday_names)
weekday_analysis = nov_trades.groupby('weekday_name').agg({
    'pnl': ['count', 'sum', 'mean'],
}).round(2)
weekday_analysis.columns = ['Count', 'Total P&L', 'Avg P&L']
print(weekday_analysis)

print("\n" + "="*80)
print("HOUR 17 ANALYSIS BY WEEKDAY (ALL MONTHS)")
print("="*80)

# Filter hour 17 trades across all months
hour_17_trades = trades_df[trades_df['entry_hour'] == 17].copy()
hour_17_trades['weekday_name'] = hour_17_trades['entry_weekday'].map(weekday_names)

print(f"\nTotal hour 17 trades: {len(hour_17_trades)}")
print(f"Hour 17 total P&L: ${hour_17_trades['pnl'].sum():.2f}")
print(f"Hour 17 win rate: {(hour_17_trades['pnl'] > 0).sum() / len(hour_17_trades) * 100:.1f}%")

print("\n" + "-"*80)
print("HOUR 17 PERFORMANCE BY WEEKDAY")
print("-"*80)
hour_17_by_weekday = hour_17_trades.groupby('weekday_name').agg({
    'pnl': ['count', 'sum', 'mean', lambda x: (x > 0).sum() / len(x) * 100]
}).round(2)
hour_17_by_weekday.columns = ['Count', 'Total P&L', 'Avg P&L', 'Win Rate %']
hour_17_by_weekday = hour_17_by_weekday.sort_values('Total P&L', ascending=False)
print(hour_17_by_weekday)

# Check if any weekday is profitable at hour 17
print("\n" + "-"*80)
print("HOUR 17 RECOMMENDATION")
print("-"*80)
profitable_days = hour_17_by_weekday[hour_17_by_weekday['Total P&L'] > 0]
if len(profitable_days) > 0:
    print(f"✅ Hour 17 is PROFITABLE on these days:")
    for day in profitable_days.index:
        pnl = hour_17_by_weekday.loc[day, 'Total P&L']
        count = hour_17_by_weekday.loc[day, 'Count']
        print(f"   - {day}: ${pnl:.2f} ({int(count)} trades)")
    print(f"\n❌ Hour 17 is LOSING on these days:")
    losing_days = hour_17_by_weekday[hour_17_by_weekday['Total P&L'] <= 0]
    for day in losing_days.index:
        pnl = hour_17_by_weekday.loc[day, 'Total P&L']
        count = hour_17_by_weekday.loc[day, 'Count']
        print(f"   - {day}: ${pnl:.2f} ({int(count)} trades)")
else:
    print("❌ Hour 17 is LOSING on ALL weekdays")
    print("Recommendation: Exclude hour 17 from all trading days")

# Worst losing trades in November
print("\n" + "="*80)
print("TOP 10 WORST NOVEMBER TRADES")
print("="*80)
worst_trades = nov_trades.nsmallest(10, 'pnl')[['entry_time', 'side', 'entry_hour', 'weekday_name', 'pnl', 'exit_reason', 'duration_bars']]
worst_trades['pnl'] = worst_trades['pnl'].round(2)
print(worst_trades.to_string(index=False))

# Best winning trades in November
print("\n" + "="*80)
print("TOP 10 BEST NOVEMBER TRADES")
print("="*80)
best_trades = nov_trades.nlargest(10, 'pnl')[['entry_time', 'side', 'entry_hour', 'weekday_name', 'pnl', 'exit_reason', 'duration_bars']]
best_trades['pnl'] = best_trades['pnl'].round(2)
print(best_trades.to_string(index=False))

# Calculate impact of excluding hour 17
print("\n" + "="*80)
print("IMPACT OF EXCLUDING HOUR 17")
print("="*80)
hour_17_pnl = trades_df[trades_df['entry_hour'] == 17]['pnl'].sum()
total_pnl = trades_df['pnl'].sum()
print(f"Current total P&L: ${total_pnl:.2f}")
print(f"Hour 17 P&L: ${hour_17_pnl:.2f}")
print(f"P&L without hour 17: ${total_pnl - hour_17_pnl:.2f}")
print(f"Improvement: ${-hour_17_pnl:.2f} ({-hour_17_pnl / total_pnl * 100:.1f}%)")

# Check hour 20 as well (also negative in summary)
hour_20_trades = trades_df[trades_df['entry_hour'] == 20].copy()
hour_20_trades['weekday_name'] = hour_20_trades['entry_weekday'].map(weekday_names)
print("\n" + "="*80)
print("HOUR 20 ANALYSIS BY WEEKDAY")
print("="*80)
print(f"Total hour 20 trades: {len(hour_20_trades)}")
print(f"Hour 20 total P&L: ${hour_20_trades['pnl'].sum():.2f}")
hour_20_by_weekday = hour_20_trades.groupby('weekday_name').agg({
    'pnl': ['count', 'sum', 'mean']
}).round(2)
hour_20_by_weekday.columns = ['Count', 'Total P&L', 'Avg P&L']
print(hour_20_by_weekday.sort_values('Total P&L', ascending=False))
