import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class EnvConfig:
    backtest_start: date
    backtest_end: date
    config_timezone: str


def _parse_env_file(path: Path) -> EnvConfig:
    values: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()

    start_str = values.get("MTF2_BACKTEST_START")
    end_str = values.get("MTF2_BACKTEST_END")
    tz = values.get("MTF2_CONFIG_TIMEZONE", "UTC")
    if not start_str or not end_str:
        raise ValueError("Missing MTF2_BACKTEST_START/MTF2_BACKTEST_END in env file")

    return EnvConfig(
        backtest_start=date.fromisoformat(start_str),
        backtest_end=date.fromisoformat(end_str),
        config_timezone=tz,
    )


def _parse_ts(value: str) -> datetime:
    text = value.strip()
    return datetime.fromisoformat(text.replace(" ", "T"))


def _utc_to_local_date(ts_utc: datetime, config_timezone: str) -> date:
    tz = (config_timezone or "UTC").upper()
    if tz == "UTC":
        return ts_utc.date()

    if tz == "EST":
        try:
            from zoneinfo import ZoneInfo

            ny = ZoneInfo("America/New_York")
            return ts_utc.astimezone(ny).date()
        except Exception:
            offset = timezone(timedelta(hours=-5))
            return ts_utc.astimezone(offset).date()

    return ts_utc.date()


def _date_range_inclusive(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _read_trade_dates(trades_csv: Path, ts_field: str, config_timezone: str) -> list[date]:
    dates: list[date] = []
    with trades_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = _parse_ts(row[ts_field])
            dates.append(_utc_to_local_date(ts, config_timezone))
    return dates


def _weekday_name(d: date) -> str:
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return names[d.weekday()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        required=True,
        help="Backtest run folder (must contain trades.csv and .env.mtf_v2)",
    )
    parser.add_argument(
        "--by",
        choices=["entry", "exit"],
        default="entry",
        help="Count trades per day by entry_time or exit_time",
    )
    parser.add_argument(
        "--max-k",
        type=int,
        default=10,
        help="Show distribution for day trade-counts up to this k (then aggregate as >k)",
    )
    args = parser.parse_args()

    run_dir = Path(args.run)
    trades_path = run_dir / "trades.csv"
    env_path = run_dir / ".env.mtf_v2"

    if not trades_path.exists():
        raise SystemExit(f"Missing file: {trades_path}")
    if not env_path.exists():
        raise SystemExit(f"Missing file: {env_path}")

    cfg = _parse_env_file(env_path)
    ts_field = "entry_time" if args.by == "entry" else "exit_time"

    trade_dates = _read_trade_dates(trades_path, ts_field=ts_field, config_timezone=cfg.config_timezone)
    counts_by_day = Counter(trade_dates)

    all_days = list(_date_range_inclusive(cfg.backtest_start, cfg.backtest_end))
    daily_counts = [counts_by_day.get(d, 0) for d in all_days]

    dist = Counter(daily_counts)

    max_k = max(0, int(args.max_k))
    over_k = sum(v for k, v in dist.items() if k > max_k)

    print(f"Run: {run_dir}")
    print(f"Range: {cfg.backtest_start.isoformat()} to {cfg.backtest_end.isoformat()} ({len(all_days)} days)")
    print(f"Timezone for day-bucketing: {cfg.config_timezone}")
    print(f"Counting by: {ts_field}")
    print(f"Trades: {len(trade_dates)}")

    print("\nDays by # trades:")
    for k in range(0, max_k + 1):
        print(f"  {k}: {dist.get(k, 0)}")
    if over_k:
        print(f"  >{max_k}: {over_k}")

    zero_days = [d for d in all_days if counts_by_day.get(d, 0) == 0]
    print(f"\nZero-trade days: {len(zero_days)}")

    zero_by_weekday = Counter(_weekday_name(d) for d in zero_days)
    if zero_days:
        print("Zero-trade days by weekday:")
        for name in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
            print(f"  {name}: {zero_by_weekday.get(name, 0)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
