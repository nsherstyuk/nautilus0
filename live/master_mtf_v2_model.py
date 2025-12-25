from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from live.hmtf_engine import BarEvent


@dataclass
class _BarRow:
    ts: Any
    open: float
    high: float
    low: float
    close: float
    volume: float


class MtfV2SklearnMasterModel:
    """Master model using the existing v2 MTF sklearn model + feature recipe.

    This is the *live/replay* counterpart to scripts/build_hmtf_stitched_dataset.py::_compute_master_predictions.

    It maintains an in-memory history of 15m bars and recomputes the required
    feature row for the latest close on each call.

    Output is a signed confidence:
      - positive => bullish (LONG)
      - negative => bearish (SHORT)
      - magnitude ~ confidence strength

    Notes:
    - This class intentionally recomputes features using pandas/pandas_ta for
      correctness and parity with the offline pipeline. Given 15m cadence, this
      is typically fast enough.
    """

    def __init__(self, *, model_path: Path) -> None:
        self.model_path = Path(model_path)
        self._rows: List[_BarRow] = []

        try:
            import joblib  # type: ignore

            self._model = joblib.load(self.model_path)
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Failed to load master model at {self.model_path}: {e}")

    def _append_bar(self, bar: BarEvent) -> None:
        self._rows.append(
            _BarRow(
                ts=bar.end_time_utc,
                open=float(bar.o),
                high=float(bar.h),
                low=float(bar.l),
                close=float(bar.c),
                volume=float(bar.v),
            )
        )

        # Keep the history bounded (enough for warmup + stability).
        if len(self._rows) > 2000:
            self._rows = self._rows[-2000:]

    def predict(self, bar_15m: BarEvent, atr_15m: float) -> float:
        # atr_15m is computed by the engine; we keep it for interface parity.
        # The feature recipe here matches the offline builder (which derives ATR
        # via pandas_ta). We don't rely on atr_15m for the classifier input.

        self._append_bar(bar_15m)

        # Need sufficient history (offline builder uses 30 x 15m warmup).
        if len(self._rows) < 40:
            return 0.0

        try:
            import numpy as np  # type: ignore
            import pandas as pd  # type: ignore
            import pandas_ta as ta  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Missing dependency for live master model feature computation. "
                "Install pandas and pandas_ta. "
                f"Import error: {e}"
            )

        df = pd.DataFrame([r.__dict__ for r in self._rows])
        df = df.set_index("ts")
        df = df.sort_index()

        # Align to offline columns
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        log_ret = np.log(close / close.shift(1))

        hl2 = (high + low) / 2.0
        mama = ta.mama(hl2, fastlimit=0.5, slowlimit=0.05)
        if mama is not None and getattr(mama, "shape", (0, 0))[1] >= 2:
            mama_diff = mama.iloc[:, 0] - mama.iloc[:, 1]
        else:
            mama_diff = pd.Series(0.0, index=df.index)

        atr = ta.atr(high, low, close, length=14)
        atr = atr.astype(float)
        atr_norm = atr / close

        hour = df.index.hour.astype(float)
        dow = df.index.dayofweek.astype(float)

        # 30m resample + indicators
        df30 = df.resample("30min").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ).dropna()

        adx = ta.adx(df30["high"], df30["low"], df30["close"], length=14)
        dmp = adx["DMP_14"] if adx is not None and "DMP_14" in adx.columns else pd.Series(0.0, index=df30.index)
        dmn = adx["DMN_14"] if adx is not None and "DMN_14" in adx.columns else pd.Series(0.0, index=df30.index)

        stoch = ta.stoch(df30["high"], df30["low"], df30["close"], k=14, d=3, smooth_k=3)
        if stoch is not None and getattr(stoch, "shape", (0, 0))[1] >= 2:
            stoch_k = stoch.iloc[:, 0]
            stoch_d = stoch.iloc[:, 1]
        else:
            stoch_k = pd.Series(50.0, index=df30.index)
            stoch_d = pd.Series(50.0, index=df30.index)

        wma_fast = ta.wma(df30["close"], length=9)
        wma_slow = ta.wma(df30["close"], length=23)
        if wma_fast is not None and wma_slow is not None:
            wma_diff = (wma_fast - wma_slow) / df30["close"]
        else:
            wma_diff = pd.Series(0.0, index=df30.index)

        df30_ind = (
            pd.DataFrame(
                {
                    "ts": df30.index,
                    "dmp_30m": dmp.values,
                    "dmn_30m": dmn.values,
                    "stoch_k": stoch_k.values,
                    "stoch_d": stoch_d.values,
                    "wma_diff": wma_diff.values,
                }
            )
            .sort_values("ts")
            .reset_index(drop=True)
        )

        df15_base = (
            pd.DataFrame(
                {
                    "ts": df.index,
                    "log_ret": log_ret.values,
                    "mama_diff": mama_diff.values,
                    "atr_norm": atr_norm.values,
                    "hour": hour,
                    "dow": dow,
                }
            )
            .sort_values("ts")
            .reset_index(drop=True)
        )

        dfm = pd.merge_asof(df15_base, df30_ind, on="ts", direction="backward")

        feature_cols = [
            "log_ret",
            "mama_diff",
            "dmp_30m",
            "dmn_30m",
            "stoch_k",
            "stoch_d",
            "wma_diff",
            "atr_norm",
            "hour",
            "dow",
        ]

        dfm["i"] = np.arange(len(dfm))
        dfm = dfm[dfm["i"] >= 30]
        dfm = dfm.dropna(subset=feature_cols)

        if dfm.empty:
            return 0.0

        last = dfm.iloc[[-1]].copy()
        X = last[feature_cols].astype(float).to_numpy()

        pred = self._model.predict(X)
        try:
            proba = self._model.predict_proba(X)
            conf = float(proba.max(axis=1)[0])
        except Exception:
            conf = 0.5

        conf_signed = conf if int(pred[0]) == 1 else -conf
        return float(conf_signed)
