"""
ibkr_download_etf_intraday.py — Download intraday bars from IBKR for ETF strategies

Downloads 1h bars for SPY, TLT, GLD, VNQ (Risk Parity universe) and
QQQ, IWM, EFA, EEM, DBC, IEF (CTA/Momentum universe).

IBKR limits:
  - 1h bars: max 365 days per request, up to ~2y total
  - Rate limit: ~6 requests per 10 seconds for historical data
  - Must have market data subscription for these ETFs

Usage:
  Ensure IB Gateway / TWS is running on port 4002 (paper) or 4001 (live)
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\ibkr_download_etf_intraday.py
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from ib_insync import IB, Stock, util

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ETFs to download
ETFS = {
    # Risk Parity core
    "SPY": "S&P 500",
    "TLT": "20+ Year Treasury",
    "GLD": "Gold ETF",
    "VNQ": "REITs",
    # Extended universe for CTA / Momentum
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "EFA": "EAFE Intl Dev",
    "EEM": "Emerging Markets",
    "IEF": "7-10 Year Treasury",
    "DBC": "Commodities Broad",
}

PORT = 4002        # paper trading; use 4001 for live
CLIENT_ID = 55
BAR_SIZE = "1 hour"
WHAT_TO_SHOW = "TRADES"  # TRADES gives OHLCV for stocks/ETFs

# IBKR allows max 365 calendar days per request for 1h bars
# We'll make 2 requests per symbol: last 365d and prior 365d
CHUNK_DAYS = 365
N_CHUNKS = 2  # ~2 years total

PACE_DELAY = 2.5  # seconds between requests (conservative for rate limits)


def download_etf_bars(ib: IB, symbol: str, bar_size: str = BAR_SIZE,
                      n_chunks: int = N_CHUNKS) -> pd.DataFrame:
    """Download historical bars for an ETF in chunks to maximize history."""
    contract = Stock(symbol, "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        print(f"    ✗ Could not qualify {symbol}")
        return pd.DataFrame()

    all_bars = []
    end_dt = ""  # empty = now

    for chunk_idx in range(n_chunks):
        duration = f"{CHUNK_DAYS} D"
        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_dt,
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=WHAT_TO_SHOW,
                useRTH=False,  # include pre/post market
                formatDate=1,
            )
        except Exception as e:
            print(f"    ✗ Chunk {chunk_idx}: {e}")
            break

        if not bars:
            print(f"    ✗ Chunk {chunk_idx}: no data returned")
            break

        df_chunk = util.df(bars)
        print(f"    Chunk {chunk_idx}: {len(df_chunk):,} bars  "
              f"{df_chunk['date'].iloc[0]} → {df_chunk['date'].iloc[-1]}")

        all_bars.append(df_chunk)

        # Set end_dt to the earliest bar in this chunk for next iteration
        earliest = df_chunk['date'].iloc[0]
        if isinstance(earliest, str):
            end_dt = earliest
        else:
            end_dt = earliest.strftime("%Y%m%d-%H:%M:%S")

        time.sleep(PACE_DELAY)

    if not all_bars:
        return pd.DataFrame()

    combined = pd.concat(all_bars, ignore_index=True)
    combined = combined.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)

    # Rename columns to standard OHLCV
    combined = combined.rename(columns={
        'date': 'timestamp',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'volume': 'volume',
    })

    # Keep only OHLCV + barCount + average if present
    keep_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    for c in ['barCount', 'average']:
        if c in combined.columns:
            keep_cols.append(c)
    combined = combined[[c for c in keep_cols if c in combined.columns]]

    return combined


def main():
    print("=" * 60)
    print("  IBKR ETF Intraday Data Download")
    print("=" * 60)
    print(f"  Port: {PORT}  ClientID: {CLIENT_ID}")
    print(f"  Bar size: {BAR_SIZE}  Chunks: {N_CHUNKS} x {CHUNK_DAYS}d")
    print(f"  ETFs: {list(ETFS.keys())}")
    print()

    ib = IB()
    try:
        ib.connect("127.0.0.1", PORT, clientId=CLIENT_ID)
    except Exception as e:
        print(f"  ✗ Could not connect to IBKR on port {PORT}: {e}")
        print(f"  Make sure IB Gateway or TWS is running!")
        sys.exit(1)

    print(f"  ✓ Connected to IBKR\n")

    results = {}

    for symbol, name in ETFS.items():
        print(f"  {symbol} ({name}):")
        cache_path = DATA_DIR / f"{symbol.lower()}_1h_ibkr.parquet"

        # Check cache
        if cache_path.exists():
            existing = pd.read_parquet(cache_path)
            print(f"    Cache exists: {len(existing):,} bars  "
                  f"{existing['timestamp'].iloc[0]} → {existing['timestamp'].iloc[-1]}")
            # Re-download only if older than 1 day
            last_ts = pd.to_datetime(existing['timestamp'].iloc[-1])
            if (datetime.now() - last_ts.replace(tzinfo=None)).days < 1:
                print(f"    ✓ Up to date, skipping")
                results[symbol] = len(existing)
                time.sleep(0.5)
                continue

        df = download_etf_bars(ib, symbol)

        if df.empty:
            print(f"    ✗ No data for {symbol}")
            continue

        # If cache exists, merge with new data
        if cache_path.exists():
            existing = pd.read_parquet(cache_path)
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)

        df.to_parquet(cache_path, index=False)
        n = len(df)
        results[symbol] = n
        print(f"    ✓ Saved {n:,} bars → {cache_path.name}")
        print(f"      Range: {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")
        print(f"      Price: ${df['close'].iloc[-1]:.2f}")

        time.sleep(PACE_DELAY)

    ib.disconnect()
    print(f"\n  ✓ Disconnected")

    # Summary
    print(f"\n{'='*60}")
    print(f"  DOWNLOAD SUMMARY")
    print(f"{'='*60}")
    for sym, n in results.items():
        print(f"    {sym:>5s}: {n:>6,} bars")
    total = sum(results.values())
    print(f"    {'TOTAL':>5s}: {total:>6,} bars across {len(results)} symbols")

    # Also save a combined wide-format file for easy strategy use
    if results:
        print(f"\n  Building combined close-price matrix...")
        frames = {}
        for sym in results:
            path = DATA_DIR / f"{sym.lower()}_1h_ibkr.parquet"
            if path.exists():
                df = pd.read_parquet(path)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.set_index('timestamp')
                frames[sym] = df['close']

        if frames:
            combined = pd.DataFrame(frames)
            combined = combined.sort_index().ffill()
            out_path = DATA_DIR / "etf_1h_combined.parquet"
            combined.to_parquet(out_path)
            print(f"    ✓ Saved {len(combined):,} rows × {len(combined.columns)} cols → {out_path.name}")
            print(f"      Range: {combined.index[0]} → {combined.index[-1]}")


if __name__ == "__main__":
    main()
