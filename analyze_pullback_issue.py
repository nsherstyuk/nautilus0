"""
Analyze why pullback entry is rejecting so many signals and performing poorly.
"""
import pandas as pd
import json
from pathlib import Path

# Latest backtest directory
latest_dir = Path("logs/backtest_results/EUR-USD_20251116_160436")

# Load performance stats
with open(latest_dir / "performance_stats.json") as f:
    stats = json.load(f)

print("=" * 80)
print("PULLBACK ENTRY ANALYSIS")
print("=" * 80)

print("\n📊 PERFORMANCE OVERVIEW:")
print(f"Total PnL: ${stats['pnls']['PnL (total)']:,.2f}")
print(f"Win Rate: {stats['pnls']['Win Rate']*100:.1f}%")
print(f"Rejected Signals: {stats['rejected_signals_count']:,}")

# Load positions
pos = pd.read_csv(latest_dir / "positions.csv")
pos['ts_opened'] = pd.to_datetime(pos['ts_opened'])
pos['ts_closed'] = pd.to_datetime(pos['ts_closed'])
pos['duration_hours'] = (pos['ts_closed'] - pos['ts_opened']).dt.total_seconds() / 3600

print(f"Executed Trades: {len(pos)}")
print(f"\nAvg Winner: ${stats['pnls']['Avg Winner']:.2f}")
print(f"Avg Loser: ${stats['pnls']['Avg Loser']:.2f}")
print(f"Expectancy: ${stats['pnls']['Expectancy']:.2f}")

# Load rejected signals
rejected = pd.read_csv(latest_dir / "rejected_signals.csv")
rejected['timestamp'] = pd.to_datetime(rejected['timestamp'])

# Analyze rejection reasons
print("\n" + "=" * 80)
print("REJECTION ANALYSIS")
print("=" * 80)

# Try to extract rejection types
rejection_summary = rejected['reason'].value_counts()
print(f"\nTotal Rejections: {len(rejected):,}")

# Check if there are "entry_timing" related rejections
entry_timing_rejections = rejected[rejected['reason'].str.contains('entry_timing|pullback|timeout', case=False, na=False)]
time_filter_rejections = rejected[rejected['reason'].str.contains('time_filter', case=False, na=False)]
other_rejections = rejected[~rejected['reason'].str.contains('entry_timing|pullback|timeout|time_filter', case=False, na=False)]

print(f"\nTime Filter Rejections: {len(time_filter_rejections):,} ({len(time_filter_rejections)/len(rejected)*100:.1f}%)")
print(f"Entry Timing/Pullback Rejections: {len(entry_timing_rejections):,} ({len(entry_timing_rejections)/len(rejected)*100:.1f}%)")
print(f"Other Rejections: {len(other_rejections):,} ({len(other_rejections)/len(rejected)*100:.1f}%)")

if len(entry_timing_rejections) > 0:
    print("\nEntry Timing Rejection Details:")
    print(entry_timing_rejections['reason'].value_counts().head(10))

# Compare with baseline (without pullback entry)
baseline_dir = Path("logs/backtest_results/EUR-USD_20251116_140938")
if baseline_dir.exists():
    with open(baseline_dir / "performance_stats.json") as f:
        baseline_stats = json.load(f)
    
    baseline_pos = pd.read_csv(baseline_dir / "positions.csv")
    
    print("\n" + "=" * 80)
    print("COMPARISON WITH BASELINE (Without Pullback Entry)")
    print("=" * 80)
    
    print(f"\n{'Metric':<30} {'Baseline':<20} {'With Pullback':<20} {'Delta':<20}")
    print("-" * 90)
    
    pnl_diff = stats['pnls']['PnL (total)'] - baseline_stats['pnls']['PnL (total)']
    print(f"{'Total PnL':<30} ${baseline_stats['pnls']['PnL (total)']:>18,.2f} ${stats['pnls']['PnL (total)']:>18,.2f} ${pnl_diff:>18,.2f}")
    
    wr_diff = (stats['pnls']['Win Rate'] - baseline_stats['pnls']['Win Rate']) * 100
    print(f"{'Win Rate':<30} {baseline_stats['pnls']['Win Rate']*100:>17.1f}% {stats['pnls']['Win Rate']*100:>17.1f}% {wr_diff:>17.1f}%")
    
    trade_diff = len(pos) - len(baseline_pos)
    print(f"{'Total Trades':<30} {len(baseline_pos):>19,} {len(pos):>19,} {trade_diff:>19,}")
    
    exp_diff = stats['pnls']['Expectancy'] - baseline_stats['pnls']['Expectancy']
    print(f"{'Expectancy':<30} ${baseline_stats['pnls']['Expectancy']:>18,.2f} ${stats['pnls']['Expectancy']:>18,.2f} ${exp_diff:>18,.2f}")
    
    print("\n" + "=" * 80)
    print("DIAGNOSIS")
    print("=" * 80)
    
    print(f"\n⚠️  CRITICAL ISSUES:")
    print(f"1. PnL decreased by ${abs(pnl_diff):,.2f} (vs baseline: ${baseline_stats['pnls']['PnL (total)']:,.2f})")
    print(f"2. Trade count increased by {trade_diff:,} trades")
    print(f"3. Win rate decreased by {wr_diff:.1f}%")
    print(f"4. Expectancy per trade: ${stats['pnls']['Expectancy']:.2f} (baseline: ${baseline_stats['pnls']['Expectancy']:.2f})")
    
    print(f"\n💡 LIKELY CAUSES:")
    print(f"   - Pullback logic is filtering OUT good trades from baseline")
    print(f"   - The strict pullback conditions (within 3 pips of fast EMA) are too restrictive")
    print(f"   - 2-minute bar timing may not align well with 15-minute signal generation")
    print(f"   - Fast EMA might not be the right level for pullback entries")
    
    print(f"\n📋 RECOMMENDATIONS:")
    print(f"   1. DISABLE pullback entry feature (STRATEGY_ENTRY_TIMING_ENABLED=false)")
    print(f"   2. Stick with immediate entry on 15-minute crossover signals")
    print(f"   3. Focus on other improvements like trailing stops or position sizing")
    print(f"   4. If implementing entry timing, consider:")
    print(f"      - Use same timeframe (15-min) instead of 2-min bars")
    print(f"      - Widen the pullback buffer (e.g., 10-15 pips instead of 3)")
    print(f"      - Use support/resistance levels instead of fast EMA")
    print(f"      - Wait for breakout instead of pullback")

else:
    print("\n⚠️  Baseline results not found. Cannot compare.")

print("\n" + "=" * 80)
