"""
meta_labeling_v3_signal.py — Meta-Labeling Pipeline on v3 HMTF XGB Signals

This script replaces the broken breakout base-signal with the production v3
XGBoost model signals, which have confirmed OOS edge of +19 pp (2015-2023).

Architecture:
1. Base Signal:  v3 XGB model on 15m bars (confidence ≥ CONF_THRESHOLD).
2. Trade Sim:    TP = TP_ATR × ATR14, SL = SL_ATR × ATR14 on 15m OHLCV path.
3. Meta-Labels:  y_tp = 1 if TP hit before SL; y_mfe = max excursion before SL.
4. Features:     v3 50-feature vector + model_confidence + extra meta-context.

The resulting dataset trains a meta-model that answers:
"Given that the v3 model flagged this 15m bar with high confidence,
 what is the probability it will hit TP before SL — and how far will it go?"

Output columns:
  - All 50 v3 feature columns (already shift(1)-clean, no lookahead)
  - model_confidence   : max(P0, P1) from the base XGB model
  - direction          : +1 (LONG) or -1 (SHORT)
  - conf_x_direction   : confidence signed by direction (interaction feature)
  - y_tp               : 1 = hit TP, 0 = hit SL (binary classification target)
  - y_mfe              : MFE in ATR multiples before SL (regression target)
  - timestamp          : bar close timestamp (UTC)
  - bar_idx            : integer position in 15m frame

Usage:
  python -m trading_system_v4.scripts.meta_labeling_v3_signal
  python -m trading_system_v4.scripts.meta_labeling_v3_signal --threshold 0.70
"""
import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DATA_DIR   = ROOT / "trading_system_v4" / "data"
INPUT_FILE = DATA_DIR / "eurusd_1000t_bars.parquet"
MODEL_PATH = ROOT / "models" / "ml_model_mtf_v3_xgb.pkl"

from strategies.feature_engineering_v3 import (  # noqa: E402
    FEATURE_COLUMNS_V3,
    compute_v3_features,
)

# ── Defaults ──────────────────────────────────────────────────────────────────
CONF_THRESHOLD = 0.65    # base XGB confidence gate (LONG or SHORT)
SL_ATR         = 1.4     # stop-loss in ATR multiples (matches live config)
TP_ATR         = 1.5     # take-profit in ATR multiples
LOOKAHEAD_BARS = 100     # max 15m bars to hold the trade
SPREAD_EST     = 0.0001  # ~1 pip fixed spread cost


