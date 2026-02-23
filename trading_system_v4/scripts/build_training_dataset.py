"""
Script to build training dataset for hybrid modular trading system (v4).

- Loads NautilusTrader Parquet bar files from data/historical/data/bar/
- Decodes NautilusTrader binary-encoded price columns (little-endian int64 / 1e9)
- Filters to a single bar size (default: 5-MINUTE) to avoid mixing timeframes
- Processes each symbol independently to prevent cross-symbol contamination
- Derives UTC timestamp from ts_init (nanoseconds)
- Handles FX zero-volume by substituting 1.0 (volume features become neutral)
- Applies add_features(df) for all 35 features
- Outputs: trading_system_v4/data/training_features.parquet

Usage:
    python -m trading_system_v4.scripts.build_training_dataset [BAR_SIZE]
    BAR_SIZE default: 5-MINUTE
    Examples: 1-MINUTE, 15-MINUTE, 5-MINUTE
"""
import os
import struct
import sys
import pandas as pd
import numpy as np
from pathlib import Path

from trading_system_v4.features.feature_engineering import add_features

# ── constants ────────────────────────────────────────────────────────────────

BAR_ROOT = Path(r"c:\nautilus0\data\historical\data\bar")
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "training_features.parquet"

# NautilusTrader stores Price/Quantity as little-endian int64 with factor 1e9
NAUTILUS_PRICE_FACTOR = 1e9

# ── helpers ──────────────────────────────────────────────────────────────────

def _decode_nautilus_bytes(series: pd.Series) -> pd.Series:
    """
    Decode NautilusTrader binary-encoded price/quantity bytes columns.
    Each value is an 8-byte little-endian int64 representing price * 1e9.
    """
    def _decode(val):
        if isinstance(val, (bytes, bytearray)) and len(val) == 8:
            return struct.unpack('<q', val)[0] / NAUTILUS_PRICE_FACTOR
        return float('nan')
    return series.apply(_decode)


def _load_symbol_bars(symbol_dir: Path, bar_size: str) -> pd.DataFrame | None:
    """
    Load and decode all Parquet files for one symbol/bar-size folder.
    Returns None if no files found or decoding fails.
    """
    parquet_files = sorted(symbol_dir.glob("*.parquet"))
    if not parquet_files:
        return None

    dfs = []
    for f in parquet_files:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
        except Exception as exc:
            print(f"  [WARN] Failed to read {f.name}: {exc}")

    if not dfs:
        return None

    data = pd.concat(dfs, ignore_index=True)

    # ── Decode NautilusTrader binary-encoded price columns ──────────────
    for col in ("open", "high", "low", "close", "volume"):
        if col not in data.columns:
            continue
        if data[col].dtype == object:
            data[col] = _decode_nautilus_bytes(data[col])
        else:
            data[col] = pd.to_numeric(data[col], errors="coerce")

    # ── FX MID bars have no real volume → substitute 1.0 ───────────────
    if "volume" not in data.columns or data["volume"].isna().all() or (data["volume"] == 0).all():
        data["volume"] = 1.0
    else:
        data["volume"] = data["volume"].replace(0, 1.0)

    # ── Derive UTC timestamp from ts_init (nanoseconds) ─────────────────
    if "ts_init" in data.columns:
        data["timestamp"] = pd.to_datetime(data["ts_init"], unit="ns", utc=True)
    elif "ts_event" in data.columns:
        data["timestamp"] = pd.to_datetime(data["ts_event"], unit="ns", utc=True)
    else:
        print(f"  [WARN] No timestamp column found in {symbol_dir.name}")
        return None

    # ── Drop rows with invalid prices ────────────────────────────────────
    price_cols = ["open", "high", "low", "close"]
    before = len(data)
    data = data.dropna(subset=price_cols)
    dropped = before - len(data)
    if dropped > 0:
        print(f"  [WARN] Dropped {dropped} rows with NaN prices in {symbol_dir.name}")

    # ── Sort chronologically ─────────────────────────────────────────────
    data = data.sort_values("timestamp").reset_index(drop=True)

    # ── Tag with symbol and bar_size ─────────────────────────────────────
    # Derive clean symbol name from folder: e.g. "EURUSD.IDEALPRO-5-MINUTE-MID-EXTERNAL"
    # → symbol = "EURUSD.IDEALPRO", bar_size = "5-MINUTE"
    data["symbol"] = symbol_dir.name.split("-")[0]          # e.g. "EURUSD.IDEALPRO"
    data["bar_size"] = bar_size

    return data


# ── main ─────────────────────────────────────────────────────────────────────

def main(bar_size: str = "5-MINUTE") -> None:
    print(f"Building training dataset — bar_size={bar_size}")

    if not BAR_ROOT.exists():
        print(f"[ERROR] bar root not found: {BAR_ROOT}")
        sys.exit(1)

    # Discover all folders matching the requested bar size
    matching_dirs = [
        d for d in BAR_ROOT.iterdir()
        if d.is_dir() and f"-{bar_size}-" in d.name
    ]
    if not matching_dirs:
        print(f"[ERROR] No folders found matching bar_size='{bar_size}' under {BAR_ROOT}")
        sys.exit(1)

    print(f"Found {len(matching_dirs)} symbol/timeframe folders:")
    for d in sorted(matching_dirs):
        print(f"  {d.name}")

    # ── Load + feature-engineer per symbol independently ─────────────────
    # CRITICAL: must NOT concatenate across symbols before add_features().
    # Cross-symbol rows would corrupt open_gap, return_1, ATR, EMA etc.
    result_dfs = []
    for symbol_dir in sorted(matching_dirs):
        print(f"\nProcessing: {symbol_dir.name}")
        raw = _load_symbol_bars(symbol_dir, bar_size)
        if raw is None or raw.empty:
            print("  [SKIP] No usable data.")
            continue

        print(f"  Loaded {len(raw)} rows  [{raw['timestamp'].iloc[0]} → {raw['timestamp'].iloc[-1]}]")

        try:
            featured = add_features(raw)
        except Exception as exc:
            print(f"  [ERROR] Feature engineering failed: {exc}")
            continue

        result_dfs.append(featured)
        print(f"  Features computed. Shape: {featured.shape}")

    if not result_dfs:
        print("[ERROR] No data after processing. Nothing to save.")
        sys.exit(1)

    # ── Combine all symbols ───────────────────────────────────────────────
    final = pd.concat(result_dfs, ignore_index=True)
    final = final.sort_values("timestamp").reset_index(drop=True)

    # ── Report NaN coverage ───────────────────────────────────────────────
    feature_cols = [c for c in final.columns if c not in
                    ("timestamp", "symbol", "bar_size", "ts_init", "ts_event",
                     "open", "high", "low", "close", "volume")]
    nan_pct = final[feature_cols].isna().mean().sort_values(ascending=False)
    high_nan = nan_pct[nan_pct > 0.05]
    if not high_nan.empty:
        print("\n[WARN] Features with >5% NaN (expected for warm-up rows):")
        print(high_nan.to_string())

    # ── Save ──────────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    final.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nSaved {len(final)} rows x {final.shape[1]} columns → {OUTPUT_PATH}")
    print(f"Symbols: {sorted(final['symbol'].unique())}")
    print(f"Date range: {final['timestamp'].min()} → {final['timestamp'].max()}")


if __name__ == "__main__":
    bar_size_arg = sys.argv[1] if len(sys.argv) > 1 else "5-MINUTE"
    main(bar_size_arg)
