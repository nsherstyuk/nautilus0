"""
train_meta_model_v3_signal.py — Meta-Model Training on v3 XGB Signals

Trains a secondary XGBoost **classifier** that predicts, given a v3 XGB
base signal (confidence ≥ threshold), whether the trade will hit TP before SL.

The meta-model adds a second layer of filtering on top of the already-edged
base signal (+16 pp OOS), aiming to push WR further by selecting only the
highest-quality signals.

Pipeline:
  1. Load meta_labeled_v3_signal_thr65.parquet
  2. Purged time-series CV  (5 folds, embargo=5 bars)
  3. Train XGBClassifier  → predict P(y_tp = 1)
  4. Evaluate lift at meta-score thresholds 0.55, 0.60, 0.65, 0.70
  5. Train final model on full data
  6. Save model + feature list + lift analysis

Outputs:
  trading_system_v4/model/meta_model_v3_clf.pkl
  trading_system_v4/model/meta_model_v3_clf_features.json
  trading_system_v4/model/meta_model_v3_clf_lift.txt

Usage:
  python -m trading_system_v4.scripts.train_meta_model_v3_signal
  python -m trading_system_v4.scripts.train_meta_model_v3_signal --thr 0.70
"""
import argparse
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parents[2]
DATA_DIR  = ROOT / "trading_system_v4" / "data"
MODEL_DIR = ROOT / "trading_system_v4" / "model"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Defaults (can be overridden via CLI)
DEFAULT_SIGNAL_THR  = 0.65  # confidence threshold used in meta_labeling step

LOOKAHEAD_BARS = 100   # matches simulation lookahead
EMBARGO_BARS   = 5     # purge these many rows around fold boundary

SL_ATR = 1.4
TP_ATR = 1.5
BREAK_EVEN = SL_ATR / (SL_ATR + TP_ATR)   # ~48.3 %

# ── XGBClassifier hyperparameters ────────────────────────────────────────────
XGB_PARAMS = dict(
    objective="binary:logistic",
    eval_metric="logloss",
    max_depth=4,
    learning_rate=0.05,
    n_estimators=400,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=30,      # prevents fitting tiny groups
    gamma=0.2,
    reg_lambda=2.0,
    tree_method="hist",
    random_state=42,
    verbosity=0,
    early_stopping_rounds=30,
)


# ── Feature definitions ───────────────────────────────────────────────────────
META_FEATURES = [
    "model_confidence",
    "direction",
    "conf_x_direction",
]


def _lift_table(y_true: np.ndarray, y_score: np.ndarray, label: str = "") -> str:
    """Print WR / edge at various meta-score thresholds."""
    lines = [f"\n  {'Thr':>5}  {'n':>7}  {'take%':>6}  {'WR%':>6}  {'edge pp':>8}"]
    total = len(y_true)
    for thr in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75]:
        mask = y_score >= thr
        n = mask.sum()
        if n < 10:
            continue
        wr = y_true[mask].mean()
        take_pct = n / total * 100
        edge_pp  = (wr - BREAK_EVEN) * 100
        lines.append(
            f"  {thr:.2f}  {n:>7,}  {take_pct:>5.1f}%  {wr*100:>5.1f}%  {edge_pp:>+7.1f}"
        )
    return "\n".join(lines)


