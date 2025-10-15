"""
Utility script to inspect the NautilusTrader ParquetDataCatalog.

This script loads the catalog located at ``data/historical`` and prints:
- Instruments registered in the catalog and their bar types (datasets).
- Bar counts and date ranges per bar type.
- Validation that the bar spec strings include the required ``-EXTERNAL`` suffix
  for historical datasets (NautilusTrader v1.220.0+).

Usage:
    python data/verify_catalog.py [catalog_path]

If ``catalog_path`` is omitted, ``data/historical`` is used.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow.parquet as pq
from dotenv import load_dotenv

try:
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
    from nautilus_trader.model.data import Bar
except ImportError as exc:
    print("Error: NautilusTrader is not installed in this environment.")
    print(f"Details: {exc}")
    sys.exit(1)

EXPECTED_SUFFIX = "-EXTERNAL"


@dataclass
class CatalogBarSummary:
    instrument_id: str
    bar_type: str
    bar_count: int
    start_ts: pd.Timestamp | None
    end_ts: pd.Timestamp | None

    def format_summary(self) -> str:
        if self.bar_count == 0 or self.start_ts is None or self.end_ts is None:
            return f"{self.bar_type}: 0 bars"
        return (
            f"{self.bar_type}: {self.bar_count:,} bars"
            f" ({self.start_ts.date()} to {self.end_ts.date()})"
        )

    def has_expected_suffix(self) -> bool:
        return self.bar_type.endswith(EXPECTED_SUFFIX)


def collect_bar_summaries(catalog: ParquetDataCatalog) -> list[CatalogBarSummary]:
    """Collect bar counts and date ranges grouped by instrument and bar type."""
    catalog_root = Path(catalog.path)
    bar_root = catalog_root / "data" / "bar"
    if not bar_root.exists():
        return []

    summaries: list[CatalogBarSummary] = []

    for dataset_dir in sorted(bar_root.iterdir()):
        if not dataset_dir.is_dir():
            continue

        bar_type = dataset_dir.name
        instrument_id = bar_type.split("-", 1)[0] if "-" in bar_type else "UNKNOWN"

        total_rows = 0
        min_ts: int | None = None
        max_ts: int | None = None

        parquet_files = sorted(dataset_dir.glob("*.parquet"))
        for parquet_file in parquet_files:
            try:
                metadata = pq.read_metadata(parquet_file)
            except Exception:  # noqa: BLE001
                continue

            total_rows += metadata.num_rows

            ts_column_name = None
            for candidate in ("ts_init", "ts_event"):
                if candidate in metadata.schema.names:
                    ts_column_name = candidate
                    break
            if ts_column_name is None:
                continue

            ts_index = metadata.schema.names.index(ts_column_name)

            for rg_index in range(metadata.num_row_groups):
                column = metadata.row_group(rg_index).column(ts_index)
                stats = column.statistics
                if stats is None:
                    continue

                rg_min = stats.min
                rg_max = stats.max

                if isinstance(rg_min, (bytes, bytearray)):
                    rg_min = int.from_bytes(rg_min, byteorder="little", signed=True)
                if isinstance(rg_max, (bytes, bytearray)):
                    rg_max = int.from_bytes(rg_max, byteorder="little", signed=True)

                if min_ts is None or (rg_min is not None and rg_min < min_ts):
                    min_ts = rg_min
                if max_ts is None or (rg_max is not None and rg_max > max_ts):
                    max_ts = rg_max

        start_ts = pd.to_datetime(min_ts, unit="ns", utc=True) if min_ts is not None else None
        end_ts = pd.to_datetime(max_ts, unit="ns", utc=True) if max_ts is not None else None

        summaries.append(
            CatalogBarSummary(
                instrument_id=instrument_id,
                bar_type=bar_type,
                bar_count=total_rows,
                start_ts=start_ts,
                end_ts=end_ts,
            )
        )

    return sorted(summaries, key=lambda s: (s.instrument_id, s.bar_type))


def group_by_instrument(summaries: Iterable[CatalogBarSummary]) -> dict[str, list[CatalogBarSummary]]:
    grouped: dict[str, list[CatalogBarSummary]] = defaultdict(list)
    for summary in summaries:
        grouped[summary.instrument_id].append(summary)
    return dict(sorted(grouped.items()))


def summarize_catalog(summaries: list[CatalogBarSummary]) -> dict[str, object]:
    instrument_groups = group_by_instrument(summaries)
    total_bars = sum(summary.bar_count for summary in summaries)
    earliest = None
    latest = None

    for summary in summaries:
        if summary.start_ts is not None:
            earliest = summary.start_ts if earliest is None else min(earliest, summary.start_ts)
        if summary.end_ts is not None:
            latest = summary.end_ts if latest is None else max(latest, summary.end_ts)

    return {
        "instrument_count": len(instrument_groups),
        "bar_type_count": len(summaries),
        "total_bars": total_bars,
        "coverage": {
            "earliest": earliest.isoformat() if earliest is not None else None,
            "latest": latest.isoformat() if latest is not None else None,
        },
    }


def check_date_overlap(
    summaries: list[CatalogBarSummary],
    target_start: str | None,
    target_end: str | None,
) -> list[dict[str, object]]:
    if not target_start or not target_end:
        return []

    try:
        start = pd.to_datetime(target_start)
        end = pd.to_datetime(target_end)
    except ValueError:
        return []

    if start.tz is None:
        start = start.tz_localize("UTC")
    if end.tz is None:
        end = end.tz_localize("UTC")

    overlaps: list[dict[str, object]] = []
    for summary in summaries:
        if summary.start_ts is None or summary.end_ts is None:
            continue
        summary_start = summary.start_ts.tz_localize("UTC") if summary.start_ts.tzinfo is None else summary.start_ts
        summary_end = summary.end_ts.tz_localize("UTC") if summary.end_ts.tzinfo is None else summary.end_ts
        if summary_end >= start and summary_start <= end:
            overlaps.append(
                {
                    "instrument_id": summary.instrument_id,
                    "bar_type": summary.bar_type,
                    "start": summary_start.isoformat(),
                    "end": summary_end.isoformat(),
                }
            )
    return overlaps


def check_interval_overlaps(catalog: ParquetDataCatalog) -> list[dict[str, object]]:
    """Check for overlapping time intervals within each bar type's Parquet files."""
    catalog_root = Path(catalog.path)
    bar_root = catalog_root / "data" / "bar"
    if not bar_root.exists():
        return []

    overlaps: list[dict[str, object]] = []

    for dataset_dir in sorted(bar_root.iterdir()):
        if not dataset_dir.is_dir():
            continue

        bar_type = dataset_dir.name
        instrument_id = bar_type.split("-", 1)[0] if "-" in bar_type else "UNKNOWN"

        # Collect file intervals
        file_intervals = []
        parquet_files = sorted(dataset_dir.glob("*.parquet"))
        
        for parquet_file in parquet_files:
            try:
                metadata = pq.read_metadata(parquet_file)
            except Exception:  # noqa: BLE001
                continue

            # Find timestamp column
            ts_column_name = None
            for candidate in ("ts_init", "ts_event"):
                if candidate in metadata.schema.names:
                    ts_column_name = candidate
                    break
            if ts_column_name is None:
                continue

            ts_index = metadata.schema.names.index(ts_column_name)

            # Get min/max timestamps from all row groups
            min_ts: int | None = None
            max_ts: int | None = None

            for rg_index in range(metadata.num_row_groups):
                column = metadata.row_group(rg_index).column(ts_index)
                stats = column.statistics
                if stats is None:
                    continue

                rg_min = stats.min
                rg_max = stats.max

                if isinstance(rg_min, (bytes, bytearray)):
                    rg_min = int.from_bytes(rg_min, byteorder="little", signed=True)
                if isinstance(rg_max, (bytes, bytearray)):
                    rg_max = int.from_bytes(rg_max, byteorder="little", signed=True)

                if min_ts is None or (rg_min is not None and rg_min < min_ts):
                    min_ts = rg_min
                if max_ts is None or (rg_max is not None and rg_max > max_ts):
                    max_ts = rg_max

            if min_ts is not None and max_ts is not None:
                file_intervals.append({
                    "file_path": str(parquet_file.relative_to(catalog_root)),
                    "start_ts": min_ts,
                    "end_ts": max_ts,
                })

        # Sort by start timestamp
        file_intervals.sort(key=lambda x: x["start_ts"])

        # Check for overlaps between adjacent files
        for i in range(len(file_intervals) - 1):
            current_file = file_intervals[i]
            next_file = file_intervals[i + 1]
            
            if current_file["end_ts"] >= next_file["start_ts"]:
                # Calculate overlap duration
                overlap_start = max(current_file["start_ts"], next_file["start_ts"])
                overlap_end = min(current_file["end_ts"], next_file["end_ts"])
                overlap_duration_ns = overlap_end - overlap_start

                # Only record overlaps with positive duration
                if overlap_duration_ns > 0:
                    # Convert timestamps to ISO format
                    current_start_iso = pd.to_datetime(current_file["start_ts"], unit="ns", utc=True).isoformat()
                    current_end_iso = pd.to_datetime(current_file["end_ts"], unit="ns", utc=True).isoformat()
                    next_start_iso = pd.to_datetime(next_file["start_ts"], unit="ns", utc=True).isoformat()
                    next_end_iso = pd.to_datetime(next_file["end_ts"], unit="ns", utc=True).isoformat()

                    overlaps.append({
                        "bar_type": bar_type,
                        "instrument_id": instrument_id,
                        "file1": current_file["file_path"],
                        "file2": next_file["file_path"],
                        "file1_path": current_file["file_path"],
                        "file2_path": next_file["file_path"],
                        "file1_range": {
                            "start": current_start_iso,
                            "end": current_end_iso,
                        },
                        "file2_range": {
                            "start": next_start_iso,
                            "end": next_end_iso,
                        },
                        "overlap_duration_ns": overlap_duration_ns,
                    })

    return overlaps


