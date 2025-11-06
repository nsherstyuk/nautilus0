"""
Quick test script for historical data backfill functionality.

This script tests the backfill calculation and logging without requiring
a full IBKR connection or live trading setup.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from live.historical_backfill import (
    calculate_required_bars,
    calculate_required_duration_hours,
    calculate_required_duration_days,
    format_duration_string,
)


def test_backfill_calculations():
    """Test backfill calculations for Phase 6 configuration."""
    print("=" * 80)
    print("HISTORICAL DATA BACKFILL CALCULATION TEST")
    print("=" * 80)
    print()
    
    # Phase 6 configuration
    slow_period = 270
    bar_spec = "15-MINUTE-MID-EXTERNAL"
    
    print(f"Configuration:")
    print(f"  Slow period: {slow_period}")
    print(f"  Bar spec: {bar_spec}")
    print()
    
    # Calculate requirements
    required_bars = calculate_required_bars(slow_period, bar_spec)
    duration_hours = calculate_required_duration_hours(slow_period, bar_spec)
    duration_days = calculate_required_duration_days(slow_period, bar_spec)
    duration_str = format_duration_string(duration_hours)
    
    print(f"Results:")
    print(f"  Required bars: {required_bars}")
    print(f"  Duration: {duration_hours:.2f} hours ({duration_days:.2f} days)")
    print(f"  IBKR duration string: '{duration_str}'")
    print()
    
    # Test with different configurations
    print("=" * 80)
    print("ADDITIONAL TEST CASES")
    print("=" * 80)
    print()
    
    test_cases = [
        (42, "15-MINUTE-MID-EXTERNAL", "Fast period"),
        (270, "15-MINUTE-MID-EXTERNAL", "Slow period (Phase 6)"),
        (20, "1-MINUTE-MID-EXTERNAL", "1-minute bars"),
        (50, "1-HOUR-MID-EXTERNAL", "Hourly bars"),
        (10, "1-DAY-MID-EXTERNAL", "Daily bars"),
    ]
    
    for period, spec, description in test_cases:
        bars = calculate_required_bars(period, spec)
        hours = calculate_required_duration_hours(period, spec)
        days = calculate_required_duration_days(period, spec)
        dur_str = format_duration_string(hours)
        
        print(f"{description}:")
        print(f"  Period: {period}, Bar spec: {spec}")
        print(f"  Required bars: {bars}, Duration: {hours:.2f}h ({days:.2f}d), IBKR format: '{dur_str}'")
        print()


if __name__ == "__main__":
    test_backfill_calculations()

