"""
Analyze profitability by trading hour from latest backtest results.
"""
from pathlib import Path
import pandas as pd
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Find latest backtest results
results_dir = Path("logs/backtest_results")
dirs = [d for d in results_dir.iterdir() if d.is_dir() and "EUR-USD_" in d.name]
if not dirs:
    print("No backtest results found!")
    sys.exit(1)

latest_dir = max(dirs, key=lambda d: d.stat().st_mtime)
print(f"Analyzing backtest: {latest_dir.name}\n")

# Load positions data
positions_file = latest_dir / "positions.csv"
if not positions_file.exists():
    print(f"Positions file not found: {positions_file}")
    sys.exit(1)

positions_df = pd.read_csv(positions_file)

# Convert timestamps to datetime
positions_df["ts_opened"] = pd.to_datetime(positions_df["ts_opened"])
positions_df["ts_closed"] = pd.to_datetime(positions_df["ts_closed"])

# Extract PnL (remove currency suffix)
def extract_pnl(value):
    if pd.isna(value):
        return 0.0
    value_str = str(value)
    # Remove currency suffix (e.g., "494.87 USD" -> 494.87)
    import re
    cleaned = re.sub(r'\s*[A-Z]{3}\s*$', '', value_str)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

positions_df["realized_pnl_value"] = positions_df["realized_pnl"].apply(extract_pnl)

# Extract hour from entry time (ts_opened)
positions_df["entry_hour"] = positions_df["ts_opened"].dt.hour

# Group by hour and calculate statistics
hourly_stats = positions_df.groupby("entry_hour").agg({
    "realized_pnl_value": ["sum", "mean", "count"],
}).round(2)

hourly_stats.columns = ["Total_PnL", "Avg_PnL", "Trade_Count"]
hourly_stats = hourly_stats.sort_values("Total_PnL")

print("=" * 80)
print("PROFITABILITY BY TRADING HOUR (UTC)")
print("=" * 80)
print()
print(f"{'Hour':<6} {'Total PnL':<12} {'Avg PnL':<12} {'Trade Count':<12} {'Status':<15}")
print("-" * 80)

unprofitable_hours = []
for hour in range(24):
    hour_data = hourly_stats.loc[hour] if hour in hourly_stats.index else None
    if hour_data is not None:
        total_pnl = hour_data["Total_PnL"]
        avg_pnl = hour_data["Avg_PnL"]
        count = int(hour_data["Trade_Count"])
        status = "PROFITABLE" if total_pnl > 0 else "UNPROFITABLE"
        if total_pnl < 0:
            unprofitable_hours.append(hour)
        print(f"{hour:02d}:00  ${total_pnl:>10.2f}  ${avg_pnl:>10.2f}  {count:>11}  {status}")
    else:
        print(f"{hour:02d}:00  ${0:>10.2f}  ${0:>10.2f}  {0:>11}  NO TRADES")

print()
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Total trades: {len(positions_df)}")
print(f"Total PnL: ${positions_df['realized_pnl_value'].sum():.2f}")
print(f"Profitable hours: {24 - len(unprofitable_hours)}")
print(f"Unprofitable hours: {len(unprofitable_hours)}")
if unprofitable_hours:
    print(f"\nUnprofitable hours: {sorted(unprofitable_hours)}")
    print(f"\nRecommendation: Consider excluding these hours:")
    print(f"  BACKTEST_EXCLUDED_HOURS={','.join(map(str, sorted(unprofitable_hours)))}")
else:
    print("\nAll hours are profitable!")

print()
print("=" * 80)

