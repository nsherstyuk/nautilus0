import enum
from typing import Optional, List
import logging

from ..config.strategy_config import StrategyConfig
from ..core.market_types import Bar, Fill, RebreakSignal, TradeRecord
from ..core.pattern_detector import PatternDetector
from ..core.interfaces import ExecutionEngine


class StrategyState(enum.Enum):
    SCANNING = "SCANNING"       # Looking for confirmed rebreak signals
    IN_TRADE = "IN_TRADE"       # Position open, managing exit
    COOLDOWN = "COOLDOWN"       # Brief cooldown after a trade


class RebreakStrategy:
    """Pure state machine strategy for the confirmed rebreak pattern.

    Environment-agnostic. No data plumbing, no Pandas, no file I/O.
    Receives signals from PatternDetector, issues commands to ExecutionEngine.
    """

    def __init__(self, config: StrategyConfig,
                 logger: Optional[logging.Logger] = None):
        self.config = config
        self.state = StrategyState.SCANNING
        self.logger = logger or logging.getLogger(__name__)
        self.trades: List[TradeRecord] = []

        # Current trade tracking
        self._entry_bar_idx: int = 0
        self._current_signal: Optional[RebreakSignal] = None
        self._bars_in_trade: int = 0
        self._cooldown_bars: int = 0

    def on_bar(self, bar: Bar, bar_idx: int,
               detector: PatternDetector,
               execution: ExecutionEngine) -> None:
        """Called every bar. Pure state machine."""

        if self.state == StrategyState.COOLDOWN:
            self._cooldown_bars += 1
            if self._cooldown_bars >= self.config.imbalance_window:
                self.state = StrategyState.SCANNING
                self._cooldown_bars = 0
            return

        if self.state == StrategyState.SCANNING:
            # Let the detector process this bar and check for signals
            signals = detector.process_bar(bar)
            for signal in signals:
                if execution.has_position():
                    continue
                atr = detector.current_atr
                if atr <= 0:
                    continue

                # Compute SL/TP from ATR
                sl_dist = atr * self.config.sl_atr_multiple
                tp_dist = atr * self.config.tp_atr_multiple

                if signal.direction == "long":
                    sl_price = signal.entry_price - sl_dist
                    tp_price = signal.entry_price + tp_dist
                else:
                    sl_price = signal.entry_price + sl_dist
                    tp_price = signal.entry_price - tp_dist

                self.logger.info(
                    f"SIGNAL {signal.direction} @ {signal.entry_price:.2f} "
                    f"pivot={signal.pivot_price:.2f} "
                    f"buy_ratio={signal.buy_ratio:.3f} "
                    f"gap={signal.bars_since_first} "
                    f"ATR={atr:.2f} SL={sl_price:.2f} TP={tp_price:.2f}"
                )

                execution.enter(signal.direction, signal.entry_price,
                                sl_price, tp_price)
                self.state = StrategyState.IN_TRADE
                self._entry_bar_idx = bar_idx
                self._current_signal = signal
                self._bars_in_trade = 0
                break
            return

        if self.state == StrategyState.IN_TRADE:
            self._bars_in_trade += 1

            # Check SL/TP
            fill = execution.process_bar(bar)
            if fill:
                self._record_trade(fill, bar_idx)
                self.state = StrategyState.COOLDOWN
                self._cooldown_bars = 0
                return

            # Time stop
            if self._bars_in_trade >= self.config.max_hold_bars:
                fill = execution.close_at_market(bar, reason="TIME_STOP")
                if fill:
                    self._record_trade(fill, bar_idx)
                self.state = StrategyState.COOLDOWN
                self._cooldown_bars = 0
                return

    def on_bar_no_detect(self, bar: Bar, bar_idx: int,
                         detector: PatternDetector,
                         execution: ExecutionEngine) -> None:
        """Process bar for in-trade management only (detector already called).
        Used when the runner manages the detector call separately."""

        if self.state == StrategyState.IN_TRADE:
            self._bars_in_trade += 1

            fill = execution.process_bar(bar)
            if fill:
                self._record_trade(fill, bar_idx)
                self.state = StrategyState.COOLDOWN
                self._cooldown_bars = 0
                return

            if self._bars_in_trade >= self.config.max_hold_bars:
                fill = execution.close_at_market(bar, reason="TIME_STOP")
                if fill:
                    self._record_trade(fill, bar_idx)
                self.state = StrategyState.COOLDOWN
                self._cooldown_bars = 0

    def _record_trade(self, fill: Fill, bar_idx: int) -> None:
        sig = self._current_signal
        if sig is None:
            return
        trade = TradeRecord(
            entry_time=sig.timestamp,
            exit_time=fill.timestamp,
            direction=sig.direction,
            entry_price=sig.entry_price,
            exit_price=fill.price,
            sl_price=0.0,
            tp_price=0.0,
            pivot_price=sig.pivot_price,
            exit_reason=fill.reason,
            pnl=fill.pnl,
            hold_bars=self._bars_in_trade,
            buy_ratio_at_entry=sig.buy_ratio,
        )
        self.trades.append(trade)
        self.logger.info(
            f"TRADE CLOSED: {fill.reason} {sig.direction} "
            f"PnL={fill.pnl:+.2f} hold={self._bars_in_trade}bars"
        )
        self._current_signal = None
