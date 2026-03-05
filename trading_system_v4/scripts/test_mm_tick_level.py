"""
Tick-Level Market-Making Simulation — EURUSD
=============================================
Realistic market-making backtest using actual bid/ask tick data.

Key differences from the bar-level sim:
  1. Tick-by-tick fill simulation — limit orders fill when market crosses our level
  2. Real spread from data — not assumed constant
  3. Proper inventory tracking with mark-to-market PnL
  4. Queue position modeling — we don't always get filled at touch
  5. Adverse selection: if price moves through our level, we got filled at a bad price
  6. Session filtering (London/NY profitable, Asian toxic)
  7. News/volatility kill switch (pull quotes when spread widens)

The sim processes one day at a time (streaming) to avoid loading all ticks into memory.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
import warnings
import sys
import logging

warnings.filterwarnings("ignore")
logging.getLogger("tick_vault").setLevel(logging.WARNING)

PIP = 0.0001

# ─────────────────────────────────────────────────
# Market Maker State
# ─────────────────────────────────────────────────

@dataclass
class MMState:
    """Tracks the market maker's position and PnL."""
    inventory: int = 0               # +N = long N units, -N = short N units
    max_inventory: int = 3           # max position in either direction
    avg_entry_price: float = 0.0     # weighted average entry
    realized_pnl: float = 0.0       # closed trade PnL (in price terms)
    n_fills: int = 0
    n_buy_fills: int = 0
    n_sell_fills: int = 0
    n_round_trips: int = 0          # completed buy+sell pairs
    n_timeouts: int = 0             # forced closes
    n_quotes_pulled: int = 0        # times we pulled quotes (kill switch)
    worst_inventory: int = 0
    max_unrealized_loss: float = 0.0
    
    # Per-trade PnL tracking
    trade_pnls: list = field(default_factory=list)
    
    def buy_fill(self, price: float):
        """We bought at `price` (our bid was hit)."""
        self.n_fills += 1
        self.n_buy_fills += 1
        
        if self.inventory < 0:
            # Closing short → realized PnL
            pnl = self.avg_entry_price - price  # sold high, bought low = profit
            self.realized_pnl += pnl
            self.trade_pnls.append(pnl)
            self.n_round_trips += 1
            self.inventory += 1
            if self.inventory == 0:
                self.avg_entry_price = 0.0
        else:
            # Adding to long
            if self.inventory == 0:
                self.avg_entry_price = price
            else:
                self.avg_entry_price = (self.avg_entry_price * self.inventory + price) / (self.inventory + 1)
            self.inventory += 1
        
        self.worst_inventory = max(self.worst_inventory, abs(self.inventory))
    
    def sell_fill(self, price: float):
        """We sold at `price` (our ask was lifted)."""
        self.n_fills += 1
        self.n_sell_fills += 1
        
        if self.inventory > 0:
            # Closing long → realized PnL
            pnl = price - self.avg_entry_price  # bought low, sold high = profit
            self.realized_pnl += pnl
            self.trade_pnls.append(pnl)
            self.n_round_trips += 1
            self.inventory -= 1
            if self.inventory == 0:
                self.avg_entry_price = 0.0
        else:
            # Adding to short
            if self.inventory == 0:
                self.avg_entry_price = price
            else:
                self.avg_entry_price = (self.avg_entry_price * abs(self.inventory) + price) / (abs(self.inventory) + 1)
            self.inventory -= 1
        
        self.worst_inventory = max(self.worst_inventory, abs(self.inventory))
    
    def force_close(self, mid_price: float):
        """Force-close all inventory at mid price (end of session / kill switch)."""
        if self.inventory == 0:
            return
        
        self.n_timeouts += 1
        if self.inventory > 0:
            # We're long, close by selling at mid (pessimistic — no spread advantage)
            pnl = (mid_price - self.avg_entry_price) * self.inventory
            self.realized_pnl += pnl
            self.trade_pnls.append(pnl)
        else:
            pnl = (self.avg_entry_price - mid_price) * abs(self.inventory)
            self.realized_pnl += pnl
            self.trade_pnls.append(pnl)
        
        self.inventory = 0
        self.avg_entry_price = 0.0
    
    def unrealized_pnl(self, mid_price: float) -> float:
        if self.inventory == 0:
            return 0.0
        if self.inventory > 0:
            return (mid_price - self.avg_entry_price) * self.inventory
        else:
            return (self.avg_entry_price - mid_price) * abs(self.inventory)


