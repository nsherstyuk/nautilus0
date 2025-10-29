"""
Synthetic Data Generator for Moving Average Crossover Strategy Testing

This module provides comprehensive synthetic data generation capabilities for systematic
testing of the Moving Average Crossover strategy with controlled, predictable patterns.
It generates ParquetDataCatalog-compatible bar data that can be consumed by the existing
backtest infrastructure.

Key Features:
- Generate controlled MA crossover patterns with configurable separation distances
- Support testing individual filters in isolation (DMI, Stochastic, ATR, ADX, time-of-day, circuit breaker)
- Generate data for both passing and failing filter scenarios
- Maintain compatibility with NautilusTrader's Bar, BarType, Price, Quantity objects
- Support both forex (5-decimal precision) and stock (2-decimal precision) instruments

Usage Examples:
    # Generate simple bullish crossover
    bars = generate_simple_crossover(
        symbol="EUR/USD", venue="IDEALPRO", 
        fast_period=10, slow_period=20,
        crossover_type="bullish", crossover_bar=50,
        total_bars=100, base_price=1.08000
    )
    
    # Generate data with DMI alignment
    bars = generate_with_dmi_patterns(
        symbol="EUR/USD", venue="IDEALPRO",
        crossover_type="bullish", dmi_aligned=True,
        fast_period=10, slow_period=20, total_bars=100
    )
    
    # Save to catalog for backtest
    success = write_to_catalog(
        bars, "EUR/USD", "IDEALPRO", 
        "/path/to/catalog", "1-MINUTE-MID-EXTERNAL"
    )

Expected Data Patterns:
- Simple crossovers: Clear MA separation before/after crossover
- DMI patterns: Directional movement aligned/misaligned with crossover
- Stochastic patterns: %K/%D values in oversold/overbought regions
- Time patterns: Crossovers at specific times for time-of-day filter testing
- Volatility patterns: Controlled ATR values for volatility filter testing
- ADX patterns: Strong/weak trend patterns for trend strength testing

Filter Behaviors:
- Pre-crossover separation: Rejects crossovers with insufficient MA separation
- DMI alignment: Requires trend direction to match crossover direction
- Stochastic momentum: Requires favorable %K/%D conditions and recent crossing
- Time-of-day: Restricts trading to specific hours
- ATR volatility: Requires volatility within acceptable range
- ADX trend strength: Requires sufficient trend strength
- Circuit breaker: Prevents trading after consecutive losses

Troubleshooting:
- Ensure proper decimal precision for instrument type (5 for forex, 2 for stocks)
- Verify timestamp continuity for time-based filters
- Check OHLCV relationships (high >= open/close, low <= open/close)
- Validate MA calculation periods match strategy configuration
- Ensure sufficient data points for indicator calculations
"""

import datetime
import sys
from typing import List, Optional, Tuple
from pathlib import Path

import pandas as pd
import numpy as np

# Add project root to sys.path for module imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from utils.instruments import normalize_instrument_id
from backtest.run_backtest import create_instrument


# Configuration Constants
DEFAULT_FOREX_SYMBOL = "EUR/USD"
DEFAULT_FOREX_VENUE = "IDEALPRO"
DEFAULT_STOCK_SYMBOL = "SPY"
DEFAULT_STOCK_VENUE = "SMART"
DEFAULT_BAR_SPEC = "1-MINUTE-MID-EXTERNAL"  # for forex
DEFAULT_STOCK_BAR_SPEC = "1-MINUTE-LAST-EXTERNAL"  # for stocks
DEFAULT_BASE_PRICE_FOREX = 1.08000  # EUR/USD typical
DEFAULT_BASE_PRICE_STOCK = 450.00  # SPY typical
DEFAULT_FAST_PERIOD = 10
DEFAULT_SLOW_PERIOD = 20
DEFAULT_TOTAL_BARS = 200
FOREX_PRICE_PRECISION = 5
STOCK_PRICE_PRECISION = 2


def _create_bar(
    bar_type: BarType,
    timestamp: pd.Timestamp,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: float,
    price_precision: int
) -> Bar:
    """
    Create a single NautilusTrader Bar object with proper typing.
    
    Args:
        bar_type: BarType for the bar
        timestamp: Timestamp for the bar
        open_price: Open price
        high_price: High price
        low_price: Low price
        close_price: Close price
        volume: Volume
        price_precision: Decimal precision for price formatting
        
    Returns:
        Bar object with proper NautilusTrader typing
    """
    # Convert timestamp to nanoseconds
    timestamp_ns = dt_to_unix_nanos(timestamp)
    
    # Validate OHLCV relationships
    if high_price < max(open_price, close_price):
        high_price = max(open_price, close_price)
    if low_price > min(open_price, close_price):
        low_price = min(open_price, close_price)
    
    # Create Price objects with proper decimal formatting
    price_format = f"{{:.{price_precision}f}}"
    open_price_str = price_format.format(open_price)
    high_price_str = price_format.format(high_price)
    low_price_str = price_format.format(low_price)
    close_price_str = price_format.format(close_price)
    
    open_price_obj = Price.from_str(open_price_str)
    high_price_obj = Price.from_str(high_price_str)
    low_price_obj = Price.from_str(low_price_str)
    close_price_obj = Price.from_str(close_price_str)
    
    # Create Quantity object for volume
    volume_str = f"{volume:.2f}"
    volume_obj = Quantity.from_str(volume_str)
    
    # Create Bar object
    bar = Bar(
        bar_type=bar_type,
        open=open_price_obj,
        high=high_price_obj,
        low=low_price_obj,
        close=close_price_obj,
        volume=volume_obj,
        ts_event=timestamp_ns,
        ts_init=timestamp_ns,
        is_revision=False
    )
    
    return bar


