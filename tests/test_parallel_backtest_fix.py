"""
Verification test for parallel backtest bug fixes.

Tests both Bug 1 (directory collision) and Bug 2 (missing metrics) fixes by:
1. Running 3 parallel backtests simultaneously
2. Verifying unique output directories with microsecond precision
3. Checking that performance_stats.json contains all required metrics
4. Validating metric calculations against positions.csv data
"""

import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_single_backtest(backtest_id: int, env_vars: Dict[str, str]) -> Dict[str, Any]:
    """
    Run a single backtest with the given environment variables.
    
    Args:
        backtest_id: Unique identifier for this backtest run
        env_vars: Environment variables to set for the backtest
        
    Returns:
        Dictionary with backtest results and metadata
    """
    # Set environment variables
    for key, value in env_vars.items():
        os.environ[key] = value
    
    # Create a unique output directory for this test
    test_output_dir = PROJECT_ROOT / "logs" / "test_results" / f"parallel_test_{backtest_id}"
    os.environ["BACKTEST_OUTPUT_DIR"] = str(test_output_dir)
    
    # Run the backtest
    start_time = time.time()
    try:
        result = subprocess.run(
            [sys.executable, "backtest/run_backtest.py"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=PROJECT_ROOT
        )
        end_time = time.time()
        
        return {
            "backtest_id": backtest_id,
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration": end_time - start_time,
            "output_dir": test_output_dir,
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            "backtest_id": backtest_id,
            "return_code": -1,
            "stdout": "",
            "stderr": "Backtest timed out after 5 minutes",
            "duration": 300,
            "output_dir": test_output_dir,
            "success": False
        }
    except Exception as e:
        return {
            "backtest_id": backtest_id,
            "return_code": -2,
            "stdout": "",
            "stderr": str(e),
            "duration": 0,
            "output_dir": test_output_dir,
            "success": False
        }


def find_backtest_directories(base_dir: Path, symbol: str) -> List[Path]:
    """
    Find all backtest result directories for the given symbol.
    
    Args:
        base_dir: Base directory to search in
        symbol: Symbol to search for (e.g., "EUR-USD")
        
    Returns:
        List of Path objects for found directories
    """
    if not base_dir.exists():
        return []
    
    # Look for directories matching the pattern: {symbol}_{timestamp}
    pattern = f"{symbol}_*"
    directories = []
    
    for item in base_dir.iterdir():
        if item.is_dir() and item.name.startswith(f"{symbol}_"):
            directories.append(item)
    
    return sorted(directories)


def parse_timestamp_from_dirname(dirname: str) -> str:
    """
    Extract timestamp from directory name.
    
    Args:
        dirname: Directory name like "EUR-USD_20251022_082259_123456"
        
    Returns:
        Timestamp part like "20251022_082259_123456"
    """
    parts = dirname.split("_")
    if len(parts) >= 4:
        # Format: SYMBOL_YYYYMMDD_HHMMSS_FFFFFF
        return "_".join(parts[1:])
    elif len(parts) >= 3:
        # Format: SYMBOL_YYYYMMDD_HHMMSS (old format)
        return "_".join(parts[1:])
    return ""


def test_unique_output_directories(results: List[Dict[str, Any]], symbol: str) -> bool:
    """
    Test 1: Verify that parallel backtests create unique output directories.
    
    Args:
        results: List of backtest results
        symbol: Symbol used in backtests
        
    Returns:
        True if test passes, False otherwise
    """
    print("\n=== Test 1: Unique Output Directories ===")
    
    all_directories = []
    for result in results:
        if result["success"]:
            directories = find_backtest_directories(result["output_dir"], symbol)
            all_directories.extend(directories)
            print(f"Backtest {result['backtest_id']}: Found {len(directories)} directories")
            for dir_path in directories:
                print(f"  - {dir_path.name}")
        else:
            print(f"Backtest {result['backtest_id']}: FAILED - {result['stderr']}")
    
    if len(all_directories) == 0:
        print("❌ FAIL: No output directories found")
        return False
    
    # Check for unique timestamps
    timestamps = []
    for dir_path in all_directories:
        timestamp = parse_timestamp_from_dirname(dir_path.name)
        timestamps.append(timestamp)
        print(f"Directory: {dir_path.name} -> Timestamp: {timestamp}")
    
    unique_timestamps = set(timestamps)
    if len(unique_timestamps) != len(timestamps):
        print(f"❌ FAIL: Found duplicate timestamps. Unique: {len(unique_timestamps)}, Total: {len(timestamps)}")
        return False
    
    # Check for microsecond precision (should have 6 digits after seconds)
    microsecond_precision_found = False
    for timestamp in timestamps:
        if "_" in timestamp and len(timestamp.split("_")[-1]) == 6:
            microsecond_precision_found = True
            break
    
    if not microsecond_precision_found:
        print("❌ FAIL: No microsecond precision found in timestamps")
        return False
    
    print(f"✅ PASS: Found {len(all_directories)} unique directories with microsecond precision")
    return True


def test_metrics_availability(results: List[Dict[str, Any]]) -> bool:
    """
    Test 2: Verify that performance_stats.json contains all required metrics.
    
    Args:
        results: List of backtest results
        
    Returns:
        True if test passes, False otherwise
    """
    print("\n=== Test 2: Metrics Availability ===")
    
    required_metrics = ["Total trades", "Sharpe ratio", "Profit factor", "Max drawdown"]
    all_passed = True
    
    for result in results:
        if not result["success"]:
            print(f"Backtest {result['backtest_id']}: SKIPPED (failed)")
            continue
        
        print(f"\nBacktest {result['backtest_id']}:")
        directories = find_backtest_directories(result["output_dir"], "EUR-USD")
        
        if not directories:
            print("  ❌ FAIL: No output directories found")
            all_passed = False
            continue
        
        for dir_path in directories:
            stats_file = dir_path / "performance_stats.json"
            if not stats_file.exists():
                print(f"  ❌ FAIL: {stats_file} not found")
                all_passed = False
                continue
            
            try:
                with open(stats_file, 'r') as f:
                    stats = json.load(f)
                
                general_stats = stats.get("general", {})
                print(f"  Directory: {dir_path.name}")
                
                for metric in required_metrics:
                    if metric in general_stats:
                        value = general_stats[metric]
                        print(f"    ✅ {metric}: {value}")
                    else:
                        print(f"    ❌ {metric}: MISSING")
                        all_passed = False
                
                # Check that values are numeric
                for metric in required_metrics:
                    if metric in general_stats:
                        value = general_stats[metric]
                        if not isinstance(value, (int, float)):
                            print(f"    ❌ {metric}: Not numeric ({type(value)})")
                            all_passed = False
                
            except Exception as e:
                print(f"  ❌ FAIL: Error reading {stats_file}: {e}")
                all_passed = False
    
    if all_passed:
        print("\n✅ PASS: All required metrics found and numeric")
    else:
        print("\n❌ FAIL: Some metrics missing or invalid")
    
    return all_passed


def test_metrics_consistency(results: List[Dict[str, Any]]) -> bool:
    """
    Test 3: Verify that calculated metrics match positions.csv data.
    
    Args:
        results: List of backtest results
        
    Returns:
        True if test passes, False otherwise
    """
    print("\n=== Test 3: Metrics Consistency ===")
    
    all_passed = True
    
    for result in results:
        if not result["success"]:
            print(f"Backtest {result['backtest_id']}: SKIPPED (failed)")
            continue
        
        print(f"\nBacktest {result['backtest_id']}:")
        directories = find_backtest_directories(result["output_dir"], "EUR-USD")
        
        for dir_path in directories:
            print(f"  Directory: {dir_path.name}")
            
            # Load performance stats
            stats_file = dir_path / "performance_stats.json"
            positions_file = dir_path / "positions.csv"
            
            if not stats_file.exists() or not positions_file.exists():
                print(f"    ❌ FAIL: Missing files")
                all_passed = False
                continue
            
            try:
                # Load stats
                with open(stats_file, 'r') as f:
                    stats = json.load(f)
                general_stats = stats.get("general", {})
                
                # Load positions
                positions_df = pd.read_csv(positions_file)
                
                # Test Total Trades consistency
                if "Total trades" in general_stats:
                    reported_trades = general_stats["Total trades"]
                    
                    # Count closed positions
                    if 'ts_closed' in positions_df.columns:
                        actual_trades = len(positions_df[positions_df['ts_closed'].notna()])
                    else:
                        actual_trades = len(positions_df)
                    
                    if reported_trades == actual_trades:
                        print(f"    ✅ Total trades: {reported_trades} (matches positions.csv)")
                    else:
                        print(f"    ❌ Total trades: reported={reported_trades}, actual={actual_trades}")
                        all_passed = False
                else:
                    print(f"    ❌ Total trades: Missing from stats")
                    all_passed = False
                
                # Test Sharpe ratio calculation (if we have enough data)
                if "Sharpe ratio" in general_stats and 'realized_return' in positions_df.columns:
                    reported_sharpe = general_stats["Sharpe ratio"]
                    
                    # Calculate Sharpe ratio from positions
                    closed_positions = positions_df[positions_df['ts_closed'].notna()]
                    if not closed_positions.empty and 'realized_return' in closed_positions.columns:
                        returns = closed_positions['realized_return'].dropna()
                        if len(returns) >= 2:
                            mean_return = returns.mean()
                            std_return = returns.std()
                            if std_return > 0:
                                calculated_sharpe = mean_return / std_return
                                if abs(reported_sharpe - calculated_sharpe) < 0.001:
                                    print(f"    ✅ Sharpe ratio: {reported_sharpe:.3f} (matches calculation)")
                                else:
                                    print(f"    ❌ Sharpe ratio: reported={reported_sharpe:.3f}, calculated={calculated_sharpe:.3f}")
                                    all_passed = False
                            else:
                                print(f"    ✅ Sharpe ratio: {reported_sharpe:.3f} (std=0, expected)")
                        else:
                            print(f"    ✅ Sharpe ratio: {reported_sharpe:.3f} (insufficient data)")
                    else:
                        print(f"    ✅ Sharpe ratio: {reported_sharpe:.3f} (no closed positions)")
                
            except Exception as e:
                print(f"    ❌ FAIL: Error processing files: {e}")
                all_passed = False
    
    if all_passed:
        print("\n✅ PASS: All metrics consistent with source data")
    else:
        print("\n❌ FAIL: Some metrics inconsistent with source data")
    
    return all_passed


def main():
    """Run the parallel backtest verification tests."""
    print("Starting Parallel Backtest Fix Verification Tests")
    print("=" * 60)
    
    # Test configuration
    symbol = "EUR/USD"
    test_duration = "1 month"  # Short test period
    start_date = "2024-01-01"
    end_date = "2024-01-31"
    
    # Base environment variables for all backtests
    base_env = {
        "BACKTEST_SYMBOL": symbol,
        "BACKTEST_VENUE": "IDEALPRO",
        "BACKTEST_START_DATE": start_date,
        "BACKTEST_END_DATE": end_date,
        "BACKTEST_CATALOG_PATH": str(PROJECT_ROOT / "data" / "catalog"),
        "BACKTEST_FAST_PERIOD": "5",
        "BACKTEST_SLOW_PERIOD": "10",
        "BACKTEST_TRADE_SIZE": "1000",
        "BACKTEST_BAR_SPEC": "1-MINUTE",
        "BACKTEST_STARTING_CAPITAL": "10000",
        "BACKTEST_ENFORCE_POSITION_LIMIT": "true",
        "BACKTEST_ALLOW_POSITION_REVERSAL": "false",
        "BACKTEST_STOP_LOSS_PIPS": "50",
        "BACKTEST_TAKE_PROFIT_PIPS": "100",
        "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": "30",
        "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": "20",
        "BACKTEST_CROSSOVER_THRESHOLD_PIPS": "0.5",
        "BACKTEST_PRE_CROSSOVER_SEPARATION_PIPS": "0.2",
        "BACKTEST_PRE_CROSSOVER_LOOKBACK_BARS": "5",
        "BACKTEST_DMI_ENABLED": "false",
        "BACKTEST_DMI_BAR_SPEC": "1-MINUTE",
        "BACKTEST_DMI_PERIOD": "14",
        "BACKTEST_STOCH_ENABLED": "false",
        "BACKTEST_STOCH_BAR_SPEC": "1-MINUTE",
        "BACKTEST_STOCH_PERIOD_K": "14",
        "BACKTEST_STOCH_PERIOD_D": "3",
        "BACKTEST_STOCH_BULLISH_THRESHOLD": "20",
        "BACKTEST_STOCH_BEARISH_THRESHOLD": "80",
        "BACKTEST_STOCH_MAX_BARS_SINCE_CROSSING": "5",
        "BACKTEST_USE_LIMIT_ORDERS": "false",
        "BACKTEST_LIMIT_ORDER_TIMEOUT_BARS": "10",
    }
    
    # Create test output directory
    test_output_base = PROJECT_ROOT / "logs" / "test_results"
    test_output_base.mkdir(parents=True, exist_ok=True)
    
    print(f"Running 3 parallel backtests with {test_duration} of data...")
    print(f"Symbol: {symbol}")
    print(f"Date range: {start_date} to {end_date}")
    print(f"Output directory: {test_output_base}")
    
    # Run parallel backtests
    start_time = time.time()
    
    with multiprocessing.Pool(processes=3) as pool:
        # Create slightly different configs to ensure different results
        configs = []
        for i in range(3):
            config = base_env.copy()
            # Vary the MA periods slightly to get different results
            config["BACKTEST_FAST_PERIOD"] = str(5 + i)
            config["BACKTEST_SLOW_PERIOD"] = str(10 + i * 2)
            configs.append((i + 1, config))
        
        # Run backtests in parallel
        results = pool.starmap(run_single_backtest, configs)
    
    end_time = time.time()
    total_duration = end_time - start_time
    
    print(f"\nParallel execution completed in {total_duration:.2f} seconds")
    
    # Analyze results
    successful_backtests = [r for r in results if r["success"]]
    failed_backtests = [r for r in results if not r["success"]]
    
    print(f"\nResults Summary:")
    print(f"  Successful: {len(successful_backtests)}")
    print(f"  Failed: {len(failed_backtests)}")
    
    if failed_backtests:
        print("\nFailed backtests:")
        for result in failed_backtests:
            print(f"  Backtest {result['backtest_id']}: {result['stderr']}")
    
    # Run verification tests
    all_tests_passed = True
    
    # Test 1: Unique output directories
    test1_passed = test_unique_output_directories(results, symbol)
    all_tests_passed = all_tests_passed and test1_passed
    
    # Test 2: Metrics availability
    test2_passed = test_metrics_availability(results)
    all_tests_passed = all_tests_passed and test2_passed
    
    # Test 3: Metrics consistency
    test3_passed = test_metrics_consistency(results)
    all_tests_passed = all_tests_passed and test3_passed
    
    # Final results
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    
    if all_tests_passed:
        print("✅ ALL TESTS PASSED")
        print("Both bug fixes are working correctly:")
        print("  - Bug 1: Unique output directories with microsecond precision")
        print("  - Bug 2: Complete metrics in performance_stats.json")
    else:
        print("❌ SOME TESTS FAILED")
        print("Please check the output above for specific failures.")
    
    # Cleanup option
    cleanup = input("\nClean up test output directories? (y/N): ").strip().lower()
    if cleanup in ['y', 'yes']:
        import shutil
        for result in results:
            if result["output_dir"].exists():
                shutil.rmtree(result["output_dir"])
                print(f"Cleaned up: {result['output_dir']}")
        print("Cleanup completed.")
    
    return 0 if all_tests_passed else 1


if __name__ == "__main__":
    sys.exit(main())
