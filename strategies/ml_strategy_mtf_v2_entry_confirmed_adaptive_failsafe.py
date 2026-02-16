"""
MLSignalStrategy V2 with Adaptive Entry Confirmation and Fail-Safe Protection

This strategy combines:
1. ADAPTIVE entry confirmation - dynamically adjusts confirmation requirements based on:
   - Signal confidence (high confidence signals get easier confirmation)
   - Market volatility (high volatility gets faster entry, low volatility stricter)
2. FAIL-SAFE bracket protection - ensures NO positions exist without SL/TP:
   - 30-second grace period after order submission
   - Protection checks every 5 seconds
   - Emergency flatten after 3 failed protection checks

Key features:
- Adaptive confirmation filter using 1-minute bar momentum
- High confidence bypass threshold (reduces confirmation for strong signals)
- Volatility-based adjustment (adapts to market conditions)
- Automatic bracket order verification
- Emergency position flattening for unprotected positions
- Maintains all original V2 functionality
"""

import logging
import os
import sys
from collections import deque
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import joblib
import numpy as np
import pandas as pd
import zoneinfo

import pandas_ta as ta

from strategies.feature_engineering_v2_rf40 import latest_rf40_row
from strategies.feature_engineering_v3 import latest_v3_row, FEATURE_COLUMNS_V3
from strategies.feature_engineering_4h import compute_4h_features, FEATURE_COLUMNS_4H

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.data import Data
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.orders import MarketOrder, StopMarketOrder, LimitOrder
from nautilus_trader.model.position import Position
from nautilus_trader.trading.strategy import Strategy

# Import configuration
from config.mtf_v2_config import load_mtf_v2_config

# Feature names (matching `models/strategy_model.joblib` / `models/model_metadata.json`)
FEATURE_NAMES = [
    "log_ret",
    "mama_diff",
    "adx",
    "dmp",
    "dmn",
    "stoch_k",
    "stoch_d",
    "atr",
    "hour",
    "day_of_week",
]

# Setup logging
_py_logger = logging.getLogger("MLSignalStrategy_V2_EntryConfirmedAdaptive")
_py_logger.setLevel(logging.INFO)

def get_dynamic_sl_tp(entry_time: pd.Timestamp) -> Dict[str, float]:
    """
    Get dynamic SL/TP multipliers based on entry time.
    For now, return default values - can be enhanced later.
    """
    return {
        'sl_atr_mult': 1.4,
        'pos1_tp_atr_mult': 0.6,
        'pos2_tp_atr_mult': 1.5,
    }

def get_meta_filter_params() -> Dict[str, Any]:
    """
    Get meta-filter parameters.
    For now, return disabled values - can be enhanced later.
    """
    return {
        'mama_enabled': False,
        'mama_min_diff': 0.0000,
        'dmi_enabled': False,
        'dmi_min_dmp': 0.20,
    }

class MLSignalStrategyV2EntryConfirmedAdaptiveConfig(StrategyConfig, kw_only=True):
    """Configuration for MLSignalStrategy V2 with Adaptive Entry Confirmation."""
    
    instrument_id: str
    bar_type: str
    model_path: str = "models/ml_model_mtf.pkl"
    
    # Position sizing (total = 100k, split into 2)
    # OPTIMIZED Dec 2025: 85/15 two-position bracket
    # PnL: $38,421 | WR: 69.6% | Sharpe: 9.91 | Neg Days: 63 | Neg Months: 0
    total_position_size: int = 100000
    pos1_fraction: float = 0.85
    pos2_fraction: float = 0.15
    pos3_fraction: float = 0.0  # Disabled in optimized config
    
    # Default SL/TP multipliers
    sl_atr_mult: float = 1.4
    pos1_tp_atr_mult: float = 0.6
    pos2_tp_atr_mult: float = 1.5
    pos3_tp_atr_mult: float = 2.0
    trailing_distance_atr_mult: float = 0.4

    # Prediction settings
    prediction_threshold: float = 0.55
    prediction_threshold_long: float = 0.0   # 0 = use prediction_threshold
    prediction_threshold_short: float = 0.0  # 0 = use prediction_threshold

    # Session filtering (used for verification parity when entry confirmation is disabled)
    trade_start_hour: int = 7
    trade_end_hour: int = 20
    entry_cooldown_bars: int = 0

    # Weekday-specific excluded hours
    excluded_hours_mode: str = "simple"  # 'disabled', 'simple', or 'weekday'
    config_timezone: str = "UTC"  # 'EST' or 'UTC'
    excluded_hours_monday: list[int] = []
    excluded_hours_tuesday: list[int] = []
    excluded_hours_wednesday: list[int] = []
    excluded_hours_thursday: list[int] = []
    excluded_hours_friday: list[int] = []
    excluded_hours_saturday: list[int] = []
    excluded_hours_sunday: list[int] = []

    # Risk management (used for verification parity when entry confirmation is disabled)
    min_atr: float = 0.0003
    max_atr: float = 0.005
    
    # Entry confirmation settings
    entry_confirmation_enabled: bool = True
    entry_confirmation_bars: int = 2  # Number of bars to wait for confirmation
    entry_confirmation_threshold: float = 0.2  # Minimum favorable movement in ATR units
    entry_max_wait_bars: int = 5  # Maximum bars to wait for confirmation before discarding signal
    
    # Adaptive confirmation parameters
    high_confidence_bypass_threshold: float = 0.8  # Confidence level to bypass strict confirmation
    volatility_adjustment_enabled: bool = True  # Enable dynamic adjustment based on volatility
    volatility_high_threshold: float = 0.003  # ATR threshold for high volatility
    volatility_low_threshold: float = 0.001  # ATR threshold for low volatility
    volatility_high_bars: int = 1  # Reduced bars required in high volatility
    volatility_low_threshold_reduction: float = 0.05  # Threshold reduction in high volatility

    # Optional: confidence-tiered SL (no behavior change unless enabled)
    # Format: "min_conf:sl_atr_mult,min_conf:sl_atr_mult" e.g. "0.85:1.25,0.90:1.35"
    # Rule: choose the sl_atr_mult for the highest min_conf <= confidence.
    confidence_sl_enabled: bool = False
    confidence_sl_tiers: str = ""
    # If True, linearly interpolate SL multiplier between adjacent tier points.
    # If False, use step-function tiers (current behavior).
    confidence_sl_interpolate: bool = False
    
    # Seasonal hour×weekday exclusions (EST timezone)
    # Format: list of (hour, weekday) tuples where hour=0-23, weekday=1-7 (1=Mon, 7=Sun)
    seasonal_hour_exclusions_enabled: bool = False
    djf_excluded_hour_weekday_pairs: list = []
    mam_excluded_hour_weekday_pairs: list = []
    jja_excluded_hour_weekday_pairs: list = []
    son_excluded_hour_weekday_pairs: list = []

    # HTF (Higher Timeframe) 4H confirmation model
    # When enabled, the 15m signal must agree with the 4H model's directional prediction.
    # Modes: 'disabled' | 'agree' (strict: must agree) | 'soft' (only filter if HTF confident)
    htf_model_path: str = ""
    htf_confirmation_mode: str = "disabled"  # 'disabled', 'agree', 'soft'
    htf_min_confidence: float = 0.55  # Min HTF confidence to act as filter

    # Cross-pair USD strength confirmation filter
    # Uses GBP/USD and USD/CHF to derive a USD strength signal.
    # Blocks trades that disagree with the cross-pair USD consensus.
    # Modes: 'disabled' | 'agree' (must agree) | 'soft' (only block strong disagreement)
    xpair_confirmation_mode: str = "disabled"  # 'disabled', 'agree', 'soft'
    xpair_gbpusd_bar_type: str = ""  # e.g. GBP/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL
    xpair_usdchf_bar_type: str = ""  # e.g. USD/CHF.IDEALPRO-15-MINUTE-MID-EXTERNAL
    xpair_lookback_bars: int = 4  # Number of 15m bars for return calculation (4 = 1 hour)
    xpair_ema_period: int = 8  # EMA smoothing period for USD strength signal
    xpair_strength_threshold: float = 0.0003  # Min USD strength magnitude to trigger filter

class PendingSignal:
    """Stores a pending signal waiting for entry confirmation."""
    
    def __init__(self, direction: str, entry_bar: Bar, features: List[float], 
                 prediction: int, prediction_proba: np.ndarray, dynamic_params: Dict[str, float],
                 entry_atr: float, confidence: float = 0.5):
        self.direction = direction
        self.entry_bar = entry_bar
        self.features = features
        self.prediction = prediction
        self.prediction_proba = prediction_proba
        self.dynamic_params = dynamic_params
        self.confidence = confidence
        self.entry_atr = entry_atr
        self.bars_waited = 0
        self.created_time = entry_bar.ts_event
        self.signal_generation_time = entry_bar.ts_init  # Track when signal was generated

