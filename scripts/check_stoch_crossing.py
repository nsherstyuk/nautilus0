"""
Diagnostic script to check if stochastic crossing detection is working
"""
import pandas as pd
from pathlib import Path

results_dir = Path('logs/backtest_results')
# Find most recent backtest
dirs = sorted([d for d in results_dir.iterdir() if d.is_dir()], 
              key=lambda d: d.stat().st_mtime, reverse=True)

if not dirs:
    print("No backtest results found")
    exit(1)

latest_dir = dirs[0]
print(f"Analyzing: {latest_dir.name}")

# Check rejected signals
rejected_file = latest_dir / 'rejected_signals.csv'
if rejected_file.exists():
    rejected_df = pd.read_csv(rejected_file)
    
    # Count rejections by reason
    if 'reason' in rejected_df.columns:
        reason_counts = rejected_df['reason'].value_counts()
        print("\nRejected signal reasons:")
        print(reason_counts)
        
        # Check for stochastic-related rejections
        stoch_rejections = rejected_df[rejected_df['reason'].str.contains('stochastic', case=False, na=False)]
        print(f"\nTotal stochastic-related rejections: {len(stoch_rejections)}")
        
        if len(stoch_rejections) > 0:
            print("\nStochastic rejection breakdown:")
            print(stoch_rejections['reason'].value_counts())
    else:
        print("No 'reason' column in rejected_signals.csv")
else:
    print("No rejected_signals.csv found")

# Check performance stats
stats_file = latest_dir / 'performance_stats.json'
if stats_file.exists():
    import json
    stats = json.load(open(stats_file))
    print(f"\nTotal rejected signals: {stats.get('rejected_signals_count', 'N/A')}")
    print(f"Total PnL: ${stats['pnls']['PnL (total)']:,.2f}")






