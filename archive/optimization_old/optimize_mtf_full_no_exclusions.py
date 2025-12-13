"""
Comprehensive MTF Strategy Optimization - NO HOUR EXCLUSIONS.
Tests combinations WITHOUT any hour filters to find true potential.

Tests:
- Partial Close Threshold
- Trailing Stop Activation
- Trailing Stop Distance
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
    
    # NO EXCLUDED HOURS - Trade 24/7
    excluded_hours_by_weekday: dict = None
    excluded_hours: list = None
    
    # Variable parameters
    partial_close_enabled: bool = True
    partial_close_fraction: float = 0.5
    partial_close_atr_mult: float = 1.5  # VARIABLE
    
    trailing_stop_enabled: bool = True
    trailing_activation_atr_mult: float = 1.0  # VARIABLE
    trailing_distance_atr_mult: float = 0.8  # VARIABLE

def main():
    print("="*80)
    print("MTF COMPREHENSIVE OPTIMIZATION - NO HOUR EXCLUSIONS")
    print("Trading 24/7 to find true potential")
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
    partial_close_range = [1.0, 1.5, 2.0, 2.5]  # When to partial close
    activation_range = [1.5, 2.0, 2.5, 3.0]     # When to start trailing
    distance_range = [0.5, 0.8, 1.0]            # How far to trail
    
    total_combinations = len(partial_close_range) * len(activation_range) * len(distance_range)
    
    print(f"\nTesting {total_combinations} combinations...")
    print(f"Partial Close: {partial_close_range}")
    print(f"Activation:    {activation_range}")
    print(f"Distance:      {distance_range}")
    print(f"Hour Filter:   NONE (24/7 trading)")
    print("-" * 100)
    print(f"{'Partial':<10} {'Activation':<12} {'Distance':<10} {'P&L':<15} {'Trades':<8} {'Win Rate':<10} {'Sharpe':<8}")
    print("-" * 100)
    
    results = []
    counter = 0
    
    # 3. Grid Search
    for partial, activation, distance in itertools.product(partial_close_range, activation_range, distance_range):
        counter += 1
        
        # Create specific config for this run
        opt_config = OptimizeConfig(
            backtest_start_date=base_config.backtest_start_date,
            backtest_end_date=base_config.backtest_end_date,
            
            # NO EXCLUSIONS
            excluded_hours_by_weekday={},  # Empty dict
            excluded_hours=[],  # Empty list
            
            # Variables
            partial_close_atr_mult=partial,
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
            
            # Calculate Sharpe ratio (simple version)
            returns = df_trades['pnl']
            sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        else:
            total_pnl = 0
            win_rate = 0
            count = 0
            sharpe = 0
            
        results.append({
            'partial_close': partial,
            'activation': activation,
            'distance': distance,
            'pnl': total_pnl,
            'trades': count,
            'win_rate': win_rate,
            'sharpe': sharpe
        })
        
        print(f"{partial:<10.1f} {activation:<12.1f} {distance:<10.1f} ${total_pnl:<14,.0f} {count:<8} {win_rate:>8.1f}%  {sharpe:>7.2f}  [{counter}/{total_combinations}]")

    # 4. Show Best Results
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values('pnl', ascending=False)
    
    print("\n" + "="*100)
    print("TOP 10 CONFIGURATIONS (NO HOUR EXCLUSIONS)")
    print("="*100)
    print(df_results.head(10).to_string(index=False))
    
    # Save to CSV
    output_path = PROJECT_ROOT / "optimization_full_no_exclusions_results.csv"
    df_results.to_csv(output_path, index=False)
    print(f"\nFull results saved to: {output_path}")
    
    # Show best by partial close level
    print("\n" + "="*100)
    print("BEST CONFIGURATION FOR EACH PARTIAL CLOSE LEVEL")
    print("="*100)
    for pc in partial_close_range:
        best = df_results[df_results['partial_close'] == pc].iloc[0]
        print(f"Partial={pc:.1f}: Act={best['activation']:.1f}, Dist={best['distance']:.1f} → ${best['pnl']:,.0f} ({best['trades']} trades, {best['win_rate']:.1f}%)")

if __name__ == "__main__":
    main()
