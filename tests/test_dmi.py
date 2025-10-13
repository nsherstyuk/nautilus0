import pytest
from decimal import Decimal

# Import Nautilus types as referenced (not strictly required for mock bars)
from nautilus_trader.model.data import Bar, BarType  # noqa: F401
from nautilus_trader.model.identifiers import InstrumentId  # noqa: F401
from nautilus_trader.model.objects import Price, Quantity  # noqa: F401
from nautilus_trader.test_kit.providers import TestDataProvider  # noqa: F401

from indicators.dmi import DMI


class _MockBar:
    """Lightweight bar-like object exposing high/low/close as floats."""

    def __init__(self, high: float, low: float, close: float) -> None:
        self.high = float(high)
        self.low = float(low)
        self.close = float(close)


@pytest.fixture
def sample_bars():
    # Uptrend (1-5)
    bars = [
        _MockBar(100, 99, 99.5),
        _MockBar(101, 100, 100.5),
        _MockBar(102, 101, 101.5),
        _MockBar(103, 102, 102.5),
        _MockBar(104, 103, 103.5),
    ]
    # Downtrend (6-10)
    bars += [
        _MockBar(104.5, 103.5, 104.0),
        _MockBar(104.0, 103.0, 103.5),
        _MockBar(103.0, 102.0, 102.5),
        _MockBar(102.0, 101.0, 101.5),
        _MockBar(101.0, 100.0, 100.5),
    ]
    # Ranging (11-15)
    bars += [
        _MockBar(101.0, 100.0, 100.5),
        _MockBar(100.5, 99.5, 100.0),
        _MockBar(101.0, 100.0, 100.5),
        _MockBar(100.5, 99.5, 100.0),
        _MockBar(101.0, 100.0, 100.5),
    ]
    # Extra bars (16-22)
    bars += [
        _MockBar(101.5, 100.5, 101.0),
        _MockBar(101.0, 100.0, 100.5),
        _MockBar(102.0, 101.0, 101.5),
        _MockBar(101.5, 100.5, 101.0),
        _MockBar(102.0, 101.0, 101.5),
        _MockBar(102.5, 101.5, 102.0),
        _MockBar(103.0, 102.0, 102.5),
    ]
    return bars


def test_dmi_initialization():
    dmi = DMI()
    assert dmi.period == 14
    assert dmi.name == "DMI(14)"
    assert dmi.has_inputs is False
    assert dmi.initialized is False
    assert dmi.plus_di == 0.0
    assert dmi.minus_di == 0.0
    assert dmi.is_bullish is False
    assert dmi.is_bearish is False


def test_dmi_custom_period(sample_bars):
    dmi = DMI(period=20)
    assert dmi.period == 20
    assert dmi.name == "DMI(20)"
    for bar in sample_bars[:19]:
        dmi.handle_bar(bar)
    assert dmi.initialized is False
    dmi.handle_bar(sample_bars[19])
    assert dmi.initialized is True


def test_dmi_invalid_period():
    with pytest.raises(ValueError):
        DMI(period=0)
    with pytest.raises(ValueError):
        DMI(period=-5)


def test_dmi_first_bar(sample_bars):
    dmi = DMI(period=14)
    dmi.handle_bar(sample_bars[0])
    assert dmi.has_inputs is True
    assert dmi.initialized is False
    assert dmi.plus_di == 0.0
    assert dmi.minus_di == 0.0
    assert dmi._prev_close is not None


def test_dmi_accumulation_phase(sample_bars):
    dmi = DMI(period=14)
    for bar in sample_bars[:13]:
        dmi.handle_bar(bar)
    assert dmi.has_inputs is True
    assert dmi.initialized is False
    assert dmi._count == 13
    assert len(dmi._plus_dm_buffer) == 12 or len(dmi._plus_dm_buffer) == 13
    assert dmi._smoothed_tr is None


def test_dmi_initialization_complete(sample_bars):
    dmi = DMI(period=14)
    for bar in sample_bars[:14]:
        dmi.handle_bar(bar)
    assert dmi.initialized is True
    assert dmi._count >= 14
    assert dmi._smoothed_tr is not None
    assert dmi._smoothed_plus_dm is not None
    assert dmi._smoothed_minus_dm is not None
    assert (dmi.plus_di != 0.0) or (dmi.minus_di != 0.0)
    assert len(dmi._tr_buffer) <= 14


def test_dmi_uptrend_detection():
    dmi = DMI(period=5)
    bars = [
        _MockBar(100, 99, 99.5),
        _MockBar(101, 100, 100.5),
        _MockBar(102, 101, 101.5),
        _MockBar(103, 102, 102.5),
        _MockBar(104, 103, 103.5),
        _MockBar(105, 104, 104.5),
    ]
    for i, b in enumerate(bars, start=1):
        dmi.handle_bar(b)
        if i >= 5:
            assert dmi.plus_di > dmi.minus_di
            assert dmi.is_bullish is True
            assert dmi.is_bearish is False


