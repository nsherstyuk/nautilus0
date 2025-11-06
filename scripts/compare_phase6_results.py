"""
Compare Phase 6 results with current backtest results.
"""
import json
import pandas as pd
from pathlib import Path

# Phase 6 expected results
phase6_file = Path("optimization/results/phase6_refinement_results_top_10.json")
phase6_data = json.load(open(phase6_file))
phase6_best = phase6_data[0]

print("=" * 80)
print("PHASE 6 vs CURRENT BACKTEST COMPARISON")
print("=" * 80)
print()

print("Phase 6 Expected Results (run_id 21):")
print(f"  Total PnL: ${phase6_best['total_pnl']:.2f}")
print(f"  Sharpe Ratio: {phase6_best['sharpe_ratio']:.3f}")
print(f"  Trade Count: {phase6_best['trade_count']}")
print(f"  Win Rate: {phase6_best['win_rate']*100:.1f}%")
print()

# Find latest backtest
results_dir = Path("logs/backtest_results")
backtest_dirs = [d for d in results_dir.iterdir() if d.is_dir() and "EUR-USD_" in d.name]
if not backtest_dirs:
    print("No recent backtest found!")
    exit(1)

latest_backtest = max(backtest_dirs, key=lambda d: d.stat().st_mtime)
print(f"Latest Backtest: {latest_backtest.name}")
print()

# Load current results
stats_file = latest_backtest / "performance_stats.json"
if stats_file.exists():
    stats = pd.read_json(stats_file)
    print("Current Backtest Results:")
    print(f"  Total PnL: ${stats['total_pnl'].iloc[0]:.2f}")
    print(f"  Sharpe Ratio: {stats['sharpe_ratio'].iloc[0]:.3f}")
    print(f"  Trade Count: {stats['trade_count'].iloc[0]}")
    print(f"  Win Rate: {stats['win_rate'].iloc[0]*100:.1f}%")
    print()
    
    # Compare
    pnl_diff = stats['total_pnl'].iloc[0] - phase6_best['total_pnl']
    sharpe_diff = stats['sharpe_ratio'].iloc[0] - phase6_best['sharpe_ratio']
    trades_diff = stats['trade_count'].iloc[0] - phase6_best['trade_count']
    
    print("Differences:")
    print(f"  PnL Difference: ${pnl_diff:+.2f}")
    print(f"  Sharpe Difference: {sharpe_diff:+.3f}")
    print(f"  Trades Difference: {trades_diff:+d}")
    print()
    
    if abs(pnl_diff) < 0.01 and abs(sharpe_diff) < 0.001 and trades_diff == 0:
        print("[OK] Results match Phase 6!")
    else:
        print("[WARNING] Results differ from Phase 6!")
else:
    print("No performance_stats.json found in latest backtest")