def _generate_ma_prices(
    fast_period: int,
    slow_period: int,
    total_bars: int,
    crossover_bar: int,
    crossover_type: str,
    separation_before: float,
    separation_after: float,
    base_price: float,
    seed: Optional[int] = None
) -> List[float]:
    """
    Generate price series that produces specific MA values and crossovers.
    
    Args:
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars to generate
        crossover_bar: Bar index where crossover occurs
        crossover_type: "bullish" or "bearish"
        separation_before: MA separation before crossover
        separation_after: MA separation after crossover
        base_price: Base price level
        seed: Optional random seed for deterministic generation
        
    Returns:
        List of close prices that will produce the desired MA pattern
    """
    # Set random seed if provided
    if seed is not None:
        np.random.seed(seed)
    
    close_prices = []
    
    # Generate very clean, deterministic price series
    # Before crossover: build up separation gradually
    for i in range(crossover_bar):
        if i < slow_period - 1:
            # Not enough data for slow MA yet - use base price
            price = base_price
        else:
            # Build up separation before crossover with a trend
            if crossover_type == "bullish":
                # Fast MA should be below slow MA before bullish crossover
                # Create a downward trend to build separation
                trend_factor = (crossover_bar - i) / (crossover_bar - slow_period + 1)
                price = base_price - separation_before * trend_factor
            else:
                # Fast MA should be above slow MA before bearish crossover
                # Create an upward trend to build separation
                trend_factor = (crossover_bar - i) / (crossover_bar - slow_period + 1)
                price = base_price + separation_before * trend_factor
        close_prices.append(price)
    
    # Generate crossover bar - create the crossover
    if crossover_type == "bullish":
        # Price that will make fast MA cross above slow MA
        # Need a significant price jump to create the crossover
        price = base_price + separation_after * 2
    else:
        # Price that will make fast MA cross below slow MA
        price = base_price - separation_after * 2
    close_prices.append(price)
    
    # Generate prices after crossover - maintain separation
    for i in range(crossover_bar + 1, total_bars):
        if crossover_type == "bullish":
            # Fast MA should stay above slow MA after bullish crossover
            price = base_price + separation_after + (i - crossover_bar) * 0.00001
        else:
            # Fast MA should stay below slow MA after bearish crossover
            price = base_price - separation_after - (i - crossover_bar) * 0.00001
        close_prices.append(price)
    
    return close_prices


def _compute_ma_values_for_prices(
    close_prices: List[float],
    fast_period: int,
    slow_period: int
) -> List[Tuple[int, float, float]]:
    """
    Compute fast and slow SMA values for a given price series.
    
    Args:
        close_prices: List of close prices
        fast_period: Fast MA period
        slow_period: Slow MA period
        
    Returns:
        List of tuples: (bar_index, fast_sma, slow_sma)
    """
    ma_values = []
    
    # Start from slow_period - 1 (when slow MA becomes valid)
    for i in range(slow_period - 1, len(close_prices)):
        # Calculate slow SMA
        slow_sma = sum(close_prices[i - slow_period + 1:i + 1]) / slow_period
        
        # Calculate fast SMA if enough data
        if i >= fast_period - 1:
            fast_sma = sum(close_prices[i - fast_period + 1:i + 1]) / fast_period
        else:
            fast_sma = None
        
        ma_values.append((i, fast_sma, slow_sma))
    
    return ma_values


def _detect_crossovers_from_ma_values(
    ma_values: List[Tuple[int, float, float]],
    start_date: str,
    bar_spec: str
) -> List[dict]:
    """
    Detect crossover points from MA value series.
    
    Args:
        ma_values: List of (bar_index, fast_sma, slow_sma) tuples
        start_date: Start date string for timestamp calculation
        bar_spec: Bar specification for interval calculation
        
    Returns:
        List of crossover dicts with bar_index, timestamp, type, fast_ma, slow_ma
    """
    crossovers = []
    
    # Parse bar interval from bar_spec (e.g., "1-MINUTE-MID-EXTERNAL" -> 1 minute)
    if "MINUTE" in bar_spec:
        interval_minutes = int(bar_spec.split("-")[0])
    else:
        interval_minutes = 1  # Default to 1 minute
    
    for i in range(1, len(ma_values)):
        prev_bar, prev_fast, prev_slow = ma_values[i - 1]
        curr_bar, curr_fast, curr_slow = ma_values[i]
        
        # Skip if fast MA not available yet
        if prev_fast is None or curr_fast is None:
            continue
        
        # Detect bullish crossover: prev_fast < prev_slow and curr_fast > curr_slow
        if prev_fast < prev_slow and curr_fast > curr_slow:
            # Calculate timestamp for crossover bar
            start_timestamp = pd.Timestamp(start_date, tz="UTC")
            crossover_timestamp = start_timestamp + pd.Timedelta(minutes=curr_bar * interval_minutes)
            
            crossovers.append({
                "bar_index": curr_bar,
                "timestamp": crossover_timestamp.isoformat(),
                "type": "bullish",
                "fast_ma": curr_fast,
                "slow_ma": curr_slow
            })
        
        # Detect bearish crossover: prev_fast > prev_slow and curr_fast < curr_slow
        elif prev_fast > prev_slow and curr_fast < curr_slow:
            # Calculate timestamp for crossover bar
            start_timestamp = pd.Timestamp(start_date, tz="UTC")
            crossover_timestamp = start_timestamp + pd.Timedelta(minutes=curr_bar * interval_minutes)
            
            crossovers.append({
                "bar_index": curr_bar,
                "timestamp": crossover_timestamp.isoformat(),
                "type": "bearish",
                "fast_ma": curr_fast,
                "slow_ma": curr_slow
            })
    
    return crossovers


def generate_ma_diagnostic_metadata(
    close_prices: List[float],
    fast_period: int,
    slow_period: int,
    start_date: str,
    bar_spec: str,
    scenario_name: str
) -> dict:
    """
    Generate metadata JSON for MA diagnostic scenarios.
    
    Args:
        close_prices: List of close prices
        fast_period: Fast MA period
        slow_period: Slow MA period
        start_date: Start date string
        bar_spec: Bar specification string
        scenario_name: Name of the scenario
        
    Returns:
        Metadata dict with expected crossovers
    """
    # Compute MA values
    ma_values = _compute_ma_values_for_prices(close_prices, fast_period, slow_period)
    
    # Detect crossovers
    expected_crossovers = _detect_crossovers_from_ma_values(ma_values, start_date, bar_spec)
    
    # Create metadata dict
    metadata = {
        "scenario_name": scenario_name,
        "fast_period": fast_period,
        "slow_period": slow_period,
        "total_bars": len(close_prices),
        "start_date": start_date,
        "expected_crossovers": expected_crossovers
    }
    
    return metadata


