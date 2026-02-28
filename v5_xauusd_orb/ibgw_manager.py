"""
ibgw_manager.py -- IB Gateway process manager  (v5)

Monitors IB Gateway health and restarts on crashes.
All parameters from config.yaml.

Usage:
  # Start and monitor (runs until Ctrl+C):
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.ibgw_manager

  # Just check status:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.ibgw_manager --status

  # Start Gateway once and exit:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.ibgw_manager --start-only

  # Force restart:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.ibgw_manager --restart

  # Custom config:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.ibgw_manager --config my.yaml

Windows Scheduled Task (auto-start on logon):
  schtasks /create /tn "IBGatewayManager" ^
    /tr "C:\\nautilus0\\.venv\\Scripts\\python.exe -m v5_xauusd_orb.ibgw_manager" ^
    /sc onlogon /rl highest
"""
from __future__ import annotations

import argparse
import logging
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from v5_xauusd_orb.config import load_config, Config


# ── Logging (deferred until config loaded) ────────────────────────────────────

def setup_logging(cfg: Config) -> logging.Logger:
    log = logging.getLogger("ibgw_manager")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    log.addHandler(sh)

    fh = logging.FileHandler(cfg.paths.ibgw_log)
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)

    return log


# ── Process helpers ───────────────────────────────────────────────────────────

def is_process_running(cfg: Config) -> bool:
    name = cfg.gateway.process_name
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}"],
            capture_output=True, text=True, timeout=15,
        )
        return name.lower() in result.stdout.lower()
    except Exception:
        return False


def get_process_pid(cfg: Config) -> int | None:
    name = cfg.gateway.process_name
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}",
             "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.strip().split("\n"):
            if name.lower() in line.lower():
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    return int(parts[1])
    except Exception:
        pass
    return None


def is_port_listening(port: int, timeout: int = 5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, socket.timeout):
        return False


def start_gateway(cfg: Config, log: logging.Logger) -> bool:
    if is_process_running(cfg):
        log.info("IB Gateway already running")
        return True
    exe = Path(cfg.gateway.exe_path)
    if not exe.exists():
        log.error(f"IB Gateway not found: {exe}")
        return False
    log.info(f"Starting IB Gateway: {exe}")
    try:
        subprocess.Popen(
            [str(exe)], cwd=str(exe.parent),
            creationflags=(subprocess.DETACHED_PROCESS |
                           subprocess.CREATE_NEW_PROCESS_GROUP),
        )
        log.info("IB Gateway launched")
        return True
    except Exception as e:
        log.error(f"Failed to start: {e}")
        return False


def kill_gateway(cfg: Config, log: logging.Logger) -> bool:
    pid = get_process_pid(cfg)
    if pid is None:
        log.info("Gateway not running, nothing to kill")
        return True
    log.warning(f"Killing Gateway (PID {pid})")
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, text=True, timeout=15)
        time.sleep(3)
        if not is_process_running(cfg):
            log.info("Gateway killed successfully")
            return True
        log.error("Gateway still running after kill")
        return False
    except Exception as e:
        log.error(f"Kill failed: {e}")
        return False


def restart_gateway(cfg: Config, log: logging.Logger) -> bool:
    log.warning("Restarting IB Gateway...")
    kill_gateway(cfg, log)
    time.sleep(5)
    return start_gateway(cfg, log)


# ── Health tracker ────────────────────────────────────────────────────────────

class GatewayHealth:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.port = cfg.ibkr.port
        self.process_alive = False
        self.port_open = False
        self.last_restart = 0.0
        self.restart_count = 0
        self.consecutive_port_failures = 0

    def check(self) -> dict:
        self.process_alive = is_process_running(self.cfg)
        self.port_open = (is_port_listening(
            self.port, self.cfg.gateway.port_check_timeout_sec)
            if self.process_alive else False)
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
        now = time.time()
        cooldown = self.cfg.gateway.restart_cooldown_sec
        if now - self.last_restart < cooldown:
            remaining = int(cooldown - (now - self.last_restart))
            return False, f"In cooldown ({remaining}s left)"
        if not self.process_alive:
            return True, "Process not running"
        max_fail = self.cfg.gateway.max_consecutive_port_failures
        if self.consecutive_port_failures >= max_fail:
            return True, (f"Port {self.port} unresponsive "
                          f"{self.consecutive_port_failures}x")
        return False, "Healthy"

    def record_restart(self):
        self.last_restart = time.time()
        self.restart_count += 1
        self.consecutive_port_failures = 0


