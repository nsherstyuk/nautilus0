"""
Helper script to analyze completed grid results and extract best configuration.
Works for any grid output directory.
"""
import json
import sys
from pathlib import Path


def find_best_run(grid_dir: str) -> dict:
    """Find the run with maximum net PnL from a grid output directory."""
    base = Path(grid_dir)
    
    if not base.exists():
        print(f"Error: Directory '{grid_dir}' does not exist")
        sys.exit(1)
    
    best = None
    run_count = 0
    
    for run_dir in sorted(base.glob('run_*')):
        run_count += 1
        params_file = run_dir / 'params.json'
        stats_file = run_dir / 'stats.json'
        
        if not params_file.exists() or not stats_file.exists():
            continue
        
        with params_file.open() as pf:
            params = json.load(pf)
        with stats_file.open() as sf:
            stats = json.load(sf)
        
        pnl = stats.get('net_pnl', stats.get('Net PnL', 0))
        win_rate = stats.get('win_rate', stats.get('Win Rate', 0))
        
        if best is None or pnl > best['pnl']:
            best = {
                'run': run_dir.name,
                'pnl': pnl,
                'win_rate': win_rate,
                'params': params,
                'stats': stats
            }
    
    if best is None:
        print(f"Error: No valid runs found in '{grid_dir}'")
        sys.exit(1)
    
    print(f"\n📊 Grid Analysis: {grid_dir}")
    print(f"   Total runs: {run_count}")
    print(f"\n🏆 Best Run: {best['run']}")
    print(f"   Net PnL: ${best['pnl']:,.2f}")
    print(f"   Win Rate: {best['win_rate']:.2%}")
    print(f"\n📋 Parameters:")
    print(json.dumps(best['params'], indent=2))
    
    return best


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_grid_best.py <grid_output_dir>")
        print("Example: python analyze_grid_best.py logs/atr_phase1")
        sys.exit(1)
    
    grid_dir = sys.argv[1]
    find_best_run(grid_dir)
