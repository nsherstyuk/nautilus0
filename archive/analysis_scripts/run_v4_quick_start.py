"""
Quick Start V4 - Dynamic SL/TP Strategy

This script helps you get V4 running quickly with proper setup.
"""

import os
import sys
from pathlib import Path
import shutil

def setup_v4_environment():
    """Setup V4 environment and dependencies."""
    
    print("Setting up V4 environment...")
    
    # Create necessary directories
    directories = [
        "v4/logs",
        "v4/models",
        "v4/data"
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"Created: {directory}")
    
    # Copy model from main directory
    model_source = Path("models/ml_model_mtf.pkl")
    model_target = Path("v4/models/ml_model_mtf.pkl")
    
    if model_source.exists() and not model_target.exists():
        shutil.copy2(model_source, model_target)
        print(f"Copied model: {model_source} -> {model_target}")
    
    # Set environment variable for V4
    os.environ["V4_CONFIG_PATH"] = str(Path("v4/.env.mtf_v4").absolute())
    
    print("V4 environment setup complete!")

def run_v4_backtest():
    """Run V4 backtest with proper setup."""
    
    print("\nRunning V4 backtest...")
    
    # Change to project root
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    # Set environment
    os.environ["V4_CONFIG_PATH"] = str(Path("v4/.env.mtf_v4").absolute())
    
    # Run backtest
    import subprocess
    result = subprocess.run([
        sys.executable, str(Path(__file__).parent / "v4" / "backtest" / "run_backtest_mtf_v4_replay.py")
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        print("V4 backtest completed successfully!")
        print(result.stdout)
    else:
        print("V4 backtest failed!")
        print(result.stderr)
    
    return result.returncode == 0

def compare_v4_v2():
    """Compare V4 with V2 results."""
    
    print("\nComparing V4 vs V2...")
    
    # Find latest results
    v2_results = find_latest_results("backtest_results", "MTF_V2_REPLAY")
    v4_results = find_latest_results("v4/backtest_results", "MTF_V4_REPLAY")
    
    if v2_results and v4_results:
        print(f"V2 results: {v2_results.name}")
        print(f"V4 results: {v4_results.name}")
        
        # Simple comparison
        v2_summary = v2_results / "summary.txt"
        v4_summary = v4_results / "summary.txt"
        
        if v2_summary.exists() and v4_summary.exists():
            print("\nV2 Summary:")
            print(v2_summary.read_text())
            print("\nV4 Summary:")
            print(v4_summary.read_text())
    else:
        print("Could not find both V2 and V4 results")

def find_latest_results(base_dir, pattern):
    """Find latest results directory."""
    
    base_path = Path(base_dir)
    if not base_path.exists():
        return None
    
    matching_dirs = [d for d in base_path.iterdir() if d.is_dir() and pattern in d.name]
    return max(matching_dirs, key=lambda x: x.stat().st_mtime) if matching_dirs else None

def main():
    """Main V4 quick start."""
    
    print("MTF V4 Quick Start - Dynamic SL/TP Strategy")
    print("=" * 50)
    
    # Setup environment
    setup_v4_environment()
    
    # Run backtest
    success = run_v4_backtest()
    
    if success:
        # Compare results
        compare_v4_v2()
        
        print("\n" + "=" * 50)
        print("V4 Quick Start Complete!")
        print("\nNext steps:")
        print("1. Review V4 results in v4/backtest_results/")
        print("2. Compare with V2 performance")
        print("3. Adjust dynamic parameters in v4/config/mtf_v4_config.py")
        print("4. Re-run to test improvements")
        print("\nV4 is completely separate from V2 - safe for experimentation!")
    else:
        print("\nV4 setup failed. Check error messages above.")

if __name__ == "__main__":
    main()
