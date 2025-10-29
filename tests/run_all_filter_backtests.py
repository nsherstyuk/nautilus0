#!/usr/bin/env python3
"""
Comprehensive backtest execution script for all filter test scenarios.

This script discovers test scenarios from the catalog directory, generates
environment configurations dynamically for each filter type, executes backtests
via subprocess, and organizes results in a structured output format.

Usage:
    python run_all_filter_backtests.py [--filter FILTER_TYPE] [--scenario SCENARIO_NAME] [--list] [--verbose]
"""

import subprocess
import json
import logging
import os
import sys
import argparse
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
import shutil


# Constants
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKTEST_SCRIPT = PROJECT_ROOT / "backtest" / "run_backtest.py"
CATALOG_BASE = PROJECT_ROOT / "data" / "test_catalog" / "comprehensive_filter_tests"
RESULTS_BASE = PROJECT_ROOT / "logs" / "test_results" / "comprehensive_filter_tests"

FILTER_TYPES = [
    "crossover_threshold", "pre_separation", "dmi", "stochastic", 
    "time_filter", "atr", "adx", "circuit_breaker"
]


def get_base_env_config() -> Dict[str, str]:
    """Get base environment configuration that applies to all scenarios."""
    return {
        "BACKTEST_VENUE": "IDEALPRO",
        "BACKTEST_BAR_SPEC": "1-MINUTE-MID-EXTERNAL",
        "BACKTEST_START_DATE": "2024-01-01",
        "BACKTEST_END_DATE": "2024-01-10",
        "BACKTEST_FAST_PERIOD": "10",
        "BACKTEST_SLOW_PERIOD": "20",
        "BACKTEST_TRADE_SIZE": "100000",
        "BACKTEST_STARTING_CAPITAL": "100000.0",
        "ENFORCE_POSITION_LIMIT": "true",
        "ALLOW_POSITION_REVERSAL": "false",
        "BACKTEST_STOP_LOSS_PIPS": "1000",  # High to avoid premature exits
        "BACKTEST_TAKE_PROFIT_PIPS": "2000",
        "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": "1",
        "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": "0",
        "STRATEGY_USE_LIMIT_ORDERS": "false",
        "STRATEGY_LIMIT_ORDER_TIMEOUT_BARS": "0",
        "LOG_LEVEL": "INFO",
        "LOG_DIR": "logs"
    }


def get_disabled_filters_config() -> Dict[str, str]:
    """Get configuration with all filters disabled."""
    return {
        "STRATEGY_CROSSOVER_THRESHOLD_PIPS": "0.0",
        "STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS": "0.0",
        "STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS": "1",
        "STRATEGY_DMI_ENABLED": "false",
        "STRATEGY_DMI_PERIOD": "14",
        "STRATEGY_DMI_BAR_SPEC": "1-MINUTE-MID-EXTERNAL",
        "STRATEGY_STOCH_ENABLED": "false",
        "STRATEGY_STOCH_PERIOD_K": "14",
        "STRATEGY_STOCH_PERIOD_D": "3",
        "STRATEGY_STOCH_BULLISH_THRESHOLD": "30",
        "STRATEGY_STOCH_BEARISH_THRESHOLD": "70",
        "STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING": "9",
        "STRATEGY_STOCH_BAR_SPEC": "1-MINUTE-MID-EXTERNAL",
        "STRATEGY_ATR_ENABLED": "false",
        "STRATEGY_ATR_PERIOD": "14",
        "STRATEGY_ATR_MIN_THRESHOLD": "0.0",
        "STRATEGY_ATR_MAX_THRESHOLD": "999.0",
        "STRATEGY_ATR_BAR_SPEC": "1-MINUTE-MID-EXTERNAL",
        "STRATEGY_ADX_ENABLED": "false",
        "STRATEGY_ADX_MIN_THRESHOLD": "0.0",
        "STRATEGY_TIME_FILTER_ENABLED": "false",
        "STRATEGY_TRADING_HOURS_START": "0",
        "STRATEGY_TRADING_HOURS_END": "23",
        "STRATEGY_MARKET_TIMEZONE": "UTC",
        "STRATEGY_CIRCUIT_BREAKER_ENABLED": "false",
        "STRATEGY_MAX_CONSECUTIVE_LOSSES": "999",
        "STRATEGY_COOLDOWN_BARS": "0"
    }


