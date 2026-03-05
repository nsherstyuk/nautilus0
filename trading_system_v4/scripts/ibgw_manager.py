"""
ibgw_manager.py -- IB Gateway process manager

Keeps IB Gateway running and restarts it if it crashes or becomes
unresponsive. Designed to run as a background process or Windows
Scheduled Task.

What it does:
  1. Starts IB Gateway if not running
  2. Monitors the process and API port health every 60s
  3. Restarts Gateway if the process dies or the API port stops responding
  4. Logs everything to trading_system_v4/logs/ibgw_manager.log

Limitations:
  - Gateway requires manual login on FIRST start of each day
    (username + 2FA). Subsequent restarts within the same day
    use IBKR's AutoRestart feature.
  - This script cannot type credentials -- it only launches the
    Gateway process and monitors liveness.

Usage:
  # Start and monitor (runs until Ctrl+C):
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\ibgw_manager.py

  # Just check status:
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\ibgw_manager.py --status

  # Start Gateway and exit (one-shot):
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\ibgw_manager.py --start-only

To set up as Windows Scheduled Task (run at system boot):
  schtasks /create /tn "IBGatewayManager" /tr "C:\\nautilus0\\.venv\\Scripts\\python.exe C:\\nautilus0\\trading_system_v4\\scripts\\ibgw_manager.py" /sc onlogon /rl highest
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "trading_system_v4" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Configuration ─────────────────────────────────────────────────────────────
IBGW_EXE = Path(r"C:\Jts\ibgateway\1041\ibgateway.exe")
IBGW_PROCESS_NAME = "ibgateway.exe"

# API ports to monitor
PAPER_PORT = 4002
LIVE_PORT = 4001

# Monitoring intervals
CHECK_INTERVAL = 60          # seconds between health checks
STARTUP_WAIT = 60            # seconds to wait for Gateway API after launch
RESTART_COOLDOWN = 300       # minimum seconds between restart attempts
PORT_CHECK_TIMEOUT = 5       # seconds to wait for port connection

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger("ibgw_manager")
log.setLevel(logging.DEBUG)

_fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")

_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
_sh.setLevel(logging.INFO)
log.addHandler(_sh)

_fh = logging.FileHandler(LOG_DIR / "ibgw_manager.log")
_fh.setFormatter(_fmt)
_fh.setLevel(logging.DEBUG)
log.addHandler(_fh)


# ── Process helpers ───────────────────────────────────────────────────────────

def is_process_running(name: str = IBGW_PROCESS_NAME) -> bool:
    """Check if a process with the given name is running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}"],
            capture_output=True, text=True, timeout=15
        )
        return name.lower() in result.stdout.lower()
    except Exception as e:
        log.debug(f"tasklist check failed: {e}")
        return False