# ── Status display ────────────────────────────────────────────────────────────

def show_status(cfg: Config):
    running = is_process_running(cfg)
    pid = get_process_pid(cfg) if running else None
    paper = is_port_listening(cfg.gateway.paper_port,
                              cfg.gateway.port_check_timeout_sec)
    live = is_port_listening(cfg.gateway.live_port,
                             cfg.gateway.port_check_timeout_sec)

    print("=" * 50)
    print("  IB Gateway Status")
    print("=" * 50)
    print(f"  Process:     {'RUNNING' if running else 'NOT RUNNING'}"
          f"{f' (PID {pid})' if pid else ''}")
    print(f"  Paper API:   {'OPEN' if paper else 'CLOSED'} "
          f"(port {cfg.gateway.paper_port})")
    print(f"  Live API:    {'OPEN' if live else 'CLOSED'} "
          f"(port {cfg.gateway.live_port})")
    print(f"  Executable:  {cfg.gateway.exe_path}")
    print(f"  Exists:      "
          f"{'YES' if Path(cfg.gateway.exe_path).exists() else 'NO'}")
    print("=" * 50)


# ── Monitor loop ──────────────────────────────────────────────────────────────

def monitor_loop(cfg: Config, log: logging.Logger):
    health = GatewayHealth(cfg)
    gw = cfg.gateway

    log.info(f"Gateway monitor started (port {health.port}, "
             f"check every {gw.check_interval_sec}s)")

    if not is_process_running(cfg):
        log.info("Gateway not running -- launching...")
        if start_gateway(cfg, log):
            health.record_restart()
            log.info(f"Waiting {gw.startup_wait_sec}s for API...")
            time.sleep(gw.startup_wait_sec)

    while True:
        try:
            status = health.check()
            now_str = datetime.now(tz=timezone.utc).strftime("%H:%M UTC")

            if status['port_open']:
                log.debug(f"[{now_str}] Healthy")
            elif status['process_alive']:
                log.warning(f"[{now_str}] Port {health.port} unresponsive "
                            f"({health.consecutive_port_failures}x)")
            else:
                log.warning(f"[{now_str}] Process NOT running")

            should, reason = health.needs_restart()
            if should:
                log.warning(f"Restart needed: {reason}")
                if restart_gateway(cfg, log):
                    health.record_restart()
                    log.info(f"Restart #{health.restart_count}. "
                             f"Waiting {gw.startup_wait_sec}s...")
                    time.sleep(gw.startup_wait_sec)
                    if is_port_listening(health.port,
                                        gw.port_check_timeout_sec):
                        log.info(f"Port {health.port} responding")
                    else:
                        log.warning(f"Port {health.port} still down "
                                    f"-- may need manual login")
                else:
                    log.error("Restart failed")

            time.sleep(gw.check_interval_sec)

        except KeyboardInterrupt:
            log.info("Monitor stopped by user")
            break
        except Exception as e:
            log.error(f"Monitor error: {e}", exc_info=True)
            time.sleep(gw.check_interval_sec)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="IB Gateway process manager (v5)")
    parser.add_argument("--status", action="store_true",
                        help="Show status and exit")
    parser.add_argument("--start-only", action="store_true",
                        help="Start Gateway and exit")
    parser.add_argument("--restart", action="store_true",
                        help="Force restart and exit")
    parser.add_argument("--port", type=int, default=None,
                        help="Override IBKR port to monitor")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to alternative config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.port is not None:
        cfg.ibkr.port = args.port

    if args.status:
        show_status(cfg)
        return

    log = setup_logging(cfg)
    gw = cfg.gateway

    if args.restart:
        if restart_gateway(cfg, log):
            log.info(f"Waiting {gw.startup_wait_sec}s for API...")
            time.sleep(gw.startup_wait_sec)
            if is_port_listening(cfg.ibkr.port,
                                 gw.port_check_timeout_sec):
                log.info(f"Port {cfg.ibkr.port} responding")
            else:
                log.warning(f"Port {cfg.ibkr.port} not responding "
                            f"-- may need manual login")
        return

    if args.start_only:
        if start_gateway(cfg, log):
            log.info("Gateway launched. Exiting.")
        else:
            sys.exit(1)
        return

    def shutdown(signum, frame):
        log.info("Shutdown signal received")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    monitor_loop(cfg, log)


if __name__ == "__main__":
    main()