def configure_filter_for_scenario(filter_type: str, scenario_name: str, base_config: Dict[str, str]) -> Dict[str, str]:
    """Configure specific filter based on filter type and scenario."""
    config = base_config.copy()
    
    if filter_type == "crossover_threshold":
        config["STRATEGY_CROSSOVER_THRESHOLD_PIPS"] = "0.7"
        
    elif filter_type == "pre_separation":
        config["STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS"] = "2.0"
        config["STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS"] = "5"
        
    elif filter_type == "dmi":
        config["STRATEGY_DMI_ENABLED"] = "true"
        config["STRATEGY_DMI_PERIOD"] = "14"
        config["STRATEGY_DMI_BAR_SPEC"] = "1-MINUTE-MID-EXTERNAL"
        
    elif filter_type == "stochastic":
        config["STRATEGY_STOCH_ENABLED"] = "true"
        config["STRATEGY_STOCH_PERIOD_K"] = "14"
        config["STRATEGY_STOCH_PERIOD_D"] = "3"
        config["STRATEGY_STOCH_BULLISH_THRESHOLD"] = "30"
        config["STRATEGY_STOCH_BEARISH_THRESHOLD"] = "70"
        config["STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING"] = "9"
        config["STRATEGY_STOCH_BAR_SPEC"] = "1-MINUTE-MID-EXTERNAL"
        
    elif filter_type == "time_filter":
        config["STRATEGY_TIME_FILTER_ENABLED"] = "true"
        config["STRATEGY_TRADING_HOURS_START"] = "8"
        config["STRATEGY_TRADING_HOURS_END"] = "16"
        config["STRATEGY_MARKET_TIMEZONE"] = "America/New_York"
        
    elif filter_type == "atr":
        config["STRATEGY_ATR_ENABLED"] = "true"
        config["STRATEGY_ATR_PERIOD"] = "14"
        config["STRATEGY_ATR_MIN_THRESHOLD"] = "0.0003"
        config["STRATEGY_ATR_MAX_THRESHOLD"] = "0.003"
        config["STRATEGY_ATR_BAR_SPEC"] = "1-MINUTE-MID-EXTERNAL"
        
    elif filter_type == "adx":
        config["STRATEGY_ADX_ENABLED"] = "true"
        config["STRATEGY_ADX_MIN_THRESHOLD"] = "20.0"
        
    elif filter_type == "circuit_breaker":
        config["STRATEGY_CIRCUIT_BREAKER_ENABLED"] = "true"
        config["STRATEGY_MAX_CONSECUTIVE_LOSSES"] = "3"
        config["STRATEGY_COOLDOWN_BARS"] = "10"
    
    return config


