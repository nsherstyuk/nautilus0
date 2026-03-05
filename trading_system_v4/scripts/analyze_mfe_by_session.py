"""
Analyze MFE predictability by session regime.
"""
from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "trading_system_v4" / "data" / "meta_labeled_1000t_mfe.parquet"
SELECTED = ROOT / "trading_system_v4" / "model" / "meta_model_mfe_eurusd_selected_features.json"

FEATURES = ["atr_norm", "atr_sma50", "bar_range_norm", "max_spread", "total_volume", "hour_sin"]


def _session(hour: int) -> str:
    if 7 <= hour < 13:
        return "london_open"
    if 13 <= hour < 21:
        return "ny"
    return "asian"


def _cv_auc(df: pd.DataFrame) -> float:
    if len(df) < 1000:
        return float("nan")

    X = df[FEATURES].astype(np.float32).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = (df["y_meta"] >= 1.5).astype(int)

    if y.nunique() < 2:
        return float("nan")

    tscv = TimeSeriesSplit(n_splits=4)
    aucs = []
    for tr, te in tscv.split(X):
        Xtr, Xte = X.iloc[tr], X.iloc[te]
        ytr, yte = y.iloc[tr], y.iloc[te]
        if ytr.nunique() < 2 or yte.nunique() < 2:
            continue
        spw = (int((ytr == 0).sum()) / max(int((ytr == 1).sum()), 1))
        clf = XGBClassifier(
            objective="binary:logistic",
            eval_metric="auc",
            max_depth=3,
            learning_rate=0.05,
            n_estimators=140,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=20,
            gamma=0.1,
            tree_method="hist",
            random_state=42,
            verbosity=0,
            scale_pos_weight=spw,
        )
        clf.fit(Xtr, ytr, verbose=False)
        p = clf.predict_proba(Xte)[:, 1]
        aucs.append(roc_auc_score(yte, p))

    return float(np.mean(aucs)) if aucs else float("nan")


def run() -> None:
    df = pd.read_parquet(DATA).sort_values("timestamp").reset_index(drop=True)
    if SELECTED.exists():
        with open(SELECTED, encoding="utf-8") as fh:
            payload = json.load(fh)
        selected = payload.get("selected_features", [])
        selected = [f for f in selected if f in df.columns]
        if selected:
            print(f"Using selected features: {len(selected)}")
            global FEATURES
            FEATURES = selected

    ts = pd.to_datetime(df["timestamp"], utc=True)
    df["session"] = ts.dt.hour.map(_session)

    print(f"Rows={len(df):,}  HitRate@1.5={(df['y_meta'] >= 1.5).mean()*100:.2f}%")

    for sess in ["asian", "london_open", "ny"]:
        d = df[df["session"] == sess].copy()
        hit = (d["y_meta"] >= 1.5).mean() * 100 if len(d) else np.nan
        auc = _cv_auc(d)
        print(f"{sess:12} rows={len(d):6,}  hit@1.5={hit:6.2f}%  cv_auc={auc:.3f}")


if __name__ == "__main__":
    run()
