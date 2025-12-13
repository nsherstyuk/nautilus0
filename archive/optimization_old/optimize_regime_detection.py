#!/usr/bin/env python3
"""
Regime Detection Optimization Script

This script runs optimization for regime detection parameters to find optimal
ADX thresholds and TP/SL/trailing stop multipliers.

Usage:
    # Focused optimization (54 combinations, ~1 hour)
    python optimize_regime_detection.py --focused
    
    # Full optimization (109k+ combinations, ~15+ hours)
    python optimize_regime_detection.py --full
    
    # Custom workers
    python optimize_regime_detection.py --focused --workers 16
    
    # Custom objective
    python optimize_regime_detection.py --focused --objective total_pnl
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

def load_env_file():
    """Load environment variables from .env file."""
    env_vars = {}
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars

def run_optimization(config_file: Path, objective: str = "sharpe_ratio", workers: int = 8, output_file: str = None):
    """Run regime detection optimization."""
    
    if not config_file.exists():
        print(f"ERROR: Config file not found: {config_file}")
        return False
    
    # Determine output file if not specified
    if output_file is None:
        if "focused" in config_file.name:
            output_file = "optimization/results/regime_detection_focused_results.csv"
        else:
            output_file = "optimization/results/regime_detection_results.csv"
    
    print("=" * 80)
    print("REGIME DETECTION OPTIMIZATION")
    print("=" * 80)
    print(f"Config: {config_file.name}")
    print(f"Objective: {objective}")
    print(f"Workers: {workers}")
    print(f"Output: {output_file}")
    print("=" * 80)
    print()
    
    # Build command
    cmd = [
        sys.executable,
        "optimization/grid_search.py",
        "--config", str(config_file),
        "--objective", objective,
        "--workers", str(workers),
        "--output", output_file,
        "--no-resume"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    print()
    
    # Load environment variables from .env file
    env = load_env_file()
    env.update(os.environ)  # Merge with existing environment
    
    # Run optimization
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            check=False
        )
        
        if result.returncode == 0:
            print("\n" + "=" * 80)
            print("OPTIMIZATION COMPLETED SUCCESSFULLY!")
            print("=" * 80)
            print(f"Results saved to: {output_file}")
            print("\nTo analyze results:")
            print(f"  python -c \"import pandas as pd; df = pd.read_csv('{output_file}'); print(df.nlargest(10, '{objective}'))\"")
            return True
        else:
            print("\n" + "=" * 80)
            print("OPTIMIZATION FAILED!")
            print("=" * 80)
            print(f"Exit code: {result.returncode}")
            return False
            
    except KeyboardInterrupt:
        print("\n\nOptimization interrupted by user.")
        print("Checkpoint saved. Resume with --resume flag.")
        return False
    except Exception as e:
        print(f"\nERROR: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Optimize regime detection parameters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick test (54 combinations, ~1 hour)
  python optimize_regime_detection.py --focused
  
  # Full optimization (109k+ combinations, ~15+ hours)
  python optimize_regime_detection.py --full
  
  # Custom settings
  python optimize_regime_detection.py --focused --workers 16 --objective total_pnl
        """
    )
    
    parser.add_argument(
        "--focused",
        action="store_true",
        help="Run focused optimization (54 combinations, ~1 hour)"
    )
    
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full optimization (109k+ combinations, ~15+ hours)"
    )
    
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel workers (default: 8)"
    )
    
    parser.add_argument(
        "--objective",
        type=str,
        default="sharpe_ratio",
        choices=["sharpe_ratio", "total_pnl", "win_rate", "profit_factor"],
        help="Objective function to optimize (default: sharpe_ratio)"
    )
    
    args = parser.parse_args()
    
    # Determine which config to use
    if args.focused and args.full:
        print("ERROR: Cannot specify both --focused and --full")
        return 1
    
    if not args.focused and not args.full:
        print("ERROR: Must specify either --focused or --full")
        print("\nUse --focused for quick test (54 combinations, ~1 hour)")
        print("Use --full for comprehensive optimization (109k+ combinations, ~15+ hours)")
        return 1
    
    if args.focused:
        config_file = PROJECT_ROOT / "optimization" / "configs" / "regime_detection_focused.yaml"
    else:
        config_file = PROJECT_ROOT / "optimization" / "configs" / "regime_detection_optimization.yaml"
    
    # Confirm before running full optimization
    if args.full:
        print("\n" + "!" * 80)
        print("WARNING: Full optimization will test 109,350+ combinations!")
        print("Estimated time: 15+ hours")
        print("Consider using --focused first to test if regime detection works")
        print("!" * 80)
        response = input("\nContinue with full optimization? (yes/no): ")
        if response.lower() != "yes":
            print("Cancelled.")
            return 0
    
    # Run optimization
    success = run_optimization(config_file, args.objective, args.workers)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())

