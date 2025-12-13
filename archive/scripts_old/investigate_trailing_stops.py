"""
Investigate why trailing stops aren't affecting results.
Check if trades are hitting TP/SL before trailing stops can activate.
"""
import pandas as pd
from pathlib import Path

# Load positions
result_folder = Path("logs/backtest_results/EUR-USD_20251112_175738")
pos_df = pd.read_csv(result_folder / "positions.csv")

print("=" * 80)
print("INVESTIGATING TRAILING STOP IMPACT")
print("=" * 80)

# Extract PnL and prices
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

# Current TP/SL settings (from defaults)
TP_PIPS = 50
SL_PIPS = 25
TRAILING_ACTIVATION = 20  # Needs 20 pips profit to activate

print(f"\nCurrent Settings:")
print(f"  Take Profit: {TP_PIPS} pips")
print(f"  Stop Loss: {SL_PIPS} pips")
print(f"  Trailing Activation: {TRAILING_ACTIVATION} pips")
print(f"  Trailing Distance: 15 pips (default)")

print(f"\n{'='*80}")
print("TRADE OUTCOME ANALYSIS")
print(f"{'='*80}")

# Categorize trades
trades_hit_tp = pos_df[pos_df['price_diff_pips'] >= TP_PIPS]
trades_hit_sl = pos_df[pos_df['price_diff_pips'] <= -SL_PIPS]
trades_between = pos_df[(pos_df['price_diff_pips'] > -SL_PIPS) & (pos_df['price_diff_pips'] < TP_PIPS)]
trades_reached_activation = pos_df[pos_df['price_diff_pips'] >= TRAILING_ACTIVATION]

print(f"\nTotal Trades: {len(pos_df)}")
print(f"\nTrades that hit TP ({TP_PIPS} pips): {len(trades_hit_tp)} ({len(trades_hit_tp)/len(pos_df)*100:.1f}%)")
print(f"  These close immediately - trailing stop can't help")
print(f"  Avg PnL: ${trades_hit_tp['pnl_value'].mean():.2f}")

print(f"\nTrades that hit SL ({SL_PIPS} pips): {len(trades_hit_sl)} ({len(trades_hit_sl)/len(pos_df)*100:.1f}%)")
print(f"  These close at loss - trailing stop can't activate (needs {TRAILING_ACTIVATION} pips profit)")
print(f"  Avg PnL: ${trades_hit_sl['pnl_value'].mean():.2f}")

print(f"\nTrades closed between TP/SL: {len(trades_between)} ({len(trades_between)/len(pos_df)*100:.1f}%)")
print(f"  These might benefit from trailing stops")
print(f"  Avg PnL: ${trades_between['pnl_value'].mean():.2f}")

print(f"\nTrades that reached activation threshold ({TRAILING_ACTIVATION}+ pips): {len(trades_reached_activation)} ({len(trades_reached_activation)/len(pos_df)*100:.1f}%)")
print(f"  These could have trailing stops activated")
print(f"  Avg PnL: ${trades_reached_activation['pnl_value'].mean():.2f}")

# Check trades that reached activation but didn't hit TP
trades_with_trailing_potential = pos_df[
    (pos_df['price_diff_pips'] >= TRAILING_ACTIVATION) & 
    (pos_df['price_diff_pips'] < TP_PIPS)
]
print(f"\nTrades that reached {TRAILING_ACTIVATION}+ pips but didn't hit TP: {len(trades_with_trailing_potential)}")
if len(trades_with_trailing_potential) > 0:
    print(f"  These are where trailing stops SHOULD help")
    print(f"  Price movement range: {trades_with_trailing_potential['price_diff_pips'].min():.1f} to {trades_with_trailing_potential['price_diff_pips'].max():.1f} pips")
    print(f"  Avg movement: {trades_with_trailing_potential['price_diff_pips'].mean():.1f} pips")
    print(f"\n  Sample trades:")
    for idx, trade in trades_with_trailing_potential.head(5).iterrows():
        print(f"    {trade['ts_opened']}: {trade['price_diff_pips']:.1f} pips, PnL=${trade['pnl_value']:.2f}")

print(f"\n{'='*80}")
print("DIAGNOSIS")
print(f"{'='*80}")

if len(trades_hit_tp) + len(trades_hit_sl) >= len(pos_df) * 0.9:
    print("\n⚠️  PROBLEM IDENTIFIED:")
    print(f"  {len(trades_hit_tp) + len(trades_hit_sl)} out of {len(pos_df)} trades ({len(trades_hit_tp) + len(trades_hit_sl)/len(pos_df)*100:.1f}%)")
    print(f"  hit TP or SL immediately, so trailing stops never get a chance to activate.")
    print(f"\n  Trailing stops only help trades that:")
    print(f"    1. Don't hit TP immediately")
    print(f"    2. Don't hit SL immediately") 
    print(f"    3. Reach {TRAILING_ACTIVATION}+ pips profit, then reverse")
    print(f"\n  SOLUTION:")
    print(f"    - Increase TP to give trailing stops more room (e.g., 70-80 pips)")
    print(f"    - Or reduce trailing activation threshold (e.g., 10-15 pips)")
    print(f"    - Or check if trailing stops are actually being applied in backtest")

if len(trades_with_trailing_potential) == 0:
    print("\n⚠️  NO TRADES BENEFIT FROM TRAILING STOPS")
    print(f"  All trades either:")
    print(f"    - Hit TP immediately ({len(trades_hit_tp)} trades)")
    print(f"    - Hit SL immediately ({len(trades_hit_sl)} trades)")
    print(f"    - Never reached {TRAILING_ACTIVATION} pips profit")
    print(f"\n  This explains why changing trailing stop settings has no effect!")

print(f"\n{'='*80}")
print("RECOMMENDATIONS")
print(f"{'='*80}")
print(f"\n1. Check if trailing stops are actually being applied:")
print(f"   - Look for log messages: 'Trailing stop activated' and 'Trailing stop moved'")
print(f"   - Check if modify_order is being called")

print(f"\n2. If most trades hit TP/SL immediately:")
print(f"   - Trailing stops won't help - they need time to activate")
print(f"   - Consider wider TP (70-100 pips) to test trailing stops")
print(f"   - Or lower activation threshold (10-15 pips)")

print(f"\n3. To test trailing stops properly:")
print(f"   - Use wider TP (e.g., 100 pips) so trades don't close immediately")
print(f"   - Use lower activation (e.g., 10 pips) so it activates sooner")
print(f"   - Then compare different trailing distances")

