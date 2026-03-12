"""
V8 Confirmed Rebreak -- Core Types

Single source of truth for all data types used across backtest and live.
All value objects are frozen dataclasses (immutable).
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Bar:
    """A 1-minute OHLCV bar with tick volume breakdown."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    tick_count: int
    buy_volume: float
    sell_volume: float

    @property
    def total_volume(self) -> float:
        return self.buy_volume + self.sell_volume

    @property
    def buy_ratio(self) -> float:
        total = self.total_volume
        if total == 0:
            return 0.5
        return self.buy_volume / total

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2


@dataclass(frozen=True)
class RebreakSignal:
    """Emitted by PatternDetector when a confirmed rebreak is detected.

    The strategy receives this and decides whether to trade.
    All pattern-detection complexity is hidden behind this simple object.
    """
    timestamp: datetime
    direction: str          # "long" or "short"
    pivot_price: float      # the level that was re-broken
    entry_price: float      # price at the confirmation bar
    buy_ratio: float        # buy_ratio at confirmation
    bars_since_first: int   # gap between first break and rebreak


@dataclass(frozen=True)
class Fill:
    """An execution event reported by the ExecutionEngine."""
    timestamp: datetime
    price: float
    direction: str      # "long" or "short"
    reason: str         # "ENTRY", "SL", "TP", "TIME_STOP", "CATASTROPHE_SL"
    pnl: float = 0.0   # realized P&L (0 for entries)


@dataclass
class TradeRecord:
    """Complete record of a round-trip trade for reporting."""
    entry_time: datetime
    exit_time: Optional[datetime]
    direction: str
    entry_price: float
    exit_price: float
    sl_price: float
    tp_price: float
    pivot_price: float
    exit_reason: str
    pnl: float
    hold_bars: int
    buy_ratio_at_entry: float
    gap: int = 0
