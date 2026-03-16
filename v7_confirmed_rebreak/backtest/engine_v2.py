"""
V7 Backtest Engine v2 -- Pre-computed shifted pivots.

Uses centered pivot detection with a configurable shift delay,
computed once at data load time. This matches the proven research
methodology while remaining honest (no future data at trade time).

The pattern detection logic is a direct port of the standalone
research loop that achieved +$672 / 1496 trades / 51.9% WR.
"""
import numpy as np
import pandas as pd
import logging
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime

from ..config.strategy_config import StrategyConfig


@dataclass
class TradeRecord:
    entry_time: datetime
    exit_time: datetime
    direction: str
    entry_price: float
    exit_price: float
    pivot_price: float
    exit_reason: str
    pnl: float
    hold_bars: int
    buy_ratio: float
    gap: int


class BacktestEngineV2:
    """Backtest engine using pre-computed shifted-centered pivots.

    Computes pivots once over the full dataset using centered rolling
    max/min, then shifts the forward-fill by `confirm_bars` to simulate
    the causal delay of confirming a pivot in real time.

    Pattern detection, imbalance filtering, and trade execution are
    handled in a single pass matching the proven research loop.
    """

    def __init__(self, data_path: str, config: StrategyConfig,
                 start_date: Optional[str] = None,
                 end_date: Optional[str] = None,
                 logger: Optional[logging.Logger] = None,
                 preloaded_df: Optional[pd.DataFrame] = None):
        self.data_path = data_path
        self.config = config
        self.start_date = start_date
        self.end_date = end_date
        self.logger = logger or logging.getLogger(__name__)
        self.trades: List[TradeRecord] = []
        self._preloaded_df = preloaded_df

    @staticmethod
    def load_csv(data_path: str) -> pd.DataFrame:
        """Load and clean CSV once. Reuse via preloaded_df parameter."""
        print(f"Loading data from {data_path}...")
        df = pd.read_csv(data_path, parse_dates=["timestamp"])
        df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
        if df["timestamp"].dt.tz is not None:
            df["timestamp"] = df["timestamp"].dt.tz_localize(None)
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df[df["tick_count"] > 0].reset_index(drop=True)
        print(f"  {len(df):,} bars loaded")
        return df

    def _load_data(self) -> pd.DataFrame:
        if self._preloaded_df is not None:
            df = self._preloaded_df.copy()
        else:
            df = self.load_csv(self.data_path)

        if self.start_date:
            df = df[df["timestamp"] >= self.start_date].reset_index(drop=True)
        if self.end_date:
            df = df[df["timestamp"] <= self.end_date].reset_index(drop=True)

        if len(df) == 0:
            print(f"  0 bars in range")
            return df

        print(f"  {len(df):,} bars from {df['timestamp'].iloc[0]} "
              f"to {df['timestamp'].iloc[-1]}")
        return df

    def _compute_pivots(self, highs: np.ndarray, lows: np.ndarray,
                        n: int) -> tuple:
        """Centered pivot detection with shift delay."""
        window = self.config.pivot_window
        shift = self.config.confirm_bars
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
            lookback = i - shift
            if lookback >= 0:
                if is_ph[lookback]:
                    last_ph = highs[lookback]
                if is_pl[lookback]:
                    last_pl = lows[lookback]
            pivot_high[i] = last_ph
            pivot_low[i] = last_pl

        return pivot_high, pivot_low

    def _get_buy_ratio(self, buy_vols, sell_vols, tick_counts,
                       start: int, end: int, n: int) -> float:
        """Buy ratio with min_bar_ticks quality filter."""
        if end > n:
            return float("nan")
        ticks = tick_counts[start:end]
        min_t = self.config.min_bar_ticks
        if min_t > 0 and np.any(ticks < min_t):
            return float("nan")
        bv = buy_vols[start:end].sum()
        sv = sell_vols[start:end].sum()
        total = bv + sv
        if total == 0:
            return float("nan")
        return bv / total

    def run(self) -> List[TradeRecord]:
        df = self._load_data()
        n = len(df)
        if n == 0:
            print("Simulation complete. 0 trades.")
            self.trades = []
            return self.trades

        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        buy_vols = df["buy_volume"].values
        sell_vols = df["sell_volume"].values
        tick_counts = df["tick_count"].values
        timestamps = df["timestamp"].values

        # Pre-compute pivots
        pivot_high, pivot_low = self._compute_pivots(highs, lows, n)

        # Compute rolling ATR for catastrophe SL
        atr_period = self.config.atr_period
        tr_buf = []
        atr_arr = np.full(n, np.nan)
        prev_c = closes[0]
        for i in range(n):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - prev_c),
                     abs(lows[i] - prev_c))
            tr_buf.append(tr)
            if len(tr_buf) > atr_period:
                tr_buf.pop(0)
            atr_arr[i] = np.mean(tr_buf)
            prev_c = closes[i]

        # Config shortcuts
        imb_w = self.config.imbalance_window
        div_thr = self.config.divergence_threshold
        max_pb = self.config.max_pullback_bars
        min_pb = self.config.min_pullback_bars
        hold = self.config.max_hold_bars
        spread = self.config.spread_cost
        sl_mult = self.config.sl_atr_multiple

        # State
        in_trade = False
        trade_entry_idx = 0
        trade_direction = ""
        trade_entry_price = 0.0
        trade_pivot = 0.0
        trade_br = 0.0
        trade_gap = 0
        trade_sl_price = 0.0
        cooldown = 0

        # Pattern state per direction
        h_level = np.nan; h_broke = False; h_pb = False
        h_idx = -1; h_div = False
        l_level = np.nan; l_broke = False; l_pb = False
        l_idx = -1; l_div = False

        self.trades = []

        for i in range(n):
            # Cooldown
            if cooldown > 0:
                cooldown -= 1
                continue

            # In-trade management
            if in_trade:
                bars_held = i - trade_entry_idx

                # Check catastrophe SL (using bar high/low for intra-bar detection)
                sl_hit = False
                if trade_sl_price != 0.0:
                    if trade_direction == "long" and lows[i] <= trade_sl_price:
                        sl_hit = True
                    elif trade_direction == "short" and highs[i] >= trade_sl_price:
                        sl_hit = True

                if sl_hit:
                    # Exit at SL price (worst case: SL was hit intra-bar)
                    exit_price = trade_sl_price
                    if trade_direction == "long":
                        pnl = (exit_price - spread / 2) - trade_entry_price
                    else:
                        pnl = trade_entry_price - (exit_price + spread / 2)
                    self.trades.append(TradeRecord(
                        entry_time=pd.Timestamp(timestamps[trade_entry_idx]).to_pydatetime(),
                        exit_time=pd.Timestamp(timestamps[i]).to_pydatetime(),
                        direction=trade_direction,
                        entry_price=trade_entry_price,
                        exit_price=exit_price,
                        pivot_price=trade_pivot,
                        exit_reason="CATASTROPHE_SL",
                        pnl=pnl,
                        hold_bars=bars_held,
                        buy_ratio=trade_br,
                        gap=trade_gap,
                    ))
                    in_trade = False
                    cooldown = imb_w
                elif bars_held >= hold:
                    exit_price = closes[i]
                    if trade_direction == "long":
                        pnl = (exit_price - spread / 2) - trade_entry_price
                    else:
                        pnl = trade_entry_price - (exit_price + spread / 2)
                    self.trades.append(TradeRecord(
                        entry_time=pd.Timestamp(timestamps[trade_entry_idx]).to_pydatetime(),
                        exit_time=pd.Timestamp(timestamps[i]).to_pydatetime(),
                        direction=trade_direction,
                        entry_price=trade_entry_price,
                        exit_price=exit_price,
                        pivot_price=trade_pivot,
                        exit_reason="TIME_STOP",
                        pnl=pnl,
                        hold_bars=bars_held,
                        buy_ratio=trade_br,
                        gap=trade_gap,
                    ))
                    in_trade = False
                    cooldown = imb_w
                continue

            # Update pivot levels - reset state on change
            if not np.isnan(pivot_high[i]) and pivot_high[i] != h_level:
                h_level = pivot_high[i]
                h_broke = False; h_pb = False; h_idx = -1
            if not np.isnan(pivot_low[i]) and pivot_low[i] != l_level:
                l_level = pivot_low[i]
                l_broke = False; l_pb = False; l_idx = -1

            signal = None

            # --- LONG (pivot high breakout) ---
            if not np.isnan(h_level):
                if not h_broke:
                    if closes[i] > h_level:
                        ie = min(i + imb_w + 1, n)
                        if ie > i + 1:
                            br = self._get_buy_ratio(buy_vols, sell_vols,
                                                     tick_counts, i + 1, ie, n)
                            if not np.isnan(br):
                                h_broke = True; h_idx = i
                                h_div = (br < div_thr)
                                if not h_div:
                                    h_broke = False
                elif not h_pb:
                    if closes[i] <= h_level:
                        h_pb = True
                else:
                    gap = i - h_idx
                    if gap > max_pb:
                        h_broke = False; h_pb = False
                    elif gap >= min_pb and closes[i] > h_level:
                        ie = min(i + imb_w + 1, n)
                        if ie > i + 1:
                            br = self._get_buy_ratio(buy_vols, sell_vols,
                                                     tick_counts, i + 1, ie, n)
                            if not np.isnan(br):
                                if h_div and br >= div_thr:
                                    eidx = i + imb_w
                                    if eidx < n:
                                        signal = ("long", eidx, closes[eidx],
                                                  h_level, br, gap)
                                h_broke = False; h_pb = False

            # --- SHORT (pivot low breakout) ---
            if signal is None and not np.isnan(l_level):
                if not l_broke:
                    if closes[i] < l_level:
                        ie = min(i + imb_w + 1, n)
                        if ie > i + 1:
                            br = self._get_buy_ratio(buy_vols, sell_vols,
                                                     tick_counts, i + 1, ie, n)
                            if not np.isnan(br):
                                l_broke = True; l_idx = i
                                l_div = (br > div_thr)
                                if not l_div:
                                    l_broke = False
                elif not l_pb:
                    if closes[i] >= l_level:
                        l_pb = True
                else:
                    gap = i - l_idx
                    if gap > max_pb:
                        l_broke = False; l_pb = False
                    elif gap >= min_pb and closes[i] < l_level:
                        ie = min(i + imb_w + 1, n)
                        if ie > i + 1:
                            br = self._get_buy_ratio(buy_vols, sell_vols,
                                                     tick_counts, i + 1, ie, n)
                            if not np.isnan(br):
                                if l_div and br <= div_thr:
                                    eidx = i + imb_w
                                    if eidx < n:
                                        signal = ("short", eidx, closes[eidx],
                                                  l_level, br, gap)
                                l_broke = False; l_pb = False

            # Enter trade
            if signal is not None:
                direction, eidx, ep, pivot, br, gap = signal
                if direction == "long":
                    trade_entry_price = ep + spread / 2
                else:
                    trade_entry_price = ep - spread / 2
                trade_entry_idx = eidx
                trade_direction = direction
                trade_pivot = pivot
                trade_br = br
                trade_gap = gap
                # Catastrophe SL based on ATR at entry
                entry_atr = atr_arr[eidx] if not np.isnan(atr_arr[eidx]) else 0.5
                if sl_mult < 50:  # Only set SL if not effectively disabled
                    if direction == "long":
                        trade_sl_price = trade_entry_price - sl_mult * entry_atr
                    else:
                        trade_sl_price = trade_entry_price + sl_mult * entry_atr
                else:
                    trade_sl_price = 0.0  # Disabled
                in_trade = True

            if i % 500_000 == 0 and i > 0:
                print(f"  ... processed {i:,} bars, {len(self.trades)} trades so far")

        print(f"Simulation complete. {len(self.trades)} trades.")
        return self.trades

    def print_summary(self):
        trades = self.trades
        if not trades:
            print("No trades.")
            return

        pnls = [t.pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total_pnl = sum(pnls)
        win_rate = len(wins) / len(pnls) if pnls else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        avg_hold = sum(t.hold_bars for t in trades) / len(trades)

        reasons = {}
        for t in trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

        longs = [t for t in trades if t.direction == "long"]
        shorts = [t for t in trades if t.direction == "short"]

        monthly = {}
        for t in trades:
            key = t.entry_time.strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + t.pnl

        yearly = {}
        for t in trades:
            key = t.entry_time.strftime("%Y")
            yearly[key] = yearly.get(key, 0) + t.pnl

        c = self.config
        print(f"\n{'='*60}")
        print(f"BACKTEST RESULTS: {c.instrument}")
        print(f"  pivot_window={c.pivot_window} confirm_bars={c.confirm_bars} "
              f"imb_window={c.imbalance_window} min_ticks={c.min_bar_ticks}")
        print(f"  SL={c.sl_atr_multiple}xATR TP={c.tp_atr_multiple}xATR "
              f"max_hold={c.max_hold_bars}bars")
        print(f"  spread={c.spread_cost}")
        print(f"{'='*60}")
        print(f"  Total trades:  {len(trades)}")
        print(f"  Total PnL:     ${total_pnl:+,.2f}")
        print(f"  Win rate:      {win_rate:.1%}")
        print(f"  Avg PnL/trade: ${total_pnl/len(trades):+,.3f}")
        print(f"  Avg win:       ${avg_win:+,.2f}")
        print(f"  Avg loss:      ${avg_loss:+,.2f}")
        print(f"  Avg hold:      {avg_hold:.1f} bars")
        print(f"  Longs:         {len(longs)} (PnL: ${sum(t.pnl for t in longs):+,.2f})")
        print(f"  Shorts:        {len(shorts)} (PnL: ${sum(t.pnl for t in shorts):+,.2f})")
        print(f"  Exit reasons:  {reasons}")

        print(f"\n  Yearly P&L:")
        for yr in sorted(yearly):
            n_yr = sum(1 for t in trades if t.entry_time.strftime("%Y") == yr)
            print(f"    {yr}: ${yearly[yr]:+,.2f} ({n_yr} trades)")

        if monthly:
            worst_m = min(monthly, key=monthly.get)
            best_m = max(monthly, key=monthly.get)
            neg_months = sum(1 for v in monthly.values() if v < 0)
            print(f"\n  Monthly breakdown: {len(monthly)} months, "
                  f"{neg_months} negative")
            print(f"    Best:  {best_m} ${monthly[best_m]:+,.2f}")
            print(f"    Worst: {worst_m} ${monthly[worst_m]:+,.2f}")

        print(f"{'='*60}")
