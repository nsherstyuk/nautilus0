"""
Year-over-year consistency analysis for hour×weekday patterns.
Identifies both exceptional positive AND negative patterns with cross-year validation.
"""
import pandas as pd
from pathlib import Path
import re
from datetime import datetime
from collections import defaultdict

def get_baseline_runs():
    """Find all clean baseline monthly runs from Jan 26 batch."""
    backtest_dir = Path("backtest_results")
    baseline_runs = []
    
    for run_dir in backtest_dir.glob("MTF_V2_ENTRY_CONFIRMED_20260126_*"):
        env_file = run_dir / ".env.mtf_v2"
        sum_file = run_dir / "summary.txt"
        
        if not env_file.exists() or not sum_file.exists():
            continue
            
        # Check if seasonal exclusions disabled
        env_content = env_file.read_text()
        if "MTF2_SEASONAL_HOUR_EXCLUSIONS_ENABLED=false" not in env_content:
            continue
            
        # Get period
        sum_content = sum_file.read_text()
        period_match = re.search(r'Period:\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})', sum_content)
        if not period_match:
            continue
            
        start_date = period_match.group(1)
        end_date = period_match.group(2)
        
        # Verify it's a monthly run (roughly 27-31 days)
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days = (end_dt - start_dt).days
        
        if 25 <= days <= 32:
            year = start_date[:4]
            month_num = start_date[5:7]  # Just the month number (01-12)
            baseline_runs.append({
                'run_dir': run_dir,
                'start_date': start_date,
                'end_date': end_date,
                'year': year,
                'month_num': month_num,
                'month_label': start_date[:7]  # YYYY-MM for display
            })
    
    return sorted(baseline_runs, key=lambda x: x['start_date'])

def load_all_trades(baseline_runs):
    """Load and combine trades from all baseline runs with year/month metadata."""
    all_trades = []
    
    for run in baseline_runs:
        trades_file = run['run_dir'] / "trades.csv"
        if not trades_file.exists():
            print(f"Warning: No trades.csv in {run['run_dir'].name}")
            continue
            
        df = pd.read_csv(trades_file)
        df['year'] = run['year']
        df['month_num'] = run['month_num']  # 01-12
        df['month_label'] = run['month_label']  # YYYY-MM for display
        df['run_dir'] = run['run_dir'].name
        all_trades.append(df)
        print(f"Loaded {len(df)} trades from {run['month_label']}")
    
    if not all_trades:
        raise ValueError("No trades loaded!")
    
    combined = pd.concat(all_trades, ignore_index=True)
    print(f"\nTotal trades: {len(combined)}")
    return combined

def parse_entry_time(trades_df):
    """Parse entry timestamp and extract hour/weekday in EST."""
    import pytz
    
    # Try multiple timestamp column names
    time_col = None
    for col in ['entry_time', 'Entry Time', 'timestamp', 'Timestamp']:
        if col in trades_df.columns:
            time_col = col
            break
    
    if time_col is None:
        raise ValueError(f"No timestamp column found. Columns: {trades_df.columns.tolist()}")
    
    # Parse timestamps
    trades_df['entry_dt'] = pd.to_datetime(trades_df[time_col])
    
    # Convert UTC to EST
    est = pytz.timezone('US/Eastern')
    trades_df['entry_est'] = trades_df['entry_dt'].dt.tz_localize('UTC').dt.tz_convert(est)
    trades_df['hour_est'] = trades_df['entry_est'].dt.hour
    trades_df['weekday'] = trades_df['entry_est'].dt.weekday  # 0=Monday, 6=Sunday
    
    return trades_df

def get_season(month_str):
    """Convert YYYY-MM to season (DJF, MAM, JJA, SON)."""
    month_num = int(month_str.split('-')[1])
    if month_num in [12, 1, 2]:
        return 'DJF'
    elif month_num in [3, 4, 5]:
        return 'MAM'
    elif month_num in [6, 7, 8]:
        return 'JJA'
    else:
        return 'SON'

def analyze_hour_weekday_performance(trades_df):
    """Analyze performance by hour×weekday combination."""
    
    # Group by hour and weekday
    grouped = trades_df.groupby(['hour_est', 'weekday']).agg({
        'realized_pnl': ['sum', 'count', 'mean', lambda x: (x > 0).sum()],
    }).round(2)
    
    grouped.columns = ['total_pnl', 'trade_count', 'avg_pnl', 'wins']
    grouped['win_rate'] = (grouped['wins'] / grouped['trade_count'] * 100).round(1)
    grouped['losses'] = grouped['trade_count'] - grouped['wins']
    
    # Sort by total PnL (worst first)
    grouped = grouped.sort_values('total_pnl')
    
    return grouped

