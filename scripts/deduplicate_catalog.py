import pandas as pd
from pathlib import Path
import shutil
import os

def deduplicate_parquet_files(catalog_path: str):
    path = Path(catalog_path)
    if not path.exists():
        print(f"Path does not exist: {path}")
        return

    parquet_files = sorted(list(path.glob("*.parquet")))
    if not parquet_files:
        print(f"No parquet files found in {path}")
        return

    print(f"Processing {len(parquet_files)} parquet files in {path.name}")
    
    # Read all data
    all_dfs = []
    for file in parquet_files:
        try:
            df = pd.read_parquet(file)
            all_dfs.append(df)
        except Exception as e:
            print(f"Error reading {file.name}: {e}")

    if not all_dfs:
        return

    # Combine all data
    combined_df = pd.concat(all_dfs, ignore_index=True)
    
    # Determine timestamp column
    ts_col = 'ts_event' if 'ts_event' in combined_df.columns else 'ts_init'
    
    # Sort by timestamp and keep the last entry (most recent update)
    combined_df = combined_df.sort_values(by=ts_col)
    
    original_len = len(combined_df)
    deduped_df = combined_df.drop_duplicates(subset=[ts_col], keep='last')
    deduped_len = len(deduped_df)
    
    print(f"Original rows: {original_len}")
    print(f"Deduplicated rows: {deduped_len}")
    print(f"Removed {original_len - deduped_len} duplicate rows.")
    
    if original_len == deduped_len:
        print("No duplicates to remove. Exiting.")
        return

    # Backup original directory
    backup_path = path.parent / f"{path.name}_backup"
    if not backup_path.exists():
        print(f"Creating backup at {backup_path}")
        shutil.copytree(path, backup_path)
    else:
        print(f"Backup already exists at {backup_path}")

    # Clear original directory
    print("Clearing original parquet files...")
    for file in parquet_files:
        os.remove(file)

    # Write deduplicated data back as a single parquet file
    # Nautilus can read a single large parquet file just fine
    # We'll name it based on the min and max timestamps
    min_ts = pd.Timestamp(deduped_df[ts_col].min(), unit='ns', tz='UTC')
    max_ts = pd.Timestamp(deduped_df[ts_col].max(), unit='ns', tz='UTC')
    
    # Format: YYYY-MM-DDTHH-MM-SS-000000000Z
    min_str = min_ts.strftime('%Y-%m-%dT%H-%M-%S-000000000Z')
    max_str = max_ts.strftime('%Y-%m-%dT%H-%M-%S-000000000Z')
    
    new_filename = f"{min_str}_{max_str}.parquet"
    new_filepath = path / new_filename
    
    print(f"Writing deduplicated data to {new_filename}...")
    deduped_df.to_parquet(new_filepath, index=False)
    print("Done!")

if __name__ == "__main__":
    base_dir = Path("c:/nautilus0/data/historical/data/bar")
    
    print("--- Deduplicating 15-Minute Bars ---")
    deduplicate_parquet_files(base_dir / "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL")
    
    print("\n--- Deduplicating 1-Minute Bars ---")
    deduplicate_parquet_files(base_dir / "EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL")
