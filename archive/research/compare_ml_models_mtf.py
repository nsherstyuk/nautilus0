import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import joblib

from sklearn.base import clone
try:
    from sklearn.frozen import FrozenEstimator
except Exception:  # pragma: no cover
    FrozenEstimator = None
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, f1_score, log_loss, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from research.train_model_mtf import (
    calculate_features_15m,
    calculate_features_30m,
    create_labels,
    load_data,
    merge_mtf_data,
)


def _setup_logger(output_dir: Path) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("ml_experiments_mtf")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(output_dir / "experiments.log", mode="w", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger


def _prepare_training_data_with_index(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    feature_columns = [
        "log_ret",
        "mama_diff",
        "dmp_30m",
        "dmn_30m",
        "stoch_k_30m",
        "stoch_d_30m",
        "wma_diff_30m",
        "atr",
        "hour",
        "day_of_week",
    ]

    df_clean = df.dropna(subset=feature_columns + ["label"]).copy()
    df_signals = df_clean[df_clean["label"] != 0].copy()
    df_signals["label_binary"] = (df_signals["label"] == 1).astype(int)

    df_signals.sort_index(inplace=True)

    X = df_signals[feature_columns].values
    y = df_signals["label_binary"].values
    ts = df_signals.index.values

    return X, y, ts, feature_columns


def _score_confidence_threshold(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    proba: np.ndarray,
    confidence_threshold: float,
) -> dict:
    conf = np.max(proba, axis=1)
    mask = conf >= confidence_threshold

    coverage = float(mask.mean()) if len(mask) else 0.0

    if mask.sum() == 0:
        return {
            "confident_coverage": coverage,
            "confident_accuracy": np.nan,
            "confident_f1": np.nan,
            "confident_precision": np.nan,
            "confident_recall": np.nan,
        }

    y_true_c = y_true[mask]
    y_pred_c = y_pred[mask]

    return {
        "confident_coverage": coverage,
        "confident_accuracy": float(accuracy_score(y_true_c, y_pred_c)),
        "confident_f1": float(f1_score(y_true_c, y_pred_c, zero_division=0)),
        "confident_precision": float(precision_score(y_true_c, y_pred_c, zero_division=0)),
        "confident_recall": float(recall_score(y_true_c, y_pred_c, zero_division=0)),
    }


def _fit_estimator(
    estimator,
    X_train: np.ndarray,
    y_train: np.ndarray,
    calibrate: bool,
    calibration_fraction: float,
    random_state: int,
):
    if not calibrate:
        estimator.fit(X_train, y_train)
        return estimator

    n = len(X_train)
    if n < 100:
        estimator.fit(X_train, y_train)
        return estimator

    split = int(n * (1.0 - calibration_fraction))
    split = max(1, min(split, n - 1))

    X_fit, y_fit = X_train[:split], y_train[:split]
    X_cal, y_cal = X_train[split:], y_train[split:]

    estimator.fit(X_fit, y_fit)

    if FrozenEstimator is not None:
        calibrated = CalibratedClassifierCV(FrozenEstimator(estimator), method="sigmoid")
    else:
        calibrated = CalibratedClassifierCV(estimator, method="sigmoid", cv="prefit")
    calibrated.fit(X_cal, y_cal)

    return calibrated


def _build_model_specs(random_state: int) -> list[tuple[str, object, bool]]:
    hgb = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.05,
        max_depth=6,
        min_samples_leaf=20,
        l2_regularization=1.0,
        class_weight="balanced",
        random_state=random_state,
    )

    et = ExtraTreesClassifier(
        n_estimators=800,
        max_depth=None,
        min_samples_leaf=10,
        max_features="sqrt",
        class_weight="balanced",
        random_state=random_state,
        n_jobs=-1,
    )

    rf = RandomForestClassifier(
        n_estimators=800,
        max_depth=None,
        min_samples_leaf=10,
        max_features="sqrt",
        class_weight="balanced",
        random_state=random_state,
        n_jobs=-1,
    )

    lr = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    C=0.5,
                    solver="lbfgs",
                    max_iter=5000,
                    class_weight="balanced",
                    random_state=random_state,
                ),
            ),
        ]
    )

    return [
        ("HGB", hgb, False),
        ("HGB_CAL", hgb, True),
        ("EXTRA_TREES", et, False),
        ("EXTRA_TREES_CAL", et, True),
        ("RANDOM_FOREST", rf, False),
        ("RANDOM_FOREST_CAL", rf, True),
        ("LOGREG", lr, False),
        ("LOGREG_CAL", lr, True),
    ]


def _safe_roc_auc(y_true: np.ndarray, proba: np.ndarray) -> float:
    try:
        return float(roc_auc_score(y_true, proba[:, 1]))
    except Exception:
        return float("nan")


