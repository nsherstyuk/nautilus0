#!/usr/bin/env python3
"""
Comprehensive test data generator for all 8 strategy filters.

This script generates synthetic test data to validate the behavior of all filters
in the moving average crossover strategy. It creates predictable scenarios that
test both pass and fail conditions for each filter.

Usage:
    python generate_all_filter_test_data.py
    python generate_all_filter_test_data.py --filter crossover_threshold
    python generate_all_filter_test_data.py --verbose --output-dir custom/path
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from synthetic_data_generator import (
    generate_simple_crossover,
    generate_with_insufficient_separation,
    generate_with_dmi_patterns,
    generate_with_stochastic_patterns,
    generate_with_time_patterns,
    generate_with_volatility_patterns,
    generate_with_adx_patterns,
    generate_circuit_breaker_scenario,
    write_to_catalog,
    write_metadata_to_catalog
)

# Configuration constants
CATALOG_PATH = "data/test_catalog/comprehensive_filter_tests"
VENUE = "IDEALPRO"
BAR_SPEC = "1-MINUTE-MID-EXTERNAL"
MA_FAST_PERIOD = 10
MA_SLOW_PERIOD = 20
BASE_PRICE = 1.1000
START_DATE = "2024-01-01T00:00:00Z"
TOTAL_BARS = 300
CROSSOVER_BAR = 100

# Filter test scenarios configuration
FILTER_TEST_SCENARIOS = {
    # Crossover Threshold Filter (2 scenarios)
    "crossover_threshold": {
        "crossover_threshold_pass": {
            "symbol": "EUR/USD",
            "generator_func": generate_simple_crossover,
            "params": {
                "separation_after": 0.00015,  # 1.5 pips > 0.7 default threshold
                "separation_before": 0.00020,
                "crossover_type": "bullish"
            },
            "expected_trades": 1,
            "expected_rejection": None,
            "description": "Crossover with sufficient separation (1.5 pips) should pass threshold filter"
        },
        "crossover_threshold_fail": {
            "symbol": "GBP/USD",
            "generator_func": generate_simple_crossover,
            "params": {
                "separation_after": 0.00005,  # 0.5 pips < 0.7 threshold
                "separation_before": 0.00020,
                "crossover_type": "bullish"
            },
            "expected_trades": 0,
            "expected_rejection": "crossover_threshold_not_met",
            "description": "Crossover with insufficient separation (0.5 pips) should fail threshold filter"
        }
    },
    
    # Pre-Crossover Separation Filter (2 scenarios)
    "pre_separation": {
        "pre_separation_pass": {
            "symbol": "AUD/USD",
            "generator_func": generate_simple_crossover,
            "params": {
                "separation_after": 0.00010,
                "separation_before": 0.00025,  # 2.5 pips, sufficient
                "crossover_type": "bullish"
            },
            "expected_trades": 1,
            "expected_rejection": None,
            "description": "Crossover with sufficient pre-separation (2.5 pips) should pass filter"
        },
        "pre_separation_fail": {
            "symbol": "NZD/USD",
            "generator_func": generate_with_insufficient_separation,
            "params": {
                "max_separation_in_lookback": 0.00015,  # 1.5 pips, insufficient
                "crossover_type": "bullish"
            },
            "expected_trades": 0,
            "expected_rejection": "pre_crossover_separation_insufficient",
            "description": "Crossover with insufficient pre-separation (1.5 pips) should fail filter"
        }
    },
    
    # DMI Filter (2 scenarios)
    "dmi": {
        "dmi_aligned_pass": {
            "symbol": "USD/CHF",
            "generator_func": generate_with_dmi_patterns,
            "params": {
                "crossover_type": "bullish",
                "dmi_aligned": True
            },
            "expected_trades": 1,
            "expected_rejection": None,
            "description": "Bullish crossover with aligned DMI (+DI > -DI) should pass filter"
        },
        "dmi_misaligned_fail": {
            "symbol": "USD/JPY",
            "generator_func": generate_with_dmi_patterns,
            "params": {
                "crossover_type": "bullish",
                "dmi_aligned": False
            },
            "expected_trades": 0,
            "expected_rejection": "dmi_trend_mismatch",
            "description": "Bullish crossover with misaligned DMI (-DI > +DI) should fail filter"
        }
    },
    
    # Stochastic Filter (3 scenarios)
    "stochastic": {
        "stoch_favorable_pass": {
            "symbol": "EUR/GBP",
            "generator_func": generate_with_stochastic_patterns,
            "params": {
                "stoch_favorable": True,
                "stoch_crossing_bars_ago": 5,
                "crossover_type": "bullish"
            },
            "expected_trades": 1,
            "expected_rejection": None,
            "description": "Crossover with favorable stochastic conditions should pass filter"
        },
        "stoch_unfavorable_fail": {
            "symbol": "EUR/JPY",
            "generator_func": generate_with_stochastic_patterns,
            "params": {
                "stoch_favorable": False,
                "stoch_crossing_bars_ago": 5,
                "crossover_type": "bullish"
            },
            "expected_trades": 0,
            "expected_rejection": "stochastic_unfavorable",
            "description": "Crossover with unfavorable stochastic conditions should fail filter"
        },
        "stoch_crossing_old_fail": {
            "symbol": "GBP/JPY",
            "generator_func": generate_with_stochastic_patterns,
            "params": {
                "stoch_favorable": True,
                "stoch_crossing_bars_ago": 15,  # > max 9 bars
                "crossover_type": "bullish"
            },
            "expected_trades": 0,
            "expected_rejection": "stochastic_crossing_too_old",
            "description": "Crossover with old stochastic crossing (>9 bars) should fail filter"
        }
    },
    
    # Time-of-Day Filter (2 scenarios)
    "time_filter": {
        "time_inside_window_pass": {
            "symbol": "AUD/JPY",
            "generator_func": generate_with_time_patterns,
            "params": {
                "crossover_hour": 10,
                "crossover_minute": 0,
                "timezone": "America/New_York"
            },
            "expected_trades": 1,
            "expected_rejection": None,
            "description": "Crossover within trading window (10:00 ET) should pass filter"
        },
        "time_outside_window_fail": {
            "symbol": "NZD/JPY",
            "generator_func": generate_with_time_patterns,
            "params": {
                "crossover_hour": 18,
                "crossover_minute": 0,
                "timezone": "America/New_York"
            },
            "expected_trades": 0,
            "expected_rejection": "time_filter_outside_hours",
            "description": "Crossover outside trading window (18:00 ET) should fail filter"
        }
    },
    
    # ATR Filter (3 scenarios)
    "atr": {
        "atr_normal_pass": {
            "symbol": "EUR/CHF",
            "generator_func": generate_with_volatility_patterns,
            "params": {
                "target_atr": 0.0005,  # Within 0.0003-0.003 range
                "crossover_type": "bullish"
            },
            "expected_trades": 1,
            "expected_rejection": None,
            "description": "Crossover with normal ATR (0.0005) should pass filter"
        },
        "atr_too_low_fail": {
            "symbol": "GBP/CHF",
            "generator_func": generate_with_volatility_patterns,
            "params": {
                "target_atr": 0.0001,  # < 0.0003 min
                "crossover_type": "bullish"
            },
            "expected_trades": 0,
            "expected_rejection": "atr_too_low",
            "description": "Crossover with too low ATR (0.0001) should fail filter"
        },
        "atr_too_high_fail": {
            "symbol": "AUD/NZD",
            "generator_func": generate_with_volatility_patterns,
            "params": {
                "target_atr": 0.005,  # > 0.003 max
                "crossover_type": "bullish"
            },
            "expected_trades": 0,
            "expected_rejection": "atr_too_high",
            "description": "Crossover with too high ATR (0.005) should fail filter"
        }
    },
    
    # ADX Filter (2 scenarios)
    "adx": {
        "adx_strong_pass": {
            "symbol": "EUR/AUD",
            "generator_func": generate_with_adx_patterns,
            "params": {
                "target_adx": 30,  # > 20 threshold
                "crossover_type": "bullish"
            },
            "expected_trades": 1,
            "expected_rejection": None,
            "description": "Crossover with strong ADX (30) should pass filter"
        },
        "adx_weak_fail": {
            "symbol": "GBP/AUD",
            "generator_func": generate_with_adx_patterns,
            "params": {
                "target_adx": 15,  # < 20 threshold
                "crossover_type": "bullish"
            },
            "expected_trades": 0,
            "expected_rejection": "adx_trend_too_weak",
            "description": "Crossover with weak ADX (15) should fail filter"
        }
    },
    
    # Circuit Breaker Filter (2 scenarios)
    "circuit_breaker": {
        "circuit_breaker_inactive_pass": {
            "symbol": "USD/CAD",
            "generator_func": generate_simple_crossover,
            "params": {
                "separation_after": 0.00010,
                "separation_before": 0.00020,
                "crossover_type": "bullish"
            },
            "expected_trades": 1,
            "expected_rejection": None,
            "description": "Crossover with inactive circuit breaker should pass filter"
        },
        "circuit_breaker_active_fail": {
            "symbol": "EUR/CAD",
            "generator_func": generate_circuit_breaker_scenario,
            "params": {
                "losing_trade_count": 3  # Triggers cooldown
            },
            "expected_trades": 0,
            "expected_rejection": "circuit_breaker_active",
            "description": "Crossover with active circuit breaker (3 losses) should fail filter"
        }
    }
}


def generate_crossover_threshold_scenarios(output_dir: str) -> bool:
    """Generate test scenarios for crossover threshold filter."""
    try:
        filter_dir = Path(output_dir) / "crossover_threshold"
        filter_dir.mkdir(parents=True, exist_ok=True)
        
        scenarios = FILTER_TEST_SCENARIOS["crossover_threshold"]
        success_count = 0
        
        for scenario_name, config in scenarios.items():
            try:
                logging.info(f"  📊 Generating {scenario_name}...")
                
                # Generate bars
                bars = config["generator_func"](
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC,
                    start_date=START_DATE,
                    base_price=BASE_PRICE,
                    fast_period=MA_FAST_PERIOD,
                    slow_period=MA_SLOW_PERIOD,
                    total_bars=TOTAL_BARS,
                    crossover_bar=CROSSOVER_BAR,
                    **config["params"]
                )
                
                # Write to catalog
                write_to_catalog(
                    bars=bars,
                    catalog_path=str(filter_dir),
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC
                )
                
                # Create metadata
                metadata = {
                    "symbol": config["symbol"],
                    "venue": VENUE,
                    "bar_spec": BAR_SPEC,
                    "start_date": START_DATE,
                    "expected_trades": config["expected_trades"],
                    "expected_rejection_reason": config["expected_rejection"],
                    "test_purpose": config["description"],
                    "filter_config": {
                        "filter_type": "crossover_threshold",
                        "scenario": scenario_name,
                        "parameters": config["params"]
                    }
                }
                
                # Write metadata
                write_metadata_to_catalog(
                    metadata=metadata,
                    symbol=config["symbol"],
                    catalog_path=str(filter_dir)
                )
                
                logging.info(f"    ✅ {scenario_name} generated successfully")
                success_count += 1
                
            except Exception as e:
                logging.error(f"    ❌ Failed to generate {scenario_name}: {e}")
                continue
        
        return success_count == len(scenarios)
        
    except Exception as e:
        logging.error(f"❌ Failed to generate crossover threshold scenarios: {e}")
        return False


def generate_pre_separation_scenarios(output_dir: str) -> bool:
    """Generate test scenarios for pre-crossover separation filter."""
    try:
        filter_dir = Path(output_dir) / "pre_separation"
        filter_dir.mkdir(parents=True, exist_ok=True)
        
        scenarios = FILTER_TEST_SCENARIOS["pre_separation"]
        success_count = 0
        
        for scenario_name, config in scenarios.items():
            try:
                logging.info(f"  📊 Generating {scenario_name}...")
                
                # Generate bars
                bars = config["generator_func"](
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC,
                    start_date=START_DATE,
                    base_price=BASE_PRICE,
                    fast_period=MA_FAST_PERIOD,
                    slow_period=MA_SLOW_PERIOD,
                    total_bars=TOTAL_BARS,
                    crossover_bar=CROSSOVER_BAR,
                    **config["params"]
                )
                
                # Write to catalog
                write_to_catalog(
                    bars=bars,
                    catalog_path=str(filter_dir),
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC
                )
                
                # Create metadata
                metadata = {
                    "symbol": config["symbol"],
                    "venue": VENUE,
                    "bar_spec": BAR_SPEC,
                    "start_date": START_DATE,
                    "expected_trades": config["expected_trades"],
                    "expected_rejection_reason": config["expected_rejection"],
                    "test_purpose": config["description"],
                    "filter_config": {
                        "filter_type": "pre_separation",
                        "scenario": scenario_name,
                        "parameters": config["params"]
                    }
                }
                
                # Write metadata
                write_metadata_to_catalog(
                    metadata=metadata,
                    symbol=config["symbol"],
                    catalog_path=str(filter_dir)
                )
                
                logging.info(f"    ✅ {scenario_name} generated successfully")
                success_count += 1
                
            except Exception as e:
                logging.error(f"    ❌ Failed to generate {scenario_name}: {e}")
                continue
        
        return success_count == len(scenarios)
        
    except Exception as e:
        logging.error(f"❌ Failed to generate pre-separation scenarios: {e}")
        return False


def generate_dmi_scenarios(output_dir: str) -> bool:
    """Generate test scenarios for DMI filter."""
    try:
        filter_dir = Path(output_dir) / "dmi"
        filter_dir.mkdir(parents=True, exist_ok=True)
        
        scenarios = FILTER_TEST_SCENARIOS["dmi"]
        success_count = 0
        
        for scenario_name, config in scenarios.items():
            try:
                logging.info(f"  📊 Generating {scenario_name}...")
                
                # Generate bars
                bars = config["generator_func"](
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC,
                    start_date=START_DATE,
                    base_price=BASE_PRICE,
                    fast_period=MA_FAST_PERIOD,
                    slow_period=MA_SLOW_PERIOD,
                    total_bars=TOTAL_BARS,
                    **config["params"]
                )
                
                # Write to catalog
                write_to_catalog(
                    bars=bars,
                    catalog_path=str(filter_dir),
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC
                )
                
                # Create metadata
                metadata = {
                    "symbol": config["symbol"],
                    "venue": VENUE,
                    "bar_spec": BAR_SPEC,
                    "start_date": START_DATE,
                    "expected_trades": config["expected_trades"],
                    "expected_rejection_reason": config["expected_rejection"],
                    "test_purpose": config["description"],
                    "filter_config": {
                        "filter_type": "dmi",
                        "scenario": scenario_name,
                        "parameters": config["params"]
                    }
                }
                
                # Write metadata
                write_metadata_to_catalog(
                    metadata=metadata,
                    symbol=config["symbol"],
                    catalog_path=str(filter_dir)
                )
                
                logging.info(f"    ✅ {scenario_name} generated successfully")
                success_count += 1
                
            except Exception as e:
                logging.error(f"    ❌ Failed to generate {scenario_name}: {e}")
                continue
        
        return success_count == len(scenarios)
        
    except Exception as e:
        logging.error(f"❌ Failed to generate DMI scenarios: {e}")
        return False


def generate_stochastic_scenarios(output_dir: str) -> bool:
    """Generate test scenarios for stochastic filter."""
    try:
        filter_dir = Path(output_dir) / "stochastic"
        filter_dir.mkdir(parents=True, exist_ok=True)
        
        scenarios = FILTER_TEST_SCENARIOS["stochastic"]
        success_count = 0
        
        for scenario_name, config in scenarios.items():
            try:
                logging.info(f"  📊 Generating {scenario_name}...")
                
                # Generate bars
                bars = config["generator_func"](
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC,
                    start_date=START_DATE,
                    base_price=BASE_PRICE,
                    fast_period=MA_FAST_PERIOD,
                    slow_period=MA_SLOW_PERIOD,
                    total_bars=TOTAL_BARS,
                    crossover_bar=CROSSOVER_BAR,
                    **config["params"]
                )
                
                # Write to catalog
                write_to_catalog(
                    bars=bars,
                    catalog_path=str(filter_dir),
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC
                )
                
                # Create metadata
                metadata = {
                    "symbol": config["symbol"],
                    "venue": VENUE,
                    "bar_spec": BAR_SPEC,
                    "start_date": START_DATE,
                    "expected_trades": config["expected_trades"],
                    "expected_rejection_reason": config["expected_rejection"],
                    "test_purpose": config["description"],
                    "filter_config": {
                        "filter_type": "stochastic",
                        "scenario": scenario_name,
                        "parameters": config["params"]
                    }
                }
                
                # Write metadata
                write_metadata_to_catalog(
                    metadata=metadata,
                    symbol=config["symbol"],
                    catalog_path=str(filter_dir)
                )
                
                logging.info(f"    ✅ {scenario_name} generated successfully")
                success_count += 1
                
            except Exception as e:
                logging.error(f"    ❌ Failed to generate {scenario_name}: {e}")
                continue
        
        return success_count == len(scenarios)
        
    except Exception as e:
        logging.error(f"❌ Failed to generate stochastic scenarios: {e}")
        return False


def generate_time_filter_scenarios(output_dir: str) -> bool:
    """Generate test scenarios for time-of-day filter."""
    try:
        filter_dir = Path(output_dir) / "time_filter"
        filter_dir.mkdir(parents=True, exist_ok=True)
        
        scenarios = FILTER_TEST_SCENARIOS["time_filter"]
        success_count = 0
        
        for scenario_name, config in scenarios.items():
            try:
                logging.info(f"  📊 Generating {scenario_name}...")
                
                # Generate bars
                bars = config["generator_func"](
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC,
                    start_date=START_DATE,
                    base_price=BASE_PRICE,
                    fast_period=MA_FAST_PERIOD,
                    slow_period=MA_SLOW_PERIOD,
                    total_bars=TOTAL_BARS,
                    crossover_bar=CROSSOVER_BAR,
                    **config["params"]
                )
                
                # Write to catalog
                write_to_catalog(
                    bars=bars,
                    catalog_path=str(filter_dir),
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC
                )
                
                # Create metadata
                metadata = {
                    "symbol": config["symbol"],
                    "venue": VENUE,
                    "bar_spec": BAR_SPEC,
                    "start_date": START_DATE,
                    "expected_trades": config["expected_trades"],
                    "expected_rejection_reason": config["expected_rejection"],
                    "test_purpose": config["description"],
                    "filter_config": {
                        "filter_type": "time_filter",
                        "scenario": scenario_name,
                        "parameters": config["params"]
                    }
                }
                
                # Write metadata
                write_metadata_to_catalog(
                    metadata=metadata,
                    symbol=config["symbol"],
                    catalog_path=str(filter_dir)
                )
                
                logging.info(f"    ✅ {scenario_name} generated successfully")
                success_count += 1
                
            except Exception as e:
                logging.error(f"    ❌ Failed to generate {scenario_name}: {e}")
                continue
        
        return success_count == len(scenarios)
        
    except Exception as e:
        logging.error(f"❌ Failed to generate time filter scenarios: {e}")
        return False


def generate_atr_scenarios(output_dir: str) -> bool:
    """Generate test scenarios for ATR filter."""
    try:
        filter_dir = Path(output_dir) / "atr"
        filter_dir.mkdir(parents=True, exist_ok=True)
        
        scenarios = FILTER_TEST_SCENARIOS["atr"]
        success_count = 0
        
        for scenario_name, config in scenarios.items():
            try:
                logging.info(f"  📊 Generating {scenario_name}...")
                
                # Generate bars
                bars = config["generator_func"](
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC,
                    start_date=START_DATE,
                    base_price=BASE_PRICE,
                    fast_period=MA_FAST_PERIOD,
                    slow_period=MA_SLOW_PERIOD,
                    total_bars=TOTAL_BARS,
                    crossover_bar=CROSSOVER_BAR,
                    **config["params"]
                )
                
                # Write to catalog
                write_to_catalog(
                    bars=bars,
                    catalog_path=str(filter_dir),
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC
                )
                
                # Create metadata
                metadata = {
                    "symbol": config["symbol"],
                    "venue": VENUE,
                    "bar_spec": BAR_SPEC,
                    "start_date": START_DATE,
                    "expected_trades": config["expected_trades"],
                    "expected_rejection_reason": config["expected_rejection"],
                    "test_purpose": config["description"],
                    "filter_config": {
                        "filter_type": "atr",
                        "scenario": scenario_name,
                        "parameters": config["params"]
                    }
                }
                
                # Write metadata
                write_metadata_to_catalog(
                    metadata=metadata,
                    symbol=config["symbol"],
                    catalog_path=str(filter_dir)
                )
                
                logging.info(f"    ✅ {scenario_name} generated successfully")
                success_count += 1
                
            except Exception as e:
                logging.error(f"    ❌ Failed to generate {scenario_name}: {e}")
                continue
        
        return success_count == len(scenarios)
        
    except Exception as e:
        logging.error(f"❌ Failed to generate ATR scenarios: {e}")
        return False


def generate_adx_scenarios(output_dir: str) -> bool:
    """Generate test scenarios for ADX filter."""
    try:
        filter_dir = Path(output_dir) / "adx"
        filter_dir.mkdir(parents=True, exist_ok=True)
        
        scenarios = FILTER_TEST_SCENARIOS["adx"]
        success_count = 0
        
        for scenario_name, config in scenarios.items():
            try:
                logging.info(f"  📊 Generating {scenario_name}...")
                
                # Generate bars
                bars = config["generator_func"](
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC,
                    start_date=START_DATE,
                    base_price=BASE_PRICE,
                    fast_period=MA_FAST_PERIOD,
                    slow_period=MA_SLOW_PERIOD,
                    total_bars=TOTAL_BARS,
                    crossover_bar=CROSSOVER_BAR,
                    **config["params"]
                )
                
                # Write to catalog
                write_to_catalog(
                    bars=bars,
                    catalog_path=str(filter_dir),
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC
                )
                
                # Create metadata
                metadata = {
                    "symbol": config["symbol"],
                    "venue": VENUE,
                    "bar_spec": BAR_SPEC,
                    "start_date": START_DATE,
                    "expected_trades": config["expected_trades"],
                    "expected_rejection_reason": config["expected_rejection"],
                    "test_purpose": config["description"],
                    "filter_config": {
                        "filter_type": "adx",
                        "scenario": scenario_name,
                        "parameters": config["params"]
                    }
                }
                
                # Write metadata
                write_metadata_to_catalog(
                    metadata=metadata,
                    symbol=config["symbol"],
                    catalog_path=str(filter_dir)
                )
                
                logging.info(f"    ✅ {scenario_name} generated successfully")
                success_count += 1
                
            except Exception as e:
                logging.error(f"    ❌ Failed to generate {scenario_name}: {e}")
                continue
        
        return success_count == len(scenarios)
        
    except Exception as e:
        logging.error(f"❌ Failed to generate ADX scenarios: {e}")
        return False


def generate_circuit_breaker_scenarios(output_dir: str) -> bool:
    """Generate test scenarios for circuit breaker filter."""
    try:
        filter_dir = Path(output_dir) / "circuit_breaker"
        filter_dir.mkdir(parents=True, exist_ok=True)
        
        scenarios = FILTER_TEST_SCENARIOS["circuit_breaker"]
        success_count = 0
        
        for scenario_name, config in scenarios.items():
            try:
                logging.info(f"  📊 Generating {scenario_name}...")
                
                # Generate bars
                bars = config["generator_func"](
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC,
                    start_date=START_DATE,
                    base_price=BASE_PRICE,
                    fast_period=MA_FAST_PERIOD,
                    slow_period=MA_SLOW_PERIOD,
                    total_bars=TOTAL_BARS,
                    crossover_bar=CROSSOVER_BAR,
                    **config["params"]
                )
                
                # Write to catalog
                write_to_catalog(
                    bars=bars,
                    catalog_path=str(filter_dir),
                    symbol=config["symbol"],
                    venue=VENUE,
                    bar_spec=BAR_SPEC
                )
                
                # Create metadata
                metadata = {
                    "symbol": config["symbol"],
                    "venue": VENUE,
                    "bar_spec": BAR_SPEC,
                    "start_date": START_DATE,
                    "expected_trades": config["expected_trades"],
                    "expected_rejection_reason": config["expected_rejection"],
                    "test_purpose": config["description"],
                    "filter_config": {
                        "filter_type": "circuit_breaker",
                        "scenario": scenario_name,
                        "parameters": config["params"]
                    }
                }
                
                # Write metadata
                write_metadata_to_catalog(
                    metadata=metadata,
                    symbol=config["symbol"],
                    catalog_path=str(filter_dir)
                )
                
                logging.info(f"    ✅ {scenario_name} generated successfully")
                success_count += 1
                
            except Exception as e:
                logging.error(f"    ❌ Failed to generate {scenario_name}: {e}")
                continue
        
        return success_count == len(scenarios)
        
    except Exception as e:
        logging.error(f"❌ Failed to generate circuit breaker scenarios: {e}")
        return False


def main():
    """Main function to generate comprehensive filter test data."""
    parser = argparse.ArgumentParser(
        description="Generate comprehensive test data for all 8 strategy filters"
    )
    parser.add_argument(
        "--filter",
        choices=list(FILTER_TEST_SCENARIOS.keys()),
        help="Generate data for specific filter only"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--output-dir",
        default=CATALOG_PATH,
        help=f"Output directory for test data (default: {CATALOG_PATH})"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Define scenario registry
    scenario_registry = {
        "crossover_threshold": generate_crossover_threshold_scenarios,
        "pre_separation": generate_pre_separation_scenarios,
        "dmi": generate_dmi_scenarios,
        "stochastic": generate_stochastic_scenarios,
        "time_filter": generate_time_filter_scenarios,
        "atr": generate_atr_scenarios,
        "adx": generate_adx_scenarios,
        "circuit_breaker": generate_circuit_breaker_scenarios
    }
    
    # Determine which filters to process
    if args.filter:
        filters_to_process = [args.filter]
    else:
        filters_to_process = list(scenario_registry.keys())
    
    logging.info(f"🚀 Starting comprehensive filter test data generation...")
    logging.info(f"📁 Output directory: {output_dir}")
    logging.info(f"🎯 Processing filters: {', '.join(filters_to_process)}")
    
    # Process each filter
    success_count = 0
    total_filters = len(filters_to_process)
    
    for filter_name in filters_to_process:
        try:
            logging.info(f"📊 Generating {filter_name} scenarios...")
            
            generator_func = scenario_registry[filter_name]
            success = generator_func(str(output_dir))
            
            if success:
                logging.info(f"✅ {filter_name} scenarios generated successfully")
                success_count += 1
            else:
                logging.error(f"❌ {filter_name} scenarios generation failed")
                
        except Exception as e:
            logging.error(f"❌ Failed to process {filter_name}: {e}")
            continue
    
    # Report final summary
    logging.info(f"📊 Generation complete!")
    logging.info(f"✅ Successful: {success_count}/{total_filters} filters")
    logging.info(f"❌ Failed: {total_filters - success_count}/{total_filters} filters")
    
    if success_count == total_filters:
        logging.info("🎉 All filter test data generated successfully!")
        return 0
    else:
        logging.error("💥 Some filters failed to generate test data")
        return 1


if __name__ == "__main__":
    sys.exit(main())
