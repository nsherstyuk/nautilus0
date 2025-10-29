#!/usr/bin/env python3
"""
Baseline Validation Script for Optimization Workflow

Purpose: Validate EUR/USD data availability and establish baseline performance metrics for optimization
Usage: python optimization/validate_baseline.py [--catalog-path PATH] [--output-dir PATH] [--verbose]
Output: optimization/results/baseline_metrics.json with baseline performance metrics

This script orchestrates a three-phase workflow:
1. Verify EUR/USD historical data availability for the optimization period
2. Execute a baseline backtest with default parameters
3. Extract and save performance metrics for comparison with optimized results

The script uses subprocess execution for isolation, follows existing patterns from
data/verify_catalog.py and backtest/run_backtest.py, and generates both JSON and console reports.
"""

import sys
import os
import json
import logging
import subprocess
import argparse
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

import pandas as pd

# Project imports
from data.verify_catalog import collect_bar_summaries, check_date_overlap, CatalogBarSummary
from config.backtest_config import BacktestConfig

# ParquetDataCatalog will be imported locally within verify_data_availability() to avoid premature termination

# Constants
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "data" / "historical"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "optimization" / "results"
BACKTEST_SCRIPT = PROJECT_ROOT / "backtest" / "run_backtest.py"
TARGET_SYMBOL = "EUR/USD"
TARGET_VENUE = "IDEALPRO"
TARGET_START_DATE = "2025-01-01"
TARGET_END_DATE = "2025-07-31"
TARGET_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
EXPECTED_INSTRUMENT_ID = "EURUSD.IDEALPRO"  # catalog format without slash
EXPECTED_BAR_TYPE = f"{EXPECTED_INSTRUMENT_ID}-{TARGET_BAR_SPEC}"
SCRIPT_VERSION = "1.0.0"


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Setup logging configuration."""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    return logger


def verify_data_availability(catalog_path: Path, logger: logging.Logger) -> Tuple[bool, Dict[str, Any]]:
    """
    Verify EUR/USD data exists for optimization period using patterns from data/verify_catalog.py.
    
    Returns:
        Tuple[bool, Dict[str, Any]]: (success, data_coverage_dict)
    """
    try:
        logger.info(f"Verifying data availability for {TARGET_SYMBOL} ({TARGET_VENUE})")
        
        # Check catalog path exists
        if not catalog_path.exists():
            return False, {"error": "Catalog not found"}
        
        # Load ParquetDataCatalog with error handling
        try:
            from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
        except ImportError as exc:
            return False, {"error": "NautilusTrader not installed", "details": str(exc)}
        
        try:
            catalog = ParquetDataCatalog(str(catalog_path))
        except Exception as exc:
            return False, {"error": f"Failed to initialize ParquetDataCatalog: {exc}"}
        
        # Collect bar summaries
        summaries = collect_bar_summaries(catalog)
        
        # Prepare acceptable instrument IDs (both slashed and no-slash representations)
        acceptable_instrument_ids = {"EURUSD.IDEALPRO", "EUR/USD.IDEALPRO"}
        
        # Filter for acceptable EUR/USD instrument IDs
        eurusd_summaries = [s for s in summaries if s.instrument_id in acceptable_instrument_ids]
        
        if not eurusd_summaries:
            available_instruments = list(set(s.instrument_id for s in summaries))
            logger.error(f"No EURUSD data found. Available instruments: {available_instruments}")
            return False, {"error": "No EURUSD data found", "available_instruments": available_instruments}
        
        # Find matching bar type (support both slashed and no-slash representations)
        matching_summary = None
        for summary in eurusd_summaries:
            # Check if bar_type matches either EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL or EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL
            if summary.bar_type.endswith(f"-{TARGET_BAR_SPEC}") and (
                summary.bar_type.startswith("EURUSD.IDEALPRO-") or 
                summary.bar_type.startswith("EUR/USD.IDEALPRO-")
            ):
                matching_summary = summary
                break
        
        if not matching_summary:
            available_bar_types = [s.bar_type for s in eurusd_summaries]
            logger.error(f"Required bar type ending with -{TARGET_BAR_SPEC} not found in catalog")
            logger.error(f"Available bar types for EURUSD: {available_bar_types}")
            return False, {"error": "Required bar type not found", "available": available_bar_types}
        
        # Extract data coverage information
        bar_count = matching_summary.bar_count
        start_ts = matching_summary.start_ts
        end_ts = matching_summary.end_ts
        
        logger.info(f"Found {bar_count} bars from {start_ts} to {end_ts}")
        
        # Convert timestamps to datetime objects
        start_dt = pd.to_datetime(start_ts)
        end_dt = pd.to_datetime(end_ts)
        
        # Parse target dates
        target_start = pd.to_datetime(TARGET_START_DATE)
        target_end = pd.to_datetime(TARGET_END_DATE)
        
        # Check date overlap
        overlap_start = max(start_dt, target_start)
        overlap_end = min(end_dt, target_end)
        
        if overlap_start >= overlap_end:
            logger.error(f"No date overlap between data ({start_dt} to {end_dt}) and target period ({target_start} to {target_end})")
            return False, {"error": "No date overlap", "data_range": f"{start_dt} to {end_dt}", "target_range": f"{target_start} to {target_end}"}
        
        # Validate sufficient coverage - enforce full target range using boundary equality
        # This avoids off-by-one errors and ensures exact full-range coverage is accepted
        if overlap_start > target_start or overlap_end < target_end:
            # Calculate coverage days for reporting (inclusive)
            coverage_days = (overlap_end - overlap_start).days + 1
            target_days = (target_end - target_start).days + 1
            return False, {"error": "Insufficient coverage", "coverage_days": coverage_days, "expected_days": target_days, "data_range": f"{start_dt} to {end_dt}"}
        
        # Calculate coverage days for reporting (inclusive)
        coverage_days = (overlap_end - overlap_start).days + 1
        
        return True, {
            "bars_available": bar_count,
            "start_date": start_dt.isoformat(),
            "end_date": end_dt.isoformat(),
            "coverage_days": coverage_days
        }
        
    except Exception as exc:
        logger.error(f"Data verification failed: {exc}")
        return False, {"error": str(exc)}


def run_baseline_backtest(catalog_path: Path, logger: logging.Logger, timeout_seconds: int = 1800) -> Tuple[bool, Optional[Path]]:
    """
    Execute baseline backtest with default parameters via subprocess.
    
    Returns:
        Tuple[bool, Optional[Path]]: (success, backtest_output_dir)
    """
    try:
        logger.info("Executing baseline backtest with default parameters...")
        
        # Build environment variables with defaults from BacktestConfig
        env = os.environ.copy()
        env.update({
            "BACKTEST_SYMBOL": TARGET_SYMBOL,
            "BACKTEST_VENUE": TARGET_VENUE,
            "BACKTEST_START_DATE": TARGET_START_DATE,
            "BACKTEST_END_DATE": TARGET_END_DATE,
            "BACKTEST_BAR_SPEC": TARGET_BAR_SPEC,
            "CATALOG_PATH": str(catalog_path),
            "OUTPUT_DIR": str(PROJECT_ROOT / "logs" / "backtest_results"),
            # Default parameters from BacktestConfig
            "BACKTEST_FAST_PERIOD": "10",
            "BACKTEST_SLOW_PERIOD": "20",
            "BACKTEST_TRADE_SIZE": "100",
            "BACKTEST_STARTING_CAPITAL": "100000.0",
            "BACKTEST_STOP_LOSS_PIPS": "25",
            "BACKTEST_TAKE_PROFIT_PIPS": "50",
            "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": "20",
            "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": "15",
            "BACKTEST_CROSSOVER_THRESHOLD_PIPS": "0.7",
            "BACKTEST_PRE_CROSSOVER_SEPARATION_PIPS": "0.0",
            "BACKTEST_PRE_CROSSOVER_LOOKBACK_BARS": "1",
            "BACKTEST_DMI_ENABLED": "True",
            "BACKTEST_DMI_PERIOD": "14",
            "BACKTEST_DMI_BAR_SPEC": "2-MINUTE-MID-EXTERNAL",
            "BACKTEST_STOCH_ENABLED": "True",
            "STRATEGY_STOCH_PERIOD_K": "14",
            "STRATEGY_STOCH_PERIOD_D": "3",
            "BACKTEST_STOCH_BULLISH_THRESHOLD": "30",
            "BACKTEST_STOCH_BEARISH_THRESHOLD": "70",
            "BACKTEST_STOCH_MAX_BARS_SINCE_CROSSING": "9",
            "BACKTEST_USE_LIMIT_ORDERS": "True",
            "BACKTEST_LIMIT_ORDER_TIMEOUT_BARS": "1"
        })
        
        logger.info(f"Baseline backtest configuration: fast={env['BACKTEST_FAST_PERIOD']}, slow={env['BACKTEST_SLOW_PERIOD']}, SL={env['BACKTEST_STOP_LOSS_PIPS']}, TP={env['BACKTEST_TAKE_PROFIT_PIPS']}")
        
        # Build command
        cmd = [sys.executable, str(BACKTEST_SCRIPT)]
        
        # Execute subprocess
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(PROJECT_ROOT)
        )
        
        if result.returncode == 0:
            logger.info("Backtest completed successfully")
        else:
            logger.error(f"Backtest failed with return code {result.returncode}")
            logger.error(f"Backtest stderr: {result.stderr}")
            return False, None
        
        # Find most recent output directory
        output_base = PROJECT_ROOT / "logs" / "backtest_results"
        if not output_base.exists():
            logger.error("Backtest output directory not found")
            return False, None
        
        # Find directories matching EUR-USD_* pattern
        eurusd_dirs = [d for d in output_base.iterdir() if d.is_dir() and d.name.startswith("EUR-USD_")]
        
        if not eurusd_dirs:
            logger.error("No EUR-USD backtest results found")
            return False, None
        
        # Get most recent by modification time
        most_recent = max(eurusd_dirs, key=lambda d: d.stat().st_mtime)
        
        logger.debug(f"Found backtest output: {most_recent}")
        return True, most_recent
        
    except subprocess.TimeoutExpired:
        logger.error(f"Backtest timed out after {timeout_seconds} seconds")
        return False, None
    except FileNotFoundError:
        logger.error(f"Backtest script not found: {BACKTEST_SCRIPT}")
        return False, None
    except Exception as exc:
        logger.error(f"Unexpected error during backtest: {exc}")
        return False, None


def extract_metrics(output_dir: Path, logger: logging.Logger) -> Tuple[bool, Dict[str, Any]]:
    """
    Parse performance_stats.json and extract required metrics.
    
    Returns:
        Tuple[bool, Dict[str, Any]]: (success, metrics_dict)
    """
    try:
        logger.info(f"Extracting metrics from {output_dir}")
        
        # Construct path to performance_stats.json
        performance_stats_path = output_dir / "performance_stats.json"
        
        if not performance_stats_path.exists():
            logger.error("performance_stats.json not found")
            return False, {"error": "performance_stats.json not found"}
        
        # Load JSON
        stats = json.loads(performance_stats_path.read_text())
        
        # Import shared metrics extraction helper
        from optimization.grid_search import extract_metrics_from_stats
        
        # Extract metrics using shared helper for consistency
        base_metrics = extract_metrics_from_stats(stats)
        
        # Build metrics dictionary with consistent structure
        metrics = {
            "total_pnl": base_metrics["total_pnl"],
            "sharpe_ratio": base_metrics["sharpe_ratio"],
            "win_rate": base_metrics["win_rate"],
            "max_drawdown": base_metrics["max_drawdown"],
            "total_trades": base_metrics["trade_count"],
            "additional_metrics": {
                "profit_factor": base_metrics["profit_factor"],
                "avg_win": base_metrics["avg_winner"],
                "avg_loss": base_metrics["avg_loser"],
                "total_pnl_percentage": base_metrics["pnl_percentage"],
                "max_drawdown_percentage": base_metrics.get("max_drawdown_percentage", 0.0),
                "rejected_signals_count": base_metrics["rejected_signals_count"]
            }
        }
        
        logger.info(f"Baseline metrics: PnL={metrics['total_pnl']:.2f}, Sharpe={metrics['sharpe_ratio']:.2f}, WinRate={metrics['win_rate']:.2%}, Trades={metrics['total_trades']}")
        
        if metrics['total_trades'] == 0:
            logger.warning("Zero trades detected - baseline may not be meaningful")
        
        return True, metrics
        
    except json.JSONDecodeError:
        logger.error("Invalid JSON in performance_stats.json")
        return False, {"error": "Invalid JSON"}
    except FileNotFoundError:
        logger.error("performance_stats.json not found")
        return False, {"error": "performance_stats.json not found"}
    except KeyError as exc:
        logger.error(f"Missing expected keys in performance_stats.json: {exc}")
        return False, {"error": "Missing keys"}
    except Exception as exc:
        logger.error(f"Unexpected error extracting metrics: {exc}")
        return False, {"error": str(exc)}


def collect_baseline_configuration() -> Dict[str, Any]:
    """
    Document all default parameters used in baseline backtest.
    
    Returns:
        Dict[str, Any]: Configuration dictionary with all default parameters
    """
    return {
        "fast_period": 10,
        "slow_period": 20,
        "trade_size": 100,
        "starting_capital": 100000.0,
        "stop_loss_pips": 25,
        "take_profit_pips": 50,
        "trailing_stop_activation_pips": 20,
        "trailing_stop_distance_pips": 15,
        "crossover_threshold_pips": 0.7,
        "pre_crossover_separation_pips": 0.0,
        "pre_crossover_lookback_bars": 1,
        "dmi_enabled": True,
        "dmi_period": 14,
        "dmi_bar_spec": "2-MINUTE-MID-EXTERNAL",
        "stoch_enabled": True,
        "stoch_period_k": 14,
        "stoch_period_d": 3,
        "stoch_bullish_threshold": 30,
        "stoch_bearish_threshold": 70,
        "stoch_max_bars_since_crossing": 9,
        "use_limit_orders": True,
        "limit_order_timeout_bars": 1
    }


def save_baseline_report(output_path: Path, data_coverage: Dict[str, Any], metrics: Dict[str, Any], 
                        config: Dict[str, Any], backtest_output_dir: Path, execution_time: float, 
                        logger: logging.Logger) -> bool:
    """
    Save comprehensive baseline report to JSON file.
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Saving baseline report to {output_path}")
        
        # Create output directory
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Build report structure
        report = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "script_version": SCRIPT_VERSION,
                "execution_time_seconds": execution_time
            },
            "configuration": {
                "symbol": TARGET_SYMBOL,
                "venue": TARGET_VENUE,
                "period": {"start": TARGET_START_DATE, "end": TARGET_END_DATE},
                "bar_spec": TARGET_BAR_SPEC,
                "parameters": config
            },
            "data_coverage": data_coverage,
            "metrics": metrics,
            "backtest_output_dir": str(backtest_output_dir)
        }
        
        # Write JSON with indent for readability
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info("Baseline report saved successfully")
        return True
        
    except OSError as exc:
        logger.error(f"Failed to create output directory: {exc}")
        return False
    except Exception as exc:
        logger.error(f"Failed to write baseline report: {exc}")
        return False


