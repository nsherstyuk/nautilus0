import pandas as pd
from pathlib import Path

latest = Path('backtest_results/MTF_V2_REPLAY_20251224_194453')
original = Path('backtest_results/MTF_V2_REPLAY_20251224_173121')

pos_new = pd.read_csv(latest / 'positions.csv')
pos_old = pd.read_csv(original / 'positions.csv')

def parse_pnl(x):
    s = str(x).replace(' USD', '').strip()
    return float(s) if s and s != 'nan' else 0.0

pnl_new = pos_new['realized_pnl'].apply(parse_pnl).sum()
pnl_old = pos_old['realized_pnl'].apply(parse_pnl).sum()

print('COMPARISON: Original vs With Slippage')
print('===========================================')
print('')
print('Original (no slippage):')
print(f'  Positions: {len(pos_old)}')
print(f'  Total PnL: ${pnl_old:,.2f}')
print('')
print('With slippage (40% prob):')
print(f'  Positions: {len(pos_new)}')
print(f'  Total PnL: ${pnl_new:,.2f}')
print('')
print('Impact:')
print(f'  Position difference: {len(pos_new) - len(pos_old):+d}')
if pnl_old != 0:
    print(f'  PnL difference: ${pnl_new - pnl_old:+,.2f} ({((pnl_new - pnl_old) / pnl_old * 100):+.1f}%)')
else:
    print(f'  PnL difference: ${pnl_new - pnl_old:+,.2f}')
