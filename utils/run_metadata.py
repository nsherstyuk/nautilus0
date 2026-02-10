from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_repo_root(start: Path | None = None) -> Path | None:
    candidate = (start or Path.cwd()).resolve()
    for parent in [candidate, *candidate.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _run_git(repo_root: Path, args: list[str], timeout_s: float = 2.0) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except Exception:
        return None

    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip()


def _get_git_metadata(repo_root: Path) -> dict[str, Any]:
    commit = _run_git(repo_root, ["rev-parse", "HEAD"])
    branch = _run_git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    describe = _run_git(repo_root, ["describe", "--always", "--dirty", "--tags"])
    status = _run_git(repo_root, ["status", "--porcelain"])

    dirty = bool(status)

    return {
        "repo_root": str(repo_root),
        "branch": branch,
        "commit": commit,
        "describe": describe,
        "dirty": dirty,
    }


def build_run_metadata(*, run_kind: str, entrypoint: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    repo_root = _find_repo_root(Path(entrypoint).resolve() if entrypoint else None)
    git_meta = _get_git_metadata(repo_root) if repo_root else {"repo_root": None, "branch": None, "commit": None, "describe": None, "dirty": None}

    metadata: dict[str, Any] = {
        "timestamp_utc": _utc_now_iso(),
        "run_kind": run_kind,
        "entrypoint": entrypoint,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "code": git_meta,
    }

    if extra:
        # Avoid accidentally serializing non-JSON types.
        safe_extra: dict[str, Any] = {}
        for key, value in extra.items():
            try:
                json.dumps(value)
                safe_extra[key] = value
            except Exception:
                safe_extra[key] = str(value)
        metadata["extra"] = safe_extra

    return metadata


def write_run_metadata(output_dir: Path, filename: str, metadata: dict[str, Any]) -> Path | None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / filename
        tmp = output_dir / f".{filename}.tmp"
        tmp.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(target)
        return target
    except Exception:
        return None


def log_and_write_run_metadata(
    logger: Any,
    *,
    output_dir: Path,
    run_kind: str,
    run_id: str,
    entrypoint: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Best-effort: logs git branch/commit and writes JSON metadata.

    This must never crash a live run/backtest.
    """
    if os.getenv("RUN_METADATA_DISABLE", "").strip().lower() in {"1", "true", "yes", "y", "on"}:
        return

    try:
        meta = build_run_metadata(run_kind=run_kind, entrypoint=entrypoint, extra=extra)
        code = meta.get("code") or {}
        logger.info(
            "CODE_VERSION run_kind=%s run_id=%s branch=%s commit=%s dirty=%s describe=%s",
            run_kind,
            run_id,
            code.get("branch"),
            code.get("commit"),
            code.get("dirty"),
            code.get("describe"),
        )

        written = write_run_metadata(output_dir, f"run_metadata_{run_kind}_{run_id}.json", meta)
        if written:
            logger.info("Run metadata written: %s", written)
        else:
            logger.warning("Run metadata not written (non-fatal)")
    except Exception:
        try:
            logger.exception("Failed to capture/write run metadata (non-fatal)")
        except Exception:
            # Last resort: swallow everything.
            return
