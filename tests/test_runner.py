"""
Test Runner for MA Crossover Strategy

Comprehensive test runner that executes all phases of testing for the MA crossover strategy.
This includes data generation, backtest execution, and diagnostic analysis.

Phases:
1. Phase 1: Core Strategy Testing
2. Phase 2: Filter Testing  
3. Phase 3: Crossover Filter Testing
4. Phase 4: Integration Testing
5. Phase 5: Performance Testing
6. Phase 6: MA Diagnostics Testing

Usage:
    python tests/test_runner.py [--phase PHASE] [--skip-data-gen] [--skip-backtests] [--verbose]
"""

import os
import sys
import subprocess
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add project root to sys.path for module imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Test phase configurations
TEST_PHASES = {
    "phase1": {
        "name": "Core Strategy Testing",
        "script": "tests/test_basic_crossovers.py",
        "description": "Basic MA crossover detection and trade execution"
    },
    "phase2": {
        "name": "Filter Testing",
        "script": "tests/generate_phase2_data.py",
        "description": "Individual filter behavior testing"
    },
    "phase3": {
        "name": "Crossover Filter Testing", 
        "script": "tests/generate_phase3_crossover_data.py",
        "description": "Crossover-specific filter testing"
    },
    "phase4": {
        "name": "Integration Testing",
        "script": "tests/test_backtest_runner_integration.py",
        "description": "End-to-end integration testing"
    },
    "phase5": {
        "name": "Performance Testing",
        "script": "tests/test_loss_patterns.py",
        "description": "Performance and loss pattern analysis"
    },
    "phase6": {
        "name": "MA Diagnostics Testing",
        "script": "tests/run_ma_diagnostics.py",
        "description": "Comprehensive MA crossover algorithm diagnostics"
    }
}


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


