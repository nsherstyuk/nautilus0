"""Analyze how model confidence correlates with outcome and TP/SL headroom.

What this does
- Parses `strategy_decisions.log` for:
  - `[SIGNAL] Generated ... confidence: X` (direction + time + confidence)
  - `[BAR_METRICS] ... atr=Y ... thresh=Z` (time + ATR + threshold)
- Loads `trades.csv` for realized outcomes.
- Loads 1-minute bars from the Nautilus Parquet catalog to compute per-trade:
  - MFE (max favorable excursion)
  - MAE (max adverse excursion)
  - both expressed in ATR multiples
- Produces confidence-binned and hour/weekday breakdowns.

Why this answers your question
- If higher confidence consistently shows larger MFE (in ATR), then using a larger TP
  for those trades is plausible.
- If higher confidence consistently shows smaller MAE (in ATR), then using a tighter SL
  for those trades is plausible.
- We also compute a counterfactual grid: "would TP=X or SL=Y have been hit" using MFE/MAE.
  Note: this ignores intrabar ordering when both TP and SL would be touched.

Run
  python scripts/analyze_confidence_tp_sl.py --backtest-dir backtest_results/MTF_V2_ENTRY_CONFIRMED_20260123_110808

Outputs are written into the backtest directory.
"""

from __future__ import annotations

import argparse
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

try:
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
except Exception as exc:  # pragma: no cover
    ParquetDataCatalog = None  # type: ignore
    _CATALOG_IMPORT_ERROR = exc


_SIGNAL_RE = re.compile(
    r"\[SIGNAL\] Generated (?P<side>LONG|SHORT) signal at (?P<ts>[^,]+), confidence: (?P<conf>[0-9.]+)"
)

# Example:
# [BAR_METRICS] 2024-12-27 12:30:00+00:00 close=... atr=0.00062 pred=1 conf=0.545 thresh=0.69 ...
_BAR_METRICS_RE = re.compile(
    r"\[BAR_METRICS\]\s+(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\+00:00).*?\batr=(?P<atr>NA|[0-9.]+).*?\bthresh=(?P<thresh>[0-9.]+)"
)


@dataclass(frozen=True)
class BacktestPaths:
    backtest_dir: Path
    trades_csv: Path
    decisions_log: Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze confidence vs TP/SL behavior")
    parser.add_argument(
        "--backtest-dir",
        type=str,
        required=True,
        help="Path to a backtest folder containing trades.csv and strategy_decisions.log",
    )
    parser.add_argument(
        "--catalog-path",
        type=str,
        default=str(Path(__file__).resolve().parents[1] / "data" / "historical"),
        help="Path to Nautilus Parquet catalog root (default: data/historical)",
    )
    parser.add_argument(
        "--bar-type-1m",
        type=str,
        default="EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL",
        help="1-minute bar type to compute MFE/MAE (default: EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL)",
    )
    parser.add_argument(
        "--atr-tolerance-mins",
        type=int,
        default=60,
        help="Max minutes allowed between trade entry and nearest ATR sample (default: 60)",
    )
    parser.add_argument(
        "--signal-tolerance-mins",
        type=int,
        default=60,
        help="Max minutes allowed between trade entry and nearest signal (default: 60)",
    )
    parser.add_argument(
        "--conf-bins",
        type=str,
        default="0.69,0.72,0.75,0.80,0.85,0.90,1.01",
        help="Comma-separated confidence bin edges (default tuned around 0.69 threshold)",
    )
    parser.add_argument(
        "--tp-grid",
        type=str,
        default="0.6,0.65,0.7,0.8,0.9,1.0,1.2",
        help="Comma-separated TP ATR-multipliers to test in counterfactual grid",
    )
    parser.add_argument(
        "--sl-grid",
        type=str,
        default="0.8,1.0,1.1,1.2,1.25,1.4,1.6",
        help="Comma-separated SL ATR-multipliers to test in counterfactual grid",
    )
    return parser.parse_args()