def summaries_to_json(
    catalog_path: Path,
    summaries: list[CatalogBarSummary],
    date_overlaps: list[dict[str, object]],
    interval_overlaps: list[dict[str, object]],
    interval_overlaps_error: str | None = None,
) -> dict[str, object]:
    instrument_groups = group_by_instrument(summaries)
    summary_info = summarize_catalog(summaries)

    instruments_json: list[dict[str, object]] = []
    for instrument_id, instrument_summaries in instrument_groups.items():
        instruments_json.append(
            {
                "instrument_id": instrument_id,
                "bar_types": [
                    {
                        "bar_type": s.bar_type,
                        "bar_count": s.bar_count,
                        "start_date": s.start_ts.isoformat() if s.start_ts is not None else None,
                        "end_date": s.end_ts.isoformat() if s.end_ts is not None else None,
                        "has_external_suffix": s.has_expected_suffix(),
                    }
                    for s in instrument_summaries
                ],
            }
        )

    result = {
        "catalog_path": str(catalog_path),
        "summary": summary_info,
        "instruments": instruments_json,
        "overlaps": date_overlaps,  # existing date range overlaps
        "interval_overlaps": interval_overlaps,  # new file-level overlaps
        "interval_overlap_count": len(interval_overlaps),
    }
    
    if interval_overlaps_error is not None:
        result["interval_overlaps_error"] = interval_overlaps_error
    
    return result


