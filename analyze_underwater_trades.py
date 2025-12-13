"""
Analyze underwater trades - how long do trades spend in negative territory?
For winning trades that were temporarily underwater, this helps understand
if a time-based exit would hurt more than help.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog

# Load trades
results_dir = 'backtest_results/MTF_V2_20251206_171427'
trades_df = pd.read_csv(f'{results_dir}/trades.csv')
trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])

# Load bar data
PROJECT_ROOT = Path(__file__).parent
catalog = ParquetDataCatalog(str(PROJECT_ROOT / "data" / "historical"))
bars = catalog.bars(instrument_ids=["EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"])

bar_df = pd.DataFrame([{
    'timestamp': b.ts_event,
    'open': float(b.open),
    'high': float(b.high),
    'low': float(b.low),
    'close': float(b.close),
} for b in bars])
bar_df['timestamp'] = pd.to_datetime(bar_df['timestamp'], unit='ns', utc=True)
bar_df = bar_df.set_index('timestamp').sort_index()

print("Analyzing underwater periods for each trade...")
print("=" * 70)

# For each trade, analyze bar-by-bar PnL
trade_underwater_stats = []

for idx, trade in trades_df.iterrows():
    entry_time = trade['entry_time']
    exit_time = trade['exit_time']
    entry_price = trade['entry']
    side = trade['side']
    final_pnl = trade['pnl']
    exit_reason = trade['exit_reason']
    
    # Get bars during this trade
    trade_bars = bar_df[(bar_df.index >= entry_time) & (bar_df.index <= exit_time)]
    
    if len(trade_bars) == 0:
        continue
    
    # Calculate unrealized PnL at each bar
    max_drawdown = 0
    max_unrealized_profit = 0
    time_underwater = 0  # bars spent negative
    first_underwater_bar = None
    recovered_from_underwater = False
    deepest_underwater_time = None
    
    for bar_idx, (bar_time, bar_data) in enumerate(trade_bars.iterrows()):
        if side == 'LONG':
            # Use low for worst case, close for typical
            worst_pnl = (bar_data['low'] - entry_price) * 100000  # approximate
            typical_pnl = (bar_data['close'] - entry_price) * 100000
        else:
            worst_pnl = (entry_price - bar_data['high']) * 100000
            typical_pnl = (entry_price - bar_data['close']) * 100000
        
        if worst_pnl < max_drawdown:
            max_drawdown = worst_pnl
            deepest_underwater_time = bar_time
        
        if typical_pnl > max_unrealized_profit:
            max_unrealized_profit = typical_pnl
        
        if typical_pnl < 0:
            time_underwater += 1
            if first_underwater_bar is None:
                first_underwater_bar = bar_time
    
    # Was this trade ever underwater but ended positive?
    was_underwater = max_drawdown < -10  # at least $10 underwater
    ended_positive = final_pnl > 0
    
    trade_underwater_stats.append({
        'entry_time': entry_time,
        'exit_time': exit_time,
        'side': side,
        'final_pnl': final_pnl,
        'exit_reason': exit_reason,
        'max_drawdown': max_drawdown,
        'max_unrealized_profit': max_unrealized_profit,
        'bars_underwater': time_underwater,
        'mins_underwater': time_underwater * 15,
        'was_underwater': was_underwater,
        'ended_positive': ended_positive,
        'recovered': was_underwater and ended_positive,
        'duration_bars': len(trade_bars),
        'duration_mins': len(trade_bars) * 15,
    })

stats_df = pd.DataFrame(trade_underwater_stats)

# ============================================
# ANALYSIS 1: SL trades - time before hitting SL
# ============================================
print("\n" + "=" * 70)
print("1. SL TRADES - TIME BEFORE HITTING STOP LOSS")
print("=" * 70)

sl_trades = stats_df[stats_df['exit_reason'] == 'SL']
print(f"Total SL trades: {len(sl_trades)}")
print(f"\nTime before SL hit:")
print(f"   0-15 min:    {len(sl_trades[sl_trades['duration_mins'] <= 15])} trades")
print(f"   15-60 min:   {len(sl_trades[(sl_trades['duration_mins'] > 15) & (sl_trades['duration_mins'] <= 60)])} trades")
print(f"   1-3 hours:   {len(sl_trades[(sl_trades['duration_mins'] > 60) & (sl_trades['duration_mins'] <= 180)])} trades")
print(f"   >3 hours:    {len(sl_trades[sl_trades['duration_mins'] > 180])} trades")

print(f"\nMax drawdown before SL hit:")
print(f"   Avg: ${sl_trades['max_drawdown'].mean():.2f}")
print(f"   Median: ${sl_trades['max_drawdown'].median():.2f}")

# ============================================
# ANALYSIS 2: Winning trades that recovered from underwater
# ============================================
print("\n" + "=" * 70)
print("2. WINNING TRADES THAT WERE UNDERWATER FIRST")
print("=" * 70)

winning_trades = stats_df[stats_df['ended_positive']]
recovered_trades = stats_df[stats_df['recovered']]

print(f"Total winning trades: {len(winning_trades)}")
print(f"Winning trades that were underwater first: {len(recovered_trades)} ({len(recovered_trades)/len(winning_trades)*100:.1f}%)")
print(f"\nThese recovered trades:")
print(f"   Total PnL: ${recovered_trades['final_pnl'].sum():.2f}")
print(f"   Avg PnL: ${recovered_trades['final_pnl'].mean():.2f}")
print(f"   Avg time underwater: {recovered_trades['mins_underwater'].mean():.0f} mins")
print(f"   Avg max drawdown: ${recovered_trades['max_drawdown'].mean():.2f}")

# ============================================
# ANALYSIS 3: What if we exited after X mins underwater?
# ============================================
print("\n" + "=" * 70)
print("3. IMPACT OF TIME-BASED EXIT RULE")
print("=" * 70)

# Current baseline
current_total_pnl = stats_df['final_pnl'].sum()
print(f"Current Total PnL: ${current_total_pnl:.2f}")
print()

# Simulate different time-based exit rules
for exit_mins in [15, 30, 45, 60, 90, 120]:
    # Trades that would be closed early (were underwater for > X mins)
    # For SL trades: would we save money?
    sl_early_exit = sl_trades[sl_trades['mins_underwater'] >= exit_mins]
    # Estimate savings: assume we close at 50% of final loss
    sl_savings = sl_early_exit['final_pnl'].sum() * 0.5  # half the loss saved
    
    # For winning trades that recovered: we'd miss these gains
    lost_winners = recovered_trades[recovered_trades['mins_underwater'] >= exit_mins]
    lost_profit = lost_winners['final_pnl'].sum()
    
    net_impact = sl_savings - lost_profit
    
    print(f"Exit if underwater for {exit_mins} mins:")
    print(f"   SL trades affected: {len(sl_early_exit)} (save ~${-sl_savings:.0f})")
    print(f"   Winners killed: {len(lost_winners)} (lose ${lost_profit:.0f})")
    print(f"   Net impact: ${net_impact:.0f}")
    print()

# ============================================
# ANALYSIS 4: Deep dive on recovered trades
# ============================================
print("=" * 70)
print("4. RECOVERED TRADES - DETAILED BREAKDOWN")
print("=" * 70)

print("\nBy time spent underwater:")
for mins_threshold in [15, 30, 60, 120, 180]:
    subset = recovered_trades[recovered_trades['mins_underwater'] >= mins_threshold]
    if len(subset) > 0:
        print(f"   Underwater {mins_threshold}+ mins: {len(subset)} trades, Total PnL: ${subset['final_pnl'].sum():.2f}")

print("\nBy max drawdown depth:")
for dd_threshold in [-50, -75, -100, -125, -150]:
    subset = recovered_trades[recovered_trades['max_drawdown'] <= dd_threshold]
    if len(subset) > 0:
        print(f"   Drawdown {dd_threshold}+ : {len(subset)} trades, Total PnL: ${subset['final_pnl'].sum():.2f}")

# ============================================
# ANALYSIS 5: Most impressive recoveries
# ============================================
print("\n" + "=" * 70)
print("5. TOP 10 MOST IMPRESSIVE RECOVERIES")
print("=" * 70)

top_recoveries = recovered_trades.nlargest(10, 'final_pnl')
print("Trades with biggest max drawdown that still ended positive:")
for _, t in top_recoveries.iterrows():
    print(f"   {str(t['entry_time'])[:16]} | DD: ${t['max_drawdown']:.0f} -> Final: +${t['final_pnl']:.0f} | Underwater: {t['mins_underwater']:.0f}min")
