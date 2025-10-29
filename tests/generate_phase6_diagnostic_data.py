"""
Phase 6: MA Diagnostic Test Data Generator

This module generates synthetic test data for Phase 6 MA diagnostics and writes to ParquetDataCatalog.
It creates 8 specialized diagnostic scenarios designed to stress-test the MA crossover algorithm
and detect potential misbehavior patterns.

Diagnostic Scenarios:
1. Choppy Market - Test behavior in ranging market with frequent small crossovers
2. Whipsaw Pattern - Test handling of immediate signal reversals
3. Threshold Boundary - Test boundary condition handling for crossover threshold
4. Delayed Crossover - Test crossover detection timing with slow MA convergence
5. False Breakout - Test resilience to price spikes causing temporary crossovers
6. No-Trade Zone - Test that strategy doesn't generate false signals when MAs are close but not crossing
7. Filter Cascade Failure - Test filter cascade logic and rejection reason accuracy
8. MA Lag Test - Quantify inherent MA lag in trending markets

Usage:
    python tests/generate_phase6_diagnostic_data.py

Note: Run this before executing run_ma_diagnostics.py
"""

from pathlib import Path
import sys
import logging

# Add project root to sys.path for module imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from synthetic_data_generator import (
    generate_choppy_market,
    generate_whipsaw_pattern,
    generate_threshold_boundary_crossover,
    generate_delayed_crossover,
    generate_false_breakout,
    generate_no_trade_zone,
    generate_filter_cascade_failure,
    generate_ma_lag_test,
    write_to_catalog
)

# Configuration Constants
CATALOG_PATH = "data/test_catalog/phase6_diagnostics"
VENUE = "IDEALPRO"
BAR_SPEC = "1-MINUTE-MID-EXTERNAL"
BASE_PRICE = 1.08000
FAST_PERIOD = 10
SLOW_PERIOD = 20
TOTAL_BARS = 300
START_DATE = "2024-01-01"


