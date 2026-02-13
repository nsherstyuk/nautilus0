"""4H Higher Timeframe (HTF) feature engineering for trend confirmation model.

This module computes features from 4-hour OHLCV bars for a separate XGBoost model
that acts as a directional filter for the primary 15-minute trading model.

The 4H model answers: "What is the dominant trend direction over the next 1-2 days?"
The 15m model answers: "Is there a good entry right now?"

When both agree, trade confidence is highest.

Designed for 4-hour OHLCV input with UTC datetime index.
Input: 4H bars resampled from 15m bars (or loaded directly).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=length).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=length).mean()
    rs = gain / loss
    return 100.0 - (100.0 / (1.0 + rs))


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series,
         length: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (ADX, DI+, DI-)."""
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = np.maximum(
        high - low,
        np.maximum((high - close.shift(1)).abs(), (low - close.shift(1)).abs()),
    )
    atr = tr.rolling(length).mean()
    di_plus = 100.0 * plus_dm.rolling(length).mean() / atr
    di_minus = 100.0 * minus_dm.rolling(length).mean() / atr
    dx = 100.0 * (di_plus - di_minus).abs() / (di_plus + di_minus)
    adx = dx.rolling(length).mean()
    return adx, di_plus, di_minus


def _stochastic_k(high: pd.Series, low: pd.Series, close: pd.Series,
                   length: int = 14) -> pd.Series:
    lowest = low.rolling(length).min()
    highest = high.rolling(length).max()
    span = highest - lowest
    return np.where(span > 0, 100.0 * (close - lowest) / span, 50.0)


