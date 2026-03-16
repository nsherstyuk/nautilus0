"""
V7 Live Trading Engine

Implements the confirmed rebreak strategy for live trading using:
- Rolling bar buffer (circular buffer of recent 1-min bars)
- Real-time pivot detection with confirm_bars delay
- Pattern state machine (first break -> pullback -> rebreak)
- IBKR order execution via ib_insync

Architecture:
  1. Tick data -> 1-min bar aggregator
  2. Rolling buffer maintains last N bars
  3. Pivot tracker computes pivots with confirm_bars delay
  4. Pattern detector watches for confirmed rebreak setups
  5. Order manager submits bracket orders (entry + SL)
"""
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional, List, Deque
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config.strategy_config import StrategyConfig
from .live_config import LiveConfig


@dataclass
class Bar:
    """1-minute OHLCV bar with volume split."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    buy_volume: float
    sell_volume: float
    tick_count: int


@dataclass
class Trade:
    """Active trade record."""
    entry_time: datetime
    direction: str
    entry_price: float
    quantity: float
    sl_price: float
    pivot_price: float
    entry_bar_idx: int
    buy_ratio: float
    gap: int


class RollingBuffer:
    """Circular buffer for bars with efficient pivot computation."""
    
    def __init__(self, maxlen: int):
        self.maxlen = maxlen
        self.bars: Deque[Bar] = deque(maxlen=maxlen)
        self.pivot_high: Deque[float] = deque(maxlen=maxlen)
        self.pivot_low: Deque[float] = deque(maxlen=maxlen)
        
    def append(self, bar: Bar):
        """Add new bar and update pivot levels."""
        self.bars.append(bar)
        
    def get_arrays(self):
        """Extract numpy arrays for computation."""
        if not self.bars:
            return None
        
        n = len(self.bars)
        closes = np.array([b.close for b in self.bars])
        highs = np.array([b.high for b in self.bars])
        lows = np.array([b.low for b in self.bars])
        buy_vols = np.array([b.buy_volume for b in self.bars])
        sell_vols = np.array([b.sell_volume for b in self.bars])
        tick_counts = np.array([b.tick_count for b in self.bars])
        timestamps = np.array([b.timestamp for b in self.bars])
        
        return {
            'n': n,
            'closes': closes,
            'highs': highs,
            'lows': lows,
            'buy_vols': buy_vols,
            'sell_vols': sell_vols,
            'tick_counts': tick_counts,
            'timestamps': timestamps,
        }
    
    def compute_pivots(self, window: int, confirm_bars: int):
        """Compute shifted-centered pivots on current buffer."""
        data = self.get_arrays()
        if data is None or data['n'] < window * 2 + 1:
            return np.array([]), np.array([])
        
        highs = data['highs']
        lows = data['lows']
        n = data['n']
        
        full_win = 2 * window + 1
        roll_max = pd.Series(highs).rolling(full_win, center=True).max().values
        roll_min = pd.Series(lows).rolling(full_win, center=True).min().values
        
        is_ph = (highs == roll_max) & ~np.isnan(roll_max)
        is_pl = (lows == roll_min) & ~np.isnan(roll_min)
        
        pivot_high = np.full(n, np.nan)
        pivot_low = np.full(n, np.nan)
        last_ph = np.nan
        last_pl = np.nan
        
        for i in range(n):
            lookback = i - confirm_bars
            if lookback >= 0:
                if is_ph[lookback]:
                    last_ph = highs[lookback]
                if is_pl[lookback]:
                    last_pl = lows[lookback]
            pivot_high[i] = last_ph
            pivot_low[i] = last_pl
        
        return pivot_high, pivot_low
    
    def compute_atr(self, period: int = 60):
        """Compute ATR on current buffer."""
        data = self.get_arrays()
        if data is None or data['n'] < 2:
            return 0.5
        
        highs = data['highs']
        lows = data['lows']
        closes = data['closes']
        n = data['n']
        
        tr_buf = []
        prev_c = closes[0]
        for i in range(n):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - prev_c),
                     abs(lows[i] - prev_c))
            tr_buf.append(tr)
            if len(tr_buf) > period:
                tr_buf.pop(0)
            prev_c = closes[i]
        
        return np.mean(tr_buf) if tr_buf else 0.5


class LiveEngine:
    """Live trading engine for V7 confirmed rebreak strategy.

    Key design: pattern detection processes bar at index n-1-imb_w
    (not the latest bar). This provides the imb_w-bar lookahead window
    needed for buy_ratio computation, exactly matching backtest behavior.
    Entry happens at the current bar (index n-1), imb_w bars after the
    breakout/rebreak was detected.
    """
    
    def __init__(self, live_config: LiveConfig, strategy_config: StrategyConfig,
                 logger: Optional[logging.Logger] = None):
        self.live_cfg = live_config
        self.strat_cfg = strategy_config
        self.log = logger or logging.getLogger(__name__)
        
        self.buffer = RollingBuffer(maxlen=live_config.buffer_size)
        self.current_trade: Optional[Trade] = None
        
        # Pattern state per direction
        self.h_level = np.nan
        self.h_broke = False
        self.h_pb = False
        self.h_idx = -1
        self.h_div = False
        
        self.l_level = np.nan
        self.l_broke = False
        self.l_pb = False
        self.l_idx = -1
        self.l_div = False
        
        self.cooldown = 0
        self.bar_count = 0
        self._last_processed_bar_count = -1
        
        # Safety counters
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.last_reset_date = datetime.now(timezone.utc).date()
        
    def reset_daily_counters(self):
        """Reset daily trade/PnL counters at midnight UTC."""
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset_date:
            self.log.info(f"Daily reset: {self.daily_trades} trades, "
                         f"${self.daily_pnl:+.2f} PnL")
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self.last_reset_date = today
    
    def on_bar(self, bar: Bar) -> Optional[dict]:
        """Process new 1-min bar. Returns signal dict if entry triggered.

        Pattern detection runs on bar [n-1-imb_w] so the imb_w lookahead
        bars are already in the buffer. This matches the backtest exactly:
        breakout detected at bar i, buy_ratio from bars [i+1..i+imb_w],
        entry at bar i+imb_w (which is the current bar n-1).
        """
        self.reset_daily_counters()
        self.buffer.append(bar)
        self.bar_count += 1
        
        imb_w = self.strat_cfg.imbalance_window
        n = len(self.buffer.bars)
        
        # Need enough bars for pivot computation + imb_w lookahead
        min_bars = 2 * self.strat_cfg.pivot_window + self.strat_cfg.confirm_bars + imb_w + 10
        if n < min_bars:
            return None
        
        # Cooldown (decrement per bar)
        if self.cooldown > 0:
            self.cooldown -= 1
            return None
        
        # In trade - check exit using latest bar
        if self.current_trade is not None:
            return self._check_exit(bar)
        
        # Check safety limits
        if self.daily_trades >= self.live_cfg.max_daily_trades:
            return None
        if self.daily_pnl <= -self.live_cfg.max_daily_loss:
            self.log.warning(f"Daily loss limit hit: ${self.daily_pnl:.2f}")
            return None
        
        # Compute pivots over full buffer
        pivot_high, pivot_low = self.buffer.compute_pivots(
            self.strat_cfg.pivot_window,
            self.strat_cfg.confirm_bars
        )
        
        if len(pivot_high) == 0:
            return None
        
        data = self.buffer.get_arrays()
        
        # Process bar at delayed index (imb_w bars behind current)
        # This gives us the lookahead window for buy_ratio
        i = n - 1 - imb_w
        if i < 0:
            return None
        # Use monotonic bar_count to avoid stalling when deque is full
        processing_bar = self.bar_count - imb_w
        if processing_bar <= self._last_processed_bar_count:
            return None
        self._last_processed_bar_count = processing_bar
        
        # Update pivot levels at the processing point
        if not np.isnan(pivot_high[i]) and pivot_high[i] != self.h_level:
            self.h_level = pivot_high[i]
            self.h_broke = False
            self.h_pb = False
            self.h_idx = -1
        
        if not np.isnan(pivot_low[i]) and pivot_low[i] != self.l_level:
            self.l_level = pivot_low[i]
            self.l_broke = False
            self.l_pb = False
            self.l_idx = -1
        
        # Pattern detection at delayed bar i, with lookahead to i+imb_w
        signal = self._detect_long_pattern(i, data, pivot_high)
        if signal is None:
            signal = self._detect_short_pattern(i, data, pivot_low)
        
        return signal
    
    def _detect_long_pattern(self, i: int, data: dict, pivot_high: np.ndarray):
        """Detect long (pivot high rebreak) pattern.
        
        Bar i is imb_w bars behind current. Bars [i+1..i+imb_w] are
        available for buy_ratio. Entry bar is i+imb_w (current bar).
        """
        if np.isnan(self.h_level):
            return None
        
        closes = data['closes']
        buy_vols = data['buy_vols']
        sell_vols = data['sell_vols']
        tick_counts = data['tick_counts']
        n = data['n']
        
        imb_w = self.strat_cfg.imbalance_window
        div_thr = self.strat_cfg.divergence_threshold
        max_pb = self.strat_cfg.max_pullback_bars
        min_pb = self.strat_cfg.min_pullback_bars
        
        if not self.h_broke:
            if closes[i] > self.h_level:
                br = self._get_buy_ratio(buy_vols, sell_vols, tick_counts,
                                         i + 1, i + imb_w + 1, n)
                if not np.isnan(br):
                    self.h_broke = True
                    self.h_idx = i
                    self.h_div = (br < div_thr)
                    if not self.h_div:
                        self.h_broke = False
        elif not self.h_pb:
            if closes[i] <= self.h_level:
                self.h_pb = True
        else:
            gap = i - self.h_idx
            if gap > max_pb:
                self.h_broke = False
                self.h_pb = False
            elif gap >= min_pb and closes[i] > self.h_level:
                br = self._get_buy_ratio(buy_vols, sell_vols, tick_counts,
                                         i + 1, i + imb_w + 1, n)
                if not np.isnan(br):
                    if self.h_div and br >= div_thr:
                        eidx = i + imb_w
                        if eidx < n:
                            signal = {
                                'direction': 'long',
                                'entry_idx': eidx,
                                'entry_price': closes[eidx],
                                'pivot': self.h_level,
                                'buy_ratio': br,
                                'gap': gap,
                            }
                            self.h_broke = False
                            self.h_pb = False
                            return signal
                    self.h_broke = False
                    self.h_pb = False
        return None
    
    def _detect_short_pattern(self, i: int, data: dict, pivot_low: np.ndarray):
        """Detect short (pivot low rebreak) pattern.
        
        Bar i is imb_w bars behind current. Bars [i+1..i+imb_w] are
        available for buy_ratio. Entry bar is i+imb_w (current bar).
        """
        if np.isnan(self.l_level):
            return None
        
        closes = data['closes']
        buy_vols = data['buy_vols']
        sell_vols = data['sell_vols']
        tick_counts = data['tick_counts']
        n = data['n']
        
        imb_w = self.strat_cfg.imbalance_window
        div_thr = self.strat_cfg.divergence_threshold
        max_pb = self.strat_cfg.max_pullback_bars
        min_pb = self.strat_cfg.min_pullback_bars
        
        if not self.l_broke:
            if closes[i] < self.l_level:
                br = self._get_buy_ratio(buy_vols, sell_vols, tick_counts,
                                         i + 1, i + imb_w + 1, n)
                if not np.isnan(br):
                    self.l_broke = True
                    self.l_idx = i
                    self.l_div = (br > div_thr)
                    if not self.l_div:
                        self.l_broke = False
        elif not self.l_pb:
            if closes[i] >= self.l_level:
                self.l_pb = True
        else:
            gap = i - self.l_idx
            if gap > max_pb:
                self.l_broke = False
                self.l_pb = False
            elif gap >= min_pb and closes[i] < self.l_level:
                br = self._get_buy_ratio(buy_vols, sell_vols, tick_counts,
                                         i + 1, i + imb_w + 1, n)
                if not np.isnan(br):
                    if self.l_div and br <= div_thr:
                        eidx = i + imb_w
                        if eidx < n:
                            signal = {
                                'direction': 'short',
                                'entry_idx': eidx,
                                'entry_price': closes[eidx],
                                'pivot': self.l_level,
                                'buy_ratio': br,
                                'gap': gap,
                            }
                            self.l_broke = False
                            self.l_pb = False
                            return signal
                    self.l_broke = False
                    self.l_pb = False
        return None
    
    def _get_buy_ratio(self, buy_vols, sell_vols, tick_counts, start: int, end: int, n: int) -> float:
        """Buy ratio with min_bar_ticks quality filter."""
        if end > n:
            return float('nan')
        ticks = tick_counts[start:end]
        min_t = self.strat_cfg.min_bar_ticks
        if min_t > 0 and np.any(ticks < min_t):
            return float('nan')
        bv = buy_vols[start:end].sum()
        sv = sell_vols[start:end].sum()
        total = bv + sv
        if total == 0:
            return float('nan')
        return bv / total
    
    def _check_exit(self, bar: Bar) -> Optional[dict]:
        """Check if current trade should exit."""
        if self.current_trade is None:
            return None
        
        trade = self.current_trade
        bars_held = self.bar_count - trade.entry_bar_idx
        
        # Check catastrophe SL
        if trade.direction == 'long' and bar.low <= trade.sl_price:
            return {'action': 'exit', 'reason': 'SL', 'price': trade.sl_price}
        elif trade.direction == 'short' and bar.high >= trade.sl_price:
            return {'action': 'exit', 'reason': 'SL', 'price': trade.sl_price}
        
        # Check time stop
        if bars_held >= self.strat_cfg.max_hold_bars:
            return {'action': 'exit', 'reason': 'TIME', 'price': bar.close}
        
        return None
    
    def enter_trade(self, signal: dict, bar: Bar):
        """Enter trade based on signal."""
        direction = signal['direction']
        entry_price = signal['entry_price']
        
        # Adjust for spread
        if direction == 'long':
            entry_price += self.live_cfg.spread_cost / 2
        else:
            entry_price -= self.live_cfg.spread_cost / 2
        
        # Compute SL
        atr = self.buffer.compute_atr()
        sl_mult = self.strat_cfg.sl_atr_multiple
        if direction == 'long':
            sl_price = entry_price - sl_mult * atr
        else:
            sl_price = entry_price + sl_mult * atr
        
        self.current_trade = Trade(
            entry_time=bar.timestamp,
            direction=direction,
            entry_price=entry_price,
            quantity=self.live_cfg.quantity,
            sl_price=sl_price,
            pivot_price=signal['pivot'],
            entry_bar_idx=self.bar_count,
            buy_ratio=signal['buy_ratio'],
            gap=signal['gap'],
        )
        
        self.cooldown = self.strat_cfg.imbalance_window
        self.daily_trades += 1
        
        self.log.info(f"ENTER {direction.upper()} @ {entry_price:.2f} "
                     f"SL={sl_price:.2f} pivot={signal['pivot']:.2f}")
        
        return self.current_trade
    
    def exit_trade(self, exit_info: dict) -> dict:
        """Exit current trade."""
        if self.current_trade is None:
            return {}
        
        trade = self.current_trade
        exit_price = exit_info['price']
        
        # Adjust for spread
        if trade.direction == 'long':
            exit_price -= self.live_cfg.spread_cost / 2
        else:
            exit_price += self.live_cfg.spread_cost / 2
        
        # Compute PnL
        if trade.direction == 'long':
            pnl = (exit_price - trade.entry_price) * trade.quantity
        else:
            pnl = (trade.entry_price - exit_price) * trade.quantity
        
        self.daily_pnl += pnl
        
        result = {
            'entry_time': trade.entry_time,
            'exit_time': datetime.now(timezone.utc),
            'direction': trade.direction,
            'entry_price': trade.entry_price,
            'exit_price': exit_price,
            'sl_price': trade.sl_price,
            'pivot_price': trade.pivot_price,
            'quantity': trade.quantity,
            'pnl': pnl,
            'exit_reason': exit_info['reason'],
            'buy_ratio': trade.buy_ratio,
            'gap': trade.gap,
        }
        
        self.log.info(f"EXIT {trade.direction.upper()} @ {exit_price:.2f} "
                     f"PnL=${pnl:+.2f} reason={exit_info['reason']}")
        
        self.current_trade = None
        self.cooldown = self.strat_cfg.imbalance_window
        
        return result
