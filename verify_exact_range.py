
import pandas as pd
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog_path = Path("data/historical")
catalog = ParquetDataCatalog(str(catalog_path))
bars = catalog.bars(instrument_ids=["EUR/USD.IDEALPRO"], bar_types=["EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL"])

if not bars:
    print("No bars found.")
else:
    df = pd.DataFrame([
        {'timestamp': pd.Timestamp(b.ts_init, unit='ns')} 
        for b in bars
    ])
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    
    print(f"Total bars: {len(df)}")
    print("First 5 bars:")
    print(df.head())
    print("Last 5 bars:")
    print(df.tail())
