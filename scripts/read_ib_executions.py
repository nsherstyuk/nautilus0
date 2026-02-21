"""
Read IBKR execution reports via ib_insync and dump them as CSV.

Usage (run while IB Gateway / TWS is running):
    python scripts/read_ib_executions.py \\
        --host 127.0.0.1 --port 4002 --client-id 99 \\
        --days 5 \\
        --out logs/live_mtf/ib_executions.csv

The output CSV can then be cross-referenced with trade_journal.csv via the
order_id / permId columns to reconcile live fills with strategy events.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# IB connection helpers
# ---------------------------------------------------------------------------

def _connect_ib(host: str, port: int, client_id: int):
    try:
        from ib_insync import IB
    except ImportError:
        sys.exit("ERROR: ib_insync is not installed.  Run: pip install ib_insync")

    ib = IB()
    ib.connect(host, port, clientId=client_id)
    return ib


# ---------------------------------------------------------------------------
# Execution fetching
# ---------------------------------------------------------------------------

COLUMNS = [
    "exec_id",
    "perm_id",
    "order_id",
    "client_id",
    "symbol",
    "sec_type",
    "currency",
    "exchange",
    "side",
    "shares",
    "price",
    "avg_price",
    "cum_qty",
    "time_utc",
    "account",
    "order_ref",
    "realized_pnl",
    "commission",
    "commission_currency",
]


def _fetch_executions(ib, days: int) -> list[dict]:
    from ib_insync import ExecutionFilter

    filt = ExecutionFilter()
    # IB filter supports symbol/side/secType but not time range directly;
    # we filter by date afterwards.
    fills = ib.reqExecutions(filt)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows = []
    for fill in fills:
        exec_ = fill.execution
        contract = fill.contract
        comm = fill.commissionReport

        # Parse execution time (IB returns "YYYYMMDD  HH:MM:SS" in local or UTC)
        raw_time = getattr(exec_, "time", "") or ""
        try:
            # IB format: "20240101  14:30:00" — treat as UTC
            t = datetime.strptime(raw_time.strip(), "%Y%m%d  %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                t = datetime.strptime(raw_time.strip(), "%Y%m%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                t = None

        if t is not None and t < cutoff:
            continue

        rows.append({
            "exec_id": getattr(exec_, "execId", ""),
            "perm_id": getattr(exec_, "permId", ""),
            "order_id": getattr(exec_, "orderId", ""),
            "client_id": getattr(exec_, "clientId", ""),
            "symbol": getattr(contract, "symbol", ""),
            "sec_type": getattr(contract, "secType", ""),
            "currency": getattr(contract, "currency", ""),
            "exchange": getattr(contract, "exchange", ""),
            "side": getattr(exec_, "side", ""),
            "shares": getattr(exec_, "shares", ""),
            "price": getattr(exec_, "price", ""),
            "avg_price": getattr(exec_, "avgPrice", ""),
            "cum_qty": getattr(exec_, "cumQty", ""),
            "time_utc": t.isoformat() if t else raw_time,
            "account": getattr(exec_, "acctNumber", ""),
            "order_ref": getattr(exec_, "orderRef", ""),
            "realized_pnl": getattr(comm, "realizedPNL", "") if comm else "",
            "commission": getattr(comm, "commission", "") if comm else "",
            "commission_currency": getattr(comm, "currency", "") if comm else "",
        })

    rows.sort(key=lambda r: r["time_utc"])
    return rows


def _write_csv(rows: list[dict], path: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written {len(rows)} executions to {out}")


def _print_summary(rows: list[dict]) -> None:
    print(f"\nTotal executions fetched: {len(rows)}")
    if not rows:
        return
    print(f"{'time_utc':<28} {'symbol':<10} {'side':<5} {'shares':<8} {'price':<10} {'order_ref':<20} {'realized_pnl'}")
    print("-" * 100)
    for r in rows:
        print(
            f"{str(r['time_utc']):<28} {str(r['symbol']):<10} {str(r['side']):<5} "
            f"{str(r['shares']):<8} {str(r['price']):<10} {str(r['order_ref']):<20} "
            f"{r['realized_pnl']}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch IB execution reports and write to CSV")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4002, help="IB Gateway port (4002=paper, 7497=live TWS)")
    ap.add_argument("--client-id", type=int, default=99)
    ap.add_argument("--days", type=int, default=5, help="How many days back to fetch")
    ap.add_argument("--out", default="logs/live_mtf/ib_executions.csv", help="Output CSV path")
    ap.add_argument("--no-write", action="store_true", help="Print only, do not write CSV")
    args = ap.parse_args()

    print(f"Connecting to IB Gateway {args.host}:{args.port} (clientId={args.client_id}) ...")
    ib = _connect_ib(args.host, args.port, args.client_id)
    print("Connected.")

    try:
        rows = _fetch_executions(ib, days=args.days)
    finally:
        ib.disconnect()
        print("Disconnected.")

    _print_summary(rows)

    if not args.no_write:
        _write_csv(rows, args.out)


if __name__ == "__main__":
    main()