def write_metadata_to_catalog(
    metadata: dict,
    symbol: str,
    catalog_path: str
) -> bool:
    """
    Write metadata JSON file to catalog directory.
    
    Args:
        metadata: Metadata dict to save
        symbol: Instrument symbol
        catalog_path: Path to catalog directory
        
    Returns:
        True on success, False on failure
    """
    try:
        import json
        
        # Create metadata directory
        metadata_dir = Path(catalog_path) / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        
        # Write JSON file
        metadata_file = metadata_dir / f"{symbol.replace('/', '-')}_metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"Successfully wrote metadata to {metadata_file}")
        return True
        
    except Exception as e:
        print(f"Error writing metadata to catalog: {e}")
        return False


def _prices_to_ohlcv(
    close_prices: List[float],
    volatility: float = 0.0002
) -> List[Tuple[float, float, float, float, float]]:
    """
    Convert close price series to realistic OHLCV bars.
    
    Args:
        close_prices: List of close prices
        volatility: Volatility factor for high/low generation
        
    Returns:
        List of (open, high, low, close, volume) tuples
    """
    ohlcv_bars = []
    prev_close = None
    
    for i, close_price in enumerate(close_prices):
        # Open price (previous close or close with small variation for first bar)
        if prev_close is None:
            open_price = close_price + np.random.normal(0, volatility * close_price)
        else:
            open_price = prev_close
        
        # High and low prices with realistic volatility
        high_low_range = volatility * close_price
        high_price = max(open_price, close_price) + np.random.uniform(0, high_low_range)
        low_price = min(open_price, close_price) - np.random.uniform(0, high_low_range)
        
        # Volume (random realistic range with decimal precision)
        volume = round(np.random.uniform(1000, 10001), 2)
        
        ohlcv_bars.append((open_price, high_price, low_price, close_price, volume))
        prev_close = close_price
    
    return ohlcv_bars


def _create_bars_from_ohlcv(
    ohlcv_bars: List[Tuple[float, float, float, float, float]],
    symbol: str,
    venue: str,
    bar_spec: str,
    start_date: str,
    total_bars: int
) -> List[Bar]:
    """
    Common helper to create Bar objects from OHLCV data.
    
    Args:
        ohlcv_bars: List of (open, high, low, close, volume) tuples
        symbol: Instrument symbol
        venue: Trading venue
        bar_spec: Bar specification string
        start_date: Start date string
        total_bars: Total number of bars
        
    Returns:
        List of Bar objects
    """
    # Generate timestamps
    start_timestamp = pd.Timestamp(start_date, tz="UTC")
    timestamps = [start_timestamp + pd.Timedelta(minutes=i) for i in range(total_bars)]
    
    # Create Bar objects
    bars = []
    instrument_id = normalize_instrument_id(symbol, venue)
    bar_type = BarType.from_str(f"{instrument_id}-{bar_spec}")
    
    # Determine price precision
    price_precision = FOREX_PRICE_PRECISION if "/" in symbol else STOCK_PRICE_PRECISION
    
    for i, (timestamp, (open_price, high_price, low_price, close_price, volume)) in enumerate(
        zip(timestamps, ohlcv_bars)
    ):
        bar = _create_bar(
            bar_type, timestamp, open_price, high_price, low_price, close_price, volume, price_precision
        )
        bars.append(bar)
    
    return bars


def _create_bars_from_ohlcv_with_timestamps(
    ohlcv_bars: List[Tuple[float, float, float, float, float]],
    timestamps: List[pd.Timestamp],
    symbol: str,
    venue: str,
    bar_spec: str
) -> List[Bar]:
    """
    Helper to create Bar objects from OHLCV data with custom timestamps.
    
    Args:
        ohlcv_bars: List of (open, high, low, close, volume) tuples
        timestamps: List of custom timestamps
        symbol: Instrument symbol
        venue: Trading venue
        bar_spec: Bar specification string
        
    Returns:
        List of Bar objects
    """
    # Create Bar objects
    bars = []
    instrument_id = normalize_instrument_id(symbol, venue)
    bar_type = BarType.from_str(f"{instrument_id}-{bar_spec}")
    
    # Determine price precision
    price_precision = FOREX_PRICE_PRECISION if "/" in symbol else STOCK_PRICE_PRECISION
    
    for i, (timestamp, (open_price, high_price, low_price, close_price, volume)) in enumerate(
        zip(timestamps, ohlcv_bars)
    ):
        bar = _create_bar(
            bar_type, timestamp, open_price, high_price, low_price, close_price, volume, price_precision
        )
        bars.append(bar)
    
    return bars


