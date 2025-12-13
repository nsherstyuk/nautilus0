"""
Deep analysis of duration-based trailing stop feature
Compare baseline vs new backtest for >12h trades
"""
import pandas as pd
import json
from pathlib import Path

print("="*80)
print("DURATION-BASED TRAILING ANALYSIS")
print("="*80)

# Load baseline results
baseline_dir = Path('logs/backtest_results/EUR-USD_20251116_161604')
if not baseline_dir.exists():
    baseline_dir = Path('logs/backtest_results/EUR-USD_20251116_140938')

# Load new results
new_dir = Path('logs/backtest_results/EUR-USD_20251116_164617')

print(f"\n📁 Baseline: {baseline_dir.name}")
print(f"📁 New:      {new_dir.name}")

# Load positions
baseline_pos = pd.read_csv(baseline_dir / 'positions.csv')
new_pos = pd.read_csv(new_dir / 'positions.csv')

# Parse data
for df in [baseline_pos, new_pos]:
    df['realized_pnl'] = df['realized_pnl'].str.replace(' USD', '').astype(float)
    df['ts_opened'] = pd.to_datetime(df['ts_opened'])
    df['ts_closed'] = pd.to_datetime(df['ts_closed'])
    df['duration_hours'] = (df['ts_closed'] - df['ts_opened']).dt.total_seconds() / 3600
    df['is_winner'] = df['realized_pnl'] > 0

# Load orders to check cancellations
baseline_orders = pd.read_csv(baseline_dir / 'orders.csv')
new_orders = pd.read_csv(new_dir / 'orders.csv')

# Overall comparison
print(f"\n{'='*80}")
print("OVERALL COMPARISON")
print(f"{'='*80}")

print(f"\nBaseline:")
print(f"  Trades: {len(baseline_pos)}")
print(f"  PnL: ${baseline_pos['realized_pnl'].sum():,.2f}")
print(f"  Win Rate: {baseline_pos['is_winner'].mean()*100:.1f}%")

print(f"\nNew:")
print(f"  Trades: {len(new_pos)}")
print(f"  PnL: ${new_pos['realized_pnl'].sum():,.2f}")
print(f"  Win Rate: {new_pos['is_winner'].mean()*100:.1f}%")

# Focus on >12h trades
print(f"\n{'='*80}")
print("TRADES >12 HOURS (Target of Optimization)")
print(f"{'='*80}")

baseline_long = baseline_pos[baseline_pos['duration_hours'] >= 12].copy()
new_long = new_pos[new_pos['duration_hours'] >= 12].copy()

print(f"\n📊 COUNT & PnL:")
print(f"  Baseline: {len(baseline_long)} trades, ${baseline_long['realized_pnl'].sum():,.2f}")
print(f"  New:      {len(new_long)} trades, ${new_long['realized_pnl'].sum():,.2f}")
print(f"  Change:   {len(new_long)-len(baseline_long):+d} trades, ${new_long['realized_pnl'].sum()-baseline_long['realized_pnl'].sum():+,.2f}")

print(f"\n📊 WINNERS:")
baseline_long_winners = baseline_long[baseline_long['is_winner']]
new_long_winners = new_long[new_long['is_winner']]

print(f"  Baseline: {len(baseline_long_winners)} winners, ${baseline_long_winners['realized_pnl'].sum():,.2f}")
print(f"  New:      {len(new_long_winners)} winners, ${new_long_winners['realized_pnl'].sum():,.2f}")
print(f"  Change:   {len(new_long_winners)-len(baseline_long_winners):+d} winners, ${new_long_winners['realized_pnl'].sum()-baseline_long_winners['realized_pnl'].sum():+,.2f}")

if len(new_long_winners) > 0 and len(baseline_long_winners) > 0:
    print(f"\n  Avg Winner:")
    print(f"    Baseline: ${baseline_long_winners['realized_pnl'].mean():.2f}")
    print(f"    New:      ${new_long_winners['realized_pnl'].mean():.2f}")
    print(f"    Change:   ${new_long_winners['realized_pnl'].mean() - baseline_long_winners['realized_pnl'].mean():+.2f}")
    
    print(f"\n  Max Winner:")
    print(f"    Baseline: ${baseline_long_winners['realized_pnl'].max():.2f}")
    print(f"    New:      ${new_long_winners['realized_pnl'].max():.2f}")
    print(f"    Change:   ${new_long_winners['realized_pnl'].max() - baseline_long_winners['realized_pnl'].max():+.2f}")

# Check TP cancellations
print(f"\n{'='*80}")
print("TP ORDER CANCELLATIONS (Feature Activation)")
print(f"{'='*80}")

baseline_cancelled_tp = baseline_orders[(baseline_orders['status'] == 'CANCELED') & 
                                        (baseline_orders['tags'].str.contains('TP', na=False))].copy()
new_cancelled_tp = new_orders[(new_orders['status'] == 'CANCELED') & 
                               (new_orders['tags'].str.contains('TP', na=False))].copy()

print(f"\nCancelled TP orders:")
print(f"  Baseline: {len(baseline_cancelled_tp)}")
print(f"  New:      {len(new_cancelled_tp)}")
print(f"  Difference: {len(new_cancelled_tp) - len(baseline_cancelled_tp):+d}")

if len(new_cancelled_tp) > len(baseline_cancelled_tp):
    print(f"\n✅ Feature IS activating! {len(new_cancelled_tp) - len(baseline_cancelled_tp)} additional TPs cancelled")
else:
    print(f"\n⚠️  No additional TP cancellations detected")

