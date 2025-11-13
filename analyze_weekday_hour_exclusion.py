"""
Analyze whether weekday-specific hour exclusion could improve win rate and PnL.
Compares current flat exclusion vs optimized per-weekday exclusion.
"""

import pandas as pd
import json
from pathlib import Path

# Load the hourly PnL by weekday data
results_dir = Path("logs/backtest_results/EUR-USD_20251113_141438")
hourly_data = pd.read_csv(results_dir / "hourly_pnl_by_weekday.csv")

# Current flat exclusion hours (from .env)
current_excluded = {0, 1, 8, 10, 11, 12, 13, 18, 19, 23}

print("=" * 80)
print("WEEKDAY-SPECIFIC HOUR EXCLUSION ANALYSIS")
print("=" * 80)
print(f"\nCurrent flat exclusion: hours {sorted(current_excluded)}")
print("\n1. CURRENT PERFORMANCE WITH FLAT EXCLUSION")
print("-" * 80)

# Filter to only hours NOT currently excluded
current_included = hourly_data[~hourly_data['hour'].isin(current_excluded)]

current_trades = current_included['trade_count'].sum()
current_pnl = current_included['total_pnl'].sum()
current_wins = current_included['wins'].sum()
current_losses = current_included['losses'].sum()
current_winrate = current_wins / (current_wins + current_losses) * 100

print(f"Total PnL: ${current_pnl:,.2f}")
print(f"Total Trades: {current_trades}")
print(f"Winners: {current_wins} ({current_winrate:.2f}%)")
print(f"Losers: {current_losses}")
print(f"Avg PnL per trade: ${current_pnl/current_trades:.2f}")

print("\n2. ANALYSIS BY WEEKDAY-HOUR")
print("-" * 80)

# Group by weekday and show performance
weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Sunday']

# For each weekday, identify good vs bad hours
weekday_analysis = {}

for weekday in weekdays:
    wd_data = hourly_data[hourly_data['weekday'] == weekday].copy()
    
    if len(wd_data) == 0:
        continue
    
    # Calculate metrics
    wd_data['expectancy'] = wd_data['avg_pnl']
    wd_data['win_rate_decimal'] = wd_data['win_rate'] / 100.0
    
    # Identify bad hours (negative expectancy OR very low win rate)
    bad_hours = wd_data[
        (wd_data['expectancy'] < 0) | 
        ((wd_data['win_rate'] < 20) & (wd_data['trade_count'] >= 3))
    ]['hour'].tolist()
    
    # Identify good hours (positive expectancy AND reasonable win rate)
    good_hours = wd_data[
        (wd_data['expectancy'] > 0) & 
        (wd_data['win_rate'] >= 25)
    ]['hour'].tolist()
    
    weekday_analysis[weekday] = {
        'all_hours': wd_data['hour'].tolist(),
        'bad_hours': bad_hours,
        'good_hours': good_hours,
        'current_excluded': [h for h in current_excluded if h in wd_data['hour'].tolist()],
        'data': wd_data
    }
    
    print(f"\n{weekday}:")
    print(f"  Currently excluded hours that appear: {sorted([h for h in current_excluded if h in wd_data['hour'].tolist()])}")
    print(f"  Bad performing hours: {sorted(bad_hours)}")
    print(f"  Good performing hours: {sorted(good_hours)}")

print("\n3. OPTIMIZED WEEKDAY-SPECIFIC EXCLUSION")
print("-" * 80)

# Build optimized exclusion per weekday
optimized_exclusion = {}
for weekday in weekdays:
    if weekday not in weekday_analysis:
        optimized_exclusion[weekday] = sorted(list(current_excluded))
        continue
    
    # Start with bad hours
    exclude_hours = set(weekday_analysis[weekday]['bad_hours'])
    
    # Always keep the global exclusions as baseline unless they perform very well
    wd_data = weekday_analysis[weekday]['data']
    for hour in current_excluded:
        if hour in wd_data['hour'].values:
            hour_stats = wd_data[wd_data['hour'] == hour].iloc[0]
            # Only keep excluded if it's not clearly good
            if not (hour_stats['expectancy'] > 50 and hour_stats['win_rate'] > 40):
                exclude_hours.add(hour)
        else:
            exclude_hours.add(hour)
    
    optimized_exclusion[weekday] = sorted(list(exclude_hours))

print("\nOptimized exclusions per weekday:")
for weekday in weekdays:
    if weekday in optimized_exclusion:
        print(f"  {weekday}: {optimized_exclusion[weekday]}")

print("\n4. PROJECTED PERFORMANCE WITH OPTIMIZED EXCLUSION")
print("-" * 80)

optimized_trades = 0
optimized_pnl = 0
optimized_wins = 0
optimized_losses = 0