def run(signal_thr: float = DEFAULT_SIGNAL_THR) -> None:
    input_file = DATA_DIR / f"meta_labeled_v3_signal_thr{int(signal_thr*100):02d}.parquet"
    output_model    = MODEL_DIR / "meta_model_v3_clf.pkl"
    output_features = MODEL_DIR / "meta_model_v3_clf_features.json"
    output_lift     = MODEL_DIR / "meta_model_v3_clf_lift.txt"

    if not input_file.exists():
        print(f"[ERROR] Input not found: {input_file}")
        print("Run meta_labeling_v3_signal.py first.")
        return

    # ── 1. Load dataset ───────────────────────────────────────────────────────
    print(f"Loading {input_file} ...")
    df = pd.read_parquet(input_file)
    df = df.sort_values("timestamp").reset_index(drop=True)
    print(f"  {len(df):,} rows  |  base WR={df['y_tp'].mean()*100:.1f}%  "
          f"(break-even {BREAK_EVEN*100:.1f}%)")

    # Feature columns: v3 features + meta features; exclude targets + housekeeping
    exclude = {"timestamp", "bar_idx", "y_tp", "y_mfe"}
    from strategies.feature_engineering_v3 import FEATURE_COLUMNS_V3  # noqa: PLC0415
    # Priority: listed v3 cols first, then meta cols (ensures reproducibility)
    all_avail = [c for c in df.columns if c not in exclude]
    v3_avail  = [c for c in FEATURE_COLUMNS_V3 if c in df.columns]
    meta_avail = [c for c in META_FEATURES if c in df.columns]
    extra      = [c for c in all_avail if c not in v3_avail and c not in meta_avail]
    feature_cols = v3_avail + meta_avail + extra

    print(f"  Features: {len(v3_avail)} v3 + {len(meta_avail)} meta = {len(feature_cols)} total")

    X = df[feature_cols].astype(np.float32).replace([np.inf, -np.inf], np.nan)
    y = df["y_tp"].astype(np.float32)

    # Drop any rows with NaN in features
    valid = X.notna().all(axis=1)
    X, y = X[valid].reset_index(drop=True), y[valid].reset_index(drop=True)
    print(f"  After NaN drop: {len(X):,} rows")

    # ── 2. Purged time-series cross-validation ────────────────────────────────
    print("\n" + "=" * 65)
    print("PURGED + EMBARGOED CV  (5 folds, XGBClassifier)")
    print(f"  EMBARGO_BARS={EMBARGO_BARS}  LOOKAHEAD_BARS={LOOKAHEAD_BARS}")
    print("=" * 65)

    tscv = TimeSeriesSplit(n_splits=5)
    fold_aucs, fold_lls = [], []
    oof_scores = np.full(len(X), np.nan, dtype=np.float32)

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        test_start = int(test_idx[0])
        test_end   = int(test_idx[-1])
        purge_before = test_start - EMBARGO_BARS
        purge_after  = test_end   + LOOKAHEAD_BARS

        purged = np.array([
            i for i in train_idx
            if i < purge_before or i > purge_after
        ])
        if len(purged) < 100:
            print(f"Fold {fold+1}: SKIP — insufficient training rows after purging")
            continue

        dropped = len(train_idx) - len(purged)
        X_tr, y_tr = X.iloc[purged],    y.iloc[purged]
        X_te, y_te = X.iloc[test_idx],  y.iloc[test_idx]

        clf = XGBClassifier(**XGB_PARAMS)
        clf.fit(
            X_tr, y_tr,
            eval_set=[(X_te, y_te)],
            verbose=False,
        )

        proba = clf.predict_proba(X_te.values)[:, 1]
        oof_scores[test_idx] = proba

        auc = roc_auc_score(y_te, proba)
        ll  = log_loss(y_te, proba)
        fold_aucs.append(auc)
        fold_lls.append(ll)

        print(f"Fold {fold+1}: train={len(purged):,} (purged {dropped})  "
              f"test={len(test_idx):,}  AUC={auc:.4f}  LogLoss={ll:.4f}")

    print(f"\nMean AUC:     {np.nanmean(fold_aucs):.4f}")
    print(f"Mean LogLoss: {np.nanmean(fold_lls):.4f}")

    # ── 3. OOF lift analysis ─────────────────────────────────────────────────
    oof_valid = ~np.isnan(oof_scores)
    if oof_valid.sum() > 100:
        print("\n" + "=" * 65)
        print("OOF META-SCORE LIFT  (all folds combined)")
        print(f"  Baseline WR = {y[oof_valid].mean()*100:.1f}%  "
              f"(break-even {BREAK_EVEN*100:.1f}%)")
        print(_lift_table(y[oof_valid].to_numpy(), oof_scores[oof_valid]))

        # Period decomposition on OOF
        ts_col = pd.to_datetime(df["timestamp"][valid].reset_index(drop=True))
        print("\n  OOF lift by period (meta-score ≥ 0.60):")
        thr_oof = 0.60
        for label, s, e in [
            ("OOS-EARLY  2015-2023",
             pd.Timestamp("2015-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")),
            ("IN-SAMPLE  2024-2025",
             pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")),
            ("OOS-RECENT 2026+    ",
             pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2030-01-01", tz="UTC")),
        ]:
            ts_utc = ts_col.dt.tz_localize("UTC") if ts_col.dt.tz is None else ts_col
            period_mask  = (ts_utc >= s) & (ts_utc < e)
            combined     = period_mask.to_numpy() & oof_valid & (oof_scores >= thr_oof)
            all_period   = period_mask.to_numpy() & oof_valid
            n_all = all_period.sum(); n_sel = combined.sum()
            if n_all < 10:
                continue
            wr_all = y[all_period].mean()
            wr_sel = y[combined].mean() if n_sel >= 10 else float("nan")
            print(f"    {label}: all n={n_all:,} WR={wr_all*100:.1f}%  "
                  f"→  selected n={n_sel:,} WR={wr_sel*100:.1f}%")

    # ── 4. Train final model on full data ────────────────────────────────────
    print("\n" + "=" * 65)
    print("TRAINING FINAL META-MODEL  (full data, n_estimators=200)")
    print("=" * 65)

    final_params = {k: v for k, v in XGB_PARAMS.items()
                    if k != "early_stopping_rounds"}
    final_params["n_estimators"] = 200

    final_clf = XGBClassifier(**final_params)
    final_clf.fit(X, y, verbose=False)

    # Feature importance
    imp = dict(zip(feature_cols, final_clf.feature_importances_))
    top = sorted(imp.items(), key=lambda x: x[1], reverse=True)[:15]
    print("\nTop 15 features (gain):")
    for feat, score in top:
        print(f"  {feat:<40} {score:.4f}")

    # ── 5. Save artifacts ────────────────────────────────────────────────────
    with open(output_model, "wb") as fh:
        pickle.dump(final_clf, fh)

    with open(output_features, "w", encoding="utf-8") as fh:
        json.dump({"feature_columns": feature_cols, "signal_threshold": signal_thr}, fh, indent=2)

    # Write lift summary text
    if oof_valid.sum() > 100:
        lift_text = (
            f"Meta-model lift on v3 XGB signals (base threshold={signal_thr})\n"
            f"Base WR={y[oof_valid].mean()*100:.1f}%  break-even={BREAK_EVEN*100:.1f}%\n"
            + _lift_table(y[oof_valid].to_numpy(), oof_scores[oof_valid])
        )
        output_lift.write_text(lift_text, encoding="utf-8")
        print(f"\nLift summary → {output_lift}")

    print(f"\nModel    → {output_model}")
    print(f"Features → {output_features}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--thr", type=float, default=DEFAULT_SIGNAL_THR,
        help=f"Signal confidence threshold used in labeling step (default {DEFAULT_SIGNAL_THR})"
    )
    args = parser.parse_args()
    run(signal_thr=args.thr)
