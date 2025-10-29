"""
Phase 3.1-3.2 Crossover Filter Tests

This module contains pytest-based tests for Phase 3.1-3.2 crossover threshold and 
pre-crossover separation filter tests with rejection reason verification.

Prerequisites: Run `python tests/generate_phase3_crossover_data.py` first
Usage: pytest tests/test_crossover_filters.py -v

Expected outcomes for each scenario:
- threshold_fail: 0 trades, rejection logged
- threshold_pass: 1 trade, no rejection
- separation_once: 1 trade, no rejection
- separation_never: 0 trades, rejection logged
- separation_recent: 1 trade, no rejection

Note: Tests verify both trade counts AND rejection reasons in rejected_signals.csv
"""

import pytest
import subprocess
import json
import os
import csv
from pathlib import Path
from typing import Dict, Any, List

# Configuration constants
PROJECT_ROOT = Path(__file__).parent.parent
BACKTEST_SCRIPT = PROJECT_ROOT / "backtest" / "run_backtest.py"
ENV_CONFIGS_DIR = PROJECT_ROOT / "tests" / "env_configs"
TEST_RESULTS_DIR = PROJECT_ROOT / "logs" / "test_results" / "phase3_crossover_filters"

# Test scenarios configuration
TEST_SCENARIOS = [
    # Crossover Threshold Tests
    {
        "name": "threshold_fail",
        "env_file": "env.test_crossover_threshold",
        "symbol": "TST/USD",
        "expected_trades": 0,
        "expected_rejection": "crossover_threshold_not_met",
        "description": "Crossover with 0.5 pip separation (below 1.0 pip threshold)"
    },
    {
        "name": "threshold_pass",
        "env_file": "env.test_crossover_threshold",
        "symbol": "TST/USD",
        "expected_trades": 1,
        "expected_rejection": None,
        "description": "Crossover with 1.5 pip separation (above 1.0 pip threshold)"
    },
    # Pre-Crossover Separation Tests
    {
        "name": "separation_once",
        "env_file": "env.test_pre_crossover_separation",
        "symbol": "TST/USD",
        "expected_trades": 1,
        "expected_rejection": None,
        "description": "Separation met once at bar N-3 (within 5-bar lookback)"
    },
    {
        "name": "separation_never",
        "env_file": "env.test_pre_crossover_separation",
        "symbol": "TST/USD",
        "expected_trades": 0,
        "expected_rejection": "pre_crossover_separation_insufficient",
        "description": "Separation never met in 5-bar lookback"
    },
    {
        "name": "separation_recent",
        "env_file": "env.test_pre_crossover_separation",
        "symbol": "TST/USD",
        "expected_trades": 1,
        "expected_rejection": None,
        "description": "Separation met at bar N-1 (immediate previous bar)"
    },
]


