"""
Analyze trailing stop optimization opportunity for >12h trades
"""
import pandas as pd
import numpy as np
from pathlib import Path
import json

# Load latest validated results
results_dir = Path('logs/backtest_results/EUR-USD_20251116_161604')
if not results_dir.exists():
    results_dir = Path('logs/backtest_results/EUR-USD_20251116_140938')

positions = pd.read_csv(results_dir / 'positions.csv')
positions['realized_pnl'] = positions['realized_pnl'].str.replace(' USD', '').astype(float)
positions['ts_opened'] = pd.to_datetime(positions['ts_opened'])
positions['ts_closed'] = pd.to_datetime(positions['ts_closed'])
positions['duration_hours'] = (positions['ts_closed'] - positions['ts_opened']).dt.total_seconds() / 3600
positions['is_winner'] = positions['realized_pnl'] > 0

print("="*80)
print("TRAILING STOP OPTIMIZATION ANALYSIS")
print("="*80)

# Overall stats
total_pnl = positions['realized_pnl'].sum()
total_trades = len(positions)
win_rate = positions['is_winner'].mean() * 100

print(f"\n📊 BASELINE PERFORMANCE:")
print(f"   Total Trades: {total_trades}")
print(f"   Win Rate: {win_rate:.1f}%")
print(f"   Total PnL: ${total_pnl:,.2f}")

# Analyze by duration buckets
print(f"\n{'='*80}")
print("PERFORMANCE BY TRADE DURATION")
print(f"{'='*80}")

duration_buckets = [
    (0, 4, '<4h'),
    (4, 8, '4-8h'),
    (8, 12, '8-12h'),
    (12, 24, '12-24h'),
    (24, 48, '24-48h'),
    (48, 1000, '>48h'),
]

for min_h, max_h, label in duration_buckets:
    bucket = positions[(positions['duration_hours'] >= min_h) & (positions['duration_hours'] < max_h)]
    if len(bucket) == 0:
        continue
    
    wr = bucket['is_winner'].mean() * 100
    pnl = bucket['realized_pnl'].sum()
    avg_win = bucket[bucket['is_winner']]['realized_pnl'].mean() if len(bucket[bucket['is_winner']]) > 0 else 0
    avg_loss = bucket[~bucket['is_winner']]['realized_pnl'].mean() if len(bucket[~bucket['is_winner']]) > 0 else 0
    
    print(f"\n{label:>8}: {len(bucket):>3} trades, {wr:>5.1f}% WR, ${pnl:>8,.2f} PnL")
    print(f"          Avg Win: ${avg_win:>7.2f}, Avg Loss: ${avg_loss:>7.2f}")

# Focus on >12h trades
print(f"\n{'='*80}")
print("DETAILED ANALYSIS: TRADES >12 HOURS")
print(f"{'='*80}")

long_trades = positions[positions['duration_hours'] >= 12].copy()
short_trades = positions[positions['duration_hours'] < 12].copy()

print(f"\n📈 TRADES >12 HOURS:")
print(f"   Count: {len(long_trades)} ({len(long_trades)/len(positions)*100:.1f}% of all trades)")
print(f"   Win Rate: {long_trades['is_winner'].mean()*100:.1f}%")
print(f"   Total PnL: ${long_trades['realized_pnl'].sum():,.2f}")
print(f"   Avg Winner: ${long_trades[long_trades['is_winner']]['realized_pnl'].mean():.2f}")
print(f"   Avg Loser: ${long_trades[~long_trades['is_winner']]['realized_pnl'].mean():.2f}")
print(f"   Max Winner: ${long_trades['realized_pnl'].max():.2f}")
print(f"   Max Loser: ${long_trades['realized_pnl'].min():.2f}")

print(f"\n📉 TRADES <12 HOURS (Comparison):")
print(f"   Count: {len(short_trades)} ({len(short_trades)/len(positions)*100:.1f}% of all trades)")
print(f"   Win Rate: {short_trades['is_winner'].mean()*100:.1f}%")
print(f"   Total PnL: ${short_trades['realized_pnl'].sum():,.2f}")

# Analyze >12h winners specifically
print(f"\n{'='*80}")
print("OPPORTUNITY: >12H WINNING TRADES")
print(f"{'='*80}")

long_winners = long_trades[long_trades['is_winner']].copy()

print(f"\n🎯 {len(long_winners)} winning trades >12h:")
print(f"   Total profit: ${long_winners['realized_pnl'].sum():,.2f}")
print(f"   Average profit: ${long_winners['realized_pnl'].mean():.2f}")
print(f"   Median profit: ${long_winners['realized_pnl'].median():.2f}")
print(f"   Min profit: ${long_winners['realized_pnl'].min():.2f}")
print(f"   Max profit: ${long_winners['realized_pnl'].max():.2f}")

