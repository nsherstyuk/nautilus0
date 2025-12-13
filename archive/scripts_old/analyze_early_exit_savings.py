"""
Analyze potential savings from early exit on early opposite signals.
Question: If we exit immediately when opposite signal appears in first 2 bars,
how much would we save compared to waiting for SL?
"""

import re
from collections import defaultdict
import pandas as pd

def parse_decisions_log_detailed(log_path):
    """Parse log with price tracking for savings estimation."""
    
    trades = []
    current_trade = None
    
    with open(log_path, 'r') as f:
        for line in f:
            if line.startswith('=') or line.startswith('Backtest') or line.startswith('Prediction') or line.startswith('ATR'):
                continue
            
            match = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[^\]]*)\] \[([^\]]+)\](.+)', line.strip())
            if not match:
                continue
                
            timestamp = match.group(1)
            event_type = match.group(2)
            details = match.group(3).strip()
            
            if event_type == 'ORDER':
                # New position opened
                price_match = re.search(r'entry at ([\d.]+)', details)
                sl_match = re.search(r'SL: ([\d.]+)', details)
                tp_match = re.search(r'TP: ([\d.]+)', details)
                conf_match = re.search(r'confidence=([\d.]+)', details)
                
                side = 'LONG' if 'Long entry' in details else 'SHORT'
                
                current_trade = {
                    'entry_time': timestamp,
                    'side': side,
                    'entry_price': float(price_match.group(1)) if price_match else None,
                    'sl_price': float(sl_match.group(1)) if sl_match else None,
                    'tp_price': float(tp_match.group(1)) if tp_match else None,
                    'entry_confidence': float(conf_match.group(1)) if conf_match else None,
                    'bars': 0,
                    'opposite_signals': [],
                    'bar_closes': [],
                    'partial_pnl': 0,
                    'exit_type': None,
                    'exit_pnl': None,
                    'exit_price': None
                }
                
            elif current_trade and event_type == 'BLOCKED':
                current_trade['bars'] += 1
                
                # Check for opposite signal
                is_long_blocked = 'LONG signal blocked' in details
                is_short_blocked = 'SHORT signal blocked' in details
                
                if (current_trade['side'] == 'SHORT' and is_long_blocked) or \
                   (current_trade['side'] == 'LONG' and is_short_blocked):
                    conf_match = re.search(r'conf=([\d.]+)', details)
                    conf = float(conf_match.group(1)) if conf_match else 0
                    if conf >= 0.55:
                        current_trade['opposite_signals'].append({
                            'bar': current_trade['bars'],
                            'confidence': conf
                        })
                        
            elif current_trade and event_type == 'PREDICTION':
                current_trade['bars'] += 1
                
            elif current_trade and event_type == 'EXIT PARTIAL':
                # Partial close
                pnl_match = re.search(r'pnl=\$([-\d.]+)', details)
                if pnl_match:
                    current_trade['partial_pnl'] += float(pnl_match.group(1))
                    
            elif current_trade and event_type.startswith('EXIT'):
                # Final exit
                pnl_match = re.search(r'pnl=\$([-\d.]+)', details)
                price_match = re.search(r'closed at ([\d.]+)', details)
                
                current_trade['exit_pnl'] = float(pnl_match.group(1)) if pnl_match else 0
                current_trade['exit_price'] = float(price_match.group(1)) if price_match else None
                current_trade['exit_type'] = 'SL' if 'SL' in event_type else ('TP' if 'TP' in event_type else 'OTHER')
                current_trade['total_pnl'] = current_trade['partial_pnl'] + current_trade['exit_pnl']
                
                trades.append(current_trade)
                current_trade = None
                
    return trades

