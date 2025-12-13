#!/usr/bin/env python3
"""Compare two backtest results."""
import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).parent

# Get the two most recent MTF backtest folders
results_dir = PROJECT_ROOT / "logs" / "backtest_results"
mtf_folders = sorted(results_dir.glob("MTF_ML_*"), reverse=True)

if len(mtf_folders) < 2:
    print("❌ Need at least 2 backtest results to compare!")
    sys.exit(1)

# Load the two most recent
backtest1 = mtf_folders[0]
backtest2 = mtf_folders[1]

print("="*80)
print("BACKTEST COMPARISON")
print("="*80)
print(f"\nBacktest 1 (Most Recent): {backtest1.name}")
print(f"Backtest 2 (Previous):    {backtest2.name}")

# Load summaries
summary1 = backtest1 / "summary.txt"
summary2 = backtest2 / "summary.txt"

if summary1.exists():
    with open(summary1) as f:
        lines1 = f.readlines()
else:
    print(f"❌ Summary not found for {backtest1.name}")
    sys.exit(1)

if summary2.exists():
    with open(summary2) as f:
        lines2 = f.readlines()
else:
    print(f"❌ Summary not found for {backtest2.name}")
    sys.exit(1)

# Extract key metrics
def extract_metrics(lines):
    metrics = {}
    for line in lines:
        if "Total Trades:" in line:
            metrics['trades'] = int(line.split(":")[1].strip())
        elif "Total P&L:" in line:
            pnl_str = line.split(":")[1].strip().replace("$", "").replace(",", "")
            metrics['pnl'] = float(pnl_str)
        elif "Win Rate:" in line:
            wr_str = line.split(":")[1].strip().replace("%", "")
            metrics['win_rate'] = float(wr_str)
    return metrics

metrics1 = extract_metrics(lines1)
metrics2 = extract_metrics(lines2)

# Load trade details
trades1 = pd.read_csv(backtest1 / "trades.csv")
trades2 = pd.read_csv(backtest2 / "trades.csv")

# Get date ranges
trades1['entry_time'] = pd.to_datetime(trades1['entry_time'])
trades2['entry_time'] = pd.to_datetime(trades2['entry_time'])

date_range1 = f"{trades1['entry_time'].min().date()} to {trades1['entry_time'].max().date()}"
date_range2 = f"{trades2['entry_time'].min().date()} to {trades2['entry_time'].max().date()}"

# Calculate additional metrics
avg_pnl1 = metrics1['pnl'] / metrics1['trades']
avg_pnl2 = metrics2['pnl'] / metrics2['trades']

winning_trades1 = len(trades1[trades1['pnl'] > 0])
losing_trades1 = len(trades1[trades1['pnl'] <= 0])
winning_trades2 = len(trades2[trades2['pnl'] > 0])
losing_trades2 = len(trades2[trades2['pnl'] <= 0])

avg_win1 = trades1[trades1['pnl'] > 0]['pnl'].mean()
avg_loss1 = trades1[trades1['pnl'] <= 0]['pnl'].mean()
avg_win2 = trades2[trades2['pnl'] > 0]['pnl'].mean()
avg_loss2 = trades2[trades2['pnl'] <= 0]['pnl'].mean()

# Print comparison
print("\n" + "="*80)
print("COMPARISON REPORT")
print("="*80)

print(f"\n{'Metric':<25} {'Backtest 1 (New)':<25} {'Backtest 2 (Old)':<25} {'Change':<15}")
print("-"*90)

