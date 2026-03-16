import enum
from typing import Optional
import logging

from ..config.config import StrategyConfig
from ..core.market_event import Tick, Fill, RangeInfo
from ..core.interfaces import MarketContext, ExecutionEngine


class StrategyState(enum.Enum):
    IDLE = "IDLE"                   # Waiting for range to form
    RANGE_READY = "RANGE_READY"     # Range formed, monitoring velocity
    ORDERS_PLACED = "ORDERS_PLACED" # Velocity high, resting brackets active
    IN_TRADE = "IN_TRADE"           # Entry filled, managing position
    DONE_TODAY = "DONE_TODAY"       # Trade finished or skipped, done until tomorrow


class ORBStrategy:
    """
    Pure ORB strategy logic. Environment-agnostic.
    """
    def __init__(self, config: StrategyConfig, logger: Optional[logging.Logger] = None):
        self.config = config
        self.state = StrategyState.IDLE
        self.range: Optional[RangeInfo] = None
        self.logger = logger or logging.getLogger(__name__)
        self.orders_active = False

    def on_tick(self, tick: Tick, context: MarketContext, execution: ExecutionEngine):
        """
        Called on every tick. This is a pure state machine.
        """
        # If we're done for the day, ignore all ticks
        if self.state == StrategyState.DONE_TODAY:
            return

        # STATE: IDLE -> RANGE_READY
        # We wait until we enter the trading window, then calculate the Asian range.
        if self.state == StrategyState.IDLE:
            if context.time_is_in_trade_window(tick.timestamp, self.config.trade_start_hour, self.config.trade_end_hour):
                self.range = context.get_asian_range(self.config.range_start_hour, self.config.range_end_hour, tick.timestamp)
                
                # Check if the range is valid (not too tight, not too wide)
                if self.range and self.range.is_valid(self.config.min_range_size, self.config.max_range_size):
                    self.logger.info(f"Range established: {self.range.low:.4f} - {self.range.high:.4f} (size: {self.range.high - self.range.low:.4f})")
                    self.state = StrategyState.RANGE_READY
                else:
                    if self.range:
                        self.logger.info(f"Range invalid (size: {self.range.high - self.range.low:.4f}), done for today")
                    else:
                        self.logger.info("No range data available, done for today")
                    self.state = StrategyState.DONE_TODAY
            return

        # STATE: RANGE_READY <-> ORDERS_PLACED
        # We continuously monitor velocity. If it's high, we place orders. If it drops, we pull them.
        if self.state in (StrategyState.RANGE_READY, StrategyState.ORDERS_PLACED):
            # Check if we've run out of time for the day
            if not context.time_is_in_trade_window(tick.timestamp, self.config.trade_start_hour, self.config.trade_end_hour):
                if self.state == StrategyState.ORDERS_PLACED:
                    self.logger.info("Trade window closed, canceling brackets")
                    execution.cancel_orb_brackets()
                self.state = StrategyState.DONE_TODAY
                return

            # Check velocity filter (if enabled)
            if self.config.velocity_filter_enabled:
                vel = context.get_velocity(self.config.velocity_lookback_minutes, tick.timestamp)
                velocity_ok = vel >= self.config.velocity_threshold
            else:
                vel = 0.0
                velocity_ok = True
            
            if velocity_ok:
                if self.state == StrategyState.RANGE_READY:
                    self.logger.info(f"Velocity {vel:.1f} >= {self.config.velocity_threshold:.1f}, placing brackets")
                    execution.set_orb_brackets(self.range, self.config.rr_ratio)
                    self.state = StrategyState.ORDERS_PLACED
            else:
                if self.state == StrategyState.ORDERS_PLACED:
                    self.logger.info(f"Velocity {vel:.1f} < {self.config.velocity_threshold:.1f}, canceling brackets")
                    execution.cancel_orb_brackets()
                    self.state = StrategyState.RANGE_READY
            return

        # STATE: IN_TRADE
        # Position management is handled by ExecutionEngine (SL/TP brackets are resting).
        # We only need to check for end-of-day time exits here.
        if self.state == StrategyState.IN_TRADE:
            if not context.time_is_in_trade_window(tick.timestamp, self.config.trade_start_hour, self.config.trade_end_hour):
                self.logger.info("Trade window closed, closing position at market")
                execution.close_at_market()
                self.state = StrategyState.DONE_TODAY
            return

    def on_fill(self, fill: Fill, context: MarketContext, execution: ExecutionEngine):
        """
        Called when the execution engine reports a fill.
        """
        if fill.reason == "ENTRY":
            self.logger.info(f"ENTRY fill: {fill.direction} @ {fill.price:.4f}")
            self.state = StrategyState.IN_TRADE
            
        elif fill.reason in ("SL", "TP", "MARKET"):
            self.logger.info(f"{fill.reason} fill: {fill.direction} @ {fill.price:.4f}")
            self.state = StrategyState.DONE_TODAY
            
    def get_state_snapshot(self) -> dict:
        """
        Returns a pure dict representation of state. 
        The Runner (not the Strategy) is responsible for saving this to JSON.
        """
        return {
            "state": self.state.value,
            "range_high": self.range.high if self.range else None,
            "range_low": self.range.low if self.range else None,
            "orders_active": self.state == StrategyState.ORDERS_PLACED
        }
        
    def restore_state(self, snapshot: dict):
        """
        Restores state from a dict.
        """
        self.state = StrategyState(snapshot["state"])
        if snapshot["range_high"] is not None and snapshot["range_low"] is not None:
            # We don't save times to dict for simplicity unless needed
            self.range = RangeInfo(
                high=snapshot["range_high"], 
                low=snapshot["range_low"], 
                start_time=None, 
                end_time=None
            )
