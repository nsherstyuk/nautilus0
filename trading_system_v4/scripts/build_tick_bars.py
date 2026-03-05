"""
build_tick_bars.py — Robust Tick Bar Builder (resume-able, monthly saves)

Differences from download_tick_data.py:
  - Saves parquet after EVERY month (not every 12) — crash-safe
  - Resumes from last saved month automatically — never re-processes
  - Per-month asyncio timeout (default 240s) — never hangs forever
  - Logs to file + stdout with timestamps
  - All raw .bi5 data assumed already in tick_vault cache

Usage:
  python -m trading_system_v4.scripts.build_tick_bars
  python -m trading_system_v4.scripts.build_tick_bars --start 2020 --end 2025
"""
import argparse
import asyncio
import gc
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from tick_vault import download_range, read_tick_data

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL        = "EURUSD"  # overridden by --symbol arg
START_YEAR    = 2015
END_YEAR      = 2026
TICKS_PER_BAR = 1000
MONTH_TIMEOUT = 240  # seconds per month before giving up

ROOT     = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"

# Derived paths — recalculated after arg parsing in __main__
OUTPUT_FILE = DATA_DIR / f"{SYMBOL.lower()}_{TICKS_PER_BAR}t_bars.parquet"
LOG_FILE    = DATA_DIR / f"build_tick_bars_{SYMBOL.lower()}.log"

# ── Logging ───────────────────────────────────────────────────────────────────
DATA_DIR.mkdir(parents=True, exist_ok=True)

fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S")

handler_stdout = logging.StreamHandler(sys.stdout)
handler_stdout.setFormatter(fmt)

log = logging.getLogger("build")
log.setLevel(logging.DEBUG)
log.addHandler(handler_stdout)
# File handler added in __main__ after symbol is known


# ── Bar builder (identical logic to download_tick_data.py) ────────────────────
def process_ticks_to_bars(df: pd.DataFrame, ticks_per_bar: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    df["mid"]          = (df["ask"] + df["bid"]) / 2.0
    df["spread"]       = df["ask"] - df["bid"]
    df["vol_imbalance"] = df["ask_volume"] - df["bid_volume"]
    df = df.reset_index(drop=True)
    group_id = df.index // ticks_per_bar

    bars = df.groupby(group_id).agg(
        timestamp    = ("time",         "last"),
        open         = ("mid",          "first"),
        high         = ("mid",          "max"),
        low          = ("mid",          "min"),
        close        = ("mid",          "last"),
        tick_count   = ("mid",          "count"),
        avg_spread   = ("spread",       "mean"),
        max_spread   = ("spread",       "max"),
        vol_imbalance= ("vol_imbalance","sum"),
        buy_volume   = ("ask_volume",   "sum"),
        sell_volume  = ("bid_volume",   "sum"),
        duration_sec = ("time",         lambda x: (x.iloc[-1] - x.iloc[0]).total_seconds()),
    )
    bars = bars[bars["tick_count"] == ticks_per_bar].copy()
    bars["tick_velocity"] = ticks_per_bar / (bars["duration_sec"] + 1e-6)
    bars["total_volume"]  = bars["buy_volume"] + bars["sell_volume"]
    bars["buy_ratio"]     = bars["buy_volume"] / (bars["total_volume"] + 1e-6)
    bars = bars.drop(columns=["tick_count", "duration_sec"])
    bars = bars.reset_index(drop=True)
    return bars


# ── Resume logic ──────────────────────────────────────────────────────────────
def get_resume_point() -> tuple[int, int] | None:
    """Return (year, month) of the NEXT month to process based on existing parquet."""
    if not OUTPUT_FILE.exists():
        return None
    try:
        df = pd.read_parquet(OUTPUT_FILE, columns=["timestamp"])
        if df.empty:
            return None
        last_ts = pd.to_datetime(df["timestamp"].max())
        # advance by one month
        month = last_ts.month + 1
        year  = last_ts.year
        if month > 12:
            month = 1
            year += 1
        log.info(f"Existing parquet ends at {last_ts.strftime('%Y-%m-%d')} — "
                 f"resuming from {year}-{month:02d}")
        return year, month
    except Exception as e:
        log.warning(f"Could not read existing parquet ({e}) — starting from scratch")
        return None


def save_month(df_bars: pd.DataFrame) -> int:
    """Append month bars to parquet. Returns total row count after save."""
    if OUTPUT_FILE.exists():
        existing = pd.read_parquet(OUTPUT_FILE)
        combined = pd.concat([existing, df_bars], ignore_index=True)
        del existing
    else:
        combined = df_bars.copy()

    combined = (combined
                .sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True))
    combined.to_parquet(OUTPUT_FILE, index=False)
    n = len(combined)
    del combined
    gc.collect()
    return n


