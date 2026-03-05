"""
Tick-Level Market-Making Simulation v2 — EURUSD
=================================================
Properly models RESTING limit orders that persist until filled.

Key design: 
  - Place bid/ask quotes relative to mid at time of placement.
  - Quotes REST on book until filled or CANCELLED (refreshed).
  - Refresh quotes every N ticks (requote_interval) to track the market.
  - A fill happens when the market reaches our resting level.
"""

import logging
import os
import sys
os.environ["TQDM_DISABLE"] = "1"
# Suppress ALL logging noise from tick_vault
logging.disable(logging.WARNING)
logging.getLogger("tick_vault").setLevel(logging.CRITICAL)
logging.getLogger().setLevel(logging.CRITICAL)

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional


PIP = 0.0001


@dataclass
class MMState:
    inventory: int = 0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    n_buy_fills: int = 0
    n_sell_fills: int = 0
    n_round_trips: int = 0
    n_timeouts: int = 0
    n_quotes_pulled: int = 0
    max_unrealized_loss: float = 0.0
    trade_pnls: list = field(default_factory=list)
    
    def buy_fill(self, price: float):
        self.n_buy_fills += 1
        if self.inventory < 0:
            pnl = self.avg_entry_price - price
            self.realized_pnl += pnl
            self.trade_pnls.append(pnl)
            self.n_round_trips += 1
            self.inventory += 1
            if self.inventory == 0:
                self.avg_entry_price = 0.0
        else:
            if self.inventory == 0:
                self.avg_entry_price = price
            else:
                self.avg_entry_price = (self.avg_entry_price * self.inventory + price) / (self.inventory + 1)
            self.inventory += 1
    
    def sell_fill(self, price: float):
        self.n_sell_fills += 1
        if self.inventory > 0:
            pnl = price - self.avg_entry_price
            self.realized_pnl += pnl
            self.trade_pnls.append(pnl)
            self.n_round_trips += 1
            self.inventory -= 1
            if self.inventory == 0:
                self.avg_entry_price = 0.0
        else:
            if self.inventory == 0:
                self.avg_entry_price = price
            else:
                self.avg_entry_price = (self.avg_entry_price * abs(self.inventory) + price) / (abs(self.inventory) + 1)
            self.inventory -= 1
    
    def force_close(self, mid_price: float):
        if self.inventory == 0:
            return
        self.n_timeouts += 1
        if self.inventory > 0:
            pnl = (mid_price - self.avg_entry_price) * self.inventory
        else:
            pnl = (self.avg_entry_price - mid_price) * abs(self.inventory)
        self.realized_pnl += pnl
        self.trade_pnls.append(pnl)
        self.inventory = 0
        self.avg_entry_price = 0.0


@dataclass
class MMParams:
    half_spread_pips: float = 2.0
    max_inventory: int = 3
    inventory_skew_pips: float = 0.3
    session_start_hour: int = 7
    session_end_hour: int = 17
    # How often to refresh quotes (ticks). Smaller = tighter tracking; larger = more patient.
    requote_interval: int = 50
    # Kill switch
    spread_kill_pips: float = 2.0   # pull quotes if market spread > this
    vol_kill_window: int = 500      # ticks to measure volatility
    vol_kill_threshold: float = 4.0 # net move / expected random walk
    cooldown_ticks: int = 500       # stay out after kill
    # Fill modeling
    fill_probability: float = 0.7


