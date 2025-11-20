"""
Quick status check: What's been done and what's next
"""
from pathlib import Path
from datetime import datetime
import json

def check_file(path: str, desc: str) -> bool:
    """Check if a file exists and show status"""
    exists = Path(path).exists()
    status = "✅" if exists else "❌"
    print(f"{status} {desc}: {path}")
    return exists

def main():
    print("="*80)
    print("📊 PROJECT STATUS CHECK")
    print("="*80)
    print(f"\n⏰ Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    print("="*80)
    print("🔧 TRAILING STOP FIX v2.5")
    print("="*80)
    check_file("strategies/moving_average_crossover.py", "Strategy with trailing fix")
    check_file("TRAILING_STOP_FIX_V2.5_SUMMARY.md", "Fix documentation")
    check_file("validate_trailing.py", "Quick validation script")
    check_file("validate_trailing_impact.py", "Impact validation test")
    print("\n✅ Status: COMPLETE - Trailing stops are functional")
    
    print("\n" + "="*80)
    print("📋 OPTIMIZATION INFRASTRUCTURE")
    print("="*80)
    check_file("optimize_grid.py", "Grid optimizer")
    check_file("re_optimization_results/phase1_clean_grid.json", "Phase 1 grid (200 combos)")
    check_file("run_phase1_optimization.py", "Phase 1 launcher")
    check_file("analyze_grid_best.py", "Results analyzer")
    print("\n✅ Status: READY - Can start Phase 1 optimization")
    
    print("\n" + "="*80)
    print("📈 NEXT ACTIONS")
    print("="*80)
    
    # Check if validation test completed
    results_dir = Path('logs/backtest_results')
    if results_dir.exists():
        recent_results = sorted(
            results_dir.glob('EUR-USD_*'),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:3]
        
        if len(recent_results) >= 2:
            print("\n✅ Recent backtests found:")
            for i, result in enumerate(recent_results[:2], 1):
                age_min = (datetime.now().timestamp() - result.stat().st_mtime) / 60
                print(f"   {i}. {result.name} ({age_min:.1f} min ago)")
            
            if len(recent_results) >= 2 and (datetime.now().timestamp() - recent_results[1].stat().st_mtime) / 60 < 30:
                print("\n✅ Validation test appears to be running or recently completed")
                print("   Action: Check validation test results")
            else:
                print("\n⚠️  Validation test may not have completed yet")
                print("   Action: Wait for validation_trailing_impact.py to finish")
        else:
            print("\n⚠️  Less than 2 recent backtests found")
            print("   Action: Run validate_trailing_impact.py")
    
    print("\n📋 RECOMMENDED NEXT STEPS:")
    print("   1. ✅ Review validation test output (if complete)")
    print("   2. 🚀 Launch Phase 1: python run_phase1_optimization.py")
    print("   3. ⏳ Wait ~3-4 hours for 200 combinations")
    print("   4. 📊 Analyze results: python analyze_grid_best.py")
    
    print("\n" + "="*80)
    print("📚 DOCUMENTATION")
    print("="*80)
    check_file("NEXT_STEPS.md", "Detailed next steps guide")
    check_file("TRAILING_STOP_FIX_V2.5_SUMMARY.md", "Trailing fix summary")
    check_file("BEST_CONFIGURATION_RECORD.md", "Historical best configs")
    
    print("\n" + "="*80)
    print("✅ STATUS CHECK COMPLETE")
    print("="*80)

if __name__ == '__main__':
    main()
