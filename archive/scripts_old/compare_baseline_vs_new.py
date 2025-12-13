"""
Compare baseline vs new results with time-based exclusions
"""
import pandas as pd
import json
from pathlib import Path

# Baseline (without hour 6/17 exclusions)
baseline_dir = Path('logs/backtest_results_baseline/EUR-USD_20251116_130912')
baseline_stats = json.load(open(baseline_dir / 'performance_stats.json'))
baseline_pos = pd.read_csv(baseline_dir / 'positions.csv')
baseline_pos['realized_pnl'] = baseline_pos['realized_pnl'].str.replace(' USD', '').astype(float)
baseline_pos['ts_opened'] = pd.to_datetime(baseline_pos['ts_opened'])
baseline_pos['hour'] = baseline_pos['ts_opened'].dt.hour
baseline_pos['weekday'] = baseline_pos['ts_opened'].dt.day_name()

# New results (with hour 6/17 exclusions)
new_dir = Path('logs/backtest_results/EUR-USD_20251116_140938')
new_stats = json.load(open(new_dir / 'performance_stats.json'))
new_pos = pd.read_csv(new_dir / 'positions.csv')
new_pos['realized_pnl'] = new_pos['realized_pnl'].str.replace(' USD', '').astype(float)
new_pos['ts_opened'] = pd.to_datetime(new_pos['ts_opened'])
new_pos['hour'] = new_pos['ts_opened'].dt.hour
new_pos['weekday'] = new_pos['ts_opened'].dt.day_name()

print("="*80)
print("BASELINE vs NEW RESULTS (Time-Based Exclusions)")
print("="*80)

# Performance metrics
b_pnl = baseline_stats['pnls']['PnL (total)']
n_pnl = new_stats['pnls']['PnL (total)']
b_wr = baseline_stats['pnls']['Win Rate'] * 100
n_wr = new_stats['pnls']['Win Rate'] * 100
b_exp = baseline_stats['pnls']['Expectancy']
n_exp = new_stats['pnls']['Expectancy']
b_avg_win = baseline_stats['pnls']['Avg Winner']
n_avg_win = new_stats['pnls']['Avg Winner']
b_avg_loss = baseline_stats['pnls']['Avg Loser']
n_avg_loss = new_stats['pnls']['Avg Loser']

print(f"\n{'Metric':<25} {'BASELINE':<18} {'NEW':<18} {'CHANGE':<15}")
print("-"*76)

metrics = [
    ('Total PnL', f'${b_pnl:,.2f}', f'${n_pnl:,.2f}', f'${n_pnl-b_pnl:+,.2f}'),
    ('Total Trades', f'{len(baseline_pos)}', f'{len(new_pos)}', f'{len(new_pos)-len(baseline_pos):+d}'),
    ('Win Rate', f'{b_wr:.1f}%', f'{n_wr:.1f}%', f'{n_wr-b_wr:+.1f}%'),
    ('Expectancy', f'${b_exp:.2f}', f'${n_exp:.2f}', f'${n_exp-b_exp:+.2f}'),
    ('Avg Winner', f'${b_avg_win:.2f}', f'${n_avg_win:.2f}', f'${n_avg_win-b_avg_win:+.2f}'),
    ('Avg Loser', f'${b_avg_loss:.2f}', f'${n_avg_loss:.2f}', f'${n_avg_loss-b_avg_loss:+.2f}'),
]

for name, base, new, change in metrics:
    print(f"{name:<25} {base:<18} {new:<18} {change:<15}")

# Calculate improvement
pnl_change = n_pnl - b_pnl
pnl_pct = (pnl_change / b_pnl) * 100

print("\n" + "="*80)
print("SUMMARY")
print("="*80)

if pnl_change > 0:
    print(f"\n✅ IMPROVEMENT: ${pnl_change:+,.2f} ({pnl_pct:+.1f}%)")
else:
    print(f"\n❌ DECREASE: ${pnl_change:+,.2f} ({pnl_pct:+.1f}%)")

print(f"\n📊 Trade Reduction: {len(baseline_pos) - len(new_pos)} trades removed")
print(f"   ({(len(new_pos)/len(baseline_pos)-1)*100:+.1f}% trade count)")

# Verify which hours were actually excluded
print("\n" + "="*80)
print("VERIFICATION: Which hours were removed?")
print("="*80)

