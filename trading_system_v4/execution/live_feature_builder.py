"""
live_feature_builder.py — Incremental Feature Builder for Live Tick Bars

Bridges the gap between LiveTickAggregator (raw bar dicts) and V4ModelInference
(flat feature dicts).  Mirrors the exact feature engineering in meta_labeling_ema.py
so the live distribution matches the training distribution.

Architecture:
  LiveTickAggregator  →  LiveFeatureBuilder.push_bar()  →  V4ModelInference

For every completed tick bar:
  1. Updates incremental EMA-fast / EMA-slow state.
  2. Detects EMA crossovers (the base strategy signal).
  3. If a crossover occurred, computes the full feature dict and returns it.
  4. Returns (0, None) on every non-crossover bar (nothing to trade).

EMA / ATR / RSI all use the same formula as meta_labeling_ema.py:
  EWM with adjust=False, so:  new = alpha * value + (1 - alpha) * prev
  where alpha = 2/(span+1) for EMA, and alpha = 1/period for ATR/RSI (com=period-1).

Usage:
  builder = LiveFeatureBuilder()
  ...
  signal, features = builder.push_bar(bar_dict)
  if signal != 0 and features is not None:
      should_trade, prob = inference.should_trade(features)
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from typing import Optional


# ── constants matching meta_labeling_ema.py ───────────────────────────────────
_EMA_FAST  = 20
_EMA_SLOW  = 50
_ATR_COM   = 13   # com = period - 1 → alpha = 1/14
_RSI_COM   = 13
_SMA_WIN   = 5    # window for tick_velocity_sma5, spread_sma5, etc.

# Minimum bars processed before crossovers are reported.
# Need EMA_SLOW warmup + SMA5 + a few extra to stabilise ATR/RSI.
_WARMUP_BARS_MIN = _EMA_SLOW + 20   # 70


class LiveFeatureBuilder:
    """
    Stateful, incremental feature engine for live 1000-tick bars.

    Call ``push_bar(bar_dict)`` on every completed bar from LiveTickAggregator.
    The bar dict must contain the keys emitted by LiveTickAggregator._emit_bar():
      timestamp, open, high, low, close, avg_spread, max_spread,
      vol_imbalance, buy_volume, sell_volume, total_volume,
      buy_ratio, tick_velocity
    """

    def __init__(
        self,
        ema_fast: int = _EMA_FAST,
        ema_slow: int = _EMA_SLOW,
        warmup_bars: int = _WARMUP_BARS_MIN,
    ) -> None:
        self.EMA_FAST = ema_fast
        self.EMA_SLOW = ema_slow
        self.WARMUP   = warmup_bars

        self._k_fast: float = 2.0 / (ema_fast + 1)
        self._k_slow: float = 2.0 / (ema_slow + 1)
        self._k_atr:  float = 1.0 / (_ATR_COM + 1)   # = 1/14
        self._k_rsi:  float = 1.0 / (_RSI_COM + 1)

        # EMA state
        self._ema_fast: Optional[float] = None
        self._ema_slow: Optional[float] = None
        self._prev_ema_fast: Optional[float] = None
        self._prev_ema_slow: Optional[float] = None

        # ATR / RSI state
        self._atr: Optional[float] = None
        self._rsi_gain: Optional[float] = None
        self._rsi_loss: Optional[float] = None
        self._prev_close: Optional[float] = None

        # Rolling history (deque capped at 100 bars — no memory leak)
        self._bars: deque[dict] = deque(maxlen=100)
        self._bar_count: int = 0

    # ── public API ────────────────────────────────────────────────────────────

    def push_bar(self, bar: dict) -> tuple[int, Optional[dict]]:
        """
        Process one completed tick bar.

        Returns:
            (signal, features) where:
              signal   +1 (bull cross) | -1 (bear cross) | 0 (no event)
              features  flat feature dict for V4ModelInference, or None
        """
        self._bars.append(bar)
        self._bar_count += 1

        close = float(bar["close"])
        high  = float(bar["high"])
        low   = float(bar["low"])

        # ── step 1: save prev EMA before updating ────────────────────────────
        self._prev_ema_fast = self._ema_fast
        self._prev_ema_slow = self._ema_slow

        # ── step 2: update EMA ────────────────────────────────────────────────
        if self._ema_fast is None:
            self._ema_fast = close
            self._ema_slow = close
        else:
            self._ema_fast = close * self._k_fast + self._ema_fast * (1.0 - self._k_fast)
            self._ema_slow = close * self._k_slow + self._ema_slow * (1.0 - self._k_slow)

        # ── step 3: update ATR ────────────────────────────────────────────────
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(
                high - low,
                abs(high - self._prev_close),
                abs(low  - self._prev_close),
            )
        if self._atr is None:
            self._atr = tr
        else:
            self._atr = tr * self._k_atr + self._atr * (1.0 - self._k_atr)

        # ── step 4: update RSI ────────────────────────────────────────────────
        if self._prev_close is not None:
            delta = close - self._prev_close
            gain  = max(delta,  0.0)
            loss  = max(-delta, 0.0)
            if self._rsi_gain is None:
                self._rsi_gain = gain
                self._rsi_loss = loss
            else:
                self._rsi_gain = gain * self._k_rsi + self._rsi_gain * (1.0 - self._k_rsi)
                self._rsi_loss = loss * self._k_rsi + self._rsi_loss * (1.0 - self._k_rsi)

        self._prev_close = close

        # ── step 5: still in warmup → no signals ─────────────────────────────
        if self._bar_count < self.WARMUP or self._prev_ema_fast is None:
            return 0, None

        # ── step 6: detect EMA crossover ──────────────────────────────────────
        bull_cross = (
            self._ema_fast >  self._ema_slow and
            self._prev_ema_fast <= self._prev_ema_slow
        )
        bear_cross = (
            self._ema_fast <  self._ema_slow and
            self._prev_ema_fast >= self._prev_ema_slow
        )

        if not (bull_cross or bear_cross):
            return 0, None

        signal = 1 if bull_cross else -1
        features = self._compute_features(bar, signal)
        return signal, features

    @property
    def bar_count(self) -> int:
        return self._bar_count

    @property
    def warmed_up(self) -> bool:
        return self._bar_count >= self.WARMUP

    # ── internal feature computation ──────────────────────────────────────────

    def _compute_features(self, bar: dict, signal: int) -> dict:
        """
        Build the flat feature dict that V4ModelInference expects.
        Mirrors meta_labeling_ema.py feature logic exactly.
        """
        # ── raw bar scalars ───────────────────────────────────────────────────
        tick_velocity = float(bar["tick_velocity"])
        avg_spread    = float(bar["avg_spread"])
        max_spread    = float(bar["max_spread"])
        vol_imbalance = float(bar["vol_imbalance"])
        buy_volume    = float(bar.get("buy_volume",  0.0))
        sell_volume   = float(bar.get("sell_volume", 0.0))
        total_volume  = float(bar.get("total_volume", 0.0))
        buy_ratio     = float(bar["buy_ratio"])
        close         = float(bar["close"])

        # ── time features ─────────────────────────────────────────────────────
        ts = bar["timestamp"]
        if not isinstance(ts, datetime):
            # Handle pandas Timestamp, ISO strings, etc.
            import pandas as pd
            ts = pd.to_datetime(ts, utc=True).to_pydatetime()

        hour = ts.hour
        hour_sin  = math.sin(2 * math.pi * hour / 24)
        hour_cos  = math.cos(2 * math.pi * hour / 24)
        is_london = float(7 <= hour < 16)
        is_ny     = float(13 <= hour < 21)

        # ── ATR-normalised volatility ─────────────────────────────────────────
        atr_val  = self._atr if self._atr is not None else 1e-8
        atr_norm = atr_val / (close + 1e-8)

        # ── RSI ───────────────────────────────────────────────────────────────
        rsi_gain = self._rsi_gain if self._rsi_gain is not None else 0.0
        rsi_loss = self._rsi_loss if self._rsi_loss is not None else 1e-8
        rs       = rsi_gain / (rsi_loss + 1e-10)
        rsi_14   = (100.0 - (100.0 / (1.0 + rs))) / 100.0

        # ── rolling SMA5 (uses deque snapshot) ───────────────────────────────
        bars_list = list(self._bars)
        recent    = bars_list[-_SMA_WIN:] if len(bars_list) >= _SMA_WIN else bars_list
        n = len(recent)  # ≥ 1 always

        vel_sma5  = sum(float(b["tick_velocity"]) for b in recent) / n
        spread_sma5   = sum(float(b["avg_spread"])    for b in recent) / n
        vol_imb_sma5  = sum(float(b["vol_imbalance"]) for b in recent) / n
        buy_ratio_sma5 = sum(float(b["buy_ratio"])    for b in recent) / n

        tick_velocity_ratio = tick_velocity  / (vel_sma5    + 1e-6)
        spread_ratio        = avg_spread     / (spread_sma5 + 1e-6)
        liquidity_shock     = max_spread     / (avg_spread  + 1e-6)
        order_flow_toxicity = buy_ratio - buy_ratio_sma5

        # ── micro-structural composite features ───────────────────────────────
        if tick_velocity_ratio > 1.0 and spread_ratio < 1.0:
            micro_trend_alignment = 1.0
        elif tick_velocity_ratio < 1.0 and spread_ratio > 1.0:
            micro_trend_alignment = -1.0
        else:
            micro_trend_alignment = 0.0

        if (signal == 1 and vol_imb_sma5 < 0) or (signal == -1 and vol_imb_sma5 > 0):
            price_vol_divergence = 1.0
        else:
            price_vol_divergence = 0.0

        return {
            # ── raw bar ──────────────────────────────────────────────────────
            "tick_velocity":         tick_velocity,
            "avg_spread":            avg_spread,
            "max_spread":            max_spread,
            "vol_imbalance":         vol_imbalance,
            "buy_volume":            buy_volume,
            "sell_volume":           sell_volume,
            "total_volume":          total_volume,
            "buy_ratio":             buy_ratio,
            # ── time ─────────────────────────────────────────────────────────
            "hour_sin":              hour_sin,
            "hour_cos":              hour_cos,
            "is_london":             is_london,
            "is_ny":                 is_ny,
            # ── oscillators ──────────────────────────────────────────────────
            "rsi_14":                rsi_14,
            "atr_norm":              atr_norm,
            # ── rolling / SMA-derived ────────────────────────────────────────
            "tick_velocity_sma5":    vel_sma5,
            "tick_velocity_ratio":   tick_velocity_ratio,
            "spread_sma5":           spread_sma5,
            "spread_ratio":          spread_ratio,
            "liquidity_shock":       liquidity_shock,
            "vol_imbalance_sma5":    vol_imb_sma5,
            "buy_ratio_sma5":        buy_ratio_sma5,
            "order_flow_toxicity":   order_flow_toxicity,
            # ── composite ────────────────────────────────────────────────────
            "micro_trend_alignment": micro_trend_alignment,
            "price_vol_divergence":  price_vol_divergence,
        }
