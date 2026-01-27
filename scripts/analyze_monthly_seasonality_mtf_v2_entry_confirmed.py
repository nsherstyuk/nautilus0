"""Analyze month/season patterns from monthly V2 Entry Confirmed backtests.

This script is designed for your workflow where you ran one backtest per month and
saved the usual artifacts in each run folder under `backtest_results/`.

It answers two questions:
1) Are there common profitable/unprofitable trading hours (and weekdays) that
   repeat for the same calendar month across years (e.g., Jan 2024 vs Jan 2025)
   or across seasons (DJF/MAM/JJA/SON)?
2) Do those patterns line up with market regime changes (volatility/trend),
   suggesting certain parameters might be better as seasonal presets?

Outputs:
- Writes CSV + a small markdown report into `analysis_outputs/seasonality_mtf_v2/`.

Notes:
- Hour stats are based on the backtest's `performance_by_hour.csv` which uses EST.
- Price regime metrics are computed from local EURUSD 15m parquet bars if present.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import struct
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


try:
    import pandas as pd
except Exception as exc:  # noqa: BLE001
    raise SystemExit(
        "This script requires pandas. Install with: pip install pandas"
    ) from exc


EST = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


PERIOD_RE = re.compile(r"^Period:\s*(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\s*$")


@dataclass(frozen=True)
class MonthlyRun:
    run_dir: Path
    period_start: date
    period_end: date

    @property
    def yyyymm(self) -> str:
        return f"{self.period_start.year:04d}-{self.period_start.month:02d}"

    @property
    def year(self) -> int:
        return self.period_start.year

    @property
    def month(self) -> int:
        return self.period_start.month

    @property
    def season(self) -> str:
        m = self.month
        if m in (12, 1, 2):
            return "DJF"
        if m in (3, 4, 5):
            return "MAM"
        if m in (6, 7, 8):
            return "JJA"
        return "SON"


def parse_period_from_summary(summary_path: Path) -> tuple[date, date] | None:
    try:
        with summary_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                m = PERIOD_RE.match(line)
                if m:
                    start = date.fromisoformat(m.group(1))
                    end = date.fromisoformat(m.group(2))
                    return start, end
    except Exception:
        return None
    return None


def discover_monthly_runs(results_dir: Path, from_month: date, to_month: date) -> dict[str, MonthlyRun]:
    """Return one run per YYYY-MM (preferring the latest run folder name)."""
    best: dict[str, MonthlyRun] = {}

    for entry in results_dir.iterdir():
        if not entry.is_dir():
            continue

        summary_path = entry / "summary.txt"
        if not summary_path.exists():
            continue

        period = parse_period_from_summary(summary_path)
        if period is None:
            continue

        start, end = period
        if start < from_month or start > to_month:
            continue

        # Only treat as a monthly run if it starts on day 1.
        # (End date can be the last day; we don't strictly enforce it to avoid edge cases.)
        if start.day != 1:
            continue

        yyyymm = f"{start.year:04d}-{start.month:02d}"
        candidate = MonthlyRun(run_dir=entry, period_start=start, period_end=end)

        # Prefer lexicographically-larger folder names (usually later timestamped run)
        existing = best.get(yyyymm)
        if existing is None or candidate.run_dir.name > existing.run_dir.name:
            best[yyyymm] = candidate

    return dict(sorted(best.items(), key=lambda kv: kv[0]))


def read_perf_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def compute_hour_score(df_hour: pd.DataFrame) -> pd.DataFrame:
    df = df_hour.copy()
    df["pnl_per_trade"] = df.apply(
        lambda r: (r["pnl"] / r["trades"]) if r.get("trades", 0) else 0.0,
        axis=1,
    )
    return df


def load_monthly_performance(runs: dict[str, MonthlyRun]) -> tuple[pd.DataFrame, pd.DataFrame]:
    hour_rows: list[pd.DataFrame] = []
    weekday_rows: list[pd.DataFrame] = []

    for yyyymm, run in runs.items():
        hour_path = run.run_dir / "performance_by_hour.csv"
        weekday_path = run.run_dir / "performance_by_weekday.csv"

        if hour_path.exists():
            dfh = compute_hour_score(read_perf_csv(hour_path))
            dfh["yyyymm"] = yyyymm
            dfh["year"] = run.year
            dfh["month"] = run.month
            dfh["season"] = run.season
            dfh["run_dir"] = str(run.run_dir)
            hour_rows.append(dfh)

        if weekday_path.exists():
            dfw = read_perf_csv(weekday_path)
            dfw["pnl_per_trade"] = dfw.apply(
                lambda r: (r["pnl"] / r["trades"]) if r.get("trades", 0) else 0.0,
                axis=1,
            )
            dfw["yyyymm"] = yyyymm
            dfw["year"] = run.year
            dfw["month"] = run.month
            dfw["season"] = run.season
            dfw["run_dir"] = str(run.run_dir)
            weekday_rows.append(dfw)

    hour_all = pd.concat(hour_rows, ignore_index=True) if hour_rows else pd.DataFrame()
    weekday_all = pd.concat(weekday_rows, ignore_index=True) if weekday_rows else pd.DataFrame()
    return hour_all, weekday_all


def decode_price_bytes_to_float(series: pd.Series) -> pd.Series:
    # Fast-ish conversion from bytes(8) little-endian int64 to float with 1e9 scale.
    # Avoid Python-level loops over rows.
    values = series.to_numpy()
    raw = b"".join(values.tolist())
    ints = struct.unpack("<" + "q" * len(values), raw)
    return pd.Series([i / 1e9 for i in ints])


def load_eurusd_15m_bars(parquet_dir: Path, from_month: date, to_month: date) -> pd.DataFrame | None:
    if not parquet_dir.exists():
        return None

    parquet_files = sorted([p for p in parquet_dir.iterdir() if p.is_file() and p.suffix == ".parquet"])
    if not parquet_files:
        return None

    # Read all matching files (the annual parquet partitions are already coarse).
    dfs: list[pd.DataFrame] = []
    for p in parquet_files:
        try:
            df = pd.read_parquet(p)
        except Exception:
            continue

        if df.empty:
            continue

        # Expect Nautilus-style columns.
        required = {"open", "high", "low", "close", "ts_event"}
        if not required.issubset(set(df.columns)):
            continue

        # Convert ts_event (ns) -> datetime UTC
        ts = pd.to_datetime(df["ts_event"], utc=True)
        start_utc = datetime(from_month.year, from_month.month, 1, tzinfo=UTC)
        end_utc = datetime(to_month.year, to_month.month, 28, tzinfo=UTC)  # loose upper bound
        df = df.assign(ts_utc=ts)
        df = df[(df["ts_utc"] >= start_utc) & (df["ts_utc"] <= end_utc)]
        if df.empty:
            continue

        # Decode OHLC
        for col in ("open", "high", "low", "close"):
            if isinstance(df[col].iloc[0], (bytes, bytearray)):
                df[col] = decode_price_bytes_to_float(df[col])

        dfs.append(df[["ts_utc", "open", "high", "low", "close"]])

    if not dfs:
        return None

    out = pd.concat(dfs, ignore_index=True).sort_values("ts_utc")
    return out


def compute_monthly_regime(bars_15m: pd.DataFrame) -> pd.DataFrame:
    df = bars_15m.copy()

    # Convert to EST for grouping that matches your reports.
    df["ts_est"] = df["ts_utc"].dt.tz_convert(EST)
    df["yyyymm"] = df["ts_est"].dt.strftime("%Y-%m")

    # True range and ATR(14)
    prev_close = df["close"].shift(1)
    tr = (df["high"] - df["low"]).to_frame("hl")
    tr["hc"] = (df["high"] - prev_close).abs()
    tr["lc"] = (df["low"] - prev_close).abs()
    df["tr"] = tr.max(axis=1)
    df["atr14"] = df["tr"].rolling(14).mean()

    df["ret"] = df["close"].pct_change()

    grouped = df.groupby("yyyymm", as_index=False)
    out = grouped.agg(
        bars=("close", "size"),
        open_first=("open", "first"),
        close_last=("close", "last"),
        tr_mean=("tr", "mean"),
        tr_median=("tr", "median"),
        atr14_mean=("atr14", "mean"),
        atr14_median=("atr14", "median"),
        ret_std=("ret", "std"),
    )
    out["month_return"] = (out["close_last"] / out["open_first"]) - 1.0
    return out


def recommend_hours(df_hour_all: pd.DataFrame, min_trades_per_hour: int, group_by: str) -> pd.DataFrame:
    """Produce candidate hour exclusions by month or season.

    Rule-of-thumb:
    - aggregate pnl_per_trade across the group weighted by trades
    - only consider hours with enough total trades
    """
    df = df_hour_all.copy()

    # Normalize column name (hour_EST)
    if "hour_EST" not in df.columns:
        raise ValueError("Expected 'hour_EST' column in performance_by_hour.csv")

    group_cols = [group_by, "hour_EST"]

    def weighted_avg(x: pd.DataFrame) -> float:
        trades = x["trades"].sum()
        if trades <= 0:
            return 0.0
        return float((x["pnl"].sum()) / trades)

    agg = df.groupby(group_cols, as_index=False).agg(
        total_trades=("trades", "sum"),
        total_pnl=("pnl", "sum"),
        avg_win_rate=("win_rate", "mean"),
    )
    agg["pnl_per_trade"] = agg.apply(
        lambda r: (r["total_pnl"] / r["total_trades"]) if r["total_trades"] else 0.0,
        axis=1,
    )

    agg = agg[agg["total_trades"] >= min_trades_per_hour].copy()

    # Rank within group
    agg["rank_best"] = agg.groupby(group_by)["pnl_per_trade"].rank(ascending=False, method="dense")
    agg["rank_worst"] = agg.groupby(group_by)["pnl_per_trade"].rank(ascending=True, method="dense")

    return agg.sort_values([group_by, "pnl_per_trade"], ascending=[True, False])


def write_markdown_report(
    out_path: Path,
    runs: dict[str, MonthlyRun],
    hour_reco_month: pd.DataFrame,
    hour_reco_season: pd.DataFrame,
    weekday_all: pd.DataFrame,
    regime: pd.DataFrame | None,
) -> None:
    lines: list[str] = []
    lines.append("# Seasonality report (MTF V2 Entry Confirmed)\n")
    lines.append(f"Monthly runs discovered: {len(runs)}\n")
    if runs:
        lines.append(f"Range: {next(iter(runs.keys()))} .. {next(reversed(runs.keys()))}\n")

    lines.append("## Hour patterns (by calendar month)\n")
    if hour_reco_month.empty:
        lines.append("No hour data found.\n")
    else:
        for month in sorted(hour_reco_month["month"].unique()):
            sub = hour_reco_month[hour_reco_month["month"] == month]
            lines.append(f"### Month {int(month):02d}\n")
            best = sub.nsmallest(5, "rank_best").sort_values("rank_best")
            worst = sub.nsmallest(5, "rank_worst").sort_values("rank_worst")
            lines.append("Best hours (EST) by pnl/trade:\n")
            for _, r in best.iterrows():
                lines.append(
                    f"- {int(r['hour_EST']):02d}:00  pnl/trade={r['pnl_per_trade']:.2f}  trades={int(r['total_trades'])}"
                )
            lines.append("Worst hours (EST) by pnl/trade:\n")
            for _, r in worst.iterrows():
                lines.append(
                    f"- {int(r['hour_EST']):02d}:00  pnl/trade={r['pnl_per_trade']:.2f}  trades={int(r['total_trades'])}"
                )
            lines.append("")

    lines.append("## Hour patterns (by season)\n")
    if hour_reco_season.empty:
        lines.append("No hour data found.\n")
    else:
        for season in ["DJF", "MAM", "JJA", "SON"]:
            sub = hour_reco_season[hour_reco_season["season"] == season]
            if sub.empty:
                continue
            lines.append(f"### {season}\n")
            best = sub.nsmallest(5, "rank_best").sort_values("rank_best")
            worst = sub.nsmallest(5, "rank_worst").sort_values("rank_worst")
            lines.append("Best hours (EST) by pnl/trade:\n")
            for _, r in best.iterrows():
                lines.append(
                    f"- {int(r['hour_EST']):02d}:00  pnl/trade={r['pnl_per_trade']:.2f}  trades={int(r['total_trades'])}"
                )
            lines.append("Worst hours (EST) by pnl/trade:\n")
            for _, r in worst.iterrows():
                lines.append(
                    f"- {int(r['hour_EST']):02d}:00  pnl/trade={r['pnl_per_trade']:.2f}  trades={int(r['total_trades'])}"
                )
            lines.append("")

    lines.append("## Weekday patterns (overall)\n")
    if weekday_all.empty:
        lines.append("No weekday data found.\n")
    else:
        overall = weekday_all.groupby("entry_weekday", as_index=False).agg(
            total_trades=("trades", "sum"),
            total_pnl=("pnl", "sum"),
        )
        overall["pnl_per_trade"] = overall.apply(
            lambda r: (r["total_pnl"] / r["total_trades"]) if r["total_trades"] else 0.0,
            axis=1,
        )
        overall = overall.sort_values("pnl_per_trade", ascending=False)
        for _, r in overall.iterrows():
            lines.append(
                f"- {r['entry_weekday']}: pnl/trade={r['pnl_per_trade']:.2f} trades={int(r['total_trades'])}"
            )
        lines.append("")

    lines.append("## Price regime (EURUSD 15m)\n")
    if regime is None or regime.empty:
        lines.append("Price regime metrics not computed (15m parquet not found or unreadable).\n")
    else:
        # Show a compact table of top volatility months
        top_vol = regime.sort_values("atr14_median", ascending=False).head(10)
        lines.append("Top 10 months by ATR(14) median (15m):\n")
        for _, r in top_vol.iterrows():
            lines.append(
                f"- {r['yyyymm']}: atr14_median={r['atr14_median']:.6f} ret={r['month_return']:.2%}"
            )
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate monthly backtest results to find hour/weekday seasonality patterns."
    )
    parser.add_argument(
        "--results-dir",
        default="backtest_results",
        help="Directory containing run folders (default: backtest_results)",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default="2024-01-01",
        help="First month start date to include (YYYY-MM-01). Default: 2024-01-01",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        default="2026-01-01",
        help="Last month start date to include (YYYY-MM-01). Default: 2026-01-01",
    )
    parser.add_argument(
        "--min-trades-per-hour",
        type=int,
        default=50,
        help="Minimum total trades for an hour to be considered in recommendations.",
    )
    parser.add_argument(
        "--eurusd-15m-parquet-dir",
        default="data/historical/data/bar/EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL",
        help="Directory with EURUSD 15m parquet bars for regime analysis.",
    )
    parser.add_argument(
        "--out-dir",
        default="analysis_outputs/seasonality_mtf_v2",
        help="Output directory for reports (default: analysis_outputs/seasonality_mtf_v2)",
    )

    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    from_month = date.fromisoformat(args.from_date)
    to_month = date.fromisoformat(args.to_date)

    runs = discover_monthly_runs(results_dir, from_month, to_month)
    if not runs:
        raise SystemExit(
            f"No monthly runs found in {results_dir}. Expected run folders with summary.txt containing 'Period: YYYY-MM-01 to ...'."
        )

    hour_all, weekday_all = load_monthly_performance(runs)

    # Price regime
    parquet_dir = Path(args.eurusd_15m_parquet_dir)
    bars_15m = load_eurusd_15m_bars(parquet_dir, from_month, to_month)
    regime = compute_monthly_regime(bars_15m) if bars_15m is not None and not bars_15m.empty else None

    # Recommendations
    hour_reco_month = recommend_hours(hour_all.rename(columns={"month": "month"}), args.min_trades_per_hour, "month")
    hour_reco_season = recommend_hours(hour_all, args.min_trades_per_hour, "season")

    # Write outputs
    (out_dir / "runs_discovered.csv").write_text(
        "yyyymm,run_dir,period_start,period_end\n"
        + "\n".join(
            f"{k},{v.run_dir},{v.period_start.isoformat()},{v.period_end.isoformat()}" for k, v in runs.items()
        )
        + "\n",
        encoding="utf-8",
    )

    if not hour_all.empty:
        hour_all.to_csv(out_dir / "hour_by_month_raw.csv", index=False)
    if not weekday_all.empty:
        weekday_all.to_csv(out_dir / "weekday_by_month_raw.csv", index=False)

    if hour_reco_month is not None and not hour_reco_month.empty:
        hour_reco_month.to_csv(out_dir / "hour_recommendations_by_month.csv", index=False)
    if hour_reco_season is not None and not hour_reco_season.empty:
        hour_reco_season.to_csv(out_dir / "hour_recommendations_by_season.csv", index=False)

    if regime is not None and not regime.empty:
        regime.to_csv(out_dir / "price_regime_by_month.csv", index=False)

    write_markdown_report(
        out_dir / "seasonality_report.md",
        runs,
        hour_reco_month,
        hour_reco_season,
        weekday_all,
        regime,
    )

    print(f"Wrote outputs to: {out_dir}")
    print(f"Monthly runs analyzed: {len(runs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
