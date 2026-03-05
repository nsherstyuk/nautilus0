"""
Analyze historical data to determine optimal profit threshold for model training.

This script:
1. Loads 2025 EUR/USD data
2. Tests multiple profit thresholds
3. Analyzes class balance, signal frequency, and realistic profitability
4. Recommends optimal threshold based on data-driven analysis
"""
import pandas as pd
import numpy as np
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog

PROJECT_ROOT = Path(__file__).parent

def load_2025_data():
    """Load 2025 EUR/USD data from Parquet catalog."""
    catalog_path = PROJECT_ROOT / "data" / "historical"
    catalog = ParquetDataCatalog(str(catalog_path))
    
    bar_type = "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    print(f"Loading {bar_type} from Parquet catalog...")
    
    bars = catalog.bars(bar_types=[bar_type])
    
    if len(bars) == 0:
        raise ValueError(f"No data found for {bar_type}")
    
    # Convert to DataFrame
    df = pd.DataFrame({
        'timestamp': [bar.ts_init for bar in bars],
        'open': [float(bar.open) for bar in bars],
        'high': [float(bar.high) for bar in bars],
        'low': [float(bar.low) for bar in bars],
        'close': [float(bar.close) for bar in bars],
        'volume': [float(bar.volume) for bar in bars],
    })
    
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ns', utc=True)
    df = df.set_index('timestamp').sort_index()
    
    # Filter to 2025 only
    df = df[(df.index >= '2025-01-01') & (df.index < '2026-01-01')]
    
    print(f"Loaded {len(df):,} bars from {df.index.min()} to {df.index.max()}")
    
    return df

def analyze_threshold(df, forward_periods, profit_threshold):
    """
    Analyze a specific profit threshold.
    
    Returns:
        dict with analysis metrics
    """
    df = df.copy()
    
    # Calculate forward returns
    df['forward_high'] = df['high'].rolling(forward_periods).max().shift(-forward_periods)
    df['forward_low'] = df['low'].rolling(forward_periods).min().shift(-forward_periods)
    
    # Calculate potential profit/loss
    df['max_profit'] = (df['forward_high'] - df['close']) / df['close']
    df['max_loss'] = (df['close'] - df['forward_low']) / df['close']
    
    # Label: 1 if profitable long opportunity, 0 otherwise
    df['label'] = (df['max_profit'] >= profit_threshold).astype(int)
    
    # Remove rows where we can't calculate forward returns
    df = df.dropna(subset=['forward_high', 'forward_low', 'label'])
    
    # Calculate metrics
    total_samples = len(df)
    positive_samples = df['label'].sum()
    negative_samples = total_samples - positive_samples
    positive_pct = (positive_samples / total_samples * 100) if total_samples > 0 else 0
    
    # Average profit when threshold is met
    profitable_trades = df[df['label'] == 1]
    avg_profit_when_met = profitable_trades['max_profit'].mean() if len(profitable_trades) > 0 else 0
    
    # Average loss when threshold is NOT met
    unprofitable_trades = df[df['label'] == 0]
    avg_loss_when_not_met = unprofitable_trades['max_loss'].mean() if len(unprofitable_trades) > 0 else 0
    
    # Calculate realistic win rate (if we traded all positive signals)
    # Assume we exit at threshold profit or max loss
    if len(profitable_trades) > 0:
        # For profitable trades: how many actually reached the threshold before hitting stop loss?
        # Simplified: assume we capture the threshold profit
        expected_profit_per_positive = profit_threshold
    else:
        expected_profit_per_positive = 0
    
    # For negative trades: assume we lose on average
    expected_loss_per_negative = avg_loss_when_not_met if avg_loss_when_not_met > 0 else 0
    
    # Expected value if we trade all signals
    expected_value = (positive_pct / 100 * expected_profit_per_positive - 
                     (100 - positive_pct) / 100 * expected_loss_per_negative)
    
    return {
        'threshold': profit_threshold,
        'threshold_pct': profit_threshold * 100,
        'threshold_pips': profit_threshold * 10000,  # Approximate for EUR/USD
        'total_samples': total_samples,
        'positive_samples': positive_samples,
        'negative_samples': negative_samples,
        'positive_pct': positive_pct,
        'negative_pct': 100 - positive_pct,
        'avg_profit_when_met': avg_profit_when_met * 100,  # Convert to %
        'avg_loss_when_not_met': avg_loss_when_not_met * 100,  # Convert to %
        'expected_value_pct': expected_value * 100,
        'signals_per_day': positive_samples / 365 if total_samples > 0 else 0,
    }