def print_console_report(data_coverage: Dict[str, Any], metrics: Dict[str, Any], 
                        config: Dict[str, Any], logger: logging.Logger) -> None:
    """Print formatted summary to console."""
    
    print("\n" + "="*60)
    print("BASELINE VALIDATION REPORT")
    print("="*60)
    
    # Data coverage section
    print("\nDATA COVERAGE:")
    print(f"Symbol: {TARGET_SYMBOL} ({TARGET_VENUE})")
    print(f"Period: {TARGET_START_DATE} to {TARGET_END_DATE}")
    print(f"Bar Spec: {TARGET_BAR_SPEC}")
    print(f"Bars Available: {data_coverage.get('bars_available', 0):,}")
    print(f"Actual Coverage: {data_coverage.get('start_date', 'N/A')} to {data_coverage.get('end_date', 'N/A')} ({data_coverage.get('coverage_days', 0)} days)")
    
    # Baseline configuration section
    print("\nBASELINE CONFIGURATION:")
    print(f"MA Periods: Fast={config.get('fast_period', 'N/A')}, Slow={config.get('slow_period', 'N/A')}")
    print(f"Risk Management: SL={config.get('stop_loss_pips', 'N/A')} pips, TP={config.get('take_profit_pips', 'N/A')} pips")
    print(f"Trailing Stop: Activation={config.get('trailing_stop_activation_pips', 'N/A')} pips, Distance={config.get('trailing_stop_distance_pips', 'N/A')} pips")
    print(f"Filters: DMI={config.get('dmi_enabled', 'N/A')}, Stochastic={config.get('stoch_enabled', 'N/A')}")
    
    # Baseline metrics section
    print("\nBASELINE PERFORMANCE METRICS:")
    print(f"Total Trades: {metrics.get('total_trades', 0)}")
    print(f"Total PnL: ${metrics.get('total_pnl', 0):,.2f} ({metrics.get('additional_metrics', {}).get('total_pnl_percentage', 0):.2f}%)")
    print(f"Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.3f}")
    print(f"Win Rate: {metrics.get('win_rate', 0):.2%}")
    print(f"Max Drawdown: ${metrics.get('max_drawdown', 0):,.2f} ({metrics.get('additional_metrics', {}).get('max_drawdown_percentage', 0):.2f}%)")
    print(f"Profit Factor: {metrics.get('additional_metrics', {}).get('profit_factor', 'N/A')}")
    print(f"Rejected Signals: {metrics.get('additional_metrics', {}).get('rejected_signals_count', 0)}")
    
    # Footer
    print("\n" + "="*60)
    print("Baseline validation completed successfully.")
    print("Use these metrics as comparison baseline for optimization.")
    print("="*60 + "\n")


