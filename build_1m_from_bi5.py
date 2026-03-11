"""
build_1m_from_bi5.py -- Read raw .bi5 tick files from disk, aggregate to 1-min bars.

Bypasses tick-vault's metadata DB entirely. Reads the .bi5 files directly
from the tick_vault_data/downloads/XAUUSD/ directory structure.

Dukascopy .bi5 format:
  - LZMA compressed
  - 20 bytes per tick: >u4 time_ms, >u4 ask, >u4 bid, >f4 ask_vol, >f4 bid_vol
  - time_ms is milliseconds offset from the hour start
  - Prices are in pipets (multiply by 0.001 for XAUUSD)

Directory structure (Dukascopy convention):
  XAUUSD/{year}/{month_0indexed}/{day_1indexed}/{hour}h_ticks.bi5
  Month is 0-indexed: 00=Jan, 01=Feb, ..., 11=Dec

Output: 1-minute bars with tick_count, spread, volume microstructure.
"""
import lzma
import struct
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

TICK_DIR = Path(r"C:\nautilus0\tick_vault_data\downloads\XAUUSD")
OUTPUT = Path(r"C:\nautilus0\data\1m_csv\xauusd_1m_tick.csv")
PIPET = 0.001  # XAUUSD price scale

TICK_DTYPE = np.dtype([
    ("time_ms", ">u4"),
    ("ask", ">u4"),
    ("bid", ">u4"),
    ("ask_volume", ">f4"),
    ("bid_volume", ">f4"),
])


def decode_bi5(path: Path, hour_start: datetime) -> np.ndarray:
    """Decode a single .bi5 file into a structured numpy array."""
    data = path.read_bytes()
    if len(data) == 0:
        return None
    try:
        buf = lzma.decompress(data)
    except lzma.LZMAError:
        return None
    if len(buf) == 0:
        return None

    raw = np.frombuffer(buf, dtype=TICK_DTYPE)
    n = len(raw)

    result = np.empty(n, dtype=[
        ("time", "datetime64[ms]"),
        ("ask", "float64"),
        ("bid", "float64"),
        ("ask_volume", "int64"),
        ("bid_volume", "int64"),
    ])

    base = np.datetime64(hour_start.replace(tzinfo=None), "ms")
    result["time"] = base + raw["time_ms"].astype(np.int64).astype("timedelta64[ms]")
    result["ask"] = raw["ask"].astype(np.float64) * PIPET
    result["bid"] = raw["bid"].astype(np.float64) * PIPET
    result["ask_volume"] = np.round(raw["ask_volume"].astype(np.float64) * 1e6).astype(np.int64)
    result["bid_volume"] = np.round(raw["bid_volume"].astype(np.float64) * 1e6).astype(np.int64)

    return result


def find_all_bi5_files(base: Path, start_year: int, end_year: int) -> list:
    """Walk the directory tree and collect all .bi5 files with their hour timestamps."""
    files = []
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir():
            continue
        try:
            year = int(year_dir.name)
        except ValueError:
            continue
        if year < start_year or year > end_year:
            continue

        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            try:
                month_0 = int(month_dir.name)  # 0-indexed
                month = month_0 + 1  # convert to 1-indexed
            except ValueError:
                continue
            if month < 1 or month > 12:
                continue

            for day_dir in sorted(month_dir.iterdir()):
                if not day_dir.is_dir():
                    continue
                try:
                    day = int(day_dir.name)
                except ValueError:
                    continue

                for bi5 in sorted(day_dir.glob("*h_ticks.bi5")):
                    try:
                        hour = int(bi5.name.split("h")[0])
                    except ValueError:
                        continue
                    try:
                        hour_ts = datetime(year, month, day, hour, tzinfo=timezone.utc)
                        files.append((bi5, hour_ts))
                    except ValueError:
                        continue

    return files


