"""
MLSignalStrategy V2 - Three-Position Bracket Approach

Instead of one position with multi-layer partial closes, this strategy opens
three separate positions simultaneously, each with its own bracket order:

Position 1 (Quick Win): 70% size, SL=1.4 ATR, TP=0.9 ATR
Position 2 (Extended):  25% size, SL=1.4 ATR, TP=1.75 ATR  
Position 3 (Runner):     5% size, SL=1.4 ATR, TP=1.75 ATR (converts to trailing)

Progression:
1. All 3 positions open with independent brackets (native IBKR OCO)
2. When Pos1 TP hits -> Adjust Pos2 & Pos3 SL to breakeven+1pip
3. When Pos2 TP hits -> Convert Pos3 SL to trailing stop

Advantages over V1:
- Native IBKR bracket orders (no OCA recreation)
- Simpler state management
- More robust protection
"""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional, Dict, List, Any
import os
import logging
import json
import csv
import numpy as np
import pandas as pd
import pandas_ta as ta
import joblib

from strategies.feature_engineering_v2_rf40 import latest_rf40_row

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.data import Data
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.orders import MarketOrder, StopMarketOrder, LimitOrder
from nautilus_trader.model.position import Position
from nautilus_trader.trading.strategy import Strategy

# Setup file-based logging
_py_logger = logging.getLogger("MLSignalStrategy_V2")
_py_logger.setLevel(logging.INFO)

FEATURE_NAMES = [
    "log_ret", "mama_diff", "adx", "dmp", "dmn", "stoch_k", "stoch_d",
    "atr", "hour", "day_of_week"
]

@dataclass
class PositionLayer:
    """Track state for each position layer."""
    name: str  # "POS1", "POS2", "POS3"
    size_fraction: float  # 0.7, 0.2, 0.1
    tp_atr_mult: float  # 0.9, 1.75, 1.75
    
    # Runtime state
    entry_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    venue_sl_id: Optional[str] = None
    venue_tp_id: Optional[str] = None
    
    is_open: bool = False
    is_closed: bool = False
    entry_price: Optional[float] = None
    entry_time: Optional[pd.Timestamp] = None
    sl_adjusted_to_be: bool = False  # SL moved to breakeven?
    converted_to_trailing: bool = False
    
    # Feature logging
    entry_features: Optional[Dict[str, Any]] = None


class MLSignalStrategyV2Config(StrategyConfig, kw_only=True):
    """Configuration for MLSignalStrategy V2."""
    
    instrument_id: str
    bar_type: str
    model_path: str = "models/rf_model_mtf.joblib"
    
    # Position sizing (total = 100k, split into 2)
    # OPTIMIZED Dec 2025: 85/15 two-position bracket
    # PnL: $38,421 | WR: 69.6% | Sharpe: 9.91 | Neg Days: 63 | Neg Months: 0
    total_position_size: int = 100000
    pos1_fraction: float = 0.85  # Quick win (85%)
    pos2_fraction: float = 0.15  # Extended (15%)
    pos3_fraction: float = 0.00  # Disabled in 2-position mode
    
    # Stop loss (same for all positions initially)
    sl_atr_mult: float = 1.4
    
    # Take profit (different for each position)
    pos1_tp_atr_mult: float = 0.6   # Quick win target
    pos2_tp_atr_mult: float = 1.5   # Extended target
    pos3_tp_atr_mult: float = 1.5   # Runner target (unused in 2-position mode)
    
    # Trailing stop for Position 2 (in 2-position mode after POS1 TP)
    trailing_activation_atr_mult: float = 0.6
    trailing_distance_atr_mult: float = 0.4
    
    # Prediction settings
    prediction_threshold: float = 0.55
    
    # Session filtering
    trade_start_hour: int = 7
    trade_end_hour: int = 20
    entry_cooldown_bars: int = 0
    
    # Weekday-specific excluded hours
    excluded_hours_mode: str = "simple"  # 'simple' or 'weekday'
    config_timezone: str = "UTC"  # 'EST' or 'UTC' - timezone for excluded hours
    excluded_hours_monday: str = ""
    excluded_hours_tuesday: str = ""
    excluded_hours_wednesday: str = ""
    excluded_hours_thursday: str = ""
    excluded_hours_friday: str = ""
    excluded_hours_saturday: str = ""
    excluded_hours_sunday: str = ""
    
    # Risk management
    min_atr: float = 0.0003
    max_atr: float = 0.005
    max_positions: int = 2  # Allows 2 simultaneous positions (2-position mode)
    
    # Stall detection (tighten SL if trade not progressing to TP1)
    stall_detection_enabled: bool = False
    stall_check_bars: int = 6
    stall_min_profit_atr: float = 0.2
    stall_sl_atr: float = 0.2
    
    # Meta-Filters (derived from feature analysis)
    meta_filter_mama_enabled: bool = False
    meta_filter_mama_min_diff: float = 0.0000  # Filter out negative MAMA diff
    meta_filter_dmi_enabled: bool = False
    meta_filter_dmi_min_dmp: float = 0.20      # Filter out low DMI+
    
    # Order identification
    order_id_tag: str = "V2"


