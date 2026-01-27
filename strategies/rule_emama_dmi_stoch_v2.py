"""Rule-based V2 strategy: EMAMA/MAMA crossover + DMI (15m/30m) + Stoch(15m).

Goal: keep the existing V2 ML strategy intact, but allow experimenting with a
formalized indicator rule-set while reusing the *same* order submission and
ATR-based SL/TP logic from MLSignalStrategyV2.

Notes:
- "EMAMA" on TradingView here appears to match MAMA/FAMA style parameters
  (fast/slow limits). We implement this with `pandas_ta.mama`.
- No lookahead: signals are evaluated on the most recently completed bar.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import pandas_ta as ta

from nautilus_trader.model.data import Bar

from strategies.ml_strategy_mtf_v2 import MLSignalStrategyV2, MLSignalStrategyV2Config


class RuleEmamaDmiStochV2Config(MLSignalStrategyV2Config, kw_only=True):
    # MAMA ("EMAMA"-like) parameters
    mama_fast: float = 0.30
    mama_slow: float = 0.05

    # DMI parameters
    dmi_length_15m: int = 14
    dmi_length_30m: int = 14

    # Stochastic parameters (15m)
    stoch_k: int = 14
    stoch_d: int = 3
    stoch_smooth_k: int = 3

    # "Not too high/low" filters
    stoch_max_for_long: float = 80.0
    stoch_min_for_short: float = 20.0

    # Optional trend-strength filter (0 disables)
    adx_min_30m: float = 0.0


class RuleEmamaDmiStochV2(MLSignalStrategyV2):
    """V2 strategy using deterministic indicator rules instead of ML."""

    def __init__(self, config: RuleEmamaDmiStochV2Config):
        self._rule_cfg = config
        super().__init__(config)

    def _load_model(self) -> None:  # override
        # Rule-based strategy: no model file needed.
        self.model = None

    def _build_df_15m(self) -> pd.DataFrame:
        data = {
            "open": [float(b.open) for b in self.bars_buffer_15m],
            "high": [float(b.high) for b in self.bars_buffer_15m],
            "low": [float(b.low) for b in self.bars_buffer_15m],
            "close": [float(b.close) for b in self.bars_buffer_15m],
            "volume": [float(getattr(b, "volume", 0.0)) for b in self.bars_buffer_15m],
            "timestamp": [pd.Timestamp(b.ts_init, unit="ns", tz="UTC") for b in self.bars_buffer_15m],
        }
        df = pd.DataFrame(data)
        df.set_index("timestamp", inplace=True)
        return df.loc[~df.index.duplicated(keep="first")]

    def _build_df_30m(self) -> pd.DataFrame:
        data = {
            "high": [float(b.high) for b in self.bars_buffer_30m],
            "low": [float(b.low) for b in self.bars_buffer_30m],
            "close": [float(b.close) for b in self.bars_buffer_30m],
            "timestamp": [pd.Timestamp(b.ts_init, unit="ns", tz="UTC") for b in self.bars_buffer_30m],
        }
        df = pd.DataFrame(data)
        df.set_index("timestamp", inplace=True)
        return df.loc[~df.index.duplicated(keep="first")]

    def _compute_rule_signal(self) -> tuple[Optional[str], Optional[np.ndarray], float]:
        """Returns (direction, features10, confidence)."""
        if len(self.bars_buffer_15m) < self._min_warmup_bars_15m:
            return None, None, 0.0
        if len(self.bars_buffer_30m) < self._min_warmup_bars_30m:
            return None, None, 0.0

        df_15m = self._build_df_15m()
        df_30m = self._build_df_30m()

        if len(df_15m) < 3 or len(df_30m) < 3:
            return None, None, 0.0

        # --- MAMA/FAMA crossover on 15m (hl2)
        df_15m["hl2"] = (df_15m["high"] + df_15m["low"]) / 2.0
        mama_fama = ta.mama(df_15m["hl2"], fast=float(self._rule_cfg.mama_fast), slow=float(self._rule_cfg.mama_slow))
        if mama_fama is None or len(mama_fama) < 2:
            return None, None, 0.0

        mama = mama_fama.iloc[:, 0]
        fama = mama_fama.iloc[:, 1]
        mama_diff = (mama - fama) / df_15m["close"]

        prev_diff = float(mama_diff.iloc[-2])
        curr_diff = float(mama_diff.iloc[-1])

        cross_long = prev_diff <= 0.0 and curr_diff > 0.0
        cross_short = prev_diff >= 0.0 and curr_diff < 0.0

        if not cross_long and not cross_short:
            # Keep meta updated even without a signal
            self._latest_meta["mama_diff"] = curr_diff
            return None, None, 0.0

        direction = "LONG" if cross_long else "SHORT"

        # --- DMI confirmation (15m)
        dmi_15 = ta.adx(df_15m["high"], df_15m["low"], df_15m["close"], length=int(self._rule_cfg.dmi_length_15m))
        if dmi_15 is None or len(dmi_15) == 0:
            return None, None, 0.0

        adx_15 = float((dmi_15.iloc[:, 0] / 100.0).iloc[-1])
        dmp_15 = float((dmi_15.iloc[:, 1] / 100.0).iloc[-1])
        dmn_15 = float((dmi_15.iloc[:, 2] / 100.0).iloc[-1])

        # --- DMI confirmation (30m)
        dmi_30 = ta.adx(df_30m["high"], df_30m["low"], df_30m["close"], length=int(self._rule_cfg.dmi_length_30m))
        if dmi_30 is None or len(dmi_30) == 0:
            return None, None, 0.0

        adx_30 = float((dmi_30.iloc[:, 0] / 100.0).iloc[-1])
        dmp_30 = float((dmi_30.iloc[:, 1] / 100.0).iloc[-1])
        dmn_30 = float((dmi_30.iloc[:, 2] / 100.0).iloc[-1])

        # Store meta values for any downstream filters/logging
        self._latest_meta["mama_diff"] = curr_diff
        self._latest_meta["dmp_30m"] = dmp_30

        if float(self._rule_cfg.adx_min_30m) > 0.0 and adx_30 < float(self._rule_cfg.adx_min_30m):
            return None, None, 0.0

        if direction == "LONG":
            if not (dmp_15 > dmn_15 and dmp_30 > dmn_30):
                return None, None, 0.0
        else:
            if not (dmn_15 > dmp_15 and dmn_30 > dmp_30):
                return None, None, 0.0

        # --- Stochastic confirmation (15m)
        stoch = ta.stoch(
            df_15m["high"],
            df_15m["low"],
            df_15m["close"],
            k=int(self._rule_cfg.stoch_k),
            d=int(self._rule_cfg.stoch_d),
            smooth_k=int(self._rule_cfg.stoch_smooth_k),
        )
        if stoch is None or len(stoch) == 0:
            return None, None, 0.0

        stoch_k = float(stoch.iloc[-1, 0])
        stoch_d = float(stoch.iloc[-1, 1])

        if direction == "LONG":
            if not (stoch_k > stoch_d and stoch_k < float(self._rule_cfg.stoch_max_for_long)):
                return None, None, 0.0
        else:
            if not (stoch_k < stoch_d and stoch_k > float(self._rule_cfg.stoch_min_for_short)):
                return None, None, 0.0

        # Features vector (for logging + consistent order submission contract)
        log_ret = float(np.log(df_15m["close"].iloc[-1] / df_15m["close"].iloc[-2]) * 100.0)
        atr_norm = self._calculate_atr() or 0.0
        ts = df_15m.index[-1]

        features = np.array(
            [
                log_ret,
                float(curr_diff),
                float(adx_30),
                float(dmp_30),
                float(dmn_30),
                float(stoch_k / 100.0),
                float(stoch_d / 100.0),
                float(atr_norm),
                float(ts.hour),
                float(ts.dayofweek),
            ],
            dtype=np.float64,
        )

        # Confidence: deterministic rule-set; treat as high-confidence.
        # You can later tune this to a graded score and keep using prediction_threshold.
        confidence = 1.0
        return direction, features, confidence

    def on_bar(self, bar: Bar):  # override
        # Reuse the base state machine (buffers, warmup, trailing updates, stall logic,
        # and order submission). We only replace the ML prediction step.
        bar_time = pd.Timestamp(bar.ts_init, unit="ns", tz="UTC")

        self.bars_buffer_15m.append(bar)
        self._resample_to_30m()

        if len(self.bars_buffer_15m) < self._min_warmup_bars_15m:
            return
        if len(self.bars_buffer_30m) < self._min_warmup_bars_30m:
            return

        if self._warmup_mode:
            self._warmup_mode = False

        instrument = self.cache.instrument(self.instrument_id)
        if instrument is None:
            return

        if self._layers["POS2"].converted_to_trailing:
            self._update_trailing_stop(self._layers["POS2"], float(bar.close))
        if self._layers["POS3"].converted_to_trailing:
            self._update_trailing_stop(self._layers["POS3"], float(bar.close))

        self._check_stall_detection(float(bar.close))

        any_open = any(l.is_open for l in self._layers.values())
        positions = list(self.cache.positions_open(instrument_id=self.instrument_id))
        open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
        if any_open or len(positions) > 0 or len(open_orders) > 0:
            return

        if self._cooldown_remaining_bars > 0:
            self._cooldown_remaining_bars -= 1
            return

        # Session filter (with weekday-specific exclusions)
        hour = bar_time.hour
        weekday = bar_time.weekday()
        if not self._is_trading_allowed(hour, weekday, bar_time):
            return

        atr = self._calculate_atr()
        if atr is None:
            return
        if atr < self.min_atr or atr > self.max_atr:
            return

        direction, features, confidence = self._compute_rule_signal()
        if direction is None or features is None:
            return

        if confidence < self.prediction_threshold:
            return

        self._execute_entry(bar, atr, direction, features, confidence)
