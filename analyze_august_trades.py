"""
Analyze why August 2025 had fewer trades in the backtest.
"""
import pandas as pd
import sys
from pathlib import Path

backtest_folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("backtest_results/MTF_V2_REPLAY_20251227_123947")

print(f"\n{'='*60}")
print(f"Analyzing: {backtest_folder.name}")
print(f"{'='*60}\n")

# Load trades
trades = pd.read_csv(backtest_folder / "trades.csv")
trades['entry_time'] = pd.to_datetime(trades['entry_time'], utc=True)
trades['exit_time'] = pd.to_datetime(trades['exit_time'], utc=True)
trades['month'] = trades['entry_time'].dt.to_period('M')
trades['weekday'] = trades['entry_time'].dt.day_name()
trades['hour_utc'] = trades['entry_time'].dt.hour

# Monthly breakdown
print("📊 Monthly Trade Count:")
print(trades.groupby('month').size().to_string())
print()

# August details
august_trades = trades[trades['entry_time'].dt.month == 8]
print(f"\n📅 August 2025 Analysis:")
print(f"   Total trades: {len(august_trades)}")
print(f"   Total P&L: ${august_trades['pnl'].sum():.2f}")
print(f"   Win rate: {(august_trades['pnl'] > 0).sum() / len(august_trades) * 100:.1f}%")
print()

# August by weekday
print("   Trades by weekday:")
aug_weekday = august_trades.groupby('weekday').agg({
    'pnl': ['count', 'sum']
}).round(2)
print(aug_weekday.to_string())
print()

# Compare with other months
comparison = trades[trades['entry_time'].dt.month.isin([7, 8, 9])].groupby('month').agg({
    'pnl': ['count', 'sum', 'mean'],
    'entry_time': ['min', 'max']
})
comparison.columns = ['_'.join(col).strip() for col in comparison.columns.values]
print("\n📊 Comparison with neighboring months:")
print(comparison.to_string())
print()

# Check for data gaps in August
all_months = trades.groupby('month').agg({
    'entry_time': ['min', 'max', 'count']
})
all_months.columns = ['first_trade', 'last_trade', 'count']
print("\n📅 Data coverage by month:")
print(all_months.to_string())
print()

# August calendar days with trades
august_days = august_trades['entry_time'].dt.date.unique()
print(f"\n📆 August trading days: {len(august_days)} days")
print(f"   First trade: {august_trades['entry_time'].min()}")
print(f"   Last trade: {august_trades['entry_time'].max()}")
print()

# Check if there's a big gap
august_dates = pd.date_range('2025-08-01', '2025-08-31', freq='D')
trading_dates = set(august_trades['entry_time'].dt.date)
missing_dates = [d.date() for d in august_dates if d.date() not in trading_dates]
if missing_dates:
    print(f"⚠️  Days with NO trades in August: {len(missing_dates)} days")
    if len(missing_dates) <= 10:
        for d in missing_dates:
            print(f"     {d}")
    else:
        print(f"     First 5: {missing_dates[:5]}")
        print(f"     Last 5: {missing_dates[-5:]}")
    print()

# Load replay log to check for bars processed in August
log_file = backtest_folder / "replay.log"
if log_file.exists():
    print("\n📜 Checking replay log for August bar processing...")
    with open(log_file, 'r') as f:
        august_lines = [line for line in f if '2025-08-' in line and 'BAR_METRICS' in line]
    
    if august_lines:
        # Count unique timestamps
        import re
        timestamps = set()
        for line in august_lines:
            match = re.search(r'2025-08-\d{2} \d{2}:\d{2}', line)
            if match:
                timestamps.add(match.group())
        
        print(f"   ✓ Found {len(august_lines)} BAR_METRICS entries")
        print(f"   ✓ Unique timestamps: {len(timestamps)}")
        
        # Sample a few lines to check confidence
        print("\n   Sample bars (first 5):")
        for i, line in enumerate(august_lines[:5]):
            if 'conf=' in line:
                match = re.search(r'conf=(\d+\.\d+).*thresh=(\d+\.\d+)', line)
                if match:
                    conf, thresh = match.groups()
                    timestamp = re.search(r'2025-08-\d{2} \d{2}:\d{2}:\d{2}', line).group()
                    print(f"     {timestamp}: conf={conf} (threshold={thresh})")
    else:
        print("   ⚠️  No BAR_METRICS entries found for August")
print()

# Final diagnosis
print("\n🔍 DIAGNOSIS:")
if len(august_trades) < 50:
    print(f"   August has significantly fewer trades ({len(august_trades)}) compared to other months")
    if missing_dates and len(missing_dates) > 20:
        print(f"   ⚠️  Possible data gap: {len(missing_dates)} days with no trades")
        print(f"   → Check if bar data exists for entire August period")
    else:
        print(f"   → Bars are being processed, but confidence is below threshold")
        print(f"   → Average confidence in August is likely < 0.68 (the threshold)")
        print(f"   → This could be due to:")
        print(f"      - Model uncertainty during August market conditions")
        print(f"      - Lower volatility or unclear trends")
        print(f"      - Summer trading slowdown")
else:
    print(f"   August trade count ({len(august_trades)}) appears normal")

print()
