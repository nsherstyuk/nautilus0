
import sys
from pathlib import Path
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

def check_volume_precision():
    catalog_path = Path("data/historical")
    catalog = ParquetDataCatalog(str(catalog_path))
    
    # Try to load bars for EUR/USD 1-minute
    # Note: The dataset name might vary slightly, checking for standard name
    bar_types = [
        "EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL",
        "EURUSD.IDEALPRO-5-MINUTE-MID-EXTERNAL",
        "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    ]
    
    for bt in bar_types:
        try:
            bars = catalog.bars(bar_types=[bt])
            if not bars:
                print(f"{bt}: No bars found.")
                continue
                
            sample_bar = bars[0]
            vol = sample_bar.volume
            print(f"{bt}: Sample volume: {vol}, Precision: {vol.precision}")
            
            if vol.precision != 2:
                print(f"  FAIL: Expected precision 2, got {vol.precision}")
            else:
                print(f"  PASS: Precision is correct.")
                
        except Exception as e:
            print(f"Error checking {bt}: {e}")

if __name__ == "__main__":
    check_volume_precision()
