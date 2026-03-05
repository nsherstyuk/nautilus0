"""
download_fx_weekly.py -- Download FX tick data from Dukascopy week-by-week.

Downloads in small weekly chunks to avoid worker timeouts, with automatic
retry logic. Processes ticks into 1000-tick bars and saves as parquet.

Usage:
  python -m trading_system_v4.scripts.download_fx_weekly GBPUSD
  python -m trading_system_v4.scripts.download_fx_weekly USDJPY --start-year 2020
"""
import argparse
import asyncio
import gc
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from tick_vault import download_range, read_tick_data

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
TICKS_PER_BAR = 1000
MAX_RETRIES = 3
RETRY_DELAY = 10  # seconds


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


def save_checkpoint(all_bars, output_file, total_bars):
    """Save accumulated bars to parquet."""
    if not all_bars:
        return
    print(f"  [SAVE] Writing {total_bars:,} bars to {output_file.name}")
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
    return combined


async def download_week(symbol, start, end, retries=MAX_RETRIES):
    """Download one week with retry logic."""
    for attempt in range(1, retries + 1):
        try:
            await asyncio.wait_for(
                download_range(symbol=symbol, start=start, end=end),
                timeout=120,  # 2 min timeout per week
            )
            df = read_tick_data(symbol=symbol, start=start, end=end)
            return df
        except asyncio.TimeoutError:
            print(f"    [TIMEOUT] Attempt {attempt}/{retries} -- retrying in {RETRY_DELAY}s")
            if attempt < retries:
                await asyncio.sleep(RETRY_DELAY)
        except Exception as e:
            print(f"    [ERROR] Attempt {attempt}/{retries}: {e}")
            if attempt < retries:
                await asyncio.sleep(RETRY_DELAY)
    print(f"    [SKIP] Failed after {retries} attempts")
    return None


def generate_weeks(start_year, end_year):
    """Generate (week_start, week_end) tuples."""
    current = datetime(start_year, 1, 1)
    end = datetime(end_year + 1, 1, 1)
    now = datetime.now()
    if end > now:
        end = now

    while current < end:
        week_end = min(current + timedelta(days=7), end)
        yield current, week_end
        current = week_end


async def main():
    parser = argparse.ArgumentParser(
        description="Download FX tick data week-by-week from Dukascopy")
    parser.add_argument("symbol", help="e.g. GBPUSD, USDJPY")
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()

    symbol = args.symbol.upper()
    output_file = DATA_DIR / f"{symbol.lower()}_{TICKS_PER_BAR}t_bars.parquet"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    weeks = list(generate_weeks(args.start_year, args.end_year))
    total_weeks = len(weeks)

    print(f"Download {symbol} tick data")
    print(f"Period: {args.start_year} to {args.end_year} ({total_weeks} weeks)")
    print(f"Output: {output_file}")
    print("-" * 60)

    all_bars = []
    total_bars = 0
    failed_weeks = 0
    t0 = time.time()

    for i, (ws, we) in enumerate(weeks, 1):
        label = ws.strftime("%Y-%m-%d")
        pct = i / total_weeks * 100
        elapsed = time.time() - t0
        rate = i / elapsed if elapsed > 0 else 0
        eta = (total_weeks - i) / rate / 60 if rate > 0 else 0

        sys.stdout.write(
            f"\r[{i}/{total_weeks}] ({pct:.0f}%) {symbol} {label}"
            f" | bars={total_bars:,} | ETA={eta:.0f}m   "
        )
        sys.stdout.flush()

        df_raw = await download_week(symbol, ws, we)

        if df_raw is None or df_raw.empty:
            failed_weeks += 1
            continue

        df_bars = process_ticks_to_bars(df_raw, TICKS_PER_BAR)
        if not df_bars.empty:
            all_bars.append(df_bars)
            total_bars += len(df_bars)

        del df_raw
        gc.collect()

        # Checkpoint every 52 weeks (~1 year)
        if len(all_bars) >= 52:
            print()
            save_checkpoint(all_bars, output_file, total_bars)
            all_bars = []
            gc.collect()

    # Final save
    print()
    if all_bars:
        save_checkpoint(all_bars, output_file, total_bars)

    elapsed_min = (time.time() - t0) / 60

    if output_file.exists():
        final_df = pd.read_parquet(output_file)
        print("=" * 60)
        print(f"COMPLETE: {symbol}")
        print(f"  File: {output_file}")
        print(f"  Bars: {len(final_df):,}")
        print(f"  Range: {final_df['timestamp'].min()} to {final_df['timestamp'].max()}")
        print(f"  Time: {elapsed_min:.1f} min")
        print(f"  Failed weeks: {failed_weeks}/{total_weeks}")
        print("=" * 60)
    else:
        print(f"[ERROR] No data downloaded for {symbol}")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
