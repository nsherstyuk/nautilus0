"""
MA Diagnostics Runner

End-to-end automated diagnostic system for MA crossover strategy.
This script orchestrates the complete diagnostic workflow: generate data → run backtests → analyze results → generate reports.

Workflow:
1. Generate diagnostic test data (8 specialized scenarios)
2. Run backtests for each scenario
3. Analyze results to detect algorithmic misbehavior
4. Generate comprehensive reports (HTML + JSON)

Usage:
    python tests/run_ma_diagnostics.py [--skip-data-gen] [--skip-backtests] [--output-dir PATH]

Options:
    --skip-data-gen: Skip data generation step (use existing data)
    --skip-backtests: Skip backtest execution (analyze existing results)
    --output-dir PATH: Custom output directory for reports (default: reports/ma_diagnostics)
    --verbose: Enable debug logging

Output:
    - HTML report with embedded charts
    - JSON report for programmatic access
    - Console summary
"""

import os
import sys
import subprocess
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add project root to sys.path for module imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ma_diagnostics_analyzer import (
    analyze_diagnostic_results,
    export_report_json,
    MADiagnosticReport,
    DiagnosticScenario,
    DIAGNOSTIC_SCENARIOS_CONFIG
)
from ma_diagnostics_reporter import generate_html_report, generate_markdown_report, print_console_report

# Configuration Constants
DATA_GENERATOR_SCRIPT = PROJECT_ROOT / "tests" / "generate_phase6_ma_diagnostic_data.py"
BACKTEST_SCRIPT = PROJECT_ROOT / "backtest" / "run_backtest.py"
ENV_CONFIGS_DIR = PROJECT_ROOT / "tests" / "env_configs"
CATALOG_PATH = "data/test_catalog/phase6_ma_diagnostics"
DEFAULT_OUTPUT_DIR = "reports/ma_diagnostics"

# MA Diagnostic Scenarios
MA_DIAGNOSTIC_SCENARIOS = [
    DiagnosticScenario(
        name="single_crossover",
        symbol="EUR/USD",
        expected_trades=1,
        expected_outcome="pass",
        purpose="Verify single bullish crossover detection",
        issue_indicators=["missed_crossover", "timing_error"]
    ),
    DiagnosticScenario(
        name="multiple_crossovers",
        symbol="GBP/USD",
        expected_trades=5,
        expected_outcome="pass",
        purpose="Verify multiple alternating crossover detection",
        issue_indicators=["missed_crossovers", "false_positives"]
    ),
    DiagnosticScenario(
        name="edge_case",
        symbol="AUD/USD",
        expected_trades=1,
        expected_outcome="pass",
        purpose="Verify crossover at exact MA equality (boundary condition)",
        issue_indicators=["boundary_failure", "off_by_one"]
    ),
    DiagnosticScenario(
        name="delayed_crossover",
        symbol="USD/JPY",
        expected_trades=1,
        expected_outcome="pass",
        purpose="Verify timing accuracy with slow MA convergence",
        issue_indicators=["timing_error", "delayed_detection"]
    )
]


def setup_logging(verbose: bool = False) -> logging.Logger:
    """
    Configure logging with appropriate level and handlers.
    
    Args:
        verbose: Whether to enable debug logging
        
    Returns:
        Configured logger
    """
    level = logging.DEBUG if verbose else logging.INFO
    
    # Create logger
    logger = logging.getLogger(__name__)
    logger.setLevel(level)
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    
    # Add handler
    logger.addHandler(console_handler)
    
    return logger


