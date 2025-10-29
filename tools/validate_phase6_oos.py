#!/usr/bin/env python3
"""
Phase 6 Out-of-Sample (OOS) Validation Tool

Purpose
-------
Validate robustness of Phase 6 optimized parameters by running backtests on
out-of-sample (OOS) historical periods and comparing performance against the
original optimization baseline. The tool mirrors the subprocess execution
pattern from optimization/validate_baseline.py and uses the shared metrics
extraction helper from optimization/grid_search.py for consistency.

Usage Examples
--------------
1) Validate rank 1 using default 2024 quarterly periods and default catalog
   python tools/validate_phase6_oos.py --rank 1

2) Validate a specific rank with custom periods (JSON string)
   python tools/validate_phase6_oos.py --rank 2 \
       --periods "[{\"name\":\"Q1_2024\",\"start_date\":\"2024-01-01\",\"end_date\":\"2024-03-31\"}]"

3) Validate with periods defined in a JSON file
   python tools/validate_phase6_oos.py --rank 3 --periods tools/periods_2024.json

4) Specify custom catalog path and timeout
   python tools/validate_phase6_oos.py --rank 1 \
       --catalog-path data/historical \
       --timeout 2400 --verbose

Output
------
- JSON validation report written to tools/validation_reports by default
  (filename includes rank and timestamp)
- Console summary with baseline metrics, per-period results, and recommendation

Exit Codes
----------
0   Validation completed successfully
1   User/data/argument error (e.g., invalid rank, bad periods JSON)
2   Unexpected runtime error
130 Interrupted by user (Ctrl+C)
"""

from __future__ import annotations

import sys
import os
import json
import logging
import subprocess
import argparse
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

import pandas as pd

# Setup project root similar to other tools
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Project imports
from config.phase6_config_loader import (
    Phase6ConfigLoader,
    Phase6Parameters,
    Phase6PerformanceMetrics,
)
from optimization.grid_search import extract_metrics


# Constants
BACKTEST_SCRIPT = PROJECT_ROOT / "backtest" / "run_backtest.py"
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "data" / "historical"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "tools" / "validation_reports"
DEFAULT_TIMEOUT_SECONDS = 1800  # 30 minutes
DEGRADATION_THRESHOLD = 0.20    # 20%
SCRIPT_VERSION = "1.0.0"


@dataclass(frozen=True)
class ValidationPeriod:
    """Represents a validation period with a friendly name and date range."""

    name: str
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD

    @classmethod
    def from_dict(cls, data: dict) -> "ValidationPeriod":
        required = {"name", "start_date", "end_date"}
        if not isinstance(data, dict) or not required.issubset(data.keys()):
            raise ValueError("Each period must include 'name', 'start_date', and 'end_date'")

        # Validate date format and ordering
        try:
            sd = datetime.strptime(str(data["start_date"]).strip(), "%Y-%m-%d")
            ed = datetime.strptime(str(data["end_date"]).strip(), "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Invalid date format in period {data.get('name','<unnamed>')}: {exc}") from exc
        if sd >= ed:
            raise ValueError(
                f"Invalid date range for period {data.get('name','<unnamed>')}: start_date must be before end_date"
            )
        return cls(name=str(data["name"]).strip(), start_date=sd.strftime("%Y-%m-%d"), end_date=ed.strftime("%Y-%m-%d"))


