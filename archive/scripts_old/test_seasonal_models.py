"""
Test seasonal models on 2025 data to validate seasonal hypothesis.

Compares:
1. Q4 Model (Sep-Dec 2024) on Oct-Nov 2025
2. Oct-Nov Model (Oct-Nov 2024) on Oct-Nov 2025
3. Current model on Oct-Nov 2025
4. Window 9 on Oct-Nov 2025

Also tests on full 2025 year to ensure no degradation in other months.
"""
import pandas as pd
from pathlib import Path
from joblib import load
import sys

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from run_mtf_backtest_detailed import load_and_prepare_data, calculate_features, simulate_strategy
from config.mtf_config import load_mtf_config

def test_model(model_path, model_name, test_period_start, test_period_end):
    """Test a model on specified period."""
    print(f"\n{'='*80}")
    print(f"TESTING: {model_name}")
    print(f"Period: {test_period_start} to {test_period_end}")
    print(f"{'='*80}")
    
    # Load config
    config = load_mtf_config()
    config.backtest_start_date = test_period_start
    config.backtest_end_date = test_period_end
    
    # Load data
    print("Loading data...")
    df = load_and_prepare_data(config)
    df = calculate_features(df)
    print(f"Data prepared: {len(df)} bars")
    
    # Load model
    model = load(model_path)
    
    # Simulate
    print("Running backtest...")
    trades = simulate_strategy(df, config, model)
    
    if not trades:
        print("❌ No trades generated")
        return None
    
    # Analyze results
    df_trades = pd.DataFrame(trades)
    df_trades['entry_time'] = pd.to_datetime(df_trades['entry_time'])
    
    total_pnl = df_trades['pnl'].sum()
    trade_count = len(df_trades)
    win_rate = (df_trades['pnl'] > 0).sum() / len(df_trades) * 100
    avg_win = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if (df_trades['pnl'] > 0).any() else 0
    avg_loss = df_trades[df_trades['pnl'] < 0]['pnl'].mean() if (df_trades['pnl'] < 0).any() else 0
    
    print(f"\n{'─'*80}")
    print(f"RESULTS")
    print(f"{'─'*80}")
    print(f"Total P&L:    ${total_pnl:,.2f}")
    print(f"Trades:       {trade_count}")
    print(f"Win Rate:     {win_rate:.1f}%")
    print(f"Avg Win:      ${avg_win:.2f}")
    print(f"Avg Loss:     ${avg_loss:.2f}")
    
    # Monthly breakdown if testing multiple months
    if test_period_start != test_period_end:
        df_trades['month'] = df_trades['entry_time'].dt.to_period('M')
        monthly = df_trades.groupby('month').agg({
            'pnl': ['count', 'sum']
        })
        monthly.columns = ['Trades', 'P&L']
        print(f"\nMonthly Breakdown:")
        for month, row in monthly.iterrows():
            print(f"  {month}: ${row['P&L']:,.2f} ({int(row['Trades'])} trades)")
    
    return {
        'model_name': model_name,
        'total_pnl': total_pnl,
        'trade_count': trade_count,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss
    }

