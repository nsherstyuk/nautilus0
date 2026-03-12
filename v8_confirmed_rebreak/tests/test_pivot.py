"""
Unit tests for pivot_computer module.
"""
import numpy as np
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v8_confirmed_rebreak.core.pivot_computer import batch_centered


class TestBatchCentered:

    def test_simple_peak(self):
        """A single peak in the middle should be detected as pivot high."""
        # 11 bars: ramp up to bar 5, ramp down. window=2 → full_win=5
        highs = np.array([1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1], dtype=float)
        lows = np.array([0, 1, 2, 3, 4, 5, 4, 3, 2, 1, 0], dtype=float)
        ph, pl = batch_centered(highs, lows, window=2, shift=0)

        # Bar 5 (value 6) is the peak; with window=2, centered rolling max
        # needs 2 bars each side. At shift=0, visible immediately.
        # After the pivot is detected, it forward-fills
        assert ph[5] == 6.0 or ph[6] == 6.0  # visible at or right after peak
        # Before peak: no pivot high yet
        assert np.isnan(ph[0])

    def test_simple_trough(self):
        """A single trough should be detected as pivot low."""
        highs = np.array([6, 5, 4, 3, 2, 1, 2, 3, 4, 5, 6], dtype=float)
        lows = np.array([5, 4, 3, 2, 1, 0, 1, 2, 3, 4, 5], dtype=float)
        ph, pl = batch_centered(highs, lows, window=2, shift=0)

        # Bar 5 (value 0) is the trough
        assert pl[5] == 0.0 or pl[6] == 0.0
        assert np.isnan(pl[0])

    def test_shift_delays_visibility(self):
        """With shift > 0, pivot should appear later than shift=0."""
        highs = np.array([1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1], dtype=float)
        lows = np.array([0, 1, 2, 3, 4, 5, 4, 3, 2, 1, 0], dtype=float)

        ph_0, _ = batch_centered(highs, lows, window=2, shift=0)
        ph_3, _ = batch_centered(highs, lows, window=2, shift=3)

        # Find first non-NaN index for each
        first_0 = np.argmin(np.isnan(ph_0))
        first_3 = np.argmin(np.isnan(ph_3))
        assert first_3 >= first_0 + 3  # shift=3 delays by at least 3

    def test_forward_fill(self):
        """Once detected, pivot value should persist (forward-fill)."""
        n = 30
        highs = np.concatenate([
            np.arange(1, 11, dtype=float),   # ramp up to 10
            np.arange(9, -1, -1, dtype=float),  # ramp down
            np.arange(1, 11, dtype=float),   # ramp up again
        ])
        lows = highs - 1.0
        ph, _ = batch_centered(highs, lows, window=3, shift=0)

        # After the first pivot high is detected, all subsequent bars
        # should have a non-NaN value (forward-filled)
        first_valid = np.argmin(np.isnan(ph))
        assert first_valid > 0
        assert all(~np.isnan(ph[first_valid:]))

    def test_output_shape(self):
        """Output arrays should match input length."""
        n = 100
        highs = np.random.rand(n) + 10
        lows = np.random.rand(n) + 9
        ph, pl = batch_centered(highs, lows, window=5, shift=2)
        assert len(ph) == n
        assert len(pl) == n

    def test_no_pivots_in_flat_market(self):
        """Constant prices: every bar is max and min, so pivots appear."""
        highs = np.full(20, 100.0)
        lows = np.full(20, 99.0)
        ph, pl = batch_centered(highs, lows, window=3, shift=0)
        # In a flat market, every bar IS the rolling max/min
        # So pivots should eventually appear
        assert not all(np.isnan(ph))
        assert not all(np.isnan(pl))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
