from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


@dataclass
class AuditResult:
    rows: int
    missing_by_col: Dict[str, int]
    master_step_ok: int
    master_step_bad: int
    master_unique: int
    five_min_gaps: int


def audit_dataset(path: Path) -> AuditResult:
    if not path.exists():
        raise FileNotFoundError(str(path))

    missing: Counter[str] = Counter()
    rows = 0

    last_5m: Optional[datetime] = None
    five_min_gaps = 0

    last_master: Optional[datetime] = None
    master_step_ok = 0
    master_step_bad = 0
    master_values: set[str] = set()

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header")

        for row in reader:
            rows += 1

            for k in reader.fieldnames:
                v = (row.get(k) or "").strip()
                if v == "" or v.lower() == "nan":
                    missing[k] += 1

            ts5 = _parse_iso((row.get("ts_5m_close") or "").strip())
            tsm = _parse_iso((row.get("ts_master_15m_close") or "").strip())
            if tsm is not None:
                master_values.add(tsm.isoformat())

            # 5m gaps check
            if ts5 is not None:
                if last_5m is not None:
                    dt = (ts5 - last_5m).total_seconds()
                    # tolerate small drift; flag big gaps
                    if dt > 6 * 60:
                        five_min_gaps += 1
                last_5m = ts5

            # master stitching check: master timestamps should be non-decreasing
            if tsm is not None:
                if last_master is not None:
                    dtm = (tsm - last_master).total_seconds()
                    if dtm < 0:
                        master_step_bad += 1
                    else:
                        master_step_ok += 1
                last_master = tsm

    return AuditResult(
        rows=rows,
        missing_by_col=dict(missing),
        master_step_ok=master_step_ok,
        master_step_bad=master_step_bad,
        master_unique=len(master_values),
        five_min_gaps=five_min_gaps,
    )


def main() -> int:
    default_path = os.getenv("MTF3_DATASET_PATH", "logs/live_mtf/hmtf_5m_dataset.csv")
    path = Path(default_path)

    res = audit_dataset(path)

    print("=" * 72)
    print("HMTF DATASET AUDIT")
    print("=" * 72)
    print(f"Path: {path}")
    print(f"Rows: {res.rows}")
    print(f"Unique 15m master timestamps: {res.master_unique}")
    print(f"Master timestamp monotonic OK: {res.master_step_ok}")
    print(f"Master timestamp monotonic BAD: {res.master_step_bad}")
    print(f"5m gap flags (>6min): {res.five_min_gaps}")

    print("\nMissing values by column (top 25):")
    for k, v in sorted(res.missing_by_col.items(), key=lambda kv: kv[1], reverse=True)[:25]:
        if v:
            print(f"  {k}: {v}")

    print("\nDone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
