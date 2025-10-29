#!/usr/bin/env python3
"""
Master orchestration script for comprehensive filter testing workflow.

This script executes three sequential phases:
1. Synthetic data generation - Creates test data for all 8 strategy filters
2. Backtest execution - Runs backtests for all filter test scenarios  
3. Results analysis - Validates results and generates comprehensive reports

Usage Examples:
    # Run complete pipeline
    python run_comprehensive_filter_tests.py
    
    # Run specific filter only
    python run_comprehensive_filter_tests.py --filter dmi
    
    # Run single phase
    python run_comprehensive_filter_tests.py --phase data_generation
    
    # Skip data generation (use existing data)
    python run_comprehensive_filter_tests.py --skip-data-gen
    
    # Verbose mode with custom timeout
    python run_comprehensive_filter_tests.py --verbose --phase-timeout 3600
    
    # List available phases
    python run_comprehensive_filter_tests.py --list-phases
"""

import os
import sys
import subprocess
import argparse
import logging
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# Project configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Phase script mappings
PHASE_SCRIPTS = {
    "data_generation": PROJECT_ROOT / "tests" / "generate_all_filter_test_data.py",
    "backtest_execution": PROJECT_ROOT / "tests" / "run_all_filter_backtests.py",
    "results_analysis": PROJECT_ROOT / "tests" / "analyze_filter_test_results.py"
}

# Phase descriptions
PHASE_DESCRIPTIONS = {
    "data_generation": "Generate synthetic test data for all 8 strategy filters",
    "backtest_execution": "Execute backtests for all filter test scenarios",
    "results_analysis": "Analyze and validate backtest results"
}

# Phase execution order
PHASE_ORDER = ["data_generation", "backtest_execution", "results_analysis"]

