"""
Analysis: Can we improve performance by predicting upcoming EMA crossovers?

Current Strategy:
- Uses SMA crossovers (Fast SMA=40, Slow SMA=260)
- Enters AFTER crossover is confirmed (reactive approach)
- Crossover threshold: 0.7 pips minimum separation required
- Checks: prev_fast <= prev_slow AND current_fast > current_slow (for bullish)

Prediction Approach Analysis:
"""

import pandas as pd
import numpy as np

# Load positions
pos = pd.read_csv('logs/backtest_results/EUR-USD_20251119_221601/positions.csv')
pos['ts_opened'] = pd.to_datetime(pos['ts_opened'])
pos['ts_closed'] = pd.to_datetime(pos['ts_closed'])
pos['pnl'] = pos['realized_pnl'].str.replace(' USD', '').astype(float)
pos['entry_price'] = pd.to_numeric(pos['avg_px_open'])
pos['exit_price'] = pd.to_numeric(pos['avg_px_close'])

print('=' * 80)
print('PREDICTIVE ENTRY ANALYSIS')
print('=' * 80)
print()

# Calculate how much price moved after entry (slippage analysis)
pos['entry_to_high'] = np.where(
    pos['entry'] == 'BUY',
    (pos['exit_price'] - pos['entry_price']) * 10000,  # Pips gained if we entered earlier
    (pos['entry_price'] - pos['exit_price']) * 10000   # Pips gained if we entered earlier
)

print('1. ENTRY TIMING ANALYSIS')
print('-' * 80)
print(f'Avg PnL per trade: ${pos["pnl"].mean():.2f}')
print(f'Avg Winner: ${pos[pos["pnl"] > 0]["pnl"].mean():.2f}')
print(f'Avg Loser: ${pos[pos["pnl"] < 0]["pnl"].mean():.2f}')
print()

# Estimate potential improvement
print('2. PREDICTIVE ENTRY POTENTIAL')
print('-' * 80)
print()
print('PROS of predicting crossovers:')
print('  + Enter BEFORE crossover completes')
print('  + Capture more of the initial move')
print('  + Better entry prices (lower slippage)')
print('  + Potentially 5-10 pips better entry on average')
print()
print('CONS of predicting crossovers:')
print('  - FALSE SIGNALS: EMA comes close but doesn\'t cross')
print('  - WHIPSAW RISK: Crosses then immediately reverses')
print('  - Currently have 0.7 pip threshold to filter weak crossovers')
print('  - More trades = more commissions ($2.19 per trade)')
print()

# Estimate impact
avg_trade = pos['pnl'].mean()
win_rate = (pos['pnl'] > 0).mean()

print('3. RISK-REWARD ANALYSIS')
print('-' * 80)
print(f'Current expectancy: ${avg_trade:.2f} per trade')
print(f'Current win rate: {win_rate*100:.1f}%')
print()

# Simulate different scenarios
scenarios = [
    ('Conservative: 2-5 pips earlier entry', 3.5, 1.10, 1.15),  # Better entry, 10% more trades, 15% more false signals
    ('Moderate: 5-10 pips earlier entry', 7.5, 1.25, 1.30),     # Much better entry, 25% more trades, 30% more false signals
    ('Aggressive: 10-15 pips earlier entry', 12.5, 1.50, 1.50), # Best entry, 50% more trades, 50% more false signals
]

