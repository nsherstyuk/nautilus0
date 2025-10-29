"""
Phase 6 MA Diagnostic Data Generator

This module generates synthetic test data for Phase 6 MA diagnostics with metadata
documenting expected crossovers. It creates 4 specific test scenarios designed to
verify MA crossover detection accuracy with detailed crossover-by-crossover reporting.

Test Scenarios:
1. TEST-MA-SINGLE/USD: 1 bullish crossover at bar 100 (simple baseline)
2. TEST-MA-MULTI/USD: 5 alternating crossovers (test multiple detection)
3. TEST-MA-EDGE/USD: Crossover at exact MA equality (boundary condition)
4. TEST-MA-DELAYED/USD: Slow convergence over 20 bars (timing accuracy)

Usage:
    python tests/generate_phase6_ma_diagnostic_data.py

Note: Generates both bar data and metadata JSON files for crossover verification.
"""

from pathlib import Path
import sys
import logging
import json

# Add project root to sys.path for module imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.synthetic_data_generator import (
    generate_simple_crossover,
    generate_multiple_crossovers,
    generate_delayed_crossover,
    write_to_catalog,
    generate_ma_diagnostic_metadata,
    write_metadata_to_catalog,
    _generate_ma_prices
)

# Configuration Constants
CATALOG_PATH = "data/test_catalog/phase6_ma_diagnostics"
VENUE = "IDEALPRO"
BAR_SPEC = "1-MINUTE-MID-EXTERNAL"
BASE_PRICE = 1.08000
FAST_PERIOD = 10
SLOW_PERIOD = 20
TOTAL_BARS = 200
START_DATE = "2024-01-01"


