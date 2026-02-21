#!/usr/bin/env python3
"""Check data range in the historical catalog."""
from pathlib import Path
import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog = ParquetDataCatalog(Path('data/historical'))
bars = catalog.bars(instrument_ids=['EUR/USD.IDEALPRO'])

print(f'Total bars: {len(bars)}')

last_bars = sorted(bars, key=lambda b: b.ts_event)[-10:]
print('\nLast 10 bars:')
for b in last_bars:
    ts = pd.Timestamp(b.ts_event, unit='ns', tz='UTC')
    print(f'  {ts} close={b.close}')
