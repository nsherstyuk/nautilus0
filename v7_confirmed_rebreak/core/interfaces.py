from abc import ABC, abstractmethod
from typing import Optional

from .market_types import Bar, Fill


class ExecutionEngine(ABC):
    """Deep module: Hides order management, fill simulation, and position tracking.

    The strategy calls enter/close and receives Fill events back.
    It never knows if it is talking to a simulator or a live broker.
    """

    @abstractmethod
    def enter(self, direction: str, entry_price: float,
              sl_price: float, tp_price: float) -> None:
        """Place a market entry with SL/TP brackets."""
        pass

    @abstractmethod
    def close_at_market(self, bar: Bar, reason: str = "TIME_STOP") -> Optional[Fill]:
        """Close any open position at the current bar's close."""
        pass

    @abstractmethod
    def process_bar(self, bar: Bar) -> Optional[Fill]:
        """Check if SL or TP was hit during this bar. Returns Fill if so."""
        pass

    @abstractmethod
    def has_position(self) -> bool:
        pass

    @abstractmethod
    def reset(self) -> None:
        pass