def _validate_paths(backtest_dir: Path) -> BacktestPaths:
    trades_csv = backtest_dir / "trades.csv"
    decisions_log = backtest_dir / "strategy_decisions.log"

    missing = [p for p in [trades_csv, decisions_log] if not p.exists()]
    if missing:
        missing_str = ", ".join(str(p) for p in missing)
        raise FileNotFoundError(f"Missing required files: {missing_str}")

    return BacktestPaths(backtest_dir=backtest_dir, trades_csv=trades_csv, decisions_log=decisions_log)


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def parse_signals_and_atr(decisions_log: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse signals (time, side, conf) and ATR samples (time, atr, thresh)."""
    signals: list[dict] = []
    atr_samples: list[dict] = []

    with decisions_log.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _SIGNAL_RE.search(line)
            if m:
                ts = pd.to_datetime(m.group("ts"), utc=True).tz_convert("UTC").tz_localize(None)
                signals.append(
                    {
                        "signal_time": ts,
                        "side": m.group("side"),
                        "confidence": float(m.group("conf")),
                    }
                )
                continue

            m = _BAR_METRICS_RE.search(line)
            if m:
                atr = _parse_float(m.group("atr"))
                if atr is None:
                    continue
                ts = pd.to_datetime(m.group("ts"), utc=True).tz_convert("UTC").tz_localize(None)
                atr_samples.append(
                    {
                        "metric_time": ts,
                        "atr": atr,
                        "threshold": float(m.group("thresh")),
                    }
                )

    signals_df = pd.DataFrame(signals)
    atr_df = pd.DataFrame(atr_samples)

    if not signals_df.empty:
        signals_df = signals_df.sort_values("signal_time").reset_index(drop=True)

    if not atr_df.empty:
        # Keep last metric per timestamp (log can duplicate)
        atr_df = (
            atr_df.sort_values("metric_time")
            .drop_duplicates(subset=["metric_time"], keep="last")
            .reset_index(drop=True)
        )

    return signals_df, atr_df


def load_trades(trades_csv: Path) -> pd.DataFrame:
    trades = pd.read_csv(trades_csv)
    # Normalize to UTC-naive timestamps for stable slicing/joining
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
    trades = trades.sort_values("entry_time").reset_index(drop=True)

    # Normalize side naming to match signal log
    trades["side"] = trades["side"].str.upper()

    # Outcome helpers
    trades["is_win"] = trades["pnl"] > 0
    trades["is_tp"] = trades["exit_reason"].astype(str).str.upper().eq("TP")
    trades["is_sl"] = trades["exit_reason"].astype(str).str.upper().eq("SL")

    return trades


def _asof_join_by_side(
    trades: pd.DataFrame,
    signals: pd.DataFrame,
    left_time: str,
    right_time: str,
    tolerance: pd.Timedelta,
) -> pd.DataFrame:
    """As-of join trades to signals separately for LONG/SHORT to enforce side match."""
    out_frames: list[pd.DataFrame] = []

    for side in ["LONG", "SHORT"]:
        t = trades[trades["side"] == side].sort_values(left_time)
        s = signals[signals["side"] == side].sort_values(right_time)
        if t.empty:
            continue

        if s.empty:
            t = t.copy()
            t["signal_time"] = pd.NaT
            t["confidence"] = pd.NA
            out_frames.append(t)
            continue

        # Drop `side` from the signal frame to avoid side_x/side_y collisions.
        s_merge = s.drop(columns=["side"], errors="ignore")
        merged = pd.merge_asof(
            t,
            s_merge,
            left_on=left_time,
            right_on=right_time,
            direction="backward",
            tolerance=tolerance,
        )
        out_frames.append(merged)

    if not out_frames:
        return trades

    merged_all = pd.concat(out_frames, ignore_index=True)
    merged_all = merged_all.sort_values(left_time).reset_index(drop=True)
    return merged_all


def attach_signal_and_atr(
    trades: pd.DataFrame,
    signals_df: pd.DataFrame,
    atr_df: pd.DataFrame,
    signal_tolerance_mins: int,
    atr_tolerance_mins: int,
) -> pd.DataFrame:
    trades = trades.copy()

    if not signals_df.empty:
        trades = _asof_join_by_side(
            trades,
            signals_df,
            left_time="entry_time",
            right_time="signal_time",
            tolerance=pd.Timedelta(minutes=signal_tolerance_mins),
        )

    # If any merge introduced side_x/side_y, normalize back to `side`.
    if "side" not in trades.columns:
        if "side_x" in trades.columns:
            trades = trades.rename(columns={"side_x": "side"})
        elif "side_y" in trades.columns:
            trades = trades.rename(columns={"side_y": "side"})

    # If both are present, prefer the trade side.
    if "side_x" in trades.columns and "side" in trades.columns:
        trades = trades.drop(columns=["side_x"], errors="ignore")
    if "side_y" in trades.columns:
        trades = trades.drop(columns=["side_y"], errors="ignore")

    if not atr_df.empty:
        atr_df_sorted = atr_df.sort_values("metric_time")
        trades = pd.merge_asof(
            trades.sort_values("entry_time"),
            atr_df_sorted,
            left_on="entry_time",
            right_on="metric_time",
            direction="backward",
            tolerance=pd.Timedelta(minutes=atr_tolerance_mins),
        )

    # Excess confidence above threshold (if both exist)
    trades["conf_excess"] = pd.to_numeric(trades.get("confidence"), errors="coerce") - pd.to_numeric(
        trades.get("threshold"), errors="coerce"
    )

    return trades


def load_1m_bars(catalog_path: Path, bar_type_1m: str) -> pd.DataFrame:
    if ParquetDataCatalog is None:
        raise RuntimeError(
            "nautilus_trader is not importable; cannot load catalog bars. "
            f"Import error: {_CATALOG_IMPORT_ERROR}"
        )

    catalog = ParquetDataCatalog(str(catalog_path))
    bars = catalog.bars(bar_types=[bar_type_1m])
    if len(bars) == 0:
        raise ValueError(f"No bars returned for {bar_type_1m} from catalog {catalog_path}")

    df = pd.DataFrame(
        {
            "timestamp": [bar.ts_init for bar in bars],
            "open": [float(bar.open) for bar in bars],
            "high": [float(bar.high) for bar in bars],
            "low": [float(bar.low) for bar in bars],
            "close": [float(bar.close) for bar in bars],
        }
    )
    ts = pd.to_datetime(df["timestamp"], unit="ns", utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
    df = df.drop(columns=["timestamp"])
    df.index = ts
    df = df.sort_index()
    return df


def compute_mfe_mae(trades: pd.DataFrame, bars_1m: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()
    mfe_list: list[float] = []
    mae_list: list[float] = []

    for row in trades.itertuples(index=False):
        entry_time = row.entry_time
        exit_time = row.exit_time
        entry_price = float(row.entry)
        side = row.side

        window = bars_1m.loc[entry_time:exit_time]
        if window.empty:
            mfe_list.append(float("nan"))
            mae_list.append(float("nan"))
            continue

        high_max = float(window["high"].max())
        low_min = float(window["low"].min())

        if side == "LONG":
            mfe = high_max - entry_price
            mae = entry_price - low_min
        else:  # SHORT
            mfe = entry_price - low_min
            mae = high_max - entry_price

        mfe_list.append(mfe)
        mae_list.append(mae)

    trades["mfe"] = mfe_list
    trades["mae"] = mae_list

    # ATR multiples (if atr exists)
    trades["mfe_atr"] = trades["mfe"] / trades["atr"]
    trades["mae_atr"] = trades["mae"] / trades["atr"]

    return trades


def _parse_csv_floats(arg: str) -> list[float]:
    out: list[float] = []
    for part in arg.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    return out


def summarize_bins(trades: pd.DataFrame, conf_bins: list[float]) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = trades.copy()

    df = df.dropna(subset=["confidence", "atr", "mfe_atr", "mae_atr"])
    df["conf_bin"] = pd.cut(df["confidence"].astype(float), bins=conf_bins, right=False)

    summary = (
        df.groupby("conf_bin", observed=True)
        .agg(
            trades=("pnl", "size"),
            win_rate=("is_win", "mean"),
            tp_rate=("is_tp", "mean"),
            sl_rate=("is_sl", "mean"),
            avg_pnl=("pnl", "mean"),
            median_pnl=("pnl", "median"),
            avg_mfe_atr=("mfe_atr", "mean"),
            p80_mfe_atr=("mfe_atr", lambda x: x.quantile(0.80)),
            avg_mae_atr=("mae_atr", "mean"),
            p80_mae_atr=("mae_atr", lambda x: x.quantile(0.80)),
        )
        .reset_index()
    )

    # Hour/weekday cross
    by_hw = (
        df.groupby(["conf_bin", "entry_hour", "entry_weekday"], observed=True)
        .agg(
            trades=("pnl", "size"),
            win_rate=("is_win", "mean"),
            avg_pnl=("pnl", "mean"),
            avg_mfe_atr=("mfe_atr", "mean"),
            avg_mae_atr=("mae_atr", "mean"),
        )
        .reset_index()
    )

    return summary, by_hw


def summarize_hour_weekday(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Less sparse than hour×weekday: confidence bins are handled in summarize_bins."""
    df = trades.dropna(subset=["confidence", "mfe_atr", "mae_atr"]).copy()

    by_hour = (
        df.groupby(["entry_hour"], observed=True)
        .agg(
            trades=("pnl", "size"),
            win_rate=("is_win", "mean"),
            avg_pnl=("pnl", "mean"),
            avg_mfe_atr=("mfe_atr", "mean"),
            avg_mae_atr=("mae_atr", "mean"),
        )
        .reset_index()
        .sort_values("avg_pnl", ascending=False)
    )

    by_weekday = (
        df.groupby(["entry_weekday"], observed=True)
        .agg(
            trades=("pnl", "size"),
            win_rate=("is_win", "mean"),
            avg_pnl=("pnl", "mean"),
            avg_mfe_atr=("mfe_atr", "mean"),
            avg_mae_atr=("mae_atr", "mean"),
        )
        .reset_index()
        .sort_values("avg_pnl", ascending=False)
    )

    return by_hour, by_weekday


def counterfactual_grid(
    trades: pd.DataFrame, tp_grid: list[float], sl_grid: list[float]
) -> pd.DataFrame:
    """Estimate hit rates using MFE/MAE. Does not model intrabar ordering."""
    df = trades.dropna(subset=["confidence", "mfe_atr", "mae_atr"]).copy()

    rows: list[dict] = []
    for tp in tp_grid:
        for sl in sl_grid:
            tp_hit = (df["mfe_atr"] >= tp)
            sl_hit = (df["mae_atr"] >= sl)

            # Best-case: if both would hit, assume TP first
            best_win = tp_hit
            best_loss = (~tp_hit) & sl_hit

            # Worst-case: if both would hit, assume SL first
            worst_loss = sl_hit
            worst_win = (~sl_hit) & tp_hit

            # Some trades may hit neither within their actual holding window
            neither = (~tp_hit) & (~sl_hit)

            rows.append(
                {
                    "tp_mult": tp,
                    "sl_mult": sl,
                    "n": len(df),
                    "tp_reachable_rate": float(tp_hit.mean()),
                    "sl_reachable_rate": float(sl_hit.mean()),
                    "neither_rate": float(neither.mean()),
                    "best_case_win_rate": float(best_win.mean()),
                    "best_case_loss_rate": float(best_loss.mean()),
                    "worst_case_win_rate": float(worst_win.mean()),
                    "worst_case_loss_rate": float(worst_loss.mean()),
                }
            )

    return pd.DataFrame(rows).sort_values(["tp_mult", "sl_mult"]).reset_index(drop=True)


def main() -> int:
    args = _parse_args()

    backtest_dir = Path(args.backtest_dir)
    if not backtest_dir.is_absolute():
        backtest_dir = (Path.cwd() / backtest_dir).resolve()

    paths = _validate_paths(backtest_dir)

    print(f"Loading trades: {paths.trades_csv}")
    trades = load_trades(paths.trades_csv)

    print(f"Parsing decisions log (this can take a bit): {paths.decisions_log}")
    signals_df, atr_df = parse_signals_and_atr(paths.decisions_log)

    print(f"Signals parsed: {len(signals_df):,}; ATR samples parsed: {len(atr_df):,}")

    trades = attach_signal_and_atr(
        trades,
        signals_df,
        atr_df,
        signal_tolerance_mins=int(args.signal_tolerance_mins),
        atr_tolerance_mins=int(args.atr_tolerance_mins),
    )

    catalog_path = Path(args.catalog_path)
    print(f"Loading 1m bars from catalog: {catalog_path} ({args.bar_type_1m})")
    bars_1m = load_1m_bars(catalog_path, args.bar_type_1m)

    # Restrict bars to the trade window for speed/memory
    min_ts = trades["entry_time"].min()
    max_ts = trades["exit_time"].max()
    bars_1m = bars_1m.loc[min_ts:max_ts]

    print(f"Computing MFE/MAE over {len(trades):,} trades using {len(bars_1m):,} 1m bars")
    trades = compute_mfe_mae(trades, bars_1m)

    conf_bins = _parse_csv_floats(args.conf_bins)
    tp_grid = _parse_csv_floats(args.tp_grid)
    sl_grid = _parse_csv_floats(args.sl_grid)

    summary_bins, summary_hw = summarize_bins(trades, conf_bins)
    overall_by_hour, overall_by_weekday = summarize_hour_weekday(trades)
    grid = counterfactual_grid(trades, tp_grid, sl_grid)

    out_trades = paths.backtest_dir / "trades_with_confidence_mfe_mae.csv"
    out_bins = paths.backtest_dir / "confidence_bins_summary.csv"
    out_hw = paths.backtest_dir / "confidence_bins_by_hour_weekday.csv"
    out_overall_hour = paths.backtest_dir / "overall_by_hour_from_trades.csv"
    out_overall_weekday = paths.backtest_dir / "overall_by_weekday_from_trades.csv"
    out_grid = paths.backtest_dir / "confidence_counterfactual_tp_sl_grid.csv"

    trades.to_csv(out_trades, index=False)
    summary_bins.to_csv(out_bins, index=False)
    summary_hw.to_csv(out_hw, index=False)
    overall_by_hour.to_csv(out_overall_hour, index=False)
    overall_by_weekday.to_csv(out_overall_weekday, index=False)
    grid.to_csv(out_grid, index=False)

    print("\nWrote:")
    print(f"  - {out_trades}")
    print(f"  - {out_bins}")
    print(f"  - {out_hw}")
    print(f"  - {out_overall_hour}")
    print(f"  - {out_overall_weekday}")
    print(f"  - {out_grid}")

    # Small console preview
    pd.set_option("display.width", 140)
    pd.set_option("display.max_columns", None)

    print("\nConfidence bin summary (top):")
    print(summary_bins.head(12).to_string(index=False))

    print("\nCounterfactual grid preview (highest TP reach rates first):")
    print(grid.sort_values(["tp_reachable_rate", "best_case_win_rate"], ascending=False).head(12).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
