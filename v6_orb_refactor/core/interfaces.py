from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from .market_event import RangeInfo

class MarketContext(ABC):
    """
    Deep module: Hides data history, tick buffering, and complex aggregations.
    The strategy interacts with this to understand the market state without managing data structures.
    """
    
    @abstractmethod
    def get_velocity(self, lookback_minutes: int, current_time: datetime) -> float:
        """
        Calculate the tick velocity (ticks per minute) over the given lookback window.
        """
        pass
        
    @abstractmethod
    def get_asian_range(self, start_hour: int, end_hour: int, current_time: datetime) -> Optional[RangeInfo]:
        """
        Calculate the high and low of the session range.
        Returns None if the range cannot be calculated (e.g., missing data).
        """
        pass
        
    @abstractmethod
    def time_is_in_trade_window(self, current_time: datetime, start_hour: int, end_hour: int) -> bool:
        """
        Check if the current time falls within the trading window.
        """
        pass

class ExecutionEngine(ABC):
    """
    Deep module: Hides broker order IDs, bracket leg tracking, slippage, and fill simulation.
    The strategy calls these methods and doesn't know if it's hitting IBKR or a backtest simulator.
    """
    
    @abstractmethod
    def set_orb_brackets(self, range_info: RangeInfo, rr_ratio: float):
        """
        Place OCA (One-Cancels-All) brackets for the ORB breakout strategy.
        This includes Stop Entry, Stop Loss, and Take Profit legs.
        Order IDs are managed entirely within the ExecutionEngine.
        """
        pass
        
    @abstractmethod
    def cancel_orb_brackets(self):
        """
        Cancel the resting ORB brackets if velocity drops or time expires.
        """
        pass
        
    @abstractmethod
    def close_at_market(self):
        """
        Close any open position immediately at market price.
        """
        pass
