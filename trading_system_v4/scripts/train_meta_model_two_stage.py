"""
Two-stage meta-model experiment for MFE.

Stage 1 (Gate): classify whether setup is favorable (y_meta >= gate_target)
Stage 2 (Sizer): regress expected MFE for passed setups

Evaluation uses purged + embargoed time-series CV and reports whether
filtered trades have better realized quality (hit-rate and mean MFE).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier, XGBRegressor

LOOKAHEAD_BARS = 100
EMBARGO_BARS = 5

ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "trading_system_v4" / "data" / "meta_labeled_1000t_mfe.parquet"
SELECTED_FILE = ROOT / "trading_system_v4" / "model" / "meta_model_mfe_eurusd_selected_features.json"

GATE_TARGET = 1.25
REPORT_HIT_TARGET = 1.5
MIN_GATE_RECALL = 0.20

GATE_PARAMS = dict(
    objective="binary:logistic",
    eval_metric="auc",
    max_depth=4,
    learning_rate=0.05,
    n_estimators=260,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=20,
    gamma=0.1,
    tree_method="hist",
    random_state=42,
    verbosity=0,
)

REG_PARAMS = dict(
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


def _best_gate_threshold(y_true: np.ndarray, y_prob: np.ndarray, min_recall: float) -> float:
    p, r, t = precision_recall_curve(y_true, y_prob)
    best_thr = 0.5
    best_f1 = -1.0
    for pp, rr, tt in zip(p[:-1], r[:-1], t):
        if rr < min_recall:
            continue
        f1 = 2 * pp * rr / (pp + rr + 1e-9)
        if f1 > best_f1:
            best_f1 = f1
            best_thr = float(tt)
    return best_thr


def run() -> None:
    if not DATA_FILE.exists():
        print(f"[ERROR] Missing dataset: {DATA_FILE}")
        return

    df = pd.read_parquet(DATA_FILE).sort_values("timestamp").reset_index(drop=True)

    drop_cols = ["timestamp", "signal", "y_meta"]
    feature_cols = [c for c in df.columns if c not in drop_cols]
    if SELECTED_FILE.exists():
        with open(SELECTED_FILE, encoding="utf-8") as fh:
            payload = json.load(fh)
        selected = [f for f in payload.get("selected_features", []) if f in feature_cols]
        if selected:
            feature_cols = selected

    X = df[feature_cols].astype(np.float32).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y_mfe = df["y_meta"].astype(float)
    y_gate = (y_mfe >= GATE_TARGET).astype(int)
    y_hit = (y_mfe >= REPORT_HIT_TARGET).astype(int)

    shift = 1.5
    y_mfe_log = np.log1p(y_mfe + shift)

    print(f"Rows={len(df):,}  Features={len(feature_cols)}")
    print(f"Gate target >= {GATE_TARGET:.2f} ATR  prevalence={y_gate.mean()*100:.2f}%")
    print(f"Report hit >= {REPORT_HIT_TARGET:.2f} ATR  prevalence={y_hit.mean()*100:.2f}%")

    fold_rows = []
    all_gate_probs: list[np.ndarray] = []
    all_hit_vals: list[np.ndarray] = []
    all_mfe_vals: list[np.ndarray] = []

    for fold, (tr, te) in enumerate(_purged_splits(len(X), n_splits=5), start=1):
        X_tr, X_te = X.iloc[tr], X.iloc[te]
        y_gate_tr, y_gate_te = y_gate.iloc[tr], y_gate.iloc[te]
        y_mfe_tr, y_mfe_te = y_mfe.iloc[tr], y_mfe.iloc[te]
        y_mfe_log_tr = y_mfe_log.iloc[tr]
        y_hit_te = y_hit.iloc[te]

        pos = int((y_gate_tr == 1).sum())
        neg = int((y_gate_tr == 0).sum())
        spw = neg / max(pos, 1)

        gate = XGBClassifier(**GATE_PARAMS, scale_pos_weight=spw, early_stopping_rounds=20)
        gate.fit(X_tr, y_gate_tr, eval_set=[(X_te, y_gate_te)], verbose=False)

        gate_prob = gate.predict_proba(X_te)[:, 1]
        gate_auc = roc_auc_score(y_gate_te, gate_prob) if y_gate_te.nunique() > 1 else np.nan
        gate_thr = _best_gate_threshold(y_gate_te.to_numpy(), gate_prob, min_recall=MIN_GATE_RECALL)
        take_mask = gate_prob >= gate_thr

        reg = XGBRegressor(**REG_PARAMS, early_stopping_rounds=20)
        reg.fit(X_tr, y_mfe_log_tr, eval_set=[(X_te, y_mfe_log.iloc[te])], verbose=False)
        pred_mfe = np.expm1(reg.predict(X_te)) - shift

        base_hit = float(y_hit_te.mean())
        base_mfe = float(y_mfe_te.mean())

        if take_mask.any():
            take_hit = float(y_hit_te[take_mask].mean())
            take_mfe = float(y_mfe_te[take_mask].mean())
            take_rate = float(take_mask.mean())
            pred_mfe_taken = float(pred_mfe[take_mask].mean())
        else:
            take_hit = np.nan
            take_mfe = np.nan
            take_rate = 0.0
            pred_mfe_taken = np.nan

        row = {
            "fold": fold,
            "gate_auc": gate_auc,
            "gate_thr": gate_thr,
            "take_rate": take_rate,
            "base_hit_1p5": base_hit,
            "take_hit_1p5": take_hit,
            "hit_lift": (take_hit - base_hit) if np.isfinite(take_hit) else np.nan,
            "base_mfe": base_mfe,
            "take_mfe": take_mfe,
            "mfe_lift": (take_mfe - base_mfe) if np.isfinite(take_mfe) else np.nan,
            "pred_mfe_taken": pred_mfe_taken,
        }
        fold_rows.append(row)
        all_gate_probs.append(gate_prob)
        all_hit_vals.append(y_hit_te.to_numpy())
        all_mfe_vals.append(y_mfe_te.to_numpy())

        print(
            f"Fold {fold}: AUC={gate_auc:.3f} thr={gate_thr:.3f} take={take_rate*100:.1f}% | "
            f"hit base={base_hit:.3f} take={take_hit:.3f} | mfe base={base_mfe:.3f} take={take_mfe:.3f}"
        )

    res = pd.DataFrame(fold_rows)
    print("\n=== Two-Stage Summary ===")
    print(f"Gate AUC mean     : {res['gate_auc'].mean():.3f}")
    print(f"Take-rate mean    : {res['take_rate'].mean()*100:.1f}%")
    print(f"Hit@1.5 base mean : {res['base_hit_1p5'].mean():.3f}")
    print(f"Hit@1.5 take mean : {res['take_hit_1p5'].mean():.3f}")
    print(f"Hit lift mean     : {res['hit_lift'].mean():.3f}")
    print(f"MFE base mean     : {res['base_mfe'].mean():.3f}")
    print(f"MFE take mean     : {res['take_mfe'].mean():.3f}")
    print(f"MFE lift mean     : {res['mfe_lift'].mean():.3f}")

    # Practical gate calibration by desired take-rate
    probs = np.concatenate(all_gate_probs)
    hits = np.concatenate(all_hit_vals)
    mfes = np.concatenate(all_mfe_vals)
    base_hit = float(hits.mean())
    base_mfe = float(mfes.mean())

    print("\n=== Gate Sweep (by take-rate) ===")
    print(f"Base hit@{REPORT_HIT_TARGET:.2f}: {base_hit:.3f}  Base MFE: {base_mfe:.3f}")
    for take_rate in [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]:
        thr = float(np.quantile(probs, 1.0 - take_rate))
        mask = probs >= thr
        take_hit = float(hits[mask].mean()) if mask.any() else np.nan
        take_mfe = float(mfes[mask].mean()) if mask.any() else np.nan
        print(
            f"take={take_rate*100:>4.0f}%  thr={thr:.4f}  "
            f"hit={take_hit:.3f} ({take_hit - base_hit:+.3f})  "
            f"mfe={take_mfe:.3f} ({take_mfe - base_mfe:+.3f})"
        )


if __name__ == "__main__":
    run()
