"""
Analyze negative periods in trading to understand drawdown characteristics.

Analyzes:
1. Negative days (daily P&L < 0)
2. Negative weeks (weekly P&L < 0)
3. Consecutive losing periods
4. Worst drawdown periods

Helps determine if multi-layer exits reduce negative periods.
"""
import pandas as pd
from pathlib import Path
import numpy as np

def analyze_drawdowns(trades_file, strategy_name):
    """Analyze drawdown periods from trades file."""
    
    df = pd.read_csv(trades_file)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    
    # Sort by exit time
    df = df.sort_values('exit_time')
    
    # Calculate cumulative P&L
    df['cumulative_pnl'] = df['pnl'].cumsum()
    
    print(f"\n{'='*80}")
    print(f"DRAWDOWN ANALYSIS: {strategy_name}")
    print(f"{'='*80}")
    
    # Daily analysis
    df['exit_date'] = df['exit_time'].dt.date
    daily_pnl = df.groupby('exit_date')['pnl'].sum()
    
    negative_days = (daily_pnl < 0).sum()
    total_days = len(daily_pnl)
    pct_negative_days = negative_days / total_days * 100
    
    print(f"\nDAILY ANALYSIS:")
    print(f"  Total trading days: {total_days}")
    print(f"  Negative days: {negative_days} ({pct_negative_days:.1f}%)")
    print(f"  Positive days: {total_days - negative_days} ({100-pct_negative_days:.1f}%)")
    print(f"  Worst day: ${daily_pnl.min():,.2f}")
    print(f"  Best day: ${daily_pnl.max():,.2f}")
    
    # Weekly analysis
    df['exit_week'] = df['exit_time'].dt.to_period('W')
    weekly_pnl = df.groupby('exit_week')['pnl'].sum()
    
    negative_weeks = (weekly_pnl < 0).sum()
    total_weeks = len(weekly_pnl)
    pct_negative_weeks = negative_weeks / total_weeks * 100
    
    print(f"\nWEEKLY ANALYSIS:")
    print(f"  Total trading weeks: {total_weeks}")
    print(f"  Negative weeks: {negative_weeks} ({pct_negative_weeks:.1f}%)")
    print(f"  Positive weeks: {total_weeks - negative_weeks} ({100-pct_negative_weeks:.1f}%)")
    print(f"  Worst week: ${weekly_pnl.min():,.2f}")
    print(f"  Best week: ${weekly_pnl.max():,.2f}")
    
    # Monthly analysis
    monthly_pnl = df.groupby('entry_month')['pnl'].sum()
    
    negative_months = (monthly_pnl < 0).sum()
    total_months = len(monthly_pnl)
    pct_negative_months = negative_months / total_months * 100
    
    print(f"\nMONTHLY ANALYSIS:")
    print(f"  Total trading months: {total_months}")
    print(f"  Negative months: {negative_months} ({pct_negative_months:.1f}%)")
    print(f"  Positive months: {total_months - negative_months} ({100-pct_negative_months:.1f}%)")
    print(f"  Worst month: ${monthly_pnl.min():,.2f}")
    print(f"  Best month: ${monthly_pnl.max():,.2f}")
    
    # Consecutive losing periods
    print(f"\nCONSECUTIVE LOSING PERIODS:")
    
    # Days
    daily_negative = (daily_pnl < 0).astype(int)
    max_consecutive_days = 0
    current_streak = 0
    
    for is_negative in daily_negative:
        if is_negative:
            current_streak += 1
            max_consecutive_days = max(max_consecutive_days, current_streak)
        else:
            current_streak = 0
    
    print(f"  Max consecutive losing days: {max_consecutive_days}")
    
    # Weeks
    weekly_negative = (weekly_pnl < 0).astype(int)
    max_consecutive_weeks = 0
    current_streak = 0
    
    for is_negative in weekly_negative:
        if is_negative:
            current_streak += 1
            max_consecutive_weeks = max(max_consecutive_weeks, current_streak)
        else:
            current_streak = 0
    
    print(f"  Max consecutive losing weeks: {max_consecutive_weeks}")
    
    # Drawdown analysis
    print(f"\nDRAWDOWN ANALYSIS:")
    
    running_max = df['cumulative_pnl'].cummax()
    drawdown = df['cumulative_pnl'] - running_max
    max_drawdown = drawdown.min()
    
    print(f"  Max drawdown: ${max_drawdown:,.2f}")
    
    # Find max drawdown period
    max_dd_idx = drawdown.idxmin()
    max_dd_date = df.loc[max_dd_idx, 'exit_time']
    
    # Find peak before drawdown
    peak_idx = df.loc[:max_dd_idx, 'cumulative_pnl'].idxmax()
    peak_date = df.loc[peak_idx, 'exit_time']
    
    dd_duration = (max_dd_date - peak_date).days
    
    print(f"  Drawdown period: {peak_date.date()} to {max_dd_date.date()}")
    print(f"  Duration: {dd_duration} days")
    
    return {
        'strategy': strategy_name,
        'negative_days': negative_days,
        'total_days': total_days,
        'pct_negative_days': pct_negative_days,
        'negative_weeks': negative_weeks,
        'total_weeks': total_weeks,
        'pct_negative_weeks': pct_negative_weeks,
        'negative_months': negative_months,
        'total_months': total_months,
        'pct_negative_months': pct_negative_months,
        'max_drawdown': max_drawdown,
        'max_consecutive_days': max_consecutive_days,
        'max_consecutive_weeks': max_consecutive_weeks
    }

