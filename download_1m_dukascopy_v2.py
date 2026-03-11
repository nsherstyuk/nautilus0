"""
download_1m_dukascopy_v2.py -- Download XAUUSD ticks from Dukascopy, aggregate to 1-min bars.
Processes one month at a time with explicit progress output.
"""
import asyncio
import gc
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from tick_vault import download_range, read_tick_data, reload_config

OUTPUT_DIR = Path(r"C:\nautilus0\data\1m_csv")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "xauusd_1m_dukascopy.csv"
SYMBOL = "XAUUSD"
TICK_VAULT_DIR = r"C:\nautilus0\tick_vault_data"


def ticks_to_1m_bars(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df["mid"] = (df["ask"] + df["bid"]) / 2.0
    df["spread"] = df["ask"] - df["bid"]
    df["imbalance"] = df["ask_volume"] - df["bid_volume"]
    df["minute"] = df["time"].dt.floor("1min")
    bars = df.groupby("minute").agg(
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


async def process_month(year: int, month: int) -> pd.DataFrame:
    start_date = datetime(year, month, 1)
    end_date = datetime(year + (1 if month == 12 else 0), (month % 12) + 1, 1)
    tag = f"{year}-{month:02d}"

    sys.stdout.write(f"  {tag}: downloading... ")
    sys.stdout.flush()

    try:
        await download_range(symbol=SYMBOL, start=start_date, end=end_date)
    except Exception as e:
        print(f"DOWNLOAD ERROR: {e}")
        return pd.DataFrame()

    sys.stdout.write("reading... ")
    sys.stdout.flush()

    try:
        df_raw = read_tick_data(symbol=SYMBOL, start=start_date, end=end_date)
    except Exception as e:
        print(f"READ ERROR: {e}")
        return pd.DataFrame()

    if df_raw is None or df_raw.empty:
        print("NO DATA")
        return pd.DataFrame()

    raw_n = len(df_raw)
    sys.stdout.write(f"{raw_n:,} ticks -> ")
    sys.stdout.flush()

    bars = ticks_to_1m_bars(df_raw)
    print(f"{len(bars):,} bars")

    del df_raw
    gc.collect()
    return bars


async def main(start_year: int, end_year: int):
    reload_config(base_directory=TICK_VAULT_DIR)

    print(f"XAUUSD 1-Min Bar Download ({start_year}-{end_year})")
    print(f"Output: {OUTPUT_FILE}")
    print()

    all_bars = []

    for year in range(start_year, end_year + 1):
        print(f"--- {year} ---")
        for month in range(1, 13):
            if year == datetime.now().year and month > datetime.now().month:
                break
            bars = await process_month(year, month)
            if not bars.empty:
                all_bars.append(bars)

        # Save after each year
        if all_bars:
            combined = pd.concat(all_bars, ignore_index=True)
            if OUTPUT_FILE.exists():
                existing = pd.read_csv(OUTPUT_FILE)
                existing['timestamp'] = pd.to_datetime(existing['timestamp'])
                combined['timestamp'] = pd.to_datetime(combined['timestamp'])
                combined = pd.concat([existing, combined], ignore_index=True)
            combined = combined.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
            combined.to_csv(OUTPUT_FILE, index=False)
            print(f"  -> Saved {len(combined):,} total bars\n")
            all_bars = []
            del combined
            gc.collect()

    if OUTPUT_FILE.exists():
        final = pd.read_csv(OUTPUT_FILE)
        print(f"\nDONE: {len(final):,} bars, {OUTPUT_FILE.stat().st_size/1024/1024:.1f} MB")
        print(f"Range: {final['timestamp'].iloc[0]} to {final['timestamp'].iloc[-1]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2018)
    parser.add_argument("--end", type=int, default=2026)
    args = parser.parse_args()

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main(args.start, args.end))
