"""
train_meta_model_mfe_hit.py — Binary meta-model for MFE hit target.

Target:
  y_hit = 1 when y_meta >= 1.5 ATR, else 0

Purpose:
  In noisy markets, classification of "good enough move" often works better
  than exact MFE regression.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

LOOKAHEAD_BARS = 100
EMBARGO_BARS = 5

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
MODEL_DIR = ROOT / "trading_system_v4" / "model"

INPUT_FILE = DATA_DIR / "meta_labeled_1000t_mfe.parquet"
SELECTED_FILE = MODEL_DIR / "meta_model_mfe_eurusd_selected_features.json"

XGB_PARAMS = dict(
    objective="binary:logistic",
    eval_metric="auc",
    max_depth=4,
    learning_rate=0.05,
    n_estimators=250,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=20,
    gamma=0.1,
    tree_method="hist",
    random_state=42,
    verbosity=0,
)


def _purged_split(tscv, n_rows: int):
    idx = np.arange(n_rows)
    for train_idx, test_idx in tscv.split(idx):
        test_start = int(test_idx[0])
        test_end = int(test_idx[-1])

        purge_before = test_start - EMBARGO_BARS
        purge_after = test_end + LOOKAHEAD_BARS

        purged_train_idx = np.array([
            i for i in train_idx
            if i < purge_before or i > purge_after
        ])

        if len(purged_train_idx) == 0:
            continue

        yield purged_train_idx, test_idx


def _best_threshold(y_true: np.ndarray, y_prob: np.ndarray, min_recall: float = 0.10) -> float:
    p, r, t = precision_recall_curve(y_true, y_prob)
    best = 0.5
    best_f1 = -1.0
    for pp, rr, tt in zip(p[:-1], r[:-1], t):
        if rr < min_recall:
            continue
        f1 = 2 * pp * rr / (pp + rr + 1e-9)
        if f1 > best_f1:
            best_f1 = f1
            best = float(tt)
    return best


def run() -> None:
    if not INPUT_FILE.exists():
        print(f"[ERROR] Missing input: {INPUT_FILE}")
        return

    df = pd.read_parquet(INPUT_FILE).sort_values("timestamp").reset_index(drop=True)

    drop_cols = ["timestamp", "signal", "y_meta"]
    feature_cols = [c for c in df.columns if c not in drop_cols]

    if SELECTED_FILE.exists():
        with open(SELECTED_FILE, encoding="utf-8") as fh:
            payload = json.load(fh)
        selected = [f for f in payload.get("selected_features", []) if f in feature_cols]
        if selected:
            feature_cols = selected

    X = df[feature_cols].astype(np.float32).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = (df["y_meta"] >= 1.5).astype(int)

    print(f"Dataset: {len(df):,} rows  Features: {len(feature_cols)}  HitRate@1.5ATR: {y.mean()*100:.2f}%")

    tscv = TimeSeriesSplit(n_splits=5)

    aucs, precs, recs = [], [], []
    last_probs = None
    last_y = None

    for fold, (train_idx, test_idx) in enumerate(_purged_split(tscv, len(X)), start=1):
        X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
        X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]

        pos = int((y_train == 1).sum())
        neg = int((y_train == 0).sum())
        spw = (neg / max(pos, 1))

        clf = XGBClassifier(**XGB_PARAMS, scale_pos_weight=spw, early_stopping_rounds=20)
        clf.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

        prob = clf.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, prob)

        thr = 0.5
        pred = (prob >= thr).astype(int)
        prec = precision_score(y_test, pred, zero_division=0)
        rec = recall_score(y_test, pred, zero_division=0)

        print(f"Fold {fold}: AUC={auc:.3f}  Precision@0.5={prec:.3f}  Recall={rec:.3f}")

        aucs.append(auc)
        precs.append(prec)
        recs.append(rec)
        last_probs = prob
        last_y = y_test.to_numpy()

    print(f"\nAvg AUC={np.mean(aucs):.3f}  Avg Precision@0.5={np.mean(precs):.3f}  Avg Recall={np.mean(recs):.3f}")

    if last_probs is not None and last_y is not None:
        thr = _best_threshold(last_y, last_probs, min_recall=0.10)
        pred = (last_probs >= thr).astype(int)
        p = precision_score(last_y, pred, zero_division=0)
        r = recall_score(last_y, pred, zero_division=0)
        take = pred.mean() * 100
        print(f"Best threshold on last fold: {thr:.4f}  Precision={p:.3f}  Recall={r:.3f}  TakeRate={take:.1f}%")


if __name__ == "__main__":
    run()
