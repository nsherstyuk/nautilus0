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
    
    # Convert to EST (handle both timezone-aware and naive timestamps)
    est = pytz.timezone('US/Eastern')
    if trades_df['entry_dt'].dt.tz is None:
        # Naive timestamps - assume UTC
        trades_df['entry_est'] = trades_df['entry_dt'].dt.tz_localize('UTC').dt.tz_convert(est)
    else:
        # Already timezone-aware
        trades_df['entry_est'] = trades_df['entry_dt'].dt.tz_convert(est)
    
    trades_df['hour_est'] = trades_df['entry_est'].dt.hour
    trades_df['weekday'] = trades_df['entry_est'].dt.weekday  # 0=Monday, 6=Sunday
    
    return trades_df

def analyze_year_over_year_consistency(trades_df):
    """
    Analyze consistency of hour×weekday×month patterns across different years.
    Returns patterns that are consistently good or bad.
    """
    weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # Group by month_num, hour, weekday, and year
    grouped = trades_df.groupby(['month_num', 'hour_est', 'weekday', 'year']).agg({
        'pnl': ['sum', 'count', 'mean', lambda x: (x > 0).sum()],
    }).round(2)
    
    grouped.columns = ['total_pnl', 'trade_count', 'avg_pnl', 'wins']
    grouped['win_rate'] = (grouped['wins'] / grouped['trade_count'] * 100).round(1)
    grouped = grouped.reset_index()
    
    # Find patterns that appear in multiple years
    patterns = defaultdict(list)
    
    for _, row in grouped.iterrows():
        key = (row['month_num'], row['hour_est'], row['weekday'])
        patterns[key].append({
            'year': row['year'],
            'trades': row['trade_count'],
            'win_rate': row['win_rate'],
            'total_pnl': row['total_pnl'],
            'avg_pnl': row['avg_pnl']
        })
    
    # Analyze consistency
    consistent_negative = []  # Consistently bad patterns
    consistent_positive = []  # Consistently good patterns
    exceptional_gems = []     # 100% win rate patterns
    
    for (month_num, hour, weekday), years_data in patterns.items():
        if len(years_data) < 2:  # Need at least 2 years for consistency
            continue
        
        # Check for consistent negative pattern
        negative_years = sum(1 for y in years_data if y['total_pnl'] < 0 and y['win_rate'] < 45)
        total_trades = sum(y['trades'] for y in years_data)
        total_pnl = sum(y['total_pnl'] for y in years_data)
        avg_win_rate = sum(y['win_rate'] * y['trades'] for y in years_data) / total_trades
        
        # CONSISTENTLY BAD: negative in 2+ years, low overall win rate, enough trades
        if negative_years >= 2 and avg_win_rate < 45 and total_trades >= 5 and total_pnl < -50:
            consistent_negative.append({
                'month_num': month_num,
                'hour': hour,
                'weekday': weekday,
                'weekday_name': weekday_names[weekday],
                'years_count': len(years_data),
                'negative_years': negative_years,
                'total_trades': total_trades,
                'total_pnl': total_pnl,
                'avg_win_rate': avg_win_rate,
                'years_detail': years_data
            })
        
        # CONSISTENTLY GOOD: positive in 2+ years, high win rate, good PnL
        positive_years = sum(1 for y in years_data if y['total_pnl'] > 0 and y['win_rate'] > 60)
        if positive_years >= 2 and avg_win_rate > 60 and total_trades >= 5 and total_pnl > 50:
            consistent_positive.append({
                'month_num': month_num,
                'hour': hour,
                'weekday': weekday,
                'weekday_name': weekday_names[weekday],
                'years_count': len(years_data),
                'positive_years': positive_years,
                'total_trades': total_trades,
                'total_pnl': total_pnl,
                'avg_win_rate': avg_win_rate,
                'years_detail': years_data
            })
        
        # EXCEPTIONAL GEMS: 100% win rate in any year with 5+ trades
        for year_data in years_data:
            if year_data['win_rate'] >= 100 and year_data['trades'] >= 5:
                exceptional_gems.append({
                    'month_num': month_num,
                    'hour': hour,
                    'weekday': weekday,
                    'weekday_name': weekday_names[weekday],
                    'year': year_data['year'],
                    'trades': year_data['trades'],
                    'total_pnl': year_data['total_pnl'],
                    'win_rate': year_data['win_rate']
                })
    
    return {
        'negative': sorted(consistent_negative, key=lambda x: x['total_pnl']),
        'positive': sorted(consistent_positive, key=lambda x: -x['total_pnl']),
        'gems': sorted(exceptional_gems, key=lambda x: -x['total_pnl'])
    }

def print_consistency_report(consistency_results):
    """Print detailed year-over-year consistency analysis."""
    
    print("\n" + "=" * 80)
    print("YEAR-OVER-YEAR CONSISTENCY ANALYSIS")
    print("=" * 80)
    
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
        if p['total_pnl'] < -30:  # Lowered threshold to catch more patterns
            by_month[p['month_num']].append(f"{p['hour']}-{p['weekday']}")
    
    if not by_month:
        print("No patterns meet exclusion criteria (total PnL < -$30)")
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
    
    print(f"\nDate range: {baseline_runs[0]['start_date']} to {baseline_runs[-1]['end_date']}")
    
    print("\n2. Loading trades...")
    trades = load_all_trades(baseline_runs)
    
    print("\n3. Parsing timestamps...")
    trades = parse_entry_time(trades)
    
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
    print(f"Total PnL: ${trades['pnl'].sum():.2f}")
    print(f"Win rate: {(trades['pnl'] > 0).sum() / len(trades) * 100:.1f}%")
    print(f"\nConsistency findings:")
    print(f"  - Consistently negative patterns: {len(consistency['negative'])}")
    print(f"  - Consistently positive patterns: {len(consistency['positive'])}")
    print(f"  - Exceptional gems (100% WR): {len(consistency['gems'])}")

if __name__ == "__main__":
    main()
