from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import zoneinfo

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


@dataclass
class Window:
    name: str
    start_md: str
    end_md: str

    def mask(self, series: pd.Series) -> pd.Series:
        md_series = series.dt.strftime("%m-%d")
        if self._start_tuple() <= self._end_tuple():
            return (md_series >= self.start_md) & (md_series <= self.end_md)
        return (md_series >= self.start_md) | (md_series <= self.end_md)

    def _start_tuple(self) -> Tuple[int, int]:
        month, day = self.start_md.split("-")
        return int(month), int(day)

    def _end_tuple(self) -> Tuple[int, int]:
        month, day = self.end_md.split("-")
        return int(month), int(day)


HOLIDAY_WINDOWS: List[Window] = [
    Window("pre_christmas", "12-18", "12-24"),
    Window("christmas_boxing", "12-25", "12-26"),
    Window("post_christmas_pre_newyear", "12-27", "12-30"),
    Window("new_year_window", "12-31", "01-03"),
]

HOLIDAY_ENVELOPE = Window("holiday_envelope", "12-18", "01-03")
FOCUS_DAYS = [
    "12-22",
    "12-23",
    "12-24",
    "12-25",
    "12-26",
    "12-27",
    "12-28",
    "12-29",
    "12-30",
    "12-31",
    "01-01",
    "01-02",
    "01-03",
]


@dataclass
class Stats:
    trades: int
    pnl_sum: float
    pnl_mean: float
    win_rate: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "trades": self.trades,
            "pnl_sum": round(self.pnl_sum, 2),
            "pnl_mean": round(self.pnl_mean, 2),
            "win_rate": round(self.win_rate, 2),
        }


def compute_stats(df: pd.DataFrame) -> Stats:
    trades = len(df)
    if trades == 0:
        return Stats(0, 0.0, 0.0, 0.0)
    pnl = df["pnl"].astype(float)
    pnl_sum = float(pnl.sum())
    pnl_mean = float(pnl.mean())
    win_rate = float((pnl > 0).mean() * 100.0)
    return Stats(trades, pnl_sum, pnl_mean, win_rate)


def load_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "entry_time" not in df.columns or "pnl" not in df.columns:
        raise ValueError("CSV must include entry_time and pnl columns")

    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True, errors="coerce")
    df = df.dropna(subset=["entry_time"])
    df["entry_time_ny"] = df["entry_time"].dt.tz_convert(NY_TZ)
    df["entry_date_ny"] = df["entry_time_ny"].dt.date
    df["entry_md"] = df["entry_time_ny"].dt.strftime("%m-%d")
    df["entry_year"] = df["entry_time_ny"].dt.year
    return df


def analyze(trades: pd.DataFrame) -> Dict[str, object]:
    result: Dict[str, object] = {}

    result["span_start_utc"] = trades["entry_time"].min().isoformat()
    result["span_end_utc"] = trades["entry_time"].max().isoformat()
    result["overall"] = compute_stats(trades).to_dict()

    # Holiday envelope (Dec 18–Jan 3)
    holiday_mask = HOLIDAY_ENVELOPE.mask(trades["entry_time_ny"])
    holiday_trades = trades[holiday_mask]
    non_holiday_trades = trades[~holiday_mask]
    result["holiday_envelope"] = compute_stats(holiday_trades).to_dict()
    result["non_holiday"] = compute_stats(non_holiday_trades).to_dict()

    result["windows"] = {
        window.name: compute_stats(trades[window.mask(trades["entry_time_ny"])]).to_dict()
        for window in HOLIDAY_WINDOWS
    }

    focus = []
    for md in FOCUS_DAYS:
        subset = trades[trades["entry_md"] == md]
        stats = compute_stats(subset)
        focus.append({"month_day": md, **stats.to_dict()})
    result["focus_days"] = focus

    per_year = []
    for year, subset in holiday_trades.groupby("entry_year"):
        per_year.append({"year": int(year), **compute_stats(subset).to_dict()})
    result["holiday_per_year"] = per_year

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze holiday-period trades from backtest results.")
    parser.add_argument(
        "--trades",
        type=Path,
        default=Path("backtest_results/MTF_V2_REPLAY_20251219_224236/trades.csv"),
        help="Path to trades.csv (default: backtest_results/MTF_V2_REPLAY_20251219_224236/trades.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to save JSON output. Prints to stdout if omitted.",
    )
    args = parser.parse_args()

    trades = load_trades(args.trades)
    data = analyze(trades)
    data["source_file"] = str(args.trades)

    if args.output:
        args.output.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Holiday analysis written to {args.output}")
    else:
        print(json.dumps(data, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
