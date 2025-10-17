import math
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytest

from analysis.loss_patterns import (
    CHOPPY_MARKET_SEQUENCE_DURATION_SECONDS,
    FALSE_BREAKOUT_DURATION_SECONDS,
    TREND_EXHAUSTION_DURATION_SECONDS,
    calculate_duration_seconds,
    choppy_market_pattern,
    create_mock_orders_df,
    create_mock_position,
    detect_all_patterns,
    detect_stopped_out,
    detect_reversal,
    detect_false_breakout,
    detect_choppy_market,
    detect_trend_exhaustion,
    get_closing_order_details,
    get_dominant_pattern,
    has_tag,
    parse_order_tags,
    reversal_pattern,
    stopped_out_pattern,
    trend_exhaustion_pattern,
    validate_position_data,
    false_breakout_pattern,
)


# ---------------------
# Fixtures
# ---------------------
@pytest.fixture()
def sample_orders_df() -> pd.DataFrame:
    orders: List[Dict[str, Any]] = [
        {"venue_order_id": "SL-1", "tags": "MA_CROSS_SL", "status": "FILLED", "type": "STOP"},
        {"venue_order_id": "TP-1", "tags": "MA_CROSS_TP", "status": "FILLED", "type": "LIMIT"},
        {"venue_order_id": "ENTRY-1", "tags": "MA_CROSS", "status": "FILLED", "type": "MARKET"},
        {"venue_order_id": "MIXED-1", "tags": "MA_CROSS,MA_CROSS_SL", "status": "FILLED", "type": "MARKET"},
        {"venue_order_id": "PENDING-SL", "tags": "MA_CROSS_SL", "status": "SUBMITTED", "type": "STOP"},
        {"venue_order_id": "OTHER-1", "tags": "OTHER_TAG", "status": "FILLED", "type": "MARKET"},
    ]
    return create_mock_orders_df(orders)


@pytest.fixture()
def stopped_out_position() -> Dict[str, Any]:
    return {
        "duration_ns": 600 * 1_000_000_000,  # 10 minutes
        "realized_pnl": -50.0,
        "closing_order_id": "SL-1",
        "entry_time": pd.Timestamp("2025-10-01 10:00:00"),
    }


@pytest.fixture()
def reversal_position() -> Dict[str, Any]:
    return {
        "duration_ns": 1800 * 1_000_000_000,  # 30 minutes
        "realized_pnl": -30.0,
        "closing_order_id": "ENTRY-1",
        "entry_time": pd.Timestamp("2025-10-01 11:00:00"),
    }


@pytest.fixture()
def false_breakout_position() -> Dict[str, Any]:
    return {
        "duration_ns": 120 * 1_000_000_000,  # 2 minutes
        "realized_pnl": -25.0,
        "closing_order_id": "SL-1",
        "entry_time": pd.Timestamp("2025-10-01 12:00:00"),
    }


@pytest.fixture()
def trend_exhaustion_position() -> Dict[str, Any]:
    return {
        "duration_ns": 7200 * 1_000_000_000,  # 2 hours
        "realized_pnl": -10.0,
        "closing_order_id": "SL-1",
        "entry_time": pd.Timestamp("2025-10-01 13:00:00"),
    }


@pytest.fixture()
def loss_trades_sequence() -> List[Dict[str, Any]]:
    base = pd.Timestamp("2025-10-02 09:00:00")
    losses = []
    for i in range(5):
        losses.append({
            "entry_time": base + pd.Timedelta(minutes=10 * i),
            "realized_pnl": -10.0 - i,  # varying PnL
        })
    return losses


# ---------------------
# Helper function tests
# ---------------------
def test_parse_order_tags():
    assert parse_order_tags("MA_CROSS_SL") == ["MA_CROSS_SL"]
    assert parse_order_tags("MA_CROSS_SL,MA_CROSS") == ["MA_CROSS_SL", "MA_CROSS"]
    assert parse_order_tags("MA_CROSS_SL MA_CROSS") == ["MA_CROSS_SL", "MA_CROSS"]
    assert parse_order_tags("") == []
    assert parse_order_tags(None) == []


