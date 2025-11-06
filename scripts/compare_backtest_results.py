"""
Compare backtest results: before and after time filter.
"""
from pathlib import Path
import pandas as pd
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Find latest two backtest results
results_dir = Path("logs/backtest_results")
dirs = sorted([d for d in results_dir.iterdir() if d.is_dir() and "EUR-USD_" in d.name], 
              key=lambda d: d.stat().st_mtime, reverse=True)

if len(dirs) < 2:
    print("Need at least 2 backtest results to compare!")
    sys.exit(1)

latest_dir = dirs[0]  # With time filter
previous_dir = dirs[1]  # Without time filter

print("=" * 80)
print("BACKTEST COMPARISON: TIME FILTER IMPACT")
print("=" * 80)
print()

# Load performance stats
def load_perf_stats(dir_path):
    perf_file = dir_path / "performance_stats.json"
    if not perf_file.exists():
        return None
    with open(perf_file, "r") as f:
        return json.load(f)

def extract_pnl(value):
    if pd.isna(value):
        return 0.0
    value_str = str(value)
    import re
    cleaned = re.sub(r'\s*[A-Z]{3}\s*$', '', value_str)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

# Load positions
positions_before = pd.read_csv(previous_dir / "positions.csv")
positions_after = pd.read_csv(latest_dir / "positions.csv")

positions_before["realized_pnl_value"] = positions_before["realized_pnl"].apply(extract_pnl)
positions_after["realized_pnl_value"] = positions_after["realized_pnl"].apply(extract_pnl)

# Load performance stats
stats_before = load_perf_stats(previous_dir)
stats_after = load_perf_stats(latest_dir)

print(f"BEFORE (no time filter): {previous_dir.name}")
print(f"  Total trades: {len(positions_before)}")
print(f"  Total PnL: ${positions_before['realized_pnl_value'].sum():.2f}")
if stats_before:
    print(f"  Win Rate: {stats_before.get('win_rate', 0)*100:.1f}%")
    print(f"  Sharpe Ratio: {stats_before.get('sharpe_ratio', 0):.3f}")
    print(f"  Profit Factor: {stats_before.get('profit_factor', 0):.3f}")
print()

print(f"AFTER (with time filter): {latest_dir.name}")
print(f"  Total trades: {len(positions_after)}")
print(f"  Total PnL: ${positions_after['realized_pnl_value'].sum():.2f}")
if stats_after:
    print(f"  Win Rate: {stats_after.get('win_rate', 0)*100:.1f}%")
    print(f"  Sharpe Ratio: {stats_after.get('sharpe_ratio', 0):.3f}")
    print(f"  Profit Factor: {stats_after.get('profit_factor', 0):.3f}")
print()

print("=" * 80)
print("IMPROVEMENT")
print("=" * 80)
pnl_before = positions_before['realized_pnl_value'].sum()
pnl_after = positions_after['realized_pnl_value'].sum()
pnl_improvement = pnl_after - pnl_before
trades_diff = len(positions_after) - len(positions_before)

print(f"PnL Improvement: ${pnl_improvement:.2f} ({pnl_improvement/pnl_before*100:.1f}% increase)")
print(f"Trade Count Change: {trades_diff} trades ({'+' if trades_diff > 0 else ''}{trades_diff})")
print(f"Avg PnL per Trade:")
print(f"  Before: ${pnl_before/len(positions_before):.2f}")
print(f"  After: ${pnl_after/len(positions_after):.2f}")
print()

if stats_before and stats_after:
    sharpe_improvement = stats_after.get('sharpe_ratio', 0) - stats_before.get('sharpe_ratio', 0)
    pf_improvement = stats_after.get('profit_factor', 0) - stats_before.get('profit_factor', 0)
    print(f"Sharpe Ratio Change: {sharpe_improvement:+.3f}")
    print(f"Profit Factor Change: {pf_improvement:+.3f}")
    print()

print("=" * 80)
print("CONCLUSION")
print("=" * 80)
if pnl_improvement > 0:
    print(f"[SUCCESS] Time filter improved performance by ${pnl_improvement:.2f}!")
    print(f"Excluding hours [1, 2, 12, 18, 21, 23] UTC avoided losses from unprofitable trading hours.")
else:
    print(f"[MIXED] Time filter resulted in ${pnl_improvement:.2f} change.")
print()

