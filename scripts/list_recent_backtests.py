from pathlib import Path
import json

files = sorted(
    Path('logs/backtest_results').glob('EUR-USD_*/performance_stats.json'),
    key=lambda x: x.stat().st_mtime,
    reverse=True
)

print('Recent backtest runs:')
for i, f in enumerate(files[:10]):
    stats = json.load(open(f))
    print(f'{i+1}. {f.parent.name}')
    print(f'   PnL: ${stats["pnls"]["PnL (total)"]:,.2f}')
    print(f'   Rejected Signals: {stats["rejected_signals_count"]}')
    print()



