"""
Phase 2 Basic Crossover Tests

Pytest-based test suite to execute Phase 2 basic crossover tests and verify expected trade counts.

This test suite validates the fundamental MA crossover detection logic without any filters enabled.
It establishes a baseline to verify the strategy correctly identifies crossovers before testing 
individual filters in subsequent phases.

Prerequisites: Run `python tests/generate_phase2_data.py` first
Usage: pytest tests/test_basic_crossovers.py -v
Expected outcomes for each scenario:
- Simple Bullish: 1 BUY trade
- Simple Bearish: 1 SELL trade  
- Multiple Crossovers: 5 trades (alternating BUY/SELL)
- No Crossover: 0 trades

Note: Tests run sequentially, each takes ~10-30 seconds
"""

import pytest
import subprocess
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Any

# Configuration Constants
PROJECT_ROOT = Path(__file__).parent.parent
BACKTEST_SCRIPT = PROJECT_ROOT / "backtest" / "run_backtest.py"
ENV_CONFIGS_DIR = PROJECT_ROOT / "tests" / "env_configs"
TEST_RESULTS_DIR = PROJECT_ROOT / "logs" / "test_results" / "phase2_basic"

# Test Scenarios Configuration
TEST_SCENARIOS = [
    {
        "name": "simple_bullish",
        "env_file": "env.test_simple_bullish",
        "expected_trades": 1,
        "expected_direction": "BUY",
        "description": "Single bullish MA crossover"
    },
    {
        "name": "simple_bearish",
        "env_file": "env.test_simple_bearish",
        "expected_trades": 1,
        "expected_direction": "SELL",
        "description": "Single bearish MA crossover"
    },
    {
        "name": "multiple_crossovers",
        "env_file": "env.test_multiple_crossovers",
        "expected_trades": 5,
        "expected_direction": None,  # Mixed BUY/SELL
        "description": "Five alternating crossovers"
    },
    {
        "name": "no_crossover",
        "env_file": "env.test_no_crossover",
        "expected_trades": 0,
        "expected_direction": None,
        "description": "Parallel MAs with no crossover"
    },
]


