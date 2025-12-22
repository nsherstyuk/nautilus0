from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True)
    with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
    os.replace(tmp_path, path)


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=True, sort_keys=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


@dataclass
class Command:
    cmd_id: str
    ts_wall_utc: str
    command: str
    source: str
    notes: str = ""


class CommandReader:
    def __init__(self, commands_path: Path):
        self.commands_path = commands_path
        self._offset = 0

    def iter_new(self) -> Iterator[Command]:
        if not self.commands_path.exists():
            return
        with self.commands_path.open("r", encoding="utf-8") as f:
            f.seek(self._offset)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                cmd_id = str(obj.get("cmd_id", ""))
                ts_wall_utc = str(obj.get("ts_wall_utc", ""))
                command = str(obj.get("command", ""))
                source = str(obj.get("source", ""))
                notes = str(obj.get("notes", ""))

                if not cmd_id or not command:
                    continue

                yield Command(
                    cmd_id=cmd_id,
                    ts_wall_utc=ts_wall_utc,
                    command=command,
                    source=source,
                    notes=notes,
                )
            self._offset = f.tell()


def safe_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None