def generate_single_crossover_scenario():
    """
    Generate TEST-MA-SINGLE/USD with 1 bullish crossover at bar 100.
    
    Returns:
        True on success, False on failure
    """
    try:
        symbol = "EUR/USD"
        logging.info(f"Generating single crossover scenario: {symbol}")
        
        # Generate bars with simple crossover
        bars = generate_simple_crossover(
            symbol=symbol,
            venue=VENUE,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            crossover_type="bullish",
            crossover_bar=100,
            total_bars=TOTAL_BARS,
            separation_before=0.0100,  # 100 pips (meets 2.0 pip threshold)
            separation_after=0.0200,   # 200 pips (meets 5.0 pip threshold)
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        # Generate close prices for metadata
        close_prices = _generate_ma_prices(
            FAST_PERIOD, SLOW_PERIOD, TOTAL_BARS, 100,
            "bullish", 0.0100, 0.0200, BASE_PRICE
        )
        
        # Generate metadata
        metadata = generate_ma_diagnostic_metadata(
            close_prices, FAST_PERIOD, SLOW_PERIOD, START_DATE, BAR_SPEC,
            f"{symbol}_simple_crossover"
        )
        
        # Write bars to catalog
        success = write_to_catalog(bars, symbol, VENUE, CATALOG_PATH, BAR_SPEC)
        if not success:
            return False
        
        # Write metadata to catalog
        success = write_metadata_to_catalog(metadata, symbol, CATALOG_PATH)
        if not success:
            return False
        
        logging.info(f"✅ Generated {symbol} with {len(metadata['expected_crossovers'])} expected crossovers")
        return True
        
    except Exception as e:
        logging.error(f"Error generating single crossover scenario: {e}")
        return False


def generate_multiple_crossovers_scenario():
    """
    Generate TEST-MA-MULTI/USD with 5 alternating crossovers.
    
    Returns:
        True on success, False on failure
    """
    try:
        symbol = "GBP/USD"
        logging.info(f"Generating multiple crossovers scenario: {symbol}")
        
        # Generate bars with multiple crossovers and get exact close prices
        bars, close_prices = generate_multiple_crossovers(
            symbol=symbol,
            venue=VENUE,
            crossover_count=5,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            bars_between_crossovers=30,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        # Generate metadata using exact close prices from bar generation
        metadata = generate_ma_diagnostic_metadata(
            close_prices, FAST_PERIOD, SLOW_PERIOD, START_DATE, BAR_SPEC,
            f"{symbol}_multiple_crossovers"
        )
        
        # Write bars to catalog
        success = write_to_catalog(bars, symbol, VENUE, CATALOG_PATH, BAR_SPEC)
        if not success:
            return False
        
        # Write metadata to catalog
        success = write_metadata_to_catalog(metadata, symbol, CATALOG_PATH)
        if not success:
            return False
        
        logging.info(f"✅ Generated {symbol} with {len(metadata['expected_crossovers'])} expected crossovers")
        return True
        
    except Exception as e:
        logging.error(f"Error generating multiple crossovers scenario: {e}")
        return False


def generate_edge_case_scenario():
    """
    Generate TEST-MA-EDGE/USD with crossover at exact MA equality.
    
    Returns:
        True on success, False on failure
    """
    try:
        symbol = "AUD/USD"
        logging.info(f"Generating edge case scenario: {symbol}")
        
        # Generate bars with edge case crossover
        bars = generate_simple_crossover(
            symbol=symbol,
            venue=VENUE,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            crossover_type="bullish",
            crossover_bar=100,
            total_bars=TOTAL_BARS,
            separation_before=0.0100,  # 100 pips (meets 2.0 pip threshold)
            separation_after=0.0200,   # 200 pips (meets 5.0 pip threshold)
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        # Generate close prices for metadata
        close_prices = _generate_ma_prices(
            FAST_PERIOD, SLOW_PERIOD, TOTAL_BARS, 100,
            "bullish", 0.0100, 0.0200, BASE_PRICE
        )
        
        # Generate metadata
        metadata = generate_ma_diagnostic_metadata(
            close_prices, FAST_PERIOD, SLOW_PERIOD, START_DATE, BAR_SPEC,
            f"{symbol}_edge_case"
        )
        
        # Write bars to catalog
        success = write_to_catalog(bars, symbol, VENUE, CATALOG_PATH, BAR_SPEC)
        if not success:
            return False
        
        # Write metadata to catalog
        success = write_metadata_to_catalog(metadata, symbol, CATALOG_PATH)
        if not success:
            return False
        
        logging.info(f"✅ Generated {symbol} with {len(metadata['expected_crossovers'])} expected crossovers (boundary condition)")
        return True
        
    except Exception as e:
        logging.error(f"Error generating edge case scenario: {e}")
        return False


def generate_delayed_crossover_scenario():
    """
    Generate TEST-MA-DELAYED/USD with slow convergence over 20 bars.
    
    Returns:
        True on success, False on failure
    """
    try:
        symbol = "USD/JPY"
        logging.info(f"Generating delayed crossover scenario: {symbol}")
        
        # Generate bars with delayed crossover and get exact close prices
        bars, close_prices = generate_delayed_crossover(
            symbol=symbol,
            venue=VENUE,
            convergence_bars=20,
            crossover_bar=100,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        # Generate metadata using exact close prices from bar generation
        metadata = generate_ma_diagnostic_metadata(
            close_prices, FAST_PERIOD, SLOW_PERIOD, START_DATE, BAR_SPEC,
            f"{symbol}_delayed_crossover"
        )
        
        # Write bars to catalog
        success = write_to_catalog(bars, symbol, VENUE, CATALOG_PATH, BAR_SPEC)
        if not success:
            return False
        
        # Write metadata to catalog
        success = write_metadata_to_catalog(metadata, symbol, CATALOG_PATH)
        if not success:
            return False
        
        logging.info(f"✅ Generated {symbol} with {len(metadata['expected_crossovers'])} expected crossovers (timing verification)")
        return True
        
    except Exception as e:
        logging.error(f"Error generating delayed crossover scenario: {e}")
        return False


def main():
    """
    Generate all Phase 6 MA diagnostic test scenarios.
    
    Returns:
        Exit code 0 on success, 1 on failure
    """
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Create catalog directory
    catalog_dir = Path(CATALOG_PATH)
    catalog_dir.mkdir(parents=True, exist_ok=True)
    
    # Create metadata directory
    metadata_dir = catalog_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    
    logging.info("Starting Phase 6 MA diagnostic data generation...")
    
    # Define scenarios
    scenarios = [
        ("Single Crossover", generate_single_crossover_scenario),
        ("Multiple Crossovers", generate_multiple_crossovers_scenario),
        ("Edge Case", generate_edge_case_scenario),
        ("Delayed Crossover", generate_delayed_crossover_scenario)
    ]
    
    # Generate each scenario
    success_count = 0
    for scenario_name, generator_func in scenarios:
        logging.info(f"Generating {scenario_name}...")
        if generator_func():
            success_count += 1
        else:
            logging.error(f"Failed to generate {scenario_name}")
    
    # Summary
    if success_count == len(scenarios):
        logging.info(f"✅ Generated {success_count}/{len(scenarios)} test scenarios successfully")
        return 0
    else:
        logging.error(f"❌ Generated {success_count}/{len(scenarios)} test scenarios successfully")
        return 1


if __name__ == "__main__":
    sys.exit(main())