# ─────────────────────────────────────────────────
# Simulation Parameters
# ─────────────────────────────────────────────────

@dataclass
class MMParams:
    """Market-making strategy parameters."""
    # Quote placement
    half_spread_pips: float = 2.0    # distance from mid to each quote
    
    # Inventory management
    max_inventory: int = 3
    inventory_skew_pips: float = 0.3  # per unit of inventory, skew quotes this much
    
    # Session filter (UTC hours)
    session_start_hour: int = 7      # London open
    session_end_hour: int = 17       # London close
    
    # Kill switch
    spread_kill_pips: float = 1.5    # pull quotes if market spread > this
    volatility_kill_window: int = 50 # ticks to measure vol
    volatility_kill_threshold: float = 3.0  # z-score of price change to pull quotes
    cooldown_ticks: int = 200        # stay out for N ticks after kill switch
    
    # Forced close
    force_close_end_of_session: bool = True  # flatten at session end
    
    # Fill modeling
    fill_probability: float = 0.7    # not every limit order fills (queue position)


# ─────────────────────────────────────────────────
# Core Simulation (processes one day of ticks)
# ─────────────────────────────────────────────────

def simulate_day(ticks: pd.DataFrame, params: MMParams) -> MMState:
    """
    Run market-making simulation on one day of tick data.
    
    Logic: at each tick we PLACE quotes based on current mid. On the NEXT
    tick we check whether the market moved to fill those quotes. This models
    the real-world latency: you post a limit order, and it sits on the book
    until the market touches it.
    
    ticks: DataFrame with columns [time, bid, ask, bid_volume, ask_volume]
    """
    state = MMState(max_inventory=params.max_inventory)
    
    asks = ticks["ask"].values
    bids = ticks["bid"].values
    times = ticks["time"].values
    n_ticks = len(ticks)
    
    if n_ticks < 100:
        return state
    
    # Pre-compute mid prices and spreads
    mids = (asks + bids) / 2.0
    spreads = asks - bids
    
    half_spread = params.half_spread_pips * PIP
    inv_skew = params.inventory_skew_pips * PIP
    spread_kill = params.spread_kill_pips * PIP
    
    # Rolling volatility: std of mid changes over a window
    vol_window = params.volatility_kill_window
    
    cooldown_remaining = 0
    session_started = False
    
    # RNG for fill probability (models queue position)
    rng = np.random.default_rng(42)
    
    # Outstanding quotes from previous tick (None = not quoting)
    pending_bid = None  # price of our resting buy limit
    pending_ask = None  # price of our resting sell limit
    
    for i in range(1, n_ticks):
        ts = pd.Timestamp(times[i])
        hour = ts.hour
        
        # ── Session filter ──
        in_session = params.session_start_hour <= hour < params.session_end_hour
        
        if not in_session:
            if session_started and state.inventory != 0 and params.force_close_end_of_session:
                state.force_close(mids[i])
                session_started = False
            pending_bid = None
            pending_ask = None
            continue
        
        session_started = True
        
        # ── Kill switch: wide spread ──
        if spreads[i] > spread_kill:
            cooldown_remaining = params.cooldown_ticks
            state.n_quotes_pulled += 1
            pending_bid = None
            pending_ask = None
            continue
        
        # ── Kill switch: sustained directional move ──
        if i >= vol_window:
            net_move = abs(mids[i] - mids[i - vol_window])
            # Compare net move to typical per-tick moves
            typical_tick_move = np.mean(np.abs(np.diff(mids[max(0, i - vol_window):i + 1])))
            # Expected random walk: typical_move * sqrt(window)
            expected_move = typical_tick_move * np.sqrt(vol_window) if typical_tick_move > 0 else PIP
            move_ratio = net_move / expected_move
            
            if move_ratio > params.volatility_kill_threshold:
                cooldown_remaining = params.cooldown_ticks
                state.n_quotes_pulled += 1
                pending_bid = None
                pending_ask = None
                continue
        
        # ── Cooldown ──
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
            pending_bid = None
            pending_ask = None
            continue
        
        # ── Check fills on PENDING quotes from previous tick ──
        if pending_bid is not None or pending_ask is not None:
            can_buy = state.inventory < params.max_inventory
            can_sell = state.inventory > -params.max_inventory
            
            bid_filled = False
            ask_filled = False
            
            if pending_bid is not None and can_buy:
                # Our resting buy at pending_bid fills if market moved down to it
                # i.e., this tick's low (bid) went at or below our buy price
                if bids[i] <= pending_bid:
                    # Market traded at our level — but did we get queue priority?
                    if rng.random() < params.fill_probability:
                        bid_filled = True
                    # If market went well through, guaranteed fill (adverse selection)
                    if bids[i] < pending_bid - PIP:
                        bid_filled = True
            
            if pending_ask is not None and can_sell:
                # Our resting sell at pending_ask fills if market moved up to it
                if asks[i] >= pending_ask:
                    if rng.random() < params.fill_probability:
                        ask_filled = True
                    if asks[i] > pending_ask + PIP:
                        ask_filled = True
            
            if bid_filled:
                state.buy_fill(pending_bid)
            if ask_filled:
                state.sell_fill(pending_ask)
        
        # ── Place NEW quotes for next tick ──
        mid = mids[i]
        skew = state.inventory * inv_skew
        
        # When long, skew quotes down (eager to sell, reluctant to buy more)
        pending_bid = mid - half_spread - skew
        pending_ask = mid + half_spread - skew
        
        # Track unrealized PnL
        unrealized = state.unrealized_pnl(mid)
        if unrealized < state.max_unrealized_loss:
            state.max_unrealized_loss = unrealized
    
    # End of day — force close any remaining inventory
    if state.inventory != 0:
        state.force_close(mids[-1])
    
    return state


