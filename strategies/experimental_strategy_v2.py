"""Experimental V2 strategy scaffold.

This strategy is intentionally isolated from the existing V2 ML strategy so you can
iterate on alternative entry/exit logic while keeping the current strategy intact.

Safety: by default this strategy will NOT place orders unless
MTF2_EXPERIMENTAL_ALLOW_ORDERS=1 is set in the environment.
"""

from __future__ import annotations

import os
import logging
from collections import deque
from dataclasses import dataclass

import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


_logger = logging.getLogger("ExperimentalStrategy_V2")
_logger.setLevel(logging.INFO)


class ExperimentalStrategyV2Config(StrategyConfig, kw_only=True):
    instrument_id: str
    bar_type: str

    total_position_size: int = 100000

    trade_start_hour: int = 0
    trade_end_hour: int = 23

    order_id_tag: str = "V2-EXP"


@dataclass
class _PositionState:
    is_open: bool = False
    entry_time: pd.Timestamp | None = None


class ExperimentalStrategyV2(Strategy):
    def __init__(self, config: ExperimentalStrategyV2Config):
        super().__init__(config)

        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.order_id_tag = config.order_id_tag

        self._size = Quantity.from_int(int(config.total_position_size))
        self._trade_start_hour = int(config.trade_start_hour)
        self._trade_end_hour = int(config.trade_end_hour)

        self._allow_orders = os.getenv("MTF2_EXPERIMENTAL_ALLOW_ORDERS", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }

        self._bars_15m: deque[Bar] = deque(maxlen=200)
        self._pos = _PositionState()

    def on_start(self) -> None:
        if os.getenv("MTF2_REPLAY_MODE", "0").strip().lower() in {"1", "true", "yes"}:
            self.subscribe_bars(self.bar_type)

        _logger.info("Experimental strategy started")
        _logger.info("Instrument: %s", self.instrument_id)
        _logger.info("BarType: %s", self.bar_type)
        _logger.info("Orders enabled: %s (MTF2_EXPERIMENTAL_ALLOW_ORDERS)", self._allow_orders)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type != self.bar_type:
            return

        self._bars_15m.append(bar)
        if len(self._bars_15m) < 60:
            return

        ts = pd.Timestamp(bar.ts_event, unit="ns", tz="UTC")
        hour = int(ts.hour)
        if hour < self._trade_start_hour or hour > self._trade_end_hour:
            return

        if not self._allow_orders:
            return

        if not self._pos.is_open:
            self._submit_market(OrderSide.BUY)
            self._pos.is_open = True
            self._pos.entry_time = ts
            return

        if self._pos.entry_time is not None and ts >= self._pos.entry_time + pd.Timedelta(minutes=60):
            self._submit_market(OrderSide.SELL)
            self._pos = _PositionState()

    def _submit_market(self, side: OrderSide) -> None:
        order = MarketOrder(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=self._size,
            tags=[self.order_id_tag],
        )
        self.submit_order(order)
