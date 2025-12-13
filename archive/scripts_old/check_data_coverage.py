"""
Check if historical data covers the backtest period.
"""
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from datetime import datetime

def check_data_coverage():
    """Check what data is available and if it covers the backtest period."""
    
    # Read backtest dates from .env.best or .env
    env_file = Path(".env.best")
    if not env_file.exists():
        env_file = Path(".env")
    
    backtest_start = None
    backtest_end = None
    
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('BACKTEST_START_DATE='):
                    backtest_start = line.split('=', 1)[1].strip()
                elif line.startswith('BACKTEST_END_DATE='):
                    backtest_end = line.split('=', 1)[1].strip()
    
    if not backtest_start or not backtest_end:
        print("ERROR: Could not find BACKTEST_START_DATE or BACKTEST_END_DATE in .env file")
        return
    
    print("=" * 80)
    print("HISTORICAL DATA COVERAGE CHECK")
    print("=" * 80)
    print(f"\nBacktest Period Required:")
    print(f"  Start: {backtest_start}")
    print(f"  End:   {backtest_end}")
    
    # Check catalog
    catalog_path = Path("data/historical")
    if not catalog_path.exists():
        print(f"\nERROR: Catalog directory not found: {catalog_path}")
        print("  Run: python data/ingest_historical.py")
        return
    
    catalog = ParquetDataCatalog(str(catalog_path))
    
    # Check for EUR-USD data - try both formats
    instrument_ids = ["EUR/USD.IDEALPRO", "EURUSD.IDEALPRO"]
    
    print(f"\nChecking catalog: {catalog_path}")
    
    # Check different bar types needed
    bar_types = [
        "1-MINUTE-MID-EXTERNAL",  # Primary timeframe
        "2-MINUTE-MID-EXTERNAL",  # DMI filter
        "15-MINUTE-MID-EXTERNAL", # Stochastic filter
    ]
    
    print(f"\nRequired Bar Types:")
    for bt in bar_types:
        print(f"  - {bt}")
    
    print("\n" + "=" * 80)
    print("DATA AVAILABILITY BY BAR TYPE")
    print("=" * 80)
    
    all_covered = True
    
    # Use verify_catalog approach to check parquet files directly
    bar_root = catalog_path / "data" / "bar"
    
    if not bar_root.exists():
        print("\nERROR: No bar data directory found")
        return
    
    start_dt = pd.Timestamp(backtest_start, tz='UTC')
    end_dt = pd.Timestamp(backtest_end, tz='UTC')
    
    for bar_type in bar_types:
        # Find matching dataset directory
        found = False
        for dataset_dir in bar_root.iterdir():
            if not dataset_dir.is_dir():
                continue
            
            if bar_type in dataset_dir.name:
                found = True
                total_rows = 0
                min_ts = None
                max_ts = None
                
                parquet_files = sorted(dataset_dir.glob("*.parquet"))
                if not parquet_files:
                    print(f"\n[WARNING] {bar_type}: No parquet files found")
                    all_covered = False
                    continue
                
                for parquet_file in parquet_files:
                    try:
                        metadata = pq.read_metadata(parquet_file)
                        total_rows += metadata.num_rows
                        
                        # Find timestamp column
                        ts_column_name = None
                        for candidate in ("ts_init", "ts_event"):
                            if candidate in metadata.schema.names:
                                ts_column_name = candidate
                                break
                        
                        if ts_column_name:
                            ts_index = metadata.schema.names.index(ts_column_name)
                            for rg_index in range(metadata.num_row_groups):
                                column = metadata.row_group(rg_index).column(ts_index)
                                stats = column.statistics
                                if stats:
                                    rg_min = stats.min
                                    rg_max = stats.max
                                    if isinstance(rg_min, (bytes, bytearray)):
                                        rg_min = int.from_bytes(rg_min, byteorder="little", signed=True)
                                    if isinstance(rg_max, (bytes, bytearray)):
                                        rg_max = int.from_bytes(rg_max, byteorder="little", signed=True)
                                    
                                    if min_ts is None or (rg_min is not None and rg_min < min_ts):
                                        min_ts = rg_min
                                    if max_ts is None or (rg_max is not None and rg_max > max_ts):
                                        max_ts = rg_max
                    except Exception as e:
                        print(f"\n[ERROR] {bar_type}: Error reading {parquet_file.name} - {e}")
                        continue
                
                if min_ts and max_ts:
                    first_dt = pd.to_datetime(min_ts, unit="ns", utc=True)
                    last_dt = pd.to_datetime(max_ts, unit="ns", utc=True)
                    
                    coverage_start = first_dt <= start_dt
                    coverage_end = last_dt >= end_dt
                    
                    status = "[OK]" if (coverage_start and coverage_end) else "[WARNING]"
                    
                    print(f"\n{status} {bar_type}:")
                    print(f"  Bars available: {total_rows:,}")
                    print(f"  First bar: {first_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"  Last bar:  {last_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    if not coverage_start:
                        print(f"  [WARNING] Missing data BEFORE {start_dt.strftime('%Y-%m-%d')}")
                        all_covered = False
                    if not coverage_end:
                        print(f"  [WARNING] Missing data AFTER {end_dt.strftime('%Y-%m-%d')}")
                        all_covered = False
                    
                    if coverage_start and coverage_end:
                        print(f"  [OK] Full coverage for backtest period")
                else:
                    print(f"\n[ERROR] {bar_type}: Could not determine date range")
                    all_covered = False
                break
        
        if not found:
            print(f"\n[ERROR] {bar_type}: Dataset directory not found")
            all_covered = False
    
    print("\n" + "=" * 80)
    if all_covered:
        print("[OK] RESULT: All required data is available for the backtest period!")
    else:
        print("[WARNING] RESULT: Some data is missing. You may need to ingest more data.")
        print("\nTo ingest missing data:")
        print("  1. Set DATA_START_DATE and DATA_END_DATE in .env")
        print("  2. Run: python data/ingest_historical.py")
    print("=" * 80)

if __name__ == "__main__":
    check_data_coverage()