# Analyze current strategy (baseline)
print("="*80)
print("COMPARING DRAWDOWN CHARACTERISTICS")
print("="*80)

results = []

# Current strategy (from most recent backtest with multi-layer disabled)
baseline_file = Path("logs/backtest_results/MTF_ML_20251129_163254/trades.csv")
if baseline_file.exists():
    result = analyze_drawdowns(baseline_file, "Current (50/50)")
    results.append(result)

# Conservative strategy
conservative_file = Path("logs/backtest_results/MTF_ML_20251129_163357/trades.csv")
if conservative_file.exists():
    result = analyze_drawdowns(conservative_file, "Conservative (70/20/10)")
    results.append(result)

# Comparison
if len(results) >= 2:
    print(f"\n{'='*80}")
    print("COMPARISON SUMMARY")
    print(f"{'='*80}")
    
    print(f"\n{'Metric':<30} {'Current':<20} {'Conservative':<20} {'Change':<15}")
    print("-"*85)
    
    baseline = results[0]
    conservative = results[1]
    
    print(f"{'Negative Days':<30} {baseline['negative_days']:<20} {conservative['negative_days']:<20} {conservative['negative_days']-baseline['negative_days']:<15}")
    print(f"{'% Negative Days':<30} {baseline['pct_negative_days']:<20.1f} {conservative['pct_negative_days']:<20.1f} {conservative['pct_negative_days']-baseline['pct_negative_days']:<15.1f}")
    print(f"{'Negative Weeks':<30} {baseline['negative_weeks']:<20} {conservative['negative_weeks']:<20} {conservative['negative_weeks']-baseline['negative_weeks']:<15}")
    print(f"{'% Negative Weeks':<30} {baseline['pct_negative_weeks']:<20.1f} {conservative['pct_negative_weeks']:<20.1f} {conservative['pct_negative_weeks']-baseline['pct_negative_weeks']:<15.1f}")
    print(f"{'Negative Months':<30} {baseline['negative_months']:<20} {conservative['negative_months']:<20} {conservative['negative_months']-baseline['negative_months']:<15}")
    print(f"{'Max Drawdown':<30} ${baseline['max_drawdown']:<19,.2f} ${conservative['max_drawdown']:<19,.2f} ${conservative['max_drawdown']-baseline['max_drawdown']:<14,.2f}")
    print(f"{'Max Consecutive Days':<30} {baseline['max_consecutive_days']:<20} {conservative['max_consecutive_days']:<20} {conservative['max_consecutive_days']-baseline['max_consecutive_days']:<15}")
    print(f"{'Max Consecutive Weeks':<30} {baseline['max_consecutive_weeks']:<20} {conservative['max_consecutive_weeks']:<20} {conservative['max_consecutive_weeks']-baseline['max_consecutive_weeks']:<15}")

print(f"\n{'='*80}")
print("RECOMMENDATION")
print(f"{'='*80}")

print("""
Key Metrics for Smooth Equity Curve:
1. Lower % of negative days/weeks
2. Smaller max drawdown
3. Fewer consecutive losing periods

If Conservative shows improvement in these areas, it might be worth
the trade-off of slightly lower total P&L for smoother returns.
""")
