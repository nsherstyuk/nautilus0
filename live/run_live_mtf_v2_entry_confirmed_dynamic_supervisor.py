"""Supervisor for MTF V2 Entry Confirmed Dynamic live runner.

Starts `live/run_live_mtf_v2_entry_confirmed_dynamic.py` as a child process and restarts it:
- On a daily scheduled downtime window
- When the child exits unexpectedly

This is intended for Windows PowerShell usage.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv

logger = logging.getLogger("live_v2_entry_confirmed_dynamic_supervisor")


def _load_env_file() -> None:
    project_root = Path(__file__).resolve().parent.parent
    env_file = project_root / ".env.mtf_v2"
    try:
        if env_file.exists():
            load_dotenv(env_file, override=True)
            logger.info("Loaded env file: %s", env_file)
    except Exception as e:
        logger.warning("Failed to load env file %s: %s", env_file, e)


def _strip_env_value(raw: object | None) -> str:
    if raw is None:
        return ""
    v = str(raw)
    if "#" in v:
        v = v.split("#", 1)[0]
    v = v.strip()
    if not v:
        return ""
    return v.split()[0].strip()


@dataclass
class SupervisorConfig:
    """Supervisor configuration."""

    # Daily schedule (Eastern time)
    daily_stop_time: dtime = dtime(23, 30)  # 11:30 PM ET
    daily_restart_time: dtime = dtime(1, 30)  # 1:30 AM ET

    # Child process monitoring
    check_interval_sec: int = 10
    restart_delay_sec: int = 120

    # Stale data detection
    stale_enabled: bool = True
    stale_max_bar_age_sec: int = 1500
    stale_max_status_age_sec: int = 90
    stale_consec_fails: int = 3

    # Persistent failure backoff
    max_short_restarts: int = 3
    extended_delay_sec: int = 1800  # 30 minutes
    stability_reset_sec: int = 1800

    @classmethod
    def from_env(cls) -> "SupervisorConfig":
        """Load configuration from environment variables."""
        return cls(
            daily_stop_time=dtime(
                int(os.getenv("MTF2_SUPERVISOR_DAILY_STOP_LOCAL", "23:30").split(":")[0]),
                int(os.getenv("MTF2_SUPERVISOR_DAILY_STOP_LOCAL", "23:30").split(":")[1]),
            ),
            daily_restart_time=dtime(
                int(os.getenv("MTF2_SUPERVISOR_DAILY_RESTART_LOCAL", "1:30").split(":")[0]),
                int(os.getenv("MTF2_SUPERVISOR_DAILY_RESTART_LOCAL", "1:30").split(":")[1]),
            ),
            check_interval_sec=int(os.getenv("MTF2_SUPERVISOR_CHECK_INTERVAL_SEC", "10")),
            restart_delay_sec=int(os.getenv("MTF2_SUPERVISOR_RESTART_DELAY_SEC", "120")),
            stale_enabled=_env_bool("MTF2_SUPERVISOR_STALE_ENABLED", True),
            stale_max_bar_age_sec=int(os.getenv("MTF2_SUPERVISOR_STALE_MAX_BAR_AGE_SEC", "1500")),
            stale_max_status_age_sec=int(os.getenv("MTF2_SUPERVISOR_STALE_MAX_STATUS_AGE_SEC", "90")),
            stale_consec_fails=int(os.getenv("MTF2_SUPERVISOR_STALE_CONSEC_FAILS", "3")),
            max_short_restarts=int(os.getenv("MTF2_SUPERVISOR_MAX_SHORT_RESTARTS", "3")),
            extended_delay_sec=int(os.getenv("MTF2_SUPERVISOR_EXTENDED_DELAY_SEC", "1800")),
            stability_reset_sec=int(os.getenv("MTF2_SUPERVISOR_STABILITY_RESET_SEC", "1800")),
        )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


class ChildProcessMonitor:
    """Monitors the child process and handles restarts."""

    def __init__(self, config: SupervisorConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.start_time: Optional[datetime] = None
        self.restart_count = 0
        self.consec_failures = 0
        self.last_failure_time: Optional[datetime] = None

    def start_child(self) -> bool:
        """Start the child process."""
        try:
            logger.info("Starting child process: run_live_mtf_v2_entry_confirmed_dynamic.py")

            # Use the same Python executable and environment
            python_exe = sys.executable
            script_path = Path(__file__).parent / "run_live_mtf_v2_entry_confirmed_dynamic.py"

            self.process = subprocess.Popen(
                [python_exe, str(script_path)],
                cwd=Path(__file__).parent.parent,  # Project root
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            self.start_time = datetime.now()
            self.restart_count += 1
            logger.info("Child process started (PID: %d, restart #%d)", self.process.pid, self.restart_count)
            return True

        except Exception as e:
            logger.error("Failed to start child process: %s", e)
            return False

    def stop_child(self) -> None:
        """Stop the child process."""
        if self.process is None:
            return

        logger.info("Stopping child process (PID: %d)", self.process.pid)

        try:
            # Try graceful shutdown first
            if hasattr(signal, 'SIGTERM'):
                self.process.terminate()

            # Wait for graceful shutdown
            try:
                self.process.wait(timeout=10)
                logger.info("Child process terminated gracefully")
            except subprocess.TimeoutExpired:
                logger.warning("Child process didn't terminate gracefully, forcing kill")
                self.process.kill()
                self.process.wait()
                logger.info("Child process killed")

        except Exception as e:
            logger.error("Error stopping child process: %s", e)
        finally:
            self.process = None

    def is_child_running(self) -> bool:
        """Check if child process is still running."""
        if self.process is None:
            return False

        return self.process.poll() is None

    def get_child_output(self) -> Optional[str]:
        """Get latest output from child process."""
        if self.process is None or self.process.stdout is None:
            return None

        try:
            # Read any available output without blocking
            output = ""
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                output += line
            return output.strip() if output else None
        except Exception:
            return None

    def should_restart_for_schedule(self, now: datetime) -> bool:
        """Check if we should restart for daily schedule."""
        if not self.config.daily_stop_time or not self.config.daily_restart_time:
            return False

        # Convert to local time for schedule checking
        local_now = now.astimezone()
        current_time = local_now.time()

        # Check if we're in the downtime window
        if self.config.daily_stop_time <= self.config.daily_restart_time:
            # Same day window (e.g., 23:30 to 1:30 next day)
            in_downtime = current_time >= self.config.daily_stop_time or current_time <= self.config.daily_restart_time
        else:
            # Overnight window (e.g., 22:00 to 6:00)
            in_downtime = self.config.daily_stop_time <= current_time <= self.config.daily_restart_time

        return in_downtime

    def should_restart_for_failures(self) -> bool:
        """Check if we should restart due to consecutive failures."""
        if self.consec_failures >= self.config.stale_consec_fails:
            return True
        return False

    def record_failure(self) -> None:
        """Record a failure for backoff logic."""
        now = datetime.now()
        self.consec_failures += 1
        self.last_failure_time = now

        if self.consec_failures >= self.config.max_short_restarts:
            logger.warning(
                "Reached max short restarts (%d), will use extended delay (%d sec)",
                self.config.max_short_restarts,
                self.config.extended_delay_sec
            )

    def reset_failure_count(self) -> None:
        """Reset failure count after successful period."""
        if self.consec_failures > 0:
            logger.info("Resetting failure count after successful period")
            self.consec_failures = 0
            self.last_failure_time = None

    def get_restart_delay(self) -> int:
        """Get delay before next restart attempt."""
        if self.consec_failures >= self.config.max_short_restarts:
            return self.config.extended_delay_sec
        return self.config.restart_delay_sec


def main() -> int:
    """Main supervisor loop."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("Starting MTF V2 Entry Confirmed Dynamic supervisor")

    # Load environment
    _load_env_file()

    # Load configuration
    config = SupervisorConfig.from_env()
    logger.info("Supervisor config: stop=%s, restart=%s, check_interval=%ds",
                config.daily_stop_time, config.daily_restart_time, config.check_interval_sec)

    # Create monitor
    monitor = ChildProcessMonitor(config)

    last_schedule_check = datetime.now()
    last_stability_reset = datetime.now()

    while True:
        now = datetime.now()

        # Periodic stability reset
        if (now - last_stability_reset).total_seconds() >= config.stability_reset_sec:
            monitor.reset_failure_count()
            last_stability_reset = now

        # Check if we should be running based on schedule
        should_be_running = not monitor.should_restart_for_schedule(now)

        if should_be_running:
            # We should be running - check if child is alive
            if not monitor.is_child_running():
                if monitor.process is not None:
                    # Child exited unexpectedly
                    exit_code = monitor.process.returncode
                    logger.warning("Child process exited unexpectedly (code: %s)", exit_code)
                    monitor.record_failure()

                    # Get any remaining output
                    output = monitor.get_child_output()
                    if output:
                        logger.info("Child output: %s", output)

                # Start new child process
                delay = monitor.get_restart_delay()
                if delay > 0:
                    logger.info("Waiting %d seconds before restart...", delay)
                    time.sleep(delay)

                if not monitor.start_child():
                    logger.error("Failed to start child process, will retry...")
                    time.sleep(config.check_interval_sec)
                    continue

        else:
            # We should be stopped - check if child is running
            if monitor.is_child_running():
                logger.info("Scheduled downtime window - stopping child process")
                monitor.stop_child()

        # Check for stale data if enabled
        if config.stale_enabled and monitor.is_child_running():
            # TODO: Implement stale data detection logic
            # This would check if the strategy has received recent bar data
            pass

        # Log status periodically
        if (now - last_schedule_check).total_seconds() >= 300:  # Every 5 minutes
            status = "RUNNING" if monitor.is_child_running() else "STOPPED"
            schedule_status = "ACTIVE" if should_be_running else "DOWNTIME"
            logger.info("Status: child=%s, schedule=%s, restarts=%d, failures=%d",
                       status, schedule_status, monitor.restart_count, monitor.consec_failures)
            last_schedule_check = now

        time.sleep(config.check_interval_sec)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("Supervisor shutdown requested")
        sys.exit(0)
    except Exception as e:
        logger.error("Supervisor crashed: %s", e)
        sys.exit(1)