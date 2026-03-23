from typing import Optional, Callable

from ..core.interfaces import ExecutionEngine
from ..core.market_event import Bar, Fill, RangeInfo, Tick


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
        
        # Track last tick/bar for market close execution
        self.last_tick: Optional[Tick] = None
        self.last_bar: Optional[Bar] = None
        
        # Flag: when True, skip SL/TP checks this bar (entry just happened)
        self._entry_this_bar: bool = False
        
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
        
        # Pre-calculate range-based TP levels (V5 approach)
        rs = range_info.high - range_info.low
        self._tp_long = range_info.high + rr_ratio * rs
        self._tp_short = range_info.low - rr_ratio * rs
        
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

    def modify_sl(self, new_sl_price: float):
        """Move the stop-loss on the active position."""
        if self.position != 0:
            self.sl_price = new_sl_price

    def has_position(self) -> bool:
        return self.position != 0

    def has_resting_entries(self) -> bool:
        return self.long_entry_stop is not None or self.short_entry_stop is not None

    def _trigger_fill(self, fill: Fill):
        self.on_fill_callback(fill)
        if fill.reason == "ENTRY":
            self.cancel_orb_brackets()  # OCA cancellation
        else:
            self.position = 0
            self.entry_price = None
            self.sl_price = None
            self.tp_price = None

    def process_bar(self, bar: Bar):
        """
        Bar-level fill simulation matching V5 backtest_1m.py exactly.
        
        Rules (from V5 parity):
        1. Entry: bar.high >= stop (LONG) or bar.low <= stop (SHORT)
        2. Fill price: stop + half_spread (level fill) or open +/- half_spread (gap fill)
        3. TP: range-based (range_high + rr*range_size), NOT fill-price-based
        4. SL/TP checked from NEXT bar (entry bar returns immediately)
        5. SL precedence over TP when both triggered on same bar
        6. Exit price: level +/- half_spread (spread cost on exit)
        """
        self.last_bar = bar
        hs = bar.avg_spread / 2
        
        # If entry happened this bar, skip SL/TP (V5 monitors from next bar)
        if self._entry_this_bar:
            self._entry_this_bar = False
            return
        
        if self.position == 0:
            self._check_entry(bar, hs)
        else:
            self._check_exit(bar, hs)
    
    def _check_entry(self, bar: Bar, hs: float):
        """Check if resting entry stops are triggered by this bar."""
        direction = None
        entry_px = None
        
        # OCA: check long first, then short (matches V5 ordering)
        if self.long_entry_stop is not None and bar.high >= self.long_entry_stop:
            direction = "LONG"
            if bar.open >= self.long_entry_stop:
                entry_px = bar.open + hs          # Gap fill
            else:
                entry_px = self.long_entry_stop + hs  # Level fill
        elif self.short_entry_stop is not None and bar.low <= self.short_entry_stop:
            direction = "SHORT"
            if bar.open <= self.short_entry_stop:
                entry_px = bar.open - hs          # Gap fill
            else:
                entry_px = self.short_entry_stop - hs  # Level fill
        
        if direction is None:
            return
        
        self.position = 1 if direction == "LONG" else -1
        self.entry_price = entry_px
        
        # SL/TP from range levels (V5 approach)
        if direction == "LONG":
            self.sl_price = self.range_info.low
            self.tp_price = self._tp_long
        else:
            self.sl_price = self.range_info.high
            self.tp_price = self._tp_short
        
        self._entry_this_bar = True  # Skip SL/TP check this bar
        
        self._trigger_fill(Fill(
            timestamp=bar.timestamp,
            price=entry_px,
            direction=direction,
            reason="ENTRY"
        ))
    
    def _check_exit(self, bar: Bar, hs: float):
        """Check SL/TP against bar OHLC. SL has precedence."""
        if self.position == 1:  # LONG
            if bar.low <= self.sl_price:
                self._trigger_fill(Fill(
                    timestamp=bar.timestamp,
                    price=self.sl_price - hs,
                    direction="SHORT",
                    reason="SL"
                ))
            elif bar.high >= self.tp_price:
                self._trigger_fill(Fill(
                    timestamp=bar.timestamp,
                    price=self.tp_price - hs,
                    direction="SHORT",
                    reason="TP"
                ))
        elif self.position == -1:  # SHORT
            if bar.high >= self.sl_price:
                self._trigger_fill(Fill(
                    timestamp=bar.timestamp,
                    price=self.sl_price + hs,
                    direction="LONG",
                    reason="SL"
                ))
            elif bar.low <= self.tp_price:
                self._trigger_fill(Fill(
                    timestamp=bar.timestamp,
                    price=self.tp_price + hs,
                    direction="LONG",
                    reason="TP"
                ))
    
    def close_at_market_bar(self, bar: Bar):
        """
        Close position at bar close price +/- half_spread (V5 EOD logic).
        """
        if self.position == 0:
            return
        hs = bar.avg_spread / 2
        if self.position == 1:
            self._trigger_fill(Fill(
                timestamp=bar.timestamp,
                price=bar.close - hs,
                direction="SHORT",
                reason="MARKET"
            ))
        elif self.position == -1:
            self._trigger_fill(Fill(
                timestamp=bar.timestamp,
                price=bar.close + hs,
                direction="LONG",
                reason="MARKET"
            ))

    def process_tick(self, tick: Tick):
        """
        Tick-level fill simulation (used by live trading, not for backtest parity).
        For backtest parity with V5, use process_bar() instead.
        """
        self.last_tick = tick
        
        if self.position == 0:
            hs = tick.spread / 2 if tick.spread > 0 else self.spread / 2
            if self.long_entry_stop and tick.ask >= self.long_entry_stop:
                self.position = 1
                fill_price = self.long_entry_stop + hs
                self.entry_price = fill_price
                self.sl_price = self.range_info.low
                self.tp_price = self._tp_long
                
                self._trigger_fill(Fill(
                    timestamp=tick.timestamp,
                    price=fill_price,
                    direction="LONG",
                    reason="ENTRY"
                ))
                return
                
            elif self.short_entry_stop and tick.bid <= self.short_entry_stop:
                self.position = -1
                fill_price = self.short_entry_stop - hs
                self.entry_price = fill_price
                self.sl_price = self.range_info.high
                self.tp_price = self._tp_short
                
                self._trigger_fill(Fill(
                    timestamp=tick.timestamp,
                    price=fill_price,
                    direction="SHORT",
                    reason="ENTRY"
                ))
                return
                
        else:
            if self.position == 1:  # LONG
                if tick.bid <= self.sl_price:
                    self._trigger_fill(Fill(
                        timestamp=tick.timestamp,
                        price=self.sl_price - self.slippage,
                        direction="SHORT",
                        reason="SL"
                    ))
                elif tick.bid >= self.tp_price:
                    self._trigger_fill(Fill(
                        timestamp=tick.timestamp,
                        price=self.tp_price,
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
        Close position at market using tick bid/ask.
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
