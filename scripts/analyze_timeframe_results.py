"""
Analyze optimization results grouped by timeframe (bar_spec) to identify
which timeframes perform best and what parameters work for each.
"""
import sys
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def analyze_by_timeframe(csv_file: Path):
    """Analyze results grouped by bar_spec (timeframe)."""
    if not csv_file.exists():
        print(f"Error: File not found: {csv_file}")
        return
    
    df = pd.read_csv(csv_file)
    
    # Filter to completed runs only
    df = df[df['status'] == 'completed'].copy()
    
    if len(df) == 0:
        print("No completed runs found!")
        return
    
    # Group by bar_spec
    if 'bar_spec' not in df.columns:
        print("Error: 'bar_spec' column not found in results")
        print(f"Available columns: {list(df.columns)}")
        return
    
    grouped = df.groupby('bar_spec').agg({
        'sharpe_ratio': ['count', 'mean', 'max', 'min'],
        'total_pnl': ['mean', 'max', 'min'],
        'win_rate': ['mean', 'max'],
        'trade_count': ['mean', 'max'],
        'max_drawdown': ['mean', 'max']
    }).round(2)
    
    print("=" * 100)
    print("MULTI-TIMEFRAME OPTIMIZATION ANALYSIS")
    print("=" * 100)
    print()
    print(f"Total completed runs: {len(df)}")
    print(f"Timeframes tested: {df['bar_spec'].nunique()}")
    print()
    
    print("=" * 100)
    print("PERFORMANCE BY TIMEFRAME")
    print("=" * 100)
    print()
    
    # Sort by best Sharpe ratio
    best_by_timeframe = df.loc[df.groupby('bar_spec')['sharpe_ratio'].idxmax()]
    best_by_timeframe = best_by_timeframe.sort_values('sharpe_ratio', ascending=False)
    
    print(f"{'Timeframe':<25} {'Best Sharpe':<15} {'Best PnL':<15} {'Win Rate':<12} {'Trades':<10} {'Rank':<8}")
    print("-" * 100)
    
    for idx, row in best_by_timeframe.iterrows():
        timeframe = row['bar_spec']
        count = len(df[df['bar_spec'] == timeframe])
        print(f"{timeframe:<25} {row['sharpe_ratio']:<15.3f} ${row['total_pnl']:<14.2f} "
              f"{row['win_rate']*100:<11.1f}% {int(row['trade_count']):<10} #{count}")
    
    print()
    print("=" * 100)
    print("TOP 5 CONFIGURATIONS OVERALL")
    print("=" * 100)
    print()
    
    top5 = df.nlargest(5, 'sharpe_ratio')
    for i, (idx, row) in enumerate(top5.iterrows(), 1):
        print(f"Rank {i}: {row['bar_spec']}")
        print(f"  Sharpe: {row['sharpe_ratio']:.3f}, PnL: ${row['total_pnl']:.2f}")
        print(f"  MA: fast={row.get('fast_period', 'N/A')}, slow={row.get('slow_period', 'N/A')}")
        print(f"  Risk: SL={row.get('stop_loss_pips', 'N/A')}, TP={row.get('take_profit_pips', 'N/A')}")
        print(f"  Win Rate: {row['win_rate']*100:.1f}%, Trades: {int(row['trade_count'])}")
        print()
    
    print("=" * 100)
    print("PARAMETER PATTERNS BY TIMEFRAME")
    print("=" * 100)
    print()
    
    for timeframe in df['bar_spec'].unique():
        tf_df = df[df['bar_spec'] == timeframe]
        best = tf_df.loc[tf_df['sharpe_ratio'].idxmax()]
        
        print(f"Timeframe: {timeframe}")
        print(f"  Best Sharpe: {best['sharpe_ratio']:.3f}, PnL: ${best['total_pnl']:.2f}")
        print(f"  Optimal MA: fast={best.get('fast_period', 'N/A')}, slow={best.get('slow_period', 'N/A')}")
        print(f"  Optimal Risk: SL={best.get('stop_loss_pips', 'N/A')}, TP={best.get('take_profit_pips', 'N/A')}")
        print(f"  Avg Sharpe (all configs): {tf_df['sharpe_ratio'].mean():.3f}")
        print(f"  Configs tested: {len(tf_df)}")
        print()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze_timeframe_results.py <results_csv>")
        print("Example: python scripts/analyze_timeframe_results.py optimization/results/multi_timeframe_focused_results.csv")
        sys.exit(1)
    
    csv_file = Path(sys.argv[1])
    analyze_by_timeframe(csv_file)

