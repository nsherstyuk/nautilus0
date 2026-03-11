"""
download_1m_bars.py -- Download 1-minute historical bars from IBKR.

Saves CSV files to C:\nautilus0\data\1m_csv\
Run when IBKR Gateway is connected (port 4002).

IBKR limits for 1-min bars:
- Max duration per request: ~1-2 days
- Need to chunk carefully to avoid pacing violations

Usage:
    python download_1m_bars.py
    python download_1m_bars.py --pairs XAUUSD --start 2020-01-01
"""

import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from ib_insync import IB, Contract, Forex

# ── Config ────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(r"C:\nautilus0\data\1m_csv")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PAIR_CONTRACTS = {
    'XAUUSD': lambda: Contract(secType='CMDTY', symbol='XAUUSD', exchange='SMART', currency='USD'),
    'EURUSD': lambda: Forex('EURUSD'),
    'GBPUSD': lambda: Forex('GBPUSD'),
    'USDJPY': lambda: Forex('USDJPY'),
    'AUDUSD': lambda: Forex('AUDUSD'),
}

# IBKR 1-min bar limits: up to ~10 days per request
# Going back 10+ years = ~400 requests at 10 days each
DEFAULT_START = '2015-01-01'
SLEEP_BETWEEN_REQUESTS = 12  # seconds (conservative for pacing)
CHUNK_DAYS = 10  # 10 days per request for 1-min bars (IBKR allows this)


def download_pair(ib: IB, pair: str, start_date: str = DEFAULT_START):
    """Download 1-minute bars for one pair, day by day."""

    if pair not in PAIR_CONTRACTS:
        print(f"  Unknown pair: {pair}")
        return

    contract = PAIR_CONTRACTS[pair]()
    ib.qualifyContracts(contract)

    output_file = OUTPUT_DIR / f"{pair.lower()}_1m.csv"

    # If file exists, resume from last timestamp
    if output_file.exists():
        existing = pd.read_csv(output_file)
        existing['timestamp'] = pd.to_datetime(existing['timestamp'], utc=True)
        last_ts = existing['timestamp'].max()
        print(f"  Resuming {pair} from {last_ts}")
        all_bars = [existing]
        # Start from the day after last data
        start_from = last_ts.to_pydatetime() + timedelta(minutes=1)
    else:
        start_from = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        all_bars = []

    end_dt = datetime.now(timezone.utc)
    current_end = start_from + timedelta(days=CHUNK_DAYS)

    request_count = 0
    new_bars_total = 0
    empty_streak = 0

    while current_end <= end_dt + timedelta(days=1):
        end_str = current_end.strftime('%Y%m%d %H:%M:%S') + ' UTC'

        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_str,
                durationStr=f'{CHUNK_DAYS} D',
                barSizeSetting='1 min',
                whatToShow='MIDPOINT',
                useRTH=False,
                formatDate=1,
            )
        except Exception as e:
            print(f"  Error at {end_str}: {e}")
            time.sleep(30)
            current_end += timedelta(days=CHUNK_DAYS)
            continue

        if not bars:
            empty_streak += 1
            if empty_streak > 10:
                print(f"  10 consecutive empty responses, skipping ahead...")
                current_end += timedelta(days=7)
                empty_streak = 0
            else:
                current_end += timedelta(days=CHUNK_DAYS)
            time.sleep(2)
            continue

        empty_streak = 0

        chunk_df = pd.DataFrame([{
            'timestamp': b.date,
            'open': b.open,
            'high': b.high,
            'low': b.low,
            'close': b.close,
            'volume': getattr(b, 'volume', 0),
        } for b in bars])

        chunk_df['timestamp'] = pd.to_datetime(chunk_df['timestamp'], utc=True)

        all_bars.append(chunk_df)
        new_bars_total += len(chunk_df)

        request_count += 1

        if request_count % 10 == 0:
            print(f"  {pair}: {new_bars_total:,} bars downloaded, "
                  f"current date: {current_end.date()}")

        if request_count % 50 == 0:
            # Periodic save to avoid data loss
            print(f"  Periodic save ({new_bars_total:,} bars)...")
            combined = pd.concat(all_bars, ignore_index=True)
            combined = combined.drop_duplicates(subset='timestamp').sort_values('timestamp').reset_index(drop=True)
            combined.to_csv(output_file, index=False)

        # Move forward
        current_end += timedelta(days=CHUNK_DAYS)

        # Rate limiting
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    if not all_bars:
        print(f"  {pair}: no data downloaded")
        return

    # Final combine and save
    combined = pd.concat(all_bars, ignore_index=True)
    combined = combined.drop_duplicates(subset='timestamp').sort_values('timestamp').reset_index(drop=True)
    combined.to_csv(output_file, index=False)
    print(f"\n  {pair}: saved {len(combined):,} bars to {output_file}")
    print(f"  Date range: {combined['timestamp'].iloc[0]} to {combined['timestamp'].iloc[-1]}")
    print(f"  Total requests: {request_count}")


def main():
    parser = argparse.ArgumentParser(description="Download 1-min bars from IBKR")
    parser.add_argument('--pairs', nargs='+', default=['XAUUSD'])
    parser.add_argument('--start', default=DEFAULT_START)
    parser.add_argument('--port', type=int, default=4002)
    args = parser.parse_args()

    pairs = [p.upper() for p in args.pairs]

    # Estimate time
    start = datetime.strptime(args.start, '%Y-%m-%d')
    days = (datetime.now() - start).days
    est_minutes = days * SLEEP_BETWEEN_REQUESTS / 60
    print(f"Downloading 1-min bars for: {', '.join(pairs)}")
    print(f"Start date: {args.start} (~{days} days)")
    print(f"Estimated time: ~{est_minutes:.0f} minutes ({est_minutes/60:.1f} hours) per pair")
    print(f"Output dir: {OUTPUT_DIR}")
    print()

    ib = IB()
    ib.connect('127.0.0.1', args.port, clientId=99)

    for pair in pairs:
        print(f"\n{'='*60}")
        print(f"  {pair}")
        print(f"{'='*60}")
        download_pair(ib, pair, start_date=args.start)

    ib.disconnect()
    print("\nDone.")


if __name__ == '__main__':
    main()
