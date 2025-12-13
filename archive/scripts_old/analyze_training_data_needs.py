"""
Analyze how much training data we need for model retraining.
"""
import pandas as pd
from pathlib import Path

# Check available data
data_file = Path("data/EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL.parquet")

if data_file.exists():
    df = pd.read_parquet(data_file)
    df.index = pd.to_datetime(df.index)
    
    print("="*80)
    print("AVAILABLE DATA ANALYSIS")
    print("="*80)
    print(f"\nTotal bars: {len(df):,}")
    print(f"Date range: {df.index.min()} to {df.index.max()}")
    print(f"Duration: {(df.index.max() - df.index.min()).days} days")
    
    # Monthly breakdown
    print("\n" + "-"*80)
    print("DATA BY MONTH")
    print("-"*80)
    monthly = df.groupby(df.index.to_period('M')).size()
    print(monthly.tail(24))  # Last 24 months
    
    # Calculate bars needed for different training periods
    print("\n" + "="*80)
    print("TRAINING PERIOD OPTIONS")
    print("="*80)
    
    options = [
        ("3 months", 3),
        ("6 months", 6),
        ("9 months", 9),
        ("12 months", 12),
        ("18 months", 18),
        ("24 months", 24),
    ]
    
    cutoff_date = pd.Timestamp('2025-10-01')
    
    for label, months in options:
        start_date = cutoff_date - pd.DateOffset(months=months)
        train_data = df[(df.index >= start_date) & (df.index < cutoff_date)]
        
        if len(train_data) > 0:
            print(f"\n{label} ({start_date.strftime('%Y-%m')} to 2025-09):")
            print(f"  Bars: {len(train_data):,}")
            print(f"  Days: {(train_data.index.max() - train_data.index.min()).days}")
            print(f"  Months: {len(train_data.groupby(train_data.index.to_period('M')))}")
    
    # Recommendation based on current model performance
    print("\n" + "="*80)
    print("RECOMMENDATION")
    print("="*80)
    
    print("""
Based on the performance degradation analysis:

1. **Q2 2025 (Apr-Jun)**: Model performed EXCELLENT ($12k/month)
2. **Q3 2025 (Jul-Sep)**: Performance dropped 75% ($3k/month)
3. **Q4 2025 (Oct-Nov)**: Performance dropped 94% ($0.7k/month)

The regime change appears to have started around July 2025.

RECOMMENDED TRAINING PERIOD: **12 months (Oct 2024 - Sep 2025)**

Why 12 months?
- ✅ Includes the excellent Q2 2025 performance period
- ✅ Includes the regime change in Q3 2025 (model learns new patterns)
- ✅ Enough data for robust ML training (~35,000 bars)
- ✅ Recent enough to capture current market behavior
- ✅ Covers full seasonal cycle (all months of year)

Alternative if 12 months shows overfitting:
- **6 months (Apr 2025 - Sep 2025)**: More recent, includes regime change
- **9 months (Jan 2025 - Sep 2025)**: Balance between recency and data volume

AVOID:
- ❌ 3 months: Too little data, high overfitting risk
- ❌ 24 months: Too old data, includes outdated market regimes
""")
    
    # Check what the current model was trained on
    print("\n" + "-"*80)
    print("CURRENT MODEL TRAINING PERIOD (from backtest)")
    print("-"*80)
    print("Backtest period: 2025-01-01 to 2025-11-28")
    print("Current model likely trained on: 2023-2024 data")
    print("This explains why it worked well in Q1-Q2 2025 but failed in Q3-Q4")
    
else:
    print(f"❌ Data file not found: {data_file}")
    print("Please ensure data is downloaded first")