# ── ATR (14-period, Wilder/EWM) ───────────────────────────────────────────────
def _atr14(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(com=13, adjust=False).mean()


# ── Core MFE / TP simulation on 15m bars ──────────────────────────────────────
def _simulate(
    signal_positions: np.ndarray,
    directions: np.ndarray,
    close_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    atr_arr: np.ndarray,
    n_bars: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    For each signal bar, simulate a trade entry on the next bar's open
    (approximated as bar's close + spread) and compute:
      y_tp  : 1 if TP_ATR hit before SL_ATR, else 0
      y_mfe : maximum favourable excursion in ATR multiples before SL hit

    Returns two arrays, same length as signal_positions.
    """
    y_tp  = np.zeros(len(signal_positions), dtype=np.float32)
    y_mfe = np.zeros(len(signal_positions), dtype=np.float32)

    for k, (pos, direction) in enumerate(zip(signal_positions, directions)):
        if pos + LOOKAHEAD_BARS >= n_bars:
            y_tp[k]  = np.nan
            y_mfe[k] = np.nan
            continue

        c = close_arr[pos]
        a = atr_arr[pos]
        if not np.isfinite(a) or a <= 0:
            y_tp[k]  = np.nan
            y_mfe[k] = np.nan
            continue

        h_path = high_arr[pos + 1 : pos + 1 + LOOKAHEAD_BARS]
        l_path = low_arr[ pos + 1 : pos + 1 + LOOKAHEAD_BARS]

        if direction == 1:  # LONG
            entry    = c + SPREAD_EST
            sl_level = entry - a * SL_ATR
            tp_level = entry + a * TP_ATR
            # Find first SL bar
            sl_hits  = l_path <= sl_level
            idx_sl   = int(np.argmax(sl_hits)) if sl_hits.any() else LOOKAHEAD_BARS
            # Find first TP bar (before SL)
            tp_hits  = h_path[:idx_sl] >= tp_level
            idx_tp   = int(np.argmax(tp_hits)) if tp_hits.any() else LOOKAHEAD_BARS
            if tp_hits.any() and idx_tp < idx_sl:
                y_tp[k] = 1.0
            # MFE = highest high in [entry, SL hit) excursion in ATR units
            window   = h_path[:idx_sl] if idx_sl > 0 else np.array([c])
            y_mfe[k] = float((np.max(window) - entry) / a)
        else:  # SHORT
            entry    = c - SPREAD_EST
            sl_level = entry + a * SL_ATR
            tp_level = entry - a * TP_ATR
            sl_hits  = h_path >= sl_level
            idx_sl   = int(np.argmax(sl_hits)) if sl_hits.any() else LOOKAHEAD_BARS
            tp_hits  = l_path[:idx_sl] <= tp_level
            idx_tp   = int(np.argmax(tp_hits)) if tp_hits.any() else LOOKAHEAD_BARS
            if tp_hits.any() and idx_tp < idx_sl:
                y_tp[k] = 1.0
            window   = l_path[:idx_sl] if idx_sl > 0 else np.array([c])
            y_mfe[k] = float((entry - np.min(window)) / a)

    return y_tp, y_mfe


# ── Main ──────────────────────────────────────────────────────────────────────
def run(threshold: float = CONF_THRESHOLD) -> None:
    output_file = DATA_DIR / f"meta_labeled_v3_signal_thr{int(threshold*100):02d}.parquet"

    if not INPUT_FILE.exists():
        print(f"[ERROR] Tick bar data not found: {INPUT_FILE}")
        return
    if not MODEL_PATH.exists():
        print(f"[ERROR] v3 XGB model not found: {MODEL_PATH}")
        return

    # ── 1. Load tick bars and resample to 15m ─────────────────────────────────
    print(f"Loading tick bars from {INPUT_FILE} ...")
    tick = pd.read_parquet(INPUT_FILE)
    tick["timestamp"] = pd.to_datetime(tick["timestamp"], utc=True)
    tick = tick.sort_values("timestamp").set_index("timestamp")
    df15 = (
        tick.resample("15min", label="right", closed="right")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("total_volume", "sum"),
        )
        .dropna()
    )
    print(f"15m bars: {len(df15):,}  ({df15.index[0]} → {df15.index[-1]})")

    # ── 2. Compute ATR on 15m frame ──────────────────────────────────────────
    atr_series = _atr14(df15)

    # ── 3. Compute v3 features ──────────────────────────────────────────────
    print("Computing v3 features ...")
    feats = compute_v3_features(df15)                     # shape: (n_bars, 50)

    # ── 4. Run v3 XGB model ─────────────────────────────────────────────────
    print(f"Loading model from {MODEL_PATH} ...")
    model = joblib.load(MODEL_PATH)

    X = feats[FEATURE_COLUMNS_V3].astype(float).replace([np.inf, -np.inf], np.nan)
    valid_mask = X.notna().all(axis=1)
    X_clean = X[valid_mask]
    print(f"Valid feature rows: {len(X_clean):,}")

    proba     = model.predict_proba(X_clean.values)       # (n, 2)
    p0, p1    = proba[:, 0], proba[:, 1]
    conf      = np.maximum(p0, p1)                        # max(P_short, P_long)
    direction = np.where(p1 >= p0, 1, -1)                 # +1 LONG, -1 SHORT

    # ── 5. Gate on confidence threshold ─────────────────────────────────────
    gate = conf >= threshold
    print(f"Signals at threshold {threshold:.2f}: {gate.sum():,} / {len(X_clean):,}")

    signal_ts  = X_clean.index[gate]                      # DatetimeIndex (UTC)
    signal_dir = direction[gate]
    signal_cf  = conf[gate]

    # Map signal timestamps → integer positions in the 15m frame
    ts_to_pos = {ts: i for i, ts in enumerate(df15.index)}
    positions  = np.array([ts_to_pos.get(ts, -1) for ts in signal_ts])
    valid_pos  = positions >= 0
    signal_ts  = signal_ts[valid_pos]
    signal_dir = signal_dir[valid_pos]
    signal_cf  = signal_cf[valid_pos]
    positions  = positions[valid_pos]

    # ── 6. Simulate MFE / TP ─────────────────────────────────────────────────
    print(f"Simulating {len(positions):,} trades (SL={SL_ATR}×ATR, TP={TP_ATR}×ATR) ...")
    close_arr = df15["close"].to_numpy()
    high_arr  = df15["high"].to_numpy()
    low_arr   = df15["low"].to_numpy()
    atr_arr   = atr_series.to_numpy()
    n_bars    = len(df15)

    y_tp, y_mfe = _simulate(
        positions, signal_dir, close_arr, high_arr, low_arr, atr_arr, n_bars
    )

    # ── 7. Assemble output DataFrame ──────────────────────────────────────────
    print("Assembling meta-labeled dataset ...")
    feats_at_signals = X_clean.loc[signal_ts].copy()      # 50 v3 features

    meta_df = feats_at_signals.copy()
    meta_df["model_confidence"]  = signal_cf
    meta_df["direction"]         = signal_dir.astype(np.float32)
    meta_df["conf_x_direction"]  = signal_cf * signal_dir
    meta_df["bar_idx"]           = positions
    meta_df["y_tp"]              = y_tp
    meta_df["y_mfe"]             = y_mfe
    meta_df.index.name           = "timestamp"

    # Drop rows where simulation hit the end of data (nan)
    meta_df = meta_df.dropna(subset=["y_tp", "y_mfe"]).reset_index()

    # ── 8. Print summary ─────────────────────────────────────────────────────
    n   = len(meta_df)
    wr  = meta_df["y_tp"].mean()
    be  = SL_ATR / (SL_ATR + TP_ATR)
    print(f"\n{'='*60}")
    print(f"META-LABELING COMPLETE  (threshold={threshold:.2f})")
    print(f"  Total signal rows     : {n:,}")
    print(f"  Win rate (y_tp=1)     : {wr*100:.1f}%  (break-even {be*100:.1f}%)")
    print(f"  Edge                  : {(wr-be)*100:+.1f} pp")
    print(f"  Mean MFE (ATR)        : {meta_df['y_mfe'].mean():.3f}")
    print(f"  MFE ≥ TP_ATR ({TP_ATR})  : {(meta_df['y_mfe'] >= TP_ATR).mean()*100:.1f}%")
    print(f"  Feature columns       : {len(FEATURE_COLUMNS_V3)} v3 + 3 meta = "
          f"{len(FEATURE_COLUMNS_V3) + 3}")
    print(f"{'='*60}")

    # ── 9. Period breakdown ─────────────────────────────────────────────────
    ts_col = pd.DatetimeIndex(meta_df["timestamp"])
    for label, s, e in [
        ("OOS-EARLY  2015-2023", pd.Timestamp("2015-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")),
        ("IN-SAMPLE  2024-2025", pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")),
        ("OOS-RECENT 2026+    ", pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2030-01-01", tz="UTC")),
    ]:
        mask = (ts_col >= s) & (ts_col < e)
        sub  = meta_df[mask]
        if len(sub) == 0:
            continue
        wr_p = sub["y_tp"].mean()
        print(f"  {label}: n={len(sub):,}  WR={wr_p*100:.1f}%  edge={+(wr_p-be)*100:+.1f}pp")

    # ── 10. Save ─────────────────────────────────────────────────────────────
    meta_df.to_parquet(output_file, index=False)
    print(f"\nSaved → {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Meta-labeling pipeline on v3 XGB signals")
    parser.add_argument(
        "--threshold", type=float, default=CONF_THRESHOLD,
        help=f"Confidence gate for base signal (default {CONF_THRESHOLD})"
    )
    args = parser.parse_args()
    run(threshold=args.threshold)