# Duration distribution comparison
print(f"\n{'='*80}")
print("DURATION DISTRIBUTION")
print(f"{'='*80}")

duration_bins = [(0, 12, '<12h'), (12, 24, '12-24h'), (24, 48, '24-48h'), (48, 1000, '>48h')]

print(f"\n{'Duration':<10} {'Baseline Cnt':<15} {'New Cnt':<15} {'Baseline PnL':<15} {'New PnL':<15} {'Change':<15}")
print("-"*85)

for min_h, max_h, label in duration_bins:
    b_bucket = baseline_pos[(baseline_pos['duration_hours'] >= min_h) & (baseline_pos['duration_hours'] < max_h)]
    n_bucket = new_pos[(new_pos['duration_hours'] >= min_h) & (new_pos['duration_hours'] < max_h)]
    
    b_pnl = b_bucket['realized_pnl'].sum()
    n_pnl = n_bucket['realized_pnl'].sum()
    
    print(f"{label:<10} {len(b_bucket):<15} {len(n_bucket):<15} ${b_pnl:<13,.2f} ${n_pnl:<13,.2f} ${n_pnl-b_pnl:+,.2f}")

# Check if positions closed differently
print(f"\n{'='*80}")
print("POSITION CLOSE ANALYSIS (>12h trades)")
print(f"{'='*80}")

# Match positions by opening time to see if they closed differently
baseline_long['open_key'] = baseline_long['ts_opened'].astype(str) + '_' + baseline_long['side'].astype(str)
new_long['open_key'] = new_long['ts_opened'].astype(str) + '_' + new_long['side'].astype(str)

# Find matching positions
common_keys = set(baseline_long['open_key']) & set(new_long['open_key'])
print(f"\nMatching >12h positions: {len(common_keys)}")

if len(common_keys) > 0:
    # Compare matched positions
    differences = []
    
    for key in common_keys:
        b_pos = baseline_long[baseline_long['open_key'] == key].iloc[0]
        n_pos = new_long[new_long['open_key'] == key].iloc[0]
        
        pnl_diff = n_pos['realized_pnl'] - b_pos['realized_pnl']
        duration_diff = n_pos['duration_hours'] - b_pos['duration_hours']
        
        if abs(pnl_diff) > 1.0 or abs(duration_diff) > 0.5:  # Significant difference
            differences.append({
                'opened': b_pos['ts_opened'],
                'side': b_pos['side'],
                'baseline_pnl': b_pos['realized_pnl'],
                'new_pnl': n_pos['realized_pnl'],
                'pnl_diff': pnl_diff,
                'baseline_duration': b_pos['duration_hours'],
                'new_duration': n_pos['duration_hours'],
                'duration_diff': duration_diff
            })
    
    if differences:
        print(f"\n🔍 Found {len(differences)} positions with significant differences:")
        diff_df = pd.DataFrame(differences)
        diff_df = diff_df.sort_values('pnl_diff', ascending=False)
        
        print(f"\n{'Opened':<20} {'Side':<6} {'Base PnL':<12} {'New PnL':<12} {'Δ PnL':<12} {'Base Dur':<10} {'New Dur':<10}")
        print("-"*90)
        for _, row in diff_df.head(20).iterrows():
            print(f"{str(row['opened'])[:19]:<20} {row['side']:<6} ${row['baseline_pnl']:>10.2f} ${row['new_pnl']:>10.2f} ${row['pnl_diff']:>10.2f} {row['baseline_duration']:>8.1f}h {row['new_duration']:>8.1f}h")
        
        total_pnl_change = diff_df['pnl_diff'].sum()
        improved = len(diff_df[diff_df['pnl_diff'] > 0])
        worsened = len(diff_df[diff_df['pnl_diff'] < 0])
        
        print(f"\n💰 Net PnL change from differences: ${total_pnl_change:+,.2f}")
        print(f"   Improved: {improved} positions")
        print(f"   Worsened: {worsened} positions")
    else:
        print(f"\n⚠️  No significant differences found in matched positions")
        print(f"   All >12h positions closed at same PnL and duration")

# Overall assessment
print(f"\n{'='*80}")
print("ASSESSMENT")
print(f"{'='*80}")

total_pnl_diff = new_pos['realized_pnl'].sum() - baseline_pos['realized_pnl'].sum()
long_pnl_diff = new_long['realized_pnl'].sum() - baseline_long['realized_pnl'].sum()

print(f"\n💰 Total PnL Change: ${total_pnl_diff:+,.2f}")
print(f"💰 >12h trades PnL Change: ${long_pnl_diff:+,.2f}")

if abs(total_pnl_diff) < 10:
    print(f"\n⚠️  IDENTICAL RESULTS")
    print(f"\n🔍 Possible reasons:")
    print(f"   1. TP cancellation worked, but positions closed at same points anyway")
    print(f"   2. Trailing stops triggered before hitting wider stops")
    print(f"   3. Positions reversed before benefiting from removed TP")
    print(f"   4. Feature needs different parameters (threshold, distance)")
    
    print(f"\n💡 Recommendations:")
    print(f"   • Check if positions are actually running longer (duration increase)")
    print(f"   • Review if trailing distance (30 pips) is too tight")
    print(f"   • Consider lower threshold (8h instead of 12h)")
    print(f"   • Try even wider trailing distance (40-50 pips)")
elif total_pnl_diff > 500:
    print(f"\n✅ SIGNIFICANT IMPROVEMENT!")
    print(f"   Feature is working as expected")
else:
    print(f"\n⚠️  MODEST CHANGE")
    print(f"   Feature may need parameter tuning")

print(f"\n{'='*80}")
