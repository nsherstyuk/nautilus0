import json
import sys

positions_file = sys.argv[1] if len(sys.argv) > 1 else 'logs/eurusd_regime_final/run_0001/EUR-USD_20251115_113506/positions.json'

with open(positions_file) as f:
    positions = json.load(f)

print(f'Total positions: {len(positions)}')
print('\nFirst 5 positions TP/SL distances:')
for i, p in enumerate(positions[:5]):
    entry = float(p['entry_price'])
    tp = float(p.get('take_profit_price', 0))
    sl = float(p.get('stop_loss_price', 0))
    side = p['side']
    
    if side == 'BUY':
        tp_pips = (tp - entry) * 10000
        sl_pips = (entry - sl) * 10000
    else:
        tp_pips = (entry - tp) * 10000
        sl_pips = (sl - entry) * 10000
    
    print(f"  Pos {i+1} ({side}): TP={tp_pips:.1f} pips, SL={sl_pips:.1f} pips")

print('\nLast 5 positions TP/SL distances:')
for i, p in enumerate(positions[-5:]):
    entry = float(p['entry_price'])
    tp = float(p.get('take_profit_price', 0))
    sl = float(p.get('stop_loss_price', 0))
    side = p['side']
    
    if side == 'BUY':
        tp_pips = (tp - entry) * 10000
        sl_pips = (entry - sl) * 10000
    else:
        tp_pips = (entry - tp) * 10000
        sl_pips = (sl - entry) * 10000
    
    print(f"  Pos {len(positions)-4+i} ({side}): TP={tp_pips:.1f} pips, SL={sl_pips:.1f} pips")

# Check for unique TP/SL combinations
tp_sl_combos = set()
for p in positions:
    entry = float(p['entry_price'])
    tp = float(p.get('take_profit_price', 0))
    sl = float(p.get('stop_loss_price', 0))
    side = p['side']
    
    if side == 'BUY':
        tp_pips = round((tp - entry) * 10000, 1)
        sl_pips = round((entry - sl) * 10000, 1)
    else:
        tp_pips = round((entry - tp) * 10000, 1)
        sl_pips = round((sl - entry) * 10000, 1)
    
    tp_sl_combos.add((tp_pips, sl_pips))

print(f'\nUnique TP/SL combinations: {len(tp_sl_combos)}')
for combo in sorted(tp_sl_combos):
    print(f"  TP={combo[0]} pips, SL={combo[1]} pips")
