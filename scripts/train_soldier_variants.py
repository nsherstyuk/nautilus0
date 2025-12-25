from __future__ import annotations

import argparse
import json
import os
import pickle
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


FEATURE_COLS: Tuple[str, ...] = (
    # Must match live feature keys (see live/hmtf_engine.py)
    "macro_permission",  # mapped from last_15m_prediction
    "atr_15m",
    "rsi_5m",
    "macd_5m",
    "macd_signal_5m",
    "macd_hist_5m",
    "bb_width_5m",
    "body_5m",
    "upper_wick_5m",
    "lower_wick_5m",
)


@dataclass
class VariantResult:
    name: str
    rows_total: int
    rows_train: int
    rows_val: int
    positive_rate_train: float
    positive_rate_val: float
    threshold_master_abs: Optional[float]
    use_sample_weight: bool

    # Metrics @ 0.5
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float
    average_precision: float

    confusion_matrix: List[List[int]]


@dataclass
class TrainingReport:
    created_utc: str
    dataset_path: str
    model_out: str
    feature_list_out: str
    report_out: str
    optimize_for: str
    val_days: int
    variants: List[VariantResult]
    best_variant: str


def _parse_ts(s: Any) -> datetime:
    return datetime.fromisoformat(str(s))


def _load_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "ts_5m_close" not in df.columns:
        raise ValueError("Dataset must contain ts_5m_close")
    if "last_15m_prediction" not in df.columns:
        raise ValueError("Dataset must contain last_15m_prediction")
    if "y" not in df.columns:
        raise ValueError(
            "Dataset must contain label column y. "
            "Use scripts/build_hmtf_stitched_dataset.py to generate an offline labeled dataset."
        )

    df["ts_5m_close"] = pd.to_datetime(df["ts_5m_close"], utc=True)

    # Map master output into the live feature name.
    df["macro_permission"] = pd.to_numeric(df["last_15m_prediction"], errors="coerce").astype(float)

    # Coerce numeric feature columns.
    for c in FEATURE_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)

    df["y"] = pd.to_numeric(df["y"], errors="coerce").astype(float)
    df = df.dropna(subset=["ts_5m_close", "y"])

    # Ensure labels are 0/1 ints.
    df["y"] = df["y"].astype(int)

    return df


