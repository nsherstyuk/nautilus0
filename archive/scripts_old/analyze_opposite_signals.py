"""
Analyze if opposite signal predictions correlate with subsequent stop losses.
Question: Can we use opposite predictions as early exit indicators?
"""

import re
from datetime import datetime
from collections import defaultdict
import pandas as pd

def parse_decisions_log(log_path):
    """Parse the strategy decisions log file."""
    
    events = []
    
    with open(log_path, 'r') as f:
        for line in f:
            # Skip header lines
            if line.startswith('=') or line.startswith('Backtest') or line.startswith('Prediction') or line.startswith('ATR'):
                continue
            
            # Parse timestamp
            match = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[^\]]*)\] \[([^\]]+)\](.+)', line.strip())
            if match:
                timestamp = match.group(1)
                event_type = match.group(2)
                details = match.group(3).strip()
                
                events.append({
                    'timestamp': timestamp,
                    'event_type': event_type,
                    'details': details
                })
    
    return events

def analyze_opposite_signals(log_path):
    """Analyze correlation between opposite predictions and stop losses."""
    
    events = parse_decisions_log(log_path)
    
    # Track state
    current_position = None  # {'side': 'LONG'/'SHORT', 'entry_time': str, 'entry_price': float}
    opposite_signals_before_exit = []  # List of (position_side, exit_type, had_opposite_signal, bars_to_exit)
    
    # Track opposite signals while in position
    opposite_signal_detected = False
    opposite_signal_confidence = 0
    bars_since_entry = 0
    bars_to_opposite = None
    
    for event in events:
        event_type = event['event_type']
        details = event['details']
        
        if event_type == 'ORDER':
            # Position opened
            if 'Long entry' in details:
                current_position = {'side': 'LONG', 'entry_time': event['timestamp']}
            elif 'Short entry' in details:
                current_position = {'side': 'SHORT', 'entry_time': event['timestamp']}
            opposite_signal_detected = False
            opposite_signal_confidence = 0
            bars_since_entry = 0
            bars_to_opposite = None
            
        elif event_type == 'PREDICTION' and current_position:
            bars_since_entry += 1
            
            # Parse prediction
            pred_match = re.search(r'prediction=(\d), confidence=([\d.]+)', details)
            if pred_match:
                prediction = int(pred_match.group(1))
                confidence = float(pred_match.group(2))
                
                # Check for opposite signal
                is_opposite = (current_position['side'] == 'LONG' and prediction == 0) or \
                             (current_position['side'] == 'SHORT' and prediction == 1)
                
                if is_opposite and confidence >= 0.55:  # Only count high-confidence opposite signals
                    if not opposite_signal_detected:
                        opposite_signal_detected = True
                        opposite_signal_confidence = confidence
                        bars_to_opposite = bars_since_entry
                        
        elif event_type == 'BLOCKED' and current_position:
            bars_since_entry += 1
            
            # Parse blocked signal - this also contains prediction info
            if 'LONG signal blocked' in details and current_position['side'] == 'SHORT':
                # Opposite signal while SHORT
                conf_match = re.search(r'conf=([\d.]+)', details)
                if conf_match:
                    confidence = float(conf_match.group(1))
                    if confidence >= 0.55 and not opposite_signal_detected:
                        opposite_signal_detected = True
                        opposite_signal_confidence = confidence
                        bars_to_opposite = bars_since_entry
                        
            elif 'SHORT signal blocked' in details and current_position['side'] == 'LONG':
                # Opposite signal while LONG  
                conf_match = re.search(r'conf=([\d.]+)', details)
                if conf_match:
                    confidence = float(conf_match.group(1))
                    if confidence >= 0.55 and not opposite_signal_detected:
                        opposite_signal_detected = True
                        opposite_signal_confidence = confidence
                        bars_to_opposite = bars_since_entry
        
        # Also check PREDICTION events for opposite signals (when no position blocks)
        elif event_type == 'FILTERED' and current_position:
            bars_since_entry += 1
            # Filtered but might still be opposite
            # Format: [FILTERED] Confidence too low: 0.513 < 0.55 (prediction=1, time=...)
            pred_match = re.search(r'prediction=(\d)', details)
            if pred_match:
                prediction = int(pred_match.group(1))
                is_opposite = (current_position['side'] == 'LONG' and prediction == 0) or \
                             (current_position['side'] == 'SHORT' and prediction == 1)
                # Note: Filtered signals are low confidence, so we don't count them
                        
        elif event_type.startswith('EXIT') and current_position:
            # Position closed
            exit_type = 'SL' if 'SL' in event_type else ('TP' if 'TP' in event_type else 'OTHER')
            
            # Parse PnL
            pnl_match = re.search(r'pnl=\$([-\d.]+)', details)
            pnl = float(pnl_match.group(1)) if pnl_match else 0
            
            # Parse partial
            partial = 'partial_closed=True' in details
            
            opposite_signals_before_exit.append({
                'position_side': current_position['side'],
                'exit_type': exit_type,
                'had_opposite_signal': opposite_signal_detected,
                'opposite_confidence': opposite_signal_confidence if opposite_signal_detected else None,
                'bars_to_exit': bars_since_entry,
                'bars_to_opposite': bars_to_opposite,
                'pnl': pnl,
                'partial_closed': partial
            })
            
            current_position = None
            opposite_signal_detected = False
            
    return opposite_signals_before_exit

