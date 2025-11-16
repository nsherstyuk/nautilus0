"""
Analyze regime detection optimization results.
"""
import pandas as pd
import json
from pathlib import Path

# Load CSV results
csv_file = Path("optimization/results/regime_detection_focused_results.csv")
if not csv_file.exists():
    print(f"ERROR: Results file not found: {csv_file}")
    exit(1)

df = pd.read_csv(csv_file)

print("=" * 80)
print("REGIME DETECTION OPTIMIZATION RESULTS ANALYSIS")
print("=" * 80)

print(f"\nTotal Runs: {len(df)}")
print(f"Completed: {len(df[df['status'] == 'completed'])}")
print(f"Failed: {len(df[df['status'] == 'failed'])}")

# Filter completed runs
completed = df[df['status'] == 'completed'].copy()

if len(completed) == 0:
    print("\nNo completed runs to analyze!")
    exit(1)

print(f"\nCompleted Runs: {len(completed)}")

# Summary statistics
print("\n" + "=" * 80)
print("SUMMARY STATISTICS")
print("=" * 80)
print(f"Average PnL: ${completed['total_pnl'].mean():,.2f}")
print(f"Best PnL: ${completed['total_pnl'].max():,.2f}")
print(f"Worst PnL: ${completed['total_pnl'].min():,.2f}")
print(f"\nAverage Sharpe Ratio: {completed['sharpe_ratio'].mean():.4f}")
print(f"Best Sharpe Ratio: {completed['sharpe_ratio'].max():.4f}")
print(f"Worst Sharpe Ratio: {completed['sharpe_ratio'].min():.4f}")
print(f"\nAverage Win Rate: {completed['win_rate'].mean():.2%}")
print(f"Average Trade Count: {completed['trade_count'].mean():.0f}")

# Top 10 by Sharpe Ratio
print("\n" + "=" * 80)
print("TOP 10 BY SHARPE RATIO")
print("=" * 80)
top_sharpe = completed.nlargest(10, 'sharpe_ratio')
display_cols = ['run_id', 'regime_adx_trending_threshold', 'regime_adx_ranging_threshold',
                'regime_tp_multiplier_trending', 'regime_tp_multiplier_ranging',
                'total_pnl', 'sharpe_ratio', 'win_rate', 'trade_count']
print(top_sharpe[display_cols].to_string(index=False))

# Top 10 by Total PnL
print("\n" + "=" * 80)
print("TOP 10 BY TOTAL PNL")
print("=" * 80)
top_pnl = completed.nlargest(10, 'total_pnl')
print(top_pnl[display_cols].to_string(index=False))

# Check if any results beat baseline
baseline_pnl = 14203.91  # From 14k optimization
baseline_sharpe = 0.453

print("\n" + "=" * 80)
print("COMPARISON TO BASELINE (14k PnL Configuration)")
print("=" * 80)
print(f"Baseline PnL: ${baseline_pnl:,.2f}")
print(f"Baseline Sharpe: {baseline_sharpe:.3f}")

better_pnl = completed[completed['total_pnl'] > baseline_pnl]
better_sharpe = completed[completed['sharpe_ratio'] > baseline_sharpe]

print(f"\nRuns with BETTER PnL than baseline: {len(better_pnl)}")
print(f"Runs with BETTER Sharpe than baseline: {len(better_sharpe)}")

if len(better_pnl) > 0:
    print("\nBest PnL improvement:")
    best = better_pnl.nlargest(1, 'total_pnl').iloc[0]
    print(f"  Run ID: {best['run_id']}")
    print(f"  PnL: ${best['total_pnl']:,.2f} (${best['total_pnl'] - baseline_pnl:+,.2f} vs baseline)")
    print(f"  Sharpe: {best['sharpe_ratio']:.3f}")
    print(f"  ADX Trending: {best['regime_adx_trending_threshold']}")
    print(f"  ADX Ranging: {best['regime_adx_ranging_threshold']}")
    print(f"  TP Trending Mult: {best['regime_tp_multiplier_trending']}")
    print(f"  TP Ranging Mult: {best['regime_tp_multiplier_ranging']}")

if len(better_sharpe) > 0:
    print("\nBest Sharpe improvement:")
    best = better_sharpe.nlargest(1, 'sharpe_ratio').iloc[0]
    print(f"  Run ID: {best['run_id']}")
    print(f"  Sharpe: {best['sharpe_ratio']:.3f} ({best['sharpe_ratio'] - baseline_sharpe:+.3f} vs baseline)")
    print(f"  PnL: ${best['total_pnl']:,.2f}")
    print(f"  ADX Trending: {best['regime_adx_trending_threshold']}")
    print(f"  ADX Ranging: {best['regime_adx_ranging_threshold']}")
    print(f"  TP Trending Mult: {best['regime_tp_multiplier_trending']}")
    print(f"  TP Ranging Mult: {best['regime_tp_multiplier_ranging']}")

if len(better_pnl) == 0 and len(better_sharpe) == 0:
    print("\n" + "!" * 80)
    print("WARNING: NO RUNS BEAT BASELINE!")
    print("!" * 80)
    print("\nThis suggests regime detection is NOT improving performance.")
    print("Possible reasons:")
    print("  1. Regime detection parameters need different ranges")
    print("  2. Regime detection concept doesn't work for this strategy")
    print("  3. Date range/data differences affecting results")
    print("  4. Need to test different base TP/SL values")

# Parameter analysis
print("\n" + "=" * 80)
print("PARAMETER PATTERNS")
print("=" * 80)

# Group by ADX thresholds
print("\nPerformance by ADX Trending Threshold:")
for threshold in sorted(completed['regime_adx_trending_threshold'].unique()):
    subset = completed[completed['regime_adx_trending_threshold'] == threshold]
    print(f"  {threshold:.1f}: Avg PnL=${subset['total_pnl'].mean():,.2f}, "
          f"Avg Sharpe={subset['sharpe_ratio'].mean():.4f}, "
          f"Count={len(subset)}")

print("\nPerformance by ADX Ranging Threshold:")
for threshold in sorted(completed['regime_adx_ranging_threshold'].unique()):
    subset = completed[completed['regime_adx_ranging_threshold'] == threshold]
    print(f"  {threshold:.1f}: Avg PnL=${subset['total_pnl'].mean():,.2f}, "
          f"Avg Sharpe={subset['sharpe_ratio'].mean():.4f}, "
          f"Count={len(subset)}")

print("\nPerformance by TP Trending Multiplier:")
for mult in sorted(completed['regime_tp_multiplier_trending'].unique()):
    subset = completed[completed['regime_tp_multiplier_trending'] == mult]
    print(f"  {mult:.2f}: Avg PnL=${subset['total_pnl'].mean():,.2f}, "
          f"Avg Sharpe={subset['sharpe_ratio'].mean():.4f}, "
          f"Count={len(subset)}")

print("\nPerformance by TP Ranging Multiplier:")
for mult in sorted(completed['regime_tp_multiplier_ranging'].unique()):
    subset = completed[completed['regime_tp_multiplier_ranging'] == mult]
    print(f"  {mult:.2f}: Avg PnL=${subset['total_pnl'].mean():,.2f}, "
          f"Avg Sharpe={subset['sharpe_ratio'].mean():.4f}, "
          f"Count={len(subset)}")

print("\n" + "=" * 80)

