"""Check what data exists in the catalog."""
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from datetime import datetime
import pandas as pd

catalog = ParquetDataCatalog('data/historical')

print("Checking catalog data coverage...\n")

# Get all bars for 2025
try:
    bars = list(catalog.bars(
        'EUR/USD.IDEALPRO-1-MINUTE-MID-EXTERNAL',
        start=datetime(2025, 1, 1),
        end=datetime(2025, 12, 31)
    ))
    
    if bars:
        print(f"Total 1-minute bars in 2025: {len(bars):,}")
        
        # Convert to timestamps
        timestamps = [pd.Timestamp(bar.ts_init, unit='ns', tz='UTC') for bar in bars]
        
        print(f"First bar: {timestamps[0]}")
        print(f"Last bar: {timestamps[-1]}")
        
        # Check for gaps by month
        print("\nBars by month:")
        df = pd.DataFrame({'timestamp': timestamps})
        df['month'] = df['timestamp'].dt.to_period('M')
        monthly = df.groupby('month').size()
        print(monthly.to_string())
        
        # Check specific gap period
        print("\n\nChecking gap period:")
        gap_bars = [ts for ts in timestamps if datetime(2025, 8, 7) <= ts <= datetime(2025, 10, 9)]
        print(f"Aug 7 - Oct 9: {len(gap_bars)} bars")
        if gap_bars:
            print(f"  First: {gap_bars[0]}")
            print(f"  Last: {gap_bars[-1]}")
        else:
            print("  ⚠️  NO DATA in this period!")
    else:
        print("❌ No bars found in catalog for 2025")
        
except Exception as e:
    print(f"Error: {e}")

# Also check 15-minute bars
print("\n" + "="*60)
print("Checking 15-minute bars...")
try:
    bars_15m = list(catalog.bars(
        'EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL',
        start=datetime(2025, 8, 7),
        end=datetime(2025, 10, 9)
    ))
    print(f"15-minute bars (Aug 7 - Oct 9): {len(bars_15m)}")
except Exception as e:
    print(f"Error: {e}")
