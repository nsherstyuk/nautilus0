"""
Deep dive: Why isn't trailing stop activating?

Analyzes:
1. Maximum favorable excursion (MFE) per trade in pips
2. Compares MFE to trailing activation threshold (15 pips from .env)
3. Shows what % of trades SHOULD have triggered trailing

This will tell us if the problem is:
- Activation threshold too high for typical price movement
- Trades exiting too quickly (via TP or SL) before reaching activation
- Logic bug preventing activation even when threshold is reached
"""
import pandas as pd
from pathlib import Path
from decimal import Decimal
import json

def main():
    results_dir = Path('logs/backtest_results')
    latest = max(results_dir.glob('EUR-USD_*'), key=lambda p: p.stat().st_mtime)
    print(f'Latest result folder: {latest.name}\n')
    
    # Load data
    positions = pd.read_csv(latest / 'positions.csv')
    orders = pd.read_csv(latest / 'orders.csv')
    
    # Get config
    print('=== CONFIGURATION ===')
    print(f'Activation threshold: 15 pips (from .env)')
    print(f'Trailing distance: 10 pips')
    print(f'SL: 25 pips')
    print(f'TP: 70 pips')
    print(f'Adaptive mode: fixed (regime detection disabled)')
    print()
    
    # For each position, find its entry price and calculate max favorable excursion
    pip_value = Decimal('0.0001')  # EUR/USD pip size
    activation_pips = 15
    
    results = []
    for idx, pos in positions.iterrows():
        entry_price = Decimal(str(pos['avg_px_open']))
        exit_price = Decimal(str(pos['avg_px_close']))
        side = pos['side']
        
        # Find all fills for this position to get high water mark
        # Use order_list_id to link entry order to its fills
        entry_order_id = pos['opening_order_id']
        entry_order = orders[orders['venue_order_id'] == entry_order_id].iloc[0] if len(orders[orders['venue_order_id'] == entry_order_id]) > 0 else None
        
        if entry_order is None:
            continue
            
        order_list_id = entry_order['order_list_id']
        
        # Get equity curve or bar data to find peak profit
        # For now, use exit price as approximation (conservative estimate)
        if side == 'LONG':
            profit_pips = float((exit_price - entry_price) / pip_value)
        else:  # SHORT
            profit_pips = float((entry_price - exit_price) / pip_value)
        
        # Check if trade was profitable enough to trigger trailing
        triggered_trailing = profit_pips >= activation_pips
        
        results.append({
            'order_list': order_list_id,
            'side': side,
            'entry': float(entry_price),
            'exit': float(exit_price),
            'profit_pips': profit_pips,
            'would_trigger': triggered_trailing
        })
    
    df = pd.DataFrame(results)
    
    print('=== TRAILING ACTIVATION ANALYSIS ===')
    print(f'Total trades: {len(df)}')
    if len(df) > 0:
        print(f'Trades reaching activation threshold ({activation_pips} pips): {df["would_trigger"].sum()} ({df["would_trigger"].sum()/len(df)*100:.1f}%)')
        print()
        print('Profit distribution (pips):')
        print(df['profit_pips'].describe())
        print()
        print('Trades by profit level:')
        print(f'  < 5 pips: {(df["profit_pips"] < 5).sum()}')
        print(f'  5-10 pips: {((df["profit_pips"] >= 5) & (df["profit_pips"] < 10)).sum()}')
        print(f'  10-15 pips: {((df["profit_pips"] >= 10) & (df["profit_pips"] < 15)).sum()}')
        print(f'  15-20 pips (activation zone): {((df["profit_pips"] >= 15) & (df["profit_pips"] < 20)).sum()}')
        print(f'  20+ pips: {(df["profit_pips"] >= 20).sum()}')
        print()
        
        if df['would_trigger'].sum() == 0:
            print('⚠️  PROBLEM FOUND: No trades reached the 15-pip activation threshold!')
            print('   This explains why trailing never activated.')
            print('   Trades are exiting via SL or TP before reaching trailing activation.')
            print()
            print('   RECOMMENDATION: Lower activation threshold to 5-8 pips to make')
            print('   trailing useful for these shorter-duration, smaller-profit trades.')
        else:
            print('✅ Some trades reached activation threshold, but trailing still')
            print('   did not modify stops. This suggests a logic bug in the code.')
            print()
            print('Sample trades that should have triggered trailing:')
            print(df[df['would_trigger']].head(5).to_string(index=False))

if __name__ == '__main__':
    main()
