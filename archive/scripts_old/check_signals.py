"""
Signal monitoring utility.
Shows all ML predictions, signals generated, and why they were filtered.
"""
import sys
from pathlib import Path
from datetime import datetime
import re

def parse_strategy_log(log_file):
    """Parse strategy log for signals and filters."""
    if not Path(log_file).exists():
        return {
            'predictions': [],
            'signals': [],
            'filtered': [],
            'positions': []
        }
    
    results = {
        'predictions': [],
        'signals': [],
        'filtered': [],
        'positions': []
    }
    
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        for line in lines:
            timestamp = extract_timestamp(line)
            
            # ML Predictions
            if 'Prediction:' in line:
                # Extract prediction details
                match = re.search(r'Prediction:\s*(LONG|SHORT|NEUTRAL),\s*confidence=([\d.]+)', line)
                if match:
                    side = match.group(1)
                    confidence = float(match.group(2))
                    results['predictions'].append({
                        'time': timestamp,
                        'side': side,
                        'confidence': confidence,
                        'raw': line.strip()
                    })
            
            # Signal generation
            if 'signal detected' in line.lower():
                match = re.search(r'(Long|Short|LONG|SHORT)\s+signal detected', line, re.IGNORECASE)
                if match:
                    side = match.group(1).upper()
                    # Extract confidence if present
                    conf_match = re.search(r'confidence[=:]\s*([\d.]+)', line)
                    confidence = float(conf_match.group(1)) if conf_match else None
                    results['signals'].append({
                        'time': timestamp,
                        'side': side,
                        'confidence': confidence,
                        'raw': line.strip()
                    })
            
            # Filtered signals
            if any(keyword in line for keyword in [
                'Skipping signal',
                'Signal filtered',
                'Position limit reached',
                'Cooldown active',
                'ATR filter',
                'Outside trading session',
                'excluded',
                'Skip signal'
            ]):
                results['filtered'].append({
                    'time': timestamp,
                    'reason': extract_filter_reason(line),
                    'raw': line.strip()
                })
            
            # Position opened
            if 'entry at' in line.lower() and ('long' in line.lower() or 'short' in line.lower()):
                match = re.search(r'(Long|Short|LONG|SHORT)\s+entry at\s+([\d.]+)', line, re.IGNORECASE)
                if match:
                    side = match.group(1).upper()
                    price = float(match.group(2))
                    results['positions'].append({
                        'time': timestamp,
                        'side': side,
                        'price': price,
                        'raw': line.strip()
                    })
        
        return results
        
    except Exception as e:
        print(f"Error parsing log: {e}")
        return results


def extract_timestamp(line):
    """Extract timestamp from log line."""
    match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
    if match:
        return match.group(1)
    return "Unknown"


def extract_filter_reason(line):
    """Extract the reason why a signal was filtered."""
    if 'Position limit' in line:
        return "Position limit reached"
    elif 'Cooldown' in line:
        return "Cooldown active"
    elif 'ATR' in line:
        return "ATR filter"
    elif 'trading session' in line or 'excluded' in line:
        return "Outside trading hours"
    elif 'Skip signal' in line or 'Skipping' in line:
        return "Signal skipped"
    else:
        return "Other filter"


