"""Generate performance comparison reports for live trading vs Phase 6 benchmarks.

Purpose
-------
Reads snapshots written by `live/performance_monitor.py` and generates daily,
weekly, monthly, or full-period reports which compare live metrics against the
Phase 6 benchmark expectations embedded in the metrics file metadata. Reports
can be written as JSON and/or Markdown and summarized on the console.

Usage
-----
    python live/generate_performance_report.py --period daily
    python live/generate_performance_report.py --period weekly --format json
    python live/generate_performance_report.py --period monthly --output logs/live/reports/monthly.json

Inputs
------
- logs/live/performance_metrics.json (default)

Outputs
-------
- logs/live/reports/{period}_report_{timestamp}.json (default JSON path)
- logs/live/reports/{period}_report_{timestamp}.md (Markdown summary when requested)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from live.performance_monitor import Phase6Benchmark


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METRICS_FILE = PROJECT_ROOT / "logs" / "live" / "performance_metrics.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "logs" / "live" / "reports"

REPORT_PERIODS: Dict[str, Optional[timedelta]] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
    "full": None,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PerformanceComparison:
    period_name: str
    start_time: str
    end_time: str
    live_metrics: Dict[str, Any]
    benchmark_metrics: Dict[str, Any]
    deviations: Dict[str, float]
    alerts_triggered: List[str]
    recommendation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period_name": self.period_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "live_metrics": self.live_metrics,
            "benchmark_metrics": self.benchmark_metrics,
            "deviations": self.deviations,
            "alerts_triggered": list(self.alerts_triggered),
            "recommendation": self.recommendation,
        }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> logging.Logger:
    """Configure console logging similar to other project tools."""
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("live")
    logger.setLevel(level)
    # Reset existing handlers for idempotency
    for h in list(logger.handlers):
        logger.removeHandler(h)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


def load_metrics_file(metrics_file: Path, logger: logging.Logger) -> Dict[str, Any]:
    """Load performance metrics JSON file and validate structure.

    Raises FileNotFoundError when missing; ValueError when malformed.
    """
    if not metrics_file.exists():
        raise FileNotFoundError(f"Metrics file not found: {metrics_file}")
    try:
        with metrics_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse JSON from {metrics_file}: {exc}") from exc

    if not isinstance(data, dict) or "metadata" not in data or "snapshots" not in data:
        raise ValueError("Invalid metrics file structure: expected 'metadata' and 'snapshots'")

    snapshots = data.get("snapshots", [])
    if snapshots:
        try:
            first_ts = pd.to_datetime(snapshots[0]["timestamp"], utc=True)
            last_ts = pd.to_datetime(snapshots[-1]["timestamp"], utc=True)
            logger.info("Loaded %s snapshots spanning %s → %s", len(snapshots), first_ts, last_ts)
        except Exception:
            logger.info("Loaded %s snapshots", len(snapshots))
    else:
        logger.info("Metrics file contains no snapshots yet.")
    return data


def filter_snapshots_by_period(snapshots: List[Dict[str, Any]], period: str, logger: logging.Logger) -> List[Dict[str, Any]]:
    """Filter snapshots by requested period name (daily/weekly/monthly/full)."""
    if period not in REPORT_PERIODS:
        raise ValueError(f"Unsupported period: {period}")
    td = REPORT_PERIODS[period]
    if td is None:
        return snapshots
    cutoff = datetime.now(timezone.utc) - td
    filtered = [s for s in snapshots if pd.to_datetime(s.get("timestamp"), utc=True) >= cutoff]
    logger.info("Filtered to %s snapshots for period '%s'", len(filtered), period)
    return filtered


def calculate_live_metrics(snapshots: List[Dict[str, Any]], logger: logging.Logger) -> Dict[str, Any]:
    """Aggregate live metrics from the filtered snapshots."""
    if not snapshots:
        return {
            "total_pnl": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "avg_pnl_per_trade": 0.0,
            "total_alerts": 0,
            "monitoring_duration_hours": 0.0,
            "expected_pnl_to_date": 0.0,
        }

    latest = snapshots[-1]
    first_ts = pd.to_datetime(snapshots[0].get("timestamp"), utc=True)
    last_ts = pd.to_datetime(latest.get("timestamp"), utc=True)
    monitoring_hours = max((last_ts - first_ts).total_seconds() / 3600.0, 0.0)

    # Count unique alerts across snapshots
    alerts: List[str] = []
    for s in snapshots:
        for a in s.get("alerts", []) or []:
            alerts.append(str(a))
    unique_alerts = sorted(set(alerts))

    # Collect recent trades from snapshots (deduplicated by id, most recent first)
    trade_records: List[Dict[str, Any]] = []
    seen_trade_ids: set[str] = set()
    for s in reversed(snapshots):
        for t in s.get("trades", []) or []:
            tid = str(t.get("id")) if t.get("id") is not None else None
            if not tid or tid in seen_trade_ids:
                continue
            seen_trade_ids.add(tid)
            trade_records.append({
                "id": tid,
                "timestamp": t.get("timestamp"),
                "pnl": float(t.get("pnl", 0.0)),
            })
            if len(trade_records) >= 50:
                break
        if len(trade_records) >= 50:
            break

    total_pnl = float(latest.get("cumulative_pnl", 0.0))
    total_trades = int(latest.get("total_trades", 0))
    win_rate = float(latest.get("win_rate", 0.0))
    sharpe = float(latest.get("rolling_sharpe_ratio", 0.0))
    max_dd = float(latest.get("max_drawdown", 0.0))
    avg_pnl = (total_pnl / total_trades) if total_trades > 0 else 0.0

    # Prefer expected-to-date carried in snapshots; report will fallback to benchmark when missing
    expected_to_date = float(latest.get("expected_pnl_so_far", 0.0))

    metrics = {
        "total_pnl": total_pnl,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "avg_pnl_per_trade": avg_pnl,
        "total_alerts": len(unique_alerts),
        "monitoring_duration_hours": monitoring_hours,
        "start_time": first_ts.isoformat(),
        "end_time": last_ts.isoformat(),
        "alerts": unique_alerts,
        "expected_pnl_to_date": expected_to_date,
        "recent_trades": trade_records,
    }
    return metrics


def calculate_deviations(live_metrics: Dict[str, Any], benchmark: Phase6Benchmark) -> Dict[str, float]:
    """Compute percentage deviations of key metrics relative to the benchmark."""
    def pct_delta(live_value: float, bench_value: float) -> float:
        if bench_value == 0:
            return 0.0
        return (float(live_value) - float(bench_value)) / float(bench_value) * 100.0

    deviations: Dict[str, float] = {}
    deviations["sharpe_ratio_deviation_pct"] = pct_delta(live_metrics.get("sharpe_ratio", 0.0), benchmark.expected_sharpe_ratio)
    deviations["win_rate_deviation_pct"] = pct_delta(live_metrics.get("win_rate", 0.0), benchmark.expected_win_rate)
    # Prefer deviation vs expected-to-date PnL rather than full backtest
    expected_to_date = float(live_metrics.get("expected_pnl_to_date", 0.0))
    deviations["pnl_vs_expected_to_date_deviation_pct"] = pct_delta(live_metrics.get("total_pnl", 0.0), expected_to_date)

    # Trade frequency deviation: compare trades per day
    hours = float(live_metrics.get("monitoring_duration_hours", 0.0))
    days = max(hours / 24.0, 1e-9)
    live_trades_per_day = float(live_metrics.get("total_trades", 0)) / days
    period_days = float(benchmark.expected_period_days) if getattr(benchmark, "expected_period_days", None) else 365.0
    if period_days <= 0:
        period_days = 365.0
    bench_trades_per_day = float(benchmark.expected_trade_count) / period_days if benchmark.expected_trade_count else 0.0
    deviations["trade_frequency_deviation_pct"] = (
        0.0 if bench_trades_per_day == 0 else (live_trades_per_day - bench_trades_per_day) / bench_trades_per_day * 100.0
    )

    return deviations


def generate_recommendation(deviations: Dict[str, float], alerts: List[str]) -> str:
    """Return PASS/CAUTION/FAIL given deviations and triggered alerts."""
    try:
        win_dev = deviations.get("win_rate_deviation_pct", 0.0)
        sharpe_dev = deviations.get("sharpe_ratio_deviation_pct", 0.0)
        trade_freq_dev = deviations.get("trade_frequency_deviation_pct", 0.0)
        drawdown_flag = any("drawdown" in a.lower() for a in alerts)

        if win_dev <= -10.0 or sharpe_dev <= -20.0 or drawdown_flag:
            return "FAIL"
        if abs(trade_freq_dev) >= 50.0 or alerts:
            return "CAUTION"
        return "PASS"
    except Exception:
        return "CAUTION"


def create_performance_comparison(period: str, snapshots: List[Dict[str, Any]], benchmark: Phase6Benchmark, logger: logging.Logger) -> PerformanceComparison:
    """Assemble a comparison for the requested period."""
    filtered = filter_snapshots_by_period(snapshots, period, logger)
    live_metrics = calculate_live_metrics(filtered, logger)
    deviations = calculate_deviations(live_metrics, benchmark)
    alerts = list(live_metrics.get("alerts", []))

    benchmark_metrics = {
        "sharpe_ratio": benchmark.expected_sharpe_ratio,
        "total_pnl": benchmark.expected_total_pnl,
        "win_rate": benchmark.expected_win_rate,
        "trade_count": benchmark.expected_trade_count,
        "max_drawdown": benchmark.expected_max_drawdown,
        "avg_winner": benchmark.expected_avg_winner,
        "avg_loser": benchmark.expected_avg_loser,
        "expectancy": benchmark.expected_expectancy,
        "rejected_signals": benchmark.expected_rejected_signals,
        "consecutive_losses": benchmark.expected_consecutive_losses,
    }

    start_time = live_metrics.get("start_time", "")
    end_time = live_metrics.get("end_time", "")
    recommendation = generate_recommendation(deviations, alerts)
    return PerformanceComparison(
        period_name=period,
        start_time=start_time,
        end_time=end_time,
        live_metrics=live_metrics,
        benchmark_metrics=benchmark_metrics,
        deviations=deviations,
        alerts_triggered=alerts,
        recommendation=recommendation,
    )


def generate_json_report(comparison: PerformanceComparison, output_path: Path, logger: logging.Logger) -> bool:
    """Write JSON comparison report to the output path."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(comparison.to_dict(), f, indent=2)
        logger.info("JSON report written: %s", output_path.as_posix())
        return True
    except Exception as exc:
        logger.error("Failed to write JSON report: %s", exc)
        return False


