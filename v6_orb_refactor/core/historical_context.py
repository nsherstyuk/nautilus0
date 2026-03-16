from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Deque, List

from ..core.interfaces import MarketContext
from ..core.market_event import RangeInfo, Tick, Bar


class HistoricalMarketContext(MarketContext):
    """
    MarketContext implementation for backtesting.
    Manages a rolling window of bars/ticks to calculate velocity and range.
    """
    def __init__(self, tick_buffer_minutes: int = 10):
        self.bar_buffer: Deque[Bar] = deque()
        self.tick_buffer_minutes = tick_buffer_minutes
        
        # We need to cache the asian range once calculated for the day
        self.current_range: Optional[RangeInfo] = None
        self.range_date: Optional[datetime] = None

    def process_bar(self, bar: Bar):
        """
        Called by the runner to feed bar data into the context BEFORE the strategy sees synthetic ticks.
        """
        self.bar_buffer.append(bar)
        
        # Prune old bars
        cutoff = bar.timestamp - timedelta(minutes=self.tick_buffer_minutes)
        while self.bar_buffer and self.bar_buffer[0].timestamp < cutoff:
            self.bar_buffer.popleft()

    def get_velocity(self, lookback_minutes: int, current_time: datetime) -> float:
        """
        Calculate ticks per minute over the lookback window.
        Uses the tick_count field from the 1m bars.
        
        PARITY WARNING: This counts historical tick_count from CSV data (actual
        market ticks recorded by data provider). LiveMarketContext counts
        reqMktData bid/ask updates from IBKR, which are throttled/aggregated.
        A threshold calibrated on historical data will NOT transfer directly
        to live. Calibrate live threshold using velocity logger data.
        """
        cutoff = current_time - timedelta(minutes=lookback_minutes)
        
        # Sum tick_counts in the window
        total_ticks = sum(b.tick_count for b in self.bar_buffer if b.timestamp >= cutoff)
        
        return total_ticks / max(lookback_minutes, 0.01)

    def get_asian_range(self, start_hour: int, end_hour: int, current_time: datetime) -> Optional[RangeInfo]:
        """
        Calculate the high and low of the session range.
        For HistoricalMarketContext, we assume the runner pre-calculates this.
        """
        if self.current_range and self.range_date and self.range_date.date() == current_time.date():
            return self.current_range
        return None
        
    def set_daily_range(self, range_info: RangeInfo, current_date: datetime):
        """
        Helper for the backtest runner to inject the pre-calculated range.
        """
        self.current_range = range_info
        self.range_date = current_date

    def time_is_in_trade_window(self, current_time: datetime, start_hour: int, end_hour: int) -> bool:
        """
        Check if the current time falls within the trading window.
        Assumes current_time is UTC.
        """
        return start_hour <= current_time.hour < end_hour