@dataclass
class PeriodResult:
    """Backtest results for a single validation period."""

    period_name: str
    start_date: str
    end_date: str
    total_pnl: float
    sharpe_ratio: float
    win_rate: float
    max_drawdown: float
    trade_count: int
    profit_factor: float
    status: str  # completed | failed | timeout
    error_message: str
    backtest_duration_seconds: float
    output_directory: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure console logging and return a logger."""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


def load_phase6_config(rank: int, results_path: Optional[Path], logger: logging.Logger) -> Tuple[Phase6Parameters, Phase6PerformanceMetrics]:
    """Load Phase 6 configuration by rank.

    Returns the parameter set and baseline performance metrics.
    Raises ValueError if the requested rank cannot be found.
    """
    loader = Phase6ConfigLoader(results_path=results_path)
    result = loader.get_by_rank(rank)
    if result is None:
        available = [r.rank for r in loader.results]
        raise ValueError(f"Phase 6 result with rank {rank} not found. Available ranks: {available}")

    logger.info(
        "Loaded Phase 6 result: rank=%s, run_id=%s, baseline Sharpe=%.3f, PnL=%.2f, WinRate=%.2f%%, Trades=%s",
        result.rank,
        result.run_id,
        result.metrics.sharpe_ratio,
        result.metrics.total_pnl,
        result.metrics.win_rate * 100.0,
        result.metrics.trade_count,
    )
    return result.parameters, result.metrics


def parse_periods_from_json(json_str: str) -> List[ValidationPeriod]:
    """Parse validation periods from a JSON string and validate structure and dates."""
    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse periods JSON: {exc.msg} (pos {exc.pos})") from exc

    if not isinstance(raw, list):
        raise ValueError("Periods JSON must be an array of period objects")

    periods: List[ValidationPeriod] = []
    for entry in raw:
        periods.append(ValidationPeriod.from_dict(entry))
    return periods


def parse_periods_from_file(file_path: Path) -> List[ValidationPeriod]:
    """Load and parse validation periods from a JSON file path."""
    if not file_path.exists():
        raise FileNotFoundError(f"Periods file not found: {file_path}")
    content = file_path.read_text(encoding="utf-8")
    return parse_periods_from_json(content)


def get_default_periods(logger: logging.Logger) -> List[ValidationPeriod]:
    """Return default quarterly validation periods for 2024."""
    logger.info("Using default 2024 quarterly periods for validation")
    defaults = [
        {"name": "Q1_2024", "start_date": "2024-01-01", "end_date": "2024-03-31"},
        {"name": "Q2_2024", "start_date": "2024-04-01", "end_date": "2024-06-30"},
        {"name": "Q3_2024", "start_date": "2024-07-01", "end_date": "2024-09-30"},
        {"name": "Q4_2024", "start_date": "2024-10-01", "end_date": "2024-12-31"},
    ]
    return [ValidationPeriod.from_dict(d) for d in defaults]


def _params_to_env(params: Phase6Parameters) -> Dict[str, str]:
    """Convert Phase 6 parameters to environment variables expected by backtest."""
    return {
        "BACKTEST_FAST_PERIOD": str(params.fast_period),
        "BACKTEST_SLOW_PERIOD": str(params.slow_period),
        "BACKTEST_STOP_LOSS_PIPS": str(params.stop_loss_pips),
        "BACKTEST_TAKE_PROFIT_PIPS": str(params.take_profit_pips),
        "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": str(params.trailing_stop_activation_pips),
        "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": str(params.trailing_stop_distance_pips),
        "STRATEGY_CROSSOVER_THRESHOLD_PIPS": str(params.crossover_threshold_pips),
        "STRATEGY_DMI_ENABLED": str(params.dmi_enabled).lower(),
        "STRATEGY_DMI_PERIOD": str(params.dmi_period),
        "STRATEGY_STOCH_ENABLED": str(params.stoch_enabled).lower(),
        "STRATEGY_STOCH_PERIOD_K": str(params.stoch_period_k),
        "STRATEGY_STOCH_PERIOD_D": str(params.stoch_period_d),
        "STRATEGY_STOCH_BULLISH_THRESHOLD": str(params.stoch_bullish_threshold),
        "STRATEGY_STOCH_BEARISH_THRESHOLD": str(params.stoch_bearish_threshold),
    }


def run_backtest_for_period(
    period: ValidationPeriod,
    params: Phase6Parameters,
    catalog_path: Path,
    timeout: int,
    logger: logging.Logger,
) -> PeriodResult:
    """Execute a backtest for a single validation period via subprocess."""
    env = os.environ.copy()
    env.update(
        {
            "BACKTEST_SYMBOL": "EUR/USD",
            "BACKTEST_VENUE": "IDEALPRO",
            "BACKTEST_START_DATE": period.start_date,
            "BACKTEST_END_DATE": period.end_date,
            "BACKTEST_BAR_SPEC": "15-MINUTE-MID-EXTERNAL",
            "CATALOG_PATH": str(catalog_path),
            "OUTPUT_DIR": str(PROJECT_ROOT / "logs" / "backtest_results"),
        }
    )
    env.update(_params_to_env(params))

    start_time = time.time()
    try:
        # Ensure deterministic encoding to avoid replacement characters
        if "PYTHONIOENCODING" not in env:
            env["PYTHONIOENCODING"] = "utf-8"

        result = subprocess.run(
            [sys.executable, str(BACKTEST_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        duration = time.time() - start_time

        if result.returncode != 0:
            return PeriodResult(
                period_name=period.name,
                start_date=period.start_date,
                end_date=period.end_date,
                total_pnl=0.0,
                sharpe_ratio=0.0,
                win_rate=0.0,
                max_drawdown=0.0,
                trade_count=0,
                profit_factor=0.0,
                status="failed",
                error_message=(result.stderr or "").strip(),
                backtest_duration_seconds=duration,
                output_directory="",
            )

        # Parse output directory from stdout or fallback to latest
        import re

        output_dir: Optional[Path] = None
        match = re.search(r"Results written to: (.+)", result.stdout or "")
        if match:
            output_dir = Path(match.group(1))
        else:
            # Fallback to latest EUR-USD_* directory
            base = PROJECT_ROOT / "logs" / "backtest_results"
            if base.exists():
                candidates = [d for d in base.iterdir() if d.is_dir() and d.name.startswith("EUR-USD_")]
                if candidates:
                    output_dir = max(candidates, key=lambda d: d.stat().st_mtime)

        if not output_dir or not output_dir.exists():
            return PeriodResult(
                period_name=period.name,
                start_date=period.start_date,
                end_date=period.end_date,
                total_pnl=0.0,
                sharpe_ratio=0.0,
                win_rate=0.0,
                max_drawdown=0.0,
                trade_count=0,
                profit_factor=0.0,
                status="failed",
                error_message="No backtest output directory found",
                backtest_duration_seconds=duration,
                output_directory="",
            )

        stats_file = output_dir / "performance_stats.json"
        if not stats_file.exists():
            return PeriodResult(
                period_name=period.name,
                start_date=period.start_date,
                end_date=period.end_date,
                total_pnl=0.0,
                sharpe_ratio=0.0,
                win_rate=0.0,
                max_drawdown=0.0,
                trade_count=0,
                profit_factor=0.0,
                status="failed",
                error_message="No performance stats generated",
                backtest_duration_seconds=duration,
                output_directory=str(output_dir),
            )

        stats = json.loads(stats_file.read_text(encoding="utf-8"))
        metrics = extract_metrics(stats, output_dir)

        return PeriodResult(
            period_name=period.name,
            start_date=period.start_date,
            end_date=period.end_date,
            total_pnl=float(metrics.get("total_pnl", 0.0)),
            sharpe_ratio=float(metrics.get("sharpe_ratio", 0.0)),
            win_rate=float(metrics.get("win_rate", 0.0)),
            max_drawdown=float(metrics.get("max_drawdown", 0.0)),
            trade_count=int(metrics.get("trade_count", 0)),
            profit_factor=float(metrics.get("profit_factor", 0.0)),
            status="completed",
            error_message="",
            backtest_duration_seconds=duration,
            output_directory=str(output_dir),
        )

    except subprocess.TimeoutExpired:
        return PeriodResult(
            period_name=period.name,
            start_date=period.start_date,
            end_date=period.end_date,
            total_pnl=0.0,
            sharpe_ratio=0.0,
            win_rate=0.0,
            max_drawdown=0.0,
            trade_count=0,
            profit_factor=0.0,
            status="timeout",
            error_message=f"Backtest timed out after {timeout} seconds",
            backtest_duration_seconds=float(timeout),
            output_directory="",
        )
    except Exception as exc:
        duration = time.time() - start_time
        return PeriodResult(
            period_name=period.name,
            start_date=period.start_date,
            end_date=period.end_date,
            total_pnl=0.0,
            sharpe_ratio=0.0,
            win_rate=0.0,
            max_drawdown=0.0,
            trade_count=0,
            profit_factor=0.0,
            status="failed",
            error_message=str(exc),
            backtest_duration_seconds=duration,
            output_directory="",
        )


def compute_performance_comparison(
    baseline_metrics: Phase6PerformanceMetrics, period_results: List[PeriodResult]
) -> Dict[str, Any]:
    """Compare OOS performance across periods against the Phase 6 baseline."""
    completed = [r for r in period_results if r.status == "completed"]
    failed = [r for r in period_results if r.status == "failed"]
    timed_out = [r for r in period_results if r.status == "timeout"]

    data = {
        "baseline_metrics": {
            "total_pnl": baseline_metrics.total_pnl,
            "sharpe_ratio": baseline_metrics.sharpe_ratio,
            "win_rate": baseline_metrics.win_rate,
            "trade_count": baseline_metrics.trade_count,
            "profit_factor": baseline_metrics.profit_factor,
            "max_drawdown": baseline_metrics.max_drawdown,
        }
    }

    if completed:
        df = pd.DataFrame([r.to_dict() for r in completed])
        stats = {
            "mean": {
                "total_pnl": float(df["total_pnl"].mean()),
                "sharpe_ratio": float(df["sharpe_ratio"].mean()),
                "win_rate": float(df["win_rate"].mean()),
                "max_drawdown": float(df["max_drawdown"].mean()),
                "profit_factor": float(df["profit_factor"].mean()),
                "trade_count": float(df["trade_count"].mean()),
            },
            "std": {
                "total_pnl": float(df["total_pnl"].std(ddof=0)),
                "sharpe_ratio": float(df["sharpe_ratio"].std(ddof=0)),
                "win_rate": float(df["win_rate"].std(ddof=0)),
                "max_drawdown": float(df["max_drawdown"].std(ddof=0)),
                "profit_factor": float(df["profit_factor"].std(ddof=0)),
                "trade_count": float(df["trade_count"].std(ddof=0)),
            },
            "min": {
                "total_pnl": float(df["total_pnl"].min()),
                "sharpe_ratio": float(df["sharpe_ratio"].min()),
                "win_rate": float(df["win_rate"].min()),
                "max_drawdown": float(df["max_drawdown"].min()),
                "profit_factor": float(df["profit_factor"].min()),
                "trade_count": int(df["trade_count"].min()),
            },
            "max": {
                "total_pnl": float(df["total_pnl"].max()),
                "sharpe_ratio": float(df["sharpe_ratio"].max()),
                "win_rate": float(df["win_rate"].max()),
                "max_drawdown": float(df["max_drawdown"].max()),
                "profit_factor": float(df["profit_factor"].max()),
                "trade_count": int(df["trade_count"].max()),
            },
        }
    else:
        stats = {"mean": {}, "std": {}, "min": {}, "max": {}}

    degradation_flags: List[Dict[str, Any]] = []
    baseline = data["baseline_metrics"]
    for r in completed:
        comparisons = [
            ("sharpe_ratio", baseline.get("sharpe_ratio") or 0.0, r.sharpe_ratio),
            ("total_pnl", baseline.get("total_pnl") or 0.0, r.total_pnl),
            ("win_rate", baseline.get("win_rate") or 0.0, r.win_rate),
        ]
        for metric, base, val in comparisons:
            # Avoid division by zero; if baseline is ~0, treat any negative change as degradation
            if base == 0:
                change_pct = -100.0 if val < 0 else 0.0
            else:
                change_pct = (val - base) / base
            if change_pct < -DEGRADATION_THRESHOLD:
                degradation_flags.append(
                    {
                        "period_name": r.period_name,
                        "metric": metric,
                        "baseline_value": float(base),
                        "period_value": float(val),
                        "change_percentage": float(change_pct * 100.0),
                    }
                )

        # Drawdown degradation: higher drawdown is worse; flag if increase > 20%
        base_dd = baseline.get("max_drawdown") or 0.0
        val_dd = r.max_drawdown
        if base_dd == 0:
            dd_change_pct = 100.0 if val_dd > 0 else 0.0
        else:
            dd_change_pct = (val_dd - base_dd) / base_dd * 100.0
        if dd_change_pct > (DEGRADATION_THRESHOLD * 100.0):
            degradation_flags.append(
                {
                    "period_name": r.period_name,
                    "metric": "max_drawdown",
                    "baseline_value": float(base_dd),
                    "period_value": float(val_dd),
                    "change_percentage": float(dd_change_pct),
                }
            )

    data["period_statistics"] = stats
    data["degradation_flags"] = degradation_flags
    data["summary"] = {
        "completed": len(completed),
        "failed": len(failed),
        "timeout": len(timed_out),
        "total": len(period_results),
    }
    return data


def _recommendation_from_flags(flags: List[Dict[str, Any]], results: List[PeriodResult]) -> str:
    if not results:
        return "FAIL"
    completed = [r for r in results if r.status == "completed"]
    failed_or_timeout = [r for r in results if r.status != "completed"]
    if failed_or_timeout:
        # Any operational failures warrant caution at minimum
        if len(failed_or_timeout) >= max(1, len(results) // 2):
            return "FAIL"
        return "CAUTION"
    if not flags:
        return "PASS"
    # If more than half of completed periods show >=2 degraded metrics, mark as FAIL
    from collections import Counter

    by_period = Counter([f["period_name"] for f in flags])
    severe = sum(1 for _, cnt in by_period.items() if cnt >= 2)
    if severe >= max(1, len(completed) // 2):
        return "FAIL"
    return "CAUTION"


def generate_validation_report(
    rank: int,
    run_id: int,
    baseline_metrics: Phase6PerformanceMetrics,
    period_results: List[PeriodResult],
    comparison: Dict[str, Any],
    execution_time: float,
    output_path: Path,
    logger: logging.Logger,
) -> bool:
    """Generate JSON validation report to the specified output path."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        recommendation = _recommendation_from_flags(comparison.get("degradation_flags", []), period_results)

        report = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "script_version": SCRIPT_VERSION,
                "execution_time_seconds": execution_time,
                "rank": rank,
                "run_id": run_id,
            },
            "baseline_performance": asdict(baseline_metrics),
            "validation_periods": [r.to_dict() for r in period_results],
            "performance_comparison": comparison,
            "degradation_summary": comparison.get("degradation_flags", []),
            "recommendation": recommendation,
        }

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Validation report written to {output_path}")
        return True
    except Exception as exc:
        logger.error(f"Failed to write validation report: {exc}")
        return False


