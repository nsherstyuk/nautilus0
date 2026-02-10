"""V3 feature engineering with directional predictive power.

Key improvements over V2 RF40:
- Multi-timeframe trend context (resampled 1H, 4H from 15m bars)
- Signed directional features (not just magnitude)
- Trend alignment across timeframes
- Mean-reversion signals (stochastic, BB z-score)
- Microstructure proxies (close position, consecutive bars, range expansion)
- MAMA/FAMA as a feature (was only a meta-filter before)

Designed for 15-minute OHLCV input with UTC datetime index.
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


def _stochastic_k(high: pd.Series, low: pd.Series, close: pd.Series,
                   length: int = 14) -> pd.Series:
    lowest = low.rolling(length).min()
    highest = high.rolling(length).max()
    span = highest - lowest
    return np.where(span > 0, 100.0 * (close - lowest) / span, 50.0)


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


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _mama_fama(close: pd.Series, fast: float = 0.5, slow: float = 0.05) -> tuple[pd.Series, pd.Series]:
    """Simplified MAMA/FAMA approximation using adaptive EMA."""
    mama = close.ewm(alpha=fast, adjust=False).mean()
    fama = mama.ewm(alpha=slow, adjust=False).mean()
    return mama, fama


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 15m OHLCV to a higher timeframe."""
    resampled = df.resample(rule).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna()
    return resampled


FEATURE_COLUMNS_V3: list[str] = [
    # --- Signed directional momentum (15m) ---
    "returns_1",
    "returns_4",
    "returns_8",
    "returns_16",
    "returns_32",
    "log_returns_1",
    # --- Trend indicators (15m) ---
    "macd",
    "macd_signal",
    "macd_diff",
    "macd_diff_slope",       # Is MACD histogram expanding or contracting?
    "ema_12_slope",          # Signed slope of fast EMA
    "ema_26_slope",          # Signed slope of slow EMA
    "price_to_sma_20",
    "price_to_sma_50",
    "sma_20_slope",          # Is SMA20 rising or falling?
    "sma_50_slope",          # Is SMA50 rising or falling?
    # --- MAMA/FAMA (15m) ---
    "mama_diff",             # MAMA - FAMA normalized by close (directional)
    "mama_diff_slope",       # Is MAMA diff expanding?
    # --- DMI / ADX (15m) ---
    "adx",
    "di_plus",
    "di_minus",
    "di_diff",               # DI+ minus DI- (signed directional)
    # --- Mean reversion (15m) ---
    "rsi",
    "rsi_slope",             # RSI momentum
    "stoch_k",
    "bb_position",
    "bb_zscore",             # How many std devs from BB middle
    # --- Volatility context (keep useful ones) ---
    "atr_pct",
    "volatility",
    "atr_expansion",         # Current ATR vs ATR(50) — regime change detection
    # --- Microstructure proxies (15m) ---
    "close_position",        # Where close sits in bar range (buying/selling pressure)
    "signed_body",           # Signed candle body (positive = bullish)
    "consec_up",             # Consecutive up-close bars
    "consec_down",           # Consecutive down-close bars
    "range_expansion",       # Current bar range vs average (breakout detection)
    # --- Multi-timeframe trend (resampled from 15m) ---
    "returns_1h_4",          # 1H: 4-bar (4 hour) return
    "rsi_1h",                # 1H RSI
    "macd_diff_1h",          # 1H MACD histogram
    "price_to_sma20_1h",    # 1H price relative to SMA20
    "di_diff_1h",            # 1H DI+ minus DI-
    "returns_4h_4",          # 4H: 4-bar (16 hour) return
    "rsi_4h",                # 4H RSI
    "macd_diff_4h",          # 4H MACD histogram
    "price_to_sma20_4h",    # 4H price relative to SMA20
    # --- Trend alignment ---
    "trend_alignment",       # How many TFs agree on direction (-3 to +3)
    # --- Time features ---
    "hour",
    "day_of_week",
    "is_london_session",
    "is_ny_session",
    "is_overlap",
]