def run_experiments(
    train_start: str,
    train_end: str,
    horizon: int,
    atr_multiplier: float,
    n_splits: int,
    confidence_threshold: float,
    calibration_fraction: float,
    random_state: int,
    output_dir: Path,
    save_best: bool,
    model_out: Optional[Path],
    rank_by: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    logger = _setup_logger(output_dir)

    symbol = "EUR-USD"

    logger.info("Loading 15-minute data...")
    df_15m = load_data(symbol, "15_MINUTE", train_start, train_end)

    logger.info("Loading 30-minute data...")
    df_30m = load_data(symbol, "30_MINUTE", train_start, train_end)

    logger.info("Calculating features...")
    df_15m = calculate_features_15m(df_15m)
    df_30m = calculate_features_30m(df_30m)

    logger.info("Merging timeframes...")
    df_merged = merge_mtf_data(df_15m, df_30m)

    logger.info("Creating labels...")
    df_labeled = create_labels(df_merged, horizon=horizon, atr_multiplier=atr_multiplier)

    X, y, ts, feature_names = _prepare_training_data_with_index(df_labeled)

    logger.info("Samples: %s", len(X))
    logger.info("Buy: %s", int((y == 1).sum()))
    logger.info("Sell: %s", int((y == 0).sum()))

    tscv = TimeSeriesSplit(n_splits=n_splits)

    results: list[dict] = []

    model_specs = _build_model_specs(random_state)

    for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X), start=1):
        X_train, y_train = X[train_idx], y[train_idx]
        X_test, y_test = X[test_idx], y[test_idx]

        ts_train_start = pd.Timestamp(ts[train_idx[0]]).isoformat()
        ts_train_end = pd.Timestamp(ts[train_idx[-1]]).isoformat()
        ts_test_start = pd.Timestamp(ts[test_idx[0]]).isoformat()
        ts_test_end = pd.Timestamp(ts[test_idx[-1]]).isoformat()

        logger.info(
            "Fold %s/%s train=%s test=%s train_range=%s..%s test_range=%s..%s",
            fold_idx,
            n_splits,
            len(train_idx),
            len(test_idx),
            ts_train_start,
            ts_train_end,
            ts_test_start,
            ts_test_end,
        )

        for name, base_estimator, should_calibrate in model_specs:
            estimator = clone(base_estimator)
            fitted = _fit_estimator(
                estimator,
                X_train,
                y_train,
                calibrate=should_calibrate,
                calibration_fraction=calibration_fraction,
                random_state=random_state,
            )

            y_pred = fitted.predict(X_test)
            proba = fitted.predict_proba(X_test)

            row = {
                "model": name,
                "fold": fold_idx,
                "n_train": int(len(train_idx)),
                "n_test": int(len(test_idx)),
                "accuracy": float(accuracy_score(y_test, y_pred)),
                "f1": float(f1_score(y_test, y_pred, zero_division=0)),
                "precision": float(precision_score(y_test, y_pred, zero_division=0)),
                "recall": float(recall_score(y_test, y_pred, zero_division=0)),
                "roc_auc": _safe_roc_auc(y_test, proba),
            }

            try:
                row["log_loss"] = float(log_loss(y_test, proba))
            except Exception:
                row["log_loss"] = float("nan")

            row.update(_score_confidence_threshold(y_test, y_pred, proba, confidence_threshold))
            results.append(row)

    results_df = pd.DataFrame(results)

    agg = {
        "accuracy": ["mean", "std"],
        "f1": ["mean", "std"],
        "precision": ["mean", "std"],
        "recall": ["mean", "std"],
        "roc_auc": ["mean", "std"],
        "log_loss": ["mean", "std"],
        "confident_coverage": ["mean", "std"],
        "confident_accuracy": ["mean", "std"],
        "confident_f1": ["mean", "std"],
        "confident_precision": ["mean", "std"],
        "confident_recall": ["mean", "std"],
    }

    summary_df = results_df.groupby("model").agg(agg)
    summary_df.columns = [f"{a}_{b}" for a, b in summary_df.columns]
    summary_df.reset_index(inplace=True)

    if rank_by not in summary_df.columns:
        rank_by = "confident_f1_mean"

    sort_ascending = False
    if "log_loss" in rank_by:
        sort_ascending = True

    summary_df.sort_values(by=rank_by, ascending=sort_ascending, inplace=True)

    results_path = output_dir / "results_by_fold.csv"
    summary_path = output_dir / "summary_by_model.csv"
    results_df.to_csv(results_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    logger.info("\nRANKED SUMMARY (rank_by=%s):\n%s", rank_by, summary_df.to_string(index=False))

    logger.info("Saved: %s", str(results_path))
    logger.info("Saved: %s", str(summary_path))

    best_model_name = str(summary_df.iloc[0]["model"]) if len(summary_df) else None

    if save_best and best_model_name and model_out is not None:
        logger.info("Training best model on full dataset: %s", best_model_name)

        spec_by_name = {name: (est, cal) for name, est, cal in model_specs}
        base_estimator, should_calibrate = spec_by_name[best_model_name]

        estimator = clone(base_estimator)
        fitted = _fit_estimator(
            estimator,
            X,
            y,
            calibrate=should_calibrate,
            calibration_fraction=calibration_fraction,
            random_state=random_state,
        )

        model_out.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(fitted, model_out)
        logger.info("Saved best model to: %s", str(model_out))

    return results_df, summary_df


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-start", default="2024-01-01")
    parser.add_argument("--train-end", default="2025-12-18")
    parser.add_argument("--horizon", type=int, default=12)
    parser.add_argument("--atr-multiplier", type=float, default=1.5)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--confidence-threshold", type=float, default=0.68)
    parser.add_argument("--calibration-fraction", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--save-best", action="store_true")
    parser.add_argument("--model-out", default="")
    parser.add_argument("--rank-by", default="confident_f1_mean")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_root = _PROJECT_ROOT
    output_dir = project_root / "logs" / "ml_experiments" / f"mtf_{timestamp}"

    model_out = Path(args.model_out) if args.model_out else None
    if model_out is not None and not model_out.is_absolute():
        model_out = project_root / model_out

    run_experiments(
        train_start=args.train_start,
        train_end=args.train_end,
        horizon=args.horizon,
        atr_multiplier=args.atr_multiplier,
        n_splits=args.n_splits,
        confidence_threshold=args.confidence_threshold,
        calibration_fraction=args.calibration_fraction,
        random_state=args.random_state,
        output_dir=output_dir,
        save_best=bool(args.save_best),
        model_out=model_out,
        rank_by=args.rank_by,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