def test_has_tag():
    assert has_tag("MA_CROSS_SL", "MA_CROSS_SL") is True
    assert has_tag("MA_CROSS_SL", "MA_CROSS") is False  # boundary check
    assert has_tag("MA_CROSS,OTHER", "MA_CROSS") is True
    assert has_tag("PREFIX_MA_CROSS", "MA_CROSS") is False


def test_get_closing_order_details(sample_orders_df: pd.DataFrame):
    pos_valid = {"closing_order_id": "SL-1"}
    row = get_closing_order_details(pos_valid, sample_orders_df)
    assert row is not None
    assert row["venue_order_id"] == "SL-1"

    pos_invalid = {"closing_order_id": "NOPE"}
    assert get_closing_order_details(pos_invalid, sample_orders_df) is None

    pos_missing = {"other": 1}
    assert get_closing_order_details(pos_missing, sample_orders_df) is None


def test_calculate_duration_seconds():
    pos = {"duration_ns": 60 * 1_000_000_000}
    assert calculate_duration_seconds(pos) == 60.0
    pos_zero = {"duration_ns": 0}
    assert calculate_duration_seconds(pos_zero) == 0.0
    pos_missing = {}
    assert calculate_duration_seconds(pos_missing) == 0.0


def test_validate_position_data():
    pos_ok = {"a": 1, "b": 2}
    assert validate_position_data(pos_ok, ["a", "b"]) is True
    pos_missing = {"a": 1}
    assert validate_position_data(pos_missing, ["a", "b"]) is False
    pos_nan = {"a": 1, "b": float("nan")}
    assert validate_position_data(pos_nan, ["a", "b"]) is False


# ---------------------
# Stopped out tests
# ---------------------
def test_stopped_out_pattern_positive(stopped_out_position: Dict[str, Any], sample_orders_df: pd.DataFrame):
    matched, conf = stopped_out_pattern(stopped_out_position, sample_orders_df)
    assert matched is True and conf == 1.0


def test_stopped_out_pattern_negative_no_sl_tag(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 100 * 1_000_000_000, "realized_pnl": -20.0, "closing_order_id": "OTHER-1"}
    matched, conf = stopped_out_pattern(pos, sample_orders_df)
    assert matched is False and conf == 0.0


def test_stopped_out_pattern_negative_positive_pnl(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 100 * 1_000_000_000, "realized_pnl": 5.0, "closing_order_id": "SL-1"}
    matched, conf = stopped_out_pattern(pos, sample_orders_df)
    assert matched is False and conf == 0.0


def test_stopped_out_pattern_missing_closing_order(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 100 * 1_000_000_000, "realized_pnl": -5.0}
    matched, conf = stopped_out_pattern(pos, sample_orders_df)
    assert matched is False and conf == 0.0


def test_stopped_out_pattern_unfilled_order(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 100 * 1_000_000_000, "realized_pnl": -5.0, "closing_order_id": "PENDING-SL"}
    matched, conf = stopped_out_pattern(pos, sample_orders_df)
    assert matched is False and conf == 0.0


# ---------------------
# Reversal tests
# ---------------------
def test_reversal_pattern_positive(reversal_position: Dict[str, Any], sample_orders_df: pd.DataFrame):
    matched, conf = reversal_pattern(reversal_position, sample_orders_df)
    assert matched is True and conf == 1.0


def test_reversal_pattern_negative_sl_tag(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 100 * 1_000_000_000, "realized_pnl": -5.0, "closing_order_id": "SL-1"}
    matched, conf = reversal_pattern(pos, sample_orders_df)
    assert matched is False and conf == 0.0


def test_reversal_pattern_negative_tp_tag(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 100 * 1_000_000_000, "realized_pnl": -5.0, "closing_order_id": "TP-1"}
    matched, conf = reversal_pattern(pos, sample_orders_df)
    assert matched is False and conf == 0.0


def test_reversal_pattern_ambiguous_tags(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 100 * 1_000_000_000, "realized_pnl": -5.0, "closing_order_id": "MIXED-1"}
    matched, conf = reversal_pattern(pos, sample_orders_df)
    assert matched is False and conf == 0.0


