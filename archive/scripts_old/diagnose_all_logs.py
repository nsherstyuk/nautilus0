"""
Comprehensive diagnostic - check ALL log files.
"""
from pathlib import Path
from datetime import datetime

def check_all_logs():
    """Check all log files in live_mtf directory."""
    log_dir = Path("logs/live_mtf")
    
    if not log_dir.exists():
        print(f"ERROR: Log directory not found: {log_dir}")
        return
    
    print("="*80)
    print("COMPREHENSIVE LOG FILE ANALYSIS")
    print("="*80)
    print(f"Log directory: {log_dir}")
    print()
    
    log_files = [
        "application.log",
        "live_trading.log",
        "strategy.log",
        "orders.log",
        "trades.log",
        "errors.log"
    ]
    
    for log_file in log_files:
        log_path = log_dir / log_file
        
        if not log_path.exists():
            print(f"{log_file:20s}: NOT FOUND")
            continue
        
        size = log_path.stat().st_size
        modified = datetime.fromtimestamp(log_path.stat().st_mtime)
        
        print(f"{log_file:20s}: {size:,} bytes, modified {modified}")
        
        if size > 0:
            # Read last 10 lines
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            print(f"  Total lines: {len(lines)}")
            print(f"  Last 3 lines:")
            for line in lines[-3:]:
                print(f"    {line.strip()[:100]}")
        print()
    
    # Check which log has the most recent activity
    print("="*80)
    print("MOST RECENT ACTIVITY")
    print("="*80)
    
    most_recent = None
    most_recent_time = None
    
    for log_file in log_files:
        log_path = log_dir / log_file
        if log_path.exists() and log_path.stat().st_size > 0:
            modified = datetime.fromtimestamp(log_path.stat().st_mtime)
            if most_recent_time is None or modified > most_recent_time:
                most_recent = log_file
                most_recent_time = modified
    
    if most_recent:
        print(f"Most recent log: {most_recent} ({most_recent_time})")
        print(f"\nAnalyzing {most_recent}...")
        
        log_path = log_dir / most_recent
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        print(f"\nLast 20 lines of {most_recent}:")
        print("-"*80)
        for line in lines[-20:]:
            print(line.rstrip())
    else:
        print("No log files have any content!")
        print("\nThis means the strategy is NOT RUNNING.")
        print("\nPossible causes:")
        print("1. Strategy not added to trading node")
        print("2. Strategy on_start() never called")
        print("3. Logging not configured for strategy")
        print("4. Strategy failed to initialize silently")

if __name__ == "__main__":
    check_all_logs()
