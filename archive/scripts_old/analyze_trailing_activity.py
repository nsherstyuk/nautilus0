"""
Diagnostic script: Analyze trailing stop activity per position/trade.

In NETTING mode, all trades share the same position_id, so we need to group by
trade cycles using order_list_id (bracket orders) or parent_order_id.

- Reports how many trades had their SL (STOP_MARKET) modified (multiple unique trigger prices).
- Summarizes the distribution: how many trades had 1, 2, 3+ SL modifications.
- Shows example trades with heavy trailing activity.
- Checks how many trades exited via SL vs TP.

Usage:
    python analyze_trailing_activity.py
"""
import pandas as pd
from pathlib import Path
import json
from collections import Counter

def main():
    results_dir = Path('logs/backtest_results')
    latest = max(results_dir.glob('EUR-USD_*'), key=lambda p: p.stat().st_mtime)
    print(f'Latest result folder: {latest.name}\n')

    orders = pd.read_csv(latest / 'orders.csv')
    positions = pd.read_csv(latest / 'positions.csv')
    fills = pd.read_csv(latest / 'fills.csv') if (latest / 'fills.csv').exists() else None

    # In NETTING mode, use order_list_id to group bracket orders (entry + SL + TP for each trade)
    sl_orders = orders[orders['type'] == 'STOP_MARKET'].copy()
    
    if 'order_list_id' not in sl_orders.columns:
        print('ERROR: No order_list_id column found in orders.csv')
        return
    
    # Count unique SL trigger prices per order_list (i.e., per trade/bracket)
    sl_mods_per_trade = sl_orders.groupby('order_list_id')['trigger_price'].nunique()
    mod_counts = Counter(sl_mods_per_trade)

    print('Trailing SL modification count per trade:')
    for n in sorted(mod_counts):
        print(f'  {n} unique SL prices: {mod_counts[n]} trades')
    print()
    
    total_trades = sum(mod_counts.values())
    multi_mod = sum(v for k, v in mod_counts.items() if k > 1)
    print(f'Total trades (with SL orders): {total_trades}')
    print(f'Trades with >1 SL price (trailing activated): {multi_mod} ({multi_mod/total_trades*100:.1f}%)')
    
    # Show examples of trades with heavy trailing
    if multi_mod > 0:
        heavy_trailing = sl_mods_per_trade[sl_mods_per_trade > 1].sort_values(ascending=False).head(5)
        print(f'\nTop 5 trades with most SL modifications:')
        for order_list_id, num_mods in heavy_trailing.items():
            trade_sl_orders = sl_orders[sl_orders['order_list_id'] == order_list_id]
            prices = sorted(trade_sl_orders['trigger_price'].unique())
            print(f'  {order_list_id}: {num_mods} modifications')
            print(f'    Trigger prices: {[f"{p:.5f}" for p in prices[:6]]}{"..." if len(prices) > 6 else ""}')

    # Optional: check how many trades exited via SL vs TP
    if fills is not None and 'order_type' in fills.columns:
        sl_fills = fills[fills['order_type'] == 'STOP_MARKET']
        # Check if tags column exists in fills
        if 'tags' in fills.columns:
            tp_fills = fills[fills['order_type'].str.contains('LIMIT', na=False) & fills['tags'].str.contains('TP', na=False)]
        else:
            tp_fills = fills[fills['order_type'] == 'LIMIT']
        print(f'\nExit type breakdown (fills):')
        print(f'  SL (STOP_MARKET) fills: {len(sl_fills)}')
        print(f'  TP (LIMIT with TP tag) fills: {len(tp_fills)}')
        print(f'  Other fills: {len(fills) - len(sl_fills) - len(tp_fills)}')

if __name__ == '__main__':
    main()