def main():
    print("=" * 80)
    print("PROFIT THRESHOLD ANALYSIS - 2025 EUR/USD DATA")
    print("=" * 80)
    print()
    
    # Load data
    df = load_2025_data()
    
    # Test different thresholds
    forward_periods = 4  # 4 bars = 1 hour (15min bars)
    
    thresholds = [
        0.0005,  # 0.05% = ~5.5 pips
        0.0007,  # 0.07% = ~7.7 pips
        0.0009,  # 0.09% = ~9.9 pips
        0.0010,  # 0.10% = ~11 pips
        0.0012,  # 0.12% = ~13 pips
        0.0015,  # 0.15% = ~16.5 pips (current)
        0.0018,  # 0.18% = ~20 pips
        0.0020,  # 0.20% = ~22 pips
        0.0025,  # 0.25% = ~27.5 pips
        0.0030,  # 0.30% = ~33 pips
    ]
    
    print(f"Testing {len(thresholds)} profit thresholds on {len(df):,} bars...")
    print(f"Forward window: {forward_periods} bars (1 hour)")
    print()
    
    results = []
    for threshold in thresholds:
        result = analyze_threshold(df, forward_periods, threshold)
        results.append(result)
    
    # Create results DataFrame
    results_df = pd.DataFrame(results)
    
    # Display results
    print("=" * 80)
    print("THRESHOLD ANALYSIS RESULTS")
    print("=" * 80)
    print()
    
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    pd.set_option('display.float_format', '{:.2f}'.format)
    
    display_df = results_df[[
        'threshold_pct', 'threshold_pips', 'positive_pct', 'signals_per_day',
        'avg_profit_when_met', 'avg_loss_when_not_met', 'expected_value_pct'
    ]].copy()
    
    display_df.columns = [
        'Threshold %', 'Pips', 'Positive %', 'Signals/Day',
        'Avg Profit %', 'Avg Loss %', 'Expected Value %'
    ]
    
    print(display_df.to_string(index=False))
    print()
    
    # Analysis and recommendations
    print("=" * 80)
    print("ANALYSIS & RECOMMENDATIONS")
    print("=" * 80)
    print()
    
    # Find optimal threshold based on different criteria
    
    # 1. Best class balance (closest to 50/50)
    results_df['balance_score'] = abs(results_df['positive_pct'] - 50)
    best_balance = results_df.loc[results_df['balance_score'].idxmin()]
    
    # 2. Best expected value
    best_ev = results_df.loc[results_df['expected_value_pct'].idxmax()]
    
    # 3. Good balance between signals and quality (30-40% positive, >1 signal/day)
    practical = results_df[
        (results_df['positive_pct'] >= 30) & 
        (results_df['positive_pct'] <= 40) &
        (results_df['signals_per_day'] >= 1.0)
    ]
    if len(practical) > 0:
        best_practical = practical.loc[practical['expected_value_pct'].idxmax()]
    else:
        best_practical = None
    
    print("1. BEST CLASS BALANCE (closest to 50/50):")
    print(f"   Threshold: {best_balance['threshold_pct']:.2f}% ({best_balance['threshold_pips']:.1f} pips)")
    print(f"   Positive class: {best_balance['positive_pct']:.1f}%")
    print(f"   Signals per day: {best_balance['signals_per_day']:.1f}")
    print(f"   Expected value: {best_balance['expected_value_pct']:.3f}%")
    print()
    
    print("2. BEST EXPECTED VALUE:")
    print(f"   Threshold: {best_ev['threshold_pct']:.2f}% ({best_ev['threshold_pips']:.1f} pips)")
    print(f"   Positive class: {best_ev['positive_pct']:.1f}%")
    print(f"   Signals per day: {best_ev['signals_per_day']:.1f}")
    print(f"   Expected value: {best_ev['expected_value_pct']:.3f}%")
    print()
    
    if best_practical is not None:
        print("3. BEST PRACTICAL (30-40% positive, >1 signal/day):")
        print(f"   Threshold: {best_practical['threshold_pct']:.2f}% ({best_practical['threshold_pips']:.1f} pips)")
        print(f"   Positive class: {best_practical['positive_pct']:.1f}%")
        print(f"   Signals per day: {best_practical['signals_per_day']:.1f}")
        print(f"   Expected value: {best_practical['expected_value_pct']:.3f}%")
        print()
    
    # Current threshold analysis
    current = results_df[results_df['threshold'] == 0.0015].iloc[0]
    print("4. CURRENT THRESHOLD (0.15% / 16.5 pips):")
    print(f"   Positive class: {current['positive_pct']:.1f}%")
    print(f"   Signals per day: {current['signals_per_day']:.1f}")
    print(f"   Expected value: {current['expected_value_pct']:.3f}%")
    print()
    
    # Final recommendation
    print("=" * 80)
    print("FINAL RECOMMENDATION")
    print("=" * 80)
    print()
    
    # Choose threshold with best expected value that also has reasonable signal frequency
    viable = results_df[results_df['signals_per_day'] >= 0.5]  # At least 0.5 signals/day
    if len(viable) > 0:
        recommended = viable.loc[viable['expected_value_pct'].idxmax()]
        
        print(f"Recommended threshold: {recommended['threshold_pct']:.2f}% ({recommended['threshold_pips']:.1f} pips)")
        print()
        print("Rationale:")
        print(f"  - Positive class: {recommended['positive_pct']:.1f}% (good for ML training)")
        print(f"  - Signals per day: {recommended['signals_per_day']:.1f} (sufficient trading opportunities)")
        print(f"  - Expected value: {recommended['expected_value_pct']:.3f}% (best risk/reward)")
        print()
        print("To use this threshold, update retrain_model.py:")
        print(f"  PROFIT_THRESHOLD = {recommended['threshold']:.4f}")
    else:
        print("WARNING: No viable threshold found with sufficient signal frequency.")
    
    print()
    print("=" * 80)

if __name__ == "__main__":
    main()
