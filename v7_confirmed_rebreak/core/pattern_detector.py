import math
from collections import deque
from typing import Optional, List

from .market_types import Bar, RebreakSignal
from .pivot_tracker import PivotTracker
from .imbalance_classifier import ImbalanceClassifier


class _LevelState:
    """Internal state machine for tracking one pivot level through the
    breakout -> pullback -> rebreak sequence.

    Not exposed outside PatternDetector (information hiding).
    """

    __slots__ = (
        "level", "direction", "first_break_idx", "first_was_divergent",
        "pulled_back", "done",
    )

    def __init__(self, level: float, direction: str):
        self.level = level
        self.direction = direction  # "long" or "short"
        self.first_break_idx: int = -1
        self.first_was_divergent: bool = False
        self.pulled_back: bool = False
        self.done: bool = False


class PatternDetector:
    """Deep module: Detects the confirmed-rebreak pattern.

    Absorbs ALL complexity of pivot tracking, breakout detection,
    pullback monitoring, imbalance classification, and rebreak confirmation.

    Interface:
        process_bar(bar: Bar) -> List[RebreakSignal]

    One method. The strategy never touches pivots, imbalance windows,
    pullback counters, or level state machines.

    Internal complexity hidden:
        - PivotTracker for rolling pivot detection
        - ImbalanceClassifier for buy_ratio with min_tick quality filter
        - Two _LevelState machines (current pivot high, current pivot low)
        - ATR computation for SL/TP levels
        - Cooldown between signals
    """

    def __init__(self, pivot_window: int, imbalance_window: int,
                 divergence_threshold: float, max_pullback_bars: int,
                 min_pullback_bars: int, atr_period: int = 60,
                 min_bar_ticks: int = 0, confirm_bars: int = 5):
        self._pivot = PivotTracker(pivot_window, confirm_bars=confirm_bars)
        self._imbalance = ImbalanceClassifier(
            max_lookback=imbalance_window + 5,
            min_bar_ticks=min_bar_ticks,
        )
        self._imb_window = imbalance_window
        self._div_threshold = divergence_threshold
        self._max_pb = max_pullback_bars
        self._min_pb = min_pullback_bars
        self._atr_period = atr_period

        # Level state (one per direction)
        self._high_state: Optional[_LevelState] = None
        self._low_state: Optional[_LevelState] = None

        # ATR buffer
        self._tr_buffer: deque = deque(maxlen=atr_period)
        self._prev_close: Optional[float] = None
        self._current_atr: float = 0.0

        # Bar counter
        self._bar_idx: int = 0

        # Imbalance collection state for delayed assessment
        self._pending_high_break: Optional[dict] = None
        self._pending_low_break: Optional[dict] = None
        self._pending_high_rebreak: Optional[dict] = None
        self._pending_low_rebreak: Optional[dict] = None

    @property
    def current_atr(self) -> float:
        return self._current_atr

    def process_bar(self, bar: Bar) -> List[RebreakSignal]:
        """Feed one bar. Returns a list of confirmed rebreak signals (usually 0 or 1)."""
        signals = []

        # 1. Update ATR
        self._update_atr(bar)

        # 2. Update imbalance buffer (must happen BEFORE checking pending assessments)
        self._imbalance.add_bar(bar)

        # 3. Check pending imbalance assessments (we waited imb_window bars)
        sig = self._check_pending_high_break()
        sig2 = self._check_pending_low_break()
        sig3 = self._check_pending_high_rebreak(bar)
        if sig3:
            signals.append(sig3)
        sig4 = self._check_pending_low_rebreak(bar)
        if sig4:
            signals.append(sig4)

        # 4. Update pivots
        self._pivot.update(bar)

        # Update level state when pivot value changes.
        # If the state machine is mid-sequence (first break seen, waiting for
        # pullback or rebreak), keep tracking the OLD level -- a pivot change
        # doesn't invalidate an in-progress breakout pattern.
        # Only start a fresh state when the previous state is idle or done.
        if self._pivot.high_changed:
            new_level = self._pivot.current_pivot_high
            hs = self._high_state
            idle = (hs is None or hs.done or hs.first_break_idx < 0)
            if idle:
                self._high_state = _LevelState(new_level, "long")
                self._pending_high_break = None
                self._pending_high_rebreak = None

        if self._pivot.low_changed:
            new_level = self._pivot.current_pivot_low
            ls = self._low_state
            idle = (ls is None or ls.done or ls.first_break_idx < 0)
            if idle:
                self._low_state = _LevelState(new_level, "short")
                self._pending_low_break = None
                self._pending_low_rebreak = None

        # 5. Run state machines for current levels
        if self._high_state and not self._high_state.done and self._pending_high_break is None and self._pending_high_rebreak is None:
            self._process_high(bar)

        if self._low_state and not self._low_state.done and self._pending_low_break is None and self._pending_low_rebreak is None:
            self._process_low(bar)

        self._prev_close = bar.close
        self._bar_idx += 1
        return signals

    def _update_atr(self, bar: Bar) -> None:
        if self._prev_close is not None:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - self._prev_close),
                abs(bar.low - self._prev_close),
            )
        else:
            tr = bar.high - bar.low
        self._tr_buffer.append(tr)
        if len(self._tr_buffer) > 0:
            self._current_atr = sum(self._tr_buffer) / len(self._tr_buffer)

    def _process_high(self, bar: Bar) -> None:
        """State machine for pivot HIGH breakout tracking."""
        st = self._high_state
        if st is None:
            return

        if st.first_break_idx < 0:
            # WATCHING: waiting for first break above pivot high
            if bar.close > st.level:
                # Start collecting imbalance bars
                self._pending_high_break = {
                    "break_idx": self._bar_idx,
                    "bars_collected": 0,
                }
        elif not st.pulled_back:
            # BROKE: waiting for pullback below pivot
            if bar.close <= st.level:
                st.pulled_back = True
        else:
            # PULLED BACK: waiting for rebreak above pivot
            gap = self._bar_idx - st.first_break_idx
            if gap > self._max_pb:
                st.done = True
                return
            if gap >= self._min_pb and bar.close > st.level:
                # Start collecting imbalance bars for rebreak
                self._pending_high_rebreak = {
                    "rebreak_idx": self._bar_idx,
                    "bars_collected": 0,
                    "gap": gap,
                }

    def _process_low(self, bar: Bar) -> None:
        """State machine for pivot LOW breakout tracking."""
        st = self._low_state
        if st is None:
            return

        if st.first_break_idx < 0:
            # WATCHING: waiting for first break below pivot low
            if bar.close < st.level:
                self._pending_low_break = {
                    "break_idx": self._bar_idx,
                    "bars_collected": 0,
                }
        elif not st.pulled_back:
            # BROKE: waiting for pullback above pivot
            if bar.close >= st.level:
                st.pulled_back = True
        else:
            # PULLED BACK: waiting for rebreak below pivot
            gap = self._bar_idx - st.first_break_idx
            if gap > self._max_pb:
                st.done = True
                return
            if gap >= self._min_pb and bar.close < st.level:
                self._pending_low_rebreak = {
                    "rebreak_idx": self._bar_idx,
                    "bars_collected": 0,
                    "gap": gap,
                }

    def _check_pending_high_break(self) -> None:
        """After collecting imb_window bars post-breakout, assess divergence."""
        p = self._pending_high_break
        if p is None:
            return
        p["bars_collected"] += 1
        if p["bars_collected"] < self._imb_window:
            return
        # Assess
        st = self._high_state
        if st is None:
            self._pending_high_break = None
            return
        divergent = self._imbalance.is_divergent("long", self._imb_window, self._div_threshold)
        has_data = self._imbalance.has_quality_data(self._imb_window)
        if has_data:
            st.first_break_idx = p["break_idx"]
            st.first_was_divergent = divergent
            if not divergent:
                # Clean first break -- not interesting for rebreak pattern, mark done
                st.done = True
        else:
            # Low quality data, skip this break but keep watching
            pass
        self._pending_high_break = None

    def _check_pending_low_break(self) -> None:
        """After collecting imb_window bars post-breakout, assess divergence."""
        p = self._pending_low_break
        if p is None:
            return
        p["bars_collected"] += 1
        if p["bars_collected"] < self._imb_window:
            return
        st = self._low_state
        if st is None:
            self._pending_low_break = None
            return
        divergent = self._imbalance.is_divergent("short", self._imb_window, self._div_threshold)
        has_data = self._imbalance.has_quality_data(self._imb_window)
        if has_data:
            st.first_break_idx = p["break_idx"]
            st.first_was_divergent = divergent
            if not divergent:
                st.done = True
        else:
            pass
        self._pending_low_break = None

    def _check_pending_high_rebreak(self, bar: Bar) -> Optional[RebreakSignal]:
        """After collecting imb_window bars post-rebreak, assess matching."""
        p = self._pending_high_rebreak
        if p is None:
            return None
        p["bars_collected"] += 1
        if p["bars_collected"] < self._imb_window:
            return None
        st = self._high_state
        signal = None
        if st is not None and st.first_was_divergent:
            matching = self._imbalance.is_matching("long", self._imb_window, self._div_threshold)
            if matching:
                signal = RebreakSignal(
                    timestamp=bar.timestamp,
                    direction="long",
                    pivot_price=st.level,
                    entry_price=bar.close,
                    buy_ratio=self._imbalance.get_buy_ratio(self._imb_window),
                    bars_since_first=p["gap"],
                )
        if st is not None:
            st.done = True
        self._pending_high_rebreak = None
        return signal

    def _check_pending_low_rebreak(self, bar: Bar) -> Optional[RebreakSignal]:
        """After collecting imb_window bars post-rebreak, assess matching."""
        p = self._pending_low_rebreak
        if p is None:
            return None
        p["bars_collected"] += 1
        if p["bars_collected"] < self._imb_window:
            return None
        st = self._low_state
        signal = None
        if st is not None and st.first_was_divergent:
            matching = self._imbalance.is_matching("short", self._imb_window, self._div_threshold)
            if matching:
                signal = RebreakSignal(
                    timestamp=bar.timestamp,
                    direction="short",
                    pivot_price=st.level,
                    entry_price=bar.close,
                    buy_ratio=self._imbalance.get_buy_ratio(self._imb_window),
                    bars_since_first=p["gap"],
                )
        if st is not None:
            st.done = True
        self._pending_low_rebreak = None
        return signal

    def reset(self) -> None:
        """Full reset. Used between trading days if needed."""
        self._pivot.reset()
        self._imbalance.reset()
        self._high_state = None
        self._low_state = None
        self._tr_buffer.clear()
        self._prev_close = None
        self._current_atr = 0.0
        self._bar_idx = 0
        self._pending_high_break = None
        self._pending_low_break = None
        self._pending_high_rebreak = None
        self._pending_low_rebreak = None
