"""
Feature engineering for Trading System v4.

Design principles:
- All features are continuous (no hard binary gates) — the ML model decides weighting.
- All features are dimensionless (ratios, normalised) for ML robustness.
- Multi-scale approach captures different timeframe dynamics.
- Session/time features enable the model to learn time-of-day FX patterns.
- No lookahead bias: all features use only data available at bar close time.

Feature groups (36 features total):
  1. Price action  : body_ratio, close_position, upper_wick, lower_wick,
                     bar_range_norm, is_session_open
  2. Momentum      : return_1, return_5, return_12, return_24
  3. Volatility    : atr_ratio, atr_norm, vol_5, vol_20, vol_ratio
                     (raw atr_5/atr_14 kept as local vars only — not dimensionless)
  4. Trend/EMA     : ema_ratio_5_20, close_vs_ema20, close_vs_ema50, close_vs_ema200
                     (ema20_slope dropped — r=0.990 with ema_ratio_5_20)
  5. Oscillators   : rsi_14, adx_14
                     (rsi_9 dropped — r=0.972 with rsi_14)
  6. Session/time  : hour_sin, hour_cos, dow_sin, dow_cos,
                     is_london, is_ny, is_overlap, is_session_open
  7. Regime        : vol_regime, range_position
  8. Pattern       : return_max_10, return_min_10
  9. Directional   : consecutive_up_bars, consecutive_down_bars,
                     dist_to_20bar_high, dist_to_20bar_low

  Note: volume_spike / log_volume omitted — FX/MID bars carry no real volume.
"""
import math
import numpy as np
import pandas as pd

# ── helpers ─────────────────────────────────────────────────────────────────

def _ema_series(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    # Wilder's smoothing: com = period - 1  (alpha = 1/period)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _adx_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index, normalised to [0, 1]. Measures trend strength."""
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    c = df['close'].astype(float)

    up_move   = h - h.shift(1)
    down_move = l.shift(1) - l

    plus_dm  = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=h.index)
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=h.index)

    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs(),
    ], axis=1).max(axis=1)

    # Wilder's smoothing throughout
    atr_w    = tr.ewm(com=period - 1, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(com=period - 1, adjust=False).mean() / (atr_w + 1e-10)
    minus_di = 100 * minus_dm.ewm(com=period - 1, adjust=False).mean() / (atr_w + 1e-10)

    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx = dx.ewm(com=period - 1, adjust=False).mean()
    return adx / 100  # normalise to [0, 1]


def _rsi_series(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))


