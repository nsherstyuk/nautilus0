from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class BinSpec:
    name: str
    low: float
    high: float

    def contains(self, x: float) -> bool:
        return self.low <= x < self.high


MASTER_ABS_BINS: List[BinSpec] = [
    BinSpec("0.70-0.75", 0.70, 0.75),
    BinSpec("0.75-0.80", 0.75, 0.80),
    BinSpec("0.80-0.85", 0.80, 0.85),
    BinSpec("0.85-0.90", 0.85, 0.90),
    BinSpec("0.90-1.00", 0.90, 1.00),
]

SOLDIER_SCORE_BINS: List[BinSpec] = [
    BinSpec("0.50-0.70", 0.50, 0.70),
    BinSpec("0.70-0.90", 0.70, 0.90),
    BinSpec("0.90-1.00", 0.90, 1.00),
]


def _parse_iso_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, float):
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "none":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() == "none":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _latest_results_dir(root: Path) -> Path:
    candidates: List[Path] = []
    for p in root.iterdir():
        if not p.is_dir():
            continue
        if p.name.startswith("MTF_V3_BACKTEST_REPLAY_"):
            candidates.append(p)
    if not candidates:
        raise FileNotFoundError(f"No v3 replay results found under {root}")
    return max(candidates, key=lambda x: x.stat().st_mtime)


def _read_summary(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_trades(path: Path) -> Iterable[Dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            yield row


def _max_drawdown(equity_curve_csv: Path) -> Optional[float]:
    if not equity_curve_csv.exists() or equity_curve_csv.stat().st_size == 0:
        return None
    peak: Optional[float] = None
    mdd: float = 0.0
    with equity_curve_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            eq = _safe_float(row.get("equity"))
            if eq is None:
                continue
            if peak is None or eq > peak:
                peak = eq
            if peak and peak > 0:
                dd = (peak - eq) / peak
                if dd > mdd:
                    mdd = dd
    return mdd if peak is not None else None


def _bucket(value: Optional[float], bins: List[BinSpec]) -> Optional[str]:
    if value is None:
        return None
    for b in bins:
        if b.contains(value):
            return b.name
    return None


def _accum(stats: Dict[str, Any], key: str, pnl: float) -> None:
    bucket = stats.setdefault(key, {"count": 0, "pnl": 0.0, "wins": 0, "losses": 0})
    bucket["count"] += 1
    bucket["pnl"] += pnl
    if pnl >= 0:
        bucket["wins"] += 1
    else:
        bucket["losses"] += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze v3 replay PnL results (diagnostics buckets)")
    parser.add_argument(
        "--results-dir",
        default=None,
        help="Path to a backtest_results/MTF_V3_BACKTEST_REPLAY_* directory (default: latest)",
    )
    parser.add_argument(
        "--root",
        default=str(PROJECT_ROOT / "backtest_results"),
        help="Root folder to search for latest results if --results-dir not provided",
    )
    args = parser.parse_args()

    root = Path(args.root)
    results_dir = Path(args.results_dir) if args.results_dir else _latest_results_dir(root)

    trades_csv = results_dir / "trades.csv"
    equity_csv = results_dir / "equity_curve.csv"
    summary_json = results_dir / "summary.json"

    summary = _read_summary(summary_json)

    total_trades = 0
    wins = 0
    losses = 0
    pnl_sum = 0.0
    pnl_gross_sum = 0.0
    commission_sum = 0.0

    by_side: Dict[str, Any] = {}
    by_reason: Dict[str, Any] = {}
    by_entry_hour: Dict[str, Any] = {}
    by_master_abs: Dict[str, Any] = {}
    by_soldier_score: Dict[str, Any] = {}

    missing_master_conf = 0
    missing_soldier_score = 0

    worst: List[Tuple[float, str, str]] = []
    best: List[Tuple[float, str, str]] = []

    for row in _iter_trades(trades_csv):
        total_trades += 1

        pnl = _safe_float(row.get("pnl_net")) or 0.0
        pnl_sum += pnl

        pnl_gross = _safe_float(row.get("pnl_gross")) or 0.0
        pnl_gross_sum += pnl_gross

        commission = _safe_float(row.get("commission")) or 0.0
        commission_sum += commission

        side = (row.get("side") or "").strip() or "UNKNOWN"
        reason = (row.get("reason") or "").strip() or "UNKNOWN"

        _accum(by_side, side, pnl)
        _accum(by_reason, reason, pnl)

        entry_time_s = row.get("entry_time")
        if entry_time_s:
            try:
                hour = _parse_iso_dt(entry_time_s).strftime("%H")
                _accum(by_entry_hour, hour, pnl)
            except ValueError:
                pass

        master_conf = _safe_float(row.get("master_confidence"))
        if master_conf is None:
            missing_master_conf += 1
        else:
            mb = _bucket(abs(master_conf), MASTER_ABS_BINS)
            if mb:
                _accum(by_master_abs, mb, pnl)

        soldier_score = _safe_float(row.get("soldier_score_entry"))
        if soldier_score is None:
            missing_soldier_score += 1
        else:
            sb = _bucket(soldier_score, SOLDIER_SCORE_BINS)
            if sb:
                _accum(by_soldier_score, sb, pnl)

        exit_time_s = row.get("exit_time") or ""
        worst.append((pnl, entry_time_s or "", exit_time_s))
        best.append((pnl, entry_time_s or "", exit_time_s))

        if pnl >= 0:
            wins += 1
        else:
            losses += 1

    worst_sorted = sorted(worst, key=lambda x: x[0])[:10]
    best_sorted = sorted(best, key=lambda x: -x[0])[:10]

    mdd = _max_drawdown(equity_csv)

    report: Dict[str, Any] = {
        "results_dir": str(results_dir),
        "summary": summary,
        "computed": {
            "trades": total_trades,
            "net_pnl": pnl_sum,
            "gross_pnl": pnl_gross_sum,
            "commission": commission_sum,
            "win_rate": (wins / total_trades) if total_trades else None,
            "avg_trade": (pnl_sum / total_trades) if total_trades else None,
            "max_drawdown_frac": mdd,
            "wins": wins,
            "losses": losses,
            "missing_master_confidence_rows": missing_master_conf,
            "missing_soldier_score_rows": missing_soldier_score,
        },
        "buckets": {
            "by_side": by_side,
            "by_reason": by_reason,
            "by_entry_hour_utc": by_entry_hour,
            "by_master_abs_conf": by_master_abs,
            "by_soldier_score_entry": by_soldier_score,
        },
        "top": {
            "worst_10": [{"pnl": p, "entry_time": et, "exit_time": xt} for (p, et, xt) in worst_sorted],
            "best_10": [{"pnl": p, "entry_time": et, "exit_time": xt} for (p, et, xt) in best_sorted],
        },
    }

    out_path = results_dir / "diagnostics_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Results: {results_dir}")
    print(f"Trades: {total_trades}  NetPnL: {pnl_sum:.2f}  WinRate: {(wins/total_trades if total_trades else 0):.3f}")
    if mdd is not None:
        print(f"MaxDD: {mdd:.3%}")
    if missing_master_conf:
        print(f"WARNING: {missing_master_conf} trades missing master_confidence (rerun backtest to populate)")
    if missing_soldier_score:
        print(f"WARNING: {missing_soldier_score} trades missing soldier_score_entry (rerun backtest to populate)")
    print(f"Wrote: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
