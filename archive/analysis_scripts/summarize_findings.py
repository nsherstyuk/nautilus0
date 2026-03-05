"""
Summarize the key findings from the premature entry analysis.
"""

import pandas as pd
from pathlib import Path

# Load analysis results
analysis_path = Path("backtest_results/premature_entry_analysis.csv")
df = pd.read_csv(analysis_path)

print("=" * 80)
print("PREMATURE ENTRY ANALYSIS SUMMARY")
print("=" * 80)
print()

# Overall statistics
print("OVERALL RESULTS:")
print("-" * 80)
print(f"Total trades analyzed: {len(df)}")
print(f"  PREMATURE (SL=1.2 loss -> SL=1.4 win): {len(df[df['category']=='PREMATURE'])}")
print(f"  GOOD (won with both): {len(df[df['category']=='GOOD'])}")
print(f"  BAD (lost with both): {len(df[df['category']=='BAD'])}")
print(f"  IMPROVED (smaller loss with SL=1.4): {len(df[df['category']=='IMPROVED'])}")
print()

# Premature entry details
premature = df[df['category'] == 'PREMATURE']

if len(premature) > 0:
    print("PREMATURE ENTRY DETAILS:")
    print("-" * 80)
    
    total_loss_sl12 = premature['pnl_sl12'].sum()
    total_win_sl14 = premature['pnl_sl14'].sum()
    net_impact = total_win_sl14 - total_loss_sl12
    
    print(f"Financial Impact:")
    print(f"  Lost with SL=1.2: ${total_loss_sl12:,.2f}")
    print(f"  Won with SL=1.4: ${total_win_sl14:,.2f}")
    print(f"  Net opportunity cost: ${net_impact:,.2f}")
    print()
    
    print("Individual Premature Trades:")
    print(f"{'Entry Time':<25} | {'Side':<6} | {'Entry':<8} | {'Exit SL1.2':<10} | {'Exit SL1.4':<10} | {'PnL Change':<12}")
    print("-" * 80)
    
    for idx, trade in premature.iterrows():
        entry_time = trade['entry_time']
        side = trade['side']
        entry = trade['entry_price']
        exit_12 = trade['exit_price_sl12']
        exit_14 = trade['exit_price_sl14']
        pnl_12 = trade['pnl_sl12']
        pnl_14 = trade['pnl_sl14']
        pnl_change = pnl_14 - pnl_12
        
        # Calculate pip movements
        if side == 'LONG':
            move_12 = (exit_12 - entry) * 10000
            move_14 = (exit_14 - entry) * 10000
        else:
            move_12 = (entry - exit_12) * 10000
            move_14 = (entry - exit_14) * 10000
        
        print(f"{entry_time:<25} | {side:<6} | {entry:.5f} | {move_12:+6.1f} pips | {move_14:+6.1f} pips | ${pnl_change:+7.1f}")
    
    print()
    print("KEY PATTERN:")
    print("-" * 80)
    print("All premature entries show the same pattern:")
    print("  1. Price moves AGAINST us initially (hits SL=1.2)")
    print("  2. Price then REVERSES and moves in predicted direction (wins with SL=1.4)")
    print("  3. Average adverse move: ~10-11 pips before reversal")
    print()
    print("This suggests: MODEL DIRECTION IS CORRECT, but ENTRY TIMING IS TOO EARLY")
    print()

# Compare good vs premature entries
good = df[df['category'] == 'GOOD']

if len(good) > 0 and len(premature) > 0:
    print("COMPARISON: PREMATURE vs GOOD ENTRIES")
    print("-" * 80)
    
    # Calculate average price movements at exit for SL=1.2
    def calc_avg_move(trades_df):
        moves = []
        for idx, trade in trades_df.iterrows():
            entry = trade['entry_price']
            exit_price = trade['exit_price_sl12']
            side = trade['side']
            
            if pd.notna(entry) and pd.notna(exit_price):
                if side == 'LONG':
                    move = (exit_price - entry) * 10000
                else:
                    move = (entry - exit_price) * 10000
                moves.append(move)
        return moves
    
    prem_moves = calc_avg_move(premature)
    good_moves = calc_avg_move(good)
    
    import numpy as np
    
    print(f"Average price movement (at SL=1.2 exit point):")
    print(f"  PREMATURE entries: {np.mean(prem_moves):.2f} pips (adverse)")
    print(f"  GOOD entries: {np.mean(good_moves):.2f} pips (favorable)")
    print(f"  Difference: {abs(np.mean(prem_moves) - np.mean(good_moves)):.2f} pips")
    print()

print("=" * 80)
print("RECOMMENDATIONS")
print("=" * 80)
print()
print("1. ADD ENTRY CONFIRMATION")
print("   Wait for price action to confirm the signal before entering")
print("   Options:")
print("   - Wait 1-2 bars and check if price is moving in predicted direction")
print("   - Require recent momentum to align with signal")
print("   - Wait for pullback completion before entry")
print()
print("2. ADD 'ENTRY QUALITY' FEATURE")
print("   Create a feature that measures immediate momentum:")
print("   - Recent 3-5 bar price momentum")
print("   - Momentum consistency (bars moving in same direction)")
print("   - Distance from recent support/resistance")
print()
print("3. IMPLEMENT TWO-STAGE ENTRY")
print("   Stage 1: Model predicts direction -> store as 'pending signal'")
print("   Stage 2: Next bar confirms direction -> enter trade")
print()
print("4. ANALYZE FEATURE DIFFERENCES")
print("   Need to log and compare features at entry time for:")
print("   - Premature entries (to avoid)")
print("   - Good entries (to replicate)")
print("   This requires adding feature logging to the strategy")
print()
print("=" * 80)

