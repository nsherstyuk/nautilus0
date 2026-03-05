"""
retrain_v3_xgb_clean.py — Retrain v3 XGB model with leak-free features.

Uses tick-bar 15m resampled data (same source as meta-labeling pipeline).
Applies the fixed feature_engineering_v3.py (label='right', closed='right')
and the same SL/TP-aware labeling from retrain_model.py.

Matches the original training logic:
  - XGBClassifier, max_depth=4, n_estimators=300, lr=0.05
  - SL/TP-aware labels: TP = 1.4 ATR, SL = 1.8 ATR, forward_bars = 60
  - Label = 1 (LONG) if TP hit before SL; Label = 0 (SHORT) if SL hit first.

Training window: configurable (default 2024-01-01 to 2025-12-31 = 24 months).
Saves model to models/ml_model_mtf_v3_xgb.pkl (overwrites the leaked version).

Usage:
  python -m trading_system_v4.scripts.retrain_v3_xgb_clean
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import dump
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from strategies.feature_engineering_v3 import (  # noqa: E402
    FEATURE_COLUMNS_V3,
    compute_v3_features,
)

# ── Configuration ─────────────────────────────────────────────────────────────
TICK_BARS = ROOT / "trading_system_v4" / "data" / "eurusd_1000t_bars.parquet"
MODEL_OUT = ROOT / "models" / "ml_model_mtf_v3_xgb.pkl"
BACKUP_OUT = ROOT / "models" / "ml_model_mtf_v3_xgb_leaked_backup.pkl"

TRAIN_START = pd.Timestamp("2024-01-01", tz="UTC")
TRAIN_END   = pd.Timestamp("2026-01-01", tz="UTC")  # exclusive

# Labeling params (match retrain_model.py exactly)
SL_MULT    = 1.8
TP1_MULT   = 1.4
FWD_BARS   = 60
ATR_PERIOD = 14


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ),
    )
    return tr.rolling(period).mean()


def create_labels(df: pd.DataFrame) -> pd.DataFrame:
    """SL/TP-aware directional labeling — mirrors retrain_model.py."""
    df = df.copy()
    atr = _atr(df, ATR_PERIOD)
    df["_atr"] = atr
    df = df.dropna(subset=["_atr"])

    c = df["close"].values
    h = df["high"].values
    lo = df["low"].values
    a = df["_atr"].values
    n = len(c)

    tp_level = c + a * TP1_MULT
    sl_level = c - a * SL_MULT

    labels = np.full(n, -1, dtype=np.int8)
    for fwd in range(1, FWD_BARS + 1):
        unresolved = labels == -1
        if not unresolved.any():
            break
        idx = np.arange(n)
        valid = (idx + fwd) < n
        future_h = np.where(valid, h[np.minimum(idx + fwd, n - 1)], np.nan)
        future_l = np.where(valid, lo[np.minimum(idx + fwd, n - 1)], np.nan)

        tp_hit = unresolved & valid & (future_h >= tp_level)
        sl_hit = unresolved & valid & (future_l <= sl_level)

        labels[tp_hit & sl_hit] = -2    # ambiguous
        labels[tp_hit & ~sl_hit] = 1    # LONG
        labels[sl_hit & ~tp_hit] = 0    # SHORT

    df["label"] = labels
    n_unresolved = int((labels == -1).sum())
    n_ambiguous = int((labels == -2).sum())
    df = df[(df["label"] == 0) | (df["label"] == 1)].copy()
    df["label"] = df["label"].astype(int)

    print(f"SL/TP labels: {len(df):,} usable  "
          f"({n_unresolved} unresolved, {n_ambiguous} ambiguous dropped)")
    vc = df["label"].value_counts()
    print(f"  LONG={vc.get(1,0):,} ({vc.get(1,0)/len(df)*100:.1f}%)  "
          f"SHORT={vc.get(0,0):,} ({vc.get(0,0)/len(df)*100:.1f}%)")
    return df


def run() -> None:
    print("=" * 70)
    print("RETRAIN V3 XGB — LEAK-FREE FEATURES")
    print(f"Training window: {TRAIN_START.date()} → {TRAIN_END.date()}")
    print("=" * 70)

    # ── 1. Load tick bars → 15m ──────────────────────────────────────────────
    print(f"\nLoading tick bars from {TICK_BARS} ...")
    tick = pd.read_parquet(TICK_BARS)
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

    # ── 2. Compute V3 features (leak-free) ──────────────────────────────────
    print("Computing V3 features (fixed HTF resample) ...")
    feats = compute_v3_features(df15)

    # Merge features with OHLCV (needed for labeling)
    combined = df15[["open", "high", "low", "close", "volume"]].copy()
    for col in feats.columns:
        combined[col] = feats[col]
    combined = combined.dropna()

    # ── 3. Filter to training window ─────────────────────────────────────────
    train_df = combined[(combined.index >= TRAIN_START) & (combined.index < TRAIN_END)].copy()
    print(f"Training window: {len(train_df):,} bars")

    # ── 4. Create labels ────────────────────────────────────────────────────
    train_df = create_labels(train_df)

    # ── 5. Prepare X, y ────────────────────────────────────────────────────
    X = train_df[FEATURE_COLUMNS_V3].astype(np.float32)
    y = train_df["label"]

    # Clean infinities
    X = X.replace([np.inf, -np.inf], np.nan)
    valid = X.notna().all(axis=1)
    X, y = X[valid], y[valid]
    print(f"\nTraining samples: {len(X):,}  features: {len(FEATURE_COLUMNS_V3)}")

    # ── 6. Walk-forward CV ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("WALK-FORWARD CV  (3 folds)")
    print("=" * 70)
    tscv = TimeSeriesSplit(n_splits=3)
    cv_model = XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.1, reg_lambda=1.0,
        min_child_weight=20, gamma=0.1,
        random_state=42, n_jobs=-1, eval_metric="logloss",
    )
    cv_scores = cross_val_score(cv_model, X, y, cv=tscv, scoring="accuracy")
    print(f"CV accuracies: {[f'{s:.3f}' for s in cv_scores]}")
    print(f"Mean: {cv_scores.mean():.3f}  Std: {cv_scores.std():.3f}")

    # ── 7. Train final model ────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("TRAINING FINAL MODEL  (80/20 split)")
    print("=" * 70)
    split_idx = int(len(X) * 0.8)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    model = XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        min_child_weight=20,
        gamma=0.1,
        random_state=42,
        n_jobs=-1,
        eval_metric="logloss",
        early_stopping_rounds=30,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    train_acc = model.score(X_train, y_train)
    val_acc = model.score(X_val, y_val)
    print(f"Train accuracy: {train_acc:.4f}")
    print(f"Val accuracy:   {val_acc:.4f}")

    y_pred = model.predict(X_val)
    print("\nClassification Report (Val):")
    print(classification_report(y_val, y_pred, target_names=["SHORT", "LONG"]))

    # Threshold sweep
    y_proba = model.predict_proba(X_val)[:, 1]
    print("Confidence threshold sweep (LONG, vs val set):")
    for thr in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75]:
        pred = (y_proba >= thr).astype(int)
        if pred.sum() > 0:
            prec = (y_val[pred == 1] == 1).sum() / pred.sum()
            cov = pred.sum() / len(y_val)
            print(f"  thr={thr:.2f}: precision={prec:.3f}  coverage={cov:.3f}  "
                  f"n={pred.sum()}")

    # Feature importance
    fi = pd.DataFrame({
        "feature": FEATURE_COLUMNS_V3,
        "importance": model.feature_importances_,
    }).sort_values("importance", ascending=False)
    print("\nTop 15 features:")
    for _, row in fi.head(15).iterrows():
        print(f"  {row['feature']:<35} {row['importance']:.4f}")

    # ── 8. Save ─────────────────────────────────────────────────────────────
    import shutil
    if MODEL_OUT.exists():
        shutil.copy2(MODEL_OUT, BACKUP_OUT)
        print(f"\nBacked up old model → {BACKUP_OUT}")

    dump(model, MODEL_OUT)
    print(f"Saved new model → {MODEL_OUT}")

    # Save feature list
    feat_list_path = ROOT / "models" / "feature_list_v3_clean.txt"
    feat_list_path.write_text("\n".join(FEATURE_COLUMNS_V3), encoding="utf-8")
    print(f"Feature list → {feat_list_path}")
    print("\nDone.")


if __name__ == "__main__":
    run()