for weekday in weekdays:
    if weekday not in weekday_analysis:
        continue
    
    excluded_hours = set(optimized_exclusion[weekday])
    wd_data = weekday_analysis[weekday]['data']
    
    # Include hours NOT in exclusion list
    included_data = wd_data[~wd_data['hour'].isin(excluded_hours)]
    
    optimized_trades += included_data['trade_count'].sum()
    optimized_pnl += included_data['total_pnl'].sum()
    optimized_wins += included_data['wins'].sum()
    optimized_losses += included_data['losses'].sum()

optimized_winrate = optimized_wins / (optimized_wins + optimized_losses) * 100 if (optimized_wins + optimized_losses) > 0 else 0

print(f"Total PnL: ${optimized_pnl:,.2f}")
print(f"Total Trades: {optimized_trades}")
print(f"Winners: {optimized_wins} ({optimized_winrate:.2f}%)")
print(f"Losers: {optimized_losses}")
print(f"Avg PnL per trade: ${optimized_pnl/optimized_trades:.2f}")

print("\n5. COMPARISON")
print("-" * 80)

pnl_diff = optimized_pnl - current_pnl
pnl_diff_pct = (pnl_diff / current_pnl * 100) if current_pnl != 0 else 0
winrate_diff = optimized_winrate - current_winrate
trade_diff = optimized_trades - current_trades

print(f"PnL Change: ${pnl_diff:+,.2f} ({pnl_diff_pct:+.2f}%)")
print(f"Win Rate Change: {winrate_diff:+.2f}pp (from {current_winrate:.2f}% to {optimized_winrate:.2f}%)")
print(f"Trade Count Change: {trade_diff:+d} (from {current_trades} to {optimized_trades})")

print("\n6. RECOMMENDATION")
print("-" * 80)

if pnl_diff > 500 and winrate_diff > 1.0:
    print("✓ RECOMMENDED: Weekday-specific exclusion shows significant improvement")
    print(f"  Expected gains: ${pnl_diff:,.2f} PnL and {winrate_diff:.2f}pp win rate")
    print("  Implementation should allow reverting to flat exclusion via config")
elif pnl_diff > 200 or winrate_diff > 0.5:
    print("~ MARGINAL: Weekday-specific exclusion shows modest improvement")
    print(f"  Expected gains: ${pnl_diff:,.2f} PnL and {winrate_diff:.2f}pp win rate")
    print("  Consider implementing if flexibility is valuable")
else:
    print("✗ NOT RECOMMENDED: Weekday-specific exclusion shows minimal improvement")
    print(f"  Expected gains: ${pnl_diff:,.2f} PnL and {winrate_diff:.2f}pp win rate")
    print("  Current flat exclusion is sufficient")

print("\n7. DETAILED HOUR-BY-HOUR BREAKDOWN")
print("-" * 80)

# Show which hours would change per weekday
for weekday in weekdays:
    if weekday not in weekday_analysis:
        continue
    
    current_ex = set([h for h in current_excluded if h in weekday_analysis[weekday]['all_hours']])
    optimized_ex = set(optimized_exclusion[weekday]) & set(weekday_analysis[weekday]['all_hours'])
    
    newly_excluded = optimized_ex - current_ex
    newly_included = current_ex - optimized_ex
    
    if newly_excluded or newly_included:
        print(f"\n{weekday} changes:")
        if newly_excluded:
            print(f"  Would newly EXCLUDE: {sorted(newly_excluded)}")
            for hour in sorted(newly_excluded):
                hour_data = weekday_analysis[weekday]['data'][
                    weekday_analysis[weekday]['data']['hour'] == hour
                ]
                if len(hour_data) > 0:
                    row = hour_data.iloc[0]
                    print(f"    Hour {hour}: {row['trade_count']} trades, ${row['total_pnl']:.2f} PnL, {row['win_rate']:.1f}% WR")
        
        if newly_included:
            print(f"  Would newly INCLUDE: {sorted(newly_included)}")
            for hour in sorted(newly_included):
                hour_data = weekday_analysis[weekday]['data'][
                    weekday_analysis[weekday]['data']['hour'] == hour
                ]
                if len(hour_data) > 0:
                    row = hour_data.iloc[0]
                    print(f"    Hour {hour}: {row['trade_count']} trades, ${row['total_pnl']:.2f} PnL, {row['win_rate']:.1f}% WR")

print("\n" + "=" * 80)

# Save optimized exclusion to JSON for easy implementation
output = {
    "flat_exclusion": sorted(list(current_excluded)),
    "weekday_exclusion": optimized_exclusion,
    "analysis": {
        "current_pnl": float(current_pnl),
        "current_winrate": float(current_winrate),
        "current_trades": int(current_trades),
        "optimized_pnl": float(optimized_pnl),
        "optimized_winrate": float(optimized_winrate),
        "optimized_trades": int(optimized_trades),
        "pnl_improvement": float(pnl_diff),
        "winrate_improvement": float(winrate_diff)
    }
}

output_file = results_dir / "weekday_hour_exclusion_analysis.json"
with open(output_file, 'w') as f:
    json.dump(output, f, indent=2)

print(f"\nAnalysis saved to: {output_file}")
