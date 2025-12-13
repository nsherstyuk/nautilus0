"""
Test all rolling window models on Oct-Nov 2025 period.
Uses the SAME optimized config (trailing stops, etc.) but different models.
This shows which model would have performed best recently.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from joblib import load
import sys

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from run_mtf_backtest_detailed import load_and_prepare_data, calculate_features, simulate_strategy
from config.mtf_config import load_mtf_config

def test_model_on_period(model_path, config, df):
    """Test a specific model on the data."""
    try:
        model = load(model_path)
        trades = simulate_strategy(df, config, model)
        
        if not trades:
            return None
        
        df_trades = pd.DataFrame(trades)
        
        # Calculate metrics
        total_pnl = df_trades['pnl'].sum()
        trade_count = len(df_trades)
        win_rate = (df_trades['pnl'] > 0).sum() / len(df_trades) * 100
        avg_win = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if (df_trades['pnl'] > 0).any() else 0
        avg_loss = df_trades[df_trades['pnl'] < 0]['pnl'].mean() if (df_trades['pnl'] < 0).any() else 0
        
        # Monthly breakdown
        df_trades['entry_time'] = pd.to_datetime(df_trades['entry_time'])
        df_trades['month'] = df_trades['entry_time'].dt.to_period('M')
        monthly = df_trades.groupby('month')['pnl'].agg(['sum', 'count']).to_dict('index')
        
        return {
            'total_pnl': total_pnl,
            'trade_count': trade_count,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'monthly': monthly
        }
    except Exception as e:
        print(f"Error testing {model_path}: {e}")
        return None

def main():
    print("="*80)
    print("TESTING ROLLING WINDOW MODELS ON OCT-NOV 2025")
    print("="*80)
    print("\nUsing OPTIMIZED config:")
    print("  - Trailing activation: 3.0 ATR")
    print("  - Trailing distance: 0.5 ATR")
    print("  - Partial close: 2.5 ATR")
    print("  - Max ATR: 0.0050")
    print("  - No hour exclusions")
    
    # Load config (the optimized one)
    config = load_mtf_config()
    
    # Override dates to test only Oct-Nov 2025
    config.backtest_start_date = "2025-10-01"
    config.backtest_end_date = "2025-12-01"
    
    print(f"\nTest period: {config.backtest_start_date} to {config.backtest_end_date}")
    
    # Load and prepare data ONCE
    print("\nLoading data...")
    df = load_and_prepare_data(config)
    df = calculate_features(df)
    print(f"Data prepared: {len(df)} bars")
    
    # Load rolling window info
    rolling_csv = PROJECT_ROOT / "models" / "rolling" / "rolling_window_results.csv"
    rolling_info = pd.read_csv(rolling_csv)
    
    # Test each model
    results = []
    
    print("\n" + "="*80)
    print("TESTING MODELS")
    print("="*80)
    
    for idx, row in rolling_info.iterrows():
        window_id = row['window_id']
        model_path = PROJECT_ROOT / "models" / "rolling" / f"ml_model_mtf_window_{window_id:02d}.pkl"
        
        print(f"\nTesting Window {window_id}...")
        print(f"  Trained: {row['train_start']} to {row['train_end']}")
        print(f"  Original test: {row['test_start']} to {row['test_end']}")
        
        result = test_model_on_period(model_path, config, df)
        
        if result:
            print(f"  ✅ Oct-Nov P&L: ${result['total_pnl']:.2f}")
            print(f"     Trades: {result['trade_count']}, Win rate: {result['win_rate']:.1f}%")
            
            results.append({
                'window_id': window_id,
                'train_start': row['train_start'],
                'train_end': row['train_end'],
                'oct_nov_pnl': result['total_pnl'],
                'oct_nov_trades': result['trade_count'],
                'oct_nov_win_rate': result['win_rate'],
                'avg_win': result['avg_win'],
                'avg_loss': result['avg_loss'],
                'monthly': result['monthly']
            })
        else:
            print(f"  ❌ Failed")
    
    # Create results DataFrame
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('oct_nov_pnl', ascending=False)
    
    print("\n" + "="*80)
    print("RESULTS SUMMARY - SORTED BY OCT-NOV P&L")
    print("="*80)
    
    print("\n" + results_df[['window_id', 'train_start', 'train_end', 'oct_nov_pnl', 'oct_nov_trades', 'oct_nov_win_rate']].to_string(index=False))
    
    # Top 5
    print("\n" + "="*80)
    print("TOP 5 MODELS FOR OCT-NOV 2025")
    print("="*80)
    
    for idx, row in results_df.head(5).iterrows():
        print(f"\n#{idx+1}. Window {row['window_id']}")
        print(f"   Training: {row['train_start']} to {row['train_end']}")
        print(f"   Oct-Nov P&L: ${row['oct_nov_pnl']:.2f}")
        print(f"   Trades: {row['oct_nov_trades']}, Win rate: {row['oct_nov_win_rate']:.1f}%")
        print(f"   Avg win: ${row['avg_win']:.2f}, Avg loss: ${row['avg_loss']:.2f}")
        
        # Monthly breakdown
        if row['monthly']:
            print(f"   Monthly breakdown:")
            for month, stats in row['monthly'].items():
                print(f"     {month}: ${stats['sum']:.2f} ({int(stats['count'])} trades)")
    
    # Compare with current model
    print("\n" + "="*80)
    print("COMPARISON WITH CURRENT MODEL")
    print("="*80)
    
    current_model_path = PROJECT_ROOT / "models" / "ml_model_mtf.pkl"
    print(f"\nTesting current model: {current_model_path}")
    current_result = test_model_on_period(current_model_path, config, df)
    
    if current_result:
        print(f"Current model Oct-Nov P&L: ${current_result['total_pnl']:.2f}")
        print(f"Trades: {current_result['trade_count']}, Win rate: {current_result['win_rate']:.1f}%")
        
        best_rolling = results_df.iloc[0]
        improvement = best_rolling['oct_nov_pnl'] - current_result['total_pnl']
        
        print(f"\nBest rolling window (Window {best_rolling['window_id']}):")
        print(f"  P&L: ${best_rolling['oct_nov_pnl']:.2f}")
        print(f"  Improvement: ${improvement:.2f} ({improvement / abs(current_result['total_pnl']) * 100:.1f}%)")
        
        if improvement > 1000:
            print(f"\n✅ RECOMMENDATION: Switch to Window {best_rolling['window_id']}")
            print(f"   Command: copy models\\rolling\\ml_model_mtf_window_{best_rolling['window_id']:02d}.pkl models\\ml_model_mtf.pkl")
        else:
            print(f"\n⚠️  Improvement is small. Consider keeping current model or testing more.")
    
    # Save results
    output_path = PROJECT_ROOT / "models" / "rolling" / "oct_nov_test_results.csv"
    results_df.to_csv(output_path, index=False)
    print(f"\n✅ Results saved to: {output_path}")
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
    print("\nNext steps:")
    print("1. Review the top performing models")
    print("2. If a model shows significant improvement, switch to it")
    print("3. Run full backtest (Jan-Nov 2025) with the best model")
    print("4. If satisfied, deploy to live trading")

if __name__ == "__main__":
    main()
