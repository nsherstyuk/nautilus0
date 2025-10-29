from __future__ import annotations

import logging
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Deque, Literal, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from ib_insync import Forex, IB, Order

from config.ibkr_config import get_ibkr_config, get_market_data_type_enum
from config.live_config import get_live_config
from live.bar_utils import Bar, BarAggregator, timeframe_to_seconds


logger = logging.getLogger("ib_insync_runner")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@dataclass
class TradeSignal:
    action: Literal["BUY", "SELL"]
    price: float
    bar: Bar


class MovingAverageStrategy:
    """Lightweight SMA crossover strategy independent of NautilusTrader."""

    def __init__(self, fast_period: int, slow_period: int) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be strictly less than slow_period")

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.closes: Deque[float] = deque(maxlen=slow_period)
        self._prev_fast: Optional[float] = None
        self._prev_slow: Optional[float] = None

    def on_bar(self, bar: Bar) -> Optional[TradeSignal]:
        self.closes.append(bar.close)
        if len(self.closes) < self.slow_period:
            return None

        fast = self._sma(self.fast_period)
        slow = self._sma(self.slow_period)

        signal: Optional[TradeSignal] = None
        if self._prev_fast is not None and self._prev_slow is not None:
            crossed_up = fast > slow and self._prev_fast <= self._prev_slow
            crossed_down = fast < slow and self._prev_fast >= self._prev_slow

            if crossed_up:
                signal = TradeSignal(action="BUY", price=bar.close, bar=bar)
            elif crossed_down:
                signal = TradeSignal(action="SELL", price=bar.close, bar=bar)

        self._prev_fast = fast
        self._prev_slow = slow
        return signal

    def _sma(self, period: int) -> float:
        if period > len(self.closes):
            raise ValueError("Not enough data for SMA computation")
        values = list(self.closes)[-period:]
        return sum(values) / period


def pip_value_for_symbol(symbol: str) -> float:
    base = symbol.replace("/", "").upper()
    if base.endswith("JPY"):
        return 0.01
    return 0.0001


def round_to_pips(price: float, pip: float) -> float:
    return round(round(price / pip) * pip, 10)


