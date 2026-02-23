"""
Model inference for Trading System v4.

V4ModelInference loads the three artifacts produced by train_model.py:
  <stem>.pkl             — XGBoost model
  <stem>_features.json   — ordered list of 80+ feature names
  <stem>_threshold.json  — {"threshold": X.XX}  (EV-optimal threshold)

Usage:
    from trading_system_v4.model.model_inference import V4ModelInference
    inf = V4ModelInference("hybrid_model_eurusd_v4")
    prob = inf.predict_proba(features_dict)
    should_trade, prob = inf.should_trade(features_dict)
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np

# ── default model directory ────────────────────────────────────────────────────
_DEFAULT_MODEL_DIR = Path(__file__).resolve().parent


class V4ModelInference:
    """
    Thin inference wrapper around a trained XGBoost v4 model.

    Loads model, the canonical feature-name list, and the EV-optimal threshold
    all in one go.  Feature ordering is enforced by the saved JSON list, so the
    caller can pass a plain dict and this class handles alignment.  Missing keys
    are filled with 0.0 (should not occur in steady-state production).
    """

    def __init__(self, model_stem: str, model_dir: str | Path | None = None) -> None:
        """
        Args:
            model_stem:  Base name of the model artifacts, e.g.
                         ``"hybrid_model_eurusd_v4"``.
            model_dir:   Directory that contains the .pkl / .json files.
                         Defaults to ``trading_system_v4/model/``.
        """
        model_dir = Path(model_dir) if model_dir is not None else _DEFAULT_MODEL_DIR

        model_path     = model_dir / f"{model_stem}.pkl"
        features_path  = model_dir / f"{model_stem}_features.json"
        threshold_path = model_dir / f"{model_stem}_threshold.json"

        for p in (model_path, features_path, threshold_path):
            if not p.exists():
                raise FileNotFoundError(f"[V4ModelInference] artifact not found: {p}")

        with open(model_path, "rb") as fh:
            self.model = pickle.load(fh)

        with open(features_path) as fh:
            self.feature_names: list[str] = json.load(fh)

        with open(threshold_path) as fh:
            data = json.load(fh)
            self.threshold: float = float(data["threshold"])

        print(
            f"[V4ModelInference] Loaded {model_stem}  "
            f"features={len(self.feature_names)}  threshold={self.threshold:.4f}"
        )

    # ── public API ────────────────────────────────────────────────────────────

    def predict_proba(self, features_dict: dict) -> float:
        """
        Return P(y=1) for the given feature dict.

        Feature order is enforced from the saved JSON list.  Missing keys get 0.0.
        """
        vec = np.array(
            [float(features_dict.get(f, 0.0)) for f in self.feature_names],
            dtype=np.float32,
        ).reshape(1, -1)
        return float(self.model.predict_proba(vec)[0, 1])

    def should_trade(self, features_dict: dict) -> tuple[bool, float]:
        """
        Return ``(signal, prob)`` where ``signal`` is True when the model
        probability meets or exceeds the EV-optimal threshold.
        """
        prob = self.predict_proba(features_dict)
        return prob >= self.threshold, prob

    def n_features(self) -> int:
        return len(self.feature_names)


# ── legacy thin wrappers (kept for backward-compat with old callers) ──────────

def load_model(path: str):
    with open(path, "rb") as fh:
        return pickle.load(fh)


def predict(model, features):
    return model.predict(np.array(features).reshape(1, -1))[0]
