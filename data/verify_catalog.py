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


def summaries_to_json(
    catalog_path: Path,
    summaries: list[CatalogBarSummary],
    overlaps: list[dict[str, object]],
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

    return {
        "catalog_path": str(catalog_path),
        "summary": summary_info,
        "instruments": instruments_json,
        "overlaps": overlaps,
    }


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
                        "warning": message,
                    }
                )
            )
        else:
            print(message)
        return 2

    target_start = os.getenv("BACKTEST_START_DATE")
    target_end = os.getenv("BACKTEST_END_DATE")
    overlaps = check_date_overlap(summaries, target_start, target_end)

    if args.json:
        output = summaries_to_json(catalog_path, summaries, overlaps)
        if target_start and target_end:
            output["target_range"] = {
                "start": target_start,
                "end": target_end,
                "overlaps_found": len(overlaps),
            }
        print(json.dumps(output, indent=2))
    else:
        print_catalog_report(catalog_path, summaries)
        if overlaps:
            print("Overlaps with BACKTEST date range:")
            for overlap in overlaps:
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
