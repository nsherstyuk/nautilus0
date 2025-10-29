from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any


@dataclass
class Bar:
    start: datetime
    end: datetime
    open: float
    high: float
    low: float
    close: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            # Name/index will be set by caller using `end` as timestamp
        }


class BarAggregator:
    """
    Generic mid-price bar aggregator aligned to wall-clock boundaries.
    Call `add_tick(ts, bid, ask)` for every tick. When a bar completes,
    it will be returned from `drain_completed()`.

    seconds: bar length in seconds (e.g., 30, 60, 120, 180, 300)
    name: human-readable timeframe string (e.g., '30s', '1m')
    """

    def __init__(self, seconds: int, name: Optional[str] = None) -> None:
        self.seconds = int(seconds)
        self.name = name or f"{int(seconds)}s"
        self._current: Optional[Bar] = None
        self._completed: List[Bar] = []

    def _bucket_start(self, ts: datetime) -> datetime:
        # Align to lower boundary of `self.seconds` using seconds since midnight
        ts0 = ts.replace(microsecond=0)
        base = ts0.replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_since_midnight = int((ts0 - base).total_seconds())
        start_seconds = (seconds_since_midnight // self.seconds) * self.seconds
        return base + timedelta(seconds=start_seconds)

    def add_tick(self, ts: datetime, bid: float, ask: float) -> None:
        if bid is None or ask is None:
            return
        mid = (float(bid) + float(ask)) / 2.0
        start = self._bucket_start(ts)
        end = start + timedelta(seconds=self.seconds)

        # If we have an existing bar and we've crossed into a new bucket, finalize it
        if self._current and ts >= self._current.end:
            self._completed.append(self._current)
            self._current = None

        # Initialize current bar if needed; otherwise update extremes/close
        if not self._current:
            self._current = Bar(start=start, end=end, open=mid, high=mid, low=mid, close=mid)
        else:
            self._current.high = max(self._current.high, mid)
            self._current.low = min(self._current.low, mid)
            self._current.close = mid

    def drain_completed(self) -> List[Bar]:
        bars = self._completed
        self._completed = []
        return bars

    def finalize(self) -> List[Bar]:
        """
        Flush the current in-progress bar (if any) into the completed list and
        return drained bars. Useful at end-of-stream to ensure the last partial
        bucket is processed.
        """
        if self._current is not None:
            self._completed.append(self._current)
            self._current = None
        return self.drain_completed()


class BarAggregator30s(BarAggregator):
    """Backward-compatible 30-second aggregator."""
    def __init__(self) -> None:
        super().__init__(seconds=30, name='30s')


def normalize_timeframe(tf: Optional[str]) -> str:
    """Normalize timeframe aliases to one of: '30s','1m','2m','3m','5m'. Defaults to '30s'."""
    if not tf:
        return '30s'
    s = str(tf).strip().lower()
    alias_map = {
        '30s': '30s', '30sec': '30s', '30': '30s',
        '1m': '1m', '1min': '1m', '1t': '1m', '60s': '1m', '60': '1m',
        '2m': '2m', '2min': '2m', '2t': '2m', '120s': '2m', '120': '2m',
        '3m': '3m', '3min': '3m', '3t': '3m', '180s': '3m', '180': '3m',
        '5m': '5m', '5min': '5m', '5t': '5m', '300s': '5m', '300': '5m',
    }
    return alias_map.get(s, '30s')


def timeframe_to_seconds(tf: Optional[str]) -> int:
    ntf = normalize_timeframe(tf)
    return {
        '30s': 30,
        '1m': 60,
        '2m': 120,
        '3m': 180,
        '5m': 300,
    }[ntf]


def make_aggregator(tf: Optional[str]) -> BarAggregator:
    ntf = normalize_timeframe(tf)
    secs = timeframe_to_seconds(ntf)
    return BarAggregator(seconds=secs, name=ntf)
