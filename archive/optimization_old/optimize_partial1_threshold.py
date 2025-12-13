#!/usr/bin/env python3
"""
Optimize 'first partial close' fixed threshold (partial1) while keeping trailing
activation/distance fixed and both partial fractions at chosen values.

- Does NOT edit .env on disk; uses per-run environment overrides
- Prints per-run results; saves CSV/JSON summaries to logs/
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_ROOT / "logs" / "backtest_results"
LOGS_DIR = PROJECT_ROOT / "logs"


@dataclass
class RunResult:
    threshold_pips: float
    success: bool
    results_folder: Optional[str] = None
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    trailing_activations: int = 0
    trailing_moves: int = 0
    error: Optional[str] = None


def parse_list_of_floats(arg: Optional[str]) -> Optional[List[float]]:
    if not arg:
        return None
    return [float(x.strip()) for x in arg.split(",") if x.strip()]


def find_results_folder_from_output(output: str) -> Optional[Path]:
    m = re.search(r"Results written to:\s*(.+)", output)
    if m:
        p = Path(m.group(1).strip().strip("'\""))
        if p.exists():
            return p
    if RESULTS_DIR.exists():
        folders = sorted([f for f in RESULTS_DIR.iterdir() if f.is_dir()],
                         key=lambda x: x.stat().st_mtime, reverse=True)
        if folders:
            return folders[0]
    return None


def parse_positions(results_folder: Path) -> Tuple[float, float, float, int]:
    df = pd.read_csv(results_folder / "positions.csv")
    if "realized_pnl" not in df.columns:
        raise ValueError("positions.csv missing realized_pnl")
    if df["realized_pnl"].dtype == "object":
        vals = (
            df["realized_pnl"]
            .astype(str)
            .str.replace(" USD", "", regex=False)
            .str.replace("USD", "", regex=False)
            .str.strip()
            .astype(float)
        )
    else:
        vals = df["realized_pnl"].astype(float)
    total_pnl = float(vals.sum())
    avg_pnl = float(vals.mean()) if len(vals) else 0.0
    win_rate = float((vals > 0).mean() * 100.0) if len(vals) else 0.0
    total_trades = int(len(vals))
    return total_pnl, avg_pnl, win_rate, total_trades


def count_trailing_events_from_output(output: str) -> Tuple[int, int]:
    activations = len(re.findall(r"\[TRAILING\].*Activated", output, flags=re.IGNORECASE))
    moves = len(re.findall(r"Moving stop:", output, flags=re.IGNORECASE))
    return activations, moves


def run_single_backtest(
    threshold_pips: float,
    fraction1: float,
    fraction2: float,
    act: int,
    dist: int,
    fixed_mode: bool,
    move_sl_be_p1: bool,
    move_sl_be_p2: bool,
    timeout_sec: int = 900,
) -> RunResult:
    result = RunResult(threshold_pips=threshold_pips, success=False)
    env = os.environ.copy()

    # Fixed trailing parameters
    env["BACKTEST_TRAILING_STOP_ACTIVATION_PIPS"] = str(act)
    env["BACKTEST_TRAILING_STOP_DISTANCE_PIPS"] = str(dist)
    if fixed_mode:
        env["BACKTEST_ADAPTIVE_STOP_MODE"] = "fixed"

    # Partial 1 (before trailing activation)
    env["STRATEGY_PARTIAL1_ENABLED"] = "true"
    env["STRATEGY_PARTIAL1_FRACTION"] = str(fraction1)
    env["STRATEGY_PARTIAL1_THRESHOLD_PIPS"] = str(threshold_pips)
    env["STRATEGY_PARTIAL1_MOVE_SL_TO_BE"] = "true" if move_sl_be_p1 else "false"

    # Partial 2 (at trailing activation)
    env["STRATEGY_PARTIAL_CLOSE_ENABLED"] = "true"
    env["STRATEGY_PARTIAL_CLOSE_FRACTION"] = str(fraction2)
    env["STRATEGY_PARTIAL_CLOSE_MOVE_SL_TO_BE"] = "true" if move_sl_be_p2 else "false"
    env["STRATEGY_PARTIAL_CLOSE_REMAINDER_TRAIL_MULTIPLIER"] = "1.0"

    import subprocess

    try:
        cp = subprocess.run(
            [sys.executable, "backtest/run_backtest.py"],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
    except Exception as e:
        result.error = f"subprocess error: {e}"
        return result

    output = (cp.stdout or "") + "\n" + (cp.stderr or "")
    result.trailing_activations, result.trailing_moves = count_trailing_events_from_output(output)

    if cp.returncode != 0:
        result.error = f"backtest exit {cp.returncode}: {(cp.stderr or '')[:200]}"
        return result

    results_folder = find_results_folder_from_output(output)
    if results_folder is None:
        result.error = "could not locate results folder"
        return result
    result.results_folder = str(results_folder)

    try:
        total_pnl, avg_pnl, win_rate, total_trades = parse_positions(results_folder)
    except Exception as e:
        result.error = f"parse positions error: {e}"
        return result

    result.total_pnl = total_pnl
    result.avg_pnl = avg_pnl
    result.win_rate = win_rate
    result.total_trades = total_trades
    result.success = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize first partial close fixed threshold (partial1).")
    parser.add_argument("--thresholds", type=str, default="8,10,12,15,18", help="Comma-separated thresholds in pips")
    parser.add_argument("--fraction1", type=float, default=0.3, help="Partial1 fraction (0<f<1)")
    parser.add_argument("--fraction2", type=float, default=0.3, help="Partial2 fraction (0<f<1)")
    parser.add_argument("--act", type=int, default=35, help="Trailing activation pips (fixed)")
    parser.add_argument("--dist", type=int, default=15, help="Trailing distance pips (fixed)")
    parser.add_argument("--fixed-mode", action="store_true", help="Force BACKTEST_ADAPTIVE_STOP_MODE=fixed")
    parser.add_argument("--p1-move-be", action="store_true", help="Move SL to BE after partial1")
    parser.add_argument("--p2-move-be", action="store_true", help="Move SL to BE after partial2 (activation)")
    parser.add_argument("--timeout", type=int, default=900, help="Per-run timeout seconds")
    args = parser.parse_args()

    thresholds = parse_list_of_floats(args.thresholds) or [8, 10, 12, 15, 18]

    print("=" * 80)
    print("PARTIAL1 THRESHOLD OPTIMIZATION")
    print("=" * 80)
    print(f"Runs: {len(thresholds)}")
    print(f"Trailing: act={args.act} dist={args.dist} fixed_mode={args.fixed_mode}")
    print(f"Fractions: partial1={args.fraction1} partial2={args.fraction2}")
    print(f"Move SL to BE: p1={args.p1_move_be} p2={args.p2_move_be}")
    print("=" * 80)

    results: List[RunResult] = []
    start = time.time()
    for i, thr in enumerate(thresholds, 1):
        print(f"\n[{i}/{len(thresholds)}] partial1_threshold={thr}")
        res = run_single_backtest(
            threshold_pips=thr,
            fraction1=args.fraction1,
            fraction2=args.fraction2,
            act=args.act,
            dist=args.dist,
            fixed_mode=args.fixed_mode,
            move_sl_be_p1=args.p1_move_be,
            move_sl_be_p2=args.p2_move_be,
            timeout_sec=args.timeout,
        )
        results.append(res)
        if res.success:
            print(
                f"  -> OK PnL=${res.total_pnl:.2f} WR={res.win_rate:.1f}% Trades={res.total_trades} "
                f"TA={res.trailing_activations} TM={res.trailing_moves}"
            )
        else:
            print(f"  -> FAIL: {res.error}")

    dur = time.time() - start
    print("\n" + "=" * 80)
    print(f"DONE in {dur:.1f}s - {sum(1 for r in results if r.success)}/{len(results)} succeeded")

    LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = LOGS_DIR / f"partial1_threshold_optimization_{ts}.csv"
    json_path = LOGS_DIR / f"partial1_threshold_optimization_{ts}.json"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "partial1_threshold_pips",
                "success",
                "results_folder",
                "total_pnl",
                "avg_pnl",
                "win_rate",
                "total_trades",
                "trailing_activations",
                "trailing_moves",
                "error",
            ]
        )
        for r in results:
            w.writerow(
                [
                    r.threshold_pips,
                    r.success,
                    r.results_folder or "",
                    f"{r.total_pnl:.2f}",
                    f"{r.avg_pnl:.2f}",
                    f"{r.win_rate:.2f}",
                    r.total_trades,
                    r.trailing_activations,
                    r.trailing_moves,
                    r.error or "",
                ]
            )

    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump([asdict(r) for r in results], jf, indent=2)

    print(f"CSV saved: {csv_path}")
    print(f"JSON saved: {json_path}")

    ok = [r for r in results if r.success]
    if ok:
        ok_sorted = sorted(ok, key=lambda x: x.total_pnl, reverse=True)
        best = ok_sorted[0]
        print("\nBEST:")
        print(
            f"  partial1_threshold={best.threshold_pips} PnL=${best.total_pnl:.2f} WR={best.win_rate:.1f}% "
            f"Trades={best.total_trades} TA={best.trailing_activations} TM={best.trailing_moves}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())


