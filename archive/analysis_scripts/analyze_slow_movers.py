"""
Analyze slow vs fast movers to +$60 and test time-based SL adjustment.
Also explore other scenarios that might improve performance.
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

print("Analyzing slow vs fast movers to +$60...")
print("=" * 70)

# Track detailed journey for each trade
trade_data = []

for idx, trade in trades_df.iterrows():
    entry_time = trade['entry_time']
    exit_time = trade['exit_time']
    entry_price = trade['entry']
    side = trade['side']
    final_pnl = trade['pnl']
    exit_reason = trade['exit_reason']
    entry_hour = trade['entry_hour']
    
    trade_bars = bar_df[(bar_df.index >= entry_time) & (bar_df.index <= exit_time)]
    
    if len(trade_bars) == 0:
        continue
    
    # Track journey
    max_unrealized = 0
    bars_to_60 = None
    min_pnl_after_60 = None
    max_pnl_after_60 = None
    
    for bar_idx, (bar_time, bar_data) in enumerate(trade_bars.iterrows()):
        if side == 'LONG':
            high_pnl = (bar_data['high'] - entry_price) * 100000
            low_pnl = (bar_data['low'] - entry_price) * 100000
        else:
            high_pnl = (entry_price - bar_data['low']) * 100000
            low_pnl = (entry_price - bar_data['high']) * 100000
        
        if high_pnl > max_unrealized:
            max_unrealized = high_pnl
        
        if bars_to_60 is None and high_pnl >= 60:
            bars_to_60 = bar_idx
            min_pnl_after_60 = low_pnl
            max_pnl_after_60 = high_pnl
        elif bars_to_60 is not None:
            if low_pnl < min_pnl_after_60:
                min_pnl_after_60 = low_pnl
            if high_pnl > max_pnl_after_60:
                max_pnl_after_60 = high_pnl
    
    if max_unrealized >= 60:
        trade_data.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'side': side,
            'final_pnl': final_pnl,
            'exit_reason': exit_reason,
            'entry_hour': entry_hour,
            'max_unrealized': max_unrealized,
            'bars_to_60': bars_to_60,
            'mins_to_60': bars_to_60 * 15 if bars_to_60 is not None else None,
            'min_pnl_after_60': min_pnl_after_60,
            'max_pnl_after_60': max_pnl_after_60,
            'total_bars': len(trade_bars),
            'ended_positive': final_pnl > 0,
        })

df = pd.DataFrame(trade_data)
df = df.dropna(subset=['mins_to_60'])  # Only trades where we know time to +$60

print(f"Total trades that reached +$60: {len(df)}")

# ============================================
# 1. FAST VS SLOW MOVERS COMPARISON
# ============================================
print("\n" + "=" * 70)
print("1. FAST VS SLOW MOVERS TO +$60")
print("=" * 70)

# Define speed categories
df['speed_category'] = pd.cut(df['mins_to_60'], 
                               bins=[0, 15, 30, 60, 120, float('inf')],
                               labels=['0-15min', '15-30min', '30-60min', '60-120min', '120+min'])

for cat in ['0-15min', '15-30min', '30-60min', '60-120min', '120+min']:
    subset = df[df['speed_category'] == cat]
    if len(subset) == 0:
        continue
    winners = subset[subset['ended_positive']]
    losers = subset[~subset['ended_positive']]
    
    print(f"\n{cat}:")
    print(f"   Total: {len(subset)}")
    print(f"   Win Rate: {len(winners)/len(subset)*100:.1f}%")
    print(f"   Winners: {len(winners)}, Avg PnL: ${winners['final_pnl'].mean():.2f}" if len(winners) > 0 else "   Winners: 0")
    print(f"   Losers: {len(losers)}, Avg PnL: ${losers['final_pnl'].mean():.2f}" if len(losers) > 0 else "   Losers: 0")
    print(f"   Losers avg min after +$60: ${losers['min_pnl_after_60'].mean():.2f}" if len(losers) > 0 else "")

# ============================================
# 2. TIME-BASED SL ADJUSTMENT SIMULATION
# ============================================
print("\n" + "=" * 70)
print("2. TIME-BASED SL ADJUSTMENT (Tighten for slow movers)")
print("=" * 70)

# Idea: If trade takes > X mins to reach +$60, tighten SL to Y
# Fast movers: keep original trailing
# Slow movers: tighten SL

current_pnl = df['final_pnl'].sum()
print(f"Current total PnL: ${current_pnl:.2f}")

# Test different thresholds
for slow_threshold in [30, 45, 60, 90, 120]:
    print(f"\n--- Slow threshold: {slow_threshold} mins ---")
    
    for sl_level in [40, 30, 20, 10, 0, -10]:
        # Fast trades: unchanged
        fast_trades = df[df['mins_to_60'] < slow_threshold]
        fast_pnl = fast_trades['final_pnl'].sum()
        
        # Slow trades: apply tighter SL
        slow_trades = df[df['mins_to_60'] >= slow_threshold]
        
        # For each slow trade, check if it would have been stopped at sl_level
        slow_pnl = 0
        stopped_early = 0
        for _, trade in slow_trades.iterrows():
            if trade['min_pnl_after_60'] <= sl_level:
                # Would have been stopped at sl_level
                slow_pnl += sl_level
                stopped_early += 1
            else:
                # Would not have been stopped, keep original exit
                slow_pnl += trade['final_pnl']
        
        new_total = fast_pnl + slow_pnl
        diff = new_total - current_pnl
        
        if diff > 0:
            print(f"   SL=${sl_level} for slow trades: +${diff:.0f} ({stopped_early} stopped early)")

# ============================================
# 3. ANALYSIS BY ENTRY HOUR
# ============================================
print("\n" + "=" * 70)
print("3. WIN RATE BY ENTRY HOUR (for trades reaching +$60)")
print("=" * 70)

hourly = df.groupby('entry_hour').agg({
    'final_pnl': ['count', 'sum', 'mean'],
    'ended_positive': 'mean',
    'mins_to_60': 'mean'
}).reset_index()
hourly.columns = ['hour', 'count', 'total_pnl', 'avg_pnl', 'win_rate', 'avg_mins_to_60']

# Sort by win rate
hourly = hourly.sort_values('win_rate')
print("\nLowest win rate hours (might benefit from tighter SL):")
for _, row in hourly.head(5).iterrows():
    print(f"   Hour {int(row['hour']):02d}: {row['win_rate']*100:.1f}% WR, {int(row['count'])} trades, avg {row['avg_mins_to_60']:.0f} mins to +$60")

print("\nHighest win rate hours:")
for _, row in hourly.tail(5).iterrows():
    print(f"   Hour {int(row['hour']):02d}: {row['win_rate']*100:.1f}% WR, {int(row['count'])} trades, avg {row['avg_mins_to_60']:.0f} mins to +$60")

# ============================================
# 4. ANALYSIS BY DIRECTION
# ============================================
print("\n" + "=" * 70)
print("4. WIN RATE BY DIRECTION (for trades reaching +$60)")
print("=" * 70)

for side in ['LONG', 'SHORT']:
    subset = df[df['side'] == side]
    winners = subset[subset['ended_positive']]
    losers = subset[~subset['ended_positive']]
    
    print(f"\n{side}:")
    print(f"   Total: {len(subset)}")
    print(f"   Win Rate: {len(winners)/len(subset)*100:.1f}%")
    print(f"   Avg time to +$60: {subset['mins_to_60'].mean():.0f} mins")
    if len(losers) > 0:
        print(f"   Losers avg drawdown after +$60: ${losers['min_pnl_after_60'].mean():.2f}")

# ============================================
# 5. COMBINED RULE: SLOW + CERTAIN HOURS
# ============================================
print("\n" + "=" * 70)
print("5. COMBINED RULES TEST")
print("=" * 70)

# Find worst performing combinations
df['is_slow'] = df['mins_to_60'] >= 60

# Group by slow + hour
df['hour_group'] = df['entry_hour'].apply(lambda x: f"{int(x):02d}")
combo = df.groupby(['is_slow', 'hour_group']).agg({
    'final_pnl': ['count', 'sum'],
    'ended_positive': 'mean'
}).reset_index()
combo.columns = ['is_slow', 'hour', 'count', 'total_pnl', 'win_rate']

# Filter to show problematic combinations
print("\nSlow trades (60+ mins to +$60) with worst win rates:")
slow_combos = combo[combo['is_slow'] == True].sort_values('win_rate')
for _, row in slow_combos[slow_combos['count'] >= 5].head(10).iterrows():
    print(f"   Hour {row['hour']}: {row['win_rate']*100:.1f}% WR, {int(row['count'])} trades, PnL: ${row['total_pnl']:.0f}")

# ============================================
# 6. OPTIMAL COMBINED STRATEGY
# ============================================
print("\n" + "=" * 70)
print("6. FINDING OPTIMAL STRATEGY")
print("=" * 70)

best_improvement = 0
best_params = None

# Test combinations
for slow_threshold in [30, 45, 60, 90]:
    for sl_level in [40, 30, 20, 10, 0, -10, -20]:
        fast_trades = df[df['mins_to_60'] < slow_threshold]
        slow_trades = df[df['mins_to_60'] >= slow_threshold]
        
        fast_pnl = fast_trades['final_pnl'].sum()
        
        slow_pnl = 0
        for _, trade in slow_trades.iterrows():
            if trade['min_pnl_after_60'] <= sl_level:
                slow_pnl += sl_level
            else:
                slow_pnl += trade['final_pnl']
        
        new_total = fast_pnl + slow_pnl
        diff = new_total - current_pnl
        
        if diff > best_improvement:
            best_improvement = diff
            best_params = (slow_threshold, sl_level)

if best_params:
    print(f"\nBest strategy found:")
    print(f"   If trade takes >= {best_params[0]} mins to reach +$60:")
    print(f"   Tighten SL to ${best_params[1]} after reaching +$60")
    print(f"   Expected improvement: +${best_improvement:.0f}")
    
    # Show detailed impact
    slow_threshold, sl_level = best_params
    slow_trades = df[df['mins_to_60'] >= slow_threshold]
    slow_winners = slow_trades[slow_trades['ended_positive']]
    slow_losers = slow_trades[~slow_trades['ended_positive']]
    
    winners_hurt = slow_winners[slow_winners['min_pnl_after_60'] <= sl_level]
    losers_helped = slow_losers[slow_losers['min_pnl_after_60'] <= sl_level]
    
    print(f"\n   Slow trades affected: {len(slow_trades)}")
    print(f"   Winners hurt by early exit: {len(winners_hurt)}")
    print(f"   Losers saved by early exit: {len(losers_helped)}")
else:
    print("\nNo improvement found with time-based SL adjustment")

# ============================================
# 7. DRAWDOWN VELOCITY ANALYSIS
# ============================================
print("\n" + "=" * 70)
print("7. OTHER PATTERNS IN LOSERS")
print("=" * 70)

losers = df[~df['ended_positive']]
winners = df[df['ended_positive']]

print(f"\nWinners vs Losers comparison (trades reaching +$60):")
print(f"   {'Metric':<30} {'Winners':>15} {'Losers':>15}")
print(f"   {'-'*60}")
print(f"   {'Count':<30} {len(winners):>15} {len(losers):>15}")
print(f"   {'Avg time to +$60 (mins)':<30} {winners['mins_to_60'].mean():>15.0f} {losers['mins_to_60'].mean():>15.0f}")
print(f"   {'Median time to +$60':<30} {winners['mins_to_60'].median():>15.0f} {losers['mins_to_60'].median():>15.0f}")
print(f"   {'Avg max unrealized':<30} {winners['max_unrealized'].mean():>15.1f} {losers['max_unrealized'].mean():>15.1f}")
print(f"   {'Avg min after +$60':<30} {winners['min_pnl_after_60'].mean():>15.1f} {losers['min_pnl_after_60'].mean():>15.1f}")
print(f"   {'Avg total duration (bars)':<30} {winners['total_bars'].mean():>15.1f} {losers['total_bars'].mean():>15.1f}")