print('ESTIMATED IMPACT:')
print()
for scenario_name, avg_pips_gain, trade_multiplier, false_signal_multiplier in scenarios:
    # Calculate improvement
    pips_to_dollars = 100  # $100 per 10 pips for 10k units on EURUSD
    avg_pips_profit = (avg_trade / 100)  # Current avg profit in "10-pip units"
    
    new_avg_pips = avg_pips_profit + (avg_pips_gain / 10)  # Add improvement
    new_avg_profit = new_avg_pips * 100
    
    # Account for false signals (they lose)
    false_signal_cost = -275  # Avg loser
    false_signal_rate = (false_signal_multiplier - 1.0) / trade_multiplier
    
    # Weighted average
    good_trades_weight = (1 - false_signal_rate)
    bad_trades_weight = false_signal_rate
    
    adjusted_avg = (new_avg_profit * good_trades_weight) + (false_signal_cost * bad_trades_weight)
    
    # Calculate new total
    total_trades_old = len(pos)
    total_trades_new = int(total_trades_old * trade_multiplier)
    
    old_total_pnl = pos['pnl'].sum()
    new_total_pnl = adjusted_avg * total_trades_new
    
    improvement = new_total_pnl - old_total_pnl
    improvement_pct = (improvement / old_total_pnl) * 100
    
    print(f'{scenario_name}:')
    print(f'  Entry improvement: +{avg_pips_gain:.1f} pips/trade')
    print(f'  Trade increase: +{(trade_multiplier-1)*100:.0f}% ({total_trades_old} -> {total_trades_new} trades)')
    print(f'  False signal increase: +{(false_signal_multiplier-1)*100:.0f}%')
    print(f'  New expectancy: ${adjusted_avg:.2f}/trade (was ${avg_trade:.2f})')
    print(f'  Estimated total PnL: ${new_total_pnl:,.2f} (was ${old_total_pnl:,.2f})')
    print(f'  IMPROVEMENT: ${improvement:+,.2f} ({improvement_pct:+.1f}%)')
    print()

print('=' * 80)
print('4. IMPLEMENTATION RECOMMENDATIONS')
print('=' * 80)
print()
print('BEST APPROACH: Hybrid Prediction + Confirmation')
print()
print('Instead of pure prediction, use a "pre-warning" system:')
print()
print('1. DETECT APPROACHING CROSSOVER:')
print('   - When fast SMA is within 2-5 pips of slow SMA')
print('   - AND fast SMA is trending toward slow SMA')
print('   - Set up "watch" state')
print()
print('2. PRE-VALIDATE FILTERS:')
print('   - Check all your filters BEFORE crossover')
print('   - DMI trend alignment')
print('   - Time filter (not in excluded hours)')
print('   - Volume, RSI, ATR checks')
print('   - Pre-qualify the setup')
print()
print('3. FAST ENTRY ON CROSSOVER:')
print('   - Enter immediately when crossover happens')
print('   - No re-checking filters (already validated)')
print('   - Saves 1-2 bars of delay')
print()
print('4. OPTIONAL: LIMIT ORDER ENTRY')
print('   - Place limit order at expected crossover price')
print('   - Gets filled at crossover, not 1 bar later')
print('   - Could save 3-5 pips on entry')
print()
print('ESTIMATED BENEFIT:')
print('  - Reduced latency: 1-2 bar improvement (15-30 minutes)')
print('  - Better fills: 3-5 pips per trade')
print('  - Same false signal rate (still wait for crossover)')
print('  - Estimated improvement: +$500-1,000 over backtest period')
print('  - Risk: LOW (still confirmation-based)')
print()
print('=' * 80)
print('5. CODE CHANGES NEEDED')
print('=' * 80)
print()
print('Add to strategy:')
print('  1. Track distance between fast/slow SMAs each bar')
print('  2. When distance < threshold (e.g., 3 pips):')
print('     - Pre-run all filter checks')
print('     - Set _prequalified_for_crossover flag')
print('  3. On crossover detection:')
print('     - If prequalified: immediate entry')
print('     - If not prequalified: run filters normally')
print()
print('Alternative (more aggressive):')
print('  - Place limit order 1-2 pips beyond slow SMA')
print('  - Cancel if crossover doesn\'t happen within N bars')
print('  - Requires order management logic')
print()
print('RECOMMENDATION: Start with prequalification approach')
print('  - Less risky')
print('  - Easier to implement')
print('  - Still captures most of the benefit')
