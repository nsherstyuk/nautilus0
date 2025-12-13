#!/usr/bin/env python3
"""
Optimize trailing stop settings by grid-searching activation and distance.

Features:
- Uses environment overrides per run (does NOT edit .env on disk)
- Optional activation assurance: widen TP to give trailing room to activate
- Records PnL, win rate, trades, trailing activation/move counts (via log scan)
- Saves CSV and JSON summaries to logs/
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
from typing import Iterable, List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_ROOT / "logs" / "backtest_results"
LOGS_DIR = PROJECT_ROOT / "logs"


@dataclass
class RunResult:
    activation_pips: int
    distance_pips: int
    take_profit_pips: Optional[int]
    success: bool
    results_folder: Optional[str] = None
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    trailing_activations: int = 0
    trailing_moves: int = 0
    error: Optional[str] = None


def parse_list_of_ints(arg: Optional[str]) -> Optional[List[int]]:
    if not arg:
        return None
    return [int(x.strip()) for x in arg.split(",") if x.strip()]


def find_results_folder_from_output(output: str) -> Optional[Path]:
    # backtest/run_backtest.py prints: "Results written to: logs\backtest_results\EUR-USD_..."
    m = re.search(r"Results written to:\s*(.+)", output)
    if m:
        p = Path(m.group(1).strip().strip("'\""))
        if p.exists():
            return p
    # Fallback: latest folder by mtime
    if RESULTS_DIR.exists():
        folders = sorted([f for f in RESULTS_DIR.iterdir() if f.is_dir()],
                         key=lambda x: x.stat().st_mtime, reverse=True)
        if folders:
            return folders[0]
    return None


def parse_positions(results_folder: Path) -> Tuple[float, float, float, int]:
    positions_file = results_folder / "positions.csv"
    if not positions_file.exists():
        raise FileNotFoundError(f"positions.csv not found in {results_folder}")
    df = pd.read_csv(positions_file)
    if "realized_pnl" not in df.columns:
        raise ValueError("positions.csv missing realized_pnl")
    # realized_pnl may be like "123.45 USD"
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
    # Count our diagnostic prints injected by the strategy
    activations = len(re.findall(r"\[TRAILING\].*Activated", output, flags=re.IGNORECASE))
    moves = len(re.findall(r"Moving stop:", output, flags=re.IGNORECASE))
    return activations, moves


def run_single_backtest(
    activation_pips: int,
    distance_pips: int,
    take_profit_override: Optional[int],
    ensure_fixed_mode: bool,
    extra_env: Optional[dict] = None,
    timeout_sec: int = 900,
) -> RunResult:
    """
    Execute one backtest with env overrides and parse metrics.
    """
    result = RunResult(
        activation_pips=activation_pips,
        distance_pips=distance_pips,
        take_profit_pips=take_profit_override,
        success=False,
    )
    env = os.environ.copy()
    # Trailing settings (validation requires activation > distance)
    env["BACKTEST_TRAILING_STOP_ACTIVATION_PIPS"] = str(activation_pips)
    env["BACKTEST_TRAILING_STOP_DISTANCE_PIPS"] = str(distance_pips)
    # Optionally widen TP to allow trailing to activate
    if take_profit_override is not None:
        env["BACKTEST_TAKE_PROFIT_PIPS"] = str(take_profit_override)
    if ensure_fixed_mode:
        env["BACKTEST_ADAPTIVE_STOP_MODE"] = "fixed"
    if extra_env:
        env.update(extra_env)

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


def default_combinations() -> List[Tuple[int, int]]:
    # Reasonable grid; activation strictly greater than distance
    combos: List[Tuple[int, int]] = []
    for act in (10, 12, 15):
        for dist in (6, 8, 10):
            if act > dist:
                combos.append((act, dist))
    return combos


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Optimize trailing stop activation and distance (grid search)."
    )
    parser.add_argument(
        "--activations",
        type=str,
        default=None,
        help="Comma-separated activation pips, e.g. 8,10,12,15",
    )
    parser.add_argument(
        "--distances",
        type=str,
        default=None,
        help="Comma-separated distance pips, e.g. 5,8,10",
    )
    parser.add_argument(
        "--ensure-activation",
        action="store_true",
        help="Widen TP to help trailing activate (sets TP if --tp is provided).",
    )
    parser.add_argument(
        "--tp",
        type=int,
        default=None,
        help="TP override used when --ensure-activation is set (e.g., 100 or 120).",
    )
    parser.add_argument(
        "--fixed-mode",
        action="store_true",
        help="Force BACKTEST_ADAPTIVE_STOP_MODE=fixed during tests.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of combinations (for quick runs).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Per-run timeout seconds (default: 900).",
    )
    args = parser.parse_args()

    activations = parse_list_of_ints(args.activations)
    distances = parse_list_of_ints(args.distances)
    if activations is None or distances is None:
        combos = default_combinations()
    else:
        combos = [(a, d) for a in activations for d in distances if a > d]

    if args.limit is not None and args.limit < len(combos):
        combos = combos[: args.limit]

    take_profit_override = args.tp if args.ensure_activation else None
    ensure_fixed_mode = args.fixed_mode

    print("=" * 80)
    print("TRAILING STOP OPTIMIZATION")
    print("=" * 80)
    print(f"Runs: {len(combos)}")
    print(f"Ensure activation (TP override): {args.ensure_activation} (TP={take_profit_override})")
    print(f"Fixed mode: {ensure_fixed_mode}")
    print("=" * 80)

    results: List[RunResult] = []
    start = time.time()
    for i, (act, dist) in enumerate(combos, 1):
        print(f"\n[{i}/{len(combos)}] act={act} dist={dist}")
        run_res = run_single_backtest(
            activation_pips=act,
            distance_pips=dist,
            take_profit_override=take_profit_override,
            ensure_fixed_mode=ensure_fixed_mode,
            extra_env=None,
            timeout_sec=args.timeout,
        )
        results.append(run_res)
        if run_res.success:
            print(
                f"  -> OK PnL=${run_res.total_pnl:.2f} WR={run_res.win_rate:.1f}% Trades={run_res.total_trades} "
                f"TA={run_res.trailing_activations} TM={run_res.trailing_moves}"
            )
        else:
            print(f"  -> FAIL: {run_res.error}")

    dur = time.time() - start
    print("\n" + "=" * 80)
    print(f"DONE in {dur:.1f}s - {sum(1 for r in results if r.success)}/{len(results)} succeeded")

    # Save outputs
    LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = LOGS_DIR / f"trailing_stop_optimization_{ts}.csv"
    json_path = LOGS_DIR / f"trailing_stop_optimization_{ts}.json"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "activation_pips",
                "distance_pips",
                "take_profit_pips",
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
                    r.activation_pips,
                    r.distance_pips,
                    r.take_profit_pips if r.take_profit_pips is not None else "",
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

    # Show quick top results
    ok = [r for r in results if r.success]
    if ok:
        ok_sorted = sorted(ok, key=lambda x: x.total_pnl, reverse=True)
        best = ok_sorted[0]
        print("\nBEST:")
        print(
            f"  act={best.activation_pips} dist={best.distance_pips} "
            f"TP={best.take_profit_pips} PnL=${best.total_pnl:.2f} WR={best.win_rate:.1f}% "
            f"Trades={best.total_trades} TA={best.trailing_activations} TM={best.trailing_moves}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())


