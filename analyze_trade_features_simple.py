import pandas as pd
import numpy as np
from scipy import stats
import glob
import os

def get_latest_trade_features():
    # Find all trade_features.csv files
    files = glob.glob('logs/backtest_results/**/trade_features.csv', recursive=True)
    if not files:
        raise FileNotFoundError("No trade_features.csv found in logs/backtest_results")
    
    # Sort by modification time
    latest_file = max(files, key=os.path.getmtime)
    print(f"Analyzing latest file: {latest_file}")
    return pd.read_csv(latest_file)

def analyze_single_factor(df, feature, thresholds):
    """Test if feature split predicts PnL"""
    results = []
    for threshold in thresholds:
        # Handle NaN values if any
        valid_df = df.dropna(subset=[feature, 'pnl_pips'])
        
        low = valid_df[valid_df[feature] < threshold]
        high = valid_df[valid_df[feature] >= threshold]
        
        if len(low) < 30 or len(high) < 30:
            results.append({
                'feature': feature,
                'threshold': threshold,
                'low_n': len(low),
                'high_n': len(high),
                'status': 'Skipped (N<30)'
            })
            continue  # Skip insufficient sample
            
        # T-test
        t_stat, p_value = stats.ttest_ind(low['pnl_pips'], high['pnl_pips'], equal_var=False)
        
        results.append({
            'feature': feature,
            'threshold': threshold,
            'low_n': len(low),
            'low_mean_pnl': low['pnl_pips'].mean(),
            'high_n': len(high),
            'high_mean_pnl': high['pnl_pips'].mean(),
            'diff_pnl': high['pnl_pips'].mean() - low['pnl_pips'].mean(),
            'p_value': p_value,
            'significant': p_value < 0.01  # Bonferroni-adjusted
        })
    
    return pd.DataFrame(results)

def main():
    try:
        df = get_latest_trade_features()
        print(f"Total trades loaded: {len(df)}")
        
        # Test each feature
        test_features = {
            'adx_value': [15, 20, 25, 30],
            'atr_pips': [5, 10, 15, 20],
            'hour_utc': [2, 6, 10, 14, 18, 22],
            'dist_to_swing_high_pips': [5, 10, 15, 20, 30, 50],
            'dist_to_swing_low_pips': [5, 10, 15, 20, 30, 50],
            'fast_slow_sep_pips': [1, 2, 3, 5, 10]
        }

        for feature, thresholds in test_features.items():
            if feature not in df.columns:
                print(f"\n=== {feature} (Skipped - Not in CSV) ===")
                continue
                
            print(f"\n=== {feature} ===")
            results = analyze_single_factor(df, feature, thresholds)
            if not results.empty:
                # Format for readability
                if 'status' in results.columns:
                     # Separate skipped rows for cleaner output if mixed
                     skipped = results[results['status'].notna()]
                     analyzed = results[results['status'].isna()]
                     
                     if not analyzed.empty:
                         print(analyzed.drop(columns=['status']).to_string(index=False))
                     if not skipped.empty:
                         print("\nSkipped thresholds (insufficient data):")
                         print(skipped[['feature', 'threshold', 'low_n', 'high_n']].to_string(index=False))
                else:
                    print(results.to_string(index=False))
            else:
                print("No valid thresholds found.")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
