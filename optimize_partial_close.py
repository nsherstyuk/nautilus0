#!/usr/bin/env python3
"""
Small grid to test partial position close on first trailing activation.

- Uses environment overrides per run (does NOT edit .env on disk)
- Reports PnL, win rate, trades, trailing activations/moves (log scan)
- Saves CSV/JSON summaries to logs/
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
    fraction: float
    remainder_trail_mult: float
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
    fraction: float,
    remainder_trail_mult: float,
    timeout_sec: int = 900,
) -> RunResult:
    result = RunResult(
        fraction=fraction,
        remainder_trail_mult=remainder_trail_mult,
        success=False,
    )
    env = os.environ.copy()
    # Enable and parameterize partial close
    env["STRATEGY_PARTIAL_CLOSE_ENABLED"] = "true"
    env["STRATEGY_PARTIAL_CLOSE_FRACTION"] = str(fraction)
    env["STRATEGY_PARTIAL_CLOSE_MOVE_SL_TO_BE"] = env.get("STRATEGY_PARTIAL_CLOSE_MOVE_SL_TO_BE", "true")
    env["STRATEGY_PARTIAL_CLOSE_REMAINDER_TRAIL_MULTIPLIER"] = str(remainder_trail_mult)

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
    parser = argparse.ArgumentParser(description="Test partial close after trailing activation.")
    parser.add_argument("--fractions", type=str, default="0.33,0.5", help="Comma-separated fractions, e.g. 0.33,0.5")
    parser.add_argument("--trail-mults", type=str, default="1.0,1.3", help="Comma-separated multipliers for remainder trailing distance")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of combinations")
    parser.add_argument("--timeout", type=int, default=900, help="Per-run timeout seconds")
    args = parser.parse_args()

    fractions = parse_list_of_floats(args.fractions) or [0.33, 0.5]
    trail_mults = parse_list_of_floats(args.trail_mults) or [1.0, 1.3]
    combos: List[Tuple[float, float]] = [(f, m) for f in fractions for m in trail_mults if 0.0 < f < 1.0 and m > 0.0]
    if args.limit is not None and args.limit < len(combos):
        combos = combos[: args.limit]

    print("=" * 80)
    print("PARTIAL CLOSE TEST (on first trailing activation)")
    print("=" * 80)
    print(f"Runs: {len(combos)}")
    print("=" * 80)

    results: List[RunResult] = []
    start = time.time()
    for i, (frac, mult) in enumerate(combos, 1):
        print(f"\n[{i}/{len(combos)}] fraction={frac} remainder_trail_mult={mult}")
        res = run_single_backtest(frac, mult, timeout_sec=args.timeout)
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

    # Save outputs
    LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = LOGS_DIR / f"partial_close_test_{ts}.csv"
    json_path = LOGS_DIR / f"partial_close_test_{ts}.json"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "fraction",
                "remainder_trail_mult",
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
                    r.fraction,
                    r.remainder_trail_mult,
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
            f"  fraction={best.fraction} remainder_trail_mult={best.remainder_trail_mult} "
            f"PnL=${best.total_pnl:.2f} WR={best.win_rate:.1f}% Trades={best.total_trades} "
            f"TA={best.trailing_activations} TM={best.trailing_moves}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())


