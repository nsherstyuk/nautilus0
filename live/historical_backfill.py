"""
Historical data backfill module for live trading.

Calculates required historical data based on strategy warmup requirements,
requests data from IBKR API, and feeds it to the strategy before live trading starts.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple
from pathlib import Path

import pandas as pd

from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model.data import Bar, BarType, BarSpecification, BarAggregation
from nautilus_trader.model.enums import PriceType, AggregationSource
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.adapters.interactive_brokers.common import IB_VENUE
from nautilus_trader.adapters.interactive_brokers.data import InteractiveBrokersDataClient


logger = logging.getLogger("live")


def calculate_required_bars(slow_period: int, bar_spec: str) -> int:
    """
    Calculate the number of bars required for warmup.
    
    Args:
        slow_period: The slowest indicator period (e.g., slow SMA period)
        bar_spec: Bar specification string (e.g., "15-MINUTE-MID-EXTERNAL")
    
    Returns:
        Number of bars required, with 20% buffer for safety
    """
    # Add 20% buffer to ensure we have enough data
    required_bars = int(slow_period * 1.2)
    return max(required_bars, slow_period)


def calculate_required_duration_hours(slow_period: int, bar_spec: str) -> float:
    """
    Calculate the required duration in hours based on bar specification.
    
    Args:
        slow_period: The slowest indicator period
        bar_spec: Bar specification string (e.g., "15-MINUTE-MID-EXTERNAL")
    
    Returns:
        Required duration in hours
    """
    required_bars = calculate_required_bars(slow_period, bar_spec)
    
    # Parse bar spec to get minutes per bar
    bar_spec_upper = bar_spec.upper()
    if "MINUTE" in bar_spec_upper:
        # Extract minutes (e.g., "15-MINUTE" -> 15)
        parts = bar_spec_upper.split("-")
        try:
            minutes_per_bar = int(parts[0])
        except (ValueError, IndexError):
            logger.warning(f"Could not parse minutes from bar_spec {bar_spec}, defaulting to 15")
            minutes_per_bar = 15
    elif "HOUR" in bar_spec_upper:
        # Extract hours (e.g., "1-HOUR" -> 1)
        parts = bar_spec_upper.split("-")
        try:
            hours_per_bar = int(parts[0])
            minutes_per_bar = hours_per_bar * 60
        except (ValueError, IndexError):
            logger.warning(f"Could not parse hours from bar_spec {bar_spec}, defaulting to 1 hour")
            minutes_per_bar = 60
    elif "DAY" in bar_spec_upper:
        # Daily bars
        minutes_per_bar = 24 * 60
    else:
        logger.warning(f"Unknown bar_spec format {bar_spec}, defaulting to 15 minutes")
        minutes_per_bar = 15
    
    total_minutes = required_bars * minutes_per_bar
    theoretical_hours = total_minutes / 60.0
    
    # Add buffer for weekends and market closures (FX markets close weekends)
    # For 3+ days of data, add ~40% buffer to account for weekends
    if theoretical_hours >= 72:  # 3+ days
        buffer_multiplier = 1.4  # 40% buffer for weekends
    else:
        buffer_multiplier = 1.2  # 20% buffer for smaller requests
    
    total_hours = theoretical_hours * buffer_multiplier
    
    logger.debug(
        f"Duration calculation: required_bars={required_bars}, "
        f"theoretical_hours={theoretical_hours:.2f}, "
        f"buffer_multiplier={buffer_multiplier}, "
        f"total_hours={total_hours:.2f}"
    )
    
    return total_hours


def calculate_required_duration_days(slow_period: int, bar_spec: str) -> float:
    """
    Calculate the required duration in days.
    
    Args:
        slow_period: The slowest indicator period
        bar_spec: Bar specification string
    
    Returns:
        Required duration in days
    """
    hours = calculate_required_duration_hours(slow_period, bar_spec)
    return hours / 24.0


def _calculate_chunk_size_days(bar_spec: str) -> float:
    """
    Calculate maximum days per IBKR request based on bar specification.
    
    IBKR has documented limits and practical timeout thresholds:
    - 1-MINUTE: 7 days (practical limit to avoid timeouts)
    - 5-MINUTE: 30 days
    - 15-MINUTE: 60 days (official limit, but practical limit may be lower)
    - 30-MINUTE: 120 days
    - 1-HOUR: 365 days
    - 1-DAY: math.inf (unlimited - no chunking needed)
    
    For 15-minute bars, IBKR may return fewer bars than requested due to:
    - Market hours (FX markets close weekends)
    - Data availability gaps
    - Practical limits (~200-300 bars per request)
    
    Args:
        bar_spec: Bar specification string (e.g., "15-MINUTE-MID-EXTERNAL")
        
    Returns:
        Maximum days per request chunk (float)
    """
    spec_upper = bar_spec.upper()
    
    # Check patterns in order of specificity (most specific first)
    # Check for 15-MINUTE first (before 5-MINUTE to avoid partial matches)
    if "15-MINUTE" in spec_upper or "15-MIN" in spec_upper:
        # Conservative: Use 2 days per chunk to avoid hitting bar count limits
        # This ensures we get ~192 bars per chunk (2 days * 24 hours * 4 bars/hour)
        chunk_size = 2.0
        logger.debug(f"Matched 15-MINUTE pattern in '{bar_spec}', chunk_size={chunk_size} days")
        return chunk_size
    elif "30-MINUTE" in spec_upper or "30-MIN" in spec_upper:
        chunk_size = 120.0
        logger.debug(f"Matched 30-MINUTE pattern in '{bar_spec}', chunk_size={chunk_size} days")
        return chunk_size
    elif "1-MINUTE" in spec_upper or "1-MIN" in spec_upper:
        chunk_size = 7.0
        logger.debug(f"Matched 1-MINUTE pattern in '{bar_spec}', chunk_size={chunk_size} days")
        return chunk_size
    elif "2-MINUTE" in spec_upper or "2-MIN" in spec_upper:
        chunk_size = 30.0
        logger.debug(f"Matched 2-MINUTE pattern in '{bar_spec}', chunk_size={chunk_size} days")
        return chunk_size
    elif "5-MINUTE" in spec_upper or "5-MIN" in spec_upper:
        chunk_size = 30.0
        logger.debug(f"Matched 5-MINUTE pattern in '{bar_spec}', chunk_size={chunk_size} days")
        return chunk_size
    elif "1-HOUR" in spec_upper or "1-HR" in spec_upper or "HOUR" in spec_upper:
        chunk_size = 365.0
        logger.debug(f"Matched HOUR pattern in '{bar_spec}', chunk_size={chunk_size} days")
        return chunk_size
    elif "1-DAY" in spec_upper or "DAILY" in spec_upper or "DAY" in spec_upper:
        chunk_size = math.inf
        logger.debug(f"Matched DAY pattern in '{bar_spec}', chunk_size=unlimited")
        return chunk_size
    else:
        # Conservative default for unknown bar types
        logger.warning(f"Unknown bar spec '{bar_spec}', using conservative 2-day chunk size")
        return 2.0


def _chunk_duration_hours(duration_hours: float, chunk_size_days: float) -> List[Tuple[float, pd.Timestamp]]:
    """
    Split a duration into chunks, working backwards from end_time.
    
    Creates sequential non-overlapping chunks. Each chunk's end_time is the start_time
    of the next chunk (when going backwards in time), ensuring no overlap.
    
    IBKR historical data API behavior:
    - When requesting data with end_date_time=X and duration=Y, IBKR returns bars
      that may include/exclude the exact end_time boundary inconsistently
    - To prevent overlap, we ensure chunks are truly sequential with no shared boundaries
    
    Chunking strategy:
    - Start from NOW - 1h (to avoid incomplete recent data) and work backwards
    - Each chunk's end_time becomes the start_time of the previous chunk
    - Chunks are sequential: chunk N ends where chunk N+1 starts
    
    Example for 81 hours with 48-hour chunks:
    - Chunk 1 (oldest): end_time = NOW - 81h - 1h, duration = 48h
      → gets data from (NOW-130h) to (NOW-82h)
    - Chunk 2: end_time = NOW - 34h, duration = 48h
      → gets data from (NOW-82h) to (NOW-34h)
    - Chunk 3 (newest): end_time = NOW - 1h, duration = 17h
      → gets data from (NOW-18h) to (NOW-1h)
    
    Args:
        duration_hours: Total duration to request in hours
        chunk_size_days: Maximum days per chunk
        
    Returns:
        List of (chunk_duration_hours, chunk_end_time) tuples, oldest first
    """
    if math.isinf(chunk_size_days):
        # No chunking needed - end 1 hour ago to avoid incomplete data
        end_time = pd.Timestamp.now(tz=timezone.utc) - pd.Timedelta(hours=1)
        return [(duration_hours, end_time)]
    
    chunk_size_hours = chunk_size_days * 24.0
    chunks = []
    
    # End 1 hour ago to avoid requesting incomplete recent data
    current_end_time = pd.Timestamp.now(tz=timezone.utc) - pd.Timedelta(hours=1)
    remaining_hours = duration_hours
    
    # Build chunks from newest to oldest (then reverse)
    # This ensures each chunk's end_time is the start_time of the previous chunk
    temp_chunks = []
    while remaining_hours > 0:
        chunk_duration = min(remaining_hours, chunk_size_hours)
        
        # Calculate start time for this chunk (working backwards)
        chunk_start_time = current_end_time - pd.Timedelta(hours=chunk_duration)
        
        # Store chunk with its end_time
        temp_chunks.append((chunk_duration, current_end_time))
        
        # Next chunk ends where this one starts (no overlap)
        current_end_time = chunk_start_time
        remaining_hours -= chunk_duration
    
    # Reverse to get oldest-first order
    temp_chunks.reverse()
    return temp_chunks


def format_duration_string(hours: float) -> str:
    """
    Format duration in IBKR-compatible format.
    
    IBKR accepts: S (seconds), D (days), W (weeks), M (months), Y (years)
    IBKR does NOT accept: H (hours)
    
    Args:
        hours: Duration in hours
    
    Returns:
        IBKR duration string (e.g., "3 D", "86400 S")
    """
    if hours >= 24:
        # Convert to days
        days = int(hours / 24)
        return f"{days} D"
    else:
        # Convert to seconds (minimum 30 seconds as per IBKR requirement)
        seconds = int(hours * 3600)
        seconds = max(30, seconds)  # IBKR minimum is 30 seconds
        return f"{seconds} S"


async def check_existing_bars(
    data_client: InteractiveBrokersDataClient,
    instrument_id: InstrumentId,
    bar_type: BarType,
    required_count: int,
) -> Tuple[bool, int]:
    """
    Check if enough historical bars exist in the cache.
    
    Args:
        data_client: IBKR data client
        instrument_id: Instrument ID
        bar_type: Bar type to check
        required_count: Number of bars required
    
    Returns:
        Tuple of (has_enough, actual_count)
    """
    try:
        # Try to get bars from cache
        # Note: This is a simplified check - in practice, you'd query the cache
        # For now, we'll assume we need to fetch if this is the first run
        return False, 0
    except Exception as e:
        logger.debug(f"Error checking existing bars: {e}")
        return False, 0


def aggregate_bars(
    minute_bars: List[Bar],
    target_bar_type: BarType,
    aggregation_factor: int = 15,
) -> List[Bar]:
    """
    Aggregate 1-minute bars into higher timeframe bars (e.g., 15-minute).
    
    Bars are aggregated into time-aligned buckets (e.g., 00:00-00:14, 00:15-00:29, etc.)
    to match standard bar boundaries.
    
    Args:
        minute_bars: List of 1-minute bars to aggregate (must be sorted by timestamp)
        target_bar_type: Target BarType for the aggregated bars
        aggregation_factor: Number of minute bars per aggregated bar (e.g., 15 for 15-minute bars)
    
    Returns:
        List of aggregated bars sorted by timestamp
    """
    if not minute_bars:
        return []
    
    # Ensure bars are sorted by timestamp
    minute_bars = sorted(minute_bars, key=lambda x: x.ts_event)
    
    # Group bars by time-aligned buckets
    buckets = {}  # bucket_start_timestamp -> list of bars
    
    for bar in minute_bars:
        # Convert timestamp to pandas Timestamp for easier manipulation
        bar_time = pd.Timestamp(bar.ts_event, tz=timezone.utc)
        
        # Calculate bucket start time (aligned to aggregation_factor minutes)
        minutes_since_hour = bar_time.minute
        bucket_minute = (minutes_since_hour // aggregation_factor) * aggregation_factor
        
        # Create bucket start time
        bucket_start = bar_time.replace(minute=bucket_minute, second=0, microsecond=0)
        bucket_start_ns = dt_to_unix_nanos(bucket_start)
        
        if bucket_start_ns not in buckets:
            buckets[bucket_start_ns] = []
        buckets[bucket_start_ns].append(bar)
    
    # Aggregate each bucket into a single bar
    aggregated = []
    
    # Get price precision from the first bar
    price_precision = minute_bars[0].open.precision
    
    # Process buckets in chronological order
    for bucket_start_ns in sorted(buckets.keys()):
        bucket_bars = buckets[bucket_start_ns]
        
        if not bucket_bars:
            continue
        
        # Sort bars in bucket by timestamp
        bucket_bars.sort(key=lambda x: x.ts_event)
        
        # Calculate OHLCV for the aggregated bar
        open_price = bucket_bars[0].open.as_double()
        high_price = max(b.high.as_double() for b in bucket_bars)
        low_price = min(b.low.as_double() for b in bucket_bars)
        close_price = bucket_bars[-1].close.as_double()
        total_volume = sum(b.volume.as_double() for b in bucket_bars)
        
        # Use the last bar's timestamp (end of the aggregated period)
        ts_event = bucket_bars[-1].ts_event
        
        # Validate OHLCV relationships
        if high_price < max(open_price, close_price):
            high_price = max(open_price, close_price)
        if low_price > min(open_price, close_price):
            low_price = min(open_price, close_price)
        
        # Create Price objects
        open_price_obj = Price.from_str(f"{open_price:.{price_precision}f}")
        high_price_obj = Price.from_str(f"{high_price:.{price_precision}f}")
        low_price_obj = Price.from_str(f"{low_price:.{price_precision}f}")
        close_price_obj = Price.from_str(f"{close_price:.{price_precision}f}")
        
        # Create Quantity object
        volume_obj = Quantity.from_str(f"{total_volume:.2f}")
        
        # Create aggregated bar
        aggregated_bar = Bar(
            bar_type=target_bar_type,
            open=open_price_obj,
            high=high_price_obj,
            low=low_price_obj,
            close=close_price_obj,
            volume=volume_obj,
            ts_event=ts_event,
            ts_init=ts_event,
            is_revision=False,
        )
        
        aggregated.append(aggregated_bar)
    
    # Sort by timestamp
    aggregated.sort(key=lambda x: x.ts_event)
    return aggregated


async def request_historical_bars(
    data_client: InteractiveBrokersDataClient,
    instrument_id: InstrumentId,
    bar_type: BarType,
    duration_hours: float,
    use_rth: bool = False,
    bar_spec: str = "15-MINUTE-MID-EXTERNAL",
) -> List[Bar]:
    """
    Request historical bars from IBKR API, with automatic chunking if needed.
    
    Args:
        data_client: IBKR data client
        instrument_id: Instrument ID
        bar_type: Bar type to request
        duration_hours: Duration in hours to go back
        use_rth: Whether to use regular trading hours (False for FX)
        bar_spec: Bar specification string (for chunking calculation)
    
    Returns:
        List of historical bars
    """
    logger.info(
        f"Requesting historical bars: instrument={instrument_id}, "
        f"bar_type={bar_type}, duration={duration_hours:.2f} hours"
    )
    
    try:
        # Ensure instrument is loaded and in cache first
        cache = data_client._cache
        
        instrument = cache.instrument(instrument_id)
        
        if not instrument:
            # Try to get from instrument provider
            instrument = data_client.instrument_provider.find(instrument_id)
            
            if not instrument:
                logger.info(f"Instrument {instrument_id} not found, loading...")
                # Try to load the instrument
                loaded_ids = await data_client.instrument_provider.load_ids_with_return_async([instrument_id])
                if not loaded_ids:
                    logger.error(f"Failed to load instrument {instrument_id}")
                    return []
                
                # Wait a bit for the instrument to be fully processed
                await asyncio.sleep(1.0)
                instrument = data_client.instrument_provider.find(instrument_id)
                if not instrument:
                    logger.error(f"Instrument {instrument_id} still not available after loading attempt")
                    return []
            
            # Add instrument to cache if not already there
            if instrument and not cache.instrument(instrument_id):
                logger.info(f"Adding instrument {instrument_id} to cache...")
                cache.add_instrument(instrument)
                # Verify it's now in cache
                instrument = cache.instrument(instrument_id)
                if not instrument:
                    logger.error(f"Failed to add instrument {instrument_id} to cache")
                    return []
        
        logger.info(f"Instrument {instrument_id} is in cache")
        
        # Get contract from instrument provider's contract dictionary
        contract = data_client.instrument_provider.contract.get(instrument_id)
        
        # If not found, try to get it using the async method
        if not contract:
            logger.info(f"Contract not in cache for {instrument_id}, fetching...")
            contract = await data_client.instrument_provider.instrument_id_to_ib_contract(instrument_id)
        
        if not contract:
            logger.error(f"Could not get contract for {instrument_id}")
            return []
        
        logger.info(f"Using contract: {contract}")
        
        # Determine if chunking is needed
        chunk_size_days = _calculate_chunk_size_days(bar_spec)
        duration_days = duration_hours / 24.0
        
        logger.info(f"Chunk size calculation: bar_spec='{bar_spec}', chunk_size_days={chunk_size_days}, duration_days={duration_days:.2f}")
        
        if duration_days <= chunk_size_days:
            # Single request - no chunking needed
            logger.info(f"Duration ({duration_days:.2f} days) within chunk limit ({chunk_size_days} days), using single request")
            end_time = pd.Timestamp.now(tz=timezone.utc)
            duration_str = format_duration_string(duration_hours)
            
            bars = await data_client._client.get_historical_bars(
                bar_type=bar_type,
                contract=contract,
                use_rth=use_rth,
                end_date_time=end_time,
                duration=duration_str,
                timeout=120,
            )
            
            logger.info(f"Retrieved {len(bars)} historical bars")
            return bars
        else:
            # Chunking required
            logger.info(
                f"Duration ({duration_days:.2f} days) exceeds chunk limit ({chunk_size_days} days), "
                f"splitting into chunks"
            )
            
            chunks = _chunk_duration_hours(duration_hours, chunk_size_days)
            logger.info(f"Split into {len(chunks)} chunk(s)")
            
            all_bars = []
            
            for chunk_num, (chunk_duration_hours, chunk_end_time) in enumerate(chunks, 1):
                chunk_start_time = chunk_end_time - pd.Timedelta(hours=chunk_duration_hours)
                logger.info(
                    f"Chunk {chunk_num}/{len(chunks)}: Requesting {chunk_duration_hours:.2f} hours "
                    f"(start: {chunk_start_time.isoformat()}, end: {chunk_end_time.isoformat()})"
                )
                
                duration_str = format_duration_string(chunk_duration_hours)
                
                try:
                    chunk_bars = await data_client._client.get_historical_bars(
                        bar_type=bar_type,
                        contract=contract,
                        use_rth=use_rth,
                        end_date_time=chunk_end_time,
                        duration=duration_str,
                        timeout=120,
                    )
                    
                    if chunk_bars:
                        logger.info(f"Chunk {chunk_num}/{len(chunks)}: Retrieved {len(chunk_bars)} bars")
                        all_bars.extend(chunk_bars)
                    else:
                        logger.warning(f"Chunk {chunk_num}/{len(chunks)}: No bars returned")
                    
                    # IBKR pacing: wait between chunks (except last chunk)
                    if chunk_num < len(chunks):
                        delay_seconds = 2  # 2 second delay between chunks
                        logger.info(f"Waiting {delay_seconds}s before next chunk (IBKR pacing)...")
                        await asyncio.sleep(delay_seconds)
                        
                except Exception as chunk_error:
                    logger.error(
                        f"Chunk {chunk_num}/{len(chunks)}: Error requesting bars: {chunk_error}",
                        exc_info=True
                    )
                    # Continue with next chunk
                    continue
            
            # Deduplicate and filter bars
            if all_bars:
                logger.info(f"Processing {len(all_bars)} bars: deduplicating and filtering...")
                
                # Create a map of chunk ranges for filtering
                chunk_ranges = []
                for chunk_num, (chunk_duration_hours, chunk_end_time) in enumerate(chunks, 1):
                    chunk_start_time = chunk_end_time - pd.Timedelta(hours=chunk_duration_hours)
                    chunk_ranges.append((chunk_start_time, chunk_end_time, chunk_num))
                
                # Deduplicate by timestamp and filter by chunk ranges
                seen_timestamps = set()
                deduplicated_bars = []
                bars_out_of_range = 0
                
                for bar in all_bars:
                    bar_time = pd.Timestamp(bar.ts_event, tz=timezone.utc)
                    
                    # Skip if duplicate timestamp
                    if bar.ts_event in seen_timestamps:
                        continue
                    
                    # Check if bar falls within any chunk's range
                    in_range = False
                    for chunk_start, chunk_end, chunk_num in chunk_ranges:
                        # Include bars at chunk boundaries (start inclusive, end inclusive)
                        if chunk_start <= bar_time <= chunk_end:
                            in_range = True
                            break
                    
                    if in_range:
                        seen_timestamps.add(bar.ts_event)
                        deduplicated_bars.append(bar)
                    else:
                        bars_out_of_range += 1
                
                if bars_out_of_range > 0:
                    logger.debug(f"Filtered out {bars_out_of_range} bars outside chunk ranges")
                
                duplicates_removed = len(all_bars) - len(deduplicated_bars)
                if duplicates_removed > 0:
                    logger.info(f"Removed {duplicates_removed} duplicate/out-of-range bars ({duplicates_removed - bars_out_of_range} duplicates, {bars_out_of_range} out-of-range)")
                
                # Sort by timestamp
                deduplicated_bars.sort(key=lambda x: x.ts_event)
                all_bars = deduplicated_bars
            
            logger.info(f"Retrieved {len(all_bars)} total historical bars from {len(chunks)} chunk(s)")
            return all_bars
        
    except Exception as e:
        logger.error(f"Error requesting historical bars: {e}", exc_info=True)
        return []


async def backfill_historical_data(
    data_client: InteractiveBrokersDataClient,
    instrument_id: InstrumentId,
    bar_type: BarType,
    slow_period: int,
    bar_spec: str,
    is_forex: bool = False,
) -> Tuple[bool, int, List[Bar]]:
    """
    Backfill historical data if needed for strategy warmup.
    
    Args:
        data_client: IBKR data client
        instrument_id: Instrument ID
        bar_type: Bar type to backfill
        slow_period: Slowest indicator period
        bar_spec: Bar specification string
        is_forex: Whether this is a forex instrument
    
    Returns:
        Tuple of (success, bars_loaded, bars_list)
    """
    logger.info("=" * 80)
    logger.info("HISTORICAL DATA BACKFILL ANALYSIS")
    logger.info("=" * 80)
    
    # Calculate required data
    required_bars = calculate_required_bars(slow_period, bar_spec)
    duration_hours = calculate_required_duration_hours(slow_period, bar_spec)
    duration_days = calculate_required_duration_days(slow_period, bar_spec)
    
    logger.info(f"Instrument: {instrument_id}")
    logger.info(f"Bar specification: {bar_spec}")
    logger.info(f"Slow indicator period: {slow_period}")
    logger.info(f"Required bars for warmup: {required_bars}")
    logger.info(f"Required duration: {duration_hours:.2f} hours ({duration_days:.2f} days)")
    
    # Check if we have enough existing data
    has_enough, existing_count = await check_existing_bars(
        data_client, instrument_id, bar_type, required_bars
    )
    
    if has_enough:
        logger.info(
            f"[OK] Sufficient historical data already available: {existing_count} bars "
            f"(required: {required_bars})"
        )
        logger.info("=" * 80)
        return True, existing_count, []
    
    logger.info(
        f"[WARN] Historical data backfill required: {existing_count} bars available "
        f"(required: {required_bars})"
    )
    logger.info(f"Requesting {duration_hours:.2f} hours ({duration_days:.2f} days) of historical data...")
    
    # Always request 1-minute bars and aggregate them into target timeframe
    # This is more reliable than requesting higher timeframe bars directly
    use_rth = not is_forex
    
    # Extract bar specification components
    bar_spec_obj = bar_type.spec
    price_type = bar_spec_obj.price_type
    
    # Create 1-minute bar type
    one_min_bar_spec = BarSpecification(1, BarAggregation.MINUTE, price_type)
    one_min_bar_type = BarType(
        instrument_id=instrument_id,
        bar_spec=one_min_bar_spec,
        aggregation_source=AggregationSource.EXTERNAL,
    )
    
    # Calculate how many 1-minute bars we need (with buffer for gaps)
    # For 15-minute bars, we need 15x the number of bars, plus buffer
    # FX markets trade 24/5, but we need extra buffer for:
    # - Weekend gaps (48 hours = 2880 bars)
    # - Market closures/holidays
    # - Data gaps in historical data
    # For 4.72 days, we need ~324 bars × 15 = 4860 bars minimum
    # Adding 70% buffer to account for weekends and gaps: 4860 × 1.7 = 8262 bars
    # This ensures we get enough bars even with weekend gaps
    one_min_bars_needed = required_bars * bar_spec_obj.step * 1.7  # 70% buffer for weekends/gaps
    one_min_duration_hours = (one_min_bars_needed * 1) / 60.0  # 1 minute per bar
    
    logger.info(
        f"Requesting {one_min_duration_hours:.2f} hours of 1-minute bars "
        f"(need ~{int(one_min_bars_needed)} bars to create {required_bars} {bar_spec_obj.step}-minute bars)"
    )
    
    # Request 1-minute bars
    one_min_bars = await request_historical_bars(
        data_client=data_client,
        instrument_id=instrument_id,
        bar_type=one_min_bar_type,
        duration_hours=one_min_duration_hours,
        use_rth=use_rth,
        bar_spec="1-MINUTE-MID-EXTERNAL",  # Use MID for 1-minute bars
    )
    
    if not one_min_bars:
        logger.error("[ERROR] Failed to retrieve 1-minute bars")
        logger.error("=" * 80)
        return False, 0, []
    
    logger.info(f"Retrieved {len(one_min_bars)} 1-minute bars, aggregating into {bar_spec_obj.step}-minute bars...")
    
    # Aggregate 1-minute bars into target timeframe bars
    bars = aggregate_bars(
        minute_bars=one_min_bars,
        target_bar_type=bar_type,
        aggregation_factor=bar_spec_obj.step,
    )
    
    if not bars:
        logger.error("[ERROR] Failed to aggregate 1-minute bars")
        logger.error("=" * 80)
        return False, 0, []
    
    if len(bars) < required_bars:
        logger.warning(
            f"[WARN] Aggregated {len(bars)} bars from {len(one_min_bars)} 1-minute bars, "
            f"but {required_bars} bars are required. Strategy may not warm up immediately."
        )
    else:
        logger.info(
            f"[OK] Successfully aggregated {len(bars)} {bar_spec_obj.step}-minute bars "
            f"from {len(one_min_bars)} 1-minute bars (required: {required_bars})"
        )
    
    logger.info("=" * 80)
    return True, len(bars), bars


async def feed_historical_bars_to_strategy(
    strategy_instance,
    bars: List[Bar],
    bar_type: BarType,
) -> None:
    """
    Feed historical bars to the strategy for warmup.
    
    Args:
        strategy_instance: Strategy instance
        bars: List of historical bars
        bar_type: Bar type being fed
    """
    if not bars:
        logger.warning("No bars to feed to strategy")
        return
    
    logger.info(f"Feeding {len(bars)} historical bars to strategy for warmup...")
    
    for i, bar in enumerate(bars):
        try:
            # Feed bar to strategy
            strategy_instance.on_bar(bar)
            
            if (i + 1) % 50 == 0:
                logger.debug(f"Fed {i + 1}/{len(bars)} bars to strategy")
        except Exception as e:
            logger.error(f"Error feeding bar {i + 1} to strategy: {e}", exc_info=True)
    
    logger.info(f"[OK] Successfully fed {len(bars)} historical bars to strategy")
    
    # Check warmup status and provide detailed summary
    if hasattr(strategy_instance, '_warmup_complete'):
        if strategy_instance._warmup_complete:
            logger.info("[OK] Strategy warmup completed after feeding historical data")
            logger.info("=" * 80)
            logger.info("STRATEGY STATUS: ACTIVE - Strategy is ready to generate trading signals")
            logger.info("=" * 80)
        else:
            bar_count = getattr(strategy_instance, '_bar_count', 0)
            slow_period = getattr(strategy_instance.config, 'slow_period', 'unknown')
            remaining_bars = max(0, slow_period - bar_count) if isinstance(slow_period, int) else 0
            
            logger.warning("=" * 80)
            logger.warning(f"STRATEGY STATUS: WARMING UP")
            logger.warning(f"  - Bars processed: {bar_count}/{slow_period}")
            logger.warning(f"  - Remaining bars needed: {remaining_bars}")
            if remaining_bars > 0:
                # Calculate approximate wait time
                bar_spec = getattr(strategy_instance.config, 'bar_spec', '15-MINUTE-MID-EXTERNAL')
                if '15-MINUTE' in bar_spec.upper():
                    wait_minutes = remaining_bars * 15
                    wait_hours = wait_minutes / 60
                    logger.warning(f"  - Approximate wait time: {wait_minutes} minutes ({wait_hours:.1f} hours)")
                elif '1-MINUTE' in bar_spec.upper():
                    wait_minutes = remaining_bars
                    logger.warning(f"  - Approximate wait time: {wait_minutes} minutes")
                else:
                    logger.warning(f"  - Strategy will continue warming up as live bars arrive")
            logger.warning("  - Strategy will NOT generate signals until warmup completes")
            logger.warning("  - Watch for '[STRATEGY READY]' message in logs when warmup completes")
            logger.warning("=" * 80)

