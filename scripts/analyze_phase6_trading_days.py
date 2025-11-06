"""
Analyze Phase 6 backtest trading days.
"""
import sys
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Phase 6 run_id 21 backtest directory
backtest_dir = Path("logs/backtest_results/EUR-USD_20251024_193923_202202")

print("=" * 100)
print("PHASE 6 SETUP - TRADING DAYS ANALYSIS")
print("=" * 100)
print()

if not backtest_dir.exists():
    print(f"Error: Backtest directory not found: {backtest_dir}")
    sys.exit(1)

positions_file = backtest_dir / "positions.csv"
if not positions_file.exists():
    print(f"Error: positions.csv not found in {backtest_dir}")
    sys.exit(1)

df = pd.read_csv(positions_file)

if len(df) == 0:
    print("No trades found in Phase 6 backtest!")
    sys.exit(1)

# Convert timestamps to datetime
df["ts_opened"] = pd.to_datetime(df["ts_opened"])
df["trade_date"] = df["ts_opened"].dt.date

# Get date range
min_date = df["trade_date"].min()
max_date = df["trade_date"].max()
all_dates = pd.date_range(start=min_date, end=max_date, freq='D').date

# Count days with trades vs no trades
dates_with_trades = set(df["trade_date"].unique())
dates_without_trades = set(all_dates) - dates_with_trades
total_days = len(all_dates)

print(f"Backtest Directory: {backtest_dir.name}")
print(f"Backtest Period: {min_date} to {max_date}")
print(f"Total Days: {total_days}")
print(f"Total Trades: {len(df)}")
print()

print(f"Days WITH Trades: {len(dates_with_trades)} ({100*len(dates_with_trades)/total_days:.1f}%)")
print(f"Days WITHOUT Trades: {len(dates_without_trades)} ({100*len(dates_without_trades)/total_days:.1f}%)")
print()

# Show trade distribution
trades_per_day = df.groupby("trade_date").size()
print(f"Trade Distribution:")
print(f"  Average trades per day: {trades_per_day.mean():.1f}")
print(f"  Max trades in a single day: {trades_per_day.max()}")
print(f"  Min trades in a single day: {trades_per_day.min()}")
print()

# Count days by trade frequency
trade_counts = {}
for count in trades_per_day.values:
    trade_counts[count] = trade_counts.get(count, 0) + 1

print("Days by Trade Count:")
for count in sorted(trade_counts.keys()):
    print(f"  {count} trade(s): {trade_counts[count]} day(s)")

print()
print("=" * 100)
