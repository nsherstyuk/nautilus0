"""
Test top 5 rolling window models on full period to find best overall performer.
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

def test_model_quick(model_path, model_name):
    """Quick test of a model on full period."""
    config = load_mtf_config()
    config.backtest_start_date = "2025-01-01"
    config.backtest_end_date = "2025-12-01"
    
    # Load data (only once, reuse)
    if not hasattr(test_model_quick, 'df'):
        print("Loading data (one time)...")
        df = load_and_prepare_data(config)
        df = calculate_features(df)
        test_model_quick.df = df
    
    df = test_model_quick.df
    
    # Load model and simulate
    model = load(model_path)
    trades = simulate_strategy(df, config, model)
    
    if not trades:
        return None
    
    df_trades = pd.DataFrame(trades)
    df_trades['entry_time'] = pd.to_datetime(df_trades['entry_time'])
    
    total_pnl = df_trades['pnl'].sum()
    trade_count = len(df_trades)
    win_rate = (df_trades['pnl'] > 0).sum() / len(df_trades) * 100
    
    # Monthly
    df_trades['month'] = df_trades['entry_time'].dt.to_period('M')
    monthly = df_trades.groupby('month')['pnl'].sum()
    
    # Q2 and Q4 specifically
    q2_pnl = monthly[['2025-04', '2025-05', '2025-06']].sum()
    q4_pnl = monthly[['2025-10', '2025-11']].sum()
    
    return {
        'model_name': model_name,
        'total_pnl': total_pnl,
        'trade_count': trade_count,
        'win_rate': win_rate,
        'q2_pnl': q2_pnl,
        'q4_pnl': q4_pnl,
        'monthly': monthly
    }

def main():
    print("="*80)
    print("TESTING TOP 5 WINDOWS ON FULL PERIOD")
    print("="*80)
    
    # Top 5 from Oct-Nov test: 9, 11, 15, 8, 1
    windows_to_test = [
        (9, "Window 9 (Sep 2024 - Feb 2025)"),
        (11, "Window 11 (Nov 2024 - Apr 2025)"),
        (15, "Window 15 (Mar 2025 - Aug 2025)"),
        (8, "Window 8 (Aug 2024 - Jan 2025)"),
        (1, "Window 1 (Jan 2024 - Jun 2024)"),
    ]
    
    results = []
    
    # Test current model first
    print("\nTesting CURRENT MODEL...")
    current_path = PROJECT_ROOT / "models" / "ml_model_mtf.pkl"
    current = test_model_quick(current_path, "Current Model")
    if current:
        results.append(current)
        print(f"✅ Total P&L: ${current['total_pnl']:,.2f}")
    
    # Test each window
    for window_id, name in windows_to_test:
        print(f"\nTesting {name}...")
        model_path = PROJECT_ROOT / "models" / "rolling" / f"ml_model_mtf_window_{window_id:02d}.pkl"
        result = test_model_quick(model_path, name)
        if result:
            results.append(result)
            print(f"✅ Total P&L: ${result['total_pnl']:,.2f}")
    
    # Summary
    print("\n" + "="*80)
    print("RESULTS SUMMARY")
    print("="*80)
    
    summary = pd.DataFrame(results)
    summary = summary.sort_values('total_pnl', ascending=False)
    
    print("\n" + summary[['model_name', 'total_pnl', 'trade_count', 'win_rate', 'q2_pnl', 'q4_pnl']].to_string(index=False))
    
    # Find best overall
    print("\n" + "="*80)
    print("ANALYSIS")
    print("="*80)
    
    best = summary.iloc[0]
    current_pnl = current['total_pnl']
    
    print(f"\n🏆 BEST OVERALL: {best['model_name']}")
    print(f"   Total P&L: ${best['total_pnl']:,.2f}")
    print(f"   Q2 P&L: ${best['q2_pnl']:,.2f}")
    print(f"   Q4 P&L: ${best['q4_pnl']:,.2f}")
    
    if best['model_name'] != "Current Model":
        improvement = best['total_pnl'] - current_pnl
        print(f"\n   Improvement vs Current: ${improvement:+,.2f} ({improvement/current_pnl*100:+.1f}%)")
    else:
        print(f"\n   ✅ Current model is already the best!")
    
    # Check for balanced performers
    print("\n" + "-"*80)
    print("BALANCED PERFORMERS (Good Q2 AND Q4)")
    print("-"*80)
    
    # Filter for models with Q2 > $30k and Q4 > $3k
    balanced = summary[(summary['q2_pnl'] > 30000) & (summary['q4_pnl'] > 3000)]
    
    if len(balanced) > 0:
        print("\nModels with strong Q2 (>$30k) AND strong Q4 (>$3k):")
        print(balanced[['model_name', 'total_pnl', 'q2_pnl', 'q4_pnl']].to_string(index=False))
    else:
        print("\n❌ No model excels in BOTH Q2 and Q4")
        print("This confirms the regime change problem!")
    
    # Recommendation
    print("\n" + "="*80)
    print("RECOMMENDATION")
    print("="*80)
    
    if best['model_name'] == "Current Model":
        print("\n✅ Keep your current model - it's already optimal!")
        print(f"   Total P&L: ${current_pnl:,.2f}")
    elif best['total_pnl'] > current_pnl + 2000:
        print(f"\n✅ Switch to {best['model_name']}")
        print(f"   Improvement: ${best['total_pnl'] - current_pnl:+,.2f}")
        # Extract window number
        for window_id, name in windows_to_test:
            if name == best['model_name']:
                print(f"\n   Command:")
                print(f"   copy models\\rolling\\ml_model_mtf_window_{window_id:02d}.pkl models\\ml_model_mtf.pkl")
    else:
        print("\n⚠️  No significant improvement found from rolling windows")
        print("\n   Options:")
        print("   1. Keep current model (best overall)")
        print("   2. Retrain new model on 2024-2025 data")
        print("   3. Implement regime detection to switch models dynamically")
        print("   4. Accept the Q4 degradation and monitor live performance")

if __name__ == "__main__":
    main()
