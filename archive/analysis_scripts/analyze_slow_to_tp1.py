"""
Analyze trades that:
1. Go positive (above water)
2. Never reach TP1 (0.6 ATR)
3. Eventually hit SL

Question: Can we tighten SL or exit early for trades that are slow to reach TP1?
All analysis in ATR terms.
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

# Calculate ATR
bar_df['tr'] = np.maximum(
    bar_df['high'] - bar_df['low'],
    np.maximum(
        abs(bar_df['high'] - bar_df['close'].shift(1)),
        abs(bar_df['low'] - bar_df['close'].shift(1))
    )
)
bar_df['atr'] = bar_df['tr'].rolling(14).mean()

print("Analyzing trades that go positive but don't reach TP1 (0.6 ATR)...")
print("All values in ATR multiples")
print("=" * 70)

TP1_ATR = 0.6  # TP1 level
SL_ATR = 1.4   # Current SL level

# Track detailed journey for each trade
trade_data = []

for idx, trade in trades_df.iterrows():
    entry_time = trade['entry_time']
    exit_time = trade['exit_time']
    entry_price = trade['entry']
    side = trade['side']
    final_pnl = trade['pnl']
    exit_reason = trade['exit_reason']
    
    trade_bars = bar_df[(bar_df.index >= entry_time) & (bar_df.index <= exit_time)]
    
    if len(trade_bars) == 0:
        continue
    
    # Get ATR at entry
    entry_bar = trade_bars.iloc[0]
    atr_at_entry = entry_bar['atr']
    
    if pd.isna(atr_at_entry) or atr_at_entry <= 0:
        continue
    
    # Track journey in ATR terms
    max_profit_atr = 0
    reached_tp1 = False
    bars_to_max_profit = 0
    
    # Track when positive (above 0) for how long
    bars_positive = 0
    max_profit_while_not_tp1 = 0
    bar_of_max_profit = 0
    
    # Track ATR levels reached at each bar
    profit_at_each_bar = []
    
    for bar_idx, (bar_time, bar_data) in enumerate(trade_bars.iterrows()):
        if side == 'LONG':
            high_profit = (bar_data['high'] - entry_price) / atr_at_entry
            low_profit = (bar_data['low'] - entry_price) / atr_at_entry
            close_profit = (bar_data['close'] - entry_price) / atr_at_entry
        else:
            high_profit = (entry_price - bar_data['low']) / atr_at_entry
            low_profit = (entry_price - bar_data['high']) / atr_at_entry
            close_profit = (entry_price - bar_data['close']) / atr_at_entry
        
        profit_at_each_bar.append({
            'bar': bar_idx,
            'high_atr': high_profit,
            'low_atr': low_profit,
            'close_atr': close_profit,
        })
        
        if high_profit > max_profit_atr:
            max_profit_atr = high_profit
            bars_to_max_profit = bar_idx
        
        if high_profit >= TP1_ATR:
            reached_tp1 = True
        
        # Track positive bars before TP1
        if not reached_tp1:
            if high_profit > 0:
                bars_positive += 1
            if high_profit > max_profit_while_not_tp1:
                max_profit_while_not_tp1 = high_profit
                bar_of_max_profit = bar_idx
    
    trade_data.append({
        'entry_time': entry_time,
        'final_pnl': final_pnl,
        'final_pnl_atr': final_pnl / (atr_at_entry * 100000),
        'exit_reason': exit_reason,
        'side': side,
        'atr_at_entry': atr_at_entry,
        'atr_pips': atr_at_entry * 10000,
        'max_profit_atr': max_profit_atr,
        'reached_tp1': reached_tp1,
        'bars_to_max_profit': bars_to_max_profit,
        'bars_positive': bars_positive,
        'max_profit_before_tp1': max_profit_while_not_tp1,
        'bar_of_max_profit': bar_of_max_profit,
        'total_bars': len(trade_bars),
        'profit_journey': profit_at_each_bar,
    })

df = pd.DataFrame(trade_data)

# ============================================
# FOCUS: Trades that NEVER reached TP1
# ============================================
never_tp1 = df[~df['reached_tp1']]
reached_tp1 = df[df['reached_tp1']]

print(f"\nTotal trades: {len(df)}")
print(f"Reached TP1 (0.6 ATR): {len(reached_tp1)} ({len(reached_tp1)/len(df)*100:.1f}%)")
print(f"Never reached TP1: {len(never_tp1)} ({len(never_tp1)/len(df)*100:.1f}%)")

# ============================================
# 1. TRADES THAT NEVER REACHED TP1
# ============================================
print("\n" + "=" * 70)
print("1. TRADES THAT NEVER REACHED TP1 (0.6 ATR)")
print("=" * 70)

print(f"\nTotal: {len(never_tp1)}")
print(f"All SL exits (by definition): {len(never_tp1[never_tp1['exit_reason'] == 'SL'])}")
print(f"Total loss: ${never_tp1['final_pnl'].sum():.0f}")
print(f"Avg loss: ${never_tp1['final_pnl'].mean():.2f}")

# How high did they get before reversing?
print(f"\nMax profit reached before reversing:")
print(f"   Avg: {never_tp1['max_profit_before_tp1'].mean():.3f} ATR")
print(f"   Median: {never_tp1['max_profit_before_tp1'].median():.3f} ATR")
print(f"   Max: {never_tp1['max_profit_before_tp1'].max():.3f} ATR")

# ============================================
# 2. BREAKDOWN BY MAX PROFIT LEVEL (never reached TP1)
# ============================================
print("\n" + "=" * 70)
print("2. NEVER-TP1 TRADES BY MAX PROFIT LEVEL")
print("=" * 70)

for level, label in [(0, '0-0.1 ATR'), (0.1, '0.1-0.2 ATR'), (0.2, '0.2-0.3 ATR'), 
                      (0.3, '0.3-0.4 ATR'), (0.4, '0.4-0.5 ATR'), (0.5, '0.5-0.6 ATR')]:
    upper = level + 0.1
    subset = never_tp1[(never_tp1['max_profit_before_tp1'] >= level) & 
                        (never_tp1['max_profit_before_tp1'] < upper)]
    if len(subset) == 0:
        continue
    print(f"\n{label}: {len(subset)} trades, Total loss: ${subset['final_pnl'].sum():.0f}")
    print(f"   Avg bars positive: {subset['bars_positive'].mean():.1f}")
    print(f"   Avg bar of max profit: {subset['bar_of_max_profit'].mean():.1f}")

# ============================================
# 3. TIME ANALYSIS: HOW LONG WERE THEY POSITIVE?
# ============================================
print("\n" + "=" * 70)
print("3. TIME SPENT POSITIVE (trades that never reached TP1)")
print("=" * 70)

# Trades that were positive for X+ bars but never hit TP1
for bars_positive_threshold in [1, 2, 3, 4, 5, 6, 8, 10]:
    subset = never_tp1[never_tp1['bars_positive'] >= bars_positive_threshold]
    if len(subset) < 5:
        continue
    print(f"\nPositive for {bars_positive_threshold}+ bars but never TP1:")
    print(f"   Count: {len(subset)}")
    print(f"   Total loss: ${subset['final_pnl'].sum():.0f}")
    print(f"   Avg max profit: {subset['max_profit_before_tp1'].mean():.3f} ATR")

# ============================================
# 4. COMPARE: Same positive duration, reached TP1 vs not
# ============================================
print("\n" + "=" * 70)
print("4. TRADES THAT WERE POSITIVE BUT SLOW - TP1 vs NO TP1")
print("=" * 70)

# For trades that were positive for 3+ bars in first 4 bars
for check_bar in [2, 3, 4, 5, 6]:
    # Get max profit at bar X for all trades
    profits_at_bar = []
    for _, trade in df.iterrows():
        journey = trade['profit_journey']
        if len(journey) > check_bar:
            max_at_bar = max([j['high_atr'] for j in journey[:check_bar+1]])
            profits_at_bar.append({
                'entry_time': trade['entry_time'],
                'max_at_bar': max_at_bar,
                'reached_tp1': trade['reached_tp1'],
                'final_pnl': trade['final_pnl'],
            })
    
    pab_df = pd.DataFrame(profits_at_bar)
    
    # Trades that reached 0.3-0.5 ATR by bar X (close but not TP1 yet)
    close_but_not_tp1 = pab_df[(pab_df['max_at_bar'] >= 0.3) & (pab_df['max_at_bar'] < 0.6)]
    
    if len(close_but_not_tp1) < 10:
        continue
    
    hit_tp1 = close_but_not_tp1[close_but_not_tp1['reached_tp1']]
    missed_tp1 = close_but_not_tp1[~close_but_not_tp1['reached_tp1']]
    
    print(f"\nTrades at 0.3-0.6 ATR by bar {check_bar} ({check_bar*15} mins):")
    print(f"   Eventually hit TP1: {len(hit_tp1)} trades, PnL: ${hit_tp1['final_pnl'].sum():.0f}")
    print(f"   Never hit TP1 (SL): {len(missed_tp1)} trades, PnL: ${missed_tp1['final_pnl'].sum():.0f}")

# ============================================
# 5. RULE SIMULATION: Tighten SL if not progressing
# ============================================
print("\n" + "=" * 70)
print("5. SIMULATION: TIGHTEN SL IF NOT REACHING TP1 IN TIME")
print("=" * 70)

current_total_pnl = df['final_pnl'].sum()
print(f"Current total PnL: ${current_total_pnl:.0f}")

# Rule: After X bars, if max profit is between Y and 0.6 ATR, tighten SL to Z ATR
print("\nRule: If max profit is 0.2-0.6 ATR after X bars but not at TP1, tighten SL")

for check_after_bars in [3, 4, 5, 6, 8]:
    print(f"\n--- Check after {check_after_bars} bars ({check_after_bars*15} mins) ---")
    
    for sl_atr in [0.2, 0.1, 0.0, -0.1, -0.2]:  # New SL levels (0 = breakeven)
        
        new_total_pnl = 0
        trades_affected = 0
        saved_from_loss = 0
        hurt_winners = 0
        
        for _, trade in df.iterrows():
            journey = trade['profit_journey']
            
            if len(journey) <= check_after_bars:
                new_total_pnl += trade['final_pnl']
                continue
            
            # Max profit by check_after_bars
            max_at_check = max([j['high_atr'] for j in journey[:check_after_bars+1]])
            
            # Only apply rule if trade is in "danger zone" (positive but not TP1)
            if 0.2 <= max_at_check < 0.6:
                trades_affected += 1
                
                # Check if trade would have been stopped at sl_atr after the check
                min_after_check = min([j['low_atr'] for j in journey[check_after_bars:]])
                
                if min_after_check <= sl_atr:
                    # Would have been stopped at sl_atr
                    exit_pnl = sl_atr * trade['atr_at_entry'] * 100000
                    
                    if trade['final_pnl'] < 0:
                        saved_from_loss += 1
                    else:
                        hurt_winners += 1
                    
                    new_total_pnl += exit_pnl
                else:
                    # Wouldn't have been stopped
                    new_total_pnl += trade['final_pnl']
            else:
                new_total_pnl += trade['final_pnl']
        
        diff = new_total_pnl - current_total_pnl
        if diff > 100:
            print(f"   SL={sl_atr} ATR: +${diff:.0f} ({trades_affected} checked, {saved_from_loss} losses saved, {hurt_winners} winners hurt)")

# ============================================
# 6. OPTIMAL RULE SEARCH
# ============================================
print("\n" + "=" * 70)
print("6. FINDING OPTIMAL RULE")
print("=" * 70)

best_improvement = 0
best_params = None

for check_after_bars in [2, 3, 4, 5, 6, 7, 8]:
    for min_profit_atr in [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4]:
        for sl_atr in [0.3, 0.2, 0.15, 0.1, 0.05, 0.0, -0.05, -0.1, -0.15, -0.2]:
            
            new_total_pnl = 0
            
            for _, trade in df.iterrows():
                journey = trade['profit_journey']
                
                if len(journey) <= check_after_bars:
                    new_total_pnl += trade['final_pnl']
                    continue
                
                max_at_check = max([j['high_atr'] for j in journey[:check_after_bars+1]])
                
                # Apply rule if in danger zone
                if min_profit_atr <= max_at_check < 0.6:
                    min_after_check = min([j['low_atr'] for j in journey[check_after_bars:]])
                    
                    if min_after_check <= sl_atr:
                        exit_pnl = sl_atr * trade['atr_at_entry'] * 100000
                        new_total_pnl += exit_pnl
                    else:
                        new_total_pnl += trade['final_pnl']
                else:
                    new_total_pnl += trade['final_pnl']
            
            diff = new_total_pnl - current_total_pnl
            if diff > best_improvement:
                best_improvement = diff
                best_params = (check_after_bars, min_profit_atr, sl_atr)

if best_params:
    print(f"\nBEST RULE FOUND:")
    print(f"   Condition: After {best_params[0]} bars ({best_params[0]*15} mins)")
    print(f"              If max profit is {best_params[1]:.2f} - 0.6 ATR (not yet at TP1)")
    print(f"   Action: Tighten SL to {best_params[2]} ATR")
    print(f"   Improvement: +${best_improvement:.0f}")
    
    # Show detailed impact
    check_after_bars, min_profit_atr, sl_atr = best_params
    winners_hurt = 0
    losers_saved = 0
    
    for _, trade in df.iterrows():
        journey = trade['profit_journey']
        if len(journey) <= check_after_bars:
            continue
        
        max_at_check = max([j['high_atr'] for j in journey[:check_after_bars+1]])
        
        if min_profit_atr <= max_at_check < 0.6:
            min_after_check = min([j['low_atr'] for j in journey[check_after_bars:]])
            
            if min_after_check <= sl_atr:
                if trade['final_pnl'] > 0:
                    winners_hurt += 1
                else:
                    losers_saved += 1
    
    print(f"   Losers saved: {losers_saved}")
    print(f"   Winners hurt: {winners_hurt}")
else:
    print("\nNo improvement found")
