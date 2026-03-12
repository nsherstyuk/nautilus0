"""
Deep module: Detects the confirmed-rebreak pattern.

V8 design: pure state machine. Receives pivot levels and a buy_ratio
callable from the OUTSIDE. No internal delayed assessment.

Interface:
    process_bar(close, bar_idx, pivot_high, pivot_low, get_buy_ratio, ...) -> Optional[signal]

The caller provides:
    - close price, bar index
    - pivot_high / pivot_low (forward-filled)
    - get_buy_ratio(start, end) -> float callable

Backtest: passes array-slicing lambda (lookahead available)
Live: processes bars with imb_w delay (so lookahead bars are in buffer)
Either way, same PatternDetector code. Same results.
"""
import math
from collections import deque
from typing import Optional, Callable, Tuple

from .types import RebreakSignal


class PatternDetector:
    """Deep module: Detects confirmed-rebreak patterns.

    Pure state machine. Tracks breakout -> pullback -> rebreak per direction.
    Buy_ratio is evaluated immediately via caller-provided function.
    No internal buffering, no delayed assessment.

    Interface:
        process_bar(...) -> Optional[tuple]  (direction, gap, buy_ratio)
    """

    def __init__(self, imbalance_window: int,
                 divergence_threshold: float, max_pullback_bars: int,
                 min_pullback_bars: int, atr_period: int = 60):
        self._imb_window = imbalance_window
        self._div_threshold = divergence_threshold
        self._max_pb = max_pullback_bars
        self._min_pb = min_pullback_bars
        self._atr_period = atr_period

        # High-side state (long breakout)
        self._h_level: float = float("nan")
        self._h_broke: bool = False
        self._h_pb: bool = False
        self._h_idx: int = -1
        self._h_div: bool = False

        # Low-side state (short breakout)
        self._l_level: float = float("nan")
        self._l_broke: bool = False
        self._l_pb: bool = False
        self._l_idx: int = -1
        self._l_div: bool = False

        # ATR
        self._tr_buffer: deque = deque(maxlen=atr_period)
        self._prev_close: Optional[float] = None
        self._current_atr: float = 0.0

    @property
    def current_atr(self) -> float:
        return self._current_atr

    def update_atr(self, high: float, low: float, close: float) -> None:
        """Update ATR from bar OHLC. Call before process_bar."""
        if self._prev_close is not None:
            tr = max(high - low,
                     abs(high - self._prev_close),
                     abs(low - self._prev_close))
        else:
            tr = high - low
        self._tr_buffer.append(tr)
        if len(self._tr_buffer) > 0:
            self._current_atr = sum(self._tr_buffer) / len(self._tr_buffer)
        self._prev_close = close

    def process_bar(self, close: float, bar_idx: int,
                    pivot_high: float, pivot_low: float,
                    get_buy_ratio: Callable[[int, int], float]
                    ) -> Optional[Tuple[str, int, float]]:
        """Process one bar. Returns (direction, gap, buy_ratio) or None.

        Args:
            close: bar close price
            bar_idx: current bar index
            pivot_high: forward-filled pivot high at this bar (NaN if none)
            pivot_low: forward-filled pivot low at this bar (NaN if none)
            get_buy_ratio: callable(start_idx, end_idx) -> float
                Returns buy_ratio for bars [start, end). NaN if unavailable.
        """
        imb_w = self._imb_window
        div_thr = self._div_threshold
        max_pb = self._max_pb
        min_pb = self._min_pb

        # Update pivot levels -- reset state on change
        if not math.isnan(pivot_high) and pivot_high != self._h_level:
            self._h_level = pivot_high
            self._h_broke = False
            self._h_pb = False
            self._h_idx = -1

        if not math.isnan(pivot_low) and pivot_low != self._l_level:
            self._l_level = pivot_low
            self._l_broke = False
            self._l_pb = False
            self._l_idx = -1

        signal = None

        # --- LONG (pivot high breakout) ---
        if not math.isnan(self._h_level):
            if not self._h_broke:
                if close > self._h_level:
                    br = get_buy_ratio(bar_idx + 1, bar_idx + imb_w + 1)
                    if not math.isnan(br):
                        self._h_broke = True
                        self._h_idx = bar_idx
                        self._h_div = (br < div_thr)
                        if not self._h_div:
                            self._h_broke = False
            elif not self._h_pb:
                if close <= self._h_level:
                    self._h_pb = True
            else:
                gap = bar_idx - self._h_idx
                if gap > max_pb:
                    self._h_broke = False
                    self._h_pb = False
                elif gap >= min_pb and close > self._h_level:
                    br = get_buy_ratio(bar_idx + 1, bar_idx + imb_w + 1)
                    if not math.isnan(br):
                        if self._h_div and br >= div_thr:
                            signal = ("long", gap, br)
                        self._h_broke = False
                        self._h_pb = False

        # --- SHORT (pivot low breakout) ---
        if signal is None and not math.isnan(self._l_level):
            if not self._l_broke:
                if close < self._l_level:
                    br = get_buy_ratio(bar_idx + 1, bar_idx + imb_w + 1)
                    if not math.isnan(br):
                        self._l_broke = True
                        self._l_idx = bar_idx
                        self._l_div = (br > div_thr)
                        if not self._l_div:
                            self._l_broke = False
            elif not self._l_pb:
                if close >= self._l_level:
                    self._l_pb = True
            else:
                gap = bar_idx - self._l_idx
                if gap > max_pb:
                    self._l_broke = False
                    self._l_pb = False
                elif gap >= min_pb and close < self._l_level:
                    br = get_buy_ratio(bar_idx + 1, bar_idx + imb_w + 1)
                    if not math.isnan(br):
                        if self._l_div and br <= div_thr:
                            signal = ("short", gap, br)
                        self._l_broke = False
                        self._l_pb = False

        return signal

    def reset(self) -> None:
        """Full reset."""
        self._h_level = float("nan")
        self._h_broke = False
        self._h_pb = False
        self._h_idx = -1
        self._h_div = False
        self._l_level = float("nan")
        self._l_broke = False
        self._l_pb = False
        self._l_idx = -1
        self._l_div = False
        self._tr_buffer.clear()
        self._prev_close = None
        self._current_atr = 0.0
