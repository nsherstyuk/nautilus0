"""
Analyze why days had no trades - distinguish between:
1. No EMA crossings (no signals generated)
2. EMA crossings occurred but were filtered out
"""
import sys
import pandas as pd
from pathlib import Path
from collections import Counter
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Phase 6 backtest directory
backtest_dir = Path("logs/backtest_results/EUR-USD_20251024_193923_202202")

print("=" * 100)
print("PHASE 6 - SIGNAL GENERATION vs FILTER ANALYSIS")
print("=" * 100)
print()

# Load positions and rejected signals
positions_file = backtest_dir / "positions.csv"
rejected_file = backtest_dir / "rejected_signals.csv"

if not positions_file.exists():
    print(f"Error: positions.csv not found")
    sys.exit(1)

if not rejected_file.exists():
    print(f"Error: rejected_signals.csv not found")
    sys.exit(1)

df_positions = pd.read_csv(positions_file)
df_rejected = pd.read_csv(rejected_file)

# Parse dates
df_positions["ts_opened"] = pd.to_datetime(df_positions["ts_opened"])
df_positions["trade_date"] = df_positions["ts_opened"].dt.date

df_rejected["timestamp"] = pd.to_datetime(df_rejected["timestamp"])
df_rejected["bar_close_time"] = pd.to_datetime(df_rejected["bar_close_time"])
df_rejected["signal_date"] = df_rejected["timestamp"].dt.date

# Get date range
min_date = min(df_positions["trade_date"].min(), df_rejected["signal_date"].min()) if len(df_rejected) > 0 else df_positions["trade_date"].min()
max_date = max(df_positions["trade_date"].max(), df_rejected["signal_date"].max()) if len(df_rejected) > 0 else df_positions["trade_date"].max()
all_dates = pd.date_range(start=min_date, end=max_date, freq='D').date

# Days with trades
days_with_trades = set(df_positions["trade_date"].unique())

# Days with rejected signals (but no trades)
days_with_rejected_signals = set(df_rejected["signal_date"].unique())

# Days with any signals (trades or rejected)
days_with_any_signals = days_with_trades | days_with_rejected_signals

# Days with NO signals at all
days_with_no_signals = set(all_dates) - days_with_any_signals

# Days with signals but no trades (all filtered out)
days_with_signals_but_no_trades = days_with_rejected_signals - days_with_trades

print(f"Backtest Period: {min_date} to {max_date}")
print(f"Total Days: {len(all_dates)}")
print()

print("=" * 100)
print("SIGNAL GENERATION ANALYSIS")
print("=" * 100)
print()

print(f"Days WITH Any Signals (EMA crossings occurred): {len(days_with_any_signals)} ({100*len(days_with_any_signals)/len(all_dates):.1f}%)")
print(f"  - Days with executed trades: {len(days_with_trades)}")
print(f"  - Days with signals but all filtered: {len(days_with_signals_but_no_trades)}")
print()
print(f"Days WITH NO Signals (no EMA crossings): {len(days_with_no_signals)} ({100*len(days_with_no_signals)/len(all_dates):.1f}%)")
print()

print("=" * 100)
print("FILTER REJECTION ANALYSIS")
print("=" * 100)
print()

# Analyze rejection reasons
rejection_reasons = df_rejected["reason"].value_counts()
print("Rejection Reasons Breakdown:")
print()
for reason, count in rejection_reasons.items():
    percentage = 100 * count / len(df_rejected)
    print(f"  {reason}: {count} ({percentage:.1f}%)")
print()

# Categorize rejection reasons
threshold_rejections = len(df_rejected[df_rejected["reason"].str.contains("crossover_threshold", na=False)])
dmi_rejections = len(df_rejected[df_rejected["reason"].str.contains("dmi_trend_mismatch", na=False)])
stoch_rejections = len(df_rejected[df_rejected["reason"].str.contains("stochastic_unfavorable", na=False)])
close_only = len(df_rejected[df_rejected["reason"].str.contains("close_only", na=False)])

print("Filter Categories:")
print(f"  Crossover Threshold Filter: {threshold_rejections} rejections ({100*threshold_rejections/len(df_rejected):.1f}%)")
print(f"  DMI Trend Filter: {dmi_rejections} rejections ({100*dmi_rejections/len(df_rejected):.1f}%)")
print(f"  Stochastic Filter: {stoch_rejections} rejections ({100*stoch_rejections/len(df_rejected):.1f}%)")
print(f"  Close-Only (position open): {close_only} ({100*close_only/len(df_rejected):.1f}%)")
print()

print("=" * 100)
print("DAILY BREAKDOWN")
print("=" * 100)
print()

# Count signals per day
signals_per_day = df_rejected.groupby("signal_date").size()
trades_per_day = df_positions.groupby("trade_date").size()

print("Days with Signals but No Trades (all filtered):")
filtered_days = sorted(days_with_signals_but_no_trades)[:20]
for day in filtered_days:
    signal_count = signals_per_day.get(day, 0)
    print(f"  {day}: {signal_count} signal(s) rejected")
if len(days_with_signals_but_no_trades) > 20:
    print(f"  ... and {len(days_with_signals_but_no_trades) - 20} more days")
print()

print("Days with NO Signals at all (no EMA crossings):")
no_signal_days = sorted(days_with_no_signals)[:20]
for day in no_signal_days:
    print(f"  {day}")
if len(days_with_no_signals) > 20:
    print(f"  ... and {len(days_with_no_signals) - 20} more days")
print()

print("=" * 100)
print("SUMMARY")
print("=" * 100)
print()

total_days_no_trades = len(all_dates) - len(days_with_trades)
print(f"Total days with NO TRADES: {total_days_no_trades}")
print(f"  - Due to NO EMA crossings: {len(days_with_no_signals)} ({100*len(days_with_no_signals)/total_days_no_trades:.1f}%)")
print(f"  - Due to FILTER rejections: {len(days_with_signals_but_no_trades)} ({100*len(days_with_signals_but_no_trades)/total_days_no_trades:.1f}%)")
print()

print("=" * 100)

