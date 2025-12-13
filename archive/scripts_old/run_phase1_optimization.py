"""
Phase 1 Grid Optimization - Now with Functional Trailing Stops

This script launches the full 200-combination Phase 1 grid optimization.
Now that trailing stops are confirmed functional (v2.5), this will produce
meaningful, differentiated results across parameter combinations.

Expected runtime: ~3-4 hours for 200 combinations
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

def main():
    print("="*80)
    print("🚀 PHASE 1 GRID OPTIMIZATION")
    print("="*80)
    print("\n✅ Prerequisites Met:")
    print("   - Trailing stops fixed and validated (v2.5)")
    print("   - Clean grid with 200 valid combinations")
    print("   - Grid file: re_optimization_results/phase1_clean_grid.json")
    print("\n📊 Grid Parameters:")
    print("   - BACKTEST_STOP_LOSS_PIPS: [20, 25, 30, 35, 40]")
    print("   - BACKTEST_TAKE_PROFIT_PIPS: [50, 60, 70, 80]")
    print("   - BACKTEST_TRAILING_STOP_ACTIVATION_PIPS: [8, 12, 15, 18, 22]")
    print("   - BACKTEST_TRAILING_STOP_DISTANCE_PIPS: [5, 7, 10]")
    print("\n⏱️  Estimated Runtime: ~3-4 hours (200 combinations)")
    print("="*80)
    
    # Verify grid file exists
    grid_path = Path('re_optimization_results/phase1_clean_grid.json')
    if not grid_path.exists():
        print(f"\n❌ Error: Grid file not found at {grid_path}")
        return 1
    
    print(f"\n✅ Grid file found: {grid_path}")
    
    # Confirm before starting
    response = input("\n🤔 Ready to start Phase 1 optimization? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("❌ Optimization cancelled by user")
        return 0
    
    print("\n" + "="*80)
    print("🚀 LAUNCHING OPTIMIZATION...")
    print("="*80)
    
    start_time = datetime.now()
    print(f"\n⏰ Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Run optimization
    result = subprocess.run(
        ['python', 'optimize_grid.py', str(grid_path)],
        text=True
    )
    
    end_time = datetime.now()
    duration = end_time - start_time
    
    print("\n" + "="*80)
    if result.returncode == 0:
        print("✅ PHASE 1 OPTIMIZATION COMPLETE!")
    else:
        print("❌ OPTIMIZATION FAILED")
    print("="*80)
    print(f"\n⏰ End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️  Duration: {duration}")
    print(f"\n📁 Results saved to: re_optimization_results/")
    print("   - optimization_results.csv (all combinations)")
    print("   - optimization_results_final.csv (summary)")
    
    return result.returncode

if __name__ == '__main__':
    sys.exit(main())