def analyze_by_season(trades_df):
    """Analyze performance by season×hour×weekday."""
    
    trades_df['season'] = trades_df['month'].apply(get_season)
    
    results = {}
    for season in ['DJF', 'MAM', 'JJA', 'SON']:
        season_df = trades_df[trades_df['season'] == season]
        
        if len(season_df) == 0:
            continue
            
        grouped = season_df.groupby(['hour_est', 'weekday']).agg({
            'realized_pnl': ['sum', 'count', 'mean', lambda x: (x > 0).sum()],
        }).round(2)
        
        grouped.columns = ['total_pnl', 'trade_count', 'avg_pnl', 'wins']
        grouped['win_rate'] = (grouped['wins'] / grouped['trade_count'] * 100).round(1)
        
        # Sort by total PnL (worst first)
        grouped = grouped.sort_values('total_pnl')
        results[season] = grouped
    
    return results

def analyze_by_month(trades_df):
    """Analyze performance by month×hour×weekday."""
    
    results = {}
    for month in sorted(trades_df['month'].unique()):
        month_df = trades_df[trades_df['month'] == month]
        
        grouped = month_df.groupby(['hour_est', 'weekday']).agg({
            'realized_pnl': ['sum', 'count', 'mean', lambda x: (x > 0).sum()],
        }).round(2)
        
        grouped.columns = ['total_pnl', 'trade_count', 'avg_pnl', 'wins']
        grouped['win_rate'] = (grouped['wins'] / grouped['trade_count'] * 100).round(1)
        
        results[month] = grouped
    
    return results

