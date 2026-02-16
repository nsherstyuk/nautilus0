"""Weekly Hour/Weekday Exclusion Optimizer

Run this script every weekend (Saturday/Sunday) when markets are closed.
It analyzes recent trade performance by hour/weekday and updates .env.mtf_v2
with optimized exclusions for the coming week.

Data sources (in priority order):
  1. Live trade logs (if available) - ground truth
  2. Most recent backtest results - fallback

Criteria for KEEPING an hour/weekday slot:
  - Win rate >= MIN_WINRATE (default 68%)
  - Positive PnL (> 0)
  - All other slots with trades are EXCLUDED
  - Slots with zero trades are left open (no data to judge)

Usage:
  python scripts/weekly_optimize_hours.py                  # Analyze + show recommendations
  python scripts/weekly_optimize_hours.py --apply          # Analyze + update .env.mtf_v2
  python scripts/weekly_optimize_hours.py --dry-run        # Same as no flags (default)
  python scripts/weekly_optimize_hours.py --backtest-dir DIR  # Use specific backtest result dir
  python scripts/weekly_optimize_hours.py --live-csv FILE  # Use a live trades CSV
  python scripts/weekly_optimize_hours.py --min-wr 70      # Custom min win rate threshold
"""

import argparse
import csv
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env.mtf_v2"
BACKTEST_RESULTS_DIR = PROJECT_ROOT / "backtest_results"
LIVE_LOGS_DIR = PROJECT_ROOT / "logs" / "live_mtf"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_NUM_TO_NAME = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
                   4: "Friday", 5: "Saturday", 6: "Sunday"}

DEFAULT_MIN_WINRATE = 65.0
DEFAULT_MIN_TRADES_TO_EXCLUDE = 5


def find_latest_backtest_dir() -> Optional[Path]:
    """Find the most recent MTF_V2_ENTRY_CONFIRMED backtest result directory."""
    dirs = sorted(BACKTEST_RESULTS_DIR.glob("MTF_V2_ENTRY_CONFIRMED_*"), key=lambda d: d.name)
    # Filter to dirs that have trades CSV
    for d in reversed(dirs):
        if list(d.glob("trades_*.csv")):
            return d
    return None