def analyze_early_exit_savings(trades):
    """Analyze potential savings from early exit strategy."""
    
    print("=" * 80)
    print("EARLY EXIT ANALYSIS: Close on Early Opposite Signal (within 2 bars)")
    print("=" * 80)
    
    # Categorize trades
    early_opposite_trades = []  # Got opposite signal in first 2 bars
    no_early_opposite_trades = []  # No early opposite signal
    
    for t in trades:
        early_opp = [o for o in t['opposite_signals'] if o['bar'] <= 2]
        if early_opp:
            t['first_early_opposite_bar'] = early_opp[0]['bar']
            t['first_early_opposite_conf'] = early_opp[0]['confidence']
            early_opposite_trades.append(t)
        else:
            no_early_opposite_trades.append(t)
    
    print(f"\nTotal trades: {len(trades)}")
    print(f"Trades with early opposite signal (bars 1-2): {len(early_opposite_trades)} ({len(early_opposite_trades)/len(trades)*100:.1f}%)")
    print(f"Trades without early opposite signal: {len(no_early_opposite_trades)} ({len(no_early_opposite_trades)/len(trades)*100:.1f}%)")
    
    # Analyze early opposite trades
    print("\n" + "-" * 80)
    print("TRADES WITH EARLY OPPOSITE SIGNAL (potential early exits)")
    print("-" * 80)
    
    df_early = pd.DataFrame(early_opposite_trades)
    
    # By exit type
    print("\nBreakdown by actual exit type:")
    for exit_type in ['SL', 'TP', 'OTHER']:
        subset = df_early[df_early['exit_type'] == exit_type]
        if len(subset) > 0:
            print(f"\n  {exit_type}: {len(subset)} trades")
            print(f"    Total final exit PnL: ${subset['exit_pnl'].sum():.2f}")
            print(f"    Total partial PnL: ${subset['partial_pnl'].sum():.2f}")
            print(f"    Total combined PnL: ${subset['total_pnl'].sum():.2f}")
            print(f"    Avg combined PnL: ${subset['total_pnl'].mean():.2f}")
    
    # Focus on SL trades with early opposite
    sl_early = df_early[df_early['exit_type'] == 'SL']
    
    print("\n" + "-" * 80)
    print("POTENTIAL SAVINGS: SL trades with early opposite signal")
    print("-" * 80)
    
    if len(sl_early) > 0:
        print(f"\nSL trades that had early opposite signal: {len(sl_early)}")
        print(f"Total SL loss (final exit): ${sl_early['exit_pnl'].sum():.2f}")
        print(f"Partial profits before SL: ${sl_early['partial_pnl'].sum():.2f}")
        print(f"Net loss from these trades: ${sl_early['total_pnl'].sum():.2f}")
        
        # Estimate savings
        # If we exited at early opposite (bar 1-2), we'd lose less than full SL
        # Assuming price was closer to entry at bar 1-2 than at SL
        
        print("\n--- Estimated Savings Analysis ---")
        
        # Calculate avg SL distance in price terms
        sl_distances = []
        for _, row in sl_early.iterrows():
            if row['entry_price'] and row['sl_price']:
                dist = abs(row['entry_price'] - row['sl_price'])
                sl_distances.append(dist)
        
        avg_sl_distance = sum(sl_distances) / len(sl_distances) if sl_distances else 0
        print(f"\nAverage SL distance from entry: {avg_sl_distance:.5f} ({avg_sl_distance*100:.2f}%)")
        
        # Estimate that at bar 1-2, price is roughly 30-50% of the way to SL
        # This is an approximation - in reality, some would have already been profitable
        
        scenarios = [
            (0.0, "Exit at entry (breakeven)"),
            (0.25, "Exit at 25% of SL distance"),
            (0.50, "Exit at 50% of SL distance"),
            (0.75, "Exit at 75% of SL distance (conservative)"),
        ]
        
        total_sl_loss = sl_early['exit_pnl'].sum()
        avg_loss_per_trade = sl_early['exit_pnl'].mean()
        
        print(f"\nCurrent total SL loss: ${total_sl_loss:.2f} (avg ${avg_loss_per_trade:.2f}/trade)")
        print("\nEstimated outcomes if we exited early:")
        
        for pct, desc in scenarios:
            # If we exit at X% of SL distance, our loss is X% of actual SL loss
            estimated_loss = total_sl_loss * pct
            savings = total_sl_loss - estimated_loss
            print(f"\n  {desc}:")
            print(f"    Estimated loss: ${estimated_loss:.2f}")
            print(f"    Savings vs SL: ${abs(savings):.2f}")
            
        # But we also need to consider trades that would have been winners
        print("\n" + "-" * 80)
        print("OPPORTUNITY COST: What if early opposite was wrong?")
        print("-" * 80)
        
        # Trades with early opposite that ended profitably (partial or TP)
        profitable_early = df_early[df_early['total_pnl'] > 0]
        
        print(f"\nTrades with early opposite that were PROFITABLE: {len(profitable_early)}")
        if len(profitable_early) > 0:
            print(f"  Total profit from these: ${profitable_early['total_pnl'].sum():.2f}")
            print(f"  Avg profit: ${profitable_early['total_pnl'].mean():.2f}")
            print(f"\n  >> If we exited early on these, we'd LOSE this profit!")
            
        losing_early = df_early[df_early['total_pnl'] <= 0]
        print(f"\nTrades with early opposite that were LOSING: {len(losing_early)}")
        if len(losing_early) > 0:
            print(f"  Total loss from these: ${losing_early['total_pnl'].sum():.2f}")
            print(f"  Avg loss: ${losing_early['total_pnl'].mean():.2f}")
            
    # Net impact estimate
    print("\n" + "=" * 80)
    print("NET IMPACT ESTIMATE")
    print("=" * 80)
    
    if len(df_early) > 0:
        total_current_pnl = df_early['total_pnl'].sum()
        profitable_early = df_early[df_early['total_pnl'] > 0]
        losing_early = df_early[df_early['total_pnl'] <= 0]
        
        profit_at_risk = profitable_early['total_pnl'].sum() if len(profitable_early) > 0 else 0
        losses_to_reduce = losing_early['total_pnl'].sum() if len(losing_early) > 0 else 0
        
        print(f"\nCurrent PnL from early-opposite trades: ${total_current_pnl:.2f}")
        print(f"  Profitable trades: ${profit_at_risk:.2f} (at risk of losing)")
        print(f"  Losing trades: ${losses_to_reduce:.2f} (opportunity to reduce)")
        
        # If we exit at breakeven on all early opposite signals:
        # - We lose all the profit from profitable trades
        # - We avoid all the losses from losing trades
        
        net_if_breakeven = 0 - profit_at_risk + abs(losses_to_reduce)
        print(f"\nIf exit at breakeven on all early opposite:")
        print(f"  Net change: ${net_if_breakeven:.2f}")
        
        if net_if_breakeven > 0:
            print(f"  >> IMPROVEMENT: Would save ${net_if_breakeven:.2f}")
        else:
            print(f"  >> WORSE: Would lose ${abs(net_if_breakeven):.2f}")
            
        # What if we only exit early when confidence is very high?
        print("\n" + "-" * 80)
        print("FILTERED APPROACH: Exit early only on HIGH confidence opposite (>0.65)")
        print("-" * 80)
        
        high_conf_early = [t for t in early_opposite_trades if t['first_early_opposite_conf'] >= 0.65]
        
        if high_conf_early:
            df_high = pd.DataFrame(high_conf_early)
            print(f"\nHigh-confidence early opposite trades: {len(df_high)}")
            
            profitable_high = df_high[df_high['total_pnl'] > 0]
            losing_high = df_high[df_high['total_pnl'] <= 0]
            
            profit_risk_high = profitable_high['total_pnl'].sum() if len(profitable_high) > 0 else 0
            loss_reduce_high = losing_high['total_pnl'].sum() if len(losing_high) > 0 else 0
            
            print(f"  Profitable: {len(profitable_high)} trades, ${profit_risk_high:.2f}")
            print(f"  Losing: {len(losing_high)} trades, ${loss_reduce_high:.2f}")
            
            net_high_conf = 0 - profit_risk_high + abs(loss_reduce_high)
            print(f"\n  Net if exit early on high-conf only: ${net_high_conf:.2f}")
            
            if net_high_conf > 0:
                print(f"  >> IMPROVEMENT: Would save ${net_high_conf:.2f}")
            else:
                print(f"  >> WORSE: Would lose ${abs(net_high_conf):.2f}")
    
    # Compare to trades without early opposite
    print("\n" + "=" * 80)
    print("BASELINE: Trades WITHOUT early opposite signal")
    print("=" * 80)
    
    df_no_early = pd.DataFrame(no_early_opposite_trades)
    if len(df_no_early) > 0:
        print(f"\nTrades without early opposite: {len(df_no_early)}")
        print(f"Total PnL: ${df_no_early['total_pnl'].sum():.2f}")
        print(f"Avg PnL: ${df_no_early['total_pnl'].mean():.2f}")
        
        sl_no_early = df_no_early[df_no_early['exit_type'] == 'SL']
        print(f"\nSL exits: {len(sl_no_early)} ({len(sl_no_early)/len(df_no_early)*100:.1f}%)")
        
        profitable_no_early = df_no_early[df_no_early['total_pnl'] > 0]
        print(f"Profitable trades: {len(profitable_no_early)} ({len(profitable_no_early)/len(df_no_early)*100:.1f}%)")

if __name__ == "__main__":
    log_path = "backtest_results/MTF_ML_20251202_215556/strategy_decisions.log"
    
    print("Parsing strategy decisions log with detailed tracking...")
    trades = parse_decisions_log_detailed(log_path)
    print(f"Parsed {len(trades)} complete trades")
    
    analyze_early_exit_savings(trades)