def generate_diagnostic_data() -> bool:
    """
    Execute data generation script for Phase 6 diagnostics.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        logger = logging.getLogger(__name__)
        logger.info("Generating diagnostic test data...")
        
        result = subprocess.run(
            ["python", str(DATA_GENERATOR_SCRIPT)],
            check=True,
            timeout=300,
            capture_output=True,
            text=True
        )
        
        logger.info("Diagnostic data generation completed successfully")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Data generation failed with exit code {e.returncode}")
        logger.error(f"STDOUT: {e.stdout}")
        logger.error(f"STDERR: {e.stderr}")
        return False
        
    except subprocess.TimeoutExpired:
        logger.error("Data generation timed out after 5 minutes")
        return False
        
    except Exception as e:
        logger.error(f"Unexpected error during data generation: {e}")
        return False


def create_diagnostic_env_file(scenario: DiagnosticScenario, output_path: Path) -> None:
    """
    Generate .env file for specific diagnostic scenario.
    
    Args:
        scenario: Diagnostic scenario configuration
        output_path: Path to write .env file
    """
    logger = logging.getLogger(__name__)
    
    # Base template content
    env_content = f"""# Phase 6: MA Diagnostics - {scenario.name}
# Generated automatically by run_ma_diagnostics.py

# Catalog and Symbol Configuration
CATALOG_PATH={CATALOG_PATH}
OUTPUT_DIR=logs/test_results/phase6_ma_diagnostics/{scenario.name}
BACKTEST_SYMBOL={scenario.symbol}
BACKTEST_VENUE=IDEALPRO

# Date Range
BACKTEST_START_DATE=2024-01-01
BACKTEST_END_DATE=2024-01-10

# Bar Specification
BACKTEST_BAR_SPEC=1-MINUTE-MID-EXTERNAL

# MA Periods
BACKTEST_FAST_PERIOD=10
BACKTEST_SLOW_PERIOD=20

# Position Sizing
BACKTEST_TRADE_SIZE=100000
BACKTEST_STARTING_CAPITAL=100000.0

# Position Management
ENFORCE_POSITION_LIMIT=true
ALLOW_POSITION_REVERSAL=false

# Stop Loss / Take Profit (set very high to avoid premature exits)
BACKTEST_STOP_LOSS_PIPS=10000
BACKTEST_TAKE_PROFIT_PIPS=20000
BACKTEST_TRAILING_STOP_ACTIVATION_PIPS=1
BACKTEST_TRAILING_STOP_DISTANCE_PIPS=0

# FILTERS ENABLED FOR PROPER MA DIAGNOSTICS TESTING
STRATEGY_CROSSOVER_THRESHOLD_PIPS=5.0
STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS=2.0
STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS=3
STRATEGY_DMI_ENABLED=false
STRATEGY_DMI_PERIOD=14
STRATEGY_DMI_BAR_SPEC=1-MINUTE-MID-EXTERNAL
STRATEGY_STOCH_ENABLED=false
STRATEGY_STOCH_PERIOD_K=14
STRATEGY_STOCH_PERIOD_D=3
STRATEGY_STOCH_BULLISH_THRESHOLD=30
STRATEGY_STOCH_BEARISH_THRESHOLD=70
STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING=9
STRATEGY_STOCH_BAR_SPEC=1-MINUTE-MID-EXTERNAL
STRATEGY_ATR_ENABLED=false
STRATEGY_ATR_PERIOD=14
STRATEGY_ATR_MIN_THRESHOLD=0.0
STRATEGY_ATR_MAX_THRESHOLD=999.0
STRATEGY_ATR_BAR_SPEC=1-MINUTE-MID-EXTERNAL
STRATEGY_ADX_ENABLED=false
STRATEGY_ADX_MIN_THRESHOLD=0.0
STRATEGY_TIME_FILTER_ENABLED=false
STRATEGY_TRADING_HOURS_START=0
STRATEGY_TRADING_HOURS_END=23
STRATEGY_MARKET_TIMEZONE=UTC
STRATEGY_CIRCUIT_BREAKER_ENABLED=false
STRATEGY_MAX_CONSECUTIVE_LOSSES=999
STRATEGY_COOLDOWN_BARS=0

# Order Configuration
STRATEGY_USE_LIMIT_ORDERS=false
STRATEGY_LIMIT_ORDER_TIMEOUT_BARS=0

