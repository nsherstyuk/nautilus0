from typing import Optional, Callable

from ..core.market_types import Bar, Fill
from ..core.interfaces import ExecutionEngine


class SimExecutionEngine(ExecutionEngine):
    """Backtest fill simulator.

    Simulates order execution with spread and slippage.
    Checks SL/TP against bar high/low each bar.

    Fill precedence: SL checked before TP (conservative).
    """

    def __init__(self, spread: float = 0.30,
                 on_fill_callback: Optional[Callable] = None):
        self._spread = spread
        self._on_fill = on_fill_callback

        # Position state
        self._direction: Optional[str] = None  # "long" or "short"
        self._entry_price: float = 0.0
        self._sl_price: float = 0.0
        self._tp_price: float = 0.0
        self._entry_bar: Optional[Bar] = None

    def has_position(self) -> bool:
        return self._direction is not None

    def enter(self, direction: str, entry_price: float,
              sl_price: float, tp_price: float) -> None:
        # Apply half-spread slippage to entry
        if direction == "long":
            self._entry_price = entry_price + self._spread / 2
        else:
            self._entry_price = entry_price - self._spread / 2
        self._direction = direction
        self._sl_price = sl_price
        self._tp_price = tp_price

    def close_at_market(self, bar: Bar, reason: str = "TIME_STOP") -> Optional[Fill]:
        if self._direction is None:
            return None
        # Apply half-spread slippage to exit
        if self._direction == "long":
            exit_price = bar.close - self._spread / 2
            pnl = exit_price - self._entry_price
        else:
            exit_price = bar.close + self._spread / 2
            pnl = self._entry_price - exit_price

        fill = Fill(
            timestamp=bar.timestamp,
            price=exit_price,
            direction=self._direction,
            reason=reason,
            pnl=pnl,
        )
        self._direction = None
        if self._on_fill:
            self._on_fill(fill)
        return fill

    def process_bar(self, bar: Bar) -> Optional[Fill]:
        """Check if SL or TP hit during this bar."""
        if self._direction is None:
            return None

        if self._direction == "long":
            # SL hit? (price went below SL)
            if bar.low <= self._sl_price:
                pnl = self._sl_price - self._entry_price
                fill = Fill(
                    timestamp=bar.timestamp,
                    price=self._sl_price,
                    direction="long",
                    reason="SL",
                    pnl=pnl,
                )
                self._direction = None
                if self._on_fill:
                    self._on_fill(fill)
                return fill
            # TP hit?
            if bar.high >= self._tp_price:
                pnl = self._tp_price - self._entry_price
                fill = Fill(
                    timestamp=bar.timestamp,
                    price=self._tp_price,
                    direction="long",
                    reason="TP",
                    pnl=pnl,
                )
                self._direction = None
                if self._on_fill:
                    self._on_fill(fill)
                return fill

        else:  # short
            # SL hit? (price went above SL)
            if bar.high >= self._sl_price:
                pnl = self._entry_price - self._sl_price
                fill = Fill(
                    timestamp=bar.timestamp,
                    price=self._sl_price,
                    direction="short",
                    reason="SL",
                    pnl=pnl,
                )
                self._direction = None
                if self._on_fill:
                    self._on_fill(fill)
                return fill
            # TP hit?
            if bar.low <= self._tp_price:
                pnl = self._entry_price - self._tp_price
                fill = Fill(
                    timestamp=bar.timestamp,
                    price=self._tp_price,
                    direction="short",
                    reason="TP",
                    pnl=pnl,
                )
                self._direction = None
                if self._on_fill:
                    self._on_fill(fill)
                return fill

        return None

    def reset(self) -> None:
        self._direction = None
        self._entry_price = 0.0
        self._sl_price = 0.0
        self._tp_price = 0.0
        self._entry_bar = None