def generate_simple_crossover(
    symbol: str,
    venue: str,
    fast_period: int,
    slow_period: int,
    crossover_type: str,
    crossover_bar: int,
    total_bars: int,
    separation_before: float,
    separation_after: float,
    base_price: float,
    bar_spec: str,
    start_date: str
) -> List[Bar]:
    """
    Generate data with a single predictable MA crossover.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        fast_period: Fast MA period
        slow_period: Slow MA period
        crossover_type: "bullish" or "bearish"
        crossover_bar: Bar index where crossover occurs
        total_bars: Total number of bars
        separation_before: MA separation before crossover
        separation_after: MA separation after crossover
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with controlled crossover pattern
    """
    # Generate price series with controlled crossover
    close_prices = _generate_ma_prices(
        fast_period, slow_period, total_bars, crossover_bar,
        crossover_type, separation_before, separation_after, base_price
    )
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_with_insufficient_separation(
    symbol: str,
    venue: str,
    fast_period: int,
    slow_period: int,
    crossover_type: str,
    crossover_bar: int,
    total_bars: int,
    max_separation_in_lookback: float,
    base_price: float,
    bar_spec: str,
    start_date: str
) -> List[Bar]:
    """
    Generate crossover data that fails pre-crossover separation filter.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        fast_period: Fast MA period
        slow_period: Slow MA period
        crossover_type: "bullish" or "bearish"
        crossover_bar: Bar index where crossover occurs
        total_bars: Total number of bars
        max_separation_in_lookback: Maximum allowed separation in lookback window
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with insufficient separation pattern
    """
    # Generate price series with insufficient separation
    close_prices = _generate_ma_prices(
        fast_period, slow_period, total_bars, crossover_bar,
        crossover_type, max_separation_in_lookback * 0.5, 0.001, base_price
    )
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_with_dmi_patterns(
    symbol: str,
    venue: str,
    crossover_type: str,
    dmi_aligned: bool,
    fast_period: int,
    slow_period: int,
    total_bars: int,
    base_price: float,
    bar_spec: str,
    start_date: str
) -> List[Bar]:
    """
    Generate data with specific DMI trend patterns (aligned or misaligned with crossover).
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        crossover_type: "bullish" or "bearish"
        dmi_aligned: Whether DMI trend aligns with crossover direction
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with DMI pattern
    """
    # Generate controlled MA crossover pattern first
    crossover_bar = total_bars // 2
    close_prices = _generate_ma_prices(
        fast_period, slow_period, total_bars, crossover_bar,
        crossover_type, 0.001, 0.002, base_price
    )
    
    # Generate directional movement pattern for DMI
    trend_direction = 1 if (crossover_type == "bullish" and dmi_aligned) or (crossover_type == "bearish" and not dmi_aligned) else -1
    
    # Convert to OHLCV with directional movement
    ohlcv_bars = []
    prev_close = base_price
    
    for i, close_price in enumerate(close_prices):
        # Open price
        open_price = prev_close
        
        # High and low with directional bias
        if trend_direction > 0:  # Uptrend
            high_price = max(open_price, close_price) + np.random.uniform(0, 0.0003)
            low_price = min(open_price, close_price) - np.random.uniform(0, 0.0001)
        else:  # Downtrend
            high_price = max(open_price, close_price) + np.random.uniform(0, 0.0001)
            low_price = min(open_price, close_price) - np.random.uniform(0, 0.0003)
        
        # Volume (with decimal precision)
        volume = round(np.random.uniform(1000, 10001), 2)
        
        ohlcv_bars.append((open_price, high_price, low_price, close_price, volume))
        prev_close = close_price
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_with_stochastic_patterns(
    symbol: str,
    venue: str,
    crossover_type: str,
    stoch_favorable: bool,
    stoch_crossing_bars_ago: int,
    fast_period: int,
    slow_period: int,
    total_bars: int,
    base_price: float,
    bar_spec: str,
    start_date: str
) -> List[Bar]:
    """
    Generate data with specific Stochastic %K/%D patterns.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        crossover_type: "bullish" or "bearish"
        stoch_favorable: Whether stochastic conditions are favorable
        stoch_crossing_bars_ago: Bars ago when stochastic crossing occurred
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with stochastic pattern
    """
    # Generate controlled MA crossover pattern first
    crossover_bar = total_bars // 2
    close_prices = _generate_ma_prices(
        fast_period, slow_period, total_bars, crossover_bar,
        crossover_type, 0.001, 0.002, base_price
    )
    
    # Convert to OHLCV with controlled ranges for stochastic
    ohlcv_bars = []
    prev_close = base_price
    
    for i, close_price in enumerate(close_prices):
        # Open price
        open_price = prev_close
        
        # Position stochastic crossing relative to current bar
        crossing_bar = total_bars - stoch_crossing_bars_ago - 1
        is_near_crossing = abs(i - crossing_bar) <= 2  # Within 2 bars of crossing
        
        # Control high/low ranges to achieve target %K values
        if stoch_favorable and is_near_crossing:
            if crossover_type == "bullish":
                # Oversold region: wide low range, narrow high range
                high_price = max(open_price, close_price) + np.random.uniform(0, 0.0001)
                low_price = min(open_price, close_price) - np.random.uniform(0.0002, 0.0005)
            else:  # bearish
                # Overbought region: wide high range, narrow low range
                high_price = max(open_price, close_price) + np.random.uniform(0.0002, 0.0005)
                low_price = min(open_price, close_price) - np.random.uniform(0, 0.0001)
        else:
            # Unfavorable or not near crossing: narrow ranges, middle %K values
            high_price = max(open_price, close_price) + np.random.uniform(0, 0.0001)
            low_price = min(open_price, close_price) - np.random.uniform(0, 0.0001)
        
        # Volume (with decimal precision)
        volume = round(np.random.uniform(1000, 10001), 2)
        
        ohlcv_bars.append((open_price, high_price, low_price, close_price, volume))
        prev_close = close_price
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_with_time_patterns(
    symbol: str,
    venue: str,
    crossover_hour: int,
    crossover_minute: int,
    timezone: str,
    fast_period: int,
    slow_period: int,
    total_bars: int,
    base_price: float,
    bar_spec: str,
    start_date: str
) -> List[Bar]:
    """
    Generate data with specific timestamps for time-of-day filter testing.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        crossover_hour: Hour when crossover occurs
        crossover_minute: Minute when crossover occurs
        timezone: Timezone for timestamps
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with controlled timestamps
    """
    # Generate simple MA crossover pattern
    crossover_bar = total_bars // 2
    close_prices = _generate_ma_prices(
        fast_period, slow_period, total_bars, crossover_bar,
        "bullish", 0.001, 0.002, base_price
    )
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Generate timestamps with specific crossover time
    start_timestamp = pd.Timestamp(start_date, tz=timezone).tz_convert("UTC")
    
    # Calculate offset to reach target crossover time
    target_time = start_timestamp.replace(hour=crossover_hour, minute=crossover_minute)
    if target_time <= start_timestamp:
        target_time += pd.Timedelta(days=1)
    
    offset_minutes = (target_time - start_timestamp).total_seconds() / 60
    timestamps = [start_timestamp + pd.Timedelta(minutes=offset_minutes + i) for i in range(total_bars)]
    
    # Create Bar objects using custom helper
    return _create_bars_from_ohlcv_with_timestamps(ohlcv_bars, timestamps, symbol, venue, bar_spec)