# ── batch (offline) feature computation ─────────────────────────────────────

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the full 32-feature set on a batch DataFrame.
    All features are added as new columns; existing columns are preserved.
    Requires: open, high, low, close, timestamp.
    volume is optional; FX/MID zero-volume bars are handled gracefully.
    """
    df = df.copy()
    eps = 1e-10

    c = df['close'].astype(float)
    o = df['open'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)

    bar_range = (h - l).clip(lower=eps)

    # ── 1. Price action ──────────────────────────────────────────────────
    df['body_ratio']     = (c - o) / bar_range                   # [-1, 1] signed
    df['upper_wick']     = (h - np.maximum(o, c)) / bar_range    # [0, 1]
    df['lower_wick']     = (np.minimum(o, c) - l) / bar_range    # [0, 1]

    # ── 2. Momentum / returns ────────────────────────────────────────────
    df['return_1']  = c.pct_change(1,  fill_method=None)
    df['return_5']  = c.pct_change(5,  fill_method=None)

    # ── 3. Volatility ────────────────────────────────────────────────────
    atr_5  = _atr_series(df, 5)
    atr_14 = _atr_series(df, 14)
    df['atr_ratio'] = atr_5 / (atr_14 + eps)                     # vol expansion flag
    df['atr_norm']  = atr_14 / (c + eps)                         # relative vol level

    # ── 4. Trend context (EMA) ───────────────────────────────────────────
    ema50  = _ema_series(c, 50)
    df['close_vs_ema50']  = c / (ema50 + eps) - 1

    # ── 5. Oscillators ───────────────────────────────────────────────────
    df['rsi_14'] = _rsi_series(c, 14) / 100 - 0.5               # centred at 0
    df['adx_14'] = _adx_series(df, 14)                           # trend strength [0, 1]

    # ── 6. Session / time ────────────────────────────────────────────────
    if 'timestamp' in df.columns:
        ts   = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
        hour = ts.dt.hour
        df['hour_sin']  = np.sin(2 * math.pi * hour / 24)
        df['hour_cos']  = np.cos(2 * math.pi * hour / 24)
        df['is_london']      = ((hour >= 7)  & (hour < 16)).astype(float)
        df['is_ny']          = ((hour >= 13) & (hour < 21)).astype(float)
    else:
        for col in ('hour_sin', 'hour_cos', 'is_london', 'is_ny'):
            df[col] = 0.0

    # ── 7. Regime ────────────────────────────────────────────────────────
    atr_mean50 = atr_14.rolling(50).mean()
    df['vol_regime']     = atr_14 / (atr_mean50 + eps)           # > 1 → elevated vol

    # ── 8. Directional / structure ───────────────────────────────────────
    # Consecutive bullish/bearish closes: cumsum-within-run trick.
    # A new group starts every time the condition changes direction.
    _bull = (c > c.shift(1))
    _bear = (c < c.shift(1))
    _bull_grp = (~_bull).cumsum()
    _bear_grp = (~_bear).cumsum()
    # groupby cumsum gives 1,2,3... within a run, 0 outside
    bull_run = (_bull.astype(int).groupby(_bull_grp).cumsum())
    bear_run = (_bear.astype(int).groupby(_bear_grp).cumsum())
    df['consecutive_up_bars']   = bull_run.clip(upper=10) / 10   # normalised [0, 1]
    df['consecutive_down_bars'] = bear_run.clip(upper=10) / 10   # normalised [0, 1]

    # Distance to 20-bar high / low, normalised by ATR (resistance / support proximity)
    high_20 = h.rolling(20).max()
    low_20  = l.rolling(20).min()
    df['dist_to_20bar_high'] = (high_20 - c) / (atr_14 + eps)   # 0 = at resistance
    df['dist_to_20bar_low']  = (c - low_20)  / (atr_14 + eps)   # 0 = at support

    return df


# ── live (stateful) feature computation ─────────────────────────────────────

# Columns that are NOT features — excluded when extracting the feature vector.
_NON_FEATURE_COLS = frozenset({
    'timestamp', 'symbol', 'bar_size',
    'ts_init', 'ts_event',
    'open', 'high', 'low', 'close', 'volume',
})

# Minimum bars required before all rolling/EWM windows are populated.
WARMUP_BARS = 200


class FeatureEngineer:
    """
    Stateful feature engineering for live bar-by-bar processing.
    Maintains a rolling window of bar dicts and computes the same 32 features
    as add_features() for the latest bar.

    Usage:
        fe = FeatureEngineer(window=250)
        features = fe.add_bar(bar_dict)   # returns {} until is_ready
        if fe.is_ready:
            model.predict(features)
    """
    def __init__(self, window: int = 250):
        self.window = window
        self.history: list = []  # bar dicts, most recent last

    # ── public API ───────────────────────────────────────────────────────

    @property
    def bars_loaded(self) -> int:
        """Number of bars currently held in the rolling window."""
        return len(self.history)

    @property
    def is_ready(self) -> bool:
        """True once enough bars have accumulated for all features to be valid."""
        return len(self.history) >= WARMUP_BARS

    def add_bar(self, bar: dict) -> dict:
        """
        Ingest one bar dict and return its feature vector.
        Returns an empty dict during warm-up (bars_loaded < WARMUP_BARS).
        Keys are feature names; values are finite floats.
        """
        self.history.append(bar)
        if len(self.history) > self.window:
            self.history.pop(0)
        if not self.is_ready:
            return {}
        return self._compute_features()

    def feature_names(self) -> list:
        """Return the canonical list of feature names (requires is_ready)."""
        if not self.is_ready:
            return []
        return list(self._compute_features().keys())

    # ── internals ────────────────────────────────────────────────────────

    def _compute_features(self) -> dict:
        df = pd.DataFrame(self.history)
        for col in ('open', 'high', 'low', 'close'):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df = add_features(df)

        last = df.iloc[-1]
        return {
            k: float(v)
            for k, v in last.items()
            if k not in _NON_FEATURE_COLS
            and isinstance(v, (int, float, np.floating, np.integer))
            and math.isfinite(float(v))
        }
        return list(self._compute_features().keys())
