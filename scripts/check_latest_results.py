"""
Get latest backtest results and compare with Phase 6.
"""
import json
import pandas as pd
from pathlib import Path

# Phase 6 expected
phase6_data = json.load(open("optimization/results/phase6_refinement_results_top_10.json"))
phase6_best = phase6_data[0]

print("=" * 80)
print("LATEST BACKTEST RESULTS")
print("=" * 80)
print()

# Find latest backtest
results_dir = Path("logs/backtest_results")
backtest_dirs = [d for d in results_dir.iterdir() if d.is_dir() and "EUR-USD_" in d.name]
if not backtest_dirs:
    print("No backtest found!")
    exit(1)

latest_backtest = max(backtest_dirs, key=lambda d: d.stat().st_mtime)
print(f"Latest Backtest: {latest_backtest.name}")
print()

# Check if performance_stats.json exists
stats_file = latest_backtest / "performance_stats.json"
if stats_file.exists():
    with open(stats_file, 'r') as f:
        stats = json.load(f)
    
    # Extract metrics (the structure varies)
    if 'pnls' in stats:
        pnl_data = stats['pnls']
        print("Current Results:")
        print(f"  Total PnL: ${pnl_data.get('PnL (total)', 'N/A')}")
        if 'general' in stats:
            general = stats['general']
            print(f"  Trade Count: {general.get('Total trades', 'N/A')}")
            print(f"  Sharpe Ratio: {general.get('Sharpe ratio', 'N/A')}")
            print(f"  Win Rate: {general.get('Win Rate', 'N/A')}")
    else:
        print("Stats structure:", list(stats.keys()))
        print(json.dumps(stats, indent=2, default=str))
else:
    print("No performance_stats.json found")

print()
print("Phase 6 Expected:")
print(f"  Total PnL: ${phase6_best['total_pnl']:.2f}")
print(f"  Trade Count: {phase6_best['trade_count']}")
print(f"  Sharpe Ratio: {phase6_best['sharpe_ratio']:.3f}")
print(f"  Win Rate: {phase6_best['win_rate']*100:.1f}%")

