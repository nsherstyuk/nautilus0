import pandas as pd
import logging
from typing import Optional
from pathlib import Path

from ..config.strategy_config import StrategyConfig
from ..core.market_types import Bar
from ..core.pattern_detector import PatternDetector
from ..execution.sim_executor import SimExecutionEngine
from ..strategy.rebreak_strategy import RebreakStrategy


class BacktestRunner:
    """Orchestrates the backtest.

    Loads 1-min CSV data, wires deep modules together, and runs the
    simulation loop. The strategy sees only Bars and Signals.
    """

    def __init__(self, data_path: str, config: StrategyConfig,
                 start_date: Optional[str] = None,
                 end_date: Optional[str] = None,
                 logger: Optional[logging.Logger] = None):
        self.data_path = data_path
        self.config = config
        self.start_date = start_date
        self.end_date = end_date
        self.logger = logger or logging.getLogger(__name__)

        # Instantiate deep modules
        self.detector = PatternDetector(
            pivot_window=config.pivot_window,
            imbalance_window=config.imbalance_window,
            divergence_threshold=config.divergence_threshold,
            max_pullback_bars=config.max_pullback_bars,
            min_pullback_bars=config.min_pullback_bars,
            atr_period=config.atr_period,
            min_bar_ticks=config.min_bar_ticks,
            confirm_bars=config.confirm_bars,
        )
        self.execution = SimExecutionEngine(
            spread=config.spread_cost,
        )
        self.strategy = RebreakStrategy(config, logger=self.logger)

    def run(self):
        print(f"Loading data from {self.data_path}...")
        df = pd.read_csv(self.data_path, parse_dates=["timestamp"])
        df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
        if df["timestamp"].dt.tz is not None:
            df["timestamp"] = df["timestamp"].dt.tz_localize(None)
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df[df["tick_count"] > 0].reset_index(drop=True)

        if self.start_date:
            df = df[df["timestamp"] >= self.start_date].reset_index(drop=True)
        if self.end_date:
            df = df[df["timestamp"] <= self.end_date].reset_index(drop=True)

        print(f"  {len(df):,} bars from {df['timestamp'].iloc[0]} "
              f"to {df['timestamp'].iloc[-1]}")

        for i in range(len(df)):
            row = df.iloc[i]
            bar = Bar(
                timestamp=row["timestamp"].to_pydatetime(),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                tick_count=int(row["tick_count"]),
                buy_volume=row["buy_volume"],
                sell_volume=row["sell_volume"],
            )
            self.strategy.on_bar(bar, i, self.detector, self.execution)

            if i % 500_000 == 0 and i > 0:
                n_trades = len(self.strategy.trades)
                print(f"  ... processed {i:,} bars, {n_trades} trades so far")

        # Close any open position at end
        if self.execution.has_position():
            last_row = df.iloc[-1]
            last_bar = Bar(
                timestamp=last_row["timestamp"].to_pydatetime(),
                open=last_row["open"],
                high=last_row["high"],
                low=last_row["low"],
                close=last_row["close"],
                tick_count=int(last_row["tick_count"]),
                buy_volume=last_row["buy_volume"],
                sell_volume=last_row["sell_volume"],
            )
            self.execution.close_at_market(last_bar, "END_OF_DATA")

        print(f"Simulation complete. {len(self.strategy.trades)} trades.")
        return self.strategy.trades

    def print_summary(self):
        trades = self.strategy.trades
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

        # Exit reasons
        reasons = {}
        for t in trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

        # Direction breakdown
        longs = [t for t in trades if t.direction == "long"]
        shorts = [t for t in trades if t.direction == "short"]

        # Monthly P&L
        monthly = {}
        for t in trades:
            key = t.entry_time.strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + t.pnl

        # Yearly P&L
        yearly = {}
        for t in trades:
            key = t.entry_time.strftime("%Y")
            yearly[key] = yearly.get(key, 0) + t.pnl

        print(f"\n{'='*60}")
        print(f"BACKTEST RESULTS: {self.config.instrument}")
        print(f"  pivot_window={self.config.pivot_window} "
              f"imb_window={self.config.imbalance_window} "
              f"min_ticks={self.config.min_bar_ticks}")
        print(f"  SL={self.config.sl_atr_multiple}xATR "
              f"TP={self.config.tp_atr_multiple}xATR "
              f"max_hold={self.config.max_hold_bars}bars")
        print(f"  spread={self.config.spread_cost}")
        print(f"{'='*60}")
        print(f"  Total trades:  {len(trades)}")
        print(f"  Total PnL:     ${total_pnl:+,.2f}")
        print(f"  Win rate:      {win_rate:.1%}")
        print(f"  Avg win:       ${avg_win:+,.2f}")
        print(f"  Avg loss:      ${avg_loss:+,.2f}")
        print(f"  Avg hold:      {avg_hold:.1f} bars")
        print(f"  Longs:         {len(longs)} (PnL: ${sum(t.pnl for t in longs):+,.2f})")
        print(f"  Shorts:        {len(shorts)} (PnL: ${sum(t.pnl for t in shorts):+,.2f})")
        print(f"  Exit reasons:  {reasons}")

        print(f"\n  Yearly P&L:")
        for yr in sorted(yearly):
            print(f"    {yr}: ${yearly[yr]:+,.2f}")

        # Worst/best month
        if monthly:
            worst_m = min(monthly, key=monthly.get)
            best_m = max(monthly, key=monthly.get)
            neg_months = sum(1 for v in monthly.values() if v < 0)
            print(f"\n  Monthly breakdown: {len(monthly)} months, "
                  f"{neg_months} negative")
            print(f"    Best:  {best_m} ${monthly[best_m]:+,.2f}")
            print(f"    Worst: {worst_m} ${monthly[worst_m]:+,.2f}")

        print(f"{'='*60}")
