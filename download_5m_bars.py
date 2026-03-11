"""
download_5m_bars.py -- Download 5-minute historical bars from IBKR.

Saves CSV files to C:\nautilus0\data\5m_csv\
Run when IBKR Gateway is connected (port 4002).

Usage:
    python download_5m_bars.py
    python download_5m_bars.py --pairs XAUUSD EURUSD
    python download_5m_bars.py --pairs AUDUSD --start 2020-01-01
"""

import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from ib_insync import IB, Contract, Forex

# ── Config ────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(r"C:\nautilus0\data\5m_csv")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Contract definitions for each pair
PAIR_CONTRACTS = {
    'XAUUSD': lambda: Contract(secType='CMDTY', symbol='XAUUSD', exchange='SMART', currency='USD'),
    'EURUSD': lambda: Forex('EURUSD'),
    'GBPUSD': lambda: Forex('GBPUSD'),
    'USDJPY': lambda: Forex('USDJPY'),
    'AUDUSD': lambda: Forex('AUDUSD'),
    'NZDUSD': lambda: Forex('NZDUSD'),
    'USDCAD': lambda: Forex('USDCAD'),
    'USDCHF': lambda: Forex('USDCHF'),
    'EURJPY': lambda: Forex('EURJPY'),
    'GBPJPY': lambda: Forex('GBPJPY'),
    'EURGBP': lambda: Forex('EURGBP'),
}

# How far back to go (IBKR limits vary by data type)
# 5-min bars: max ~1 year per request, but we can chain requests
DEFAULT_START = '2015-01-01'

# IBKR rate limit: max 60 requests per 10 minutes
SLEEP_BETWEEN_REQUESTS = 11  # seconds


def download_pair(ib: IB, pair: str, start_date: str = DEFAULT_START):
    """Download 5-minute bars for one pair, chunk by chunk."""

    if pair not in PAIR_CONTRACTS:
        print(f"  Unknown pair: {pair}")
        return

    contract = PAIR_CONTRACTS[pair]()
    ib.qualifyContracts(contract)

    output_file = OUTPUT_DIR / f"{pair.lower()}_5m.csv"

    # If file exists, resume from last timestamp
    if output_file.exists():
        existing = pd.read_csv(output_file)
        existing['timestamp'] = pd.to_datetime(existing['timestamp'], utc=True)
        last_ts = existing['timestamp'].max()
        print(f"  Resuming {pair} from {last_ts}")
        end_dt = datetime.now(timezone.utc)
        all_bars = [existing]
    else:
        last_ts = pd.Timestamp(start_date, tz='UTC')
        end_dt = datetime.now(timezone.utc)
        all_bars = []

    # IBKR returns max ~8000 bars per request for 5-min data (~27 days)
    # We chunk backwards from end_dt
    current_end = end_dt
    chunk_duration = timedelta(days=25)  # conservative chunk size

    request_count = 0
    new_bars_total = 0

    while True:
        end_str = current_end.strftime('%Y%m%d %H:%M:%S') + ' UTC'

        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_str,
                durationStr='25 D',
                barSizeSetting='5 mins',
                whatToShow='MIDPOINT',
                useRTH=False,
                formatDate=1,
            )
        except Exception as e:
            print(f"  Error at {end_str}: {e}")
            time.sleep(30)
            continue

        if not bars:
            print(f"  No more data before {end_str}")
            break

        chunk_df = pd.DataFrame([{
            'timestamp': b.date,
            'open': b.open,
            'high': b.high,
            'low': b.low,
            'close': b.close,
            'volume': getattr(b, 'volume', 0),
        } for b in bars])

        chunk_df['timestamp'] = pd.to_datetime(chunk_df['timestamp'], utc=True)

        # Filter to only new bars
        new_bars = chunk_df[chunk_df['timestamp'] > last_ts]
        if len(new_bars) == 0:
            # We've reached data we already have
            break

        all_bars.append(new_bars)
        new_bars_total += len(new_bars)

        earliest = chunk_df['timestamp'].min()
        print(f"  {pair}: got {len(new_bars)} new bars, earliest={earliest.date()}")

        # Move window back
        current_end = earliest.to_pydatetime() - timedelta(minutes=1)
        if current_end.tzinfo is None:
            current_end = current_end.replace(tzinfo=timezone.utc)

        if current_end < pd.Timestamp(start_date, tz='UTC'):
            break

        request_count += 1
        if request_count % 5 == 0:
            print(f"  ... {new_bars_total} bars so far, sleeping to respect rate limit ...")

        time.sleep(SLEEP_BETWEEN_REQUESTS)

    if not all_bars:
        print(f"  {pair}: no data downloaded")
        return

    # Combine and deduplicate
    combined = pd.concat(all_bars, ignore_index=True)
    combined = combined.drop_duplicates(subset='timestamp').sort_values('timestamp').reset_index(drop=True)

    # Save
    combined.to_csv(output_file, index=False)
    print(f"  {pair}: saved {len(combined)} bars to {output_file}")
    print(f"  Date range: {combined['timestamp'].iloc[0]} to {combined['timestamp'].iloc[-1]}")


def main():
    parser = argparse.ArgumentParser(description="Download 5-min bars from IBKR")
    parser.add_argument('--pairs', nargs='+', default=['XAUUSD', 'EURUSD'])
    parser.add_argument('--start', default=DEFAULT_START)
    parser.add_argument('--port', type=int, default=4002)
    parser.add_argument('--all', action='store_true', help='Download all pairs')
    args = parser.parse_args()

    if args.all:
        pairs = list(PAIR_CONTRACTS.keys())
    else:
        pairs = [p.upper() for p in args.pairs]

    print(f"Downloading 5-min bars for: {', '.join(pairs)}")
    print(f"Start date: {args.start}")
    print(f"Output dir: {OUTPUT_DIR}")
    print()

    ib = IB()
    ib.connect('127.0.0.1', args.port, clientId=98)

    for pair in pairs:
        print(f"\n--- {pair} ---")
        download_pair(ib, pair, start_date=args.start)

    ib.disconnect()
    print("\nDone.")


if __name__ == '__main__':
    main()