def print_signal_report(log_dir='logs/live_mtf'):
    """Print comprehensive signal report."""
    strategy_log = Path(log_dir) / 'strategy.log'
    
    print("=" * 80)
    print("MTF SIGNAL MONITORING REPORT")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    if not strategy_log.exists():
        print("ERROR: Strategy log not found!")
        print(f"Expected location: {strategy_log}")
        print("Make sure live trading system is running.")
        return
    
    # Parse log
    results = parse_strategy_log(strategy_log)
    
    # Summary
    print("[SUMMARY]")
    print(f"  ML Predictions: {len(results['predictions'])}")
    print(f"  Signals Generated: {len(results['signals'])}")
    print(f"  Signals Filtered: {len(results['filtered'])}")
    print(f"  Positions Opened: {len(results['positions'])}")
    print()
    
    # ML Predictions
    if results['predictions']:
        print("[ML PREDICTIONS] (Last 10)")
        print("-" * 80)
        for pred in results['predictions'][-10:]:
            conf_str = f"{pred['confidence']:.3f}" if pred['confidence'] else "N/A"
            print(f"  {pred['time']} | {pred['side']:8} | Confidence: {conf_str}")
        print()
    else:
        print("[ML PREDICTIONS]")
        print("  No predictions yet (strategy may still be warming up)")
        print()
    
    # Signals Generated
    if results['signals']:
        print("[SIGNALS GENERATED] (Last 10)")
        print("-" * 80)
        for signal in results['signals'][-10:]:
            conf_str = f"{signal['confidence']:.3f}" if signal['confidence'] else "N/A"
            print(f"  {signal['time']} | {signal['side']:8} | Confidence: {conf_str}")
        print()
    else:
        print("[SIGNALS GENERATED]")
        print("  No signals generated yet")
        print()
    
    # Filtered Signals
    if results['filtered']:
        print("[FILTERED SIGNALS] (Last 10)")
        print("-" * 80)
        for filtered in results['filtered'][-10:]:
            print(f"  {filtered['time']} | Reason: {filtered['reason']}")
            # Show partial raw line for context
            if len(filtered['raw']) > 100:
                print(f"    {filtered['raw'][:100]}...")
            else:
                print(f"    {filtered['raw']}")
        print()
        
        # Filter reason breakdown
        print("[FILTER BREAKDOWN]")
        reasons = {}
        for filtered in results['filtered']:
            reason = filtered['reason']
            reasons[reason] = reasons.get(reason, 0) + 1
        
        for reason, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
            print(f"  {reason}: {count}")
        print()
    else:
        print("[FILTERED SIGNALS]")
        print("  No signals have been filtered")
        print()
    
    # Positions Opened
    if results['positions']:
        print("[POSITIONS OPENED] (Last 5)")
        print("-" * 80)
        for pos in results['positions'][-5:]:
            print(f"  {pos['time']} | {pos['side']:8} @ {pos['price']:.5f}")
        print()
    else:
        print("[POSITIONS OPENED]")
        print("  No positions opened yet")
        print()
    
    # Analysis
    print("=" * 80)
    print("[ANALYSIS]")
    
    if len(results['predictions']) == 0:
        print("  Status: Strategy is still warming up or no bars received yet")
        print("  Action: Wait for strategy to receive bars and make predictions")
    elif len(results['signals']) == 0:
        print("  Status: Predictions made but no signals above threshold")
        print("  Action: ML model confidence not high enough (threshold: 0.55)")
    elif len(results['filtered']) > 0:
        print(f"  Status: {len(results['signals'])} signals generated, {len(results['filtered'])} filtered")
        print("  Action: Review filter reasons above")
    elif len(results['positions']) == 0:
        print("  Status: Signals generated but no positions opened")
        print("  Action: Check order logs for execution issues")
    else:
        print(f"  Status: System working normally - {len(results['positions'])} positions opened")
    
    print("=" * 80)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor ML signals and filters")
    parser.add_argument("--log-dir", default="logs/live_mtf",
                       help="Log directory (default: logs/live_mtf)")
    parser.add_argument("--watch", action="store_true",
                       help="Continuously watch for new signals (refresh every 30s)")
    
    args = parser.parse_args()
    
    if args.watch:
        import time
        import os
        print("Watching for signals... (Press Ctrl+C to exit)")
        print()
        try:
            while True:
                os.system('cls' if os.name == 'nt' else 'clear')
                print_signal_report(args.log_dir)
                time.sleep(30)
        except KeyboardInterrupt:
            print("\nStopped watching.")
    else:
        print_signal_report(args.log_dir)


if __name__ == "__main__":
    main()
