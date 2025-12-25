from __future__ import annotations

import argparse
import csv
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional


TS_5M_COL = "ts_5m_close"
TS_MASTER_COL = "ts_master_15m_close"


def _parse_iso(ts: str) -> Optional[datetime]:
    ts = ts.strip()
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _is_missing(v: str) -> bool:
    v = (v or "").strip()
    return v == "" or v.lower() == "nan" or v.lower() == "none"


def _floor_to_15m(ts: datetime) -> datetime:
    # Preserve tzinfo; only align minutes/seconds.
    minute = ts.minute - (ts.minute % 15)
    return ts.replace(minute=minute, second=0, microsecond=0)


def _is_aligned(ts: datetime, minutes: int) -> bool:
    return ts.second == 0 and ts.microsecond == 0 and (ts.minute % minutes) == 0


@dataclass
class RunningStats:
    count: int = 0
    nan_count: int = 0
    bad_count: int = 0
    sum: float = 0.0
    min: float = float("inf")
    max: float = float("-inf")

    def add(self, raw: str) -> None:
        raw = (raw or "").strip()
        if _is_missing(raw):
            self.nan_count += 1
            return
        try:
            x = float(raw)
        except Exception:
            self.bad_count += 1
            return
        if x != x:  # NaN
            self.nan_count += 1
            return
        self.count += 1
        self.sum += x
        if x < self.min:
            self.min = x
        if x > self.max:
            self.max = x

    @property
    def mean(self) -> float:
        return (self.sum / self.count) if self.count else float("nan")


@dataclass
class AuditResult:
    path: Path
    rows: int = 0
    fieldnames: list[str] = field(default_factory=list)
    missing_by_col: Dict[str, int] = field(default_factory=dict)
    parse_fail_ts5: int = 0
    parse_fail_master: int = 0

    ts5_nonmonotonic: int = 0
    ts5_duplicates: int = 0
    ts5_step_ok: int = 0
    ts5_step_short: int = 0
    ts5_step_long: int = 0
    ts5_gap_big: int = 0
    ts5_max_gap_seconds: float = 0.0

    ts5_alignment_bad: int = 0
    master_alignment_bad: int = 0
    master_lookahead_violations: int = 0

    master_nonmonotonic: int = 0
    master_step_bad: int = 0
    master_unique: int = 0
    master_age_buckets: Dict[str, int] = field(default_factory=dict)

    master_expected_match: int = 0
    master_expected_late_by_15m: int = 0
    master_expected_other_mismatch: int = 0

    plateau_len_hist: Dict[int, int] = field(default_factory=dict)
    plateau_len_bad: int = 0
    plateau_total: int = 0

    numeric_stats: Dict[str, RunningStats] = field(default_factory=dict)


