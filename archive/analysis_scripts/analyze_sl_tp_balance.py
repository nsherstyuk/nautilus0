"""
Analyze SL vs TP balance in B2 results.
Check if tight SL is causing unnecessary losses.
"""

import pandas as pd
import numpy as np

B2_TRADES = r"backtest_results\MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_20260213_090610\trades_20260213_090610.csv"

df = pd.read_csv(B2_TRADES)

# Split by exit reason
losers = df[df['exit_reason'] == 'SL']
winners = df[df['exit_reason'] == 'TP']

print("="*80)
print("B2 (SL=1.2x, TP=0.9x) - WIN/LOSS ANALYSIS")
print("="*80)

print(f"\n📊 TRADE BREAKDOWN:")
print(f"Total Trades: {len(df)}")
print(f"TP Winners: {len(winners)} ({len(winners)/len(df)*100:.1f}%)")
print(f"SL Losers: {len(losers)} ({len(losers)/len(df)*100:.1f}%)")

print(f"\n💰 P&L STATISTICS:")
print(f"Average Win: ${winners['pnl'].mean():.2f}")
print(f"Average Loss: ${losers['pnl'].mean():.2f}")
print(f"Win Range: ${winners['pnl'].min():.2f} to ${winners['pnl'].max():.2f}")
print(f"Loss Range: ${losers['pnl'].min():.2f} to ${losers['pnl'].max():.2f}")

risk_reward = abs(losers['pnl'].mean()) / winners['pnl'].mean()
print(f"\n⚖️ RISK/REWARD RATIO: {risk_reward:.2f}:1")
print(f"(Risking ${abs(losers['pnl'].mean()):.2f} to make ${winners['pnl'].mean():.2f})")

# Check for "marginal" losses (small SL hits that might have recovered)
small_losses = losers[losers['pnl'] > -30]  # Lost less than $30
print(f"\n🔍 MARGINAL LOSSES (under $30):")
print(f"Count: {len(small_losses)} ({len(small_losses)/len(losers)*100:.1f}% of all losses)")
print(f"Total P&L from marginal losses: ${small_losses['pnl'].sum():.2f}")
print(f"→ If these had room to breathe (wider SL), some might have recovered")

# Duration analysis
print(f"\n⏱️ TRADE DURATION:")
print(f"Avg duration (winners): {winners['duration_bars'].mean():.1f} bars")
print(f"Avg duration (losers): {losers['duration_bars'].mean():.1f} bars")

# Hypothesis: What if we had SL=2.0x instead of 1.2x?
# Rough estimate: losses would be ~67% larger (2.0/1.2), but maybe 30-40% would turn to wins
print(f"\n🧪 HYPOTHESIS: What if SL = 2.0x ATR (instead of 1.2x)?")
print(f"Current losses with 1.2x SL: {len(losers)} trades, ${losers['pnl'].sum():.2f}")

# Estimate: 35% of marginal losses might recover
recoverable_pct = 0.35
recoverable_count = int(len(small_losses) * recoverable_pct)
remaining_losses = len(losers) - recoverable_count
larger_loss_amt = losers['pnl'].mean() * (2.0 / 1.2)

print(f"\nEstimated outcome:")
print(f"  Trades that still hit SL: {remaining_losses}")
print(f"  Average loss (wider): ${larger_loss_amt:.2f}")
print(f"  Total loss amount: ${remaining_losses * larger_loss_amt:.2f}")
print(f"  Trades saved (now wins): ~{recoverable_count}")
print(f"  New wins: ${winners['pnl'].mean():.2f} x {recoverable_count} = ${winners['pnl'].mean() * recoverable_count:.2f}")

original_pnl = df['pnl'].sum()
new_loss_total = remaining_losses * larger_loss_amt
new_win_total = winners['pnl'].sum() + (winners['pnl'].mean() * recoverable_count)
estimated_new_pnl = new_win_total + new_loss_total

print(f"\n📈 P&L COMPARISON:")
print(f"  Original (SL=1.2x): ${original_pnl:.2f}")
print(f"  Estimated (SL=2.0x): ${estimated_new_pnl:.2f}")
print(f"  Difference: ${estimated_new_pnl - original_pnl:.2f} ({((estimated_new_pnl/original_pnl)-1)*100:+.1f}%)")

# Calculate new win rate
new_winners = len(winners) + recoverable_count
new_total = new_winners + remaining_losses
new_wr = new_winners / new_total * 100

print(f"\n🎯 WIN RATE COMPARISON:")
print(f"  Original: {len(winners)/len(df)*100:.1f}%")
print(f"  Estimated (SL=2.0x): {new_wr:.1f}%")

print(f"\n💡 INSIGHT:")
if estimated_new_pnl > original_pnl:
    print(f"  Wider stops (SL=2.0x) could IMPROVE P&L by ~${estimated_new_pnl - original_pnl:.0f}!")
    print(f"  This suggests entries are good but stop placement is too tight.")
else:
    print(f"  Current tight stops are optimal for this strategy.")

print("="*80)