def run_phase(phase_key: str, skip_data_gen: bool = False, skip_backtests: bool = False, verbose: bool = False) -> Dict[str, Any]:
    """
    Run a specific test phase.
    
    Args:
        phase_key: Phase key (e.g., "phase1", "phase6")
        skip_data_gen: Whether to skip data generation
        skip_backtests: Whether to skip backtest execution
        verbose: Whether to enable verbose logging
        
    Returns:
        Dictionary with phase execution results
    """
    logger = logging.getLogger(__name__)
    
    if phase_key not in TEST_PHASES:
        logger.error(f"Unknown phase: {phase_key}")
        return {"success": False, "error": f"Unknown phase: {phase_key}"}
    
    phase_config = TEST_PHASES[phase_key]
    script_path = PROJECT_ROOT / phase_config["script"]
    
    if not script_path.exists():
        logger.error(f"Script not found: {script_path}")
        return {"success": False, "error": f"Script not found: {script_path}"}
    
    logger.info(f"Running {phase_config['name']}...")
    logger.info(f"Description: {phase_config['description']}")
    
    try:
        # Build command arguments
        cmd_args = [sys.executable, str(script_path)]
        
        # Add phase-specific arguments
        if phase_key == "phase6":
            # Phase 6 MA diagnostics supports skip flags
            if skip_data_gen:
                cmd_args.append("--skip-data-gen")
            if skip_backtests:
                cmd_args.append("--skip-backtests")
            if verbose:
                cmd_args.append("--verbose")
        
        # Run the phase
        logger.info(f"Executing: {' '.join(cmd_args)}")
        
        result = subprocess.run(
            cmd_args,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        
        if result.returncode == 0:
            logger.info(f"✅ {phase_config['name']} completed successfully")
            return {
                "success": True,
                "phase": phase_key,
                "name": phase_config["name"],
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        else:
            logger.error(f"❌ {phase_config['name']} failed with return code {result.returncode}")
            logger.error(f"STDERR: {result.stderr}")
            return {
                "success": False,
                "phase": phase_key,
                "name": phase_config["name"],
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "error": f"Phase failed with return code {result.returncode}"
            }
            
    except subprocess.TimeoutExpired:
        logger.error(f"❌ {phase_config['name']} timed out after 10 minutes")
        return {
            "success": False,
            "phase": phase_key,
            "name": phase_config["name"],
            "error": "Phase timed out after 10 minutes"
        }
    except Exception as e:
        logger.error(f"❌ {phase_config['name']} failed with exception: {e}")
        return {
            "success": False,
            "phase": phase_key,
            "name": phase_config["name"],
            "error": str(e)
        }


def run_all_phases(skip_data_gen: bool = False, skip_backtests: bool = False, verbose: bool = False) -> Dict[str, Any]:
    """
    Run all test phases in sequence.
    
    Args:
        skip_data_gen: Whether to skip data generation
        skip_backtests: Whether to skip backtest execution
        verbose: Whether to enable verbose logging
        
    Returns:
        Dictionary with overall test results
    """
    logger = logging.getLogger(__name__)
    
    results = {
        "phases_run": 0,
        "phases_passed": 0,
        "phases_failed": 0,
        "phase_results": [],
        "overall_success": True,
        "start_time": datetime.now().isoformat(),
        "end_time": None
    }
    
    logger.info("=" * 80)
    logger.info("MA CROSSOVER STRATEGY - COMPREHENSIVE TEST RUNNER")
    logger.info("=" * 80)
    logger.info(f"Started at: {results['start_time']}")
    logger.info("")
    
    # Run each phase
    for phase_key in TEST_PHASES.keys():
        logger.info(f"Running {phase_key.upper()}...")
        
        phase_result = run_phase(phase_key, skip_data_gen, skip_backtests, verbose)
        results["phase_results"].append(phase_result)
        results["phases_run"] += 1
        
        if phase_result["success"]:
            results["phases_passed"] += 1
        else:
            results["phases_failed"] += 1
            results["overall_success"] = False
        
        logger.info("")
    
    results["end_time"] = datetime.now().isoformat()
    
    # Summary
    logger.info("=" * 80)
    logger.info("TEST RUNNER SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Phases run: {results['phases_run']}")
    logger.info(f"Phases passed: {results['phases_passed']}")
    logger.info(f"Phases failed: {results['phases_failed']}")
    logger.info(f"Overall success: {'✅ YES' if results['overall_success'] else '❌ NO'}")
    logger.info(f"Completed at: {results['end_time']}")
    logger.info("")
    
    # Detailed results
    logger.info("DETAILED RESULTS:")
    logger.info("-" * 40)
    for phase_result in results["phase_results"]:
        status = "✅ PASS" if phase_result["success"] else "❌ FAIL"
        logger.info(f"{phase_result['phase'].upper()}: {status}")
        if not phase_result["success"] and "error" in phase_result:
            logger.info(f"  Error: {phase_result['error']}")
    
    return results


def main() -> int:
    """Main entry point for test runner."""
    parser = argparse.ArgumentParser(description="MA Crossover Strategy Test Runner")
    parser.add_argument("--phase", type=str, choices=list(TEST_PHASES.keys()) + ["all"],
                       default="all", help="Phase to run (default: all)")
    parser.add_argument("--skip-data-gen", action="store_true",
                       help="Skip data generation steps")
    parser.add_argument("--skip-backtests", action="store_true",
                       help="Skip backtest execution steps")
    parser.add_argument("--verbose", action="store_true",
                       help="Enable verbose logging")
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.verbose)
    
    try:
        if args.phase == "all":
            # Run all phases
            results = run_all_phases(args.skip_data_gen, args.skip_backtests, args.verbose)
            return 0 if results["overall_success"] else 1
        else:
            # Run specific phase
            result = run_phase(args.phase, args.skip_data_gen, args.skip_backtests, args.verbose)
            return 0 if result["success"] else 1
            
    except KeyboardInterrupt:
        logger.info("Test runner interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.exception("Full traceback:")
        return 2


if __name__ == "__main__":
    sys.exit(main())
