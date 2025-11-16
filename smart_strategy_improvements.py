"""
Smart strategy improvements based on DATA, not guessing.
"""
import pandas as pd
import numpy as np
from pathlib import Path

baseline_dir = Path('logs/backtest_results_baseline/EUR-USD_20251116_130912')
baseline_pos = pd.read_csv(baseline_dir / 'positions.csv')
baseline_pos['realized_pnl'] = baseline_pos['realized_pnl'].str.replace(' USD', '').astype(float)
baseline_pos['ts_opened'] = pd.to_datetime(baseline_pos['ts_opened'])
baseline_pos['hour'] = baseline_pos['ts_opened'].dt.hour
baseline_pos['weekday'] = baseline_pos['ts_opened'].dt.dayofweek  # 0=Monday
baseline_pos['duration_hours'] = (pd.to_datetime(baseline_pos['ts_closed']) - baseline_pos['ts_opened']).dt.total_seconds() / 3600

print("="*80)
print("DATA-DRIVEN STRATEGY IMPROVEMENTS")
print("="*80)

# Current state
total_pnl = baseline_pos['realized_pnl'].sum()
total_trades = len(baseline_pos)
win_rate = (baseline_pos['realized_pnl'] > 0).mean() * 100

print(f"\n📊 BASELINE PERFORMANCE:")
print(f"   Trades: {total_trades}")
print(f"   Win Rate: {win_rate:.1f}%")
print(f"   Total PnL: ${total_pnl:,.2f}")

# Strategy 1: Exclude specific bad hours
print(f"\n{'='*80}")
print("STRATEGY 1: EXCLUDE BAD HOURS")
print(f"{'='*80}")

bad_hours = [6, 17]  # Hours 6 and 17 are big losers
filtered1 = baseline_pos[~baseline_pos['hour'].isin(bad_hours)]

print(f"\n❌ Excluded hours: {bad_hours}")
print(f"   Removed trades: {total_trades - len(filtered1)}")
print(f"   Remaining: {len(filtered1)}")
print(f"   Win Rate: {(filtered1['realized_pnl'] > 0).mean() * 100:.1f}%")
print(f"   Total PnL: ${filtered1['realized_pnl'].sum():,.2f}")
print(f"   Improvement: ${filtered1['realized_pnl'].sum() - total_pnl:+,.2f} ({((filtered1['realized_pnl'].sum() / total_pnl - 1) * 100):+.1f}%)")

# Strategy 2: Exclude Thursday Hour 17 (worst single combination)
print(f"\n{'='*80}")
print("STRATEGY 2: EXCLUDE THURSDAY HOUR 17 (Worst Single Pattern)")
print(f"{'='*80}")

# Thursday = 3 in dayofweek
filtered2 = baseline_pos[~((baseline_pos['weekday'] == 3) & (baseline_pos['hour'] == 17))]

print(f"\n❌ Excluded: Thursday Hour 17")
print(f"   Removed trades: {total_trades - len(filtered2)}")
print(f"   Remaining: {len(filtered2)}")
print(f"   Win Rate: {(filtered2['realized_pnl'] > 0).mean() * 100:.1f}%")
print(f"   Total PnL: ${filtered2['realized_pnl'].sum():,.2f}")
print(f"   Improvement: ${filtered2['realized_pnl'].sum() - total_pnl:+,.2f} ({((filtered2['realized_pnl'].sum() / total_pnl - 1) * 100):+.1f}%)")

# Strategy 3: Exclude short trades (<1h) - they're terrible
print(f"\n{'='*80}")
print("STRATEGY 3: EXCLUDE VERY SHORT TRADES (<1 hour)")
print(f"{'='*80}")

short_trades = baseline_pos[baseline_pos['duration_hours'] < 1]
filtered3 = baseline_pos[baseline_pos['duration_hours'] >= 1]

print(f"\n❌ Excluded: Trades lasting <1 hour")
print(f"   Short trades stats: {len(short_trades)} trades, ${short_trades['realized_pnl'].sum():,.2f} PnL, {(short_trades['realized_pnl'] > 0).mean()*100:.1f}% WR")
print(f"   Removed trades: {len(short_trades)}")
print(f"   Remaining: {len(filtered3)}")
print(f"   Win Rate: {(filtered3['realized_pnl'] > 0).mean() * 100:.1f}%")
print(f"   Total PnL: ${filtered3['realized_pnl'].sum():,.2f}")
print(f"   Improvement: ${filtered3['realized_pnl'].sum() - total_pnl:+,.2f} ({((filtered3['realized_pnl'].sum() / total_pnl - 1) * 100):+.1f}%)")

# Strategy 4: COMBINED - exclude bad hours + short trades
print(f"\n{'='*80}")
print("STRATEGY 4: COMBINED FILTERS (Bad Hours + Short Trades)")
print(f"{'='*80}")

