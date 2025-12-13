#!/usr/bin/env python3
"""Trailing vs no-trailing validation harness.

Runs two backtests using the current .env configuration:
1. Trailing disabled (by overriding key env vars so trailing never activates)
2. Trailing enabled (baseline config)

Each run is archived under validation_results/trailing_comparison/<label>
and key metrics (PnL, trades, win rate, expectancy) are compared.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

RESULTS_BASE = Path("logs/backtest_results")
ARCHIVE_BASE = Path("validation_results/trailing_comparison")

TRAILING_DISABLED_ENV: Dict[str, str] = {
    # Push activation so far away that trailing never turns on
    "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": "1000",
    # Keep distance reasonable but unused because activation never triggers
    "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": "10",
    # Force fixed stops so adaptive logic cannot tighten the threshold
    "BACKTEST_ADAPTIVE_STOP_MODE": "fixed",
    # Ensure regime multipliers do not change activation
    "STRATEGY_REGIME_DETECTION_ENABLED": "false",
    # Hard-disable duration-based trailing helpers regardless of .env
    "STRATEGY_TRAILING_DURATION_ENABLED": "false",
    "STRATEGY_TRAILING_DURATION_ACTIVATE_IF_NOT_ACTIVE": "false",
    "STRATEGY_TRAILING_DURATION_REMOVE_TP": "false",
}


@dataclass
class RunResult:
    label: str
    folder: Path
    metrics: Dict[str, Optional[float]]


def ensure_directories() -> None:
    ARCHIVE_BASE.mkdir(parents=True, exist_ok=True)


def list_result_folders() -> list[Path]:
    if not RESULTS_BASE.exists():
        return []
    return [
        path
        for path in RESULTS_BASE.iterdir()
        if path.is_dir() and path.name.startswith("EUR-USD_")
    ]


def detect_new_folder(previous: set[str]) -> Path:
    folders = sorted(list_result_folders(), key=lambda p: p.stat().st_mtime, reverse=True)
    for folder in folders:
        if folder.name not in previous:
            return folder
    if folders:
        return folders[0]
    raise RuntimeError("No backtest result folders found after run")


def archive_results(source: Path, label: str) -> Path:
    destination = ARCHIVE_BASE / label
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


def run_backtest(label: str, env_overrides: Optional[Dict[str, str]] = None) -> Path:
    ensure_directories()
    before = {folder.name for folder in list_result_folders()}
    env = os.environ.copy()
    if env_overrides:
        env.update({k: str(v) for k, v in env_overrides.items()})

    print(f"\n🚀 Running backtest [{label}]...")
    result = subprocess.run(
        [sys.executable, "backtest/run_backtest.py"],
        cwd=".",
        env=env,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Backtest [{label}] failed with exit code {result.returncode}")

    # Give the filesystem a moment to flush timestamps on slower disks
    time.sleep(1.0)
    latest_folder = detect_new_folder(before)
    archived_folder = archive_results(latest_folder, label)
    print(f"📁 Archived {label} results to {archived_folder}")
    return archived_folder


def _first_available(data: dict, keys: list[str]) -> Optional[float]:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def extract_metrics(folder: Path) -> Dict[str, Optional[float]]:
    perf_path = folder / "performance_stats.json"
    perf_data: dict = {}
    if perf_path.exists():
        with open(perf_path, "r", encoding="utf-8") as f:
            perf_data = json.load(f)

    pnls = perf_data.get("pnls", {}) or {}

    pnl = _first_available(
        pnls,
        [
            "PnL (total)",
            "Total PnL",
            "Net PnL",
        ],
    )
    if pnl is None:
        pnl = perf_data.get("total_pnl")

    win_rate = _first_available(pnls, ["Win Rate"])
    if win_rate is None:
        win_rate = perf_data.get("win_rate")

    expectancy = _first_available(pnls, ["Expectancy"]) or perf_data.get("expectancy")

    trades: Optional[int]
    positions_path = folder / "positions.csv"
    if positions_path.exists():
        positions = pd.read_csv(positions_path)
        trades = len(positions)
    else:
        trades = perf_data.get("total_trades")

    return {
        "pnl": float(pnl) if pnl is not None else None,
        "win_rate": float(win_rate) if win_rate is not None else None,
        "expectancy": float(expectancy) if expectancy is not None else None,
        "trades": float(trades) if trades is not None else None,
    }


def print_metrics(label: str, metrics: Dict[str, Optional[float]]) -> None:
    pnl = metrics.get("pnl")
    trades = metrics.get("trades")
    win_rate = metrics.get("win_rate")
    expectancy = metrics.get("expectancy")

    print(f"\n📊 {label} metrics:")
    if pnl is not None:
        print(f"   PnL: {pnl:,.2f}")
    else:
        print("   PnL: n/a")

    if trades is not None:
        print(f"   Trades: {int(trades)}")
    else:
        print("   Trades: n/a")

    if win_rate is not None:
        pct = win_rate * 100 if win_rate <= 1 else win_rate
        print(f"   Win Rate: {pct:.2f}%")
    else:
        print("   Win Rate: n/a")

    if expectancy is not None:
        print(f"   Expectancy: {expectancy:.2f}")
    else:
        print("   Expectancy: n/a")


def print_comparison(enabled: Dict[str, Optional[float]], disabled: Dict[str, Optional[float]]) -> None:
    pnl_enabled = enabled.get("pnl")
    pnl_disabled = disabled.get("pnl")

    print("\n" + "=" * 80)
    print("🔍 TRAILING IMPACT ANALYSIS")
    print("=" * 80)

    if pnl_enabled is not None and pnl_disabled is not None:
        pnl_diff = pnl_enabled - pnl_disabled
        pct = (pnl_diff / abs(pnl_disabled) * 100) if pnl_disabled not in (0, None) else float("inf")
        print(f"PnL Difference (Enabled - Disabled): {pnl_diff:+,.2f} ({pct:+.2f}%)")
    else:
        print("PnL Difference: n/a")

    trades_enabled = enabled.get("trades")
    trades_disabled = disabled.get("trades")
    if trades_enabled is not None and trades_disabled is not None:
        trade_diff = trades_enabled - trades_disabled
        print(f"Trade Count Difference: {trade_diff:+.0f}")

    win_enabled = enabled.get("win_rate")
    win_disabled = disabled.get("win_rate")
    if win_enabled is not None and win_disabled is not None:
        win_diff = (win_enabled - win_disabled) * 100
        print(f"Win Rate Difference: {win_diff:+.2f} percentage points")

    expectancy_enabled = enabled.get("expectancy")
    expectancy_disabled = disabled.get("expectancy")
    if expectancy_enabled is not None and expectancy_disabled is not None:
        exp_diff = expectancy_enabled - expectancy_disabled
        print(f"Expectancy Difference: {exp_diff:+.2f}")

    if pnl_enabled is not None and pnl_disabled is not None:
        if pnl_enabled > pnl_disabled:
            print("\n✅ Trailing improves PnL versus disabled run.")
        elif pnl_enabled < pnl_disabled:
            print("\n⚠️  Trailing hurts PnL versus disabled run.")
        else:
            print("\nℹ️  Trailing PnL matches disabled run.")


def execute_comparison() -> None:
    print("=" * 80)
    print("🧪 TRAILING vs NO-TRAILING VALIDATION")
    print("=" * 80)

    disabled_folder = run_backtest("trailing_disabled", TRAILING_DISABLED_ENV)
    enabled_folder = run_backtest("trailing_enabled", None)

    disabled_metrics = extract_metrics(disabled_folder)
    enabled_metrics = extract_metrics(enabled_folder)

    print_metrics("Trailing DISABLED", disabled_metrics)
    print_metrics("Trailing ENABLED", enabled_metrics)
    print_comparison(enabled_metrics, disabled_metrics)


if __name__ == "__main__":
    try:
        execute_comparison()
    except Exception as exc:  # pragma: no cover - top-level exception handler
        print(f"\n❌ Comparison failed: {exc}")
        sys.exit(1)