def main():
    print("="*80)
    print("SEASONAL MODEL COMPARISON")
    print("="*80)
    
    # Models to test
    models = [
        {
            'name': 'Q4 Model (Sep-Dec 2024)',
            'path': PROJECT_ROOT / 'models' / 'ml_model_mtf_q4_2024.pkl'
        },
        {
            'name': 'Oct-Nov Model (Oct-Nov 2024)',
            'path': PROJECT_ROOT / 'models' / 'ml_model_mtf_oct_nov_2024.pkl'
        },
        {
            'name': 'Current Model',
            'path': PROJECT_ROOT / 'models' / 'ml_model_mtf.pkl'
        },
        {
            'name': 'Window 9 (Sep 2024 - Feb 2025)',
            'path': PROJECT_ROOT / 'models' / 'rolling' / 'ml_model_mtf_window_09.pkl'
        }
    ]
    
    # Test periods
    test_periods = [
        {
            'name': 'Oct-Nov 2025',
            'start': '2025-10-01',
            'end': '2025-12-01'
        },
        {
            'name': 'Full Year 2025',
            'start': '2025-01-01',
            'end': '2025-12-01'
        }
    ]
    
    # Run tests
    all_results = {}
    
    for period in test_periods:
        print(f"\n\n{'#'*80}")
        print(f"TEST PERIOD: {period['name']}")
        print(f"{'#'*80}")
        
        period_results = []
        
        for model in models:
            if not model['path'].exists():
                print(f"\n⚠️  Skipping {model['name']} - model file not found")
                continue
            
            result = test_model(
                model['path'],
                model['name'],
                period['start'],
                period['end']
            )
            
            if result:
                period_results.append(result)
        
        all_results[period['name']] = period_results
    
    # Summary comparison
    print(f"\n\n{'='*80}")
    print("SUMMARY COMPARISON")
    print(f"{'='*80}")
    
    for period_name, results in all_results.items():
        print(f"\n{period_name}:")
        print(f"{'─'*80}")
        
        # Sort by P&L
        results_sorted = sorted(results, key=lambda x: x['total_pnl'], reverse=True)
        
        for i, result in enumerate(results_sorted, 1):
            print(f"{i}. {result['model_name']}")
            print(f"   P&L: ${result['total_pnl']:,.2f} | Trades: {result['trade_count']} | WR: {result['win_rate']:.1f}%")
    
    # Key findings
    print(f"\n{'='*80}")
    print("KEY FINDINGS")
    print(f"{'='*80}")
    
    oct_nov_results = all_results.get('Oct-Nov 2025', [])
    if oct_nov_results:
        best = max(oct_nov_results, key=lambda x: x['total_pnl'])
        print(f"\n🏆 BEST FOR OCT-NOV 2025: {best['model_name']}")
        print(f"   P&L: ${best['total_pnl']:,.2f}")
        
        # Check if it's a seasonal model
        if 'Oct-Nov Model' in best['model_name']:
            print("\n✅ SEASONAL HYPOTHESIS CONFIRMED!")
            print("   Pure Oct-Nov 2024 training performs best on Oct-Nov 2025")
            print("   This proves seasonal patterns exist!")
        elif 'Q4 Model' in best['model_name']:
            print("\n✅ Q4 SEASONAL PATTERN CONFIRMED!")
            print("   4-month Q4 training performs best")
            print("   Optimal window length: 4 months for Q4")
        elif 'Window 9' in best['model_name']:
            print("\n⚠️  6-month window still best")
            print("   Shorter windows don't improve performance")
            print("   Current approach may already be optimal")
        else:
            print("\n⚠️  Current model still best")
            print("   Seasonal models don't outperform")
            print("   May need different approach")
    
    full_year_results = all_results.get('Full Year 2025', [])
    if full_year_results:
        best_full = max(full_year_results, key=lambda x: x['total_pnl'])
        print(f"\n🏆 BEST FOR FULL YEAR 2025: {best_full['model_name']}")
        print(f"   P&L: ${best_full['total_pnl']:,.2f}")
        
        # Check if seasonal model hurts other months
        seasonal_models = [r for r in full_year_results if 'Oct-Nov Model' in r['model_name'] or 'Q4 Model' in r['model_name']]
        if seasonal_models:
            seasonal_full = seasonal_models[0]
            print(f"\n   Seasonal model full year: ${seasonal_full['total_pnl']:,.2f}")
            if seasonal_full['total_pnl'] < best_full['total_pnl'] * 0.8:
                print("   ⚠️  WARNING: Seasonal model hurts performance on other months!")
                print("   Recommendation: Use seasonal model ONLY for Oct-Nov")
    
    print(f"\n{'='*80}")
    print("RECOMMENDATION")
    print(f"{'='*80}")
    
    if oct_nov_results:
        oct_nov_best = max(oct_nov_results, key=lambda x: x['total_pnl'])
        current_oct_nov = next((r for r in oct_nov_results if 'Current Model' in r['model_name']), None)
        
        if current_oct_nov:
            improvement = oct_nov_best['total_pnl'] - current_oct_nov['total_pnl']
            
            if improvement > 2000 and 'Oct-Nov Model' in oct_nov_best['model_name']:
                print(f"\n✅ DEPLOY OCT-NOV MODEL for December 2025!")
                print(f"   Expected improvement: ${improvement:,.2f}")
                print(f"\n   Steps:")
                print(f"   1. Backup current model:")
                print(f"      copy models\\ml_model_mtf.pkl models\\ml_model_mtf_backup.pkl")
                print(f"   2. Deploy Oct-Nov model:")
                print(f"      copy models\\ml_model_mtf_oct_nov_2024.pkl models\\ml_model_mtf.pkl")
                print(f"   3. Monitor December performance")
                print(f"   4. Switch back to current model in January")
            elif improvement > 2000:
                print(f"\n✅ SWITCH TO: {oct_nov_best['model_name']}")
                print(f"   Improvement: ${improvement:,.2f}")
            else:
                print(f"\n⚠️  Improvement too small (${improvement:,.2f})")
                print(f"   Keep current model or investigate other approaches")

if __name__ == "__main__":
    main()
