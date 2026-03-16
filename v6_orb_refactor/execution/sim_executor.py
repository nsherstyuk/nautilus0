from typing import Optional, Callable

from ..core.interfaces import ExecutionEngine
from ..core.market_event import Fill, RangeInfo, Tick


class SimExecutionEngine(ExecutionEngine):
    """
    Simulates bracket order execution for backtesting.
    Applies exact fill logic to match v5 parity.
    """
    
    def __init__(self, spread: float, slippage: float, on_fill_callback: Callable[[Fill], None]):
        self.spread = spread
        self.slippage = slippage
        self.on_fill_callback = on_fill_callback
        
        # Resting orders
        self.long_entry_stop: Optional[float] = None
        self.short_entry_stop: Optional[float] = None
        
        # Active position management
        self.position = 0  # 1 for LONG, -1 for SHORT
        self.entry_price: Optional[float] = None
        self.sl_price: Optional[float] = None
        self.tp_price: Optional[float] = None
        
        # Track last tick for market close execution
        self.last_tick: Optional[Tick] = None
        
    def set_orb_brackets(self, range_info: RangeInfo, rr_ratio: float):
        """
        Places OCA brackets based on the Asian Range.
        """
        # Long side
        self.long_entry_stop = range_info.high
        # Short side
        self.short_entry_stop = range_info.low
        
        self.range_info = range_info
        self.rr_ratio = rr_ratio
        
    def cancel_orb_brackets(self):
        """
        Cancels resting entry brackets. 
        Does NOT cancel SL/TP if a position is already active.
        """
        self.long_entry_stop = None
        self.short_entry_stop = None
        
    def close_at_market(self):
        """
        Closes any active position immediately at market.
        Uses last processed tick for realistic fill simulation.
        """
        if self.position != 0 and self.last_tick:
            self.close_at_market_with_tick(self.last_tick)

    def _trigger_fill(self, fill: Fill):
        self.on_fill_callback(fill)
        if fill.reason == "ENTRY":
            self.cancel_orb_brackets()  # OCA cancellation
        else:
            self.position = 0
            self.entry_price = None
            self.sl_price = None
            self.tp_price = None

    def process_tick(self, tick: Tick):
        """
        Called by the backtest runner to simulate fills against the current tick.
        """
        self.last_tick = tick  # Track for potential market close
        
        if self.position == 0:
            # Check entry stops
            if self.long_entry_stop and tick.ask >= self.long_entry_stop:
                self.position = 1
                fill_price = self.long_entry_stop + self.spread
                self.entry_price = fill_price
                self.sl_price = self.range_info.low
                risk = fill_price - self.sl_price
                self.tp_price = fill_price + (risk * self.rr_ratio)
                
                self._trigger_fill(Fill(
                    timestamp=tick.timestamp,
                    price=fill_price,
                    direction="LONG",
                    reason="ENTRY"
                ))
                return  # Return immediately, evaluate SL/TP on next tick to simulate latency
                
            elif self.short_entry_stop and tick.bid <= self.short_entry_stop:
                self.position = -1
                fill_price = self.short_entry_stop - self.spread
                self.entry_price = fill_price
                self.sl_price = self.range_info.high
                risk = self.sl_price - fill_price
                self.tp_price = fill_price - (risk * self.rr_ratio)
                
                self._trigger_fill(Fill(
                    timestamp=tick.timestamp,
                    price=fill_price,
                    direction="SHORT",
                    reason="ENTRY"
                ))
                return
                
        else:
            # We are in a position, check SL and TP
            if self.position == 1:  # LONG
                if tick.bid <= self.sl_price:
                    self._trigger_fill(Fill(
                        timestamp=tick.timestamp,
                        price=self.sl_price - self.slippage,  # Assume slippage on SL stop market
                        direction="SHORT",
                        reason="SL"
                    ))
                elif tick.bid >= self.tp_price:
                    self._trigger_fill(Fill(
                        timestamp=tick.timestamp,
                        price=self.tp_price,  # TP is a limit order, usually fills at price
                        direction="SHORT",
                        reason="TP"
                    ))
            elif self.position == -1:  # SHORT
                if tick.ask >= self.sl_price:
                    self._trigger_fill(Fill(
                        timestamp=tick.timestamp,
                        price=self.sl_price + self.slippage,
                        direction="LONG",
                        reason="SL"
                    ))
                elif tick.ask <= self.tp_price:
                    self._trigger_fill(Fill(
                        timestamp=tick.timestamp,
                        price=self.tp_price,
                        direction="LONG",
                        reason="TP"
                    ))

    def close_at_market_with_tick(self, tick: Tick):
        """
        Actually closes the position at market price based on a tick.
        """
        if self.position == 1:
            self._trigger_fill(Fill(
                timestamp=tick.timestamp,
                price=tick.bid - self.slippage,
                direction="SHORT",
                reason="MARKET"
            ))
        elif self.position == -1:
            self._trigger_fill(Fill(
                timestamp=tick.timestamp,
                price=tick.ask + self.slippage,
                direction="LONG",
                reason="MARKET"
            ))