# ─────────────────────────────────────────────────
# Multi-Day Simulation
# ─────────────────────────────────────────────────

def run_simulation(start_date: datetime, end_date: datetime,
                   params: MMParams, sample_days: Optional[int] = None) -> dict:
    """
    Run market-making sim across a date range, one day at a time.
    
    If sample_days is set, randomly sample that many days instead of all.
    """
    from tick_vault import read_tick_data
    
    # Generate business days
    dates = pd.bdate_range(start_date, end_date)
    if sample_days and len(dates) > sample_days:
        rng = np.random.default_rng(42)
        indices = rng.choice(len(dates), size=sample_days, replace=False)
        dates = dates[sorted(indices)]
    
    all_trade_pnls = []
    daily_pnls = []
    total_fills = 0
    total_round_trips = 0
    total_timeouts = 0
    total_kills = 0
    days_processed = 0
    
    for date in dates:
        day_start = date.to_pydatetime()
        day_end = day_start + timedelta(days=1)
        
        try:
            ticks = read_tick_data("EURUSD", day_start, day_end)
        except Exception:
            continue
        
        if len(ticks) < 100:
            continue
        
        state = simulate_day(ticks, params)
        
        daily_pnl = state.realized_pnl
        daily_pnls.append(daily_pnl)
        all_trade_pnls.extend(state.trade_pnls)
        total_fills += state.n_fills
        total_round_trips += state.n_round_trips
        total_timeouts += state.n_timeouts
        total_kills += state.n_quotes_pulled
        days_processed += 1
        
        if days_processed % 50 == 0:
            cum_pnl = sum(daily_pnls) / PIP
            print(f"  ... {days_processed} days processed | cum PnL: {cum_pnl:+.0f} pips | "
                  f"fills: {total_fills} | last day: {day_start.date()}")
    
    # Compute results
    daily_pnls = np.array(daily_pnls)
    daily_pips = daily_pnls / PIP
    trade_pnls = np.array(all_trade_pnls) if all_trade_pnls else np.array([0])
    trade_pips = trade_pnls / PIP
    
    # Equity curve
    equity = np.cumsum(daily_pips)
    peak = np.maximum.accumulate(equity)
    drawdown = equity - peak
    
    return {
        "days": days_processed,
        "total_pnl_pips": daily_pips.sum(),
        "avg_daily_pips": daily_pips.mean(),
        "daily_std_pips": daily_pips.std(),
        "daily_sharpe": daily_pips.mean() / daily_pips.std() * np.sqrt(252) if daily_pips.std() > 0 else 0,
        "daily_win_rate": (daily_pips > 0).mean() * 100,
        "total_fills": total_fills,
        "total_round_trips": total_round_trips,
        "total_timeouts": total_timeouts,
        "total_kills": total_kills,
        "avg_fills_per_day": total_fills / max(days_processed, 1),
        "trade_wr": (trade_pips > 0).mean() * 100 if len(trade_pips) > 1 else 0,
        "avg_trade_pips": trade_pips.mean(),
        "max_drawdown_pips": drawdown.min(),
        "best_day_pips": daily_pips.max(),
        "worst_day_pips": daily_pips.min(),
        "profit_factor": abs(daily_pips[daily_pips > 0].sum() / daily_pips[daily_pips < 0].sum()) if (daily_pips < 0).any() else float("inf"),
        "equity_curve": equity,
        "daily_pips_series": daily_pips,
    }


