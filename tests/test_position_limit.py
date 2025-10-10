"""Unit tests for position limit enforcement in MovingAverageCrossover."""
from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from strategies.moving_average_crossover import (
    MovingAverageCrossover,
    MovingAverageCrossoverConfig,
)


class TestPositionLimitEnforcement(unittest.TestCase):
    def setUp(self) -> None:
        config = MovingAverageCrossoverConfig(
            instrument_id="SPY.SMART",
            bar_spec="1-MINUTE-LAST",
            fast_period=5,
            slow_period=10,
            trade_size=Decimal("100"),
            enforce_position_limit=True,
            allow_position_reversal=False,
        )
        self.strategy = MovingAverageCrossover(config)
        # Override runtime dependencies with mocks
        self.strategy.cache = MagicMock()
        self.strategy.portfolio = MagicMock()
        self.strategy.portfolio.net_position.return_value = None
        self.strategy.id = "TEST_STRATEGY"
        self.strategy.log = MagicMock()
        self.strategy.fast_sma = MagicMock()
        self.strategy.slow_sma = MagicMock()
        self.strategy.fast_sma.value = Decimal("1")
        self.strategy.slow_sma.value = Decimal("2")
        self.strategy.fast_sma.reset = MagicMock()
        self.strategy.slow_sma.reset = MagicMock()

    def _mock_position(self, side: str) -> SimpleNamespace:
        return SimpleNamespace(
            side=side,
            is_long=side.upper() == "LONG",
            is_short=side.upper() == "SHORT",
        )

    def _mock_bar(self) -> SimpleNamespace:
        now = datetime.utcnow()
        ts_ns = int(now.timestamp() * 1_000_000_000)
        return SimpleNamespace(ts_event=ts_ns, ts_init=ts_ns)

    def test_on_bar_flat_bullish_executes_buy(self) -> None:
        bar = self._mock_bar()
        bar.bar_type = SimpleNamespace(instrument_id=self.strategy.instrument_id, spec=self.strategy.bar_type.spec)
        # Simulate bullish crossover with indicators
        self.strategy.fast_sma.value = Decimal("2")
        self.strategy.slow_sma.value = Decimal("1")
        self.strategy._prev_fast = Decimal("1")
        self.strategy._prev_slow = Decimal("1")

        self.strategy.close_all_positions = MagicMock()
        self.strategy.buy = MagicMock()
        self.strategy.sell = MagicMock()

        self.strategy.on_bar(bar)

        self.strategy.close_all_positions.assert_not_called()
        self.strategy.buy.assert_called_once()
        self.strategy.sell.assert_not_called()

    def test_on_bar_strict_close_only(self) -> None:
        bar = self._mock_bar()
        bar.bar_type = SimpleNamespace(instrument_id=self.strategy.instrument_id, spec=self.strategy.bar_type.spec)
        self.strategy.fast_sma.value = Decimal("1")
        self.strategy.slow_sma.value = Decimal("2")
        self.strategy._prev_fast = Decimal("2")
        self.strategy._prev_slow = Decimal("2")

        long_position = self._mock_position("LONG")
        self.strategy.portfolio.net_position.return_value = long_position
        self.strategy.close_all_positions = MagicMock()
        self.strategy.buy = MagicMock()
        self.strategy.sell = MagicMock()

        self.strategy.on_bar(bar)

        self.strategy.close_all_positions.assert_called_once_with(self.strategy.instrument_id)
        self.strategy.buy.assert_not_called()
        self.strategy.sell.assert_not_called()

    def test_on_bar_strict_close_only_bullish(self) -> None:
        bar = self._mock_bar()
        bar.bar_type = SimpleNamespace(instrument_id=self.strategy.instrument_id, spec=self.strategy.bar_type.spec)
        self.strategy.fast_sma.value = Decimal("2")
        self.strategy.slow_sma.value = Decimal("1")
        self.strategy._prev_fast = Decimal("1")
        self.strategy._prev_slow = Decimal("1")

        short_position = self._mock_position("SHORT")
        self.strategy.portfolio.net_position.return_value = short_position
        self.strategy.close_all_positions = MagicMock()
        self.strategy.buy = MagicMock()
        self.strategy.sell = MagicMock()

        self.strategy.on_bar(bar)

        self.strategy.close_all_positions.assert_called_once_with(self.strategy.instrument_id)
        self.strategy.buy.assert_not_called()
        self.strategy.sell.assert_not_called()

    def test_on_bar_reversal_mode_executes_sell(self) -> None:
        bar = self._mock_bar()
        bar.bar_type = SimpleNamespace(instrument_id=self.strategy.instrument_id, spec=self.strategy.bar_type.spec)
        self.strategy.fast_sma.value = Decimal("1")
        self.strategy.slow_sma.value = Decimal("2")
        self.strategy._prev_fast = Decimal("2")
        self.strategy._prev_slow = Decimal("2")

        self.strategy._allow_reversal = True
        long_position = self._mock_position("LONG")
        self.strategy.portfolio.net_position.return_value = long_position
        self.strategy.close_all_positions = MagicMock()
        self.strategy.buy = MagicMock()
        self.strategy.sell = MagicMock()

        self.strategy.on_bar(bar)

        self.strategy.close_all_positions.assert_called_once_with(self.strategy.instrument_id)
        self.strategy.sell.assert_called_once()
        self.strategy.buy.assert_not_called()

    def test_position_limit_enforced_rejects_signal_when_position_open(self) -> None:
        self.strategy.portfolio.net_position.return_value = self._mock_position("LONG")
        can_trade, reason = self.strategy._check_can_open_position("BUY")
        self.assertFalse(can_trade)
        self.assertIn("Position already open", reason)

    def test_position_limit_allows_trade_when_flat(self) -> None:
        self.strategy.portfolio.net_position.return_value = None
        can_trade, reason = self.strategy._check_can_open_position("BUY")
        self.assertTrue(can_trade)
        self.assertEqual("", reason)

    def test_position_reversal_allowed_when_configured(self) -> None:
        self.strategy._allow_reversal = True
        self.strategy.portfolio.net_position.return_value = self._mock_position("LONG")
        can_trade, reason = self.strategy._check_can_open_position("SELL")
        self.assertTrue(can_trade)
        self.assertEqual("reversal_allowed", reason)

    def test_position_limit_disabled_allows_all_trades(self) -> None:
        self.strategy._enforce_position_limit = False
        self.strategy.portfolio.net_position.return_value = self._mock_position("LONG")
        for signal in ("BUY", "SELL"):
            can_trade, reason = self.strategy._check_can_open_position(signal)
            self.assertTrue(can_trade)
            self.assertEqual("", reason)

    def test_rejected_signals_tracking(self) -> None:
        bar = self._mock_bar()
        self.strategy._log_rejected_signal("BUY", "Position already open", bar)
        rejected = self.strategy.get_rejected_signals()
        self.assertEqual(len(rejected), 1)
        entry = rejected[0]
        self.assertEqual(entry["signal_type"], "BUY")
        self.assertEqual(entry["reason"], "Position already open")
        self.assertEqual(entry["timestamp"], bar.ts_event)
        self.strategy.log.info.assert_called()

    def test_rejected_signals_reset_on_strategy_reset(self) -> None:
        bar = self._mock_bar()
        self.strategy._log_rejected_signal("BUY", "Position already open", bar)
        self.strategy.on_reset()
        self.assertEqual(self.strategy.get_rejected_signals(), [])
        self.strategy.fast_sma.reset.assert_called_once()
        self.strategy.slow_sma.reset.assert_called_once()


if __name__ == "__main__":
    unittest.main()
