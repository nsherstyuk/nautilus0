"""
Analyze trades that:
1. Were positive for some time (but didn't hit TP1)
2. Fell back to negative territory
3. Recovered and ended positive

Question: Should we exit if a profitable trade goes negative?
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

# Load config for TP1 level
from config.mtf_v2_config import load_mtf_v2_config
config = load_mtf_v2_config()
TP1_ATR_MULT = config.pos1_tp_atr_mult  # 0.6

print("Analyzing trades that were positive then went underwater...")
print("=" * 70)

# Track detailed journey for each trade
trade_journeys = []

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
    
    # Track the journey
    max_profit_before_negative = 0
    max_profit_bar = 0
    went_positive = False
    went_negative_after_positive = False
    time_positive_before_drop = 0
    time_underwater_after_positive = 0
    max_drawdown_after_positive = 0
    recovered_from_drop = False
    
    # States: 'initial', 'positive', 'underwater_after_positive', 'recovered'
    state = 'initial'
    bars_in_positive = 0
    bars_underwater_after_positive = 0
    
    for bar_idx, (bar_time, bar_data) in enumerate(trade_bars.iterrows()):
        if side == 'LONG':
            unrealized_pnl = (bar_data['close'] - entry_price) * 100000
            max_pnl_this_bar = (bar_data['high'] - entry_price) * 100000
            min_pnl_this_bar = (bar_data['low'] - entry_price) * 100000
        else:
            unrealized_pnl = (entry_price - bar_data['close']) * 100000
            max_pnl_this_bar = (entry_price - bar_data['low']) * 100000
            min_pnl_this_bar = (entry_price - bar_data['high']) * 100000
        
        # Track state transitions
        if state == 'initial':
            if unrealized_pnl > 10:  # At least $10 positive
                state = 'positive'
                went_positive = True
                bars_in_positive = 1
                max_profit_before_negative = unrealized_pnl
        
        elif state == 'positive':
            if unrealized_pnl > max_profit_before_negative:
                max_profit_before_negative = unrealized_pnl
            
            if unrealized_pnl > 0:
                bars_in_positive += 1
            else:
                # Dropped to negative after being positive
                state = 'underwater_after_positive'
                went_negative_after_positive = True
                bars_underwater_after_positive = 1
                max_drawdown_after_positive = min_pnl_this_bar
        
        elif state == 'underwater_after_positive':
            if min_pnl_this_bar < max_drawdown_after_positive:
                max_drawdown_after_positive = min_pnl_this_bar
            
            if unrealized_pnl < 0:
                bars_underwater_after_positive += 1
            else:
                # Recovered!
                state = 'recovered'
                recovered_from_drop = True
    
    # Only track trades that went positive then negative
    if went_negative_after_positive:
        trade_journeys.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'side': side,
            'final_pnl': final_pnl,
            'exit_reason': exit_reason,
            'max_profit_before_drop': max_profit_before_negative,
            'mins_positive_before_drop': bars_in_positive * 15,
            'mins_underwater_after_positive': bars_underwater_after_positive * 15,
            'max_drawdown_after_positive': max_drawdown_after_positive,
            'recovered': recovered_from_drop,
            'ended_positive': final_pnl > 0,
            'duration_mins': len(trade_bars) * 15,
        })

journey_df = pd.DataFrame(trade_journeys)

# ============================================
# ANALYSIS
# ============================================
print(f"\nTotal trades: {len(trades_df)}")
print(f"Trades that went POSITIVE then NEGATIVE: {len(journey_df)} ({len(journey_df)/len(trades_df)*100:.1f}%)")

# Split by final outcome
positive_then_neg_won = journey_df[journey_df['ended_positive']]
positive_then_neg_lost = journey_df[~journey_df['ended_positive']]

print("\n" + "=" * 70)
print("1. TRADES THAT WERE POSITIVE, WENT NEGATIVE, THEN WON")
print("=" * 70)
print(f"Count: {len(positive_then_neg_won)}")
print(f"Total PnL: ${positive_then_neg_won['final_pnl'].sum():.2f}")
print(f"Avg final PnL: ${positive_then_neg_won['final_pnl'].mean():.2f}")
print(f"\nBefore dropping negative:")
print(f"   Avg max profit: ${positive_then_neg_won['max_profit_before_drop'].mean():.2f}")
print(f"   Avg time in profit: {positive_then_neg_won['mins_positive_before_drop'].mean():.0f} mins")
print(f"\nWhile underwater (after being positive):")
print(f"   Avg time underwater: {positive_then_neg_won['mins_underwater_after_positive'].mean():.0f} mins")
print(f"   Avg max drawdown: ${positive_then_neg_won['max_drawdown_after_positive'].mean():.2f}")

print("\n" + "=" * 70)
print("2. TRADES THAT WERE POSITIVE, WENT NEGATIVE, THEN LOST (SL)")
print("=" * 70)
print(f"Count: {len(positive_then_neg_lost)}")
print(f"Total PnL: ${positive_then_neg_lost['final_pnl'].sum():.2f}")
print(f"Avg final PnL: ${positive_then_neg_lost['final_pnl'].mean():.2f}")
print(f"\nBefore dropping negative:")
print(f"   Avg max profit: ${positive_then_neg_lost['max_profit_before_drop'].mean():.2f}")
print(f"   Avg time in profit: {positive_then_neg_lost['mins_positive_before_drop'].mean():.0f} mins")
print(f"\nWhile underwater (after being positive):")
print(f"   Avg time underwater: ${positive_then_neg_lost['mins_underwater_after_positive'].mean():.0f} mins")
print(f"   Avg max drawdown: ${positive_then_neg_lost['max_drawdown_after_positive'].mean():.2f}")

# ============================================
# WHAT IF: Exit when positive trade goes negative?
# ============================================
print("\n" + "=" * 70)
print("3. WHAT IF: EXIT WHEN POSITIVE TRADE GOES NEGATIVE?")
print("=" * 70)

# If we exited at breakeven when trade went from positive to negative
# Winners that dropped: we'd get ~$0 instead of their final PnL
lost_profit = positive_then_neg_won['final_pnl'].sum()

# Losers that dropped: we'd get ~$0 instead of losing
saved_loss = -positive_then_neg_lost['final_pnl'].sum()

print(f"Winners we'd exit at BE: {len(positive_then_neg_won)} trades (lose ${lost_profit:.0f} profit)")
print(f"Losers we'd exit at BE: {len(positive_then_neg_lost)} trades (save ${saved_loss:.0f} loss)")
print(f"Net impact: ${saved_loss - lost_profit:.0f}")

# ============================================
# WHAT IF: Exit after being underwater X mins (after positive)?
# ============================================
print("\n" + "=" * 70)
print("4. WHAT IF: EXIT AFTER X MINS UNDERWATER (AFTER BEING POSITIVE)?")
print("=" * 70)

for exit_underwater_mins in [15, 30, 45, 60, 90]:
    # Winners that spent >= X mins underwater after being positive
    winners_affected = positive_then_neg_won[positive_then_neg_won['mins_underwater_after_positive'] >= exit_underwater_mins]
    losers_affected = positive_then_neg_lost[positive_then_neg_lost['mins_underwater_after_positive'] >= exit_underwater_mins]
    
    # Estimate: exit at 50% of max drawdown after positive
    winners_lost = winners_affected['final_pnl'].sum()
    # For losers, we'd exit earlier - estimate saving half the loss
    losers_saved = -losers_affected['final_pnl'].sum() * 0.5
    
    print(f"\nExit if underwater {exit_underwater_mins}+ mins after being positive:")
    print(f"   Winners affected: {len(winners_affected)} (lose ${winners_lost:.0f})")
    print(f"   Losers affected: {len(losers_affected)} (save ~${losers_saved:.0f})")
    print(f"   Net: ${losers_saved - winners_lost:.0f}")

# ============================================
# By profit level before drop
# ============================================
print("\n" + "=" * 70)
print("5. BREAKDOWN BY PROFIT LEVEL BEFORE DROPPING")
print("=" * 70)

for profit_threshold in [20, 40, 60, 80, 100]:
    winners_above = positive_then_neg_won[positive_then_neg_won['max_profit_before_drop'] >= profit_threshold]
    losers_above = positive_then_neg_lost[positive_then_neg_lost['max_profit_before_drop'] >= profit_threshold]
    
    print(f"\nTrades that reached +${profit_threshold}+ before dropping:")
    print(f"   Winners: {len(winners_above)}, PnL: ${winners_above['final_pnl'].sum():.0f}")
    print(f"   Losers: {len(losers_above)}, PnL: ${losers_above['final_pnl'].sum():.0f}")

# ============================================
# Sample of worst "almost winners" that lost
# ============================================
print("\n" + "=" * 70)
print("6. MOST PAINFUL: HIGH PROFIT THEN BIG LOSS")
print("=" * 70)

painful = positive_then_neg_lost.nlargest(10, 'max_profit_before_drop')
print("Trades with highest unrealized profit that ended as SL loss:")
for _, t in painful.iterrows():
    print(f"   {str(t['entry_time'])[:16]} | Was +${t['max_profit_before_drop']:.0f} -> Lost ${t['final_pnl']:.0f} | Positive for {t['mins_positive_before_drop']:.0f}min")
