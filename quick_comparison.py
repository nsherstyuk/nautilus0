"""
Quick comparison of baseline vs minimum hold time results
"""
import json
from pathlib import Path

# Load baseline results (without minimum hold time)
baseline_stats_file = Path('logs/backtest_results_baseline/EUR-USD_20251116_130912/performance_stats.json')
# Load test results (with minimum hold time)
test_stats_file = Path('logs/backtest_results/EUR-USD_20251116_131055/performance_stats.json')

if baseline_stats_file.exists() and test_stats_file.exists():
    with open(baseline_stats_file) as f:
        baseline = json.load(f)
    
    with open(test_stats_file) as f:
        test = json.load(f)
    
    print("="*80)
    print("MINIMUM HOLD TIME FEATURE - COMPARISON RESULTS")
    print("="*80)
    
    print(f"\n{'Metric':<25} {'WITHOUT':<18} {'WITH':<18} {'Change':<15}")
    print("-"*76)
    
    metrics = [
        ('Total PnL', 'total_pnl'),
        ('Total Trades', 'total_trades'),
        ('Win Rate (%)', 'win_rate'),
        ('Profit Factor', 'profit_factor'),
        ('Max Drawdown', 'max_drawdown'),
        ('Sharpe Ratio', 'sharpe_ratio'),
        ('Average Win', 'avg_win'),
        ('Average Loss', 'avg_loss'),
        ('Avg Trade Duration (h)', 'avg_trade_duration_hours'),
    ]
    
    for name, key in metrics:
        b_val = baseline.get(key, 0)
        t_val = test.get(key, 0)
        
        # Calculate change
        if isinstance(b_val, (int, float)) and b_val != 0:
            change_pct = ((t_val - b_val) / abs(b_val)) * 100
            change_str = f"{change_pct:+.1f}%"
        else:
            change_str = "N/A"
        
        # Format values
        if 'PnL' in name or 'Win' in name or 'Loss' in name or 'Drawdown' in name:
            b_fmt = f"${b_val:,.2f}"
            t_fmt = f"${t_val:,.2f}"
        elif '%' in name:
            b_fmt = f"{b_val:.2f}%"
            t_fmt = f"{t_val:.2f}%"
        elif 'Duration' in name:
            b_fmt = f"{b_val:.1f}h"
            t_fmt = f"{t_val:.1f}h"
        else:
            b_fmt = f"{b_val:.2f}" if isinstance(b_val, float) else str(b_val)
            t_fmt = f"{t_val:.2f}" if isinstance(t_val, float) else str(t_val)
        
        print(f"{name:<25} {b_fmt:<18} {t_fmt:<18} {change_str:<15}")
    
    print("\n" + "="*80)
    print("KEY FINDINGS")
    print("="*80)
    
    pnl_diff = test.get('total_pnl', 0) - baseline.get('total_pnl', 0)
    pnl_pct = (pnl_diff / abs(baseline.get('total_pnl', 1))) * 100
    
    print(f"\n💰 Total PnL Change: ${pnl_diff:+,.2f} ({pnl_pct:+.1f}%)")
    
    if pnl_diff > 0:
        print("   ✅ Feature IMPROVED performance")
    elif pnl_diff < 0:
        print("   ❌ Feature DECREASED performance")
    else:
        print("   ➖ No change in performance")
    
    wr_diff = test.get('win_rate', 0) - baseline.get('win_rate', 0)
    print(f"\n🎯 Win Rate Change: {wr_diff:+.2f}%")
    
    trades_diff = test.get('total_trades', 0) - baseline.get('total_trades', 0)
    print(f"\n📊 Trade Count Change: {trades_diff:+d} trades")
    
    duration_diff = test.get('avg_trade_duration_hours', 0) - baseline.get('avg_trade_duration_hours', 0)
    print(f"\n⏱️  Avg Trade Duration Change: {duration_diff:+.1f} hours")
    
    print("\n" + "="*80)
    print("COMPARISON COMPLETE")
    print("="*80)
    print(f"\nBaseline: logs/backtest_results_baseline/EUR-USD_20251116_130912")
    print(f"Test:     logs/backtest_results/EUR-USD_20251116_131055")
    
else:
    print("ERROR: Could not find performance stats files")
    print(f"Baseline: {baseline_stats_file.exists()}")
    print(f"Test: {test_stats_file.exists()}")