def _fmt_pct(value: float) -> str:
    try:
        return f"{value:.2%}"
    except Exception:
        return "0.00%"


def generate_markdown_summary(comparison: PerformanceComparison, output_path: Path, logger: logging.Logger) -> bool:
    """Write a human-readable Markdown summary file."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        live = comparison.live_metrics
        bench = comparison.benchmark_metrics
        dev = comparison.deviations

        lines: List[str] = []
        lines.append(f"# Performance Report ({comparison.period_name.capitalize()})")
        lines.append("")
        lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"Period: {comparison.start_time} → {comparison.end_time}")
        lines.append("")

        lines.append("## Live Performance Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---:|")
        lines.append(f"| Total PnL | ${live.get('total_pnl', 0.0):.2f} |")
        lines.append(f"| Total Trades | {live.get('total_trades', 0)} |")
        lines.append(f"| Win Rate | {_fmt_pct(live.get('win_rate', 0.0))} |")
        lines.append(f"| Sharpe Ratio | {live.get('sharpe_ratio', 0.0):.3f} |")
        lines.append(f"| Max Drawdown | ${live.get('max_drawdown', 0.0):.2f} |")
        lines.append(f"| Avg PnL/Trade | ${live.get('avg_pnl_per_trade', 0.0):.2f} |")
        lines.append(f"| Duration (hours) | {live.get('monitoring_duration_hours', 0.0):.1f} |")
        if float(live.get("expected_pnl_to_date", 0.0)) != 0.0:
            lines.append(f"| Expected PnL To Date | ${live.get('expected_pnl_to_date', 0.0):.2f} |")
        lines.append("")

        lines.append("## Phase 6 Benchmark")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---:|")
        lines.append(f"| Total PnL | ${bench.get('total_pnl', 0.0):.2f} |")
        lines.append(f"| Total Trades | {bench.get('trade_count', 0)} |")
        lines.append(f"| Win Rate | {_fmt_pct(bench.get('win_rate', 0.0))} |")
        lines.append(f"| Sharpe Ratio | {bench.get('sharpe_ratio', 0.0):.3f} |")
        lines.append(f"| Max Drawdown | ${bench.get('max_drawdown', 0.0):.2f} |")
        lines.append(f"| Avg Winner | ${bench.get('avg_winner', 0.0):.2f} |")
        lines.append(f"| Avg Loser | ${bench.get('avg_loser', 0.0):.2f} |")
        lines.append(f"| Expectancy | ${bench.get('expectancy', 0.0):.2f} |")
        lines.append("")

        lines.append("## Performance Comparison")
        lines.append("")
        lines.append("| Metric | Deviation |")
        lines.append("|---|---:|")
        lines.append(f"| Win Rate | {dev.get('win_rate_deviation_pct', 0.0):+.1f}% |")
        lines.append(f"| Sharpe Ratio | {dev.get('sharpe_ratio_deviation_pct', 0.0):+.1f}% |")
        lines.append(f"| PnL vs Expected-To-Date | {dev.get('pnl_vs_expected_to_date_deviation_pct', 0.0):+.1f}% |")
        lines.append(f"| Trade Frequency | {dev.get('trade_frequency_deviation_pct', 0.0):+.1f}% |")
        lines.append("")

        # Optional Trade Summary (recent trades)
        recent_trades = list(comparison.live_metrics.get("recent_trades", []))
        if recent_trades:
            lines.append("## Recent Trades (up to 50)")
            lines.append("")
            lines.append("| ID | Timestamp | PnL |")
            lines.append("|---|---|---:|")
            total_recent_pnl = 0.0
            for t in recent_trades:
                total_recent_pnl += float(t.get("pnl", 0.0))
                lines.append(f"| {t.get('id','')} | {t.get('timestamp','')} | ${float(t.get('pnl',0.0)):.2f} |")
            lines.append("")
            lines.append(f"Recent trades count: {len(recent_trades)} | Total recent PnL: ${total_recent_pnl:.2f}")
            lines.append("")

        lines.append("## Alerts")
        lines.append("")
        if comparison.alerts_triggered:
            for a in comparison.alerts_triggered:
                lines.append(f"- {a}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Recommendation")
        lines.append("")
        rec = comparison.recommendation
        symbol = "✅" if rec == "PASS" else ("⚠️" if rec == "CAUTION" else "❌")
        lines.append(f"{symbol} {rec}")

        content = "\n".join(lines)
        with output_path.open("w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Markdown summary written: %s", output_path.as_posix())
        return True
    except Exception as exc:
        logger.error("Failed to write Markdown summary: %s", exc)
        return False


def print_console_summary(comparison: PerformanceComparison, logger: logging.Logger) -> None:
    """Print a brief console summary of performance vs benchmark."""
    rec_symbol = {
        "PASS": "✅",
        "CAUTION": "⚠️",
        "FAIL": "❌",
    }.get(comparison.recommendation, "")

    print("")
    print(f"=== Live Performance Report ({comparison.period_name}) ===")
    print(f"Range: {comparison.start_time} → {comparison.end_time}")
    print("")
    print("Live Metrics:")
    lm = comparison.live_metrics
    print(
        f"  PnL=${lm.get('total_pnl', 0.0):.2f} | Trades={lm.get('total_trades', 0)} | "
        f"WinRate={lm.get('win_rate', 0.0)*100:.1f}% | Sharpe={lm.get('sharpe_ratio', 0.0):.3f} | "
        f"MaxDD=${lm.get('max_drawdown', 0.0):.2f}"
    )
    print("Benchmark:")
    bm = comparison.benchmark_metrics
    print(
        f"  PnL=${bm.get('total_pnl', 0.0):.2f} | Trades={bm.get('trade_count', 0)} | "
        f"WinRate={bm.get('win_rate', 0.0)*100:.1f}% | Sharpe={bm.get('sharpe_ratio', 0.0):.3f} | "
        f"MaxDD=${bm.get('max_drawdown', 0.0):.2f}"
    )
    print("Deviations:")
    dv = comparison.deviations
    print(
        f"  WinRate={dv.get('win_rate_deviation_pct', 0.0):+.1f}% | "
        f"Sharpe={dv.get('sharpe_ratio_deviation_pct', 0.0):+.1f}% | "
        f"PnL_vs_ExpectedToDate={dv.get('pnl_vs_expected_to_date_deviation_pct', 0.0):+.1f}% | "
        f"TradeFreq={dv.get('trade_frequency_deviation_pct', 0.0):+.1f}%"
    )
    if comparison.alerts_triggered:
        print("Alerts:")
        for a in comparison.alerts_triggered:
            print(f"  - {a}")
    print("")
    print(f"Recommendation: {rec_symbol} {comparison.recommendation}")
    print("")


def setup_argument_parser() -> argparse.ArgumentParser:
    """Build CLI arguments parser."""
    parser = argparse.ArgumentParser(description="Generate live performance comparison report.")
    parser.add_argument(
        "--period",
        type=str,
        choices=list(REPORT_PERIODS.keys()),
        default="daily",
        help="Report period",
    )
    parser.add_argument(
        "--metrics-file",
        type=str,
        default=str(DEFAULT_METRICS_FILE),
        help="Path to performance metrics JSON file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for JSON report (default auto in logs/live/reports)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "markdown", "both"],
        default="both",
        help="Output format",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--no-console", action="store_true", help="Skip console output")
    return parser


def main() -> int:
    parser = setup_argument_parser()
    args = parser.parse_args()

    logger = setup_logging(verbose=bool(args.verbose))
    logger.info("Generating performance report for period: %s", args.period)

    try:
        metrics_path = Path(args.metrics_file)
        data = load_metrics_file(metrics_path, logger)
        meta = data.get("metadata", {})
        bench_meta = meta.get("benchmark", {})
        benchmark = Phase6Benchmark(
            rank=int(bench_meta.get("rank", 1)),
            run_id=int(bench_meta.get("run_id", 0)),
            expected_sharpe_ratio=float(bench_meta.get("expected_sharpe_ratio", 0.0)),
            expected_total_pnl=float(bench_meta.get("expected_total_pnl", 0.0)),
            expected_win_rate=float(bench_meta.get("expected_win_rate", 0.0)),
            expected_trade_count=int(bench_meta.get("expected_trade_count", 0)),
            expected_max_drawdown=float(bench_meta.get("expected_max_drawdown", 0.0)),
            expected_avg_winner=float(bench_meta.get("expected_avg_winner", 0.0)),
            expected_avg_loser=float(bench_meta.get("expected_avg_loser", 0.0)),
            expected_expectancy=float(bench_meta.get("expected_expectancy", 0.0)),
            expected_rejected_signals=int(bench_meta.get("expected_rejected_signals", 0)),
            expected_consecutive_losses=int(bench_meta.get("expected_consecutive_losses", 0)),
            expected_period_days=(
                float(bench_meta.get("expected_period_days"))
                if bench_meta.get("expected_period_days") is not None and str(bench_meta.get("expected_period_days")).strip() != ""
                else None
            ),
        )
        snapshots: List[Dict[str, Any]] = data.get("snapshots", [])
        if not snapshots:
            logger.error("No snapshots available in metrics file. Aborting report generation.")
            return 1

        comparison = create_performance_comparison(args.period, snapshots, benchmark, logger)

        # Determine output paths
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_json = Path(args.output) if args.output else (DEFAULT_OUTPUT_DIR / f"{args.period}_report_{timestamp}.json")
        output_md = output_json.with_suffix(".md")

        ok = True
        if args.format in ("json", "both"):
            ok = generate_json_report(comparison, output_json, logger) and ok
        if args.format in ("markdown", "both"):
            ok = generate_markdown_summary(comparison, output_md, logger) and ok

        if not args.no_console:
            print_console_summary(comparison, logger)

        logger.info("Report generation complete.")
        return 0 if ok else 1
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected error during report generation: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())