def get_process_pid(name: str = IBGW_PROCESS_NAME) -> int | None:
    """Get PID of the process. Returns None if not running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15
        )
        for line in result.stdout.strip().split("\n"):
            if name.lower() in line.lower():
                # CSV format: "name","PID","Session","Session#","Mem"
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    return int(parts[1])
    except Exception:
        pass
    return None


def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=PORT_CHECK_TIMEOUT):
            return True
    except (OSError, ConnectionRefusedError, socket.timeout):
        return False


def start_gateway() -> bool:
    """Launch IB Gateway process.

    Returns True if launched or already running.
    """
    if is_process_running():
        log.info("IB Gateway already running")
        return True

    if not IBGW_EXE.exists():
        log.error(f"IB Gateway executable not found: {IBGW_EXE}")
        return False

    log.info(f"Starting IB Gateway: {IBGW_EXE}")
    try:
        subprocess.Popen(
            [str(IBGW_EXE)],
            cwd=str(IBGW_EXE.parent),
            creationflags=(
                subprocess.DETACHED_PROCESS |
                subprocess.CREATE_NEW_PROCESS_GROUP
            ),
        )
        log.info("IB Gateway process launched")
        return True
    except Exception as e:
        log.error(f"Failed to start Gateway: {e}")
        return False


def kill_gateway() -> bool:
    """Force-kill IB Gateway process."""
    pid = get_process_pid()
    if pid is None:
        log.info("Gateway not running, nothing to kill")
        return True

    log.warning(f"Killing Gateway process (PID {pid})")
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(3)
        if not is_process_running():
            log.info("Gateway killed successfully")
            return True
        else:
            log.error("Gateway still running after kill attempt")
            return False
    except Exception as e:
        log.error(f"Kill failed: {e}")
        return False


def restart_gateway() -> bool:
    """Kill and restart IB Gateway."""
    log.warning("Restarting IB Gateway...")
    kill_gateway()
    time.sleep(5)
    return start_gateway()


# ── Health check ──────────────────────────────────────────────────────────────

class GatewayHealth:
    """Tracks Gateway health status."""

    def __init__(self, port: int):
        self.port = port
        self.process_alive = False
        self.port_open = False
        self.last_restart = 0.0
        self.restart_count = 0
        self.consecutive_port_failures = 0

    def check(self) -> dict:
        """Run health check. Returns status dict."""
        self.process_alive = is_process_running()
        self.port_open = is_port_listening(self.port) if self.process_alive else False

        if self.port_open:
            self.consecutive_port_failures = 0
        elif self.process_alive:
            self.consecutive_port_failures += 1

        return {
            'process_alive': self.process_alive,
            'port_open': self.port_open,
            'port': self.port,
            'restart_count': self.restart_count,
            'consecutive_port_failures': self.consecutive_port_failures,
        }

    def needs_restart(self) -> tuple[bool, str]:
        """Determine if Gateway needs restart. Returns (should_restart, reason)."""
        now = time.time()

        # Cooldown: don't restart too frequently
        if now - self.last_restart < RESTART_COOLDOWN:
            remaining = int(RESTART_COOLDOWN - (now - self.last_restart))
            return False, f"In restart cooldown ({remaining}s remaining)"

        # Process dead
        if not self.process_alive:
            return True, "Process not running"

        # Process alive but port not responding for 3+ consecutive checks
        if self.consecutive_port_failures >= 3:
            return True, (f"API port {self.port} unresponsive for "
                         f"{self.consecutive_port_failures} consecutive checks")

        return False, "Healthy"

    def record_restart(self):
        self.last_restart = time.time()
        self.restart_count += 1
        self.consecutive_port_failures = 0


# ── Status display ────────────────────────────────────────────────────────────

def show_status(port: int):
    """Print current Gateway status and exit."""
    process_running = is_process_running()
    pid = get_process_pid() if process_running else None
    paper_ok = is_port_listening(PAPER_PORT)
    live_ok = is_port_listening(LIVE_PORT)

    print("=" * 50)
    print("  IB Gateway Status")
    print("=" * 50)
    print(f"  Process:     {'RUNNING' if process_running else 'NOT RUNNING'}"
          f"{f' (PID {pid})' if pid else ''}")
    print(f"  Paper API:   {'OPEN' if paper_ok else 'CLOSED'} (port {PAPER_PORT})")
    print(f"  Live API:    {'OPEN' if live_ok else 'CLOSED'} (port {LIVE_PORT})")
    print(f"  Executable:  {IBGW_EXE}")
    print(f"  Exists:      {'YES' if IBGW_EXE.exists() else 'NO'}")
    print("=" * 50)


# ── Monitor loop ──────────────────────────────────────────────────────────────

def monitor_loop(port: int):
    """Main monitoring loop -- runs until interrupted."""
    health = GatewayHealth(port)

    log.info(f"Starting Gateway monitor (API port {port}, "
             f"check every {CHECK_INTERVAL}s)")

    # Initial start if needed
    if not is_process_running():
        log.info("Gateway not running on startup -- launching...")
        if start_gateway():
            health.record_restart()
            log.info(f"Waiting {STARTUP_WAIT}s for Gateway to initialize...")
            time.sleep(STARTUP_WAIT)

    while True:
        try:
            status = health.check()
            now_str = datetime.now(tz=timezone.utc).strftime("%H:%M UTC")

            if status['port_open']:
                log.debug(f"[{now_str}] Healthy: process alive, "
                         f"port {port} open")
            elif status['process_alive']:
                log.warning(f"[{now_str}] Process alive but port {port} "
                           f"not responding "
                           f"({health.consecutive_port_failures} failures)")
            else:
                log.warning(f"[{now_str}] Process NOT running")

            should_restart, reason = health.needs_restart()
            if should_restart:
                log.warning(f"Restart needed: {reason}")

                if restart_gateway():
                    health.record_restart()
                    log.info(f"Restart #{health.restart_count} successful. "
                            f"Waiting {STARTUP_WAIT}s for API...")
                    time.sleep(STARTUP_WAIT)

                    # Verify after restart
                    if is_port_listening(port):
                        log.info(f"API port {port} responding after restart")
                    else:
                        log.warning(f"API port {port} still not responding "
                                   f"after restart -- may need manual login")
                else:
                    log.error("Restart failed")

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            log.info("Monitor stopped by user")
            break
        except Exception as e:
            log.error(f"Monitor error: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="IB Gateway process manager"
    )
    parser.add_argument("--status", action="store_true",
                        help="Show Gateway status and exit")
    parser.add_argument("--start-only", action="store_true",
                        help="Start Gateway and exit (no monitoring)")
    parser.add_argument("--restart", action="store_true",
                        help="Force restart Gateway and exit")
    parser.add_argument("--port", type=int, default=PAPER_PORT,
                        help=f"API port to monitor (default: {PAPER_PORT})")
    args = parser.parse_args()

    if args.status:
        show_status(args.port)
        return

    if args.restart:
        if restart_gateway():
            log.info(f"Waiting {STARTUP_WAIT}s for API...")
            time.sleep(STARTUP_WAIT)
            if is_port_listening(args.port):
                log.info(f"Gateway restarted, port {args.port} responding")
            else:
                log.warning(f"Gateway restarted but port {args.port} not "
                           f"responding -- may need manual login")
        return

    if args.start_only:
        if start_gateway():
            log.info("Gateway launched. Exiting.")
        else:
            sys.exit(1)
        return

    # Default: start + monitor
    def shutdown(signum, frame):
        log.info("Shutdown signal received")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    monitor_loop(args.port)


if __name__ == "__main__":
    main()