def generate_with_volatility_patterns(
    symbol: str,
    venue: str,
    target_atr: float,
    fast_period: int,
    slow_period: int,
    total_bars: int,
    base_price: float,
    bar_spec: str,
    start_date: str
) -> List[Bar]:
    """
    Generate data with controlled ATR (Average True Range) values.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        target_atr: Target ATR value
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with controlled volatility
    """
    # Generate price series with controlled volatility
    close_prices = []
    current_price = base_price
    
    for i in range(total_bars):
        # Generate price movement with controlled volatility
        movement = np.random.normal(0, target_atr / 4)  # Scale to achieve target ATR
        current_price += movement
        close_prices.append(current_price)
    
    # Convert to OHLCV with controlled ranges for ATR
    ohlcv_bars = []
    prev_close = base_price
    
    for i, close_price in enumerate(close_prices):
        # Open price
        open_price = prev_close
        
        # Control high/low ranges to achieve target ATR
        range_size = target_atr * np.random.uniform(0.8, 1.2)
        high_price = max(open_price, close_price) + range_size / 2
        low_price = min(open_price, close_price) - range_size / 2
        
        # Volume (with decimal precision)
        volume = round(np.random.uniform(1000, 10001), 2)
        
        ohlcv_bars.append((open_price, high_price, low_price, close_price, volume))
        prev_close = close_price
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_with_adx_patterns(
    symbol: str,
    venue: str,
    target_adx: float,
    fast_period: int,
    slow_period: int,
    total_bars: int,
    base_price: float,
    bar_spec: str,
    start_date: str
) -> List[Bar]:
    """
    Generate data with controlled ADX (trend strength) values.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        target_adx: Target ADX value
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with controlled trend strength
    """
    # Generate price series with controlled trend strength
    close_prices = []
    current_price = base_price
    
    if target_adx > 25:  # Strong trend
        # Generate consistent directional movement
        trend_direction = 1 if np.random.random() > 0.5 else -1
        for i in range(total_bars):
            movement = trend_direction * 0.0005 + np.random.normal(0, 0.0001)
            current_price += movement
            close_prices.append(current_price)
    else:  # Weak trend/ranging
        # Generate choppy, ranging movement
        for i in range(total_bars):
            movement = np.random.normal(0, 0.0002)
            current_price += movement
            close_prices.append(current_price)
    
    # Convert to OHLCV with appropriate directional movement
    ohlcv_bars = []
    prev_close = base_price
    
    for i, close_price in enumerate(close_prices):
        # Open price
        open_price = prev_close
        
        # Generate high/low with trend strength
        if target_adx > 25:  # Strong trend
            # Consistent directional movement
            if close_price > open_price:  # Uptrend bar
                high_price = close_price + np.random.uniform(0, 0.0003)
                low_price = open_price - np.random.uniform(0, 0.0001)
            else:  # Downtrend bar
                high_price = open_price + np.random.uniform(0, 0.0001)
                low_price = close_price - np.random.uniform(0, 0.0003)
        else:  # Weak trend
            # Random high/low ranges
            high_price = max(open_price, close_price) + np.random.uniform(0, 0.0002)
            low_price = min(open_price, close_price) - np.random.uniform(0, 0.0002)
        
        # Volume (with decimal precision)
        volume = round(np.random.uniform(1000, 10001), 2)
        
        ohlcv_bars.append((open_price, high_price, low_price, close_price, volume))
        prev_close = close_price
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_multiple_crossovers(
    symbol: str,
    venue: str,
    crossover_count: int,
    fast_period: int,
    slow_period: int,
    bars_between_crossovers: int,
    base_price: float,
    bar_spec: str,
    start_date: str
) -> Tuple[List[Bar], List[float]]:
    """
    Generate data with multiple alternating crossovers.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        crossover_count: Number of crossovers to generate
        fast_period: Fast MA period
        slow_period: Slow MA period
        bars_between_crossovers: Bars between each crossover
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        Tuple of (List of Bar objects with multiple crossovers, List of close prices)
    """
    # Calculate total bars needed
    total_bars = crossover_count * bars_between_crossovers + slow_period
    
    # Generate price series with multiple crossovers
    close_prices = []
    current_price = base_price
    
    for i in range(total_bars):
        # Generate alternating price movements for crossovers
        if i % bars_between_crossovers == 0 and i >= slow_period:
            # Crossover point - generate strong movement
            movement = 0.002 if (i // bars_between_crossovers) % 2 == 0 else -0.002
        else:
            # Normal price movement
            movement = np.random.normal(0, 0.0002)
        
        current_price += movement
        close_prices.append(current_price)
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Create Bar objects using common helper
    bars = _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)
    return bars, close_prices


