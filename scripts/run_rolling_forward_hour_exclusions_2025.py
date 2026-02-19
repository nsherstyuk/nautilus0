#!/usr/bin/env python3
"""Rolling forward hour-exclusion walk-forward test for 2025.

Protocol per fold:
1) Train window: run backtest with exclusions disabled.
2) Build weekday-hour exclusions from train results using rule:
   WR < min_wr AND PnL <= 0 AND trades >= min_trades.
3) Test window control: run backtest with exclusions disabled.
4) Test window filtered: run same backtest with derived weekday exclusions enabled.
5) Record fold metrics and deltas.

This script updates `.env.mtf_v2` temporarily and restores it at the end.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env.mtf_v2"
BACKTEST_RESULTS = PROJECT_ROOT / "backtest_results"
BACKTEST_ENTRY = PROJECT_ROOT / "run_backtest_mtf_v2_entry_confirmed.py"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class SummaryMetrics:
    total_trades: int
    total_pnl: float
    win_rate: float
    max_drawdown_pct: Optional[float]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rolling walk-forward hour exclusion test for 2025")
    p.add_argument("--start", default="2025-01-01", help="Global start date (YYYY-MM-DD)")
    p.add_argument("--end", default="2025-12-30", help="Global end date (YYYY-MM-DD)")
    p.add_argument("--train-days", type=int, default=56, help="Training window size in days")
    p.add_argument("--test-days", type=int, default=28, help="Forward test window size in days")
    p.add_argument("--step-days", type=int, default=28, help="How far to roll each fold")
    p.add_argument("--min-wr", type=float, default=65.0, help="Exclude when WR < min-wr")
    p.add_argument("--min-trades", type=int, default=5, help="Exclude when trades >= min-trades")
    p.add_argument("--output-csv", default="logs/rolling_hour_exclusion_2025_results.csv", help="Output CSV path")
    p.add_argument("--timezone", default="EST", help="Config timezone for exclusion mapping")
    p.add_argument("--max-folds", type=int, default=0, help="Run only first N folds (0 = all)")
    p.add_argument("--dry-run", action="store_true", help="Print folds only, do not run backtests")
    return p.parse_args()


def parse_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def set_env_key(content: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(content):
        return pattern.sub(line, content)
    if not content.endswith("\n"):
        content += "\n"
    return content + line + "\n"


def update_env(
    base_content: str,
    start_date: date,
    end_date: date,
    excluded_mode: str,
    excluded_hours: Optional[Dict[str, List[int]]] = None,
    timezone: str = "EST",
) -> str:
    content = base_content
    content = set_env_key(content, "MTF2_BACKTEST_START", start_date.strftime("%Y-%m-%d"))
    content = set_env_key(content, "MTF2_BACKTEST_END", end_date.strftime("%Y-%m-%d"))
    content = set_env_key(content, "MTF2_EXCLUDED_HOURS_MODE", excluded_mode)
    content = set_env_key(content, "MTF2_CONFIG_TIMEZONE", timezone)

    excluded_hours = excluded_hours or {d: [] for d in DAYS}
    for day in DAYS:
        key = f"MTF2_EXCLUDED_HOURS_{day.upper()}"
        val = ",".join(str(h) for h in sorted(excluded_hours.get(day, [])))
        content = set_env_key(content, key, val)

    return content


def latest_result_dir(prefix: str, started_at: datetime) -> Optional[Path]:
    candidates = []
    for d in BACKTEST_RESULTS.glob(f"{prefix}*"):
        if d.is_dir() and datetime.fromtimestamp(d.stat().st_ctime) >= started_at:
            candidates.append(d)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_ctime, reverse=True)
    return candidates[0]


def run_backtest_and_get_result_dir() -> Path:
    started_at = datetime.now() - timedelta(seconds=2)
    cmd = [sys.executable, str(BACKTEST_ENTRY)]
    subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=True)
    out = latest_result_dir("MTF_V2_ENTRY_CONFIRMED_", started_at)
    if out is None:
        raise RuntimeError("Could not locate newly created backtest result directory.")
    return out


def read_matrix(path: Path) -> Dict[int, Dict[str, float]]:
    data: Dict[int, Dict[str, float]] = {}
    with path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            h = int(row["hour_EST"])
            data[h] = {d: float(row[d]) for d in DAYS}
    return data


def derive_exclusions(result_dir: Path, min_wr: float, min_trades: int) -> Dict[str, List[int]]:
    pnl_file = sorted(result_dir.glob("hour_weekday_pnl_matrix_*.csv"))
    trades_file = sorted(result_dir.glob("hour_weekday_trades_matrix_*.csv"))
    wr_file = sorted(result_dir.glob("hour_weekday_winrate_matrix_*.csv"))
    if not (pnl_file and trades_file and wr_file):
        raise RuntimeError(f"Missing hour-weekday matrix files in {result_dir}")

    pnl = read_matrix(pnl_file[0])
    trades = read_matrix(trades_file[0])
    wr = read_matrix(wr_file[0])

    out: Dict[str, List[int]] = {d: [] for d in DAYS}
    for h in range(24):
        if h not in pnl or h not in trades or h not in wr:
            continue
        for d in DAYS:
            t = int(trades[h][d])
            p = float(pnl[h][d])
            w = float(wr[h][d])
            if t >= min_trades and w < min_wr and p <= 0:
                out[d].append(h)
    return out


def parse_summary(summary_path: Path) -> SummaryMetrics:
    text = read_text(summary_path)

    def _m(pattern: str) -> Optional[str]:
        m = re.search(pattern, text, flags=re.MULTILINE)
        return m.group(1) if m else None

    t = _m(r"^Total Trades:\s+(\d+)")
    p = _m(r"^Total P&L:\s+\$([-,\d\.]+)")
    w = _m(r"^Win Rate:\s+([\d\.]+)%")
    dd = _m(r"^Max Drawdown:\s+\$[-,\d\.]+\s+\(([-\d\.]+)%\)")

    if t is None or p is None or w is None:
        raise RuntimeError(f"Could not parse summary metrics from {summary_path}")

    return SummaryMetrics(
        total_trades=int(t),
        total_pnl=float(p.replace(",", "")),
        win_rate=float(w),
        max_drawdown_pct=float(dd) if dd is not None else None,
    )


def load_summary_metrics(result_dir: Path) -> SummaryMetrics:
    summaries = sorted(result_dir.glob("summary_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not summaries:
        raise RuntimeError(f"No summary_*.txt found in {result_dir}")
    return parse_summary(summaries[0])


def exclusion_count(ex: Dict[str, List[int]]) -> int:
    return sum(len(v) for v in ex.values())


def build_folds(global_start: date, global_end: date, train_days: int, test_days: int, step_days: int) -> List[Tuple[date, date, date, date]]:
    folds = []
    cur = global_start
    one_day = timedelta(days=1)
    while True:
        train_start = cur
        train_end = train_start + timedelta(days=train_days - 1)
        test_start = train_end + one_day
        test_end = test_start + timedelta(days=test_days - 1)
        if test_end > global_end:
            break
        folds.append((train_start, train_end, test_start, test_end))
        cur = cur + timedelta(days=step_days)
    return folds


def main() -> None:
    args = parse_args()

    if not ENV_FILE.exists():
        raise FileNotFoundError(f"Missing env file: {ENV_FILE}")

    global_start = parse_yyyy_mm_dd(args.start)
    global_end = parse_yyyy_mm_dd(args.end)
    folds = build_folds(global_start, global_end, args.train_days, args.test_days, args.step_days)

    if args.max_folds and args.max_folds > 0:
        folds = folds[: args.max_folds]

    if not folds:
        raise ValueError("No valid folds generated. Adjust date range/window sizes.")

    output_csv = (PROJECT_ROOT / args.output_csv).resolve() if not Path(args.output_csv).is_absolute() else Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 90)
    print("ROLLING FORWARD HOUR EXCLUSION TEST")
    print(f"Range: {global_start} -> {global_end}")
    print(f"Folds: {len(folds)} | train={args.train_days}d | test={args.test_days}d | step={args.step_days}d")
    print(f"Rule: exclude if WR < {args.min_wr} AND PnL <= 0 AND trades >= {args.min_trades}")
    print("=" * 90)

    for i, (tr_s, tr_e, te_s, te_e) in enumerate(folds, 1):
        print(f"Fold {i:02d}: train {tr_s}..{tr_e} | test {te_s}..{te_e}")

    if args.dry_run:
        return

    original_env = read_text(ENV_FILE)
    backup_path = ENV_FILE.with_name(f".env.mtf_v2.backup_rolling_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(ENV_FILE, backup_path)
    print(f"Backup saved: {backup_path}")

    rows = []

    try:
        for idx, (tr_s, tr_e, te_s, te_e) in enumerate(folds, 1):
            print("\n" + "-" * 90)
            print(f"Fold {idx:02d}/{len(folds)}")

            # 1) Train run (no exclusions)
            env_train = update_env(
                base_content=original_env,
                start_date=tr_s,
                end_date=tr_e,
                excluded_mode="disabled",
                excluded_hours=None,
                timezone=args.timezone,
            )
            write_text(ENV_FILE, env_train)
            print(f"Train run: {tr_s} -> {tr_e} (exclusions disabled)")
            train_dir = run_backtest_and_get_result_dir()
            print(f"Train result: {train_dir.name}")

            # 2) Derive exclusions from train
            ex = derive_exclusions(train_dir, min_wr=args.min_wr, min_trades=args.min_trades)
            ex_count = exclusion_count(ex)
            print(f"Derived exclusions: {ex_count} day-hour slots")

            # 3) Test control (no exclusions)
            env_test_control = update_env(
                base_content=original_env,
                start_date=te_s,
                end_date=te_e,
                excluded_mode="disabled",
                excluded_hours=None,
                timezone=args.timezone,
            )
            write_text(ENV_FILE, env_test_control)
            print(f"Test control run: {te_s} -> {te_e} (exclusions disabled)")
            test_control_dir = run_backtest_and_get_result_dir()
            control_metrics = load_summary_metrics(test_control_dir)
            print(f"Control result: {test_control_dir.name}")

            # 4) Test filtered (derived exclusions enabled)
            env_test_filtered = update_env(
                base_content=original_env,
                start_date=te_s,
                end_date=te_e,
                excluded_mode="weekday",
                excluded_hours=ex,
                timezone=args.timezone,
            )
            write_text(ENV_FILE, env_test_filtered)
            print(f"Test filtered run: {te_s} -> {te_e} (exclusions enabled)")
            test_filtered_dir = run_backtest_and_get_result_dir()
            filtered_metrics = load_summary_metrics(test_filtered_dir)
            print(f"Filtered result: {test_filtered_dir.name}")

            delta_pnl = filtered_metrics.total_pnl - control_metrics.total_pnl
            delta_wr = filtered_metrics.win_rate - control_metrics.win_rate
            delta_trades = filtered_metrics.total_trades - control_metrics.total_trades

            row = {
                "fold": idx,
                "train_start": tr_s.isoformat(),
                "train_end": tr_e.isoformat(),
                "test_start": te_s.isoformat(),
                "test_end": te_e.isoformat(),
                "derived_exclusion_slots": ex_count,
                "train_result_dir": train_dir.name,
                "test_control_result_dir": test_control_dir.name,
                "test_filtered_result_dir": test_filtered_dir.name,
                "control_trades": control_metrics.total_trades,
                "control_pnl": control_metrics.total_pnl,
                "control_wr": control_metrics.win_rate,
                "control_max_dd_pct": control_metrics.max_drawdown_pct,
                "filtered_trades": filtered_metrics.total_trades,
                "filtered_pnl": filtered_metrics.total_pnl,
                "filtered_wr": filtered_metrics.win_rate,
                "filtered_max_dd_pct": filtered_metrics.max_drawdown_pct,
                "delta_trades": delta_trades,
                "delta_pnl": delta_pnl,
                "delta_wr_pp": delta_wr,
                "exclusions_monday": ",".join(str(h) for h in ex["Monday"]),
                "exclusions_tuesday": ",".join(str(h) for h in ex["Tuesday"]),
                "exclusions_wednesday": ",".join(str(h) for h in ex["Wednesday"]),
                "exclusions_thursday": ",".join(str(h) for h in ex["Thursday"]),
                "exclusions_friday": ",".join(str(h) for h in ex["Friday"]),
                "exclusions_saturday": ",".join(str(h) for h in ex["Saturday"]),
                "exclusions_sunday": ",".join(str(h) for h in ex["Sunday"]),
            }
            rows.append(row)

            print(
                f"Fold {idx:02d} delta: trades={delta_trades:+d}, "
                f"pnl={delta_pnl:+.2f}, wr={delta_wr:+.2f}pp"
            )

        # write report
        fieldnames = list(rows[0].keys()) if rows else []
        with output_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

        total_delta_pnl = sum(float(r["delta_pnl"]) for r in rows)
        avg_delta_wr = sum(float(r["delta_wr_pp"]) for r in rows) / len(rows)
        win_folds = sum(1 for r in rows if float(r["delta_pnl"]) > 0)

        print("\n" + "=" * 90)
        print("ROLLING TEST COMPLETE")
        print(f"CSV: {output_csv}")
        print(f"Folds: {len(rows)} | Positive delta PnL folds: {win_folds}/{len(rows)}")
        print(f"Total forward delta PnL: {total_delta_pnl:+.2f}")
        print(f"Average forward delta WR: {avg_delta_wr:+.2f}pp")
        print("=" * 90)

    finally:
        write_text(ENV_FILE, original_env)
        print(f"Restored env: {ENV_FILE}")


if __name__ == "__main__":
    main()
