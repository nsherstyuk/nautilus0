from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict
import re


@dataclass
class LiveBarCsvLogger:
    """Append-only CSV logger for live and warmup bars with partition/rotation support."""

    base_dir: Path
    partition_daily: bool = True
    max_file_mb: int = 128

    def __post_init__(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._header = [
            "time_utc",
            "received_at_utc",
            "symbol",
            "bar_size",
            "what_to_show",
            "use_rth",
            "source",
            "is_warmup",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "subscription_key",
        ]

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())

    def _resolve_target_path(self, row: Dict[str, Any]) -> Path:
        symbol = self._safe_name(str(row.get("symbol", "UNKNOWN"))).replace("/", "_")
        bar_size = self._safe_name(str(row.get("bar_size", "unknown"))).replace(" ", "")
        what_to_show = self._safe_name(str(row.get("what_to_show", "unknown")) )
        use_rth = str(int(bool(row.get("use_rth", 0))))

        date_part = None
        raw_ts = str(row.get("time_utc", "")).strip()
        try:
            dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            dt = dt.astimezone(timezone.utc)
            date_part = dt.strftime("%Y-%m-%d")
        except Exception:
            date_part = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if self.partition_daily:
            target_dir = self.base_dir / date_part
        else:
            target_dir = self.base_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        stem = f"{symbol}_{bar_size}_{what_to_show}_rth{use_rth}"
        max_bytes = max(1, int(self.max_file_mb)) * 1024 * 1024

        for idx in range(1, 10000):
            suffix = "" if idx == 1 else f"_part{idx:03d}"
            candidate = target_dir / f"{stem}{suffix}.csv"
            if not candidate.exists():
                return candidate
            try:
                if candidate.stat().st_size < max_bytes:
                    return candidate
            except Exception:
                return candidate

        return target_dir / f"{stem}_part9999.csv"

    def _ensure_header(self, path: Path) -> None:
        if path.exists() and path.stat().st_size > 0:
            return
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._header)
            writer.writeheader()

    def log_row(self, row: Dict[str, Any]) -> None:
        output: Dict[str, Any] = {k: row.get(k, "") for k in self._header}
        with self._lock:
            target_path = self._resolve_target_path(output)
            self._ensure_header(target_path)
            with target_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._header)
                writer.writerow(output)

    @staticmethod
    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