def print_catalog_report(catalog_path: Path, summaries: list[CatalogBarSummary]) -> None:
    summary_info = summarize_catalog(summaries)
    instruments = group_by_instrument(summaries)

    print(f"Catalog: {catalog_path}")
    print(
        "Total: "
        f"{summary_info['instrument_count']} instruments, "
        f"{summary_info['bar_type_count']} bar types, "
        f"{summary_info['total_bars']} bars"
    )

    coverage = summary_info.get("coverage", {})
    if coverage.get("earliest") and coverage.get("latest"):
        earliest = coverage["earliest"][:10]
        latest = coverage["latest"][:10]
        print(f"Data spans: {earliest} to {latest}")

    if not instruments:
        print("No instruments found in the catalog.")
        return

    for instrument_id, instrument_summaries in instruments.items():
        print(instrument_id)
        for summary in instrument_summaries:
            warning = ""
            if not summary.has_expected_suffix():
                warning = " ⚠️ WARNING: missing -EXTERNAL suffix"
            print(f"    {summary.format_summary()}{warning}")
        print()


def print_interval_overlaps(overlaps: list[dict[str, object]]) -> None:
    """Print formatted interval overlap information."""
    if not overlaps:
        return

    print("Interval Overlaps Detected:")
    
    # Group overlaps by bar type for better organization
    overlaps_by_bar_type = {}
    for overlap in overlaps:
        bar_type = overlap["bar_type"]
        if bar_type not in overlaps_by_bar_type:
            overlaps_by_bar_type[bar_type] = []
        overlaps_by_bar_type[bar_type].append(overlap)

    for bar_type, bar_overlaps in overlaps_by_bar_type.items():
        print(f"  {bar_type}:")
        for overlap in bar_overlaps:
            # Format timestamps for display
            file1_start = overlap["file1_range"]["start"][:19].replace("T", " ")
            file1_end = overlap["file1_range"]["end"][:19].replace("T", " ")
            file2_start = overlap["file2_range"]["start"][:19].replace("T", " ")
            file2_end = overlap["file2_range"]["end"][:19].replace("T", " ")
            
            # Convert overlap duration to human-readable format
            duration_ns = overlap["overlap_duration_ns"]
            duration_seconds = duration_ns / 1_000_000_000
            if duration_seconds < 60:
                duration_str = f"{duration_seconds:.1f} seconds"
            elif duration_seconds < 3600:
                minutes = duration_seconds / 60
                duration_str = f"{minutes:.1f} minutes"
            else:
                hours = duration_seconds / 3600
                duration_str = f"{hours:.1f} hours"
            
            print(f"    - {overlap['file1']} ({file1_start} to {file1_end})")
            print(f"      overlaps with")
            print(f"      {overlap['file2']} ({file2_start} to {file2_end})")
            print(f"      Overlap duration: {duration_str}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect NautilusTrader ParquetDataCatalog contents.")
    parser.add_argument(
        "catalog_path",
        nargs="?",
        default="data/historical",
        help="Path to the ParquetDataCatalog root (default: data/historical)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output catalog information as JSON for downstream tooling.",
    )
    parser.add_argument(
        "--check-overlaps",
        action="store_true",
        help="Check for overlapping intervals within bar type datasets",
    )
    args = parser.parse_args(argv)

    catalog_path = Path(args.catalog_path)
    load_dotenv()

    if not catalog_path.exists():
        message = (
            f"Catalog path '{catalog_path}' does not exist. "
            "If you have not ingested data yet, run: python data/ingest_historical.py"
        )
        if args.json:
            print(json.dumps({"catalog_path": str(catalog_path), "error": message}))
        else:
            print(f"Error: {message}")
        return 1

    try:
        catalog = ParquetDataCatalog(str(catalog_path))
    except Exception as exc:  # noqa: BLE001 (we want to surface any failure)
        message = f"Failed to load ParquetDataCatalog from '{catalog_path}'."
        if args.json:
            print(
                json.dumps(
                    {
                        "catalog_path": str(catalog_path),
                        "error": message,
                        "details": str(exc),
                    }
                )
            )
        else:
            print(f"Error: {message}")
            print(f"Details: {exc}")
        return 1

    summaries = collect_bar_summaries(catalog)
    if not summaries:
        message = (
            f"Catalog '{catalog_path}' exists but contains no bar data." \
            " Run 'python data/ingest_historical.py' to populate it."
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "catalog_path": str(catalog_path),
                        "summary": summarize_catalog([]),
                        "instruments": [],
                        "overlaps": [],
                        "interval_overlaps": [],
                        "interval_overlap_count": 0,
                        "warning": message,
                    }
                )
            )
        else:
            print(message)
        return 2

    # Check for interval overlaps only when needed
    interval_overlaps = []
    interval_overlaps_error = None
    if args.json or args.check_overlaps:
        try:
            interval_overlaps = check_interval_overlaps(catalog)
        except Exception as exc:  # noqa: BLE001
            interval_overlaps_error = str(exc)
            if args.json:
                # For JSON mode, include error in output but don't exit non-zero
                pass
            else:
                print(f"Warning: Failed to check interval overlaps: {exc}")

    target_start = os.getenv("BACKTEST_START_DATE")
    target_end = os.getenv("BACKTEST_END_DATE")
    date_overlaps = check_date_overlap(summaries, target_start, target_end)

    if args.json:
        output = summaries_to_json(catalog_path, summaries, date_overlaps, interval_overlaps, interval_overlaps_error)
        if target_start and target_end:
            output["target_range"] = {
                "start": target_start,
                "end": target_end,
                "overlaps_found": len(date_overlaps),
            }
        print(json.dumps(output, indent=2))
    else:
        print_catalog_report(catalog_path, summaries)
        
        # Handle interval overlap reporting
        if args.check_overlaps:
            if interval_overlaps:
                print()
                print_interval_overlaps(interval_overlaps)
            else:
                print("No interval overlaps detected - all bar type files have disjoint time ranges.")
        
        # Handle date overlap reporting (existing functionality)
        if date_overlaps:
            print("Overlaps with BACKTEST date range:")
            for overlap in date_overlaps:
                start = overlap["start"][:10]
                end = overlap["end"][:10]
                print(
                    f"  - {overlap['instrument_id']} {overlap['bar_type']}: "
                    f"{start} to {end}"
                )
        elif target_start and target_end:
            print(
                "No catalog data overlaps with BACKTEST date range "
                f"({target_start} to {target_end})."
            )

    # Return non-zero exit code if interval overlaps found and --check-overlaps was specified
    if args.check_overlaps and interval_overlaps:
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
