"""
Trade Journal — append-only CSV logger for per-event signal/trade data.

Models live/live_bar_csv_logger.py: dataclass, Lock, _ensure_header, log_row.

Event types written by the strategy:
  SIGNAL         – generated signal before confirmation wait
  CONFIRM_WAIT   – pending signal stored, waiting for 1m confirmation
  CONFIRM_FAIL   – signal expired without confirmation
  CONFIRM_PASS   – signal confirmed, proceeding to order submission
  ORDER_SUBMIT   – bracket order submitted per position layer
  POSITION_CLOSE – position closed (exit fill received)

Columns (always written in this order; extras appended as None):
  event_type, timestamp_utc, bar_time, layer,
  side, confidence, threshold,
  atr, close_px,
  mama_diff, dmi_plus,
  meta_pass,
  sl_px, tp_px, entry_px, exit_px,
  quantity, exit_reason, pnl_usd, duration_bars,
  order_id
"""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any

COLUMNS = [
    "event_type",
    "timestamp_utc",
    "bar_time",
    "layer",
    "side",
    "confidence",
    "threshold",
    "atr",
    "close_px",
    "mama_diff",
    "dmi_plus",
    "meta_pass",
    "sl_px",
    "tp_px",
    "entry_px",
    "exit_px",
    "quantity",
    "exit_reason",
    "pnl_usd",
    "duration_bars",
    "order_id",
]


class TradeJournal:
    """Thread-safe, append-only CSV trade-event logger."""

    def __init__(self, path: str | os.PathLike = "logs/live_mtf/trade_journal.csv"):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._ensure_header()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(self, row: Dict[str, Any]) -> None:
        """Append one event row.  Unknown keys are silently ignored; missing
        columns are written as empty strings."""
        with self._lock:
            self._ensure_header()
            with self._path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
                # Fill mandatory timestamp if caller omitted it
                if "timestamp_utc" not in row or not row["timestamp_utc"]:
                    row = dict(row)
                    row["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
                writer.writerow({col: row.get(col, "") for col in COLUMNS})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_header(self) -> None:
        """Write CSV header once if the file does not yet exist or is empty."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists() or self._path.stat().st_size == 0:
            with self._path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=COLUMNS)
                writer.writeheader()
