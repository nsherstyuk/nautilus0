"""
Run backtest with duration-based trailing and compare to baseline
"""
import json
from pathlib import Path
import subprocess
import sys

print("="*80)
print("DURATION-BASED TRAILING OPTIMIZATION - BACKTEST COMPARISON")
print("="*80)

# Baseline results
baseline_dir = Path('logs/backtest_results/EUR-USD_20251116_161604')
if not baseline_dir.exists():
    baseline_dir = Path('logs/backtest_results/EUR-USD_20251116_140938')

if baseline_dir.exists():
    with open(baseline_dir / 'performance_stats.json') as f:
        baseline_stats = json.load(f)
    
    baseline_pnl = baseline_stats['pnls']['PnL (total)']
    baseline_wr = baseline_stats['pnls']['Win Rate'] * 100
    baseline_trades = baseline_stats.get('total_trades', 0)
    
    print(f"\n📊 BASELINE (Validated Configuration):")
    print(f"   Directory: {baseline_dir.name}")
    print(f"   Total PnL: ${baseline_pnl:,.2f}")
    print(f"   Win Rate: {baseline_wr:.1f}%")
    print(f"   Trades: {baseline_trades}")
else:
    print("\n⚠️  Baseline results not found. Using expected values.")
    baseline_pnl = 9517.35
    baseline_wr = 48.3
    baseline_trades = 211

print(f"\n🎯 EXPECTED IMPROVEMENT:")
print(f"   Duration-based trailing: +$2,725 (+28.6%)")
print(f"   Target PnL: ${baseline_pnl + 2725:,.2f}")

print(f"\n{'='*80}")
print("Running backtest with duration-based trailing...")
print(f"{'='*80}\n")

# Run backtest
result = subprocess.run(
    ['python', 'backtest/run_backtest.py'],
    capture_output=True,
    text=True
)

if result.returncode != 0:
    print(f"❌ Backtest failed!")
    if result.stderr:
        print(result.stderr)
    sys.exit(1)

print("✅ Backtest completed successfully")

# Find latest results directory
results_base = Path('logs/backtest_results')
latest_dir = max(results_base.glob('EUR-USD_*'), key=lambda p: p.stat().st_mtime)

print(f"\n📁 Results directory: {latest_dir.name}")

# Load and compare results
with open(latest_dir / 'performance_stats.json') as f:
    new_stats = json.load(f)

new_pnl = new_stats['pnls']['PnL (total)']
new_wr = new_stats['pnls']['Win Rate'] * 100
new_trades = new_stats.get('total_trades', 0)

print(f"\n{'='*80}")
print("COMPARISON RESULTS")
print(f"{'='*80}")

metrics = [
    ('Total PnL', baseline_pnl, new_pnl, '$'),
    ('Win Rate', baseline_wr, new_wr, '%'),
    ('Total Trades', baseline_trades, new_trades, ''),
]

print(f"\n{'Metric':<20} {'Baseline':<15} {'New':<15} {'Change':<15}")
print("-"*65)

for name, base_val, new_val, unit in metrics:
    if unit == '$':
        base_str = f"${base_val:,.2f}"
        new_str = f"${new_val:,.2f}"
        change_val = new_val - base_val
        change_str = f"${change_val:+,.2f}"
    elif unit == '%':
        base_str = f"{base_val:.1f}%"
        new_str = f"{new_val:.1f}%"
        change_val = new_val - base_val
        change_str = f"{change_val:+.1f}%"
    else:
        base_str = f"{int(base_val)}"
        new_str = f"{int(new_val)}"
        change_val = int(new_val) - int(base_val)
        change_str = f"{change_val:+d}"
    
    print(f"{name:<20} {base_str:<15} {new_str:<15} {change_str:<15}")

# Analysis
pnl_diff = new_pnl - baseline_pnl
pnl_pct = (pnl_diff / baseline_pnl) * 100
predicted_improvement = 2725