class MLSignalStrategyV2EntryConfirmedAdaptiveFailSafe(Strategy):
    """
    ML-based trading strategy with adaptive entry confirmation and fail-safe protection.
    
    Features:
    - Adaptive entry confirmation (volatility-based, confidence-based)
    - Fail-safe bracket order protection (30s grace, 5s checks, emergency flatten)
    - Dynamic SL/TP based on market conditions
    """
    
    def __init__(self, config: MLSignalStrategyV2EntryConfirmedAdaptiveConfig):
        super().__init__(config)
        
        # Configuration
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.model_path = config.model_path
        
        # Position sizing
        self.total_size = config.total_position_size
        self._pos1_fraction = config.pos1_fraction
        self._pos2_fraction = config.pos2_fraction
        self._pos3_fraction = config.pos3_fraction
        
        # Default SL/TP multipliers
        self.sl_atr_mult = config.sl_atr_mult
        self.pos1_tp_atr_mult = config.pos1_tp_atr_mult
        self.pos2_tp_atr_mult = config.pos2_tp_atr_mult
        self.pos3_tp_atr_mult = config.pos3_tp_atr_mult
        self.trailing_distance_atr_mult = config.trailing_distance_atr_mult

        # Prediction
        self.prediction_threshold = config.prediction_threshold
        self._threshold_long = float(getattr(config, 'prediction_threshold_long', 0) or 0)
        self._threshold_short = float(getattr(config, 'prediction_threshold_short', 0) or 0)

        # V2 parity gates (Option A): only enforced when entry confirmation is disabled
        self.trade_start_hour = config.trade_start_hour
        self.trade_end_hour = config.trade_end_hour
        self._entry_cooldown_bars = int(config.entry_cooldown_bars)
        self._cooldown_remaining_bars = 0
        self.min_atr = config.min_atr
        self.max_atr = config.max_atr
        self._excluded_hours_mode = str(config.excluded_hours_mode)
        self._config_timezone = str(config.config_timezone).upper()
        self._excluded_hours = {
            0: self._parse_hours(config.excluded_hours_monday),
            1: self._parse_hours(config.excluded_hours_tuesday),
            2: self._parse_hours(config.excluded_hours_wednesday),
            3: self._parse_hours(config.excluded_hours_thursday),
            4: self._parse_hours(config.excluded_hours_friday),
            5: self._parse_hours(config.excluded_hours_saturday),
            6: self._parse_hours(config.excluded_hours_sunday),
        }
        
        # Entry confirmation settings
        self.entry_confirmation_enabled = config.entry_confirmation_enabled
        self.entry_confirmation_bars = config.entry_confirmation_bars
        self.entry_confirmation_threshold = config.entry_confirmation_threshold
        self.entry_max_wait_bars = config.entry_max_wait_bars
        
        # Adaptive confirmation parameters
        self.high_confidence_bypass_threshold = config.high_confidence_bypass_threshold
        self.volatility_adjustment_enabled = config.volatility_adjustment_enabled
        self.volatility_high_threshold = config.volatility_high_threshold
        self.volatility_low_threshold = config.volatility_low_threshold
        self.volatility_high_bars = config.volatility_high_bars
        self.volatility_low_threshold_reduction = config.volatility_low_threshold_reduction

        # Confidence-tiered SL
        self._confidence_sl_enabled = bool(getattr(config, "confidence_sl_enabled", False))
        self._confidence_sl_tiers_raw = str(getattr(config, "confidence_sl_tiers", "") or "").strip()
        self._confidence_sl_tiers = self._parse_confidence_sl_tiers(self._confidence_sl_tiers_raw)
        self._confidence_sl_interpolate = bool(getattr(config, "confidence_sl_interpolate", False))
        
        # Seasonal hour×weekday exclusions
        self._seasonal_hour_exclusions_enabled = bool(getattr(config, "seasonal_hour_exclusions_enabled", False))
        self._djf_excluded_hour_weekday_pairs = self._parse_hour_weekday_pairs(getattr(config, "djf_excluded_hour_weekday_pairs", []))
        self._mam_excluded_hour_weekday_pairs = self._parse_hour_weekday_pairs(getattr(config, "mam_excluded_hour_weekday_pairs", []))
        self._jja_excluded_hour_weekday_pairs = self._parse_hour_weekday_pairs(getattr(config, "jja_excluded_hour_weekday_pairs", []))
        self._son_excluded_hour_weekday_pairs = self._parse_hour_weekday_pairs(getattr(config, "son_excluded_hour_weekday_pairs", []))
        
        # Strategy state
        self.instrument: Optional[Instrument] = None
        self.model = None
        self.pending_signal: Optional[PendingSignal] = None
        
        # Meta values used by filters (computed alongside features)
        self._latest_meta: Dict[str, Optional[float]] = {"mama_diff": None, "dmp_30m": None}

        # FAIL-SAFE: Protection check cadence (fast, but rate-limited)
        self._last_protection_check_ns: int = 0
        self._protection_check_interval_ns: int = 5_000_000_000  # 5 seconds
        
        # Position tracking
        self.active_positions: Dict[str, Position] = {}
        self.position_layers: Dict[str, Dict] = {}
        
        # Meta-filters state
        self._meta_filter_enabled = False
        self._meta_filter_params = {}
        
        # Initialize bar buffers
        # V3 model needs ~500+ bars; HTF 4H needs 1600+ unique 15m bars → ~100 4H bars
        # Backtest delivers each 15m bar twice (dual subscription), so buffer=3400
        self.bars_buffer_15m = deque(maxlen=3400)
        self.bars_buffer_30m = deque(maxlen=50)
        self._min_warmup_bars_15m = 500
        self._min_warmup_bars_30m = 25
        self._atr_values = deque(maxlen=14)
        self._atr_window = 14

        # HTF (4H) confirmation model
        self._htf_model = None
        self._htf_confirmation_mode = str(getattr(config, 'htf_confirmation_mode', 'disabled')).lower()
        self._htf_min_confidence = float(getattr(config, 'htf_min_confidence', 0.55))
        self._htf_model_path = str(getattr(config, 'htf_model_path', '') or '')
        self._htf_last_direction = None   # Cached: 'LONG', 'SHORT', or None
        self._htf_last_confidence = 0.0   # Cached confidence
        self._htf_last_bar_time = None    # Timestamp of last 4H prediction
        self._htf_bars_buffer_4h = deque(maxlen=200)  # 4H bars resampled from 15m
        self._htf_min_warmup_4h = 100     # Need ~100 4H bars for features

        # Cross-pair USD strength filter
        self._xpair_mode = str(getattr(config, 'xpair_confirmation_mode', 'disabled')).lower()
        self._xpair_gbpusd_bar_type_str = str(getattr(config, 'xpair_gbpusd_bar_type', '') or '')
        self._xpair_usdchf_bar_type_str = str(getattr(config, 'xpair_usdchf_bar_type', '') or '')
        self._xpair_lookback = int(getattr(config, 'xpair_lookback_bars', 4))
        self._xpair_ema_period = int(getattr(config, 'xpair_ema_period', 8))
        self._xpair_threshold = float(getattr(config, 'xpair_strength_threshold', 0.0003))
        self._xpair_gbpusd_bar_type = None
        self._xpair_usdchf_bar_type = None
        if self._xpair_mode != 'disabled' and self._xpair_gbpusd_bar_type_str and self._xpair_usdchf_bar_type_str:
            self._xpair_gbpusd_bar_type = BarType.from_str(self._xpair_gbpusd_bar_type_str)
            self._xpair_usdchf_bar_type = BarType.from_str(self._xpair_usdchf_bar_type_str)
        self._xpair_gbpusd_closes = deque(maxlen=200)
        self._xpair_usdchf_closes = deque(maxlen=200)
        self._xpair_usd_strength_ema = None  # Smoothed USD strength
        self._xpair_ema_alpha = 2.0 / (self._xpair_ema_period + 1)

        # Live startup guard: block stale/backfill-driven entries after process start.
        # In replay mode this guard is disabled.
        self._is_replay_mode = os.getenv("MTF2_REPLAY_MODE", "0").strip().lower() in {"1", "true", "yes"}
        self._live_signal_max_age_sec = int(os.getenv("MTF2_LIVE_SIGNAL_MAX_AGE_SEC", "1200"))  # default 20 minutes

        # Initialize position layers
        self._init_position_layers()
        
        # Load model
        self._load_model()
        
        # Load HTF model if configured
        self._load_htf_model()

        _py_logger.info("MLSignalStrategy V2 Entry Confirmed ADAPTIVE + FAIL-SAFE initialized")
        _py_logger.info(f"Entry confirmation: {'ENABLED' if self.entry_confirmation_enabled else 'DISABLED'}")
        _py_logger.info(f"Confirmation bars: {self.entry_confirmation_bars}, threshold: {self.entry_confirmation_threshold} ATR")
        _py_logger.info(f"High confidence bypass threshold: {self.high_confidence_bypass_threshold}")
        _py_logger.info(f"Volatility adjustment: {'ENABLED' if self.volatility_adjustment_enabled else 'DISABLED'}")
        if self.volatility_adjustment_enabled:
            _py_logger.info(f"Volatility thresholds: high={self.volatility_high_threshold}, low={self.volatility_low_threshold}")
        _py_logger.info("Fail-safe protection: ENABLED (30s grace, 5s checks, 3 max failures)")
        if self._confidence_sl_enabled:
            _py_logger.info(
                "Confidence SL: ENABLED tiers=%s interpolate=%s",
                self._confidence_sl_tiers_raw,
                self._confidence_sl_interpolate,
            )
        else:
            _py_logger.info("Confidence SL: DISABLED")
        _py_logger.info(
            "HTF 4H confirmation: mode=%s path=%s min_conf=%s",
            self._htf_confirmation_mode,
            self._htf_model_path or '<none>',
            self._htf_min_confidence,
        )
        _py_logger.info(
            "Cross-pair USD filter: mode=%s gbpusd=%s usdchf=%s lookback=%d ema=%d thresh=%s",
            self._xpair_mode,
            self._xpair_gbpusd_bar_type_str or '<none>',
            self._xpair_usdchf_bar_type_str or '<none>',
            self._xpair_lookback,
            self._xpair_ema_period,
            self._xpair_threshold,
        )
        if not self._is_replay_mode:
            _py_logger.info(
                "Live signal freshness guard: ENABLED (max_age=%ss)",
                self._live_signal_max_age_sec,
            )

    def _is_live_signal_fresh(self, signal_time_utc: pd.Timestamp) -> bool:
        """Return True if a signal timestamp is fresh enough for live execution.

        Prevents stale startup/backfill bars from generating real entries in live mode.
        """
        if self._is_replay_mode:
            return True

        try:
            ts = pd.Timestamp(signal_time_utc)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")

            now_utc = pd.Timestamp.now(tz="UTC")
            age_sec = float((now_utc - ts).total_seconds())

            # Reject very old signals and clearly future timestamps.
            if age_sec < -120:
                return False
            return age_sec <= float(self._live_signal_max_age_sec)
        except Exception:
            return False

    @staticmethod
    def _parse_confidence_sl_tiers(tiers_str: str) -> List[Tuple[float, float]]:
        """Parse confidence SL tiers string into sorted (min_conf, sl_mult) pairs."""
        tiers: List[Tuple[float, float]] = []
        raw = str(tiers_str or "").strip()
        if not raw:
            return tiers

        for part in raw.split(","):
            item = part.strip()
            if not item:
                continue
            if ":" not in item:
                continue
            left, right = item.split(":", 1)
            try:
                min_conf = float(left.strip())
                sl_mult = float(right.strip())
            except Exception:
                continue
            if not (0.0 <= min_conf <= 1.0):
                continue
            if sl_mult <= 0.0:
                continue
            tiers.append((min_conf, sl_mult))

        tiers.sort(key=lambda x: x[0])
        return tiers

    def _sl_mult_for_confidence(self, confidence: float, base_sl_mult: float) -> float:
        if not self._confidence_sl_enabled:
            return base_sl_mult
        if not self._confidence_sl_tiers:
            return base_sl_mult

        confidence = float(confidence)
        base_sl_mult = float(base_sl_mult)

        # Below lowest tier: keep base SL (preserves current semantics)
        if confidence < float(self._confidence_sl_tiers[0][0]):
            chosen = base_sl_mult
        # At/above highest tier: use highest tier value
        elif confidence >= float(self._confidence_sl_tiers[-1][0]):
            chosen = float(self._confidence_sl_tiers[-1][1])
        # Between tiers
        else:
            if not self._confidence_sl_interpolate:
                chosen = base_sl_mult
                for min_conf, sl_mult in self._confidence_sl_tiers:
                    if confidence >= float(min_conf):
                        chosen = float(sl_mult)
                    else:
                        break
            else:
                chosen = base_sl_mult
                for i in range(len(self._confidence_sl_tiers) - 1):
                    c0, s0 = self._confidence_sl_tiers[i]
                    c1, s1 = self._confidence_sl_tiers[i + 1]
                    c0f = float(c0)
                    c1f = float(c1)
                    if c1f <= c0f:
                        continue
                    if c0f <= confidence <= c1f:
                        t = (confidence - c0f) / (c1f - c0f)
                        chosen = float(s0) + t * (float(s1) - float(s0))
                        break

        # Round to a friendly decimal format (e.g. 0.95 not 0.95745632)
        chosen = round(float(chosen), 2)

        # Safety clamp (prevents accidental nonsense config)
        return float(min(max(chosen, 0.05), 10.0))

    def _init_position_layers(self):
        """Initialize position layer configuration."""
        self.position_layers = {
            "POS1": {
                "fraction": self._pos1_fraction,
                "tp_atr_mult": self.pos1_tp_atr_mult,
                "size": int(self.total_size * self._pos1_fraction),
                "entry_features": {},
            }
        }
        
        if self._pos2_fraction > 0:
            self.position_layers["POS2"] = {
                "fraction": self._pos2_fraction,
                "tp_atr_mult": self.pos2_tp_atr_mult,
                "size": int(self.total_size * self._pos2_fraction),
                "entry_features": {},
            }
        
        if self._pos3_fraction > 0:
            self.position_layers["POS3"] = {
                "fraction": self._pos3_fraction,
                "tp_atr_mult": self.pos3_tp_atr_mult,
                "size": int(self.total_size * self._pos3_fraction),
                "entry_features": {},
            }

    def _load_model(self):
        """Load the ML model."""
        try:
            self.model = joblib.load(self.model_path)
            _py_logger.info(f"Loaded ML model from {self.model_path}")
            # Print model info for debugging
            if hasattr(self.model, 'feature_names_in_'):
                _py_logger.info(f"Model features: {self.model.feature_names_in_}")
            if hasattr(self.model, 'classes_'):
                _py_logger.info(f"Model classes: {self.model.classes_}")
        except Exception as e:
            _py_logger.error(f"Failed to load ML model: {e}")
            raise

    def _load_htf_model(self):
        """Load the HTF (4H) confirmation model if configured."""
        if self._htf_confirmation_mode == 'disabled' or not self._htf_model_path:
            _py_logger.info("HTF 4H confirmation model: DISABLED")
            return
        try:
            self._htf_model = joblib.load(self._htf_model_path)
            _py_logger.info(f"Loaded HTF 4H model from {self._htf_model_path}")
            if hasattr(self._htf_model, 'feature_names_in_'):
                _py_logger.info(f"HTF model features: {len(self._htf_model.feature_names_in_)} features")
        except Exception as e:
            _py_logger.error(f"Failed to load HTF model: {e}")
            _py_logger.warning("HTF confirmation will be DISABLED due to load failure")
            self._htf_confirmation_mode = 'disabled'

    def _update_htf_prediction(self, bar_time_utc):
        """Update the cached 4H prediction when a new 4H boundary is crossed.
        
        Called on every 15m bar. Resamples the 15m buffer to 4H bars,
        computes features, and runs the HTF model.
        """
        if self._htf_model is None or self._htf_confirmation_mode == 'disabled':
            return

        # Only recompute at 4H boundaries (hours 0, 4, 8, 12, 16, 20)
        if hasattr(bar_time_utc, 'hour'):
            hour = bar_time_utc.hour
            minute = bar_time_utc.minute if hasattr(bar_time_utc, 'minute') else 0
        else:
            return

        # Check if we're at a 4H boundary (within 15 min tolerance)
        is_4h_boundary = (hour % 4 == 0) and (minute < 15)
        
        # Also recompute if we've never computed before
        if not is_4h_boundary and self._htf_last_bar_time is not None:
            return

        # Need enough 15m bars to resample to 4H
        n_15m = len(self.bars_buffer_15m)
        # Backtest delivers each bar twice; need ~1600 unique 15m bars for ~100 4H bars
        min_15m_for_htf = 1600  # After dedup: ~100 4H bars for reliable features
        if n_15m < min_15m_for_htf:
            return

        try:
            # Build 15m DataFrame from buffer
            records = []
            for b in self.bars_buffer_15m:
                ts = pd.Timestamp(b.ts_event, unit='ns', tz='UTC')
                records.append({
                    'open': float(b.open),
                    'high': float(b.high),
                    'low': float(b.low),
                    'close': float(b.close),
                    'volume': float(b.volume),
                    'timestamp': ts,
                })
            df_15m = pd.DataFrame(records).set_index('timestamp').sort_index()
            
            # Deduplicate: keep last value for each timestamp
            df_15m = df_15m[~df_15m.index.duplicated(keep='last')]

            # Resample to 4H
            df_4h = df_15m.resample("4h").agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum',
            }).dropna()

            _py_logger.info(f"[HTF_4H_DEBUG] 15m_unique={len(df_15m)}, 4h_bars={len(df_4h)}, boundary={is_4h_boundary}")

            if len(df_4h) < 40:
                _py_logger.info(f"[HTF_4H_DEBUG] Not enough 4H bars: {len(df_4h)} < 40")
                return

            # Compute 4H features
            feats = compute_4h_features(df_4h)
            row = feats.iloc[[-1]].astype(float)
            values = row.to_numpy(dtype=float)
            nan_cols = [c for c, v in zip(row.columns, values[0]) if not np.isfinite(v)]
            if not np.isfinite(values).all():
                _py_logger.info(f"[HTF_4H_DEBUG] NaN in features: {nan_cols[:5]}")
                return

            # Predict with HTF model
            if hasattr(self._htf_model, 'feature_names_in_'):
                names = list(self._htf_model.feature_names_in_)
                X = pd.DataFrame(row.values, columns=names)
            else:
                X = row

            pred = self._htf_model.predict(X)[0]
            proba = self._htf_model.predict_proba(X)[0]

            # pred=1 means LONG/bullish, pred=0 means SHORT/bearish
            htf_direction = "LONG" if pred == 1 else "SHORT"
            htf_confidence = float(proba[1]) if pred == 1 else float(proba[0])

            self._htf_last_direction = htf_direction
            self._htf_last_confidence = htf_confidence
            self._htf_last_bar_time = bar_time_utc

            _py_logger.info(
                f"[HTF_4H] Prediction updated: {htf_direction} (conf={htf_confidence:.3f}) "
                f"at {bar_time_utc} from {len(df_4h)} 4H bars"
            )

        except Exception as e:
            _py_logger.warning(f"[HTF_4H] Prediction failed: {e}")

    def _htf_confirms_direction(self, direction: str) -> bool:
        """Check if the HTF 4H model confirms the given trade direction.
        
        Returns True if:
        - HTF confirmation is disabled
        - HTF model not loaded or no prediction yet
        - Mode is 'agree' and HTF direction matches with sufficient confidence
        - Mode is 'soft' and HTF is either neutral or agrees
        """
        if self._htf_confirmation_mode == 'disabled' or self._htf_model is None:
            return True

        if self._htf_last_direction is None:
            # No prediction yet (warmup) — allow trades
            _py_logger.info("[HTF_4H] No prediction yet (warmup), allowing trade")
            return True

        htf_dir = self._htf_last_direction
        htf_conf = self._htf_last_confidence

        if self._htf_confirmation_mode == 'agree':
            # Strict: HTF must agree on direction with min confidence
            if htf_dir == direction and htf_conf >= self._htf_min_confidence:
                _py_logger.info(
                    f"[HTF_4H] CONFIRMED: {direction} agrees with HTF {htf_dir} (conf={htf_conf:.3f})"
                )
                return True
            else:
                _py_logger.info(
                    f"[HTF_4H] REJECTED: {direction} vs HTF {htf_dir} (conf={htf_conf:.3f}, "
                    f"min={self._htf_min_confidence})"
                )
                return False

        elif self._htf_confirmation_mode == 'soft':
            # Soft: only reject if HTF confidently disagrees
            if htf_dir != direction and htf_conf >= self._htf_min_confidence:
                _py_logger.info(
                    f"[HTF_4H] SOFT REJECT: {direction} vs HTF {htf_dir} (conf={htf_conf:.3f})"
                )
                return False
            else:
                _py_logger.info(
                    f"[HTF_4H] SOFT PASS: {direction}, HTF={htf_dir} (conf={htf_conf:.3f})"
                )
                return True

        return True

    def _update_xpair_usd_strength(self):
        """Recompute the smoothed USD strength signal from cross-pair returns.

        USD strength = -gbpusd_return + usdchf_return
        Positive = USD strengthening (bearish EUR/USD)
        Negative = USD weakening (bullish EUR/USD)
        """
        n = self._xpair_lookback
        if len(self._xpair_gbpusd_closes) < n + 1 or len(self._xpair_usdchf_closes) < n + 1:
            return  # Not enough data yet

        gbp_ret = (self._xpair_gbpusd_closes[-1] - self._xpair_gbpusd_closes[-1 - n]) / self._xpair_gbpusd_closes[-1 - n]
        chf_ret = (self._xpair_usdchf_closes[-1] - self._xpair_usdchf_closes[-1 - n]) / self._xpair_usdchf_closes[-1 - n]

        # USD strength: GBP/USD falling + USD/CHF rising = USD strong
        raw_strength = -gbp_ret + chf_ret

        # EMA smoothing
        if self._xpair_usd_strength_ema is None:
            self._xpair_usd_strength_ema = raw_strength
        else:
            alpha = self._xpair_ema_alpha
            self._xpair_usd_strength_ema = alpha * raw_strength + (1 - alpha) * self._xpair_usd_strength_ema

    def _xpair_confirms_direction(self, direction: str) -> bool:
        """Check if cross-pair USD strength confirms the given trade direction.

        Returns True if:
        - Cross-pair filter is disabled
        - Not enough cross-pair data yet (warmup)
        - Mode is 'agree' and USD strength agrees with direction
        - Mode is 'soft' and USD strength does not strongly disagree
        """
        if self._xpair_mode == 'disabled':
            return True

        if self._xpair_usd_strength_ema is None:
            _py_logger.info("[XPAIR] No USD strength data yet (warmup), allowing trade")
            return True

        strength = self._xpair_usd_strength_ema
        thresh = self._xpair_threshold

        # USD strong (positive) -> bearish EUR/USD -> favors SHORT
        # USD weak (negative) -> bullish EUR/USD -> favors LONG
        if self._xpair_mode == 'agree':
            if direction == "LONG" and strength < -thresh:
                _py_logger.info(
                    f"[XPAIR] CONFIRMED: LONG, USD weak (strength={strength:.6f}, thresh={thresh})"
                )
                return True
            elif direction == "SHORT" and strength > thresh:
                _py_logger.info(
                    f"[XPAIR] CONFIRMED: SHORT, USD strong (strength={strength:.6f}, thresh={thresh})"
                )
                return True
            elif abs(strength) < thresh:
                _py_logger.info(
                    f"[XPAIR] NEUTRAL: {direction}, USD neutral (strength={strength:.6f}, thresh={thresh})"
                )
                return False
            else:
                _py_logger.info(
                    f"[XPAIR] REJECTED: {direction} vs USD strength={strength:.6f} (thresh={thresh})"
                )
                return False

        elif self._xpair_mode == 'soft':
            # Only reject if USD strength strongly contradicts the direction
            if direction == "LONG" and strength > thresh:
                _py_logger.info(
                    f"[XPAIR] SOFT REJECT: LONG but USD strong (strength={strength:.6f}, thresh={thresh})"
                )
                return False
            elif direction == "SHORT" and strength < -thresh:
                _py_logger.info(
                    f"[XPAIR] SOFT REJECT: SHORT but USD weak (strength={strength:.6f}, thresh={thresh})"
                )
                return False
            else:
                _py_logger.info(
                    f"[XPAIR] SOFT PASS: {direction}, USD strength={strength:.6f} (thresh={thresh})"
                )
                return True

        return True

    def _using_v3_model(self) -> bool:
        if self.model is None:
            return False
        if hasattr(self.model, "feature_names_in_"):
            names = list(self.model.feature_names_in_)
            return len(names) == 50 and "returns_1" in names and "trend_alignment" in names
        if hasattr(self.model, "n_features_in_"):
            try:
                return int(self.model.n_features_in_) == 50
            except Exception:
                return False
        return False

    def _using_rf40_model(self) -> bool:
        if self.model is None:
            return False
        if hasattr(self.model, "feature_names_in_"):
            names = list(self.model.feature_names_in_)
            return len(names) == 40 and "returns" in names and "is_overlap" in names
        if hasattr(self.model, "n_features_in_"):
            try:
                return int(self.model.n_features_in_) == 40
            except Exception:
                return False
        return False

    def _current_feature_names(self) -> List[str]:
        if self.model is not None and hasattr(self.model, "feature_names_in_"):
            return list(self.model.feature_names_in_)
        return FEATURE_NAMES

    def on_start(self):
        """Initialize strategy."""
        # NOTE:
        # - In replay/backtest mode, bars are delivered via Nautilus' data engine and we must subscribe.
        # - In live mode, bars are fed directly from ib_insync (see live runner) and subscribing would
        #   cause duplicate bars if a Nautilus data client is also connected.
        is_replay = os.getenv("MTF2_REPLAY_MODE", "0").strip().lower() in {"1", "true", "yes"}

        bar_type_str = str(self.bar_type)
        one_min_bar_type_str = bar_type_str.replace("15-MINUTE", "1-MINUTE")
        self.one_min_bar_type = BarType.from_str(one_min_bar_type_str)

        if is_replay:
            # Subscribe to 15m bars for signals
            self.subscribe_bars(self.bar_type)

            # Subscribe to 1m bars for confirmation
            self.subscribe_bars(self.one_min_bar_type)
            _py_logger.info(f"Subscribed to {self.bar_type} and {self.one_min_bar_type} (replay mode)")

            # Subscribe to cross-pair bar types for USD strength filter
            if self._xpair_gbpusd_bar_type is not None:
                self.subscribe_bars(self._xpair_gbpusd_bar_type)
                _py_logger.info(f"Subscribed to cross-pair: {self._xpair_gbpusd_bar_type}")
            if self._xpair_usdchf_bar_type is not None:
                self.subscribe_bars(self._xpair_usdchf_bar_type)
                _py_logger.info(f"Subscribed to cross-pair: {self._xpair_usdchf_bar_type}")
        else:
            _py_logger.info(
                "Live mode: expecting bars fed directly via ib_insync for %s and %s",
                self.bar_type,
                self.one_min_bar_type,
            )
        
        # Get instrument
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            _py_logger.error(f"Instrument {self.instrument_id} not found")
            return
        
        # Load configuration
        config = load_mtf_v2_config()
        
        # Configure meta-filters
        self._meta_filter_enabled = config.meta_filter_mama_enabled or config.meta_filter_dmi_enabled
        if self._meta_filter_enabled:
            self._meta_filter_params = {
                'mama_enabled': config.meta_filter_mama_enabled,
                'mama_min_diff': config.meta_filter_mama_min_diff,
                'dmi_enabled': config.meta_filter_dmi_enabled,
                'dmi_min_dmp': config.meta_filter_dmi_min_dmp,
            }
            _py_logger.info("Meta-filters enabled")
            _py_logger.info(f"  MAMA filter: enabled={self._meta_filter_params['mama_enabled']}, min_diff={self._meta_filter_params['mama_min_diff']}")
            _py_logger.info(f"  DMI filter: enabled={self._meta_filter_params['dmi_enabled']}, min_dmp={self._meta_filter_params['dmi_min_dmp']}")

    def on_bar(self, bar: Bar):
        """Handle incoming bar data."""
        # Route 1m bars to entry confirmation logic
        if hasattr(self, "one_min_bar_type") and bar.bar_type == self.one_min_bar_type:
            if self.pending_signal is not None:
                self._check_entry_confirmation(bar)

            # FAIL-SAFE: check protection frequently while positions are open
            if len(self.active_positions) > 0:
                self._maybe_check_position_protection()
            return

        # Route cross-pair bars to USD strength buffers
        if self._xpair_gbpusd_bar_type is not None and bar.bar_type == self._xpair_gbpusd_bar_type:
            self._xpair_gbpusd_closes.append(float(bar.close))
            self._update_xpair_usd_strength()
            return
        if self._xpair_usdchf_bar_type is not None and bar.bar_type == self._xpair_usdchf_bar_type:
            self._xpair_usdchf_closes.append(float(bar.close))
            self._update_xpair_usd_strength()
            return

        # Only 15m bars drive signal generation and feature updates
        if bar.bar_type != self.bar_type:
            return
        
        bar_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')

        # FAIL-SAFE: Check position protection (rate-limited)
        if len(self.active_positions) > 0:
            self._maybe_check_position_protection()

        # Add to 15m buffer
        self.bars_buffer_15m.append(bar)

        # Create 30m bars from 15m data
        self._resample_to_30m()

        # Update ATR
        self._update_atr(bar)

        # Update HTF 4H prediction (only recomputes at 4H boundaries)
        self._update_htf_prediction(bar_time)

        _py_logger.info(
            f"[BAR] {bar_time} close={float(bar.close):.5f} 15m={len(self.bars_buffer_15m)} 30m={len(self.bars_buffer_30m)}"
        )

        # Live-only freshness guard: ignore stale historical bars during startup catch-up.
        if not self._is_live_signal_fresh(bar_time):
            _py_logger.info(
                "[STARTUP_GUARD] Skipping stale bar for signal generation: bar_time=%s",
                bar_time,
            )
            return

        # --- Always compute/log bar metrics when possible (even if filtered later) ---
        atr_normalized = self._calculate_atr_normalized()
        atr_text = f"{atr_normalized:.5f}" if atr_normalized is not None else "NA"

        warmup_15_ok = len(self.bars_buffer_15m) >= self._min_warmup_bars_15m
        warmup_30_ok = len(self.bars_buffer_30m) >= self._min_warmup_bars_30m
        warmup_ok = warmup_15_ok and warmup_30_ok

        excluded = not self._is_trading_allowed(bar_time.hour, bar_time.weekday(), bar_time)

        prediction = None
        prediction_proba = None
        confidence = None
        mama_diff = None
        dmp_30m = None
        meta_ok = None

        features = self._calculate_features() if warmup_ok else None
        if features is not None:
            try:
                pred, proba = self._predict_with_feature_names(features)
                prediction = int(pred) if pred is not None else None
                prediction_proba = proba
                confidence = float(max(prediction_proba))
                mama_diff = self._latest_meta.get("mama_diff")
                dmp_30m = self._latest_meta.get("dmp_30m")

                if self._meta_filter_enabled:
                    meta_ok = self._check_meta_filters()
                else:
                    meta_ok = True
            except Exception:
                # If model/meta computation fails, we still want the strategy to keep running.
                prediction = None
                confidence = None
                meta_ok = None

        pred_text = str(prediction) if prediction is not None else "NA"
        conf_text = f"{confidence:.3f}" if confidence is not None else "NA"
        mama_text = f"{mama_diff:.6f}" if mama_diff is not None else "NA"
        dmp_text = f"{dmp_30m:.4f}" if dmp_30m is not None else "NA"
        meta_text = "NA" if meta_ok is None else ("PASS" if meta_ok else "FAIL")

        htf_text = "disabled"
        if self._htf_confirmation_mode != 'disabled' and self._htf_last_direction is not None:
            htf_text = f"{self._htf_last_direction}({self._htf_last_confidence:.2f})"
        elif self._htf_confirmation_mode != 'disabled':
            htf_text = "warmup"

        xpair_text = "disabled"
        if self._xpair_mode != 'disabled' and self._xpair_usd_strength_ema is not None:
            xpair_text = f"{self._xpair_usd_strength_ema:.6f}"
        elif self._xpair_mode != 'disabled':
            xpair_text = "warmup"

        _py_logger.info(
            f"[BAR_METRICS] {bar_time} close={float(bar.close):.5f} atr={atr_text} "
            f"pred={pred_text} conf={conf_text} thresh={self.prediction_threshold} "
            f"mama_diff={mama_text} dmi_plus={dmp_text} meta={meta_text} "
            f"excluded={excluded} htf4h={htf_text} xpair_usd={xpair_text} "
            f"warmup15={len(self.bars_buffer_15m)}/{self._min_warmup_bars_15m} "
            f"warmup30={len(self.bars_buffer_30m)}/{self._min_warmup_bars_30m}"
        )

        # If we already have a pending signal, do not run entry gating for new signals.
        # The pending signal will be confirmed (or expired) on 1m bars.
        if self.pending_signal is not None:
            return

        # Option B: Always apply V2-style entry gates on 15m signal bars.
        # Robust in-trade protection using cache (prevents duplicate entries on rapid bar processing)
        positions_open = list(self.cache.positions_open(instrument_id=self.instrument_id))
        orders_open = list(self.cache.orders_open(instrument_id=self.instrument_id))
        if len(positions_open) > 0 or len(orders_open) > 0:
            _py_logger.info("[FILTERED] Open position/order exists - skipping new signal")
            return

        if self._cooldown_remaining_bars > 0:
            _py_logger.info(f"[FILTERED] Entry cooldown active: remaining_bars={self._cooldown_remaining_bars}")
            self._cooldown_remaining_bars -= 1
            return

        # Excluded hours filter (still blocks trading, but metrics are logged above)
        if excluded:
            _py_logger.info(f"[FILTERED] Excluded hour/time: {bar_time}")
            return

        # ATR range filter (normalized) (still blocks trading, but metrics are logged above)
        if atr_normalized is None:
            _py_logger.info("[FILTERED] ATR unavailable")
            return
        if atr_normalized < self.min_atr or atr_normalized > self.max_atr:
            _py_logger.info(f"[FILTERED] ATR {atr_normalized:.5f} outside range [{self.min_atr}, {self.max_atr}]")
            return
        
        # Warmup check (still blocks trading, but metrics are logged above)
        if not warmup_15_ok:
            _py_logger.info(f"[FILTERED] Warmup: 15m bars {len(self.bars_buffer_15m)}/{self._min_warmup_bars_15m}")
            return
        if not warmup_30_ok:
            _py_logger.info(f"[FILTERED] Warmup: 30m bars {len(self.bars_buffer_30m)}/{self._min_warmup_bars_30m}")
            return

        # Meta-filters (still block trading, but values/results are logged above)
        if meta_ok is False:
            return

        # Confidence filter (still blocks trading, but values are logged above)
        if confidence is None:
            return
        # Determine direction-aware threshold
        direction = "LONG" if prediction == 1 else "SHORT"
        effective_threshold = self.prediction_threshold
        if direction == "LONG" and self._threshold_long > 0:
            effective_threshold = self._threshold_long
        elif direction == "SHORT" and self._threshold_short > 0:
            effective_threshold = self._threshold_short

        if confidence < effective_threshold:
            _py_logger.info(f"[FILTERED] Confidence {confidence:.3f} < {effective_threshold} ({direction})")
            return

        # HTF 4H confirmation filter
        if not self._htf_confirms_direction(direction):
            _py_logger.info(f"[FILTERED] HTF 4H confirmation rejected {direction}")
            return

        # Cross-pair USD strength confirmation filter
        if not self._xpair_confirms_direction(direction):
            _py_logger.info(f"[FILTERED] Cross-pair USD strength rejected {direction}")
            return

        # Generate trading signal
        _py_logger.debug(f"[BAR] Attempting to generate signal for {bar_time}")
        signal = self._generate_signal(
            bar,
            features=features,
            prediction=prediction,
            prediction_proba=prediction_proba,
            confidence=confidence,
        )
        if signal is None:
            _py_logger.debug(f"[BAR] No signal generated for {bar_time}")
            return

        direction, features, prediction, prediction_proba, dynamic_params, entry_atr = signal

        if self.entry_confirmation_enabled:
            # Store as pending signal and wait for confirmation
            confidence = float(prediction_proba[1]) if hasattr(prediction_proba, '__getitem__') else float(prediction_proba)
            self.pending_signal = PendingSignal(
                direction=direction,
                entry_bar=bar,
                features=features,
                prediction=prediction,
                prediction_proba=prediction_proba,
                dynamic_params=dynamic_params,
                entry_atr=entry_atr,
                confidence=confidence,
            )
            _py_logger.info(f"Signal generated: {direction} (confidence={confidence:.3f}), waiting for entry confirmation...")
        else:
            # Enter immediately (original behavior)
            _py_logger.info(f"[BAR] Executing {direction} signal immediately (confirmation disabled)")
            self._execute_signal(
                bar,
                direction,
                features,
                prediction,
                prediction_proba,
                dynamic_params,
                entry_atr,
            )

    def _predict_with_feature_names(self, features: np.ndarray):
        """Predict using model feature names when available (avoids sklearn warnings)."""
        if self.model is None:
            return None, None

        if hasattr(self.model, "feature_names_in_"):
            names = list(self.model.feature_names_in_)
            try:
                X = pd.DataFrame([features], columns=names)
                pred = self.model.predict(X)[0]
                proba = self.model.predict_proba(X)[0]
                return pred, proba
            except Exception:
                # Fallback to legacy numpy input.
                pass

        pred = self.model.predict([features])[0]
        proba = self.model.predict_proba([features])[0]
        return pred, proba

    def _calculate_features(self) -> Optional[np.ndarray]:
        """Calculate MTF features using pandas-ta.

        MUST match ml_strategy_mtf_v2.py feature logic.
        """
        if len(self.bars_buffer_15m) < self._min_warmup_bars_15m:
            return None
        if len(self.bars_buffer_30m) < self._min_warmup_bars_30m:
            return None

        data_15m = {
            'open': [float(b.open) for b in self.bars_buffer_15m],
            'high': [float(b.high) for b in self.bars_buffer_15m],
            'low': [float(b.low) for b in self.bars_buffer_15m],
            'close': [float(b.close) for b in self.bars_buffer_15m],
            'volume': [float(getattr(b, 'volume', 0.0)) for b in self.bars_buffer_15m],
            'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer_15m],
        }
        df_15m = pd.DataFrame(data_15m)
        df_15m.set_index('timestamp', inplace=True)
        df_15m = df_15m.loc[~df_15m.index.duplicated(keep='first')]

        data_30m = {
            'close': [float(b.close) for b in self.bars_buffer_30m],
            'high': [float(b.high) for b in self.bars_buffer_30m],
            'low': [float(b.low) for b in self.bars_buffer_30m],
            'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer_30m],
        }
        df_30m = pd.DataFrame(data_30m)
        df_30m.set_index('timestamp', inplace=True)
        df_30m = df_30m.loc[~df_30m.index.duplicated(keep='first')]

        try:
            # Compute meta values (used by filters regardless of model features)
            df_15m['hl2'] = (df_15m['high'] + df_15m['low']) / 2
            mama_fama = ta.mama(df_15m['hl2'], fast=0.5, slow=0.05)
            if mama_fama is None or len(mama_fama) == 0:
                self._latest_meta["mama_diff"] = None
            else:
                mama = mama_fama.iloc[:, 0]
                fama = mama_fama.iloc[:, 1]
                mama_diff = (mama - fama) / df_15m['close']
                self._latest_meta["mama_diff"] = float(mama_diff.iloc[-1])

            dmi_30m = ta.adx(df_30m['high'], df_30m['low'], df_30m['close'], length=14)
            if dmi_30m is None or len(dmi_30m) == 0:
                self._latest_meta["dmp_30m"] = None
            else:
                self._latest_meta["dmp_30m"] = float((dmi_30m.iloc[:, 1] / 100.0).iloc[-1])

            # If using the V3 50-feature model, generate that feature vector.
            if self._using_v3_model():
                row = latest_v3_row(df_15m[["open", "high", "low", "close", "volume"]])
                if row is None:
                    return None
                features = row.to_numpy(dtype=np.float64)[0]
                return features

            # If using the 40-feature RF backup model, generate that exact feature vector.
            if self._using_rf40_model():
                row = latest_rf40_row(df_15m[["open", "high", "low", "close", "volume"]])
                if row is None:
                    return None
                features = row.to_numpy(dtype=np.float64)[0]
                return features

            # === 15m Features ===
            df_15m['log_ret'] = np.log(df_15m['close'] / df_15m['close'].shift(1)) * 100

            if self._latest_meta.get("mama_diff") is None:
                return None
            df_15m['mama_diff'] = self._latest_meta["mama_diff"]

            df_15m['atr'] = ta.atr(df_15m['high'], df_15m['low'], df_15m['close'], length=14) / df_15m['close']
            df_15m['hour'] = df_15m.index.hour
            df_15m['day_of_week'] = df_15m.index.dayofweek

            # === 30m Features ===
            if dmi_30m is None or len(dmi_30m) == 0:
                return None
            df_30m['adx'] = dmi_30m.iloc[:, 0] / 100.0
            df_30m['dmp'] = dmi_30m.iloc[:, 1] / 100.0
            df_30m['dmn'] = dmi_30m.iloc[:, 2] / 100.0

            stoch_30m = ta.stoch(df_30m['high'], df_30m['low'], df_30m['close'], k=14, d=3, smooth_k=3)
            if stoch_30m is None or len(stoch_30m) == 0:
                rsi_30m = ta.rsi(df_30m['close'], length=14)
                if rsi_30m is None or len(rsi_30m) == 0:
                    return None
                rsi_val = rsi_30m.iloc[-1] / 100.0
                df_30m['stoch_k'] = rsi_val
                df_30m['stoch_d'] = rsi_val
            else:
                df_30m['stoch_k'] = stoch_30m.iloc[:, 0] / 100.0
                df_30m['stoch_d'] = stoch_30m.iloc[:, 1] / 100.0

            latest_15m = df_15m.iloc[-1]
            latest_30m = df_30m.iloc[-1]

            features = np.array([
                latest_15m['log_ret'],
                latest_15m['mama_diff'],
                latest_30m['adx'],
                latest_30m['dmp'],
                latest_30m['dmn'],
                latest_30m['stoch_k'],
                latest_30m['stoch_d'],
                latest_15m['atr'],
                latest_15m['hour'],
                latest_15m['day_of_week'],
            ], dtype=np.float64)

            if np.any(np.isnan(features)) or np.any(np.isinf(features)):
                return None
            # Update meta state from 10-feature schema
            self._latest_meta["mama_diff"] = float(features[1])
            self._latest_meta["dmp_30m"] = float(features[3])
            return features

        except Exception as e:
            _py_logger.error(f"[ERROR] Feature calculation failed: {e}")
            return None
    
    def _resample_to_30m(self):
        """Resample 15m bars to 30m using pandas."""
        if len(self.bars_buffer_15m) < 2:
            return

        data = {
            'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer_15m],
            'open': [float(b.open) for b in self.bars_buffer_15m],
            'high': [float(b.high) for b in self.bars_buffer_15m],
            'low': [float(b.low) for b in self.bars_buffer_15m],
            'close': [float(b.close) for b in self.bars_buffer_15m],
            'volume': [float(b.volume) for b in self.bars_buffer_15m],
        }

        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)

        df_30m = df.resample('30min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

        self.bars_buffer_30m.clear()
        for idx, row in df_30m.iterrows():
            class SimpleBar:
                def __init__(self, o, h, l, c, ts):
                    self.open = o
                    self.high = h
                    self.low = l
                    self.close = c
                    self.volume = 0
                    self.ts_init = ts

            # Convert pandas Timestamp to nanoseconds safely
            ts_ns = int(idx.timestamp() * 1_000_000_000) if hasattr(idx, 'timestamp') else int(idx.value)
            bar_30m = SimpleBar(row['open'], row['high'], row['low'], row['close'], ts_ns)
            self.bars_buffer_30m.append(bar_30m)

    def _check_entry_confirmation(self, current_bar: Bar):
        """Check if pending signal should be confirmed for entry using 1m bars with adaptive logic."""
        if self.pending_signal is None:
            return

        # Live-only freshness guard: do not confirm stale pending signals.
        signal_time = pd.Timestamp(self.pending_signal.signal_generation_time, unit='ns', tz='UTC')
        if not self._is_live_signal_fresh(signal_time):
            _py_logger.info(
                "[STARTUP_GUARD] Dropping stale pending signal: direction=%s signal_time=%s",
                self.pending_signal.direction,
                signal_time,
            )
            self.pending_signal = None
            return
        
        # Only check confirmation on 1m bars
        if "1-MINUTE" not in str(current_bar.bar_type):
            return
        
        self.pending_signal.bars_waited += 1
        
        # Check if we've waited too long
        if self.pending_signal.bars_waited > self.entry_max_wait_bars:
            _py_logger.info(f"Signal expired after {self.pending_signal.bars_waited} 1m bars")
            self.pending_signal = None
            return
        
        # Calculate price movement since signal
        signal_price = float(self.pending_signal.entry_bar.close)
        current_price = float(current_bar.close)
        atr = float(self.pending_signal.entry_atr)

        if atr <= 0:
            _py_logger.debug("[CONFIRM] ATR <= 0, skipping confirmation check")
            return
        
        if self.pending_signal.direction == "LONG":
            # For LONG: positive movement is favorable
            price_change = (current_price - signal_price) / atr
        else:  # SHORT
            # For SHORT: negative movement is favorable
            price_change = (signal_price - current_price) / atr
        
        # Adaptive confirmation: adjust criteria based on volatility and confidence
        required_bars = self.entry_confirmation_bars
        required_threshold = self.entry_confirmation_threshold
        
        # Adjust for volatility if enabled
        if self.volatility_adjustment_enabled and atr > 0:
            if atr >= self.volatility_high_threshold:
                required_bars = self.volatility_high_bars
                required_threshold = max(0.05, self.entry_confirmation_threshold - self.volatility_low_threshold_reduction)
                _py_logger.info(f"High volatility (ATR={atr:.5f}): Adjusted to {required_bars} bars, threshold={required_threshold} ATR")
            elif atr <= self.volatility_low_threshold:
                required_threshold = self.entry_confirmation_threshold
                _py_logger.debug(f"Low volatility (ATR={atr:.5f}): Standard threshold={required_threshold} ATR")
        
        # Adjust for high confidence signals
        if self.pending_signal.confidence >= self.high_confidence_bypass_threshold:
            required_bars = max(1, required_bars - 1)
            required_threshold = max(0.05, required_threshold - 0.05)
            _py_logger.info(f"High confidence ({self.pending_signal.confidence:.3f}): Adjusted to {required_bars} bars, threshold={required_threshold} ATR")
        
        is_favorable = price_change > required_threshold
        
        _py_logger.debug(f"[CONFIRM] Price change: {price_change:.2f} ATR, Required: {required_threshold:.2f}, Favorable: {is_favorable}")
        
        # Check if we have enough confirmation bars
        if self.pending_signal.bars_waited >= required_bars:
            if is_favorable:
                _py_logger.info(f"Entry confirmed after {self.pending_signal.bars_waited} 1m bars (movement: {price_change:+.2f} ATR)")

                # Option B safety: re-check we are still allowed to enter (flat + not cooling down)
                positions_open = list(self.cache.positions_open(instrument_id=self.instrument_id))
                orders_open = list(self.cache.orders_open(instrument_id=self.instrument_id))
                if len(positions_open) > 0 or len(orders_open) > 0:
                    _py_logger.info("[CONFIRM] Skipping entry: position or order already open")
                    self.pending_signal = None
                    return
                if self._cooldown_remaining_bars > 0:
                    _py_logger.info("[CONFIRM] Skipping entry: cooldown active")
                    self.pending_signal = None
                    return

                # Entry-time gating: session/excluded-hours check uses the confirmation bar timestamp
                entry_time = pd.Timestamp(current_bar.ts_init, unit='ns', tz='UTC')
                if not self._is_trading_allowed(entry_time.hour, entry_time.weekday(), entry_time):
                    _py_logger.info("[CONFIRM] Skipping entry: session filter")
                    self.pending_signal = None
                    return

                self._execute_signal(
                    current_bar,
                    self.pending_signal.direction,
                    self.pending_signal.features,
                    self.pending_signal.prediction,
                    self.pending_signal.prediction_proba,
                    self.pending_signal.dynamic_params,
                    self.pending_signal.entry_atr,
                    self.pending_signal.signal_generation_time,
                )
                self.pending_signal = None
            else:
                _py_logger.info(f"Entry not confirmed (movement: {price_change:+.2f} ATR, threshold: {self.entry_confirmation_threshold:+.2f})")
                # Keep waiting unless we've exceeded max wait
                if self.pending_signal.bars_waited >= self.entry_max_wait_bars:
                    self.pending_signal = None

    def _execute_signal(self, bar: Bar, direction: str, features: List[float], 
                       prediction: int, prediction_proba: np.ndarray, 
                       dynamic_params: Dict[str, float], entry_atr: float,
                       signal_generation_time: int = None):
        """Execute a confirmed trading signal."""
        # Use bar timestamp if signal_generation_time not provided
        if signal_generation_time is None:
            signal_generation_time = bar.ts_init

        # Entry-time gating: session/excluded-hours check uses the bar timestamp.
        # - Confirmation enabled: bar is the 1m bar at entry.
        # - Confirmation disabled: bar is the 15m signal bar (entry is immediate).
        entry_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        if not self._is_trading_allowed(entry_time.hour, entry_time.weekday(), entry_time):
            return
        
        # Check if we already have positions
        if len(self.active_positions) >= len(self.position_layers):
            return
        
        # Calculate SL and TP distances using normalized ATR at signal time
        # entry_atr is absolute ATR (same units as price)
        atr_normalized = float(entry_atr) / float(bar.close)
        sl_distance = atr_normalized * float(dynamic_params['sl_atr_mult'])
        tp1_distance = atr_normalized * float(dynamic_params['pos1_tp_atr_mult'])
        tp2_distance = atr_normalized * float(dynamic_params['pos2_tp_atr_mult'])
        
        # Calculate prices
        if direction == "LONG":
            sl_price = bar.close * (1 - sl_distance)
            tp1_price = bar.close * (1 + tp1_distance)
            tp2_price = bar.close * (1 + tp2_distance)
        else:  # SHORT
            sl_price = bar.close * (1 + sl_distance)
            tp1_price = bar.close * (1 - tp1_distance)
            tp2_price = bar.close * (1 - tp2_distance)
        
        # Create positions
        self._create_positions(bar, direction, sl_price, tp1_price, tp2_price, 
                              features, prediction, prediction_proba, dynamic_params, 
                              atr_normalized, entry_atr, signal_generation_time)

    def on_order_filled(self, event):
        """Handle order fills."""
        # Bracket orders (entry + SL + TP) are created via order_factory.bracket,
        # so we don't manually submit SL/TP orders here.
        return

    def on_order_accepted(self, event):
        """Track when orders are confirmed at IBKR - verify SL/TP acceptance."""
        order_id = str(event.client_order_id)
        venue_id = str(event.venue_order_id)
        
        # Check all active positions for matching order IDs
        for layer_name, pos_info in self.active_positions.items():
            if pos_info.get("sl_order_id") and order_id == str(pos_info["sl_order_id"]):
                pos_info["venue_sl_id"] = venue_id
                _py_logger.info(f"[VERIFIED] {layer_name} SL accepted: venue_id={venue_id}")
            elif pos_info.get("tp_order_id") and order_id == str(pos_info["tp_order_id"]):
                pos_info["venue_tp_id"] = venue_id
                _py_logger.info(f"[VERIFIED] {layer_name} TP accepted: venue_id={venue_id}")
            elif pos_info.get("entry_order_id") and order_id == str(pos_info["entry_order_id"]):
                pos_info["venue_entry_id"] = venue_id
                _py_logger.info(f"[VERIFIED] {layer_name} ENTRY accepted: venue_id={venue_id}")

            # Mark protection as verified if both SL and TP are accepted
            has_sl_venue = pos_info.get("venue_sl_id") is not None
            has_tp_venue = pos_info.get("venue_tp_id") is not None

            if has_sl_venue and has_tp_venue and not pos_info.get("protection_verified"):
                pos_info["protection_verified"] = True
                _py_logger.info(f"[PROTECTION_OK] {layer_name} fully protected (SL + TP accepted)")

    def on_order_rejected(self, order):
        """Handle order rejection."""
        _py_logger.warning(f"Order rejected: {order}")

    def on_order_canceled(self, order):
        """Handle order cancellation."""
        _py_logger.info(f"Order canceled: {order}")

    def on_order_expired(self, order):
        """Handle order expiration."""
        _py_logger.info(f"Order expired: {order}")

    def on_position_closed(self, position):
        """Handle position closure."""
        # Find and remove from active positions by matching entry order ID
        matched_layer = None
        for layer_name, pos_info in list(self.active_positions.items()):
            entry_oid = pos_info.get("entry_order_id")
            if entry_oid is not None:
                # Match by checking if any of the position's order IDs belong to this layer
                pos_orders = set()
                if position.opening_order_id is not None:
                    pos_orders.add(str(position.opening_order_id))
                if str(entry_oid) in pos_orders:
                    matched_layer = layer_name
                    break
            # Fallback: match by instrument if no order ID match found
            if position.instrument_id == self.instrument.id and matched_layer is None:
                matched_layer = layer_name

        if matched_layer is not None:
            del self.active_positions[matched_layer]
            _py_logger.info(f"Position {matched_layer} closed")

        # Option B: apply cooldown after trade completion
        if len(self.active_positions) == 0 and self._entry_cooldown_bars > 0:
            self._cooldown_remaining_bars = int(self._entry_cooldown_bars)


    @staticmethod
    def _parse_hours(hours_str: str) -> list:
        """Parse comma-separated hours string to list of ints."""
        if not hours_str:
            return []
        if isinstance(hours_str, list):
            return [int(h) for h in hours_str]
        return [int(h.strip()) for h in str(hours_str).split(',') if h.strip()]

    def _parse_hour_weekday_pairs(self, pairs_val):
        """
        Parse hour-weekday pairs from config.
        Accepts either a list of (hour, weekday) tuples or a string like "16-1,16-3,14-5".
        
        Returns:
            List of (hour, weekday) tuples
        """
        if not pairs_val:
            return []
        
        if isinstance(pairs_val, list):
            # Already parsed or is a list of tuples
            result = []
            for item in pairs_val:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    result.append((int(item[0]), int(item[1])))
                elif isinstance(item, str) and '-' in item:
                    # String format "16-1"
                    h, w = item.split('-', 1)
                    result.append((int(h.strip()), int(w.strip())))
            return result
        
        if isinstance(pairs_val, str):
            # Parse string format "16-1,16-3,14-5"
            result = []
            for pair_str in pairs_val.split(','):
                pair_str = pair_str.strip()
                if not pair_str:
                    continue
                if '-' in pair_str:
                    h, w = pair_str.split('-', 1)
                    result.append((int(h.strip()), int(w.strip())))
            return result
        
        return []

    def _is_trading_allowed(self, utc_hour: int, utc_weekday: int, bar_time: Optional[pd.Timestamp] = None) -> bool:
        """Check if trading is allowed at this UTC hour on this weekday."""
        # Mode options: 'disabled', 'simple', 'weekday'
        # - 'disabled': no time-based filtering at all
        # - 'simple': only enforce trade_start_hour/trade_end_hour
        # - 'weekday': enforce trade_start_hour/trade_end_hour + weekday-specific excluded hours
        if str(self._excluded_hours_mode).lower() == 'disabled':
            # Still check seasonal exclusions if enabled
            if self._seasonal_hour_exclusions_enabled:
                return self._check_seasonal_hour_weekday_allowed(utc_hour, utc_weekday, bar_time)
            return True

        if not (self.trade_start_hour <= utc_hour < self.trade_end_hour):
            return False

        if self._excluded_hours_mode == 'weekday':
            if self._config_timezone == 'EST':
                est_hour, est_weekday = self._utc_to_est(utc_hour, utc_weekday, bar_time)
                excluded = self._excluded_hours.get(est_weekday, [])
                if est_hour in excluded:
                    return False
            else:
                excluded = self._excluded_hours.get(utc_weekday, [])
                if utc_hour in excluded:
                    return False

        # Finally check seasonal hour×weekday exclusions
        if self._seasonal_hour_exclusions_enabled:
            if not self._check_seasonal_hour_weekday_allowed(utc_hour, utc_weekday, bar_time):
                return False

        return True

    def _utc_to_est(self, utc_hour: int, utc_weekday: int, utc_timestamp: Optional[pd.Timestamp] = None) -> tuple:
        """
        Convert UTC hour/weekday to US Eastern time (handles EST/EDT automatically).
        Uses datetime for proper DST handling.
        """
        from datetime import datetime, timezone
        import zoneinfo
        
        try:
            if utc_timestamp is not None:
                # Prefer pandas timezone conversion to avoid losing nanosecond precision
                # (and avoid "Discarding nonzero nanoseconds" warnings).
                if isinstance(utc_timestamp, pd.Timestamp):
                    if utc_timestamp.tzinfo is None:
                        utc_timestamp = utc_timestamp.tz_localize("UTC")
                    est_ts = utc_timestamp.tz_convert("America/New_York")
                    return est_ts.hour, est_ts.weekday()

                utc_dt = utc_timestamp
                if utc_dt.tzinfo is None:
                    utc_dt = utc_dt.replace(tzinfo=timezone.utc)
            else:
                # Create a UTC datetime for today with the given hour
                now = datetime.now(timezone.utc)
                utc_dt = now.replace(hour=utc_hour, minute=0, second=0, microsecond=0)
                
                # Adjust weekday if needed (if utc_weekday differs from current)
                days_diff = utc_weekday - now.weekday()
                if days_diff != 0:
                    from datetime import timedelta
                    utc_dt = utc_dt + timedelta(days=days_diff)
            
            # Convert to Eastern time (handles DST automatically)
            eastern = zoneinfo.ZoneInfo("America/New_York")
            est_dt = utc_dt.astimezone(eastern)
            
            return est_dt.hour, est_dt.weekday()
            
        except Exception as e:
            _py_logger.warning(f"Timezone conversion error: {e}, returning UTC values")
            return utc_hour, utc_weekday

    def _check_seasonal_hour_weekday_allowed(self, utc_hour: int, utc_weekday: int, bar_time: Optional[pd.Timestamp] = None) -> bool:
        """
        Check if trading is allowed based on seasonal hour×weekday exclusions.
        Always operates in EST timezone (hour×weekday pairs are defined in EST).
        
        Args:
            utc_hour: Hour in UTC (0-23)
            utc_weekday: Weekday in UTC (0=Monday, 6=Sunday)
            bar_time: Optional timestamp for precise timezone conversion
            
        Returns:
            True if allowed, False if excluded
        """
        # Convert UTC to EST
        est_hour, est_weekday = self._utc_to_est(utc_hour, utc_weekday, bar_time)
        
        # Convert Python weekday (0=Mon, 6=Sun) to ISO format (1=Mon, 7=Sun) for config consistency
        est_weekday_iso = est_weekday + 1
        
        # Determine season from bar_time or current date
        if bar_time is not None:
            month = bar_time.month
        else:
            from datetime import datetime
            month = datetime.now().month
        
        # DJF = Dec, Jan, Feb (12, 1, 2)
        # MAM = Mar, Apr, May (3, 4, 5)
        # JJA = Jun, Jul, Aug (6, 7, 8)
        # SON = Sep, Oct, Nov (9, 10, 11)
        if month in [12, 1, 2]:
            excluded_pairs = self._djf_excluded_hour_weekday_pairs
        elif month in [3, 4, 5]:
            excluded_pairs = self._mam_excluded_hour_weekday_pairs
        elif month in [6, 7, 8]:
            excluded_pairs = self._jja_excluded_hour_weekday_pairs
        elif month in [9, 10, 11]:
            excluded_pairs = self._son_excluded_hour_weekday_pairs
        else:
            excluded_pairs = []
        
        # Check if this (hour, weekday) pair is excluded
        for ex_hour, ex_weekday in excluded_pairs:
            if est_hour == ex_hour and est_weekday_iso == ex_weekday:
                return False
        
        return True

    def _log_signal(self, entry_time: pd.Timestamp, prediction: int, 
                   prediction_proba: np.ndarray, dynamic_params: Dict[str, float]) -> None:
        """Log trading signal with dynamic parameters."""
        signal_data = {
            'timestamp': entry_time.isoformat(),
            'prediction': prediction,
            'confidence': max(prediction_proba),
            'sl_mult': dynamic_params['sl_atr_mult'],
            'tp_mult': dynamic_params['pos1_tp_atr_mult']
        }
        
        # Log to file (append mode)
        log_file = Path("logs/strategy_signals_v2_entry_confirmed.csv")
        log_file.parent.mkdir(exist_ok=True)
        
        file_exists = log_file.exists()
        with open(log_file, 'a', newline='') as f:
            import csv
            writer = csv.DictWriter(f, fieldnames=signal_data.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(signal_data)

    def _reset_layers(self):
        """Reset position layers after all positions are closed."""
        self._init_position_layers()

    def on_stop(self):
        """Strategy cleanup."""
        _py_logger.info("Strategy stopped")

    def _generate_signal(
        self,
        bar: Bar,
        features: Optional[np.ndarray] = None,
        prediction: Optional[int] = None,
        prediction_proba: Optional[np.ndarray] = None,
        confidence: Optional[float] = None,
    ) -> Optional[Tuple]:
        """Generate trading signal using ML model."""
        try:
            bar_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')

            # Features/pred/conf are computed in on_bar for consistent logging.
            if features is None or prediction is None or prediction_proba is None or confidence is None:
                return None
            
            # Convert prediction to direction
            direction = "LONG" if prediction == 1 else "SHORT"
            
            # Use configured SL/TP multipliers (avoid hidden dynamic overrides)
            dynamic_params = {
                'sl_atr_mult': float(self.sl_atr_mult),
                'pos1_tp_atr_mult': float(self.pos1_tp_atr_mult),
                'pos2_tp_atr_mult': float(self.pos2_tp_atr_mult),
            }

            # Optional: adjust SL multiplier based on confidence tiers
            dynamic_params['sl_atr_mult'] = self._sl_mult_for_confidence(
                float(confidence),
                float(dynamic_params['sl_atr_mult']),
            )

            # Compute ATR using the same normalized ATR method as classic V2
            atr_normalized = self._calculate_atr_normalized()
            if atr_normalized is None:
                return None
            entry_atr = float(atr_normalized) * float(bar.close)
            
            _py_logger.info(
                f"[SIGNAL] Generated {direction} signal at {bar_time}, confidence: {confidence:.3f}"
            )
            if self._confidence_sl_enabled:
                _py_logger.info(
                    "[CONF_SL] conf=%.3f sl_atr_mult=%.2f base_sl_atr_mult=%.2f",
                    float(confidence),
                    float(dynamic_params['sl_atr_mult']),
                    float(self.sl_atr_mult),
                )
            return direction, features, prediction, prediction_proba, dynamic_params, entry_atr
        except Exception as e:
            _py_logger.error(f"Error generating signal: {e}")
            import traceback
            _py_logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _check_meta_filters(self) -> bool:
        """Check additional meta-filters to avoid toxic regimes identified in analysis."""
        mama_diff = self._latest_meta.get("mama_diff")
        dmp_30m = self._latest_meta.get("dmp_30m")

        if self._meta_filter_params.get('mama_enabled', False):
            min_diff = float(self._meta_filter_params.get('mama_min_diff', 0.0))
            if mama_diff is None:
                _py_logger.info("[FILTERED] MAMA Diff unavailable")
                return False
            if mama_diff < min_diff:
                _py_logger.info(f"[FILTERED] MAMA Diff {mama_diff:.6f} < {min_diff}")
                return False
            _py_logger.info(f"[META_FILTER] MAMA Diff {mama_diff:.6f} >= {min_diff} PASS")

        if self._meta_filter_params.get('dmi_enabled', False):
            min_dmp = float(self._meta_filter_params.get('dmi_min_dmp', 0.0))
            if dmp_30m is None:
                _py_logger.info("[FILTERED] DMI+ unavailable")
                return False
            if dmp_30m < min_dmp:
                _py_logger.info(f"[FILTERED] DMI+ {dmp_30m:.4f} < {min_dmp}")
                return False
            _py_logger.info(f"[META_FILTER] DMI+ {dmp_30m:.4f} >= {min_dmp} PASS")

        return True

    def _generate_features(self, bar: Bar) -> Optional[List[float]]:
        """Generate features for ML prediction."""
        features = self._calculate_features()
        if features is None:
            return None
        return features.tolist()
        
    def _update_atr(self, bar: Bar):
        """Update ATR calculation."""
        # Add current bar's high-low range
        high_low = float(bar.high) - float(bar.low)
        high_close = abs(float(bar.high) - float(self.bars_buffer_15m[-2].close)) if len(self.bars_buffer_15m) >= 2 else 0
        low_close = abs(float(bar.low) - float(self.bars_buffer_15m[-2].close)) if len(self.bars_buffer_15m) >= 2 else 0
        true_range = max(high_low, high_close, low_close)
        
        self._atr_values.append(true_range)
        
        # Calculate ATR if we have enough data
        if len(self._atr_values) >= self._atr_window:
            self._current_atr = sum(self._atr_values) / len(self._atr_values)
        else:
            self._current_atr = true_range  # Use current TR as fallback 

    def _get_current_atr(self) -> Optional[float]:
        """Get current ATR value."""
        if len(self._atr_values) < self._atr_window:
            return None
        return np.mean(self._atr_values)

    def _calculate_atr_normalized(self) -> Optional[float]:
        """Calculate normalized ATR from 15m bars (matches classic V2)."""
        if len(self.bars_buffer_15m) < 14:
            return None

        highs = [float(b.high) for b in self.bars_buffer_15m]
        lows = [float(b.low) for b in self.bars_buffer_15m]
        closes = [float(b.close) for b in self.bars_buffer_15m]

        df = pd.DataFrame({'high': highs, 'low': lows, 'close': closes})
        atr = ta.atr(df['high'], df['low'], df['close'], length=14)
        if atr is None or atr.empty:
            return None
        return float(atr.iloc[-1]) / float(closes[-1])

    def _quantity_from_units(self, units: int) -> Quantity:
        instrument = self.cache.instrument(self.instrument_id)
        if instrument is None:
            return Quantity.from_int(units)

        precision = int(instrument.size_precision)
        quant = Decimal("1").scaleb(-precision)
        value = Decimal(units).quantize(quant)
        return Quantity.from_str(format(value, "f"))

    def _create_positions(self, bar: Bar, direction: str, sl_price: float, 
                         tp1_price: float, tp2_price: float, features: List[float],
                         prediction: int, prediction_proba: np.ndarray,
                         dynamic_params: Dict[str, float], atr_normalized: float, entry_atr: float,
                         signal_generation_time: int = None):
        """Create positions with dynamic SL/TP and signal time tracking."""
        
        entry_price = float(bar.close)
        entry_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        
        # Use bar timestamp if signal_generation_time not provided
        if signal_generation_time is None:
            signal_generation_time = bar.ts_init
        
        # Update position layer TP multipliers with dynamic values
        self.position_layers["POS1"]["tp_atr_mult"] = dynamic_params['pos1_tp_atr_mult']
        if "POS2" in self.position_layers:
            self.position_layers["POS2"]["tp_atr_mult"] = dynamic_params['pos2_tp_atr_mult']
        if "POS3" in self.position_layers:
            self.position_layers["POS3"]["tp_atr_mult"] = float(self.pos3_tp_atr_mult)
        
        # Create each position layer
        for layer_name, layer in self.position_layers.items():
            if layer_name in self.active_positions:
                continue
            
            # Determine order side
            order_side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL

            size_int = int(layer["size"])
            if size_int <= 0:
                continue

            size = self._quantity_from_units(size_int)

            tag_prefix = f"EC_{layer_name}"
            tp_price = tp1_price if layer_name == "POS1" else tp2_price

            # Encode signal generation time as base36 for compact SL/TP tags
            signal_time_s = int(signal_generation_time // 1_000_000_000)
            def _to_base36(value: int) -> str:
                alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                if value <= 0:
                    return "0"
                result = ""
                n = value
                while n:
                    n, r = divmod(n, 36)
                    result = alphabet[r] + result
                return result
            signal_time_code = _to_base36(signal_time_s)

            bracket = self.order_factory.bracket(
                instrument_id=self.instrument_id,
                order_side=order_side,
                quantity=size,
                sl_trigger_price=Price.from_str(f"{float(sl_price):.5f}"),
                tp_price=Price.from_str(f"{float(tp_price):.5f}"),
                tp_post_only=False,
                entry_tags=[tag_prefix],
                sl_tags=[f"SL{signal_time_code}"],
                tp_tags=[f"TP{signal_time_code}"],
            )

            # Track order IDs before submission
            entry_order_id = None
            sl_order_id = None
            tp_order_id = None
            
            for order in bracket.orders:
                if isinstance(order, MarketOrder):
                    entry_order_id = order.client_order_id
                elif isinstance(order, StopMarketOrder):
                    sl_order_id = order.client_order_id
                elif isinstance(order, LimitOrder):
                    tp_order_id = order.client_order_id
            
            # CRITICAL: Submit bracket atomically to ensure SL/TP are linked to entry
            self.submit_order_list(bracket)
            
            _py_logger.info(f"[SUBMIT] {layer_name}: {direction} {size} units @ MARKET, SL={sl_price:.5f}, TP={tp_price:.5f}")
            _py_logger.info(f"[ORDER_IDS] {layer_name} Entry={entry_order_id}, SL={sl_order_id}, TP={tp_order_id}")
            
            # Verify bracket orders are in cache
            try:
                open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
                _py_logger.info(f"[VERIFICATION] Open orders after {layer_name} submission: {len(open_orders)} orders")
                for order in open_orders:
                    order_type = type(order).__name__
                    _py_logger.info(f"  - {order_type}: {order.client_order_id} (status: {order.status})")
            except Exception as e:
                _py_logger.warning(f"[VERIFICATION] Could not verify open orders: {e}")
            
            # Store position info with FAIL-SAFE tracking
            self.active_positions[layer_name] = {
                "direction": direction,
                "entry_price": entry_price,
                "entry_time": entry_time,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "size": layer["size"],
                "features": dict(zip(self._current_feature_names(), features)),
                "entry_atr": atr_normalized,
                "prediction_conf": max(prediction_proba),
                "dynamic_params": dynamic_params,
                "entry_order_id": entry_order_id,
                "sl_order_id": sl_order_id,
                "tp_order_id": tp_order_id,
                # FAIL-SAFE tracking
                "submission_time": self.clock.timestamp_ns(),
                "grace_period_ns": 30_000_000_000,  # 30 seconds
                "protection_verified": False,
                "failed_protection_checks": 0,
                "max_failed_checks": 3,
            }
            
            # Store features for logging
            layer["entry_features"] = dict(zip(self._current_feature_names(), features))
            
            _py_logger.info(f"[SUBMITTED] {layer_name} bracket order submitted to IBKR")
            _py_logger.info(f"  Dynamic SL: {dynamic_params['sl_atr_mult']:.2f}x, TP: {dynamic_params['pos1_tp_atr_mult']:.2f}x")

    def _maybe_check_position_protection(self) -> None:
        """Rate-limited wrapper for _check_position_protection."""
        now_ns = int(self.clock.timestamp_ns())
        if (now_ns - int(self._last_protection_check_ns)) < int(self._protection_check_interval_ns):
            return
        self._last_protection_check_ns = now_ns
        self._check_position_protection()

    def _is_position_protected(self, layer_name: str, pos_info: Dict) -> bool:
        """Verify position has active SL and TP orders."""
        
        # 1. Check if we're still in grace period
        time_since_submission = self.clock.timestamp_ns() - pos_info["submission_time"]
        if time_since_submission < pos_info["grace_period_ns"]:
            return True  # Still in grace period, assume OK
        
        # 2. Check if we already verified protection (SL/TP accepted)
        if pos_info.get("protection_verified"):
            return True  # Already confirmed, no need to re-check
        
        # 3. Get open orders from cache
        open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
        
        # 4. Look for our specific SL and TP orders by client_order_id
        has_sl = any(str(o.client_order_id) == str(pos_info.get("sl_order_id")) 
                     for o in open_orders)
        has_tp = any(str(o.client_order_id) == str(pos_info.get("tp_order_id")) 
                     for o in open_orders)
        
        # 5. Alternative: check by venue IDs (if accepted)
        if not has_sl and pos_info.get("venue_sl_id"):
            has_sl = any(str(o.venue_order_id) == str(pos_info["venue_sl_id"]) 
                         for o in open_orders)
        if not has_tp and pos_info.get("venue_tp_id"):
            has_tp = any(str(o.venue_order_id) == str(pos_info["venue_tp_id"]) 
                         for o in open_orders)
        
        return has_sl and has_tp

    def _check_position_protection(self):
        """Periodic check: verify all positions have SL/TP."""
        
        for layer_name, pos_info in list(self.active_positions.items()):
            
            if self._is_position_protected(layer_name, pos_info):
                # Position is protected, reset counter
                pos_info["failed_protection_checks"] = 0
                continue
            
            # Position NOT protected - increment counter
            pos_info["failed_protection_checks"] += 1
            failed_count = pos_info["failed_protection_checks"]
            max_fails = pos_info["max_failed_checks"]
            
            _py_logger.warning(
                f"[PROTECTION_CHECK] {layer_name} protection check FAILED "
                f"({failed_count}/{max_fails})"
            )
            
            # Only flatten after multiple consecutive failures
            if failed_count >= max_fails:
                _py_logger.error(f"[FAIL-SAFE] {layer_name} UNPROTECTED after {failed_count} checks - FLATTENING")
                self._emergency_flatten(layer_name, "Missing SL/TP orders")

    def _emergency_flatten(self, layer_name: str, reason: str):
        """Emergency position close with detailed logging."""
        
        _py_logger.error("=" * 80)
        _py_logger.error(f"[EMERGENCY FLATTEN] Closing {layer_name}")
        _py_logger.error(f"[REASON] {reason}")
        _py_logger.error(f"[TIME] {self.clock.timestamp_ns()}")
        
        # Log current state
        pos_info = self.active_positions.get(layer_name)
        if pos_info:
            _py_logger.error(f"[POSITION] Direction: {pos_info['direction']}, Size: {pos_info['size']}")
            _py_logger.error(f"[ORDER_IDS] Entry: {pos_info.get('entry_order_id')}")
            _py_logger.error(f"[ORDER_IDS] SL: {pos_info.get('sl_order_id')}")
            _py_logger.error(f"[ORDER_IDS] TP: {pos_info.get('tp_order_id')}")
            _py_logger.error(f"[VENUE_IDS] SL: {pos_info.get('venue_sl_id')}")
            _py_logger.error(f"[VENUE_IDS] TP: {pos_info.get('venue_tp_id')}")
        
        # Log all open orders
        open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
        _py_logger.error(f"[OPEN_ORDERS] Count: {len(open_orders)}")
        for order in open_orders:
            _py_logger.error(f"  - {type(order).__name__}: {order.client_order_id} (venue: {order.venue_order_id})")
        
        # Log all open positions
        open_positions = list(self.cache.positions_open(instrument_id=self.instrument_id))
        _py_logger.error(f"[OPEN_POSITIONS] Count: {len(open_positions)}")
        for pos in open_positions:
            _py_logger.error(f"  - {pos.id}: {pos.quantity} units")
        
        _py_logger.error("=" * 80)
        
        # Flatten the position
        self.flatten_all_positions(self.instrument_id)
        
        # Clear tracking
        if layer_name in self.active_positions:
            del self.active_positions[layer_name]
        self.pending_signal = None

