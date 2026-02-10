"""
Trade-Level Feature Analysis + MFE/MAE Analysis

Reads backtest results (trades.csv, orders.csv, positions.csv, strategy_decisions.log)
and 1-minute historical bar data to produce actionable optimization insights.

Analyses:
1. Trade-level feature extraction (confidence, ATR, hour, weekday, meta-filters)
2. MFE/MAE (Max Favorable/Adverse Excursion) from 1m bars
3. Confidence band analysis (win rate, avg PnL by confidence bucket)
4. ATR regime analysis (performance in low/mid/high volatility)
5. Entry confirmation effectiveness (bars waited vs outcome)
6. Hour x Weekday toxic regime detection
7. SL/TP efficiency (how often SL/TP is optimal vs leaving money on table)

Usage:
    python scripts/analyze_backtest_trades.py <backtest_results_folder>
    python scripts/analyze_backtest_trades.py  # auto-picks latest
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 1. Data Loading
# ---------------------------------------------------------------------------

def _find_file(results_dir: Path, prefix: str, ext: str = ".csv") -> Path:
    """Find a file by prefix, handling both plain and timestamped names."""
    plain = results_dir / f"{prefix}{ext}"
    if plain.exists():
        return plain
    matches = sorted(results_dir.glob(f"{prefix}_*{ext}"))
    if matches:
        return matches[-1]
    raise FileNotFoundError(f"No {prefix}*{ext} found in {results_dir}")


def load_trades(results_dir: Path) -> pd.DataFrame:
    """Load trades.csv from backtest results."""
    df = pd.read_csv(_find_file(results_dir, "trades"), parse_dates=["entry_time", "exit_time"])
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    df["win"] = df["pnl"] > 0
    return df


def load_orders(results_dir: Path) -> pd.DataFrame:
    """Load orders.csv for SL/TP price extraction."""
    df = pd.read_csv(_find_file(results_dir, "orders"))
    return df


def load_positions(results_dir: Path) -> pd.DataFrame:
    """Load positions.csv."""
    df = pd.read_csv(_find_file(results_dir, "positions"))
    return df


def parse_strategy_log(results_dir: Path) -> pd.DataFrame:
    """
    Parse strategy_decisions.log to extract per-signal features.
    Returns DataFrame with columns: bar_time, close, atr, pred, conf, excluded, ...
    """
    log_file = None
    for pattern in ["strategy_decisions*.log", "replay.log"]:
        matches = sorted(results_dir.glob(pattern))
        if matches:
            log_file = matches[-1]
            break
    if log_file is None or not log_file.exists():
        print("  [WARN] No strategy log found, skipping log-based analysis")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # Parse [BAR_METRICS] lines
    bar_metrics_pattern = re.compile(
        r"\[BAR_METRICS\]\s+(\S+\s+\S+)\s+"
        r"close=([\d.]+)\s+"
        r"atr=(\S+)\s+"
        r"pred=(\S+)\s+"
        r"conf=(\S+)\s+"
        r"thresh=(\S+)"
        r"(?:\s+mama_diff=(\S+))?"
        r"(?:\s+dmi_plus=(\S+))?"
        r"(?:\s+meta=(\S+))?"
        r"(?:\s+excluded=(\S+))?"
    )

    # Parse [SIGNAL] lines
    signal_pattern = re.compile(
        r"\[SIGNAL\]\s+Generated\s+(\w+)\s+signal\s+at\s+(\S+\s+\S+),\s+confidence:\s+([\d.]+)"
    )

    # Parse entry confirmation lines
    confirm_pattern = re.compile(
        r"Entry confirmed after (\d+) 1m bars \(movement: ([+-]?[\d.]+) ATR\)"
    )
    expired_pattern = re.compile(
        r"Signal expired after (\d+) 1m bars"
    )

    bar_rows = []
    signal_rows = []
    confirm_rows = []

    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = bar_metrics_pattern.search(line)
            if m:
                bar_rows.append({
                    "bar_time": m.group(1),
                    "close": float(m.group(2)),
                    "atr": _safe_float(m.group(3)),
                    "pred": _safe_int(m.group(4)),
                    "conf": _safe_float(m.group(5)),
                    "thresh": _safe_float(m.group(6)),
                    "mama_diff": _safe_float(m.group(7)) if m.group(7) else None,
                    "dmi_plus": _safe_float(m.group(8)) if m.group(8) else None,
                    "meta": m.group(9) if m.group(9) else None,
                    "excluded": m.group(10) if m.group(10) else None,
                })
                continue

            m = signal_pattern.search(line)
            if m:
                signal_rows.append({
                    "direction": m.group(1),
                    "signal_time": m.group(2),
                    "confidence": float(m.group(3)),
                })
                continue

            m = confirm_pattern.search(line)
            if m:
                confirm_rows.append({
                    "type": "confirmed",
                    "bars_waited": int(m.group(1)),
                    "movement_atr": float(m.group(2)),
                })
                continue

            m = expired_pattern.search(line)
            if m:
                confirm_rows.append({
                    "type": "expired",
                    "bars_waited": int(m.group(1)),
                    "movement_atr": None,
                })

    df_bars = pd.DataFrame(bar_rows)
    if not df_bars.empty:
        df_bars["bar_time"] = pd.to_datetime(df_bars["bar_time"], utc=True)
        # Deduplicate (some bars appear twice in log)
        df_bars = df_bars.drop_duplicates(subset=["bar_time"], keep="last")

    df_signals = pd.DataFrame(signal_rows)
    if not df_signals.empty:
        df_signals["signal_time"] = pd.to_datetime(df_signals["signal_time"], utc=True)

    df_confirms = pd.DataFrame(confirm_rows)

    return df_bars, df_signals, df_confirms


def load_1m_bars(start_date: str, end_date: str) -> pd.DataFrame:
    """Load 1-minute bars from NautilusTrader ParquetDataCatalog."""
    catalog_path = PROJECT_ROOT / "data" / "historical"
    if not catalog_path.exists():
        print(f"  [WARN] Catalog not found: {catalog_path}")
        return pd.DataFrame()

    try:
        from nautilus_trader.persistence.catalog import ParquetDataCatalog
        cat = ParquetDataCatalog(str(catalog_path))
        bars = cat.bars(
            ["EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL"],
            start=start_date,
            end=end_date,
        )
    except Exception as e:
        print(f"  [WARN] Failed to load 1m bars from catalog: {e}")
        return pd.DataFrame()

    if not bars:
        print("  [WARN] No 1m bars found in catalog for date range")
        return pd.DataFrame()

    # Convert Bar objects to DataFrame
    rows = []
    for b in bars:
        rows.append({
            "timestamp": pd.Timestamp(b.ts_event, unit="ns", tz="UTC"),
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df.drop_duplicates(subset=["timestamp"], keep="last")
    print(f"  Loaded {len(df):,} 1m bars ({df['timestamp'].min()} to {df['timestamp'].max()})")
    return df


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 2. MFE / MAE Calculation
# ---------------------------------------------------------------------------

def compute_mfe_mae(trades: pd.DataFrame, bars_1m: pd.DataFrame) -> pd.DataFrame:
    """
    For each trade, compute Max Favorable Excursion (MFE) and Max Adverse Excursion (MAE)
    using 1-minute bar data.

    MFE = max price movement in favorable direction (in pips and ATR units)
    MAE = max price movement in adverse direction (in pips and ATR units)
    """
    if bars_1m.empty:
        print("  [SKIP] No 1m bars available for MFE/MAE")
        return trades

    bars_1m_indexed = bars_1m.set_index("timestamp").sort_index()

    mfe_pips_list = []
    mae_pips_list = []
    mfe_atr_list = []
    mae_atr_list = []
    time_to_mfe_list = []

    for _, trade in trades.iterrows():
        entry_time = trade["entry_time"]
        exit_time = trade["exit_time"]
        entry_price = trade["entry"]
        side = trade["side"]

        # Get 1m bars during trade (widen by 1 min each side for alignment)
        lookup_start = entry_time - pd.Timedelta(minutes=1)
        lookup_end = exit_time + pd.Timedelta(minutes=1)
        mask = (bars_1m_indexed.index >= lookup_start) & (bars_1m_indexed.index <= lookup_end)
        trade_bars = bars_1m_indexed.loc[mask]

        if trade_bars.empty or len(trade_bars) < 1:
            mfe_pips_list.append(None)
            mae_pips_list.append(None)
            mfe_atr_list.append(None)
            mae_atr_list.append(None)
            time_to_mfe_list.append(None)
            continue

        if side == "LONG":
            favorable = trade_bars["high"] - entry_price
            adverse = entry_price - trade_bars["low"]
        else:  # SHORT
            favorable = entry_price - trade_bars["low"]
            adverse = trade_bars["high"] - entry_price

        # Drop NaN before computing max
        favorable = favorable.dropna()
        adverse = adverse.dropna()

        if favorable.empty or adverse.empty:
            mfe_pips_list.append(None)
            mae_pips_list.append(None)
            mfe_atr_list.append(None)
            mae_atr_list.append(None)
            time_to_mfe_list.append(None)
            continue

        mfe = float(favorable.max()) * 10000  # pips
        mae = float(adverse.max()) * 10000    # pips

        # Time to MFE (minutes from entry)
        mfe_idx = favorable.idxmax()
        time_to_mfe = (mfe_idx - entry_time).total_seconds() / 60.0

        mfe_pips_list.append(mfe)
        mae_pips_list.append(mae)
        time_to_mfe_list.append(time_to_mfe)

        # ATR-normalized (use trade's entry ATR if available from log matching)
        mfe_atr_list.append(None)  # Will be filled after log merge
        mae_atr_list.append(None)

    trades = trades.copy()
    trades["mfe_pips"] = mfe_pips_list
    trades["mae_pips"] = mae_pips_list
    trades["mfe_atr"] = mfe_atr_list
    trades["mae_atr"] = mae_atr_list
    trades["time_to_mfe_min"] = time_to_mfe_list

    return trades


# ---------------------------------------------------------------------------
# 3. Merge Log Features with Trades
# ---------------------------------------------------------------------------

def merge_log_features(trades: pd.DataFrame, df_signals: pd.DataFrame,
                       df_bars: pd.DataFrame) -> pd.DataFrame:
    """Match each trade to its signal and bar metrics for feature-level analysis."""
    if df_signals.empty or df_bars.empty:
        return trades

    trades = trades.copy()

    conf_list = []
    atr_list = []
    mama_list = []
    dmi_list = []

    for _, trade in trades.iterrows():
        entry_time = trade["entry_time"]

        # Find closest signal before entry (within 15 min window for confirmation delay)
        window_start = entry_time - pd.Timedelta(minutes=20)
        candidates = df_signals[
            (df_signals["signal_time"] >= window_start) &
            (df_signals["signal_time"] <= entry_time)
        ]

        if candidates.empty:
            # Try wider window
            candidates = df_signals[
                (df_signals["signal_time"] >= entry_time - pd.Timedelta(minutes=30)) &
                (df_signals["signal_time"] <= entry_time + pd.Timedelta(minutes=2))
            ]

        if not candidates.empty:
            signal = candidates.iloc[-1]
            signal_time = signal["signal_time"]
            conf_list.append(signal["confidence"])

            # Find bar metrics at signal time
            bar_match = df_bars[df_bars["bar_time"] == signal_time]
            if bar_match.empty:
                # Find closest bar within 1 minute
                time_diffs = (df_bars["bar_time"] - signal_time).abs()
                closest_idx = time_diffs.idxmin()
                if time_diffs.loc[closest_idx] < pd.Timedelta(minutes=16):
                    bar_match = df_bars.iloc[[closest_idx]]

            if not bar_match.empty:
                row = bar_match.iloc[0]
                atr_list.append(row.get("atr"))
                mama_list.append(row.get("mama_diff"))
                dmi_list.append(row.get("dmi_plus"))
            else:
                atr_list.append(None)
                mama_list.append(None)
                dmi_list.append(None)
        else:
            conf_list.append(None)
            atr_list.append(None)
            mama_list.append(None)
            dmi_list.append(None)

    trades["confidence"] = conf_list
    trades["entry_atr"] = atr_list
    trades["mama_diff"] = mama_list
    trades["dmi_plus"] = dmi_list

    # Now compute ATR-normalized MFE/MAE
    if "mfe_pips" in trades.columns:
        trades["mfe_atr"] = trades.apply(
            lambda r: r["mfe_pips"] / (r["entry_atr"] * 10000) if r.get("entry_atr") and r.get("mfe_pips") else None,
            axis=1,
        )
        trades["mae_atr"] = trades.apply(
            lambda r: r["mae_pips"] / (r["entry_atr"] * 10000) if r.get("entry_atr") and r.get("mae_pips") else None,
            axis=1,
        )

    return trades


# ---------------------------------------------------------------------------
# 4. Analysis Functions
# ---------------------------------------------------------------------------

def analyze_confidence_bands(trades: pd.DataFrame) -> str:
    """Analyze win rate and P&L by confidence bands."""
    lines = []
    lines.append("=" * 80)
    lines.append("CONFIDENCE BAND ANALYSIS")
    lines.append("=" * 80)

    df = trades.dropna(subset=["confidence"])
    if df.empty:
        lines.append("  No confidence data available")
        return "\n".join(lines)

    bins = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.01]
    labels = ["0.50-0.55", "0.55-0.60", "0.60-0.65", "0.65-0.70", "0.70-0.75",
              "0.75-0.80", "0.80-0.85", "0.85-0.90", "0.90-0.95", "0.95-1.00"]
    df = df.copy()
    df["conf_band"] = pd.cut(df["confidence"], bins=bins, labels=labels, right=False)

    lines.append(f"{'Band':<12} {'Trades':>7} {'WinRate':>8} {'AvgPnL':>9} {'TotalPnL':>10} {'AvgMAE':>8} {'AvgMFE':>8}")
    lines.append("-" * 72)

    for band in labels:
        subset = df[df["conf_band"] == band]
        if len(subset) == 0:
            continue
        n = len(subset)
        wr = subset["win"].mean() * 100
        avg_pnl = subset["pnl"].mean()
        total_pnl = subset["pnl"].sum()
        avg_mae = subset["mae_pips"].mean() if "mae_pips" in subset.columns else 0
        avg_mfe = subset["mfe_pips"].mean() if "mfe_pips" in subset.columns else 0
        flag = " <-- LOW" if wr < 60 else (" ** HIGH" if wr > 85 else "")
        lines.append(f"{band:<12} {n:>7} {wr:>7.1f}% ${avg_pnl:>8.2f} ${total_pnl:>9.2f} {avg_mae:>7.1f}p {avg_mfe:>7.1f}p{flag}")

    return "\n".join(lines)


def analyze_atr_regimes(trades: pd.DataFrame) -> str:
    """Analyze performance by ATR regime."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("ATR REGIME ANALYSIS")
    lines.append("=" * 80)

    df = trades.dropna(subset=["entry_atr"])
    if df.empty:
        lines.append("  No ATR data available")
        return "\n".join(lines)

    # Define regimes
    bins = [0, 0.0005, 0.001, 0.0015, 0.002, 0.003, 0.005, 1.0]
    labels = ["<0.0005", "0.0005-0.001", "0.001-0.0015", "0.0015-0.002",
              "0.002-0.003", "0.003-0.005", ">0.005"]
    df = df.copy()
    df["atr_regime"] = pd.cut(df["entry_atr"], bins=bins, labels=labels, right=False)

    lines.append(f"{'ATR Regime':<16} {'Trades':>7} {'WinRate':>8} {'AvgPnL':>9} {'TotalPnL':>10} {'AvgMAE':>8}")
    lines.append("-" * 62)

    for regime in labels:
        subset = df[df["atr_regime"] == regime]
        if len(subset) == 0:
            continue
        n = len(subset)
        wr = subset["win"].mean() * 100
        avg_pnl = subset["pnl"].mean()
        total_pnl = subset["pnl"].sum()
        avg_mae = subset["mae_pips"].mean() if "mae_pips" in subset.columns else 0
        flag = " <-- TOXIC" if total_pnl < 0 and n >= 5 else ""
        lines.append(f"{regime:<16} {n:>7} {wr:>7.1f}% ${avg_pnl:>8.2f} ${total_pnl:>9.2f} {avg_mae:>7.1f}p{flag}")

    return "\n".join(lines)


