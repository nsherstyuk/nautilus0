#!/usr/bin/env python3
"""
Convert existing CSV historical data to Nautilus Parquet catalog format.
This is needed for backtesting with the MTF strategy.
"""
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from nautilus_trader.model.data import Bar, BarType, BarSpecification
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

def convert_csv_to_catalog(
    csv_path: Path,
    instrument_id: str,
    bar_spec_str: str,
    catalog_path: Path
):
    """
    Convert CSV data to Nautilus catalog format.
    
    Args:
        csv_path: Path to CSV file
        instrument_id: Instrument ID (e.g., "EUR/USD.IDEALPRO")
        bar_spec_str: Bar specification (e.g., "15-MINUTE-MID-EXTERNAL")
        catalog_path: Path to catalog directory
    """
    print(f"\n{'='*80}")
    print(f"Converting: {csv_path.name}")
    print(f"Instrument: {instrument_id}")
    print(f"Bar Spec: {bar_spec_str}")
    print(f"{'='*80}")
    
    # Load CSV
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    
    # Sort and deduplicate to ensure valid Parquet writing
    df = df.sort_values('timestamp')
    df = df.drop_duplicates(subset=['timestamp'])
    
    print(f"Loaded {len(df)} bars")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    # Create instrument
    instrument_id_obj = InstrumentId.from_str(instrument_id)
    
    # For EUR/USD, create a simple currency pair
    # In production, you'd want to properly define the instrument
    instrument = TestInstrumentProvider.default_fx_ccy(instrument_id.split('.')[0].replace('/', ''))
    
    # Parse bar spec
    parts = bar_spec_str.split('-')
    step = int(parts[0])
    aggregation = BarAggregation[parts[1]]
    price_type = PriceType[parts[2]]
    
    bar_spec = BarSpecification(
        step=step,
        aggregation=aggregation,
        price_type=price_type
    )
    
    bar_type = BarType(
        instrument_id=instrument_id_obj,
        bar_spec=bar_spec,
        aggregation_source=AggregationSource.EXTERNAL
    )
    
    # Convert to Bar objects
    bars = []
    for idx, row in df.iterrows():
        bar = Bar(
            bar_type=bar_type,
            open=Price.from_str(f"{row['open']:.5f}"),
            high=Price.from_str(f"{row['high']:.5f}"),
            low=Price.from_str(f"{row['low']:.5f}"),
            close=Price.from_str(f"{row['close']:.5f}"),
            # Ensure volume has precision 2 to match instrument definition (EUR/USD typically precision 2)
            volume=Quantity.from_str(f"{int(row['volume']):.2f}"),
            ts_event=int(row['timestamp'].value),
            ts_init=int(row['timestamp'].value)
        )
        bars.append(bar)
    
    print(f"Created {len(bars)} Bar objects")
    
    # Write to catalog
    catalog = ParquetDataCatalog(str(catalog_path))
    
    # Write instrument
    catalog.write_data([instrument])
    print(f"Wrote instrument: {instrument.id}")
    
    # Write bars
    catalog.write_data(bars)
    print(f"Wrote {len(bars)} bars to catalog")
    
    print(f"✅ Conversion complete!\n")

def main():
    """Convert all required CSV files to catalog."""
    
    # Paths
    historical_dir = PROJECT_ROOT / "data" / "historical"
    catalog_dir = PROJECT_ROOT / "data" / "historical"
    
    # Create catalog directory
    catalog_dir.mkdir(exist_ok=True)
    
    print("="*80)
    print("CSV TO CATALOG CONVERTER")
    print("="*80)
    
    # Define files to convert
    files_to_convert = [
        ("EUR-USD_EUR_USD_IDEALPRO_1_MINUTE_MID_EXTERNAL.csv", "1-MINUTE-MID-EXTERNAL"),
        ("EUR-USD_EUR_USD_IDEALPRO_5_MINUTE_MID_EXTERNAL.csv", "5-MINUTE-MID-EXTERNAL"),
        ("EUR-USD_EUR_USD_IDEALPRO_15_MINUTE_MID_EXTERNAL.csv", "15-MINUTE-MID-EXTERNAL"),
    ]
    
    for filename, bar_spec in files_to_convert:
        csv_file = historical_dir / filename
        
        if not csv_file.exists():
            print(f"❌ CSV file not found: {csv_file}")
            continue
            
        try:
            convert_csv_to_catalog(
                csv_path=csv_file,
                instrument_id="EUR/USD.IDEALPRO",
                bar_spec_str=bar_spec,
                catalog_path=catalog_dir
            )
        except Exception as e:
            print(f"\n❌ Error converting {filename}: {e}")
            import traceback
            traceback.print_exc()
            
    print("="*80)
    print("✅ ALL CONVERSIONS COMPLETE")
    print("="*80)
    print(f"\nCatalog location: {catalog_dir}")
    print("Ready for backtesting!")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
