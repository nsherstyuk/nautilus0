"""
Live Trading Status Monitor
Quick dashboard to see current status of live trading system
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import re

def get_file_age(filepath):
    """Get how long ago file was modified."""
    if not filepath.exists():
        return "N/A"
    mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
    age = datetime.now() - mtime
    if age.total_seconds() < 60:
        return f"{int(age.total_seconds())}s ago"
    elif age.total_seconds() < 3600:
        return f"{int(age.total_seconds() / 60)}m ago"
    else:
        return f"{int(age.total_seconds() / 3600)}h ago"

def check_process():
    """Check if Python process is running."""
    try:
        import subprocess
        result = subprocess.run(
            ['powershell', '-Command', 'Get-Process python -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count'],
            capture_output=True,
            text=True,
            timeout=5
        )
        count = int(result.stdout.strip() or 0)
        return count > 0, count
    except:
        return None, 0

def get_last_log_lines(filepath, pattern, count=5):
    """Get last N lines matching pattern."""
    if not filepath.exists():
        return []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        matches = [line.strip() for line in lines if pattern in line]
        return matches[-count:]
    except:
        return []

def parse_timestamp(line):
    """Extract timestamp from log line."""
    match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
        except:
            pass
    return None

def main():
    log_dir = Path("logs/live_mtf")
    strategy_log = log_dir / "strategy.log"
    live_log = log_dir / "live_trading.log"
    orders_log = log_dir / "orders.log"
    trades_log = log_dir / "trades.log"
    errors_log = log_dir / "errors.log"
    
    print("="*80)
    print(" LIVE TRADING STATUS MONITOR")
    print("="*80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Process Status
    print("PROCESS STATUS:")
    print("-" * 80)
    running, count = check_process()
    if running:
        print(f"  Status: RUNNING ({count} Python process(es))")
    elif running is None:
        print(f"  Status: UNKNOWN (could not check)")
    else:
        print(f"  Status: NOT RUNNING")
    print()
    
    # Log Files
    print("LOG FILES:")
    print("-" * 80)
    for name, path in [
        ("Strategy", strategy_log),
        ("Live Trading", live_log),
        ("Orders", orders_log),
        ("Trades", trades_log),
        ("Errors", errors_log),
    ]:
        if path.exists():
            size = path.stat().st_size
            age = get_file_age(path)
            print(f"  {name:15} {size:>10,} bytes  (updated {age})")
        else:
            print(f"  {name:15} NOT FOUND")
    print()
    
    # Last Bars Received
    print("RECENT BAR ACTIVITY:")
    print("-" * 80)
    bar_lines = get_last_log_lines(strategy_log, "on_bar called", 5)
    if bar_lines:
        for line in bar_lines:
            ts = parse_timestamp(line)
            # Extract close price
            close_match = re.search(r'close=([\d.]+)', line)
            warmup_match = re.search(r'warmup=(True|False)', line)
            close = close_match.group(1) if close_match else "?"
            warmup = warmup_match.group(1) if warmup_match else "?"
            
            if ts:
                age = datetime.now() - ts
                age_str = f"{int(age.total_seconds())}s ago" if age.total_seconds() < 60 else f"{int(age.total_seconds()/60)}m ago"
                print(f"  {ts.strftime('%H:%M:%S')} ({age_str:>8}) - close={close}, warmup={warmup}")
            else:
                print(f"  {line[:80]}")
        
        # Check if bars are stale
        last_line = bar_lines[-1]
        last_ts = parse_timestamp(last_line)
        if last_ts:
            age = datetime.now() - last_ts
            if age.total_seconds() > 900:  # 15 minutes
                print(f"\n  WARNING: Last bar was {int(age.total_seconds()/60)} minutes ago!")
                print(f"  Expected: bars every 15 minutes")
    else:
        print("  No bars received yet")
    print()
    
    # Warmup Status
    print("WARMUP STATUS:")
    print("-" * 80)
    warmup_lines = get_last_log_lines(strategy_log, "WARMUP COMPLETE", 1)
    if warmup_lines:
        line = warmup_lines[0]
        ts = parse_timestamp(line)
        if ts:
            age = datetime.now() - ts
            print(f"  Completed: {ts.strftime('%H:%M:%S')} ({int(age.total_seconds()/60)}m ago)")
        else:
            print(f"  Completed: Yes")
    else:
        progress_lines = get_last_log_lines(strategy_log, "Waiting for warmup", 1)
        if progress_lines:
            print(f"  Status: In Progress")
            print(f"  {progress_lines[0][:80]}")
        else:
            print(f"  Status: Unknown")
    print()
    
    # Predictions
    print("RECENT PREDICTIONS:")
    print("-" * 80)
    pred_lines = get_last_log_lines(strategy_log, "prediction=", 3)
    if pred_lines:
        for line in pred_lines:
            ts = parse_timestamp(line)
            # Extract prediction details
            pred_match = re.search(r'prediction=(\d+)', line)
            conf_match = re.search(r'confidence=([\d.]+)', line)
            
            if ts and pred_match:
                age = datetime.now() - ts
                age_str = f"{int(age.total_seconds())}s ago" if age.total_seconds() < 60 else f"{int(age.total_seconds()/60)}m ago"
                pred = "LONG" if pred_match.group(1) == "1" else "SHORT"
                conf = conf_match.group(1) if conf_match else "?"
                print(f"  {ts.strftime('%H:%M:%S')} ({age_str:>8}) - {pred} (confidence={conf})")
    else:
        print("  No predictions yet")
    print()
    
    # Orders
    print("RECENT ORDERS:")
    print("-" * 80)
    if orders_log.exists() and orders_log.stat().st_size > 0:
        order_lines = get_last_log_lines(orders_log, "", 3)
        if order_lines:
            for line in order_lines:
                print(f"  {line[:80]}")
        else:
            print("  No orders")
    else:
        print("  No orders yet")
    print()
    
    # Trades
    print("RECENT TRADES:")
    print("-" * 80)
    if trades_log.exists() and trades_log.stat().st_size > 0:
        trade_lines = get_last_log_lines(trades_log, "", 3)
        if trade_lines:
            for line in trade_lines:
                print(f"  {line[:80]}")
        else:
            print("  No trades")
    else:
        print("  No trades yet")
    print()
    
    # Errors
    print("RECENT ERRORS:")
    print("-" * 80)
    if errors_log.exists() and errors_log.stat().st_size > 0:
        error_lines = get_last_log_lines(errors_log, "ERROR", 3)
        if error_lines:
            for line in error_lines:
                print(f"  {line[:80]}")
        else:
            print("  No errors")
    else:
        print("  No errors")
    print()
    
    # Next Expected Bar
    print("NEXT EXPECTED BAR:")
    print("-" * 80)
    now = datetime.now()
    # Calculate next 15-minute boundary
    minutes_to_next = 15 - (now.minute % 15)
    next_15 = now + timedelta(minutes=minutes_to_next)
    next_15 = next_15.replace(second=0, microsecond=0)
    time_until = next_15 - now
    print(f"  Time: {next_15.strftime('%H:%M:%S')}")
    print(f"  In: {int(time_until.total_seconds() / 60)} minutes {int(time_until.total_seconds() % 60)} seconds")
    print()
    
    print("="*80)
    print("Tip: Run 'python monitor_live_status.py' anytime to check status")
    print("="*80)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMonitoring interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
