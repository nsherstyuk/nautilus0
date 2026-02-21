import pyarrow.parquet as pq
from pathlib import Path

def restore_metadata(backup_dir: str, new_file: str):
    backup_path = Path(backup_dir)
    new_path = Path(new_file)
    
    # Get the first backup file
    backup_files = list(backup_path.glob("*.parquet"))
    if not backup_files:
        print("No backup files found.")
        return
        
    backup_file = backup_files[0]
    print(f"Reading metadata from {backup_file.name}")
    
    # Read metadata from backup
    backup_table = pq.read_table(backup_file)
    metadata = backup_table.schema.metadata
    
    print(f"Found metadata keys: {list(metadata.keys())}")
    
    # Read new file
    print(f"Reading new file {new_path.name}")
    new_table = pq.read_table(new_path)
    
    # Apply metadata
    new_table = new_table.replace_schema_metadata(metadata)
    
    # Write back
    print(f"Writing back to {new_path.name} with restored metadata")
    pq.write_table(new_table, new_path)
    print("Done!")

if __name__ == "__main__":
    base_dir = Path("c:/nautilus0/data/historical/data/bar")
    
    print("--- Restoring 15-Minute Metadata ---")
    restore_metadata(
        base_dir / "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL_backup",
        base_dir / "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL" / "2023-12-27T22-15-00-000000000Z_2026-02-20T21-30-00-000000000Z.parquet"
    )
    
    print("\n--- Restoring 1-Minute Metadata ---")
    restore_metadata(
        base_dir / "EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL_backup",
        base_dir / "EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL" / "2023-12-27T22-15-00-000000000Z_2026-02-20T21-58-00-000000000Z.parquet"
    )