# ---------------------
# False breakout tests
# ---------------------
def test_false_breakout_pattern_positive_high_confidence(false_breakout_position: Dict[str, Any], sample_orders_df: pd.DataFrame):
    matched, conf = false_breakout_pattern(false_breakout_position, sample_orders_df)
    assert matched is True and conf > 0.9


def test_false_breakout_pattern_positive_medium_confidence(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 150 * 1_000_000_000, "realized_pnl": -10.0, "closing_order_id": "SL-1"}
    matched, conf = false_breakout_pattern(pos, sample_orders_df)
    assert matched is True and 0.4 < conf < 0.6


def test_false_breakout_pattern_positive_low_confidence(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 290 * 1_000_000_000, "realized_pnl": -10.0, "closing_order_id": "SL-1"}
    matched, conf = false_breakout_pattern(pos, sample_orders_df)
    assert matched is True and conf < 0.1


def test_false_breakout_pattern_negative_long_duration(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 600 * 1_000_000_000, "realized_pnl": -10.0, "closing_order_id": "SL-1"}
    matched, conf = false_breakout_pattern(pos, sample_orders_df)
    assert matched is False and conf == 0.0


def test_false_breakout_pattern_negative_not_stopped_out(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 60 * 1_000_000_000, "realized_pnl": -10.0, "closing_order_id": "ENTRY-1"}
    matched, conf = false_breakout_pattern(pos, sample_orders_df)
    assert matched is False and conf == 0.0


def test_false_breakout_pattern_instant_stopout(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 0, "realized_pnl": -10.0, "closing_order_id": "SL-1"}
    matched, conf = false_breakout_pattern(pos, sample_orders_df)
    assert matched is True and conf == 1.0


# ---------------------
# Choppy market tests
# ---------------------
def test_choppy_market_pattern_positive_minimum_sequence(loss_trades_sequence: List[Dict[str, Any]]):
    current = {"entry_time": loss_trades_sequence[-1]["entry_time"], "realized_pnl": -5.0}
    matched, conf = choppy_market_pattern(loss_trades_sequence[:2], current)
    assert matched is True and conf >= 0.6


def test_choppy_market_pattern_positive_strong_sequence(loss_trades_sequence: List[Dict[str, Any]]):
    current = {"entry_time": loss_trades_sequence[-1]["entry_time"], "realized_pnl": -5.0}
    matched, conf = choppy_market_pattern(loss_trades_sequence, current)
    assert matched is True and conf >= 0.9


def test_choppy_market_pattern_negative_insufficient_losses(loss_trades_sequence: List[Dict[str, Any]]):
    current = {"entry_time": loss_trades_sequence[-1]["entry_time"], "realized_pnl": -5.0}
    matched, conf = choppy_market_pattern(loss_trades_sequence[:1], current)
    assert matched is False and conf == 0.0


def test_choppy_market_pattern_negative_losses_too_spread(loss_trades_sequence: List[Dict[str, Any]]):
    # Create 3 losses more than 2 hours apart
    base = pd.Timestamp("2025-10-02 00:00:00")
    seq = [
        {"entry_time": base, "realized_pnl": -5.0},
        {"entry_time": base + pd.Timedelta(hours=2, minutes=1), "realized_pnl": -5.0},
        {"entry_time": base + pd.Timedelta(hours=4, minutes=2), "realized_pnl": -5.0},
    ]
    current = {"entry_time": seq[-1]["entry_time"], "realized_pnl": -2.0}
    matched, conf = choppy_market_pattern(seq[:-1], current)
    assert matched is False and conf == 0.0


def test_choppy_market_no_double_count():
    # History includes current trade; ensure it is not double-counted
    t0 = pd.Timestamp("2025-10-02 00:00:00")
    loss_trades = [
        {"entry_time": t0, "realized_pnl": -5.0},
        {"entry_time": t0 + pd.Timedelta(minutes=10), "realized_pnl": -6.0},
    ]
    current = {"entry_time": t0 + pd.Timedelta(minutes=10), "realized_pnl": -7.0}
    matched, conf = choppy_market_pattern(loss_trades, current)
    assert matched is True


