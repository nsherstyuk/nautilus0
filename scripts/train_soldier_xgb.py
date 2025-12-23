from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class TrainConfig:
    dataset_path: Path
    model_out: Path
    feature_list_out: Path


def _load_rows(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header")
        rows = list(reader)
        return rows, list(reader.fieldnames)


def main() -> int:
    # NOTE: This is a scaffold. Label-building (+0.6 ATR before -1.4 ATR) requires
    # a forward-looking scan over future bars, which well implement once we lock
    # down what extra columns we want (e.g., close series, or a postprocess pass).

    try:
        import xgboost as xgb
    except Exception as e:
        raise SystemExit(
            "xgboost is not installed in the active environment. Install it first, e.g. `pip install xgboost`.\n"
            f"Import error: {e}"
        )

    dataset_path = Path(os.getenv("MTF3_DATASET_PATH", "logs/live_mtf/hmtf_5m_dataset.csv"))
    model_out = Path(os.getenv("MTF3_SOLDIER_MODEL_PATH", "models/soldier_5m_xgb.pkl"))
    feature_list_out = Path(os.getenv("MTF3_FEATURE_LIST_PATH", "models/soldier_5m_feature_names.txt"))

    rows, fieldnames = _load_rows(dataset_path)
    if not rows:
        raise SystemExit(f"No rows found in dataset: {dataset_path}")

    print(f"Loaded {len(rows)} rows from {dataset_path}")

    # Feature columns (exclude timestamps and raw OHLC by default; adjust as needed)
    drop = {
        "ts_5m_close",
        "ts_master_15m_close",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "last_15m_prediction",
        "atr_15m",
    }

    feature_cols = [c for c in fieldnames if c not in drop]

    # Sample weighting per spec: abs(last_15m_prediction)
    weights = [abs(float(r.get("last_15m_prediction", "0") or 0.0)) for r in rows]

    # Placeholder labels: must be replaced with the ATR-first-hit label generation
    y = [0 for _ in rows]

    # Build X
    X = [[float(r.get(c, "nan") or "nan") for c in feature_cols] for r in rows]

    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        random_state=42,
    )

    # IMPORTANT (secret sauce): pass sample_weight
    model.fit(X, y, sample_weight=weights)

    model_out.parent.mkdir(parents=True, exist_ok=True)
    feature_list_out.parent.mkdir(parents=True, exist_ok=True)

    import pickle

    with model_out.open("wb") as f:
        pickle.dump(model, f)

    feature_list_out.write_text("\n".join(feature_cols), encoding="utf-8")

    print(f"Saved model: {model_out}")
    print(f"Saved feature list: {feature_list_out}")
    print(f"Weights stats: min={min(weights):.4f} max={max(weights):.4f} mean={sum(weights)/len(weights):.4f}")
    print("NOTE: Labels are placeholders; implement ATR-first-hit label creation next.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
