"""
download_tick_data_multi.py -- Download tick data from Dukascopy for any FX pair.

Usage:
  python -m trading_system_v4.scripts.download_tick_data_multi GBPUSD
  python -m trading_system_v4.scripts.download_tick_data_multi USDJPY
  python -m trading_system_v4.scripts.download_tick_data_multi GBPUSD --start-year 2018
"""
import argparse
import asyncio
import gc
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from tick_vault import download_range, read_tick_data

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
TICKS_PER_BAR = 1000


def process_ticks_to_bars(df: pd.DataFrame, ticks_per_bar: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df["mid"] = (df["ask"] + df["bid"]) / 2.0
    df["spread"] = df["ask"] - df["bid"]
    df["vol_imbalance"] = df["ask_volume"] - df["bid_volume"]
    df = df.reset_index(drop=True)
    group_id = df.index // ticks_per_bar
    bars = df.groupby(group_id).agg(
        timestamp=("time", "last"),
        open=("mid", "first"),
        high=("mid", "max"),
        low=("mid", "min"),
        close=("mid", "last"),
        tick_count=("mid", "count"),
        avg_spread=("spread", "mean"),
        max_spread=("spread", "max"),
        vol_imbalance=("vol_imbalance", "sum"),
        buy_volume=("ask_volume", "sum"),
        sell_volume=("bid_volume", "sum"),
        duration_sec=("time", lambda x: (x.iloc[-1] - x.iloc[0]).total_seconds()),
    )
    bars = bars[bars["tick_count"] == ticks_per_bar].copy()
    bars["tick_velocity"] = ticks_per_bar / (bars["duration_sec"] + 1e-6)
    bars["total_volume"] = bars["buy_volume"] + bars["sell_volume"]
    bars["buy_ratio"] = bars["buy_volume"] / (bars["total_volume"] + 1e-6)
    bars = bars.drop(columns=["tick_count", "duration_sec"])
    bars = bars.reset_index(drop=True)
    return bars


async def main():
    parser = argparse.ArgumentParser(description="Download FX tick data from Dukascopy")
    parser.add_argument("symbol", help="FX pair symbol, e.g. GBPUSD, USDJPY")
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()

    symbol = args.symbol.upper()
    start_year = args.start_year
    end_year = args.end_year
    output_file = DATA_DIR / f"{symbol.lower()}_{TICKS_PER_BAR}t_bars.parquet"

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    all_bars = []
    total_bars = 0

    print(f"Starting Tick Data Pipeline for {symbol}")
    print(f"Target: {start_year} to {end_year} ({TICKS_PER_BAR}-Tick Bars)")
    print(f"Output: {output_file}")
    print("-" * 60)

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            if year == datetime.now().year and month > datetime.now().month:
                break

            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)

            label = start_date.strftime("%Y-%m")
            print(f"[{symbol}] Processing {label} ...")

            try:
                await download_range(symbol=symbol, start=start_date, end=end_date)
                df_raw = read_tick_data(symbol=symbol, start=start_date, end=end_date)

                if df_raw is None or df_raw.empty:
                    print(f"  [WARN] No data for {label}")
                    continue

                raw_count = len(df_raw)
                df_bars = process_ticks_to_bars(df_raw, TICKS_PER_BAR)
                bar_count = len(df_bars)
                print(f"  Raw Ticks: {raw_count:,} -> {TICKS_PER_BAR}-Tick Bars: {bar_count:,}")

                if not df_bars.empty:
                    all_bars.append(df_bars)
                    total_bars += len(df_bars)

                del df_raw
                gc.collect()

            except Exception as e:
                print(f"  [ERROR] Failed: {e}")

            # Checkpoint every 12 months
            if len(all_bars) >= 12:
                print(f"[CHECKPOINT] Saving {total_bars:,} bars...")
                combined = pd.concat(all_bars, ignore_index=True)
                if output_file.exists():
                    existing = pd.read_parquet(output_file)
                    combined = pd.concat([existing, combined], ignore_index=True)
                combined = (
                    combined.sort_values("timestamp")
                    .drop_duplicates(subset=["timestamp"])
                    .reset_index(drop=True)
                )
                combined.to_parquet(output_file, index=False)
                all_bars = []
                del combined
                gc.collect()

    # Final save
    if all_bars:
        print(f"[FINAL] Saving remaining bars...")
        combined = pd.concat(all_bars, ignore_index=True)
        if output_file.exists():
            existing = pd.read_parquet(output_file)
            combined = pd.concat([existing, combined], ignore_index=True)
        combined = (
            combined.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"])
            .reset_index(drop=True)
        )
        combined.to_parquet(output_file, index=False)

    if output_file.exists():
        final_df = pd.read_parquet(output_file)
        print("=" * 60)
        print("PIPELINE COMPLETE")
        print(f"Saved to: {output_file}")
        print(f"Total {TICKS_PER_BAR}-Tick Bars: {len(final_df):,}")
        print(f"Date Range: {final_df['timestamp'].min()} to {final_df['timestamp'].max()}")
        print("=" * 60)
    else:
        print("[ERROR] No data was downloaded successfully.")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
