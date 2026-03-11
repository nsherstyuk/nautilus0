"""
download_1m_dukascopy.py -- Download XAUUSD raw ticks from Dukascopy via tick-vault,
aggregate to 1-minute bars with microstructure features.

Output: c:/nautilus0/data/1m_csv/xauusd_1m.csv
  Columns: timestamp, open, high, low, close, tick_count, avg_spread, max_spread,
           vol_imbalance, buy_volume, sell_volume, buy_ratio

Usage:
    python download_1m_dukascopy.py
    python download_1m_dukascopy.py --start 2020 --end 2026
"""
import asyncio
import gc
import os
import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from tick_vault import download_range, read_tick_data, reload_config

# ── Config ────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(r"C:\nautilus0\data\1m_csv")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "xauusd_1m.csv"

SYMBOL = "XAUUSD"
TICK_VAULT_DIR = r"C:\nautilus0\tick_vault_data"


def ticks_to_1m_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate raw ticks into 1-minute OHLCV bars with microstructure features."""
    if df is None or df.empty:
        return pd.DataFrame()

    # Midpoint and spread
    df["mid"] = (df["ask"] + df["bid"]) / 2.0
    df["spread"] = df["ask"] - df["bid"]
    df["imbalance"] = df["ask_volume"] - df["bid_volume"]

    # Floor timestamps to the minute
    df["minute"] = df["time"].dt.floor("1min")

    # Aggregate
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

    # Derived features
    bars["total_volume"] = bars["buy_volume"] + bars["sell_volume"]
    bars["buy_ratio"] = bars["buy_volume"] / (bars["total_volume"] + 1e-9)

    return bars


async def download_and_process_month(year: int, month: int) -> pd.DataFrame:
    """Download 1 month of raw ticks, aggregate to 1-min bars."""
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    tag = start_date.strftime('%Y-%m')
    print(f"  [{tag}] Downloading ticks...", end="", flush=True)

    try:
        await download_range(symbol=SYMBOL, start=start_date, end=end_date)
        print(" reading...", end="", flush=True)

        df_raw = read_tick_data(symbol=SYMBOL, start=start_date, end=end_date)

        if df_raw is None or df_raw.empty:
            print(f" NO DATA")
            return pd.DataFrame()

        raw_count = len(df_raw)
        print(f" aggregating {raw_count:,} ticks...", end="", flush=True)

        bars = ticks_to_1m_bars(df_raw)
        print(f" {len(bars):,} bars")

        del df_raw
        gc.collect()
        return bars

    except Exception as e:
        print(f" ERROR: {e}")
        return pd.DataFrame()


async def main(start_year: int, end_year: int):
    reload_config(base_directory=TICK_VAULT_DIR)

    all_bars = []
    total_bars = 0

    print(f"{'='*60}")
    print(f"  XAUUSD 1-Minute Bar Download (Dukascopy via tick-vault)")
    print(f"  Range: {start_year}-01 to {end_year}-present")
    print(f"  Output: {OUTPUT_FILE}")
    print(f"{'='*60}\n")

    for year in range(start_year, end_year + 1):
        print(f"\n--- {year} ---")
        for month in range(1, 13):
            if year == datetime.now().year and month > datetime.now().month:
                break

            bars = await download_and_process_month(year, month)

            if not bars.empty:
                all_bars.append(bars)
                total_bars += len(bars)

            # Save every 12 months to avoid RAM issues
            if len(all_bars) >= 12:
                print(f"\n  [SAVE] {total_bars:,} bars accumulated, saving checkpoint...")
                _save_checkpoint(all_bars)
                all_bars = []
                gc.collect()

    # Final save
    if all_bars:
        print(f"\n  [FINAL SAVE] {total_bars:,} total bars...")
        _save_checkpoint(all_bars)

    # Print summary
    if OUTPUT_FILE.exists():
        final = pd.read_csv(OUTPUT_FILE)
        final['timestamp'] = pd.to_datetime(final['timestamp'])
        print(f"\n{'='*60}")
        print(f"  DONE")
        print(f"  Total 1-min bars: {len(final):,}")
        print(f"  Date range: {final['timestamp'].min()} to {final['timestamp'].max()}")
        print(f"  File size: {OUTPUT_FILE.stat().st_size / 1024 / 1024:.1f} MB")
        print(f"{'='*60}")


def _save_checkpoint(bar_list: list):
    """Append new bars to the output file."""
    combined = pd.concat(bar_list, ignore_index=True)

    if OUTPUT_FILE.exists():
        existing = pd.read_csv(OUTPUT_FILE)
        existing['timestamp'] = pd.to_datetime(existing['timestamp'])
        combined['timestamp'] = pd.to_datetime(combined['timestamp'])
        combined = pd.concat([existing, combined], ignore_index=True)

    combined = combined.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
    combined.to_csv(OUTPUT_FILE, index=False)
    print(f"  Saved {len(combined):,} bars to {OUTPUT_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2018)
    parser.add_argument("--end", type=int, default=2026)
    args = parser.parse_args()

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main(args.start, args.end))
