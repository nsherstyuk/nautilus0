"""
Simple SL Analysis - identify fade patterns by hour.
"""

import pandas as pd
import numpy as np

def analyze_sl_patterns():
    """Analyze stop loss patterns from the backtest results."""
    
    # Load data
    positions = pd.read_csv("backtest_results/MTF_V2_REPLAY_20260102_152105/positions.csv")
    hourly_perf = pd.read_csv("backtest_results/MTF_V2_REPLAY_20260102_152105/performance_by_hour.csv")
    
    # Clean and prepare data
    positions['ts_opened'] = pd.to_datetime(positions['ts_opened'])
    positions['ts_closed'] = pd.to_datetime(positions['ts_closed'])
    positions['hour'] = positions['ts_opened'].dt.hour
    
    # Clean P&L
    def clean_pnl(pnl_str):
        if isinstance(pnl_str, str):
            return float(pnl_str.replace("['", "").replace(" USD']", "").replace(' USD', ''))
        return pnl_str
    
    positions['realized_pnl'] = positions['realized_pnl'].apply(clean_pnl)
    positions['duration_minutes'] = (positions['ts_closed'] - positions['ts_opened']).dt.total_seconds() / 60
    
    # Identify near-SL trades (long duration + profitable)
    duration_threshold = positions['duration_minutes'].quantile(0.75)
    near_sl = positions[(positions['duration_minutes'] > duration_threshold) & (positions['realized_pnl'] > 0)]
    
    print("=== SL BEHAVIOR ANALYSIS ===")
    print(f"Total trades: {len(positions)}")
    print(f"Win rate: {(positions['realized_pnl'] > 0).mean():.1%}")
    print(f"Near-SL candidates: {len(near_sl)} ({len(near_sl)/len(positions):.1%} of trades)")
    print(f"Duration threshold: {duration_threshold:.1f} minutes")
    
    # Analyze by hour
    hourly_stats = []
    for hour in range(24):
        hour_trades = positions[positions['hour'] == hour]
        hour_near_sl = near_sl[near_sl['hour'] == hour]
        
        if len(hour_trades) > 0:
            fade_pct = len(hour_near_sl) / len(hour_trades) * 100
            win_rate = (hour_trades['realized_pnl'] > 0).mean() * 100
            avg_pnl = hour_trades['realized_pnl'].mean()
            
            # Determine SL recommendation
            if fade_pct >= 25 and win_rate >= 75:
                sl_mult = 1.6
                reason = "High fade + high win rate"
            elif fade_pct >= 15 and win_rate >= 70:
                sl_mult = 1.4
                reason = "Moderate fade + good win rate"
            elif fade_pct <= 10 and win_rate <= 65:
                sl_mult = 1.0
                reason = "Low fade + poor win rate"
            else:
                sl_mult = 1.2
                reason = "Standard"
            
            hourly_stats.append({
                'Hour': hour,
                'Total_Trades': len(hour_trades),
                'Near_SL_Trades': len(hour_near_sl),
                'Fade_Percent': fade_pct,
                'Win_Rate': win_rate,
                'Avg_PnL': avg_pnl,
                'Recommended_SL': sl_mult,
                'Reason': reason
            })
    
    # Create dataframe and display
    results_df = pd.DataFrame(hourly_stats)
    results_df = results_df.sort_values('Fade_Percent', ascending=False)
    
    print("\n=== HOURLY ANALYSIS ===")
    print(results_df.to_string(index=False))
    
    # Highlight key findings
    high_fade = results_df[results_df['Fade_Percent'] >= 20]
    low_fade = results_df[results_df['Fade_Percent'] <= 10]
    
    print(f"\n=== KEY INSIGHTS ===")
    print(f"High fade hours (>=20%): {len(high_fade)} hours")
    if len(high_fade) > 0:
        print(f"  Hours: {high_fade['Hour'].tolist()}")
        print(f"  Recommended SL: 1.4-1.6x ATR")
    
    print(f"Low fade hours (<=10%): {len(low_fade)} hours")
    if len(low_fade) > 0:
        print(f"  Hours: {low_fade['Hour'].tolist()}")
        print(f"  Recommended SL: 1.0x ATR (tighter)")
    
    # Save results
    results_df.to_csv("sl_analysis_by_hour.csv", index=False)
    print(f"\nResults saved to: sl_analysis_by_hour.csv")
    
    return results_df

if __name__ == "__main__":
    results = analyze_sl_patterns()
    
    print(f"\n=== RECOMMENDATIONS ===")
    print("1. Consider dynamic SL based on trading hour")
    print("2. High fade hours (20%+) need 1.4-1.6x SL")
    print("3. Low fade hours (10%-) can use 1.0x SL")
    print("4. Test dynamic SL with replay backtest")
