"""
train_model.py — Walk-forward training for trading_system_v4

Walk-forward CV (3 folds, time-ordered):
  Fold 1 : train year ≤ 2023,  test 2024
  Fold 2 : train year ≤ 2024,  test 2025
  Fold 3 : train year ≤ 2025,  test 2026 YTD

Final model trained on ALL data, then isotonic-calibrated on a held-out
20% slice (by time) to avoid leaking calibration signal into training.

Outputs (in trading_system_v4/model/):
  hybrid_model_v1.pkl     — XGBClassifier (fitted on all train data)
  calibrator_v1.pkl       — CalibratedClassifierCV (isotonic, cv='prefit')
  feature_list_v1.json    — ordered feature name list for inference parity

Usage:
  python -m trading_system_v4.scripts.train_model --direction long
  python -m trading_system_v4.scripts.train_model --input <labeled.parquet> --stem <model_stem> --symbol [SYMBOL] --direction [long|short]
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

# ── paths ──────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parents[2]
_DATA_DIR = ROOT / "trading_system_v4" / "data"
MODEL_DIR = ROOT / "trading_system_v4" / "model"

parser = argparse.ArgumentParser()
parser.add_argument("--input", type=str, default=str(_DATA_DIR / "training_labeled_htf.parquet"))
parser.add_argument("--stem", type=str, default="hybrid_model_v4")
parser.add_argument("--symbol", type=str, default=None)
parser.add_argument("--direction", type=str, choices=["long", "short"], required=True)
args = parser.parse_args()

INPUT_PATH = Path(args.input)
_MODEL_STEM = args.stem
_SYMBOL_FILTER = args.symbol
_DIRECTION = args.direction

if _SYMBOL_FILTER is not None:
    _sym_slug = _SYMBOL_FILTER.split(".")[0].lower()
    _MODEL_STEM = f"{_MODEL_STEM}_{_sym_slug}"

_MODEL_STEM = f"{_MODEL_STEM}_{_DIRECTION}"

MODEL_PATH        = MODEL_DIR / f"{_MODEL_STEM}.pkl"
CALIBRATOR_PATH   = MODEL_DIR / f"{_MODEL_STEM}_calibrator.pkl"
FEATURE_LIST_PATH = MODEL_DIR / f"{_MODEL_STEM}_features.json"

# ── constants ─────────────────────────────────────────────────────────────────
THRESHOLD  = 0.60    # inference decision threshold (overridden by EV search)
EVAL_FRAC  = 0.20    # fraction of final train set held out for threshold search

FEATURE_COLS: list[str] = [
    # Price action
    "body_ratio", "close_position", "upper_wick", "lower_wick", "bar_range_norm",
    # Momentum
    "return_1", "return_5", "return_12", "return_24",
    # Volatility
    "atr_ratio", "atr_norm", "vol_5", "vol_20", "vol_ratio",
    # Trend/EMA
    "ema_ratio_5_20", "close_vs_ema20", "close_vs_ema50", "close_vs_ema200",
    # Oscillators
    "rsi_14", "adx_14",
    # Session/time
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "is_london", "is_ny", "is_overlap", "is_session_open",
    # Regime
    "vol_regime", "range_position",
    # Pattern
    "return_max_10", "return_min_10",
]

# Walk-forward fold definitions (train_years = year ≤ cutoff, test_year = year)
FOLDS = [
    {"name": "Fold 1", "train_cutoff": 2023, "test_year": 2024},
    {"name": "Fold 2", "train_cutoff": 2024, "test_year": 2025},
    {"name": "Fold 3", "train_cutoff": 2025, "test_year": 2026},
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_xgb(scale_pos_weight: float) -> XGBClassifier:
    return XGBClassifier(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=10,
        scale_pos_weight=scale_pos_weight,
        eval_metric="logloss",
        use_label_encoder=False,
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )


def _find_optimal_threshold(y_true: np.ndarray, proba: np.ndarray) -> float:
    """
    Find the threshold that maximises Total Expected Profit assuming a 1:1 Risk/Reward.
    EV per trade = (precision * 1.0) - ((1 - precision) * 1.0) = 2 * precision - 1
    Total Profit = EV * number_of_signals
    """
    best_profit = -999.0
    best_thresh = 0.50

    # Scan thresholds from 0.50 to 0.90
    for t in np.arange(0.50, 0.91, 0.01):
        y_pred = (proba >= t).astype(int)
        n_signals = y_pred.sum()
        if n_signals < 50:  # ignore thresholds with too few signals to be statistically valid
            continue
        
        prec = precision_score(y_true, y_pred, zero_division=0)
        
        # Expected profit assuming 1:1 RR
        profit = (2 * prec - 1) * n_signals
        
        if profit > best_profit:
            best_profit = profit
            best_thresh = t

    return float(best_thresh)


def _metrics(y_true: np.ndarray, proba: np.ndarray, threshold: float, label: str) -> None:
    y_pred = (proba >= threshold).astype(int)
    n_signals = y_pred.sum()
    if n_signals == 0:
        print(f"  {label}: NO signals at threshold {threshold}")
        return
    prec  = precision_score(y_true, y_pred, zero_division=0)
    rec   = recall_score(y_true, y_pred, zero_division=0)
    f1    = f1_score(y_true, y_pred, zero_division=0)
    auc   = roc_auc_score(y_true, proba)
    print(
        f"  {label}:  precision@{threshold}={prec:.3f}  recall={rec:.3f}  "
        f"f1={f1:.3f}  AUC={auc:.3f}  signals={n_signals:,}/{len(y_true):,}"
    )
    if prec < 0.65:
        print(f"    [WARN] precision@{threshold} below 0.65 target")


# Non-feature columns excluded during auto-detection
_NON_FEATURE_COLS_TRAIN = frozenset({
    'timestamp', 'symbol', 'bar_size',
    'ts_init', 'ts_event',
    'open', 'high', 'low', 'close', 'volume',
    'y', 'y_long', 'y_short',
})


def _detect_feature_cols(df: pd.DataFrame) -> list[str]:
    """Auto-detect feature columns from a labeled DataFrame."""
    cols = [c for c in df.columns if c not in _NON_FEATURE_COLS_TRAIN]
    return cols


def _split_xy(df: pd.DataFrame, feature_cols: Sequence[str]) -> tuple[pd.DataFrame, np.ndarray]:
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")
    X = df[feature_cols]  # keep as DataFrame to preserve feature names
    target_col = f"y_{_DIRECTION}"
    y = df[target_col].to_numpy(dtype=np.int8)
    return X, y


# ── main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    if not INPUT_PATH.exists():
        print(f"[ERROR] Input not found: {INPUT_PATH}")
        print("  Run: python -m trading_system_v4.scripts.add_labels first")
        sys.exit(1)

    print(f"Loading {INPUT_PATH} …")
    df = pd.read_parquet(INPUT_PATH)
    print(f"  {len(df):,} rows × {df.shape[1]} cols — symbols: {sorted(df['symbol'].unique())}")

    # Optional symbol filter
    if _SYMBOL_FILTER is not None:
        available = sorted(df["symbol"].unique())
        if _SYMBOL_FILTER not in available:
            print(f"[ERROR] Symbol '{_SYMBOL_FILTER}' not found. Available: {available}")
            sys.exit(1)
        df = df[df["symbol"] == _SYMBOL_FILTER].copy().reset_index(drop=True)
        print(f"  Filtered to {_SYMBOL_FILTER}: {len(df):,} rows")

    # Ensure sorted; add year column for fold splitting
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["_year"] = df["timestamp"].dt.year

    # Auto-detect feature columns from the parquet itself
    feature_cols = _detect_feature_cols(df)
    # Remove the helper year column if it somehow snuck in
    feature_cols = [c for c in feature_cols if c != "_year"]
    print(f"  Feature columns detected: {len(feature_cols)}")

    # Drop rows with any NaN in feature cols
    n_before = len(df)
    df = df.dropna(subset=feature_cols).reset_index(drop=True)
    n_after = len(df)
    if n_before != n_after:
        print(f"  Dropped {n_before - n_after:,} rows with NaN features")

    print(f"\n{'━'*65}")
    print("  WALK-FORWARD CROSS-VALIDATION")
    print(f"{'━'*65}")

    for fold in FOLDS:
        name        = fold["name"]
        train_mask  = df["_year"] <= fold["train_cutoff"]
        test_mask   = df["_year"] == fold["test_year"]

        df_train = df[train_mask]
        df_test  = df[test_mask]

        if len(df_train) == 0 or len(df_test) == 0:
            print(f"\n  {name}: insufficient data — train={len(df_train):,} test={len(df_test):,} (skipping)")
            continue

        X_train, y_train = _split_xy(df_train, feature_cols)
        X_test,  y_test  = _split_xy(df_test,  feature_cols)

        pos_rate = y_train.mean()
        spw      = (1 - pos_rate) / pos_rate if pos_rate > 0 else 1.0

        print(f"\n  {name}: train={len(df_train):,} (≤{fold['train_cutoff']})  "
              f"test={len(df_test):,} ({fold['test_year']})  "
              f"pos_rate_train={pos_rate:.2%}  scale_pos_weight={spw:.2f}")

        model = _build_xgb(spw)
        model.fit(X_train, y_train)

        proba_raw = model.predict_proba(X_test)[:, 1]
        _metrics(y_test, proba_raw, THRESHOLD, "raw")

    # ── Final model: train on ALL data ────────────────────────────────────────
    print(f"\n{'━'*65}")
    sym_label = _SYMBOL_FILTER if _SYMBOL_FILTER else "ALL SYMBOLS"
    print(f"  FINAL MODEL  [{sym_label}]")
    print(f"{'━'*65}")

    X_all, y_all = _split_xy(df, feature_cols)
    pos_rate_all = y_all.mean()
    spw_all      = (1 - pos_rate_all) / pos_rate_all if pos_rate_all > 0 else 1.0

    # Split into train (80%) + eval slice (20%) — by time, not random.
    # The eval slice is used solely for EV threshold search; the final model is
    # saved unfitted so it uses all data implicitly via the full-data retrain below.
    eval_start_idx = int(len(df) * (1 - EVAL_FRAC))
    X_fit  = X_all.iloc[:eval_start_idx]
    y_fit  = y_all[:eval_start_idx]
    X_eval = X_all.iloc[eval_start_idx:]
    y_eval = y_all[eval_start_idx:]

    print(f"  Fit set:  {len(y_fit):,} rows")
    print(f"  Eval set: {len(y_eval):,} rows (last {EVAL_FRAC:.0%} by time — threshold search only)")
    print(f"  scale_pos_weight = {spw_all:.2f}")

    # Train on 80% slice, find optimal EV threshold on the held-out 20%
    thresh_model = _build_xgb(spw_all)
    thresh_model.fit(X_fit, y_fit)
    raw_proba_eval = thresh_model.predict_proba(X_eval)[:, 1]

    optimal_thresh = _find_optimal_threshold(y_eval, raw_proba_eval)
    print(f"\n  Eval set metrics (raw probabilities, no calibration):")
    print(f"  Optimal EV threshold found: {optimal_thresh:.2f}")
    _metrics(y_eval, raw_proba_eval, optimal_thresh, "raw")

    # Retrain final model on ALL data using the optimal threshold found above
    print(f"\n  Retraining final model on all {len(y_all):,} rows …")
    final_model = _build_xgb(spw_all)
    final_model.fit(X_all, y_all)

    # ── Feature importances (top 15) ─────────────────────────────────────────
    print(f"\n  Top 15 feature importances (gain):")
    importances = final_model.get_booster().get_score(importance_type="gain")
    sorted_imp  = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:15]
    for feat, imp in sorted_imp:
        print(f"    {feat:<35}  {imp:.1f}")

    # ── Save artefacts ────────────────────────────────────────────────────────
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(final_model, f)
    print(f"\nSaved model        → {MODEL_PATH}")

    # No isotonic calibration — save None as a sentinel so live code that loads
    # the calibrator file can detect it and use raw probabilities directly.
    with open(CALIBRATOR_PATH, "wb") as f:
        pickle.dump(None, f)
    print(f"Saved calibrator   → {CALIBRATOR_PATH}  (None — raw probabilities used)")

    # Persist the optimal threshold alongside the model so the live runner can
    # load it without hardcoding.
    threshold_path = MODEL_DIR / f"{_MODEL_STEM}_threshold.json"
    with open(threshold_path, "w") as f:
        json.dump({"threshold": optimal_thresh}, f)
    print(f"Saved threshold    → {threshold_path}  ({optimal_thresh:.2f})")

    with open(FEATURE_LIST_PATH, "w") as f:
        json.dump(feature_cols, f, indent=2)
    print(f"Saved feature list → {FEATURE_LIST_PATH}  ({len(feature_cols)} features)")

    print(f"\n{'━'*65}")
    print("  DONE")
    print(f"{'━'*65}")


if __name__ == "__main__":
    run()