def audit_dataset(path: Path, *, max_rows: Optional[int] = None) -> AuditResult:
    if not path.exists():
        raise FileNotFoundError(str(path))

    missing: Counter[str] = Counter()
    parse_fail_ts5 = 0
    parse_fail_master = 0

    last_ts5: Optional[datetime] = None
    last_master: Optional[datetime] = None
    seen_master: set[str] = set()

    # Plateau tracking: consecutive 5m rows that share the same master close.
    plateau_master: Optional[datetime] = None
    plateau_len = 0
    plateau_len_hist: Counter[int] = Counter()
    plateau_len_bad = 0
    plateau_total = 0

    # 5m cadence thresholds
    target_5m = 300.0
    tol = 1.0
    big_gap = 6 * 60.0

    ts5_nonmonotonic = 0
    ts5_duplicates = 0
    ts5_step_ok = 0
    ts5_step_short = 0
    ts5_step_long = 0
    ts5_gap_big = 0
    ts5_max_gap_seconds = 0.0

    ts5_alignment_bad = 0
    master_alignment_bad = 0
    master_lookahead_violations = 0

    master_nonmonotonic = 0
    master_step_bad = 0

    master_age_buckets: Counter[str] = Counter()
    master_expected_match = 0
    master_expected_late_by_15m = 0
    master_expected_other_mismatch = 0

    numeric_cols: Iterable[str] = (
        "last_15m_prediction",
        "atr_15m",
        "macro_permission",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "rsi_5m",
        "macd_5m",
        "macd_signal_5m",
        "macd_hist_5m",
        "bb_width_5m",
        "body_5m",
        "upper_wick_5m",
        "lower_wick_5m",
    )
    stats: Dict[str, RunningStats] = {c: RunningStats() for c in numeric_cols}

    rows = 0
    fieldnames: list[str] = []

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header")
        fieldnames = list(reader.fieldnames)

        for row in reader:
            rows += 1
            if max_rows is not None and rows > max_rows:
                break

            for k in fieldnames:
                v = row.get(k) or ""
                if _is_missing(v):
                    missing[k] += 1

            ts5_raw = row.get(TS_5M_COL) or ""
            master_raw = row.get(TS_MASTER_COL) or ""
            ts5 = _parse_iso(ts5_raw)
            tsm = _parse_iso(master_raw)
            if ts5 is None:
                parse_fail_ts5 += 1
            if tsm is None:
                parse_fail_master += 1

            if ts5 is not None and not _is_aligned(ts5, 5):
                ts5_alignment_bad += 1
            if tsm is not None and not _is_aligned(tsm, 15):
                master_alignment_bad += 1

            # 5m monotonic + cadence checks
            if ts5 is not None and last_ts5 is not None:
                dt = (ts5 - last_ts5).total_seconds()
                if dt < 0:
                    ts5_nonmonotonic += 1
                elif dt == 0:
                    ts5_duplicates += 1
                else:
                    if abs(dt - target_5m) <= tol:
                        ts5_step_ok += 1
                    elif dt < target_5m - tol:
                        ts5_step_short += 1
                    else:
                        ts5_step_long += 1
                    if dt > big_gap:
                        ts5_gap_big += 1
                        if dt > ts5_max_gap_seconds:
                            ts5_max_gap_seconds = dt
            if ts5 is not None:
                last_ts5 = ts5

            # Master checks
            if tsm is not None:
                seen_master.add(tsm.isoformat())

                if ts5 is not None and tsm > ts5:
                    master_lookahead_violations += 1

                if last_master is not None:
                    dmt = (tsm - last_master).total_seconds()
                    if dmt < 0:
                        master_nonmonotonic += 1
                    # If it changes, it should change by 15 minutes.
                    if dmt != 0 and abs(dmt - 900.0) > tol:
                        master_step_bad += 1
                last_master = tsm

                # Expected master-asof mapping
                if ts5 is not None:
                    expected = _floor_to_15m(ts5)
                    if tsm == expected:
                        master_expected_match += 1
                    elif tsm == (expected - timedelta(minutes=15)):
                        master_expected_late_by_15m += 1
                    else:
                        master_expected_other_mismatch += 1

                    age_min = (ts5 - tsm).total_seconds() / 60.0
                    if age_min < 0:
                        master_age_buckets["<0"] += 1
                    elif age_min <= 2.5:
                        master_age_buckets["~0"] += 1
                    elif age_min <= 7.5:
                        master_age_buckets["~5"] += 1
                    elif age_min <= 12.5:
                        master_age_buckets["~10"] += 1
                    elif age_min <= 17.5:
                        master_age_buckets["~15"] += 1
                    else:
                        master_age_buckets[">15"] += 1

            # Plateau histogram for tsm (requires at least a parsed tsm)
            if tsm is not None:
                if plateau_master is None:
                    plateau_master = tsm
                    plateau_len = 1
                elif tsm == plateau_master:
                    plateau_len += 1
                else:
                    plateau_len_hist[plateau_len] += 1
                    plateau_total += 1
                    if plateau_len not in (3,):
                        plateau_len_bad += 1
                    plateau_master = tsm
                    plateau_len = 1

            # Numeric stats (best-effort)
            for col, s in stats.items():
                s.add(row.get(col) or "")

    # close plateau
    if plateau_master is not None and plateau_len > 0:
        plateau_len_hist[plateau_len] += 1
        plateau_total += 1
        if plateau_len not in (3,):
            plateau_len_bad += 1

    return AuditResult(
        path=path,
        rows=rows,
        fieldnames=fieldnames,
        missing_by_col=dict(missing),
        parse_fail_ts5=parse_fail_ts5,
        parse_fail_master=parse_fail_master,
        ts5_nonmonotonic=ts5_nonmonotonic,
        ts5_duplicates=ts5_duplicates,
        ts5_step_ok=ts5_step_ok,
        ts5_step_short=ts5_step_short,
        ts5_step_long=ts5_step_long,
        ts5_gap_big=ts5_gap_big,
        ts5_max_gap_seconds=ts5_max_gap_seconds,
        ts5_alignment_bad=ts5_alignment_bad,
        master_alignment_bad=master_alignment_bad,
        master_lookahead_violations=master_lookahead_violations,
        master_nonmonotonic=master_nonmonotonic,
        master_step_bad=master_step_bad,
        master_unique=len(seen_master),
        master_age_buckets=dict(master_age_buckets),
        master_expected_match=master_expected_match,
        master_expected_late_by_15m=master_expected_late_by_15m,
        master_expected_other_mismatch=master_expected_other_mismatch,
        plateau_len_hist=dict(plateau_len_hist),
        plateau_len_bad=plateau_len_bad,
        plateau_total=plateau_total,
        numeric_stats=stats,
    )