def _time_split(df: pd.DataFrame, *, val_days: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("ts_5m_close").reset_index(drop=True)
    last_ts = df["ts_5m_close"].iloc[-1]
    cutoff = last_ts - timedelta(days=val_days)
    train = df[df["ts_5m_close"] < cutoff].copy()
    val = df[df["ts_5m_close"] >= cutoff].copy()
    if train.empty or val.empty:
        raise ValueError(
            f"Time split produced empty train/val (val_days={val_days}, cutoff={cutoff.isoformat()}). "
            "Increase date range or reduce val_days."
        )
    return train, val


def _compute_metrics(y_true: np.ndarray, y_prob: np.ndarray) -> Dict[str, Any]:
    from sklearn.metrics import (
        accuracy_score,
        average_precision_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    y_pred = (y_prob >= 0.5).astype(int)

    out: Dict[str, Any] = {}
    out["accuracy"] = float(accuracy_score(y_true, y_pred))
    out["precision"] = float(precision_score(y_true, y_pred, zero_division=0))
    out["recall"] = float(recall_score(y_true, y_pred, zero_division=0))
    out["f1"] = float(f1_score(y_true, y_pred, zero_division=0))

    # AUC can fail if only one class is present.
    try:
        out["roc_auc"] = float(roc_auc_score(y_true, y_prob))
    except Exception:
        out["roc_auc"] = float("nan")

    try:
        out["average_precision"] = float(average_precision_score(y_true, y_prob))
    except Exception:
        out["average_precision"] = float("nan")

    out["confusion_matrix"] = confusion_matrix(y_true, y_pred).astype(int).tolist()
    return out


def _train_xgb(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    *,
    sample_weight_train: Optional[np.ndarray],
) -> Any:
    import xgboost as xgb

    model = xgb.XGBClassifier(
        n_estimators=1200,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        random_state=42,
    )

    fit_kwargs: Dict[str, Any] = {
        "eval_set": [(X_val, y_val)],
        "verbose": False,
    }

    # xgboost>=3 changed the sklearn API and may not accept early_stopping_rounds.
    # We keep the training simple and deterministic here; metrics will still guide model selection.

    if sample_weight_train is not None:
        fit_kwargs["sample_weight"] = sample_weight_train

    model.fit(X_train, y_train, **fit_kwargs)
    return model


def _choose_best(variants: List[VariantResult], optimize_for: str) -> str:
    optimize_for = (optimize_for or "precision").strip().lower()

    # Use simple scalar comparison.
    if optimize_for == "precision":
        key = lambda vr: (vr.precision, vr.average_precision)
    elif optimize_for == "f1":
        key = lambda vr: (vr.f1, vr.average_precision)
    elif optimize_for in ("ap", "average_precision"):
        key = lambda vr: (vr.average_precision, vr.precision)
    elif optimize_for in ("roc_auc", "auc"):
        key = lambda vr: (vr.roc_auc, vr.average_precision)
    else:
        key = lambda vr: (vr.precision, vr.average_precision)

    best = max(variants, key=key)
    return best.name


def _variant_specs(master_abs_threshold: float) -> List[Tuple[str, Optional[float], bool]]:
    # name, threshold (None means no filter), use_sample_weight
    return [
        ("A_unweighted", None, False),
        ("B_weight_abs_master", None, True),
        ("C_filter_master_abs", master_abs_threshold, False),
    ]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Train soldier model variants (A/B/C) from offline labeled HMTF dataset")
    p.add_argument(
        "--dataset",
        default="logs/offline_mtf/hmtf_offline_20251001_20251201.csv",
        help="Offline labeled dataset CSV (must include y).",
    )
    p.add_argument("--val-days", type=int, default=14, help="Number of trailing days reserved for validation")
    p.add_argument(
        "--master-abs-threshold",
        type=float,
        default=float(os.getenv("MTF3_MASTER_PREDICTION_THRESHOLD", "0.70")),
        help="Threshold used for variant C filtering (abs(master_pred) >= threshold)",
    )
    p.add_argument(
        "--optimize-for",
        default=os.getenv("MTF3_TRAIN_OPTIMIZE_FOR", "precision"),
        help="Which metric to pick the best variant by (precision|f1|average_precision|roc_auc)",
    )
    p.add_argument(
        "--model-out",
        default=os.getenv("MTF3_SOLDIER_MODEL_PATH", "models/soldier_5m_xgb.pkl"),
        help="Where to write the winning model",
    )
    p.add_argument(
        "--feature-list-out",
        default=os.getenv("MTF3_FEATURE_LIST_PATH", "models/soldier_5m_feature_names.txt"),
        help="Where to write the feature list",
    )
    p.add_argument(
        "--report-out",
        default="",
        help="Optional JSON report path (default: reports/soldier_training_report_<ts>.json)",
    )

    args = p.parse_args(argv)

    project_root = Path(__file__).resolve().parent.parent
    dataset_path = (project_root / args.dataset).resolve() if not Path(args.dataset).is_absolute() else Path(args.dataset)
    model_out = (project_root / args.model_out).resolve() if not Path(args.model_out).is_absolute() else Path(args.model_out)
    feature_list_out = (project_root / args.feature_list_out).resolve() if not Path(args.feature_list_out).is_absolute() else Path(args.feature_list_out)

    report_out: Path
    if args.report_out:
        report_out = (project_root / args.report_out).resolve() if not Path(args.report_out).is_absolute() else Path(args.report_out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_out = (project_root / "reports" / f"soldier_training_report_{ts}.json").resolve()

    df = _load_dataset(dataset_path)
    train_df, val_df = _time_split(df, val_days=args.val_days)

    # Base arrays (no variant-specific filtering yet)
    X_train_base = train_df.loc[:, FEATURE_COLS].to_numpy(dtype=float)
    y_train_base = train_df["y"].to_numpy(dtype=int)
    X_val_base = val_df.loc[:, FEATURE_COLS].to_numpy(dtype=float)
    y_val_base = val_df["y"].to_numpy(dtype=int)

    variants: List[VariantResult] = []
    trained_models: Dict[str, Any] = {}

    for name, thr, use_weight in _variant_specs(args.master_abs_threshold):
        tr = train_df
        va = val_df

        if thr is not None:
            tr = tr[np.abs(tr["macro_permission"]) >= thr]
            va = va[np.abs(va["macro_permission"]) >= thr]

        if tr.empty or va.empty:
            # Skip variant rather than hard-failing; record NaNs.
            variants.append(
                VariantResult(
                    name=name,
                    rows_total=len(df),
                    rows_train=len(tr),
                    rows_val=len(va),
                    positive_rate_train=float("nan"),
                    positive_rate_val=float("nan"),
                    threshold_master_abs=thr,
                    use_sample_weight=use_weight,
                    accuracy=float("nan"),
                    precision=float("nan"),
                    recall=float("nan"),
                    f1=float("nan"),
                    roc_auc=float("nan"),
                    average_precision=float("nan"),
                    confusion_matrix=[[0, 0], [0, 0]],
                )
            )
            continue

        X_train = tr.loc[:, FEATURE_COLS].to_numpy(dtype=float)
        y_train = tr["y"].to_numpy(dtype=int)
        X_val = va.loc[:, FEATURE_COLS].to_numpy(dtype=float)
        y_val = va["y"].to_numpy(dtype=int)

        w_train: Optional[np.ndarray]
        if use_weight:
            w_train = np.abs(tr["macro_permission"].to_numpy(dtype=float))
        else:
            w_train = None

        model = _train_xgb(X_train, y_train, X_val, y_val, sample_weight_train=w_train)

        y_prob = model.predict_proba(X_val)[:, 1]
        m = _compute_metrics(y_val, y_prob)

        vr = VariantResult(
            name=name,
            rows_total=len(df),
            rows_train=len(tr),
            rows_val=len(va),
            positive_rate_train=float(np.mean(y_train)) if len(y_train) else float("nan"),
            positive_rate_val=float(np.mean(y_val)) if len(y_val) else float("nan"),
            threshold_master_abs=thr,
            use_sample_weight=use_weight,
            accuracy=float(m["accuracy"]),
            precision=float(m["precision"]),
            recall=float(m["recall"]),
            f1=float(m["f1"]),
            roc_auc=float(m["roc_auc"]),
            average_precision=float(m["average_precision"]),
            confusion_matrix=m["confusion_matrix"],
        )

        variants.append(vr)
        trained_models[name] = model

    # Drop NaN variants from selection
    selectable = [v for v in variants if np.isfinite(v.precision)]
    if not selectable:
        raise SystemExit("No variants produced valid metrics (check dataset/threshold/val split)")

    best_name = _choose_best(selectable, args.optimize_for)

    best_model = trained_models[best_name]
    model_out.parent.mkdir(parents=True, exist_ok=True)
    with model_out.open("wb") as f:
        pickle.dump(best_model, f)

    feature_list_out.parent.mkdir(parents=True, exist_ok=True)
    feature_list_out.write_text("\n".join(FEATURE_COLS), encoding="utf-8")

    report = TrainingReport(
        created_utc=datetime.now(timezone.utc).isoformat(),
        dataset_path=str(dataset_path),
        model_out=str(model_out),
        feature_list_out=str(feature_list_out),
        report_out=str(report_out),
        optimize_for=str(args.optimize_for),
        val_days=int(args.val_days),
        variants=variants,
        best_variant=best_name,
    )

    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    # Console summary
    print("=" * 80)
    print("SOLDIER TRAINING REPORT")
    print("=" * 80)
    print(f"Dataset: {dataset_path}")
    print(f"Train rows: {len(train_df)}  Val rows: {len(val_df)}  (val_days={args.val_days})")
    print(f"Feature cols ({len(FEATURE_COLS)}): {', '.join(FEATURE_COLS)}")
    print("\nVariant results (val metrics @ p>=0.5):")
    for v in variants:
        print(
            f"- {v.name}: rows(train={v.rows_train}, val={v.rows_val}) "
            f"thr={v.threshold_master_abs} weight={v.use_sample_weight} "
            f"precision={v.precision:.4f} recall={v.recall:.4f} f1={v.f1:.4f} "
            f"ap={v.average_precision:.4f} auc={v.roc_auc:.4f}"
        )
    print(f"\nBest variant by {args.optimize_for}: {best_name}")
    print(f"Saved model: {model_out}")
    print(f"Saved feature list: {feature_list_out}")
    print(f"Saved report: {report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
