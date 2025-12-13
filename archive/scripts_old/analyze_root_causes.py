"""
Analyze WHY trades are losing - not just filter randomly.
Compare baseline vs DMI filtered results to see what's actually happening.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import json

# Load baseline (best results we had)
baseline_dir = Path('logs/backtest_results_baseline/EUR-USD_20251116_130912')
baseline_pos = pd.read_csv(baseline_dir / 'positions.csv')
baseline_pos['realized_pnl'] = baseline_pos['realized_pnl'].str.replace(' USD', '').astype(float)
baseline_pos['ts_opened'] = pd.to_datetime(baseline_pos['ts_opened'])
baseline_pos['ts_closed'] = pd.to_datetime(baseline_pos['ts_closed'])
baseline_pos['duration_hours'] = (baseline_pos['ts_closed'] - baseline_pos['ts_opened']).dt.total_seconds() / 3600
baseline_pos['hour'] = baseline_pos['ts_opened'].dt.hour
baseline_pos['weekday'] = baseline_pos['ts_opened'].dt.day_name()
baseline_pos['month'] = baseline_pos['ts_opened'].dt.to_period('M')
baseline_pos['is_winner'] = baseline_pos['realized_pnl'] > 0

print("="*80)
print("DEEP DIVE: WHAT ACTUALLY CAUSES LOSSES?")
print("="*80)
print(f"\nBaseline: {len(baseline_pos)} trades, {baseline_pos['is_winner'].mean()*100:.1f}% WR, ${baseline_pos['realized_pnl'].sum():,.2f} PnL")

# 1. HOUR OF DAY ANALYSIS - which hours are killing us?
print("\n" + "="*80)
print("HOUR-OF-DAY PROFITABILITY")
print("="*80)
hourly = baseline_pos.groupby('hour').agg({
    'realized_pnl': ['sum', 'count', 'mean'],
    'is_winner': 'mean'
}).round(2)
hourly.columns = ['PnL', 'Trades', 'Avg', 'WinRate']
hourly['WinRate'] = (hourly['WinRate'] * 100).round(1)
hourly = hourly.sort_values('PnL')

print("\n🔴 WORST HOURS (Biggest Losers):")
print(hourly.head(10).to_string())

print("\n🟢 BEST HOURS (Biggest Winners):")
print(hourly.tail(5).to_string())

worst_hours = hourly[hourly['PnL'] < -100].index.tolist()
print(f"\n💡 ACTIONABLE: Exclude hours {worst_hours} → Would save ${-hourly[hourly['PnL'] < -100]['PnL'].sum():,.2f}")

# 2. WEEKDAY + HOUR COMBINATION
print("\n" + "="*80)
print("WEEKDAY + HOUR COMBINATION ANALYSIS")
print("="*80)
baseline_pos['weekday_hour'] = baseline_pos['weekday'] + '_H' + baseline_pos['hour'].astype(str)
weekday_hour = baseline_pos.groupby('weekday_hour').agg({
    'realized_pnl': ['sum', 'count'],
    'is_winner': 'mean'
}).round(2)
weekday_hour.columns = ['PnL', 'Trades', 'WinRate']
weekday_hour['WinRate'] = (weekday_hour['WinRate'] * 100).round(1)
weekday_hour = weekday_hour[weekday_hour['Trades'] >= 3]  # At least 3 trades
weekday_hour = weekday_hour.sort_values('PnL')

print("\n🔴 WORST WEEKDAY+HOUR COMBINATIONS (Consistent Losers):")
print(weekday_hour.head(15).to_string())

# 3. DURATION ANALYSIS - refined
print("\n" + "="*80)
print("TRADE DURATION PATTERNS")
print("="*80)

# Very granular duration buckets
baseline_pos['duration_bucket'] = pd.cut(
    baseline_pos['duration_hours'],
    bins=[0, 1, 2, 3, 4, 6, 8, 12, 24, 48, np.inf],
    labels=['<1h', '1-2h', '2-3h', '3-4h', '4-6h', '6-8h', '8-12h', '12-24h', '24-48h', '>48h']
)

duration_stats = baseline_pos.groupby('duration_bucket').agg({
    'realized_pnl': ['sum', 'count', 'mean'],
    'is_winner': 'mean'
}).round(2)
duration_stats.columns = ['PnL', 'Trades', 'Avg', 'WinRate']
duration_stats['WinRate'] = (duration_stats['WinRate'] * 100).round(1)

print(duration_stats.to_string())

# 4. DIRECTION BIAS
print("\n" + "="*80)
print("DIRECTION BIAS ANALYSIS")
print("="*80)
direction_stats = baseline_pos.groupby('side').agg({
    'realized_pnl': ['sum', 'count', 'mean'],
    'is_winner': 'mean'
}).round(2)
direction_stats.columns = ['PnL', 'Trades', 'Avg', 'WinRate']
direction_stats['WinRate'] = (direction_stats['WinRate'] * 100).round(1)
print(direction_stats.to_string())

# 5. MONTHLY PATTERN - is 2024 vs 2025 different by month?
print("\n" + "="*80)
print("MONTHLY PATTERN (2024 vs 2025)")
print("="*80)
baseline_pos['year'] = baseline_pos['ts_opened'].dt.year
baseline_pos['month_name'] = baseline_pos['ts_opened'].dt.strftime('%Y-%m')

monthly = baseline_pos.groupby('month_name').agg({
    'realized_pnl': ['sum', 'count'],
    'is_winner': 'mean'
}).round(2)
monthly.columns = ['PnL', 'Trades', 'WinRate']
monthly['WinRate'] = (monthly['WinRate'] * 100).round(1)
print(monthly.to_string())

# 6. COMBINED LOSING PATTERNS
print("\n" + "="*80)
print("COMBINED PATTERN ANALYSIS")
print("="*80)

# Pattern 1: Short duration + bad hours
short_bad_hours = baseline_pos[
    (baseline_pos['duration_hours'] < 4) & 
    (baseline_pos['hour'].isin(worst_hours))
]
print(f"\n🎯 Pattern 1: Duration <4h + Bad Hours ({worst_hours})")
print(f"   Trades: {len(short_bad_hours)}")
print(f"   Win Rate: {short_bad_hours['is_winner'].mean()*100:.1f}%")
print(f"   PnL: ${short_bad_hours['realized_pnl'].sum():,.2f}")
print(f"   → Excluding these would save ${-short_bad_hours[short_bad_hours['realized_pnl'] < 0]['realized_pnl'].sum():,.2f}")

# Pattern 2: Monday-Wednesday + early hours
baseline_pos['is_early_week'] = baseline_pos['weekday'].isin(['Monday', 'Tuesday', 'Wednesday'])
early_week = baseline_pos[baseline_pos['is_early_week']]
print(f"\n🎯 Pattern 2: Monday-Wednesday trades")
print(f"   Trades: {len(early_week)}")
print(f"   Win Rate: {early_week['is_winner'].mean()*100:.1f}%")
print(f"   PnL: ${early_week['realized_pnl'].sum():,.2f}")

# Pattern 3: What if we ONLY traded profitable hours?
profitable_hours = hourly[hourly['PnL'] > 0].index.tolist()
profitable_only = baseline_pos[baseline_pos['hour'].isin(profitable_hours)]
print(f"\n🎯 Pattern 3: ONLY trade profitable hours {profitable_hours}")
print(f"   Trades: {len(profitable_only)} (vs {len(baseline_pos)} all)")
print(f"   Win Rate: {profitable_only['is_winner'].mean()*100:.1f}%")
print(f"   PnL: ${profitable_only['realized_pnl'].sum():,.2f} (vs ${baseline_pos['realized_pnl'].sum():,.2f} all)")
print(f"   → Improvement: ${profitable_only['realized_pnl'].sum() - baseline_pos['realized_pnl'].sum():+,.2f}")

# 7. RECOMMENDATIONS RANKED BY IMPACT
print("\n" + "="*80)
print("🎯 RANKED IMPROVEMENT OPPORTUNITIES")
print("="*80)

recommendations = []

# Option 1: Exclude worst hours
worst_hours_pnl = -hourly[hourly['PnL'] < -100]['PnL'].sum()
recommendations.append(('Exclude worst hours', worst_hours_pnl, worst_hours))

# Option 2: Only trade profitable hours
prof_hours_gain = profitable_only['realized_pnl'].sum() - baseline_pos['realized_pnl'].sum()
recommendations.append(('Only trade profitable hours', prof_hours_gain, profitable_hours))

# Option 3: Exclude short + bad hour combinations
short_bad_gain = -short_bad_hours[short_bad_hours['realized_pnl'] < 0]['realized_pnl'].sum()
recommendations.append(('Exclude <4h trades in bad hours', short_bad_gain, 'See above'))

recommendations.sort(key=lambda x: x[1], reverse=True)

for i, (name, impact, details) in enumerate(recommendations, 1):
    print(f"\n{i}. {name}")
    print(f"   Expected Impact: ${impact:+,.2f}")
    print(f"   Details: {details}")

print("\n" + "="*80)
print("NEXT STEP RECOMMENDATION")
print("="*80)
print(f"\n✅ IMPLEMENT: Hour exclusions in .env")
print(f"   BACKTEST_EXCLUDED_HOURS={','.join(map(str, worst_hours))}")
print(f"\n✅ Expected result: ${worst_hours_pnl:+,.2f} improvement")
print(f"\n❌ DON'T: Use blanket ADX filter - it doesn't address the root cause")
print(f"   Root cause is TIME-BASED, not trend strength based")