def ticks_to_1m_bars(ticks: pd.DataFrame) -> pd.DataFrame:
    """
    Given a dataframe of raw Dukascopy ticks for a month, aggregate them
    into 1-minute OHLCV bars with microstructure features.
    Index must be 'timestamp' datetime.
    """
    ticks["spread"] = ticks["ask"] - ticks["bid"]
    ticks["mid"] = (ticks["ask"] + ticks["bid"]) / 2
    ticks["imbalance"] = ticks["ask_volume"] - ticks["bid_volume"]
    
    # Need time column for grouper
    ticks["time"] = ticks.index
    ticks["minute"] = ticks["time"].dt.floor("1min")

    bars = ticks.groupby("minute").agg(
        open=("mid", "first"),
        high=("mid", "max"),
        low=("mid", "min"),
        close=("mid", "last"),
        tick_count=("mid", "count"),
        avg_spread=("spread", "mean"),
        max_spread=("spread", "max"),
        vol_imbalance=("imbalance", "sum"),
        buy_volume=("ask_volume", "sum"),
        sell_volume=("bid_volume", "sum"),
    )
    bars.index.name = "timestamp"
    bars = bars.reset_index()
    bars["total_volume"] = bars["buy_volume"] + bars["sell_volume"]
    bars["buy_ratio"] = bars["buy_volume"] / (bars["total_volume"] + 1e-9)
    return bars


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('symbol', type=str, help='e.g. XAUUSD or EURUSD')
    parser.add_argument('--start', type=int, default=2015)
    parser.add_argument('--end', type=int, default=2026)
    args = parser.parse_args()
    
    symbol = args.symbol.upper()
    IN_DIR = Path(r"C:\nautilus0\tick_vault_data\downloads") / symbol
    OUT_DIR = Path(r"C:\nautilus0\data\1m_csv")
    out_file = OUT_DIR / f"{symbol.lower()}_1m_tick.csv"

    print(f"Aggregating 1-minute bars from {symbol} .bi5 files...")
    print(f"Source: {IN_DIR}")
    print(f"Output: {out_file}")
    
    # Process month by month
    months = []
    for y in range(args.start, args.end + 1):
        for m in range(1, 13):
            if y == args.end and m > 3: continue
            months.append((y, m))

    # Clear existing file
    if out_file.exists():
        out_file.unlink()
        
    for i, (y, m) in enumerate(months):
        sys.stdout.write(f"  [{i+1}/{len(months)}] {y}-{m:02d}: ")
        sys.stdout.flush()
        
        month_dir = IN_DIR / str(y) / f"{m-1:02d}"
        if not month_dir.exists():
            print("no data")
            continue
            
        dfs = []
        for path in sorted(month_dir.rglob("*.bi5")):
            try:
                # Extract day/hour from path: .../YYYY/MM/DD/HHh_ticks.bi5
                parts = path.parts
                day = int(parts[-2])
                hour = int(parts[-1].split('h')[0])
                hour_start = datetime(y, m, day, hour, tzinfo=timezone.utc)
                
                df = decode_bi5(path, hour_start)
                if df is not None and len(df) > 0:
                    dfs.append(df)
            except Exception as e:
                # Log actual errors for debugging
                print(f"\nError processing {path}: {e}")
                continue
                
        if not dfs:
            print("no valid data")
            continue
            
        monthly_df = pd.DataFrame(np.concatenate(dfs))
        
        # Add columns if not already there from structured array
        if 'timestamp' not in monthly_df.columns:
            # Assuming columns: timestamp, ask, bid, ask_vol, bid_vol
            monthly_df.columns = ['timestamp', 'ask', 'bid', 'ask_volume', 'bid_volume']
            
        monthly_df['timestamp'] = pd.to_datetime(monthly_df['timestamp'], unit='ms', utc=True)
        monthly_df.set_index('timestamp', inplace=True)
        monthly_df.sort_index(inplace=True)
        
        monthly_1m = ticks_to_1m_bars(monthly_df)
        
        # Append to CSV
        mode = 'a' if out_file.exists() else 'w'
        header = not out_file.exists()
        monthly_1m.to_csv(out_file, mode=mode, header=header)
        
        print(f"{len(monthly_1m):,} bars")
        
    print(f"\nDone! File saved to {out_file}")
    print(f"Total: {len(pd.read_csv(out_file)):,} bars")


if __name__ == "__main__":
    main()
