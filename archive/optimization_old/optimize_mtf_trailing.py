"""
Optimize MTF Strategy Trailing Stop Parameters.
Runs a grid search to find the best trailing stop configuration.
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from joblib import load
import itertools
from dataclasses import dataclass

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from run_mtf_backtest_detailed import load_and_prepare_data, calculate_features, simulate_strategy
from config.mtf_config import load_mtf_config

@dataclass
class OptimizeConfig:
    """Mock config for optimization."""
    # Base settings (fixed)
    backtest_start_date: str
    backtest_end_date: str
    position_size: int = 100000
    cooldown_minutes: int = 30
    prediction_threshold: float = 0.55
    min_atr: float = 0.0003
    max_atr: float = 0.0050
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5
    partial_close_enabled: bool = True
    partial_close_fraction: float = 0.5
    partial_close_atr_mult: float = 1.5
    
    # Excluded hours (using new optimized hours)
    excluded_hours_by_weekday: dict = None
    excluded_hours: list = None
    
    # Trailing settings (variable)
    trailing_stop_enabled: bool = True
    trailing_activation_atr_mult: float = 1.0
    trailing_distance_atr_mult: float = 0.8

def main():
    print("="*80)
    print("MTF TRAILING STOP OPTIMIZATION")
    print("="*80)
    
    # 1. Load Base Config & Data
    base_config = load_mtf_config()
    print("Loading data and model...")
    
    # Load Model
    model_path = PROJECT_ROOT / "models" / "ml_model_mtf.pkl"
    model = load(model_path)
    
    # Load Data
    df = load_and_prepare_data(base_config)
    df = calculate_features(df)
    
    # 2. Define Parameter Grid
    activation_range = [1.0, 1.5, 2.0, 2.5]  # When to start trailing (ATR multiples)
    distance_range = [0.5, 0.8, 1.0, 1.2, 1.5]   # How far to trail (ATR multiples)
    
    print(f"\nTesting {len(activation_range) * len(distance_range)} combinations...")
    print(f"Activation Range: {activation_range}")
    print(f"Distance Range:   {distance_range}")
    print("-" * 80)
    print(f"{'Activation':<12} {'Distance':<10} {'P&L':<15} {'Trades':<8} {'Win Rate':<10}")
    print("-" * 80)
    
    results = []
    
    # 3. Grid Search
    for activation, distance in itertools.product(activation_range, distance_range):
        # Create specific config for this run
        opt_config = OptimizeConfig(
            backtest_start_date=base_config.backtest_start_date,
            backtest_end_date=base_config.backtest_end_date,
            excluded_hours_by_weekday=base_config.excluded_hours_by_weekday,
            excluded_hours=base_config.excluded_hours,
            
            # Variables
            trailing_stop_enabled=True,
            trailing_activation_atr_mult=activation,
            trailing_distance_atr_mult=distance
        )
        
        # Run simulation
        trades = simulate_strategy(df, opt_config, model)
        
        # Calculate metrics
        df_trades = pd.DataFrame(trades)
        if len(df_trades) > 0:
            total_pnl = df_trades['pnl'].sum()
            win_rate = len(df_trades[df_trades['pnl'] > 0]) / len(df_trades) * 100
            count = len(df_trades)
        else:
            total_pnl = 0
            win_rate = 0
            count = 0
            
        results.append({
            'activation': activation,
            'distance': distance,
            'pnl': total_pnl,
            'trades': count,
            'win_rate': win_rate
        })
        
        print(f"{activation:<12.1f} {distance:<10.1f} ${total_pnl:<14,.0f} {count:<8} {win_rate:>8.1f}%")

    # 4. Show Best Results
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values('pnl', ascending=False)
    
    print("\n" + "="*80)
    print("TOP 5 CONFIGURATIONS")
    print("="*80)
    print(df_results.head(5).to_string(index=False))
    
    # Save to CSV
    output_path = PROJECT_ROOT / "optimization_trailing_results.csv"
    df_results.to_csv(output_path, index=False)
    print(f"\nFull results saved to: {output_path}")

if __name__ == "__main__":
    main()
