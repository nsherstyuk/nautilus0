from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict


@dataclass
class LiveBarCsvLogger:
    """Append-only CSV logger for live and warmup bars."""

    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def _ensure_header(self) -> None:
        if self.path.exists() and self.path.stat().st_size > 0:
            return
        with self.path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._header)
            writer.writeheader()

    def log_row(self, row: Dict[str, Any]) -> None:
        output: Dict[str, Any] = {k: row.get(k, "") for k in self._header}
        with self._lock:
            self._ensure_header()
            with self.path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._header)
                writer.writerow(output)

    @staticmethod
    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
