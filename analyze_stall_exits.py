import argparse
import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class TradeRow:
    exit_time: datetime
    pnl: float
    row: dict


_TS_RE = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\+00:00"
_STALL_RE = re.compile(rf"^(?P<ts>{_TS_RE}) \| STALL detected")
_CLOSED_RE = re.compile(rf"^(?P<ts>{_TS_RE}) \| TRADE CLOSED")


def _parse_ts(value: str) -> datetime:
    text = value.strip()
    return datetime.fromisoformat(text.replace(" ", "T"))


def _read_trades_csv(path: Path) -> list[TradeRow]:
    trades: list[TradeRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            exit_time = _parse_ts(row["exit_time"])
            pnl = float(row["pnl"])
            trades.append(TradeRow(exit_time=exit_time, pnl=pnl, row=row))
    return trades


def _iter_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8") as f:
        yield from f


def _read_stall_close_times(path: Path) -> tuple[list[datetime], list[datetime]]:
    stall_detected: list[datetime] = []
    stall_closed: list[datetime] = []

    armed = False
    for raw in _iter_lines(path):
        line = raw.strip("\n")

        m = _STALL_RE.match(line)
        if m:
            stall_detected.append(_parse_ts(m.group("ts")))
            armed = True
            continue

        m = _CLOSED_RE.match(line)
        if m:
            if armed:
                stall_closed.append(_parse_ts(m.group("ts")))
                armed = False
            continue

    return stall_detected, stall_closed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        required=True,
        help="Backtest run folder (must contain trades.csv and strategy_decisions.log)",
    )
    parser.add_argument(
        "--show-unmatched",
        action="store_true",
        help="Print first 20 STALL timestamps which didn't match any trade exit_time",
    )
    args = parser.parse_args()

    run_dir = Path(args.run)
    trades_path = run_dir / "trades.csv"
    log_path = run_dir / "strategy_decisions.log"

    if not trades_path.exists():
        raise SystemExit(f"Missing file: {trades_path}")
    if not log_path.exists():
        raise SystemExit(f"Missing file: {log_path}")

    trades = _read_trades_csv(trades_path)
    stall_detected, stall_closed = _read_stall_close_times(log_path)

    closed_set = set(stall_closed)
    stall_trades = [t for t in trades if t.exit_time in closed_set]

    neg = sum(1 for t in stall_trades if t.pnl < 0)
    pos = sum(1 for t in stall_trades if t.pnl > 0)
    zero = sum(1 for t in stall_trades if t.pnl == 0)

    print(f"Run: {run_dir}")
    print(f"Trades: {len(trades)}")
    print(f"STALL detected events in log: {len(stall_detected)}")
    print(f"STALL->CLOSED events in log: {len(stall_closed)}")
    print(f"Matched STALL-closed trades (by exit_time): {len(stall_trades)}")
    print(f"  pnl<0: {neg}")
    print(f"  pnl=0: {zero}")
    print(f"  pnl>0: {pos}")

    if stall_trades:
        total = sum(t.pnl for t in stall_trades)
        avg = total / len(stall_trades)
        print(f"  avg pnl: {avg:.6f}")
        print(f"  sum pnl: {total:.6f}")

    if args.show_unmatched:
        trade_exit_set = {t.exit_time for t in trades}
        unmatched = [ts for ts in stall_closed if ts not in trade_exit_set]
        print(f"Unmatched STALL-closed timestamps: {len(unmatched)}")
        for ts in unmatched[:20]:
            print(f"  {ts.isoformat()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
