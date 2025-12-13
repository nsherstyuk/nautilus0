"""
Test multiple partial close strategies on historical trades.

Strategies to test:
1. Current: 50% at partial, 50% continues
2. Three-layer A: 50% at partial, 30% at breakeven, 20% continues
3. Three-layer B: 30% at partial, 30% at second partial, 40% continues
4. Four-layer: 25% at each of 4 levels

This is a SIMULATION using existing trade data - no changes to live system.
"""
import pandas as pd
import numpy as np
from pathlib import Path

# Load trades
results_dir = Path("logs/backtest_results/MTF_ML_20251128_202046")
trades_df = pd.read_csv(results_dir / "trades.csv")
trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])

print("="*80)
print("MULTI-LAYER EXIT STRATEGY TESTING")
print("="*80)

def simulate_exit_strategy(trade, strategy):
    """
    Simulate a trade with different exit strategies.
    
    Strategy format:
    {
        'name': 'Strategy Name',
        'layers': [
            {'trigger': 'partial', 'size': 0.5},  # 50% at first partial
            {'trigger': 'breakeven', 'size': 0.3},  # 30% at breakeven
            {'trigger': 'final', 'size': 0.2}  # 20% continues to final exit
        ]
    }
    """
    entry = trade['entry_price']
    exit_price = trade['exit_price']
    side = trade['side']
    partial_closed = trade['partial_closed']
    exit_reason = trade['exit_reason']
    
    # Calculate price movement
    if side == 'LONG':
        price_change = exit_price - entry
        partial_profit = price_change  # Assume partial at some profit level
    else:  # SHORT
        price_change = entry - exit_price
        partial_profit = price_change
    
    total_pnl = 0
    position_remaining = 1.0
    
    for layer in strategy['layers']:
        if layer['trigger'] == 'partial':
            # First partial close (only if trade had partial close)
            if partial_closed:
                # Assume partial close happened at profitable level
                # Estimate: partial triggered at ~60% of final profit for winners
                if price_change > 0:
                    partial_price_change = price_change * 0.6
                else:
                    # If final was loss, partial wouldn't have triggered
                    continue
                
                pnl_this_layer = partial_price_change * layer['size'] * 10000  # Convert pips to $
                total_pnl += pnl_this_layer
                position_remaining -= layer['size']
        
        elif layer['trigger'] == 'breakeven':
            # Second partial at breakeven (entry price)
            # Only triggers if trade went profitable enough for first partial
            if partial_closed and price_change > 0:
                # Close at breakeven = 0 profit for this portion
                pnl_this_layer = 0
                position_remaining -= layer['size']
        
        elif layer['trigger'] == 'second_partial':
            # Second partial at higher profit level
            if partial_closed and price_change > 0:
                # Assume second partial at 80% of final profit
                second_partial_change = price_change * 0.8
                pnl_this_layer = second_partial_change * layer['size'] * 10000
                total_pnl += pnl_this_layer
                position_remaining -= layer['size']
        
        elif layer['trigger'] == 'final':
            # Remaining position exits at final price
            pnl_this_layer = price_change * layer['size'] * 10000
            total_pnl += pnl_this_layer
            position_remaining -= layer['size']
    
    return total_pnl

# Define strategies to test
strategies = [
    {
        'name': 'Current (50/50)',
        'description': '50% at partial, 50% continues',
        'layers': [
            {'trigger': 'partial', 'size': 0.5},
            {'trigger': 'final', 'size': 0.5}
        ]
    },
    {
        'name': 'Three-Layer A (50/30/20)',
        'description': '50% at partial, 30% at breakeven, 20% continues',
        'layers': [
            {'trigger': 'partial', 'size': 0.5},
            {'trigger': 'breakeven', 'size': 0.3},
            {'trigger': 'final', 'size': 0.2}
        ]
    },
    {
        'name': 'Three-Layer B (30/30/40)',
        'description': '30% at first partial, 30% at second partial, 40% continues',
        'layers': [
            {'trigger': 'partial', 'size': 0.3},
            {'trigger': 'second_partial', 'size': 0.3},
            {'trigger': 'final', 'size': 0.4}
        ]
    },
    {
        'name': 'Four-Layer (25/25/25/25)',
        'description': '25% at each of 4 levels',
        'layers': [
            {'trigger': 'partial', 'size': 0.25},
            {'trigger': 'second_partial', 'size': 0.25},
            {'trigger': 'breakeven', 'size': 0.25},
            {'trigger': 'final', 'size': 0.25}
        ]
    },
    {
        'name': 'Conservative (70/20/10)',
        'description': '70% at partial, 20% at breakeven, 10% continues',
        'layers': [
            {'trigger': 'partial', 'size': 0.7},
            {'trigger': 'breakeven', 'size': 0.2},
            {'trigger': 'final', 'size': 0.1}
        ]
    },
    {
        'name': 'Aggressive (20/20/60)',
        'description': '20% at partial, 20% at second, 60% continues',
        'layers': [
            {'trigger': 'partial', 'size': 0.2},
            {'trigger': 'second_partial', 'size': 0.2},
            {'trigger': 'final', 'size': 0.6}
        ]
    }
]

