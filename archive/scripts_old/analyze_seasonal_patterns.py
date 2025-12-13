"""
Analyze if EUR/USD shows seasonal patterns that could explain model performance.
Test if models trained on specific months perform better on those same months.
"""
import pandas as pd
import numpy as np
from pathlib import Path

# Load backtest trades
results_dir = Path("logs/backtest_results/MTF_ML_20251128_202046")
trades_df = pd.read_csv(results_dir / "trades.csv")
trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])

print("="*80)
print("SEASONAL PATTERN ANALYSIS")
print("="*80)

# Extract month from entry_time
trades_df['month_num'] = trades_df['entry_time'].dt.month
trades_df['year'] = trades_df['entry_time'].dt.year

# Month names
month_names = {1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
               7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'}

print("\n" + "-"*80)
print("PERFORMANCE BY CALENDAR MONTH (2025)")
print("-"*80)

monthly_2025 = trades_df[trades_df['year'] == 2025].groupby('month_num').agg({
    'pnl': ['count', 'sum', 'mean', lambda x: (x > 0).sum() / len(x) * 100]
}).round(2)
monthly_2025.columns = ['Trades', 'Total P&L', 'Avg P&L', 'Win Rate %']
monthly_2025.index = monthly_2025.index.map(month_names)

print(monthly_2025)

# Identify seasonal patterns
print("\n" + "="*80)
print("SEASONAL HYPOTHESIS TEST")
print("="*80)

print("\nWindow 9 training period: Sep 2024 - Feb 2025")
print("Includes: Sep, Oct, Nov, Dec (2024) + Jan, Feb (2025)")

# Check if Window 9 would have learned Oct/Nov patterns from 2024
print("\nDoes Window 9's Oct-Nov 2024 training help predict Oct-Nov 2025?")

# We need to check if Oct-Nov have similar characteristics year-over-year
# But we only have 2025 data in this backtest

print("\n⚠️  We only have 2025 data in current backtest")
print("Need to check if Oct-Nov 2024 data exists to confirm seasonal hypothesis")

# Check rolling window results for seasonal alignment
print("\n" + "="*80)
print("ROLLING WINDOW SEASONAL ALIGNMENT")
print("="*80)

rolling_info = pd.read_csv("models/rolling/rolling_window_results.csv")

print("\nModels that TRAINED on Oct-Nov (any year):")
for idx, row in rolling_info.iterrows():
    train_start = pd.Timestamp(row['train_start'])
    train_end = pd.Timestamp(row['train_end'])
    
    # Check if training period includes Oct or Nov
    includes_oct_nov = False
    if train_start.month <= 10 <= train_end.month or train_start.month <= 11 <= train_end.month:
        includes_oct_nov = True
    # Handle year wrap
    if train_start.year < train_end.year:
        if train_start.month <= 10 or train_end.month >= 10:
            includes_oct_nov = True
        if train_start.month <= 11 or train_end.month >= 11:
            includes_oct_nov = True
    
    if includes_oct_nov:
        print(f"\nWindow {row['window_id']}: {row['train_start']} to {row['train_end']}")
        print(f"  Test accuracy: {row['test_accuracy']:.4f}")

# Load Oct-Nov test results
oct_nov_results = pd.read_csv("models/rolling/oct_nov_test_results.csv")

print("\n" + "="*80)
print("CORRELATION: TRAINING PERIOD vs OCT-NOV 2025 PERFORMANCE")
print("="*80)

# For each window, check if it was trained on Oct-Nov months
for idx, row in oct_nov_results.iterrows():
    window_id = row['window_id']
    oct_nov_pnl = row['oct_nov_pnl']
    
    # Get training period
    train_info = rolling_info[rolling_info['window_id'] == window_id].iloc[0]
    train_start = pd.Timestamp(train_info['train_start'])
    train_end = pd.Timestamp(train_info['train_end'])
    
    # Check months in training period
    train_months = pd.date_range(train_start, train_end, freq='MS').month.tolist()
    
    has_oct = 10 in train_months
    has_nov = 11 in train_months
    
    if has_oct or has_nov:
        seasonal_match = "✅ SEASONAL MATCH"
    else:
        seasonal_match = "❌ No seasonal match"
    
    print(f"\nWindow {window_id}: {train_info['train_start']} to {train_info['train_end']}")
    print(f"  Training months: {[month_names[m] for m in sorted(set(train_months))]}")
    print(f"  Has Oct: {has_oct}, Has Nov: {has_nov}")
    print(f"  Oct-Nov 2025 P&L: ${oct_nov_pnl:.2f}")
    print(f"  {seasonal_match}")

# Statistical analysis
print("\n" + "="*80)
print("STATISTICAL TEST: SEASONAL EFFECT")
print("="*80)

# Split windows into two groups
seasonal_windows = []
non_seasonal_windows = []

for idx, row in oct_nov_results.iterrows():
    window_id = row['window_id']
    train_info = rolling_info[rolling_info['window_id'] == window_id].iloc[0]
    train_start = pd.Timestamp(train_info['train_start'])
    train_end = pd.Timestamp(train_info['train_end'])
    train_months = pd.date_range(train_start, train_end, freq='MS').month.tolist()
    
    if 10 in train_months or 11 in train_months:
        seasonal_windows.append(row['oct_nov_pnl'])
    else:
        non_seasonal_windows.append(row['oct_nov_pnl'])

if seasonal_windows and non_seasonal_windows:
    seasonal_avg = np.mean(seasonal_windows)
    non_seasonal_avg = np.mean(non_seasonal_windows)
    
    print(f"\nWindows trained on Oct/Nov months:")
    print(f"  Count: {len(seasonal_windows)}")
    print(f"  Avg Oct-Nov 2025 P&L: ${seasonal_avg:.2f}")
    
    print(f"\nWindows NOT trained on Oct/Nov months:")
    print(f"  Count: {len(non_seasonal_windows)}")
    print(f"  Avg Oct-Nov 2025 P&L: ${non_seasonal_avg:.2f}")
    
    print(f"\nDifference: ${seasonal_avg - non_seasonal_avg:.2f}")
    
    if seasonal_avg > non_seasonal_avg + 500:
        print("\n✅ STRONG SEASONAL EFFECT DETECTED!")
        print("Models trained on Oct/Nov perform better on Oct/Nov 2025")
    elif seasonal_avg > non_seasonal_avg:
        print("\n⚠️  Weak seasonal effect (not conclusive)")
    else:
        print("\n❌ No seasonal effect detected")

# Recommendation
print("\n" + "="*80)
print("SEASONAL STRATEGY RECOMMENDATION")
print("="*80)

print("""
If seasonal patterns exist, the optimal strategy is:

1. **Use different models for different months**
   - Oct-Nov: Use model trained on Oct-Nov 2024
   - Apr-Jun: Use model trained on Apr-Jun 2024
   - etc.

2. **Implement month-specific model switching**
   - At start of each month, load the model trained on that month from previous year
   - This captures recurring seasonal patterns

3. **Create a seasonal ensemble**
   - Train 12 models, one for each calendar month
   - Use the appropriate model based on current month

4. **Test the hypothesis with more data**
   - Need multi-year data to confirm seasonal patterns
   - Check if Oct 2023, Oct 2024, Oct 2025 have similar characteristics
""")

# Find best model for each month based on training alignment
print("\n" + "="*80)
print("BEST MODEL FOR EACH MONTH (Based on Seasonal Hypothesis)")
print("="*80)

for month_num in range(1, 13):
    month_name = month_names[month_num]
    
    # Find windows that were trained on this month
    best_window = None
    best_score = -999999
    
    for idx, row in rolling_info.iterrows():
        window_id = row['window_id']
        train_start = pd.Timestamp(row['train_start'])
        train_end = pd.Timestamp(row['train_end'])
        train_months = pd.date_range(train_start, train_end, freq='MS').month.tolist()
        
        if month_num in train_months:
            # This window was trained on this month
            # Check its test accuracy as a proxy for quality
            if row['test_accuracy'] > best_score:
                best_score = row['test_accuracy']
                best_window = window_id
    
    if best_window:
        print(f"{month_name}: Window {best_window} (test accuracy: {best_score:.4f})")
    else:
        print(f"{month_name}: No window trained on this month")
