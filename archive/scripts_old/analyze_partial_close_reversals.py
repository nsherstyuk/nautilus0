"""
Analyze trades that had successful partial closes but ended with trailing stop losses.

This identifies the pattern:
1. Trade goes profitable → partial close executed
2. Remaining position reverses → trailing stop hit
3. Net result: reduced profit or even loss

This could be a key issue in Oct-Nov degradation.
"""
import pandas as pd
from pathlib import Path

# Load trades
results_dir = Path("logs/backtest_results/MTF_ML_20251128_202046")
trades_df = pd.read_csv(results_dir / "trades.csv")
trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])

print("="*80)
print("PARTIAL CLOSE REVERSAL ANALYSIS")
print("="*80)

# Filter Oct-Nov 2025
oct_nov = trades_df[trades_df['entry_month'].isin(['2025-10', '2025-11'])].copy()

print(f"\nTotal Oct-Nov trades: {len(oct_nov)}")
print(f"Trades with partial close: {oct_nov['partial_closed'].sum()}")

# Identify the problematic pattern
print("\n" + "="*80)
print("PATTERN: Partial Close → Trailing Stop Loss")
print("="*80)

# Trades that had partial close AND hit trailing stop
partial_then_trail = oct_nov[
    (oct_nov['partial_closed'] == True) & 
    (oct_nov['exit_reason'] == 'TRAIL')
].copy()

print(f"\nTrades with this pattern: {len(partial_then_trail)}")

if len(partial_then_trail) > 0:
    # Calculate what would have happened without partial close
    # Partial close locks in profit, but then trailing stop might lose
    
    print("\n" + "-"*80)
    print("DETAILED ANALYSIS")
    print("-"*80)
    
    # Group by outcome
    winners = partial_then_trail[partial_then_trail['pnl'] > 0]
    losers = partial_then_trail[partial_then_trail['pnl'] < 0]
    breakeven = partial_then_trail[partial_then_trail['pnl'] == 0]
    
    print(f"\nAfter partial close + trail stop:")
    print(f"  Winners: {len(winners)} (${winners['pnl'].sum():,.2f})")
    print(f"  Losers:  {len(losers)} (${losers['pnl'].sum():,.2f})")
    print(f"  Breakeven: {len(breakeven)}")
    
    print(f"\nNet P&L from this pattern: ${partial_then_trail['pnl'].sum():,.2f}")
    print(f"Average P&L: ${partial_then_trail['pnl'].mean():.2f}")
    
    # Show examples of losers (partial close but still lost)
    if len(losers) > 0:
        print("\n" + "-"*80)
        print("EXAMPLES: Partial Close but STILL LOST")
        print("-"*80)
        
        for idx, trade in losers.head(10).iterrows():
            print(f"\nTrade {idx}:")
            print(f"  Entry: {trade['entry_time']} @ {trade['entry_price']:.5f}")
            print(f"  Exit:  {trade['exit_time']} @ {trade['exit_price']:.5f}")
            print(f"  Side: {trade['side']}")
            print(f"  Duration: {trade['duration_bars']} bars")
            print(f"  Final P&L: ${trade['pnl']:.2f}")
            print(f"  Exit reason: {trade['exit_reason']}")
            print(f"  → Had partial close but trailing stop gave back gains!")

# Now analyze ALL partial closes in Oct-Nov
print("\n" + "="*80)
print("ALL PARTIAL CLOSE TRADES (Oct-Nov)")
print("="*80)

partial_trades = oct_nov[oct_nov['partial_closed'] == True].copy()

if len(partial_trades) > 0:
    print(f"\nTotal partial close trades: {len(partial_trades)}")
    
    # Group by exit reason
    exit_reasons = partial_trades.groupby('exit_reason').agg({
        'pnl': ['count', 'sum', 'mean']
    })
    exit_reasons.columns = ['Count', 'Total P&L', 'Avg P&L']
    
    print("\nBy Exit Reason:")
    print(exit_reasons)
    
    # Calculate success rate
    partial_winners = partial_trades[partial_trades['pnl'] > 0]
    partial_losers = partial_trades[partial_trades['pnl'] < 0]
    
    print(f"\nPartial Close Outcomes:")
    print(f"  Winners: {len(partial_winners)} ({len(partial_winners)/len(partial_trades)*100:.1f}%)")
    print(f"  Losers:  {len(partial_losers)} ({len(partial_losers)/len(partial_trades)*100:.1f}%)")
    print(f"  Total P&L: ${partial_trades['pnl'].sum():,.2f}")
    print(f"  Avg P&L: ${partial_trades['pnl'].mean():.2f}")

# Compare with non-partial trades
print("\n" + "="*80)
print("COMPARISON: Partial vs Non-Partial Trades")
print("="*80)

