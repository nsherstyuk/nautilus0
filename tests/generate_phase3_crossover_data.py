"""
Phase 3.1-3.2 Crossover Filter Test Data Generator

This module generates synthetic test data for Phase 3.1-3.2 crossover threshold and 
pre-crossover separation filter tests. It creates 5 test scenarios with predictable 
filter outcomes to verify both trade counts AND rejection reasons in rejected_signals.csv.

Test Scenarios:
1. Threshold Fail: 0.5 pip separation (below 1.0 pip threshold) → 0 trades, rejection
2. Threshold Pass: 1.5 pip separation (above 1.0 pip threshold) → 1 trade, no rejection
3. Separation Once: 2.5 pip separation at bar N-3 (within 5-bar lookback) → 1 trade, no rejection
4. Separation Never: Max 1.5 pip separation (never reached 2.0 pip threshold) → 0 trades, rejection
5. Separation Recent: 2.5 pip separation at bar N-1 (immediate previous bar) → 1 trade, no rejection

Usage: python tests/generate_phase3_crossover_data.py

Note: Run this before executing test_crossover_filters.py
"""

from pathlib import Path
import sys
import logging
from synthetic_data_generator import generate_simple_crossover, generate_with_insufficient_separation, write_to_catalog

# Configuration constants
CATALOG_PATH = "data/test_catalog/phase3_crossover_filters"
VENUE = "IDEALPRO"
BAR_SPEC = "1-MINUTE-MID-EXTERNAL"
BASE_PRICE = 1.08000
FAST_PERIOD = 10
SLOW_PERIOD = 20
TOTAL_BARS = 200
START_DATE = "2024-01-01"


def generate_threshold_fail_scenario():
    """Generate bullish crossover with 0.5 pip separation (below 1.0 pip threshold)"""
    try:
        bars = generate_simple_crossover(
            symbol="TEST-THRESH-FAIL/USD",
            venue=VENUE,
            crossover_type="bullish",
            crossover_bar=100,
            separation_before=0.0020,  # 20 pips, sufficient for pre-crossover check
            separation_after=0.00005,  # 0.5 pips, below 1.0 pip crossover threshold
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        write_to_catalog(bars, "TEST-THRESH-FAIL/USD", VENUE, CATALOG_PATH)
        logging.info(f"✅ Generated threshold fail scenario: {len(bars)} bars")
        return True
    except Exception as e:
        logging.error(f"❌ Failed to generate threshold fail scenario: {e}")
        return False


def generate_threshold_pass_scenario():
    """Generate bullish crossover with 1.5 pip separation (above 1.0 pip threshold)"""
    try:
        bars = generate_simple_crossover(
            symbol="TEST-THRESH-PASS/USD",
            venue=VENUE,
            crossover_type="bullish",
            crossover_bar=100,
            separation_before=0.0020,  # 20 pips
            separation_after=0.00015,  # 1.5 pips, above 1.0 pip threshold
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE,
        )
        
        write_to_catalog(bars, "TEST-THRESH-PASS/USD", VENUE, CATALOG_PATH)
        logging.info(f"✅ Generated threshold pass scenario: {len(bars)} bars")
        return True
    except Exception as e:
        logging.error(f"❌ Failed to generate threshold pass scenario: {e}")
        return False


def generate_separation_once_scenario():
    """Generate crossover where MAs were separated by 2.5 pips at bar N-3 (within 5-bar lookback)"""
    try:
        bars = generate_with_insufficient_separation(
            symbol="TEST-SEP-ONCE/USD",
            venue=VENUE,
            crossover_type="bullish",
            crossover_bar=100,
            max_separation_in_lookback=0.00025,  # 2.5 pips, above 2.0 pip threshold
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE,
        )
        
        write_to_catalog(bars, "TEST-SEP-ONCE/USD", VENUE, CATALOG_PATH)
        logging.info(f"✅ Generated separation once scenario: {len(bars)} bars")
        return True
    except Exception as e:
        logging.error(f"❌ Failed to generate separation once scenario: {e}")
        return False


def generate_separation_never_scenario():
    """Generate crossover where MAs were never separated by 2.0 pips in 5-bar lookback"""
    try:
        bars = generate_with_insufficient_separation(
            symbol="TEST-SEP-NEVER/USD",
            venue=VENUE,
            crossover_type="bullish",
            crossover_bar=100,
            max_separation_in_lookback=0.00015,  # 1.5 pips, always below 2.0 pip threshold
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE,
        )
        
        write_to_catalog(bars, "TEST-SEP-NEVER/USD", VENUE, CATALOG_PATH)
        logging.info(f"✅ Generated separation never scenario: {len(bars)} bars")
        return True
    except Exception as e:
        logging.error(f"❌ Failed to generate separation never scenario: {e}")
        return False


def generate_separation_recent_scenario():
    """Generate crossover where MAs were separated by 2.5 pips at bar N-1 (immediate previous bar)"""
    try:
        bars = generate_simple_crossover(
            symbol="TEST-SEP-RECENT/USD",
            venue=VENUE,
            crossover_type="bullish",
            crossover_bar=100,
            separation_before=0.00025,  # 2.5 pips at N-1, above 2.0 pip threshold
            separation_after=0.0020,  # 20 pips after crossover
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE,
        )
        
        write_to_catalog(bars, "TEST-SEP-RECENT/USD", VENUE, CATALOG_PATH)
        logging.info(f"✅ Generated separation recent scenario: {len(bars)} bars")
        return True
    except Exception as e:
        logging.error(f"❌ Failed to generate separation recent scenario: {e}")
        return False


def main():
    """Generate all Phase 3.1-3.2 test scenarios"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Create catalog directory
    Path(CATALOG_PATH).mkdir(parents=True, exist_ok=True)
    
    logging.info("🚀 Starting Phase 3.1-3.2 test data generation...")
    
    # Define scenarios
    scenarios = [
        ("Threshold Fail", generate_threshold_fail_scenario),
        ("Threshold Pass", generate_threshold_pass_scenario),
        ("Separation Once", generate_separation_once_scenario),
        ("Separation Never", generate_separation_never_scenario),
        ("Separation Recent", generate_separation_recent_scenario),
    ]
    
    success_count = 0
    for name, generator_func in scenarios:
        logging.info(f"Generating {name} scenario...")
        if generator_func():
            success_count += 1
        else:
            logging.error(f"Failed to generate {name} scenario")
    
    if success_count == 5:
        logging.info("🎉 Generated 5/5 test scenarios successfully")
        return 0
    else:
        logging.error(f"❌ Generated only {success_count}/5 test scenarios")
        return 1


if __name__ == "__main__":
    sys.exit(main())