def analyze_year_over_year_consistency(trades_df):
    """
    Analyze consistency of hour×weekday×month patterns across different years.
    Returns patterns that are consistently good or bad.
    """
    weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # Group by month_num, hour, weekday, and year
    grouped = trades_df.groupby(['month_num', 'hour_est', 'weekday', 'year']).agg({
        'realized_pnl': ['sum', 'count', 'mean', lambda x: (x > 0).sum()],
    }).round(2)
    
    grouped.columns = ['total_pnl', 'trade_count', 'avg_pnl', 'wins']
    grouped['win_rate'] = (grouped['wins'] / grouped['trade_count'] * 100).round(1)
    grouped = grouped.reset_index()
    
    # Find patterns that appear in multiple years
    patterns = defaultdict(list)
    
    print("\n4. Analyzing year-over-year consistency...")
    consistency = analyze_year_over_year_consistency(trades)
    
    # Print detailed consistency report
    print_consistency_report(consistency)
    
    # Generate config recommendations
    generate_exclusion_config(consistency)
    
    # Summary stats
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    print(f"Total trades: {len(trades)}")
    print(f"Total PnL: ${trades['realized_pnl'].sum():.2f}")
    print(f"Win rate: {(trades['realized_pnl'] > 0).sum() / len(trades) * 100:.1f}%")
    print(f"\nConsistency findings:")
    print(f"  - Consistently negative patterns: {len(consistency['negative'])}")
    print(f"  - Consistently positive patterns: {len(consistency['positive'])}")
    print(f"  - Exceptional gems (100% WR): {len(consistency['gems']
    # Consistently negative patterns
    negative = consistency_results['negative']
    print(f"\n🔴 CONSISTENTLY NEGATIVE PATTERNS (exclude these): {len(negative)} found")
    print("-" * 80)
    
    if negative:
        print(f"{'Month':<6} {'Hour':<6} {'Day':<5} {'Years':<7} {'Trades':<8} {'Total PnL':<12} {'Avg WR%':<10}")
        print("-" * 80)
        for p in negative[:20]:  # Top 20 worst
            print(f"{p['month_num']:<6} {p['hour']:<6} {p['weekday_name']:<5} "
                  f"{p['negative_years']}/{p['years_count']:<7} {p['total_trades']:<8} "
                  f"${p['total_pnl']:<11.2f} {p['avg_win_rate']:<10.1f}%")
            # Show year-by-year detail
            for yd in p['years_detail']:
                print(f"    └─ {yd['year']}: {int(yd['trades'])} trades, "
                      f"{yd['win_rate']:.0f}% WR, ${yd['total_pnl']:.2f} PnL")
    else:
        print("  ✅ No consistently negative patterns found!")
    
    # Consistently positive patterns
    positive = consistency_results['positive']
    print(f"\n🟢 CONSISTENTLY POSITIVE PATTERNS (prioritize these): {len(positive)} found")
    print("-" * 80)
    
    if positive:
        print(f"{'Month':<6} {'Hour':<6} {'Day':<5} {'Years':<7} {'Trades':<8} {'Total PnL':<12} {'Avg WR%':<10}")
        print("-" * 80)
        for p in positive[:20]:  # Top 20 best
            print(f"{p['month_num']:<6} {p['hour']:<6} {p['weekday_name']:<5} "
                  f"{p['positive_years']}/{p['years_count']:<7} {p['total_trades']:<8} "
                  f"${p['total_pnl']:<11.2f} {p['avg_win_rate']:<10.1f}%")
            for yd in p['years_detail']:
                print(f"    └─ {yd['year']}: {int(yd['trades'])} trades, "
                      f"{yd['win_rate']:.0f}% WR, ${yd['total_pnl']:.2f} PnL")
    else:
        print("  ⚠️  No consistently positive patterns found")
    
    # Exceptional gems (100% win rate)
    gems = consistency_results['gems']
    print(f"\n💎 EXCEPTIONAL GEMS (100% win rate, 5+ trades): {len(gems)} found")
    print("-" * 80)
    
    if gems:
        print(f"{'Month':<6} {'Hour':<6} {'Day':<5} {'Year':<6} {'Trades':<8} {'Total PnL':<12} {'Win Rate':<10}")
        print("-" * 80)
        for g in gems[:15]:
            print(f"{g['month_num']:<6} {g['hour']:<6} {g['weekday_name']:<5} "
                  f"{g['year']:<6} {g['trades']:<8} ${g['total_pnl']:<11.2f} {g['win_rate']:<10.0f}%")
    else:
        print("  No 100% win rate patterns with 5+ trades")

def generate_exclusion_config(consistency_results):
    """Generate config recommendations for monthly exclusions."""
    
    negative = consistency_results['negative']
    
    if not negative:
        print("\n" + "=" * 80)
        print("NO EXCLUSIONS RECOMMENDED")
        print("=" * 80)
        print("No consistently negative patterns found.")
        print("Recommendation: Do not implement hour×weekday exclusions.")
        return
    
    print("\n" + "=" * 80)
    print("RECOMMENDED MONTHLY EXCLUSIONS")
    print("=" * 80)
    
    # Group by month
    by_month = defaultdict(list)
    for p in negative:
        if p['total_pnl'] < -100:  # Only very bad ones
            by_month[p['month_num']].append(f"{p['hour']}-{p['weekday']}")
    
    if not by_month:
        print("No patterns meet strict exclusion criteria (total PnL < -$100)")
        return
    
    month_names = {
        '01': 'January', '02': 'February', '03': 'March', '04': 'April',
        '05': 'May', '06': 'June', '07': 'July', '08': 'August',
        '09': 'September', '10': 'October', '11': 'November', '12': 'December'
    }
    
    print("\nAdd to .env.mtf_v2:")
    print("-" * 80)
    print("MTF2_MONTHLY_HOUR_EXCLUSIONS_ENABLED=true")
    
    for month_num in sorted(by_month.keys()):
        pairs = ','.join(by_month[month_num])
        month_name = month_names.get(month_num, month_num)
        print(f"MTF2_MONTH_{month_num}_EXCLUDED_HOUR_WEEKDAY_PAIRS={pairs}  # {month_name}")
    
    print("\n" + "=" * 80)
    print(f"Total months with exclusions: {len(by_month)}")
    print(f"Total pairs to exclude: {sum(len(v) for v in by_month.values())}")

def main():
    print("=" * 80)
    print("YEAR-OVER-YEAR HOUR×WEEKDAY CONSISTENCY ANALYSIS")
    print("=" * 80)
    
    # Load data
    print("\n1. Finding baseline runs...")
    baseline_runs = get_baseline_runs()
    print(f"Found {len(baseline_runs)} baseline monthly runs")
    
    # Show coverage
    years_coverage = defaultdict(list)
    for run in baseline_runs:
        years_coverage[run['year']].append(run['month_num'])
    
    print("\nYear coverage:")
    for year in sorted(years_coverage.keys()):
        months = sorted(years_coverage[year])
        print(f"  {year}: {len(months)} months - {', '.join(months)}")
    
    print(f"\n_runs = get_baseline_runs()
    print(f"Found {len(baseline_runs)} baseline monthly runs")
    print(f"Date range: {baseline_runs[0]['start_date']} to {baseline_runs[-1]['end_date']}")
    
    print("\n2. Loading trades...")
    trades = load_all_trades(baseline_runs)
    
    print("\n3. Parsing timestamps...")
    trades = parse_entry_time(trades)
    
    # Overall analysis
    print("\n" + "=" * 80)
    print("OVERALL HOUR×WEEKDAY PERFORMANCE (all months combined)")
    print("=" * 80)
    overall = analyze_hour_weekday_performance(trades)
    
    weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    print("\nWORST 20 hour×weekday combinations by total PnL:")
    print(f"{'Hour(EST)':<10} {'Weekday':<8} {'Trades':<7} {'Total PnL':<12} {'Avg PnL':<10} {'Win%':<8}")
    print("-" * 65)
    
    worst_pairs = []
    for (hour, weekday), row in overall.head(20).iterrows():
        wd_name = weekday_names[weekday]
        print(f"{hour:<10} {wd_name:<8} {int(row['trade_count']):<7} ${row['total_pnl']:<11.2f} ${row['avg_pnl']:<9.2f} {row['win_rate']:<8.1f}%")
        if row['total_pnl'] < -100:  # Significantly negative
            worst_pairs.append((hour, weekday, row['total_pnl']))
    
    print("\nBEST 20 hour×weekday combinations by total PnL:")
    print(f"{'Hour(EST)':<10} {'Weekday':<8} {'Trades':<7} {'Total PnL':<12} {'Avg PnL':<10} {'Win%':<8}")
    print("-" * 65)
    for (hour, weekday), row in overall.tail(20).iloc[::-1].iterrows():
        wd_name = weekday_names[weekday]
        print(f"{hour:<10} {wd_name:<8} {int(row['trade_count']):<7} ${row['total_pnl']:<11.2f} ${row['avg_pnl']:<9.2f} {row['win_rate']:<8.1f}%")
    
    # By season
    print("\n" + "=" * 80)
    print("PERFORMANCE BY SEASON")
    print("=" * 80)
    seasonal = analyze_by_season(trades)
    
    seasonal_exclusions = {}
    for season in ['DJF', 'MAM', 'JJA', 'SON']:
        if season not in seasonal:
            continue
            
        df = seasonal[season]
        print(f"\n{season} - Worst 10 hour×weekday pairs:")
        print(f"{'Hour(EST)':<10} {'Weekday':<8} {'Trades':<7} {'Total PnL':<12} {'Avg PnL':<10} {'Win%':<8}")
        print("-" * 65)
        
        exclude_pairs = []
        for (hour, weekday), row in df.head(10).iterrows():
            wd_name = weekday_names[weekday]
            print(f"{hour:<10} {wd_name:<8} {int(row['trade_count']):<7} ${row['total_pnl']:<11.2f} ${row['avg_pnl']:<9.2f} {row['win_rate']:<8.1f}%")
            
            # Criteria: total PnL < -50 AND (avg PnL < -5 OR win_rate < 50%)
            if row['total_pnl'] < -50 and (row['avg_pnl'] < -5 or row['win_rate'] < 50):
                exclude_pairs.append(f"{hour}-{weekday}")
        
        if exclude_pairs:
            seasonal_exclusions[season] = exclude_pairs
    
    # Recommendations
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    
    if seasonal_exclusions:
        print("\nSeasonal exclusions (pairs with total PnL < -$50 AND (avg < -$5 OR win% < 50%)):")
        for season, pairs in seasonal_exclusions.items():
            print(f"\n{season}: {','.join(pairs)}")
            print(f"  (would exclude {len(pairs)} hour×weekday combinations)")
    else:
        print("\nNo hour×weekday pairs meet the exclusion criteria.")
        print("Recommendation: DO NOT USE seasonal exclusions - insufficient edge.")
    
    # Save detailed results
    output_file = Path("analysis_hour_weekday_pnl_baseline.csv")
    overall.to_csv(output_file)
    print(f"\nDetailed results saved to: {output_file}")
    
    # Summary stats
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    print(f"Total trades: {len(trades)}")
    print(f"Total PnL: ${trades['realized_pnl'].sum():.2f}")
    print(f"Win rate: {(trades['realized_pnl'] > 0).sum() / len(trades) * 100:.1f}%")
    print(f"Unique hour×weekday pairs: {len(overall)}")
    print(f"Pairs with negative PnL: {(overall['total_pnl'] < 0).sum()}")
    print(f"Pairs with < -$100 PnL: {(overall['total_pnl'] < -100).sum()}")

if __name__ == "__main__":
    main()
