"""
LiveMarketContext - IBKR tick stream wrapper
Implements MarketContext interface for live trading.
"""
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable
import logging

from ib_insync import IB, Contract

from ..core.interfaces import MarketContext
from ..core.market_event import RangeInfo, Tick


class LiveMarketContext(MarketContext):
    """
    Implements MarketContext for live IBKR data feed.
    Subscribes to tick-by-tick data and maintains rolling buffer for velocity calculation.
    """
    
    def __init__(
        self, 
        ib: IB, 
        contract: Contract, 
        tick_buffer_minutes: int = 10,
        on_tick_callback: Optional[Callable[[Tick], None]] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Args:
            ib: Connected ib_insync IB instance
            contract: IBKR contract to subscribe to
            tick_buffer_minutes: How many minutes of tick history to maintain
            on_tick_callback: Called when new tick arrives (for Runner to process)
            logger: Optional logger
        """
        self.ib = ib
        self.contract = contract
        self.tick_buffer_minutes = tick_buffer_minutes
        self.on_tick_callback = on_tick_callback
        self.logger = logger or logging.getLogger(__name__)
        
        # Rolling tick buffer for velocity calculation
        self.tick_buffer = deque(maxlen=100000)  # Keep last ~100k ticks
        
        # Cached daily range (set externally or calculated on first call)
        self.daily_range: Optional[RangeInfo] = None
        self.daily_range_date: Optional[datetime] = None
        
        # Ticker for market data subscription
        self.ticker = None
        self._last_bid = None
        self._last_ask = None
        
        # Subscribe to market data
        self._subscribe_ticks()
        
    def _subscribe_ticks(self):
        """
        Subscribe to IBKR streaming market data.
        Uses reqMktData (works for all instruments including XAUUSD).
        """
        self.logger.info(f"Subscribing to tick data for {self.contract.symbol}")
        
        # Use reqMktData - works for all instruments
        self.ticker = self.ib.reqMktData(self.contract, '', False, False)
        
        # Register callback for every market data update
        self.ib.pendingTickersEvent += self._on_ticker_update
        
    def _on_ticker_update(self, tickers):
        """
        Called by ib_insync on every market data update.
        Fires whenever bid/ask/last changes.
        """
        for ticker in tickers:
            if ticker.contract and ticker.contract.conId == self.contract.conId:
                bid = ticker.bid
                ask = ticker.ask
                
                # Skip invalid prices
                if not bid or not ask or bid <= 0 or ask <= 0:
                    continue
                
                # Only record if bid or ask actually changed
                if bid != self._last_bid or ask != self._last_ask:
                    self._last_bid = bid
                    self._last_ask = ask
                    
                    tick = Tick(
                        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
                        bid=bid,
                        ask=ask
                    )
                    
                    # Buffer the tick
                    self.tick_buffer.append(tick)
                    
                    # Notify runner
                    if self.on_tick_callback:
                        self.on_tick_callback(tick)
    
    def get_velocity(self, lookback_minutes: int, current_time: datetime) -> float:
        """
        Calculate tick velocity (ticks per minute) over lookback window.
        Uses actual tick count from buffer.
        """
        cutoff_time = current_time - timedelta(minutes=lookback_minutes)
        
        # Count ticks within window
        ticks_in_window = sum(1 for t in self.tick_buffer if t.timestamp >= cutoff_time)
        
        velocity = ticks_in_window / lookback_minutes if lookback_minutes > 0 else 0.0
        
        return velocity
    
    def get_asian_range(self, start_hour: int, end_hour: int, current_time: datetime) -> Optional[RangeInfo]:
        """
        Returns pre-calculated Asian range for the current day.
        In live trading, this should be calculated at start_hour and cached.
        """
        # Check if we have a cached range for today
        current_date = current_time.date()
        
        if self.daily_range and self.daily_range_date == current_date:
            return self.daily_range
        
        # Range not available yet (will be calculated by runner at range_end_hour)
        return None
    
    def set_daily_range(self, range_info: RangeInfo, current_date: datetime):
        """
        Externally set the daily range (called by LiveRunner after calculating it).
        """
        self.daily_range = range_info
        self.daily_range_date = current_date.date()
        self.logger.info(f"Daily range set: {range_info.low:.4f} - {range_info.high:.4f}")
    
    def time_is_in_trade_window(self, current_time: datetime, start_hour: int, end_hour: int) -> bool:
        """
        Check if current time falls within trading window.
        """
        hour = current_time.hour
        return start_hour <= hour < end_hour
    
    def calculate_range_from_history(self, start_hour: int, end_hour: int) -> Optional[RangeInfo]:
        """
        Calculate range from buffered tick history (used at range_end_hour).
        Only works if we have enough buffered ticks covering the range period.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        range_start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        range_end = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        
        # Filter ticks in range window
        range_ticks = [t for t in self.tick_buffer if range_start <= t.timestamp < range_end]
        
        if not range_ticks:
            self.logger.warning(f"No ticks found in range window {start_hour}-{end_hour} UTC")
            return None
        
        high = max(t.ask for t in range_ticks)
        low = min(t.bid for t in range_ticks)
        
        return RangeInfo(
            high=high,
            low=low,
            start_time=range_start,
            end_time=range_end
        )
    
    def disconnect(self):
        """
        Cleanup: unsubscribe from market data.
        """
        self.logger.info("Disconnecting LiveMarketContext")
        self.ib.pendingTickersEvent -= self._on_ticker_update
        if self.ticker:
            self.ib.cancelMktData(self.contract)
