"""
Reusable loss pattern detection module for analyzing losing trades.

This module provides pure, side-effect-free detector functions that analyze
position and order data to identify common loss patterns and produce a
confidence score for each detection.

Patterns implemented:
- stopped_out: Position closed by a stop-loss order (MA_CROSS_SL)
- reversal: Position closed by an opposite-direction entry (MA_CROSS without _SL/_TP)
- false_breakout: Quick stop-loss hits (short duration leading to SL)
- choppy_market: Multiple consecutive losses within a short time window
- trend_exhaustion: Long-duration trades ending with relatively small losses

All detector functions return Tuple[bool, float] where:
- bool indicates whether the pattern matched
- float is a confidence score in the range [0.0, 1.0]

Example usage:
    from analysis.loss_patterns import (
        stopped_out_pattern,
        reversal_pattern,
        false_breakout_pattern,
        choppy_market_pattern,
        trend_exhaustion_pattern,
        detect_all_patterns,
        get_dominant_pattern,
    )

    pattern_results = detect_all_patterns(position_data, orders_df, loss_history)
    dominant = get_dominant_pattern(pattern_results)

The functions accept pandas Series or plain dicts for `position_data` and
loss trade items.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# Constants extracted and defined for pattern detection
FALSE_BREAKOUT_DURATION_SECONDS: int = 300  # 5 minutes
TREND_EXHAUSTION_DURATION_SECONDS: int = 3600  # 1 hour
CHOPPY_MARKET_SEQUENCE_DURATION_SECONDS: int = 7200  # 2 hours
CHOPPY_MARKET_MIN_SEQUENCE_LENGTH: int = 3

# Additional constants
CONFIDENCE_GRADIENT_DURATION_SECONDS: int = 300
# Default minimum loss magnitude threshold (configurable via wrapper/context)
MIN_LOSS_MAGNITUDE_FOR_PATTERN: float = 0.0


# -----------------------------
# Helper utility functions
# -----------------------------
def parse_order_tags(tags: Optional[str]) -> List[str]:
    """
    Parse a comma- and/or space-separated tags string into a list of tags.

    Examples:
        "MA_CROSS_SL" -> ["MA_CROSS_SL"]
        "MA_CROSS_SL,MA_CROSS" -> ["MA_CROSS_SL", "MA_CROSS"]
        "MA_CROSS_SL MA_CROSS" -> ["MA_CROSS_SL", "MA_CROSS"]
        "" or None -> []
    """
    if not tags:
        return []
    # Replace commas with spaces, split, and strip
    parts = [p.strip() for p in re.split(r"[\s,]+", str(tags)) if p and p.strip()]
    return parts


def has_tag(tags: Optional[str], tag_pattern: str) -> bool:
    """
    Check if `tags` contains a specific tag using word boundaries to avoid
    partial matches (e.g., MA_CROSS shouldn't match MA_CROSS_SL).
    """
    if not tags:
        return False
    # Build boundary-aware regex: (^|,|space)TAG($|,|space)
    pattern = rf"(?:(?<=^)|(?<=\s)|(?<=,)){re.escape(tag_pattern)}(?=$|\s|,)"
    return re.search(pattern, str(tags)) is not None


def _as_mapping(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, pd.Series):
        return obj.to_dict()
    if isinstance(obj, dict):
        return obj
    # Fallback: try attribute access
    try:
        return dict(obj)
    except Exception:
        return {}


def get_closing_order_details(
    position_data: Any, orders_df: pd.DataFrame
) -> Optional[pd.Series]:
    """
    Look up the closing order row from `orders_df` by `closing_order_id` in the
    `venue_order_id` column. Returns None if not found or missing.
    """
    pos = _as_mapping(position_data)
    closing_order_id = pos.get("closing_order_id")
    if closing_order_id is None or (isinstance(closing_order_id, float) and np.isnan(closing_order_id)):
        return None
    if orders_df is None or orders_df.empty:
        return None
    # Case-insensitive presence for columns
    cols_lower = {c.lower(): c for c in orders_df.columns}
    venue_col = cols_lower.get("venue_order_id")
    order_col = cols_lower.get("order_id")
    # Try venue_order_id first
    if venue_col in orders_df.columns:
        matches = orders_df[orders_df[venue_col] == closing_order_id]
        if not matches.empty:
            return matches.iloc[0]
    # Fallback to order_id
    if order_col in orders_df.columns:
        matches2 = orders_df[orders_df[order_col] == closing_order_id]
        if not matches2.empty:
            return matches2.iloc[0]
    return None


def calculate_duration_seconds(position_data: Any) -> float:
    """
    Convert `duration_ns` in the position to seconds. Returns 0.0 if missing.
    """
    pos = _as_mapping(position_data)
    duration_ns = pos.get("duration_ns")
    try:
        if duration_ns is None or (isinstance(duration_ns, float) and np.isnan(duration_ns)):
            return 0.0
        return float(duration_ns) / 1_000_000_000.0
    except Exception:
        return 0.0


def validate_position_data(position_data: Any, required_fields: List[str]) -> bool:
    """
    Validate that all required fields exist and are not NaN/None.
    Works for dicts and pandas Series.
    """
    pos = _as_mapping(position_data)
    for field in required_fields:
        if field not in pos:
            return False
        val = pos.get(field)
        if val is None:
            return False
        if isinstance(val, float) and np.isnan(val):
            return False
    return True


# -----------------------------
# Pattern detectors
# -----------------------------
def stopped_out_pattern(position_data: Any, orders_df: pd.DataFrame, *, min_loss_magnitude: float = MIN_LOSS_MAGNITUDE_FOR_PATTERN) -> Tuple[bool, float]:
    """
    Detect if the position was closed by a stop-loss order (MA_CROSS_SL) with a loss.

    Returns (True, 1.0) if:
    - closing order is found
    - closing order tags contain MA_CROSS_SL
    - status is FILLED (case-insensitive)
    - realized_pnl < 0 and exceeds minimum magnitude threshold
    Otherwise returns (False, 0.0).
    """
    if not validate_position_data(position_data, ["closing_order_id", "realized_pnl"]):
        return False, 0.0
    pos = _as_mapping(position_data)
    realized_pnl = float(pos.get("realized_pnl", 0.0))
    if realized_pnl >= 0.0 or abs(realized_pnl) < float(min_loss_magnitude):
        return False, 0.0

    order = get_closing_order_details(position_data, orders_df)
    if order is None:
        return False, 0.0
    tags = str(order.get("tags", ""))
    status = str(order.get("status", "")).upper()

    if has_tag(tags, "MA_CROSS_SL") and status == "FILLED":
        return True, 1.0
    return False, 0.0


def reversal_pattern(
    position_data: Any,
    orders_df: pd.DataFrame,
    *,
    bars: Optional[pd.DataFrame] = None,
    momentum_lookback: int = 5,
    min_loss_magnitude: float = MIN_LOSS_MAGNITUDE_FOR_PATTERN,
) -> Tuple[bool, float]:
    """
    Detect if the position was closed by an opposite-direction entry signal.
    Criteria:
    - closing order contains MA_CROSS tag
    - does NOT contain MA_CROSS_SL or MA_CROSS_TP
    - realized_pnl < 0 with minimum magnitude
    """
    if not validate_position_data(position_data, ["closing_order_id", "realized_pnl"]):
        return False, 0.0
    pos = _as_mapping(position_data)
    realized_pnl = float(pos.get("realized_pnl", 0.0))
    if realized_pnl >= 0.0 or abs(realized_pnl) < float(min_loss_magnitude):
        return False, 0.0

    order = get_closing_order_details(position_data, orders_df)
    if order is None:
        return False, 0.0
    tags = str(order.get("tags", ""))

    if has_tag(tags, "MA_CROSS") and not has_tag(tags, "MA_CROSS_SL") and not has_tag(tags, "MA_CROSS_TP"):
        confidence: float = 1.0
        if bars is not None and not bars.empty:
            try:
                df = bars.copy()
                if "timestamp" in df.columns:
                    df = df.sort_values("timestamp")
                closes = df["close"].astype(float)
                look = max(1, int(momentum_lookback))
                if len(closes) >= look + 1:
                    recent = closes.tail(look + 1)
                    momentum = float(recent.iloc[-1] - recent.iloc[0])
                    side = str(_as_mapping(position_data).get("side", "")).upper()
                    if side == "LONG" and momentum < 0:
                        confidence = 1.0
                    elif side == "SHORT" and momentum > 0:
                        confidence = 1.0
                    else:
                        confidence = 0.8
            except Exception:
                confidence = 1.0
        return True, float(max(0.0, min(1.0, confidence)))
    return False, 0.0


def false_breakout_pattern(
    position_data: Any,
    orders_df: pd.DataFrame,
    *,
    bars: Optional[pd.DataFrame] = None,
    min_loss_magnitude: float = MIN_LOSS_MAGNITUDE_FOR_PATTERN,
) -> Tuple[bool, float]:
    """
    Detect quick stop-loss hits indicating a false breakout.

    Logic:
    - Must be a stop-out per stopped_out_pattern
    - Duration must be evaluated with gradient confidence:
        - duration >= 300s: (True, 0.0)
        - duration < 300s: confidence = 1.0 - (duration / 300.0)
    """
    is_stopped, _ = stopped_out_pattern(position_data, orders_df, min_loss_magnitude=min_loss_magnitude)
    if not is_stopped:
        return False, 0.0

    duration_seconds = calculate_duration_seconds(position_data)
    if duration_seconds >= float(FALSE_BREAKOUT_DURATION_SECONDS):
        return False, 0.0

    confidence = 1.0 - (duration_seconds / float(CONFIDENCE_GRADIENT_DURATION_SECONDS))
    # refine using entry/exit distance vs bar range if available
    try:
        pos = _as_mapping(position_data)
        entry_price = pos.get("entry_price")
        exit_price = pos.get("exit_price")
        sl_distance = None
        if entry_price is not None and exit_price is not None:
            sl_distance = abs(float(exit_price) - float(entry_price))
        if bars is not None and not bars.empty:
            df = bars.copy()
            rng = None
            if all(col in df.columns for col in ["high", "low"]):
                rng = float(np.mean((df["high"].astype(float) - df["low"].astype(float)).clip(lower=0)))
            if rng is not None and rng > 0.0 and sl_distance is not None:
                ratio = float(sl_distance) / rng
                if ratio <= 0.5:
                    confidence += 0.15
                elif ratio >= 1.5:
                    confidence -= 0.15
    except Exception:
        pass
    confidence = float(max(0.0, min(1.0, confidence)))
    return True, confidence


def choppy_market_pattern(
    loss_trades: List[Any],
    current_position_data: Any,
    time_window_seconds: float = CHOPPY_MARKET_SEQUENCE_DURATION_SECONDS,
    *,
    bars: Optional[pd.DataFrame] = None,
) -> Tuple[bool, float]:
    """
    Detect if the current loss is part of a choppy market sequence of losses
    occurring in a short timeframe.

    Required fields for `current_position_data`: entry_time, realized_pnl
    Each item in `loss_trades` should contain at least: entry_time, realized_pnl
    """
    if loss_trades is None or len(loss_trades) == 0:
        return False, 0.0

    if not validate_position_data(current_position_data, ["entry_time", "realized_pnl"]):
        return False, 0.0
    curr = _as_mapping(current_position_data)
    if float(curr.get("realized_pnl", 0.0)) >= 0.0:
        return False, 0.0

    current_time = curr.get("entry_time")
    if isinstance(current_time, str):
        try:
            current_time = pd.to_datetime(current_time)
        except Exception:
            return False, 0.0
    if not isinstance(current_time, pd.Timestamp):
        try:
            current_time = pd.to_datetime(current_time)
        except Exception:
            return False, 0.0

    window_start = current_time - pd.Timedelta(seconds=float(time_window_seconds))

    # Gather loss trades within the window prior to the current trade
    candidate_losses: List[Dict[str, Any]] = []
    for t in loss_trades:
        m = _as_mapping(t)
        if float(m.get("realized_pnl", 0.0)) >= 0.0:
            continue
        ts = m.get("entry_time")
        try:
            ts = pd.to_datetime(ts)
        except Exception:
            continue
        if window_start <= ts <= current_time:
            candidate_losses.append({"entry_time": ts, "realized_pnl": float(m.get("realized_pnl", 0.0))})

    # Remove potential duplicate of current trade then include once
    candidate_losses = [c for c in candidate_losses if c["entry_time"] != current_time]
    candidate_losses.append({"entry_time": current_time, "realized_pnl": float(curr.get("realized_pnl", 0.0))})
    # Sort by time ascending
    candidate_losses.sort(key=lambda x: x["entry_time"])

    count_losses = len(candidate_losses)
    if count_losses < CHOPPY_MARKET_MIN_SEQUENCE_LENGTH:
        return False, 0.0

    # Base confidence by length
    if count_losses >= 5:
        base_conf = 1.0
    elif count_losses == 4:
        base_conf = 0.75
    else:  # 3
        base_conf = 0.6

    # Time density adjustments
    times = [c["entry_time"] for c in candidate_losses]
    span_seconds = (times[-1] - times[0]).total_seconds() if len(times) > 1 else 0.0
    if span_seconds <= time_window_seconds / 4.0:
        time_adj = 0.2
    elif span_seconds <= (3.0 * time_window_seconds) / 4.0:
        time_adj = 0.1
    else:
        time_adj = 0.0

    # Loss magnitude consistency adjustment using coefficient of variation
    losses = np.array([abs(c["realized_pnl"]) for c in candidate_losses], dtype=float)
    mag_adj = 0.0
    if np.all(losses > 0.0):
        mean_loss = float(np.mean(losses))
        std_loss = float(np.std(losses))
        if mean_loss > 0.0:
            cv = std_loss / mean_loss
            if cv < 0.25:
                mag_adj = 0.1
            elif cv > 0.75:
                mag_adj = -0.1

    # Optional volatility density adjustment using provided bars window
    if bars is not None and not bars.empty:
        try:
            df = bars.copy()
            if all(col in df.columns for col in ["high", "low"]):
                avg_range = float(np.mean((df["high"].astype(float) - df["low"].astype(float)).clip(lower=0)))
                if avg_range > 0:
                    med_close = float(np.median(df.get("close", pd.Series([1.0])).astype(float))) or 1.0
                    rel_vol = avg_range / med_close
                    if rel_vol >= 0.01:
                        mag_adj += 0.05
        except Exception:
            pass

    confidence = base_conf + time_adj + mag_adj
    confidence = float(max(0.0, min(1.0, confidence)))
    return True, confidence


def trend_exhaustion_pattern(
    position_data: Any, orders_df: pd.DataFrame, loss_trades: Optional[List[Any]] = None
) -> Tuple[bool, float]:
    """
    Detect long-duration trades with relatively small losses indicating trend exhaustion.

    Criteria:
    - duration_seconds > TREND_EXHAUSTION_DURATION_SECONDS
    - realized_pnl < 0
    - loss magnitude is small relative to historical losses (or absolute threshold)
    """
    if not validate_position_data(position_data, ["duration_ns", "realized_pnl"]):
        return False, 0.0
    pos = _as_mapping(position_data)
    realized_pnl = float(pos.get("realized_pnl", 0.0))
    if realized_pnl >= 0.0:
        return False, 0.0

    duration_seconds = calculate_duration_seconds(position_data)
    if duration_seconds <= float(TREND_EXHAUSTION_DURATION_SECONDS):
        return False, 0.0

    # Determine magnitude multiplier
    loss_abs = abs(realized_pnl)
    multiplier = 0.0
    if loss_trades and len(loss_trades) > 0:
        losses_abs = []
        for t in loss_trades:
            m = _as_mapping(t)
            pnl = float(m.get("realized_pnl", 0.0))
            if pnl < 0.0:
                losses_abs.append(abs(pnl))
        if len(losses_abs) > 0:
            median_loss = float(np.median(losses_abs))
        else:
            median_loss = 0.0
        if median_loss <= 0.0:
            # Fallback to absolute thresholds
            if loss_abs < 25.0:
                multiplier = 1.0
            elif loss_abs < 50.0:
                multiplier = 0.5
            else:
                multiplier = 0.0
        else:
            if loss_abs < 0.25 * median_loss:
                multiplier = 1.0
            elif loss_abs < 0.5 * median_loss:
                multiplier = 0.5
            else:
                multiplier = 0.0
    else:
        # No history provided: use absolute thresholds
        if loss_abs < 25.0:
            multiplier = 1.0
        elif loss_abs < 50.0:
            multiplier = 0.5
        else:
            multiplier = 0.0

    if multiplier <= 0.0:
        return False, 0.0

    # Duration confidence gradient: 3600 -> 0.5, 7200 -> 0.75, 10800+ -> 1.0
    min_s = float(TREND_EXHAUSTION_DURATION_SECONDS)
    max_s = 10800.0
    ratio = (duration_seconds - min_s) / (max_s - min_s)
    ratio = float(max(0.0, min(1.0, ratio)))
    duration_conf = 0.5 + 0.5 * ratio

    confidence = float(max(0.0, min(1.0, duration_conf * multiplier)))
    return True, confidence


# -----------------------------
# Composite detection utilities
# -----------------------------
def detect_stopped_out(position_data: Any, context: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Wrapper: detector(position_data, context) -> (bool, float)
    context expects: orders_df; optional min_loss_magnitude
    """
    orders_df = context.get("orders_df")
    min_loss = float(context.get("min_loss_magnitude", MIN_LOSS_MAGNITUDE_FOR_PATTERN))
    return stopped_out_pattern(position_data, orders_df, min_loss_magnitude=min_loss)


def detect_reversal(position_data: Any, context: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Wrapper for reversal using optional bars and threshold
    context: orders_df, optional bars, min_loss_magnitude
    """
    orders_df = context.get("orders_df")
    bars = context.get("bars")
    min_loss = float(context.get("min_loss_magnitude", MIN_LOSS_MAGNITUDE_FOR_PATTERN))
    return reversal_pattern(position_data, orders_df, bars=bars, min_loss_magnitude=min_loss)


def detect_false_breakout(position_data: Any, context: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Wrapper for false_breakout using optional bars and threshold
    context: orders_df, optional bars, min_loss_magnitude
    """
    orders_df = context.get("orders_df")
    bars = context.get("bars")
    min_loss = float(context.get("min_loss_magnitude", MIN_LOSS_MAGNITUDE_FOR_PATTERN))
    return false_breakout_pattern(position_data, orders_df, bars=bars, min_loss_magnitude=min_loss)


def detect_choppy_market(position_data: Any, context: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Wrapper for choppy_market using loss_trades and optional bars
    context: loss_trades, optional bars
    """
    loss_trades = context.get("loss_trades") or []
    bars = context.get("bars")
    return choppy_market_pattern(loss_trades, position_data, bars=bars)


def detect_trend_exhaustion(position_data: Any, context: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Wrapper for trend_exhaustion
    context: orders_df (unused), loss_trades
    """
    orders_df = context.get("orders_df")
    loss_trades = context.get("loss_trades") or []
    return trend_exhaustion_pattern(position_data, orders_df, loss_trades)
def detect_all_patterns(
    position_data: Any, orders_df: pd.DataFrame, loss_trades: Optional[List[Any]] = None,
    *, bars: Optional[pd.DataFrame] = None, min_loss_magnitude: float = MIN_LOSS_MAGNITUDE_FOR_PATTERN
) -> Dict[str, Tuple[bool, float]]:
    """
    Run all detectors and return a dict of pattern_name -> (matched, confidence).
    """
    results: Dict[str, Tuple[bool, float]] = {
        "stopped_out": detect_stopped_out(position_data, {"orders_df": orders_df, "min_loss_magnitude": min_loss_magnitude}),
        "reversal": detect_reversal(position_data, {"orders_df": orders_df, "bars": bars, "min_loss_magnitude": min_loss_magnitude}),
        "false_breakout": detect_false_breakout(position_data, {"orders_df": orders_df, "bars": bars, "min_loss_magnitude": min_loss_magnitude}),
        "choppy_market": detect_choppy_market(position_data, {"loss_trades": loss_trades or [], "bars": bars}),
        "trend_exhaustion": detect_trend_exhaustion(position_data, {"orders_df": orders_df, "loss_trades": loss_trades or []}),
    }
    return results


def get_dominant_pattern(pattern_results: Dict[str, Tuple[bool, float]]) -> Optional[str]:
    """
    Select the pattern with the highest confidence among matches.
    Returns None if no pattern matched.
    """
    matches = [(name, conf) for name, (ok, conf) in pattern_results.items() if ok]
    if not matches:
        return None
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches[0][0]


# -----------------------------
# Testing utilities
# -----------------------------
def create_mock_position(
    duration_seconds: float,
    realized_pnl: float,
    closing_order_tags: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Create a mock position dict for testing.
    Additional fields can be provided via kwargs (e.g., entry_time, closing_order_id).
    """
    m: Dict[str, Any] = {
        "duration_ns": int(duration_seconds * 1_000_000_000),
        "realized_pnl": float(realized_pnl),
        "closing_order_id": kwargs.get("closing_order_id", "order-1"),
    }
    if "entry_time" in kwargs:
        m["entry_time"] = kwargs["entry_time"]
    if "entry_price" in kwargs:
        m["entry_price"] = kwargs["entry_price"]
    if "exit_price" in kwargs:
        m["exit_price"] = kwargs["exit_price"]
    # Attach tags hint (used by tests in conjunction with orders_df)
    m["_closing_order_tags"] = closing_order_tags
    # Pass through any other custom fields
    for k, v in kwargs.items():
        if k not in m:
            m[k] = v
    return m


def create_mock_orders_df(orders: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Create a mock orders DataFrame with columns:
    venue_order_id, tags, status, type
    """
    df = pd.DataFrame(orders)
    # Ensure expected columns exist
    for col in ["venue_order_id", "tags", "status", "type"]:
        if col not in df.columns:
            df[col] = None
    return df


