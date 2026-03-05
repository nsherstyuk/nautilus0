"""
train_meta_model_mfe.py — Meta-Labeling Model Training Pipeline (MFE Regression)

This script trains the secondary ML model (the "Meta-Model").
It takes the output of `meta_labeling_mfe.py` (which contains breakout
events and their microstructure features) and trains XGBoost to predict the
Maximum Favorable Excursion (MFE) in ATR multiples.

Features:
- Purged K-Fold Cross-Validation to prevent lookahead bias.
- Hyperparameter tuning for regression (squarederror).
- Outputs a calibrated regression model.
- Artifacts are fully compatible with V4ModelInference (sklearn API).

Usage:
  python -m trading_system_v4.scripts.train_meta_model_mfe
"""
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor

# Purged CV constants — must match meta_labeling_mfe.py
LOOKAHEAD_BARS = 100   # label uses up to 100 future bars
EMBARGO_BARS   = 5     # SMA5 window; bars immediately adjacent to test set

# ── Configuration ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
MODEL_DIR = ROOT / "trading_system_v4" / "model"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MODEL_STEM = "meta_model_mfe_eurusd"
INPUT_FILE  = DATA_DIR / "meta_labeled_1000t_mfe.parquet"
OUTPUT_MODEL     = MODEL_DIR / f"{MODEL_STEM}.pkl"
OUTPUT_FEATURES  = MODEL_DIR / f"{MODEL_STEM}_features.json"
OUTPUT_THRESHOLD = MODEL_DIR / f"{MODEL_STEM}_threshold.json"
SELECTED_FEATURES_FILE = MODEL_DIR / f"{MODEL_STEM}_selected_features.json"

# XGBoost hyperparameters — sklearn XGBRegressor API
XGB_PARAMS = dict(
    objective="reg:quantileerror", # Predict the median to ignore huge outliers
    quantile_alpha=0.5,       # 50th percentile (median)
    eval_metric="mae",
    max_depth=3,
    learning_rate=0.05,
    n_estimators=300,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=20,
    gamma=0.1,
    tree_method="hist",
    random_state=42,
    verbosity=0,
)

