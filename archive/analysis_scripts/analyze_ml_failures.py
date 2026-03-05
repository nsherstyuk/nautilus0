
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import sys

# Set text-only mode for Windows compatibility if needed
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

def load_data(filepath):
    """Load the feature log CSV."""
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found at {path}")
        return None
    
    try:
        df = pd.read_csv(path)
        # Convert timestamp
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        # Convert numeric columns
        cols = ['pnl_currency', 'pnl_pips', 'duration_bars', 'entry_atr', 'prediction_conf']
        for col in cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Calculate win/loss
        df['win'] = df['pnl_currency'] > 0
        return df
    except Exception as e:
        print(f"Error loading data: {e}")
        return None

def analyze_confidence(df):
    """Analyze Performance by Confidence Buckets."""
    print("\n" + "="*60)
    print("ANALYSIS: PREDICTION CONFIDENCE")
    print("="*60)
    
    if 'prediction_conf' not in df.columns:
        print("Column 'prediction_conf' not found.")
        return

    # Create buckets
    df['conf_bucket'] = pd.cut(df['prediction_conf'], bins=[0.5, 0.55, 0.6, 0.65, 0.7, 0.8, 1.0])
    
    stats = df.groupby('conf_bucket', observed=False).agg({
        'pnl_currency': ['count', 'sum', 'mean'],
        'win': 'mean'
    })
    
    stats.columns = ['Count', 'Total PnL', 'Avg PnL', 'Win Rate']
    stats['Win Rate'] = stats['Win Rate'] * 100
    print(stats)

def analyze_feature_regimes(df, feature_name, bins=5):
    """Analyze Performance by Feature Regimes."""
    print("\n" + "-"*60)
    print(f"FEATURE ANALYSIS: {feature_name}")
    print("-"*60)
    
    if feature_name not in df.columns:
        print(f"Feature {feature_name} not found.")
        return

    try:
        # qcut for equal-sized buckets, cut for equal-width
        df['bucket'] = pd.qcut(df[feature_name], q=bins, duplicates='drop')
        
        stats = df.groupby('bucket', observed=False).agg({
            'pnl_currency': ['count', 'sum', 'mean'],
            'win': 'mean'
        })
        
        stats.columns = ['Count', 'Total PnL', 'Avg PnL', 'Win Rate']
        stats['Win Rate'] = stats['Win Rate'] * 100
        print(stats)
        
    except Exception as e:
        print(f"Could not bin feature {feature_name}: {e}")

def analyze_time_decay(df):
    """Analyze Performance by Duration."""
    print("\n" + "="*60)
    print("ANALYSIS: TRADE DURATION (BARS)")
    print("="*60)
    
    bins = [0, 4, 12, 24, 48, 96, 999]
    labels = ['<1h', '1-3h', '3-6h', '6-12h', '12-24h', '>24h']
    
    df['duration_bucket'] = pd.cut(df['duration_bars'], bins=bins, labels=labels)
    
    stats = df.groupby('duration_bucket', observed=False).agg({
        'pnl_currency': ['count', 'sum', 'mean'],
        'win': 'mean'
    })
    
    stats.columns = ['Count', 'Total PnL', 'Avg PnL', 'Win Rate']
    stats['Win Rate'] = stats['Win Rate'] * 100
    print(stats)

def analyze_hourly_performance(df):
    """Analyze Performance by Hour of Day."""
    print("\n" + "="*60)
    print("ANALYSIS: HOURLY PERFORMANCE (UTC)")
    print("="*60)
    
    if 'hour' not in df.columns:
        return

    stats = df.groupby('hour').agg({
        'pnl_currency': ['count', 'sum', 'mean'],
        'win': 'mean'
    }).sort_index()
    
    stats.columns = ['Count', 'Total PnL', 'Avg PnL', 'Win Rate']
    stats['Win Rate'] = stats['Win Rate'] * 100
    
    # Filter for significant activity
    print(stats[stats['Count'] > 5])

def main():
    log_file = Path("backtest_results/ml_trade_features.csv")
    
    print(f"Loading {log_file}...")
    df = load_data(log_file)
    
    if df is None or len(df) == 0:
        print("No data found. Ensure backtest has completed and generated trades.")
        return

    print(f"Loaded {len(df)} trades.")
    
    # 1. Confidence Analysis
    analyze_confidence(df)
    
    # 2. Key Feature Regimes
    # MAMA Diff (Trend check)
    analyze_feature_regimes(df, 'mama_diff')
    
    # Volatility (ATR)
    analyze_feature_regimes(df, 'entry_atr')
    
    # Stochastic (Momentum/Overbought)
    analyze_feature_regimes(df, 'stoch_k_30m')
    
    # DMI (Trend Strength)
    analyze_feature_regimes(df, 'dmp_30m')
    
    # 3. Duration Analysis
    analyze_time_decay(df)
    
    # 4. Hourly Analysis
    analyze_hourly_performance(df)
    
    print("\n" + "="*60)
    print("RECOMMENDATIONS BASED ON DATA")
    print("="*60)
    print("Look for buckets with NEGATIVE 'Total PnL' or 'Avg PnL'.")
    print("These represent Toxic Regimes we can filter out.")

if __name__ == "__main__":
    main()