def generate_choppy_market_scenario():
    """Generate choppy market scenario with frequent small crossovers."""
    try:
        bars = generate_choppy_market(
            symbol="DIAG-CHOPPY/USD",
            venue=VENUE,
            crossover_count=10,
            bars_between_crossovers=5,
            small_separation=0.00003,  # 0.3 pips
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        success = write_to_catalog(bars, "DIAG-CHOPPY/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        if success:
            print("✓ Generated choppy market scenario (DIAG-CHOPPY/USD)")
            return True
        else:
            print("✗ Failed to write choppy market scenario to catalog")
            return False
            
    except Exception as e:
        print(f"✗ Error generating choppy market scenario: {e}")
        return False


def generate_whipsaw_scenario():
    """Generate whipsaw pattern scenario with immediate reversal."""
    try:
        bars = generate_whipsaw_pattern(
            symbol="DIAG-WHIPSAW/USD",
            venue=VENUE,
            crossover_bar=100,
            reversal_bars_after=2,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        success = write_to_catalog(bars, "DIAG-WHIPSAW/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        if success:
            print("✓ Generated whipsaw pattern scenario (DIAG-WHIPSAW/USD)")
            return True
        else:
            print("✗ Failed to write whipsaw pattern scenario to catalog")
            return False
            
    except Exception as e:
        print(f"✗ Error generating whipsaw pattern scenario: {e}")
        return False


def generate_threshold_boundary_scenario():
    """Generate threshold boundary scenarios (below, exact, above threshold)."""
    try:
        success_count = 0
        
        # Below threshold (0.99 pips)
        bars = generate_threshold_boundary_crossover(
            symbol="DIAG-THRESH-BELOW/USD",
            venue=VENUE,
            threshold_pips=1.0,
            separation_offset_pips=-0.01,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        if write_to_catalog(bars, "DIAG-THRESH-BELOW/USD", VENUE, CATALOG_PATH, BAR_SPEC):
            print("✓ Generated threshold below scenario (DIAG-THRESH-BELOW/USD)")
            success_count += 1
        else:
            print("✗ Failed to write threshold below scenario to catalog")
        
        # Exact threshold (1.00 pips)
        bars = generate_threshold_boundary_crossover(
            symbol="DIAG-THRESH-EXACT/USD",
            venue=VENUE,
            threshold_pips=1.0,
            separation_offset_pips=0.0,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        if write_to_catalog(bars, "DIAG-THRESH-EXACT/USD", VENUE, CATALOG_PATH, BAR_SPEC):
            print("✓ Generated threshold exact scenario (DIAG-THRESH-EXACT/USD)")
            success_count += 1
        else:
            print("✗ Failed to write threshold exact scenario to catalog")
        
        # Above threshold (1.01 pips)
        bars = generate_threshold_boundary_crossover(
            symbol="DIAG-THRESH-ABOVE/USD",
            venue=VENUE,
            threshold_pips=1.0,
            separation_offset_pips=0.01,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        if write_to_catalog(bars, "DIAG-THRESH-ABOVE/USD", VENUE, CATALOG_PATH, BAR_SPEC):
            print("✓ Generated threshold above scenario (DIAG-THRESH-ABOVE/USD)")
            success_count += 1
        else:
            print("✗ Failed to write threshold above scenario to catalog")
        
        return success_count == 3
        
    except Exception as e:
        print(f"✗ Error generating threshold boundary scenarios: {e}")
        return False


def generate_delayed_crossover_scenario():
    """Generate delayed crossover scenario with slow MA convergence."""
    try:
        bars = generate_delayed_crossover(
            symbol="DIAG-DELAYED/USD",
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
        
        success = write_to_catalog(bars, "DIAG-DELAYED/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        if success:
            print("✓ Generated delayed crossover scenario (DIAG-DELAYED/USD)")
            return True
        else:
            print("✗ Failed to write delayed crossover scenario to catalog")
            return False
            
    except Exception as e:
        print(f"✗ Error generating delayed crossover scenario: {e}")
        return False


def generate_false_breakout_scenario():
    """Generate false breakout scenario with price spike and reversion."""
    try:
        bars = generate_false_breakout(
            symbol="DIAG-BREAKOUT/USD",
            venue=VENUE,
            spike_bar=100,
            spike_magnitude=0.0050,  # 50 pips
            revert_bars=3,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        success = write_to_catalog(bars, "DIAG-BREAKOUT/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        if success:
            print("✓ Generated false breakout scenario (DIAG-BREAKOUT/USD)")
            return True
        else:
            print("✗ Failed to write false breakout scenario to catalog")
            return False
            
    except Exception as e:
        print(f"✗ Error generating false breakout scenario: {e}")
        return False


def generate_no_trade_zone_scenario():
    """Generate no-trade zone scenario with constant MA separation."""
    try:
        bars = generate_no_trade_zone(
            symbol="DIAG-NOTRADE/USD",
            venue=VENUE,
            ma_separation=0.00005,  # 0.5 pips constant
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        success = write_to_catalog(bars, "DIAG-NOTRADE/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        if success:
            print("✓ Generated no-trade zone scenario (DIAG-NOTRADE/USD)")
            return True
        else:
            print("✗ Failed to write no-trade zone scenario to catalog")
            return False
            
    except Exception as e:
        print(f"✗ Error generating no-trade zone scenario: {e}")
        return False


def generate_filter_cascade_scenario():
    """Generate filter cascade failure scenario."""
    try:
        bars = generate_filter_cascade_failure(
            symbol="DIAG-CASCADE/USD",
            venue=VENUE,
            pass_filters=["threshold", "separation"],
            fail_filters=["dmi"],
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        success = write_to_catalog(bars, "DIAG-CASCADE/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        if success:
            print("✓ Generated filter cascade scenario (DIAG-CASCADE/USD)")
            return True
        else:
            print("✗ Failed to write filter cascade scenario to catalog")
            return False
            
    except Exception as e:
        print(f"✗ Error generating filter cascade scenario: {e}")
        return False


def generate_ma_lag_scenario():
    """Generate MA lag test scenario with strong trend."""
    try:
        bars = generate_ma_lag_test(
            symbol="DIAG-LAG/USD",
            venue=VENUE,
            trend_start_bar=50,
            trend_strength=0.0010,  # 10 pips per bar
            trend_duration=30,
            fast_period=FAST_PERIOD,
            slow_period=SLOW_PERIOD,
            total_bars=TOTAL_BARS,
            base_price=BASE_PRICE,
            bar_spec=BAR_SPEC,
            start_date=START_DATE
        )
        
        success = write_to_catalog(bars, "DIAG-LAG/USD", VENUE, CATALOG_PATH, BAR_SPEC)
        if success:
            print("✓ Generated MA lag test scenario (DIAG-LAG/USD)")
            return True
        else:
            print("✗ Failed to write MA lag test scenario to catalog")
            return False
            
    except Exception as e:
        print(f"✗ Error generating MA lag test scenario: {e}")
        return False


def main():
    """Generate all Phase 6 diagnostic test data."""
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    
    # Create catalog directory
    Path(CATALOG_PATH).mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting Phase 6 diagnostic data generation...")
    
    # Define scenarios
    scenarios = [
        ("Choppy Market", generate_choppy_market_scenario),
        ("Whipsaw Pattern", generate_whipsaw_scenario),
        ("Threshold Boundary", generate_threshold_boundary_scenario),
        ("Delayed Crossover", generate_delayed_crossover_scenario),
        ("False Breakout", generate_false_breakout_scenario),
        ("No-Trade Zone", generate_no_trade_zone_scenario),
        ("Filter Cascade", generate_filter_cascade_scenario),
        ("MA Lag Test", generate_ma_lag_scenario),
    ]
    
    # Generate each scenario
    success_count = 0
    total_scenarios = len(scenarios)
    
    for scenario_name, generator_func in scenarios:
        logger.info(f"Generating {scenario_name} scenario...")
        if generator_func():
            success_count += 1
        else:
            logger.error(f"Failed to generate {scenario_name} scenario")
    
    # Summary
    logger.info(f"Phase 6 diagnostic data generation complete: {success_count}/{total_scenarios} scenarios successful")
    
    if success_count == total_scenarios:
        logger.info("All diagnostic scenarios generated successfully!")
        return 0
    else:
        logger.error(f"Failed to generate {total_scenarios - success_count} scenarios")
        return 1


if __name__ == "__main__":
    sys.exit(main())