def print_analysis(results):
    """Print analysis results."""
    
    df = pd.DataFrame(results)
    
    print("=" * 80)
    print("OPPOSITE SIGNAL ANALYSIS")
    print("=" * 80)
    print(f"\nTotal trades analyzed: {len(df)}")
    
    # Separate partial vs full trades
    df_partial = df[df['partial_closed']]
    df_full = df[~df['partial_closed']]
    print(f"Full trades (no partial close): {len(df_full)}")
    print(f"Partial close trades: {len(df_partial)}")
    
    # IMPORTANT: Analyze partial close trades
    print("\n" + "-" * 80)
    print("PARTIAL CLOSE ANALYSIS (Where most profits come from)")
    print("-" * 80)
    
    if len(df_partial) > 0:
        total_partial_pnl = df_partial['pnl'].sum()
        print(f"\nTotal PnL from partial closes: ${total_partial_pnl:.2f}")
        
        partial_with_opp = df_partial[df_partial['had_opposite_signal']]
        partial_without_opp = df_partial[~df_partial['had_opposite_signal']]
        
        print(f"\nPartial closes WITH opposite signal before: {len(partial_with_opp)}")
        if len(partial_with_opp) > 0:
            print(f"  Total PnL: ${partial_with_opp['pnl'].sum():.2f}")
            print(f"  Avg PnL: ${partial_with_opp['pnl'].mean():.2f}")
            
        print(f"\nPartial closes WITHOUT opposite signal: {len(partial_without_opp)}")
        if len(partial_without_opp) > 0:
            print(f"  Total PnL: ${partial_without_opp['pnl'].sum():.2f}")
            print(f"  Avg PnL: ${partial_without_opp['pnl'].mean():.2f}")
    
    print("\n" + "-" * 80)
    print("OVERALL: How often do opposite signals precede each exit type?")
    print("-" * 80)
    
    for exit_type in ['SL', 'TP', 'OTHER']:
        subset = df_full[df_full['exit_type'] == exit_type]
        if len(subset) > 0:
            with_opposite = subset['had_opposite_signal'].sum()
            pct = with_opposite / len(subset) * 100
            avg_pnl = subset['pnl'].mean()
            print(f"\n{exit_type} exits ({len(subset)} trades, avg PnL: ${avg_pnl:.2f}):")
            print(f"  - Had opposite signal before exit: {with_opposite} ({pct:.1f}%)")
            print(f"  - No opposite signal before exit: {len(subset) - with_opposite} ({100-pct:.1f}%)")
    
    print("\n" + "-" * 80)
    print("KEY QUESTION: Does an opposite signal predict SL vs TP?")
    print("-" * 80)
    
    # When we get an opposite signal, what happens?
    df_with_opposite = df_full[df_full['had_opposite_signal']]
    df_without_opposite = df_full[~df_full['had_opposite_signal']]
    
    print(f"\nTrades WITH opposite signal ({len(df_with_opposite)} trades):")
    if len(df_with_opposite) > 0:
        sl_pct = (df_with_opposite['exit_type'] == 'SL').mean() * 100
        tp_pct = (df_with_opposite['exit_type'] == 'TP').mean() * 100
        avg_pnl = df_with_opposite['pnl'].mean()
        print(f"  - Ended in SL: {sl_pct:.1f}%")
        print(f"  - Ended in TP: {tp_pct:.1f}%")
        print(f"  - Average PnL: ${avg_pnl:.2f}")
        
        # Average bars to exit after opposite signal
        with_bars = df_with_opposite[df_with_opposite['bars_to_opposite'].notna()]
        if len(with_bars) > 0:
            avg_bars_remaining = (with_bars['bars_to_exit'] - with_bars['bars_to_opposite']).mean()
            print(f"  - Avg bars from opposite signal to exit: {avg_bars_remaining:.1f}")
    
    print(f"\nTrades WITHOUT opposite signal ({len(df_without_opposite)} trades):")
    if len(df_without_opposite) > 0:
        sl_pct = (df_without_opposite['exit_type'] == 'SL').mean() * 100
        tp_pct = (df_without_opposite['exit_type'] == 'TP').mean() * 100
        avg_pnl = df_without_opposite['pnl'].mean()
        print(f"  - Ended in SL: {sl_pct:.1f}%")
        print(f"  - Ended in TP: {tp_pct:.1f}%")
        print(f"  - Average PnL: ${avg_pnl:.2f}")
    
    print("\n" + "-" * 80)
    print("POTENTIAL VALUE: If we closed on opposite signal...")
    print("-" * 80)
    
    # What if we exited on opposite signal instead of waiting for SL?
    # Trades that had opposite signal and eventually hit SL
    sl_with_opposite = df_full[(df_full['exit_type'] == 'SL') & (df_full['had_opposite_signal'])]
    if len(sl_with_opposite) > 0:
        total_sl_loss = sl_with_opposite['pnl'].sum()
        print(f"\nTrades that hit SL after getting opposite signal: {len(sl_with_opposite)}")
        print(f"  Total loss from these trades: ${total_sl_loss:.2f}")
        print(f"  Average loss per trade: ${sl_with_opposite['pnl'].mean():.2f}")
        avg_bars_wasted = (sl_with_opposite['bars_to_exit'] - sl_with_opposite['bars_to_opposite']).mean()
        print(f"  Avg bars held after opposite signal: {avg_bars_wasted:.1f}")
        print(f"\n  >> These losses could potentially be reduced by exiting early on opposite signal")
    
    # But what about trades that recovered?
    tp_with_opposite = df_full[(df_full['exit_type'] == 'TP') & (df_full['had_opposite_signal'])]
    if len(tp_with_opposite) > 0:
        total_tp_profit = tp_with_opposite['pnl'].sum()
        print(f"\nTrades that hit TP despite opposite signal: {len(tp_with_opposite)}")
        print(f"  Total profit from these trades: ${total_tp_profit:.2f}")
        print(f"  Average profit per trade: ${tp_with_opposite['pnl'].mean():.2f}")
        print(f"\n  >> These profits would be lost if we exited on opposite signal")
    
    print("\n" + "-" * 80)
    print("BY POSITION SIDE")
    print("-" * 80)
    
    for side in ['LONG', 'SHORT']:
        print(f"\n{side} positions:")
        side_df = df_full[df_full['position_side'] == side]
        if len(side_df) > 0:
            with_opp = side_df[side_df['had_opposite_signal']]
            without_opp = side_df[~side_df['had_opposite_signal']]
            
            if len(with_opp) > 0:
                sl_rate_with = (with_opp['exit_type'] == 'SL').mean() * 100
                print(f"  With opposite signal ({len(with_opp)} trades): {sl_rate_with:.1f}% hit SL")
            if len(without_opp) > 0:
                sl_rate_without = (without_opp['exit_type'] == 'SL').mean() * 100
                print(f"  Without opposite signal ({len(without_opp)} trades): {sl_rate_without:.1f}% hit SL")
    
    print("\n" + "=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    
    if len(df_with_opposite) > 0 and len(df_without_opposite) > 0:
        sl_rate_with = (df_with_opposite['exit_type'] == 'SL').mean() * 100
        sl_rate_without = (df_without_opposite['exit_type'] == 'SL').mean() * 100
        
        if sl_rate_with > sl_rate_without + 10:
            print(f"\nSTRONG CORRELATION: Opposite signals predict SL")
            print(f"SL rate with opposite signal: {sl_rate_with:.1f}%")
            print(f"SL rate without: {sl_rate_without:.1f}%")
            print(f"Difference: +{sl_rate_with - sl_rate_without:.1f}%")
            print("\nRECOMMENDATION: Consider using opposite signals as early exit trigger")
        elif sl_rate_with > sl_rate_without:
            print(f"\nMODERATE CORRELATION: Some predictive value")
            print(f"SL rate with opposite signal: {sl_rate_with:.1f}%")
            print(f"SL rate without: {sl_rate_without:.1f}%")
            print(f"Difference: +{sl_rate_with - sl_rate_without:.1f}%")
            print("\nRECOMMENDATION: Test with tighter filters (higher confidence threshold)")
        else:
            print(f"\nNO CORRELATION: Opposite signals do not reliably predict SL")
            print(f"SL rate with opposite signal: {sl_rate_with:.1f}%")
            print(f"SL rate without: {sl_rate_without:.1f}%")
            print("\nRECOMMENDATION: Keep current exit strategy")

def analyze_early_exit_potential(log_path):
    """Estimate PnL if we exited on opposite signal instead of waiting for SL."""
    
    events = parse_decisions_log(log_path)
    
    # Track for each trade: price at opposite signal vs price at exit
    trades_to_analyze = []
    
    current_position = None
    entry_price = None
    opposite_signal_price = None
    opposite_signal_bar = None
    bars_since_entry = 0
    last_price = None
    
    for event in events:
        event_type = event['event_type']
        details = event['details']
        
        if event_type == 'ORDER':
            # Extract entry price
            price_match = re.search(r'entry at ([\d.]+)', details)
            if price_match:
                entry_price = float(price_match.group(1))
            
            if 'Long entry' in details:
                current_position = 'LONG'
            elif 'Short entry' in details:
                current_position = 'SHORT'
                
            opposite_signal_price = None
            opposite_signal_bar = None
            bars_since_entry = 0
            
        elif event_type == 'PREDICTION' and current_position:
            bars_since_entry += 1
            
            # Note: We don't have bar close price in PREDICTION events
            # We'll use the blocked signal info instead
            
        elif event_type == 'BLOCKED' and current_position:
            bars_since_entry += 1
            
            # Check for opposite signal
            is_opposite = ('LONG signal blocked' in details and current_position == 'SHORT') or \
                         ('SHORT signal blocked' in details and current_position == 'LONG')
            
            if is_opposite:
                conf_match = re.search(r'conf=([\d.]+)', details)
                if conf_match and float(conf_match.group(1)) >= 0.55:
                    if opposite_signal_bar is None:
                        opposite_signal_bar = bars_since_entry
                        
        elif event_type.startswith('EXIT') and current_position:
            # Parse exit details
            pnl_match = re.search(r'pnl=\$([-\d.]+)', details)
            exit_price_match = re.search(r'closed at ([\d.]+)', details)
            
            pnl = float(pnl_match.group(1)) if pnl_match else 0
            exit_price = float(exit_price_match.group(1)) if exit_price_match else None
            
            exit_type = 'SL' if 'SL' in event_type else ('TP' if 'TP' in event_type else 'PARTIAL')
            
            trades_to_analyze.append({
                'side': current_position,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl': pnl,
                'exit_type': exit_type,
                'had_opposite': opposite_signal_bar is not None,
                'bars_to_opposite': opposite_signal_bar,
                'bars_to_exit': bars_since_entry
            })
            
            current_position = None
    
    return trades_to_analyze

if __name__ == "__main__":
    log_path = "backtest_results/MTF_ML_20251202_215556/strategy_decisions.log"
    
    print("Analyzing strategy decisions log...")
    results = analyze_opposite_signals(log_path)
    print_analysis(results)
    
    print("\n" + "=" * 80)
    print("TIMING ANALYSIS: When do opposite signals occur?")
    print("=" * 80)
    
    df = pd.DataFrame(results)
    df_with_opp = df[df['had_opposite_signal'] & df['bars_to_opposite'].notna()]
    
    if len(df_with_opp) > 0:
        print(f"\nTrades with opposite signal timing data: {len(df_with_opp)}")
        
        # Distribution of bars to opposite signal
        bars_to_opp = df_with_opp['bars_to_opposite']
        print(f"\nBars until opposite signal appears:")
        print(f"  Min: {bars_to_opp.min():.0f}")
        print(f"  Max: {bars_to_opp.max():.0f}")
        print(f"  Mean: {bars_to_opp.mean():.1f}")
        print(f"  Median: {bars_to_opp.median():.1f}")
        
        # Distribution of remaining bars after opposite
        remaining = df_with_opp['bars_to_exit'] - df_with_opp['bars_to_opposite']
        print(f"\nBars from opposite signal to exit:")
        print(f"  Min: {remaining.min():.0f}")
        print(f"  Max: {remaining.max():.0f}")
        print(f"  Mean: {remaining.mean():.1f}")
        print(f"  Median: {remaining.median():.1f}")
        
        # How many opposite signals come early (within first 2 bars)?
        early_opposite = (bars_to_opp <= 2).sum()
        print(f"\nOpposite signals in first 2 bars: {early_opposite} ({early_opposite/len(df_with_opp)*100:.1f}%)")
        print("  >> Early opposite might indicate bad entry rather than exit signal")
        
        late_opposite = (bars_to_opp > 2).sum()
        print(f"Opposite signals after 2+ bars: {late_opposite} ({late_opposite/len(df_with_opp)*100:.1f}%)")
        print("  >> These are more likely genuine reversal signals")
        
        # Focus on late opposite signals only
        late_df = df_with_opp[df_with_opp['bars_to_opposite'] > 2]
        if len(late_df) > 0:
            print(f"\nLATE OPPOSITE SIGNALS (>2 bars in):")
            sl_count = (late_df['exit_type'] == 'SL').sum()
            print(f"  Trades: {len(late_df)}")
            print(f"  Ended in SL: {sl_count} ({sl_count/len(late_df)*100:.1f}%)")
            print(f"  Avg PnL: ${late_df['pnl'].mean():.2f}")
            print(f"  Total PnL: ${late_df['pnl'].sum():.2f}")
            avg_remaining = (late_df['bars_to_exit'] - late_df['bars_to_opposite']).mean()
            print(f"  Avg bars held after opposite signal: {avg_remaining:.1f}")
            
            # Potential savings
            sl_trades = late_df[late_df['exit_type'] == 'SL']
            if len(sl_trades) > 0:
                print(f"\n  POTENTIAL SAVINGS (if exited immediately on late opposite signal):")
                print(f"    SL trades with late opposite: {len(sl_trades)}")
                print(f"    Total SL losses: ${sl_trades['pnl'].sum():.2f}")
                print(f"    Could potentially save a portion of these losses by exiting early")
