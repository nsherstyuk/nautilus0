"""
Check TP/SL settings and investigate why trailing stops aren't affecting results.
"""
import pandas as pd
from pathlib import Path

# Check latest result
result_folder = Path("logs/backtest_results/EUR-USD_20251112_175738")
pos_df = pd.read_csv(result_folder / "positions.csv")

print("=" * 80)
print("INVESTIGATING WHY TRAILING STOPS DON'T AFFECT RESULTS")
print("=" * 80)

# Extract PnL
if pos_df['realized_pnl'].dtype == 'object':
    pos_df['pnl_value'] = pos_df['realized_pnl'].str.replace(' USD', '', regex=False).str.replace('USD', '', regex=False).str.strip().astype(float)
else:
    pos_df['pnl_value'] = pos_df['realized_pnl'].astype(float)

pos_df['entry_price'] = pos_df['avg_px_open'].astype(float)
pos_df['exit_price'] = pos_df['avg_px_close'].astype(float)

# Calculate price movement in pips
pos_df['price_diff'] = pos_df['exit_price'] - pos_df['entry_price']
pos_df['price_diff_pips'] = pos_df.apply(
    lambda row: row['price_diff'] * 10000 if row['entry'] == 'BUY' else -row['price_diff'] * 10000,
    axis=1
)

# Default TP/SL (from config)
TP_PIPS = 50
SL_PIPS = 25
TRAILING_ACTIVATION = 20

print(f"\nCurrent TP/SL Settings (from config defaults):")
print(f"  Take Profit: {TP_PIPS} pips")
print(f"  Stop Loss: {SL_PIPS} pips")
print(f"  Trailing Activation: {TRAILING_ACTIVATION} pips")
print(f"  Trailing Distance: 15 pips (default)")

print(f"\n{'='*80}")
print("TRADE OUTCOME BREAKDOWN")
print(f"{'='*80}")

total = len(pos_df)
trades_hit_tp = pos_df[pos_df['price_diff_pips'] >= TP_PIPS]
trades_hit_sl = pos_df[pos_df['price_diff_pips'] <= -SL_PIPS]
trades_between = pos_df[(pos_df['price_diff_pips'] > -SL_PIPS) & (pos_df['price_diff_pips'] < TP_PIPS)]
trades_reached_activation = pos_df[pos_df['price_diff_pips'] >= TRAILING_ACTIVATION]

print(f"\nTotal Trades: {total}")
print(f"\n1. Trades that hit TP ({TP_PIPS} pips): {len(trades_hit_tp)} ({len(trades_hit_tp)/total*100:.1f}%)")
print(f"   → Close immediately at TP - trailing stop can't help")
print(f"   → Avg PnL: ${trades_hit_tp['pnl_value'].mean():.2f}")

print(f"\n2. Trades that hit SL ({SL_PIPS} pips): {len(trades_hit_sl)} ({len(trades_hit_sl)/total*100:.1f}%)")
print(f"   → Close at loss - trailing stop can't activate (needs {TRAILING_ACTIVATION} pips profit)")
print(f"   → Avg PnL: ${trades_hit_sl['pnl_value'].mean():.2f}")

print(f"\n3. Trades closed between TP/SL: {len(trades_between)} ({len(trades_between)/total*100:.1f}%)")
print(f"   → These might benefit from trailing stops")
print(f"   → Avg PnL: ${trades_between['pnl_value'].mean():.2f}")

print(f"\n4. Trades that reached activation threshold ({TRAILING_ACTIVATION}+ pips): {len(trades_reached_activation)} ({len(trades_reached_activation)/total*100:.1f}%)")
print(f"   → These could have trailing stops activated")
print(f"   → Avg PnL: ${trades_reached_activation['pnl_value'].mean():.2f}")

# Key insight: trades that reached activation but didn't hit TP
trades_with_trailing_potential = pos_df[
    (pos_df['price_diff_pips'] >= TRAILING_ACTIVATION) & 
    (pos_df['price_diff_pips'] < TP_PIPS)
]

print(f"\n5. Trades that reached {TRAILING_ACTIVATION}+ pips but didn't hit TP: {len(trades_with_trailing_potential)}")
if len(trades_with_trailing_potential) > 0:
    print(f"   → These are where trailing stops SHOULD help")
    print(f"   → Price movement: {trades_with_trailing_potential['price_diff_pips'].min():.1f} to {trades_with_trailing_potential['price_diff_pips'].max():.1f} pips")
    print(f"   → Avg: {trades_with_trailing_potential['price_diff_pips'].mean():.1f} pips")
else:
    print(f"   → NONE! This explains why trailing stops don't help")

print(f"\n{'='*80}")
print("ROOT CAUSE ANALYSIS")
print(f"{'='*80}")

immediate_closes = len(trades_hit_tp) + len(trades_hit_sl)
print(f"\nTrades that close immediately (TP or SL): {immediate_closes} ({immediate_closes/total*100:.1f}%)")
print(f"Trades that could benefit from trailing: {len(trades_with_trailing_potential)} ({len(trades_with_trailing_potential)/total*100:.1f}%)")

if immediate_closes >= total * 0.9:
    print(f"\n⚠️  PROBLEM FOUND:")
    print(f"   {immediate_closes/total*100:.1f}% of trades hit TP or SL immediately!")
    print(f"   Trailing stops can't help trades that close before they activate.")
    print(f"\n   Why trailing stops don't matter:")
    print(f"   - TP = {TP_PIPS} pips (trades close here)")
    print(f"   - Trailing activation = {TRAILING_ACTIVATION} pips (needs this profit to activate)")
    print(f"   - If trade hits TP at {TP_PIPS} pips, it closes before trailing can help")
    print(f"   - If trade hits SL at {SL_PIPS} pips, trailing can't activate (needs profit)")

if len(trades_with_trailing_potential) == 0:
    print(f"\n⚠️  NO TRADES BENEFIT FROM TRAILING STOPS")
    print(f"   All trades either:")
    print(f"   - Hit TP immediately ({len(trades_hit_tp)} trades)")
    print(f"   - Hit SL immediately ({len(trades_hit_sl)} trades)")
    print(f"   - Never reached {TRAILING_ACTIVATION} pips profit")
    print(f"\n   This is why changing trailing stop settings has ZERO effect!")

print(f"\n{'='*80}")
print("SOLUTIONS")
print(f"{'='*80}")
print(f"\nTo test trailing stops properly, you need trades that:")
print(f"  1. Don't hit TP immediately")
print(f"  2. Reach {TRAILING_ACTIVATION}+ pips profit")
print(f"  3. Then reverse (giving trailing stop a chance to help)")
print(f"\nOptions:")
print(f"\n1. INCREASE TP (e.g., 70-100 pips)")
print(f"   → Gives trades more room to move")
print(f"   → Trailing stops can activate and help")
print(f"   → Test: BACKTEST_TAKE_PROFIT_PIPS=80")
print(f"\n2. DECREASE TRAILING ACTIVATION (e.g., 10-15 pips)")
print(f"   → Activates sooner")
print(f"   → More trades can benefit")
print(f"   → Test: BACKTEST_TRAILING_STOP_ACTIVATION_PIPS=10")
print(f"\n3. CHECK IF TRAILING STOPS ARE ACTUALLY WORKING")
print(f"   → Look for log messages: 'Trailing stop activated'")
print(f"   → Check if modify_order is being called")
print(f"   → Verify orders are being modified in backtest")

