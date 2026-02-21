"""
Compare live trade journal events against backtest trades CSV.

Usage:
    python scripts/compare_live_vs_backtest_trades.py \\
        --journal  logs/live_mtf/trade_journal.csv \\
        --backtest backtest_results/<run>/trades_*.csv \\
        --match-window 30   # minutes within which a signal is considered the same trade
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_journal(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp_utc", "bar_time"])
    df["bar_time"] = pd.to_datetime(df["bar_time"], utc=True, errors="coerce")
    return df


def _load_backtest_trades(pattern: str) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        sys.exit(f"ERROR: no backtest trade CSV files found matching: {pattern}")
    frames = [pd.read_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    # Try to normalise column names
    for col in df.columns:
        if "entry" in col.lower() and "time" in col.lower():
            df["entry_time_utc"] = pd.to_datetime(df[col], utc=True, errors="coerce")
        if "exit" in col.lower() and "time" in col.lower():
            df["exit_time_utc"] = pd.to_datetime(df[col], utc=True, errors="coerce")
        if "side" in col.lower() or "direction" in col.lower():
            df["_side"] = df[col].str.upper()
        if "pnl" in col.lower():
            df["_pnl"] = pd.to_numeric(df[col], errors="coerce")
    return df


def _summarise_journal(j: pd.DataFrame) -> None:
    print("\n=== LIVE TRADE JOURNAL SUMMARY ===")
    counts = j["event_type"].value_counts().to_dict()
    for ev in ["SIGNAL", "CONFIRM_WAIT", "CONFIRM_FAIL", "CONFIRM_PASS", "ORDER_SUBMIT", "POSITION_CLOSE"]:
        print(f"  {ev:<20}: {counts.get(ev, 0)}")

    signals = j[j["event_type"] == "SIGNAL"]
    if not signals.empty:
        print(f"\n  Signal sides: {signals['side'].value_counts().to_dict()}")
        print(f"  Confidence range: {signals['confidence'].min():.3f} – {signals['confidence'].max():.3f}")

    closes = j[j["event_type"] == "POSITION_CLOSE"]
    if not closes.empty:
        pnl = pd.to_numeric(closes["pnl_usd"], errors="coerce")
        print(f"\n  Closed positions: {len(closes)}")
        print(f"  Total realised PnL: {pnl.sum():.2f} USD")
        wins = (pnl > 0).sum()
        losses = (pnl <= 0).sum()
        print(f"  Win/Loss: {wins}/{losses}")

    # Confirm rates
    n_signals = counts.get("SIGNAL", 0)
    n_pass = counts.get("CONFIRM_PASS", 0)
    n_fail = counts.get("CONFIRM_FAIL", 0)
    if n_signals:
        print(f"\n  Confirm pass rate: {n_pass}/{n_signals} ({100*n_pass/n_signals:.1f}%)")
        print(f"  Confirm fail rate: {n_fail}/{n_signals} ({100*n_fail/n_signals:.1f}%)")


def _match_by_bar_time(
    journal: pd.DataFrame,
    bt: pd.DataFrame,
    window_min: int,
) -> pd.DataFrame:
    """Match live SIGNAL events to backtest entries by bar_time proximity and side."""
    live_signals = journal[journal["event_type"] == "SIGNAL"].copy()
    if live_signals.empty:
        print("\nNo SIGNAL events in journal — nothing to match.")
        return pd.DataFrame()
    if "entry_time_utc" not in bt.columns:
        print("\nNo entry_time_utc in backtest trades — skipping match.")
        return pd.DataFrame()

    window = pd.Timedelta(minutes=window_min)
    rows = []
    for _, sig in live_signals.iterrows():
        bar_t = sig["bar_time"]
        if pd.isna(bar_t):
            continue
        near = bt[abs(bt["entry_time_utc"] - bar_t) <= window]
        if near.empty:
            rows.append({
                "live_bar_time": bar_t,
                "live_side": sig.get("side", ""),
                "live_confidence": sig.get("confidence", ""),
                "bt_entry_time": pd.NaT,
                "bt_side": "",
                "bt_pnl": "",
                "match": "NO_MATCH",
            })
        else:
            for _, bt_row in near.iterrows():
                bt_side = str(bt_row.get("_side", "")).upper()
                live_side = str(sig.get("side", "")).upper()
                match_str = "SIDE_MATCH" if bt_side == live_side else "SIDE_MISMATCH"
                rows.append({
                    "live_bar_time": bar_t,
                    "live_side": live_side,
                    "live_confidence": sig.get("confidence", ""),
                    "bt_entry_time": bt_row.get("entry_time_utc", pd.NaT),
                    "bt_side": bt_side,
                    "bt_pnl": bt_row.get("_pnl", ""),
                    "match": match_str,
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Compare live trade journal vs backtest trades")
    ap.add_argument("--journal", default="logs/live_mtf/trade_journal.csv",
                    help="Path to live trade journal CSV")
    ap.add_argument("--backtest", default="backtest_results/**/trades_*.csv",
                    help="Glob pattern for backtest trade CSV(s)")
    ap.add_argument("--match-window", type=int, default=30,
                    help="Match window in minutes for pairing signals (default 30)")
    ap.add_argument("--out", default="",
                    help="Optional path to write matched pairs CSV")
    args = ap.parse_args()

    # --- Load ---
    if not Path(args.journal).exists():
        sys.exit(f"ERROR: journal not found: {args.journal}")
    journal = _load_journal(args.journal)
    print(f"Loaded journal: {len(journal)} rows from {args.journal}")

    bt = _load_backtest_trades(args.backtest)
    print(f"Loaded backtest trades: {len(bt)} rows")

    # --- Summarise journal ---
    _summarise_journal(journal)

    # --- Backtest summary ---
    print("\n=== BACKTEST TRADE SUMMARY ===")
    print(f"  Trades: {len(bt)}")
    if "_pnl" in bt.columns:
        pnl = bt["_pnl"]
        print(f"  Total PnL: {pnl.sum():.2f}")
        print(f"  Win/Loss: {(pnl > 0).sum()}/{(pnl <= 0).sum()}")
    if "_side" in bt.columns:
        print(f"  Sides: {bt['_side'].value_counts().to_dict()}")

    # --- Match ---
    matched = _match_by_bar_time(journal, bt, args.match_window)
    if not matched.empty:
        print(f"\n=== SIGNAL MATCH RESULTS (window={args.match_window}m) ===")
        print(matched.to_string(index=False))

        n_match = (matched["match"] == "SIDE_MATCH").sum()
        n_side_mis = (matched["match"] == "SIDE_MISMATCH").sum()
        n_no = (matched["match"] == "NO_MATCH").sum()
        total = len(matched)
        print(f"\n  Side matches: {n_match}/{total}")
        print(f"  Side mismatches: {n_side_mis}/{total}")
        print(f"  No counterpart in backtest: {n_no}/{total}")

        if args.out:
            matched.to_csv(args.out, index=False)
            print(f"\n  Pairs written to: {args.out}")


if __name__ == "__main__":
    main()
