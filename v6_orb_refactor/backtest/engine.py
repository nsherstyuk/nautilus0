import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional
import logging

from ..config.config import StrategyConfig
from ..core.market_event import Tick, Bar, RangeInfo
from ..core.historical_context import HistoricalMarketContext
from ..execution.sim_executor import SimExecutionEngine
from ..strategy.orb_strategy import ORBStrategy, StrategyState


class BacktestRunner:
    """
    Orchestrates the backtest.
    Responsible for loading data, wiring the modules together, and running the simulation loop.
    """
    
    def __init__(self, data_path: str, config: StrategyConfig, start_date: str = None, end_date: str = None, logger: Optional[logging.Logger] = None):
        self.data_path = data_path
        self.config = config
        self.start_date = start_date
        self.end_date = end_date
        self.logger = logger or logging.getLogger(__name__)
        
        # Instantiate deep modules
        self.context = HistoricalMarketContext(tick_buffer_minutes=config.velocity_lookback_minutes + 2)
        self.execution = SimExecutionEngine(
            spread=0.30,  # Default $0.30 spread, overridden per bar
            slippage=0.10, # $0.10 slippage for market orders
            on_fill_callback=self._on_fill
        )
        self.strategy = ORBStrategy(config, logger=logger)
        
        self.fills = []
        self.current_date = None
        
    def _on_fill(self, fill):
        self.fills.append(fill)
        self.strategy.on_fill(fill, self.context, self.execution)

    def _calculate_gap_metrics(self, df_day: pd.DataFrame, daily_range: RangeInfo):
        """Compute gap period (06:00-08:00 UTC) metrics and inject into context."""
        cfg = self.config
        if not cfg.gap_filter_enabled:
            return

        gap_data = df_day.between_time(
            f"{cfg.gap_start_hour:02d}:00",
            f"{cfg.gap_end_hour:02d}:00",
            inclusive="left"
        )
        if gap_data.empty or len(gap_data) < 3:
            # Still inject zero metrics so rolling history stays aligned
            self.context.inject_gap_data(
                df_day.index[0].date(), 0.0, 0.0,
                cfg.gap_vol_percentile, cfg.gap_range_percentile,
                cfg.gap_rolling_days)
            return

        gap_vol = HistoricalMarketContext.compute_gap_volatility_from_bars(gap_data)
        overnight_range = daily_range.size if daily_range else 0.0
        gap_range = HistoricalMarketContext.compute_gap_range_from_bars(
            gap_data, overnight_range)

        self.context.inject_gap_data(
            df_day.index[0].date(), gap_vol, gap_range,
            cfg.gap_vol_percentile, cfg.gap_range_percentile,
            cfg.gap_rolling_days)

    def _calculate_asian_range(self, df_day: pd.DataFrame) -> RangeInfo:
        """Helper to pre-calculate the Asian range for the day."""
        # Assume df index is datetime in UTC
        range_data = df_day.between_time(
            f"{self.config.range_start_hour:02d}:00", 
            f"{self.config.range_end_hour:02d}:00", 
            inclusive="left"
        )
        if range_data.empty:
            return None
            
        return RangeInfo(
            high=range_data['high'].max(),
            low=range_data['low'].min(),
            start_time=range_data.index[0].to_pydatetime(),
            end_time=range_data.index[-1].to_pydatetime()
        )

    def run(self):
        print(f"Loading data from {self.data_path}...")
        df = pd.read_csv(self.data_path)
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        
        if self.start_date:
            df = df.loc[self.start_date:]
        if self.end_date:
            df = df.loc[:self.end_date]
            
        print(f"Loaded {len(df)} 1-minute bars. Starting simulation...")
        
        # Group by day to manage daily state resets
        for date, df_day in df.groupby(df.index.date):
            wd = date.weekday()
            if wd >= 5:
                continue
            if self.config.skip_weekdays and wd in self.config.skip_weekdays:
                continue
                
            self.current_date = date
            
            # Reset strategy and execution for the new day
            self.strategy.reset_for_new_day()
            self.execution.cancel_orb_brackets()
            self.execution._entry_this_bar = False
            if self.execution.position != 0:
                self.execution.position = 0
                self.execution.entry_price = None
                self.execution.sl_price = None
                self.execution.tp_price = None
            
            # Pre-calculate the range and inject it into the context
            daily_range = self._calculate_asian_range(df_day)
            if daily_range:
                self.context.set_daily_range(daily_range, datetime.combine(date, datetime.min.time()))

            # Compute and inject gap metrics (before trade window)
            self._calculate_gap_metrics(df_day, daily_range)
            
            # Track last bar in trade window for EOD close
            last_trade_bar = None
            
            # Process bars for the day
            for timestamp, row in df_day.iterrows():
                bar_time = timestamp.to_pydatetime()
                
                # 1. Create Bar and update context (for velocity calc)
                bar = Bar(
                    timestamp=bar_time,
                    open=row['open'],
                    high=row['high'],
                    low=row['low'],
                    close=row['close'],
                    tick_count=row.get('tick_count', 0),
                    avg_spread=row.get('avg_spread', 0.30)
                )
                self.context.process_bar(bar)
                
                # Track trade window bars
                hour = bar_time.hour
                in_trade_window = self.config.trade_start_hour <= hour < self.config.trade_end_hour
                if in_trade_window:
                    last_trade_bar = bar
                
                # 2. Generate synthetic ticks for strategy state machine
                hs = bar.avg_spread / 2
                if bar.close > bar.open:
                    prices = [bar.open, bar.low, bar.high, bar.close]
                else:
                    prices = [bar.open, bar.high, bar.low, bar.close]
                    
                for px in prices:
                    tick = Tick(
                        timestamp=bar_time,
                        bid=px - hs,
                        ask=px + hs
                    )
                    self.strategy.on_tick(tick, self.context, self.execution)
                
                # 3. Bar-level fill simulation (V5-exact)
                if in_trade_window:
                    self.execution.process_bar(bar)
            
            # EOD: close any open position at last trade window bar
            if self.execution.position != 0 and last_trade_bar is not None:
                self.execution.close_at_market_bar(last_trade_bar)
                self.strategy.state = StrategyState.DONE_TODAY
                
        print("Simulation complete.")
        return self.fills