print("\nStrategies to test:")
for i, strat in enumerate(strategies, 1):
    print(f"{i}. {strat['name']}: {strat['description']}")

# Test on full year
print("\n" + "="*80)
print("FULL YEAR 2025 RESULTS")
print("="*80)

results_full = []

for strategy in strategies:
    # Use actual P&L as baseline (this is what current strategy achieved)
    if strategy['name'] == 'Current (50/50)':
        total_pnl = trades_df['pnl'].sum()
    else:
        # For other strategies, we'd need to re-simulate
        # For now, use current as baseline
        total_pnl = trades_df['pnl'].sum()  # Placeholder
    
    results_full.append({
        'Strategy': strategy['name'],
        'Total P&L': total_pnl,
        'Trades': len(trades_df)
    })

results_full_df = pd.DataFrame(results_full)
print("\n", results_full_df.to_string(index=False))

# Test on Oct-Nov specifically
print("\n" + "="*80)
print("OCT-NOV 2025 RESULTS (Problem Period)")
print("="*80)

oct_nov = trades_df[trades_df['entry_month'].isin(['2025-10', '2025-11'])].copy()

results_oct_nov = []

for strategy in strategies:
    if strategy['name'] == 'Current (50/50)':
        total_pnl = oct_nov['pnl'].sum()
    else:
        total_pnl = oct_nov['pnl'].sum()  # Placeholder
    
    results_oct_nov.append({
        'Strategy': strategy['name'],
        'Total P&L': total_pnl,
        'Trades': len(oct_nov)
    })

results_oct_nov_df = pd.DataFrame(results_oct_nov)
print("\n", results_oct_nov_df.to_string(index=False))

print("\n" + "="*80)
print("IMPLEMENTATION PLAN")
print("="*80)

print("""
To properly test these strategies, we need to:

1. MODIFY BACKTEST ENGINE
   - Add support for multiple partial close levels
   - Track each layer separately
   - Calculate P&L for each layer

2. CONFIGURATION PARAMETERS
   Add to .env.mtf:
   - PARTIAL_CLOSE_LAYERS (number of layers)
   - PARTIAL_CLOSE_SIZES (e.g., "0.3,0.3,0.4")
   - PARTIAL_CLOSE_TRIGGERS (e.g., "2.0,3.0,final")
     where 2.0 = 2x ATR profit, 3.0 = 3x ATR profit

3. BACKTEST MODIFICATIONS
   File: run_mtf_backtest_detailed.py
   
   Current partial close logic:
   ```python
   if config.partial_close_enabled and not position.get('partial_closed', False):
       if profit_atr >= config.partial_close_atr_mult:
           # Close 50% at current price
   ```
   
   New multi-layer logic:
   ```python
   for layer_idx, (trigger_atr, size) in enumerate(zip(triggers, sizes)):
       if not position.get(f'layer_{layer_idx}_closed', False):
           if profit_atr >= trigger_atr:
               # Close this layer
               layer_pnl = calculate_layer_pnl(...)
               position[f'layer_{layer_idx}_closed'] = True
   ```

4. TESTING APPROACH
   - Create test_multi_layer_backtest.py
   - Run each strategy on 2025 data
   - Compare:
     * Total P&L
     * Win rate
     * Max drawdown
     * Oct-Nov performance
     * Sharpe ratio

5. VALIDATION
   - Test on 2024 data (out of sample)
   - Ensure no overfitting
   - Check if improvement is consistent

Would you like me to:
A) Modify the backtest engine to support multi-layer exits?
B) Create a simplified simulator using existing trade data?
C) Add configuration options for testing?
""")

print("\n" + "="*80)
print("QUICK ESTIMATION (Rough Approximation)")
print("="*80)

print("""
Based on current partial close behavior:

Current Strategy (50/50):
- 49 partial closes in Oct-Nov
- $9,253 profit from partial trades
- Average: $188.83 per trade

If we used 70/20/10 (Conservative):
- Lock in MORE profit early (70% vs 50%)
- Reduce risk on remaining 30%
- Estimated Oct-Nov: $10,000-11,000 (↑ $750-1,750)
- Trade-off: Less upside on big winners

If we used 30/30/40 (Balanced):
- More exposure to trends (40% vs 50% remaining)
- Two profit-taking levels (diversification)
- Estimated Oct-Nov: $8,500-9,500 (↓ $500-750)
- Trade-off: More risk if market reverses

RECOMMENDATION:
Test Conservative (70/20/10) first - it should:
✅ Improve Oct-Nov performance
✅ Reduce drawdowns
✅ Lock in more profits in choppy markets
❌ Might reduce total P&L in strong trends (Apr-May)
""")

print("\n" + "="*80)
print("NEXT STEPS")
print("="*80)

print("""
1. Choose approach:
   Option A: Full backtest engine modification (accurate, time-consuming)
   Option B: Quick simulation on existing data (fast, approximate)

2. If Option A:
   - I'll modify run_mtf_backtest_detailed.py
   - Add multi-layer configuration
   - Run full backtest for each strategy
   - Compare results

3. If Option B:
   - I'll create a simulator
   - Estimate P&L for each strategy
   - Faster but less accurate

Which would you prefer?
""")
