"""
Analyze TP performance by hour to see if dynamic TP is viable.
"""

import pandas as pd
import numpy as np

def analyze_tp_patterns():
    """Analyze take profit patterns by trading hour."""
    
    # Load data
    positions = pd.read_csv("backtest_results/MTF_V2_REPLAY_20260102_152105/positions.csv")
    
    # Clean and prepare data
    positions['ts_opened'] = pd.to_datetime(positions['ts_opened'])
    positions['ts_closed'] = pd.to_datetime(positions['ts_closed'])
    positions['hour'] = positions['ts_opened'].dt.hour
    positions['weekday'] = positions['ts_opened'].dt.day_name()
    
    # Clean P&L
    def clean_pnl(pnl_str):
        if isinstance(pnl_str, str):
            return float(pnl_str.replace("['", "").replace(" USD']", "").replace(' USD', ''))
        return pnl_str
    
    positions['realized_pnl'] = positions['realized_pnl'].apply(clean_pnl)
    positions['duration_minutes'] = (positions['ts_closed'] - positions['ts_opened']).dt.total_seconds() / 60
    
    print("=== TP PERFORMANCE ANALYSIS ===")
    
    # Analyze profitable trades by hour
    profitable_trades = positions[positions['realized_pnl'] > 0]
    
    hourly_tp_analysis = []
    for hour in range(24):
        hour_trades = positions[positions['hour'] == hour]
        hour_profitable = profitable_trades[profitable_trades['hour'] == hour]
        
        if len(hour_trades) > 0:
            win_rate = len(hour_profitable) / len(hour_trades) * 100
            avg_win = hour_profitable['realized_pnl'].mean() if len(hour_profitable) > 0 else 0
            avg_loss = hour_trades[hour_trades['realized_pnl'] < 0]['realized_pnl'].mean() if len(hour_trades[hour_trades['realized_pnl'] < 0]) > 0 else 0
            avg_duration = hour_profitable['duration_minutes'].mean() if len(hour_profitable) > 0 else 0
            
            # Calculate profit factor
            total_wins = hour_profitable['realized_pnl'].sum()
            total_losses = abs(hour_trades[hour_trades['realized_pnl'] < 0]['realized_pnl'].sum())
            profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
            
            # TP recommendation based on performance
            if win_rate >= 80 and avg_win >= 10:
                tp_mult = 0.8  # High win rate, good profits - can increase TP
                reason = "High win rate + good profit size"
            elif win_rate >= 75 and avg_win >= 8:
                tp_mult = 0.7  # Good performance - slight TP increase
                reason = "Good performance"
            elif win_rate <= 65:
                tp_mult = 0.5  # Low win rate - reduce TP, quicker exits
                reason = "Low win rate - reduce TP"
            else:
                tp_mult = 0.6  # Standard
                reason = "Standard configuration"
            
            hourly_tp_analysis.append({
                'Hour': hour,
                'Total_Trades': len(hour_trades),
                'Win_Rate': win_rate,
                'Avg_Win': avg_win,
                'Avg_Loss': avg_loss,
                'Profit_Factor': profit_factor,
                'Avg_Duration': avg_duration,
                'Recommended_TP': tp_mult,
                'TP_Reason': reason
            })
    
    # Create dataframe
    tp_df = pd.DataFrame(hourly_tp_analysis)
    tp_df = tp_df.sort_values('Profit_Factor', ascending=False)
    
    print("\n=== HOURLY TP ANALYSIS ===")
    print(tp_df.round(2).to_string(index=False))
    
    # Weekday analysis
    print("\n=== WEEKDAY TP ANALYSIS ===")
    weekday_tp_analysis = []
    
    for weekday in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Sunday']:
        day_trades = positions[positions['weekday'] == weekday]
        day_profitable = profitable_trades[profitable_trades['weekday'] == weekday]
        
        if len(day_trades) > 0:
            win_rate = len(day_profitable) / len(day_trades) * 100
            avg_win = day_profitable['realized_pnl'].mean() if len(day_profitable) > 0 else 0
            avg_loss = day_trades[day_trades['realized_pnl'] < 0]['realized_pnl'].mean() if len(day_trades[day_trades['realized_pnl'] < 0]) > 0 else 0
            
            total_wins = day_profitable['realized_pnl'].sum()
            total_losses = abs(day_trades[day_trades['realized_pnl'] < 0]['realized_pnl'].sum())
            profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
            
            weekday_tp_analysis.append({
                'Weekday': weekday,
                'Total_Trades': len(day_trades),
                'Win_Rate': win_rate,
                'Avg_Win': avg_win,
                'Avg_Loss': avg_loss,
                'Profit_Factor': profit_factor
            })
    
    weekday_df = pd.DataFrame(weekday_tp_analysis)
    print(weekday_df.round(2).to_string(index=False))
    
    # Combined SL+TP recommendations
    print("\n=== COMBINED DYNAMIC SL+TP RECOMMENDATIONS ===")
    
    # Load previous SL analysis
    sl_df = pd.read_csv("sl_analysis_by_hour.csv")
    
    # Merge SL and TP recommendations
    combined = pd.merge(
        sl_df[['Hour', 'Fade_Percent', 'Win_Rate', 'Recommended_SL']],
        tp_df[['Hour', 'Profit_Factor', 'Recommended_TP', 'TP_Reason']],
        on='Hour'
    )
    
    # Format recommendations
    combined['Strategy'] = combined.apply(lambda row: 
        f"SL={row['Recommended_SL']}x, TP={row['Recommended_TP']}x", axis=1)
    
    print(combined[['Hour', 'Fade_Percent', 'Win_Rate', 'Profit_Factor', 'Strategy']].round(2).to_string(index=False))
    
    # Save combined recommendations
    combined.to_csv("dynamic_sl_tp_recommendations.csv", index=False)
    print(f"\nCombined recommendations saved to: dynamic_sl_tp_recommendations.csv")
    
    return combined

if __name__ == "__main__":
    results = analyze_tp_patterns()
    
    print(f"\n=== KEY INSIGHTS ===")
    print("1. Some hours show higher profit factors - could support larger TP")
    print("2. High fade hours + high profit factor = ideal for TP increase")
    print("3. Weekday patterns exist but are less pronounced than hourly")
    print("4. Dynamic TP adds complexity but may improve returns")