def generate_no_crossover(
    symbol: str,
    venue: str,
    fast_period: int,
    slow_period: int,
    total_bars: int,
    base_price: float,
    bar_spec: str,
    start_date: str,
    relative_offset: float = 0.001
) -> List[Bar]:
    """
    Generate data with no crossover - fast MA remains constant offset from slow MA.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars to generate
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        relative_offset: Constant offset between fast and slow MA
        
    Returns:
        List of Bar objects with no crossover pattern
    """
    # Generate close prices where fast MA maintains constant offset from slow MA
    close_prices = []
    current_price = base_price
    
    for i in range(total_bars):
        # Generate price with minimal drift and noise to maintain separation
        drift = relative_offset / 100  # Small drift to maintain separation
        noise = np.random.normal(0, 0.00001)  # Minimal noise
        current_price += drift + noise
        close_prices.append(current_price)
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Verify no crossover by calculating SMAs
    if len(close_prices) >= slow_period:
        fast_sma_values = []
        slow_sma_values = []
        
        for i in range(slow_period - 1, len(close_prices)):
            if i >= fast_period - 1:
                fast_sma = sum(close_prices[i - fast_period + 1:i + 1]) / fast_period
                fast_sma_values.append(fast_sma)
            else:
                fast_sma_values.append(None)
            
            slow_sma = sum(close_prices[i - slow_period + 1:i + 1]) / slow_period
            slow_sma_values.append(slow_sma)
        
        # Assert no crossover occurred
        for i in range(len(fast_sma_values)):
            if fast_sma_values[i] is not None:
                assert fast_sma_values[i] > slow_sma_values[i], f"Crossover detected at bar {i + slow_period - 1}: fast_sma={fast_sma_values[i]}, slow_sma={slow_sma_values[i]}"
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_circuit_breaker_scenario(
    symbol: str,
    venue: str,
    losing_trade_count: int,
    fast_period: int,
    slow_period: int,
    base_price: float,
    bar_spec: str,
    start_date: str
) -> List[Bar]:
    """
    Generate data that triggers circuit breaker (consecutive losses).
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        losing_trade_count: Number of losing trades to generate
        fast_period: Fast MA period
        slow_period: Slow MA period
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with circuit breaker scenario
    """
    # Calculate total bars needed (space for each losing trade)
    bars_per_trade = 50  # Enough bars for MA crossover and trade completion
    total_bars = losing_trade_count * bars_per_trade + slow_period
    
    # Generate price series with losing trade patterns
    close_prices = []
    current_price = base_price
    
    for trade_num in range(losing_trade_count):
        # Generate bullish crossover followed by price drop (losing trade)
        for i in range(bars_per_trade):
            bar_index = trade_num * bars_per_trade + i
            
            if i < 20:  # Build up to crossover
                movement = 0.0001 + np.random.normal(0, 0.0001)
            elif i == 20:  # Crossover point
                movement = 0.0005  # Strong bullish movement
            elif i < 30:  # Initial price rise
                movement = 0.0002 + np.random.normal(0, 0.0001)
            else:  # Price reversal (stop loss hit)
                movement = -0.0008 + np.random.normal(0, 0.0001)
            
            current_price += movement
            close_prices.append(current_price)
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def write_to_catalog(
    bars: List[Bar],
    symbol: str,
    venue: str,
    catalog_path: str,
    bar_spec: str
) -> bool:
    """
    Save generated bars to ParquetDataCatalog for backtest consumption.
    
    Args:
        bars: List of Bar objects to save
        symbol: Instrument symbol
        venue: Trading venue
        catalog_path: Path to catalog directory
        bar_spec: Bar specification string
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create ParquetDataCatalog instance
        catalog = ParquetDataCatalog(catalog_path)
        
        # Create instrument
        instrument = create_instrument(symbol, venue)
        
        # Register instrument
        catalog.write_data([instrument])
        
        # Write bars
        catalog.write_data(bars, skip_disjoint_check=True)
        
        print(f"Successfully wrote {len(bars)} bars to catalog at {catalog_path}")
        return True
        
    except Exception as e:
        print(f"Error writing to catalog: {e}")
        return False


def generate_choppy_market(
    symbol: str,
    venue: str,
    crossover_count: int = 10,
    bars_between_crossovers: int = 5,
    small_separation: float = 0.00003,
    fast_period: int = 10,
    slow_period: int = 20,
    total_bars: int = 300,
    base_price: float = 1.08000,
    bar_spec: str = "1-MINUTE-MID-EXTERNAL",
    start_date: str = "2024-01-01"
) -> List[Bar]:
    """
    Generate price action with frequent small MA crossovers (whipsaw pattern).
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        crossover_count: Number of rapid crossovers to generate
        bars_between_crossovers: Bars between each crossover
        small_separation: Minimal separation between MAs (0.3 pips)
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with choppy market pattern
    """
    # Generate price series with rapid alternating crossovers
    close_prices = []
    current_price = base_price
    
    for i in range(total_bars):
        # Generate alternating price movements for crossovers
        if i % bars_between_crossovers == 0 and i >= slow_period:
            # Crossover point - generate small alternating movement
            movement = small_separation if (i // bars_between_crossovers) % 2 == 0 else -small_separation
        else:
            # Normal price movement with minimal noise
            movement = np.random.normal(0, small_separation / 2)
        
        current_price += movement
        close_prices.append(current_price)
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices, volatility=small_separation)
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_whipsaw_pattern(
    symbol: str,
    venue: str,
    crossover_bar: int = 100,
    reversal_bars_after: int = 2,
    fast_period: int = 10,
    slow_period: int = 20,
    total_bars: int = 300,
    base_price: float = 1.08000,
    bar_spec: str = "1-MINUTE-MID-EXTERNAL",
    start_date: str = "2024-01-01"
) -> List[Bar]:
    """
    Generate crossover followed by immediate reversal within 2-3 bars.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        crossover_bar: Bar where first crossover occurs
        reversal_bars_after: Bars after crossover when reversal occurs
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with whipsaw pattern
    """
    # Generate price series with controlled whipsaw pattern
    close_prices = []
    current_price = base_price
    
    for i in range(total_bars):
        if i < crossover_bar:
            # Build up to first crossover
            movement = 0.0001 + np.random.normal(0, 0.00001)
        elif i == crossover_bar:
            # First crossover - bullish movement
            movement = 0.0005
        elif i < crossover_bar + reversal_bars_after:
            # Brief continuation
            movement = 0.0002 + np.random.normal(0, 0.00001)
        elif i == crossover_bar + reversal_bars_after:
            # Reversal - bearish movement
            movement = -0.0008
        else:
            # Normal price movement
            movement = np.random.normal(0, 0.0001)
        
        current_price += movement
        close_prices.append(current_price)
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_threshold_boundary_crossover(
    symbol: str,
    venue: str,
    threshold_pips: float = 1.0,
    separation_offset_pips: float = 0.0,
    fast_period: int = 10,
    slow_period: int = 20,
    total_bars: int = 300,
    base_price: float = 1.08000,
    bar_spec: str = "1-MINUTE-MID-EXTERNAL",
    start_date: str = "2024-01-01"
) -> List[Bar]:
    """
    Generate crossover with separation exactly at or very close to threshold.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        threshold_pips: Threshold in pips (e.g., 1.0)
        separation_offset_pips: Offset from threshold (e.g., -0.01, 0.0, +0.01)
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with threshold boundary pattern
    """
    # Calculate exact separation
    separation = (threshold_pips + separation_offset_pips) * 0.0001  # Convert pips to price
    
    # Generate price series with exact threshold separation
    close_prices = []
    current_price = base_price
    
    for i in range(total_bars):
        if i < 50:
            # Build up to crossover with exact separation
            movement = 0.0001 + np.random.normal(0, 0.00001)
        elif i == 50:
            # Crossover with exact threshold separation
            movement = separation
        else:
            # Normal price movement
            movement = np.random.normal(0, 0.0001)
        
        current_price += movement
        close_prices.append(current_price)
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_delayed_crossover(
    symbol: str,
    venue: str,
    convergence_bars: int = 20,
    crossover_bar: int = 100,
    fast_period: int = 10,
    slow_period: int = 20,
    total_bars: int = 300,
    base_price: float = 1.08000,
    bar_spec: str = "1-MINUTE-MID-EXTERNAL",
    start_date: str = "2024-01-01"
) -> Tuple[List[Bar], List[float]]:
    """
    Generate slow-developing crossover where MAs converge gradually over many bars.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        convergence_bars: Bars over which MAs converge
        crossover_bar: Bar where crossover finally occurs
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        Tuple of (List of Bar objects with delayed crossover pattern, List of close prices)
    """
    # Generate price series with gradual MA convergence
    close_prices = []
    current_price = base_price
    
    for i in range(total_bars):
        if i < crossover_bar - convergence_bars:
            # Initial separation
            movement = 0.0001 + np.random.normal(0, 0.00001)
        elif i < crossover_bar:
            # Gradual convergence over convergence_bars
            progress = (i - (crossover_bar - convergence_bars)) / convergence_bars
            movement = 0.0001 * (1 - progress) + np.random.normal(0, 0.00001)
        elif i == crossover_bar:
            # Final crossover
            movement = 0.0002
        else:
            # Normal price movement
            movement = np.random.normal(0, 0.0001)
        
        current_price += movement
        close_prices.append(current_price)
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Create Bar objects using common helper
    bars = _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)
    return bars, close_prices


def generate_false_breakout(
    symbol: str,
    venue: str,
    spike_bar: int = 100,
    spike_magnitude: float = 0.0050,
    revert_bars: int = 3,
    fast_period: int = 10,
    slow_period: int = 20,
    total_bars: int = 300,
    base_price: float = 1.08000,
    bar_spec: str = "1-MINUTE-MID-EXTERNAL",
    start_date: str = "2024-01-01"
) -> List[Bar]:
    """
    Generate price spike that causes temporary MA crossover, then reverts.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        spike_bar: Bar where price spike occurs
        spike_magnitude: Magnitude of price spike (50 pips)
        revert_bars: Bars after spike when price reverts
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with false breakout pattern
    """
    # Generate price series with false breakout pattern
    close_prices = []
    current_price = base_price
    
    for i in range(total_bars):
        if i < spike_bar:
            # Normal price movement before spike
            movement = np.random.normal(0, 0.0001)
        elif i == spike_bar:
            # Price spike causing temporary crossover
            movement = spike_magnitude
        elif i < spike_bar + revert_bars:
            # Gradual reversion
            movement = -spike_magnitude / revert_bars + np.random.normal(0, 0.0001)
        else:
            # Normal price movement after reversion
            movement = np.random.normal(0, 0.0001)
        
        current_price += movement
        close_prices.append(current_price)
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_no_trade_zone(
    symbol: str,
    venue: str,
    ma_separation: float = 0.00005,
    fast_period: int = 10,
    slow_period: int = 20,
    total_bars: int = 300,
    base_price: float = 1.08000,
    bar_spec: str = "1-MINUTE-MID-EXTERNAL",
    start_date: str = "2024-01-01"
) -> List[Bar]:
    """
    Generate price action where MAs are close but never cross (parallel within threshold).
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        ma_separation: Constant separation between MAs (0.5 pips)
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with no-trade zone pattern
    """
    # Generate price series maintaining constant MA separation
    close_prices = []
    current_price = base_price
    
    for i in range(total_bars):
        # Generate price with minimal drift to maintain separation
        drift = ma_separation / 1000  # Very small drift
        noise = np.random.normal(0, ma_separation / 10)  # Minimal noise
        movement = drift + noise
        
        current_price += movement
        close_prices.append(current_price)
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices, volatility=ma_separation / 5)
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_filter_cascade_failure(
    symbol: str,
    venue: str,
    pass_filters: List[str],
    fail_filters: List[str],
    fast_period: int = 10,
    slow_period: int = 20,
    total_bars: int = 300,
    base_price: float = 1.08000,
    bar_spec: str = "1-MINUTE-MID-EXTERNAL",
    start_date: str = "2024-01-01"
) -> List[Bar]:
    """
    Generate crossover that passes some filters but fails others in specific order.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        pass_filters: List of filters that should pass
        fail_filters: List of filters that should fail
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with filter cascade failure pattern
    """
    # Generate basic crossover pattern
    crossover_bar = total_bars // 2
    close_prices = _generate_ma_prices(
        fast_period, slow_period, total_bars, crossover_bar,
        "bullish", 0.001, 0.002, base_price
    )
    
    # Convert to OHLCV with patterns for specific filters
    ohlcv_bars = []
    prev_close = base_price
    
    for i, close_price in enumerate(close_prices):
        # Open price
        open_price = prev_close
        
        # Generate high/low based on filter requirements
        if "dmi" in fail_filters:
            # Create weak trend for DMI failure
            high_price = max(open_price, close_price) + np.random.uniform(0, 0.0001)
            low_price = min(open_price, close_price) - np.random.uniform(0, 0.0001)
        elif "stoch" in fail_filters:
            # Create unfavorable stochastic conditions
            high_price = max(open_price, close_price) + np.random.uniform(0.0002, 0.0005)
            low_price = min(open_price, close_price) - np.random.uniform(0, 0.0001)
        elif "atr" in fail_filters:
            # Create low volatility for ATR failure
            high_price = max(open_price, close_price) + np.random.uniform(0, 0.00005)
            low_price = min(open_price, close_price) - np.random.uniform(0, 0.00005)
        else:
            # Normal ranges
            high_price = max(open_price, close_price) + np.random.uniform(0, 0.0002)
            low_price = min(open_price, close_price) - np.random.uniform(0, 0.0002)
        
        # Volume (with decimal precision)
        volume = round(np.random.uniform(1000, 10001), 2)
        
        ohlcv_bars.append((open_price, high_price, low_price, close_price, volume))
        prev_close = close_price
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


def generate_ma_lag_test(
    symbol: str,
    venue: str,
    trend_start_bar: int = 50,
    trend_strength: float = 0.0010,
    trend_duration: int = 30,
    fast_period: int = 10,
    slow_period: int = 20,
    total_bars: int = 300,
    base_price: float = 1.08000,
    bar_spec: str = "1-MINUTE-MID-EXTERNAL",
    start_date: str = "2024-01-01"
) -> List[Bar]:
    """
    Generate strong trend with delayed MA crossover to measure lag.
    
    Args:
        symbol: Instrument symbol
        venue: Trading venue
        trend_start_bar: Bar where strong trend begins
        trend_strength: Strength of trend (10 pips per bar)
        trend_duration: Duration of strong trend
        fast_period: Fast MA period
        slow_period: Slow MA period
        total_bars: Total number of bars
        base_price: Base price level
        bar_spec: Bar specification string
        start_date: Start date string
        
    Returns:
        List of Bar objects with MA lag test pattern
    """
    # Generate price series with strong trend
    close_prices = []
    current_price = base_price
    
    for i in range(total_bars):
        if i < trend_start_bar:
            # Normal price movement before trend
            movement = np.random.normal(0, 0.0001)
        elif i < trend_start_bar + trend_duration:
            # Strong uptrend
            movement = trend_strength + np.random.normal(0, 0.0001)
        else:
            # Normal price movement after trend
            movement = np.random.normal(0, 0.0001)
        
        current_price += movement
        close_prices.append(current_price)
    
    # Convert to OHLCV
    ohlcv_bars = _prices_to_ohlcv(close_prices)
    
    # Create Bar objects using common helper
    return _create_bars_from_ohlcv(ohlcv_bars, symbol, venue, bar_spec, start_date, total_bars)


# Diagnostic scenarios configuration
DIAGNOSTIC_SCENARIOS = {
    "choppy_market": {
        "generator": generate_choppy_market,
        "expected_trades": 10,
        "expected_outcome": "mixed",
        "purpose": "Test behavior in ranging market with frequent small crossovers"
    },
    "whipsaw_pattern": {
        "generator": generate_whipsaw_pattern,
        "expected_trades": 2,
        "expected_outcome": "mixed",
        "purpose": "Test handling of immediate signal reversals"
    },
    "threshold_boundary": {
        "generator": generate_threshold_boundary_crossover,
        "expected_trades": 1,
        "expected_outcome": "pass",
        "purpose": "Test boundary condition handling for crossover threshold"
    },
    "delayed_crossover": {
        "generator": generate_delayed_crossover,
        "expected_trades": 1,
        "expected_outcome": "pass",
        "purpose": "Test crossover detection timing with slow MA convergence"
    },
    "false_breakout": {
        "generator": generate_false_breakout,
        "expected_trades": 0,
        "expected_outcome": "reject",
        "purpose": "Test resilience to price spikes causing temporary crossovers"
    },
    "no_trade_zone": {
        "generator": generate_no_trade_zone,
        "expected_trades": 0,
        "expected_outcome": "reject",
        "purpose": "Test that strategy doesn't generate false signals when MAs are close but not crossing"
    },
    "filter_cascade_failure": {
        "generator": generate_filter_cascade_failure,
        "expected_trades": 0,
        "expected_outcome": "reject",
        "purpose": "Test filter cascade logic and rejection reason accuracy"
    },
    "ma_lag_test": {
        "generator": generate_ma_lag_test,
        "expected_trades": 1,
        "expected_outcome": "pass",
        "purpose": "Quantify inherent MA lag in trending markets"
    }
}


def get_diagnostic_scenario_config(scenario_name: str) -> dict:
    """
    Get configuration for a diagnostic scenario.
    
    Args:
        scenario_name: Name of the diagnostic scenario
        
    Returns:
        Dictionary with scenario configuration
    """
    return DIAGNOSTIC_SCENARIOS.get(scenario_name, {})


def generate_test_dataset(
    test_name: str,
    generator_func: callable,
    generator_params: dict,
    catalog_path: str
) -> Optional[str]:
    """
    High-level wrapper to generate complete test dataset and save to catalog.
    
    Args:
        test_name: Name of the test scenario
        generator_func: Generator function to call
        generator_params: Parameters for generator function
        catalog_path: Path to catalog directory
        
    Returns:
        Catalog path if successful, None otherwise
    """
    try:
        # Generate bars
        bars = generator_func(**generator_params)
        
        # Extract symbol, venue, bar_spec from params
        symbol = generator_params.get('symbol', DEFAULT_FOREX_SYMBOL)
        venue = generator_params.get('venue', DEFAULT_FOREX_VENUE)
        bar_spec = generator_params.get('bar_spec', DEFAULT_BAR_SPEC)
        
        # Save to catalog
        success = write_to_catalog(bars, symbol, venue, catalog_path, bar_spec)
        
        if success:
            print(f"Generated test dataset '{test_name}' with {len(bars)} bars")
            return catalog_path
        else:
            return None
            
    except Exception as e:
        print(f"Error generating test dataset '{test_name}': {e}")
        return None
