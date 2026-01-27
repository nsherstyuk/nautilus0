from nautilus_trader.persistence.catalog import ParquetDataCatalog
from datetime import datetime
import pandas as pd

catalog = ParquetDataCatalog('data/historical')

# Check data around Aug 5 22:00 - 23:00
start = datetime(2025, 8, 5, 21, 0)
end = datetime(2025, 8, 5, 23, 30)

# Check 15-minute bars
bars_15m = catalog.bars(
    instrument_id='EURUSD.IDEALPRO',
    start=start,
    end=end,
    bar_type='EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL'
)

print(f'15-minute bars: {len(bars_15m)}')
if len(bars_15m) > 0:
    print('Last 10 bars:')
    for i, bar in enumerate(bars_15m[-10:]):
        ts = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        print(f'  {ts} - close={bar.close}')

# Check 1-minute bars
bars_1m = catalog.bars(
    instrument_id='EURUSD.IDEALPRO',
    start=start,
    end=end,
    bar_type='EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL'
)

print(f'\n1-minute bars: {len(bars_1m)}')
if len(bars_1m) > 0:
    print('First 5 bars:')
    for i, bar in enumerate(bars_1m[:5]):
        ts = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        print(f'  {ts} - close={bar.close}')
    print('Last 5 bars:')
    for i, bar in enumerate(bars_1m[-5:]):
        ts = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        print(f'  {ts} - close={bar.close}')

# Check if there's a gap after 22:30
print('\nChecking for gaps after 22:30...')
aug5_end = datetime(2025, 8, 6, 2, 0)
bars_next = catalog.bars(
    instrument_id='EURUSD.IDEALPRO',
    start=datetime(2025, 8, 5, 22, 30),
    end=aug5_end,
    bar_type='EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL'
)
print(f'Bars from 22:30 to next morning: {len(bars_next)}')
if len(bars_next) > 0:
    for bar in bars_next[:5]:
        ts = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        print(f'  {ts}')