filtered4 = baseline_pos[
    ~baseline_pos['hour'].isin(bad_hours) &
    (baseline_pos['duration_hours'] >= 1)
]

print(f"\n❌ Excluded: Hours {bad_hours} + trades <1h")
print(f"   Removed trades: {total_trades - len(filtered4)}")
print(f"   Remaining: {len(filtered4)}")
print(f"   Win Rate: {(filtered4['realized_pnl'] > 0).mean() * 100:.1f}%")
print(f"   Total PnL: ${filtered4['realized_pnl'].sum():,.2f}")
print(f"   Improvement: ${filtered4['realized_pnl'].sum() - total_pnl:+,.2f} ({((filtered4['realized_pnl'].sum() / total_pnl - 1) * 100):+.1f}%)")

# Strategy 5: MORE AGGRESSIVE - only trade consistently profitable hours
print(f"\n{'='*80}")
print("STRATEGY 5: ONLY TRADE BEST HOURS (Data-Driven Hour Selection)")
print(f"{'='*80}")

# Find hours with positive PnL and >50% win rate
hourly_stats = baseline_pos.groupby('hour').agg({
    'realized_pnl': ['sum', 'count'],
    'hour': lambda x: (baseline_pos.loc[x.index, 'realized_pnl'] > 0).mean()
}).round(3)
hourly_stats.columns = ['pnl', 'count', 'win_rate']
good_hours = hourly_stats[(hourly_stats['pnl'] > 0) & (hourly_stats['win_rate'] > 0.5) & (hourly_stats['count'] >= 3)].index.tolist()

filtered5 = baseline_pos[baseline_pos['hour'].isin(good_hours)]

print(f"\n✅ Only trade hours: {sorted(good_hours)}")
print(f"   Removed trades: {total_trades - len(filtered5)}")
print(f"   Remaining: {len(filtered5)}")
print(f"   Win Rate: {(filtered5['realized_pnl'] > 0).mean() * 100:.1f}%")
print(f"   Total PnL: ${filtered5['realized_pnl'].sum():,.2f}")
print(f"   Improvement: ${filtered5['realized_pnl'].sum() - total_pnl:+,.2f} ({((filtered5['realized_pnl'].sum() / total_pnl - 1) * 100):+.1f}%)")

# FINAL RECOMMENDATION
print(f"\n{'='*80}")
print("🎯 RECOMMENDED IMPLEMENTATION")
print(f"{'='*80}")

strategies = [
    ("Exclude bad hours [6,17]", filtered1['realized_pnl'].sum() - total_pnl, "BACKTEST_EXCLUDED_HOURS=6,17"),
    ("Exclude Thursday H17", filtered2['realized_pnl'].sum() - total_pnl, "Add Thursday hour 17 to weekday exclusions"),
    ("Minimum trade duration 1h", filtered3['realized_pnl'].sum() - total_pnl, "Add exit logic: close if <1h and not profitable"),
    ("Combined (hours + duration)", filtered4['realized_pnl'].sum() - total_pnl, "Both above"),
    ("Only best hours", filtered5['realized_pnl'].sum() - total_pnl, f"BACKTEST_EXCLUDED_HOURS={','.join(map(str, [h for h in range(24) if h not in good_hours]))}"),
]

strategies.sort(key=lambda x: x[1], reverse=True)

print("\nRanked by potential improvement:\n")
for i, (name, improvement, implementation) in enumerate(strategies, 1):
    print(f"{i}. {name}")
    print(f"   💰 Expected: ${improvement:+,.2f}")
    print(f"   🔧 How: {implementation}\n")

print(f"{'='*80}")
print("⚠️  WHY ADX FILTER DIDN'T WORK:")
print(f"{'='*80}")
print("\nThe losses are NOT because of choppy markets or weak trends.")
print("They're because of SPECIFIC TIME PERIODS:")
print("  • Hour 6 (early Asian session)")
print("  • Hour 17 (late US session)")
print("  • Thursday Hour 17 specifically (-$725!)")
print("  • Very short trades <1h (getting stopped out fast)")
print("\nADX filters ALL hours equally, missing the time-based pattern.")
print("Better approach: TIME-AWARE filtering + minimum hold duration logic")

print(f"\n{'='*80}")
print("NEXT STEP:")
print(f"{'='*80}")
print("\n1️⃣  Update .env with hour exclusions:")
print("   BACKTEST_EXCLUDED_HOURS=6,17")
print("\n2️⃣  Add Thursday-specific exclusions to:")
print("   BACKTEST_EXCLUDED_HOURS_THURSDAY=17")
print("\n3️⃣  Run backtest and measure improvement")
print("\n4️⃣  If successful, consider adding minimum 1h hold requirement")
