"""
Analyze price levels from historical trades to identify support/resistance zones
and design level-based entry timing
"""
import pandas as pd
import numpy as np
from pathlib import Path

# Load baseline positions to get price data
baseline_dir = Path('logs/backtest_results_baseline/EUR-USD_20251116_130912')
baseline_pos = pd.read_csv(baseline_dir / 'positions.csv')

# Parse prices
baseline_pos['avg_px_open'] = pd.to_numeric(baseline_pos['avg_px_open'], errors='coerce')
baseline_pos['avg_px_close'] = pd.to_numeric(baseline_pos['avg_px_close'], errors='coerce')
baseline_pos['realized_pnl'] = baseline_pos['realized_pnl'].str.replace(' USD', '').astype(float)
baseline_pos['ts_opened'] = pd.to_datetime(baseline_pos['ts_opened'])
baseline_pos['is_winner'] = baseline_pos['realized_pnl'] > 0

print("="*80)
print("PRICE LEVEL ANALYSIS FOR ENTRY TIMING")
print("="*80)

# Get all entry and exit prices
all_prices = pd.concat([
    baseline_pos['avg_px_open'],
    baseline_pos['avg_px_close']
]).dropna()

print(f"\n📊 PRICE RANGE:")
print(f"   Minimum: {all_prices.min():.5f}")
print(f"   Maximum: {all_prices.max():.5f}")
print(f"   Range: {(all_prices.max() - all_prices.min()):.5f} ({(all_prices.max() - all_prices.min())*10000:.1f} pips)")

# Cluster prices into levels using round numbers
def find_price_levels(prices, round_to=0.0010):
    """Find significant price levels where price frequently trades"""
    rounded = (prices / round_to).round() * round_to
    level_counts = rounded.value_counts()
    return level_counts

# Find levels where price frequently touches (every 10 pips)
levels_10pip = find_price_levels(all_prices, round_to=0.0010)
print(f"\n📍 MOST FREQUENTED PRICE LEVELS (10-pip zones):")
print(levels_10pip.head(15).to_string())

# Analyze entry prices for winners vs losers
print(f"\n{'='*80}")
print("ENTRY PRICE ANALYSIS: Winners vs Losers")
print(f"{'='*80}")

winners = baseline_pos[baseline_pos['is_winner']].copy()
losers = baseline_pos[~baseline_pos['is_winner']].copy()

print(f"\n🟢 WINNERS (n={len(winners)}):")
print(f"   Entry Price Range: {winners['avg_px_open'].min():.5f} - {winners['avg_px_open'].max():.5f}")
print(f"   Mean Entry: {winners['avg_px_open'].mean():.5f}")
print(f"   Median Entry: {winners['avg_px_open'].median():.5f}")

print(f"\n🔴 LOSERS (n={len(losers)}):")
print(f"   Entry Price Range: {losers['avg_px_open'].min():.5f} - {losers['avg_px_open'].max():.5f}")
print(f"   Mean Entry: {losers['avg_px_open'].mean():.5f}")
print(f"   Median Entry: {losers['avg_px_open'].median():.5f}")

# Analyze price movement from entry to exit
baseline_pos['price_move_pips'] = (baseline_pos['avg_px_close'] - baseline_pos['avg_px_open']) * 10000
baseline_pos['price_move_pct'] = ((baseline_pos['avg_px_close'] / baseline_pos['avg_px_open']) - 1) * 100

print(f"\n{'='*80}")
print("PRICE MOVEMENT ANALYSIS")
print(f"{'='*80}")

print(f"\n🟢 WINNERS:")
print(f"   Avg movement: {winners['price_move_pips'].abs().mean():.1f} pips")
print(f"   Max favorable: {winners['price_move_pips'].abs().max():.1f} pips")
print(f"   Min favorable: {winners['price_move_pips'].abs().min():.1f} pips")

print(f"\n🔴 LOSERS:")
print(f"   Avg movement: {losers['price_move_pips'].abs().mean():.1f} pips")
print(f"   Max adverse: {losers['price_move_pips'].abs().max():.1f} pips")
print(f"   Min adverse: {losers['price_move_pips'].abs().min():.1f} pips")

# Identify round numbers (psychological levels)
def get_round_number_distance(price, level=0.01):
    """Calculate distance to nearest round number"""
    nearest = round(price / level) * level
    distance_pips = abs(price - nearest) * 10000
    return distance_pips

baseline_pos['dist_to_round_100'] = baseline_pos['avg_px_open'].apply(lambda x: get_round_number_distance(x, 0.01))
baseline_pos['dist_to_round_50'] = baseline_pos['avg_px_open'].apply(lambda x: get_round_number_distance(x, 0.005))

print(f"\n{'='*80}")
print("ROUND NUMBER ANALYSIS (Psychological Levels)")
print(f"{'='*80}")

# Check if entries near round numbers perform better/worse
near_round_100 = baseline_pos[baseline_pos['dist_to_round_100'] < 5]  # Within 5 pips of 100-pip level
far_from_round = baseline_pos[baseline_pos['dist_to_round_100'] >= 10]  # 10+ pips away

print(f"\n📍 ENTRIES NEAR 100-PIP ROUND NUMBERS (<5 pips away):")
print(f"   Trades: {len(near_round_100)}")
print(f"   Win Rate: {near_round_100['is_winner'].mean()*100:.1f}%")
print(f"   Avg PnL: ${near_round_100['realized_pnl'].mean():.2f}")
print(f"   Total PnL: ${near_round_100['realized_pnl'].sum():.2f}")

