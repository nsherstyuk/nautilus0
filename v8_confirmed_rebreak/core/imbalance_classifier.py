"""
Deep module: Computes and classifies volume imbalance from bar data.

Maintains a rolling buffer of recent bars' buy/sell volumes.
Provides buy_ratio over a configurable lookback window and
classifies whether the imbalance diverges from or matches
a given price direction.

Interface:
    add_bar(bar)
    get_buy_ratio(window) -> float
    is_divergent(direction, window) -> bool
    is_matching(direction, window) -> bool
"""
import math
from collections import deque

from .types import Bar


class ImbalanceClassifier:

    def __init__(self, max_lookback: int = 10, min_bar_ticks: int = 0):
        self._buy_vols: deque = deque(maxlen=max_lookback)
        self._sell_vols: deque = deque(maxlen=max_lookback)
        self._tick_counts: deque = deque(maxlen=max_lookback)
        self._min_bar_ticks = min_bar_ticks

    def add_bar(self, bar: Bar) -> None:
        self._buy_vols.append(bar.buy_volume)
        self._sell_vols.append(bar.sell_volume)
        self._tick_counts.append(bar.tick_count)

    def get_buy_ratio(self, window: int) -> float:
        """Buy ratio over the last `window` bars.

        Returns NaN if any bar in the window has fewer than min_bar_ticks.
        Returns 0.5 if total volume is zero.
        """
        if len(self._buy_vols) < window:
            return float("nan")
        ticks = list(self._tick_counts)[-window:]
        if self._min_bar_ticks > 0 and any(t < self._min_bar_ticks for t in ticks):
            return float("nan")
        bv = sum(list(self._buy_vols)[-window:])
        sv = sum(list(self._sell_vols)[-window:])
        total = bv + sv
        if total == 0:
            return 0.5
        return bv / total

    def is_divergent(self, direction: str, window: int,
                     threshold: float = 0.5) -> bool:
        """True if imbalance opposes the given price direction.

        For 'long' (broke above pivot): divergent if buy_ratio < threshold
        For 'short' (broke below pivot): divergent if buy_ratio > threshold
        Returns False if buy_ratio is NaN (insufficient data quality).
        """
        br = self.get_buy_ratio(window)
        if math.isnan(br):
            return False
        if direction == "long":
            return br < threshold
        else:
            return br > threshold

    def is_matching(self, direction: str, window: int,
                    threshold: float = 0.5) -> bool:
        """True if imbalance supports the given price direction.
        Returns False if buy_ratio is NaN (insufficient data quality).
        """
        br = self.get_buy_ratio(window)
        if math.isnan(br):
            return False
        if direction == "long":
            return br >= threshold
        else:
            return br <= threshold

    def has_quality_data(self, window: int) -> bool:
        """True if the last `window` bars all meet the min_bar_ticks threshold."""
        return not math.isnan(self.get_buy_ratio(window))

    def reset(self) -> None:
        self._buy_vols.clear()
        self._sell_vols.clear()
        self._tick_counts.clear()
