#!/usr/bin/env python3
"""
Systematic timeframe analysis to find optimal trading frequency.
Runs the same ML strategy across multiple timeframes and compares results.
"""
import pandas as pd
from pathlib import Path
import json

# Timeframes to test
TIMEFRAMES = ['5_MINUTE', '15_MINUTE', '30_MINUTE', '1_HOUR']

def analyze_timeframe_performance():
    """
    Compare key metrics across timeframes to find optimal trading frequency.
    
    Metrics to compare:
    1. Total Return
    2. Sharpe Ratio (risk-adjusted return)
    3. Max Drawdown
    4. Win Rate
    5. Profit Factor
    6. Average Trade Duration
    7. Number of Trades
    8. Commission Impact (% of gross profit)
    """
    
    results = {}
    
    for tf in TIMEFRAMES:
        print(f"\n{'='*60}")
        print(f"Analyzing {tf}")
        print(f"{'='*60}")
        
        # TODO: Run backtest for this timeframe
        # For now, this is a template showing what to measure
        
        results[tf] = {
            'total_return_pct': 0.0,
            'sharpe_ratio': 0.0,
            'max_drawdown_pct': 0.0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'avg_trade_duration_hours': 0.0,
            'total_trades': 0,
            'commission_pct_of_gross': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'largest_win': 0.0,
            'largest_loss': 0.0
        }
    
    # Create comparison DataFrame
    df = pd.DataFrame(results).T
    
    # Calculate scores
    df['efficiency_score'] = (
        df['sharpe_ratio'] * 0.3 +  # Risk-adjusted return
        df['win_rate'] * 0.2 +       # Consistency
        df['profit_factor'] * 0.2 +  # Edge strength
        (1 - df['commission_pct_of_gross']) * 0.3  # Cost efficiency
    )
    
    print("\n" + "="*80)
    print("TIMEFRAME COMPARISON")
    print("="*80)
    print(df.to_string())
    
    # Recommendations
    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)
    
    best_overall = df['efficiency_score'].idxmax()
    print(f"\n1. Best Overall (Efficiency Score): {best_overall}")
    
    best_sharpe = df['sharpe_ratio'].idxmax()
    print(f"2. Best Risk-Adjusted Return: {best_sharpe}")
    
    lowest_commission = df['commission_pct_of_gross'].idxmin()
    print(f"3. Lowest Commission Impact: {lowest_commission}")
    
    return df

if __name__ == "__main__":
    analyze_timeframe_performance()
