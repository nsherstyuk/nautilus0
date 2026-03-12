"""
V8 Live Trading Engine -- Uses the SAME deep modules as backtest.

Architecture:
    1. RollingBuffer maintains last N bars
    2. On each new bar:
       a. Compute centered pivots over buffer (pivot_computer.rolling_centered)
       b. Process bar at DELAY position (buffer_len - 1 - imb_w) so that
          buy_ratio lookahead bars are available in the buffer
       c. PatternDetector.process_bar() -- SAME code as backtest
       d. If signal fires, return it to run_live.py for order submission

Key design: PatternDetector is identical in backtest and live.
The only difference is WHERE pivot levels and buy_ratio come from:
    - Backtest: pre-computed arrays over full dataset
    - Live: rolling buffer, recomputed each bar
"""
import math
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict

import numpy as np
import pandas as pd

from ..config.strategy_config import StrategyConfig
from ..core.pattern_detector import PatternDetector
from ..core.pivot_computer import rolling_centered
from ..live.live_config import LiveConfig


@dataclass
class LiveBar:
    """Mutable bar for aggregation during live trading."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    tick_count: int = 0
    buy_volume: float = 0.0
    sell_volume: float = 0.0


class RollingBuffer:
    """Rolling buffer of bars for live pivot and buy_ratio computation."""

    def __init__(self, max_size: int = 500):
        self.max_size = max_size
        self.timestamps: deque = deque(maxlen=max_size)
        self.opens: deque = deque(maxlen=max_size)
        self.highs: deque = deque(maxlen=max_size)
        self.lows: deque = deque(maxlen=max_size)
        self.closes: deque = deque(maxlen=max_size)
        self.tick_counts: deque = deque(maxlen=max_size)
        self.buy_volumes: deque = deque(maxlen=max_size)
        self.sell_volumes: deque = deque(maxlen=max_size)

    def add_bar(self, bar: LiveBar) -> None:
        self.timestamps.append(bar.timestamp)
        self.opens.append(bar.open)
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.tick_counts.append(bar.tick_count)
        self.buy_volumes.append(bar.buy_volume)
        self.sell_volumes.append(bar.sell_volume)

    def __len__(self) -> int:
        return len(self.closes)

    def get_arrays(self):
        """Return numpy arrays for pivot/buy_ratio computation."""
        return (
            np.array(self.highs, dtype=float),
            np.array(self.lows, dtype=float),
            np.array(self.closes, dtype=float),
            np.array(self.buy_volumes, dtype=float),
            np.array(self.sell_volumes, dtype=float),
            np.array(self.tick_counts, dtype=int),
        )


class LiveEngine:
    """Live trading engine using V8 deep modules.

    Uses the SAME PatternDetector as backtest.
    Processes bars at a delay of imb_w so that buy_ratio lookahead
    bars are available in the buffer.
    """

    def __init__(self, config: LiveConfig,
                 logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        # Rolling buffer
        self.buffer = RollingBuffer(max_size=config.buffer_size)

        # Deep module: pattern detection (SAME as backtest)
        self.detector = PatternDetector(
            imbalance_window=config.imbalance_window,
            divergence_threshold=config.divergence_threshold,
            max_pullback_bars=config.max_pullback_bars,
            min_pullback_bars=config.min_pullback_bars,
            atr_period=config.atr_period,
        )

        # Trade state
        self.in_trade: bool = False
        self.trade_direction: str = ""
        self.trade_entry_price: float = 0.0
        self.trade_entry_bar: int = 0
        self.trade_sl_price: float = 0.0
        self.trade_tp_price: float = 0.0
        self.trade_pivot: float = 0.0
        self.trade_br: float = 0.0
        self.trade_gap: int = 0

        # Cooldown
        self._cooldown: int = 0

        # Monotonic bar counter (never resets even when deque wraps)
        self._bar_count: int = 0
        self._last_processed: int = -1

        # Safety
        self.daily_trades: int = 0
        self.daily_pnl: float = 0.0

    def add_bar(self, bar: LiveBar) -> None:
        """Add a new bar to the rolling buffer."""
        self.buffer.add_bar(bar)
        self._bar_count += 1

    def on_bar(self) -> Optional[Dict]:
        """Process the latest bar. Returns a signal dict or None.

        Processes bar at delay position so buy_ratio lookahead is available.
        Returns:
            None -- no action
            {'action': 'enter', 'direction': ..., 'entry_price': ..., ...}
            {'action': 'exit', 'reason': ..., 'exit_price': ..., ...}
        """
        buf_len = len(self.buffer)
        imb_w = self.config.imbalance_window
        pw = self.config.pivot_window
        min_bars = 2 * pw + 1 + imb_w

        if buf_len < min_bars:
            return None

        # Determine which bar to process (with imb_w delay)
        process_idx = buf_len - 1 - imb_w
        if process_idx < 0:
            return None

        # Avoid processing same bar twice
        logical_idx = self._bar_count - 1 - imb_w
        if logical_idx <= self._last_processed:
            return None
        self._last_processed = logical_idx

        # Get arrays from buffer
        highs, lows, closes, buy_vols, sell_vols, tick_counts = \
            self.buffer.get_arrays()
        n = len(closes)

        # Compute pivots over buffer
        pivot_high, pivot_low = rolling_centered(
            highs, lows,
            window=pw,
            shift=self.config.confirm_bars,
        )

        # Update ATR for the processed bar
        self.detector.update_atr(
            float(highs[process_idx]),
            float(lows[process_idx]),
            float(closes[process_idx]),
        )

        # Cooldown
        if self._cooldown > 0:
            self._cooldown -= 1
            return None

        # Check exit conditions if in trade
        if self.in_trade:
            return self._check_exit(process_idx, highs, lows, closes)

        # Buy ratio callback (closure over buffer arrays)
        min_ticks = self.config.min_bar_ticks

        def get_buy_ratio(start: int, end: int) -> float:
            # Remap: PatternDetector thinks in buffer-relative indices
            if end > n or start >= end:
                return float("nan")
            ticks = tick_counts[start:end]
            if min_ticks > 0 and np.any(ticks < min_ticks):
                return float("nan")
            bv = buy_vols[start:end].sum()
            sv = sell_vols[start:end].sum()
            total = bv + sv
            if total == 0:
                return float("nan")
            return bv / total

        # Pattern detection (SAME deep module as backtest)
        signal = self.detector.process_bar(
            float(closes[process_idx]),
            process_idx,
            float(pivot_high[process_idx]),
            float(pivot_low[process_idx]),
            get_buy_ratio,
        )

        if signal is not None:
            direction, gap, br = signal
            eidx = process_idx + imb_w
            if eidx < n:
                ep = float(closes[eidx])
                spread = self.config.spread_cost
                if direction == "long":
                    entry_price = ep + spread / 2
                else:
                    entry_price = ep - spread / 2

                atr = self.detector.current_atr
                if atr <= 0:
                    atr = 0.5

                sl_mult = self.config.sl_atr_multiple
                if direction == "long":
                    sl_price = entry_price - sl_mult * atr
                    tp_price = entry_price + self.config.tp_atr_multiple * atr
                else:
                    sl_price = entry_price + sl_mult * atr
                    tp_price = entry_price - self.config.tp_atr_multiple * atr

                pivot_price = float(pivot_high[process_idx]) if direction == "long" \
                    else float(pivot_low[process_idx])

                self.in_trade = True
                self.trade_direction = direction
                self.trade_entry_price = entry_price
                self.trade_entry_bar = self._bar_count
                self.trade_sl_price = sl_price
                self.trade_tp_price = tp_price
                self.trade_pivot = pivot_price
                self.trade_br = br
                self.trade_gap = gap

                self.logger.info(
                    f"SIGNAL {direction} @ {ep:.2f} (adj {entry_price:.2f}) "
                    f"pivot={pivot_price:.2f} br={br:.3f} gap={gap} "
                    f"ATR={atr:.2f} SL={sl_price:.2f}"
                )

                return {
                    'action': 'enter',
                    'direction': direction,
                    'entry_price': ep,
                    'sl_price': sl_price,
                    'tp_price': tp_price,
                    'pivot_price': pivot_price,
                    'buy_ratio': br,
                    'gap': gap,
                    'atr': atr,
                }

        return None

    def _check_exit(self, process_idx: int,
                    highs: np.ndarray, lows: np.ndarray,
                    closes: np.ndarray) -> Optional[Dict]:
        """Check SL/TP/time-stop for current trade."""
        bars_held = self._bar_count - self.trade_entry_bar
        spread = self.config.spread_cost

        # Catastrophe SL
        sl_hit = False
        if self.trade_sl_price != 0.0:
            if self.trade_direction == "long" and lows[process_idx] <= self.trade_sl_price:
                sl_hit = True
            elif self.trade_direction == "short" and highs[process_idx] >= self.trade_sl_price:
                sl_hit = True

        if sl_hit:
            exit_price = self.trade_sl_price
            if self.trade_direction == "long":
                pnl = (exit_price - spread / 2) - self.trade_entry_price
            else:
                pnl = self.trade_entry_price - (exit_price + spread / 2)
            return self._close_trade("CATASTROPHE_SL", exit_price, pnl, bars_held)

        # Time stop
        if bars_held >= self.config.max_hold_bars:
            exit_price = float(closes[process_idx])
            if self.trade_direction == "long":
                pnl = (exit_price - spread / 2) - self.trade_entry_price
            else:
                pnl = self.trade_entry_price - (exit_price + spread / 2)
            return self._close_trade("TIME_STOP", exit_price, pnl, bars_held)

        return None

    def _close_trade(self, reason: str, exit_price: float,
                     pnl: float, bars_held: int) -> Dict:
        """Close current trade and return exit signal."""
        self.logger.info(
            f"EXIT {reason} {self.trade_direction} @ {exit_price:.2f} "
            f"PnL={pnl:+.2f} hold={bars_held}bars"
        )
        result = {
            'action': 'exit',
            'reason': reason,
            'direction': self.trade_direction,
            'exit_price': exit_price,
            'pnl': pnl,
            'hold_bars': bars_held,
            'entry_price': self.trade_entry_price,
            'pivot_price': self.trade_pivot,
            'buy_ratio': self.trade_br,
            'gap': self.trade_gap,
        }
        self.in_trade = False
        self._cooldown = self.config.imbalance_window
        self.daily_trades += 1
        self.daily_pnl += pnl
        return result

    def reset_daily(self) -> None:
        """Reset daily counters at market open."""
        self.daily_trades = 0
        self.daily_pnl = 0.0

    def safety_check(self) -> Optional[str]:
        """Check daily safety limits. Returns reason string if breached."""
        if self.daily_trades >= self.config.max_daily_trades:
            return f"MAX_DAILY_TRADES ({self.config.max_daily_trades})"
        if self.daily_pnl <= -self.config.max_daily_loss:
            return f"MAX_DAILY_LOSS (${self.config.max_daily_loss})"
        return None
