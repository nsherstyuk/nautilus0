"""
Unit tests for ImbalanceClassifier.
"""
import math
import pytest
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v8_confirmed_rebreak.core.types import Bar
from v8_confirmed_rebreak.core.imbalance_classifier import ImbalanceClassifier


def make_bar(buy_vol: float, sell_vol: float, tick_count: int = 100) -> Bar:
    """Helper to create a bar with specific volume data."""
    return Bar(
        timestamp=datetime(2025, 1, 1),
        open=100.0, high=101.0, low=99.0, close=100.0,
        tick_count=tick_count,
        buy_volume=buy_vol,
        sell_volume=sell_vol,
    )


class TestBuyRatio:

    def test_equal_volume(self):
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(50, 50))
        assert ic.get_buy_ratio(1) == 0.5

    def test_all_buying(self):
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(100, 0))
        assert ic.get_buy_ratio(1) == 1.0

    def test_all_selling(self):
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(0, 100))
        assert ic.get_buy_ratio(1) == 0.0

    def test_window_aggregation(self):
        """Buy ratio should aggregate over the window."""
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(80, 20))  # 80% buy
        ic.add_bar(make_bar(20, 80))  # 20% buy
        ic.add_bar(make_bar(50, 50))  # 50% buy
        # Total: 150 buy, 150 sell = 50%
        assert ic.get_buy_ratio(3) == pytest.approx(0.5)

    def test_insufficient_bars(self):
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(50, 50))
        assert math.isnan(ic.get_buy_ratio(3))

    def test_zero_volume(self):
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(0, 0))
        assert ic.get_buy_ratio(1) == 0.5

    def test_min_bar_ticks_filter(self):
        """Bars below min_bar_ticks should cause NaN."""
        ic = ImbalanceClassifier(max_lookback=10, min_bar_ticks=50)
        ic.add_bar(make_bar(50, 50, tick_count=100))  # OK
        ic.add_bar(make_bar(50, 50, tick_count=10))   # Below threshold
        assert math.isnan(ic.get_buy_ratio(2))

    def test_min_bar_ticks_all_pass(self):
        ic = ImbalanceClassifier(max_lookback=10, min_bar_ticks=50)
        ic.add_bar(make_bar(70, 30, tick_count=100))
        ic.add_bar(make_bar(30, 70, tick_count=100))
        assert ic.get_buy_ratio(2) == pytest.approx(0.5)


class TestDivergenceMatching:

    def test_long_divergent(self):
        """Long breakout + low buy_ratio = divergent."""
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(20, 80))  # buy_ratio = 0.2
        assert ic.is_divergent("long", 1, threshold=0.5) is True
        assert ic.is_matching("long", 1, threshold=0.5) is False

    def test_long_matching(self):
        """Long breakout + high buy_ratio = matching."""
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(80, 20))  # buy_ratio = 0.8
        assert ic.is_divergent("long", 1, threshold=0.5) is False
        assert ic.is_matching("long", 1, threshold=0.5) is True

    def test_short_divergent(self):
        """Short breakout + high buy_ratio = divergent."""
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(80, 20))
        assert ic.is_divergent("short", 1, threshold=0.5) is True
        assert ic.is_matching("short", 1, threshold=0.5) is False

    def test_short_matching(self):
        """Short breakout + low buy_ratio = matching."""
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(20, 80))
        assert ic.is_divergent("short", 1, threshold=0.5) is False
        assert ic.is_matching("short", 1, threshold=0.5) is True

    def test_nan_returns_false(self):
        """NaN buy_ratio should return False for both."""
        ic = ImbalanceClassifier(max_lookback=10, min_bar_ticks=50)
        ic.add_bar(make_bar(50, 50, tick_count=10))  # Below threshold
        assert ic.is_divergent("long", 1) is False
        assert ic.is_matching("long", 1) is False


class TestReset:

    def test_reset_clears_state(self):
        ic = ImbalanceClassifier(max_lookback=10)
        ic.add_bar(make_bar(50, 50))
        ic.reset()
        assert math.isnan(ic.get_buy_ratio(1))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
