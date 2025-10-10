"""
Backtesting diagnostic utility.

This script orchestrates a series of checks to validate that the Parquet
catalog contains the data required for NautilusTrader backtests. It inspects
catalog contents, validates bar specifications, verifies configuration values,
and generates a human-readable report with actionable recommendations.

Usage:
    python data/diagnose_backtest.py [--catalog-path PATH] [--output-dir PATH] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from config.backtest_config import BacktestConfig, get_backtest_config

EXPECTED_SUFFIX = "-EXTERNAL"
VERIFY_SCRIPT = Path(__file__).parent / "verify_catalog.py"


@dataclass
class CatalogCheckResult:
    exists_before: bool
    created: bool
    path: Path
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "exists_before": self.exists_before,
            "created": self.created,
            "error": self.error,
        }


def check_catalog_directory(catalog_path: Path, verbose: bool = False) -> CatalogCheckResult:
    exists_before = catalog_path.exists()
    created = False
    error: Optional[str] = None

    if not exists_before:
        try:
            catalog_path.mkdir(parents=True, exist_ok=True)
            created = True
            if verbose:
                print(f"Created missing catalog directory at '{catalog_path}'.")
        except Exception as exc:  # noqa: BLE001
            error = f"Failed to create catalog directory: {exc}"
            if verbose:
                print(error)
    else:
        if verbose:
            print(f"Catalog directory exists at '{catalog_path}'.")

    return CatalogCheckResult(exists_before=exists_before, created=created, path=catalog_path, error=error)


def run_catalog_verification(catalog_path: Path, verbose: bool = False) -> Dict[str, Any]:
    if not VERIFY_SCRIPT.exists():
        msg = f"Verification script not found at '{VERIFY_SCRIPT}'."
        if verbose:
            print(msg)
        return {"success": False, "error": msg, "output": "", "instruments": []}

    cmd = [sys.executable, str(VERIFY_SCRIPT), str(catalog_path), "--json"]
    if verbose:
        print(f"Running catalog verification: {' '.join(cmd)}")

    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        msg = f"Failed to execute verification script: {exc}"
        if verbose:
            print(msg)
        return {"success": False, "error": msg, "output": "", "instruments": []}

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    data: Dict[str, Any] = {}
    parse_error: Optional[str] = None
    if stdout:
        try:
            loaded = json.loads(stdout)
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError as exc:
            parse_error = f"Failed to parse verification output: {exc}"
            if verbose:
                print(parse_error)

    success = completed.returncode == 0
    empty_catalog = completed.returncode == 2

    error_msg: Optional[str] = None
    if parse_error:
        error_msg = parse_error
    elif not success and not empty_catalog:
        error_msg = stderr or data.get("error") if isinstance(data, dict) else None
        if not error_msg:
            error_msg = stdout or "Catalog verification failed."
        if verbose:
            print(error_msg)
    elif verbose:
        message = "Catalog verification completed successfully." if success else "Catalog verification reported empty catalog."
        print(message)

    return {
        "success": success,
        "output": stdout,
        "stderr": stderr,
        "data": data,
        "instruments": data.get("instruments", []) if isinstance(data, dict) else [],
        "error": error_msg,
    }


def check_parquet_files(catalog_path: Path) -> Dict[str, Any]:
    parquet_files = list(catalog_path.rglob("*.parquet")) if catalog_path.exists() else []
    total_size_bytes = sum(f.stat().st_size for f in parquet_files)
    total_size_mb = total_size_bytes / (1024 * 1024) if parquet_files else 0.0

    return {
        "file_count": len(parquet_files),
        "total_size_mb": round(total_size_mb, 3),
        "files": [str(f.relative_to(catalog_path)) for f in parquet_files],
    }


def extract_bar_types(instrument_entries: List[Dict[str, Any]]) -> List[str]:
    bar_types: List[str] = []
    for instrument in instrument_entries:
        for entry in instrument.get("bar_types", []):
            bar_types.append(entry.get("bar_type", ""))
    return bar_types


def validate_bar_specs(bar_types: List[str]) -> Dict[str, Any]:
    valid = [bt for bt in bar_types if bt.endswith(EXPECTED_SUFFIX)]
    invalid = [bt for bt in bar_types if bt and not bt.endswith(EXPECTED_SUFFIX)]
    return {
        "valid": valid,
        "invalid": invalid,
        "all_valid": len(invalid) == 0,
    }


def check_backtest_config() -> Dict[str, Any]:
    load_dotenv()
    try:
        cfg: BacktestConfig = get_backtest_config()
        start_dt = datetime.strptime(cfg.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(cfg.end_date, "%Y-%m-%d")
        date_valid = start_dt < end_dt
        return {
            "success": True,
            "config": {
                "symbol": cfg.symbol,
                "venue": cfg.venue,
                "start_date": cfg.start_date,
                "end_date": cfg.end_date,
                "bar_spec": cfg.bar_spec,
                "catalog_path": cfg.catalog_path,
            },
            "date_valid": date_valid,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "config": None,
            "date_valid": False,
            "error": str(exc),
        }


def determine_issues(
    catalog_result: CatalogCheckResult,
    parquet_info: Dict[str, Any],
    verification: Dict[str, Any],
    bar_spec_check: Dict[str, Any],
    config_info: Dict[str, Any],
) -> List[str]:
    issues: List[str] = []

    if catalog_result.error:
        issues.append(catalog_result.error)
    if not catalog_result.exists_before and not catalog_result.created:
        issues.append("Catalog directory does not exist and could not be created.")

    if parquet_info.get("file_count", 0) == 0:
        issues.append("No Parquet files found in catalog directory.")

    if not verification.get("success", False):
        error = verification.get("error")
        if error:
            issues.append(f"Catalog verification failed: {error}")
        elif parquet_info.get("file_count", 0) == 0:
            issues.append("Catalog verification reported no data.")

    if not bar_spec_check.get("all_valid", False) and bar_spec_check.get("invalid"):
        issues.append(
            "Bar types missing '-EXTERNAL' suffix detected: "
            + ", ".join(bar_spec_check["invalid"])
        )

    if not config_info.get("success", False):
        issues.append(f"Failed to load backtest configuration: {config_info.get('error')}" )
    elif not config_info.get("date_valid", False):
        issues.append("BACKTEST_START_DATE must be earlier than BACKTEST_END_DATE.")

    return issues


def build_recommendations(issues: List[str]) -> List[str]:
    recommendations: List[str] = []

    if any("Parquet files" in issue for issue in issues):
        recommendations.append("Run 'python data/ingest_historical.py' to download historical data.")

    if any("'-EXTERNAL'" in issue for issue in issues):
        recommendations.append("Re-run ingestion ensuring bar specs include the '-EXTERNAL' suffix.")

    if any("configuration" in issue.lower() for issue in issues) or any("BACKTEST_START_DATE" in issue for issue in issues):
        recommendations.append("Review .env settings for BACKTEST_* variables and ensure date range is valid.")

    if not recommendations:
        recommendations.append("No critical issues detected. Backtest should be able to load catalog data.")

    return recommendations


def generate_diagnostic_report(
    catalog_result: CatalogCheckResult,
    parquet_info: Dict[str, Any],
    verification: Dict[str, Any],
    bar_spec_check: Dict[str, Any],
    config_info: Dict[str, Any],
    issues: List[str],
    recommendations: List[str],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"backtest_diagnostics_{timestamp}.txt"

    lines: List[str] = []
    lines.append("=== Backtesting Diagnostic Report ===")
    lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append("")

    lines.append("[1] Catalog Directory Status")
    lines.append(f"  - Path: {catalog_result.path}")
    lines.append(f"  - Existed prior to run: {'Yes' if catalog_result.exists_before else 'No'}")
    lines.append(f"  - Created during run: {'Yes' if catalog_result.created else 'No'}")
    lines.append(f"  - Parquet files: {parquet_info.get('file_count', 0)}")
    lines.append(f"  - Total size: {parquet_info.get('total_size_mb', 0.0)} MB")
    lines.append("")

    lines.append("[2] Catalog Verification")
    if verification.get("data"):
        total_bars = verification["data"].get("summary", {}).get("total_bars")
        coverage = verification["data"].get("summary", {}).get("coverage")
        lines.append(f"  - Instruments found: {verification['data'].get('summary', {}).get('instrument_count', 0)}")
        lines.append(f"  - Bar types discovered: {verification['data'].get('summary', {}).get('bar_type_count', 0)}")
        if total_bars is not None:
            lines.append(f"  - Total bars: {total_bars}")
        if coverage:
            lines.append(
                "  - Data spans: "
                f"{coverage.get('earliest')} to {coverage.get('latest')}"
            )
    else:
        lines.append("  - No catalog data available.")
    lines.append("")

    lines.append("[3] Bar Spec Validation")
    lines.append(f"  - All bar types include '-EXTERNAL': {'Yes' if bar_spec_check.get('all_valid') else 'No'}")
    if bar_spec_check.get("invalid"):
        lines.append("  - Invalid bar types:")
        for invalid in bar_spec_check["invalid"]:
            lines.append(f"      * {invalid}")
    lines.append("")

    lines.append("[4] Backtest Configuration")
    if config_info.get("success"):
        cfg = config_info["config"]
        lines.append(f"  - Symbol: {cfg['symbol']}")
        lines.append(f"  - Venue: {cfg['venue']}")
        lines.append(f"  - Date range: {cfg['start_date']} to {cfg['end_date']}")
        lines.append(f"  - Bar spec: {cfg['bar_spec']}")
        lines.append(f"  - Catalog path: {cfg['catalog_path']}")
        lines.append(f"  - Date range valid: {'Yes' if config_info.get('date_valid') else 'No'}")
    else:
        lines.append("  - Failed to load backtest configuration.")
        lines.append(f"  - Error: {config_info.get('error')}")
    lines.append("")

    lines.append("[5] Issues Detected")
    if issues:
        for issue in issues:
            lines.append(f"  - {issue}")
    else:
        lines.append("  - None")
    lines.append("")

    lines.append("[6] Recommendations")
    for rec in recommendations:
        lines.append(f"  - {rec}")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def summarize_to_console(
    catalog_result: CatalogCheckResult,
    parquet_info: Dict[str, Any],
    verification: Dict[str, Any],
    bar_spec_check: Dict[str, Any],
    config_info: Dict[str, Any],
    issues: List[str],
    recommendations: List[str],
) -> None:
    print("=== Backtesting Diagnostic Summary ===")
    print(f"Catalog exists: {'Yes' if catalog_result.path.exists() else 'No'}")
    print(f"Parquet files: {parquet_info.get('file_count', 0)} (size: {parquet_info.get('total_size_mb', 0.0)} MB)")

    instrument_count = 0
    if verification.get("data"):
        instrument_count = verification["data"].get("summary", {}).get("instrument_count", 0)
    print(f"Instruments detected: {instrument_count}")
    print(f"Bar spec issues: {len(bar_spec_check.get('invalid', []))}")
    config_status = "Yes" if config_info.get("success") and config_info.get("date_valid") else "No"
    print(f"Configuration valid: {config_status}")

    if issues:
        print("Issues:")
        for issue in issues:
            print(f"  - {issue}")

    print("Recommendations:")
    for rec in recommendations:
        print(f"  - {rec}")


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose NautilusTrader backtesting catalog issues.")
    parser.add_argument(
        "--catalog-path",
        default="data/historical",
        help="Path to the ParquetDataCatalog root (default: data/historical)",
    )
    parser.add_argument(
        "--output-dir",
        default="logs",
        help="Directory where the diagnostic report will be written (default: logs)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging to stdout during diagnostics.",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    catalog_path = Path(args.catalog_path).resolve()
    output_dir = Path(args.output_dir).resolve()
    verbose = bool(args.verbose)

    if verbose:
        print("Backtesting Diagnostic Tool")
        print(f"Catalog path: {catalog_path}")
        print(f"Report output directory: {output_dir}")

    catalog_result = check_catalog_directory(catalog_path, verbose=verbose)
    parquet_info = check_parquet_files(catalog_path)
    verification = run_catalog_verification(catalog_path, verbose=verbose)
    bar_types = extract_bar_types(verification.get("instruments", [])) if verification.get("success") else []
    bar_spec_check = validate_bar_specs(bar_types)
    config_info = check_backtest_config()

    extra_issues: List[str] = []
    if config_info.get("success") and config_info.get("config"):
        config_catalog_path = Path(config_info["config"]["catalog_path"]).resolve()
        if config_catalog_path != catalog_path:
            extra_issues.append(
                "Catalog path mismatch: CLI path is "
                f"'{catalog_path}', but BACKTEST catalog path is '{config_catalog_path}'."
            )

    issues = determine_issues(catalog_result, parquet_info, verification, bar_spec_check, config_info)
    issues.extend(extra_issues)
    recommendations = build_recommendations(issues)
    report_path = generate_diagnostic_report(
        catalog_result,
        parquet_info,
        verification,
        bar_spec_check,
        config_info,
        issues,
        recommendations,
        output_dir,
    )

    summarize_to_console(catalog_result, parquet_info, verification, bar_spec_check, config_info, issues, recommendations)

    if verbose:
        print(f"Diagnostic report written to {report_path}")

    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
