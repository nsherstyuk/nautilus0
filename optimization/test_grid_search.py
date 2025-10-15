#!/usr/bin/env python3
"""
Test script for grid search optimizer.
This script tests the basic functionality without running actual backtests.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from optimization.grid_search import (
    load_grid_config, 
    generate_parameter_combinations,
    validate_parameter_combination,
    ParameterSet
)

def test_config_loading():
    """Test configuration loading."""
    print("Testing configuration loading...")
    
    config_path = Path("optimization/test_config.yaml")
    opt_config, param_ranges, fixed_params = load_grid_config(config_path)
    
    print(f"✓ Loaded config: objective={opt_config.objective}, workers={opt_config.workers}")
    print(f"✓ Parameter ranges: {len(param_ranges)} parameters")
    print(f"✓ Fixed parameters: {len(fixed_params)} parameters")
    
    return opt_config, param_ranges, fixed_params

def test_combination_generation(param_ranges, fixed_params):
    """Test parameter combination generation."""
    print("\nTesting parameter combination generation...")
    
    combinations = generate_parameter_combinations(param_ranges, fixed_params)
    
    print(f"✓ Generated {len(combinations)} combinations")
    
    # Show first few combinations
    for i, combo in enumerate(combinations[:3]):
        print(f"  Combination {i+1}: fast={combo.fast_period}, slow={combo.slow_period}")
    
    return combinations

def test_parameter_validation(combinations):
    """Test parameter validation."""
    print("\nTesting parameter validation...")
    
    valid_count = 0
    for combo in combinations:
        is_valid, error_msg = validate_parameter_combination(combo)
        if is_valid:
            valid_count += 1
        else:
            print(f"  Invalid combination: {error_msg}")
    
    print(f"✓ {valid_count}/{len(combinations)} combinations are valid")
    
    return valid_count

def test_environment_conversion(combinations):
    """Test environment variable conversion."""
    print("\nTesting environment variable conversion...")
    
    if combinations:
        combo = combinations[0]
        env_dict = combo.to_env_dict()
        
        print(f"✓ Environment variables: {len(env_dict)} variables")
        print(f"  Example: BACKTEST_FAST_PERIOD={env_dict['BACKTEST_FAST_PERIOD']}")
        print(f"  Example: STRATEGY_DMI_ENABLED={env_dict['STRATEGY_DMI_ENABLED']}")
    
    return True

def main():
    """Run all tests."""
    print("Grid Search Optimizer - Test Suite")
    print("=" * 40)
    
    try:
        # Test 1: Configuration loading
        opt_config, param_ranges, fixed_params = test_config_loading()
        
        # Test 2: Combination generation
        combinations = test_combination_generation(param_ranges, fixed_params)
        
        # Test 3: Parameter validation
        valid_count = test_parameter_validation(combinations)
        
        # Test 4: Environment conversion
        test_environment_conversion(combinations)
        
        print("\n" + "=" * 40)
        print("✓ All tests passed!")
        print(f"✓ Ready to run {len(combinations)} parameter combinations")
        print("\nTo run the actual grid search:")
        print("python optimization/grid_search.py --config optimization/test_config.yaml --workers 2")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
