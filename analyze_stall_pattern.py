"""
Analyze the "stall" pattern - trades that reach +$60 but don't progress higher.
Hypothesis: Losers stall at +$60-100 before reversing, winners push through.
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

print("Analyzing stall patterns...")
print("=" * 70)

# Track detailed journey for each trade
trade_data = []

for idx, trade in trades_df.iterrows():
    entry_time = trade['entry_time']
    exit_time = trade['exit_time']
    entry_price = trade['entry']
    side = trade['side']
    final_pnl = trade['pnl']
    
    trade_bars = bar_df[(bar_df.index >= entry_time) & (bar_df.index <= exit_time)]
    
    if len(trade_bars) == 0:
        continue
    
    # Track journey with more detail
    max_unrealized = 0
    bars_to_60 = None
    bars_to_100 = None
    bars_to_120 = None
    min_pnl_after_60 = None
    
    # Track "stall" - bars spent between +$60 and +$100 without progress
    bars_in_stall_zone = 0
    highest_in_stall = 0
    stall_started = False
    
    for bar_idx, (bar_time, bar_data) in enumerate(trade_bars.iterrows()):
        if side == 'LONG':
            high_pnl = (bar_data['high'] - entry_price) * 100000
            low_pnl = (bar_data['low'] - entry_price) * 100000
            close_pnl = (bar_data['close'] - entry_price) * 100000
        else:
            high_pnl = (entry_price - bar_data['low']) * 100000
            low_pnl = (entry_price - bar_data['high']) * 100000
            close_pnl = (entry_price - bar_data['close']) * 100000
        
        if high_pnl > max_unrealized:
            max_unrealized = high_pnl
        
        # Track milestones
        if bars_to_60 is None and high_pnl >= 60:
            bars_to_60 = bar_idx
            min_pnl_after_60 = low_pnl
        elif bars_to_60 is not None:
            if low_pnl < min_pnl_after_60:
                min_pnl_after_60 = low_pnl
        
        if bars_to_100 is None and high_pnl >= 100:
            bars_to_100 = bar_idx
            
        if bars_to_120 is None and high_pnl >= 120:
            bars_to_120 = bar_idx
        
        # Track stall zone (between +$60 and +$100, not making new highs)
        if bars_to_60 is not None and bars_to_100 is None:
            if 60 <= high_pnl <= 110:
                bars_in_stall_zone += 1
                if high_pnl > highest_in_stall:
                    highest_in_stall = high_pnl
    
    if max_unrealized >= 60:
        trade_data.append({
            'entry_time': entry_time,
            'final_pnl': final_pnl,
            'side': side,
            'max_unrealized': max_unrealized,
            'bars_to_60': bars_to_60,
            'bars_to_100': bars_to_100,
            'bars_to_120': bars_to_120,
            'bars_in_stall': bars_in_stall_zone,
            'highest_in_stall': highest_in_stall,
            'min_pnl_after_60': min_pnl_after_60,
            'total_bars': len(trade_bars),
            'ended_positive': final_pnl > 0,
            'reached_100': bars_to_100 is not None,
            'reached_120': bars_to_120 is not None,
        })

df = pd.DataFrame(trade_data)

# ============================================
# 1. MAX PROFIT REACHED ANALYSIS
# ============================================
print("\n" + "=" * 70)
print("1. MAX PROFIT REACHED (trades that hit +$60)")
print("=" * 70)

print("\nBy max profit level:")
for level, label in [(60, '$60-79'), (80, '$80-99'), (100, '$100-119'), (120, '$120-149'), (150, '$150+')]:
    if level == 60:
        subset = df[(df['max_unrealized'] >= 60) & (df['max_unrealized'] < 80)]
    elif level == 80:
        subset = df[(df['max_unrealized'] >= 80) & (df['max_unrealized'] < 100)]
    elif level == 100:
        subset = df[(df['max_unrealized'] >= 100) & (df['max_unrealized'] < 120)]
    elif level == 120:
        subset = df[(df['max_unrealized'] >= 120) & (df['max_unrealized'] < 150)]
    else:
        subset = df[df['max_unrealized'] >= 150]
    
    if len(subset) == 0:
        continue
    
    winners = subset[subset['ended_positive']]
    losers = subset[~subset['ended_positive']]
    
    print(f"\n{label}:")
    print(f"   Total: {len(subset)}, Win Rate: {len(winners)/len(subset)*100:.1f}%")
    print(f"   Winners: {len(winners)}, Avg final: ${winners['final_pnl'].mean():.0f}" if len(winners) > 0 else "   Winners: 0")
    print(f"   Losers: {len(losers)}, Avg final: ${losers['final_pnl'].mean():.0f}" if len(losers) > 0 else "   Losers: 0")

# ============================================
# 2. STALL DETECTION
# ============================================
print("\n" + "=" * 70)
print("2. STALL ZONE ANALYSIS (bars between +$60 and +$100)")
print("=" * 70)

# Trades that stalled (spent time in +60-100 zone without breaking through)
stalled = df[df['bars_in_stall'] >= 2]
not_stalled = df[df['bars_in_stall'] < 2]

print(f"\nTrades that stalled (2+ bars in +$60-100 zone without breaking $100):")
print(f"   Count: {len(stalled)}")
print(f"   Win Rate: {stalled['ended_positive'].mean()*100:.1f}%")
print(f"   Avg final PnL: ${stalled['final_pnl'].mean():.2f}")

print(f"\nTrades that didn't stall:")
print(f"   Count: {len(not_stalled)}")
print(f"   Win Rate: {not_stalled['ended_positive'].mean()*100:.1f}%")
print(f"   Avg final PnL: ${not_stalled['final_pnl'].mean():.2f}")

# ============================================
# 3. STALL DURATION VS OUTCOME
# ============================================
print("\n" + "=" * 70)
print("3. STALL DURATION VS OUTCOME")
print("=" * 70)

for stall_bars in [1, 2, 3, 4, 5, 6]:
    subset = df[df['bars_in_stall'] >= stall_bars]
    if len(subset) < 10:
        continue
    
    winners = subset[subset['ended_positive']]
    losers = subset[~subset['ended_positive']]
    
    print(f"\nStalled {stall_bars}+ bars:")
    print(f"   Total: {len(subset)}, Win Rate: {len(winners)/len(subset)*100:.1f}%")
    if len(losers) > 0:
        print(f"   Losers: {len(losers)}, Total loss: ${losers['final_pnl'].sum():.0f}")

# ============================================
# 4. TEST: EXIT IF STALLED TOO LONG
# ============================================
print("\n" + "=" * 70)
print("4. SIMULATION: EXIT IF STALLED X BARS AT STALL ZONE MIDPOINT")
print("=" * 70)

current_pnl = df['final_pnl'].sum()
print(f"Current total PnL: ${current_pnl:.2f}")

for stall_threshold in [2, 3, 4, 5, 6]:
    for exit_price in [70, 60, 50, 40]:  # Exit at this $ level if stalled
        stalled_trades = df[df['bars_in_stall'] >= stall_threshold]
        non_stalled = df[df['bars_in_stall'] < stall_threshold]
        
        # Non-stalled keep original PnL
        non_stalled_pnl = non_stalled['final_pnl'].sum()
        
        # Stalled trades: exit at exit_price instead of actual exit
        stalled_pnl = 0
        trades_exited_early = 0
        
        for _, trade in stalled_trades.iterrows():
            # Only exit early if trade would have gotten worse than exit_price
            if trade['min_pnl_after_60'] < exit_price:
                # Trade dropped below exit_price, so we'd have exited at exit_price
                stalled_pnl += exit_price
                trades_exited_early += 1
            else:
                # Trade never dropped below exit_price
                stalled_pnl += trade['final_pnl']
        
        new_total = non_stalled_pnl + stalled_pnl
        diff = new_total - current_pnl
        
        if diff > 50:  # Only show meaningful improvements
            print(f"\n   Exit at ${exit_price} if stalled {stall_threshold}+ bars:")
            print(f"      Trades affected: {len(stalled_trades)}, Early exits: {trades_exited_early}")
            print(f"      Improvement: +${diff:.0f}")

# ============================================
# 5. PATTERN: DID NOT REACH $100
# ============================================
print("\n" + "=" * 70)
print("5. TRADES THAT REACHED +$60 BUT NOT +$100")
print("=" * 70)

no_100 = df[~df['reached_100']]
yes_100 = df[df['reached_100']]

print(f"\nReached +$60 but NOT +$100:")
print(f"   Count: {len(no_100)}")
print(f"   Win Rate: {no_100['ended_positive'].mean()*100:.1f}%")
print(f"   Total PnL: ${no_100['final_pnl'].sum():.0f}")
print(f"   Losers: {len(no_100[~no_100['ended_positive']])}, Lost: ${no_100[~no_100['ended_positive']]['final_pnl'].sum():.0f}")

print(f"\nReached +$100:")
print(f"   Count: {len(yes_100)}")
print(f"   Win Rate: {yes_100['ended_positive'].mean()*100:.1f}%")
print(f"   Total PnL: ${yes_100['final_pnl'].sum():.0f}")

# ============================================
# 6. WHAT IF: TIGHTER SL FOR TRADES NOT REACHING $100 QUICKLY
# ============================================
print("\n" + "=" * 70)
print("6. RULE: IF NOT REACHING +$100 WITHIN X BARS AFTER +$60, TIGHTEN SL")
print("=" * 70)

# For trades that reached +$60, check how quickly they reached +$100
df['bars_60_to_100'] = df.apply(
    lambda x: (x['bars_to_100'] - x['bars_to_60']) if x['reached_100'] and x['bars_to_60'] is not None else None, 
    axis=1
)

for bars_limit in [2, 3, 4, 5]:
    # Trades that didn't reach +$100 within bars_limit bars after +$60
    slow_to_100 = df[
        (df['reached_100'] == False) | 
        (df['bars_60_to_100'] > bars_limit)
    ]
    fast_to_100 = df[
        (df['reached_100'] == True) & 
        (df['bars_60_to_100'] <= bars_limit)
    ]
    
    if len(slow_to_100) == 0:
        continue
    
    slow_losers = slow_to_100[~slow_to_100['ended_positive']]
    slow_winners = slow_to_100[slow_to_100['ended_positive']]
    
    print(f"\nDid NOT reach +$100 within {bars_limit} bars after +$60:")
    print(f"   Total: {len(slow_to_100)}, Win Rate: {slow_to_100['ended_positive'].mean()*100:.1f}%")
    print(f"   Losers: {len(slow_losers)}, Lost: ${slow_losers['final_pnl'].sum():.0f}")
    
    # Test SL tightening for this group
    for sl_level in [50, 40, 30, 20]:
        affected = slow_to_100[slow_to_100['min_pnl_after_60'] <= sl_level]
        winners_affected = affected[affected['ended_positive']]
        losers_affected = affected[~affected['ended_positive']]
        
        # Winners lose their profit above sl_level
        winners_lost = winners_affected['final_pnl'].sum() - (len(winners_affected) * sl_level)
        # Losers saved from full loss
        losers_saved = (len(losers_affected) * sl_level) - losers_affected['final_pnl'].sum()
        
        net = losers_saved - winners_lost
        if net > 0:
            print(f"      SL=${sl_level}: Net +${net:.0f} (save {len(losers_affected)} losers, hurt {len(winners_affected)} winners)")
