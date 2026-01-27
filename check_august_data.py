import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Load the EUR/USD 15m data (the one that failed ingestion)
df = pd.read_csv('data/historical/EUR-USD_EUR_USD_IDEALPRO_15_MINUTE_MID_EXTERNAL.csv')

# Convert timestamp (remove timezone)
df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None)
df = df.sort_values('timestamp')

# Check what dates are actually in the data
print(f'Data range: {df["timestamp"].min()} to {df["timestamp"].max()}')
print(f'Total data points: {len(df)}')

# Check for duplicates
duplicates = df[df.duplicated(subset=['timestamp'], keep=False)]
print(f'Duplicate timestamps found: {len(duplicates)}')
if len(duplicates) > 0:
    print('Sample duplicates:')
    print(duplicates.head(10))

# Check for disjointness/overlaps (time diff should be >= 15 min)
df['diff'] = df['timestamp'].diff()
overlaps = df[df['diff'] < pd.Timedelta(minutes=15)]
# First row always has NaT diff, ignore it
overlaps = overlaps[overlaps['diff'].notna()]

print(f'Overlapping intervals found (<15m diff): {len(overlaps)}')
if len(overlaps) > 0:
    print('Sample overlaps:')
    print(overlaps.head(10))

