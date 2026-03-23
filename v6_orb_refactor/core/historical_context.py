from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Deque, List
import math

from ..core.interfaces import MarketContext
from ..core.market_event import RangeInfo, Tick, Bar, GapMetrics


class HistoricalMarketContext(MarketContext):
    """
    MarketContext implementation for backtesting.
    Manages a rolling window of bars/ticks to calculate velocity and range.
    """
    def __init__(self, tick_buffer_minutes: int = 10):
        self.bar_buffer: Deque[Bar] = deque()
        self.tick_buffer_minutes = tick_buffer_minutes
        
        # We need to cache the asian range once calculated for the day
        self.current_range: Optional[RangeInfo] = None
        self.range_date: Optional[datetime] = None

        # Gap filter: rolling history of past gap metrics (injected by runner)
        self._gap_vol_history: Deque[float] = deque(maxlen=200)
        self._gap_range_history: Deque[float] = deque(maxlen=200)
        self._current_gap_metrics: Optional[GapMetrics] = None
        self._gap_metrics_date: Optional[object] = None  # date object

    def process_bar(self, bar: Bar):
        """
        Called by the runner to feed bar data into the context BEFORE the strategy sees synthetic ticks.
        """
        self.bar_buffer.append(bar)
        
        # Prune old bars
        cutoff = bar.timestamp - timedelta(minutes=self.tick_buffer_minutes)
        while self.bar_buffer and self.bar_buffer[0].timestamp < cutoff:
            self.bar_buffer.popleft()

    def get_velocity(self, lookback_minutes: int, current_time: datetime) -> float:
        """
        Calculate ticks per minute over the lookback window.
        Uses the tick_count field from the 1m bars.
        
        PARITY WARNING: This counts historical tick_count from CSV data (actual
        market ticks recorded by data provider). LiveMarketContext counts
        reqMktData bid/ask updates from IBKR, which are throttled/aggregated.
        A threshold calibrated on historical data will NOT transfer directly
        to live. Calibrate live threshold using velocity logger data.
        """
        cutoff = current_time - timedelta(minutes=lookback_minutes)
        
        # Sum tick_counts in the window
        total_ticks = sum(b.tick_count for b in self.bar_buffer if b.timestamp >= cutoff)
        
        return total_ticks / max(lookback_minutes, 0.01)

    def get_asian_range(self, start_hour: int, end_hour: int, current_time: datetime) -> Optional[RangeInfo]:
        """
        Calculate the high and low of the session range.
        For HistoricalMarketContext, we assume the runner pre-calculates this.
        """
        if self.current_range and self.range_date and self.range_date.date() == current_time.date():
            return self.current_range
        return None
        
    def set_daily_range(self, range_info: RangeInfo, current_date: datetime):
        """
        Helper for the backtest runner to inject the pre-calculated range.
        """
        self.current_range = range_info
        self.range_date = current_date

    def get_current_price(self, current_time: datetime) -> Optional[float]:
        """Return the last bar's close price (for breakeven guard checks)."""
        if self.bar_buffer:
            return self.bar_buffer[-1].close
        return None

    def time_is_in_trade_window(self, current_time: datetime, start_hour: int, end_hour: int) -> bool:
        """
        Check if the current time falls within the trading window.
        Assumes current_time is UTC.
        """
        return start_hour <= current_time.hour < end_hour

    # ── Gap Filter (Deep Module) ─────────────────────────────────────

    def inject_gap_data(self, date, gap_volatility: float,
                        gap_range: float, vol_pctl: float,
                        range_pctl: float, rolling_days: int):
        """Called by BacktestRunner BEFORE the trading day starts.
        Computes rolling percentiles from internal history and caches
        the GapMetrics for the strategy to query via get_gap_metrics().
        """
        # Compute rolling thresholds from trailing history
        vol_passes = True
        range_passes = True

        n = len(self._gap_vol_history)
        if n >= max(rolling_days // 2, 10):  # need minimum history
            # Use the last `rolling_days` values
            vol_window = list(self._gap_vol_history)[-rolling_days:]
            range_window = list(self._gap_range_history)[-rolling_days:]

            vol_idx = min(int(len(vol_window) * vol_pctl / 100), len(vol_window) - 1)
            range_idx = min(int(len(range_window) * range_pctl / 100), len(range_window) - 1)
            vol_threshold = sorted(vol_window)[vol_idx]
            range_threshold = sorted(range_window)[range_idx]

            vol_passes = gap_volatility >= vol_threshold
            range_passes = gap_range >= range_threshold

        self._current_gap_metrics = GapMetrics(
            gap_volatility=gap_volatility,
            gap_range=gap_range,
            vol_passes=vol_passes,
            range_passes=range_passes,
        )
        self._gap_metrics_date = date

        # Append AFTER computing thresholds (no lookahead)
        self._gap_vol_history.append(gap_volatility)
        self._gap_range_history.append(gap_range)

    def get_gap_metrics(self, current_time: datetime,
                        gap_start_hour: int, gap_end_hour: int,
                        vol_percentile: float, range_percentile: float,
                        rolling_days: int) -> Optional[GapMetrics]:
        """Return pre-computed gap metrics for today. None if unavailable."""
        if (self._current_gap_metrics is not None
                and self._gap_metrics_date == current_time.date()):
            return self._current_gap_metrics
        return None

    @staticmethod
    def compute_gap_volatility_from_bars(gap_bars_df) -> float:
        """Compute gap volatility = std of 1-min log returns.
        gap_bars_df: DataFrame with 'close' column, indexed by timestamp.
        """
        closes = gap_bars_df['close'].values
        if len(closes) < 3:
            return 0.0
        log_returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0 and closes[i] > 0:
                log_returns.append(math.log(closes[i] / closes[i - 1]))
        if len(log_returns) < 2:
            return 0.0
        mean_r = sum(log_returns) / len(log_returns)
        var = sum((r - mean_r) ** 2 for r in log_returns) / (len(log_returns) - 1)
        return math.sqrt(var)

    @staticmethod
    def compute_gap_range_from_bars(gap_bars_df, overnight_range: float) -> float:
        """Compute gap range = (gap_high - gap_low) / overnight_range.
        Returns 0.0 if overnight_range is zero.
        """
        if gap_bars_df.empty or overnight_range <= 0:
            return 0.0
        gap_high = gap_bars_df['high'].max()
        gap_low = gap_bars_df['low'].min()
        return (gap_high - gap_low) / overnight_range