def test_dmi_downtrend_detection():
    dmi = DMI(period=5)
    bars = [
        _MockBar(105, 104, 104.5),
        _MockBar(104, 103, 103.5),
        _MockBar(103, 102, 102.5),
        _MockBar(102, 101, 101.5),
        _MockBar(101, 100, 100.5),
        _MockBar(100, 99, 99.5),
    ]
    for i, b in enumerate(bars, start=1):
        dmi.handle_bar(b)
        if i >= 5:
            assert dmi.minus_di > dmi.plus_di
            assert dmi.is_bearish is True
            assert dmi.is_bullish is False


def test_dmi_ranging_market():
    dmi = DMI(period=5)
    bars = [
        _MockBar(100, 99, 99.5),
        _MockBar(101, 100, 100.5),
        _MockBar(100, 99, 99.5),
        _MockBar(101, 100, 100.5),
        _MockBar(100, 99, 99.5),
        _MockBar(101, 100, 100.5),
    ]
    for b in bars:
        dmi.handle_bar(b)
    assert abs(dmi.plus_di - dmi.minus_di) < 10.0


def test_dmi_flat_market_zero_atr():
    dmi = DMI(period=5)
    bars = [_MockBar(100, 100, 100) for _ in range(6)]
    for b in bars:
        dmi.handle_bar(b)
    assert dmi.plus_di == 0.0
    assert dmi.minus_di == 0.0
    assert dmi._smoothed_tr == 0.0


def test_dmi_wilder_smoothing():
    dmi = DMI(period=3)
    bars = [
        _MockBar(100, 99, 99.5),
        _MockBar(102, 100, 101.0),  # +DM=2, TR approx 2
        _MockBar(103, 101, 102.0),  # +DM=1, TR approx 2
        _MockBar(104, 102, 103.0),  # +DM=1, TR approx 2
    ]
    # Feed first three (init)
    for b in bars[:3]:
        dmi.handle_bar(b)
    assert pytest.approx(dmi._smoothed_plus_dm or 0.0, rel=1e-6) == 3.0
    assert pytest.approx(dmi._smoothed_tr or 0.0, rel=1e-6) == 6.0

    # Next bar (smoothing)
    dmi.handle_bar(bars[3])
    assert pytest.approx(dmi._smoothed_plus_dm or 0.0, abs=0.01) == 3.0
    assert pytest.approx(dmi._smoothed_tr or 0.0, abs=0.01) == 6.0


def test_dmi_reset(sample_bars):
    dmi = DMI(period=5)
    for bar in sample_bars[:10]:
        dmi.handle_bar(bar)
    assert dmi.initialized is True
    prev_plus, prev_minus = dmi.plus_di, dmi.minus_di
    assert (prev_plus != 0.0) or (prev_minus != 0.0)

    dmi.reset()
    assert dmi.has_inputs is False
    assert dmi.initialized is False
    assert dmi.plus_di == 0.0
    assert dmi.minus_di == 0.0
    assert dmi._count == 0
    assert dmi._prev_close is None
    assert len(dmi._tr_buffer) == 0
    assert dmi._smoothed_tr is None


def test_dmi_value_property():
    dmi = DMI(period=5)
    bars = [
        _MockBar(100, 99, 99.5),
        _MockBar(101, 100, 100.5),
        _MockBar(102, 101, 101.5),
        _MockBar(103, 102, 102.5),
        _MockBar(104, 103, 103.5),
        _MockBar(105, 104, 104.5),
    ]
    for b in bars:
        dmi.handle_bar(b)
    assert dmi.value == dmi.plus_di


def test_dmi_handle_quote_tick():
    dmi = DMI(period=14)
    class _Tick:  # minimal tick placeholder
        pass
    dmi.handle_quote_tick(_Tick())
    assert dmi._count == 0


def test_dmi_handle_trade_tick():
    dmi = DMI(period=14)
    class _Tick:  # minimal tick placeholder
        pass
    dmi.handle_trade_tick(_Tick())
    assert dmi._count == 0


@pytest.mark.skip(reason="Reference values require external dataset/library; example only")
def test_dmi_known_values():
    dmi = DMI(period=14)
    # Placeholder for feeding reference bars matching TA-Lib/TradingView dataset
    # After feeding 14-15 bars, expected approx:
    # +DI ~ 25.3, -DI ~ 18.7 (bar 14)
    # +DI ~ 26.1, -DI ~ 17.9 (bar 15)
    assert True