print(f"\n{'='*80}")
print("ANALYSIS")
print(f"{'='*80}")

print(f"\n💰 PnL Change: ${pnl_diff:+,.2f} ({pnl_pct:+.1f}%)")
print(f"   Predicted: +${predicted_improvement:,.0f}")
print(f"   Actual: ${pnl_diff:+,.2f}")

if abs(pnl_diff - predicted_improvement) / predicted_improvement < 0.15:
    print(f"   ✅ Within 15% of prediction - EXCELLENT!")
elif pnl_diff > 0:
    if pnl_diff > predicted_improvement * 0.5:
        print(f"   ✅ Significant improvement achieved!")
    else:
        print(f"   ⚠️  Improvement below prediction but positive")
else:
    print(f"   ❌ Performance decreased - review logs")

print(f"\n📊 Win Rate: {baseline_wr:.1f}% → {new_wr:.1f}% ({new_wr-baseline_wr:+.1f}%)")
print(f"📊 Trade Count: {baseline_trades} → {new_trades} ({new_trades-baseline_trades:+d})")

# Check for >12h trade improvements
print(f"\n{'='*80}")
print("DURATION ANALYSIS")
print(f"{'='*80}")

import pandas as pd

# Load positions from both backtests
baseline_pos = pd.read_csv(baseline_dir / 'positions.csv')
new_pos = pd.read_csv(latest_dir / 'positions.csv')

for df in [baseline_pos, new_pos]:
    df['realized_pnl'] = df['realized_pnl'].str.replace(' USD', '').astype(float)
    df['ts_opened'] = pd.to_datetime(df['ts_opened'])
    df['ts_closed'] = pd.to_datetime(df['ts_closed'])
    df['duration_hours'] = (df['ts_closed'] - df['ts_opened']).dt.total_seconds() / 3600

baseline_long = baseline_pos[baseline_pos['duration_hours'] >= 12]
new_long = new_pos[new_pos['duration_hours'] >= 12]

print(f"\n🕐 TRADES >12 HOURS (Target of optimization):")
print(f"   Baseline: {len(baseline_long)} trades, ${baseline_long['realized_pnl'].sum():,.2f} PnL")
print(f"   New:      {len(new_long)} trades, ${new_long['realized_pnl'].sum():,.2f} PnL")
print(f"   Change:   {len(new_long)-len(baseline_long):+d} trades, ${new_long['realized_pnl'].sum()-baseline_long['realized_pnl'].sum():+,.2f} PnL")

if len(new_long) > 0:
    avg_new = new_long['realized_pnl'].mean()
    avg_baseline = baseline_long['realized_pnl'].mean() if len(baseline_long) > 0 else 0
    print(f"   Avg PnL per trade: ${avg_baseline:.2f} → ${avg_new:.2f} ({avg_new-avg_baseline:+.2f})")

print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}")

if pnl_diff > 1000:
    print(f"\n✅ SUCCESS! Duration-based trailing significantly improved performance.")
    print(f"   Phase 1 delivered ${pnl_diff:+,.2f} improvement")
    print(f"   New baseline: ${new_pnl:,.2f}")
    print(f"\n💡 Next steps:")
    print(f"   • Commit these changes")
    print(f"   • Consider Phase 2: Time-of-day trailing (+$300-500 potential)")
    print(f"   • Consider Phase 3: Volatility-adaptive trailing (+$200-400 potential)")
elif pnl_diff > 0:
    print(f"\n⚠️  Modest improvement of ${pnl_diff:+,.2f}")
    print(f"   Less than predicted but still positive")
    print(f"   May need parameter tuning (threshold hours, trailing distance)")
else:
    print(f"\n❌ Performance decreased by ${abs(pnl_diff):,.2f}")
    print(f"   Review backtest logs for issues")
    print(f"   Check if duration tracking is working correctly")

print(f"\n{'='*80}")