class IBInsyncTrader:
    def __init__(self) -> None:
        load_dotenv()
        self.ib_config = get_ibkr_config()
        self.live_config = get_live_config()

        symbol = self.live_config.symbol.replace("/", "")
        self.contract = Forex(symbol)
        bar_seconds = timeframe_to_seconds(self.live_config.bar_spec)
        self.aggregator = BarAggregator(seconds=bar_seconds)
        self.strategy = MovingAverageStrategy(
            fast_period=self.live_config.fast_period,
            slow_period=self.live_config.slow_period,
        )
        self.pip = pip_value_for_symbol(symbol)

        self.ib = IB()
        self.ticker = None
        self._running = False

    def run(self) -> None:
        logger.info(
            "Connecting to IBKR host=%s port=%s client_id=%s",
            self.ib_config.host,
            self.ib_config.port,
            self.ib_config.client_id,
        )
        try:
            self.ib.connect(
                host=self.ib_config.host,
                port=self.ib_config.port,
                clientId=self.ib_config.client_id,
                timeout=30,
            )
        except TimeoutError as exc:
            logger.error("IBKR connection attempt timed out after 30s")
            logger.error("Tip: ensure no other session is using client id %s and rerun.", self.ib_config.client_id)
            self.ib.disconnect()
            raise

        if not self.ib.isConnected():
            raise RuntimeError("Failed to connect to IBKR")

        market_data_type = get_market_data_type_enum(self.ib_config.market_data_type)
        self.ib.reqMarketDataType(market_data_type)

        self.ib.qualifyContracts(self.contract)
        self.ib.reqPositions()
        self.ticker = self.ib.reqMktData(self.contract, "", False, False)
        logger.info("Subscribed to market data for %s", self.contract.symbol)

        self._running = True
        try:
            while self._running:
                self.ib.waitOnUpdate(timeout=1)
                for tick in self.ib.pendingTickers():
                    self._handle_ticker(tick)
        except KeyboardInterrupt:
            logger.info("Interrupted by user, shutting down...")
        finally:
            self._running = False
            self.ib.cancelMktData(self.contract)
            self.ib.disconnect()
            logger.info("Disconnected from IBKR")

    def _handle_ticker(self, tick) -> None:
        bid = getattr(tick, "bid", None)
        ask = getattr(tick, "ask", None)
        if bid is None or ask is None:
            return

        ts = datetime.utcnow()
        self.aggregator.add_tick(ts, bid, ask)

        for bar in self.aggregator.drain_completed():
            signal = self.strategy.on_bar(bar)
            if signal:
                logger.info(
                    "Signal %s @ %.5f (bar %s - %s)",
                    signal.action,
                    signal.price,
                    bar.start.isoformat(),
                    bar.end.isoformat(),
                )
                self._handle_signal(signal)

    def _handle_signal(self, signal: TradeSignal) -> None:
        current_side, current_size = self._current_position()

        if current_side == signal.action:
            logger.info("Already in %s position (%s). Ignoring signal.", current_side, current_size)
            return

        if current_side and current_side != signal.action:
            logger.info("Flattening existing %s position of size %s", current_side, current_size)
            self._close_position(current_side, current_size)

        logger.info("Submitting %s bracket order", signal.action)
        self._submit_bracket(signal)

    def _current_position(self) -> tuple[Optional[str], float]:
        positions = self.ib.positions()
        for pos in positions:
            if pos.contract.conId == self.contract.conId or pos.contract.symbol == self.contract.symbol:
                if pos.position > 0:
                    return "BUY", pos.position
                if pos.position < 0:
                    return "SELL", pos.position
        return None, 0.0

    def _close_position(self, side: str, size: float) -> None:
        if size == 0:
            return

        action = "SELL" if side == "BUY" else "BUY"
        order = Order(
            action=action,
            orderType="MKT",
            totalQuantity=abs(size),
            tif="DAY",
        )
        if self.ib_config.account_id:
            order.account = self.ib_config.account_id

        trade = self.ib.placeOrder(self.contract, order)
        logger.info("Flatten order submitted: %s", trade)

    def _submit_bracket(self, signal: TradeSignal) -> None:
        action = signal.action
        qty = max(1, int(self.live_config.trade_size))
        entry_price = signal.price

        entry_offset = self.pip * 0.2
        limit_price = entry_price + entry_offset if action == "BUY" else entry_price - entry_offset
        stop_loss = entry_price - (self.live_config.stop_loss_pips * self.pip) if action == "BUY" else entry_price + (self.live_config.stop_loss_pips * self.pip)
        take_profit = entry_price + (self.live_config.take_profit_pips * self.pip) if action == "BUY" else entry_price - (self.live_config.take_profit_pips * self.pip)

        limit_price = round_to_pips(limit_price, self.pip)
        stop_loss = round_to_pips(stop_loss, self.pip)
        take_profit = round_to_pips(take_profit, self.pip)

        orders = self.ib.bracketOrder(
            action=action,
            quantity=qty,
            limitPrice=limit_price,
            takeProfitPrice=take_profit,
            stopLossPrice=stop_loss,
        )

        for o in orders:
            o.tif = "GTC"
            if self.ib_config.account_id:
                o.account = self.ib_config.account_id
            self.ib.placeOrder(self.contract, o)
        logger.info(
            "Bracket submitted: action=%s qty=%s limit=%.5f tp=%.5f sl=%.5f",
            action,
            qty,
            limit_price,
            take_profit,
            stop_loss,
        )


def main() -> None:
    trader = IBInsyncTrader()
    trader.run()


if __name__ == "__main__":
    main()