# ── Per-month async worker ────────────────────────────────────────────────────
async def process_month(year: int, month: int, symbol: str) -> pd.DataFrame:
    start_date = datetime(year, month, 1)
    end_date   = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)

    log.info(f"[{year}-{month:02d}] downloading/verifying cache …")
    await download_range(symbol=symbol, start=start_date, end=end_date)

    log.info(f"[{year}-{month:02d}] reading ticks …")
    df_raw = read_tick_data(symbol=symbol, start=start_date, end=end_date)

    if df_raw is None or df_raw.empty:
        log.warning(f"[{year}-{month:02d}] no tick data returned — skipping")
        return pd.DataFrame()

    raw_count = len(df_raw)
    log.info(f"[{year}-{month:02d}] {raw_count:,} ticks → building bars …")

    df_bars = process_ticks_to_bars(df_raw, TICKS_PER_BAR)
    del df_raw
    gc.collect()

    log.info(f"[{year}-{month:02d}] → {len(df_bars):,} bars")
    return df_bars


# ── Main ──────────────────────────────────────────────────────────────────────
async def main(start_year: int, end_year: int, symbol: str) -> None:
    log.info("=" * 60)
    log.info(f"build_tick_bars  {symbol}  {TICKS_PER_BAR}t  "
             f"{start_year}–{end_year}  timeout={MONTH_TIMEOUT}s/month")
    log.info(f"Output: {OUTPUT_FILE}")
    log.info("=" * 60)

    # Determine start point (resume support)
    resume = get_resume_point()

    months_ok      = 0
    months_skipped = 0
    months_error   = 0

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            # Don't go past current month
            now = datetime.now()
            if year > now.year or (year == now.year and month > now.month):
                break

            # Skip already-processed months if resuming
            if resume and (year, month) < resume:
                continue

            tag = f"{year}-{month:02d}"
            try:
                df_bars = await asyncio.wait_for(
                    process_month(year, month, symbol),
                    timeout=MONTH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                log.error(f"[{tag}] TIMEOUT after {MONTH_TIMEOUT}s — skipping")
                months_error += 1
                continue
            except Exception as e:
                log.error(f"[{tag}] ERROR: {e} — skipping")
                months_error += 1
                continue

            if df_bars.empty:
                months_skipped += 1
                continue

            # Save immediately after this month
            total_rows = save_month(df_bars)
            months_ok += 1
            log.info(f"[{tag}] SAVED  cumulative={total_rows:,} rows  "
                     f"(ok={months_ok} skip={months_skipped} err={months_error})")

    log.info("=" * 60)
    log.info(f"DONE  ok={months_ok}  skipped={months_skipped}  errors={months_error}")
    if OUTPUT_FILE.exists():
        df_final = pd.read_parquet(OUTPUT_FILE, columns=["timestamp"])
        log.info(f"Final parquet: {len(df_final):,} rows  "
                 f"{df_final['timestamp'].min()} → {df_final['timestamp'].max()}")
    log.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",  type=int, default=START_YEAR)
    parser.add_argument("--end",    type=int, default=END_YEAR)
    parser.add_argument("--symbol", type=str, default=SYMBOL,
                        help="Dukascopy symbol, e.g. EURUSD, XAUUSD, USDCAD")
    args = parser.parse_args()

    # Patch globals so get_resume_point() / save_month() use correct paths
    SYMBOL      = args.symbol.upper()
    OUTPUT_FILE = DATA_DIR / f"{SYMBOL.lower()}_{TICKS_PER_BAR}t_bars.parquet"
    LOG_FILE    = DATA_DIR / f"build_tick_bars_{SYMBOL.lower()}.log"

    # Add per-symbol file handler now that LOG_FILE is known
    handler_file = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler_file.setFormatter(fmt)
    log.addHandler(handler_file)

    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main(args.start, args.end, SYMBOL))
