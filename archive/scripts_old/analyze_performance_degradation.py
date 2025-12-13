"""
Analyze performance degradation over time to check if model is losing predictive power.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

# Load latest backtest results
results_dir = Path("logs/backtest_results/MTF_ML_20251128_202046")
trades_df = pd.read_csv(results_dir / "trades.csv")

# Convert to datetime
trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])

print("="*80)
print("PERFORMANCE DEGRADATION ANALYSIS")
print("="*80)

# Monthly performance
monthly = trades_df.groupby('entry_month').agg({
    'pnl': ['count', 'sum', 'mean', lambda x: (x > 0).sum() / len(x) * 100],
    'exit_reason': lambda x: (x == 'SL').sum() / len(x) * 100
}).round(2)
monthly.columns = ['Trades', 'Total P&L', 'Avg P&L', 'Win Rate %', 'SL Rate %']

print("\n" + "-"*80)
print("MONTHLY PERFORMANCE TREND")
print("-"*80)
print(monthly)

# Calculate rolling 3-month average
monthly_pnl = trades_df.groupby('entry_month')['pnl'].sum()
rolling_3m = monthly_pnl.rolling(window=3).mean()

print("\n" + "-"*80)
print("3-MONTH ROLLING AVERAGE P&L")
print("-"*80)
for month, pnl in rolling_3m.items():
    if not np.isnan(pnl):
        print(f"{month}: ${pnl:.2f}")

# Analyze recent degradation
print("\n" + "="*80)
print("RECENT PERFORMANCE ANALYSIS")
print("="*80)

months = ['2025-08', '2025-09', '2025-10', '2025-11']
recent = monthly.loc[months]
print("\nLast 4 months:")
print(recent)

# Calculate trend
print("\n" + "-"*80)
print("DEGRADATION METRICS")
print("-"*80)

# Compare Q2 vs Q3 vs Q4
q2_months = ['2025-04', '2025-05', '2025-06']
q3_months = ['2025-07', '2025-08', '2025-09']
q4_months = ['2025-10', '2025-11']

q2_pnl = monthly.loc[q2_months, 'Total P&L'].sum()
q3_pnl = monthly.loc[q3_months, 'Total P&L'].sum()
q4_pnl = monthly.loc[q4_months, 'Total P&L'].sum()

q2_avg = monthly.loc[q2_months, 'Total P&L'].mean()
q3_avg = monthly.loc[q3_months, 'Total P&L'].mean()
q4_avg = monthly.loc[q4_months, 'Total P&L'].mean()

print(f"\nQ2 (Apr-Jun): ${q2_pnl:.2f} total, ${q2_avg:.2f} avg/month")
print(f"Q3 (Jul-Sep): ${q3_pnl:.2f} total, ${q3_avg:.2f} avg/month")
print(f"Q4 (Oct-Nov): ${q4_pnl:.2f} total, ${q4_avg:.2f} avg/month")

print(f"\nQ3 vs Q2: {(q3_avg - q2_avg) / q2_avg * 100:.1f}% change")
print(f"Q4 vs Q3: {(q4_avg - q3_avg) / q3_avg * 100:.1f}% change")
print(f"Q4 vs Q2: {(q4_avg - q2_avg) / q2_avg * 100:.1f}% change")

# Win rate degradation
q2_wr = monthly.loc[q2_months, 'Win Rate %'].mean()
q3_wr = monthly.loc[q3_months, 'Win Rate %'].mean()
q4_wr = monthly.loc[q4_months, 'Win Rate %'].mean()

print(f"\nWin Rate:")
print(f"Q2: {q2_wr:.1f}%")
print(f"Q3: {q3_wr:.1f}%")
print(f"Q4: {q4_wr:.1f}%")
print(f"Degradation: {q4_wr - q2_wr:.1f} percentage points")

# Check if model predictions are getting worse
print("\n" + "="*80)
print("MODEL PREDICTION QUALITY OVER TIME")
print("="*80)

# Analyze by side (LONG vs SHORT)
print("\nPerformance by trade direction over time:")
for month in months:
    month_trades = trades_df[trades_df['entry_month'] == month]
    long_pnl = month_trades[month_trades['side'] == 'LONG']['pnl'].sum()
    short_pnl = month_trades[month_trades['side'] == 'SHORT']['pnl'].sum()
    long_wr = (month_trades[month_trades['side'] == 'LONG']['pnl'] > 0).sum() / len(month_trades[month_trades['side'] == 'LONG']) * 100
    short_wr = (month_trades[month_trades['side'] == 'SHORT']['pnl'] > 0).sum() / len(month_trades[month_trades['side'] == 'SHORT']) * 100
    print(f"\n{month}:")
    print(f"  LONG:  ${long_pnl:8.2f} (WR: {long_wr:.1f}%)")
    print(f"  SHORT: ${short_pnl:8.2f} (WR: {short_wr:.1f}%)")

# Market regime change detection
print("\n" + "="*80)
print("MARKET REGIME ANALYSIS")
print("="*80)

# Check if ATR (volatility) changed
print("\nNote: We don't have ATR data in trades.csv")
print("But we can check trade duration and P&L distribution changes")

for month in months:
    month_trades = trades_df[trades_df['entry_month'] == month]
    avg_duration = month_trades['duration_bars'].mean()
    avg_win = month_trades[month_trades['pnl'] > 0]['pnl'].mean()
    avg_loss = month_trades[month_trades['pnl'] < 0]['pnl'].mean()
    print(f"\n{month}:")
    print(f"  Avg duration: {avg_duration:.1f} bars")
    print(f"  Avg win: ${avg_win:.2f}")
    print(f"  Avg loss: ${avg_loss:.2f}")
    print(f"  Win/Loss ratio: {abs(avg_win / avg_loss):.2f}")

# Statistical significance test
print("\n" + "="*80)
print("STATISTICAL ANALYSIS")
print("="*80)

q2_trades = trades_df[trades_df['entry_month'].isin(q2_months)]['pnl']
q4_trades = trades_df[trades_df['entry_month'].isin(q4_months)]['pnl']

from scipy import stats
t_stat, p_value = stats.ttest_ind(q2_trades, q4_trades)

print(f"\nT-test comparing Q2 vs Q4 trade P&L:")
print(f"T-statistic: {t_stat:.3f}")
print(f"P-value: {p_value:.4f}")
if p_value < 0.05:
    print("✅ Statistically significant difference (p < 0.05)")
    print("⚠️  Model performance HAS degraded significantly")
else:
    print("❌ Not statistically significant (p >= 0.05)")
    print("✅ Degradation might just be normal variance")

# Final recommendation
print("\n" + "="*80)
print("RECOMMENDATION")
print("="*80)

if q4_avg < q2_avg * 0.3:  # Q4 is less than 30% of Q2
    print("\n🚨 CRITICAL: Performance degraded by >70%")
    print("Recommendations:")
    print("1. DO NOT deploy to live trading yet")
    print("2. Retrain model with recent data (2024-2025)")
    print("3. Check if market regime has changed")
    print("4. Consider adding regime detection features")
elif q4_avg < q2_avg * 0.5:  # Q4 is less than 50% of Q2
    print("\n⚠️  WARNING: Significant performance degradation")
    print("Recommendations:")
    print("1. Deploy with REDUCED position size (50%)")
    print("2. Monitor closely for 1-2 weeks")
    print("3. Plan model retraining with 2024-2025 data")
    print("4. Consider paper trading first")
else:
    print("\n✅ Performance degradation is within acceptable range")
    print("Recommendations:")
    print("1. Safe to deploy to live trading")
    print("2. Monitor performance weekly")
    print("3. Plan quarterly model retraining")
