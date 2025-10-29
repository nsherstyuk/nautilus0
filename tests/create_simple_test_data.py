"""
Simple test data creation for Phase 3 crossover filter tests.
Creates basic parquet files with predictable crossover patterns.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import pyarrow as pa
import pyarrow.parquet as pq

# Configuration
CATALOG_PATH = "data/test_catalog/phase3_crossover_filters"
VENUE = "IDEALPRO"
BAR_SPEC = "1-MINUTE-MID-EXTERNAL"
BASE_PRICE = 1.08000
FAST_PERIOD = 10
SLOW_PERIOD = 20
TOTAL_BARS = 200
START_DATE = datetime(2024, 1, 1, 0, 0, 0)

def create_simple_crossover_data(symbol, crossover_bar=100, separation_after=0.0001):
    """Create simple crossover data with predictable patterns."""
    bars = []
    
    # Generate timestamps
    timestamps = [START_DATE + timedelta(minutes=i) for i in range(TOTAL_BARS)]
    
    # Generate close prices with a simple crossover pattern
    close_prices = []
    
    # Before crossover: slow MA above fast MA
    for i in range(crossover_bar):
        # Create a simple trend where slow MA is above fast MA
        base = BASE_PRICE + i * 0.00001  # Small upward trend
        close_prices.append(base)
    
    # At crossover: create the crossover
    crossover_price = BASE_PRICE + crossover_bar * 0.00001 + separation_after
    close_prices.append(crossover_price)
    
    # After crossover: fast MA above slow MA
    for i in range(crossover_bar + 1, TOTAL_BARS):
        # Continue upward trend
        base = BASE_PRICE + i * 0.00001 + separation_after
        close_prices.append(base)
    
    # Create OHLCV data
    for i, (ts, close) in enumerate(zip(timestamps, close_prices)):
        # Simple OHLCV generation
        high = close * 1.0001
        low = close * 0.9999
        open_price = close_prices[i-1] if i > 0 else close
        volume = 1000000
        
        bars.append({
            'timestamp': ts,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
            'ts_init': int(ts.timestamp() * 1_000_000_000),
            'ts_event': int(ts.timestamp() * 1_000_000_000),
        })
    
    return bars

def create_test_scenarios():
    """Create all test scenarios."""
    scenarios = [
        ("TST/USD", 100, 0.00005),  # 0.5 pips - below threshold
    ]
    
    for symbol, crossover_bar, separation in scenarios:
        print(f"Creating data for {symbol}...")
        bars = create_simple_crossover_data(symbol, crossover_bar, separation)
        
        # Create DataFrame
        df = pd.DataFrame(bars)
        
        # Create output directory - replace / with . for directory name
        symbol_dir = symbol.replace("/", ".")
        output_dir = Path(CATALOG_PATH) / "data" / "bar" / f"{symbol_dir}.{VENUE}-{BAR_SPEC}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create parquet file
        output_file = output_dir / f"{START_DATE.strftime('%Y-%m-%dT%H-%M-%S-%fZ')}_{(START_DATE + timedelta(days=10)).strftime('%Y-%m-%dT%H-%M-%S-%fZ')}.parquet"
        
        # Convert to PyArrow table and save
        table = pa.Table.from_pandas(df)
        pq.write_table(table, output_file)
        
        print(f"  Created {output_file} with {len(bars)} bars")

if __name__ == "__main__":
    print("Creating simple test data for Phase 3 crossover filters...")
    create_test_scenarios()
    print("Test data creation complete!")