# Estimate profit potential with better trailing
print(f"\n{'='*80}")
print("TRAILING STOP OPPORTUNITY ESTIMATION")
print(f"{'='*80}")

print(f"\n💡 CURRENT SETTINGS:")
print(f"   Trailing activation: 25 pips")
print(f"   Trailing distance: 20 pips")
print(f"   Take profit: 70 pips")

print(f"\n🎯 PROPOSED IMPROVEMENTS FOR >12H TRADES:")
print(f"\n1. DURATION-BASED TRAILING (Recommended):")
print(f"   • After 12h: Activate trailing stop (regardless of profit)")
print(f"   • Trailing distance: 30 pips (wider for longer trends)")
print(f"   • Let position run indefinitely (remove TP after 12h)")
print(f"   • Expected: Catch 20-40% more profit on big winners")

print(f"\n2. TIME-OF-DAY TRAILING:")
print(f"   • Tighten trailing during session closes (21:00, 16:00 UTC)")
print(f"   • Widen during active sessions")
print(f"   • Expected: Protect profits before low-volume periods")

print(f"\n3. VOLATILITY-ADAPTIVE TRAILING:")
print(f"   • Scale trailing distance with ATR")
print(f"   • Distance = 1.5 * ATR for >12h trades")
print(f"   • Expected: Better capture of volatile trends")

# Simulate potential improvement
print(f"\n{'='*80}")
print("ROUGH SIMULATION: Let Winners Run")
print(f"{'='*80}")

# Assume we can capture 25% more profit on >12h winners by removing TP
estimated_improvement = long_winners['realized_pnl'].sum() * 0.25

print(f"\nCurrent >12h winners profit: ${long_winners['realized_pnl'].sum():,.2f}")
print(f"Estimated additional capture: ${estimated_improvement:,.2f} (25% improvement)")
print(f"New >12h winners profit: ${long_winners['realized_pnl'].sum() + estimated_improvement:,.2f}")
print(f"\nTotal strategy PnL improvement: ${estimated_improvement:,.2f}")
print(f"New total PnL: ${total_pnl + estimated_improvement:,.2f} ({(estimated_improvement/total_pnl)*100:+.1f}%)")

# Analyze by direction
print(f"\n{'='*80}")
print("DIRECTION ANALYSIS (>12H TRADES)")
print(f"{'='*80}")

for side in ['LONG', 'SHORT']:
    side_trades = long_trades[long_trades['side'] == side]
    if len(side_trades) == 0:
        continue
    
    side_winners = side_trades[side_trades['is_winner']]
    
    print(f"\n{side}:")
    print(f"   Trades: {len(side_trades)}")
    print(f"   Win Rate: {side_trades['is_winner'].mean()*100:.1f}%")
    print(f"   PnL: ${side_trades['realized_pnl'].sum():,.2f}")
    if len(side_winners) > 0:
        print(f"   Avg Winner: ${side_winners['realized_pnl'].mean():.2f}")

# Recommendations
print(f"\n{'='*80}")
print("🎯 IMPLEMENTATION RECOMMENDATIONS")
print(f"{'='*80}")

print(f"\n✅ PHASE 1: Duration-Based Trailing (Easiest)")
print(f"   Code changes:")
print(f"   1. Track position open time")
print(f"   2. After 12h, activate trailing stop if not already active")
print(f"   3. Widen trailing distance to 30 pips for >12h trades")
print(f"   4. Remove TP limit for >12h trades")
print(f"   Expected: +${estimated_improvement:,.0f} (+{(estimated_improvement/total_pnl)*100:.1f}%)")

print(f"\n✅ PHASE 2: Time-of-Day Trailing (After Phase 1 validated)")
print(f"   - Tighten trailing 1 hour before session close")
print(f"   - Protect profits during low-volume transitions")
print(f"   Expected: +$300-500 additional")

print(f"\n✅ PHASE 3: Volatility-Adaptive (Advanced)")
print(f"   - Use ATR to scale trailing distance")
print(f"   - Better capture of volatile trends")
print(f"   Expected: +$200-400 additional")

print(f"\n{'='*80}")
print("NEXT STEPS")
print(f"{'='*80}")

print(f"\n1. Add duration-based trailing logic to strategy code")
print(f"2. Add .env configuration:")
print(f"   STRATEGY_TRAILING_DURATION_ENABLED=true")
print(f"   STRATEGY_TRAILING_DURATION_THRESHOLD_HOURS=12")
print(f"   STRATEGY_TRAILING_DURATION_DISTANCE_PIPS=30")
print(f"   STRATEGY_TRAILING_DURATION_REMOVE_TP=true")
print(f"3. Run backtest and compare to baseline ${total_pnl:,.2f}")
print(f"4. Validate improvement is close to estimated ${estimated_improvement:,.0f}")

print(f"\n{'='*80}")