def load_env_file(env_file_path: Path) -> Dict[str, str]:
    """Load environment variables from .env file"""
    env_vars = {}
    try:
        with open(env_file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
    except Exception as e:
        raise FileNotFoundError(f"Failed to load env file {env_file_path}: {e}")
    return env_vars


def run_backtest_with_env(env_file: Path, symbol_override: str = None) -> Dict[str, Any]:
    """Run backtest with environment file and optional symbol override"""
    try:
        # Load environment variables
        env_vars = load_env_file(env_file)
        
        # Override symbol if provided
        if symbol_override:
            env_vars['BACKTEST_SYMBOL'] = symbol_override
        
        # Create subprocess environment
        process_env = os.environ.copy()
        process_env.update(env_vars)
        
        # Run backtest
        result = subprocess.run(
            ['python', str(BACKTEST_SCRIPT)],
            env=process_env,
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
        
        # Find output directory (require OUTPUT_DIR to be set and exist)
        output_base = Path(env_vars.get('OUTPUT_DIR', ''))
        if not output_base.exists():
            return {
                "success": False,
                "trade_count": 0,
                "output_dir": output_base,
                "stats": {},
                "stdout": result.stdout,
                "stderr": "Output directory not found"
            }
        
        # Find most recent subdirectory
        subdirs = [d for d in output_base.iterdir() if d.is_dir()]
        if not subdirs:
            return {
                "success": False,
                "trade_count": 0,
                "output_dir": output_base,
                "stats": {},
                "stdout": result.stdout,
                "stderr": "No output subdirectories found"
            }
        
        output_dir = max(subdirs, key=lambda x: x.stat().st_mtime)
        
        # Read performance stats
        stats_file = output_dir / "performance_stats.json"
        if stats_file.exists():
            with open(stats_file, 'r') as f:
                stats = json.load(f)
                trade_count = stats.get('general', {}).get('total_trades', 0)
        else:
            stats = {}
            trade_count = 0
        
        # Fallback to count trades from positions.csv if total_trades is missing or zero
        if trade_count == 0:
            positions_file = output_dir / "positions.csv"
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
            "output_dir": output_dir,
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
            "stderr": "Backtest timed out after 60 seconds"
        }
    except Exception as e:
        return {
            "success": False,
            "trade_count": 0,
            "output_dir": None,
            "stats": {},
            "stdout": "",
            "stderr": f"Backtest failed: {e}"
        }


def read_rejected_signals(output_dir: Path) -> List[Dict[str, str]]:
    """Parse rejected_signals.csv and return list of rejection records"""
    rejected_file = output_dir / "rejected_signals.csv"
    
    if not rejected_file.exists():
        return []
    
    try:
        records = []
        with open(rejected_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(row)
        return records
    except Exception as e:
        print(f"Warning: Failed to read rejected_signals.csv: {e}")
        return []


def verify_rejection_reason(output_dir: Path, expected_reason_substring: str) -> bool:
    """Verify that rejected_signals.csv contains expected rejection reason"""
    records = read_rejected_signals(output_dir)
    
    if not records and expected_reason_substring is not None:
        return False
    
    if expected_reason_substring is None:
        return len(records) == 0
    
    # Check if any record contains the expected reason substring
    for record in records:
        reason = record.get('reason', '')
        if expected_reason_substring in reason:
            return True
    
    # Debug: print found rejection reasons
    found_reasons = [r.get('reason', '') for r in records]
    print(f"Found rejections: {found_reasons}")
    return False


@pytest.fixture
def ensure_test_data():
    """Ensure test data exists, generate if needed"""
    catalog_path = Path("data/test_catalog/phase3_crossover_filters")
    
    if not catalog_path.exists():
        print("Test data not found, generating...")
        try:
            subprocess.run(
                ["python", "tests/generate_phase3_crossover_data.py"],
                check=True,
                timeout=300
            )
            print("✅ Test data generated successfully")
        except subprocess.CalledProcessError as e:
            pytest.fail(f"Failed to generate test data: {e}")
        except subprocess.TimeoutExpired:
            pytest.fail("Test data generation timed out")
    
    yield


@pytest.mark.integration
@pytest.mark.timeout(300)
@pytest.mark.parametrize("scenario", TEST_SCENARIOS, ids=lambda s: s["name"])
def test_crossover_filter_scenarios(ensure_test_data, scenario):
    """Test individual crossover filter scenarios with rejection verification"""
    env_file = ENV_CONFIGS_DIR / scenario["env_file"]
    
    # Verify env file exists
    assert env_file.exists(), f"Environment file not found: {env_file}"
    
    # Run backtest
    result = run_backtest_with_env(env_file, symbol_override=scenario["symbol"])
    
    # Assert backtest succeeded
    if not result["success"]:
        print(f"Backtest stdout: {result['stdout']}")
        print(f"Backtest stderr: {result['stderr']}")
    assert result["success"], f"Backtest failed: {result['stderr']}"
    
    # Assert trade count matches
    assert result["trade_count"] == scenario["expected_trades"], \
        f"Expected {scenario['expected_trades']} trades, got {result['trade_count']}"
    
    # Verify rejection reason
    rejection_found = verify_rejection_reason(
        result["output_dir"], 
        scenario["expected_rejection"]
    )
    
    if scenario["expected_rejection"] is not None:
        assert rejection_found, \
            f"Expected rejection reason containing '{scenario['expected_rejection']}' not found in rejected_signals.csv"
    else:
        assert rejection_found, "Expected no rejections but found some"
    
    print(f"✅ {scenario['name']}: {result['trade_count']} trades, "
          f"rejection={'found' if scenario['expected_rejection'] else 'none'}")


@pytest.mark.integration
def test_catalog_exists():
    """Verify test catalog exists with all required symbols"""
    catalog_path = Path("data/test_catalog/phase3_crossover_filters")
    assert catalog_path.exists(), "Test catalog not found. Run 'python tests/generate_phase3_crossover_data.py' to generate test data."
    
    # Import here to avoid circular imports
    from backtest.run_backtest import discover_catalog_bar_types
    
    try:
        available_datasets = discover_catalog_bar_types(str(catalog_path))
        print(f"Available datasets: {available_datasets}")
        
        # Check for all required test symbols
        required_symbols = [
            "TST/USD"
        ]
        
        for symbol in required_symbols:
            # Look for the symbol in any of the available datasets (which include bar specs)
            symbol_found = any(symbol in dataset for dataset in available_datasets)
            assert symbol_found, f"Required symbol {symbol} not found in catalog. Available: {available_datasets}"
            
    except Exception as e:
        pytest.fail(f"Failed to discover catalog datasets: {e}")


@pytest.mark.integration
def test_env_configs_exist():
    """Verify environment configuration files exist with correct settings"""
    # Check crossover threshold config
    threshold_env = ENV_CONFIGS_DIR / "env.test_crossover_threshold"
    assert threshold_env.exists(), "Crossover threshold env file not found"
    
    threshold_vars = load_env_file(threshold_env)
    assert threshold_vars.get('STRATEGY_CROSSOVER_THRESHOLD_PIPS') == '1.0', \
        "Crossover threshold not set to 1.0 pips"
    assert threshold_vars.get('STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS') == '0.0', \
        "Pre-crossover separation should be disabled"
    
    # Check pre-crossover separation config
    separation_env = ENV_CONFIGS_DIR / "env.test_pre_crossover_separation"
    assert separation_env.exists(), "Pre-crossover separation env file not found"
    
    separation_vars = load_env_file(separation_env)
    assert separation_vars.get('STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS') == '2.0', \
        "Pre-crossover separation not set to 2.0 pips"
    assert separation_vars.get('STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS') == '5', \
        "Pre-crossover lookback not set to 5 bars"
    assert separation_vars.get('STRATEGY_CROSSOVER_THRESHOLD_PIPS') == '0.0', \
        "Crossover threshold should be disabled"


@pytest.mark.integration
def test_rejection_csv_format():
    """Verify rejected_signals.csv has expected format"""
    # Run a failing scenario to generate rejection data
    env_file = ENV_CONFIGS_DIR / "env.test_crossover_threshold"
    result = run_backtest_with_env(env_file, symbol_override="TEST-THRESH-FAIL/USD")
    
    assert result["success"], "Backtest should succeed even with rejections"
    
    # Check rejected_signals.csv format
    records = read_rejected_signals(result["output_dir"])
    assert len(records) > 0, "Should have at least one rejection record"
    
    # Check CSV structure - verify presence of core fields
    core_columns = ["timestamp", "status", "reason"]
    for record in records:
        for column in core_columns:
            assert column in record, f"Missing core column '{column}' in rejected_signals.csv"
        
        assert record.get('status') == 'rejected', "Status should be 'rejected'"
        assert record.get('reason'), "Reason should not be empty"
        
        # Check for either fast_sma/slow_sma if available (optional fields)
        has_sma_fields = 'fast_sma' in record or 'slow_sma' in record
        if has_sma_fields:
            assert 'fast_sma' in record, "If SMA fields present, fast_sma should be included"
            assert 'slow_sma' in record, "If SMA fields present, slow_sma should be included"
    
    print(f"✅ Rejection CSV format verified: {len(records)} rejection(s) found")