def simulate_day(ticks: pd.DataFrame, params: MMParams) -> MMState:
    """
    Simulate one day of market making with RESTING limit orders.
    
    Every requote_interval ticks, we cancel old quotes and place new ones
    around the current mid (adjusted for inventory skew). Between requotes,
    we scan each tick to see if the market reached our resting levels.
    """
    state = MMState()
    
    asks = ticks["ask"].values
    bids = ticks["bid"].values
    times = ticks["time"].values
    n = len(ticks)
    
    if n < 200:
        return state
    
    mids = (asks + bids) / 2.0
    spreads = asks - bids
    
    half_spread = params.half_spread_pips * PIP
    inv_skew = params.inventory_skew_pips * PIP
    spread_kill = params.spread_kill_pips * PIP
    
    rng = np.random.default_rng(42)
    
    # Resting order levels (None = no order)
    my_bid = None
    my_ask = None
    ticks_since_requote = 0
    cooldown = 0
    session_active = False
    
    for i in range(1, n):
        hour = pd.Timestamp(times[i]).hour
        in_session = params.session_start_hour <= hour < params.session_end_hour
        
        # ── Session boundary ──
        if not in_session:
            if session_active:
                if state.inventory != 0:
                    state.force_close(mids[i])
                my_bid = None
                my_ask = None
                session_active = False
            continue
        session_active = True
        
        # ── Kill switch: wide spread ──
        if spreads[i] > spread_kill:
            cooldown = params.cooldown_ticks
            my_bid = None
            my_ask = None
            state.n_quotes_pulled += 1
            continue
        
        # ── Kill switch: volatility ──
        if i >= params.vol_kill_window:
            net_move = abs(mids[i] - mids[i - params.vol_kill_window])
            tick_moves = np.abs(np.diff(mids[i - params.vol_kill_window:i + 1]))
            avg_tick = tick_moves.mean() if len(tick_moves) > 0 else PIP
            expected = avg_tick * np.sqrt(params.vol_kill_window)
            if expected > 0 and net_move / expected > params.vol_kill_threshold:
                cooldown = params.cooldown_ticks
                my_bid = None
                my_ask = None
                state.n_quotes_pulled += 1
                continue
        
        # ── Cooldown ──
        if cooldown > 0:
            cooldown -= 1
            continue
        
        # ── Check fills on resting orders ──
        if my_bid is not None:
            can_buy = state.inventory < params.max_inventory
            # Market low (bid) reached our buy level → we get filled
            if can_buy and bids[i] <= my_bid:
                # Queue priority check
                if rng.random() < params.fill_probability or bids[i] < my_bid - PIP:
                    state.buy_fill(my_bid)
                    my_bid = None  # order consumed
        
        if my_ask is not None:
            can_sell = state.inventory > -params.max_inventory
            # Market high (ask) reached our sell level → we get filled
            if can_sell and asks[i] >= my_ask:
                if rng.random() < params.fill_probability or asks[i] > my_ask + PIP:
                    state.sell_fill(my_ask)
                    my_ask = None  # order consumed
        
        # ── Place / refresh quotes ──
        ticks_since_requote += 1
        needs_requote = (
            ticks_since_requote >= params.requote_interval
            or my_bid is None
            or my_ask is None
        )
        
        if needs_requote:
            mid = mids[i]
            skew = state.inventory * inv_skew
            my_bid = mid - half_spread - skew
            my_ask = mid + half_spread - skew
            ticks_since_requote = 0
        
        # Track unrealized
        unrealized = 0
        if state.inventory != 0:
            if state.inventory > 0:
                unrealized = (mids[i] - state.avg_entry_price) * state.inventory
            else:
                unrealized = (state.avg_entry_price - mids[i]) * abs(state.inventory)
            if unrealized < state.max_unrealized_loss:
                state.max_unrealized_loss = unrealized
    
    # End of day flatten
    if state.inventory != 0:
        state.force_close(mids[-1])
    
    return state


def run_simulation(start_date: datetime, end_date: datetime,
                   params: MMParams, sample_days: Optional[int] = None) -> dict:
    from tick_vault import read_tick_data
    
    dates = pd.bdate_range(start_date, end_date)
    if sample_days and len(dates) > sample_days:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(dates), size=sample_days, replace=False)
        dates = dates[sorted(idx)]
    
    daily_pnls = []
    all_trades = []
    total_buys = 0
    total_sells = 0
    total_rts = 0
    total_timeouts = 0
    total_kills = 0
    days_ok = 0
    
    for date in dates:
        d0 = date.to_pydatetime()
        d1 = d0 + timedelta(days=1)
        try:
            ticks = read_tick_data("EURUSD", d0, d1)
        except Exception:
            continue
        if len(ticks) < 200:
            continue
        
        s = simulate_day(ticks, params)
        daily_pnls.append(s.realized_pnl)
        all_trades.extend(s.trade_pnls)
        total_buys += s.n_buy_fills
        total_sells += s.n_sell_fills
        total_rts += s.n_round_trips
        total_timeouts += s.n_timeouts
        total_kills += s.n_quotes_pulled
        days_ok += 1
        
        if days_ok % 50 == 0:
            cum = sum(daily_pnls) / PIP
            print(f"  ... {days_ok} days | cum PnL: {cum:+.0f}p | buys: {total_buys} sells: {total_sells} | {d0.date()}")
    
    dp = np.array(daily_pnls) / PIP
    tp = np.array(all_trades) / PIP if all_trades else np.array([0.0])
    eq = np.cumsum(dp)
    peak = np.maximum.accumulate(eq) if len(eq) > 0 else np.array([0])
    dd = (eq - peak).min() if len(eq) > 1 else 0
    
    return {
        "days": days_ok,
        "total_pips": dp.sum(),
        "avg_daily": dp.mean() if days_ok else 0,
        "daily_std": dp.std() if days_ok else 1,
        "sharpe": dp.mean() / dp.std() * np.sqrt(252) if days_ok and dp.std() > 0 else 0,
        "daily_wr": (dp > 0).mean() * 100 if days_ok else 0,
        "buys": total_buys,
        "sells": total_sells,
        "round_trips": total_rts,
        "timeouts": total_timeouts,
        "kills": total_kills,
        "fills_day": (total_buys + total_sells) / max(days_ok, 1),
        "trade_wr": (tp > 0).mean() * 100,
        "avg_trade": tp.mean(),
        "max_dd": dd,
        "best_day": dp.max() if days_ok else 0,
        "worst_day": dp.min() if days_ok else 0,
        "pf": abs(dp[dp > 0].sum() / dp[dp < 0].sum()) if (dp < 0).any() and (dp > 0).any() else float("inf"),
    }


