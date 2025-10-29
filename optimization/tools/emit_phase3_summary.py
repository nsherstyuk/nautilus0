#!/usr/bin/env python3
"""
Phase 3 Summary Emitter

Parses optimization/configs/phase3_fine_grid.yaml and prints the Phase 2 best results
and fine-grid parameter ranges to console for quick reference.

Usage:
    python optimization/tools/emit_phase3_summary.py

This script provides a lightweight way to view the key configuration details
without having to manually parse the YAML file.
"""

import sys
from pathlib import Path
import yaml


def main():
    """Parse and display Phase 3 configuration summary."""
    # Get project root (parent of optimization directory)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent
    config_path = project_root / "optimization" / "configs" / "phase3_fine_grid.yaml"
    
    if not config_path.exists():
        print(f"Error: Configuration file not found: {config_path}")
        return 1
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML configuration: {e}")
        return 1
    except Exception as e:
        print(f"Error: Failed to read configuration: {e}")
        return 1
    
    print("=" * 60)
    print("PHASE 3 FINE GRID OPTIMIZATION SUMMARY")
    print("=" * 60)
    print()
    
    # Extract and display Phase 2 best results
    print("PHASE 2 BEST RESULTS (Reference):")
    print("-" * 40)
    
    # These values are hardcoded in the YAML comments
    phase2_best = {
        "fast_period": 10,
        "slow_period": 100, 
        "crossover_threshold_pips": 1.0,
        "sharpe_ratio": 0.0
    }
    
    for param, value in phase2_best.items():
        print(f"  {param}: {value}")
    
    print()
    
    # Extract and display fine-grid parameter ranges
    print("FINE-GRID PARAMETER RANGES:")
    print("-" * 40)
    
    parameters = config.get("parameters", {})
    
    for param_name, param_config in parameters.items():
        values = param_config.get("values", [])
        if values:
            print(f"  {param_name}: {values}")
    
    print()
    
    # Display configuration summary
    print("CONFIGURATION SUMMARY:")
    print("-" * 40)
    
    # Calculate total combinations
    total_combinations = 1
    for param_name, param_config in parameters.items():
        values = param_config.get("values", [])
        total_combinations *= len(values)
    
    print(f"  Total combinations: {total_combinations}")
    print(f"  Parameters optimized: {len(parameters)}")
    
    # Display fixed parameters count
    fixed_params = config.get("fixed", {})
    print(f"  Fixed parameters: {len(fixed_params)}")
    
    # Display optimization settings
    opt_settings = config.get("optimization", {})
    print(f"  Objective: {opt_settings.get('objective', 'N/A')}")
    print(f"  Workers: {opt_settings.get('workers', 'N/A')}")
    print(f"  Timeout: {opt_settings.get('timeout_seconds', 'N/A')}s")
    
    print()
    print("=" * 60)
    print("Configuration parsed successfully!")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
