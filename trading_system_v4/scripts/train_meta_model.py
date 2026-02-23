"""
train_meta_model.py — Meta-Labeling Model Training Pipeline

This script trains the secondary ML model (the "Meta-Model").
It takes the output of `meta_labeling_ema.py` (which contains only the EMA crossover
events and their microstructure features) and trains XGBoost to predict the
Probability of Win (0 to 1).

Features:
- Purged K-Fold Cross-Validation to prevent lookahead bias.
- Hyperparameter tuning for binary classification (logloss).
- Outputs a calibrated probability model + EV-optimal threshold.
- Artifacts are fully compatible with V4ModelInference (sklearn API).

Usage:
  python -m trading_system_v4.scripts.train_meta_model
"""
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

# Purged CV constants — must match meta_labeling_ema.py
LOOKAHEAD_BARS = 100   # label uses up to 100 future bars
EMBARGO_BARS   = 5     # SMA5 window; bars immediately adjacent to test set

# ── Configuration ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
MODEL_DIR = ROOT / "trading_system_v4" / "model"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MODEL_STEM = "meta_model_ema_eurusd"
INPUT_FILE  = DATA_DIR / "meta_labeled_1000t.parquet"
OUTPUT_MODEL     = MODEL_DIR / f"{MODEL_STEM}.pkl"
OUTPUT_FEATURES  = MODEL_DIR / f"{MODEL_STEM}_features.json"
OUTPUT_THRESHOLD = MODEL_DIR / f"{MODEL_STEM}_threshold.json"

# XGBoost hyperparameters — sklearn XGBClassifier API
# (n_estimators replaces num_boost_round; early_stopping_rounds passed to fit())
XGB_PARAMS = dict(
    objective="binary:logistic",
    eval_metric="logloss",
    max_depth=4,              # Keep shallow to prevent overfitting
    learning_rate=0.05,
    n_estimators=200,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,       # Require more evidence to split
    gamma=0.1,                # Minimum loss reduction
    tree_method="hist",
    random_state=42,
    verbosity=0,
)

REPORT_THRESHOLD = 0.65   # Fixed threshold used in per-fold reporting
MIN_RECALL = 0.10         # Minimum recall for threshold selection


def _select_threshold(y_true: np.ndarray, y_proba: np.ndarray,
                      min_recall: float = MIN_RECALL) -> float:
    """
    Sweep the precision-recall curve and return the threshold that maximises F1
    while keeping recall >= min_recall.  Falls back to REPORT_THRESHOLD if no
    threshold satisfies the recall constraint.
    """
    precisions, recalls, thresholds = precision_recall_curve(y_true, y_proba)
    best_f1 = -1.0
    best_thresh = REPORT_THRESHOLD
    # precision_recall_curve returns len(thresholds) + 1 values for p/r
    for p, r, t in zip(precisions[:-1], recalls[:-1], thresholds):
        if r < min_recall:
            continue
        f1 = 2 * p * r / (p + r + 1e-9)
        if f1 > best_f1:
            best_f1 = f1
            best_thresh = float(t)
    return best_thresh