baseline_hours = baseline_pos['hour'].value_counts().sort_index()
new_hours = new_pos['hour'].value_counts().sort_index()

all_hours = sorted(set(baseline_hours.index) | set(new_hours.index))
print(f"\n{'Hour':<6} {'Baseline':<12} {'New':<12} {'Removed':<10}")
print("-"*40)

for hour in all_hours:
    b_count = baseline_hours.get(hour, 0)
    n_count = new_hours.get(hour, 0)
    removed = b_count - n_count
    if removed > 0:
        print(f"{hour:<6} {b_count:<12} {n_count:<12} {removed:<10} ⚠️")
    else:
        print(f"{hour:<6} {b_count:<12} {n_count:<12} {'-':<10}")

# Check Thursday Hour 17 specifically
print("\n" + "="*80)
print("CRITICAL CHECK: Thursday Hour 17")
print("="*80)

baseline_thu17 = baseline_pos[(baseline_pos['weekday'] == 'Thursday') & (baseline_pos['hour'] == 17)]
new_thu17 = new_pos[(new_pos['weekday'] == 'Thursday') & (new_pos['hour'] == 17)]

print(f"\nBaseline Thursday H17: {len(baseline_thu17)} trades, ${baseline_thu17['realized_pnl'].sum():,.2f} PnL")
print(f"New Thursday H17: {len(new_thu17)} trades, ${new_thu17['realized_pnl'].sum():,.2f} PnL")

if len(new_thu17) == 0 and len(baseline_thu17) > 0:
    print(f"✅ SUCCESS: Thursday H17 excluded! Saved ${-baseline_thu17['realized_pnl'].sum():,.2f}")
elif len(new_thu17) < len(baseline_thu17):
    print(f"⚠️  PARTIAL: Some Thursday H17 trades still present")
else:
    print(f"❌ FAILED: Thursday H17 NOT excluded")

# Check hours 6 and 17 overall
print("\n" + "="*80)
print("CHECK: Hours 6 and 17 Exclusion")
print("="*80)

baseline_h6 = baseline_pos[baseline_pos['hour'] == 6]
new_h6 = new_pos[new_pos['hour'] == 6]
baseline_h17 = baseline_pos[baseline_pos['hour'] == 17]
new_h17 = new_pos[new_pos['hour'] == 17]

print(f"\nHour 6:")
print(f"  Baseline: {len(baseline_h6)} trades, ${baseline_h6['realized_pnl'].sum():,.2f} PnL")
print(f"  New: {len(new_h6)} trades, ${new_h6['realized_pnl'].sum():,.2f} PnL")
print(f"  Removed: {len(baseline_h6) - len(new_h6)} trades")

print(f"\nHour 17:")
print(f"  Baseline: {len(baseline_h17)} trades, ${baseline_h17['realized_pnl'].sum():,.2f} PnL")
print(f"  New: {len(new_h17)} trades, ${new_h17['realized_pnl'].sum():,.2f} PnL")
print(f"  Removed: {len(baseline_h17) - len(new_h17)} trades")

total_saved = -baseline_h6['realized_pnl'].sum() - baseline_h17['realized_pnl'].sum()
print(f"\n💰 Expected savings from removing H6+H17: ${total_saved:,.2f}")

# Prediction vs Reality
print("\n" + "="*80)
print("PREDICTION vs REALITY")
print("="*80)

print(f"\n📊 Predicted improvement: $+478 to $+725")
print(f"🎯 Actual improvement: ${pnl_change:+,.2f}")

if abs(pnl_change - 478) < 100 or abs(pnl_change - 725) < 100:
    print("✅ Result matches prediction!")
elif pnl_change > 300:
    print("✅ Significant improvement achieved!")
elif pnl_change > 0:
    print("⚠️  Small improvement - may need additional filters")
else:
    print("❌ Unexpected result - review exclusions")

print("\n" + "="*80)
print("NEXT STEPS")
print("="*80)

if pnl_change > 0:
    print("\n✅ Time-based exclusions working!")
    print("\n📋 Next improvements to try:")
    print("   1. Minimum 1-hour hold logic (expected: +$458)")
    print("   2. Review other losing patterns")
    print("   3. Optimize trailing stops for longer trades")
else:
    print("\n⚠️  Review .env configuration")
    print("   Verify hour exclusions are correctly set")
    print("   Check rejected_signals.csv to confirm filtering")
