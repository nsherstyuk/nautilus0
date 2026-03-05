"""
Deep analysis of trades that reached +$60 unrealized profit.
Explore timing and SL tightening scenarios.
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

print("Analyzing trades that reached +$60 unrealized profit...")
print("=" * 70)

# Track trades that reached +$60
high_profit_trades = []

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
    
    # Track journey
    max_unrealized = 0
    bar_reached_60 = None
    time_reached_60 = None
    pnl_at_each_bar = []
    min_pnl_after_60 = None
    max_pnl_after_60 = None
    
    for bar_idx, (bar_time, bar_data) in enumerate(trade_bars.iterrows()):
        if side == 'LONG':
            high_pnl = (bar_data['high'] - entry_price) * 100000
            low_pnl = (bar_data['low'] - entry_price) * 100000
            close_pnl = (bar_data['close'] - entry_price) * 100000
        else:
            high_pnl = (entry_price - bar_data['low']) * 100000
            low_pnl = (entry_price - bar_data['high']) * 100000
            close_pnl = (entry_price - bar_data['close']) * 100000
        
        pnl_at_each_bar.append({
            'bar_idx': bar_idx,
            'time': bar_time,
            'high_pnl': high_pnl,
            'low_pnl': low_pnl,
            'close_pnl': close_pnl,
        })
        
        if high_pnl > max_unrealized:
            max_unrealized = high_pnl
        
        # Track when we first reach $60
        if bar_reached_60 is None and high_pnl >= 60:
            bar_reached_60 = bar_idx
            time_reached_60 = bar_time
            min_pnl_after_60 = low_pnl
            max_pnl_after_60 = high_pnl
        elif bar_reached_60 is not None:
            if low_pnl < min_pnl_after_60:
                min_pnl_after_60 = low_pnl
            if high_pnl > max_pnl_after_60:
                max_pnl_after_60 = high_pnl
    
    # Only track trades that reached +$60
    if max_unrealized >= 60:
        high_profit_trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'side': side,
            'final_pnl': final_pnl,
            'exit_reason': exit_reason,
            'max_unrealized': max_unrealized,
            'bar_reached_60': bar_reached_60,
            'mins_to_reach_60': bar_reached_60 * 15 if bar_reached_60 else None,
            'min_pnl_after_60': min_pnl_after_60,
            'max_pnl_after_60': max_pnl_after_60,
            'total_bars': len(trade_bars),
            'bars_after_60': len(trade_bars) - bar_reached_60 if bar_reached_60 else 0,
            'pnl_journey': pnl_at_each_bar,
        })

hp_df = pd.DataFrame(high_profit_trades)

print(f"\nTotal trades that reached +$60 unrealized: {len(hp_df)}")

# Split by outcome
winners = hp_df[hp_df['final_pnl'] > 0]
losers = hp_df[hp_df['final_pnl'] <= 0]

print(f"   Winners: {len(winners)} ({len(winners)/len(hp_df)*100:.1f}%)")
print(f"   Losers: {len(losers)} ({len(losers)/len(hp_df)*100:.1f}%)")

# ============================================
# TIMING ANALYSIS
# ============================================
print("\n" + "=" * 70)
print("1. TIMING TO REACH +$60")
print("=" * 70)

print("\nWinners:")
print(f"   Avg time to reach +$60: {winners['mins_to_reach_60'].mean():.0f} mins")
print(f"   Median: {winners['mins_to_reach_60'].median():.0f} mins")
print(f"   Avg bars after reaching +$60: {winners['bars_after_60'].mean():.0f}")

print("\nLosers:")
print(f"   Avg time to reach +$60: {losers['mins_to_reach_60'].mean():.0f} mins")
print(f"   Median: {losers['mins_to_reach_60'].median():.0f} mins")
print(f"   Avg bars after reaching +$60: {losers['bars_after_60'].mean():.0f}")

# ============================================
# DRAWDOWN AFTER REACHING +$60
# ============================================
print("\n" + "=" * 70)
print("2. MIN/MAX PnL AFTER REACHING +$60")
print("=" * 70)

print("\nWinners (after reaching +$60):")
print(f"   Avg min drawdown: ${winners['min_pnl_after_60'].mean():.2f}")
print(f"   Avg max profit: ${winners['max_pnl_after_60'].mean():.2f}")
print(f"   Avg final PnL: ${winners['final_pnl'].mean():.2f}")

print("\nLosers (after reaching +$60):")
print(f"   Avg min drawdown: ${losers['min_pnl_after_60'].mean():.2f}")
print(f"   Avg max profit: ${losers['max_pnl_after_60'].mean():.2f}")
print(f"   Avg final PnL: ${losers['final_pnl'].mean():.2f}")

# ============================================
# SL TIGHTENING SIMULATION
# ============================================
print("\n" + "=" * 70)
print("3. SL TIGHTENING SCENARIOS (after reaching +$60)")
print("=" * 70)

# Current system: trailing stop activates after TP1 (0.6 ATR ~$60 for EUR/USD)
# What if we tighten SL to different levels after reaching +$60?

for sl_level in [50, 40, 30, 20, 10, 0, -10, -20]:
    # Count how many trades would have been stopped out at this level
    winners_stopped = winners[winners['min_pnl_after_60'] <= sl_level]
    losers_stopped = losers[losers['min_pnl_after_60'] <= sl_level]
    
    # For winners stopped: they would exit at ~sl_level instead of final_pnl
    winners_lost_profit = winners_stopped['final_pnl'].sum() - (len(winners_stopped) * sl_level)
    
    # For losers stopped: they would exit at ~sl_level instead of final_pnl (negative)
    losers_saved = (len(losers_stopped) * sl_level) - losers_stopped['final_pnl'].sum()
    
    net = losers_saved - winners_lost_profit
    
    print(f"\nTighten SL to ${sl_level} after reaching +$60:")
    print(f"   Winners stopped early: {len(winners_stopped)} (lose ${winners_lost_profit:.0f} profit)")
    print(f"   Losers stopped early: {len(losers_stopped)} (save ${losers_saved:.0f})")
    print(f"   Net impact: ${net:.0f}")

# ============================================
# DETAILED LOOK AT THE 5 LOSERS
# ============================================
print("\n" + "=" * 70)
print("4. DETAILED ANALYSIS OF LOSERS THAT REACHED +$60")
print("=" * 70)

for _, trade in losers.iterrows():
    print(f"\n{str(trade['entry_time'])[:16]} | {trade['side']}")
    print(f"   Max unrealized: +${trade['max_unrealized']:.0f}")
    print(f"   Time to reach +$60: {trade['mins_to_reach_60']:.0f} mins")
    print(f"   Min PnL after +$60: ${trade['min_pnl_after_60']:.0f}")
    print(f"   Final PnL: ${trade['final_pnl']:.0f}")
    print(f"   Total duration: {trade['total_bars']*15} mins")
    
    # Show journey
    journey = trade['pnl_journey']
    print(f"   Journey (close PnL at each bar):")
    for j in journey[:20]:  # First 20 bars
        marker = " <-- reached +$60" if j['bar_idx'] == trade['bar_reached_60'] else ""
        print(f"      Bar {j['bar_idx']}: ${j['close_pnl']:.0f} (range: ${j['low_pnl']:.0f} to ${j['high_pnl']:.0f}){marker}")
    if len(journey) > 20:
        print(f"      ... ({len(journey) - 20} more bars)")

# ============================================
# OPTIMAL SL AFTER +$60
# ============================================
print("\n" + "=" * 70)
print("5. FINDING OPTIMAL SL LEVEL AFTER +$60")
print("=" * 70)

best_net = -float('inf')
best_sl = None

for sl_level in range(-50, 61, 5):
    winners_stopped = winners[winners['min_pnl_after_60'] <= sl_level]
    losers_stopped = losers[losers['min_pnl_after_60'] <= sl_level]
    
    winners_lost_profit = winners_stopped['final_pnl'].sum() - (len(winners_stopped) * sl_level)
    losers_saved = (len(losers_stopped) * sl_level) - losers_stopped['final_pnl'].sum()
    
    net = losers_saved - winners_lost_profit
    
    if net > best_net:
        best_net = net
        best_sl = sl_level

print(f"Optimal SL level after reaching +$60: ${best_sl}")
print(f"Net improvement: ${best_net:.0f}")

# Show impact at optimal level
winners_stopped = winners[winners['min_pnl_after_60'] <= best_sl]
losers_stopped = losers[losers['min_pnl_after_60'] <= best_sl]
print(f"   Winners affected: {len(winners_stopped)} of {len(winners)}")
print(f"   Losers caught: {len(losers_stopped)} of {len(losers)}")
