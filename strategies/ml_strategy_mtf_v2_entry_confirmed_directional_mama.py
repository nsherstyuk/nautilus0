"""
MLSignalStrategy V2 with Entry Confirmation and Directional MAMA Filter

This version implements direction-aware MAMA/FAMA filtering:
- LONG signals require MAMA > FAMA (bullish trend alignment)
- SHORT signals require MAMA < FAMA (bearish trend alignment)
- Symmetric threshold logic for both directions

Key changes from base version:
- Added entry confirmation filter using 1-minute bar momentum
- Direction-aware MAMA filter (allows both bullish and bearish signals)
- Only enters trades if price moves favorably in the first 1-2 bars
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

# Feature names (matching the 10-feature model)
FEATURE_NAMES = [
    "log_ret", "mama_diff", "dmp_30m", "dmn_30m", "stoch_k_30m", "stoch_d_30m",
    "wma_diff_30m", "atr_15m", "hour", "day_of_week"
]

# Setup logging
_py_logger = logging.getLogger("MLSignalStrategy_V2_EntryConfirmed_DirectionalMAMA")
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

class MLSignalStrategyV2EntryConfirmedConfig(StrategyConfig, kw_only=True):
    """Configuration for MLSignalStrategy V2 with Entry Confirmation."""
    
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

class PendingSignal:
    """Stores a pending signal waiting for entry confirmation."""
    
    def __init__(self, direction: str, entry_bar: Bar, features: List[float], 
                 prediction: int, prediction_proba: np.ndarray, dynamic_params: Dict[str, float],
                 entry_atr: float):
        self.direction = direction
        self.entry_bar = entry_bar
        self.features = features
        self.prediction = prediction
        self.prediction_proba = prediction_proba
        self.dynamic_params = dynamic_params
        self.entry_atr = entry_atr
        self.bars_waited = 0
        self.created_time = entry_bar.ts_event

class MLSignalStrategyV2EntryConfirmed(Strategy):
    """
    ML-based trading strategy with dynamic SL/TP and entry confirmation.
    
    This version adds entry confirmation logic to filter out premature entries
    based on the analysis showing that good entries move favorably immediately
    while premature entries move against us first.
    """
    
    def __init__(self, config: MLSignalStrategyV2EntryConfirmedConfig):
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
        
        # Strategy state
        self.instrument: Optional[Instrument] = None
        self.model = None
        self.pending_signal: Optional[PendingSignal] = None
        
        # Position tracking
        self.active_positions: Dict[str, Position] = {}
        self.position_layers: Dict[str, Dict] = {}
        
        # Meta-filters state
        self._meta_filter_enabled = False
        self._meta_filter_params = {}
        
        # Initialize position layers
        self._init_position_layers()
        
        # Load model
        self._load_model()
        
        # Initialize ATR tracking
        self._atr_values = []
        self._atr_window = 14  # 14-period ATR
        
        # Initialize bar buffers
        self.bars_buffer_15m = deque(maxlen=100)
        self.bars_buffer_30m = deque(maxlen=50)
        self._min_warmup_bars_15m = 50
        self._min_warmup_bars_30m = 25
        self._atr_values = deque(maxlen=14)
        self._atr_window = 14

        _py_logger.info("MLSignalStrategy V2 Entry Confirmed initialized")
        _py_logger.info(f"Entry confirmation: {'ENABLED' if self.entry_confirmation_enabled else 'DISABLED'}")
        _py_logger.info(f"Confirmation bars: {self.entry_confirmation_bars}, threshold: {self.entry_confirmation_threshold} ATR")

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

    def on_start(self):
        """Initialize strategy."""
        # Subscribe to both 15m (signal) and 1m (confirmation) bars
        os.environ["MTF2_REPLAY_MODE"] = "1"  # Force replay mode for backtest
        
        # Subscribe to 15m bars for signals
        self.subscribe_bars(self.bar_type)
        
        # Subscribe to 1m bars for confirmation
        bar_type_str = str(self.bar_type)
        one_min_bar_type_str = bar_type_str.replace("15-MINUTE", "1-MINUTE")
        self.one_min_bar_type = BarType.from_str(one_min_bar_type_str)
        self.subscribe_bars(self.one_min_bar_type)
        _py_logger.info(f"Subscribed to {self.bar_type} and {self.one_min_bar_type}")
        
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
            return

        # Only 15m bars drive signal generation and feature updates
        if bar.bar_type != self.bar_type:
            return
        
        bar_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')

        # Add to 15m buffer
        self.bars_buffer_15m.append(bar)

        # Create 30m bars from 15m data
        self._resample_to_30m()

        # Update ATR
        self._update_atr(bar)

        _py_logger.info(
            f"[BAR] {bar_time} close={float(bar.close):.5f} 15m={len(self.bars_buffer_15m)} 30m={len(self.bars_buffer_30m)}"
        )

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
                prediction = int(self.model.predict([features])[0])
                prediction_proba = self.model.predict_proba([features])[0]
                confidence = float(max(prediction_proba))
                mama_diff = float(features[1])
                dmp_30m = float(features[2])

                if self._meta_filter_enabled:
                    meta_ok = self._check_meta_filters(features, prediction)
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

        _py_logger.info(
            f"[BAR_METRICS] {bar_time} close={float(bar.close):.5f} atr={atr_text} "
            f"pred={pred_text} conf={conf_text} thresh={self.prediction_threshold} "
            f"mama_diff={mama_text} dmi_plus={dmp_text} meta={meta_text} "
            f"excluded={excluded} warmup15={len(self.bars_buffer_15m)}/{self._min_warmup_bars_15m} "
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
        if confidence < self.prediction_threshold:
            _py_logger.info(f"[FILTERED] Confidence {confidence:.3f} < {self.prediction_threshold}")
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
            self.pending_signal = PendingSignal(
                direction=direction,
                entry_bar=bar,
                features=features,
                prediction=prediction,
                prediction_proba=prediction_proba,
                dynamic_params=dynamic_params,
                entry_atr=entry_atr
            )
            _py_logger.info(f"Signal generated: {direction}, waiting for entry confirmation...")
        else:
            # Enter immediately (original behavior)
            _py_logger.info(f"[BAR] Executing {direction} signal immediately (confirmation disabled)")
            self._execute_signal(bar, direction, features, prediction, 
                               prediction_proba, dynamic_params, entry_atr)

    def _calculate_features(self) -> Optional[np.ndarray]:
        """Calculate MTF features using pandas-ta.

        MUST match ml_strategy_mtf_v2.py feature logic.
        """
        if len(self.bars_buffer_15m) < self._min_warmup_bars_15m:
            return None
        if len(self.bars_buffer_30m) < self._min_warmup_bars_30m:
            return None

        data_15m = {
            'close': [float(b.close) for b in self.bars_buffer_15m],
            'high': [float(b.high) for b in self.bars_buffer_15m],
            'low': [float(b.low) for b in self.bars_buffer_15m],
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
            # === 15m Features ===
            df_15m['log_ret'] = np.log(df_15m['close'] / df_15m['close'].shift(1)) * 100
            df_15m['hl2'] = (df_15m['high'] + df_15m['low']) / 2

            mama_fama = ta.mama(df_15m['hl2'], fast=0.5, slow=0.05)
            if mama_fama is None or len(mama_fama) == 0:
                return None
            df_15m['mama'] = mama_fama.iloc[:, 0]
            df_15m['fama'] = mama_fama.iloc[:, 1]
            df_15m['mama_diff'] = (df_15m['mama'] - df_15m['fama']) / df_15m['close']

            df_15m['atr'] = ta.atr(df_15m['high'], df_15m['low'], df_15m['close'], length=14) / df_15m['close']
            df_15m['hour'] = df_15m.index.hour
            df_15m['day_of_week'] = df_15m.index.dayofweek

            # === 30m Features ===
            dmi_30m = ta.adx(df_30m['high'], df_30m['low'], df_30m['close'], length=14)
            if dmi_30m is None or len(dmi_30m) == 0:
                return None
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

            wma_short = ta.wma(df_30m['close'], length=8)
            wma_long = ta.wma(df_30m['close'], length=23)
            if wma_short is not None and wma_long is not None and len(wma_short) > 0 and len(wma_long) > 0:
                df_30m['wma_diff'] = 100 * (wma_short - wma_long) / wma_long
            else:
                sma_short = ta.sma(df_30m['close'], length=8)
                sma_long = ta.sma(df_30m['close'], length=23)
                if sma_short is None or sma_long is None or len(sma_short) == 0 or len(sma_long) == 0:
                    return None
                df_30m['wma_diff'] = 100 * (sma_short - sma_long) / sma_long

            latest_15m = df_15m.iloc[-1]
            latest_30m = df_30m.iloc[-1]

            features = np.array([
                latest_15m['log_ret'],
                latest_15m['mama_diff'],
                latest_30m['dmp'],
                latest_30m['dmn'],
                latest_30m['stoch_k'],
                latest_30m['stoch_d'],
                latest_30m['wma_diff'],
                latest_15m['atr'],
                latest_15m['hour'],
                latest_15m['day_of_week'],
            ], dtype=np.float64)

            if np.any(np.isnan(features)) or np.any(np.isinf(features)):
                return None
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

            bar_30m = SimpleBar(row['open'], row['high'], row['low'], row['close'], int(idx.value))
            self.bars_buffer_30m.append(bar_30m)

    def _check_entry_confirmation(self, current_bar: Bar):
        """Check if pending signal should be confirmed for entry using 1m bars."""
        if self.pending_signal is None:
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
            is_favorable = price_change > self.entry_confirmation_threshold
        else:  # SHORT
            # For SHORT: negative movement is favorable
            price_change = (signal_price - current_price) / atr
            is_favorable = price_change > self.entry_confirmation_threshold
        
        _py_logger.debug(f"[CONFIRM] Price change: {price_change:.2f} ATR, Favorable: {is_favorable}")
        
        # Check if we have enough confirmation bars
        if self.pending_signal.bars_waited >= self.entry_confirmation_bars:
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
                    self.pending_signal.entry_atr
                )
                self.pending_signal = None
            else:
                _py_logger.info(f"Entry not confirmed (movement: {price_change:+.2f} ATR, threshold: {self.entry_confirmation_threshold:+.2f})")
                # Keep waiting unless we've exceeded max wait
                if self.pending_signal.bars_waited >= self.entry_max_wait_bars:
                    self.pending_signal = None

    def _execute_signal(self, bar: Bar, direction: str, features: List[float], 
                       prediction: int, prediction_proba: np.ndarray, 
                       dynamic_params: Dict[str, float], entry_atr: float):
        """Execute a confirmed trading signal."""

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
                              atr_normalized, entry_atr)

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
        # Find and remove from active positions
        for layer_name, pos_info in list(self.active_positions.items()):
            if position.instrument_id == self.instrument.id:
                del self.active_positions[layer_name]
                _py_logger.info(f"Position {layer_name} closed")
                break

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

    def _is_trading_allowed(self, utc_hour: int, utc_weekday: int, bar_time: Optional[pd.Timestamp] = None) -> bool:
        """Check if trading is allowed at this UTC hour on this weekday."""
        if not (self.trade_start_hour <= utc_hour < self.trade_end_hour):
            return False

        # Mode options: 'disabled', 'simple', 'weekday'
        # 'simple' mode: no hour exclusions, only check trade_start_hour/trade_end_hour
        # 'weekday' mode: apply weekday-specific excluded hours
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

            # Compute ATR using the same normalized ATR method as classic V2
            atr_normalized = self._calculate_atr_normalized()
            if atr_normalized is None:
                return None
            entry_atr = float(atr_normalized) * float(bar.close)
            
            _py_logger.info(f"[SIGNAL] Generated {direction} signal at {bar_time}, confidence: {confidence:.3f}")
            return direction, features, prediction, prediction_proba, dynamic_params, entry_atr
        except Exception as e:
            _py_logger.error(f"Error generating signal: {e}")
            import traceback
            _py_logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _check_meta_filters(self, features: np.ndarray, prediction: int) -> bool:
        """
        Check additional meta-filters with direction-aware logic.
        
        Direction-aware MAMA filter:
        - LONG signals (prediction=1): Require MAMA > FAMA (bullish trend)
        - SHORT signals (prediction=0): Require MAMA < FAMA (bearish trend)
        - Symmetric threshold logic for both directions
        """
        # 0: log_ret, 1: mama_diff, 2: dmp, 3: dmn, 4: stoch_k, 5: stoch_d,
        # 6: wma_diff, 7: atr, 8: hour, 9: day_of_week
        mama_diff = float(features[1])
        dmp_30m = float(features[2])

        if self._meta_filter_params.get('mama_enabled', False):
            min_diff = float(self._meta_filter_params.get('mama_min_diff', 0.0))
            
            # Direction-aware MAMA filter
            if prediction == 1:  # LONG signal
                # Require MAMA > FAMA (bullish trend alignment)
                if mama_diff < min_diff:
                    _py_logger.info(f"[FILTERED] LONG signal: MAMA Diff {mama_diff:.6f} < {min_diff} (need bullish trend)")
                    return False
                _py_logger.info(f"[META_FILTER] LONG: MAMA Diff {mama_diff:.6f} >= {min_diff} PASS")
            else:  # SHORT signal (prediction == 0)
                # Require MAMA < FAMA (bearish trend alignment)
                if mama_diff > -min_diff:
                    _py_logger.info(f"[FILTERED] SHORT signal: MAMA Diff {mama_diff:.6f} > {-min_diff} (need bearish trend)")
                    return False
                _py_logger.info(f"[META_FILTER] SHORT: MAMA Diff {mama_diff:.6f} <= {-min_diff} PASS")

        if self._meta_filter_params.get('dmi_enabled', False):
            min_dmp = float(self._meta_filter_params.get('dmi_min_dmp', 0.0))
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
                         dynamic_params: Dict[str, float], atr_normalized: float, entry_atr: float):
        """Create positions with dynamic SL/TP."""
        
        entry_price = float(bar.close)
        entry_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        
        # Update position layer TP multipliers with dynamic values
        self.position_layers["POS1"]["tp_atr_mult"] = dynamic_params['pos1_tp_atr_mult']
        if "POS2" in self.position_layers:
            self.position_layers["POS2"]["tp_atr_mult"] = dynamic_params['pos2_tp_atr_mult']
        if "POS3" in self.position_layers:
            self.position_layers["POS3"]["tp_atr_mult"] = dynamic_params['pos2_tp_atr_mult']
        
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

            bracket = self.order_factory.bracket(
                instrument_id=self.instrument_id,
                order_side=order_side,
                quantity=size,
                sl_trigger_price=Price.from_str(f"{float(sl_price):.5f}"),
                tp_price=Price.from_str(f"{float(tp_price):.5f}"),
                tp_post_only=False,
                entry_tags=[tag_prefix],
                sl_tags=[f"{tag_prefix}_SL"],
                tp_tags=[f"{tag_prefix}_TP"],
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
            
            # Store position info
            self.active_positions[layer_name] = {
                "direction": direction,
                "entry_price": entry_price,
                "entry_time": entry_time,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "size": layer["size"],
                "features": dict(zip(FEATURE_NAMES, features)),
                "entry_atr": atr_normalized,
                "prediction_conf": max(prediction_proba),
                "dynamic_params": dynamic_params,
                "entry_order_id": entry_order_id,
                "sl_order_id": sl_order_id,
                "tp_order_id": tp_order_id,
            }
            
            # Store features for logging
            layer["entry_features"] = dict(zip(FEATURE_NAMES, features))
            
            _py_logger.info(f"[SUBMITTED] {layer_name} bracket order submitted to IBKR")
            _py_logger.info(f"  Dynamic SL: {dynamic_params['sl_atr_mult']:.2f}x, TP: {dynamic_params['pos1_tp_atr_mult']:.2f}x")
