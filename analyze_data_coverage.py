import pandas as pd
import pyarrow.parquet as pq
from datetime import datetime
from pathlib import Path

print("=" * 70)
print("BACKTEST DATE RANGE vs AVAILABLE DATA ANALYSIS")
print("=" * 70)

# Read backtest configuration
print("\n=== BACKTEST CONFIGURATION (.env) ===")
with open('.env', 'r') as f:
    for line in f:
        if 'BACKTEST_START_DATE' in line:
            backtest_start = line.split('=')[1].strip()
            print(f"Backtest Start: {backtest_start}")
        elif 'BACKTEST_END_DATE' in line:
            backtest_end = line.split('=')[1].strip()
            print(f"Backtest End:   {backtest_end}")

# Read actual data from parquet
print("\n=== AVAILABLE DATA (15-minute bars) ===")
parquet_file = 'data/historical/data/bar/EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL/2023-12-27T22-30-00-000000000Z_2025-10-30T04-00-00-000000000Z.parquet'

if not Path(parquet_file).exists():
    print(f"ERROR: File not found: {parquet_file}")
    exit(1)

df = pq.read_table(parquet_file).to_pandas()
print(f"Total bars: {len(df):,}")

# Convert timestamps to datetime
df['datetime'] = pd.to_datetime(df['ts_init'], unit='ns')
first_bar = df['datetime'].min()
last_bar = df['datetime'].max()

print(f"First bar:  {first_bar}")
print(f"Last bar:   {last_bar}")
print(f"Days span:  {(last_bar - first_bar).days} days")

# Compare with backtest range
backtest_start_dt = pd.to_datetime(backtest_start)
backtest_end_dt = pd.to_datetime(backtest_end)

print("\n=== COMPARISON ===")
print(f"Backtest wants:  {backtest_start_dt.date()} to {backtest_end_dt.date()} ({(backtest_end_dt - backtest_start_dt).days} days)")
print(f"Data available:  {first_bar.date()} to {last_bar.date()} ({(last_bar - first_bar).days} days)")

# Check coverage
if first_bar.date() > backtest_start_dt.date():
    missing_days = (first_bar.date() - backtest_start_dt.date()).days
    print(f"\n⚠️  MISSING DATA AT START: {missing_days} days")
    print(f"   Backtest starts: {backtest_start_dt.date()}")
    print(f"   Data starts:     {first_bar.date()}")
    print(f"   Gap: {backtest_start_dt.date()} to {first_bar.date()}")
else:
    extra_days = (backtest_start_dt.date() - first_bar.date()).days
    print(f"\n✅ Extra data before backtest start: {extra_days} days")

if last_bar.date() < backtest_end_dt.date():
    missing_days = (backtest_end_dt.date() - last_bar.date()).days
    print(f"\n⚠️  MISSING DATA AT END: {missing_days} days")
    print(f"   Backtest ends: {backtest_end_dt.date()}")
    print(f"   Data ends:     {last_bar.date()}")
    print(f"   Gap: {last_bar.date()} to {backtest_end_dt.date()}")
else:
    print(f"\n✅ Data covers entire backtest period")

# Check for gaps within the data range
print("\n=== CHECKING FOR GAPS IN DATA ===")
df['date'] = df['datetime'].dt.date
unique_dates = df['date'].unique()
print(f"Unique trading days in data: {len(unique_dates)}")

# Generate expected date range (forex trades 5 days/week, excluding major holidays)
all_dates = pd.date_range(first_bar.date(), last_bar.date(), freq='D')
weekdays = [d for d in all_dates if d.weekday() < 5]  # Mon-Fri only

missing_weekdays = [d.date() for d in weekdays if d.date() not in unique_dates]
if missing_weekdays:
    print(f"\n⚠️  Missing {len(missing_weekdays)} weekdays (likely holidays/closed days):")
    if len(missing_weekdays) <= 15:
        for date in missing_weekdays:
            print(f"   - {date} ({pd.Timestamp(date).strftime('%A')})")
    else:
        print(f"   First 10:")
        for date in missing_weekdays[:10]:
            print(f"   - {date} ({pd.Timestamp(date).strftime('%A')})")
        print(f"   ... and {len(missing_weekdays) - 10} more")
else:
    print("✅ No unexpected gaps in weekday data")

# Summary
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
actual_start = max(first_bar.date(), backtest_start_dt.date())
actual_end = min(last_bar.date(), backtest_end_dt.date())
effective_days = (actual_end - actual_start).days
print(f"Effective backtest period: {actual_start} to {actual_end}")
print(f"Effective days: {effective_days} days")
print(f"Data completeness: {len(unique_dates) / len(weekdays) * 100:.1f}% of expected weekdays")