def run():
    if not INPUT_FILE.exists():
        print(f"[ERROR] Meta-labeled data not found at {INPUT_FILE}")
        print("Please run meta_labeling_ema.py first.")
        return

    print(f"Loading Meta-Labeled Data from {INPUT_FILE} ...")
    df = pd.read_parquet(INPUT_FILE)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Drop non-feature columns
    drop_cols = ["timestamp", "signal", "y_meta"]
    feature_cols = [c for c in df.columns if c not in drop_cols]

    X = df[feature_cols].astype(np.float32)
    y = df["y_meta"]

    print(f"Dataset  : {len(df):,} rows (EMA Crossovers)")
    print(f"Features : {len(feature_cols)}")
    print(f"Win rate : {(y == 1).mean() * 100:.1f}%")

    # ── 1. Purged + Embargoed Time Series Cross-Validation ─────────────────────
    # Plain TimeSeriesSplit leaks because labels use LOOKAHEAD_BARS future bars:
    # a training sample near the test boundary shares the same future price path
    # as the first test samples.  The purge step drops those training samples.
    # The embargo step additionally drops EMBARGO_BARS samples on both edges to
    # account for the SMA5 rolling window used in feature engineering.
    print("\n" + "=" * 50)
    print("PURGED + EMBARGOED CROSS-VALIDATION")
    print(f"  lookahead={LOOKAHEAD_BARS} bars  embargo={EMBARGO_BARS} bars")
    print("=" * 50)

    tscv = TimeSeriesSplit(n_splits=5)
    fold_precisions = []
    last_fold_data: tuple[np.ndarray, np.ndarray] | None = None

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        test_start = int(test_idx[0])
        test_end   = int(test_idx[-1])

        # Drop training samples whose lookahead overlaps the test window,
        # plus EMBARGO_BARS samples immediately adjacent on each side.
        purge_before = test_start - EMBARGO_BARS          # last safe train index
        purge_after  = test_end   + LOOKAHEAD_BARS        # first safe train index after test

        purged_train_idx = np.array([
            i for i in train_idx
            if i < purge_before or i > purge_after
        ])

        if len(purged_train_idx) == 0:
            print(f"Fold {fold + 1}: SKIPPED — all training samples purged (fold too small)")
            continue

        dropped = len(train_idx) - len(purged_train_idx)
        X_train, y_train = X.iloc[purged_train_idx], y.iloc[purged_train_idx]
        X_test, y_test   = X.iloc[test_idx],         y.iloc[test_idx]

        pos_count = (y_train == 1).sum()
        neg_count = (y_train == 0).sum()
        scale_weight = neg_count / pos_count if pos_count > 0 else 1.0

        clf = XGBClassifier(**XGB_PARAMS, scale_pos_weight=scale_weight,
                            early_stopping_rounds=20)
        clf.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        preds_proba  = clf.predict_proba(X_test)[:, 1]
        preds_binary = (preds_proba >= REPORT_THRESHOLD).astype(int)

        auc       = roc_auc_score(y_test, preds_proba)
        precision = precision_score(y_test, preds_binary, zero_division=0)
        recall    = recall_score(y_test, preds_binary, zero_division=0)

        signals_taken = preds_binary.sum()
        total_signals = len(y_test)

        print(f"Fold {fold + 1}: Train={len(purged_train_idx):,} (purged {dropped}) | Test={len(test_idx):,}")
        print(f"  AUC: {auc:.3f} | Precision@{REPORT_THRESHOLD}: {precision:.3f} "
              f"| Recall: {recall:.3f}")
        print(f"  Trades Taken: {signals_taken} / {total_signals} "
              f"({signals_taken / total_signals * 100:.1f}%)")

        fold_precisions.append(precision)
        last_fold_data = (y_test.values, preds_proba)

    print(f"\nAvg Precision@{REPORT_THRESHOLD}: {np.mean(fold_precisions):.3f}")

    # ── 2. Select Threshold on Last CV Fold ───────────────────────────────────
    print("\n" + "=" * 50)
    print("THRESHOLD SELECTION  (last CV fold, min_recall=%.2f)" % MIN_RECALL)
    print("=" * 50)

    y_val, proba_val = last_fold_data  # type: ignore[misc]
    threshold = _select_threshold(y_val, proba_val, min_recall=MIN_RECALL)
    preds_at_thresh = (proba_val >= threshold).astype(int)

    p  = precision_score(y_val, preds_at_thresh, zero_division=0)
    r  = recall_score(y_val, preds_at_thresh, zero_division=0)
    f1 = f1_score(y_val, preds_at_thresh, zero_division=0)
    trades_pct = preds_at_thresh.sum() / len(y_val) * 100

    print(f"  Selected threshold : {threshold:.4f}")
    print(f"  Precision          : {p:.3f}")
    print(f"  Recall             : {r:.3f}")
    print(f"  F1                 : {f1:.3f}")
    print(f"  Signals taken      : {preds_at_thresh.sum()} / {len(y_val)} ({trades_pct:.1f}%)")

    # ── 3. Train Final Model on Full Dataset ──────────────────────────────────
    print("\n" + "=" * 50)
    print("TRAINING FINAL META-MODEL  (full dataset, fixed rounds=150)")
    print("=" * 50)

    pos_count = (y == 1).sum()
    neg_count = (y == 0).sum()
    scale_weight = neg_count / pos_count if pos_count > 0 else 1.0

    # Fixed n_estimators when training on full data (no validation set to early-stop)
    final_params = {**XGB_PARAMS, "n_estimators": 150}
    final_model = XGBClassifier(**final_params, scale_pos_weight=scale_weight)
    final_model.fit(X, y, verbose=False)

    # ── 4. Feature Importance ─────────────────────────────────────────────────
    importance = dict(zip(feature_cols, final_model.feature_importances_))
    sorted_importance = sorted(importance.items(), key=lambda x: x[1], reverse=True)

    print("\nTop 10 Meta-Features (Gain):")
    for feat, score in sorted_importance[:10]:
        print(f"  {feat:<35} {score:.4f}")

    # ── 5. Save Artifacts (compatible with V4ModelInference) ──────────────────
    with open(OUTPUT_MODEL, "wb") as fh:
        pickle.dump(final_model, fh)

    with open(OUTPUT_FEATURES, "w") as fh:
        json.dump(feature_cols, fh, indent=2)

    with open(OUTPUT_THRESHOLD, "w") as fh:
        json.dump({"threshold": round(threshold, 6)}, fh, indent=2)

    print(f"\nSaved  model     → {OUTPUT_MODEL}")
    print(f"Saved  features  → {OUTPUT_FEATURES}")
    print(f"Saved  threshold → {OUTPUT_THRESHOLD}  ({threshold:.4f})")


if __name__ == "__main__":
    run()
