"""Run V2 Entry Confirmed backtests month-by-month.

Behavior:
- Uses your existing `.env.mtf_v2` settings as-is.
- Overrides ONLY `MTF2_BACKTEST_START` and `MTF2_BACKTEST_END` per month.
- Runs months sequentially and lets the underlying backtest runner write results
  to `backtest_results/` (one folder per run), same as a normal manual run.

Examples:
  python scripts/run_monthly_backtests_mtf_v2_entry_confirmed.py
  python scripts/run_monthly_backtests_mtf_v2_entry_confirmed.py --from 2024-01 --to 2024-12
  python scripts/run_monthly_backtests_mtf_v2_entry_confirmed.py --from 2025-11 --to 2025-11

Notes:
- Dates are UTC dates (YYYY-MM-DD). Runner semantics are controlled by
  `run_backtest_mtf_v2_entry_confirmed.py`.
"""

from __future__ import annotations

import argparse
import calendar
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Month:
    year: int
    month: int

    def __post_init__(self) -> None:
        if not (1 <= self.month <= 12):
            raise ValueError(f"Invalid month: {self.month}")

    @property
    def yyyymm(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def start_date(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-01"

    @property
    def end_date(self) -> str:
        last_day = calendar.monthrange(self.year, self.month)[1]
        return f"{self.year:04d}-{self.month:02d}-{last_day:02d}"


def parse_yyyy_mm(value: str) -> Month:
    try:
        parts = value.strip().split("-")
        if len(parts) != 2:
            raise ValueError
        year = int(parts[0])
        month = int(parts[1])
        return Month(year=year, month=month)
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError(
            f"Expected YYYY-MM, got {value!r}"
        ) from exc


def iter_months_inclusive(start: Month, end: Month) -> list[Month]:
    if (start.year, start.month) > (end.year, end.month):
        raise ValueError("--from must be <= --to")

    months: list[Month] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(Month(year=y, month=m))
        m += 1
        if m == 13:
            m = 1
            y += 1
    return months


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run mtf_v2 entry-confirmed backtests month-by-month (sequential)."
    )
    parser.add_argument(
        "--from",
        dest="from_month",
        type=parse_yyyy_mm,
        default=Month(2024, 1),
        help="First month to run (inclusive), format YYYY-MM. Default: 2024-01",
    )
    parser.add_argument(
        "--to",
        dest="to_month",
        type=parse_yyyy_mm,
        default=Month(2026, 1),
        help="Last month to run (inclusive), format YYYY-MM. Default: 2026-01",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="If set, continue to next month even if a run fails.",
    )

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    runner = repo_root / "run_backtest_mtf_v2_entry_confirmed.py"
    if not runner.exists():
        print(f"ERROR: runner not found: {runner}")
        return 2

    months = iter_months_inclusive(args.from_month, args.to_month)

    print(f"Running {len(months)} monthly backtests via: {runner}")
    print(f"Using Python: {sys.executable}")
    print(
        "NOTE: This uses current `.env.mtf_v2` settings; only MTF2_BACKTEST_START/END are overridden."
    )

    failures: list[str] = []

    for idx, month in enumerate(months, start=1):
        print("\n" + "=" * 80)
        print(f"[{idx}/{len(months)}] Month {month.yyyymm}  start={month.start_date}  end={month.end_date}")
        print("=" * 80)

        env = os.environ.copy()
        env["MTF2_BACKTEST_START"] = month.start_date
        env["MTF2_BACKTEST_END"] = month.end_date

        try:
            completed = subprocess.run(
                [sys.executable, str(runner)],
                cwd=str(repo_root),
                env=env,
                check=False,
            )
        except KeyboardInterrupt:
            print("\nInterrupted by user. Stopping.")
            return 130

        if completed.returncode != 0:
            msg = f"{month.yyyymm} failed (exit={completed.returncode})"
            print(f"ERROR: {msg}")
            failures.append(msg)
            if not args.continue_on_error:
                break

    print("\n" + "=" * 80)
    if failures:
        print("Monthly backtests completed with failures:")
        for f in failures:
            print(f"- {f}")
        return 1

    print("Monthly backtests completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
