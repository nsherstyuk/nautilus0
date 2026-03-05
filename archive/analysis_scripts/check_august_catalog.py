from nautilus_trader.persistence.catalog import ParquetDataCatalog
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# Load the catalog
catalog = ParquetDataCatalog('data/catalog')

# Query bars around August 5-6, 2025
start = datetime(2025, 8, 4)
end = datetime(2025, 8, 8)

bars = catalog.bars(
    instrument_id='EUR/USD.IDEALPRO',
    start=start,
    end=end,
    bar_type='EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL'
)

print(f'Bars from Aug 4-8, 2025: {len(bars)}')

if len(bars) > 0:
    # Convert to DataFrame for analysis
    data = []
    for bar in bars:
        data.append({
            'timestamp': bar.ts_init,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close
        })
    
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ns')
    df = df.sort_values('timestamp')
    
    print(f'Date range: {df["timestamp"].min()} to {df["timestamp"].max()}')
    
    # Check for gaps
    df['time_diff'] = df['timestamp'].diff()
    gaps = df[df['time_diff'] > pd.Timedelta('16 minutes')]
    
    print(f'Number of gaps (>15min): {len(gaps)}')
    if len(gaps) > 0:
        print('Gaps found:')
        for idx, row in gaps.iterrows():
            print(f'  Gap at {row["timestamp"]}: {row["time_diff"]}')
    
    # Check daily patterns
    df['date'] = df['timestamp'].dt.date
    df['hour'] = df['timestamp'].dt.hour
    daily_counts = df.groupby('date').size()
    print(f'Daily bar counts:')
    for date, count in daily_counts.items():
        print(f'  {date}: {count} bars')
        
    # Check if there's a weekend gap
    print(f'Checking weekend patterns:')
    df['weekday'] = df['timestamp'].dt.dayofweek
    print(f'Unique weekdays in data: {sorted(df["weekday"].unique())}')
    
    # Check August 5-6 specifically
    aug_5 = datetime(2025, 8, 5).date()
    aug_6 = datetime(2025, 8, 6).date()
    
    aug_5_data = df[df['date'] == aug_5]
    aug_6_data = df[df['date'] == aug_6]
    
    print(f'August 5, 2025: {len(aug_5_data)} bars')
    print(f'August 6, 2025: {len(aug_6_data)} bars')
    
    if len(aug_5_data) > 0:
        print(f'Aug 5 range: {aug_5_data["timestamp"].min()} to {aug_5_data["timestamp"].max()}')
    if len(aug_6_data) > 0:
        print(f'Aug 6 range: {aug_6_data["timestamp"].min()} to {aug_6_data["timestamp"].max()}')
        
else:
    print('No bars found for the specified period')