def analyze_mfe_mae(trades: pd.DataFrame) -> str:
    """Analyze MFE/MAE distributions for SL/TP optimization insights."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("MFE / MAE ANALYSIS (SL/TP Efficiency)")
    lines.append("=" * 80)

    df = trades.dropna(subset=["mfe_pips", "mae_pips"])
    if df.empty:
        lines.append("  No MFE/MAE data available")
        return "\n".join(lines)

    winners = df[df["win"]]
    losers = df[~df["win"]]

    lines.append("")
    lines.append(f"{'Metric':<30} {'Winners':>12} {'Losers':>12} {'All':>12}")
    lines.append("-" * 68)

    for label, col in [("MFE (pips)", "mfe_pips"), ("MAE (pips)", "mae_pips")]:
        w_mean = winners[col].mean() if len(winners) > 0 else 0
        l_mean = losers[col].mean() if len(losers) > 0 else 0
        a_mean = df[col].mean()
        lines.append(f"Avg {label:<26} {w_mean:>11.1f}p {l_mean:>11.1f}p {a_mean:>11.1f}p")

        w_med = winners[col].median() if len(winners) > 0 else 0
        l_med = losers[col].median() if len(losers) > 0 else 0
        a_med = df[col].median()
        lines.append(f"Median {label:<24} {w_med:>11.1f}p {l_med:>11.1f}p {a_med:>11.1f}p")

    if "time_to_mfe_min" in df.columns:
        w_ttm = winners["time_to_mfe_min"].median() if len(winners) > 0 else 0
        l_ttm = losers["time_to_mfe_min"].median() if len(losers) > 0 else 0
        a_ttm = df["time_to_mfe_min"].median()
        lines.append(f"{'Median Time-to-MFE (min)':<30} {w_ttm:>11.1f}m {l_ttm:>11.1f}m {a_ttm:>11.1f}m")

    # SL/TP efficiency
    lines.append("")
    lines.append("SL/TP EFFICIENCY:")

    if "mfe_atr" in df.columns:
        df_atr = df.dropna(subset=["mfe_atr", "mae_atr"])
        if not df_atr.empty:
            # How many winners had MFE > current TP (0.6 ATR for POS1)?
            tp_mult = 0.6
            sl_mult = 1.4
            winners_atr = df_atr[df_atr["win"]]
            losers_atr = df_atr[~df_atr["win"]]

            if len(winners_atr) > 0:
                pct_mfe_above_tp = (winners_atr["mfe_atr"] > tp_mult).mean() * 100
                avg_mfe_winners = winners_atr["mfe_atr"].mean()
                lines.append(f"  Winners with MFE > {tp_mult}x ATR (TP): {pct_mfe_above_tp:.1f}% (avg MFE: {avg_mfe_winners:.2f}x ATR)")
                lines.append(f"  --> If MFE >> TP, you may be exiting too early on POS1")

            if len(losers_atr) > 0:
                pct_mae_below_sl = (losers_atr["mae_atr"] < sl_mult).mean() * 100
                avg_mae_losers = losers_atr["mae_atr"].mean()
                lines.append(f"  Losers with MAE < {sl_mult}x ATR (SL): {pct_mae_below_sl:.1f}% (avg MAE: {avg_mae_losers:.2f}x ATR)")

                # How many losers reversed and became profitable?
                losers_with_mfe = losers_atr[losers_atr["mfe_atr"] > tp_mult]
                pct_losers_had_tp = len(losers_with_mfe) / len(losers_atr) * 100 if len(losers_atr) > 0 else 0
                lines.append(f"  Losers that reached TP level before SL: {pct_losers_had_tp:.1f}%")
                lines.append(f"  --> If high, SL may be too tight or TP too slow")

    return "\n".join(lines)


def analyze_hour_weekday_toxic(trades: pd.DataFrame) -> str:
    """Find toxic hour x weekday combinations."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("HOUR x WEEKDAY TOXIC REGIME DETECTION")
    lines.append("=" * 80)

    df = trades.copy()
    if "entry_hour" not in df.columns or "entry_weekday" not in df.columns:
        lines.append("  No hour/weekday data in trades")
        return "\n".join(lines)

    weekday_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

    # Group by hour x weekday
    grouped = df.groupby(["entry_hour", "entry_weekday"]).agg(
        trades=("pnl", "count"),
        total_pnl=("pnl", "sum"),
        win_rate=("win", "mean"),
        avg_pnl=("pnl", "mean"),
    ).reset_index()

    # Filter for toxic: negative total PnL with >= 3 trades
    toxic = grouped[(grouped["total_pnl"] < 0) & (grouped["trades"] >= 3)]
    toxic = toxic.sort_values("total_pnl")

    if toxic.empty:
        lines.append("  No toxic hour x weekday combinations found (all profitable)")
        return "\n".join(lines)

    lines.append(f"{'Hour':>5} {'Day':<5} {'Trades':>7} {'WinRate':>8} {'AvgPnL':>9} {'TotalPnL':>10}")
    lines.append("-" * 50)

    total_toxic_pnl = 0
    for _, row in toxic.iterrows():
        h = int(row["entry_hour"])
        wd = weekday_names.get(int(row["entry_weekday"]), "?")
        n = int(row["trades"])
        wr = row["win_rate"] * 100
        avg = row["avg_pnl"]
        total = row["total_pnl"]
        total_toxic_pnl += total
        lines.append(f"{h:>5} {wd:<5} {n:>7} {wr:>7.1f}% ${avg:>8.2f} ${total:>9.2f}")

    lines.append(f"\nTotal PnL from toxic regimes: ${total_toxic_pnl:.2f}")
    lines.append(f"Eliminating these would improve total PnL by ${abs(total_toxic_pnl):.2f}")

    return "\n".join(lines)