non_partial = oct_nov[oct_nov['partial_closed'] == False].copy()

print(f"\nPartial Close Trades ({len(partial_trades)}):")
print(f"  Win Rate: {(partial_trades['pnl'] > 0).sum() / len(partial_trades) * 100:.1f}%")
print(f"  Avg P&L: ${partial_trades['pnl'].mean():.2f}")
print(f"  Total P&L: ${partial_trades['pnl'].sum():,.2f}")

print(f"\nNon-Partial Trades ({len(non_partial)}):")
print(f"  Win Rate: {(non_partial['pnl'] > 0).sum() / len(non_partial) * 100:.1f}%")
print(f"  Avg P&L: ${non_partial['pnl'].mean():.2f}")
print(f"  Total P&L: ${non_partial['pnl'].sum():,.2f}")

# Hypothesis: Partial closes might be HURTING performance in Oct-Nov
print("\n" + "="*80)
print("HYPOTHESIS TEST")
print("="*80)

if len(partial_trades) > 0 and len(non_partial) > 0:
    partial_avg = partial_trades['pnl'].mean()
    non_partial_avg = non_partial['pnl'].mean()
    
    print(f"\nAverage P&L per trade:")
    print(f"  With partial close: ${partial_avg:.2f}")
    print(f"  Without partial close: ${non_partial_avg:.2f}")
    print(f"  Difference: ${partial_avg - non_partial_avg:.2f}")
    
    if partial_avg < non_partial_avg:
        print("\n⚠️  WARNING: Partial closes are REDUCING average profit!")
        print("   Possible reasons:")
        print("   1. Locking in small gains, then giving back more on remainder")
        print("   2. Oct-Nov market is choppy (whipsaws after partial)")
        print("   3. Trailing stop too tight after partial close")
    else:
        print("\n✅ Partial closes are helping (or neutral)")

# Detailed breakdown of partial→trail pattern
print("\n" + "="*80)
print("PARTIAL → TRAIL STOP BREAKDOWN")
print("="*80)

if len(partial_then_trail) > 0:
    # Calculate statistics
    print(f"\nTrades: {len(partial_then_trail)}")
    print(f"Total P&L: ${partial_then_trail['pnl'].sum():,.2f}")
    print(f"Average P&L: ${partial_then_trail['pnl'].mean():.2f}")
    print(f"Win Rate: {(partial_then_trail['pnl'] > 0).sum() / len(partial_then_trail) * 100:.1f}%")
    
    # Show distribution
    print("\nP&L Distribution:")
    print(f"  Max Win: ${partial_then_trail['pnl'].max():.2f}")
    print(f"  Max Loss: ${partial_then_trail['pnl'].min():.2f}")
    print(f"  Median: ${partial_then_trail['pnl'].median():.2f}")
    
    # Duration analysis
    print(f"\nDuration (bars):")
    print(f"  Average: {partial_then_trail['duration_bars'].mean():.1f}")
    print(f"  Median: {partial_then_trail['duration_bars'].median():.1f}")
    
    # Side analysis
    print(f"\nBy Side:")
    for side in ['LONG', 'SHORT']:
        side_trades = partial_then_trail[partial_then_trail['side'] == side]
        if len(side_trades) > 0:
            print(f"  {side}: {len(side_trades)} trades, ${side_trades['pnl'].sum():,.2f} total, ${side_trades['pnl'].mean():.2f} avg")

print("\n" + "="*80)
print("RECOMMENDATION")
print("="*80)

if len(partial_then_trail) > 0:
    impact = partial_then_trail['pnl'].sum()
    avg_impact = partial_then_trail['pnl'].mean()
    
    if avg_impact < 0:
        print(f"\n⚠️  CRITICAL FINDING:")
        print(f"   Partial→Trail pattern is LOSING money: ${impact:,.2f}")
        print(f"   Average loss per trade: ${avg_impact:.2f}")
        print(f"\n   RECOMMENDATION:")
        print(f"   1. Consider disabling partial closes in choppy markets")
        print(f"   2. Or widen trailing stop after partial close")
        print(f"   3. Or use time-based exit instead of trail after partial")
    elif avg_impact < 20:
        print(f"\n⚠️  Partial→Trail pattern is barely profitable: ${impact:,.2f}")
        print(f"   Average: ${avg_impact:.2f} per trade")
        print(f"   This might not be worth the complexity")
    else:
        print(f"\n✅ Partial→Trail pattern is working: ${impact:,.2f}")
        print(f"   Average: ${avg_impact:.2f} per trade")
        print(f"   Keep current settings")
else:
    print("\nNo trades with Partial→Trail pattern found")
