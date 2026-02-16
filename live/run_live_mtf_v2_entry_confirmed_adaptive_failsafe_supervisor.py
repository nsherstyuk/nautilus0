"""Supervisor for Live MTF V2 Entry Confirmed ADAPTIVE with FAIL-SAFE Trading

This supervisor script manages the adaptive fail-safe entry-confirmed live runner with:
- Automatic restart on crashes
- Daily downtime window (11 PM - 12 AM EST for maintenance)
- Graceful shutdown handling
- Logging of all supervisor events
- Position protection verification and fail-safe logic
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

logger = logging.getLogger("live_v2_adaptive_failsafe_supervisor")


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
    max_short_restarts: int
    extended_delay_sec: int
    stability_reset_sec: int
    daily_enabled: bool
    daily_stop_hhmm: Tuple[int, int]
    daily_restart_hhmm: Tuple[int, int]


def _setup_logging() -> None:
    log_dir = Path("logs/live_mtf")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"supervisor_adaptive_failsafe_{run_id}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger.info("Supervisor logging initialized: %s", log_file)
    
    try:
        from utils.run_metadata import log_and_write_run_metadata
        log_and_write_run_metadata(
            logger,
            output_dir=log_dir,
            run_kind="live",
            run_id=run_id,
            entrypoint=__file__,
            extra={"logger": "live_v2_adaptive_failsafe_supervisor"},
        )
    except Exception:
        pass


class ChildProcess:
    def __init__(self, config: SupervisorConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.started_at: Optional[float] = None

    def start(self):
        if self.is_running():
            logger.warning("Child already running")
            return

        logger.info("Starting child: %s", self.config.child_script)
        
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(self.config.child_script)],
                cwd=self.config.child_script.parent.parent,
            )
            self.started_at = time.time()
            logger.info("Child started with PID %s", self.process.pid)
        except Exception as e:
            logger.error("Failed to start child: %s", e)
            self.process = None
            self.started_at = None

    def stop(self):
        if not self.is_running():
            return

        logger.info("Stopping child (PID %s)...", self.process.pid)
        
        try:
            self.process.terminate()
            
            for _ in range(10):
                if self.process.poll() is not None:
                    logger.info("Child terminated gracefully")
                    return
                time.sleep(0.5)
            
            logger.warning("Child did not terminate, sending SIGKILL")
            self.process.kill()
            self.process.wait(timeout=5)
            logger.info("Child killed")
        except Exception as e:
            logger.error("Error stopping child: %s", e)
        finally:
            self.process = None
            self.started_at = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def uptime_sec(self) -> int:
        if not self.started_at:
            return 0
        return int(time.time() - self.started_at)


def load_config() -> SupervisorConfig:
    project_root = Path(__file__).resolve().parent.parent
    child_script = project_root / "live" / "run_live_mtf_v2_entry_confirmed_adaptive_failsafe.py"

    daily_enabled = _env_bool("MTF2_SUPERVISOR_DAILY_ENABLED", True)
    daily_stop_hhmm = _parse_hhmm(os.getenv("MTF2_SUPERVISOR_DAILY_STOP_LOCAL", ""), default=(23, 30))
    daily_restart_hhmm = _parse_hhmm(os.getenv("MTF2_SUPERVISOR_DAILY_RESTART_LOCAL", ""), default=(1, 30))

    check_interval_sec = float(_env_int("MTF2_SUPERVISOR_CHECK_INTERVAL_SEC", 10))
    restart_delay_sec = _env_int("MTF2_SUPERVISOR_RESTART_DELAY_SEC", 120)
    min_uptime_before_restart_sec = _env_int("MTF2_SUPERVISOR_MIN_UPTIME_SEC", 180)
    max_short_restarts = _env_int("MTF2_SUPERVISOR_MAX_SHORT_RESTARTS", 3)
    extended_delay_sec = _env_int("MTF2_SUPERVISOR_EXTENDED_DELAY_SEC", 1800)
    stability_reset_sec = _env_int("MTF2_SUPERVISOR_STABILITY_RESET_SEC", 1800)

    return SupervisorConfig(
        child_script=child_script,
        check_interval_sec=check_interval_sec,
        restart_delay_sec=restart_delay_sec,
        min_uptime_before_restart_sec=min_uptime_before_restart_sec,
        max_short_restarts=max_short_restarts,
        extended_delay_sec=extended_delay_sec,
        stability_reset_sec=stability_reset_sec,
        daily_enabled=daily_enabled,
        daily_stop_hhmm=daily_stop_hhmm,
        daily_restart_hhmm=daily_restart_hhmm,
    )


def main() -> int:
    _setup_logging()
    _load_env_file()

    cfg = load_config()
    logger.info("Supervisor config: child=%s", cfg.child_script)
    logger.info("Daily downtime: enabled=%s stop=%s restart=%s", 
                cfg.daily_enabled, cfg.daily_stop_hhmm, cfg.daily_restart_hhmm)
    logger.info("Check interval: %ss, restart delay: %ss, min uptime: %ss",
                cfg.check_interval_sec, cfg.restart_delay_sec, cfg.min_uptime_before_restart_sec)
    logger.info(
        "Persistent failure backoff: max_short_restarts=%s extended_delay=%ss stability_reset=%ss",
        cfg.max_short_restarts,
        cfg.extended_delay_sec,
        cfg.stability_reset_sec,
    )

    child = ChildProcess(cfg)
    short_restart_count = 0
    stable_since: Optional[float] = None

    def _handle_shutdown(_sig, _frame):
        logger.info("Shutdown signal received - shutting down supervisor")
        child.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

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
            short_restart_count = 0
            stable_since = None
            continue

        if not child.is_running():
            uptime = child.uptime_sec()
            if uptime < cfg.min_uptime_before_restart_sec:
                short_restart_count += 1
                logger.warning(
                    "Child exited after short uptime (%ss). short_restart_count=%s/%s",
                    uptime,
                    short_restart_count,
                    cfg.max_short_restarts,
                )
            else:
                short_restart_count = 0

            delay = cfg.restart_delay_sec
            if cfg.max_short_restarts > 0 and short_restart_count >= cfg.max_short_restarts:
                delay = cfg.extended_delay_sec
                logger.warning(
                    "Applying extended restart delay due to repeated short exits: %ss",
                    delay,
                )

            logger.warning("Child exited. Restarting in %ss", delay)
            time.sleep(delay)
            child.start()
            stable_since = None
            continue

        if child.uptime_sec() < cfg.min_uptime_before_restart_sec:
            stable_since = None
            continue

        # If child has stayed up long enough, clear short-restart backoff state.
        if stable_since is None:
            stable_since = time.time()

        if short_restart_count > 0 and (time.time() - stable_since) >= cfg.stability_reset_sec:
            logger.info("Stability window reached - resetting short restart counter")
            short_restart_count = 0


if __name__ == "__main__":
    raise SystemExit(main())