def analyze_entry_confirmation(df_confirms: pd.DataFrame) -> str:
    """Analyze entry confirmation effectiveness."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("ENTRY CONFIRMATION ANALYSIS")
    lines.append("=" * 80)

    if df_confirms.empty:
        lines.append("  No confirmation data available")
        return "\n".join(lines)

    confirmed = df_confirms[df_confirms["type"] == "confirmed"]
    expired = df_confirms[df_confirms["type"] == "expired"]

    total_signals = len(df_confirms)
    n_confirmed = len(confirmed)
    n_expired = len(expired)

    lines.append(f"Total signals generated: {total_signals}")
    lines.append(f"Confirmed (entered): {n_confirmed} ({n_confirmed/total_signals*100:.1f}%)")
    lines.append(f"Expired (filtered): {n_expired} ({n_expired/total_signals*100:.1f}%)")

    if not confirmed.empty:
        lines.append(f"\nConfirmed entries:")
        lines.append(f"  Avg bars waited: {confirmed['bars_waited'].mean():.1f}")
        lines.append(f"  Avg movement at confirmation: {confirmed['movement_atr'].mean():.2f} ATR")
        lines.append(f"  Median movement: {confirmed['movement_atr'].median():.2f} ATR")

        # Distribution of bars waited
        lines.append(f"\n  Bars waited distribution:")
        for n_bars in sorted(confirmed["bars_waited"].unique()):
            count = (confirmed["bars_waited"] == n_bars).sum()
            pct = count / len(confirmed) * 100
            lines.append(f"    {n_bars} bars: {count} ({pct:.1f}%)")

    return "\n".join(lines)


def generate_recommendations(trades: pd.DataFrame, df_confirms: pd.DataFrame) -> str:
    """Generate actionable parameter recommendations."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("ACTIONABLE RECOMMENDATIONS")
    lines.append("=" * 80)

    rec_num = 0

    # 1. Confidence threshold
    df = trades.dropna(subset=["confidence"])
    if not df.empty:
        low_conf = df[df["confidence"] < 0.65]
        if len(low_conf) >= 5:
            low_wr = low_conf["win"].mean() * 100
            low_pnl = low_conf["pnl"].sum()
            high_conf = df[df["confidence"] >= 0.65]
            high_wr = high_conf["win"].mean() * 100 if len(high_conf) > 0 else 0

            if low_wr < high_wr - 10 or low_pnl < 0:
                rec_num += 1
                lines.append(f"\n{rec_num}. RAISE PREDICTION THRESHOLD")
                lines.append(f"   Trades with conf < 0.65: {len(low_conf)} trades, {low_wr:.1f}% WR, ${low_pnl:.2f} total")
                lines.append(f"   Trades with conf >= 0.65: {len(high_conf)} trades, {high_wr:.1f}% WR, ${high_conf['pnl'].sum():.2f} total")
                lines.append(f"   Suggestion: Consider raising prediction_threshold to 0.65")

    # 2. ATR regime
    df = trades.dropna(subset=["entry_atr"])
    if not df.empty:
        very_low_atr = df[df["entry_atr"] < 0.0005]
        if len(very_low_atr) >= 3 and very_low_atr["pnl"].sum() < 0:
            rec_num += 1
            lines.append(f"\n{rec_num}. TIGHTEN MIN_ATR")
            lines.append(f"   Trades with ATR < 0.0005: {len(very_low_atr)} trades, ${very_low_atr['pnl'].sum():.2f} total")
            lines.append(f"   Suggestion: Raise min_atr from 0.0003 to 0.0005")

    # 3. MFE/MAE based SL/TP
    df = trades.dropna(subset=["mfe_atr", "mae_atr"])
    if not df.empty:
        winners = df[df["win"]]
        losers = df[~df["win"]]

        if len(winners) > 0:
            avg_winner_mfe = winners["mfe_atr"].mean()
            if avg_winner_mfe > 1.0:
                rec_num += 1
                lines.append(f"\n{rec_num}. CONSIDER WIDER TP FOR POS2")
                lines.append(f"   Avg winner MFE: {avg_winner_mfe:.2f}x ATR (current POS1 TP: 0.6x, POS2 TP: 1.5x)")
                lines.append(f"   Winners often move further than TP - POS2 may capture this")

        if len(losers) > 0:
            avg_loser_mae = losers["mae_atr"].mean()
            pct_losers_reversed = (losers["mfe_atr"] > 0.3).mean() * 100
            if pct_losers_reversed > 30:
                rec_num += 1
                lines.append(f"\n{rec_num}. SL TIMING ISSUE")
                lines.append(f"   {pct_losers_reversed:.1f}% of losers had MFE > 0.3 ATR before hitting SL")
                lines.append(f"   These trades moved favorably but then reversed")
                lines.append(f"   Consider: tighter TP or trailing stop activation")

    # 4. Toxic hours
    if "entry_hour" in trades.columns and "entry_weekday" in trades.columns:
        grouped = trades.groupby(["entry_hour", "entry_weekday"]).agg(
            trades=("pnl", "count"), total_pnl=("pnl", "sum")
        ).reset_index()
        toxic = grouped[(grouped["total_pnl"] < -20) & (grouped["trades"] >= 3)]
        if not toxic.empty:
            toxic_pnl = toxic["total_pnl"].sum()
            rec_num += 1
            lines.append(f"\n{rec_num}. ADD HOUR x WEEKDAY EXCLUSIONS")
            lines.append(f"   Found {len(toxic)} toxic hour x weekday combos (${toxic_pnl:.2f} total)")
            lines.append(f"   Adding these as seasonal exclusions could recover ${abs(toxic_pnl):.2f}")

    # 5. Entry confirmation
    if not df_confirms.empty:
        confirmed = df_confirms[df_confirms["type"] == "confirmed"]
        expired = df_confirms[df_confirms["type"] == "expired"]
        if len(expired) > 0:
            filter_rate = len(expired) / len(df_confirms) * 100
            if filter_rate > 50:
                rec_num += 1
                lines.append(f"\n{rec_num}. ENTRY CONFIRMATION FILTERING HEAVILY")
                lines.append(f"   {filter_rate:.1f}% of signals are being filtered out")
                lines.append(f"   Consider: lower entry_confirmation_threshold or increase max_wait_bars")

    if rec_num == 0:
        lines.append("\n  No strong recommendations at this time - parameters look well-tuned.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------

def find_latest_results() -> Optional[Path]:
    """Find the most recent backtest results folder."""
    results_base = PROJECT_ROOT / "backtest_results"
    candidates = sorted(results_base.glob("MTF_V2_ENTRY_CONFIRMED*"), reverse=True)
    for c in candidates:
        if (c / "trades.csv").exists():
            return c
    return None


def main():
    # Determine results directory
    if len(sys.argv) > 1:
        results_dir = Path(sys.argv[1])
    else:
        results_dir = find_latest_results()
        if results_dir is None:
            print("ERROR: No backtest results found. Run a backtest first.")
            return 1

    if not results_dir.exists():
        print(f"ERROR: Results directory not found: {results_dir}")
        return 1

    print("=" * 80)
    print("TRADE-LEVEL ANALYSIS + MFE/MAE REPORT")
    print("=" * 80)
    print(f"Results: {results_dir.name}")
    print()

    # Load data
    print("Loading data...")
    trades = load_trades(results_dir)
    print(f"  {len(trades)} trades loaded")

    # Parse strategy log
    log_result = parse_strategy_log(results_dir)
    if isinstance(log_result, tuple):
        df_bars, df_signals, df_confirms = log_result
        print(f"  {len(df_bars)} bar metrics, {len(df_signals)} signals, {len(df_confirms)} confirmation events")
    else:
        df_bars, df_signals, df_confirms = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # Load 1m bars for MFE/MAE
    if not trades.empty:
        start_date = trades["entry_time"].min().strftime("%Y-%m-%d")
        end_date = trades["exit_time"].max().strftime("%Y-%m-%d")
        print(f"  Loading 1m bars for {start_date} to {end_date}...")
        bars_1m = load_1m_bars(start_date, end_date)
    else:
        bars_1m = pd.DataFrame()

    # Compute MFE/MAE
    print("Computing MFE/MAE...")
    trades = compute_mfe_mae(trades, bars_1m)

    # Merge log features
    print("Merging log features...")
    trades = merge_log_features(trades, df_signals, df_bars)

    matched = trades["confidence"].notna().sum()
    print(f"  Matched {matched}/{len(trades)} trades to signal features")

    # Run analyses
    report_parts = []

    report_parts.append(analyze_confidence_bands(trades))
    report_parts.append(analyze_atr_regimes(trades))
    report_parts.append(analyze_mfe_mae(trades))
    report_parts.append(analyze_hour_weekday_toxic(trades))
    report_parts.append(analyze_entry_confirmation(df_confirms))
    report_parts.append(generate_recommendations(trades, df_confirms))

    full_report = "\n".join(report_parts)
    print(full_report)

    # Save report
    report_file = results_dir / "trade_analysis_report.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"TRADE-LEVEL ANALYSIS + MFE/MAE REPORT\n")
        f.write(f"Results: {results_dir.name}\n")
        f.write(f"Trades: {len(trades)}\n\n")
        f.write(full_report)

    print(f"\nReport saved to: {report_file}")

    # Save enriched trades CSV
    enriched_file = results_dir / "trades_enriched.csv"
    trades.to_csv(enriched_file, index=False)
    print(f"Enriched trades saved to: {enriched_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
