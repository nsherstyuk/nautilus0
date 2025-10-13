from collections import deque
from typing import Optional

from nautilus_trader.indicators import Indicator
from nautilus_trader.model.data import Bar


class DMI(Indicator):
    """
    Directional Movement Index (DMI) indicator using Wilder's method.

    Calculates +DI and -DI values based on smoothed directional movement and
    true range. The primary value returned by `value` is +DI.

    Parameters
    ----------
    period : int, default 14
        The smoothing period for Wilder's RMA (RWMA).

    Properties
    ----------
    plus_di : float
        The current +DI value (0-100 scale).
    minus_di : float
        The current -DI value (0-100 scale).
    is_bullish : bool
        True if +DI > -DI and the indicator is initialized.
    is_bearish : bool
        True if -DI > +DI and the indicator is initialized.
    """

    def __init__(self, period: int = 14) -> None:
        if period <= 0:
            raise ValueError("period must be > 0")

        # NautilusTrader Indicator base expects list of params
        super().__init__([period])

        self.period: int = period

        # Initial accumulation buffers (first `period` bars)
        self._plus_dm_buffer: deque[float] = deque(maxlen=period)
        self._minus_dm_buffer: deque[float] = deque(maxlen=period)
        self._tr_buffer: deque[float] = deque(maxlen=period)

        # Smoothed values after initialization
        self._smoothed_plus_dm: Optional[float] = None
        self._smoothed_minus_dm: Optional[float] = None
        self._smoothed_tr: Optional[float] = None

        # Outputs
        self._plus_di: float = 0.0
        self._minus_di: float = 0.0

        # State tracking
        self._count: int = 0
        self._prev_high: Optional[float] = None
        self._prev_low: Optional[float] = None
        self._prev_close: Optional[float] = None

    def handle_bar(self, bar: Bar) -> None:
        high = float(bar.high)
        low = float(bar.low)
        close = float(bar.close)

        # First bar: store and return
        if self._prev_close is None:
            self._prev_high = high
            self._prev_low = low
            self._prev_close = close
            self._count = 1 if self._count == 0 else self._count
            return

        # Calculate raw DM and TR
        up_move = high - (self._prev_high if self._prev_high is not None else high)
        down_move = (self._prev_low if self._prev_low is not None else low) - low

        plus_dm = up_move if (up_move > down_move and up_move > 0.0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0.0) else 0.0

        tr1 = high - low
        tr2 = abs(high - (self._prev_close if self._prev_close is not None else close))
        tr3 = abs(low - (self._prev_close if self._prev_close is not None else close))
        tr = max(tr1, tr2, tr3)

        # Accumulation phase (fewer than `period` values collected)
        if self._count < self.period:
            self._plus_dm_buffer.append(plus_dm)
            self._minus_dm_buffer.append(minus_dm)
            self._tr_buffer.append(tr)

            self._count += 1

            if self._count == self.period:
                # Initialize smoothed sums
                self._smoothed_plus_dm = float(sum(self._plus_dm_buffer))
                self._smoothed_minus_dm = float(sum(self._minus_dm_buffer))
                self._smoothed_tr = float(sum(self._tr_buffer))
                self._calculate_di_values()
        else:
            # Smoothing phase
            # smoothed[t] = smoothed[t-1] - smoothed[t-1]/n + raw[t]
            assert self._smoothed_plus_dm is not None
            assert self._smoothed_minus_dm is not None
            assert self._smoothed_tr is not None

            self._smoothed_plus_dm = (
                self._smoothed_plus_dm - (self._smoothed_plus_dm / self.period) + plus_dm
            )
            self._smoothed_minus_dm = (
                self._smoothed_minus_dm - (self._smoothed_minus_dm / self.period) + minus_dm
            )
            self._smoothed_tr = self._smoothed_tr - (self._smoothed_tr / self.period) + tr

            self._calculate_di_values()
            self._count += 1

        # Update previous bar values
        self._prev_high = high
        self._prev_low = low
        self._prev_close = close

    def _calculate_di_values(self) -> None:
        if self._smoothed_tr is None or self._smoothed_tr == 0.0:
            self._plus_di = 0.0
            self._minus_di = 0.0
            return

        # Scale to 0-100
        self._plus_di = 100.0 * (
            (self._smoothed_plus_dm if self._smoothed_plus_dm is not None else 0.0)
            / self._smoothed_tr
        )
        self._minus_di = 100.0 * (
            (self._smoothed_minus_dm if self._smoothed_minus_dm is not None else 0.0)
            / self._smoothed_tr
        )

    def handle_quote_tick(self, tick) -> None:  # noqa: D401 - no-op
        # DMI only uses bar data
        pass

    def handle_trade_tick(self, tick) -> None:  # noqa: D401 - no-op
        # DMI only uses bar data
        pass

    def reset(self) -> None:
        self._plus_dm_buffer.clear()
        self._minus_dm_buffer.clear()
        self._tr_buffer.clear()

        self._smoothed_plus_dm = None
        self._smoothed_minus_dm = None
        self._smoothed_tr = None

        self._plus_di = 0.0
        self._minus_di = 0.0

        self._count = 0
        self._prev_high = None
        self._prev_low = None
        self._prev_close = None

    @property
    def name(self) -> str:
        return f"DMI({self.period})"

    @property
    def has_inputs(self) -> bool:
        return self._count > 0

    @property
    def initialized(self) -> bool:
        # Indicator is considered ready after `period` bars
        return self._count >= self.period

    @property
    def value(self) -> float:
        # Return +DI as primary value
        return self._plus_di

    @property
    def plus_di(self) -> float:
        return self._plus_di

    @property
    def minus_di(self) -> float:
        return self._minus_di

    @property
    def is_bullish(self) -> bool:
        return (self._plus_di > self._minus_di) if self.initialized else False

    @property
    def is_bearish(self) -> bool:
        return (self._minus_di > self._plus_di) if self.initialized else False