def discover_test_scenarios(catalog_base: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Discover all test scenarios from catalog directory structure."""
    scenarios = {}
    
    if not catalog_base.exists():
        logging.error(f"Catalog base directory does not exist: {catalog_base}")
        return scenarios
    
    for filter_type in FILTER_TYPES:
        filter_dir = catalog_base / filter_type
        if not filter_dir.exists():
            logging.warning(f"Filter directory not found: {filter_dir}")
            continue
            
        scenarios[filter_type] = []
        
        # Look for metadata JSON files in metadata subdirectory or recursively
        metadata_files = []
        metadata_dir = filter_dir / "metadata"
        if metadata_dir.exists():
            metadata_files.extend(metadata_dir.glob("*_metadata.json"))
        else:
            # Fallback to recursive search if metadata directory doesn't exist
            metadata_files.extend(filter_dir.rglob("*_metadata.json"))
        
        for metadata_file in metadata_files:
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                scenario_name = metadata_file.stem.replace("_metadata", "")
                symbol = metadata.get("symbol", "UNKNOWN")
                
                scenario = {
                    "symbol": symbol,
                    "metadata_path": metadata_file,
                    "scenario_name": scenario_name,
                    "expected_trades": metadata.get("expected_trades", 0),
                    "expected_rejection": metadata.get("expected_rejection_reason", ""),
                    "description": metadata.get("test_purpose", ""),
                    "filter_config": metadata.get("filter_config", {})
                }
                
                scenarios[filter_type].append(scenario)
                logging.debug(f"Discovered scenario: {filter_type}/{scenario_name} ({symbol})")
                
            except (json.JSONDecodeError, KeyError) as e:
                logging.warning(f"Failed to parse metadata file {metadata_file}: {e}")
                continue
    
    total_scenarios = sum(len(scenarios[ft]) for ft in scenarios)
    logging.info(f"📊 Found {total_scenarios} scenarios across {len(scenarios)} filter types")
    
    return scenarios


def run_backtest_for_scenario(scenario: Dict[str, Any], filter_type: str, output_base: Path, catalog_base: Path, timeout: int = 300) -> Dict[str, Any]:
    """Run backtest for a specific scenario."""
    symbol = scenario["symbol"]
    scenario_name = scenario["scenario_name"]
    
    # Create filter-specific output directory
    output_dir = output_base / filter_type / scenario_name
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Build environment configuration
    base_env = get_base_env_config()
    disabled_filters = get_disabled_filters_config()
    filter_config = configure_filter_for_scenario(filter_type, scenario_name, disabled_filters)
    
    # Merge all configurations
    env_config = {**base_env, **disabled_filters, **filter_config}
    
    # Merge scenario-specific filter_config parameters into env_config
    scenario_filter_config = scenario.get("filter_config", {})
    for param_name, param_value in scenario_filter_config.items():
        # Map known parameter names to corresponding env vars
        if param_name == "time_filter_hours":
            env_config["STRATEGY_TRADING_HOURS_START"] = str(param_value.get("start", env_config.get("STRATEGY_TRADING_HOURS_START", "0")))
            env_config["STRATEGY_TRADING_HOURS_END"] = str(param_value.get("end", env_config.get("STRATEGY_TRADING_HOURS_END", "23")))
        elif param_name == "crossover_threshold_pips":
            env_config["STRATEGY_CROSSOVER_THRESHOLD_PIPS"] = str(param_value)
        elif param_name == "pre_separation_pips":
            env_config["STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS"] = str(param_value)
        elif param_name == "dmi_period":
            env_config["STRATEGY_DMI_PERIOD"] = str(param_value)
        elif param_name == "stochastic_period_k":
            env_config["STRATEGY_STOCH_PERIOD_K"] = str(param_value)
        elif param_name == "stochastic_period_d":
            env_config["STRATEGY_STOCH_PERIOD_D"] = str(param_value)
        elif param_name == "atr_period":
            env_config["STRATEGY_ATR_PERIOD"] = str(param_value)
        elif param_name == "atr_min_threshold":
            env_config["STRATEGY_ATR_MIN_THRESHOLD"] = str(param_value)
        elif param_name == "atr_max_threshold":
            env_config["STRATEGY_ATR_MAX_THRESHOLD"] = str(param_value)
        elif param_name == "adx_min_threshold":
            env_config["STRATEGY_ADX_MIN_THRESHOLD"] = str(param_value)
        elif param_name == "max_consecutive_losses":
            env_config["STRATEGY_MAX_CONSECUTIVE_LOSSES"] = str(param_value)
        elif param_name == "cooldown_bars":
            env_config["STRATEGY_COOLDOWN_BARS"] = str(param_value)
        # Add more mappings as needed for other filter parameters
    
    env_config["BACKTEST_SYMBOL"] = symbol
    env_config["CATALOG_PATH"] = str(catalog_base / filter_type)
    env_config["OUTPUT_DIR"] = str(output_dir)
    
    # Create subprocess environment
    process_env = os.environ.copy()
    process_env.update(env_config)
    
    logging.info(f"Running backtest for {filter_type}/{scenario_name} ({symbol})...")
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            [sys.executable, str(BACKTEST_SCRIPT)],
            env=process_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT)
        )
        
        duration = time.time() - start_time
        success = result.returncode == 0
        
        if success:
            logging.info(f"✅ Backtest completed successfully in {duration:.1f}s")
        else:
            logging.error(f"❌ Backtest failed with return code {result.returncode} in {duration:.1f}s")
            logging.debug(f"STDOUT: {result.stdout}")
            logging.debug(f"STDERR: {result.stderr}")
        
        # Find most recent output directory (timestamped subdirectory)
        timestamped_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
        if timestamped_dirs:
            latest_output = max(timestamped_dirs, key=lambda x: x.stat().st_mtime)
        else:
            latest_output = output_dir
        
        # Read performance stats if available
        trade_count = 0
        performance_file = latest_output / "performance_stats.json"
        if performance_file.exists():
            try:
                with open(performance_file, 'r') as f:
                    perf_data = json.load(f)
                trade_count = perf_data.get("general", {}).get("total_trades", 0)
            except (json.JSONDecodeError, KeyError) as e:
                logging.warning(f"Failed to parse performance stats: {e}")
        
        return {
            "success": success,
            "symbol": symbol,
            "scenario_name": scenario_name,
            "filter_type": filter_type,
            "trade_count": trade_count,
            "output_dir": latest_output,
            "expected_trades": scenario["expected_trades"],
            "expected_rejection": scenario["expected_rejection"],
            "duration_seconds": duration,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
        
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        logging.error(f"⏰ Backtest timed out after {duration:.1f}s")
        return {
            "success": False,
            "symbol": symbol,
            "scenario_name": scenario_name,
            "filter_type": filter_type,
            "trade_count": 0,
            "output_dir": output_dir,
            "expected_trades": scenario["expected_trades"],
            "expected_rejection": scenario["expected_rejection"],
            "duration_seconds": duration,
            "stdout": "",
            "stderr": "Timeout expired"
        }


def organize_results(result: Dict[str, Any], results_base: Path) -> None:
    """Organize results in structured output format."""
    if not result["success"] or not result["output_dir"].exists():
        return
    
    # Create organized results directory structure
    scenario_dir = results_base / result["filter_type"] / result["scenario_name"]
    scenario_dir.mkdir(parents=True, exist_ok=True)
    
    # Create runs subdirectory for timestamped runs
    runs_dir = scenario_dir / "runs"
    runs_dir.mkdir(exist_ok=True)
    
    # Get timestamp from the output directory name or create one
    timestamp = result["output_dir"].name
    if not timestamp or timestamp == result["scenario_name"]:
        # If no timestamp in directory name, use current timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create timestamped run directory
    run_dir = runs_dir / timestamp
    run_dir.mkdir(exist_ok=True)
    
    # Copy all output files to the timestamped run directory
    try:
        for file_path in result["output_dir"].iterdir():
            if file_path.is_file():
                shutil.copy2(file_path, run_dir / file_path.name)
        
        # Create or update 'latest' symlink pointing to the most recent run
        latest_link = scenario_dir / "latest"
        if latest_link.exists() or latest_link.is_symlink():
            latest_link.unlink()
        latest_link.symlink_to(f"runs/{timestamp}")
        
        logging.debug(f"Results organized at {run_dir} with latest symlink at {latest_link}")
        
    except Exception as e:
        logging.warning(f"Failed to organize results: {e}")


class BacktestProgress:
    """Track progress and statistics for backtest execution."""
    
    def __init__(self, total_scenarios: int):
        self.total_scenarios = total_scenarios
        self.completed = 0
        self.successful = 0
        self.failed = 0
        self.start_time = time.time()
        self.filter_results = {ft: {"completed": 0, "successful": 0, "failed": 0} for ft in FILTER_TYPES}
    
    def update(self, result: Dict[str, Any]) -> None:
        """Update progress based on backtest result."""
        self.completed += 1
        
        if result["success"]:
            self.successful += 1
            self.filter_results[result["filter_type"]]["successful"] += 1
        else:
            self.failed += 1
            self.filter_results[result["filter_type"]]["failed"] += 1
        
        self.filter_results[result["filter_type"]]["completed"] += 1
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time
    
    def get_eta(self, completed: int, total: int) -> float:
        """Estimate remaining time in seconds."""
        if completed == 0:
            return 0.0
        elapsed = self.get_elapsed_time()
        rate = completed / elapsed
        remaining = total - completed
        return remaining / rate if rate > 0 else 0.0
    
    def print_progress(self) -> None:
        """Print current progress status."""
        elapsed = self.get_elapsed_time()
        eta = self.get_eta(self.completed, self.total_scenarios)
        
        status = "✅" if self.successful > 0 else "❌" if self.failed > 0 else "⏳"
        logging.info(f"[{self.completed}/{self.total_scenarios}] {status} "
                    f"Completed: {self.successful}✅ {self.failed}❌ "
                    f"Elapsed: {elapsed:.1f}s ETA: {eta:.1f}s")
    
    def print_summary(self) -> None:
        """Print final summary statistics."""
        elapsed = self.get_elapsed_time()
        
        logging.info("🎉 Backtest execution completed!")
        logging.info(f"Total scenarios: {self.total_scenarios}")
        logging.info(f"Successful: {self.successful} ✅")
        logging.info(f"Failed: {self.failed} ❌")
        logging.info(f"Total time: {elapsed:.1f}s")
        
        if self.completed > 0:
            avg_time = elapsed / self.completed
            logging.info(f"Average time per scenario: {avg_time:.1f}s")
        
        # Per-filter breakdown
        logging.info("\nPer-filter results:")
        for filter_type, stats in self.filter_results.items():
            if stats["completed"] > 0:
                success_rate = (stats["successful"] / stats["completed"]) * 100
                logging.info(f"  {filter_type}: {stats['successful']}/{stats['completed']} "
                           f"({success_rate:.1f}%) ✅")


def run_all_backtests(filter_types: Optional[List[str]] = None, 
                     scenarios: Optional[List[str]] = None, 
                     parallel: bool = False,
                     timeout: int = 300,
                     continue_on_error: bool = True,
                     catalog_base: Path = CATALOG_BASE) -> int:
    """Run all backtests for discovered scenarios."""
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Validate catalog base exists
    if not catalog_base.exists():
        logging.error(f"Catalog base directory does not exist: {catalog_base}")
        return 1
    
    # Create results base directory
    RESULTS_BASE.mkdir(parents=True, exist_ok=True)
    
    # Discover test scenarios
    logging.info("📊 Discovering test scenarios...")
    all_scenarios = discover_test_scenarios(catalog_base)
    
    if not all_scenarios:
        logging.error("No test scenarios found!")
        return 1
    
    # Filter scenarios based on arguments
    filtered_scenarios = {}
    for filter_type, scenario_list in all_scenarios.items():
        if filter_types and filter_type not in filter_types:
            continue
        
        if scenarios:
            filtered_list = [s for s in scenario_list if s["scenario_name"] in scenarios]
        else:
            filtered_list = scenario_list
        
        if filtered_list:
            filtered_scenarios[filter_type] = filtered_list
    
    total_scenarios = sum(len(scenarios) for scenarios in filtered_scenarios.values())
    if total_scenarios == 0:
        logging.error("No scenarios match the specified filters!")
        return 1
    
    # Initialize progress tracker
    progress = BacktestProgress(total_scenarios)
    
    logging.info(f"🚀 Starting backtest execution for {total_scenarios} scenarios across {len(filtered_scenarios)} filters")
    
    # Execute backtests
    for filter_type, scenario_list in filtered_scenarios.items():
        logging.info(f"\n--- Running {filter_type} filter tests ---")
        
        for scenario in scenario_list:
            try:
                result = run_backtest_for_scenario(scenario, filter_type, RESULTS_BASE, catalog_base, timeout)
                progress.update(result)
                
                # Log individual result
                if result["success"]:
                    if result["trade_count"] == result["expected_trades"]:
                        logging.info(f"✅ {filter_type}/{scenario['scenario_name']}: {result['trade_count']} trades (expected)")
                    else:
                        logging.warning(f"⚠️ {filter_type}/{scenario['scenario_name']}: {result['trade_count']} trades (expected {result['expected_trades']})")
                else:
                    logging.error(f"❌ {filter_type}/{scenario['scenario_name']}: Failed")
                
                # Organize results
                organize_results(result, RESULTS_BASE)
                
                # Print progress
                progress.print_progress()
                
                # Check if we should continue on error
                if not result["success"] and not continue_on_error:
                    logging.error("Stopping execution due to failure and --continue-on-error=False")
                    return 1
                
            except Exception as e:
                logging.error(f"❌ Unexpected error in {filter_type}/{scenario['scenario_name']}: {e}")
                progress.failed += 1
                progress.completed += 1
                if not continue_on_error:
                    logging.error("Stopping execution due to unexpected error and --continue-on-error=False")
                    return 1
                continue
    
    # Print final summary
    progress.print_summary()
    
    return 0 if progress.failed == 0 else 1


def main() -> int:
    """Main entry point with command-line interface."""
    parser = argparse.ArgumentParser(
        description="Run backtests for all comprehensive filter test scenarios"
    )
    
    parser.add_argument(
        "--filter",
        choices=FILTER_TYPES,
        help="Run backtests for specific filter type only"
    )
    
    parser.add_argument(
        "--scenario",
        help="Run backtest for specific scenario name only"
    )
    
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available scenarios and exit"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (DEBUG level)"
    )
    
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        default=False,
        help="Continue running remaining scenarios after failures"
    )
    
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout for each backtest in seconds (default: 300)"
    )
    
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=CATALOG_BASE,
        help=f"Path to catalog directory (default: {CATALOG_BASE})"
    )
    
    args = parser.parse_args()
    
    # Handle --list option
    if args.list:
        logging.basicConfig(level=logging.INFO)
        scenarios = discover_test_scenarios(args.catalog_dir)
        
        print("\nAvailable test scenarios:")
        print("=" * 50)
        
        for filter_type, scenario_list in scenarios.items():
            print(f"\n{filter_type.upper()}:")
            for scenario in scenario_list:
                print(f"  - {scenario['scenario_name']} ({scenario['symbol']})")
                print(f"    Expected trades: {scenario['expected_trades']}")
                print(f"    Description: {scenario['description']}")
        
        return 0
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Run backtests
    filter_types = [args.filter] if args.filter else None
    scenario_names = [args.scenario] if args.scenario else None
    
    return run_all_backtests(filter_types, scenario_names, timeout=args.timeout, continue_on_error=args.continue_on_error, catalog_base=args.catalog_dir)


if __name__ == "__main__":
    sys.exit(main())
