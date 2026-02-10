"""
MLSignalStrategy V2 with Adaptive Entry Confirmation Logic

This is a modified version of ml_strategy_mtf_v2_entry_confirmed.py with adaptive
entry confirmation logic to improve performance by dynamically adjusting confirmation
criteria based on market volatility and bypassing strict confirmation for high-confidence signals.
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

# Feature names
FEATURE_NAMES = ["log_ret", "mama_diff", "adx", "dmp", "dmn", "stoch_k", "stoch_d", "atr", "hour", "day_of_week"]

# Setup logging
_py_logger = logging.getLogger("MLSignalStrategy_V2_EntryConfirmedAdaptive")
_py_logger.setLevel(logging.INFO)

def get_dynamic_sl_tp(entry_time: pd.Timestamp) -> Dict[str, float]:
    return {'sl_atr_mult': 1.4, 'pos1_tp_atr_mult': 0.6, 'pos2_tp_atr_mult': 1.5}

def get_meta_filter_params() -> Dict[str, Any]:
    return {'mama_enabled': False, 'mama_min_diff': 0.0000, 'dmi_enabled': False, 'dmi_min_dmp': 0.20}

class MLSignalStrategyV2EntryConfirmedAdaptiveConfig(StrategyConfig, kw_only=True):
    instrument_id: str
    bar_type: str
    model_path: str = "models/ml_model_mtf.pkl"
    total_position_size: int = 100000
    pos1_fraction: float = 0.85
    pos2_fraction: float = 0.15
    pos3_fraction: float = 0.0
    sl_atr_mult: float = 1.4
    pos1_tp_atr_mult: float = 0.6
    pos2_tp_atr_mult: float = 1.5
    pos3_tp_atr_mult: float = 2.0
    trailing_distance_atr_mult: float = 0.4
    prediction_threshold: float = 0.55
    trade_start_hour: int = 7
    trade_end_hour: int = 20
    entry_cooldown_bars: int = 0
    excluded_hours_mode: str = "simple"
    config_timezone: str = "UTC"
    excluded_hours_monday: list[int] = []
    excluded_hours_tuesday: list[int] = []
    excluded_hours_wednesday: list[int] = []
    excluded_hours_thursday: list[int] = []
    excluded_hours_friday: list[int] = []
    excluded_hours_saturday: list[int] = []
    excluded_hours_sunday: list[int] = []
    min_atr: float = 0.0003
    max_atr: float = 0.005
    entry_confirmation_enabled: bool = True
    entry_confirmation_bars: int = 3
    entry_confirmation_threshold: float = 0.15
    entry_max_wait_bars: int = 5
    high_confidence_bypass_threshold: float = 0.8
    volatility_adjustment_enabled: bool = True
    volatility_high_threshold: float = 0.003
    volatility_low_threshold: float = 0.001
    volatility_high_bars: int = 2
    volatility_low_threshold_reduction: float = 0.05
    confidence_sl_enabled: bool = False
    confidence_sl_tiers: str = ""
    confidence_sl_interpolate: bool = False
    seasonal_hour_exclusions_enabled: bool = False
    djf_excluded_hour_weekday_pairs: list = []
    mam_excluded_hour_weekday_pairs: list = []
    jja_excluded_hour_weekday_pairs: list = []
    son_excluded_hour_weekday_pairs: list = []

class PendingSignal:
    def __init__(self, direction: str, entry_bar: Bar, features: List[float], prediction: int, prediction_proba: np.ndarray, dynamic_params: Dict[str, float], entry_atr: float, confidence: float):
        self.direction = direction
        self.entry_bar = entry_bar
        self.features = features
        self.prediction = prediction
        self.prediction_proba = prediction_proba
        self.dynamic_params = dynamic_params
        self.entry_atr = entry_atr
        self.confidence = confidence
        self.bars_waited = 0
        self.created_time = entry_bar.ts_event
        self.signal_generation_time = entry_bar.ts_init  # Track when signal was generated

class MLSignalStrategyV2EntryConfirmedAdaptive(Strategy):
    """
    ML-based trading strategy with dynamic SL/TP and adaptive entry confirmation.
    
    This version enhances entry confirmation logic to filter out premature entries
    by dynamically adjusting confirmation criteria based on market volatility and
    bypassing strict confirmation for high-confidence signals.
    """
    
    def __init__(self, config: MLSignalStrategyV2EntryConfirmedAdaptiveConfig):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.model_path = config.model_path
        self.total_size = config.total_position_size
        self._pos1_fraction = config.pos1_fraction
        self._pos2_fraction = config.pos2_fraction
        self._pos3_fraction = config.pos3_fraction
        self.sl_atr_mult = config.sl_atr_mult
        self.pos1_tp_atr_mult = config.pos1_tp_atr_mult
        self.pos2_tp_atr_mult = config.pos2_tp_atr_mult
        self.pos3_tp_atr_mult = config.pos3_tp_atr_mult
        self.trailing_distance_atr_mult = config.trailing_distance_atr_mult
        self.prediction_threshold = config.prediction_threshold
        self.trade_start_hour = config.trade_start_hour
        self.trade_end_hour = config.trade_end_hour
        self._entry_cooldown_bars = int(config.entry_cooldown_bars)
        self._cooldown_remaining_bars = 0
        self.min_atr = config.min_atr
        self.max_atr = config.max_atr
        self._excluded_hours_mode = str(config.excluded_hours_mode)
        self._config_timezone = str(config.config_timezone).upper()
        self._excluded_hours = {i: self._parse_hours(getattr(config, f"excluded_hours_{day}")) for i, day in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
        self.entry_confirmation_enabled = config.entry_confirmation_enabled
        self.entry_confirmation_bars = config.entry_confirmation_bars
        self.entry_confirmation_threshold = config.entry_confirmation_threshold
        self.entry_max_wait_bars = config.entry_max_wait_bars
        self.high_confidence_bypass_threshold = config.high_confidence_bypass_threshold
        self.volatility_adjustment_enabled = config.volatility_adjustment_enabled
        self.volatility_high_threshold = config.volatility_high_threshold
        self.volatility_low_threshold = config.volatility_low_threshold
        self.volatility_high_bars = config.volatility_high_bars
        self.volatility_low_threshold_reduction = config.volatility_low_threshold_reduction
        self._confidence_sl_enabled = bool(getattr(config, "confidence_sl_enabled", False))
        self._confidence_sl_tiers_raw = str(getattr(config, "confidence_sl_tiers", "") or "").strip()
        self._confidence_sl_tiers = self._parse_confidence_sl_tiers(self._confidence_sl_tiers_raw)
        self._confidence_sl_interpolate = bool(getattr(config, "confidence_sl_interpolate", False))
        self._seasonal_hour_exclusions_enabled = bool(getattr(config, "seasonal_hour_exclusions_enabled", False))
        self._djf_excluded_hour_weekday_pairs = self._parse_hour_weekday_pairs(getattr(config, "djf_excluded_hour_weekday_pairs", []))
        self._mam_excluded_hour_weekday_pairs = self._parse_hour_weekday_pairs(getattr(config, "mam_excluded_hour_weekday_pairs", []))
        self._jja_excluded_hour_weekday_pairs = self._parse_hour_weekday_pairs(getattr(config, "jja_excluded_hour_weekday_pairs", []))
        self._son_excluded_hour_weekday_pairs = self._parse_hour_weekday_pairs(getattr(config, "son_excluded_hour_weekday_pairs", []))
        self.instrument: Optional[Instrument] = None
        self.model = None
        self.pending_signal: Optional[PendingSignal] = None
        self.active_positions: Dict[str, Position] = {}
        self.position_layers: Dict[str, Dict] = {}
        self._meta_filter_enabled = False
        self._meta_filter_params = {}
        self._init_position_layers()
        self._load_model()
        self._latest_meta: Dict[str, Optional[float]] = {"mama_diff": None, "dmp_30m": None}
        self._atr_values = []
        self._atr_window = 14
        self.bars_buffer_15m = deque(maxlen=100)
        self.bars_buffer_30m = deque(maxlen=50)
        self._min_warmup_bars_15m = 50
        self._min_warmup_bars_30m = 25
        self._atr_values = deque(maxlen=14)
        self._atr_window = 14
        _py_logger.info("MLSignalStrategy V2 Entry Confirmed Adaptive initialized")
        _py_logger.info(f"Entry confirmation: {'ENABLED' if self.entry_confirmation_enabled else 'DISABLED'}")
        _py_logger.info(f"Confirmation bars: {self.entry_confirmation_bars}, threshold: {self.entry_confirmation_threshold} ATR")
        _py_logger.info(f"High confidence bypass threshold: {self.high_confidence_bypass_threshold}")
        _py_logger.info(f"Volatility adjustment: {'ENABLED' if self.volatility_adjustment_enabled else 'DISABLED'}")
        if self.volatility_adjustment_enabled:
            _py_logger.info(f"Volatility thresholds: high={self.volatility_high_threshold}, low={self.volatility_low_threshold}")

    def _parse_hours(self, hours_str: list) -> list:
        """Parse a list of hours into a list of integers."""
        if not hours_str:
            return []
        return [int(h) for h in hours_str if isinstance(h, (int, str)) and str(h).isdigit()]

    def _parse_hour_weekday_pairs(self, pairs: list) -> list:
        """Parse list of hour-weekday pairs into list of tuples."""
        if not pairs:
            return []
        result = []
        for pair in pairs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                try:
                    hour, weekday = int(pair[0]), int(pair[1])
                    if 0 <= hour <= 23 and 1 <= weekday <= 7:
                        result.append((hour, weekday))
                except (ValueError, TypeError):
                    continue
        return result
    
    def on_start(self):
        """Initialize strategy by subscribing to necessary data streams."""
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

    def _check_entry_confirmation(self, bar: Bar):
        """Check if pending signal is confirmed based on 1-minute bar data."""
        if self.pending_signal is None:
            return

        self.pending_signal.bars_waited += 1
        entry_price = float(self.pending_signal.entry_bar.close)
        current_price = float(bar.close)
        atr = self.pending_signal.entry_atr if self.pending_signal.entry_atr > 0 else 0.001
        price_diff = current_price - entry_price if self.pending_signal.direction == "LONG" else entry_price - current_price
        atr_movement = price_diff / atr if atr > 0 else 0.0

        # Determine dynamic confirmation criteria based on volatility and confidence
        required_bars = self.entry_confirmation_bars
        required_threshold = self.entry_confirmation_threshold

        if self.volatility_adjustment_enabled and atr > 0:
            if atr >= self.volatility_high_threshold:
                required_bars = self.volatility_high_bars
                required_threshold = max(0.05, self.entry_confirmation_threshold - self.volatility_low_threshold_reduction)
                _py_logger.info(f"High volatility (ATR={atr:.5f}): Adjusted confirmation to {required_bars} bars, threshold={required_threshold} ATR")
            elif atr <= self.volatility_low_threshold:
                required_threshold = self.entry_confirmation_threshold
                _py_logger.info(f"Low volatility (ATR={atr:.5f}): Standard confirmation threshold={required_threshold} ATR")

        if self.pending_signal.confidence >= self.high_confidence_bypass_threshold:
            required_bars = max(1, required_bars - 1)
            required_threshold = max(0.05, required_threshold - 0.05)
            _py_logger.info(f"High confidence ({self.pending_signal.confidence:.3f}): Adjusted confirmation to {required_bars} bars, threshold={required_threshold} ATR")

        confirmed = False
        if atr_movement >= required_threshold:
            confirmed = True
            _py_logger.info(f"Signal confirmed: ATR movement {atr_movement:.3f} >= {required_threshold} after {self.pending_signal.bars_waited} bars")
        elif self.pending_signal.bars_waited >= self.entry_max_wait_bars:
            _py_logger.info(f"Signal expired: Waited {self.pending_signal.bars_waited} bars, max wait {self.entry_max_wait_bars}")
            self.pending_signal = None
            return
        elif self.pending_signal.bars_waited >= required_bars:
            confirmed = True
            _py_logger.info(f"Signal confirmed: Waited required {required_bars} bars with movement {atr_movement:.3f}")

        if confirmed:
            self._execute_signal(
                bar,
                self.pending_signal.direction,
                self.pending_signal.features,
                self.pending_signal.prediction,
                self.pending_signal.prediction_proba,
                self.pending_signal.dynamic_params,
                self.pending_signal.entry_atr,
                self.pending_signal.signal_generation_time
            )
            self.pending_signal = None

    def _execute_signal(self, bar: Bar, direction: str, features: List[float],
                       prediction: int, prediction_proba: np.ndarray,
                       dynamic_params: Dict[str, float], entry_atr: float,
                       signal_generation_time: int):
        """Execute a confirmed trading signal with signal time tracking."""
        entry_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        if not self._is_trading_allowed(entry_time.hour, entry_time.weekday(), entry_time):
            return
        
        if len(self.active_positions) >= len(self.position_layers):
            return
        
        atr_normalized = float(entry_atr) / float(bar.close)
        sl_distance = atr_normalized * float(dynamic_params['sl_atr_mult'])
        tp1_distance = atr_normalized * float(dynamic_params['pos1_tp_atr_mult'])
        tp2_distance = atr_normalized * float(dynamic_params['pos2_tp_atr_mult'])
        
        if direction == "LONG":
            sl_price = bar.close * (1 - sl_distance)
            tp1_price = bar.close * (1 + tp1_distance)
            tp2_price = bar.close * (1 + tp2_distance)
        else:
            sl_price = bar.close * (1 + sl_distance)
            tp1_price = bar.close * (1 - tp1_distance)
            tp2_price = bar.close * (1 - tp2_distance)
        
        self._create_positions(bar, direction, sl_price, tp1_price, tp2_price,
                              features, prediction, prediction_proba, dynamic_params,
                              atr_normalized, entry_atr, signal_generation_time)

    def _create_positions(self, bar: Bar, direction: str, sl_price: float,
                         tp1_price: float, tp2_price: float, features: List[float],
                         prediction: int, prediction_proba: np.ndarray,
                         dynamic_params: Dict[str, float], atr_normalized: float,
                         entry_atr: float, signal_generation_time: int):
        """Create positions with signal time tracking in order tags."""
        entry_price = float(bar.close)
        entry_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        
        self.position_layers["POS1"]["tp_atr_mult"] = dynamic_params['pos1_tp_atr_mult']
        if "POS2" in self.position_layers:
            self.position_layers["POS2"]["tp_atr_mult"] = dynamic_params['pos2_tp_atr_mult']
        if "POS3" in self.position_layers:
            self.position_layers["POS3"]["tp_atr_mult"] = dynamic_params['pos2_tp_atr_mult']
        
        for layer_name, layer in self.position_layers.items():
            if layer_name in self.active_positions:
                continue
            
            order_side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
            size_int = int(layer["size"])
            if size_int <= 0:
                continue

            size = self._quantity_from_units(size_int)
            tag_prefix = f"EC_{layer_name}"
            tp_price = tp1_price if layer_name == "POS1" else tp2_price

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
                # Keep these tags short to avoid Nautilus truncation.
                sl_tags=[f"SL{signal_time_code}"],
                tp_tags=[f"TP{signal_time_code}"],
            )

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
            
            self.submit_order_list(bracket)
            
            _py_logger.info(f"[SUBMIT] {layer_name}: {direction} {size} units @ MARKET, SL={sl_price:.5f}, TP={tp_price:.5f}")
            _py_logger.info(f"[ORDER_IDS] {layer_name} Entry={entry_order_id}, SL={sl_order_id}, TP={tp_order_id}")
            _py_logger.info(f"[SIGNAL_TIME] Signal generated at {signal_generation_time}")
            
            self.active_positions[layer_name] = {
                "direction": direction,
                "entry_price": entry_price,
                "entry_time": entry_time,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "size": layer["size"],
                "entry_atr": atr_normalized,
                "prediction_conf": max(prediction_proba),
                "dynamic_params": dynamic_params,
                "entry_order_id": entry_order_id,
                "sl_order_id": sl_order_id,
                "tp_order_id": tp_order_id,
                "signal_generation_time": signal_generation_time,
            }

    def _quantity_from_units(self, units: int) -> Quantity:
        instrument = self.cache.instrument(self.instrument_id)
        if instrument is None:
            return Quantity.from_int(units)
        precision = int(instrument.size_precision)
        quant = Decimal("1").scaleb(-precision)
        value = Decimal(units).quantize(quant)
        return Quantity.from_str(format(value, "f"))

    def _is_trading_allowed(self, utc_hour: int, utc_weekday: int, bar_time: Optional[pd.Timestamp] = None) -> bool:
        """Check if trading is allowed at this UTC hour on this weekday."""
        if str(self._excluded_hours_mode).lower() == 'disabled':
            return True
        if not (self.trade_start_hour <= utc_hour < self.trade_end_hour):
            return False
        if self._excluded_hours_mode == 'weekday':
            if self._config_timezone == 'EST':
                from run_backtest_mtf_v2_replay import utc_to_est
                est_hour, est_weekday = utc_to_est(bar_time.to_pydatetime() if bar_time else datetime.now(timezone.utc))
                excluded = self._excluded_hours.get(est_weekday, [])
                if est_hour in excluded:
                    return False
            else:
                excluded = self._excluded_hours.get(utc_weekday, [])
                if utc_hour in excluded:
                    return False
        return True

    def on_bar(self, bar: Bar):
        if hasattr(self, "one_min_bar_type") and bar.bar_type == self.one_min_bar_type:
            if self.pending_signal is not None:
                self._check_entry_confirmation(bar)
            return

    def _extract_features(self, bar: Bar):
        """Extract features from bar data for prediction."""
        if not self.bars_buffer_15m or len(self.bars_buffer_15m) < 2:
            return None
        
        latest_bar = bar
        prev_bar = list(self.bars_buffer_15m)[-2] if len(self.bars_buffer_15m) >= 2 else None
        features = {}
        
        # Simple feature extraction as placeholder; full implementation would be more detailed
        if prev_bar:
            features['price_diff'] = float(latest_bar.close) - float(prev_bar.close)
            features['atr'] = self._calculate_atr()
            features['volatility'] = float(latest_bar.high) - float(latest_bar.low)
        else:
            features['price_diff'] = 0.0
            features['atr'] = 0.001
            features['volatility'] = 0.0
        
        return features

    def _predict(self, features: dict):
        """Make a prediction using the loaded ML model."""
        if self.model is None:
            _py_logger.error("No model loaded for prediction")
            return 0, 0.0
        
        try:
            feature_values = [features.get('price_diff', 0.0), features.get('atr', 0.001), features.get('volatility', 0.0)]
            prediction = self.model.predict([feature_values])[0]
            prediction_proba = self.model.predict_proba([feature_values])[0][1] if hasattr(self.model, 'predict_proba') else 0.5
            return prediction, prediction_proba
        except Exception as e:
            _py_logger.error(f"Prediction error: {e}")
            return 0, 0.0

    def _calculate_atr(self):
        """Calculate Average True Range (ATR) from recent bars."""
        if len(self._atr_values) < self._atr_window:
            return 0.001  # Default small value if not enough data
        return sum(self._atr_values) / len(self._atr_values) if self._atr_values else 0.001

    def _parse_confidence_sl_tiers(self, tiers_str: str) -> List[Tuple[float, float]]:
        tiers: List[Tuple[float, float]] = []
        raw = str(tiers_str or "").strip()
        if not raw:
            return tiers
        for part in raw.split(","):
            item = part.strip()
            if not item or ":" not in item:
                continue
            left, right = item.split(":", 1)
            try:
                min_conf = float(left.strip())
                sl_mult = float(right.strip())
                if 0.0 <= min_conf <= 1.0 and sl_mult > 0.0:
                    tiers.append((min_conf, sl_mult))
            except Exception:
                continue
        tiers.sort(key=lambda x: x[0])
        return tiers

    def _init_position_layers(self):
        self.position_layers = {"POS1": {"fraction": self._pos1_fraction, "tp_atr_mult": self.pos1_tp_atr_mult, "size": int(self.total_size * self._pos1_fraction), "entry_features": {}}}
        if self._pos2_fraction > 0:
            self.position_layers["POS2"] = {"fraction": self._pos2_fraction, "tp_atr_mult": self.pos2_tp_atr_mult, "size": int(self.total_size * self._pos2_fraction), "entry_features": {}}
        if self._pos3_fraction > 0:
            self.position_layers["POS3"] = {"fraction": self._pos3_fraction, "tp_atr_mult": self.pos3_tp_atr_mult, "size": int(self.total_size * self._pos3_fraction), "entry_features": {}}

    def _load_model(self):
        try:
            self.model = joblib.load(self.model_path)
            _py_logger.info(f"Loaded ML model from {self.model_path}")
        except Exception as e:
            _py_logger.error(f"Failed to load ML model: {e}")
            raise
