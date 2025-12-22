"""Supervisor for the dashboard-enabled MTF V2 live runner.

This script starts `live/run_live_mtf_v2_dashboard.py` as a child process and
automatically restarts it:
- On a daily scheduled downtime window (e.g. stop at 23:59, restart at 00:05)
- When the child appears unhealthy (stale bar data / disconnected)

The original live runner is not modified.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv

logger = logging.getLogger("live_v2_dashboard_supervisor")


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
    # Treat any remaining whitespace as separator (common in .env with inline notes)
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

    # If the restart time is after stop time, window is [stop, restart).
    if stop_t < restart_t:
        return stop_t <= now_local < restart_t

    # Typical case: stop before midnight, restart after midnight.
    # Window is [stop, 24h) U [0, restart).
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

    stale_enabled: bool
    stale_max_bar_age_sec: int
    stale_max_status_age_sec: int
    stale_consecutive_fail_checks: int


def _load_config() -> SupervisorConfig:
    project_root = Path(__file__).resolve().parent.parent
    child_script = project_root / "live" / "run_live_mtf_v2_dashboard.py"

    cfg = SupervisorConfig(
        child_script=child_script,
        check_interval_sec=float(_env_int("MTF2_SUPERVISOR_CHECK_INTERVAL_SEC", 5)),
        restart_delay_sec=_env_int("MTF2_SUPERVISOR_RESTART_DELAY_SEC", 120),
        min_uptime_before_restart_sec=_env_int("MTF2_SUPERVISOR_MIN_UPTIME_SEC", 180),
        daily_enabled=_env_bool("MTF2_SUPERVISOR_DAILY_ENABLED", True),
        daily_stop_hhmm=_parse_hhmm(os.getenv("MTF2_SUPERVISOR_DAILY_STOP_LOCAL", "23:59"), (23, 59)),
        daily_restart_hhmm=_parse_hhmm(os.getenv("MTF2_SUPERVISOR_DAILY_RESTART_LOCAL", "00:05"), (0, 5)),
        stale_enabled=_env_bool("MTF2_SUPERVISOR_STALE_ENABLED", True),
        stale_max_bar_age_sec=_env_int("MTF2_SUPERVISOR_STALE_MAX_BAR_AGE_SEC", 25 * 60),
        stale_max_status_age_sec=_env_int("MTF2_SUPERVISOR_STALE_MAX_STATUS_AGE_SEC", 90),
        stale_consecutive_fail_checks=_env_int("MTF2_SUPERVISOR_STALE_CONSEC_FAILS", 3),
    )
    return cfg


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _status_age_seconds(path: Path) -> Optional[float]:
    try:
        mtime = path.stat().st_mtime
    except Exception:
        return None
    return max(0.0, time.time() - float(mtime))


def _spawn_child(cfg: SupervisorConfig) -> subprocess.Popen:
    if not cfg.child_script.exists():
        raise FileNotFoundError(str(cfg.child_script))

    args = [sys.executable, "-u", str(cfg.child_script)]

    creationflags = 0
    try:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    except Exception:
        creationflags = 0

    logger.info("Starting child: %s", " ".join(args))

    return subprocess.Popen(
        args,
        creationflags=creationflags,
        env=os.environ.copy(),
    )


def _graceful_stop_child(proc: subprocess.Popen, grace_sec: int) -> None:
    if proc.poll() is not None:
        return

    logger.info("Stopping child process (pid=%s)...", proc.pid)

    signaled = False

    # Try console break (best effort on Windows)
    try:
        proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        signaled = True
        logger.info("Sent CTRL_BREAK_EVENT to child")
    except Exception:
        signaled = False

    # Fallback: terminate (less graceful)
    if not signaled:
        try:
            proc.terminate()
            logger.info("Sent terminate() to child")
        except Exception:
            pass

    try:
        proc.wait(timeout=float(grace_sec))
        logger.info("Child stopped")
        return
    except Exception:
        logger.warning("Child did not stop within %ss; killing...", grace_sec)

    try:
        proc.kill()
    except Exception:
        pass

    try:
        proc.wait(timeout=10.0)
    except Exception:
        pass


def main() -> int:
    _setup_logging()
    _load_env_file()
    cfg = _load_config()

    if not cfg.child_script.exists():
        logger.error("Child script not found: %s", cfg.child_script)
        return 1

    status_path = Path("logs/live_mtf/status.json")

    proc: Optional[subprocess.Popen] = None
    last_start_ts = 0.0
    stale_fail_count = 0

    logger.info(
        "Supervisor active. Child=%s daily_enabled=%s stop=%02d:%02d restart=%02d:%02d stale_enabled=%s",
        cfg.child_script,
        cfg.daily_enabled,
        cfg.daily_stop_hhmm[0],
        cfg.daily_stop_hhmm[1],
        cfg.daily_restart_hhmm[0],
        cfg.daily_restart_hhmm[1],
        cfg.stale_enabled,
    )

    try:
        while True:
            now_local = datetime.now()

            # Scheduled downtime window
            if cfg.daily_enabled and _in_downtime_window(now_local.time(), cfg.daily_stop_hhmm, cfg.daily_restart_hhmm):
                if proc is not None and proc.poll() is None:
                    logger.info(
                        "Scheduled downtime window active (stop=%02d:%02d, restart=%02d:%02d). Stopping child.",
                        cfg.daily_stop_hhmm[0],
                        cfg.daily_stop_hhmm[1],
                        cfg.daily_restart_hhmm[0],
                        cfg.daily_restart_hhmm[1],
                    )
                    _graceful_stop_child(proc, grace_sec=30)
                    proc = None

                sleep_sec = _seconds_until_next_local(cfg.daily_restart_hhmm)
                logger.info("Sleeping %ss until scheduled restart time...", sleep_sec)
                time.sleep(max(1, sleep_sec))
                continue

            # Start child if needed
            if proc is None or proc.poll() is not None:
                if proc is not None and proc.poll() is not None:
                    logger.warning("Child exited with code %s. Restarting after %ss...", proc.returncode, cfg.restart_delay_sec)
                    time.sleep(max(1, cfg.restart_delay_sec))

                proc = _spawn_child(cfg)
                last_start_ts = time.time()
                stale_fail_count = 0

            # Stale / disconnect monitoring (via status.json)
            if cfg.stale_enabled:
                uptime = time.time() - last_start_ts
                if uptime >= float(cfg.min_uptime_before_restart_sec):
                    status_age = _status_age_seconds(status_path)
                    status = _read_json(status_path) if status_path.exists() else None

                    ib_connected = None
                    bar_age = None

                    if status is not None:
                        try:
                            conn = status.get("connection") or {}
                            ib_connected = bool(conn.get("ib_connected"))
                            bar_age_raw = conn.get("bar_age_sec")
                            bar_age = float(bar_age_raw) if bar_age_raw is not None else None
                        except Exception:
                            ib_connected = None
                            bar_age = None

                    unhealthy = False

                    if status_age is None or status_age > float(cfg.stale_max_status_age_sec):
                        unhealthy = True
                        reason = f"status_stale age_sec={status_age}"
                    elif ib_connected is False:
                        unhealthy = True
                        reason = "ib_disconnected"
                    elif bar_age is not None and bar_age > float(cfg.stale_max_bar_age_sec):
                        unhealthy = True
                        reason = f"bar_stale age_sec={bar_age:.1f}"
                    else:
                        reason = ""

                    if unhealthy:
                        stale_fail_count += 1
                        logger.warning(
                            "Health check unhealthy (%s). count=%s/%s",
                            reason,
                            stale_fail_count,
                            cfg.stale_consecutive_fail_checks,
                        )
                    else:
                        stale_fail_count = 0

                    if stale_fail_count >= int(cfg.stale_consecutive_fail_checks):
                        logger.warning(
                            "Restarting child due to repeated unhealthy status (%s). Stopping child...",
                            reason,
                        )
                        _graceful_stop_child(proc, grace_sec=30)
                        proc = None
                        stale_fail_count = 0
                        logger.info("Waiting %ss before restart...", cfg.restart_delay_sec)
                        time.sleep(max(1, cfg.restart_delay_sec))
                        continue

            time.sleep(float(cfg.check_interval_sec))

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received; stopping supervisor.")
        return 0
    finally:
        if proc is not None and proc.poll() is None:
            _graceful_stop_child(proc, grace_sec=30)

    return 0


if __name__ == "__main__":
    sys.exit(main())
