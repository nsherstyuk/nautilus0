"""
Analyze Losing Periods and Identify Improvement Opportunities
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json

def analyze_losing_periods(results_dir: str):
    """
    Deep dive into losing months to identify patterns and improvement opportunities
    """
    folder = Path(results_dir)
    positions_file = folder / 'positions.csv'
    
    if not positions_file.exists():
        print(f"ERROR: positions.csv not found in {folder}")
        return
    
    # Load positions
    df = pd.read_csv(positions_file, parse_dates=['ts_opened', 'ts_closed'])
    df['realized_pnl'] = df['realized_pnl'].str.replace(' USD', '', regex=False).astype(float)
    
    # Add time features
    df['month'] = df['ts_closed'].dt.to_period('M')
    df['hour'] = df['ts_opened'].dt.hour
    df['weekday'] = df['ts_opened'].dt.day_name()
    df['duration_hours'] = (df['ts_closed'] - df['ts_opened']).dt.total_seconds() / 3600
    df['is_winner'] = df['realized_pnl'] > 0
    
    # Identify losing months
    monthly_pnl = df.groupby('month')['realized_pnl'].sum()
    losing_months = monthly_pnl[monthly_pnl < 0].index.tolist()
    
    # Split into early period (2024) and later period (2025)
    early_period = df[df['ts_closed'].dt.year == 2024]
    later_period = df[df['ts_closed'].dt.year == 2025]
    
    print("="*80)
    print("LOSING PERIOD ANALYSIS - Finding Root Causes")
    print("="*80)
    
    # 1. Compare Early vs Later Performance
    print("\n" + "="*80)
    print("1. EARLY (2024) VS LATER (2025) COMPARISON")
    print("="*80)
    
    for period_name, period_df in [("2024 (Early Period)", early_period), 
                                    ("2025 (Later Period)", later_period)]:
        print(f"\n{period_name}:")
        print(f"  Total PnL:        ${period_df['realized_pnl'].sum():.2f}")
        print(f"  Trades:           {len(period_df)}")
        print(f"  Win Rate:         {(period_df['is_winner'].sum() / len(period_df) * 100):.1f}%")
        print(f"  Avg Winner:       ${period_df[period_df['is_winner']]['realized_pnl'].mean():.2f}")
        print(f"  Avg Loser:        ${period_df[~period_df['is_winner']]['realized_pnl'].mean():.2f}")
        print(f"  Avg Duration:     {period_df['duration_hours'].mean():.1f} hours")
        print(f"  Max Winner:       ${period_df['realized_pnl'].max():.2f}")
        print(f"  Max Loser:        ${period_df['realized_pnl'].min():.2f}")
    
    # 2. Analyze Losing Months Specifically
    print("\n" + "="*80)
    print("2. DETAILED ANALYSIS OF LOSING MONTHS")
    print("="*80)
    
    losing_trades = df[df['month'].isin(losing_months)]
    
    print(f"\nLosing Months: {', '.join(str(m) for m in losing_months)}")
    print(f"Total trades in losing months: {len(losing_trades)}")
    print(f"Win rate in losing months: {(losing_trades['is_winner'].sum() / len(losing_trades) * 100):.1f}%")
    print(f"Avg loser size: ${losing_trades[~losing_trades['is_winner']]['realized_pnl'].mean():.2f}")
    print(f"Avg winner size: ${losing_trades[losing_trades['is_winner']]['realized_pnl'].mean():.2f}")
    
    # 3. Time-of-Day Analysis for Losing Periods
    print("\n" + "="*80)
    print("3. HOUR-OF-DAY ANALYSIS (Early Period Issues)")
    print("="*80)
    
    early_by_hour = early_period.groupby('hour').agg({
        'realized_pnl': ['sum', 'mean', 'count'],
        'is_winner': 'mean'
    }).round(2)
    early_by_hour.columns = ['Total_PnL', 'Avg_PnL', 'Trades', 'Win_Rate']
    early_by_hour['Win_Rate'] = (early_by_hour['Win_Rate'] * 100).round(1)
    
    print("\nWorst performing hours in 2024:")
    worst_hours = early_by_hour.nsmallest(5, 'Total_PnL')
    for hour, row in worst_hours.iterrows():
        print(f"  Hour {hour:02d}: ${row['Total_PnL']:.2f} PnL, "
              f"{int(row['Trades'])} trades, {row['Win_Rate']:.1f}% win rate")
    
    print("\nBest performing hours in 2024:")
    best_hours = early_by_hour.nlargest(5, 'Total_PnL')
    for hour, row in best_hours.iterrows():
        print(f"  Hour {hour:02d}: ${row['Total_PnL']:.2f} PnL, "
              f"{int(row['Trades'])} trades, {row['Win_Rate']:.1f}% win rate")
    
    # 4. Weekday Analysis
    print("\n" + "="*80)
    print("4. WEEKDAY ANALYSIS (Early Period Issues)")
    print("="*80)
    
    early_by_weekday = early_period.groupby('weekday').agg({
        'realized_pnl': ['sum', 'mean', 'count'],
        'is_winner': 'mean'
    }).round(2)
    early_by_weekday.columns = ['Total_PnL', 'Avg_PnL', 'Trades', 'Win_Rate']
    early_by_weekday['Win_Rate'] = (early_by_weekday['Win_Rate'] * 100).round(1)
    
    # Order by weekday
    weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    early_by_weekday = early_by_weekday.reindex([d for d in weekday_order if d in early_by_weekday.index])
    
    print("\nWeekday performance in 2024:")
    for weekday, row in early_by_weekday.iterrows():
        status = "✗" if row['Total_PnL'] < 0 else "✓"
        print(f"  {weekday:10s}: ${row['Total_PnL']:8.2f} PnL, "
              f"{int(row['Trades']):3d} trades, {row['Win_Rate']:5.1f}% WR {status}")
    
    # 5. Trade Duration Analysis
    print("\n" + "="*80)
    print("5. TRADE DURATION ANALYSIS")
    print("="*80)
    
    # Categorize by duration
    df['duration_category'] = pd.cut(df['duration_hours'], 
                                      bins=[0, 4, 12, 24, 48, 1000],
                                      labels=['<4h', '4-12h', '12-24h', '24-48h', '>48h'])
    early_period = early_period.copy()
    early_period['duration_category'] = df[df['ts_closed'].dt.year == 2024]['duration_category']
    
    early_by_duration = early_period.groupby('duration_category').agg({
        'realized_pnl': ['sum', 'mean', 'count'],
        'is_winner': 'mean'
    }).round(2)
    early_by_duration.columns = ['Total_PnL', 'Avg_PnL', 'Trades', 'Win_Rate']
    early_by_duration['Win_Rate'] = (early_by_duration['Win_Rate'] * 100).round(1)
    
    print("\nEarly period by duration:")
    for duration, row in early_by_duration.iterrows():
        print(f"  {duration:8s}: ${row['Total_PnL']:8.2f} PnL, "
              f"{int(row['Trades']):3d} trades, {row['Win_Rate']:5.1f}% WR")
    
    # 6. Position Direction Analysis
    print("\n" + "="*80)
    print("6. POSITION DIRECTION ANALYSIS")
    print("="*80)
    
    for period_name, period_df in [("2024", early_period), ("2025", later_period)]:
        long_trades = period_df[period_df['side'] == 'LONG']
        short_trades = period_df[period_df['side'] == 'SHORT']
        
        print(f"\n{period_name}:")
        print(f"  LONG trades:  {len(long_trades):3d}, "
              f"PnL: ${long_trades['realized_pnl'].sum():8.2f}, "
              f"WR: {(long_trades['is_winner'].mean() * 100):5.1f}%")
        print(f"  SHORT trades: {len(short_trades):3d}, "
              f"PnL: ${short_trades['realized_pnl'].sum():8.2f}, "
              f"WR: {(short_trades['is_winner'].mean() * 100):5.1f}%")
    
    # 7. Consecutive Losses Analysis
    print("\n" + "="*80)
    print("7. CONSECUTIVE LOSSES ANALYSIS")
    print("="*80)
    
    early_period_sorted = early_period.sort_values('ts_closed')
    early_period_sorted['loss_streak'] = (
        (~early_period_sorted['is_winner'])
        .groupby((early_period_sorted['is_winner'] != early_period_sorted['is_winner'].shift()).cumsum())
        .cumsum()
    )
    
    max_streak = early_period_sorted['loss_streak'].max()
    print(f"\nMax consecutive losses in 2024: {int(max_streak)}")
    
    # Find the longest losing streak
    if max_streak > 0:
        streak_start = early_period_sorted[early_period_sorted['loss_streak'] == max_streak].iloc[0]
        print(f"Occurred around: {streak_start['ts_closed'].strftime('%Y-%m-%d')}")
    
    # 8. Recommendations
    print("\n" + "="*80)
    print("8. IMPROVEMENT RECOMMENDATIONS")
    print("="*80)
    
    recommendations = []
    
    # Check if certain hours are consistently bad
    bad_hours = early_by_hour[early_by_hour['Total_PnL'] < -50]
    if len(bad_hours) > 0:
        recommendations.append(
            f"⚠️  HOUR FILTERING: Consider excluding hours {', '.join(str(h) for h in bad_hours.index)} "
            f"(combined loss: ${bad_hours['Total_PnL'].sum():.2f} in 2024)"
        )
    
    # Check win rate
    early_wr = early_period['is_winner'].mean() * 100
    later_wr = later_period['is_winner'].mean() * 100
    if early_wr < 45:
        recommendations.append(
            f"⚠️  WIN RATE: Early period WR was {early_wr:.1f}% vs {later_wr:.1f}% later. "
            f"Consider stricter entry filters (trend confirmation, volatility filters)"
        )
    
    # Check loser/winner ratio
    early_avg_loser = abs(early_period[~early_period['is_winner']]['realized_pnl'].mean())
    early_avg_winner = early_period[early_period['is_winner']]['realized_pnl'].mean()
    if early_avg_loser > early_avg_winner * 0.8:
        recommendations.append(
            f"⚠️  RISK/REWARD: Average loser (${early_avg_loser:.2f}) too close to average winner (${early_avg_winner:.2f}). "
            f"Consider tighter stops or wider targets in early trending phases"
        )
    
    # Check for directional bias
    early_long_pnl = early_period[early_period['side'] == 'LONG']['realized_pnl'].sum()
    early_short_pnl = early_period[early_period['side'] == 'SHORT']['realized_pnl'].sum()
    if abs(early_long_pnl - early_short_pnl) > 1000:
        bias = "LONG" if early_long_pnl > early_short_pnl else "SHORT"
        recommendations.append(
            f"⚠️  DIRECTIONAL BIAS: {bias} trades performed much better in 2024. "
            f"Consider trend filter or only trading with dominant trend"
        )
    
    # Duration analysis
    short_duration_pnl = early_period[early_period['duration_hours'] < 4]['realized_pnl'].sum()
    if short_duration_pnl < -200:
        recommendations.append(
            f"⚠️  SHORT DURATION TRADES: Trades <4 hours lost ${short_duration_pnl:.2f} in 2024. "
            f"Consider minimum hold time or avoid choppy periods"
        )
    
    print("\nKey Recommendations:")
    for i, rec in enumerate(recommendations, 1):
        print(f"\n{i}. {rec}")
    
    # 9. Proposed Additional Filters
    print("\n" + "="*80)
    print("9. PROPOSED ADDITIONAL INDICATORS/FILTERS")
    print("="*80)
    
    print("\nBased on the analysis, consider adding:")
    print("\n📊 VOLATILITY FILTERS:")
    print("   - ATR percentile filter (only trade when ATR is in middle range)")
    print("   - Avoid trading in extreme low/high volatility conditions")
    print("   - Bollinger Band width filter to avoid consolidation")
    
    print("\n📈 TREND CONFIRMATION:")
    print("   - Higher timeframe trend filter (1H or 4H)")
    print("   - ADX threshold to ensure trending market (ADX > 20)")
    print("   - Only take longs above 200 EMA, shorts below 200 EMA")
    
    print("\n🎯 SUPPORT/RESISTANCE LEVELS:")
    print("   - Daily/Weekly pivot points")
    print("   - Round number levels (1.0800, 1.0850, etc.)")
    print("   - Swing high/low levels from previous 20 bars")
    print("   - Avoid entries near major S/R levels (prone to reversal)")
    
    print("\n⏰ TIME-BASED IMPROVEMENTS:")
    print("   - Avoid first/last hour of major sessions (whipsaw risk)")
    print("   - Focus on 14:00-17:00 UTC (London-NY overlap peak)")
    print("   - Avoid trading during major news events")
    
    print("\n💰 RISK MANAGEMENT ENHANCEMENTS:")
    print("   - Scale position size based on recent performance")
    print("   - Implement daily/weekly loss limits")
    print("   - Use correlation filters (avoid EUR/USD when USD pairs trending together)")
    
    print("\n🔄 ENTRY TIMING IMPROVEMENTS:")
    print("   - Wait for pullback after MA cross (avoid late entries)")
    print("   - Require price to be X% beyond MA before entry")
    print("   - Add momentum confirmation (RSI not in extreme)")
    
    print("\n📉 EXIT IMPROVEMENTS:")
    print("   - Time-based exit (close after 24-48 hours if no movement)")
    print("   - Trail stop tighter after X hours")
    print("   - Scale out at 1:1 R:R, trail remainder")
    
    # Save detailed analysis
    output_file = folder / 'losing_period_analysis.txt'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("LOSING PERIOD ANALYSIS\n")
        f.write("="*80 + "\n\n")
        f.write(f"Worst Hours in 2024:\n")
        for hour, row in worst_hours.iterrows():
            f.write(f"  Hour {hour:02d}: ${row['Total_PnL']:.2f}\n")
        f.write(f"\nRecommendations:\n")
        for i, rec in enumerate(recommendations, 1):
            f.write(f"{i}. {rec}\n")
    
    print(f"\n\nDetailed analysis saved to: {output_file}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python analyze_losing_periods.py <results_directory>")
        sys.exit(1)
    
    analyze_losing_periods(sys.argv[1])
