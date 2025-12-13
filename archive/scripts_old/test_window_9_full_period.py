"""
Test Window 9 model on FULL period (Jan-Nov 2025) without changing current setup.
Compares performance with current model to verify improvement across all months.
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

def test_model_full_period(model_path, model_name):
    """Test a model on the full Jan-Nov 2025 period."""
    print("\n" + "="*80)
    print(f"TESTING: {model_name}")
    print("="*80)
    
    # Load config (optimized settings)
    config = load_mtf_config()
    
    # Full period
    config.backtest_start_date = "2025-01-01"
    config.backtest_end_date = "2025-12-01"
    
    print(f"\nPeriod: {config.backtest_start_date} to {config.backtest_end_date}")
    print(f"Model: {model_path}")
    
    # Load data
    print("\nLoading data...")
    df = load_and_prepare_data(config)
    df = calculate_features(df)
    print(f"Data prepared: {len(df)} bars")
    
    # Load model and simulate
    print(f"\nLoading model and simulating...")
    model = load(model_path)
    trades = simulate_strategy(df, config, model)
    
    if not trades:
        print("❌ No trades generated!")
        return None
    
    # Convert to DataFrame
    df_trades = pd.DataFrame(trades)
    df_trades['entry_time'] = pd.to_datetime(df_trades['entry_time'])
    
    # Overall metrics
    total_pnl = df_trades['pnl'].sum()
    trade_count = len(df_trades)
    win_count = (df_trades['pnl'] > 0).sum()
    loss_count = (df_trades['pnl'] < 0).sum()
    win_rate = win_count / trade_count * 100
    
    avg_win = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if win_count > 0 else 0
    avg_loss = df_trades[df_trades['pnl'] < 0]['pnl'].mean() if loss_count > 0 else 0
    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    # Calculate Sharpe ratio
    returns = df_trades['pnl']
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    
    print("\n" + "-"*80)
    print("OVERALL PERFORMANCE")
    print("-"*80)
    print(f"Total P&L:        ${total_pnl:,.2f}")
    print(f"Total Trades:     {trade_count}")
    print(f"Winning Trades:   {win_count} ({win_rate:.1f}%)")
    print(f"Losing Trades:    {loss_count}")
    print(f"Avg Win:          ${avg_win:.2f}")
    print(f"Avg Loss:         ${avg_loss:.2f}")
    print(f"Win/Loss Ratio:   {win_loss_ratio:.2f}")
    print(f"Sharpe Ratio:     {sharpe:.2f}")
    
    # Monthly breakdown
    df_trades['month'] = df_trades['entry_time'].dt.to_period('M')
    monthly = df_trades.groupby('month').agg({
        'pnl': ['count', 'sum', 'mean', lambda x: (x > 0).sum() / len(x) * 100]
    }).round(2)
    monthly.columns = ['Trades', 'Total P&L', 'Avg P&L', 'Win Rate %']
    
    print("\n" + "-"*80)
    print("MONTHLY BREAKDOWN")
    print("-"*80)
    print(monthly.to_string())
    
    # Quarterly summary
    print("\n" + "-"*80)
    print("QUARTERLY SUMMARY")
    print("-"*80)
    
    q1_months = ['2025-01', '2025-02', '2025-03']
    q2_months = ['2025-04', '2025-05', '2025-06']
    q3_months = ['2025-07', '2025-08', '2025-09']
    q4_months = ['2025-10', '2025-11']
    
    for quarter, months in [('Q1', q1_months), ('Q2', q2_months), ('Q3', q3_months), ('Q4', q4_months)]:
        quarter_data = monthly.loc[[m for m in months if m in monthly.index]]
        if len(quarter_data) > 0:
            q_pnl = quarter_data['Total P&L'].sum()
            q_trades = quarter_data['Trades'].sum()
            q_avg_wr = quarter_data['Win Rate %'].mean()
            print(f"{quarter}: ${q_pnl:,.2f} ({int(q_trades)} trades, {q_avg_wr:.1f}% WR)")
    
    # Exit reason analysis
    print("\n" + "-"*80)
    print("EXIT REASON BREAKDOWN")
    print("-"*80)
    exit_analysis = df_trades.groupby('exit_reason').agg({
        'pnl': ['count', 'sum', 'mean']
    }).round(2)
    exit_analysis.columns = ['Count', 'Total P&L', 'Avg P&L']
    print(exit_analysis.to_string())
    
    return {
        'model_name': model_name,
        'total_pnl': total_pnl,
        'trade_count': trade_count,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'win_loss_ratio': win_loss_ratio,
        'sharpe': sharpe,
        'monthly': monthly,
        'trades_df': df_trades
    }

def main():
    print("="*80)
    print("FULL PERIOD COMPARISON: WINDOW 9 vs CURRENT MODEL")
    print("="*80)
    print("\nThis script tests both models on Jan-Nov 2025 WITHOUT changing your setup")
    print("\nUsing OPTIMIZED config:")
    print("  - Trailing activation: 3.0 ATR")
    print("  - Trailing distance: 0.5 ATR")
    print("  - Partial close: 2.5 ATR")
    print("  - Max ATR: 0.0050")
    print("  - No hour exclusions")
    
    # Test current model
    current_model_path = PROJECT_ROOT / "models" / "ml_model_mtf.pkl"
    current_results = test_model_full_period(current_model_path, "CURRENT MODEL")
    
    # Test Window 9
    window_9_path = PROJECT_ROOT / "models" / "rolling" / "ml_model_mtf_window_09.pkl"
    window_9_results = test_model_full_period(window_9_path, "WINDOW 9 (Sep 2024 - Feb 2025)")
    
    # Comparison
    print("\n" + "="*80)
    print("COMPARISON SUMMARY")
    print("="*80)
    
    if current_results and window_9_results:
        comparison = pd.DataFrame({
            'Metric': ['Total P&L', 'Total Trades', 'Win Rate %', 'Avg Win', 'Avg Loss', 'Win/Loss Ratio', 'Sharpe Ratio'],
            'Current Model': [
                f"${current_results['total_pnl']:,.2f}",
                current_results['trade_count'],
                f"{current_results['win_rate']:.1f}%",
                f"${current_results['avg_win']:.2f}",
                f"${current_results['avg_loss']:.2f}",
                f"{current_results['win_loss_ratio']:.2f}",
                f"{current_results['sharpe']:.2f}"
            ],
            'Window 9': [
                f"${window_9_results['total_pnl']:,.2f}",
                window_9_results['trade_count'],
                f"{window_9_results['win_rate']:.1f}%",
                f"${window_9_results['avg_win']:.2f}",
                f"${window_9_results['avg_loss']:.2f}",
                f"{window_9_results['win_loss_ratio']:.2f}",
                f"{window_9_results['sharpe']:.2f}"
            ]
        })
        
        print("\n" + comparison.to_string(index=False))
        
        # Calculate improvement
        pnl_diff = window_9_results['total_pnl'] - current_results['total_pnl']
        pnl_pct = (pnl_diff / current_results['total_pnl'] * 100) if current_results['total_pnl'] != 0 else 0
        
        print("\n" + "-"*80)
        print("IMPROVEMENT ANALYSIS")
        print("-"*80)
        print(f"P&L Difference:   ${pnl_diff:,.2f} ({pnl_pct:+.1f}%)")
        print(f"Trade Difference: {window_9_results['trade_count'] - current_results['trade_count']:+d}")
        print(f"Win Rate Change:  {window_9_results['win_rate'] - current_results['win_rate']:+.1f} percentage points")
        
        # Monthly comparison
        print("\n" + "-"*80)
        print("MONTHLY P&L COMPARISON")
        print("-"*80)
        
        monthly_comp = pd.DataFrame({
            'Month': current_results['monthly'].index,
            'Current Model': current_results['monthly']['Total P&L'].values,
            'Window 9': window_9_results['monthly']['Total P&L'].values
        })
        monthly_comp['Difference'] = monthly_comp['Window 9'] - monthly_comp['Current Model']
        monthly_comp['Current Model'] = monthly_comp['Current Model'].apply(lambda x: f"${x:,.2f}")
        monthly_comp['Window 9'] = monthly_comp['Window 9'].apply(lambda x: f"${x:,.2f}")
        monthly_comp['Difference'] = monthly_comp['Difference'].apply(lambda x: f"${x:+,.2f}")
        
        print("\n" + monthly_comp.to_string(index=False))
        
        # Recommendation
        print("\n" + "="*80)
        print("RECOMMENDATION")
        print("="*80)
        
        if pnl_diff > 2000:
            print(f"\n✅ STRONG RECOMMENDATION: Switch to Window 9")
            print(f"   Improvement: ${pnl_diff:,.2f} ({pnl_pct:+.1f}%)")
            print(f"\n   To deploy Window 9:")
            print(f"   1. Backup current model:")
            print(f"      copy models\\ml_model_mtf.pkl models\\ml_model_mtf_backup.pkl")
            print(f"   2. Switch to Window 9:")
            print(f"      copy models\\rolling\\ml_model_mtf_window_09.pkl models\\ml_model_mtf.pkl")
            print(f"   3. Deploy to live trading:")
            print(f"      python live\\run_live_mtf.py")
        elif pnl_diff > 0:
            print(f"\n⚠️  MODERATE IMPROVEMENT: Window 9 is better but not dramatically")
            print(f"   Improvement: ${pnl_diff:,.2f} ({pnl_pct:+.1f}%)")
            print(f"   Consider switching, but monitor closely")
        else:
            print(f"\n❌ Window 9 performs WORSE on full period")
            print(f"   Loss: ${pnl_diff:,.2f} ({pnl_pct:.1f}%)")
            print(f"   Keep current model or try other windows")
        
        # Check if any month got significantly worse
        print("\n" + "-"*80)
        print("MONTH-BY-MONTH IMPACT")
        print("-"*80)
        
        better_months = []
        worse_months = []
        
        for month in current_results['monthly'].index:
            curr_pnl = current_results['monthly'].loc[month, 'Total P&L']
            win9_pnl = window_9_results['monthly'].loc[month, 'Total P&L']
            diff = win9_pnl - curr_pnl
            
            if diff > 500:
                better_months.append((month, diff))
            elif diff < -500:
                worse_months.append((month, diff))
        
        if better_months:
            print("\n✅ Months with significant improvement (>$500):")
            for month, diff in better_months:
                print(f"   {month}: ${diff:+,.2f}")
        
        if worse_months:
            print("\n⚠️  Months with significant degradation (<-$500):")
            for month, diff in worse_months:
                print(f"   {month}: ${diff:+,.2f}")
        
        if not worse_months:
            print("\n✅ No months show significant degradation!")
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE - NO CHANGES MADE TO YOUR SETUP")
    print("="*80)

if __name__ == "__main__":
    main()