class MLSignalStrategyV2(Strategy):
    """
    Three-position bracket strategy with progressive SL adjustment.
    """
    
    def __init__(self, config: MLSignalStrategyV2Config):
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
        self.pos1_size = Quantity.from_int(int(self.total_size * config.pos1_fraction))
        self.pos2_size = Quantity.from_int(int(self.total_size * config.pos2_fraction))
        self.pos3_size = Quantity.from_int(int(self.total_size * config.pos3_fraction))
        
        # ATR multipliers
        self.sl_atr_mult = config.sl_atr_mult
        self.pos1_tp_mult = config.pos1_tp_atr_mult
        self.pos2_tp_mult = config.pos2_tp_atr_mult
        self.pos3_tp_mult = config.pos3_tp_atr_mult
        self.trailing_activation_mult = config.trailing_activation_atr_mult
        self.trailing_distance_mult = config.trailing_distance_atr_mult
        
        # Prediction
        self.prediction_threshold = config.prediction_threshold
        self.min_atr = config.min_atr
        self.max_atr = config.max_atr
        
        # Session
        self.trade_start_hour = config.trade_start_hour
        self.trade_end_hour = config.trade_end_hour
        self._entry_cooldown_bars = config.entry_cooldown_bars
        self._cooldown_remaining_bars = 0
        
        # Weekday-specific excluded hours
        self._excluded_hours_mode = config.excluded_hours_mode
        self._config_timezone = config.config_timezone.upper()  # 'EST' or 'UTC'
        self._excluded_hours = {
            0: self._parse_hours(config.excluded_hours_monday),    # Monday
            1: self._parse_hours(config.excluded_hours_tuesday),   # Tuesday
            2: self._parse_hours(config.excluded_hours_wednesday), # Wednesday
            3: self._parse_hours(config.excluded_hours_thursday),  # Thursday
            4: self._parse_hours(config.excluded_hours_friday),    # Friday
            5: self._parse_hours(config.excluded_hours_saturday),  # Saturday
            6: self._parse_hours(config.excluded_hours_sunday),    # Sunday
        }
        
        # Data buffers
        self.bars_buffer_15m = deque(maxlen=100)
        self.bars_buffer_30m = deque(maxlen=50)
        
        # Model
        self.model = None
        self._load_model()

        # Meta values (computed alongside features)
        self._latest_meta: Dict[str, Optional[float]] = {"mama_diff": None, "dmp_30m": None}
        
        # Position layers state
        self._layers: Dict[str, PositionLayer] = {}
        self._reset_layers()
        
        # Trade state
        self._trade_direction: Optional[str] = None  # "LONG" or "SHORT"
        self._entry_atr: Optional[float] = None
        self._entry_price: Optional[float] = None
        self._order_id_tag = config.order_id_tag
        self._max_positions = config.max_positions
        
        # Stall detection
        self._stall_detection_enabled = config.stall_detection_enabled
        self._stall_check_bars = config.stall_check_bars
        self._stall_min_profit_atr = config.stall_min_profit_atr
        self._stall_sl_atr = config.stall_sl_atr
        self._bars_in_trade = 0
        self._max_profit_atr = 0.0
        self._stall_sl_applied = False

        self._neg_stall_enabled = os.getenv("MTF2_NEG_STALL_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
        self._neg_stall_check_bars = int(os.getenv("MTF2_NEG_STALL_CHECK_BARS", "8"))
        self._neg_stall_max_profit_atr = float(os.getenv("MTF2_NEG_STALL_MAX_PROFIT_ATR", "0.0"))
        self._neg_stall_trigger_loss_atr = float(os.getenv("MTF2_NEG_STALL_TRIGGER_LOSS_ATR", "0.4"))
        self._neg_stall_triggered = False
        
        # Meta-filters
        self.meta_filter_mama_enabled = config.meta_filter_mama_enabled
        self.meta_filter_mama_min_diff = config.meta_filter_mama_min_diff
        self.meta_filter_dmi_enabled = config.meta_filter_dmi_enabled
        self.meta_filter_dmi_min_dmp = config.meta_filter_dmi_min_dmp
        
        # Warmup
        self._warmup_mode = True
        self._min_warmup_bars_15m = 30
        self._min_warmup_bars_30m = 25  # Need more for WMA(23) + Stochastic(14)
        
        # Feature logging setup
        self._feature_log_path = Path("backtest_results") / "ml_trade_features.csv"
        self._init_feature_log()
        
        _py_logger.info("MLSignalStrategyV2 initialized - Three-position bracket approach")
        
    def _init_feature_log(self):
        """Initialize feature log file with header."""
        if not self._feature_log_path.parent.exists():
            self._feature_log_path.parent.mkdir(parents=True, exist_ok=True)
            
        if not self._feature_log_path.exists():
            with open(self._feature_log_path, 'w', newline='') as f:
                writer = csv.writer(f)
                header = [
                    "trade_id", "entry_time", "direction", "result_type", 
                    "pnl_currency", "pnl_pips", "duration_bars",
                    "entry_atr", "prediction_conf"
                ] + self._current_feature_names()
                writer.writerow(header)

    def _reset_layers(self):
        """Reset all position layer tracking."""
        self._layers = {
            "POS1": PositionLayer(name="POS1", size_fraction=self._pos1_fraction, tp_atr_mult=self.pos1_tp_mult),
            "POS2": PositionLayer(name="POS2", size_fraction=self._pos2_fraction, tp_atr_mult=self.pos2_tp_mult),
            "POS3": PositionLayer(name="POS3", size_fraction=self._pos3_fraction, tp_atr_mult=self.pos3_tp_mult),
        }
        self._trade_direction = None
        self._entry_atr = None
        self._entry_price = None
        # Reset stall detection
        self._bars_in_trade = 0
        self._max_profit_atr = 0.0
        self._stall_sl_applied = False
        self._neg_stall_triggered = False
        
    def _load_model(self):
        """Load ML model."""
        try:
            model_path = Path(self.model_path)
            if not model_path.is_absolute():
                project_root = Path(__file__).parent.parent
                model_path = project_root / model_path
            self.model = joblib.load(model_path)
            _py_logger.info(f"Model loaded from {model_path}")
            if hasattr(self.model, "feature_names_in_"):
                _py_logger.info(f"Model features: {list(self.model.feature_names_in_)}")
        except Exception as e:
            _py_logger.error(f"Failed to load model: {e}")
            self.model = None

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

    def _current_feature_names(self) -> list:
        if self.model is not None and hasattr(self.model, "feature_names_in_"):
            return list(self.model.feature_names_in_)
        return FEATURE_NAMES
            
    @staticmethod
    def _parse_hours(hours_str: str) -> list:
        """Parse comma-separated hours string to list of ints."""
        if not hours_str:
            return []
        return [int(h.strip()) for h in hours_str.split(',') if h.strip()]
    
    def _utc_to_est(self, utc_hour: int, utc_weekday: int, utc_timestamp: Optional[pd.Timestamp] = None) -> tuple:
        """
        Convert UTC hour/weekday to US Eastern time (handles EST/EDT automatically).
        Uses datetime for proper DST handling.
        """
        from datetime import datetime, timezone
        import zoneinfo
        
        try:
            if utc_timestamp is not None:
                utc_dt = utc_timestamp
                if isinstance(utc_dt, pd.Timestamp):
                    utc_dt = utc_dt.to_pydatetime()
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
            eastern = zoneinfo.ZoneInfo('America/New_York')
            eastern_dt = utc_dt.astimezone(eastern)
            
            return eastern_dt.hour, eastern_dt.weekday()
        except Exception:
            # Fallback to simple -5 offset if zoneinfo fails
            est_hour = utc_hour - 5
            est_weekday = utc_weekday
            if est_hour < 0:
                est_hour += 24
                est_weekday = (utc_weekday - 1) % 7
            return est_hour, est_weekday
    
    def _is_trading_allowed(self, utc_hour: int, utc_weekday: int, bar_time: Optional[pd.Timestamp] = None) -> bool:
        """
        Check if trading is allowed at this UTC hour on this weekday.
        Handles EST timezone conversion if config_timezone='EST'.
        
        Args:
            utc_hour: Hour in UTC (0-23) - from bar timestamp
            utc_weekday: Weekday in UTC (0=Monday, 6=Sunday)
        """
        # First check basic hour range (always in UTC)
        if not (self.trade_start_hour <= utc_hour < self.trade_end_hour):
            return False
        
        # Then check excluded hours (if enabled)
        # Mode options: 'disabled', 'simple', 'weekday'
        if self._excluded_hours_mode in ('simple', 'weekday'):
            if self._config_timezone == 'EST':
                # Convert UTC to EST for comparison with config
                est_hour, est_weekday = self._utc_to_est(utc_hour, utc_weekday, bar_time)
                excluded = self._excluded_hours.get(est_weekday, [])
                if est_hour in excluded:
                    return False
            else:
                # Config is in UTC, compare directly
                excluded = self._excluded_hours.get(utc_weekday, [])
                if utc_hour in excluded:
                    return False
        
        return True
            
    def on_start(self):
        """Initialize strategy."""
        # NOTE: Do NOT subscribe to bars here - bars are fed directly from ib_insync
        # The ib_bar_streamer calls on_bar() directly, bypassing NautilusTrader's data engine
        # self.subscribe_bars(self.bar_type)  # DISABLED - would cause duplicate bars
        if os.getenv("MTF2_REPLAY_MODE", "0").strip().lower() in {"1", "true", "yes"}:
            self.subscribe_bars(self.bar_type)
        _py_logger.info("Strategy started - bars fed directly from ib_insync")
        _py_logger.info(f"Instrument: {self.instrument_id}")
        _py_logger.info(f"Position sizes: POS1={int(self.total_size * self._pos1_fraction)}, POS2={int(self.total_size * self._pos2_fraction)}, POS3={int(self.total_size * self._pos3_fraction)}")
        _py_logger.info(f"TP mults: POS1={self.pos1_tp_mult}x, POS2={self.pos2_tp_mult}x | SL: {self.sl_atr_mult}x ATR")
        if self._excluded_hours_mode == 'weekday':
            _py_logger.info(f"Weekday-specific hour filtering enabled (config in {self._config_timezone})")
        
    def _log_trade_feature_row(self, layer: PositionLayer, result_type: str, pnl_currency: float, exit_time_ns: int):
        """Log trade outcome and entry features to CSV."""
        if not layer.entry_features:
            return
            
        try:
            # Calculate duration
            exit_ts = pd.Timestamp(exit_time_ns, unit='ns', tz='UTC')
            entry_ts = layer.entry_time
            duration_bars = 0
            if entry_ts:
                diff = exit_ts - entry_ts
                duration_bars = int(diff.total_seconds() / 900) # 15m bars approx
            
            # Row construction
            row = [
                f"{layer.name}_{layer.entry_order_id}", # trade_id
                entry_ts.isoformat() if entry_ts else "",
                self._trade_direction,
                result_type,
                f"{pnl_currency:.2f}",
                "0", # pnl_pips placeholder
                duration_bars,
                f"{layer.entry_features.get('entry_atr', 0):.5f}",
                f"{layer.entry_features.get('prediction_conf', 0):.3f}"
            ]
            
            # Add features
            for name in FEATURE_NAMES:
                row.append(f"{layer.entry_features.get(name, 0):.5f}")
                
            # Append to file
            with open(self._feature_log_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(row)
                
        except Exception as e:
            _py_logger.error(f"Failed to log feature row: {e}")

    # =========================================================================
    # ORDER EVENT HANDLERS
    # =========================================================================
    
    def on_order_filled(self, event):
        """Handle order fills - track position opens and closes."""
        try:
            order_id = str(event.client_order_id)
            timestamp = event.ts_event
            
            # Check which layer this order belongs to
            for layer_name, layer in self._layers.items():
                # Entry filled
                if layer.entry_order_id and order_id == str(layer.entry_order_id):
                    layer.is_open = True
                    layer.entry_price = float(event.last_px)
                    self._log_position_state(f"{layer_name} ENTRY FILLED @ {event.last_px}")
                    
                # TP filled (position closed profitably)
                elif layer.tp_order_id and order_id == str(layer.tp_order_id):
                    layer.is_open = False
                    layer.is_closed = True
                    pnl = self._calculate_pnl(layer, float(event.last_px))
                    self._log_position_state(f"{layer_name} TP HIT @ {event.last_px} (PnL: ${pnl:.2f})")
                    self._on_layer_tp_hit(layer_name)
                    self._log_trade_feature_row(layer, "TP", pnl, timestamp)
                    
                # SL filled (position closed at loss)
                elif layer.sl_order_id and order_id == str(layer.sl_order_id):
                    layer.is_open = False
                    layer.is_closed = True
                    pnl = self._calculate_pnl(layer, float(event.last_px))
                    self._log_position_state(f"{layer_name} SL HIT @ {event.last_px} (PnL: ${pnl:.2f})")
                    self._log_trade_feature_row(layer, "SL", pnl, timestamp)
                    
            # Check if all positions closed
            if all(l.is_closed or not l.is_open for l in self._layers.values()):
                if any(l.is_closed for l in self._layers.values()):
                    self._log_position_state("ALL POSITIONS CLOSED - Trade complete")
                    if self._entry_cooldown_bars > 0:
                        self._cooldown_remaining_bars = int(self._entry_cooldown_bars)
                    self._reset_layers()
        except Exception as e:
            _py_logger.error(f"[ERROR] on_order_filled exception: {e}")
            # Force check if we should reset
            try:
                positions = list(self.cache.positions_open(instrument_id=self.instrument_id))
                orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
                if len(positions) == 0 and len(orders) == 0 and self._trade_direction is not None:
                    _py_logger.warning("[RECOVERY] Resetting after on_order_filled error")
                    self._reset_layers()
            except:
                pass
                
    def on_order_accepted(self, event):
        """Track when orders are confirmed at IBKR."""
        order_id = str(event.client_order_id)
        venue_id = str(event.venue_order_id)
        
        for layer_name, layer in self._layers.items():
            if layer.sl_order_id and order_id == str(layer.sl_order_id):
                layer.venue_sl_id = venue_id
                _py_logger.info(f"[VERIFIED] {layer_name} SL accepted: venue_id={venue_id}")
            elif layer.tp_order_id and order_id == str(layer.tp_order_id):
                layer.venue_tp_id = venue_id
                _py_logger.info(f"[VERIFIED] {layer_name} TP accepted: venue_id={venue_id}")
                
    def on_order_rejected(self, event):
        """Alert on order rejections."""
        order_id = str(event.client_order_id)
        reason = getattr(event, 'reason', 'Unknown')
        _py_logger.error(f"[REJECTED] Order {order_id}: {reason}")
        self._handle_order_failure(order_id, reason)
        
    def on_order_denied(self, event):
        """Handle order denials - reset state to allow new trades."""
        order_id = str(event.client_order_id)
        reason = getattr(event, 'reason', 'Unknown')
        _py_logger.error(f"[DENIED] Order {order_id}: {reason}")
        self._handle_order_failure(order_id, reason)
        
    def _handle_order_failure(self, order_id: str, reason: str):
        """Handle failed orders - reset state if no positions are actually open."""
        # Check if we actually have any OPEN positions (not closed ones)
        positions = list(self.cache.positions_open(instrument_id=self.instrument_id))
        open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
        
        # If no positions and no open orders, reset state
        if len(positions) == 0 and len(open_orders) == 0:
            if self._trade_direction is not None:
                _py_logger.warning(f"[RESET] No positions/orders - resetting trade state after failure")
                self._reset_layers()
        
    def on_position_closed(self, event):
        """Handle position close events."""
        self.log.info(f"Position closed: {event}")
        
    # =========================================================================
    # POSITION PROGRESSION LOGIC
    # =========================================================================
    
    def _on_layer_tp_hit(self, layer_name: str):
        """Handle when a layer's TP is hit - adjust other layers."""
        
        # Check if we're in 2-position mode (POS3 fraction = 0)
        two_position_mode = self._pos3_fraction == 0
        
        if layer_name == "POS1":
            if two_position_mode:
                # 2-position mode: POS1 TP -> Move POS2 SL to BE and enable trailing
                self._log_position_state("POS1 TP -> Adjusting POS2 SL to breakeven, enabling trailing")
                self._adjust_sl_to_breakeven("POS2")
                self._convert_to_trailing("POS2")
            else:
                # 3-position mode: POS1 TP -> Move POS2 and POS3 SL to breakeven+1pip
                self._log_position_state("POS1 TP -> Adjusting POS2/POS3 SL to breakeven+1pip")
                self._adjust_sl_to_breakeven("POS2")
                self._adjust_sl_to_breakeven("POS3")
            
        elif layer_name == "POS2":
            if not two_position_mode:
                # 3-position mode only: POS2 TP hit -> Convert POS3 to trailing stop
                self._log_position_state("POS2 TP -> Converting POS3 to trailing stop")
                self._convert_to_trailing("POS3")
            
    def _adjust_sl_to_breakeven(self, layer_name: str):
        """Move a layer's SL to breakeven + 1 pip."""
        layer = self._layers.get(layer_name)
        if not layer or not layer.is_open or layer.sl_adjusted_to_be:
            return
            
        try:
            # Calculate breakeven + 1 pip
            pip_value = 0.0001
            if self._trade_direction == "LONG":
                new_sl = self._entry_price + pip_value
            else:
                new_sl = self._entry_price - pip_value
                
            # Find and modify the SL order
            self._modify_sl_order(layer, new_sl)
            layer.sl_adjusted_to_be = True
            
            _py_logger.info(f"[ADJUSTED] {layer_name} SL moved to breakeven+1pip: {new_sl:.5f}")
            
        except Exception as e:
            _py_logger.error(f"Failed to adjust {layer_name} SL: {e}")
            
    def _convert_to_trailing(self, layer_name: str):
        """Convert a layer's SL to trailing stop."""
        layer = self._layers.get(layer_name)
        if not layer or not layer.is_open or layer.converted_to_trailing:
            return
            
        try:
            # Calculate trailing stop distance
            trail_distance = self._entry_price * self._entry_atr * self.trailing_distance_mult
            
            # Get current price and calculate trail level
            # For now, use entry + activation as starting point
            activation_profit = self._entry_price * self._entry_atr * self.trailing_activation_mult
            
            if self._trade_direction == "LONG":
                new_sl = self._entry_price + activation_profit - trail_distance
            else:
                new_sl = self._entry_price - activation_profit + trail_distance
                
            self._modify_sl_order(layer, new_sl)
            layer.converted_to_trailing = True
            
            _py_logger.info(f"[TRAILING] {layer_name} SL converted to trailing: {new_sl:.5f}")
            
        except Exception as e:
            _py_logger.error(f"Failed to convert {layer_name} to trailing: {e}")
            
    def _modify_sl_order(self, layer: PositionLayer, new_price: float):
        """Modify an existing SL order to a new price."""
        if not layer.sl_order_id:
            return
            
        # Find the order in cache
        order = self.cache.order(layer.sl_order_id)
        if order:
            self.modify_order(
                order,
                trigger_price=Price.from_str(f"{new_price:.5f}")
            )
            _py_logger.info(f"Modified {layer.name} SL to {new_price:.5f}")
            
    def _update_trailing_stop(self, layer: PositionLayer, current_price: float):
        """Update trailing stop for a layer if needed."""
        if not layer.converted_to_trailing or not layer.is_open:
            return
            
        trail_distance = self._entry_price * self._entry_atr * self.trailing_distance_mult
        
        if self._trade_direction == "LONG":
            new_sl = current_price - trail_distance
            # Only move up, never down
            order = self.cache.order(layer.sl_order_id)
            if order and float(order.trigger_price) < new_sl:
                self._modify_sl_order(layer, new_sl)
        else:
            new_sl = current_price + trail_distance
            # Only move down, never up
            order = self.cache.order(layer.sl_order_id)
            if order and float(order.trigger_price) > new_sl:
                self._modify_sl_order(layer, new_sl)
    
    def _check_stall_detection(self, current_price: float):
        """
        Check for stall condition and tighten SL if trade not progressing to TP1.
        
        Rule: After X bars, if max profit is between min_profit and TP1 level,
        tighten SL to lock in some profit.
        """
        if not self._stall_detection_enabled and not self._neg_stall_enabled:
            return

        # Only apply before TP1 is hit
        pos1 = self._layers.get("POS1")
        if not pos1 or not pos1.is_open or pos1.is_closed:
            return

        # Need entry price and ATR
        if not self._entry_price or not self._entry_atr:
            return

        # Calculate current profit in ATR terms
        if self._trade_direction == "LONG":
            profit = current_price - self._entry_price
        else:
            profit = self._entry_price - current_price

        profit_atr = profit / (self._entry_price * self._entry_atr)

        self._bars_in_trade += 1
        if profit_atr > self._max_profit_atr:
            self._max_profit_atr = profit_atr

        if (
            self._neg_stall_enabled
            and not self._neg_stall_triggered
            and self._bars_in_trade >= self._neg_stall_check_bars
            and self._max_profit_atr <= self._neg_stall_max_profit_atr
            and profit_atr <= -self._neg_stall_trigger_loss_atr
        ):
            self._neg_stall_triggered = True
            _py_logger.info(
                f"[NEG_STALL] Trigger: bars={self._bars_in_trade}, max={self._max_profit_atr:.2f} ATR, curr={profit_atr:.2f} ATR -> flatten"
            )

            for layer in self._layers.values():
                if layer.is_open and not layer.is_closed:
                    layer.is_open = False
                    layer.is_closed = True

            try:
                self.cancel_all_orders(self.instrument_id)
            except Exception as e:
                _py_logger.error(f"[NEG_STALL] Failed cancel_all_orders: {e}")

            try:
                self.close_all_positions(self.instrument_id, tags=[f"{self._order_id_tag}_NEG_STALL"])
            except Exception as e:
                _py_logger.error(f"[NEG_STALL] Failed close_all_positions: {e}")

            return

        if not self._stall_detection_enabled:
            return

        if self._stall_sl_applied:
            return

        # Check stall condition
        if (
            self._bars_in_trade >= self._stall_check_bars
            and self._stall_min_profit_atr <= self._max_profit_atr < self.pos1_tp_mult
        ):
            
            # Tighten SL to lock in some profit
            sl_distance = current_price * self._entry_atr * self._stall_sl_atr
            
            if self._trade_direction == "LONG":
                new_sl = current_price - sl_distance
                
                # SAFETY: Cap SL at current price to avoid "Stop > Market" (Phantom Profit)
                if new_sl > current_price:
                    new_sl = current_price

                # Only move SL up (more protective), never down
                current_sl_order = self.cache.order(pos1.sl_order_id) if pos1.sl_order_id else None
                if current_sl_order and float(current_sl_order.trigger_price) >= new_sl:
                    _py_logger.info(f"[STALL] Skip - current SL {current_sl_order.trigger_price} already >= {new_sl:.5f}")
                    return
            else:
                new_sl = current_price + sl_distance
                
                # SAFETY: Cap SL at current price to avoid "Stop < Market" (Phantom Profit)
                if new_sl < current_price:
                    new_sl = current_price
                
                # Only move SL down (more protective), never up
                current_sl_order = self.cache.order(pos1.sl_order_id) if pos1.sl_order_id else None
                if current_sl_order and float(current_sl_order.trigger_price) <= new_sl:
                    _py_logger.info(f"[STALL] Skip - current SL {current_sl_order.trigger_price} already <= {new_sl:.5f}")
                    return
            
            # Modify POS1 SL (and POS2 if exists)
            self._modify_sl_order(pos1, new_sl)
            
            pos2 = self._layers.get("POS2")
            if pos2 and pos2.is_open and not pos2.is_closed:
                self._modify_sl_order(pos2, new_sl)
            
            self._stall_sl_applied = True
            _py_logger.info(f"[STALL] Detected after {self._bars_in_trade} bars, max={self._max_profit_atr:.2f} ATR, SL tightened to {self._stall_sl_atr} ATR ({new_sl:.5f})")
                
    # =========================================================================
    # POSITION MONITORING
    # =========================================================================
    
    def _log_position_state(self, event: str):
        """Log current state of all positions."""
        print("\n" + "=" * 70)
        print(f"[POSITION EVENT] {event}")
        print("-" * 70)
        
        for name, layer in self._layers.items():
            status = "CLOSED" if layer.is_closed else ("OPEN" if layer.is_open else "PENDING")
            sl_status = "BE" if layer.sl_adjusted_to_be else "INIT"
            trail = " [TRAILING]" if layer.converted_to_trailing else ""
            
            print(f"  {name}: {status} | SL: {sl_status}{trail} | TP: {layer.tp_atr_mult}x ATR")
            
        print("=" * 70 + "\n")
        
        # Also log to file
        _py_logger.info(f"[STATE] {event}")
        for name, layer in self._layers.items():
            status = "CLOSED" if layer.is_closed else ("OPEN" if layer.is_open else "PENDING")
            _py_logger.info(f"  {name}: {status}, SL_BE={layer.sl_adjusted_to_be}, TRAIL={layer.converted_to_trailing}")
            
    def _calculate_pnl(self, layer: PositionLayer, exit_price: float) -> float:
        """Calculate PnL for a layer."""
        if not layer.entry_price:
            return 0.0
            
        size = self.total_size * layer.size_fraction
        
        if self._trade_direction == "LONG":
            return (exit_price - layer.entry_price) * size
        else:
            return (layer.entry_price - exit_price) * size
            
    # =========================================================================
    # ENTRY EXECUTION
    # =========================================================================
    
    def _execute_entry(self, bar: Bar, atr_normalized: float, direction: str, 
                       features: np.ndarray, confidence: float):
        """Open all 3 positions with their respective brackets."""
        
        entry_price = float(bar.close)
        self._trade_direction = direction
        self._entry_atr = atr_normalized
        self._entry_price = entry_price
        entry_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        
        # Prepare feature dict for logging
        feature_dict = dict(zip(self._current_feature_names(), features))
        feature_dict["entry_atr"] = atr_normalized
        feature_dict["prediction_conf"] = confidence
        
        # Calculate SL (same for all initially)
        sl_distance = entry_price * atr_normalized * self.sl_atr_mult
        
        if direction == "LONG":
            sl_price = entry_price - sl_distance
            order_side = OrderSide.BUY
        else:
            sl_price = entry_price + sl_distance
            order_side = OrderSide.SELL
            
        self._log_position_state(f"OPENING {direction} TRADE @ {entry_price:.5f}")
        
        # Open each position layer
        for layer_name, layer in self._layers.items():
            layer.entry_features = feature_dict.copy()  # Store features for logging
            self._open_layer_position(layer, order_side, entry_price, sl_price, atr_normalized)

    def _quantity_from_units(self, units: int) -> Quantity:
        instrument = self.cache.instrument(self.instrument_id)
        if instrument is None:
            return Quantity.from_int(units)

        precision = int(instrument.size_precision)
        quant = Decimal("1").scaleb(-precision)
        value = Decimal(units).quantize(quant)
        return Quantity.from_str(format(value, "f"))
            
    def _open_layer_position(self, layer: PositionLayer, order_side: OrderSide, 
                             entry_price: float, sl_price: float, atr: float):
        """Open a single position layer with bracket order."""
        
        # Calculate size - skip if 0 (2-position mode)
        size_int = int(self.total_size * layer.size_fraction)
        if size_int == 0:
            layer.is_closed = True  # Mark as closed so it doesn't block trade completion
            _py_logger.info(f"[SKIP] {layer.name}: size=0, skipping (2-position mode)")
            return

        size = self._quantity_from_units(size_int)
        
        # Calculate TP
        tp_distance = entry_price * atr * layer.tp_atr_mult
        if order_side == OrderSide.BUY:
            tp_price = entry_price + tp_distance
        else:
            tp_price = entry_price - tp_distance
            
        # Create bracket order with unique tags
        tag_prefix = f"{self._order_id_tag}_{layer.name}"
        
        bracket = self.order_factory.bracket(
            instrument_id=self.instrument_id,
            order_side=order_side,
            quantity=size,
            sl_trigger_price=Price.from_str(f"{sl_price:.5f}"),
            tp_price=Price.from_str(f"{tp_price:.5f}"),
            tp_post_only=False,
            entry_tags=[tag_prefix],
            sl_tags=[f"{tag_prefix}_SL"],
            tp_tags=[f"{tag_prefix}_TP"]
        )
        
        # Track order IDs
        for order in bracket.orders:
            if isinstance(order, MarketOrder):
                layer.entry_order_id = order.client_order_id
                _py_logger.debug(f"[ORDER_ID] {layer.name} entry: {order.client_order_id}")
            elif isinstance(order, StopMarketOrder):
                layer.sl_order_id = order.client_order_id
                _py_logger.debug(f"[ORDER_ID] {layer.name} SL: {order.client_order_id}")
            elif isinstance(order, LimitOrder):
                layer.tp_order_id = order.client_order_id
                _py_logger.debug(f"[ORDER_ID] {layer.name} TP: {order.client_order_id}")
        
        # Log order details
        direction = "LONG" if order_side == OrderSide.BUY else "SHORT"
        _py_logger.info(
            f"[SUBMIT] {layer.name}: {direction} {size} units @ MARKET, "
            f"SL={sl_price:.5f}, TP={tp_price:.5f} ({layer.tp_atr_mult}x ATR)"
        )
                
        # Submit bracket order
        self.submit_order_list(bracket)
        _py_logger.info(f"[SUBMITTED] {layer.name} bracket order submitted to IBKR")
        
    # =========================================================================
    # BAR PROCESSING
    # =========================================================================
    
    def on_bar(self, bar: Bar):
        """Process incoming bar."""
        
        bar_time = pd.Timestamp(bar.ts_init, unit='ns', tz='UTC')
        
        # Update buffers
        self.bars_buffer_15m.append(bar)
        self._resample_to_30m()
        
        # Warmup check
        if len(self.bars_buffer_15m) < self._min_warmup_bars_15m:
            _py_logger.debug(f"[WARMUP] 15m bars: {len(self.bars_buffer_15m)}/{self._min_warmup_bars_15m}")
            return
        if len(self.bars_buffer_30m) < self._min_warmup_bars_30m:
            _py_logger.debug(f"[WARMUP] 30m bars: {len(self.bars_buffer_30m)}/{self._min_warmup_bars_30m}")
            return
            
        if self._warmup_mode:
            self._warmup_mode = False
            _py_logger.info("Warmup complete - ready to trade")
        
        # Log bar receipt
        _py_logger.info(f"[BAR] {bar_time} close={bar.close} 15m={len(self.bars_buffer_15m)} 30m={len(self.bars_buffer_30m)}")
            
        # Verify instrument is loaded before any trading operations
        # This prevents "no instrument found" errors during startup
        instrument = self.cache.instrument(self.instrument_id)
        if instrument is None:
            if not hasattr(self, '_instrument_warned'):
                _py_logger.warning("[WAITING] Instrument not loaded in cache yet - buffering bars")
                self._instrument_warned = True
            return
        elif hasattr(self, '_instrument_warned'):
            _py_logger.info(f"[READY] Instrument {instrument.id} now loaded - trading enabled")
            del self._instrument_warned
            
        # Update trailing stops if active (POS2 in 2-position mode, POS3 in 3-position mode)
        if self._layers["POS2"].converted_to_trailing:
            self._update_trailing_stop(self._layers["POS2"], float(bar.close))
        if self._layers["POS3"].converted_to_trailing:
            self._update_trailing_stop(self._layers["POS3"], float(bar.close))
        
        # Stall detection: tighten SL if trade not progressing to TP1
        self._check_stall_detection(float(bar.close))

        atr = self._calculate_atr()
        prediction = None
        confidence = None
        if self.model is not None:
            features = self._calculate_features()
            if features is not None:
                try:
                    prediction = self.model.predict([features])[0]
                    confidence = self.model.predict_proba([features])[0].max()
                    _py_logger.debug(f"[DEBUG] Features: {features[:5]}... Predicted: {prediction}, Conf: {confidence:.3f}")
                except Exception as e:
                    _py_logger.error(f"[ERROR] Prediction error: {e}")
                    _py_logger.error(f"[ERROR] Features shape: {len(features) if features is not None else 'None'}")
            else:
                _py_logger.warning(f"[WARN] Feature calculation returned None")

        atr_text = f"{atr:.5f}" if atr is not None else "NA"
        conf_text = f"{confidence:.3f}" if confidence is not None else "NA"
        pred_text = str(prediction) if prediction is not None else "NA"
        _py_logger.info(
            f"[BAR_METRICS] {bar_time} close={bar.close} atr={atr_text} pred={pred_text} conf={conf_text} thresh={self.prediction_threshold}"
        )
            
        # Check if we have any open positions (check both layer state AND cache)
        any_open = any(l.is_open for l in self._layers.values())
        
        # Also check if we have any OPEN positions in cache (more reliable during rapid bar processing)
        # Note: cache.positions() returns all positions, so we filter for open only
        positions = list(self.cache.positions_open(instrument_id=self.instrument_id))
        has_cache_positions = len(positions) > 0
        
        # Also check if orders are pending (submitted but not yet filled)
        open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
        has_pending_orders = len(open_orders) > 0
        
        # Safety check: if cache shows no positions/orders but _trade_direction is set, reset state
        if not any_open and not has_cache_positions and not has_pending_orders and self._trade_direction is not None:
            _py_logger.warning(f"[AUTO-RESET] Stale trade state detected - resetting (direction was {self._trade_direction})")
            self._reset_layers()
            # Continue to prediction logic
        elif any_open or has_cache_positions or has_pending_orders:
            _py_logger.info(f"[MONITORING] In trade - layers_open={any_open}, cache_pos={len(positions)}, orders={len(open_orders)}, direction={self._trade_direction}")
            return

        if self._cooldown_remaining_bars > 0:
            _py_logger.info(f"[FILTERED] Entry cooldown active: remaining_bars={self._cooldown_remaining_bars}")
            self._cooldown_remaining_bars -= 1
            return
            
        # Check for new entry signal
        if self.model is None:
            _py_logger.warning("[SKIP] Model not loaded")
            return
            
        # Session filter (with weekday-specific exclusions)
        hour = bar_time.hour
        weekday = bar_time.weekday()
        if not self._is_trading_allowed(hour, weekday, bar_time):
            if self._excluded_hours_mode == 'weekday':
                if self._config_timezone == 'EST':
                    est_hour, est_weekday = self._utc_to_est(hour, weekday, bar_time)
                    excluded = self._excluded_hours.get(est_weekday, [])
                    _py_logger.info(
                        f"[FILTERED] Excluded hour: utc={hour} weekday={weekday} -> est={est_hour} weekday={est_weekday} excluded={excluded}"
                    )
                else:
                    excluded = self._excluded_hours.get(weekday, [])
                    _py_logger.info(f"[FILTERED] Excluded hour: utc={hour} weekday={weekday} excluded={excluded}")
            else:
                _py_logger.info(f"[FILTERED] Hour {hour} excluded for weekday {weekday}")
            return
            
        # Calculate features and get prediction
        features = self._calculate_features()
        if features is None:
            _py_logger.debug("[SKIP] Feature calculation returned None")
            return
            
        # Check Meta-Filters (Toxic Regime Avoidance)
        if not self._check_meta_filters(features):
            return
            
        # Get prediction
        prediction = self.model.predict([features])[0]
        confidence = self.model.predict_proba([features])[0].max()
        
        _py_logger.info(f"[PREDICTION] pred={prediction}, conf={confidence:.3f}, thresh={self.prediction_threshold}")
        
        if confidence < self.prediction_threshold:
            _py_logger.info(f"[FILTERED] Confidence {confidence:.3f} < {self.prediction_threshold}")
            return
            
        # Get ATR
        atr = self._calculate_atr()
        if atr is None:
            _py_logger.debug("[SKIP] ATR calculation returned None")
            return
        if atr < self.min_atr or atr > self.max_atr:
            _py_logger.info(f"[FILTERED] ATR {atr:.5f} outside range [{self.min_atr}, {self.max_atr}]")
            return
            
        # Execute entry
        direction = "LONG" if prediction == 1 else "SHORT"
        _py_logger.info(f"[SIGNAL] {direction} - conf={confidence:.3f}, ATR={atr:.5f}")
        self._execute_entry(bar, atr, direction, features, confidence)
        
    def _check_meta_filters(self, features: np.ndarray) -> bool:
        """
        Check additional meta-filters to avoid toxic regimes identified in analysis.
        Returns True if trade is allowed, False if filtered.
        """
        mama_diff = self._latest_meta.get("mama_diff")
        dmp_30m = self._latest_meta.get("dmp_30m")
        
        # 1. MAMA Difference Filter (Trend Alignment)
        if self.meta_filter_mama_enabled:
            if mama_diff is None:
                _py_logger.info("[FILTERED] MAMA Diff unavailable")
                return False
            if mama_diff < self.meta_filter_mama_min_diff:
                _py_logger.info(f"[FILTERED] MAMA Diff {mama_diff:.6f} < {self.meta_filter_mama_min_diff}")
                return False
            else:
                _py_logger.info(f"[META_FILTER] MAMA Diff {mama_diff:.6f} >= {self.meta_filter_mama_min_diff} PASS")
                
        # 2. DMI+ Strength Filter (Directional Strength)
        if self.meta_filter_dmi_enabled:
            if dmp_30m is None:
                _py_logger.info("[FILTERED] DMI+ unavailable")
                return False
            if dmp_30m < self.meta_filter_dmi_min_dmp:
                _py_logger.info(f"[FILTERED] DMI+ {dmp_30m:.4f} < {self.meta_filter_dmi_min_dmp}")
                return False
            else:
                _py_logger.info(f"[META_FILTER] DMI+ {dmp_30m:.4f} >= {self.meta_filter_dmi_min_dmp} PASS")
                
        return True

    def _resample_to_30m(self):
        """Resample 15m bars to 30m using pandas."""
        if len(self.bars_buffer_15m) < 2:
            return
            
        # Create DataFrame from 15m bars
        data = {
            'open': [float(b.open) for b in self.bars_buffer_15m],
            'high': [float(b.high) for b in self.bars_buffer_15m],
            'low': [float(b.low) for b in self.bars_buffer_15m],
            'close': [float(b.close) for b in self.bars_buffer_15m],
            'volume': [float(b.volume) for b in self.bars_buffer_15m],
            'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer_15m]
        }
        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)
        
        # Resample to 30m
        df_30m = df.resample('30min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        # Clear 30m buffer and repopulate
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
        
    def _calculate_features(self) -> Optional[np.ndarray]:
        """
        Calculate MTF features using pandas-ta.
        MUST match train_model_mtf.py features.
        
        Features (10 total):
        1. log_ret (15m)
        2. mama_diff (15m, hl2 source)
        3. adx
        4. dmp
        5. dmn
        6. stoch_k
        7. stoch_d
        8. atr (15m)
        9. hour
        10. day_of_week
        """
        if len(self.bars_buffer_15m) < self._min_warmup_bars_15m:
            return None
        if len(self.bars_buffer_30m) < self._min_warmup_bars_30m:
            return None
            
        # Create 15m DataFrame
        data_15m = {
            'open': [float(b.open) for b in self.bars_buffer_15m],
            'high': [float(b.high) for b in self.bars_buffer_15m],
            'low': [float(b.low) for b in self.bars_buffer_15m],
            'close': [float(b.close) for b in self.bars_buffer_15m],
            'volume': [float(getattr(b, 'volume', 0.0)) for b in self.bars_buffer_15m],
            'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer_15m]
        }
        df_15m = pd.DataFrame(data_15m)
        df_15m.set_index('timestamp', inplace=True)
        df_15m = df_15m.loc[~df_15m.index.duplicated(keep='first')]  # Remove duplicate timestamps
        
        # Create 30m DataFrame
        data_30m = {
            'close': [float(b.close) for b in self.bars_buffer_30m],
            'high': [float(b.high) for b in self.bars_buffer_30m],
            'low': [float(b.low) for b in self.bars_buffer_30m],
            'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in self.bars_buffer_30m]
        }
        df_30m = pd.DataFrame(data_30m)
        df_30m.set_index('timestamp', inplace=True)
        df_30m = df_30m.loc[~df_30m.index.duplicated(keep='first')]  # Remove duplicate timestamps
        
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

            # If using the 40-feature RF backup model, generate that exact feature vector.
            if self._using_rf40_model():
                row = latest_rf40_row(df_15m[["open", "high", "low", "close", "volume"]])
                if row is None:
                    return None
                features = row.to_numpy(dtype=np.float64)[0]
                return features

            # === 15m Features ===
            # 1. Log Returns
            df_15m['log_ret'] = np.log(df_15m['close'] / df_15m['close'].shift(1)) * 100
            
            # 2. Use precomputed MAMA diff
            if self._latest_meta.get("mama_diff") is None:
                _py_logger.warning(f"[WARN] MAMA calculation failed for {df_15m.index[-1]}")
                return None
            df_15m['mama_diff'] = self._latest_meta["mama_diff"]
            
            # 4. ATR (15m)
            df_15m['atr'] = ta.atr(df_15m['high'], df_15m['low'], df_15m['close'], length=14) / df_15m['close']
            
            # 5. Time Features
            df_15m['hour'] = df_15m.index.hour
            df_15m['day_of_week'] = df_15m.index.dayofweek
            
            # === 30m Features ===
            # 1. DMI
            if dmi_30m is None or len(dmi_30m) == 0:
                _py_logger.warning(f"[WARN] DMI calculation failed for {df_30m.index[-1]}")
                return None
            df_30m['adx'] = dmi_30m.iloc[:, 0] / 100.0
            df_30m['dmp'] = dmi_30m.iloc[:, 1] / 100.0
            df_30m['dmn'] = dmi_30m.iloc[:, 2] / 100.0
            
            # 2. Stochastic (30m)
            try:
                stoch_30m = ta.stoch(df_30m['high'], df_30m['low'], df_30m['close'], k=14, d=3, smooth_k=3)
                if stoch_30m is None or len(stoch_30m) == 0:
                    # Fallback: Use RSI if Stochastic fails
                    rsi_30m = ta.rsi(df_30m['close'], length=14)
                    if rsi_30m is not None and len(rsi_30m) > 0:
                        rsi_val = rsi_30m.iloc[-1] / 100.0  # Convert to 0-1 range
                        df_30m['stoch_k'] = rsi_val
                        df_30m['stoch_d'] = rsi_val  # Use same value for both
                        _py_logger.warning(f"[WARN] Stochastic failed, using RSI fallback for {df_30m.index[-1]}")
                    else:
                        _py_logger.warning(f"[WARN] Stochastic and RSI failed for {df_30m.index[-1]}")
                        return None
                else:
                    df_30m['stoch_k'] = stoch_30m.iloc[:, 0] / 100.0
                    df_30m['stoch_d'] = stoch_30m.iloc[:, 1] / 100.0
            except Exception as e:
                _py_logger.error(f"[ERROR] Stochastic calculation failed: {e}")
                return None
            
            # Get latest values
            latest_15m = df_15m.iloc[-1]
            latest_30m = df_30m.iloc[-1]
            
            # Feature order MUST match training
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
                latest_15m['day_of_week']
            ]).reshape(1, -1)
            
            # Check for NaNs
            if np.isnan(features).any():
                return None

            # Update meta state from 10-feature schema
            self._latest_meta["mama_diff"] = float(features[0][1])
            self._latest_meta["dmp_30m"] = float(features[0][3])
            return features[0]
            
        except Exception as e:
            _py_logger.error(f"Feature calculation error: {e}")
            return None
        
    def _calculate_atr(self) -> Optional[float]:
        """Calculate normalized ATR from 15m bars."""
        if len(self.bars_buffer_15m) < 14:
            return None
            
        highs = [float(b.high) for b in self.bars_buffer_15m]
        lows = [float(b.low) for b in self.bars_buffer_15m]
        closes = [float(b.close) for b in self.bars_buffer_15m]
        
        df = pd.DataFrame({'high': highs, 'low': lows, 'close': closes})
        atr = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        if atr is None or atr.empty:
            return None
            
        return atr.iloc[-1] / closes[-1]  # Normalized
