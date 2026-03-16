from collections import deque
from typing import Optional

from .market_types import Bar


class PivotTracker:
    """Deep module: Maintains rolling confirmed pivot highs and lows.

    Uses asymmetric confirmation: looks back `window` bars for a local
    extreme and requires only `confirm_bars` bars on the right side to
    confirm it (no new extreme exceeded the candidate).

    Buffer layout (window + confirm_bars + 1 total):
        [--- window bars ---][candidate bar][--- confirm_bars ---]

    The candidate bar (at index `window` in the buffer) is a confirmed
    pivot high if its high >= max of the entire buffer. Similarly for
    pivot low.

    With confirm_bars=5 (default), this gives near-research-quality
    pivot levels with only a 5-bar delay -- sufficient for 1-min bars
    where true turning points are obvious within minutes.

    Interface:
        update(bar) -- feed a new bar
        current_pivot_high -> Optional[float]
        current_pivot_low -> Optional[float]
        high_changed -> bool (did the value change on last update?)
        low_changed -> bool
    """

    def __init__(self, window: int, confirm_bars: int = 5):
        self._window = window
        self._confirm = confirm_bars
        self._buf_size = window + confirm_bars + 1
        self._highs: deque = deque(maxlen=self._buf_size)
        self._lows: deque = deque(maxlen=self._buf_size)
        self._pivot_high: Optional[float] = None
        self._pivot_low: Optional[float] = None
        self._bar_count = 0
        self._high_changed = False
        self._low_changed = False

    @property
    def current_pivot_high(self) -> Optional[float]:
        return self._pivot_high

    @property
    def current_pivot_low(self) -> Optional[float]:
        return self._pivot_low

    @property
    def high_changed(self) -> bool:
        """True if the pivot high VALUE changed on the last update call."""
        return self._high_changed

    @property
    def low_changed(self) -> bool:
        """True if the pivot low VALUE changed on the last update call."""
        return self._low_changed

    @property
    def ready(self) -> bool:
        return self._bar_count >= self._buf_size

    def update(self, bar: Bar) -> None:
        """Feed a new bar. Check if the candidate bar is a confirmed pivot."""
        self._high_changed = False
        self._low_changed = False

        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._bar_count += 1

        if self._bar_count < self._buf_size:
            return

        # Candidate bar is at index `window` in the buffer
        cand_high = self._highs[self._window]
        cand_low = self._lows[self._window]

        # Confirmed pivot high: candidate >= everything in the buffer
        if cand_high >= max(self._highs):
            if cand_high != self._pivot_high:
                self._pivot_high = cand_high
                self._high_changed = True

        # Confirmed pivot low: candidate <= everything in the buffer
        if cand_low <= min(self._lows):
            if cand_low != self._pivot_low:
                self._pivot_low = cand_low
                self._low_changed = True

    def reset(self) -> None:
        """Clear all state."""
        self._highs.clear()
        self._lows.clear()
        self._pivot_high = None
        self._pivot_low = None
        self._bar_count = 0
