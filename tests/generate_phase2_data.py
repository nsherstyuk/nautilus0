"""
Phase 2 Test Data Generator

Generate synthetic test data for Phase 2 basic crossover tests and write to ParquetDataCatalog.

This script creates 4 distinct test scenarios:
1. Simple Bullish Crossover (TEST-BULL/USD) - Expected: 1 BUY trade
2. Simple Bearish Crossover (TEST-BEAR/USD) - Expected: 1 SELL trade  
3. Multiple Alternating Crossovers (TEST-MULTI/USD) - Expected: 5 trades
4. No Crossover (TEST-NONE/USD) - Expected: 0 trades

Usage: python tests/generate_phase2_data.py
Note: Run this before executing test_basic_crossovers.py
"""

from pathlib import Path
import sys
import logging
from synthetic_data_generator import (
    generate_simple_crossover, 
    generate_multiple_crossovers, 
    generate_no_crossover,
    write_to_catalog
)

# Configuration Constants
CATALOG_PATH = "data/test_catalog/phase2_basic"
VENUE = "IDEALPRO"
BAR_SPEC = "1-MINUTE-MID-EXTERNAL"
BASE_PRICE = 1.08000  # EUR/USD typical
FAST_PERIOD = 10
SLOW_PERIOD = 20
TOTAL_BARS = 200
START_DATE = "2024-01-01"


def generate_test_bull_scenario():
    """Generate simple bullish crossover scenario (TEST-BULL/USD)."""
    try:
        bars = generate_simple_crossover(
            symbol="TEST-BULL/USD",
            venue=VENUE,
            crossover_type="bullish",
            crossover_bar=100,  # Middle of dataset
            separation_before=0.0020,  # 20 pips, well above any threshold
            separation_after=0.0020,   # 20 pips, clear separation
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        write_to_catalog(bars, "TEST-BULL/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        logging.info(f"✅ Generated TEST-BULL/USD scenario: {len(bars)} bars")
        return True
        
    except Exception as e:
        logging.error(f"❌ Failed to generate TEST-BULL/USD scenario: {e}")
        return False


def generate_test_bear_scenario():
    """Generate simple bearish crossover scenario (TEST-BEAR/USD)."""
    try:
        bars = generate_simple_crossover(
            symbol="TEST-BEAR/USD",
            venue=VENUE,
            crossover_type="bearish",
            crossover_bar=100,  # Middle of dataset
            separation_before=0.0020,  # 20 pips, well above any threshold
            separation_after=0.0020,   # 20 pips, clear separation
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        write_to_catalog(bars, "TEST-BEAR/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        logging.info(f"✅ Generated TEST-BEAR/USD scenario: {len(bars)} bars")
        return True
        
    except Exception as e:
        logging.error(f"❌ Failed to generate TEST-BEAR/USD scenario: {e}")
        return False


def generate_test_multi_scenario():
    """Generate multiple alternating crossovers scenario (TEST-MULTI/USD)."""
    try:
        bars = generate_multiple_crossovers(
            symbol="TEST-MULTI/USD",
            venue=VENUE,
            crossover_count=5,  # Alternating bullish/bearish
            bars_between_crossovers=30,  # Enough space for MA separation
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        write_to_catalog(bars, "TEST-MULTI/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        logging.info(f"✅ Generated TEST-MULTI/USD scenario: {len(bars)} bars, 5 crossovers")
        return True
        
    except Exception as e:
        logging.error(f"❌ Failed to generate TEST-MULTI/USD scenario: {e}")
        return False


def generate_test_none_scenario():
    """Generate no crossover scenario (TEST-NONE/USD) - parallel MAs."""
    try:
        # Generate bars where fast MA remains constant offset from slow MA
        bars = generate_no_crossover(
            symbol="TEST-NONE/USD",
            venue=VENUE,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE,
            relative_offset=0.0010  # 10 pips constant separation
        )
        
        write_to_catalog(bars, "TEST-NONE/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        logging.info(f"✅ Generated TEST-NONE/USD scenario: {len(bars)} bars, no crossover")
        return True
        
    except Exception as e:
        logging.error(f"❌ Failed to generate TEST-NONE/USD scenario: {e}")
        return False


def main():
    """Generate all Phase 2 test scenarios."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Create catalog directory
    catalog_dir = Path(CATALOG_PATH)
    catalog_dir.mkdir(parents=True, exist_ok=True)
    
    logging.info("🚀 Starting Phase 2 test data generation...")
    
    # Generate all scenarios
    scenarios = [
        ("Simple Bullish", generate_test_bull_scenario),
        ("Simple Bearish", generate_test_bear_scenario),
        ("Multiple Crossovers", generate_test_multi_scenario),
        ("No Crossover", generate_test_none_scenario)
    ]
    
    success_count = 0
    total_scenarios = len(scenarios)
    
    for scenario_name, generator_func in scenarios:
        logging.info(f"📊 Generating {scenario_name} scenario...")
        if generator_func():
            success_count += 1
        else:
            logging.error(f"Failed to generate {scenario_name} scenario")
    
    # Summary
    if success_count == total_scenarios:
        logging.info(f"🎉 Generated {success_count}/{total_scenarios} test scenarios successfully")
        logging.info(f"📁 Test data written to: {CATALOG_PATH}")
        return 0
    else:
        logging.error(f"❌ Generated only {success_count}/{total_scenarios} scenarios successfully")
        return 1


if __name__ == "__main__":
    sys.exit(main())
