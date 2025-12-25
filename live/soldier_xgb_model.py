from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import math
import pickle


_DEFAULT_FEATURES: List[str] = [
    "macro_permission",
    "atr_15m",
    "rsi_5m",
    "macd_5m",
    "macd_signal_5m",
    "macd_hist_5m",
    "bb_width_5m",
    "body_5m",
    "upper_wick_5m",
    "lower_wick_5m",
]


def load_feature_list(path: Path) -> List[str]:
    if not path.exists():
        return list(_DEFAULT_FEATURES)
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    feats = [ln for ln in lines if ln and not ln.startswith("#")]
    return feats or list(_DEFAULT_FEATURES)


@dataclass
class XgbSoldierModel:
    model_path: Path
    feature_names: List[str]

    def __post_init__(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(str(self.model_path))

        with self.model_path.open("rb") as f:
            self._model = pickle.load(f)

    def predict(self, features: Dict[str, float]) -> float:
        # Build a 1xN feature row in the exact order used in training.
        row: List[float] = []
        for name in self.feature_names:
            v = features.get(name, float("nan"))
            try:
                fv = float(v)
            except Exception:
                fv = float("nan")
            if fv is not None and isinstance(fv, float) and math.isfinite(fv) is False:
                # Keep NaN/inf as NaN; xgboost handles missing.
                if fv != fv:
                    pass
                else:
                    fv = float("nan")
            row.append(fv)

        # XGBoost sklearn API expects 2D.
        proba = self._model.predict_proba([row])[0]
        # binary classifier: proba[1] is P(y=1)
        return float(proba[1])
