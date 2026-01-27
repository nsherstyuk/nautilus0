"""Supervisor for MTF V2 Entry Confirmed live runner.

Starts `live/run_live_mtf_v2_entry_confirmed_v2.py` as a child process and restarts it:
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

logger = logging.getLogger("live_v2_entry_confirmed_supervisor")


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


def _env_bool(name: str, default: bool) -> bool:
    raw = _strip_env_value(os.getenv(name))
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _strip_env_value(os.getenv(name))
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _parse_hhmm(value: str, default: Tuple[int, int]) -> Tuple[int, int]:
    v = _strip_env_value(value)
    if not v:
        return default
    if ":" not in v:
        return default
    hh_str, mm_str = v.split(":", 1)
    try:
        hh = int(hh_str)
        mm = int(mm_str)
    except Exception:
        return default
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return default
    return hh, mm


def _in_downtime_window(now_local: dtime, stop_hhmm: Tuple[int, int], restart_hhmm: Tuple[int, int]) -> bool:
    stop_t = dtime(hour=stop_hhmm[0], minute=stop_hhmm[1])
    restart_t = dtime(hour=restart_hhmm[0], minute=restart_hhmm[1])

    if stop_t < restart_t:
        return stop_t <= now_local < restart_t

    return now_local >= stop_t or now_local < restart_t


def _seconds_until_next_local(target_hhmm: Tuple[int, int]) -> int:
    now = datetime.now()
    target = now.replace(hour=target_hhmm[0], minute=target_hhmm[1], second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return int((target - now).total_seconds())


@dataclass
class SupervisorConfig:
    child_script: Path
    check_interval_sec: float
    restart_delay_sec: int
    min_uptime_before_restart_sec: int
    daily_enabled: bool
    daily_stop_hhmm: Tuple[int, int]
    daily_restart_hhmm: Tuple[int, int]


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


class ChildProcess:
    def __init__(self, config: SupervisorConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.started_at: Optional[float] = None

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return

        # Ensure the child starts in INFO console mode (prevents Nautilus DEBUG spam).
        try:
            project_root = Path(__file__).resolve().parent.parent
            toggle_script = project_root / "scripts" / "toggle_debug.py"
            if toggle_script.exists():
                subprocess.run([sys.executable, str(toggle_script), "off"], check=False)
        except Exception:
            pass

        project_root = Path(__file__).resolve().parent.parent

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        cmd = [sys.executable, str(self.config.child_script)]
        logger.info("Starting child: %s", " ".join(cmd))

        kwargs = {
            "cwd": str(project_root),
            "env": env,
        }
        if sys.platform == "win32":
            # Enables CTRL_BREAK_EVENT delivery to the child.
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        self.process = subprocess.Popen(cmd, **kwargs)
        self.started_at = time.time()

    def stop(self) -> None:
        if not self.process:
            return
        if self.process.poll() is not None:
            return

        logger.info("Stopping child PID=%s", self.process.pid)
        try:
            if sys.platform == "win32" and hasattr(signal, "CTRL_BREAK_EVENT"):
                # Best-effort graceful stop on Windows.
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.send_signal(signal.SIGINT)
        except Exception:
            pass

        deadline = time.time() + 20
        while time.time() < deadline:
            if self.process.poll() is not None:
                return
            time.sleep(0.25)

        logger.warning("Child did not stop gracefully; killing PID=%s", self.process.pid)
        try:
            self.process.kill()
        except Exception:
            pass

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def uptime_sec(self) -> int:
        if not self.started_at:
            return 0
        return int(time.time() - self.started_at)


def load_config() -> SupervisorConfig:
    project_root = Path(__file__).resolve().parent.parent
    child_script = project_root / "live" / "run_live_mtf_v2_entry_confirmed_v2.py"

    daily_enabled = _env_bool("SUPERVISOR_DAILY_ENABLED", True)
    daily_stop_hhmm = _parse_hhmm(os.getenv("SUPERVISOR_DAILY_STOP", ""), default=(23, 59))
    daily_restart_hhmm = _parse_hhmm(os.getenv("SUPERVISOR_DAILY_RESTART", ""), default=(0, 5))

    check_interval_sec = float(_env_int("SUPERVISOR_CHECK_INTERVAL_SEC", 10))
    restart_delay_sec = _env_int("SUPERVISOR_RESTART_DELAY_SEC", 5)
    min_uptime_before_restart_sec = _env_int("SUPERVISOR_MIN_UPTIME_SEC", 30)

    return SupervisorConfig(
        child_script=child_script,
        check_interval_sec=check_interval_sec,
        restart_delay_sec=restart_delay_sec,
        min_uptime_before_restart_sec=min_uptime_before_restart_sec,
        daily_enabled=daily_enabled,
        daily_stop_hhmm=daily_stop_hhmm,
        daily_restart_hhmm=daily_restart_hhmm,
    )


def main() -> int:
    _setup_logging()
    _load_env_file()

    cfg = load_config()
    logger.info("Supervisor config: child=%s", cfg.child_script)

    child = ChildProcess(cfg)

    def _handle_sigint(_sig, _frame):
        logger.info("SIGINT received - shutting down supervisor")
        child.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_sigint)

    child.start()

    while True:
        time.sleep(cfg.check_interval_sec)

        now = datetime.now().time()
        if cfg.daily_enabled and _in_downtime_window(now, cfg.daily_stop_hhmm, cfg.daily_restart_hhmm):
            if child.is_running():
                logger.info("In downtime window - stopping child")
                child.stop()
            sleep_sec = _seconds_until_next_local(cfg.daily_restart_hhmm)
            logger.info("Sleeping until restart time (%ss)", sleep_sec)
            time.sleep(max(1, sleep_sec))
            logger.info("Restart window reached - starting child")
            child.start()
            continue

        if not child.is_running():
            logger.warning("Child exited. Restarting in %ss", cfg.restart_delay_sec)
            time.sleep(cfg.restart_delay_sec)
            child.start()
            continue

        if child.uptime_sec() < cfg.min_uptime_before_restart_sec:
            continue


if __name__ == "__main__":
    raise SystemExit(main())
