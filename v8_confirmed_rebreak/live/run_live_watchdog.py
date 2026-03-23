"""
Auto-restart watchdog for V8 live trader.

Monitors the live trading process and automatically restarts it if it crashes
or stops unexpectedly. Logs all restarts and provides graceful shutdown.

Usage:
    python run_live_watchdog.py --port 4002 --pw 60 --confirm 3 --max-hold 60 --sl 10 --min-ticks 75 --qty 1.0

To stop: Create a file named "STOP" in the live directory or press Ctrl+C twice
"""
import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOP_FILE = Path(__file__).parent / "STOP"
LOG_FILE = Path(__file__).parent / "logs" / "watchdog.log"

def log(msg: str):
    """Log to both console and file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp}  {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def should_stop() -> bool:
    """Check if STOP file exists."""
    return STOP_FILE.exists()

def run_trader(args: list) -> int:
    """Run the live trader and return exit code."""
    cmd = [sys.executable, "-m", "v8_confirmed_rebreak.live.run_live"] + args
    log(f"Starting trader: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, cwd=str(ROOT))
        return result.returncode
    except KeyboardInterrupt:
        log("Keyboard interrupt received")
        return 130
    except Exception as e:
        log(f"ERROR running trader: {e}")
        return 1

def main():
    parser = argparse.ArgumentParser(description="V8 Live Trader Watchdog")
    parser.add_argument("--port", type=int, default=4002)
    parser.add_argument("--pw", type=int, default=60)
    parser.add_argument("--confirm", type=int, default=3)
    parser.add_argument("--max-hold", type=int, default=60)
    parser.add_argument("--sl", type=float, default=10.0)
    parser.add_argument("--min-ticks", type=int, default=5)
    parser.add_argument("--qty", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-restarts", type=int, default=10,
                        help="Max restarts per hour (0=unlimited)")
    args = parser.parse_args()

    # Build command args
    cmd_args = [
        "--port", str(args.port),
        "--pw", str(args.pw),
        "--confirm", str(args.confirm),
        "--max-hold", str(args.max_hold),
        "--sl", str(args.sl),
        "--min-ticks", str(args.min_ticks),
        "--qty", str(args.qty),
    ]
    if args.dry_run:
        cmd_args.append("--dry-run")

    log("=" * 60)
    log("V8 Live Trader Watchdog Started")
    log(f"  Max restarts/hour: {args.max_restarts if args.max_restarts > 0 else 'unlimited'}")
    log(f"  To stop: Create file {STOP_FILE} or press Ctrl+C twice")
    log("=" * 60)

    restart_count = 0
    restart_times = []
    ctrl_c_count = 0

    while True:
        if should_stop():
            log("STOP file detected -- exiting")
            STOP_FILE.unlink()
            break

        # Check restart rate limit
        now = time.time()
        restart_times = [t for t in restart_times if now - t < 3600]  # Last hour
        if args.max_restarts > 0 and len(restart_times) >= args.max_restarts:
            log(f"ERROR: Too many restarts ({len(restart_times)} in last hour)")
            log("Waiting 10 minutes before retry...")
            time.sleep(600)
            restart_times = []

        # Run trader
        exit_code = run_trader(cmd_args)

        if exit_code == 130:  # Ctrl+C
            ctrl_c_count += 1
            if ctrl_c_count >= 2:
                log("Double Ctrl+C detected -- shutting down")
                break
            log("Single Ctrl+C -- press again within 5s to stop, or wait to restart")
            time.sleep(5)
            ctrl_c_count = 0
            continue

        if exit_code == 0:
            log("Trader exited cleanly (exit code 0)")
            break

        # Unexpected exit
        restart_count += 1
        restart_times.append(now)
        log(f"Trader crashed (exit code {exit_code}) -- restart #{restart_count}")
        log("Waiting 10 seconds before restart...")
        time.sleep(10)

    log("Watchdog stopped")

if __name__ == "__main__":
    main()