def compute_v3_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute V3 features from 15m OHLCV DataFrame with UTC datetime index.

    Requires ~200 bars of warmup for the highest-timeframe features.
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    out = pd.DataFrame(index=df.index)

    # =====================================================================
    # 15-MINUTE FEATURES
    # =====================================================================

    # --- Signed directional momentum ---
    out["returns_1"] = df["close"].pct_change(1)
    out["returns_4"] = df["close"].pct_change(4)
    out["returns_8"] = df["close"].pct_change(8)
    out["returns_16"] = df["close"].pct_change(16)
    out["returns_32"] = df["close"].pct_change(32)
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
    out["macd_diff_slope"] = macd_diff.diff(3)  # 3-bar change in histogram
    out["ema_12_slope"] = ema12.pct_change(4)
    out["ema_26_slope"] = ema26.pct_change(4)

    sma20 = df["close"].rolling(20).mean()
    sma50 = df["close"].rolling(50).mean()
    out["price_to_sma_20"] = df["close"] / sma20
    out["price_to_sma_50"] = df["close"] / sma50
    out["sma_20_slope"] = sma20.pct_change(4)
    out["sma_50_slope"] = sma50.pct_change(8)

    # --- MAMA/FAMA ---
    mama, fama = _mama_fama(df["close"])
    mama_diff = (mama - fama) / df["close"]
    out["mama_diff"] = mama_diff
    out["mama_diff_slope"] = mama_diff.diff(4)

    # --- DMI / ADX ---
    adx, di_plus, di_minus = _adx(df["high"], df["low"], df["close"], 14)
    out["adx"] = adx
    out["di_plus"] = di_plus
    out["di_minus"] = di_minus
    out["di_diff"] = di_plus - di_minus  # Signed: positive = bullish

    # --- Mean reversion ---
    rsi = _rsi(df["close"], 14)
    out["rsi"] = rsi
    out["rsi_slope"] = rsi.diff(4)
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

    # Consecutive up/down bars (vectorized)
    up = (df["close"] > df["close"].shift(1)).astype(int)
    down = (df["close"] < df["close"].shift(1)).astype(int)
    # Group consecutive runs and cumcount within each group
    up_groups = (up != up.shift()).cumsum()
    down_groups = (down != down.shift()).cumsum()
    consec_up = up.groupby(up_groups).cumsum()
    consec_down = down.groupby(down_groups).cumsum()
    out["consec_up"] = consec_up.astype(float)
    out["consec_down"] = consec_down.astype(float)

    avg_range = hl_range.rolling(20).mean()
    out["range_expansion"] = np.where(avg_range > 0, hl_range / avg_range, 1.0)

    # =====================================================================
    # MULTI-TIMEFRAME FEATURES (resampled from 15m)
    # =====================================================================

    # Resample to 1H and 4H
    df_1h = _resample_ohlcv(df, "1h")
    df_4h = _resample_ohlcv(df, "4h")

    # --- 1H features ---
    feat_1h = pd.DataFrame(index=df_1h.index)
    feat_1h["returns_1h_4"] = df_1h["close"].pct_change(4)
    feat_1h["rsi_1h"] = _rsi(df_1h["close"], 14)
    ema12_1h = _ema(df_1h["close"], 12)
    ema26_1h = _ema(df_1h["close"], 26)
    macd_1h = ema12_1h - ema26_1h
    macd_sig_1h = _ema(macd_1h, 9)
    feat_1h["macd_diff_1h"] = macd_1h - macd_sig_1h
    sma20_1h = df_1h["close"].rolling(20).mean()
    feat_1h["price_to_sma20_1h"] = df_1h["close"] / sma20_1h
    _, dip_1h, dim_1h = _adx(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    feat_1h["di_diff_1h"] = dip_1h - dim_1h

    # --- 4H features ---
    feat_4h = pd.DataFrame(index=df_4h.index)
    feat_4h["returns_4h_4"] = df_4h["close"].pct_change(4)
    feat_4h["rsi_4h"] = _rsi(df_4h["close"], 14)
    ema12_4h = _ema(df_4h["close"], 12)
    ema26_4h = _ema(df_4h["close"], 26)
    macd_4h = ema12_4h - ema26_4h
    macd_sig_4h = _ema(macd_4h, 9)
    feat_4h["macd_diff_4h"] = macd_4h - macd_sig_4h
    sma20_4h = df_4h["close"].rolling(20).mean()
    feat_4h["price_to_sma20_4h"] = df_4h["close"] / sma20_4h

    # Forward-fill higher TF features to 15m index
    feat_1h = feat_1h.reindex(out.index, method="ffill")
    feat_4h = feat_4h.reindex(out.index, method="ffill")

    # Fill remaining NaN with neutral defaults (edge cases after weekends)
    neutral_defaults = {
        "returns_1h_4": 0.0, "rsi_1h": 50.0, "macd_diff_1h": 0.0,
        "price_to_sma20_1h": 1.0, "di_diff_1h": 0.0,
        "returns_4h_4": 0.0, "rsi_4h": 50.0, "macd_diff_4h": 0.0,
        "price_to_sma20_4h": 1.0,
    }
    for col in feat_1h.columns:
        out[col] = feat_1h[col].fillna(neutral_defaults.get(col, 0.0))
    for col in feat_4h.columns:
        out[col] = feat_4h[col].fillna(neutral_defaults.get(col, 0.0))

    # --- Trend alignment ---
    # Count how many timeframes agree on bullish direction
    # 15m: MACD diff > 0, 1H: MACD diff > 0, 4H: MACD diff > 0
    align_15m = (out["macd_diff"] > 0).astype(int) * 2 - 1   # +1 or -1
    align_1h = (out["macd_diff_1h"] > 0).astype(int) * 2 - 1
    align_4h = (out["macd_diff_4h"] > 0).astype(int) * 2 - 1
    out["trend_alignment"] = align_15m + align_1h + align_4h  # Range: -3 to +3

    # --- Time features ---
    out["hour"] = out.index.hour
    out["day_of_week"] = out.index.dayofweek
    out["is_london_session"] = ((out["hour"] >= 8) & (out["hour"] < 16)).astype(int)
    out["is_ny_session"] = ((out["hour"] >= 13) & (out["hour"] < 21)).astype(int)
    out["is_overlap"] = ((out["hour"] >= 13) & (out["hour"] < 16)).astype(int)

    # Ensure column order
    return out[FEATURE_COLUMNS_V3]


def latest_v3_row(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Return a single-row DF with V3 features for the latest timestamp.

    Returns None if any required feature is NaN/inf (insufficient warmup).
    """
    feats = compute_v3_features(df)
    row = feats.iloc[[-1]].astype(float)

    values = row.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return None

    return row
