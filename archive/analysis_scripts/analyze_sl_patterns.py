"""
Analyze SL behavior patterns from the MTF_V2_REPLAY_20260102_152105 results.

This examines trades that likely experienced near-SL conditions before recovering.
"""

import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt

def analyze_sl_patterns():
    """Analyze stop loss patterns from the backtest results."""
    
    # Load positions data
    positions = pd.read_csv("backtest_results/MTF_V2_REPLAY_20260102_152105/positions.csv")
    
    # Convert timestamps and extract time features
    positions['ts_opened'] = pd.to_datetime(positions['ts_opened'])
    positions['ts_closed'] = pd.to_datetime(positions['ts_closed'])
    positions['hour'] = positions['ts_opened'].dt.hour
    positions['weekday'] = positions['ts_opened'].dt.day_name()
    
    # Convert P&L to numeric (handle different formats)
    def clean_pnl(pnl_str):
        if isinstance(pnl_str, str):
            # Remove brackets, quotes, and ' USD' suffix
            return float(pnl_str.replace("['", "").replace(" USD']", "").replace(' USD', ''))
        return pnl_str
    
    positions['realized_pnl'] = positions['realized_pnl'].apply(clean_pnl)
    
    # Calculate trade duration in minutes
    positions['duration_minutes'] = (positions['ts_closed'] - positions['ts_opened']).dt.total_seconds() / 60
    
    print("=== SL BEHAVIOR ANALYSIS ===")
    print(f"Total trades: {len(positions)}")
    print(f"Win rate: {(positions['realized_pnl'] > 0).mean():.1%}")
    print(f"Average P&L: ${positions['realized_pnl'].mean():.2f}")
    print(f"Average duration: {positions['duration_minutes'].mean():.1f} minutes")
    
    # Identify "near-SL" trades - long duration but still profitable
    # These likely went against position before recovering
    duration_75th = positions['duration_minutes'].quantile(0.75)
    positions['is_near_sl_candidate'] = (positions['duration_minutes'] > duration_75th) & (positions['realized_pnl'] > 0)
    
    near_sl_trades = positions[positions['is_near_sl_candidate']]
    
    print(f"\n=== NEAR-SL CANDIDATES (Long duration + profitable) ===")
    print(f"Count: {len(near_sl_trades)} ({len(near_sl_trades)/len(positions):.1%} of all trades)")
    print(f"Win rate: 100% (by definition)")
    print(f"Avg P&L: ${near_sl_trades['realized_pnl'].mean():.2f}")
    print(f"Avg duration: {near_sl_trades['duration_minutes'].mean():.1f} minutes")
    print(f"Duration threshold: >{duration_75th:.1f} minutes")
    
    # Analyze near-SL trades by hour
    print(f"\n=== NEAR-SL TRADES BY HOUR ===")
    near_sl_by_hour = near_sl_trades.groupby('hour').agg({
        'realized_pnl': ['count', 'mean'],
        'duration_minutes': 'mean'
    }).round(2)
    near_sl_by_hour.columns = ['Count', 'Avg_PnL', 'Avg_Duration']
    near_sl_by_hour = near_sl_by_hour[near_sl_by_hour['Count'] > 0]
    near_sl_by_hour['Pct_of_Total'] = (near_sl_by_hour['Count'] / len(near_sl_trades) * 100).round(1)
    near_sl_by_hour = near_sl_by_hour.reset_index()  # Reset index to make 'hour' a column
    print("Column names:", near_sl_by_hour.columns.tolist())
    print(near_sl_by_hour[['hour', 'Count', 'Avg_PnL', 'Avg_Duration', 'Pct_of_Total']].to_string(index=False))
    
    # Analyze near-SL trades by weekday
    print(f"\n=== NEAR-SL TRADES BY WEEKDAY ===")
    near_sl_by_weekday = near_sl_trades.groupby('weekday').agg({
        'realized_pnl': ['count', 'mean'],
        'duration_minutes': 'mean'
    }).round(2)
    near_sl_by_weekday.columns = ['Count', 'Avg_PnL', 'Avg_Duration']
    near_sl_by_weekday = near_sl_by_weekday[near_sl_by_weekday['Count'] > 0]
    near_sl_by_weekday['Pct_of_Total'] = (near_sl_by_weekday['Count'] / len(near_sl_trades) * 100).round(1)
    print(near_sl_by_weekday)
    
    # Load hourly performance data
    hourly_perf = pd.read_csv("backtest_results/MTF_V2_REPLAY_20260102_152105/performance_by_hour.csv")
    
    # Merge with near-SL analysis
    hour_analysis = pd.merge(
        near_sl_by_hour, 
        hourly_perf, 
        on='hour', 
        how='right'
    ).fillna(0)
    
    # Calculate "fade intensity" - percentage of trades that are near-SL candidates
    hour_analysis['fade_intensity'] = (hour_analysis['Count'] / hour_analysis['trades'] * 100).round(1)
    hour_analysis = hour_analysis.sort_values('fade_intensity', ascending=False)
    
    print(f"\n=== FADE INTENSITY BY HOUR ===")
    print("(Percentage of trades that were near-SL candidates)")
    fade_cols = ['hour', 'fade_intensity', 'trades', 'Count', 'win_rate', 'pnl']
    print(hour_analysis[fade_cols].rename(columns={
        'hour': 'Hour',
        'fade_intensity': 'Fade_%',
        'trades': 'Total_Trades',
        'Count': 'Near_SL_Trades',
        'win_rate': 'Win_Rate',
        'pnl': 'PnL'
    }).to_string(index=False))
    
    # Identify high-fade hours (top 33%)
    fade_threshold = hour_analysis['fade_intensity'].quantile(0.67)
    high_fade_hours = hour_analysis[hour_analysis['fade_intensity'] >= fade_threshold]
    
    print(f"\n=== HIGH FADE HOURS (Top 33%) ===")
    print(f"Fade threshold: >{fade_threshold:.1f}%")
    high_fade_display = high_fade_hours[['hour', 'fade_intensity', 'win_rate', 'pnl']].rename(columns={
        'hour': 'Hour',
        'fade_intensity': 'Fade_%',
        'win_rate': 'Win_Rate',
        'pnl': 'PnL'
    })
    print(high_fade_display.to_string(index=False))
    
    # Recommendations
    print(f"\n=== DYNAMIC SL RECOMMENDATIONS ===")
    recommendations = []
    
    for _, row in hour_analysis.iterrows():
        hour = int(row['hour'])
        fade_pct = row['fade_intensity']
        win_rate = row['win_rate']
        
        if fade_pct >= 30 and win_rate >= 75:
            sl_mult = 1.6
            reason = "High fade intensity + high win rate"
        elif fade_pct >= 20 and win_rate >= 70:
            sl_mult = 1.4
            reason = "Moderate fade + good win rate"
        elif fade_pct <= 10 and win_rate <= 65:
            sl_mult = 1.0
            reason = "Low fade + poor win rate - tighten SL"
        else:
            sl_mult = 1.2
            reason = "Standard configuration"
            
        recommendations.append({
            'Hour': hour,
            'Fade_%': fade_pct,
            'Win_Rate': win_rate,
            'Recommended_SL': sl_mult,
            'Reason': reason
        })
    
    rec_df = pd.DataFrame(recommendations)
    rec_df = rec_df.sort_values('Recommended_SL', ascending=False)
    print(rec_df.to_string(index=False))
    
    # Save recommendations
    rec_df.to_csv("dynamic_sl_recommendations.csv", index=False)
    print(f"\nRecommendations saved to: dynamic_sl_recommendations.csv")
    
    return rec_df, near_sl_trades

if __name__ == "__main__":
    recommendations, near_sl_trades = analyze_sl_patterns()
    
    print(f"\n=== SUMMARY ===")
    print(f"- Found {len(near_sl_trades)} near-SL candidates ({len(near_sl_trades)/882:.1%} of trades)")
    print(f"- These trades likely needed larger SL to avoid premature exit")
    print(f"- Consider implementing dynamic SL based on trading hours")
    print(f"- High-fade hours may benefit from 1.4-1.6x SL multiplier")
    print(f"- Low-fade hours may use tighter 1.0x SL to improve R:R")
