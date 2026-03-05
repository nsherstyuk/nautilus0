"""
Proper analysis using ATR multiples instead of fixed dollar values.
This matches how the actual strategy works.
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

# Calculate ATR (14-period) for each bar
bar_df['tr'] = np.maximum(
    bar_df['high'] - bar_df['low'],
    np.maximum(
        abs(bar_df['high'] - bar_df['close'].shift(1)),
        abs(bar_df['low'] - bar_df['close'].shift(1))
    )
)
bar_df['atr'] = bar_df['tr'].rolling(14).mean()

print("Analyzing using ATR multiples (proper approach)...")
print("=" * 70)

# Strategy parameters
TP1_ATR = 0.6  # Current TP1
TP2_ATR = 1.5  # Current TP2
SL_ATR = 1.4   # Current SL

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
    
    # Get ATR at entry
    entry_bar = trade_bars.iloc[0]
    atr_at_entry = entry_bar['atr']
    
    if pd.isna(atr_at_entry) or atr_at_entry <= 0:
        continue
    
    # Track journey in ATR terms
    max_profit_atr = 0
    bars_to_tp1 = None  # bars to reach 0.6 ATR
    bars_to_1atr = None  # bars to reach 1.0 ATR
    min_pnl_atr_after_tp1 = None
    max_pnl_atr_after_tp1 = None
    
    # Track stall in ATR terms (between 0.6 and 1.0 ATR)
    bars_in_stall_zone = 0
    
    for bar_idx, (bar_time, bar_data) in enumerate(trade_bars.iterrows()):
        if side == 'LONG':
            profit_price = bar_data['high'] - entry_price
            loss_price = bar_data['low'] - entry_price
        else:
            profit_price = entry_price - bar_data['low']
            loss_price = entry_price - bar_data['high']
        
        # Convert to ATR multiple
        profit_atr = profit_price / atr_at_entry
        loss_atr = loss_price / atr_at_entry
        
        if profit_atr > max_profit_atr:
            max_profit_atr = profit_atr
        
        # Track milestones
        if bars_to_tp1 is None and profit_atr >= TP1_ATR:
            bars_to_tp1 = bar_idx
            min_pnl_atr_after_tp1 = loss_atr
            max_pnl_atr_after_tp1 = profit_atr
        elif bars_to_tp1 is not None:
            if loss_atr < min_pnl_atr_after_tp1:
                min_pnl_atr_after_tp1 = loss_atr
            if profit_atr > max_pnl_atr_after_tp1:
                max_pnl_atr_after_tp1 = profit_atr
        
        if bars_to_1atr is None and profit_atr >= 1.0:
            bars_to_1atr = bar_idx
        
        # Track stall zone (between 0.6 and 1.0 ATR)
        if bars_to_tp1 is not None and bars_to_1atr is None:
            if TP1_ATR <= profit_atr <= 1.1:
                bars_in_stall_zone += 1
    
    # Calculate final PnL in ATR terms
    final_pnl_atr = final_pnl / (atr_at_entry * 100000)  # Convert $ to ATR
    
    if max_profit_atr >= TP1_ATR:  # Only trades that reached TP1
        trade_data.append({
            'entry_time': entry_time,
            'final_pnl': final_pnl,
            'final_pnl_atr': final_pnl_atr,
            'side': side,
            'atr_at_entry': atr_at_entry,
            'atr_in_pips': atr_at_entry * 10000,  # Convert to pips
            'max_profit_atr': max_profit_atr,
            'bars_to_tp1': bars_to_tp1,
            'bars_to_1atr': bars_to_1atr,
            'bars_in_stall': bars_in_stall_zone,
            'min_pnl_atr_after_tp1': min_pnl_atr_after_tp1,
            'max_pnl_atr_after_tp1': max_pnl_atr_after_tp1,
            'ended_positive': final_pnl > 0,
            'reached_1atr': bars_to_1atr is not None,
        })

df = pd.DataFrame(trade_data)

print(f"\nTotal trades that reached TP1 (0.6 ATR): {len(df)}")
print(f"ATR range at entry: {df['atr_in_pips'].min():.1f} to {df['atr_in_pips'].max():.1f} pips")
print(f"Average ATR: {df['atr_in_pips'].mean():.1f} pips (${df['atr_at_entry'].mean()*100000:.0f})")

# ============================================
# 1. MAX PROFIT IN ATR TERMS
# ============================================
print("\n" + "=" * 70)
print("1. MAX PROFIT REACHED (in ATR multiples)")
print("=" * 70)

for level, label in [(0.6, '0.6-0.8 ATR'), (0.8, '0.8-1.0 ATR'), (1.0, '1.0-1.2 ATR'), 
                      (1.2, '1.2-1.5 ATR'), (1.5, '1.5+ ATR')]:
    if level == 0.6:
        subset = df[(df['max_profit_atr'] >= 0.6) & (df['max_profit_atr'] < 0.8)]
    elif level == 0.8:
        subset = df[(df['max_profit_atr'] >= 0.8) & (df['max_profit_atr'] < 1.0)]
    elif level == 1.0:
        subset = df[(df['max_profit_atr'] >= 1.0) & (df['max_profit_atr'] < 1.2)]
    elif level == 1.2:
        subset = df[(df['max_profit_atr'] >= 1.2) & (df['max_profit_atr'] < 1.5)]
    else:
        subset = df[df['max_profit_atr'] >= 1.5]
    
    if len(subset) == 0:
        continue
    
    winners = subset[subset['ended_positive']]
    losers = subset[~subset['ended_positive']]
    
    print(f"\n{label}:")
    print(f"   Total: {len(subset)}, Win Rate: {len(winners)/len(subset)*100:.1f}%")
    print(f"   Losers: {len(losers)}" if len(losers) > 0 else "   Losers: 0")

# ============================================
# 2. STALL ANALYSIS (in ATR terms)
# ============================================
print("\n" + "=" * 70)
print("2. STALL ZONE ANALYSIS (bars between 0.6 and 1.0 ATR)")
print("=" * 70)

for stall_bars in [1, 2, 3, 4, 5]:
    subset = df[df['bars_in_stall'] >= stall_bars]
    if len(subset) < 10:
        continue
    
    winners = subset[subset['ended_positive']]
    losers = subset[~subset['ended_positive']]
    
    print(f"\nStalled {stall_bars}+ bars in 0.6-1.0 ATR zone:")
    print(f"   Total: {len(subset)}, Win Rate: {len(winners)/len(subset)*100:.1f}%")
    if len(losers) > 0:
        print(f"   Losers: {len(losers)}, Avg min after TP1: {losers['min_pnl_atr_after_tp1'].mean():.2f} ATR")

# ============================================
# 3. TIME TO REACH 1.0 ATR AFTER TP1
# ============================================
print("\n" + "=" * 70)
print("3. TIME TO REACH 1.0 ATR AFTER 0.6 ATR (TP1)")
print("=" * 70)

df['bars_tp1_to_1atr'] = df.apply(
    lambda x: (x['bars_to_1atr'] - x['bars_to_tp1']) if x['reached_1atr'] else None, 
    axis=1
)

# Did not reach 1.0 ATR
no_1atr = df[~df['reached_1atr']]
yes_1atr = df[df['reached_1atr']]

print(f"\nReached 0.6 ATR but NOT 1.0 ATR:")
print(f"   Count: {len(no_1atr)}, Win Rate: {no_1atr['ended_positive'].mean()*100:.1f}%")
losers_no1atr = no_1atr[~no_1atr['ended_positive']]
print(f"   Losers: {len(losers_no1atr)}, Avg final: {losers_no1atr['final_pnl_atr'].mean():.2f} ATR")

print(f"\nReached 1.0 ATR:")
print(f"   Count: {len(yes_1atr)}, Win Rate: {yes_1atr['ended_positive'].mean()*100:.1f}%")

# ============================================
# 4. SIMULATION: ATR-BASED STALL EXIT RULE
# ============================================
print("\n" + "=" * 70)
print("4. SIMULATION: ATR-BASED STALL EXIT RULES")
print("=" * 70)

current_pnl = df['final_pnl'].sum()
print(f"Current total PnL: ${current_pnl:.2f}")

# Test: If trade doesn't reach 1.0 ATR within X bars after TP1, exit at Y ATR
print("\nRule: If NOT reaching 1.0 ATR within X bars after TP1, tighten SL to Y ATR")

for bars_limit in [2, 3, 4, 5]:
    # Trades that didn't reach 1.0 ATR within bars_limit after TP1
    slow_trades = df[
        (~df['reached_1atr']) | 
        (df['bars_tp1_to_1atr'] > bars_limit)
    ]
    fast_trades = df[
        (df['reached_1atr']) & 
        (df['bars_tp1_to_1atr'] <= bars_limit)
    ]
    
    print(f"\n--- If NOT 1.0 ATR within {bars_limit} bars after TP1 ({bars_limit*15} mins) ---")
    
    for sl_atr in [0.5, 0.4, 0.3, 0.2, 0.1, 0.0]:
        fast_pnl = fast_trades['final_pnl'].sum()
        
        slow_pnl = 0
        trades_exited = 0
        for _, trade in slow_trades.iterrows():
            if trade['min_pnl_atr_after_tp1'] <= sl_atr:
                # Would have been stopped at sl_atr
                exit_pnl = sl_atr * trade['atr_at_entry'] * 100000
                slow_pnl += exit_pnl
                trades_exited += 1
            else:
                slow_pnl += trade['final_pnl']
        
        new_total = fast_pnl + slow_pnl
        diff = new_total - current_pnl
        
        if diff > 100:
            print(f"   SL={sl_atr} ATR: +${diff:.0f} improvement ({trades_exited} early exits)")

# ============================================
# 5. OPTIMAL ATR-BASED RULE
# ============================================
print("\n" + "=" * 70)
print("5. FINDING OPTIMAL ATR-BASED RULE")
print("=" * 70)

best_improvement = 0
best_params = None

for bars_limit in [2, 3, 4, 5, 6]:
    for sl_atr in [0.5, 0.45, 0.4, 0.35, 0.3, 0.25, 0.2, 0.15, 0.1, 0.05, 0.0, -0.1]:
        slow_trades = df[
            (~df['reached_1atr']) | 
            (df['bars_tp1_to_1atr'] > bars_limit)
        ]
        fast_trades = df[
            (df['reached_1atr']) & 
            (df['bars_tp1_to_1atr'] <= bars_limit)
        ]
        
        fast_pnl = fast_trades['final_pnl'].sum()
        
        slow_pnl = 0
        for _, trade in slow_trades.iterrows():
            if trade['min_pnl_atr_after_tp1'] <= sl_atr:
                exit_pnl = sl_atr * trade['atr_at_entry'] * 100000
                slow_pnl += exit_pnl
            else:
                slow_pnl += trade['final_pnl']
        
        new_total = fast_pnl + slow_pnl
        diff = new_total - current_pnl
        
        if diff > best_improvement:
            best_improvement = diff
            best_params = (bars_limit, sl_atr)

if best_params:
    print(f"\nBEST RULE FOUND:")
    print(f"   Condition: Trade reaches TP1 (0.6 ATR) but doesn't reach 1.0 ATR")
    print(f"              within {best_params[0]} bars ({best_params[0]*15} mins)")
    print(f"   Action: Tighten SL to {best_params[1]} ATR (lock in profit)")
    print(f"   Expected improvement: +${best_improvement:.0f}")

# ============================================
# 6. COMPARE TO CURRENT SYSTEM
# ============================================
print("\n" + "=" * 70)
print("6. COMPARISON: PROPOSED vs CURRENT SYSTEM")
print("=" * 70)

print(f"\nCurrent system:")
print(f"   After TP1 (0.6 ATR): Trailing stop at 0.4 ATR distance")
print(f"   Total PnL from TP1+ trades: ${current_pnl:.0f}")

if best_params:
    bars_limit, sl_atr = best_params
    print(f"\nProposed addition:")
    print(f"   IF trade doesn't progress to 1.0 ATR within {bars_limit} bars:")
    print(f"   THEN tighten SL to {sl_atr} ATR")
    print(f"   New total PnL: ${current_pnl + best_improvement:.0f}")
    print(f"   Improvement: +${best_improvement:.0f} (+{best_improvement/current_pnl*100:.1f}%)")