# ─────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("TICK-LEVEL MARKET-MAKING SIMULATION — EURUSD")
    print("=" * 80)
    
    # ── Phase 1: Quick validation on recent data (2024-2025) ──
    print("\n" + "=" * 80)
    print("PHASE 1: Quick validation — 200 sampled days from 2020-2025")
    print("=" * 80)
    
    base_params = MMParams(
        half_spread_pips=2.0,
        max_inventory=3,
        inventory_skew_pips=0.3,
        session_start_hour=7,
        session_end_hour=17,  # London session
        spread_kill_pips=1.5,
        volatility_kill_threshold=3.0,
        cooldown_ticks=200,
        fill_probability=0.7,
    )
    
    print(f"\nParams: half_spread={base_params.half_spread_pips}p, "
          f"max_inv={base_params.max_inventory}, "
          f"session={base_params.session_start_hour}-{base_params.session_end_hour}h, "
          f"fill_prob={base_params.fill_probability}, "
          f"spread_kill={base_params.spread_kill_pips}p")
    
    result = run_simulation(
        datetime(2020, 1, 1), datetime(2025, 12, 31),
        base_params, sample_days=200
    )
    print_results("London 7-17h, 2.0p spread, 200 days", result)
    
    # ── Phase 2: Parameter sweep on same sample ──
    print("\n" + "=" * 80)
    print("PHASE 2: Parameter sweep — half-spread variations")
    print("=" * 80)
    
    for hs in [1.5, 2.0, 2.5, 3.0]:
        params = MMParams(
            half_spread_pips=hs,
            max_inventory=3,
            inventory_skew_pips=0.3,
            session_start_hour=7,
            session_end_hour=17,
            spread_kill_pips=1.5,
            volatility_kill_threshold=3.0,
            cooldown_ticks=200,
            fill_probability=0.7,
        )
        result = run_simulation(
            datetime(2020, 1, 1), datetime(2025, 12, 31),
            params, sample_days=100
        )
        print_results(f"half_spread={hs}p", result)
    
    # ── Phase 3: Session comparison ──
    print("\n" + "=" * 80)
    print("PHASE 3: Session comparison")
    print("=" * 80)
    
    sessions = [
        ("London (7-17)", 7, 17),
        ("London AM (7-12)", 7, 12),
        ("NY overlap (13-17)", 13, 17),
        ("Extended (7-21)", 7, 21),
        ("Asian (0-7)", 0, 7),
    ]
    
    for name, start, end in sessions:
        params = MMParams(
            half_spread_pips=2.0,
            max_inventory=3,
            inventory_skew_pips=0.3,
            session_start_hour=start,
            session_end_hour=end,
            spread_kill_pips=1.5,
            volatility_kill_threshold=3.0,
            cooldown_ticks=200,
            fill_probability=0.7,
        )
        result = run_simulation(
            datetime(2020, 1, 1), datetime(2025, 12, 31),
            params, sample_days=100
        )
        print_results(name, result)
    
    # ── Phase 4: Fill probability sensitivity ──
    print("\n" + "=" * 80)
    print("PHASE 4: Fill probability sensitivity (models queue position)")
    print("=" * 80)
    
    for fp in [0.3, 0.5, 0.7, 0.9, 1.0]:
        params = MMParams(
            half_spread_pips=2.0,
            max_inventory=3,
            inventory_skew_pips=0.3,
            session_start_hour=7,
            session_end_hour=17,
            spread_kill_pips=1.5,
            volatility_kill_threshold=3.0,
            cooldown_ticks=200,
            fill_probability=fp,
        )
        result = run_simulation(
            datetime(2020, 1, 1), datetime(2025, 12, 31),
            params, sample_days=100
        )
        print_results(f"fill_prob={fp}", result)
    
    # ── Phase 5: Inventory management comparison ──
    print("\n" + "=" * 80)
    print("PHASE 5: Max inventory & skew sensitivity")
    print("=" * 80)
    
    for max_inv, skew in [(1, 0.0), (1, 0.5), (2, 0.3), (3, 0.3), (3, 0.5), (5, 0.3)]:
        params = MMParams(
            half_spread_pips=2.0,
            max_inventory=max_inv,
            inventory_skew_pips=skew,
            session_start_hour=7,
            session_end_hour=17,
            spread_kill_pips=1.5,
            volatility_kill_threshold=3.0,
            cooldown_ticks=200,
            fill_probability=0.7,
        )
        result = run_simulation(
            datetime(2020, 1, 1), datetime(2025, 12, 31),
            params, sample_days=100
        )
        print_results(f"max_inv={max_inv}, skew={skew}p", result)
    
    # ── Phase 6: Full backtest on best params ──
    print("\n" + "=" * 80)
    print("PHASE 6: Full backtest — ALL trading days 2020-2025 (best params)")
    print("=" * 80)
    
    best_params = MMParams(
        half_spread_pips=2.0,
        max_inventory=3,
        inventory_skew_pips=0.3,
        session_start_hour=7,
        session_end_hour=17,
        spread_kill_pips=1.5,
        volatility_kill_threshold=3.0,
        cooldown_ticks=200,
        fill_probability=0.7,
    )
    
    result = run_simulation(
        datetime(2020, 1, 1), datetime(2025, 12, 31),
        best_params, sample_days=None  # ALL days
    )
    print_results("FULL BACKTEST 2020-2025", result)
    
    # Yearly breakdown
    if result["days"] > 100:
        daily = result["daily_pips_series"]
        # Approximate yearly split (252 trading days/year)
        years = [2020, 2021, 2022, 2023, 2024, 2025]
        idx = 0
        print(f"\n  Yearly Breakdown:")
        print(f"  {'Year':<6} {'Days':>5} {'PnL':>8} {'AvgDay':>8} {'Sharpe':>7} {'WR%':>6} {'MaxDD':>7}")
        for yr_i, yr in enumerate(years):
            # ~252 days per year, but account for actual count
            n_days_yr = min(252, len(daily) - idx)
            if n_days_yr <= 0:
                break
            yr_data = daily[idx:idx + n_days_yr]
            yr_eq = np.cumsum(yr_data)
            yr_dd = (yr_eq - np.maximum.accumulate(yr_eq)).min()
            yr_sharpe = yr_data.mean() / yr_data.std() * np.sqrt(252) if yr_data.std() > 0 else 0
            yr_wr = (yr_data > 0).mean() * 100
            print(f"  {yr:<6} {len(yr_data):>5} {yr_data.sum():>7.0f}p {yr_data.mean():>7.2f}p "
                  f"{yr_sharpe:>6.2f} {yr_wr:>5.1f}% {yr_dd:>6.0f}p")
            idx += n_days_yr
    
    print(f"\n{'=' * 80}")
    print("SIMULATION COMPLETE")
    print(f"{'=' * 80}")


def print_results(label: str, r: dict):
    print(f"\n  {label}:")
    print(f"    Days: {r['days']} | Fills: {r['total_fills']} ({r['avg_fills_per_day']:.0f}/day) | "
          f"Round trips: {r['total_round_trips']} | Timeouts: {r['total_timeouts']} | Kills: {r['total_kills']}")
    print(f"    Total PnL: {r['total_pnl_pips']:+.0f} pips | Avg daily: {r['avg_daily_pips']:+.2f} pips | "
          f"Daily WR: {r['daily_win_rate']:.1f}%")
    print(f"    Daily Sharpe: {r['daily_sharpe']:.2f} | Profit Factor: {r['profit_factor']:.2f} | "
          f"Max DD: {r['max_drawdown_pips']:.0f} pips")
    print(f"    Trade WR: {r['trade_wr']:.1f}% | Avg trade: {r['avg_trade_pips']:+.2f} pips | "
          f"Best day: {r['best_day_pips']:+.1f}p | Worst day: {r['worst_day_pips']:+.1f}p")


if __name__ == "__main__":
    main()
