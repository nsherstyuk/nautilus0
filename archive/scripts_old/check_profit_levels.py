from pathlib import Path
import pandas as pd
from decimal import Decimal

results_dir = Path('logs/backtest_results')
latest = max(results_dir.glob('EUR-USD_*'), key=lambda p: p.stat().st_mtime)
pos = pd.read_csv(latest / 'positions.csv')
pip = Decimal('0.0001')

print(f'Latest: {latest.name}\n')
print('Trade profits (final, in pips):')
profits = []
for i, p in pos.iterrows():
    entry = Decimal(str(p['avg_px_open']))
    exit = Decimal(str(p['avg_px_close']))
    side = p['side']
    profit = float(((exit - entry) if side == 'LONG' else (entry - exit)) / pip)
    profits.append(profit)
    print(f'{i+1}. {side:5s} {profit:+7.1f} pips')

print(f'\nActivation threshold: 15 pips')
above_threshold = [p for p in profits if p >= 15]
print(f'Trades >= 15 pips: {len(above_threshold)} of {len(profits)} ({len(above_threshold)/len(profits)*100 if profits else 0:.1f}%)')

if not above_threshold:
    print('\n⚠️  ROOT CAUSE FOUND:')
    print('   NO trades reached the 15-pip activation threshold at exit.')
    print('   All trades closed before trailing could activate.')
    print()
    print('   This is why trailing never modified any stops.')
