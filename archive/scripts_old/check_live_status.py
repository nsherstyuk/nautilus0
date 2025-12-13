"""
Live trading status checker.
Checks if the system is running, warmed up, and ready to trade.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import re

def check_log_exists(log_dir):
    """Check if log directory and files exist."""
    log_path = Path(log_dir)
    
    if not log_path.exists():
        return False, "Log directory does not exist"
    
    required_files = ['live_trading.log', 'strategy.log']
    missing = []
    
    for file in required_files:
        if not (log_path / file).exists():
            missing.append(file)
    
    if missing:
        return False, f"Missing log files: {', '.join(missing)}"
    
    return True, "Log files found"


def get_last_log_time(log_file):
    """Get timestamp of last log entry."""
    if not Path(log_file).exists():
        return None
    
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            
        # Look for timestamp in last few lines
        for line in reversed(lines[-20:]):
            # Try to extract timestamp (format: 2025-11-30 12:13:52)
            match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
            if match:
                try:
                    return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
                except:
                    continue
        
        return None
    except Exception as e:
        return None


def check_system_running(log_dir):
    """Check if system is currently running."""
    live_log = Path(log_dir) / 'live_trading.log'
    
    last_time = get_last_log_time(live_log)
    
    if not last_time:
        return False, "Cannot determine last activity", None
    
    now = datetime.now()
    time_diff = now - last_time
    
    # If last log was within 2 minutes, system is likely running
    if time_diff < timedelta(minutes=2):
        return True, f"Active (last log {int(time_diff.total_seconds())}s ago)", last_time
    elif time_diff < timedelta(minutes=15):
        return "maybe", f"Possibly running (last log {int(time_diff.total_seconds()/60)}m ago)", last_time
    else:
        return False, f"Not running (last log {int(time_diff.total_seconds()/60)}m ago)", last_time


def check_warmup_status(log_dir):
    """Check if historical data warmup is complete."""
    strategy_log = Path(log_dir) / 'strategy.log'
    live_log = Path(log_dir) / 'live_trading.log'
    
    if not strategy_log.exists():
        return "unknown", "Strategy log not found", 0, 0
    
    try:
        # Check live_trading.log for backfill completion
        warmup_complete = False
        bars_received = 0
        bars_needed = 100  # Default
        
        if live_log.exists():
            with open(live_log, 'r', encoding='utf-8', errors='ignore') as f:
                live_lines = f.readlines()
            
            for line in live_lines:
                # Check for successful backfill
                if '[OK] Backfill successful' in line:
                    match = re.search(r'retrieved (\d+) bars', line)
                    if match:
                        bars_received = int(match.group(1))
                        warmup_complete = True
                
                # Check for bars fed to strategy
                if 'Successfully fed' in line and 'historical bars' in line:
                    match = re.search(r'fed (\d+) historical bars', line)
                    if match:
                        bars_received = int(match.group(1))
                        warmup_complete = True
                
                # Check for warmup completion message
                if 'Strategy warmup should be complete' in line:
                    warmup_complete = True
        
        # Also check strategy log
        with open(strategy_log, 'r', encoding='utf-8', errors='ignore') as f:
            strategy_lines = f.readlines()
        
        # Count received bars
        bar_count = 0
        for line in strategy_lines:
            # Check for bar reception
            if 'Received 15m bar' in line:
                bar_count += 1
            
            # Check for successful feature calculation
            if 'Feature calculation successful' in line or 'Prediction:' in line:
                warmup_complete = True
        
        # Use the higher bar count
        if bar_count > bars_received:
            bars_received = bar_count
        
        if warmup_complete:
            return "complete", "Warmup complete, strategy active", bars_received, bars_needed
        elif bars_received > 0:
            return "in_progress", f"Collecting bars ({bars_received}/{bars_needed})", bars_received, bars_needed
        else:
            return "not_started", "Warmup not started", 0, bars_needed
            
    except Exception as e:
        return "unknown", f"Error checking warmup: {e}", 0, 0


def check_trading_activity(log_dir):
    """Check for recent trading activity."""
    strategy_log = Path(log_dir) / 'strategy.log'
    orders_log = Path(log_dir) / 'orders.log'
    
    signals = 0
    orders = 0
    positions = 0
    
    # Check for signals
    if strategy_log.exists():
        try:
            with open(strategy_log, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                signals = content.count('signal detected')
                positions = content.count('entry at')
        except:
            pass
    
    # Check for orders
    if orders_log.exists():
        try:
            with open(orders_log, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                orders = content.count('Order submitted')
        except:
            pass
    
    return signals, orders, positions


def check_errors(log_dir):
    """Check for recent errors."""
    errors_log = Path(log_dir) / 'errors.log'
    
    if not errors_log.exists():
        return 0, []
    
    try:
        with open(errors_log, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        # Get last 5 errors
        error_lines = [line.strip() for line in lines if 'ERROR' in line]
        
        return len(error_lines), error_lines[-5:]
    except:
        return 0, []


def print_status():
    """Print comprehensive status report."""
    log_dir = 'logs/live_mtf'
    
    print("=" * 80)
    print("MTF LIVE TRADING - STATUS CHECK")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Check log files exist
    logs_ok, logs_msg = check_log_exists(log_dir)
    print(f"[1] LOG FILES: {'OK' if logs_ok else 'MISSING'}")
    print(f"    {logs_msg}")
    print()
    
    if not logs_ok:
        print("ERROR: Cannot proceed without log files.")
        print("Make sure live trading system is running: python live/run_live_mtf.py")
        return
    
    # Check if system is running
    is_running, run_msg, last_time = check_system_running(log_dir)
    status_symbol = "✓" if is_running == True else "?" if is_running == "maybe" else "✗"
    print(f"[2] SYSTEM STATUS: {status_symbol} {run_msg}")
    if last_time:
        print(f"    Last activity: {last_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Check warmup status
    warmup_status, warmup_msg, bars_received, bars_needed = check_warmup_status(log_dir)
    
    if warmup_status == "complete":
        warmup_symbol = "✓"
        warmup_color = "READY"
    elif warmup_status == "in_progress":
        warmup_symbol = "⟳"
        warmup_color = "IN PROGRESS"
        time_remaining = (bars_needed - bars_received) * 15  # 15 min per bar
        warmup_msg += f" (~{time_remaining} minutes remaining)"
    else:
        warmup_symbol = "✗"
        warmup_color = "NOT READY"
    
    print(f"[3] WARMUP STATUS: {warmup_symbol} {warmup_color}")
    print(f"    {warmup_msg}")
    if bars_needed > 0:
        progress = (bars_received / bars_needed) * 100
        bar_chart = "█" * int(progress / 5) + "░" * (20 - int(progress / 5))
        print(f"    Progress: [{bar_chart}] {progress:.1f}%")
    print()
    
    # Check trading activity
    signals, orders, positions = check_trading_activity(log_dir)
    print(f"[4] TRADING ACTIVITY:")
    print(f"    Signals detected: {signals}")
    print(f"    Orders submitted: {orders}")
    print(f"    Positions opened: {positions}")
    print()
    
    # Check for errors
    error_count, recent_errors = check_errors(log_dir)
    if error_count > 0:
        print(f"[5] ERRORS: ⚠ {error_count} error(s) found")
        if recent_errors:
            print(f"    Recent errors:")
            for error in recent_errors:
                print(f"      {error[:100]}")
    else:
        print(f"[5] ERRORS: ✓ No errors")
    print()
    
    # Overall status
    print("=" * 80)
    print("OVERALL STATUS:")
    
    if is_running and warmup_status == "complete":
        print("  ✓ System is RUNNING and READY TO TRADE")
        print("  ✓ Historical data warmup complete")
        print("  ✓ Strategy is actively monitoring for signals")
    elif is_running and warmup_status == "in_progress":
        print("  ⟳ System is RUNNING but WARMING UP")
        print("  ⟳ Collecting historical bars for strategy initialization")
        print(f"  ⟳ Need {bars_needed - bars_received} more bars (~{(bars_needed - bars_received) * 15} minutes)")
        print()
        print("  The system will start trading automatically once warmup is complete.")
    elif is_running:
        print("  ? System appears to be RUNNING")
        print("  ? Warmup status unclear - check logs for details")
    else:
        print("  ✗ System does NOT appear to be running")
        print("  ✗ Start with: python live/run_live_mtf.py")
    
    print("=" * 80)


def main():
    """Main entry point."""
    try:
        print_status()
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
