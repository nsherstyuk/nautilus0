import pandas as pd
import glob
import os

data_dir = r"C:\nautilus0\data\historical\data\bar\EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
files = glob.glob(os.path.join(data_dir, "*.parquet"))

print(f"Found {len(files)} parquet files.")

for f in files:
    print(f"\nAnalyzing: {os.path.basename(f)}")
    try:
        df = pd.read_parquet(f)
        if df.empty:
            print("  - File is empty")
            continue
            
        # Check index (timestamps)
        # Nautilus parquet usually has index as integer ns timestamps or datetime
        if not isinstance(df.index, pd.DatetimeIndex):
            # Try to convert if it's named 'timestamp' or similar, or just inspect index
            print(f"  - Index type: {type(df.index)}")
            # Assuming it might be the standard format where index is the timestamp
            
        start_date = df.index.min()
        end_date = df.index.max()
        count = len(df)
        
        print(f"  - Rows: {count}")
        print(f"  - Range: {start_date} to {end_date}")
        
        # Check specific gap months
        aug = df[df.index.strftime('%Y-%m') == '2025-08']
        sep = df[df.index.strftime('%Y-%m') == '2025-09']
        oct_ = df[df.index.strftime('%Y-%m') == '2025-10']
        
        print(f"  - Aug 2025 rows: {len(aug)}")
        print(f"  - Sep 2025 rows: {len(sep)}")
        print(f"  - Oct 2025 rows: {len(oct_)}")
        
    except Exception as e:
        print(f"  - Error reading file: {e}")