# Default configuration
DEFAULT_TIMEOUT = 1800  # 30 minutes per phase
CATALOG_PATH = PROJECT_ROOT / "data" / "test_catalog" / "comprehensive_filter_tests"
RESULTS_PATH = PROJECT_ROOT / "logs" / "test_results" / "comprehensive_filter_tests"
REPORTS_PATH = PROJECT_ROOT / "reports"


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Setup logging configuration following test_runner.py pattern."""
    logger = logging.getLogger(__name__)
    
    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Set log level
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(console_handler)
    
    return logger


def run_phase(phase_name: str, args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
    """Execute a single phase via subprocess following test_runner.py pattern."""
    # Validate phase name
    if phase_name not in PHASE_SCRIPTS:
        logger.error(f"❌ Unknown phase: {phase_name}")
        return {
            "success": False,
            "phase": phase_name,
            "description": "Unknown phase",
            "duration_seconds": 0.0,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Unknown phase: {phase_name}",
            "error": f"Unknown phase: {phase_name}"
        }
    
    # Get script path and verify existence
    script_path = PHASE_SCRIPTS[phase_name]
    if not script_path.exists():
        logger.error(f"❌ Required script not found: {script_path}")
        return {
            "success": False,
            "phase": phase_name,
            "description": PHASE_DESCRIPTIONS[phase_name],
            "duration_seconds": 0.0,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Script not found: {script_path}",
            "error": f"Script not found: {script_path}"
        }
    
    # Log phase start
    logger.info(f"🚀 Running {phase_name}: {PHASE_DESCRIPTIONS[phase_name]}")
    
    # Build command arguments
    cmd_args = [sys.executable, str(script_path)]
    
    # Add phase-specific arguments
    if phase_name == "data_generation":
        if args.filter:
            cmd_args.extend(["--filter", args.filter])
        if args.verbose:
            cmd_args.append("--verbose")
        if args.output_dir:
            cmd_args.extend(["--output-dir", args.output_dir])
    
    elif phase_name == "backtest_execution":
        if args.filter:
            cmd_args.extend(["--filter", args.filter])
        if args.scenario:
            cmd_args.extend(["--scenario", args.scenario])
        if args.verbose:
            cmd_args.append("--verbose")
        if args.timeout:
            cmd_args.extend(["--timeout", str(args.timeout)])
        if args.continue_on_error:
            cmd_args.append("--continue-on-error")
        if args.output_dir:
            cmd_args.extend(["--catalog-dir", args.output_dir])
    
    elif phase_name == "results_analysis":
        if args.output_dir:
            cmd_args.extend(["--catalog-dir", args.output_dir])
        else:
            cmd_args.extend(["--catalog-dir", str(CATALOG_PATH)])
        cmd_args.extend(["--results-dir", str(RESULTS_PATH)])
        if args.filter:
            cmd_args.extend(["--filter", args.filter])
        if args.scenario:
            cmd_args.extend(["--scenario", args.scenario])
        if args.verbose:
            cmd_args.append("--verbose")
        cmd_args.extend(["--output-html", str(REPORTS_PATH / "comprehensive_filter_test_report.html")])
        cmd_args.extend(["--output-json", str(REPORTS_PATH / "comprehensive_filter_test_report.json")])
    
    # Log command execution
    logger.debug(f"Executing: {' '.join(cmd_args)}")
    
    # Record start time
    start_time = time.time()
    
    try:
        # Execute subprocess
        result = subprocess.run(
            cmd_args,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=args.phase_timeout
        )
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Check return code and log result
        if result.returncode == 0:
            logger.info(f"✅ {phase_name} completed successfully in {duration:.1f}s")
        else:
            logger.error(f"❌ {phase_name} failed with return code {result.returncode} in {duration:.1f}s")
        
        # Return result dictionary
        return {
            "success": result.returncode == 0,
            "phase": phase_name,
            "description": PHASE_DESCRIPTIONS[phase_name],
            "duration_seconds": duration,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
        
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        logger.error(f"⏰ {phase_name} timed out after {duration:.1f}s")
        return {
            "success": False,
            "phase": phase_name,
            "description": PHASE_DESCRIPTIONS[phase_name],
            "duration_seconds": duration,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Phase timed out after {args.phase_timeout} seconds",
            "error": "Phase timed out"
        }
        
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"❌ {phase_name} failed with exception: {e}")
        return {
            "success": False,
            "phase": phase_name,
            "description": PHASE_DESCRIPTIONS[phase_name],
            "duration_seconds": duration,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "error": str(e)
        }


def run_full_pipeline(args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
    """Execute the complete pipeline following test_runner.py pattern."""
    # Initialize results
    results = {
        "phases_run": 0,
        "phases_passed": 0,
        "phases_failed": 0,
        "phase_results": [],
        "overall_success": True,
        "start_time": datetime.now().isoformat(),
        "end_time": None,
        "total_duration_seconds": 0.0
    }
    
    # Print header banner
    start_time = results["start_time"]
    print("\n" + "=" * 60)
    print("COMPREHENSIVE FILTER TESTING WORKFLOW")
    print("=" * 60)
    print(f"Started at: {start_time}")
    print(f"Filter: {args.filter or 'ALL'}")
    print(f"Scenario: {args.scenario or 'ALL'}")
    print("=" * 60)
    
    # Determine which phases to run
    phases_to_run = PHASE_ORDER.copy()
    
    # Adjust phases based on skip flags with prerequisite validation
    if args.skip_data_gen and "data_generation" in phases_to_run:
        phases_to_run.remove("data_generation")
        logger.info("⚠️ Skipping data generation phase (--skip-data-gen)")
        
        # Validate prerequisites for skipping data generation
        catalog_path = Path(args.output_dir) if args.output_dir else CATALOG_PATH
        if not catalog_path.exists():
            logger.error(f"❌ Catalog directory does not exist: {catalog_path}")
            logger.error("Cannot skip data generation without existing catalog data")
            return {
                "phases_run": 0,
                "phases_passed": 0,
                "phases_failed": 1,
                "phase_results": [],
                "overall_success": False,
                "start_time": results["start_time"],
                "end_time": datetime.now().isoformat(),
                "total_duration_seconds": 0.0
            }
        elif not any(catalog_path.iterdir()):
            logger.error(f"❌ Catalog directory is empty: {catalog_path}")
            logger.error("Cannot skip data generation without existing catalog data")
            return {
                "phases_run": 0,
                "phases_passed": 0,
                "phases_failed": 1,
                "phase_results": [],
                "overall_success": False,
                "start_time": results["start_time"],
                "end_time": datetime.now().isoformat(),
                "total_duration_seconds": 0.0
            }
        else:
            logger.info(f"✅ Catalog directory exists and is non-empty: {catalog_path}")
    
    if args.skip_backtests and "backtest_execution" in phases_to_run:
        phases_to_run.remove("backtest_execution")
        logger.info("⚠️ Skipping backtest execution phase (--skip-backtests)")
        
        # Validate prerequisites for skipping backtests
        if not RESULTS_PATH.exists():
            logger.error(f"❌ Results directory does not exist: {RESULTS_PATH}")
            logger.error("Cannot skip backtests without existing results")
            return {
                "phases_run": 0,
                "phases_passed": 0,
                "phases_failed": 1,
                "phase_results": [],
                "overall_success": False,
                "start_time": results["start_time"],
                "end_time": datetime.now().isoformat(),
                "total_duration_seconds": 0.0
            }
        elif not any(RESULTS_PATH.iterdir()):
            logger.error(f"❌ Results directory is empty: {RESULTS_PATH}")
            logger.error("Cannot skip backtests without existing results")
            return {
                "phases_run": 0,
                "phases_passed": 0,
                "phases_failed": 1,
                "phase_results": [],
                "overall_success": False,
                "start_time": results["start_time"],
                "end_time": datetime.now().isoformat(),
                "total_duration_seconds": 0.0
            }
        else:
            logger.info(f"✅ Results directory exists and is non-empty: {RESULTS_PATH}")
    
    if args.skip_analysis and "results_analysis" in phases_to_run:
        phases_to_run.remove("results_analysis")
        logger.info("⚠️ Skipping results analysis phase (--skip-analysis)")
    
    if not phases_to_run:
        logger.warning("⚠️ All phases skipped. Nothing to do.")
        results["end_time"] = datetime.now().isoformat()
        return results
    
    # Pre-flight timeout estimation for backtest phase
    if "backtest_execution" in phases_to_run:
        # Estimate total backtest duration based on discovered scenarios
        catalog_path = Path(args.output_dir) if args.output_dir else CATALOG_PATH
        if catalog_path.exists():
            # Count scenarios by discovering them (similar to backtest script)
            from tests.run_all_filter_backtests import discover_test_scenarios
            try:
                all_scenarios = discover_test_scenarios(catalog_path)
                total_scenarios = sum(len(scenarios) for scenarios in all_scenarios.values())
                per_scenario_timeout = args.timeout if args.timeout else 300  # Default 5 minutes per scenario
                estimated_total = total_scenarios * per_scenario_timeout
                
                if estimated_total > args.phase_timeout:
                    logger.warning(f"⚠️ Estimated backtest duration ({estimated_total}s) exceeds phase timeout ({args.phase_timeout}s)")
                    logger.warning(f"   Total scenarios: {total_scenarios}, Per-scenario timeout: {per_scenario_timeout}s")
                    logger.warning(f"   Consider increasing --phase-timeout to {estimated_total + 300} or more")
                else:
                    logger.info(f"✅ Estimated backtest duration: {estimated_total}s (within {args.phase_timeout}s timeout)")
            except Exception as e:
                logger.debug(f"Could not estimate backtest duration: {e}")
    
    # Execute phases
    for i, phase_name in enumerate(phases_to_run, 1):
        logger.info(f"\n--- PHASE {i}/{len(phases_to_run)}: {phase_name.upper()} ---")
        
        # Run phase
        phase_result = run_phase(phase_name, args, logger)
        results["phase_results"].append(phase_result)
        results["phases_run"] += 1
        
        # Track success/failure
        if phase_result["success"]:
            results["phases_passed"] += 1
        else:
            results["phases_failed"] += 1
            results["overall_success"] = False
            
            # Check if phase is critical
            critical_phases = ["data_generation", "backtest_execution"]
            if phase_name in critical_phases and not args.continue_on_error:
                logger.error("🛑 Critical phase failed. Stopping pipeline execution.")
                break
            elif phase_name == "data_generation":
                if not args.continue_on_error:
                    logger.warning("⚠️ Data generation failed. Skipping remaining phases.")
                    break
                else:
                    logger.warning("⚠️ Data generation failed. Continuing with remaining phases (--continue-on-error)")
            elif phase_name == "backtest_execution":
                logger.warning("⚠️ Backtest execution failed. Analysis may be incomplete.")
    
    # Calculate final results
    results["end_time"] = datetime.now().isoformat()
    results["total_duration_seconds"] = sum(phase["duration_seconds"] for phase in results["phase_results"])
    
    return results


def print_summary_report(results: Dict[str, Any], logger: logging.Logger) -> None:
    """Print comprehensive summary report following test_runner.py pattern."""
    print("\n" + "=" * 60)
    print("COMPREHENSIVE FILTER TESTING SUMMARY")
    print("=" * 60)
    
    # Overall statistics
    phases_run = results["phases_run"]
    phases_passed = results["phases_passed"]
    phases_failed = results["phases_failed"]
    overall_success = results["overall_success"]
    total_duration = results["total_duration_seconds"]
    start_time = results["start_time"]
    end_time = results["end_time"]
    
    print(f"Phases run: {phases_run}")
    print(f"Phases passed: {phases_passed} ✅")
    print(f"Phases failed: {phases_failed} ❌")
    print(f"Overall success: {'✅ YES' if overall_success else '❌ NO'}")
    print(f"Total duration: {total_duration:.1f}s ({total_duration/60:.1f} minutes)")
    print(f"Started at: {start_time}")
    print(f"Completed at: {end_time}")
    
    # Detailed phase results
    print("\nPHASE RESULTS:")
    print("-" * 60)
    for phase_result in results["phase_results"]:
        phase = phase_result["phase"]
        success = phase_result["success"]
        duration = phase_result["duration_seconds"]
        status = "✅ PASS" if success else "❌ FAIL"
        
        print(f"{phase.upper()}: {status} ({duration:.1f}s)")
        
        if not success and "error" in phase_result:
            print(f"  Error: {phase_result['error']}")
        
        if logger.level == logging.DEBUG and phase_result.get("stdout"):
            stdout_preview = phase_result["stdout"][:500]
            if len(phase_result["stdout"]) > 500:
                stdout_preview += "..."
            print(f"  Output: {stdout_preview}")
    
    # Output locations
    print("\nOUTPUT LOCATIONS:")
    print("-" * 60)
    print(f"Test Data: {CATALOG_PATH}")
    print(f"Backtest Results: {RESULTS_PATH}")
    print(f"Analysis Reports: {REPORTS_PATH}")
    
    # Final status
    if overall_success:
        print("\n🎉 All phases completed successfully!")
        print(f"📊 View the comprehensive report at: {REPORTS_PATH}/comprehensive_filter_test_report.html")
    else:
        print("\n💥 Some phases failed. Review the logs above for details.")
        print("🔍 Check individual phase outputs for more information.")


def list_available_phases(logger: logging.Logger) -> None:
    """List available phases and their descriptions."""
    print("Available phases:")
    print("=" * 60)
    
    for i, phase in enumerate(PHASE_ORDER, 1):
        print(f"{i}. {phase}")
        print(f"   Description: {PHASE_DESCRIPTIONS[phase]}")
        print(f"   Script: {PHASE_SCRIPTS[phase].relative_to(PROJECT_ROOT)}")
        print()
    
    print("Run 'all' to execute the complete pipeline")


def validate_prerequisites(logger: logging.Logger) -> bool:
    """Validate that all required scripts and directories exist."""
    # Check that all phase scripts exist
    for phase_name, script_path in PHASE_SCRIPTS.items():
        if not script_path.exists():
            logger.error(f"❌ Required script not found: {script_path}")
            return False
    
    # Check that project root is valid
    if not PROJECT_ROOT.exists():
        logger.error(f"❌ Project root not found: {PROJECT_ROOT}")
        return False
    
    # Create necessary directories
    try:
        CATALOG_PATH.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.mkdir(parents=True, exist_ok=True)
        REPORTS_PATH.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"❌ Failed to create required directories: {e}")
        return False
    
    logger.info("✅ All prerequisites validated")
    return True


def main() -> int:
    """Main function with argument parsing and workflow execution."""
    parser = argparse.ArgumentParser(
        description="Master orchestration script for comprehensive filter testing workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Phase Selection Group
    phase_group = parser.add_argument_group("Phase Selection")
    phase_group.add_argument(
        "--phase",
        choices=["all", "data_generation", "backtest_execution", "results_analysis"],
        default="all",
        help="Phase to run (default: all)"
    )
    phase_group.add_argument(
        "--list-phases",
        action="store_true",
        help="List available phases and exit"
    )
    
    # Filter Selection Group
    filter_group = parser.add_argument_group("Filter Selection")
    filter_group.add_argument(
        "--filter",
        choices=["crossover_threshold", "pre_separation", "dmi", "stochastic", 
                "time_filter", "atr", "adx", "circuit_breaker"],
        help="Run tests for specific filter only"
    )
    filter_group.add_argument(
        "--scenario",
        help="Run tests for specific scenario only"
    )
    
    # Execution Control Group
    exec_group = parser.add_argument_group("Execution Control")
    exec_group.add_argument(
        "--skip-data-gen",
        action="store_true",
        help="Skip data generation phase (use existing data)"
    )
    exec_group.add_argument(
        "--skip-backtests",
        action="store_true",
        help="Skip backtest execution phase (use existing results)"
    )
    exec_group.add_argument(
        "--skip-analysis",
        action="store_true",
        help="Skip results analysis phase"
    )
    exec_group.add_argument(
        "--continue-on-error",
        action="store_true",
        default=False,
        help="Continue pipeline execution even if a phase fails"
    )
    exec_group.add_argument(
        "--phase-timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout for each phase in seconds (default: {DEFAULT_TIMEOUT})"
    )
    exec_group.add_argument(
        "--timeout",
        type=int,
        help="Timeout for individual backtests in seconds (passed to backtest phase)"
    )
    
    # Output Control Group
    output_group = parser.add_argument_group("Output Control")
    output_group.add_argument(
        "--output-dir",
        help="Custom output directory for test data (overrides default)"
    )
    output_group.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (DEBUG level)"
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.verbose)
    
    try:
        # Handle --list-phases
        if args.list_phases:
            list_available_phases(logger)
            return 0
        
        # Log script start
        logger.info("🚀 Comprehensive Filter Testing Workflow")
        logger.info(f"Phase: {args.phase}")
        logger.info(f"Filter: {args.filter or 'ALL'}")
        logger.info(f"Scenario: {args.scenario or 'ALL'}")
        
        # Validate prerequisites
        if not validate_prerequisites(logger):
            return 2
        
        # Execute workflow
        if args.phase == "all":
            results = run_full_pipeline(args, logger)
        else:
            # Single phase execution
            results = {
                "phases_run": 0,
                "phases_passed": 0,
                "phases_failed": 0,
                "phase_results": [],
                "overall_success": True,
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "total_duration_seconds": 0.0
            }
            
            phase_result = run_phase(args.phase, args, logger)
            results["phase_results"].append(phase_result)
            results["phases_run"] = 1
            results["phases_passed"] = 1 if phase_result["success"] else 0
            results["phases_failed"] = 0 if phase_result["success"] else 1
            results["overall_success"] = phase_result["success"]
            results["total_duration_seconds"] = phase_result["duration_seconds"]
            results["end_time"] = datetime.now().isoformat()
        
        # Print summary report
        print_summary_report(results, logger)
        
        # Return appropriate exit code
        if results["overall_success"]:
            return 0
        else:
            return 1
            
    except KeyboardInterrupt:
        logger.warning("⚠️ Workflow interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return 2


if __name__ == "__main__":
    sys.exit(main())
