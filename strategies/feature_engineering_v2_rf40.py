"""V2 40-feature engineering for `models/ml_model_mtf_backup.pkl`.

This matches the model's `feature_names_in_` exactly (order + names).

Notes:
- Uses only OHLCV bars (single timeframe).
- Assumes timestamps are UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


FEATURE_COLUMNS_RF40: list[str] = [
    "returns",
    "log_returns",
    "sma_10",
    "price_to_sma_10",
    "sma_20",
    "price_to_sma_20",
    "sma_50",
    "price_to_sma_50",
    "ema_12",
    "ema_26",
    "macd",
    "macd_signal",
    "macd_diff",
    "rsi",
    "bb_middle",
    "bb_upper",
    "bb_lower",
    "bb_width",
    "bb_position",
    "tr",
    "atr",
    "atr_pct",
    "volatility",
    "volume_sma",
    "volume_ratio",
    "momentum_5",
    "roc_5",
    "momentum_10",
    "roc_10",
    "momentum_20",
    "roc_20",
    "body",
    "upper_shadow",
    "lower_shadow",
    "body_to_range",
    "hour",
    "day_of_week",
    "is_london_session",
    "is_ny_session",
    "is_overlap",
]


@dataclass(frozen=True)
class RF40Meta:
    """Extra metrics not part of the 40-feature model (optional)."""

    mama_diff: Optional[float] = None
    dmi_plus: Optional[float] = None


def _compute_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=length).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=length).mean()
    rs = gain / loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_rf40_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DF with FEATURE_COLUMNS_RF40 computed.

    Input df must have columns: open, high, low, close, volume and a UTC datetime index.
    """

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns for rf40 features: {sorted(missing)}")

    out = pd.DataFrame(index=df.index)

    # Price changes
    out["returns"] = df["close"].pct_change()
    out["log_returns"] = np.log(df["close"] / df["close"].shift(1))

    # Moving averages + ratios
    for period in (10, 20, 50):
        sma = df["close"].rolling(period).mean()
        out[f"sma_{period}"] = sma
        out[f"price_to_sma_{period}"] = df["close"] / sma

    # EMAs
    out["ema_12"] = df["close"].ewm(span=12).mean()
    out["ema_26"] = df["close"].ewm(span=26).mean()

    # MACD
    out["macd"] = out["ema_12"] - out["ema_26"]
    out["macd_signal"] = out["macd"].ewm(span=9).mean()
    out["macd_diff"] = out["macd"] - out["macd_signal"]

    # RSI
    out["rsi"] = _compute_rsi(df["close"], length=14)

    # Bollinger
    out["bb_middle"] = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    out["bb_upper"] = out["bb_middle"] + (bb_std * 2)
    out["bb_lower"] = out["bb_middle"] - (bb_std * 2)
    out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / out["bb_middle"]

    bb_span = out["bb_upper"] - out["bb_lower"]
    out["bb_position"] = np.where(bb_span > 0, (df["close"] - out["bb_lower"]) / bb_span, np.nan)

    # TR/ATR
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ),
    )
    out["tr"] = tr
    out["atr"] = tr.rolling(14).mean()
    out["atr_pct"] = out["atr"] / df["close"]

    # Volatility
    out["volatility"] = out["returns"].rolling(20).std()

    # Volume
    out["volume_sma"] = df["volume"].rolling(20).mean()
    out["volume_ratio"] = np.where(out["volume_sma"] > 0, df["volume"] / out["volume_sma"], 0.0)

    # Momentum + ROC
    for period in (5, 10, 20):
        out[f"momentum_{period}"] = df["close"] - df["close"].shift(period)
        out[f"roc_{period}"] = df["close"].pct_change(period)

    # Candle features
    out["body"] = (df["close"] - df["open"]).abs()
    out["upper_shadow"] = df["high"] - np.maximum(df["open"], df["close"])
    out["lower_shadow"] = np.minimum(df["open"], df["close"]) - df["low"]

    hl_range = df["high"] - df["low"]
    out["body_to_range"] = np.where(hl_range != 0, out["body"] / hl_range, np.nan)

    # Time features (assumes UTC index)
    out["hour"] = out.index.hour
    out["day_of_week"] = out.index.dayofweek
    out["is_london_session"] = ((out["hour"] >= 8) & (out["hour"] < 16)).astype(int)
    out["is_ny_session"] = ((out["hour"] >= 13) & (out["hour"] < 21)).astype(int)
    out["is_overlap"] = ((out["hour"] >= 13) & (out["hour"] < 16)).astype(int)

    # Ensure column order
    return out[FEATURE_COLUMNS_RF40]


def latest_rf40_row(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Return a single-row DF with rf40 features for the latest timestamp.

    Returns None if any required feature is NaN/inf (insufficient warmup).
    """

    feats = compute_rf40_features(df)
    row = feats.iloc[[-1]].astype(float)

    values = row.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return None

    return row
