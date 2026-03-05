"""
download_fx_ibkr.py -- Download FX hourly bars from IBKR historical data.

IBKR provides up to ~10 years of hourly MIDPOINT bars for FX pairs.
Downloads in 30-day chunks (IBKR limit for 1h bars) and stitches into
a single parquet file per pair.

For the ORB strategy we only need hourly bars (to compute Asian range
high/low and track breakouts), so this is sufficient.

Usage:
  python -m trading_system_v4.scripts.download_fx_ibkr GBPUSD
  python -m trading_system_v4.scripts.download_fx_ibkr USDJPY
  python -m trading_system_v4.scripts.download_fx_ibkr GBPUSD USDJPY
  python -m trading_system_v4.scripts.download_fx_ibkr GBPUSD --years 5
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from ib_insync import IB, Forex, util

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"

# IBKR limits: 1 hour bars, max duration "30 D" per request
CHUNK_DAYS = 30
BAR_SIZE = "1 hour"
WHAT_TO_SHOW = "MIDPOINT"
SLEEP_BETWEEN = 2  # seconds between requests (IBKR pacing)


def download_pair(ib: IB, symbol: str, years: int) -> pd.DataFrame:
    """Download hourly bars for one FX pair going back `years` years."""
    contract = Forex(symbol)
    ib.qualifyContracts(contract)
    print(f"  Contract: {contract}")

    all_bars = []
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=years * 365)
    current_end = end_dt
    # Track as naive datetimes for comparison; we'll add UTC later
    earliest_seen = None

    total_chunks = int((end_dt - start_dt).days / CHUNK_DAYS) + 1
    chunk_num = 0

    while current_end > start_dt:
        chunk_num += 1
        pct = chunk_num / total_chunks * 100
        end_str = current_end.strftime("%Y%m%d %H:%M:%S")

        sys.stdout.write(
            f"\r  [{chunk_num}/{total_chunks}] ({pct:.0f}%) "
            f"Fetching up to {current_end.strftime('%Y-%m-%d')} "
            f"| bars so far: {sum(len(b) for b in all_bars):,}   "
        )
        sys.stdout.flush()

        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_str,
                durationStr=f"{CHUNK_DAYS} D",
                barSizeSetting=BAR_SIZE,
                whatToShow=WHAT_TO_SHOW,
                useRTH=False,  # include all hours (critical for Asian session)
                formatDate=1,
            )
        except Exception as e:
            print(f"\n  [ERROR] Request failed: {e}")
            time.sleep(5)
            current_end -= timedelta(days=CHUNK_DAYS)
            continue

        if not bars:
            print(f"\n  [WARN] No data for chunk ending {end_str}")
            current_end -= timedelta(days=CHUNK_DAYS)
            time.sleep(SLEEP_BETWEEN)
            continue

        df_chunk = util.df(bars)
        all_bars.append(df_chunk)

        # Move end back to before the earliest bar in this chunk
        earliest = df_chunk["date"].min()
        # Strip timezone if present for comparison
        if hasattr(earliest, 'tzinfo') and earliest.tzinfo is not None:
            earliest = earliest.replace(tzinfo=None)
        current_end = earliest - timedelta(hours=1)

        time.sleep(SLEEP_BETWEEN)

    print()  # newline after progress

    if not all_bars:
        return pd.DataFrame()

    df = pd.concat(all_bars, ignore_index=True)
    df = df.rename(columns={"date": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = (
        df.sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"])
        .reset_index(drop=True)
    )

    # Keep only OHLCV columns
    cols = ["timestamp", "open", "high", "low", "close"]
    if "volume" in df.columns:
        cols.append("volume")
    df = df[cols]

    return df


def main():
    parser = argparse.ArgumentParser(
        description="Download FX hourly bars from IBKR")
    parser.add_argument("symbols", nargs="+", help="e.g. GBPUSD USDJPY")
    parser.add_argument("--years", type=int, default=7,
                        help="Years of history to download (default: 7)")
    parser.add_argument("--port", type=int, default=4002,
                        help="IBKR Gateway port (default: 4002)")
    parser.add_argument("--client-id", type=int, default=62,
                        help="IBKR client ID (default: 62)")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("IBKR FX Historical Data Downloader")
    print(f"Symbols: {', '.join(args.symbols)}")
    print(f"History: {args.years} years")
    print(f"Bar size: {BAR_SIZE}")
    print("=" * 60)

    ib = IB()
    try:
        ib.connect("127.0.0.1", args.port, clientId=args.client_id, timeout=15)
        print(f"Connected to IBKR (port={args.port}, clientId={args.client_id})")
    except Exception as e:
        print(f"[ERROR] Cannot connect to IBKR: {e}")
        print("Make sure IB Gateway is running.")
        sys.exit(1)

    try:
        for symbol in args.symbols:
            symbol = symbol.upper()
            output_file = DATA_DIR / f"{symbol.lower()}_1h_bars.parquet"
            print(f"\n--- {symbol} ---")

            t0 = time.time()
            df = download_pair(ib, symbol, args.years)
            elapsed = time.time() - t0

            if df.empty:
                print(f"  [ERROR] No data for {symbol}")
                continue

            df.to_parquet(output_file, index=False)
            print(f"  Saved: {output_file}")
            print(f"  Bars: {len(df):,}")
            print(f"  Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
            print(f"  Time: {elapsed:.0f}s")

    finally:
        ib.disconnect()
        print("\nDisconnected from IBKR.")


if __name__ == "__main__":
    main()