print(f"{'Date Range':<25} {date_range1:<25} {date_range2:<25} {'-':<15}")
print(f"{'Total Trades':<25} {metrics1['trades']:<25} {metrics2['trades']:<25} {metrics1['trades'] - metrics2['trades']:<15}")
print(f"{'Total P&L':<25} ${metrics1['pnl']:>23,.2f} ${metrics2['pnl']:>23,.2f} ${metrics1['pnl'] - metrics2['pnl']:>13,.2f}")
print(f"{'Win Rate':<25} {metrics1['win_rate']:>23.1f}% {metrics2['win_rate']:>23.1f}% {metrics1['win_rate'] - metrics2['win_rate']:>13.1f}%")
print(f"{'Avg P&L per Trade':<25} ${avg_pnl1:>23,.2f} ${avg_pnl2:>23,.2f} ${avg_pnl1 - avg_pnl2:>13,.2f}")
print(f"{'Winning Trades':<25} {winning_trades1:<25} {winning_trades2:<25} {winning_trades1 - winning_trades2:<15}")
print(f"{'Losing Trades':<25} {losing_trades1:<25} {losing_trades2:<25} {losing_trades1 - losing_trades2:<15}")
print(f"{'Avg Win':<25} ${avg_win1:>23,.2f} ${avg_win2:>23,.2f} ${avg_win1 - avg_win2:>13,.2f}")
print(f"{'Avg Loss':<25} ${avg_loss1:>23,.2f} ${avg_loss2:>23,.2f} ${avg_loss1 - avg_loss2:>13,.2f}")

# Calculate profit factor
gross_profit1 = trades1[trades1['pnl'] > 0]['pnl'].sum()
gross_loss1 = abs(trades1[trades1['pnl'] <= 0]['pnl'].sum())
profit_factor1 = gross_profit1 / gross_loss1 if gross_loss1 > 0 else 0

gross_profit2 = trades2[trades2['pnl'] > 0]['pnl'].sum()
gross_loss2 = abs(trades2[trades2['pnl'] <= 0]['pnl'].sum())
profit_factor2 = gross_profit2 / gross_loss2 if gross_loss2 > 0 else 0

print(f"{'Profit Factor':<25} {profit_factor1:>23.2f} {profit_factor2:>23.2f} {profit_factor1 - profit_factor2:>13.2f}")

# Analysis
print("\n" + "="*80)
print("ANALYSIS")
print("="*80)

pnl_change = metrics1['pnl'] - metrics2['pnl']
pnl_pct_change = (pnl_change / metrics2['pnl']) * 100 if metrics2['pnl'] != 0 else 0
trades_change = metrics1['trades'] - metrics2['trades']
trades_pct_change = (trades_change / metrics2['trades']) * 100 if metrics2['trades'] != 0 else 0

print(f"\nP&L Change: ${pnl_change:,.2f} ({pnl_pct_change:+.1f}%)")
print(f"Trades Change: {trades_change:,} ({trades_pct_change:+.1f}%)")
print(f"Win Rate Change: {metrics1['win_rate'] - metrics2['win_rate']:+.1f}%")

if pnl_change > 0:
    print(f"\n✅ Backtest 1 is BETTER by ${pnl_change:,.2f}")
elif pnl_change < 0:
    print(f"\n⚠️  Backtest 1 is WORSE by ${abs(pnl_change):,.2f}")
else:
    print(f"\n➖ Both backtests have the same P&L")

# Check if they're testing the same period
if date_range1 == date_range2:
    print(f"\n📅 Same testing period: {date_range1}")
else:
    print(f"\n⚠️  DIFFERENT testing periods!")
    print(f"   Backtest 1: {date_range1}")
    print(f"   Backtest 2: {date_range2}")

print("\n" + "="*80)
print("EXCLUSION IMPACT")
print("="*80)

# Try to determine what changed
if trades_change < 0:
    print(f"\n{abs(trades_change)} fewer trades in Backtest 1")
    print(f"This suggests MORE hour exclusions were applied")
    excluded_pnl = metrics2['pnl'] - metrics1['pnl']
    excluded_avg = excluded_pnl / abs(trades_change) if trades_change != 0 else 0
    print(f"Average P&L of excluded trades: ${excluded_avg:,.2f}")
    
    if excluded_avg < 0:
        print(f"✅ Good! Excluded trades were losing (${excluded_avg:,.2f} avg)")
    else:
        print(f"⚠️  Warning! Excluded trades were winning (${excluded_avg:,.2f} avg)")
elif trades_change > 0:
    print(f"\n{trades_change} more trades in Backtest 1")
    print(f"This suggests FEWER hour exclusions were applied")
else:
    print(f"\nSame number of trades - exclusions may have changed but net effect is zero")

print("\n" + "="*80)