def _print_top_missing(missing_by_col: Dict[str, int], *, top: int = 25) -> None:
    shown = 0
    for k, v in sorted(missing_by_col.items(), key=lambda kv: kv[1], reverse=True):
        if v <= 0:
            continue
        print(f"  {k}: {v}")
        shown += 1
        if shown >= top:
            break
    if shown == 0:
        print("  (none)")


def _print_stats(stats: Dict[str, RunningStats]) -> None:
    for col in sorted(stats.keys()):
        s = stats[col]
        print(
            f"  {col}: n={s.count} nan={s.nan_count} bad={s.bad_count} "
            f"min={s.min if s.count else float('nan'):.6g} "
            f"max={s.max if s.count else float('nan'):.6g} mean={s.mean:.6g}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Audit stitched HMTF 5m dataset for correctness and quality")
    p.add_argument(
        "path_positional",
        nargs="?",
        default=None,
        help="CSV path (positional alternative to --path)",
    )
    p.add_argument(
        "--path",
        default=os.getenv("MTF3_DATASET_PATH", "logs/live_mtf/hmtf_5m_dataset.csv"),
        help="CSV path (default: env MTF3_DATASET_PATH or logs/live_mtf/hmtf_5m_dataset.csv)",
    )
    p.add_argument("--max-rows", type=int, default=0, help="Limit rows processed (0 = all)")
    args = p.parse_args(argv)

    path = Path(args.path_positional or args.path)
    max_rows = None if args.max_rows <= 0 else args.max_rows
    res = audit_dataset(path, max_rows=max_rows)

    required_cols = {
        TS_5M_COL,
        TS_MASTER_COL,
        "last_15m_prediction",
        "atr_15m",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    missing_required = sorted([c for c in required_cols if c not in set(res.fieldnames)])

    print("=" * 72)
    print("HMTF DATASET AUDIT")
    print("=" * 72)
    print(f"Path: {res.path}")
    print(f"Rows processed: {res.rows}")
    if max_rows is not None:
        print(f"(Limited to first {max_rows} rows)")
    print(f"Columns: {len(res.fieldnames)}")
    if missing_required:
        print(f"Missing required columns: {missing_required}")
    else:
        print("Required columns: OK")

    print("\nTimestamp parsing:")
    print(f"  {TS_5M_COL} parse failures: {res.parse_fail_ts5}")
    print(f"  {TS_MASTER_COL} parse failures: {res.parse_fail_master}")

    print("\n5m cadence:")
    print(f"  Non-monotonic (backwards): {res.ts5_nonmonotonic}")
    print(f"  Duplicates: {res.ts5_duplicates}")
    print(f"  Step OK (~300s): {res.ts5_step_ok}")
    print(f"  Step short: {res.ts5_step_short}")
    print(f"  Step long: {res.ts5_step_long}")
    print(f"  Big gaps (>6m): {res.ts5_gap_big} (max_gap_s={res.ts5_max_gap_seconds:.1f})")
    print(f"  5m alignment bad (minute%5/seconds): {res.ts5_alignment_bad}")

    print("\n15m master stitching:")
    print(f"  Unique master closes: {res.master_unique}")
    print(f"  Master non-monotonic: {res.master_nonmonotonic}")
    print(f"  Master step != 15m: {res.master_step_bad}")
    print(f"  Master alignment bad (minute%15/seconds): {res.master_alignment_bad}")
    print(f"  LOOKAHEAD violations (master > 5m): {res.master_lookahead_violations}")
    total_master_mapped = res.master_expected_match + res.master_expected_late_by_15m + res.master_expected_other_mismatch
    if total_master_mapped:
        print(
            "  Expected master-asof mapping vs floor(ts_5m,15m): "
            f"match={res.master_expected_match} "
            f"late_by_15m={res.master_expected_late_by_15m} "
            f"other_mismatch={res.master_expected_other_mismatch}"
        )
    else:
        print("  Expected master-asof mapping: (no comparable rows)")
    if res.master_age_buckets:
        print(f"  Master age buckets (minutes): {dict(sorted(res.master_age_buckets.items()))}")

    if res.plateau_total:
        print("\nPlateau lengths (consecutive 5m rows per master close):")
        print(f"  Total plateaus: {res.plateau_total}")
        print(f"  Bad plateaus (!=3): {res.plateau_len_bad}")
        print(f"  Histogram: {dict(sorted(res.plateau_len_hist.items()))}")

    print("\nMissing values by column (top 25):")
    _print_top_missing(res.missing_by_col, top=25)

    print("\nNumeric column stats (best-effort):")
    _print_stats(res.numeric_stats)

    # Exit code: fail only on correctness issues, not on missing indicators.
    correctness_fail = (
        bool(missing_required)
        or res.master_lookahead_violations > 0
        or res.ts5_nonmonotonic > 0
        or res.master_nonmonotonic > 0
    )
    if correctness_fail:
        print("\nRESULT: FAIL (correctness issues detected)")
        return 2
    print("\nRESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
