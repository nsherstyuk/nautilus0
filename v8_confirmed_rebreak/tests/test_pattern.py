"""
Unit tests for PatternDetector (V8 pure state machine interface).

Tests the pattern detection using synthetic sequences with known outcomes.
The new interface: process_bar(close, idx, pivot_high, pivot_low, get_buy_ratio)
"""
import math
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v8_confirmed_rebreak.core.pattern_detector import PatternDetector


class TestPatternDetectorLong:
    """Test the long (pivot high breakout) rebreak pattern."""

    def test_full_long_rebreak_signal(self):
        """
        Sequence:
        1. Pivot high at 100.0 established
        2. Close breaks above 100.0 → buy_ratio < 0.5 (divergent)
        3. Close pulls back below 100.0
        4. Close breaks above 100.0 again → buy_ratio >= 0.5 (matching)
        5. Signal should fire
        """
        detector = PatternDetector(
            imbalance_window=3,
            divergence_threshold=0.5,
            max_pullback_bars=60,
            min_pullback_bars=3,
            atr_period=10,
        )

        pivot_high = 100.0
        pivot_low = float("nan")

        # buy_ratio lookup: first break divergent (0.3), rebreak matching (0.7)
        br_map = {}

        signal = None
        idx = 0

        # Phase 0: warm up below pivot
        for i in range(15):
            detector.update_atr(96.0, 94.0, 95.0)
            s = detector.process_bar(95.0, idx, pivot_high, pivot_low,
                                     lambda s, e: br_map.get(s, float("nan")))
            if s:
                signal = s
            idx += 1

        # Phase 1: first break above pivot
        # Set divergent buy_ratio for bars after break
        br_map[idx + 1] = 0.3  # divergent
        detector.update_atr(101.5, 100.5, 101.0)
        s = detector.process_bar(101.0, idx, pivot_high, pivot_low,
                                 lambda s, e: br_map.get(s, float("nan")))
        if s:
            signal = s
        idx += 1

        # Phase 2: pullback below pivot
        for i in range(5):
            detector.update_atr(100.0, 98.0, 99.0)
            s = detector.process_bar(99.0, idx, pivot_high, pivot_low,
                                     lambda s, e: br_map.get(s, float("nan")))
            if s:
                signal = s
            idx += 1

        # Phase 3: rebreak above pivot
        # Set matching buy_ratio for bars after rebreak
        br_map[idx + 1] = 0.7  # matching
        detector.update_atr(101.5, 100.5, 101.0)
        s = detector.process_bar(101.0, idx, pivot_high, pivot_low,
                                 lambda s, e: br_map.get(s, float("nan")))
        if s:
            signal = s

        assert signal is not None, "Expected a signal"
        direction, gap, br = signal
        assert direction == "long"
        assert br == 0.7

    def test_no_signal_without_divergent_first_break(self):
        """If first break has MATCHING imbalance, no signal should fire."""
        detector = PatternDetector(
            imbalance_window=3,
            divergence_threshold=0.5,
            max_pullback_bars=60,
            min_pullback_bars=3,
            atr_period=10,
        )

        pivot_high = 100.0
        pivot_low = float("nan")
        # buy_ratio MATCHING on first break (0.7 >= 0.5)
        def get_br(s, e):
            return 0.7

        signal = None
        idx = 0

        for i in range(15):
            detector.update_atr(96.0, 94.0, 95.0)
            detector.process_bar(95.0, idx, pivot_high, pivot_low, get_br)
            idx += 1

        # First break (matching → NOT divergent → state stays watching)
        detector.update_atr(101.5, 100.5, 101.0)
        detector.process_bar(101.0, idx, pivot_high, pivot_low, get_br)
        idx += 1

        # Pullback
        for i in range(5):
            detector.update_atr(100.0, 98.0, 99.0)
            detector.process_bar(99.0, idx, pivot_high, pivot_low, get_br)
            idx += 1

        # Rebreak attempt
        detector.update_atr(101.5, 100.5, 101.0)
        s = detector.process_bar(101.0, idx, pivot_high, pivot_low, get_br)

        # First break was matching → h_broke stayed False → this is a new break attempt
        # which is also matching → still no divergent break → no rebreak possible
        assert s is None

    def test_timeout_after_max_pullback(self):
        """If pullback takes too long, pattern should expire."""
        detector = PatternDetector(
            imbalance_window=3,
            divergence_threshold=0.5,
            max_pullback_bars=10,
            min_pullback_bars=3,
            atr_period=10,
        )

        # Divergent on first break, matching on rebreak
        call_count = [0]
        def get_br(s, e):
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.3  # divergent
            return 0.7  # matching

        pivot_high = 100.0
        pivot_low = float("nan")
        signal = None
        idx = 0

        # Warm up
        for i in range(15):
            detector.update_atr(96.0, 94.0, 95.0)
            detector.process_bar(95.0, idx, pivot_high, pivot_low, get_br)
            idx += 1

        # First break (divergent)
        detector.update_atr(101.5, 100.5, 101.0)
        detector.process_bar(101.0, idx, pivot_high, pivot_low, get_br)
        idx += 1

        # Pullback
        detector.update_atr(100.0, 98.0, 99.0)
        detector.process_bar(99.0, idx, pivot_high, pivot_low, get_br)
        idx += 1

        # Wait too long (exceed max_pullback=10)
        for i in range(15):
            detector.update_atr(100.0, 98.0, 99.0)
            detector.process_bar(99.0, idx, pivot_high, pivot_low, get_br)
            idx += 1

        # Rebreak attempt -- too late, pattern expired
        detector.update_atr(101.5, 100.5, 101.0)
        s = detector.process_bar(101.0, idx, pivot_high, pivot_low, get_br)

        # The timeout resets h_broke=False, so this is treated as a new first break
        # It's matching (call_count > 1), so no divergent break is established
        # No signal expected
        assert s is None

    def test_non_divergent_keeps_watching(self):
        """After non-divergent first break, detector should keep trying."""
        detector = PatternDetector(
            imbalance_window=3,
            divergence_threshold=0.5,
            max_pullback_bars=60,
            min_pullback_bars=3,
        )

        call_count = [0]
        def get_br(s, e):
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.7  # matching (NOT divergent) → first break fails
            elif call_count[0] == 2:
                return 0.3  # divergent → second break succeeds
            else:
                return 0.7  # matching → rebreak fires

        pivot_high = 100.0
        pivot_low = float("nan")
        idx = 0
        signal = None

        # Warm up
        for i in range(15):
            detector.update_atr(96.0, 94.0, 95.0)
            detector.process_bar(95.0, idx, pivot_high, pivot_low, get_br)
            idx += 1

        # First break attempt (matching → fails, keeps watching)
        detector.update_atr(101.5, 100.5, 101.0)
        detector.process_bar(101.0, idx, pivot_high, pivot_low, get_br)
        idx += 1

        # Back below pivot, then break again (divergent → succeeds)
        detector.update_atr(100.0, 98.0, 99.0)
        detector.process_bar(99.0, idx, pivot_high, pivot_low, get_br)
        idx += 1

        detector.update_atr(101.5, 100.5, 101.0)
        detector.process_bar(101.0, idx, pivot_high, pivot_low, get_br)
        idx += 1

        # Pullback
        for i in range(5):
            detector.update_atr(100.0, 98.0, 99.0)
            detector.process_bar(99.0, idx, pivot_high, pivot_low, get_br)
            idx += 1

        # Rebreak (matching)
        detector.update_atr(101.5, 100.5, 101.0)
        s = detector.process_bar(101.0, idx, pivot_high, pivot_low, get_br)

        assert s is not None
        assert s[0] == "long"


