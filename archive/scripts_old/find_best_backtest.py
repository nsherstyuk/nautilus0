import pandas as pd
import os
from pathlib import Path

results = []
for folder in Path('logs/backtest_results').glob('MTF_ML_20251129_*'):
    trades_path = folder / 'trades.csv'
    summary_path = folder / 'summary.txt'
    if trades_path.exists() and summary_path.exists():
        df = pd.read_csv(trades_path, parse_dates=['entry_time', 'exit_time'])
        summary = open(summary_path).read()
        total_pnl = df['pnl'].sum()
        
        # 2025 monthly P&L
        df_2025 = df[df['exit_time'].dt.year == 2025]
        monthly = df_2025.groupby(df_2025['exit_time'].dt.month)['pnl'].sum()
        
        # Check if all 2025 months (1-11) are positive and above 20K
        all_positive = all(monthly.get(m, 0) > 0 for m in range(1, 12))
        all_above_20k = all(monthly.get(m, 0) > 20000 for m in range(1, 12))
        nov_pnl = monthly.get(11, 0)
        min_pnl = min(monthly.get(m, 0) for m in range(1, 12))
        
        if all_positive:  # Just positive, not $20K filter
            results.append({
                'folder': folder.name,
                'total': total_pnl,
                'nov': nov_pnl,
                'min_month': min_pnl,
                'monthly': monthly
            })

results.sort(key=lambda x: x['min_month'], reverse=True)  # Sort by min month
print(f"Found {len(results)} backtests with all 2025 months positive:\n")

for r in results[:10]:
    print(f"{r['folder']}: Total=${r['total']:,.0f}, Nov=${r['nov']:,.0f}, Min=${r['min_month']:,.0f}")
    # Print monthly breakdown
    print("  Monthly P&L:", end=" ")
    for m in range(1, 12):
        pnl = r['monthly'].get(m, 0)
        print(f"{m}:${pnl/1000:.0f}K", end=" ")
    print()