def fmt(label, r):
    print(f"\n  {label}:")
    print(f"    {r['days']} days | {r['buys']}B + {r['sells']}S = {r['buys']+r['sells']} fills ({r['fills_day']:.0f}/day) | "
          f"RT: {r['round_trips']} | TO: {r['timeouts']} | Kills: {r['kills']}")
    print(f"    PnL: {r['total_pips']:+.0f}p | Avg/day: {r['avg_daily']:+.2f}p | DailyWR: {r['daily_wr']:.1f}% | "
          f"Sharpe: {r['sharpe']:.2f} | PF: {r['pf']:.2f}")
    print(f"    TradeWR: {r['trade_wr']:.1f}% | AvgTrade: {r['avg_trade']:+.2f}p | "
          f"Best: {r['best_day']:+.1f}p | Worst: {r['worst_day']:+.1f}p | MaxDD: {r['max_dd']:.0f}p")


def main():
    print("=" * 70)
    print("TICK-LEVEL MARKET-MAKING v2 — RESTING ORDER MODEL")
    print("=" * 70)
    
    # ── Single day debug ──
    print("\n--- Single day debug (2024-06-03) ---")
    from tick_vault import read_tick_data
    ticks = read_tick_data("EURUSD", datetime(2024, 6, 3), datetime(2024, 6, 4))
    p = MMParams()
    s = simulate_day(ticks, p)
    print(f"  Ticks: {len(ticks)} | Buys: {s.n_buy_fills} | Sells: {s.n_sell_fills} | "
          f"RT: {s.n_round_trips} | PnL: {s.realized_pnl/PIP:+.1f}p | Kills: {s.n_quotes_pulled}")
    
    # ── Phase 1: Base case — 100 days ──
    print("\n" + "=" * 70)
    print("PHASE 1: London 7-17h, half_spread=2.0p, 100 days (2020-2025)")
    print("=" * 70)
    r = run_simulation(datetime(2020, 1, 1), datetime(2025, 12, 31), MMParams(), sample_days=100)
    fmt("Base case", r)
    
    # ── Phase 2: Half-spread sweep ──
    print("\n" + "=" * 70)
    print("PHASE 2: Half-spread sweep (80 days each)")
    print("=" * 70)
    for hs in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0]:
        r = run_simulation(datetime(2020, 1, 1), datetime(2025, 12, 31),
                           MMParams(half_spread_pips=hs), sample_days=80)
        fmt(f"hs={hs}p", r)
    
    # ── Phase 3: Requote interval ──
    print("\n" + "=" * 70)
    print("PHASE 3: Requote interval sweep (80 days)")
    print("=" * 70)
    for rq in [10, 25, 50, 100, 200, 500]:
        r = run_simulation(datetime(2020, 1, 1), datetime(2025, 12, 31),
                           MMParams(requote_interval=rq), sample_days=80)
        fmt(f"requote={rq}", r)
    
    # ── Phase 4: Session comparison ──
    print("\n" + "=" * 70)
    print("PHASE 4: Session comparison (80 days)")
    print("=" * 70)
    for name, sh, eh in [("London 7-17", 7, 17), ("London AM 7-12", 7, 12),
                          ("NY overlap 13-17", 13, 17), ("Extended 7-21", 7, 21),
                          ("Asian 0-7", 0, 7)]:
        r = run_simulation(datetime(2020, 1, 1), datetime(2025, 12, 31),
                           MMParams(session_start_hour=sh, session_end_hour=eh), sample_days=80)
        fmt(name, r)
    
    # ── Phase 5: Fill probability sensitivity ──
    print("\n" + "=" * 70)
    print("PHASE 5: Fill probability sensitivity (80 days)")
    print("=" * 70)
    for fp in [0.3, 0.5, 0.7, 0.9, 1.0]:
        r = run_simulation(datetime(2020, 1, 1), datetime(2025, 12, 31),
                           MMParams(fill_probability=fp), sample_days=80)
        fmt(f"fill_prob={fp}", r)
    
    # ── Phase 6: Inventory limits ──
    print("\n" + "=" * 70)
    print("PHASE 6: Max inventory & skew (80 days)")
    print("=" * 70)
    for mi, sk in [(1, 0.0), (1, 0.5), (2, 0.3), (3, 0.3), (3, 0.5), (5, 0.3)]:
        r = run_simulation(datetime(2020, 1, 1), datetime(2025, 12, 31),
                           MMParams(max_inventory=mi, inventory_skew_pips=sk), sample_days=80)
        fmt(f"maxinv={mi} skew={sk}", r)
    
    # ── Phase 7: Full backtest on best params ──
    print("\n" + "=" * 70)
    print("PHASE 7: Full backtest — ALL days 2020-2025")
    print("=" * 70)
    r = run_simulation(datetime(2020, 1, 1), datetime(2025, 12, 31), MMParams())
    fmt("FULL 2020-2025", r)
    
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