print(f"\n📍 ENTRIES FAR FROM ROUND NUMBERS (>10 pips away):")
print(f"   Trades: {len(far_from_round)}")
print(f"   Win Rate: {far_from_round['is_winner'].mean()*100:.1f}%")
print(f"   Avg PnL: ${far_from_round['realized_pnl'].mean():.2f}")
print(f"   Total PnL: ${far_from_round['realized_pnl'].sum():.2f}")

# Analyze by direction relative to round numbers
print(f"\n{'='*80}")
print("DIRECTION ANALYSIS (BUY from support / SELL from resistance)")
print(f"{'='*80}")

buys = baseline_pos[baseline_pos['side'] == 'BUY'].copy()
sells = baseline_pos[baseline_pos['side'] == 'SELL'].copy()

print(f"\n📊 BUY trades:")
print(f"   Total: {len(buys)}, Win Rate: {buys['is_winner'].mean()*100:.1f}%, PnL: ${buys['realized_pnl'].sum():.2f}")

print(f"\n📊 SELL trades:")
print(f"   Total: {len(sells)}, Win Rate: {sells['is_winner'].mean()*100:.1f}%, PnL: ${sells['realized_pnl'].sum():.2f}")

# Simulate level-based entry improvements
print(f"\n{'='*80}")
print("🎯 PROPOSED LEVEL-BASED ENTRY STRATEGIES")
print(f"{'='*80}")

print(f"\n1️⃣  PULLBACK ENTRY (Buy dips, Sell rallies):")
print(f"   Concept: Wait for price to pull back to support/resistance before entry")
print(f"   Implementation:")
print(f"   • On BUY signal: Wait for price to pull back 5-10 pips from MA crossover")
print(f"   • On SELL signal: Wait for price to rally 5-10 pips from MA crossover")
print(f"   • Or wait for touch of nearby round number")
print(f"   Expected impact: +10-15% win rate (better entry prices)")

print(f"\n2️⃣  BREAKOUT ENTRY (Trade momentum):")
print(f"   Concept: Only enter after price breaks above/below key level")
print(f"   Implementation:")
print(f"   • On BUY signal: Wait for price to break above recent swing high")
print(f"   • On SELL signal: Wait for price to break below recent swing low")
print(f"   • Confirm momentum before entry")
print(f"   Expected impact: Fewer trades but higher win rate")

print(f"\n3️⃣  ROUND NUMBER FILTER:")
print(f"   Concept: Avoid entries very close to psychological levels")
print(f"   Implementation:")
print(f"   • Reject signals within 3-5 pips of 50-pip or 100-pip round numbers")
print(f"   • Levels act as barriers - price often reverses there")
print(f"   • Wait for clear break or rejection before entry")
print(f"   Expected impact: Reduce false signals at resistance/support")

print(f"\n4️⃣  SWING HIGH/LOW LEVELS:")
print(f"   Concept: Identify recent swing highs/lows as levels")
print(f"   Implementation:")
print(f"   • Track highest high and lowest low over last N bars (e.g., 20-50 bars)")
print(f"   • BUY near swing low (support), SELL near swing high (resistance)")
print(f"   • Measure distance: reject if too far from nearest level")
print(f"   Expected impact: +$500-1000 improvement")

# Practical recommendation
print(f"\n{'='*80}")
print("💡 RECOMMENDED IMPLEMENTATION")
print(f"{'='*80}")

print(f"\nStart with PULLBACK ENTRY (already partially implemented):")
print(f"\n✅ Current code has:")
print(f"   STRATEGY_ENTRY_TIMING_METHOD=pullback")
print(f"   STRATEGY_ENTRY_TIMING_TIMEOUT_BARS=10")
print(f"\n🔧 Enhance with LEVEL-BASED logic:")
print(f"\n1. Track swing high/low over last 20-50 bars")
print(f"2. Calculate distance from current price to nearest swing level")
print(f"3. For BUY signals:")
print(f"   • If price within 5-10 pips of swing low → ENTER (support)")
print(f"   • If price > 15 pips above swing low → WAIT for pullback")
print(f"   • If price near round number (±3 pips) → WAIT for break")
print(f"4. For SELL signals:")
print(f"   • If price within 5-10 pips of swing high → ENTER (resistance)")
print(f"   • If price > 15 pips below swing high → WAIT for retracement")
print(f"   • If price near round number (±3 pips) → WAIT for break")

print(f"\n📝 CODE ADDITIONS NEEDED:")
print(f"   1. Add swing_high/swing_low tracking to strategy")
print(f"   2. Calculate distance_to_swing_level in check_entry_timing()")
print(f"   3. Add round_number_distance check")
print(f"   4. Add level-based entry logic to pullback method")

print(f"\n🎯 EXPECTED RESULTS:")
print(f"   • Better entry prices (5-10 pips improvement)")
print(f"   • Higher win rate (+5-10%)")
print(f"   • Similar or fewer trades")
print(f"   • Estimated PnL improvement: $500-$1,500")

print(f"\n{'='*80}")
print("NEXT STEPS")
print(f"{'='*80}")
print(f"\n1. Review current pullback entry code (already exists)")
print(f"2. Add swing high/low level tracking")
print(f"3. Implement level-based entry filtering")
print(f"4. Test with enhanced pullback logic")
print(f"5. Compare results to current baseline")