def test_choppy_market_pattern_confidence_adjustments():
    base = pd.Timestamp("2025-10-02 10:00:00")
    # Evenly distributed
    seq_even = [
        {"entry_time": base + pd.Timedelta(minutes=i * 20), "realized_pnl": -10.0}
        for i in range(2)
    ]
    current_even = {"entry_time": base + pd.Timedelta(minutes=60), "realized_pnl": -10.0}
    matched_even, conf_even = choppy_market_pattern(seq_even, current_even)
    assert matched_even is True and conf_even >= 0.6

    # Clustered
    seq_cluster = [
        {"entry_time": base + pd.Timedelta(minutes=i), "realized_pnl": -10.0}
        for i in range(2)
    ]
    current_cluster = {"entry_time": base + pd.Timedelta(minutes=2), "realized_pnl": -10.0}
    matched_cluster, conf_cluster = choppy_market_pattern(seq_cluster, current_cluster)
    assert matched_cluster is True and conf_cluster >= conf_even

    # Varying magnitudes
    seq_var = [
        {"entry_time": base + pd.Timedelta(minutes=10 * i), "realized_pnl": -10.0 * (i + 1)}
        for i in range(2)
    ]
    current_var = {"entry_time": base + pd.Timedelta(minutes=30), "realized_pnl": -50.0}
    matched_var, conf_var = choppy_market_pattern(seq_var, current_var)
    assert matched_var is True
    # Consistency should improve confidence compared to varying; create consistent set
    seq_consistent = [
        {"entry_time": base + pd.Timedelta(minutes=10 * i), "realized_pnl": -20.0}
        for i in range(2)
    ]
    current_consistent = {"entry_time": base + pd.Timedelta(minutes=30), "realized_pnl": -20.0}
    matched_consistent, conf_consistent = choppy_market_pattern(seq_consistent, current_consistent)
    assert matched_consistent is True and conf_consistent >= conf_var


def test_choppy_market_pattern_empty_history():
    current = {"entry_time": pd.Timestamp("2025-10-02 10:00:00"), "realized_pnl": -5.0}
    matched, conf = choppy_market_pattern([], current)
    assert matched is False and conf == 0.0


# ---------------------
# Trend exhaustion tests
# ---------------------
def test_trend_exhaustion_pattern_positive_with_history(trend_exhaustion_position: Dict[str, Any], sample_orders_df: pd.DataFrame):
    history = [
        {"realized_pnl": -50.0},
        {"realized_pnl": -60.0},
        {"realized_pnl": -55.0},
    ]
    matched, conf = trend_exhaustion_pattern(trend_exhaustion_position, sample_orders_df, history)
    assert matched is True and conf > 0.5


def test_trend_exhaustion_pattern_positive_without_history(trend_exhaustion_position: Dict[str, Any], sample_orders_df: pd.DataFrame):
    matched, conf = trend_exhaustion_pattern(trend_exhaustion_position, sample_orders_df)
    assert matched is True and conf > 0.5


def test_trend_exhaustion_pattern_negative_short_duration(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 30 * 60 * 1_000_000_000, "realized_pnl": -10.0}
    matched, conf = trend_exhaustion_pattern(pos, sample_orders_df)
    assert matched is False and conf == 0.0


def test_trend_exhaustion_pattern_negative_large_loss(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 2 * 3600 * 1_000_000_000, "realized_pnl": -100.0}
    history = [{"realized_pnl": -50.0}]
    matched, conf = trend_exhaustion_pattern(pos, sample_orders_df, history)
    assert (matched is False and conf == 0.0) or (matched is True and conf <= 0.25)


def test_trend_exhaustion_pattern_confidence_gradient(sample_orders_df: pd.DataFrame):
    def mk(duration_s: int) -> Dict[str, Any]:
        return {"duration_ns": duration_s * 1_000_000_000, "realized_pnl": -10.0}

    m1 = trend_exhaustion_pattern(mk(3600), sample_orders_df)[1]
    m2 = trend_exhaustion_pattern(mk(7200), sample_orders_df)[1]
    m3 = trend_exhaustion_pattern(mk(10800), sample_orders_df)[1]
    assert m1 <= m2 <= m3


