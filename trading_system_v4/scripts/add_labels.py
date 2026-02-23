"""
add_labels.py — Label engineering for trading_system_v4

For each 5m bar, simulates a forward SL/TP trade and assigns:
  y = 1  (long TP hit first)
  y = 0  (long SL hit first)
  row dropped if neither hit within 60 bars

Label rules (copied from v3):
  atr       = atr_norm * close
  tp_level  = close + atr * 1.4
  sl_level  = close - atr * 1.8
  lookahead = 60 bars (~5 hours on 5m)

Input  : trading_system_v4/data/training_features.parquet
Output : trading_system_v4/data/training_labeled.parquet

Usage:
  python -m trading_system_v4.scripts.add_labels
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]

# Accept optional path overrides:
#   argv[1] = input parquet   (default: training_features.parquet)
#   argv[2] = output parquet  (default: training_labeled.parquet, or
#                               <input_stem>_labeled.parquet if input is custom)
_DATA_DIR = ROOT / "trading_system_v4" / "data"

if len(sys.argv) > 1:
    INPUT_PATH = Path(sys.argv[1])
else:
    INPUT_PATH = _DATA_DIR / "training_features.parquet"

if len(sys.argv) > 2:
    OUTPUT_PATH = Path(sys.argv[2])
else:
    # Auto-derive: training_features_htf.parquet → training_labeled_htf.parquet
    stem = INPUT_PATH.stem  # e.g. "training_features_htf"
    out_stem = stem.replace("training_features", "training_labeled")
    OUTPUT_PATH = INPUT_PATH.parent / f"{out_stem}.parquet"

# ── label parameters (Path-Dependent TP/SL) ─────────────────────────────────
LOOKAHEAD_BARS = 60          # ~5 hours on 5m chart
TP_ATR         = 1.5         # Take Profit distance in ATR
SL_ATR         = 1.0         # Stop Loss distance in ATR
SPREAD_EST     = 0.00010     # 1.0 pip spread penalty for FX


def _label_symbol(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign y_long and y_short labels using a Path-Dependent TP/SL approach.

    y_long = 1 if price hits +TP before -SL within LOOKAHEAD_BARS.
    y_short = 1 if price hits -TP before +SL within LOOKAHEAD_BARS.
    Rows where neither is hit are marked -1 (and dropped later).
    """
    n = len(df)

    close    = df["close"].to_numpy(dtype=np.float64)
    high     = df["high"].to_numpy(dtype=np.float64)
    low      = df["low"].to_numpy(dtype=np.float64)
    atr_norm = df["atr_norm"].to_numpy(dtype=np.float64)
    atr      = atr_norm * close
    
    y_long = np.full(n, -1, dtype=np.int8)
    y_short = np.full(n, -1, dtype=np.int8)

    # Fast numpy loop for path dependency
    for i in range(n - LOOKAHEAD_BARS):
        c = close[i]
        a = atr[i]
        
        # Long levels (incorporating spread penalty on entry)
        tp_l = (c + SPREAD_EST) + a * TP_ATR
        sl_l = (c + SPREAD_EST) - a * SL_ATR
        
        # Short levels (incorporating spread penalty on entry)
        tp_s = (c - SPREAD_EST) - a * TP_ATR
        sl_s = (c - SPREAD_EST) + a * SL_ATR
        
        # Future path
        h_path = high[i+1 : i+1+LOOKAHEAD_BARS]
        l_path = low[i+1 : i+1+LOOKAHEAD_BARS]
        
        # --- Long Evaluation ---
        hit_tp_l = h_path >= tp_l
        hit_sl_l = l_path <= sl_l
        
        idx_tp_l = np.argmax(hit_tp_l) if np.any(hit_tp_l) else LOOKAHEAD_BARS
        idx_sl_l = np.argmax(hit_sl_l) if np.any(hit_sl_l) else LOOKAHEAD_BARS
        
        if idx_tp_l < idx_sl_l:
            y_long[i] = 1
        elif idx_sl_l < idx_tp_l:
            y_long[i] = 0
        elif idx_tp_l == idx_sl_l and idx_tp_l < LOOKAHEAD_BARS:
            # Hit both in the same bar -> assume SL hit first (conservative)
            y_long[i] = 0
            
        # --- Short Evaluation ---
        hit_tp_s = l_path <= tp_s
        hit_sl_s = h_path >= sl_s
        
        idx_tp_s = np.argmax(hit_tp_s) if np.any(hit_tp_s) else LOOKAHEAD_BARS
        idx_sl_s = np.argmax(hit_sl_s) if np.any(hit_sl_s) else LOOKAHEAD_BARS
        
        if idx_tp_s < idx_sl_s:
            y_short[i] = 1
        elif idx_sl_s < idx_tp_s:
            y_short[i] = 0
        elif idx_tp_s == idx_sl_s and idx_tp_s < LOOKAHEAD_BARS:
            # Hit both in the same bar -> assume SL hit first (conservative)
            y_short[i] = 0

    out = df.copy()
    out["y_long"] = y_long
    out["y_short"] = y_short
    return out