def load_backtest_matrices(result_dir: Path) -> Tuple[Dict, Dict, Dict]:
    """Load hour/weekday PnL, trades, and winrate matrices from a backtest result dir."""
    pnl_files = list(result_dir.glob("hour_weekday_pnl_matrix_*.csv"))
    trades_files = list(result_dir.glob("hour_weekday_trades_matrix_*.csv"))
    wr_files = list(result_dir.glob("hour_weekday_winrate_matrix_*.csv"))

    if not (pnl_files and trades_files and wr_files):
        return {}, {}, {}

    def read_matrix(filepath):
        m = {}
        with open(filepath, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                h = int(row["hour_EST"])
                m[h] = {d: float(row[d]) for d in DAYS}
        return m

    return read_matrix(pnl_files[0]), read_matrix(trades_files[0]), read_matrix(wr_files[0])


def load_trades_csv(filepath: Path) -> List[Dict]:
    """Load trades from a CSV file (backtest or live format)."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def compute_hour_weekday_stats(trades: List[Dict]) -> Tuple[Dict, Dict, Dict]:
    """Compute hour/weekday PnL, trade count, and win rate from a list of trade dicts.
    
    Expects trades with keys: entry_time, side, pnl, entry_hour, entry_weekday
    """
    pnl_matrix = {h: {d: 0.0 for d in DAYS} for h in range(24)}
    trades_matrix = {h: {d: 0 for d in DAYS} for h in range(24)}
    wins_matrix = {h: {d: 0 for d in DAYS} for h in range(24)}

    for t in trades:
        try:
            hour = int(t.get("entry_hour", -1))
            weekday = int(t.get("entry_weekday", -1))
            p = float(t.get("pnl", 0))
        except (ValueError, TypeError):
            continue

        if hour < 0 or hour > 23 or weekday < 0 or weekday > 6:
            continue

        day_name = DAY_NUM_TO_NAME[weekday]
        pnl_matrix[hour][day_name] += p
        trades_matrix[hour][day_name] += 1
        if p > 0:
            wins_matrix[hour][day_name] += 1

    # Compute win rate matrix
    wr_matrix = {h: {d: 0.0 for d in DAYS} for h in range(24)}
    for h in range(24):
        for d in DAYS:
            tc = trades_matrix[h][d]
            if tc > 0:
                wr_matrix[h][d] = (wins_matrix[h][d] / tc) * 100.0

    return pnl_matrix, trades_matrix, wr_matrix


def analyze_exclusions(
    pnl: Dict, trades: Dict, wr: Dict,
    min_winrate: float = DEFAULT_MIN_WINRATE,
    min_trades_to_exclude: int = DEFAULT_MIN_TRADES_TO_EXCLUDE,
) -> Dict[str, List[int]]:
    """Determine which hour/weekday slots to exclude.

    Exclude slot if and only if ALL are true:
      - trades >= min_trades_to_exclude
      - WR < min_winrate
      - PnL <= 0

    Otherwise keep/open the slot.
    """
    exclude = {d: [] for d in DAYS}
    keep = {d: [] for d in DAYS}
    
    kept_pnl = 0.0
    exc_pnl = 0.0
    kept_trades = 0
    exc_trades = 0

    for h in range(24):
        for d in DAYS:
            t = int(trades[h][d])
            p = pnl[h][d]
            w = wr[h][d]

            if t == 0:
                continue

            should_exclude = (t >= min_trades_to_exclude) and (w < min_winrate) and (p <= 0)
            if should_exclude:
                exclude[d].append(h)
                exc_pnl += p
                exc_trades += t
            else:
                keep[d].append(h)
                kept_pnl += p
                kept_trades += t

    return {
        "exclude": exclude,
        "keep": keep,
        "kept_pnl": kept_pnl,
        "exc_pnl": exc_pnl,
        "kept_trades": kept_trades,
        "exc_trades": exc_trades,
    }


def print_analysis(result: Dict, pnl: Dict, trades: Dict, wr: Dict, min_winrate: float):
    """Print a human-readable analysis report."""
    exclude = result["exclude"]
    keep = result["keep"]

    print("=" * 70)
    print("WEEKLY HOUR EXCLUSION OPTIMIZATION REPORT")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Criteria: EXCLUDE when WR < {min_winrate}% AND PnL <= 0 AND trades >= {DEFAULT_MIN_TRADES_TO_EXCLUDE}")
    print("=" * 70)

    print(f"\nKept:     {result['kept_trades']} trades, PnL=${result['kept_pnl']:.2f}")
    print(f"Excluded: {result['exc_trades']} trades, PnL=${result['exc_pnl']:.2f}")
    print(f"Projected improvement: ${-result['exc_pnl']:.2f}")

    print("\n--- KEPT SLOTS ---")
    print(f"{'Hour':>4} | {'Day':>10} | {'Trades':>6} | {'PnL':>8} | {'WR':>6}")
    print("-" * 45)
    for h in range(24):
        for d in DAYS:
            t = int(trades[h][d])
            if t == 0:
                continue
            p = pnl[h][d]
            w = wr[h][d]
            if h in keep[d]:
                print(f"{h:>4} | {d:>10} | {t:>6} | ${p:>6.1f} | {w:>5.1f}%")

    print("\n--- EXCLUDED SLOTS ---")
    print(f"{'Hour':>4} | {'Day':>10} | {'Trades':>6} | {'PnL':>8} | {'WR':>6}")
    print("-" * 45)
    for h in range(24):
        for d in DAYS:
            t = int(trades[h][d])
            if t == 0:
                continue
            p = pnl[h][d]
            w = wr[h][d]
            if h in exclude[d]:
                print(f"{h:>4} | {d:>10} | {t:>6} | ${p:>6.1f} | {w:>5.1f}%")

    print("\n--- EXCLUSIONS PER WEEKDAY ---")
    for d in DAYS:
        k = sorted(keep[d])
        e = sorted(exclude[d])
        if e:
            print(f"  {d}: KEEP {k} | EXCLUDE {e}")
        else:
            print(f"  {d}: KEEP {k} | No exclusions")

    print("\n--- ENV FORMAT ---")
    for d in DAYS:
        e = sorted(exclude[d])
        var = f"MTF2_EXCLUDED_HOURS_{d.upper()}"
        val = ",".join(str(h) for h in e) if e else ""
        print(f"{var}={val}")


def update_env_file(result: Dict, env_file: Path = ENV_FILE, backup: bool = True):
    """Update .env.mtf_v2 with new hour exclusions."""
    exclude = result["exclude"]

    if not env_file.exists():
        print(f"ERROR: {env_file} not found")
        return False

    content = env_file.read_text()

    # Backup
    if backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = env_file.parent / f".env.mtf_v2.backup_{ts}"
        shutil.copy2(env_file, backup_path)
        print(f"Backup saved: {backup_path}")

    # Enable weekday mode
    content = re.sub(
        r"MTF2_EXCLUDED_HOURS_MODE=\S+",
        "MTF2_EXCLUDED_HOURS_MODE=weekday",
        content,
    )

    # Update each weekday's exclusions
    for d in DAYS:
        e = sorted(exclude[d])
        val = ",".join(str(h) for h in e) if e else ""
        pattern = rf"MTF2_EXCLUDED_HOURS_{d.upper()}=.*"
        replacement = f"MTF2_EXCLUDED_HOURS_{d.upper()}={val}"
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
        else:
            # Append if not found
            content += f"\n{replacement}"

    # Update comment with timestamp
    comment_pattern = r"# Based on backtest .*"
    new_comment = f"# Based on weekly optimization run {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    if re.search(comment_pattern, content):
        content = re.sub(comment_pattern, new_comment, content, count=1)

    # Update criteria comment
    criteria_pattern = r"# Exclude slots with .*"
    new_criteria = f"# Exclude slots with trades >= {DEFAULT_MIN_TRADES_TO_EXCLUDE} AND WR < {DEFAULT_MIN_WINRATE}% AND PnL <= 0"
    if re.search(criteria_pattern, content):
        content = re.sub(criteria_pattern, new_criteria, content, count=1)

    env_file.write_text(content)
    print(f"Updated: {env_file}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Weekly Hour Exclusion Optimizer")
    parser.add_argument("--apply", action="store_true", help="Apply exclusions to .env.mtf_v2")
    parser.add_argument("--dry-run", action="store_true", help="Show recommendations only (default)")
    parser.add_argument("--backtest-dir", type=str, help="Specific backtest result directory to use")
    parser.add_argument("--live-csv", type=str, help="Live trades CSV file to use")
    parser.add_argument("--min-wr", type=float, default=DEFAULT_MIN_WINRATE,
                        help=f"Minimum win rate to keep a slot (default: {DEFAULT_MIN_WINRATE})")
    parser.add_argument("--disable", action="store_true", help="Disable all hour exclusions")
    args = parser.parse_args()

    if args.disable:
        content = ENV_FILE.read_text()
        content = re.sub(r"MTF2_EXCLUDED_HOURS_MODE=\S+", "MTF2_EXCLUDED_HOURS_MODE=disabled", content)
        ENV_FILE.write_text(content)
        print("Hour exclusions DISABLED in .env.mtf_v2")
        return

    # Determine data source
    pnl, trades, wr = {}, {}, {}
    source_desc = ""

    if args.live_csv:
        # Use live trades CSV
        live_path = Path(args.live_csv)
        if not live_path.exists():
            print(f"ERROR: Live CSV not found: {live_path}")
            sys.exit(1)
        trade_rows = load_trades_csv(live_path)
        pnl, trades, wr = compute_hour_weekday_stats(trade_rows)
        source_desc = f"Live trades CSV: {live_path} ({len(trade_rows)} trades)"

    elif args.backtest_dir:
        # Use specific backtest dir
        bt_dir = Path(args.backtest_dir)
        if not bt_dir.exists():
            # Try as relative to backtest_results
            bt_dir = BACKTEST_RESULTS_DIR / args.backtest_dir
        if not bt_dir.exists():
            print(f"ERROR: Backtest dir not found: {args.backtest_dir}")
            sys.exit(1)
        pnl, trades, wr = load_backtest_matrices(bt_dir)
        source_desc = f"Backtest: {bt_dir.name}"

    else:
        # Auto-detect: try live trades first, then latest backtest
        # For now, use latest backtest (live trade CSV collection will grow over time)
        bt_dir = find_latest_backtest_dir()
        if bt_dir:
            pnl, trades, wr = load_backtest_matrices(bt_dir)
            source_desc = f"Latest backtest: {bt_dir.name}"
        else:
            print("ERROR: No backtest results found and no live CSV provided")
            sys.exit(1)

    if not pnl:
        print("ERROR: Could not load hour/weekday matrices")
        sys.exit(1)

    print(f"Data source: {source_desc}")
    print()

    # Analyze
    result = analyze_exclusions(pnl, trades, wr, min_winrate=args.min_wr)

    # Print report
    print_analysis(result, pnl, trades, wr, args.min_wr)

    # Apply if requested
    if args.apply:
        print("\n" + "=" * 70)
        print("APPLYING EXCLUSIONS TO .env.mtf_v2")
        print("=" * 70)
        update_env_file(result)
        print("\nDone! Restart the live trading supervisor to pick up changes.")
        print("The supervisor will auto-restart at the next daily restart window,")
        print("or you can manually restart it now.")
    else:
        print("\n" + "=" * 70)
        print("DRY RUN - No changes made")
        print("Run with --apply to update .env.mtf_v2")
        print("=" * 70)


if __name__ == "__main__":
    main()