def print_console_summary(
    rank: int,
    run_id: int,
    baseline_metrics: Phase6PerformanceMetrics,
    period_results: List[PeriodResult],
    comparison: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    """Print formatted validation summary to console."""
    print("\n" + "=" * 70)
    print(f"PHASE 6 OOS VALIDATION - Rank {rank} (Run ID {run_id})")
    print("=" * 70)

    print("\nBASELINE PERFORMANCE:")
    print(f"Sharpe: {baseline_metrics.sharpe_ratio:.3f} | PnL: {baseline_metrics.total_pnl:.2f} | "
          f"WinRate: {baseline_metrics.win_rate:.2%} | Trades: {baseline_metrics.trade_count}")

    print("\nPERIOD RESULTS:")
    header = f"{'Period':<16} {'Status':<10} {'PnL':>12} {'Sharpe':>8} {'WinRate':>10} {'Trades':>8} {'ΔPnL% vs Base':>14} {'ΔSharpe%':>10}"
    print(header)
    print("-" * len(header))
    baseline_pnl = baseline_metrics.total_pnl or 0.0
    baseline_sharpe = baseline_metrics.sharpe_ratio or 0.0
    for r in period_results:
        if r.status == "completed":
            pnl_change = ((r.total_pnl - baseline_pnl) / baseline_pnl * 100.0) if baseline_pnl != 0 else 0.0
            sharpe_change = ((r.sharpe_ratio - baseline_sharpe) / baseline_sharpe * 100.0) if baseline_sharpe != 0 else 0.0
        else:
            pnl_change = 0.0
            sharpe_change = 0.0
        print(
            f"{r.period_name:<16} {r.status:<10} {r.total_pnl:>12.2f} {r.sharpe_ratio:>8.3f} "
            f"{r.win_rate:>10.2%} {r.trade_count:>8} {pnl_change:>14.1f} {sharpe_change:>10.1f}"
        )

    stats = comparison.get("period_statistics", {})
    if stats.get("mean"):
        print("\nAGGREGATE STATS (completed periods):")
        mean = stats["mean"]
        std = stats["std"]
        print(
            f"Mean -> PnL: {mean.get('total_pnl', 0.0):.2f}, Sharpe: {mean.get('sharpe_ratio', 0.0):.3f}, "
            f"WinRate: {mean.get('win_rate', 0.0):.2%}, MaxDD: {mean.get('max_drawdown', 0.0):.2f}"
        )
        print(
            f"Std  -> PnL: {std.get('total_pnl', 0.0):.2f}, Sharpe: {std.get('sharpe_ratio', 0.0):.3f}, "
            f"WinRate: {std.get('win_rate', 0.0):.2%}, MaxDD: {std.get('max_drawdown', 0.0):.2f}"
        )

    flags = comparison.get("degradation_flags", [])
    if flags:
        print("\nWARNINGS (degradation > 20% vs baseline):")
        for f in flags:
            print(
                f"- {f['period_name']}: {f['metric']} baseline={f['baseline_value']:.4f}, "
                f"period={f['period_value']:.4f} ({f['change_percentage']:.1f}%)"
            )

    rec = _recommendation_from_flags(flags, period_results)
    print("\n" + "=" * 70)
    print(f"RECOMMENDATION: {rec}")
    print("=" * 70 + "\n")


def setup_argument_parser() -> argparse.ArgumentParser:
    """Create and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Validate Phase 6 parameters on out-of-sample periods",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--rank", type=int, default=1, help="Rank of Phase 6 config to validate (1-10)")
    parser.add_argument(
        "--periods",
        type=str,
        help=(
            "JSON string or file path with periods. "
            "Format: [{\\"name\\": \\\"Q1_2024\\\", \\\"start_date\\\": \\\"2024-01-01\\\", \\\"end_date\\\": \\\"2024-03-31\\\"}]"
        ),
    )
    parser.add_argument(
        "--catalog-path",
        type=str,
        default=str(DEFAULT_CATALOG_PATH),
        help="Path to ParquetDataCatalog",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Output path for validation report JSON (default: tools/validation_reports/phase6_oos_rank{rank}_{timestamp}.json)"
        ),
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Timeout per backtest in seconds")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "--results-path",
        type=str,
        default=None,
        help="Custom path to Phase 6 results JSON file",
    )
    return parser


def main() -> int:
    """Orchestrate complete Phase 6 OOS validation workflow."""
    try:
        parser = setup_argument_parser()
        args = parser.parse_args()

        logger = setup_logging(args.verbose)
        logger.info("Starting Phase 6 OOS validation (rank=%s)", args.rank)
        start_time = time.time()

        # Rank validation
        if not (1 <= int(args.rank) <= 10):
            logger.error("Rank must be between 1 and 10 inclusive")
            return 1

        # Load Phase 6 configuration
        results_path = Path(args.results_path) if args.results_path else None
        params, baseline_metrics = load_phase6_config(args.rank, results_path, logger)
        run_id = params.run_id

        # Parse periods
        periods: List[ValidationPeriod]
        if args.periods:
            candidate = Path(args.periods)
            if candidate.exists():
                periods = parse_periods_from_file(candidate)
            else:
                periods = parse_periods_from_json(args.periods)
        else:
            periods = get_default_periods(logger)

        logger.info("Validation plan: %s periods -> %s", len(periods), [p.name for p in periods])

        # Validate catalog path
        catalog_path = Path(args.catalog_path)
        if not catalog_path.exists():
            logger.error(f"Catalog path not found: {catalog_path}")
            return 1

        # Execute backtests
        results: List[PeriodResult] = []
        total = len(periods)
        for idx, period in enumerate(periods, 1):
            logger.info("Running backtest %s/%s for period %s (%s to %s)", idx, total, period.name, period.start_date, period.end_date)
            res = run_backtest_for_period(period, params, catalog_path, args.timeout, logger)
            results.append(res)
            logger.info("Completed %s: status=%s, PnL=%.2f, Sharpe=%.3f, Trades=%s", period.name, res.status, res.total_pnl, res.sharpe_ratio, res.trade_count)

        # Compute comparison
        comparison = compute_performance_comparison(baseline_metrics, results)

        # Output path
        if args.output:
            output_path = Path(args.output)
        else:
            DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = DEFAULT_OUTPUT_DIR / f"phase6_oos_rank{args.rank}_{ts}.json"

        # Generate report and console summary
        execution_time = time.time() - start_time
        _ = generate_validation_report(args.rank, run_id, baseline_metrics, results, comparison, execution_time, output_path, logger)
        print_console_summary(args.rank, run_id, baseline_metrics, results, comparison, logger)
        logger.info("Validation completed in %.1fs. Report: %s", execution_time, output_path)
        return 0

    except KeyboardInterrupt:
        logging.getLogger(__name__).warning("Validation interrupted by user")
        return 130
    except (ValueError, FileNotFoundError) as exc:
        logging.getLogger(__name__).error(str(exc))
        return 1
    except Exception as exc:
        logging.getLogger(__name__).error(f"Unexpected error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())