def load_env_file(env_file_path: Path) -> Dict[str, str]:
    """Load environment variables from .env file."""
    env_vars = {}
    try:
        with open(env_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    except Exception as e:
        raise RuntimeError(f"Failed to load env file {env_file_path}: {e}")
    return env_vars


def run_backtest_with_env(env_file: Path) -> Dict[str, Any]:
    """Run backtest with environment variables from env_file."""
    try:
        # Load environment variables
        env_vars = load_env_file(env_file)
        
        # Create environment for subprocess
        env = os.environ.copy()
        env.update(env_vars)
        
        # Execute backtest
        result = subprocess.run(
            ["python", str(BACKTEST_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT)
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "trade_count": 0,
                "output_dir": None,
                "stats": {},
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        
        # Find output directory
        output_dir = Path(env_vars.get("OUTPUT_DIR", ""))
        if not output_dir.exists():
            return {
                "success": False,
                "trade_count": 0,
                "output_dir": output_dir,
                "stats": {},
                "stdout": result.stdout,
                "stderr": "Output directory not found"
            }
        
        # Find most recent subdirectory
        subdirs = [d for d in output_dir.iterdir() if d.is_dir()]
        if not subdirs:
            return {
                "success": False,
                "trade_count": 0,
                "output_dir": output_dir,
                "stats": {},
                "stdout": result.stdout,
                "stderr": "No output subdirectories found"
            }
        
        latest_output = max(subdirs, key=lambda x: x.stat().st_mtime)
        
        # Read performance stats
        stats_file = latest_output / "performance_stats.json"
        if not stats_file.exists():
            return {
                "success": False,
                "trade_count": 0,
                "output_dir": latest_output,
                "stats": {},
                "stdout": result.stdout,
                "stderr": "performance_stats.json not found"
            }
        
        with open(stats_file, 'r') as f:
            stats = json.load(f)
        
        # Extract trade count
        trade_count = stats.get("general", {}).get("total_trades", 0)
        
        # Fallback to count trades from positions.csv if total_trades is missing or zero
        if trade_count == 0:
            positions_file = latest_output / "positions.csv"
            if positions_file.exists():
                try:
                    with open(positions_file, 'r') as f:
                        lines = f.readlines()
                        # Count non-header rows, optionally filter out snapshot rows
                        position_rows = 0
                        for line in lines[1:]:  # Skip header
                            if line.strip():
                                # Check if this is a snapshot row (if column exists)
                                parts = line.strip().split(',')
                                if len(parts) > 0 and parts[0].strip().lower() != 'snapshot':
                                    position_rows += 1
                        trade_count = position_rows
                except Exception:
                    pass  # Keep trade_count as 0 if positions.csv can't be read
        
        return {
            "success": True,
            "trade_count": trade_count,
            "output_dir": latest_output,
            "stats": stats,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "trade_count": 0,
            "output_dir": None,
            "stats": {},
            "stdout": "",
            "stderr": "Backtest timed out after 300 seconds"
        }
    except Exception as e:
        return {
            "success": False,
            "trade_count": 0,
            "output_dir": None,
            "stats": {},
            "stdout": "",
            "stderr": f"Unexpected error: {e}"
        }


def verify_trade_direction(output_dir: Path, expected_direction: str) -> bool:
    """Verify that the entry trade matches the expected direction."""
    try:
        orders_file = output_dir / "orders.csv"
        if not orders_file.exists():
            return False
        
        with open(orders_file, 'r') as f:
            lines = f.readlines()
            if len(lines) < 2:  # Header + at least one order
                return False
            
            # Parse header to find side column
            header = lines[0].strip().split(',')
            side_col_index = None
            for i, col in enumerate(header):
                if col.strip().lower() in ['side', 'order_side']:
                    side_col_index = i
                    break
            
            if side_col_index is None:
                return False
            
            # Find the first non-cancel order (entry)
            for line in lines[1:]:
                if line.strip():
                    parts = line.strip().split(',')
                    if len(parts) > side_col_index:
                        order_side = parts[side_col_index].strip().upper()
                        # Skip cancel orders
                        if order_side not in ['CANCEL', 'CANCELLED']:
                            return order_side == expected_direction.upper()
        
        return False
        
    except Exception:
        return False


@pytest.fixture
def ensure_test_data():
    """Ensure test data exists, generate if needed."""
    catalog_path = Path("data/test_catalog/phase2_basic")
    
    if not catalog_path.exists():
        print("Test catalog not found, generating test data...")
        try:
            result = subprocess.run(
                ["python", "tests/generate_phase2_data.py"],
                cwd=str(PROJECT_ROOT),
                check=True,
                timeout=120,
                capture_output=True,
                text=True
            )
            print("Test data generation completed")
        except subprocess.CalledProcessError as e:
            pytest.fail(f"Failed to generate test data: {e.stderr}")
        except subprocess.TimeoutExpired:
            pytest.fail("Test data generation timed out")
    
    yield


@pytest.mark.integration
@pytest.mark.timeout(60)
@pytest.mark.parametrize("scenario", TEST_SCENARIOS, ids=lambda s: s["name"])
def test_basic_crossover_scenarios(ensure_test_data, scenario):
    """Test basic crossover scenarios with expected trade counts."""
    # Construct env file path
    env_file = ENV_CONFIGS_DIR / scenario["env_file"]
    
    # Verify env file exists
    assert env_file.exists(), f"Environment file not found: {env_file}"
    
    # Run backtest
    result = run_backtest_with_env(env_file)
    
    # Assert backtest succeeded
    assert result["success"], f"Backtest failed: {result['stderr']}"
    
    # Assert trade count matches
    assert result["trade_count"] == scenario["expected_trades"], \
        f"Expected {scenario['expected_trades']} trades, got {result['trade_count']}"
    
    # Verify trade direction if specified
    if scenario["expected_direction"] is not None:
        direction_ok = verify_trade_direction(result["output_dir"], scenario["expected_direction"])
        assert direction_ok, f"Trade direction verification failed for {scenario['name']}"
    
    print(f"✅ {scenario['name']}: {result['trade_count']} trades as expected")


@pytest.mark.integration
def test_catalog_exists():
    """Verify test catalog exists and contains required data."""
    from backtest.run_backtest import discover_catalog_bar_types
    from utils.instruments import normalize_instrument_id
    
    catalog_path = Path("data/test_catalog/phase2_basic")
    assert catalog_path.exists(), "Test catalog directory not found"
    
    # Use discover_catalog_bar_types to get available datasets
    available_datasets = discover_catalog_bar_types(catalog_path)
    assert available_datasets, "No datasets found in catalog"
    
    # Check for required test symbols using normalized instrument IDs
    test_symbols = ["TEST-BULL/USD", "TEST-BEAR/USD", "TEST-MULTI/USD", "TEST-NONE/USD"]
    venue = "IDEALPRO"
    bar_spec = "1-MINUTE-MID-EXTERNAL"
    
    for symbol in test_symbols:
        normalized_id = normalize_instrument_id(symbol, venue)
        # Check if any dataset contains both the normalized instrument ID and bar spec
        found = any(normalized_id in dataset and bar_spec in dataset for dataset in available_datasets)
        assert found, f"Required test symbol {symbol} (normalized: {normalized_id}) not found in available datasets: {available_datasets}"
    
    print(f"Available datasets: {available_datasets}")


@pytest.mark.integration
def test_env_configs_exist():
    """Verify all environment configuration files exist and are valid."""
    required_files = [scenario["env_file"] for scenario in TEST_SCENARIOS]
    missing_files = []
    
    for env_file in required_files:
        file_path = ENV_CONFIGS_DIR / env_file
        if not file_path.exists():
            missing_files.append(env_file)
    
    assert not missing_files, f"Missing environment files: {missing_files}"
    
    # Verify each file has required parameters
    required_params = [
        "CATALOG_PATH", "BACKTEST_SYMBOL", "BACKTEST_VENUE", 
        "BACKTEST_START_DATE", "BACKTEST_END_DATE", "BACKTEST_BAR_SPEC",
        "BACKTEST_FAST_PERIOD", "BACKTEST_SLOW_PERIOD"
    ]
    
    for scenario in TEST_SCENARIOS:
        env_file = ENV_CONFIGS_DIR / scenario["env_file"]
        env_vars = load_env_file(env_file)
        
        missing_params = [param for param in required_params if param not in env_vars]
        assert not missing_params, f"Missing parameters in {scenario['env_file']}: {missing_params}"
    
    print("All environment configuration files are valid")
