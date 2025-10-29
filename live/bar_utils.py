from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


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
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }


class BarAggregator:
    """Simple mid-price bar aggregator aligned to wall-clock boundaries."""

    def __init__(self, seconds: int) -> None:
        self.seconds = int(seconds)
        self._current: Optional[Bar] = None
        self._completed: List[Bar] = []

    def _bucket_start(self, ts: datetime) -> datetime:
        ts0 = ts.replace(microsecond=0)
        base = ts0.replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_since_midnight = int((ts0 - base).total_seconds())
        start_seconds = (seconds_since_midnight // self.seconds) * self.seconds
        return base + timedelta(seconds=start_seconds)

    def add_tick(self, ts: datetime, bid: Optional[float], ask: Optional[float]) -> None:
        if bid is None or ask is None:
            return

        mid = (float(bid) + float(ask)) / 2.0
        start = self._bucket_start(ts)
        end = start + timedelta(seconds=self.seconds)

        if self._current and ts >= self._current.end:
            self._completed.append(self._current)
            self._current = None

        if not self._current:
            self._current = Bar(start=start, end=end, open=mid, high=mid, low=mid, close=mid)
        else:
            self._current.high = max(self._current.high, mid)
            self._current.low = min(self._current.low, mid)
            self._current.close = mid

    def drain_completed(self) -> List[Bar]:
        drained = self._completed
        self._completed = []
        return drained

    def finalize(self) -> List[Bar]:
        if self._current is not None:
            self._completed.append(self._current)
            self._current = None
        return self.drain_completed()


def timeframe_to_seconds(bar_spec: str) -> int:
    """Extract aggregation seconds from Nautilus-style bar spec."""
    spec = bar_spec.split("-")[0].strip().lower()
    mapping = {
        "30": 30,
        "30s": 30,
        "1": 60,
        "1m": 60,
        "2": 120,
        "2m": 120,
        "3": 180,
        "3m": 180,
        "5": 300,
        "5m": 300,
        "15": 900,
        "15m": 900,
    }
    if spec not in mapping:
        raise ValueError(f"Unsupported bar_spec prefix: '{bar_spec}'")
    return mapping[spec]