def main() -> int:
    """Orchestrate complete baseline validation workflow."""
    try:
        # Parse command-line arguments
        parser = argparse.ArgumentParser(description="Validate baseline performance for optimization workflow")
        parser.add_argument("--catalog-path", type=str, default=str(DEFAULT_CATALOG_PATH),
                           help="Path to ParquetDataCatalog")
        parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR),
                           help="Output directory for baseline metrics")
        parser.add_argument("--output-file", type=str, default="baseline_metrics.json",
                           help="Output filename")
        parser.add_argument("--verbose", action="store_true",
                           help="Enable verbose logging (DEBUG level)")
        parser.add_argument("--skip-backtest", action="store_true",
                           help="Skip backtest execution (use existing results)")
        parser.add_argument("--backtest-output-dir", type=str,
                           help="Path to existing backtest results (required with --skip-backtest)")
        parser.add_argument("--timeout-seconds", type=int, default=1800,
                           help="Backtest timeout in seconds (default: 1800)")
        
        args = parser.parse_args()
        
        # Validate argument combinations
        if args.skip_backtest and not args.backtest_output_dir:
            print("Error: --backtest-output-dir is required when using --skip-backtest")
            return 1
        
        if args.backtest_output_dir and not args.skip_backtest:
            print("Warning: --backtest-output-dir specified but --skip-backtest not set")
        
        # Setup logging
        logger = setup_logging(args.verbose)
        
        # Record start time
        start_time = time.time()
        
        logger.info(f"🚀 Starting baseline validation for {TARGET_SYMBOL}")
        
        # Convert paths
        catalog_path = Path(args.catalog_path)
        output_dir = Path(args.output_dir)
        output_path = output_dir / args.output_file
        
        # Phase 1: Data Verification
        logger.info("📊 Phase 1: Verifying data availability...")
        success, data_coverage = verify_data_availability(catalog_path, logger)
        
        if not success:
            logger.error(f"❌ Data verification failed: {data_coverage.get('error', 'Unknown error')}")
            if 'available' in data_coverage:
                logger.info(f"Available bar types: {data_coverage['available']}")
            return 1
        
        logger.info("✅ Data verification passed")
        
        # Phase 2: Backtest Execution
        if not args.skip_backtest:
            logger.info("🔄 Phase 2: Running baseline backtest...")
            success, backtest_output_dir = run_baseline_backtest(catalog_path, logger, args.timeout_seconds)
            
            if not success:
                logger.error("❌ Baseline backtest failed")
                return 2
            
            logger.info("✅ Baseline backtest completed")
        else:
            logger.info("⏭️ Phase 2: Skipping backtest (using existing results)")
            backtest_output_dir = Path(args.backtest_output_dir)
            
            if not backtest_output_dir.exists():
                logger.error(f"❌ Backtest output directory not found: {backtest_output_dir}")
                return 2
        
        # Phase 3: Metrics Extraction
        logger.info("📈 Phase 3: Extracting performance metrics...")
        success, metrics = extract_metrics(backtest_output_dir, logger)
        
        if not success:
            logger.error(f"❌ Metrics extraction failed: {metrics.get('error', 'Unknown error')}")
            return 3
        
        logger.info("✅ Metrics extraction completed")
        
        # Phase 4: Report Generation
        logger.info("📝 Phase 4: Generating baseline report...")
        config = collect_baseline_configuration()
        execution_time = time.time() - start_time
        
        success = save_baseline_report(output_path, data_coverage, metrics, config, 
                                     backtest_output_dir, execution_time, logger)
        
        if not success:
            logger.error("❌ Baseline report generation failed")
            return 4
        
        # Print console report
        print_console_report(data_coverage, metrics, config, logger)
        
        logger.info(f"✅ Baseline report saved to {output_path}")
        logger.info(f"🎉 Baseline validation completed successfully in {execution_time:.1f}s")
        
        return 0
        
    except KeyboardInterrupt:
        logger.warning("⚠️ Validation interrupted by user")
        return 130
    except Exception as exc:
        logger.error(f"❌ Unexpected error: {exc}")
        import traceback
        logger.debug(traceback.format_exc())
        return 5


if __name__ == "__main__":
    sys.exit(main())
