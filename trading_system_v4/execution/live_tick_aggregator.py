"""
live_tick_aggregator.py — Live Tick Bar Aggregator with State Recovery

This class solves the "Tick Desync" problem for live execution.
IBKR does not natively support Tick Bars. If your system crashes at tick 999, 
you lose your count and your bars desync from the ML model's training data.

This aggregator:
1. Subscribes to live ticks via `ib.reqTickByTickData`.
2. Builds N-Tick Bars in memory.
3. Persists its state (Tick Count, OHLCV) to a local JSON file on every tick.
4. Recovers its exact state upon restart.

Usage:
  from trading_system_v4.execution.live_tick_aggregator import LiveTickAggregator
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from ib_insync import IB, Contract, TickByTickBidAsk

# ── Configuration ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "trading_system_v4" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

class LiveTickAggregator:
    def __init__(self, ib: IB, contract: Contract, ticks_per_bar: int, symbol: str):
        self.ib = ib
        self.contract = contract
        self.ticks_per_bar = ticks_per_bar
        self.symbol = symbol
        
        self.state_file = STATE_DIR / f"{symbol.lower()}_tick_state.json"
        
        # Current Bar State
        self.tick_count = 0
        self.open = 0.0
        self.high = 0.0
        self.low = float('inf')
        self.close = 0.0
        self.ask_vol_sum = 0.0
        self.bid_vol_sum = 0.0
        self.spread_sum = 0.0
        self.max_spread = 0.0
        self.start_time = None
        
        # Callbacks
        self.on_bar_complete = None
        
        # Load previous state if it exists
        self._load_state()
        
        # Subscribe to live ticks
        self.ib.reqTickByTickData(self.contract, 'BidAsk')
        self.ib.pendingTickersEvent += self._on_pending_tickers

    def _load_state(self):
        """Recovers the partial bar state from disk after a crash."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    
                # Only recover if the state is from today (don't carry over weekend gaps)
                last_update = datetime.fromisoformat(state.get("last_update", "2000-01-01T00:00:00+00:00"))
                now = datetime.now(timezone.utc)
                
                if (now - last_update).total_seconds() < 86400: # Less than 24 hours old
                    self.tick_count = state.get("tick_count", 0)
                    self.open = state.get("open", 0.0)
                    self.high = state.get("high", 0.0)
                    self.low = state.get("low", float('inf'))
                    self.close = state.get("close", 0.0)
                    self.ask_vol_sum = state.get("ask_vol_sum", 0.0)
                    self.bid_vol_sum = state.get("bid_vol_sum", 0.0)
                    self.spread_sum = state.get("spread_sum", 0.0)
                    self.max_spread = state.get("max_spread", 0.0)
                    
                    start_time_str = state.get("start_time")
                    if start_time_str:
                        self.start_time = datetime.fromisoformat(start_time_str)
                        
                    print(f"[TickAggregator] Recovered state for {self.symbol}: {self.tick_count}/{self.ticks_per_bar} ticks.")
                else:
                    print(f"[TickAggregator] State file for {self.symbol} is too old. Starting fresh.")
                    
            except Exception as e:
                print(f"[TickAggregator] Failed to load state: {e}. Starting fresh.")

    def _save_state(self, current_time: datetime):
        """Persists the partial bar state to disk."""
        state = {
            "tick_count": self.tick_count,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "ask_vol_sum": self.ask_vol_sum,
            "bid_vol_sum": self.bid_vol_sum,
            "spread_sum": self.spread_sum,
            "max_spread": self.max_spread,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "last_update": current_time.isoformat()
        }
        
        # Write to a temporary file first, then rename to ensure atomic writes
        temp_file = self.state_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(state, f)
        os.replace(temp_file, self.state_file)

    def _on_pending_tickers(self, tickers):
        """Processes incoming live ticks from IBKR."""
        for ticker in tickers:
            if ticker.contract == self.contract and ticker.tickByTicks:
                for tick in ticker.tickByTicks:
                    if isinstance(tick, TickByTickBidAsk):
                        self._process_tick(tick)

    def _process_tick(self, tick: TickByTickBidAsk):
        """Updates the current bar state with a new tick."""
        mid = (tick.askPrice + tick.bidPrice) / 2.0
        spread = tick.askPrice - tick.bidPrice
        
        # Initialize new bar
        if self.tick_count == 0:
            self.open = mid
            self.high = mid
            self.low = mid
            self.start_time = tick.time
            self.ask_vol_sum = 0.0
            self.bid_vol_sum = 0.0
            self.spread_sum = 0.0
            self.max_spread = 0.0
            
        # Update current bar
        self.high = max(self.high, mid)
        self.low = min(self.low, mid)
        self.close = mid
        
        self.ask_vol_sum += tick.askSize
        self.bid_vol_sum += tick.bidSize
        self.spread_sum += spread
        self.max_spread = max(self.max_spread, spread)
        
        self.tick_count += 1
        
        # Save state every 10 ticks to balance I/O performance vs crash safety
        if self.tick_count % 10 == 0:
            self._save_state(tick.time)
            
        # Bar Complete!
        if self.tick_count >= self.ticks_per_bar:
            self._emit_bar(tick.time)

    def _emit_bar(self, end_time: datetime):
        """Packages the completed bar and sends it to the strategy."""
        duration_sec = (end_time - self.start_time).total_seconds()
        
        total_volume = self.ask_vol_sum + self.bid_vol_sum
        buy_ratio = self.ask_vol_sum / (total_volume + 1e-6)
        
        bar_data = {
            "timestamp": end_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "avg_spread": self.spread_sum / self.ticks_per_bar,
            "max_spread": self.max_spread,
            "vol_imbalance": self.ask_vol_sum - self.bid_vol_sum,
            "buy_volume": self.ask_vol_sum,
            "sell_volume": self.bid_vol_sum,
            "total_volume": total_volume,
            "buy_ratio": buy_ratio,
            "tick_velocity": self.ticks_per_bar / (duration_sec + 1e-6)
        }
        
        # Reset state for the next bar
        self.tick_count = 0
        self._save_state(end_time)
        
        # Trigger callback
        if self.on_bar_complete:
            self.on_bar_complete(bar_data)
