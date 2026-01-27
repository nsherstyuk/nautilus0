"""
Analyze SL behavior patterns by trading hours and weekdays.

This script examines trades that approach SL to understand:
1. Which hours/weekdays have more near-SL experiences
2. Whether SL sizes should be dynamic by time
3. Patterns in "fade trade" behavior
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

def analyze_sl_behavior():
    """Analyze stop loss behavior patterns by time."""
    
    # Load the most recent backtest results
    results_dir = Path("backtest_results")
    latest_result = max(results_dir.glob("MTF_V2_REPLAY_*"), key=lambda x: x.stat().st_mtime)
    
    print(f"Analyzing results from: {latest_result.name}")
    
    # Load positions and summary
    positions_file = latest_result / "positions.csv"
    positions = pd.read_csv(positions_file)
    
    # Convert timestamps
    positions['ts_opened'] = pd.to_datetime(positions['ts_opened'])
    positions['ts_closed'] = pd.to_datetime(positions['ts_closed'])
    
    # Extract time features
    positions['hour'] = positions['ts_opened'].dt.hour
    positions['weekday'] = positions['ts_opened'].dt.day_name()
    positions['weekday_num'] = positions['ts_opened'].dt.dayofweek
    
    # Calculate trade duration
    positions['duration_minutes'] = (positions['ts_closed'] - positions['ts_opened']).dt.total_seconds() / 60
    
    # Identify near-SL trades (assuming we have max_drawdown_per_trade data)
    # If not available, we'll use proxy metrics
    
    # Convert P&L to numeric (remove ' USD' suffix and brackets if present)
    if positions['realized_pnl'].dtype == 'object':
        positions['realized_pnl'] = positions['realized_pnl'].str.replace("['", "").str.replace(" USD']", "").str.replace(' USD', '').astype(float)
    
    print(f"\nTotal trades analyzed: {len(positions)}")
    print(f"Win rate: {(positions['realized_pnl'] > 0).mean():.1%}")
    print(f"Average P&L: ${positions['realized_pnl'].mean():.2f}")
    
    # Analyze by hour
    print("\n=== TRADE ANALYSIS BY HOUR ===")
    hourly_stats = positions.groupby('hour').agg({
        'realized_pnl': ['count', 'mean', lambda x: (x > 0).mean()],
        'duration_minutes': 'mean'
    }).round(2)
    
    hourly_stats.columns = ['Trades', 'Avg_PnL', 'Win_Rate', 'Avg_Duration']
    print(hourly_stats)
    
    # Analyze by weekday
    print("\n=== TRADE ANALYSIS BY WEEKDAY ===")
    weekday_stats = positions.groupby('weekday').agg({
        'realized_pnl': ['count', 'mean', lambda x: (x > 0).mean()],
        'duration_minutes': 'mean'
    }).round(2)
    
    weekday_stats.columns = ['Trades', 'Avg_PnL', 'Win_Rate', 'Avg_Duration']
    print(weekday_stats)
    
    # Find "problematic" trades - long duration but still profitable
    # These likely went near SL before recovering
    positions['is_long_duration'] = positions['duration_minutes'] > positions['duration_minutes'].quantile(0.75)
    
    print(f"\n=== LONG DURATION TRADES (Top 25% duration) ===")
    long_trades = positions[positions['is_long_duration']]
    print(f"Count: {len(long_trades)} ({len(long_trades)/len(positions):.1%} of all trades)")
    print(f"Win rate: {(long_trades['realized_pnl'] > 0).mean():.1%}")
    print(f"Avg P&L: ${long_trades['realized_pnl'].mean():.2f}")
    print(f"Avg duration: {long_trades['duration_minutes'].mean():.1f} minutes")
    
    # Analyze long trades by hour
    print("\n=== LONG DURATION TRADES BY HOUR ===")
    long_hourly = long_trades.groupby('hour').agg({
        'realized_pnl': ['count', 'mean', lambda x: (x > 0).mean()],
        'duration_minutes': 'mean'
    }).round(2)
    
    long_hourly.columns = ['Trades', 'Avg_PnL', 'Win_Rate', 'Avg_Duration']
    print(long_hourly[long_hourly['Trades'] > 0])
    
    # Analyze long trades by weekday
    print("\n=== LONG DURATION TRADES BY WEEKDAY ===")
    long_weekday = long_trades.groupby('weekday').agg({
        'realized_pnl': ['count', 'mean', lambda x: (x > 0).mean()],
        'duration_minutes': 'mean'
    }).round(2)
    
    long_weekday.columns = ['Trades', 'Avg_PnL', 'Win_Rate', 'Avg_Duration']
    print(long_weekday[long_weekday['Trades'] > 0])
    
    # Find potential "fade trade" hours (high duration, high win rate)
    print("\n=== POTENTIAL FADE TRADE PATTERNS ===")
    fade_candidates = hourly_stats[
        (hourly_stats['Avg_Duration'] > hourly_stats['Avg_Duration'].median()) &
        (hourly_stats['Win_Rate'] > 0.7)
    ].sort_values('Win_Rate', ascending=False)
    
    print("Hours with long duration but high win rate (potential fade patterns):")
    print(fade_candidates)
    
    # Calculate optimal SL by hour (simplified)
    print("\n=== RECOMMENDED SL MULTIPLIERS BY HOUR ===")
    
    # Base recommendation: larger SL for fade hours, smaller for trend hours
    hourly_recommendations = []
    for hour in range(24):
        hour_trades = positions[positions['hour'] == hour]
        if len(hour_trades) >= 5:  # Only analyze hours with sufficient data
            avg_duration = hour_trades['duration_minutes'].mean()
            win_rate = (hour_trades['realized_pnl'] > 0).mean()
            
            # Simple heuristic: longer duration = need larger SL
            if avg_duration > 200 and win_rate > 0.7:
                recommended_sl = 1.6  # Fade hour - need more room
                reason = "Fade pattern detected"
            elif avg_duration > 150:
                recommended_sl = 1.4  # Moderate fade
                reason = "Extended duration"
            elif avg_duration < 100 and win_rate < 0.6:
                recommended_sl = 1.0  # Quick failure - tighten SL
                reason = "Quick failure pattern"
            else:
                recommended_sl = 1.2  # Standard
                reason = "Normal behavior"
                
            hourly_recommendations.append({
                'Hour': hour,
                'Trades': len(hour_trades),
                'Avg_Duration': avg_duration,
                'Win_Rate': win_rate,
                'Recommended_SL': recommended_sl,
                'Reason': reason
            })
    
    rec_df = pd.DataFrame(hourly_recommendations)
    print(rec_df.to_string(index=False))
    
    # Save recommendations
    rec_df.to_csv("sl_recommendations_by_hour.csv", index=False)
    print(f"\nRecommendations saved to: sl_recommendations_by_hour.csv")
    
    return positions, rec_df

def create_dynamic_sl_config(recommendations):
    """Create dynamic SL configuration based on analysis."""
    
    print("\n=== DYNAMIC SL CONFIGURATION ===")
    
    config_lines = ["# Dynamic SL Multipliers by Hour", "# Based on trade duration and win rate analysis", ""]
    
    for _, row in recommendations.iterrows():
        hour = row['Hour']
        sl_mult = row['Recommended_SL']
        reason = row['Reason']
        
        config_lines.append(f"# Hour {hour:02d}:00 - {reason}")
        config_lines.append(f"MTF2_DYNAMIC_SL_HOUR_{hour:02d}={sl_mult}")
        config_lines.append("")
    
    # Write config file
    with open("dynamic_sl_config.env", "w") as f:
        f.write("\n".join(config_lines))
    
    print("Dynamic SL configuration saved to: dynamic_sl_config.env")
    print("\nTo use dynamic SL:")
    print("1. Add these settings to your .env.mtf_v2")
    print("2. Modify strategy to read hour-specific SL values")
    print("3. Test with replay backtest")

if __name__ == "__main__":
    print("SL BEHAVIOR ANALYSIS")
    print("=" * 50)
    
    positions, recommendations = analyze_sl_behavior()
    create_dynamic_sl_config(recommendations)
    
    print("\n" + "=" * 50)
    print("ANALYSIS COMPLETE")
    print("=" * 50)
