import pandas as pd
import pyarrow.parquet as pq
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

# Check the parquet file
print("=== Checking Parquet File ===")
file_path = 'data/historical/data/bar/EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL/2023-12-27T22-30-00-000000000Z_2025-10-30T04-00-00-000000000Z.parquet'
df = pq.read_table(file_path).to_pandas()
print(f"Rows: {len(df)}")
print(f"Columns: {list(df.columns)}")
print(f"First 3 rows:")
print(df.head(3))

# Check the catalog
print("\n=== Checking Catalog ===")
catalog = ParquetDataCatalog('data/historical')
instruments = catalog.instruments()
print(f"Instruments found: {len(instruments)}")
if instruments:
    print(f"First instrument: {instruments[0]}")
