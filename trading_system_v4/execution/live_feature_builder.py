"""
live_feature_builder.py — Incremental Feature Builder for Live Tick Bars

Bridges the gap between LiveTickAggregator (raw bar dicts) and V4ModelInference
(flat feature dicts).  Mirrors the exact feature engineering in meta_labeling_mfe.py
so the live distribution matches the training distribution.

Architecture:
  LiveTickAggregator  →  LiveFeatureBuilder.push_bar()  →  V4ModelInference

For every completed tick bar:
  1. Updates incremental state (ATR, RSI, rolling windows).
  2. Detects Breakouts (the base strategy signal).
  3. If a breakout occurred, computes the full feature dict and returns it.
  4. Returns (0, None) on every non-breakout bar (nothing to trade).

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

import numpy as np


# ── constants matching meta_labeling_mfe.py ───────────────────────────────────
_ATR_COM   = 13   # com = period - 1 → alpha = 1/14
_RSI_COM   = 13
_SMA_WIN   = 5    # window for tick_velocity_sma5, spread_sma5, etc.
_LOOKBACK  = 10   # window for roll_high, roll_low, vel_sma

# Minimum bars processed before breakouts are reported.
_WARMUP_BARS_MIN = 20


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
        warmup_bars: int = _WARMUP_BARS_MIN,
    ) -> None:
        self.WARMUP   = warmup_bars

        self._k_atr:  float = 1.0 / (_ATR_COM + 1)   # = 1/14
        self._k_rsi:  float = 1.0 / (_RSI_COM + 1)

        # ATR / RSI state
        self._atr: Optional[float] = None
        self._atr_history: deque[float] = deque(maxlen=50)
        self._rsi_gain: Optional[float] = None
        self._rsi_loss: Optional[float] = None
        self._prev_close: Optional[float] = None

        # Rolling history (deque capped at 100 bars — no memory leak)
        self._bars: deque[dict] = deque(maxlen=100)
        self._bar_count: int = 0

    @property
    def warmed_up(self) -> bool:
        return self._bar_count >= self.WARMUP

    @property
    def bar_count(self) -> int:
        return self._bar_count

    # ── public API ────────────────────────────────────────────────────────────

    def push_bar(self, bar: dict) -> tuple[int, Optional[dict]]:
        """
        Process one completed tick bar.

        Returns:
            (signal, features) where:
              signal   +1 (long breakout) | -1 (short breakout) | 0 (no event)
              features  flat feature dict for V4ModelInference, or None
        """
        self._bars.append(bar)
        self._bar_count += 1

        close = float(bar["close"])
        high  = float(bar["high"])
        low   = float(bar["low"])

        # ── step 1: update ATR ────────────────────────────────────────────────
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
        self._atr_history.append(self._atr)

        # ── step 2: update RSI ────────────────────────────────────────────────
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

        # ── step 3: still in warmup → no signals ─────────────────────────────
        if not self.warmed_up:
            return 0, None

        # ── step 4: detect breakout ───────────────────────────────────────────
        # We need the previous 10 bars (excluding the current one)
        prev_10_bars = list(self._bars)[-_LOOKBACK-1:-1]
        
        roll_high = max(float(b["high"]) for b in prev_10_bars)
        roll_low  = min(float(b["low"]) for b in prev_10_bars)
        vel_sma   = sum(float(b["tick_velocity"]) for b in prev_10_bars) / _LOOKBACK

        tick_velocity = float(bar["tick_velocity"])
        vol_imbalance = float(bar["vol_imbalance"])

        signal = 0
        if close > roll_high and tick_velocity > vel_sma * 1.2 and vol_imbalance > 0:
            signal = 1
        elif close < roll_low and tick_velocity > vel_sma * 1.2 and vol_imbalance < 0:
            signal = -1

        if signal == 0:
            return 0, None

        # ── step 5: compute full feature dict ─────────────────────────────────
        features = self._build_features(bar, signal)
        return signal, features

    def _build_features(self, bar: dict, signal: int) -> dict:
        """
        Constructs the exact feature dictionary expected by the XGBoost model.
        Must match the columns in meta_labeling_mfe.py exactly.
        """
        # Time features
        ts = bar["timestamp"]
        if not isinstance(ts, datetime):
            import pandas as pd
            ts = pd.to_datetime(ts, utc=True).to_pydatetime()

        hour = ts.hour
        hour_sin = math.sin(2 * math.pi * hour / 24)
        hour_cos = math.cos(2 * math.pi * hour / 24)
        is_london = 1.0 if 7 <= hour < 16 else 0.0
        is_ny     = 1.0 if 13 <= hour < 21 else 0.0

        # Oscillators & Volatility
        rs = (self._rsi_gain or 0.0) / ((self._rsi_loss or 0.0) + 1e-10)
        rsi_14 = (100.0 - (100.0 / (1.0 + rs))) / 100.0
        
        close = float(bar["close"])
        atr_norm = (self._atr or 0.0) / close

        # Rolling SMA5 features (includes current bar)
        last_5 = list(self._bars)[-_SMA_WIN:]
        tick_velocity_sma5 = sum(float(b["tick_velocity"]) for b in last_5) / _SMA_WIN
        spread_sma5        = sum(float(b["avg_spread"]) for b in last_5) / _SMA_WIN
        vol_imbalance_sma5 = sum(float(b["vol_imbalance"]) for b in last_5) / _SMA_WIN
        buy_ratio_sma5     = sum(float(b["buy_ratio"]) for b in last_5) / _SMA_WIN

        # Microstructure
        tick_velocity = float(bar["tick_velocity"])
        avg_spread    = float(bar["avg_spread"])
        max_spread    = float(bar["max_spread"])
        buy_ratio     = float(bar["buy_ratio"])

        tick_velocity_ratio = tick_velocity / (tick_velocity_sma5 + 1e-6)
        spread_ratio        = avg_spread / (spread_sma5 + 1e-6)
        liquidity_shock     = max_spread / (avg_spread + 1e-6)
        order_flow_toxicity = buy_ratio - buy_ratio_sma5

        # Micro trend alignment
        if tick_velocity_ratio > 1.0 and spread_ratio < 1.0:
            micro_trend_alignment = 1.0
        elif tick_velocity_ratio < 1.0 and spread_ratio > 1.0:
            micro_trend_alignment = -1.0
        else:
            micro_trend_alignment = 0.0

        # Price vol divergence
        if signal == 1 and vol_imbalance_sma5 < 0:
            price_vol_divergence = 1.0
        elif signal == -1 and vol_imbalance_sma5 > 0:
            price_vol_divergence = 1.0
        else:
            price_vol_divergence = 0.0

        # Macro Context Features
        bars_list = list(self._bars)
        
        # Price Momentum
        close_10_ago = float(bars_list[-11]["close"]) if len(bars_list) > 10 else close
        close_50_ago = float(bars_list[-51]["close"]) if len(bars_list) > 50 else close
        ret_10 = (close / close_10_ago) - 1.0 if close_10_ago > 0 else 0.0
        ret_50 = (close / close_50_ago) - 1.0 if close_50_ago > 0 else 0.0
        
        # Distance to recent highs/lows
        prev_10_bars = bars_list[-11:-1] if len(bars_list) > 10 else bars_list[:-1]
        prev_50_bars = bars_list[-51:-1] if len(bars_list) > 50 else bars_list[:-1]
        
        roll_high_10 = max((float(b["high"]) for b in prev_10_bars), default=close)
        roll_low_10  = min((float(b["low"]) for b in prev_10_bars), default=close)
        roll_high_50 = max((float(b["high"]) for b in prev_50_bars), default=close)
        roll_low_50  = min((float(b["low"]) for b in prev_50_bars), default=close)
        
        atr_val = self._atr or 0.0
        dist_to_high_10 = (close - roll_high_10) / (atr_val + 1e-8)
        dist_to_low_10  = (close - roll_low_10) / (atr_val + 1e-8)
        dist_to_high_50 = (close - roll_high_50) / (atr_val + 1e-8)
        dist_to_low_50  = (close - roll_low_50) / (atr_val + 1e-8)
        
        # Volatility Regime & Macro Order Flow
        last_50 = bars_list[-50:] if len(bars_list) >= 50 else bars_list
        vol_imbalance_sma50 = sum(float(b["vol_imbalance"]) for b in last_50) / len(last_50)
        
        atr_sma50 = sum(self._atr_history) / len(self._atr_history) if self._atr_history else atr_val
        volatility_regime = atr_val / (atr_sma50 + 1e-8)

        # Candle/path-shape and microstructure quality
        open_px = float(bar["open"])
        high_px = float(bar["high"])
        low_px = float(bar["low"])
        bar_range = max(high_px - low_px, 1e-8)

        bar_range_norm = bar_range / (close + 1e-8)
        body_ratio = abs(close - open_px) / bar_range
        upper_wick_ratio = (high_px - max(open_px, close)) / bar_range
        lower_wick_ratio = (min(open_px, close) - low_px) / bar_range

        prev_10_full = bars_list[-10:] if len(bars_list) >= 10 else bars_list
        range_sma10 = (
            sum(max(float(b["high"]) - float(b["low"]), 1e-8) for b in prev_10_full) / max(len(prev_10_full), 1)
        )
        range_ratio = bar_range / (range_sma10 + 1e-8)
        spread_to_range = avg_spread / (bar_range + 1e-8)

        prev_bar = bars_list[-2] if len(bars_list) >= 2 else bar
        vol_imbalance_chg1 = float(bar["vol_imbalance"]) - float(prev_bar["vol_imbalance"])
        buy_ratio_chg1 = float(bar["buy_ratio"]) - float(prev_bar["buy_ratio"])

        prev_20 = bars_list[-20:] if len(bars_list) >= 20 else bars_list
        tv_vals = np.array([float(b["tick_velocity"]) for b in prev_20], dtype=np.float64)
        tv_mean = float(tv_vals.mean()) if len(tv_vals) else tick_velocity
        tv_std = float(tv_vals.std()) if len(tv_vals) else 0.0
        tick_velocity_z20 = (tick_velocity - tv_mean) / (tv_std + 1e-8)

        breakout_distance_atr = 0.0
        if signal == 1:
            breakout_distance_atr = (close - roll_high_10) / (atr_val + 1e-8)
        elif signal == -1:
            breakout_distance_atr = (roll_low_10 - close) / (atr_val + 1e-8)

        return {
            "atr": atr_val,
            "hour_sin": hour_sin,
            "hour_cos": hour_cos,
            "is_london": is_london,
            "is_ny": is_ny,
            "rsi_14": rsi_14,
            "atr_norm": atr_norm,
            "tick_velocity_sma5": tick_velocity_sma5,
            "tick_velocity_ratio": tick_velocity_ratio,
            "spread_sma5": spread_sma5,
            "spread_ratio": spread_ratio,
            "liquidity_shock": liquidity_shock,
            "vol_imbalance_sma5": vol_imbalance_sma5,
            "buy_ratio_sma5": buy_ratio_sma5,
            "order_flow_toxicity": order_flow_toxicity,
            "micro_trend_alignment": micro_trend_alignment,
            "price_vol_divergence": price_vol_divergence,
            "ret_10": ret_10,
            "ret_50": ret_50,
            "dist_to_high_10": dist_to_high_10,
            "dist_to_low_10": dist_to_low_10,
            "dist_to_high_50": dist_to_high_50,
            "dist_to_low_50": dist_to_low_50,
            "atr_sma50": atr_sma50,
            "volatility_regime": volatility_regime,
            "vol_imbalance_sma50": vol_imbalance_sma50,
            "bar_range_norm": bar_range_norm,
            "body_ratio": body_ratio,
            "upper_wick_ratio": upper_wick_ratio,
            "lower_wick_ratio": lower_wick_ratio,
            "range_sma10": range_sma10,
            "range_ratio": range_ratio,
            "spread_to_range": spread_to_range,
            "vol_imbalance_chg1": vol_imbalance_chg1,
            "buy_ratio_chg1": buy_ratio_chg1,
            "tick_velocity_z20": tick_velocity_z20,
            "breakout_distance_atr": breakout_distance_atr,
            "tick_velocity": tick_velocity,
            "avg_spread": avg_spread,
            "max_spread": max_spread,
            "vol_imbalance": float(bar["vol_imbalance"]),
            "buy_volume": float(bar.get("buy_volume", 0.0)),
            "sell_volume": float(bar.get("sell_volume", 0.0)),
            "total_volume": float(bar.get("total_volume", 0.0)),
            "buy_ratio": buy_ratio,
        }
