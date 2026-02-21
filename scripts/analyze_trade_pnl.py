#!/usr/bin/env python3
"""Analyze per-trade PnL from trade CSV files.

Examples:
  python scripts/analyze_trade_pnl.py --input "optimization_results/**/trades.csv"
  python scripts/analyze_trade_pnl.py --input "optimization_results/**/trades.csv" --limit 30
  python scripts/analyze_trade_pnl.py --input "optimization_results/**/trades.csv" --from 2025-01-01 --to 2025-03-31 --out reports/trades_pnl.csv
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


TIME_COLUMNS = ["entry_time", "ts_opened", "timestamp", "time"]
EXIT_TIME_COLUMNS = ["exit_time", "ts_closed", "close_time"]
SIDE_COLUMNS = ["side", "entry", "direction"]
ENTRY_COLUMNS = ["entry", "entry_price", "avg_px_open", "open_price"]
EXIT_COLUMNS = ["exit", "exit_price", "avg_px_close", "close_price"]
QTY_COLUMNS = ["qty", "quantity", "size", "units"]
PNL_COLUMNS = ["pnl", "realized_pnl", "realizedPNL", "realized_pnl_value"]
SYMBOL_COLUMNS = ["symbol", "instrument", "instrument_id", "asset", "pair"]


@dataclass
class TradeRow:
    source_file: str
    trade_id: int
    symbol: str
    side: str
    qty: float
    entry_time: datetime
    exit_time: datetime | None
    entry_price: float
    exit_price: float
    pnl: float
    exit_reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze trade PnL from CSV files")
    parser.add_argument(
        "--input",
        required=True,
        help="Glob pattern for trade CSV files (example: optimization_results/**/trades.csv)",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        help="Filter entry_time >= YYYY-MM-DD (UTC)",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        help="Filter entry_time <= YYYY-MM-DD (UTC)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max per-trade rows to print (default: 50, use 0 for all)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Optional output CSV path for normalized per-trade rows",
    )
    return parser.parse_args()


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pick_field(row: dict[str, str], candidates: list[str], default: str = "") -> str:
    for name in candidates:
        if name in row and row[name] not in (None, ""):
            return str(row[name]).strip()
    return default


def to_float(value: str, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if not text:
        return default
    text = text.replace("$", "")
    try:
        return float(text)
    except ValueError:
        return default


def parse_trade_rows(csv_path: Path) -> list[TradeRow]:
    trades: list[TradeRow] = []
    with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=1):
            entry_time = parse_iso_utc(pick_field(row, TIME_COLUMNS))
            if entry_time is None:
                continue

            exit_time = parse_iso_utc(pick_field(row, EXIT_TIME_COLUMNS))
            side = pick_field(row, SIDE_COLUMNS, default="UNKNOWN").upper()
            symbol = pick_field(row, SYMBOL_COLUMNS, default="UNKNOWN")
            qty = to_float(pick_field(row, QTY_COLUMNS, default="0"), default=0.0)
            entry_price = to_float(pick_field(row, ENTRY_COLUMNS, default="0"), default=0.0)
            exit_price = to_float(pick_field(row, EXIT_COLUMNS, default="0"), default=0.0)
            pnl = to_float(pick_field(row, PNL_COLUMNS, default="0"), default=0.0)
            exit_reason = pick_field(row, ["exit_reason", "close_reason"], default="")

            trades.append(
                TradeRow(
                    source_file=str(csv_path),
                    trade_id=idx,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                    exit_reason=exit_reason,
                )
            )
    return trades


def date_floor_utc(date_text: str) -> datetime:
    return datetime.fromisoformat(f"{date_text}T00:00:00+00:00")


def date_ceil_utc(date_text: str) -> datetime:
    return datetime.fromisoformat(f"{date_text}T23:59:59.999999+00:00")


def apply_filters(trades: Iterable[TradeRow], from_date: str | None, to_date: str | None) -> list[TradeRow]:
    start = date_floor_utc(from_date) if from_date else None
    end = date_ceil_utc(to_date) if to_date else None

    filtered: list[TradeRow] = []
    for trade in trades:
        if start and trade.entry_time < start:
            continue
        if end and trade.entry_time > end:
            continue
        filtered.append(trade)
    return filtered


def write_output_csv(out_path: Path, trades: list[TradeRow]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "source_file",
                "trade_id",
                "symbol",
                "side",
                "qty",
                "entry_time_utc",
                "exit_time_utc",
                "entry_price",
                "exit_price",
                "pnl",
                "exit_reason",
                "cum_pnl",
            ]
        )
        cumulative = 0.0
        for trade in trades:
            cumulative += trade.pnl
            writer.writerow(
                [
                    trade.source_file,
                    trade.trade_id,
                    trade.symbol,
                    trade.side,
                    f"{trade.qty:.2f}",
                    trade.entry_time.isoformat(),
                    trade.exit_time.isoformat() if trade.exit_time else "",
                    f"{trade.entry_price:.5f}",
                    f"{trade.exit_price:.5f}",
                    f"{trade.pnl:.2f}",
                    trade.exit_reason,
                    f"{cumulative:.2f}",
                ]
            )


def print_summary(trades: list[TradeRow]) -> None:
    total = len(trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl < 0)
    breakeven = total - wins - losses
    total_pnl = sum(t.pnl for t in trades)
    avg_pnl = total_pnl / total if total else 0.0

    print("=" * 90)
    print("TRADE PNL SUMMARY")
    print("=" * 90)
    print(f"Total trades: {total}")
    print(f"Wins/Losses/BE: {wins}/{losses}/{breakeven}")
    print(f"Win rate: {(wins / total * 100) if total else 0.0:.2f}%")
    print(f"Total PnL: ${total_pnl:,.2f}")
    print(f"Avg PnL per trade: ${avg_pnl:,.2f}")


def print_rows(trades: list[TradeRow], limit: int) -> None:
    print("\n" + "-" * 90)
    print("PER-TRADE PNL")
    print("-" * 90)
    print(
        f"{'#':<6} {'Entry UTC':<25} {'Side':<7} {'Symbol':<12} {'Entry':>10} {'Exit':>10} {'PnL':>10} {'CumPnL':>10}"
    )
    print("-" * 90)

    count = len(trades) if limit == 0 else min(limit, len(trades))
    cumulative = 0.0
    for idx, trade in enumerate(trades[:count], start=1):
        cumulative += trade.pnl
        print(
            f"{idx:<6} {trade.entry_time.isoformat():<25} {trade.side:<7} {trade.symbol:<12} "
            f"{trade.entry_price:>10.5f} {trade.exit_price:>10.5f} {trade.pnl:>10.2f} {cumulative:>10.2f}"
        )

    if limit > 0 and len(trades) > limit:
        print("-" * 90)
        print(f"Showing {limit} of {len(trades)} rows. Use --limit 0 to print all.")


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    files = sorted(repo_root.glob(args.input))

    if not files:
        print(f"No files matched: {args.input}")
        return 1

    print(f"Matched files: {len(files)}")

    trade_rows: list[TradeRow] = []
    for file_path in files:
        if file_path.name.lower().startswith("hour_weekday_"):
            continue
        trade_rows.extend(parse_trade_rows(file_path))

    trade_rows.sort(key=lambda t: t.entry_time)
    trade_rows = apply_filters(trade_rows, args.from_date, args.to_date)

    if not trade_rows:
        print("No trades found after applying filters.")
        return 1

    print_summary(trade_rows)
    print_rows(trade_rows, args.limit)

    if args.out:
        write_output_csv(args.out, trade_rows)
        print(f"\nSaved normalized trade report to: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