# ---------------------
# Composite functions
# ---------------------
def test_detect_all_patterns(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 60 * 1_000_000_000, "realized_pnl": -10.0, "closing_order_id": "SL-1", "entry_time": pd.Timestamp("2025-10-02 11:00:00")}
    results = detect_all_patterns(pos, sample_orders_df, [])
    assert set(results.keys()) == {"stopped_out", "reversal", "false_breakout", "choppy_market", "trend_exhaustion"}
    for v in results.values():
        assert isinstance(v, tuple) and isinstance(v[0], bool) and isinstance(v[1], float)
    assert any(ok for ok, _ in results.values())


def test_get_dominant_pattern_single_match():
    res = {
        "stopped_out": (True, 1.0),
        "reversal": (False, 0.0),
        "false_breakout": (False, 0.0),
        "choppy_market": (False, 0.0),
        "trend_exhaustion": (False, 0.0),
    }
    assert get_dominant_pattern(res) == "stopped_out"


def test_get_dominant_pattern_multiple_matches():
    res = {
        "stopped_out": (True, 0.8),
        "reversal": (True, 1.0),
        "false_breakout": (True, 0.5),
        "choppy_market": (False, 0.0),
        "trend_exhaustion": (True, 0.1),
    }
    assert get_dominant_pattern(res) == "reversal"


def test_get_dominant_pattern_no_matches():
    res = {k: (False, 0.0) for k in ["stopped_out", "reversal", "false_breakout", "choppy_market", "trend_exhaustion"]}
    assert get_dominant_pattern(res) is None


# ---------------------
# Edge cases
# ---------------------
def test_pattern_detection_with_series_input(sample_orders_df: pd.DataFrame):
    series_pos = pd.Series({
        "duration_ns": 120 * 1_000_000_000,
        "realized_pnl": -10.0,
        "closing_order_id": "SL-1",
        "entry_time": pd.Timestamp("2025-10-02 12:00:00"),
    })
    assert stopped_out_pattern(series_pos, sample_orders_df)[0] is True
    assert reversal_pattern(series_pos, sample_orders_df)[0] is False
    assert false_breakout_pattern(series_pos, sample_orders_df)[0] is True


def test_order_lookup_fallback_order_id():
    # Only order_id column present
    orders = pd.DataFrame([
        {"order_id": "X-1", "tags": "MA_CROSS_SL", "status": "FILLED", "type": "STOP"}
    ])
    pos = {"closing_order_id": "X-1"}
    row = get_closing_order_details(pos, orders)
    assert row is not None and row.get("order_id") == "X-1"


def test_wrapper_api_interfaces(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 60 * 1_000_000_000, "realized_pnl": -10.0, "closing_order_id": "SL-1", "entry_time": pd.Timestamp("2025-10-02 11:00:00")}
    bars = pd.DataFrame({
        "timestamp": [pd.Timestamp("2025-10-02 10:59:00"), pd.Timestamp("2025-10-02 11:00:00")],
        "open": [1.0, 1.0],
        "high": [1.01, 1.01],
        "low": [0.99, 0.99],
        "close": [1.0, 0.995],
    })
    ctx = {"orders_df": sample_orders_df, "loss_trades": [], "bars": bars, "min_loss_magnitude": 0.0}
    assert isinstance(detect_stopped_out(pos, ctx), tuple)
    assert isinstance(detect_reversal(pos, ctx), tuple)
    assert isinstance(detect_false_breakout(pos, ctx), tuple)
    assert isinstance(detect_choppy_market(pos, ctx), tuple)
    assert isinstance(detect_trend_exhaustion(pos, ctx), tuple)


def test_false_breakout_uses_bars_and_prices(sample_orders_df: pd.DataFrame):
    # Short duration stopout, with small SL distance vs bar range should boost confidence
    pos = {"duration_ns": 60 * 1_000_000_000, "realized_pnl": -10.0, "closing_order_id": "SL-1", "entry_price": 1.0000, "exit_price": 0.9998}
    bars = pd.DataFrame({
        "high": [1.002, 1.003, 1.004],
        "low": [0.998, 0.997, 0.996],
        "close": [1.001, 1.002, 0.999],
    })
    m0, c0 = false_breakout_pattern(pos, sample_orders_df)
    m1, c1 = false_breakout_pattern(pos, sample_orders_df, bars=bars)
    assert m0 and m1 and c1 >= c0