# Logging
LOG_LEVEL=INFO
LOG_DIR=logs
"""
    
    # Apply scenario-specific overrides
    if scenario.name == 'filter_cascade_failure':
        # Enable DMI for this scenario
        env_content = env_content.replace('STRATEGY_DMI_ENABLED=false', 'STRATEGY_DMI_ENABLED=true')
    
    # Write to file
    with open(output_path, 'w') as f:
        f.write(env_content)
    
    logger.debug(f"Created env file for {scenario.name} at {output_path}")


def run_diagnostic_backtest(scenario: DiagnosticScenario, env_file: Path) -> Dict[str, Any]:
    """
    Run backtest for a single diagnostic scenario.
    
    Args:
        scenario: Diagnostic scenario configuration
        env_file: Path to .env file for this scenario
        
    Returns:
        Dictionary with backtest results
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Load environment variables from env_file
        env_vars = {}
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
        
        # Merge with system environment
        merged_env = {**os.environ, **env_vars}
        
        # Run backtest
        logger.info(f"Running backtest for {scenario.name}...")
        
        result = subprocess.run(
            [sys.executable, str(BACKTEST_SCRIPT)],
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            logger.error(f"Backtest failed for {scenario.name} with exit code {result.returncode}")
            logger.error(f"STDERR: {result.stderr}")
            return {
                "success": False,
                "output_dir": None,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        
        # Find output directory (most recent subdirectory in OUTPUT_DIR)
        output_dir = Path(env_vars.get("OUTPUT_DIR", "logs/test_results/phase6_ma_diagnostics"))
        if output_dir.exists():
            subdirs = [d for d in output_dir.iterdir() if d.is_dir()]
            if subdirs:
                # Sort by modification time and take most recent
                latest_dir = max(subdirs, key=lambda x: x.stat().st_mtime)
                return {
                    "success": True,
                    "output_dir": latest_dir,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
        
        logger.warning(f"Could not find output directory for {scenario.name}")
        return {
            "success": True,
            "output_dir": None,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
        
    except subprocess.TimeoutExpired:
        logger.error(f"Backtest timed out for {scenario.name}")
        return {
            "success": False,
            "output_dir": None,
            "stdout": "",
            "stderr": "Backtest timed out"
        }
        
    except Exception as e:
        logger.error(f"Error running backtest for {scenario.name}: {e}")
        return {
            "success": False,
            "output_dir": None,
            "stdout": "",
            "stderr": str(e)
        }


def run_all_diagnostic_backtests(scenarios: List[DiagnosticScenario]) -> Dict[str, Path]:
    """
    Run backtests for all diagnostic scenarios.
    
    Args:
        scenarios: List of diagnostic scenarios
        
    Returns:
        Dictionary mapping scenario name to output directory path
    """
    logger = logging.getLogger(__name__)
    
    # Create temporary env files directory
    env_dir = ENV_CONFIGS_DIR / "diagnostics"
    env_dir.mkdir(parents=True, exist_ok=True)
    
    results = {}
    
    try:
        for i, scenario in enumerate(scenarios, 1):
            logger.info(f"Running scenario {i}/{len(scenarios)}: {scenario.name}")
            
            # Create env file
            env_file = env_dir / f"{scenario.name}.env"
            create_diagnostic_env_file(scenario, env_file)
            
            # Run backtest
            backtest_result = run_diagnostic_backtest(scenario, env_file)
            
            if backtest_result["success"] and backtest_result["output_dir"]:
                results[scenario.name] = backtest_result["output_dir"]
                logger.info(f"✓ {scenario.name} completed successfully")
            else:
                logger.error(f"✗ {scenario.name} failed")
                if backtest_result["stderr"]:
                    logger.error(f"Error details: {backtest_result['stderr']}")
        
        return results
        
    finally:
        # Clean up temporary env files
        try:
            import shutil
            if env_dir.exists():
                shutil.rmtree(env_dir)
                logger.debug("Cleaned up temporary env files")
        except Exception as e:
            logger.warning(f"Could not clean up temporary env files: {e}")


def main() -> int:
    """Main entry point for MA diagnostics runner."""
    parser = argparse.ArgumentParser(description="MA Crossover Diagnostics Runner")
    parser.add_argument("--skip-data-gen", action="store_true", 
                       help="Skip data generation step (use existing data)")
    parser.add_argument("--skip-backtests", action="store_true",
                       help="Skip backtest execution (analyze existing results)")
    parser.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR,
                       help=f"Output directory for reports (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--catalog-path", type=str, default=CATALOG_PATH,
                       help=f"Catalog path for metadata loading (default: {CATALOG_PATH})")
    parser.add_argument("--verbose", action="store_true",
                       help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.verbose)
    
    logger.info("=" * 60)
    logger.info("MA Crossover Diagnostics Runner")
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info("=" * 60)
    
    try:
        # Step 1: Generate Diagnostic Data
        if not args.skip_data_gen:
            logger.info("Step 1: Generating diagnostic test data...")
            
            # Check if catalog already exists
            catalog_path = Path(CATALOG_PATH)
            if catalog_path.exists() and any(catalog_path.iterdir()):
                logger.info("Diagnostic data already exists, skipping generation")
            else:
                if not generate_diagnostic_data():
                    logger.error("Data generation failed, exiting")
                    return 1
                logger.info("✓ Diagnostic data generation completed")
        else:
            logger.info("Step 1: Skipping data generation (--skip-data-gen)")
        
        # Step 2: Run Diagnostic Backtests
        if not args.skip_backtests:
            logger.info("Step 2: Running diagnostic backtests...")
            
            backtest_results = run_all_diagnostic_backtests(MA_DIAGNOSTIC_SCENARIOS)
            
            if not backtest_results:
                logger.error("No backtests completed successfully, exiting")
                return 1
            
            logger.info(f"✓ Completed {len(backtest_results)}/{len(MA_DIAGNOSTIC_SCENARIOS)} backtests")
        else:
            logger.info("Step 2: Skipping backtests (--skip-backtests)")
            backtest_results = {}
        
        # Step 3: Analyze Results
        logger.info("Step 3: Analyzing diagnostic results...")
        
        # Determine output base directory
        if backtest_results:
            # Use first backtest result directory as base
            first_result = next(iter(backtest_results.values()))
            output_base_dir = first_result.parent
        else:
            # Use backtest logs directory when skipping backtests
            output_base_dir = Path('logs/test_results/phase6_ma_diagnostics')
        
        # Analyze results
        catalog_path = Path(args.catalog_path)
        report = analyze_diagnostic_results(MA_DIAGNOSTIC_SCENARIOS, output_base_dir, backtest_results, catalog_path)
        
        logger.info("✓ Diagnostic analysis completed")
        
        # Step 4: Generate Reports
        logger.info("Step 4: Generating reports...")
        
        # Create output directory
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate timestamp for report filenames
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Console report
        print_console_report(report)
        
        # JSON report
        json_path = output_dir / f"ma_diagnostics_{timestamp}.json"
        export_report_json(report, json_path)
        logger.info(f"✓ JSON report generated: {json_path}")
        
        # HTML report
        html_path = output_dir / f"ma_diagnostics_{timestamp}.html"
        generate_html_report(report, html_path)
        logger.info(f"✓ HTML report generated: {html_path}")
        
        # Markdown report
        markdown_path = output_dir / f"ma_diagnostics_{timestamp}.md"
        generate_markdown_report(report, markdown_path)
        logger.info(f"✓ Markdown report generated: {markdown_path}")
        
        # Step 5: Summary
        logger.info("=" * 60)
        logger.info("DIAGNOSTIC SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Scenarios tested: {report.scenarios_tested}")
        logger.info(f"Scenarios passed: {report.scenarios_passed}")
        logger.info(f"Scenarios failed: {report.scenarios_failed}")
        logger.info(f"Issues detected: {len(report.detected_issues)} categories")
        logger.info(f"Suggestions generated: {len(report.suggestions)}")
        logger.info("")
        logger.info("Report locations:")
        logger.info(f"  HTML: {html_path}")
        logger.info(f"  JSON: {json_path}")
        logger.info(f"  Markdown: {markdown_path}")
        logger.info("")
        
        if report.scenarios_failed > 0:
            logger.warning("Some scenarios failed - review the reports for details")
            return 1
        else:
            logger.info("All scenarios passed successfully!")
            return 0
            
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.exception("Full traceback:")
        return 2


if __name__ == "__main__":
    sys.exit(main())
