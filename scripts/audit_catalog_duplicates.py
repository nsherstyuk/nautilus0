import pandas as pd
from pathlib import Path
import sys

def audit_catalog_duplicates(catalog_path: str):
    path = Path(catalog_path)
    if not path.exists():
        print(f"Path does not exist: {path}")
        return

    parquet_files = list(path.glob("*.parquet"))
    if not parquet_files:
        print(f"No parquet files found in {path}")
        return

    print(f"Found {len(parquet_files)} parquet files in {path.name}")
    
    total_rows = 0
    all_timestamps = []
    
    for file in sorted(parquet_files):
        try:
            df = pd.read_parquet(file)
            total_rows += len(df)
            
            # Nautilus parquet files usually have 'ts_event' or 'ts_init'
            if 'ts_event' in df.columns:
                ts_col = 'ts_event'
            elif 'ts_init' in df.columns:
                ts_col = 'ts_init'
            else:
                print(f"Warning: No timestamp column found in {file.name}. Columns: {df.columns}")
                continue
                
            all_timestamps.extend(df[ts_col].tolist())
            
            # Check duplicates within the file
            dupes = df[df.duplicated(subset=[ts_col], keep=False)]
            if not dupes.empty:
                print(f"  [!] File {file.name} has {len(dupes)} duplicate rows!")
                
        except Exception as e:
            print(f"Error reading {file.name}: {e}")

    if not all_timestamps:
        return

    # Check global duplicates across all files
    ts_series = pd.Series(all_timestamps)
    global_dupes = ts_series[ts_series.duplicated(keep=False)]
    
    print("\n--- Summary ---")
    print(f"Total rows across all files: {total_rows}")
    print(f"Total unique timestamps: {ts_series.nunique()}")
    
    if not global_dupes.empty:
        print(f"GLOBAL DUPLICATES FOUND: {len(global_dupes)} rows have duplicate timestamps across the catalog.")
        # Show a sample of duplicates
        sample_dupes = global_dupes.value_counts().head(5)
        print("Sample of duplicated timestamps (timestamp: count):")
        for ts, count in sample_dupes.items():
            print(f"  {pd.Timestamp(ts, unit='ns', tz='UTC')}: {count} times")
    else:
        print("SUCCESS: No duplicate timestamps found across the entire catalog.")

if __name__ == "__main__":
    base_dir = Path("c:/nautilus0/data/historical/data/bar")
    
    print("Auditing 15-Minute Bars...")
    audit_catalog_duplicates(base_dir / "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL")
    
    print("\nAuditing 1-Minute Bars...")
    audit_catalog_duplicates(base_dir / "EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL")
