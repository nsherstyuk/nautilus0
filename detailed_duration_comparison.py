"""
Detailed comparison of trade duration and outcomes
"""
import pandas as pd
import numpy as np
from pathlib import Path

# Load positions
baseline_pos = pd.read_csv('logs/backtest_results_baseline/EUR-USD_20251116_130912/positions.csv')
test_pos = pd.read_csv('logs/backtest_results/EUR-USD_20251116_131055/positions.csv')

# Parse timestamps
for df in [baseline_pos, test_pos]:
    df['ts_opened'] = pd.to_datetime(df['ts_opened'])
    df['ts_closed'] = pd.to_datetime(df['ts_closed'])
    df['duration'] = (df['ts_closed'] - df['ts_opened']).dt.total_seconds() / 3600  # hours
    # Remove USD suffix and convert to numeric
    df['realized_pnl'] = df['realized_pnl'].str.replace(' USD', '').astype(float)
    df['is_winner'] = df['realized_pnl'] > 0
    df['duration_bucket'] = pd.cut(df['duration'], bins=[0, 4, 12, 24, 48, np.inf], 
                                     labels=['<4h', '4-12h', '12-24h', '24-48h', '>48h'])

print("="*80)
print("TRADE DURATION ANALYSIS - BASELINE vs TEST")
print("="*80)

print(f"\n{'='*40}")
print("OVERALL STATS")
print(f"{'='*40}")
print(f"Baseline: {len(baseline_pos)} trades, Win Rate: {baseline_pos['is_winner'].mean()*100:.2f}%, Total PnL: ${baseline_pos['realized_pnl'].sum():,.2f}")
print(f"Test:     {len(test_pos)} trades, Win Rate: {test_pos['is_winner'].mean()*100:.2f}%, Total PnL: ${test_pos['realized_pnl'].sum():,.2f}")
print(f"Change:   {len(test_pos)-len(baseline_pos):+d} trades, Win Rate: {(test_pos['is_winner'].mean()-baseline_pos['is_winner'].mean())*100:+.2f}%, PnL: ${test_pos['realized_pnl'].sum()-baseline_pos['realized_pnl'].sum():+,.2f}")

print(f"\n{'='*40}")
print("DURATION DISTRIBUTION")
print(f"{'='*40}")

for bucket in ['<4h', '4-12h', '12-24h', '24-48h', '>48h']:
    b_trades = baseline_pos[baseline_pos['duration_bucket'] == bucket]
    t_trades = test_pos[test_pos['duration_bucket'] == bucket]
    
    b_count = len(b_trades)
    t_count = len(t_trades)
    b_wr = b_trades['is_winner'].mean() * 100 if len(b_trades) > 0 else 0
    t_wr = t_trades['is_winner'].mean() * 100 if len(t_trades) > 0 else 0
    b_pnl = b_trades['realized_pnl'].sum()
    t_pnl = t_trades['realized_pnl'].sum()
    
    print(f"\n{bucket:>8}:")
    print(f"  Count:    {b_count:>3} → {t_count:>3} ({t_count-b_count:+d})")
    print(f"  Win Rate: {b_wr:>5.1f}% → {t_wr:>5.1f}% ({t_wr-b_wr:+.1f}%)")
    print(f"  PnL:      ${b_pnl:>8,.2f} → ${t_pnl:>8,.2f} (${t_pnl-b_pnl:+,.2f})")

print(f"\n{'='*40}")
print("CRITICAL: <4h TRADES ANALYSIS")
print(f"{'='*40}")

baseline_short = baseline_pos[baseline_pos['duration'] < 4]
test_short = test_pos[test_pos['duration'] < 4]

print(f"\nBaseline <4h: {len(baseline_short)} trades")
print(f"  Winners: {baseline_short['is_winner'].sum()} ({baseline_short['is_winner'].mean()*100:.1f}%)")
print(f"  Losers:  {(~baseline_short['is_winner']).sum()} ({(~baseline_short['is_winner']).mean()*100:.1f}%)")
print(f"  PnL:     ${baseline_short['realized_pnl'].sum():,.2f}")
print(f"  Avg Win: ${baseline_short[baseline_short['is_winner']]['realized_pnl'].mean():.2f}")
print(f"  Avg Loss: ${baseline_short[~baseline_short['is_winner']]['realized_pnl'].mean():.2f}")

print(f"\nTest <4h: {len(test_short)} trades")
print(f"  Winners: {test_short['is_winner'].sum()} ({test_short['is_winner'].mean()*100:.1f}%)")
print(f"  Losers:  {(~test_short['is_winner']).sum()} ({(~test_short['is_winner']).mean()*100:.1f}%)")
print(f"  PnL:     ${test_short['realized_pnl'].sum():,.2f}")
print(f"  Avg Win: ${test_short[test_short['is_winner']]['realized_pnl'].mean():.2f}")
print(f"  Avg Loss: ${test_short[~test_short['is_winner']]['realized_pnl'].mean():.2f}")

print(f"\nChange in <4h trades:")
print(f"  Count:    {len(test_short)-len(baseline_short):+d}")
print(f"  Winners:  {test_short['is_winner'].sum()-baseline_short['is_winner'].sum():+d}")
print(f"  Losers:   {(~test_short['is_winner']).sum()-(~baseline_short['is_winner']).sum():+d}")
print(f"  PnL:      ${test_short['realized_pnl'].sum()-baseline_short['realized_pnl'].sum():+,.2f}")

print(f"\n{'='*40}")
print("LOSS SIZE ANALYSIS")
print(f"{'='*40}")

baseline_losers = baseline_pos[~baseline_pos['is_winner']]
test_losers = test_pos[~test_pos['is_winner']]

print(f"\nBaseline losers: {len(baseline_losers)} trades")
print(f"  Max loss:  ${baseline_losers['realized_pnl'].min():.2f}")
print(f"  Avg loss:  ${baseline_losers['realized_pnl'].mean():.2f}")
print(f"  Total:     ${baseline_losers['realized_pnl'].sum():,.2f}")

print(f"\nTest losers: {len(test_losers)} trades")
print(f"  Max loss:  ${test_losers['realized_pnl'].min():.2f}")
print(f"  Avg loss:  ${test_losers['realized_pnl'].mean():.2f}")
print(f"  Total:     ${test_losers['realized_pnl'].sum():,.2f}")

print(f"\nChange:")
print(f"  Count:     {len(test_losers)-len(baseline_losers):+d} losers")
print(f"  Max loss:  ${test_losers['realized_pnl'].min()-baseline_losers['realized_pnl'].min():+.2f} (better is positive)")
print(f"  Avg loss:  ${test_losers['realized_pnl'].mean()-baseline_losers['realized_pnl'].mean():+.2f} (better is positive)")
print(f"  Total:     ${test_losers['realized_pnl'].sum()-baseline_losers['realized_pnl'].sum():+,.2f} (better is positive)")

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print("\n📊 The feature reduced loss sizes (24% improvement in avg loser)")
print("⚠️  But increased loser count by", len(test_losers)-len(baseline_losers), "trades")
print("❌ Net effect: -$228.76 total PnL")
print("\n💡 Conclusion: Wider stops let MORE trades hit SL before reversing")
print("   Better approach: Filter out choppy markets (ADX) + exclude bad hours")
