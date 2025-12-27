"""
MLSignalStrategy V3 - Hierarchical Multi-Timeframe (HMTF)

Master Model (15m): Generates directional confidence signals
Soldier Model (5m): Evaluates micro-entries within master direction
State Machine: IDLE → HUNTING → ACTIVE → COOLDOWN

Key Differences from V2:
- Hierarchical two-model architecture (master guides soldier)
- Quarter-hour synchronization (5m waits for 15m master update)
- Dynamic position sizing based on equity and ATR
- State-based cooldown after trade exit
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional, Dict, List
import logging
import os

import numpy as np
import pandas as pd
import joblib
import xgboost as xgb

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.data import Data
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.orders import MarketOrder, StopMarketOrder, LimitOrder
from nautilus_trader.trading.strategy import Strategy

# Import HMTF engine components
from live.hmtf_engine import (
    BarEvent,
    FeatureStore,
    SyncGate,
    TradingStateMachine,
    TradeState,
    get_dynamic_size,
)
from live.hmtf_features import Atr, make_default_soldier_indicators

_py_logger = logging.getLogger("MLSignalStrategy_V3_HMTF")
_py_logger.setLevel(logging.INFO)


class MLSignalStrategyV3Config(StrategyConfig, kw_only=True):
    """Configuration for HMTF V3 Strategy."""
    
    instrument_id: str
    bar_type_5m: str   # "EUR/USD.IDEALPRO-5-MINUTE-MID-INTERNAL"
    bar_type_15m: str  # "EUR/USD.IDEALPRO-15-MINUTE-MID-INTERNAL"
    
    # Models
    master_model_path: str = "models/ml_model_mtf_backup.pkl"
    soldier_model_path: str = "models/soldier_5m_xgb.pkl"
    soldier_feature_list_path: str = "models/soldier_5m_feature_names.txt"
    
    # HMTF parameters
    master_threshold: float = 0.70
    master_threshold_mode: str = "abs"  # "abs" or "signed"
    soldier_enabled: bool = True
    soldier_entry_threshold: float = 0.55
    cooldown_minutes: int = 30
    
    # Position sizing
    use_dynamic_sizing: bool = True  # If False, use fixed_position_size
    fixed_position_size: int = 50000  # Used when use_dynamic_sizing=False
    risk_per_trade_pct: float = 1.0  # 1% equity risk per trade (dynamic mode)
    min_position_size: int = 1000
    sl_atr_mult: float = 1.0
    tp_atr_mult: float = 1.5
    
    # Session filters
    trade_start_hour: int = 0
    trade_end_hour: int = 23
    config_timezone: str = "UTC"
    excluded_hours_mode: str = "disabled"
    excluded_hours_monday: str = ""
    excluded_hours_tuesday: str = ""
    excluded_hours_wednesday: str = ""
    excluded_hours_thursday: str = ""
    excluded_hours_friday: str = ""
    excluded_hours_saturday: str = ""
    excluded_hours_sunday: str = ""
    
    # Risk limits
    min_atr: float = 0.00010
    max_atr: float = 0.01000
    
    # Stall detection
    stall_detection_enabled: bool = False
    stall_check_bars: int = 3
    stall_min_profit_atr: float = 0.1
    stall_sl_atr: float = 0.6
    neg_stall_enabled: bool = False
    neg_stall_check_bars: int = 3
    neg_stall_max_profit_atr: float = 0.0
    neg_stall_trigger_loss_atr: float = 0.9


class MtfV2SklearnMasterModel:
    """Master model wrapper for sklearn-based MTF V2 model."""
    
    def __init__(self, model_path: Path):
        self.model = joblib.load(model_path)
        _py_logger.info(f"Master model loaded: {model_path}")
        
        # Rolling buffers for 15m and 30m bars
        self.bars_15m = deque(maxlen=100)
        self.bars_30m = deque(maxlen=50)
        self.last_30m_time = None
        
    def update_bars(self, bar_15m: BarEvent):
        """Update bar buffers."""
        self.bars_15m.append(bar_15m)
        
        # Aggregate to 30m
        bar_time = bar_15m.end_time_utc
        if self.last_30m_time is None or (bar_time.minute % 30 == 0):
            # New 30m bar
            self.last_30m_time = bar_time
            self.bars_30m.append(bar_15m)
        
    def predict(self, bar_15m: BarEvent, atr_15m: float) -> float:
        """Returns confidence score (negative=SHORT, positive=LONG)."""
        # Update bars first
        self.update_bars(bar_15m)
        
        # Need at least 60 bars for proper 30m indicators
        if len(self.bars_15m) < 60:
            return 0.0
            
        # Compute 10 MTF features
        features = self._compute_features(bar_15m, atr_15m)
        
        # Debug: log features for first few bars
        if len(self.bars_15m) == 60:
            _py_logger.info(f"Master features @ 60 bars: {[f'{f:.4f}' for f in features]}")
        
        X = np.array([features])
        
        # Predict class probabilities
        proba = self.model.predict_proba(X)[0]
        
        # Convert to signed confidence: (prob_long - prob_short)
        # Assuming classes [0=SHORT, 1=LONG]
        confidence = proba[1] - proba[0]
        return confidence
    
    def _compute_features(self, current_bar: BarEvent, atr: float) -> List[float]:
        """Compute 10 MTF features for master model."""
        import pandas as pd
        import pandas_ta as ta
        
        # Convert to DataFrame
        df_15m = pd.DataFrame([
            {'time': b.end_time_utc, 'o': b.o, 'h': b.h, 'l': b.l, 'c': b.c, 'v': b.v}
            for b in self.bars_15m
        ]).set_index('time')
        
        # 1. Log Returns
        log_ret = np.log(current_bar.c / df_15m['c'].iloc[-2]) * 100 if len(df_15m) > 1 else 0.0
        
        # 2. MAMA Diff
        hl2 = (df_15m['h'] + df_15m['l']) / 2.0
        mama = ta.mama(hl2, fastlimit=0.5, slowlimit=0.05)
        if mama is not None and hasattr(mama, 'shape') and mama.shape[1] >= 2:
            mama_diff = float((mama.iloc[-1, 0] - mama.iloc[-1, 1]) / current_bar.c)
        else:
            mama_diff = 0.0
        
        # 8. ATR norm
        atr_norm = atr / current_bar.c if current_bar.c > 0 else 0.0
        
        # === 30m Features ===
        # Resample 15m to 30m instead of using manual bars_30m buffer
        if len(self.bars_15m) >= 60:  # Need ~60 15m bars = 30 30m bars
            # Resample 15m to 30m
            df_30m = df_15m.resample('30min', label='right', closed='right').agg({
                'o': 'first',
                'h': 'max',
                'l': 'min',
                'c': 'last'
            }).dropna()
            
            if len(df_30m) >= 30:
                # 3 & 4. DMP/DMN
                adx = ta.adx(df_30m['h'], df_30m['l'], df_30m['c'], length=14)
                dmp_30m = float(adx['DMP_14'].iloc[-1]) if adx is not None and 'DMP_14' in adx.columns else 0.0
                dmn_30m = float(adx['DMN_14'].iloc[-1]) if adx is not None and 'DMN_14' in adx.columns else 0.0
                
                # 5 & 6. Stoch
                stoch = ta.stoch(df_30m['h'], df_30m['l'], df_30m['c'], k=14, d=3, smooth_k=3)
                if stoch is not None and hasattr(stoch, 'shape') and stoch.shape[1] >= 2:
                    stoch_k_30m = float(stoch.iloc[-1, 0])
                    stoch_d_30m = float(stoch.iloc[-1, 1])
                else:
                    stoch_k_30m = 50.0
                    stoch_d_30m = 50.0
                
                # 7. WMA Diff
                wma_fast = ta.wma(df_30m['c'], length=9)
                wma_slow = ta.wma(df_30m['c'], length=23)
                if wma_fast is not None and wma_slow is not None:
                    wma_diff_30m = float((wma_fast.iloc[-1] - wma_slow.iloc[-1]) / df_30m['c'].iloc[-1])
                else:
                    wma_diff_30m = 0.0
            else:
                dmp_30m = dmn_30m = 0.0
                stoch_k_30m = stoch_d_30m = 50.0
                wma_diff_30m = 0.0
        else:
            dmp_30m = dmn_30m = 0.0
            stoch_k_30m = stoch_d_30m = 50.0
            wma_diff_30m = 0.0
        
        # 9 & 10. Time features
        hour = current_bar.end_time_utc.hour
        day_of_week = current_bar.end_time_utc.weekday()
        
        return [log_ret, mama_diff, dmp_30m, dmn_30m, stoch_k_30m, stoch_d_30m, 
                wma_diff_30m, atr_norm, hour, day_of_week]


class XgbSoldierModel:
    """Soldier model wrapper for XGBoost 5m model."""
    
    def __init__(self, model_path: Path, feature_names: List[str]):
        self.model = xgb.Booster()
        self.model.load_model(str(model_path))
        self.feature_names = feature_names
        _py_logger.info(f"Soldier model loaded: {model_path} ({len(feature_names)} features)")
        
    def predict(self, features: Dict[str, float]) -> float:
        """Returns probability score [0, 1]."""
        # Convert dict to array in correct order
        X_array = np.array([[features.get(f, 0.0) for f in self.feature_names]])
        dmatrix = xgb.DMatrix(X_array, feature_names=self.feature_names)
        proba = self.model.predict(dmatrix)[0]
        return float(proba)


class MLSignalStrategyV3(Strategy):
    """Hierarchical Multi-Timeframe Strategy for Nautilus."""
    
    def __init__(self, config: MLSignalStrategyV3Config):
        super().__init__(config)
        
        # Configure Python logging to file
        import logging
        log_file = Path("backtest_results/MTF_V3_NAUTILUS/v3_debug.log")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, mode='w')
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        _py_logger.addHandler(file_handler)
        _py_logger.setLevel(logging.INFO)
        
        # Config
        self.bar_type_5m = BarType.from_str(config.bar_type_5m)
        self.bar_type_15m = BarType.from_str(config.bar_type_15m)
        self.master_threshold = config.master_threshold
        self.master_threshold_mode = config.master_threshold_mode
        self.soldier_enabled = config.soldier_enabled
        self.soldier_entry_threshold = config.soldier_entry_threshold
        self.use_dynamic_sizing = config.use_dynamic_sizing
        self.fixed_position_size = config.fixed_position_size
        self.risk_pct = config.risk_per_trade_pct / 100.0
        self.min_size = config.min_position_size
        self.sl_atr_mult = config.sl_atr_mult
        self.tp_atr_mult = config.tp_atr_mult
        self.min_atr = config.min_atr
        self.max_atr = config.max_atr
        
        # Session filters
        self.trade_start_hour = config.trade_start_hour
        self.trade_end_hour = config.trade_end_hour
        self._config_timezone = config.config_timezone.upper()
        self._excluded_hours_mode = config.excluded_hours_mode
        self._excluded_hours = {
            0: self._parse_hours(config.excluded_hours_monday),
            1: self._parse_hours(config.excluded_hours_tuesday),
            2: self._parse_hours(config.excluded_hours_wednesday),
            3: self._parse_hours(config.excluded_hours_thursday),
            4: self._parse_hours(config.excluded_hours_friday),
            5: self._parse_hours(config.excluded_hours_saturday),
            6: self._parse_hours(config.excluded_hours_sunday),
        }
        
        # HMTF engine components
        self.store = FeatureStore()
        self.sync = SyncGate(self.store)
        self.sm = TradingStateMachine(cooldown_minutes=config.cooldown_minutes)
        
        # Models
        self.master_model = None
        self.soldier_model = None
        self._load_models(config)
        
        # Indicators
        self._atr_15m = Atr(period=14)
        self._soldier_indicators = make_default_soldier_indicators()
        
        # Position tracking
        self._position_open = False
        self._entry_order_id: Optional[str] = None
        self._sl_order_id: Optional[str] = None
        self._tp_order_id: Optional[str] = None
        self._trade_direction: Optional[str] = None  # "LONG" or "SHORT"
        self._entry_atr: Optional[float] = None
        self._entry_price: Optional[float] = None
        
        # Stall detection
        self._stall_detection_enabled = config.stall_detection_enabled
        self._stall_check_bars = config.stall_check_bars
        self._stall_min_profit_atr = config.stall_min_profit_atr
        self._stall_sl_atr = config.stall_sl_atr
        self._neg_stall_enabled = config.neg_stall_enabled
        self._neg_stall_check_bars = config.neg_stall_check_bars
        self._neg_stall_max_profit_atr = config.neg_stall_max_profit_atr
        self._neg_stall_trigger_loss_atr = config.neg_stall_trigger_loss_atr
        
        self._bars_in_trade = 0
        self._max_profit_atr = 0.0
        self._stall_sl_applied = False
        self._neg_stall_triggered = False
        
        # Bar buffers for feature calculation
        self._bars_5m = deque(maxlen=100)
        self._bars_15m = deque(maxlen=50)
        
        # Warmup
        self._warmup_mode = True
        self._min_warmup_bars_15m = 30
        
        _py_logger.info("MLSignalStrategyV3 (HMTF) initialized")
        
    def _load_models(self, config: MLSignalStrategyV3Config):
        """Load master and soldier models."""
        try:
            master_path = Path(config.master_model_path)
            if not master_path.is_absolute():
                project_root = Path(__file__).parent.parent
                master_path = project_root / master_path
            self.master_model = MtfV2SklearnMasterModel(model_path=master_path)
        except Exception as e:
            _py_logger.error(f"Failed to load master model: {e}")
            self.master_model = None
            
        if config.soldier_enabled:
            try:
                soldier_path = Path(config.soldier_model_path)
                feature_path = Path(config.soldier_feature_list_path)
                if not soldier_path.is_absolute():
                    project_root = Path(__file__).parent.parent
                    soldier_path = project_root / soldier_path
                    feature_path = project_root / feature_path
                    
                with open(feature_path, 'r') as f:
                    feature_names = [line.strip() for line in f if line.strip()]
                    
                self.soldier_model = XgbSoldierModel(model_path=soldier_path, feature_names=feature_names)
            except Exception as e:
                _py_logger.error(f"Failed to load soldier model: {e}")
                self.soldier_model = None
    
    @staticmethod
    def _parse_hours(hours_str: str) -> list:
        """Parse comma-separated hours string."""
        if not hours_str:
            return []
        return [int(h.strip()) for h in hours_str.split(',') if h.strip()]
    
    def _utc_to_est(self, utc_dt: datetime) -> tuple:
        """Convert UTC datetime to EST/EDT (returns hour, weekday)."""
        from datetime import timezone as tz
        import zoneinfo
        
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=tz.utc)
            
        est_tz = zoneinfo.ZoneInfo("America/New_York")
        est_dt = utc_dt.astimezone(est_tz)
        return est_dt.hour, est_dt.weekday()
    
    def _is_excluded_hour(self, bar_time: datetime) -> bool:
        """Check if current time is in excluded hours."""
        if self._excluded_hours_mode == "disabled":
            return False
            
        # Convert to configured timezone
        if self._config_timezone == "EST":
            hour, weekday = self._utc_to_est(bar_time)
        else:
            hour = bar_time.hour
            weekday = bar_time.weekday()
            
        excluded_list = self._excluded_hours.get(weekday, [])
        return hour in excluded_list
    
    def _is_trading_session(self, bar_time: datetime) -> bool:
        """Check if within trading hours."""
        hour = bar_time.hour
        if self.trade_start_hour <= self.trade_end_hour:
            return self.trade_start_hour <= hour <= self.trade_end_hour
        else:
            return hour >= self.trade_start_hour or hour <= self.trade_end_hour
    
    def _check_stall_detection(self, current_price: float):
        """Check if trade is stalling and tighten SL if needed."""
        if not self._position_open:
            return
        
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
        
        # Negative stall check (close if underwater too long)
        if (
            self._neg_stall_enabled
            and not self._neg_stall_triggered
            and self._bars_in_trade >= self._neg_stall_check_bars
            and self._max_profit_atr <= self._neg_stall_max_profit_atr
            and profit_atr <= -self._neg_stall_trigger_loss_atr
        ):
            self._neg_stall_triggered = True
            _py_logger.info(
                f"[NEG_STALL] Trigger: bars={self._bars_in_trade}, max={self._max_profit_atr:.2f} ATR, "
                f"curr={profit_atr:.2f} ATR -> flatten"
            )
            
            # Close position
            self.close_all_positions(self.instrument_id)
            return
        
        # Regular stall detection (tighten SL)
        if not self._stall_detection_enabled:
            return
        
        if self._stall_sl_applied:
            return
        
        # Check stall condition (trade not progressing to TP)
        if (
            self._bars_in_trade >= self._stall_check_bars
            and self._stall_min_profit_atr <= self._max_profit_atr < self.tp_atr_mult
        ):
            # Tighten SL to lock in some profit
            sl_distance = self._entry_price * self._entry_atr * self._stall_sl_atr
            
            if self._trade_direction == "LONG":
                new_sl = self._entry_price + sl_distance
                
                # SAFETY: Cap SL at current price to avoid "Stop > Market"
                if new_sl > current_price:
                    new_sl = current_price
            else:
                new_sl = self._entry_price - sl_distance
                
                # SAFETY: Cap SL at current price to avoid "Stop < Market"
                if new_sl < current_price:
                    new_sl = current_price
            
            # Modify SL order
            positions = self.cache.positions_open(instrument_id=self.instrument_id)
            if positions:
                position = list(positions)[0]
                # Cancel existing SL and submit new one
                if self._sl_order_id:
                    try:
                        from nautilus_trader.model.identifiers import ClientOrderId
                        order_id = ClientOrderId(self._sl_order_id)
                        order = self.cache.order(order_id)
                        if order:
                            self.cancel_order(order)
                    except Exception as e:
                        _py_logger.error(f"[STALL] Failed to cancel SL: {e}")
                
                # Submit new SL with buffer to avoid rejection
                try:
                    # Add 1 pip buffer to avoid "in the market" rejection
                    buffer = 0.00005
                    if self._trade_direction == "LONG":
                        new_sl_buffered = new_sl - buffer
                    else:
                        new_sl_buffered = new_sl + buffer
                    
                    sl_order = self.order_factory.stop_market(
                        instrument_id=self.instrument_id,
                        order_side=OrderSide.SELL if self._trade_direction == "LONG" else OrderSide.BUY,
                        quantity=position.quantity,
                        trigger_price=Price.from_str(f"{new_sl_buffered:.5f}"),
                        time_in_force=TimeInForce.GTC,
                    )
                    self.submit_order(sl_order)
                    self._sl_order_id = str(sl_order.client_order_id)
                except Exception as e:
                    _py_logger.error(f"[STALL] Failed to submit new SL: {e}")
            
            self._stall_sl_applied = True
            _py_logger.info(
                f"[STALL] Detected after {self._bars_in_trade} bars, max={self._max_profit_atr:.2f} ATR, "
                f"SL tightened to {self._stall_sl_atr} ATR ({new_sl:.5f})"
            )
    
    def on_start(self):
        """Subscribe to both 5m and 15m bars."""
        self.subscribe_bars(self.bar_type_5m)
        self.subscribe_bars(self.bar_type_15m)
        # Store instrument ID from bar type
        self.instrument_id = self.bar_type_5m.instrument_id
        _py_logger.info(f"Subscribed to {self.bar_type_5m} and {self.bar_type_15m}")
        
    def on_stop(self):
        """Cleanup on strategy stop."""
        _py_logger.info("Strategy stopped")
        
    def on_bar(self, bar: Bar):
        """Route bars to appropriate handler."""
        try:
            if "15-MINUTE" in str(bar.bar_type) or "15-Min" in str(bar.bar_type):
                self._on_15m_bar(bar)
            elif "5-MINUTE" in str(bar.bar_type) or "5-Min" in str(bar.bar_type):
                self._on_5m_bar(bar)
        except Exception as e:
            _py_logger.error(f"Error in on_bar: {e}", exc_info=True)
    
    def _nautilus_to_bar_event(self, bar: Bar, timeframe: str) -> BarEvent:
        """Convert Nautilus Bar to HMTF BarEvent."""
        from datetime import datetime, timezone
        
        # Convert nanosecond timestamp to datetime
        ts_nanos = int(bar.ts_event)
        ts_dt = datetime.fromtimestamp(ts_nanos / 1_000_000_000, tz=timezone.utc)
        
        return BarEvent(
            timeframe=timeframe,
            end_time_utc=ts_dt,
            o=float(bar.open),
            h=float(bar.high),
            l=float(bar.low),
            c=float(bar.close),
            v=float(bar.volume),
        )
    
    def _on_15m_bar(self, bar: Bar):
        """Process 15m master bar."""
        bar_event = self._nautilus_to_bar_event(bar, "15m")
        self._bars_15m.append(bar_event)
        
        # Update ATR
        self._atr_15m.update(bar_event.h, bar_event.l, bar_event.c)
        atr_value = self._atr_15m.value
        
        if atr_value is None or atr_value < self.min_atr or atr_value > self.max_atr:
            return
            
        # Get master prediction
        if self.master_model is None:
            return
            
        confidence = self.master_model.predict(bar_event, atr_value)
        
        # Store in feature store
        from live.hmtf_engine import MasterSignal
        master_signal = MasterSignal(
            asof_15m_close=bar_event.end_time_utc,
            confidence=confidence,
            atr_15m=atr_value,
        )
        self.store.update_master(master_signal)
        
        # Update state machine (this handles IDLE<->HUNTING transitions)
        self.sm.maybe_transition_on_master(
            master_signal,
            self.master_threshold,
            bar_event.end_time_utc,
            threshold_mode=self.master_threshold_mode
        )
        
        # Check warmup
        if self._warmup_mode and len(self._bars_15m) >= self._min_warmup_bars_15m:
            self._warmup_mode = False
            _py_logger.info("Warmup complete - ready to trade")
        
        # Debug logging
        direction_str = "LONG" if confidence > 0 else "SHORT" if confidence < 0 else "NONE"
        _py_logger.info(
            f"15m: {bar_event.end_time_utc} conf={confidence:.3f} atr={atr_value:.5f} "
            f"threshold={self.master_threshold} mode={self.master_threshold_mode} "
            f"state={self.sm.state.name} direction={direction_str}"
        )
    
    def _on_5m_bar(self, bar: Bar):
        """Process 5m soldier bar."""
        if self._warmup_mode:
            return
            
        bar_event = self._nautilus_to_bar_event(bar, "5m")
        self._bars_5m.append(bar_event)
        
        # Check sync gate (wait for 15m master update)
        if not self.sync.can_process_5m(bar_event.end_time_utc):
            _py_logger.debug(f"5m: {bar_event.end_time_utc} BLOCKED by sync gate")
            return
        
        _py_logger.info(f"5m: {bar_event.end_time_utc} passed sync gate, state={self.sm.state.name}")
            
        # Update soldier indicators
        self._soldier_indicators.rsi.update(bar_event.c)
        self._soldier_indicators.macd.update(bar_event.c)
        self._soldier_indicators.bb_width.update(bar_event.c)
        
        # Check if we should evaluate soldier
        if self._position_open:
            # Check stall detection
            self._check_stall_detection(float(bar.close))
            return
            
        # Check state machine permission
        if self.sm.state not in [TradeState.HUNTING, TradeState.IDLE]:
            _py_logger.info(f"5m: state not in [HUNTING, IDLE], state={self.sm.state.name}")
            return
        
        # Only evaluate soldier when in HUNTING state
        if self.sm.state != TradeState.HUNTING:
            _py_logger.info(f"5m: state != HUNTING, state={self.sm.state.name}")
            return
        
        # Get master signal
        master = self.store.last_master
        if master is None:
            _py_logger.info(f"5m: master is None")
            return
        
        # Determine direction from master confidence
        direction = "LONG" if master.confidence > 0 else "SHORT"
        
        _py_logger.info(f"5m soldier: state=HUNTING direction={direction} conf={master.confidence:.3f} time={bar_event.end_time_utc}")
            
        # Session filters
        if not self._is_trading_session(bar_event.end_time_utc):
            _py_logger.info(f"5m: filtered by trading session")
            return
        if self._is_excluded_hour(bar_event.end_time_utc):
            _py_logger.info(f"5m: filtered by excluded hour")
            return
        
        # Get soldier features (master already retrieved above)
        if master is None:
            return
            
        features = self._compute_soldier_features(bar_event, master)
        
        # Soldier prediction
        if not self.soldier_enabled or self.soldier_model is None:
            # Master-only mode: enter if macro permission exists
            score = 1.0  # Always pass threshold
        else:
            score = self.soldier_model.predict(features)
        
        # Entry signal
        if score >= self.soldier_entry_threshold:
            self._submit_entry(bar, bar_event, master, score)
    
    def _compute_soldier_features(self, bar: BarEvent, master) -> Dict[str, float]:
        """Compute soldier model features."""
        from live.hmtf_features import candle_body_wicks
        
        features = {}
        
        # Master features
        features['master_conf'] = float(master.confidence)
        features['atr_15m'] = float(master.atr_15m)
        
        # Candle features
        body_size, upper_wick, lower_wick = candle_body_wicks(bar.o, bar.h, bar.l, bar.c)
        features['body_size'] = body_size
        features['upper_wick'] = upper_wick
        features['lower_wick'] = lower_wick
        
        # Indicator features
        features['rsi'] = float(self._soldier_indicators.rsi.value) if self._soldier_indicators.rsi.value else 50.0
        features['macd'] = float(self._soldier_indicators.macd.macd) if self._soldier_indicators.macd.macd else 0.0
        features['macd_signal'] = float(self._soldier_indicators.macd.signal) if self._soldier_indicators.macd.signal else 0.0
        features['macd_hist'] = float(self._soldier_indicators.macd.hist) if self._soldier_indicators.macd.hist else 0.0
        features['bb_width'] = float(self._soldier_indicators.bb_width.width) if self._soldier_indicators.bb_width.width else 0.0
                
        # Time features
        features['hour'] = float(bar.end_time_utc.hour)
        features['day_of_week'] = float(bar.end_time_utc.weekday())
        
        return features
    
    def _submit_entry(self, bar: Bar, bar_event: BarEvent, master, score: float):
        """Submit market entry with SL/TP bracket."""
        # Calculate position size
        if self.use_dynamic_sizing:
            equity = self.portfolio.account(self.venue).balance_total().as_double()
            size_units = int(get_dynamic_size(equity, master.atr_15m, float(bar.close)))
            size_units = max(size_units, self.min_size)
        else:
            size_units = self.fixed_position_size
        
        # Determine direction from master confidence
        direction = "LONG" if master.confidence > 0 else "SHORT"
            
        order_side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
        # Create size with proper precision (2 decimals for EUR/USD)
        size = Quantity(float(size_units), precision=2)
        
        # Calculate SL/TP prices
        entry_price = float(bar.close)
        atr = master.atr_15m
        
        # Stop Loss
        sl_distance = entry_price * atr * self.sl_atr_mult
        if order_side == OrderSide.BUY:
            sl_price = entry_price - sl_distance
        else:
            sl_price = entry_price + sl_distance
            
        # Take Profit
        tp_distance = entry_price * atr * self.tp_atr_mult
        if order_side == OrderSide.BUY:
            tp_price = entry_price + tp_distance
        else:
            tp_price = entry_price - tp_distance
        
        # Create bracket order (entry + SL + TP)
        bracket = self.order_factory.bracket(
            instrument_id=self.instrument_id,
            order_side=order_side,
            quantity=size,
            sl_trigger_price=Price.from_str(f"{sl_price:.5f}"),
            tp_price=Price.from_str(f"{tp_price:.5f}"),
            tp_post_only=False,
            entry_tags=["V3_ENTRY"],
            sl_tags=["V3_SL"],
            tp_tags=["V3_TP"]
        )
        
        # Track order IDs
        for order in bracket.orders:
            if isinstance(order, MarketOrder):
                self._entry_order_id = str(order.client_order_id)
            elif isinstance(order, StopMarketOrder):
                self._sl_order_id = str(order.client_order_id)
            elif isinstance(order, LimitOrder):
                self._tp_order_id = str(order.client_order_id)
        
        # Submit bracket
        self.submit_order_list(bracket)
        self._position_open = True
        self._trade_direction = direction
        self._entry_atr = atr
        self._entry_price = entry_price
        
        # Reset stall tracking
        self._bars_in_trade = 0
        self._max_profit_atr = 0.0
        self._stall_sl_applied = False
        self._neg_stall_triggered = False
        
        # State transitions to ACTIVE when position opens
        self.sm.state = TradeState.ACTIVE
        
        _py_logger.info(
            f"[ENTRY] {direction} {size_units} @ {entry_price:.5f}, "
            f"SL={sl_price:.5f}, TP={tp_price:.5f}, score={score:.3f}"
        )
    
    def on_order_filled(self, event):
        """Handle order fills."""
        order_id = str(event.client_order_id)
        
        if order_id == self._entry_order_id:
            _py_logger.info(f"Entry filled @ {event.last_px}")
        elif self._position_open:
            # SL or TP hit - position is closing
            self._position_open = False
            self._entry_order_id = None
            self._sl_order_id = None
            self._tp_order_id = None
            self._entry_price = None
            self._entry_atr = None
            
            # Reset stall tracking
            self._bars_in_trade = 0
            self._max_profit_atr = 0.0
            self._stall_sl_applied = False
            self._neg_stall_triggered = False
            
            # Update state machine - go to cooldown
            self.sm.state = TradeState.COOLDOWN
            self._cooldown_end = event.ts_event + (self.config.cooldown_minutes * 60 * 1_000_000_000)
            
            _py_logger.info(f"Position closed @ {event.last_px}, entering cooldown")
    
    def on_order_rejected(self, event):
        """Handle order rejections."""
        _py_logger.error(f"Order rejected: {event.client_order_id} - {event.reason}")
        self._position_open = False
        
    def on_position_closed(self, position):
        """Handle position closure."""
        pnl = position.realized_pnl.as_double()
        _py_logger.info(f"Position closed: PnL=${pnl:.2f}")
