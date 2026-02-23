"""
add_htf_features.py — Inject 15m and 1D HTF features into the 5m training dataset.

Steps:
  1. Load 15m and 1D bars from the NautilusTrader Parquet catalog
  2. Compute the same 32 feature set on 15m and 1D bars per symbol
  3. Rename all feature columns to htf_<name> (15m) and d1_<name> (1D) prefix
  4. Load training_features.parquet (5m, 624k rows)
  5. Per symbol: pd.merge_asof (direction='backward') — each 5m bar gets the
     most recently *completed* 15m and 1D bar's features.
  6. Output: trading_system_v4/data/training_features_htf.parquet

Output feature count: 32 (5m) + 32 (15m) + 32 (1D) = 96 features.

Usage:
  python -m trading_system_v4.scripts.add_htf_features
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Re-use the exact same bar loader + feature engineering from sibling scripts
_SCRIPTS_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPTS_DIR.parents[1]
sys.path.insert(0, str(_ROOT))

from trading_system_v4.scripts.build_training_dataset import (
    _load_symbol_bars,
    BAR_ROOT,
)
from trading_system_v4.features.feature_engineering import add_features, _NON_FEATURE_COLS

# ── paths ──────────────────────────────────────────────────────────────────────
INPUT_5M_PATH  = _ROOT / "trading_system_v4" / "data" / "training_features.parquet"
OUTPUT_PATH    = _ROOT / "trading_system_v4" / "data" / "training_features_htf.parquet"

HTF_BAR_SIZE   = "15-MINUTE"
D1_BAR_SIZE    = "1-DAY"

# Columns that should NOT be prefixed / not carried over from HTF into 5m dataset
_HTF_DROP_COLS = frozenset({
    "ts_init", "ts_event", "open", "high", "low", "close", "volume",
    "symbol", "bar_size",
})

# Session / time-of-day features that are computed from the bar timestamp and are
# therefore IDENTICAL across 5m, 15m and 1D timeframes.  Carrying them under an
# htf_ / d1_ prefix wastes feature slots and distorts XGBoost importance scores.
_HTF_REMOVE_TIME_COLS = frozenset({
    "is_london", "is_ny", "hour_sin", "hour_cos",
})


def _load_htf_features(symbol: str, bar_size: str, prefix: str) -> pd.DataFrame | None:
    """
    Load bars for one symbol, compute features, return DataFrame with
    <prefix>_<feature> columns + timestamp.
    """
    matches = [
        d for d in BAR_ROOT.iterdir()
        if d.is_dir()
        and symbol.split(".")[0] in d.name
        and bar_size in d.name
    ]
    if not matches:
        print(f"  [WARN] No {bar_size} directory found for {symbol} under {BAR_ROOT}")
        return None

    sym_dir = matches[0]
    df = _load_symbol_bars(sym_dir, bar_size)
    if df is None or df.empty:
        return None

    df["symbol"] = symbol
    df = add_features(df)

    # Carry the raw bar midpoint so that close_vs_htf_midpoint can be
    # computed after the 5m merge (needs both 5m close and HTF midpoint).
    df["bar_midpoint"] = (df["open"].astype(float) + df["close"].astype(float)) / 2

    feature_cols = [
        c for c in df.columns
        if c not in _HTF_DROP_COLS
        and c != "timestamp"
        and c not in _HTF_REMOVE_TIME_COLS
    ]
    rename_map   = {c: f"{prefix}_{c}" for c in feature_cols}
    htf_df = df[["timestamp"] + feature_cols].rename(columns=rename_map)
    htf_df = htf_df.sort_values("timestamp").reset_index(drop=True)

    return htf_df


def run() -> None:
    if not INPUT_5M_PATH.exists():
        print(f"[ERROR] Input not found: {INPUT_5M_PATH}")
        print("  Run: python -m trading_system_v4.scripts.build_training_dataset first")
        sys.exit(1)

    print(f"Loading 5m features from {INPUT_5M_PATH} …")
    df_5m = pd.read_parquet(INPUT_5M_PATH)
    print(f"  {len(df_5m):,} rows × {df_5m.shape[1]} cols")
    print(f"  Symbols: {sorted(df_5m['symbol'].unique())}")

    df_5m = df_5m.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    merged_parts: list[pd.DataFrame] = []

    for symbol in sorted(df_5m["symbol"].unique()):
        df_sym = df_5m[df_5m["symbol"] == symbol].copy().reset_index(drop=True)
        n_5m   = len(df_sym)

        print(f"\n  {symbol}: loading 15m and 1D bars …")
        htf_df = _load_htf_features(symbol, HTF_BAR_SIZE, "htf")
        d1_df  = _load_htf_features(symbol, D1_BAR_SIZE, "d1")

        if htf_df is None or d1_df is None:
            print(f"    [SKIP] Missing 15m or 1D data — symbol will be excluded")
            continue

        print(f"    15m bars: {len(htf_df):,} rows  (NaN warm-up: {htf_df.isna().any(axis=1).sum():,})")
        print(f"    1D bars:  {len(d1_df):,} rows  (NaN warm-up: {d1_df.isna().any(axis=1).sum():,})")

        # ── No-lookahead merge ─────────────────────────────────────────────────
        merged = pd.merge_asof(
            df_sym,
            htf_df,
            on="timestamp",
            direction="backward",
            suffixes=("", "_htf_dup"),
        )
        merged = merged[[c for c in merged.columns if not c.endswith("_htf_dup")]]

        merged = pd.merge_asof(
            merged,
            d1_df,
            on="timestamp",
            direction="backward",
            suffixes=("", "_d1_dup"),
        )
        merged = merged[[c for c in merged.columns if not c.endswith("_d1_dup")]]

        # Derived cross-timeframe feature: 5m close position vs prior 15m bar midpoint.
        # Dimensionless ratio (positive = 5m close above 15m midpoint).
        if "htf_bar_midpoint" in merged.columns:
            merged["close_vs_htf_midpoint"] = (
                (merged["close"].astype(float) - merged["htf_bar_midpoint"])
                / (merged["close"].astype(float).abs() + 1e-10)
            )

        htf_feature_cols = [c for c in merged.columns if c.startswith("htf_") or c.startswith("d1_")]
        n_htf_cols       = len(htf_feature_cols)

        n_before    = len(merged)
        merged_clean = merged.dropna(subset=htf_feature_cols)
        n_after     = len(merged_clean)
        n_dropped   = n_before - n_after

        print(
            f"    5m rows: {n_5m:,}  →  after HTF/1D join+dropna: {n_after:,}  "
            f"(dropped {n_dropped:,} warm-up rows)  htf_cols={n_htf_cols}"
        )
        merged_parts.append(merged_clean)

    if not merged_parts:
        print("[ERROR] No symbols merged — check 15m data availability")
        sys.exit(1)

    out = pd.concat(merged_parts, ignore_index=True)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    n_5m_features  = len([c for c in out.columns if c not in _HTF_DROP_COLS
                          and not c.startswith("htf_") and not c.startswith("d1_") and c not in {"timestamp", "symbol", "bar_size", "y"}])
    n_htf_features = len([c for c in out.columns if c.startswith("htf_")])
    n_d1_features  = len([c for c in out.columns if c.startswith("d1_")])

    print(f"\n{'─'*65}")
    print(f"  Output: {len(out):,} rows × {out.shape[1]} cols")
    print(f"  5m features:  {n_5m_features}")
    print(f"  15m features: {n_htf_features}")
    print(f"  1D features:  {n_d1_features}")
    print(f"  Total features: {n_5m_features + n_htf_features + n_d1_features}")
    print(f"{'─'*65}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUTPUT_PATH, index=False)
    print(f"Saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    run()
