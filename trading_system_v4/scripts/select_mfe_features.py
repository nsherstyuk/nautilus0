"""
select_mfe_features.py — Time-series feature selection for MFE regression.

Standard process used:
1) Relevance filter (mutual information + fold IC)
2) Stability filter across time folds
3) Redundancy pruning (high pairwise correlation)
4) Wrapper subset search (purged CV, MAE objective)

Usage:
  python -m trading_system_v4.scripts.select_mfe_features
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_regression
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor

LOOKAHEAD_BARS = 100
EMBARGO_BARS = 5

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
MODEL_DIR = ROOT / "trading_system_v4" / "model"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

INPUT_FILE = DATA_DIR / "meta_labeled_1000t_mfe.parquet"
SELECTED_FILE = MODEL_DIR / "meta_model_mfe_eurusd_selected_features.json"
REPORT_FILE = DATA_DIR / "mfe_feature_selection_report.csv"

XGB_PARAMS = dict(
    objective="reg:pseudohubererror",
    eval_metric="mae",
    max_depth=3,
    learning_rate=0.05,
    n_estimators=180,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=20,
    gamma=0.1,
    tree_method="hist",
    random_state=42,
    verbosity=0,
)


def _purged_splits(n_rows: int, n_splits: int = 5):
    tscv = TimeSeriesSplit(n_splits=n_splits)
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


def _safe_spearman(a: pd.Series, b: pd.Series) -> float:
    data = pd.DataFrame({"a": a, "b": b}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 30:
        return 0.0
    if data["a"].std() == 0.0 or data["b"].std() == 0.0:
        return 0.0
    return float(data["a"].corr(data["b"], method="spearman"))


def _cv_mae(X: pd.DataFrame, y_raw: pd.Series, y_log: pd.Series) -> float:
    maes: list[float] = []
    shift_val = 1.5

    for train_idx, test_idx in _purged_splits(len(X), n_splits=5):
        X_train, y_train = X.iloc[train_idx], y_log.iloc[train_idx]
        X_test, y_test_raw = X.iloc[test_idx], y_raw.iloc[test_idx]

        model = XGBRegressor(**XGB_PARAMS, early_stopping_rounds=20)
        model.fit(
            X_train,
            y_train,
            eval_set=[(X_test, y_log.iloc[test_idx])],
            verbose=False,
        )

        pred_log = model.predict(X_test)
        pred_raw = np.expm1(pred_log) - shift_val
        maes.append(float(mean_absolute_error(y_test_raw, pred_raw)))

    if not maes:
        return 1e9
    return float(np.mean(maes))


def run() -> None:
    if not INPUT_FILE.exists():
        print(f"[ERROR] Missing input: {INPUT_FILE}")
        return

    print(f"Loading {INPUT_FILE} ...")
    df = pd.read_parquet(INPUT_FILE).sort_values("timestamp").reset_index(drop=True)

    drop_cols = ["timestamp", "signal", "y_meta"]
    feature_cols = [c for c in df.columns if c not in drop_cols]

    X = df[feature_cols].astype(np.float32).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y_raw = df["y_meta"].astype(float)

    shift_val = 1.5
    y_log = np.log1p(y_raw + shift_val)

    # 1) Relevance
    print("Scoring relevance (MI + fold IC) ...")
    mi = mutual_info_regression(X, y_raw, random_state=42)

    fold_ic_mean = []
    fold_ic_std = []
    for col in feature_cols:
        vals = []
        for _, test_idx in _purged_splits(len(X), n_splits=5):
            vals.append(_safe_spearman(X[col].iloc[test_idx], y_raw.iloc[test_idx]))
        fold_ic_mean.append(float(np.mean(vals)) if vals else 0.0)
        fold_ic_std.append(float(np.std(vals)) if vals else 1.0)

    score_df = pd.DataFrame(
        {
            "feature": feature_cols,
            "mi": mi,
            "fold_ic_mean": fold_ic_mean,
            "fold_ic_std": fold_ic_std,
        }
    )
    score_df["stability"] = np.maximum(0.0, 1.0 - (score_df["fold_ic_std"] / (score_df["fold_ic_mean"].abs() + 1e-6)))
    score_df["relevance"] = (score_df["mi"].rank(pct=True) * 0.5) + (score_df["fold_ic_mean"].abs().rank(pct=True) * 0.5)

    # Keep top relevance + minimum stability
    phase1 = score_df.sort_values("relevance", ascending=False).head(min(24, len(score_df))).copy()
    phase1 = phase1[phase1["stability"] >= 0.10].copy()
    if len(phase1) < 8:
        phase1 = score_df.sort_values("relevance", ascending=False).head(min(12, len(score_df))).copy()

    # 2) Redundancy pruning
    print("Pruning redundancy (|corr| > 0.92) ...")
    candidates = phase1["feature"].tolist()
    corr = X[candidates].corr().abs()

    kept: list[str] = []
    for feat in phase1.sort_values("relevance", ascending=False)["feature"]:
        if not kept:
            kept.append(feat)
            continue
        too_close = any(corr.loc[feat, k] > 0.92 for k in kept)
        if not too_close:
            kept.append(feat)

    # 3) Wrapper subset search
    print("Searching subset size by purged-CV MAE ...")
    ranked = phase1.set_index("feature").loc[kept].sort_values("relevance", ascending=False).index.tolist()

    candidate_sizes = sorted(set([6, 8, 10, 12, 14, min(16, len(ranked)), len(ranked)]))
    candidate_sizes = [k for k in candidate_sizes if 4 <= k <= len(ranked)]

    results = []
    for k in candidate_sizes:
        subset = ranked[:k]
        mae = _cv_mae(X[subset], y_raw, y_log)
        results.append({"k": k, "mae": mae, "features": subset})
        print(f"  k={k:>2}  MAE={mae:.4f}")

    best = min(results, key=lambda x: x["mae"])
    selected = best["features"]

    with open(SELECTED_FILE, "w", encoding="utf-8") as fh:
        json.dump({"selected_features": selected, "cv_mae": best["mae"]}, fh, indent=2)

    score_df["selected"] = score_df["feature"].isin(selected)
    score_df.sort_values(["selected", "relevance"], ascending=[False, False]).to_csv(REPORT_FILE, index=False)

    print("\nSelection complete")
    print(f"Selected {len(selected)} features (best MAE={best['mae']:.4f})")
    print(f"Saved selected list: {SELECTED_FILE}")
    print(f"Saved report      : {REPORT_FILE}")
    print("Selected:")
    for f in selected:
        print(f"  - {f}")


if __name__ == "__main__":
    run()