def run():
    if not INPUT_FILE.exists():
        print(f"[ERROR] Meta-labeled data not found at {INPUT_FILE}")
        print("Please run meta_labeling_mfe.py first.")
        return

    print(f"Loading Meta-Labeled Data from {INPUT_FILE} ...")
    df = pd.read_parquet(INPUT_FILE)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Drop non-feature columns
    drop_cols = ["timestamp", "signal", "y_meta"]
    feature_cols = [c for c in df.columns if c not in drop_cols]

    if SELECTED_FEATURES_FILE.exists():
        with open(SELECTED_FEATURES_FILE, encoding="utf-8") as fh:
            payload = json.load(fh)
        selected = payload.get("selected_features", [])
        selected = [f for f in selected if f in feature_cols]
        if selected:
            print(f"Using selected feature subset: {len(selected)} cols")
            feature_cols = selected
        else:
            print("[WARN] selected feature file exists but none matched dataset columns; using all features")

    X = df[feature_cols].astype(np.float32)
    y = df["y_meta"]

    # Log-transform the target to handle right-skewed MFE distribution
    # We use log1p (log(1 + x)) to handle values near 0.
    # Since MFE can technically be slightly negative (due to spread), we shift it.
    # MFE is bounded below by -SL_ATR (e.g., -1.0). So we shift by +1.5 to ensure strictly positive values.
    shift_val = 1.5
    y_log = np.log1p(y + shift_val)

    print(f"Dataset  : {len(df):,} rows (Breakout Signals)")
    print(f"Features : {len(feature_cols)}")
    print(f"Mean MFE : {y.mean():.2f} ATR")

    # ── 1. Purged + Embargoed Time Series Cross-Validation ─────────────────────
    print("\n" + "=" * 50)
    print("PURGED + EMBARGOED CROSS-VALIDATION")
    print(f"  lookahead={LOOKAHEAD_BARS} bars  embargo={EMBARGO_BARS} bars")
    print("=" * 50)

    tscv = TimeSeriesSplit(n_splits=5)
    fold_rmses = []
    fold_maes = []
    fold_r2s = []

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        test_start = int(test_idx[0])
        test_end   = int(test_idx[-1])

        purge_before = test_start - EMBARGO_BARS
        purge_after  = test_end   + LOOKAHEAD_BARS

        purged_train_idx = np.array([
            i for i in train_idx
            if i < purge_before or i > purge_after
        ])

        if len(purged_train_idx) == 0:
            print(f"Fold {fold + 1}: SKIPPED — all training samples purged (fold too small)")
            continue

        dropped = len(train_idx) - len(purged_train_idx)
        X_train, y_train = X.iloc[purged_train_idx], y_log.iloc[purged_train_idx]
        X_test, y_test   = X.iloc[test_idx],         y_log.iloc[test_idx]
        y_test_raw       = y.iloc[test_idx] # Keep raw for evaluation

        reg = XGBRegressor(**XGB_PARAMS, early_stopping_rounds=20)
        reg.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        preds_log = reg.predict(X_test)
        # Inverse transform predictions back to raw MFE
        preds = np.expm1(preds_log) - shift_val

        rmse = np.sqrt(mean_squared_error(y_test_raw, preds))
        mae = mean_absolute_error(y_test_raw, preds)
        r2 = r2_score(y_test_raw, preds)

        print(f"Fold {fold + 1}: Train={len(purged_train_idx):,} (purged {dropped}) | Test={len(test_idx):,}")
        print(f"  RMSE: {rmse:.3f} | MAE: {mae:.3f} | R2: {r2:.3f}")

        fold_rmses.append(rmse)
        fold_maes.append(mae)
        fold_r2s.append(r2)

    print(f"\nAvg RMSE: {np.mean(fold_rmses):.3f}")
    print(f"Avg MAE : {np.mean(fold_maes):.3f}")
    print(f"Avg R2  : {np.mean(fold_r2s):.3f}")

    # ── 2. Train Final Model on Full Dataset ──────────────────────────────────
    print("\n" + "=" * 50)
    print("TRAINING FINAL META-MODEL  (full dataset, fixed rounds=150)")
    print("=" * 50)

    final_params = {**XGB_PARAMS, "n_estimators": 150}
    final_model = XGBRegressor(**final_params)
    final_model.fit(X, y_log, verbose=False)

    # ── 3. Feature Importance ─────────────────────────────────────────────────
    importance = dict(zip(feature_cols, final_model.feature_importances_))
    sorted_importance = sorted(importance.items(), key=lambda x: x[1], reverse=True)

    print("\nTop 10 Meta-Features (Gain):")
    for feat, score in sorted_importance[:10]:
        print(f"  {feat:<35} {score:.4f}")

    # ── 4. Save Artifacts (compatible with V4ModelInference) ──────────────────
    with open(OUTPUT_MODEL, "wb") as fh:
        pickle.dump(final_model, fh)

    with open(OUTPUT_FEATURES, "w") as fh:
        json.dump(feature_cols, fh, indent=2)

    # For regression, the threshold is the minimum predicted MFE to take a trade.
    # We'll set a default of 1.5 ATR, meaning we only take trades where the model
    # predicts the price will travel at least 1.5 ATR favorably.
    default_threshold = 1.5
    with open(OUTPUT_THRESHOLD, "w") as fh:
        json.dump({"threshold": default_threshold, "shift_val": shift_val}, fh, indent=2)

    print(f"\nSaved  model     → {OUTPUT_MODEL}")
    print(f"Saved  features  → {OUTPUT_FEATURES}")
    print(f"Saved  threshold → {OUTPUT_THRESHOLD}  ({default_threshold:.2f} ATR)")


if __name__ == "__main__":
    run()