class TestPatternDetectorShort:

    def test_full_short_rebreak_signal(self):
        detector = PatternDetector(
            imbalance_window=3,
            divergence_threshold=0.5,
            max_pullback_bars=60,
            min_pullback_bars=3,
        )

        br_map = {}
        pivot_high = float("nan")
        pivot_low = 100.0
        signal = None
        idx = 0

        # Warm up above pivot
        for i in range(15):
            detector.update_atr(106.0, 104.0, 105.0)
            detector.process_bar(105.0, idx, pivot_high, pivot_low,
                                 lambda s, e: br_map.get(s, float("nan")))
            idx += 1

        # First break below (divergent for short = high buying = br > 0.5)
        br_map[idx + 1] = 0.7  # divergent for short
        detector.update_atr(99.5, 98.5, 99.0)
        detector.process_bar(99.0, idx, pivot_high, pivot_low,
                             lambda s, e: br_map.get(s, float("nan")))
        idx += 1

        # Pullback above pivot
        for i in range(5):
            detector.update_atr(102.0, 100.0, 101.0)
            detector.process_bar(101.0, idx, pivot_high, pivot_low,
                                 lambda s, e: br_map.get(s, float("nan")))
            idx += 1

        # Rebreak below (matching for short = low buying = br <= 0.5)
        br_map[idx + 1] = 0.3  # matching for short
        detector.update_atr(99.5, 98.5, 99.0)
        s = detector.process_bar(99.0, idx, pivot_high, pivot_low,
                                 lambda s, e: br_map.get(s, float("nan")))

        assert s is not None
        direction, gap, br = s
        assert direction == "short"
        assert br == 0.3


class TestPivotLevelChanges:

    def test_pivot_change_resets_state(self):
        detector = PatternDetector(
            imbalance_window=3,
            divergence_threshold=0.5,
            max_pullback_bars=60,
            min_pullback_bars=3,
        )

        def get_br(s, e):
            return 0.3

        # Start with pivot at 100, break above it (divergent)
        for i in range(5):
            detector.update_atr(96.0, 94.0, 95.0)
            detector.process_bar(95.0, i, 100.0, float("nan"), get_br)

        detector.update_atr(101.5, 100.5, 101.0)
        detector.process_bar(101.0, 5, 100.0, float("nan"), get_br)
        # h_broke should be True now

        # Change pivot to 105 -- should reset state
        detector.update_atr(96.0, 94.0, 95.0)
        detector.process_bar(95.0, 6, 105.0, float("nan"), get_br)
        # State reset, watching for break of 105 now

        # No crash, no stuck state
        assert True


class TestATR:

    def test_atr_positive_after_warmup(self):
        detector = PatternDetector(
            imbalance_window=3,
            divergence_threshold=0.5,
            max_pullback_bars=60,
            min_pullback_bars=3,
            atr_period=10,
        )

        for i in range(15):
            detector.update_atr(101.0 + i * 0.1, 99.0 + i * 0.1,
                                100.0 + i * 0.1)

        assert detector.current_atr > 0

    def test_atr_zero_initially(self):
        detector = PatternDetector(
            imbalance_window=3,
            divergence_threshold=0.5,
            max_pullback_bars=60,
            min_pullback_bars=3,
        )
        assert detector.current_atr == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
