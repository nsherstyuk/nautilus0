"""
download_tick_data.py — Institutional-grade FX Tick Data Downloader

Downloads raw tick data from Dukascopy using `tick-vault`, processes it into
Information-Driven Bars (e.g., 1,000-Tick Bars), and saves the result as Parquet.

Features:
- Downloads data month-by-month to manage RAM.
- Converts raw Bid/Ask ticks into Midpoint OHLCV bars.
- Engineers microstructure features: Average Spread, Tick Velocity, Volume Imbalance.
- Appends to a master Parquet dataset.

Usage:
  python -m trading_system_v4.scripts.download_tick_data
"""
import asyncio
import gc
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from tick_vault import download_range, read_tick_data

# ── Configuration ─────────────────────────────────────────────────────────────
SYMBOL = "EURUSD"
START_YEAR = 2015
END_YEAR = 2025
TICKS_PER_BAR = 1000

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
OUTPUT_FILE = DATA_DIR / f"{SYMBOL.lower()}_{TICKS_PER_BAR}t_bars.parquet"


def process_ticks_to_bars(df: pd.DataFrame, ticks_per_bar: int) -> pd.DataFrame:
    """
    Converts raw tick data into Information-Driven Bars (Tick Bars).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # 1. Calculate Midpoint and Spread
    df["mid"] = (df["ask"] + df["bid"]) / 2.0
    df["spread"] = df["ask"] - df["bid"]
    df["vol_imbalance"] = df["ask_volume"] - df["bid_volume"]

    # 2. Create grouping index (every N ticks is a new bar)
    # We use integer division on the index to group rows
    df = df.reset_index(drop=True)
    group_id = df.index // ticks_per_bar

    # 3. Aggregate into OHLCV + Microstructure features
    bars = df.groupby(group_id).agg(
        timestamp=("time", "last"),          # Time the bar closed
        open=("mid", "first"),
        high=("mid", "max"),
        low=("mid", "min"),
        close=("mid", "last"),
        tick_count=("mid", "count"),         # Should equal ticks_per_bar (except maybe the last one)
        avg_spread=("spread", "mean"),
        max_spread=("spread", "max"),        # NEW: Max spread during the bar (liquidity shock)
        vol_imbalance=("vol_imbalance", "sum"),
        buy_volume=("ask_volume", "sum"),    # NEW: Total buy volume
        sell_volume=("bid_volume", "sum"),   # NEW: Total sell volume
        duration_sec=("time", lambda x: (x.iloc[-1] - x.iloc[0]).total_seconds())
    )

    # Filter out incomplete bars at the very end of the dataset
    bars = bars[bars["tick_count"] == ticks_per_bar].copy()
    
    # Calculate Tick Velocity (ticks per second)
    # Add a small epsilon to duration to prevent division by zero
    bars["tick_velocity"] = ticks_per_bar / (bars["duration_sec"] + 1e-6)
    
    # NEW: Volume-weighted features
    bars["total_volume"] = bars["buy_volume"] + bars["sell_volume"]
    bars["buy_ratio"] = bars["buy_volume"] / (bars["total_volume"] + 1e-6) # % of volume that was buying

    # Clean up
    bars = bars.drop(columns=["tick_count", "duration_sec"])
    bars = bars.reset_index(drop=True)
    
    return bars


async def download_and_process_month(year: int, month: int) -> pd.DataFrame:
    """
    Downloads 1 month of tick data, processes it into bars, and returns the DataFrame.
    """
    start_date = datetime(year, month, 1)
    
    # Handle end of year rollover for the end date
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    print(f"\n[{SYMBOL}] Processing {start_date.strftime('%Y-%m')} ...")
    
    try:
        # 1. Download the raw .bi5 files concurrently
        await download_range(symbol=SYMBOL, start=start_date, end=end_date)
        
        # 2. Read into Pandas
        df_raw = read_tick_data(symbol=SYMBOL, start=start_date, end=end_date)
        
        if df_raw is None or df_raw.empty:
            print(f"  [WARN] No data found for {start_date.strftime('%Y-%m')}")
            return pd.DataFrame()
            
        raw_count = len(df_raw)
        
        # 3. Process into Tick Bars
        df_bars = process_ticks_to_bars(df_raw, TICKS_PER_BAR)
        bar_count = len(df_bars)
        
        print(f"  Raw Ticks: {raw_count:,}  ->  {TICKS_PER_BAR}-Tick Bars: {bar_count:,}")
        
        # 4. Aggressive memory cleanup
        del df_raw
        gc.collect()
        
        return df_bars

    except Exception as e:
        print(f"  [ERROR] Failed to process {start_date.strftime('%Y-%m')}: {e}")
        return pd.DataFrame()


async def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    all_bars = []
    total_bars = 0
    
    print(f"Starting Tick Data Pipeline for {SYMBOL}")
    print(f"Target: {START_YEAR} to {END_YEAR} ({TICKS_PER_BAR}-Tick Bars)")
    print("-" * 60)

    for year in range(START_YEAR, END_YEAR + 1):
        for month in range(1, 13):
            # Stop if we reach the current future month
            if year == datetime.now().year and month > datetime.now().month:
                break
                
            df_month = await download_and_process_month(year, month)
            
            if not df_month.empty:
                all_bars.append(df_month)
                total_bars += len(df_month)
                
            # Periodically save to disk to prevent RAM issues on smaller machines
            if len(all_bars) >= 12:  # Save every year
                print(f"\n[CHECKPOINT] Saving {total_bars:,} accumulated bars to disk...")
                combined = pd.concat(all_bars, ignore_index=True)
                
                if OUTPUT_FILE.exists():
                    existing = pd.read_parquet(OUTPUT_FILE)
                    combined = pd.concat([existing, combined], ignore_index=True)
                    
                combined = combined.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
                combined.to_parquet(OUTPUT_FILE, index=False)
                
                # Clear memory
                all_bars = []
                del combined
                gc.collect()

    # Final save for any remaining months
    if all_bars:
        print(f"\n[FINAL] Saving remaining bars to disk...")
        combined = pd.concat(all_bars, ignore_index=True)
        
        if OUTPUT_FILE.exists():
            existing = pd.read_parquet(OUTPUT_FILE)
            combined = pd.concat([existing, combined], ignore_index=True)
            
        combined = combined.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
        combined.to_parquet(OUTPUT_FILE, index=False)

    if OUTPUT_FILE.exists():
        final_df = pd.read_parquet(OUTPUT_FILE)
        print("\n" + "=" * 60)
        print(f"PIPELINE COMPLETE")
        print(f"Saved to: {OUTPUT_FILE}")
        print(f"Total {TICKS_PER_BAR}-Tick Bars: {len(final_df):,}")
        print(f"Date Range: {final_df['timestamp'].min()} to {final_df['timestamp'].max()}")
        print("=" * 60)


if __name__ == "__main__":
    # Windows asyncio fix for ProactorEventLoop
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
