"""
V8 Backtest Runner -- Uses deep modules exclusively.

Data flow:
    1. Load CSV -> numpy arrays
    2. batch_centered() -> pivot_high[], pivot_low[] arrays
    3. Pre-compute ATR array
    4. Loop bars:
        PatternDetector.update_atr(...)
        PatternDetector.process_bar(close, i, pivot_high[i], pivot_low[i], get_buy_ratio)
        -> Optional[signal]
        Trade management (SL/TP/time-stop) inline

The same PatternDetector is used by live trading.
"""
import logging
from typing import Optional, List

import numpy as np
import pandas as pd

from ..config.strategy_config import StrategyConfig
from ..core.types import TradeRecord
from ..core.pattern_detector import PatternDetector
from ..core.pivot_computer import batch_centered


class BacktestRunner:
    """Orchestrates the backtest using deep modules.

    Loads data, pre-computes centered pivots and ATR, then runs the
    simulation loop feeding bars through PatternDetector.
    Trade management (SL/time-stop) is inline, matching engine_v2 exactly.
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
        self._preloaded_df = preloaded_df
        self.trades: List[TradeRecord] = []

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
            print("  0 bars in range")
            return df

        print(f"  {len(df):,} bars from {df['timestamp'].iloc[0]} "
              f"to {df['timestamp'].iloc[-1]}")
        return df

    @staticmethod
    def _compute_buy_ratio(buy_vols, sell_vols, tick_counts,
                           start: int, end: int, n: int,
                           min_bar_ticks: int) -> float:
        """Buy ratio with min_bar_ticks quality filter. Matches engine_v2."""
        if end > n:
            return float("nan")
        if start >= end:
            return float("nan")
        ticks = tick_counts[start:end]
        if min_bar_ticks > 0 and np.any(ticks < min_bar_ticks):
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

        # Extract arrays
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        buy_vols = df["buy_volume"].values
        sell_vols = df["sell_volume"].values
        tick_counts = df["tick_count"].values
        timestamps = df["timestamp"].values

        # Pre-compute pivots (deep module)
        pivot_high, pivot_low = batch_centered(
            highs, lows,
            window=self.config.pivot_window,
            shift=self.config.confirm_bars,
        )

        # Pre-compute ATR array (matches engine_v2)
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
        c = self.config
        imb_w = c.imbalance_window
        hold = c.max_hold_bars
        spread = c.spread_cost
        sl_mult = c.sl_atr_multiple
        min_ticks = c.min_bar_ticks

        # Deep module: pattern detection
        detector = PatternDetector(
            imbalance_window=imb_w,
            divergence_threshold=c.divergence_threshold,
            max_pullback_bars=c.max_pullback_bars,
            min_pullback_bars=c.min_pullback_bars,
            atr_period=atr_period,
        )

        # Buy ratio callback (closure over arrays)
        def get_buy_ratio(start: int, end: int) -> float:
            return self._compute_buy_ratio(
                buy_vols, sell_vols, tick_counts, start, end, n, min_ticks)

        # Trade state
        in_trade = False
        trade_entry_idx = 0
        trade_direction = ""
        trade_entry_price = 0.0
        trade_pivot = 0.0
        trade_br = 0.0
        trade_gap = 0
        trade_sl_price = 0.0
        cooldown = 0

        self.trades = []

        for i in range(n):
            # Update ATR in detector (for live parity -- not used in backtest trade mgmt)
            detector.update_atr(float(highs[i]), float(lows[i]), float(closes[i]))

            # Cooldown
            if cooldown > 0:
                cooldown -= 1
                continue

            # In-trade management
            if in_trade:
                bars_held = i - trade_entry_idx

                # Check catastrophe SL
                sl_hit = False
                if trade_sl_price != 0.0:
                    if trade_direction == "long" and lows[i] <= trade_sl_price:
                        sl_hit = True
                    elif trade_direction == "short" and highs[i] >= trade_sl_price:
                        sl_hit = True

                if sl_hit:
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
                        sl_price=trade_sl_price,
                        tp_price=0.0,
                        pivot_price=trade_pivot,
                        exit_reason="CATASTROPHE_SL",
                        pnl=pnl,
                        hold_bars=bars_held,
                        buy_ratio_at_entry=trade_br,
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
                        sl_price=trade_sl_price,
                        tp_price=0.0,
                        pivot_price=trade_pivot,
                        exit_reason="TIME_STOP",
                        pnl=pnl,
                        hold_bars=bars_held,
                        buy_ratio_at_entry=trade_br,
                        gap=trade_gap,
                    ))
                    in_trade = False
                    cooldown = imb_w
                continue

            # Pattern detection (deep module)
            signal = detector.process_bar(
                float(closes[i]), i,
                float(pivot_high[i]), float(pivot_low[i]),
                get_buy_ratio,
            )

            # Enter trade
            if signal is not None:
                direction, gap, br = signal
                eidx = i + imb_w
                if eidx < n:
                    ep = closes[eidx]
                    if direction == "long":
                        trade_entry_price = ep + spread / 2
                    else:
                        trade_entry_price = ep - spread / 2
                    trade_entry_idx = eidx
                    trade_direction = direction
                    trade_pivot = float(pivot_high[i]) if direction == "long" else float(pivot_low[i])
                    trade_br = br
                    trade_gap = gap
                    # Catastrophe SL
                    entry_atr = atr_arr[eidx] if not np.isnan(atr_arr[eidx]) else 0.5
                    if sl_mult < 50:
                        if direction == "long":
                            trade_sl_price = trade_entry_price - sl_mult * entry_atr
                        else:
                            trade_sl_price = trade_entry_price + sl_mult * entry_atr
                    else:
                        trade_sl_price = 0.0

                    in_trade = True

            if i % 500_000 == 0 and i > 0:
                print(f"  ... processed {i:,} bars, "
                      f"{len(self.trades)} trades so far")

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
        print(f"  Longs:         {len(longs)} "
              f"(PnL: ${sum(t.pnl for t in longs):+,.2f})")
        print(f"  Shorts:        {len(shorts)} "
              f"(PnL: ${sum(t.pnl for t in shorts):+,.2f})")
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