def _mama_fama(close: pd.Series, fast: float = 0.5, slow: float = 0.05) -> tuple[pd.Series, pd.Series]:
    """Simplified MAMA/FAMA approximation using adaptive EMA."""
    mama = close.ewm(alpha=fast, adjust=False).mean()
    fama = mama.ewm(alpha=slow, adjust=False).mean()
    return mama, fama


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample OHLCV to a higher timeframe."""
    resampled = df.resample(rule).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna()
    return resampled


FEATURE_COLUMNS_4H: list[str] = [
    # --- Signed directional momentum (4H) ---
    "returns_1",           # 1-bar (4 hour) return
    "returns_2",           # 2-bar (8 hour) return
    "returns_4",           # 4-bar (16 hour) return
    "returns_6",           # 6-bar (24 hour / 1 day) return
    "returns_12",          # 12-bar (48 hour / 2 day) return
    "log_returns_1",
    # --- Trend indicators (4H) ---
    "macd",
    "macd_signal",
    "macd_diff",
    "macd_diff_slope",
    "ema_12_slope",
    "ema_26_slope",
    "price_to_sma_20",
    "price_to_sma_50",
    "sma_20_slope",
    "sma_50_slope",
    # --- MAMA/FAMA (4H) ---
    "mama_diff",
    "mama_diff_slope",
    # --- DMI / ADX (4H) ---
    "adx",
    "di_plus",
    "di_minus",
    "di_diff",
    # --- Mean reversion (4H) ---
    "rsi",
    "rsi_slope",
    "stoch_k",
    "bb_position",
    "bb_zscore",
    # --- Volatility context (4H) ---
    "atr_pct",
    "volatility",
    "atr_expansion",
    # --- Microstructure proxies (4H) ---
    "close_position",
    "signed_body",
    "consec_up",
    "consec_down",
    "range_expansion",
    # --- Daily context (resampled from 4H) ---
    "returns_1d_1",        # 1-day return
    "rsi_1d",              # Daily RSI
    "macd_diff_1d",        # Daily MACD histogram
    "price_to_sma20_1d",   # Daily price relative to SMA20
    "di_diff_1d",          # Daily DI+ minus DI-
    # --- Weekly context (resampled from 4H) ---
    "returns_1w_1",        # 1-week return
    "rsi_1w",              # Weekly RSI
    "price_to_sma20_1w",   # Weekly price relative to SMA20
    # --- Trend alignment ---
    "trend_alignment",     # How many TFs agree on direction (-3 to +3)
    # --- Time features ---
    "hour",
    "day_of_week",
]


def compute_4h_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute 4H HTF features from 4H OHLCV DataFrame with UTC datetime index.

    Requires ~100 bars of warmup for the highest-timeframe features.
    Input should be 4H OHLCV bars.
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    out = pd.DataFrame(index=df.index)

    # =====================================================================
    # 4-HOUR FEATURES
    # =====================================================================

    # --- Signed directional momentum ---
    out["returns_1"] = df["close"].pct_change(1)
    out["returns_2"] = df["close"].pct_change(2)
    out["returns_4"] = df["close"].pct_change(4)
    out["returns_6"] = df["close"].pct_change(6)
    out["returns_12"] = df["close"].pct_change(12)
    out["log_returns_1"] = np.log(df["close"] / df["close"].shift(1))

    # --- Trend indicators ---
    ema12 = _ema(df["close"], 12)
    ema26 = _ema(df["close"], 26)
    macd = ema12 - ema26
    macd_signal = _ema(macd, 9)
    macd_diff = macd - macd_signal

    out["macd"] = macd
    out["macd_signal"] = macd_signal
    out["macd_diff"] = macd_diff
    out["macd_diff_slope"] = macd_diff.diff(2)  # 2-bar change in histogram
    out["ema_12_slope"] = ema12.pct_change(2)
    out["ema_26_slope"] = ema26.pct_change(4)

    sma20 = df["close"].rolling(20).mean()
    sma50 = df["close"].rolling(50).mean()
    out["price_to_sma_20"] = df["close"] / sma20
    out["price_to_sma_50"] = df["close"] / sma50
    out["sma_20_slope"] = sma20.pct_change(2)
    out["sma_50_slope"] = sma50.pct_change(4)

    # --- MAMA/FAMA ---
    mama, fama = _mama_fama(df["close"])
    mama_diff = (mama - fama) / df["close"]
    out["mama_diff"] = mama_diff
    out["mama_diff_slope"] = mama_diff.diff(2)

    # --- DMI / ADX ---
    adx, di_plus, di_minus = _adx(df["high"], df["low"], df["close"], 14)
    out["adx"] = adx
    out["di_plus"] = di_plus
    out["di_minus"] = di_minus
    out["di_diff"] = di_plus - di_minus

    # --- Mean reversion ---
    rsi = _rsi(df["close"], 14)
    out["rsi"] = rsi
    out["rsi_slope"] = rsi.diff(2)
    out["stoch_k"] = pd.Series(
        _stochastic_k(df["high"], df["low"], df["close"], 14),
        index=df.index,
    )

    bb_middle = sma20
    bb_std = df["close"].rolling(20).std()
    bb_upper = bb_middle + (bb_std * 2)
    bb_lower = bb_middle - (bb_std * 2)
    bb_span = bb_upper - bb_lower
    out["bb_position"] = np.where(bb_span > 0, (df["close"] - bb_lower) / bb_span, 0.5)
    out["bb_zscore"] = np.where(bb_std > 0, (df["close"] - bb_middle) / bb_std, 0.0)

    # --- Volatility context ---
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ),
    )
    atr14 = tr.rolling(14).mean()
    atr50 = tr.rolling(50).mean()
    out["atr_pct"] = atr14 / df["close"]
    out["volatility"] = out["returns_1"].rolling(20).std()
    out["atr_expansion"] = np.where(atr50 > 0, atr14 / atr50, 1.0)

    # --- Microstructure proxies ---
    hl_range = df["high"] - df["low"]
    out["close_position"] = np.where(hl_range > 0, (df["close"] - df["low"]) / hl_range, 0.5)
    out["signed_body"] = (df["close"] - df["open"]) / np.where(hl_range > 0, hl_range, 1e-10)

    up = (df["close"] > df["close"].shift(1)).astype(int)
    down = (df["close"] < df["close"].shift(1)).astype(int)
    up_groups = (up != up.shift()).cumsum()
    down_groups = (down != down.shift()).cumsum()
    consec_up = up.groupby(up_groups).cumsum()
    consec_down = down.groupby(down_groups).cumsum()
    out["consec_up"] = consec_up.astype(float)
    out["consec_down"] = consec_down.astype(float)

    avg_range = hl_range.rolling(20).mean()
    out["range_expansion"] = np.where(avg_range > 0, hl_range / avg_range, 1.0)

    # =====================================================================
    # HIGHER TIMEFRAME FEATURES (Daily and Weekly resampled from 4H)
    # =====================================================================

    df_1d = _resample_ohlcv(df, "1D")
    df_1w = _resample_ohlcv(df, "1W")

    # --- Daily features ---
    feat_1d = pd.DataFrame(index=df_1d.index)
    feat_1d["returns_1d_1"] = df_1d["close"].pct_change(1)
    feat_1d["rsi_1d"] = _rsi(df_1d["close"], 14)
    ema12_1d = _ema(df_1d["close"], 12)
    ema26_1d = _ema(df_1d["close"], 26)
    macd_1d = ema12_1d - ema26_1d
    macd_sig_1d = _ema(macd_1d, 9)
    feat_1d["macd_diff_1d"] = macd_1d - macd_sig_1d
    sma20_1d = df_1d["close"].rolling(20).mean()
    feat_1d["price_to_sma20_1d"] = df_1d["close"] / sma20_1d
    _, dip_1d, dim_1d = _adx(df_1d["high"], df_1d["low"], df_1d["close"], 14)
    feat_1d["di_diff_1d"] = dip_1d - dim_1d

    # --- Weekly features ---
    feat_1w = pd.DataFrame(index=df_1w.index)
    feat_1w["returns_1w_1"] = df_1w["close"].pct_change(1)
    feat_1w["rsi_1w"] = _rsi(df_1w["close"], 14)
    sma20_1w = df_1w["close"].rolling(20).mean()
    feat_1w["price_to_sma20_1w"] = df_1w["close"] / sma20_1w

    # Forward-fill higher TF features to 4H index
    feat_1d = feat_1d.reindex(out.index, method="ffill")
    feat_1w = feat_1w.reindex(out.index, method="ffill")

    neutral_defaults = {
        "returns_1d_1": 0.0, "rsi_1d": 50.0, "macd_diff_1d": 0.0,
        "price_to_sma20_1d": 1.0, "di_diff_1d": 0.0,
        "returns_1w_1": 0.0, "rsi_1w": 50.0, "price_to_sma20_1w": 1.0,
    }
    for col in feat_1d.columns:
        out[col] = feat_1d[col].fillna(neutral_defaults.get(col, 0.0))
    for col in feat_1w.columns:
        out[col] = feat_1w[col].fillna(neutral_defaults.get(col, 0.0))

    # --- Trend alignment ---
    align_4h = (out["macd_diff"] > 0).astype(int) * 2 - 1
    align_1d = (out["macd_diff_1d"] > 0).astype(int) * 2 - 1
    align_1w = np.where(out["returns_1w_1"] > 0, 1, -1)
    out["trend_alignment"] = align_4h + align_1d + align_1w

    # --- Time features ---
    out["hour"] = out.index.hour
    out["day_of_week"] = out.index.dayofweek

    # Ensure column order
    return out[FEATURE_COLUMNS_4H]


def compute_4h_features_from_15m(df_15m: pd.DataFrame) -> pd.DataFrame:
    """Convenience: resample 15m bars to 4H, then compute features.
    
    Args:
        df_15m: DataFrame with 15m OHLCV bars and UTC datetime index.
    
    Returns:
        DataFrame with 4H features indexed at 4H bar timestamps.
    """
    df_4h = _resample_ohlcv(df_15m, "4h")
    return compute_4h_features(df_4h)


def latest_4h_row(df_4h: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Return a single-row DF with 4H features for the latest timestamp.

    Returns None if any required feature is NaN/inf (insufficient warmup).
    """
    feats = compute_4h_features(df_4h)
    row = feats.iloc[[-1]].astype(float)

    values = row.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return None

    return row