def test_pattern_detection_with_missing_fields(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 60 * 1_000_000_000}
    for fn in [stopped_out_pattern, reversal_pattern, false_breakout_pattern, trend_exhaustion_pattern]:
        matched, conf = fn(pos, sample_orders_df)
        assert matched is False and conf == 0.0


def test_pattern_detection_with_nan_values(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": float("nan"), "realized_pnl": float("nan"), "closing_order_id": None}
    for fn in [stopped_out_pattern, reversal_pattern, false_breakout_pattern, trend_exhaustion_pattern]:
        matched, conf = fn(pos, sample_orders_df)
        assert matched is False and conf == 0.0


def test_pattern_detection_with_zero_values(sample_orders_df: pd.DataFrame):
    pos = {"duration_ns": 0, "realized_pnl": 0.0, "closing_order_id": "SL-1", "entry_time": pd.Timestamp("2025-10-02 12:00:00")}
    # stopped_out requires negative PnL above min magnitude
    assert stopped_out_pattern(pos, sample_orders_df) == (False, 0.0)
    # false breakout requires stopped out
    assert false_breakout_pattern(pos, sample_orders_df) == (False, 0.0)


def test_confidence_score_bounds(sample_orders_df: pd.DataFrame):
    positions = [
        {"duration_ns": 0, "realized_pnl": -1.0, "closing_order_id": "SL-1", "entry_time": pd.Timestamp("2025-10-02 12:00:00")},
        {"duration_ns": 10 * 1_000_000_000, "realized_pnl": -100.0, "closing_order_id": "SL-1", "entry_time": pd.Timestamp("2025-10-02 12:10:00")},
        {"duration_ns": 600 * 1_000_000_000, "realized_pnl": -10.0, "closing_order_id": "SL-1", "entry_time": pd.Timestamp("2025-10-02 12:20:00")},
    ]
    for pos in positions:
        results = detect_all_patterns(pos, sample_orders_df, positions)
        for ok, conf in results.values():
            assert 0.0 <= conf <= 1.0


# ---------------------
# Integration tests
# ---------------------
def test_pattern_detection_workflow(sample_orders_df: pd.DataFrame):
    positions = [
        {"duration_ns": 30 * 1_000_000_000, "realized_pnl": -5.0, "closing_order_id": "SL-1", "entry_time": pd.Timestamp("2025-10-02 10:00:00")},
        {"duration_ns": 150 * 1_000_000_000, "realized_pnl": -15.0, "closing_order_id": "SL-1", "entry_time": pd.Timestamp("2025-10-02 10:10:00")},
        {"duration_ns": 4000 * 1_000_000_000, "realized_pnl": -10.0, "closing_order_id": "SL-1", "entry_time": pd.Timestamp("2025-10-02 10:20:00")},
    ]
    for pos in positions:
        res = detect_all_patterns(pos, sample_orders_df, positions)
        dom = get_dominant_pattern(res)
        assert isinstance(dom, (str, type(None)))


def test_pattern_detection_performance(sample_orders_df: pd.DataFrame):
    base = pd.Timestamp("2025-10-02 00:00:00")
    positions = []
    for i in range(1000):
        positions.append({
            "duration_ns": (60 + (i % 600)) * 1_000_000_000,
            "realized_pnl": -float((i % 50) + 1),
            "closing_order_id": "SL-1" if i % 2 == 0 else "ENTRY-1",
            "entry_time": base + pd.Timedelta(seconds=i * 30),
        })

    # Run detection; we don't assert runtime but expect it to be fast.
    results = [detect_all_patterns(p, sample_orders_df, positions) for p in positions]
    assert len(results) == len(positions)


# ---------------------
# Bars-driven adjustments tests
# ---------------------
def test_reversal_pattern_uses_bars_momentum(sample_orders_df: pd.DataFrame):
    # LONG losing position closed by ENTRY-1 with downward momentum
    pos_long = {
        "duration_ns": 1800 * 1_000_000_000,
        "realized_pnl": -20.0,
        "closing_order_id": "ENTRY-1",
        "entry_time": pd.Timestamp("2025-10-03 10:00:00"),
        "side": "LONG",
    }
    bars_down = pd.DataFrame({
        "timestamp": [
            pd.Timestamp("2025-10-03 09:55:00"),
            pd.Timestamp("2025-10-03 09:56:00"),
            pd.Timestamp("2025-10-03 09:57:00"),
            pd.Timestamp("2025-10-03 09:58:00"),
            pd.Timestamp("2025-10-03 09:59:00"),
            pd.Timestamp("2025-10-03 10:00:00"),
        ],
        "close": [1.0100, 1.0090, 1.0080, 1.0070, 1.0060, 1.0050],
    })
    m0, c0 = reversal_pattern(pos_long, sample_orders_df)
    m1, c1 = reversal_pattern(pos_long, sample_orders_df, bars=bars_down)
    assert m0 is True and m1 is True
    assert 0.0 <= c0 <= 1.0 and 0.0 <= c1 <= 1.0
    assert c1 >= c0  # momentum aligns with LONG loss (down), no worse than baseline

    # SHORT losing position closed by ENTRY-1 with upward momentum
    pos_short = {
        "duration_ns": 1800 * 1_000_000_000,
        "realized_pnl": -15.0,
        "closing_order_id": "ENTRY-1",
        "entry_time": pd.Timestamp("2025-10-03 11:00:00"),
        "side": "SHORT",
    }
    bars_up = pd.DataFrame({
        "timestamp": [
            pd.Timestamp("2025-10-03 10:55:00"),
            pd.Timestamp("2025-10-03 10:56:00"),
            pd.Timestamp("2025-10-03 10:57:00"),
            pd.Timestamp("2025-10-03 10:58:00"),
            pd.Timestamp("2025-10-03 10:59:00"),
            pd.Timestamp("2025-10-03 11:00:00"),
        ],
        "close": [1.0000, 1.0010, 1.0020, 1.0030, 1.0040, 1.0050],
    })
    m2, c2 = reversal_pattern(pos_short, sample_orders_df)
    m3, c3 = reversal_pattern(pos_short, sample_orders_df, bars=bars_up)
    assert m2 is True and m3 is True
    assert 0.0 <= c2 <= 1.0 and 0.0 <= c3 <= 1.0
    assert c3 >= c2


def test_choppy_market_pattern_uses_bars_volatility():
    # Construct minimal sequence: 2 recent losses + current loss within window
    base = pd.Timestamp("2025-10-04 09:00:00")
    loss_trades = [
        {"entry_time": base + pd.Timedelta(minutes=0), "realized_pnl": -5.0},
        {"entry_time": base + pd.Timedelta(minutes=10), "realized_pnl": -6.0},
    ]
    current = {"entry_time": base + pd.Timedelta(minutes=20), "realized_pnl": -7.0}
    # Baseline without bars
    m0, c0 = choppy_market_pattern(loss_trades, current)
    assert m0 is True
    assert 0.0 <= c0 <= 1.0

    # Bars window with elevated high-low ranges
    bars = pd.DataFrame({
        "timestamp": [
            base + pd.Timedelta(minutes=15),
            base + pd.Timedelta(minutes=16),
            base + pd.Timedelta(minutes=17),
            base + pd.Timedelta(minutes=18),
            base + pd.Timedelta(minutes=19),
            base + pd.Timedelta(minutes=20),
        ],
        "high": [1.020, 1.022, 1.025, 1.024, 1.026, 1.028],
        "low":  [0.980, 0.978, 0.975, 0.976, 0.974, 0.972],
        "close": [1.000, 1.005, 1.010, 1.008, 1.012, 1.015],
    })
    m1, c1 = choppy_market_pattern(loss_trades, current, bars=bars)
    assert m1 is True
    assert 0.0 <= c1 <= 1.0
    assert c1 >= c0  # volatility-based adjustment should not reduce confidence


