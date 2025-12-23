from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Deque, Tuple
from collections import deque


def _safe_float(x: object, default: float = float("nan")) -> float:
    try:
        return float(x)
    except Exception:
        return default


def candle_body_wicks(open_: float, high: float, low: float, close: float) -> Tuple[float, float, float]:
    """Return (body, upper_wick, lower_wick) in price units."""
    body = abs(close - open_)
    upper = max(0.0, high - max(open_, close))
    lower = max(0.0, min(open_, close) - low)
    return body, upper, lower


class Ema:
    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be > 0")
        self.period = period
        self.alpha = 2.0 / (period + 1.0)
        self.value: Optional[float] = None

    def update(self, x: float) -> float:
        if self.value is None:
            self.value = x
        else:
            self.value = self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value


class Atr:
    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._ema = Ema(period)
        self._prev_close: Optional[float] = None
        self.value: Optional[float] = None

    def update(self, high: float, low: float, close: float) -> float:
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        self.value = self._ema.update(tr)
        return self.value


class Rsi:
    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._ema_gain = Ema(period)
        self._ema_loss = Ema(period)
        self._prev: Optional[float] = None
        self.value: Optional[float] = None

    def update(self, close: float) -> float:
        if self._prev is None:
            self._prev = close
            self.value = 50.0
            return self.value

        change = close - self._prev
        self._prev = close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        avg_gain = self._ema_gain.update(gain)
        avg_loss = self._ema_loss.update(loss)

        if avg_loss == 0.0:
            self.value = 100.0
            return self.value

        rs = avg_gain / avg_loss
        self.value = 100.0 - (100.0 / (1.0 + rs))
        return self.value


class Macd:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.ema_fast = Ema(fast)
        self.ema_slow = Ema(slow)
        self.ema_signal = Ema(signal)
        self.macd: Optional[float] = None
        self.signal: Optional[float] = None
        self.hist: Optional[float] = None

    def update(self, close: float) -> Tuple[float, float, float]:
        fast_v = self.ema_fast.update(close)
        slow_v = self.ema_slow.update(close)
        self.macd = fast_v - slow_v
        self.signal = self.ema_signal.update(self.macd)
        self.hist = self.macd - self.signal
        return self.macd, self.signal, self.hist


class BollingerWidth:
    def __init__(self, period: int = 20, num_std: float = 2.0) -> None:
        self.period = period
        self.num_std = num_std
        self._window: Deque[float] = deque(maxlen=period)
        self.width: Optional[float] = None

    def update(self, close: float) -> float:
        self._window.append(close)
        if len(self._window) < self.period:
            self.width = float("nan")
            return self.width

        mean = sum(self._window) / float(self.period)
        var = sum((x - mean) ** 2 for x in self._window) / float(self.period)
        std = var ** 0.5
        upper = mean + self.num_std * std
        lower = mean - self.num_std * std

        if mean == 0.0:
            self.width = float("nan")
        else:
            self.width = (upper - lower) / abs(mean)

        return self.width


@dataclass
class SoldierIndicators:
    rsi: Rsi
    macd: Macd
    bb_width: BollingerWidth


def make_default_soldier_indicators() -> SoldierIndicators:
    return SoldierIndicators(
        rsi=Rsi(period=14),
        macd=Macd(fast=12, slow=26, signal=9),
        bb_width=BollingerWidth(period=20, num_std=2.0),
    )
