import pandas as pd
import glob
import os
import datetime

data_dir = r"C:\nautilus0\data\historical\data\bar\EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL"
files = glob.glob(os.path.join(data_dir, "*.parquet"))

print(f"Found {len(files)} parquet files.")

def get_timestamp_col(df):
    for col in df.columns:
        if 'timestamp' in col.lower() or 'date' in col.lower():
            return col
    return None

for f in files:
    mtime = os.path.getmtime(f)
    dt_mtime = datetime.datetime.fromtimestamp(mtime)
    print(f"\nAnalyzing: {os.path.basename(f)}")
    print(f"  - Modified: {dt_mtime}")
    
    try:
        df = pd.read_parquet(f)
        if df.empty:
            print("  - File is empty")
            continue
            
        ts_col = 'ts_event'
        if ts_col in df.columns:
            # Convert to datetime (uint64 ns)
            df['ts'] = pd.to_datetime(df[ts_col], unit='ns')
        else:
            # Fallback to other checks
            ts_col = get_timestamp_col(df)
            # Check if index is datetime
            if isinstance(df.index, pd.DatetimeIndex):
                 df['ts'] = df.index
            else:
                print(f"  - No timestamp column found. Columns: {df.columns.tolist()}")
                continue
                
        start_date = df['ts'].min()
        end_date = df['ts'].max()
        count = len(df)
        
        print(f"  - Rows: {count}")
        print(f"  - Range: {start_date} to {end_date}")
        
        # Check specific gap months
        mask_aug = (df['ts'].dt.year == 2025) & (df['ts'].dt.month == 8)
        mask_sep = (df['ts'].dt.year == 2025) & (df['ts'].dt.month == 9)
        mask_oct = (df['ts'].dt.year == 2025) & (df['ts'].dt.month == 10)
        
        print(f"  - Aug 2025 rows: {mask_aug.sum()}")
        print(f"  - Sep 2025 rows: {mask_sep.sum()}")
        print(f"  - Oct 2025 rows: {mask_oct.sum()}")
        
    except Exception as e:
        print(f"  - Error reading file: {e}")