def run() -> None:
    if not INPUT_PATH.exists():
        print(f"[ERROR] Input not found: {INPUT_PATH}")
        print("  Run: python -m trading_system_v4.scripts.build_training_dataset first")
        sys.exit(1)

    print(f"Loading {INPUT_PATH} …")
    df = pd.read_parquet(INPUT_PATH)
    print(f"  {len(df):,} rows × {df.shape[1]} cols — symbols: {sorted(df['symbol'].unique())}")

    # Ensure sorted within each symbol
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    # Sanity-check required columns
    required = {"close", "high", "low", "atr_norm", "symbol", "timestamp"}
    missing = required - set(df.columns)
    if missing:
        print(f"[ERROR] Missing columns: {missing}")
        sys.exit(1)

    print(f"\nLabelling per symbol (Path-Dependent TP={TP_ATR} ATR, SL={SL_ATR} ATR, Lookahead={LOOKAHEAD_BARS} bars) …")

    symbol_results: list[pd.DataFrame] = []
    total_rows_in  = 0
    total_rows_out = 0

    for symbol, grp in df.groupby("symbol", sort=True):
        grp_sorted = grp.sort_values("timestamp").reset_index(drop=True)
        rows_in = len(grp_sorted)
        total_rows_in += rows_in

        labelled = _label_symbol(grp_sorted)

        kept   = labelled[(labelled["y_long"] != -1) & (labelled["y_short"] != -1)].copy()
        kept["y_long"] = kept["y_long"].astype(np.int8)
        kept["y_short"] = kept["y_short"].astype(np.int8)
        rows_out = len(kept)
        total_rows_out += rows_out

        n_pos_long    = (kept["y_long"] == 1).sum()
        n_pos_short   = (kept["y_short"] == 1).sum()
        pct_pos_long  = 100.0 * n_pos_long / rows_out if rows_out else 0.0
        pct_pos_short = 100.0 * n_pos_short / rows_out if rows_out else 0.0
        dropped  = rows_in - rows_out

        print(
            f"  {symbol:<25}  in={rows_in:>7,}  kept={rows_out:>7,}  "
            f"dropped={dropped:>6,}  "
            f"long_pos={n_pos_long:>6,} ({pct_pos_long:.1f}%)  "
            f"short_pos={n_pos_short:>6,} ({pct_pos_short:.1f}%)"
        )
        symbol_results.append(kept)

    out = pd.concat(symbol_results, ignore_index=True)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    # ── summary ───────────────────────────────────────────────────────────────
    total_pos_long  = (out["y_long"] == 1).sum()
    total_pos_short = (out["y_short"] == 1).sum()
    total_drop = total_rows_in - total_rows_out
    pct_pos_long_total = 100.0 * total_pos_long / total_rows_out if total_rows_out else 0.0
    pct_pos_short_total = 100.0 * total_pos_short / total_rows_out if total_rows_out else 0.0

    print(f"\n{'─'*65}")
    print(f"  TOTAL  in={total_rows_in:>7,}  kept={total_rows_out:>7,}  dropped={total_drop:>6,}")
    print(f"  Label balance: {total_pos_long:,} long pos ({pct_pos_long_total:.1f}%)  /  {total_pos_short:,} short pos ({pct_pos_short_total:.1f}%)")
    print(f"{'─'*65}")

    if pct_pos_long_total < 20.0 or pct_pos_short_total < 20.0:
        print("[WARN] Positive rate < 20% — consider raising TP multiplier or lookahead")
    elif pct_pos_long_total > 55.0 or pct_pos_short_total > 55.0:
        print("[WARN] Positive rate > 55% — check for lookahead leakage or overly wide TP")
    else:
        print("[OK]  Label balance looks healthy (20–55% positives)")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nSaved → {OUTPUT_PATH}")
    print(f"  {len(out):,} rows × {out.shape[1]} cols")


if __name__ == "__main__":
    run()
