"""Review and compare backtest runs by parameters.

This script scans `backtest_results/<RUN_DIR>/` folders, extracts:
- The saved `.env.mtf_v2` for the run (parameter values)
- Key metrics from `summary.txt`

It then outputs a CSV you can sort/filter, plus prints a small console report
showing which parameter values are associated with better results.

Typical usage:
  python scripts/review_backtest_results.py \
    --root backtest_results \
    --pattern MTF_V2_ENTRY_CONFIRMED_* \
    --out reports/mtf_v2_entry_confirmed_param_review.csv

Notes:
- This is *observational*: it summarizes what happened in completed runs.
- For true "what-if" evaluation of TP/SL or filters, you still need reruns;
  but this quickly tells you which values are promising to test next.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


_NUM = r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?"

_METRIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("total_trades", re.compile(r"^\s*Total Trades:\s*(?P<v>[-+]?\d+)\s*$", re.I)),
    ("win_rate", re.compile(r"^\s*Win Rate:\s*(?P<v>[-+]?\d+(?:\.\d+)?)%\s*$", re.I)),
    # Repo summaries use "Total P&L" (sometimes with commas)
    ("total_pnl", re.compile(rf"^\s*Total\s+P\&L:\s*\$?(?P<v>(?:{_NUM}))\s*$", re.I)),
    ("net_profit", re.compile(rf"^\s*Net\s+Profit:\s*\$?(?P<v>(?:{_NUM}))\s*$", re.I)),
    ("sharpe", re.compile(r"^\s*Sharpe(?: Ratio)?:\s*(?P<v>[-+]?\d+(?:\.\d+)?)\s*$", re.I)),
    ("profit_factor", re.compile(r"^\s*Profit Factor:\s*(?P<v>[-+]?\d+(?:\.\d+)?)\s*$", re.I)),
    # Repo summaries: "Max Drawdown: $-18.10 (-49.8%)"
    ("max_drawdown_usd", re.compile(rf"^\s*Max\s+Drawdown:\s*\$?(?P<v>(?:{_NUM}))\s*(?:\(|$)", re.I)),
    ("max_drawdown_pct", re.compile(r"^\s*Max\s+Drawdown:.*\((?P<v>[-+]?\d+(?:\.\d+)?)%\)\s*$", re.I)),
]


@dataclass(frozen=True)
class RunRecord:
    run_dir: str
    env: Dict[str, str]
    metrics: Dict[str, float]


def _parse_env_file(env_path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not env_path.exists():
        return env

    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        env[key] = value
    return env


def _parse_summary(summary_path: Path) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    if not summary_path.exists():
        return metrics

    for raw_line in summary_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.rstrip("\n")
        for name, pat in _METRIC_PATTERNS:
            m = pat.match(line)
            if not m:
                continue
            try:
                raw = m.group("v")
                if isinstance(raw, str):
                    raw = raw.replace(",", "")
                metrics[name] = float(raw)
            except Exception:
                pass
    return metrics


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _extract_focus_params(env: Dict[str, str]) -> Dict[str, str]:
    """Keep the CSV narrow by extracting a focused subset of parameters."""
    keys = [
        # Core risk/targets
        "MTF2_SL_ATR_MULT",
        "MTF2_POS1_TP_ATR_MULT",
        "MTF2_POS2_TP_ATR_MULT",
        "MTF2_TRAILING_ACTIVATION_ATR_MULT",
        "MTF2_TRAILING_DISTANCE_ATR_MULT",
        # Prediction
        "MTF2_PREDICTION_THRESHOLD",
        # Meta filters
        "MTF2_META_FILTER_MAMA_ENABLED",
        "MTF2_META_FILTER_MAMA_MIN_DIFF",
        "MTF2_META_FILTER_DMI_ENABLED",
        "MTF2_META_FILTER_DMI_MIN_DMP",
        "MTF2_META_FILTER_DMI_MIN_DIVERGENCE",
        "MTF2_META_FILTER_DMI_CHECK_ABSOLUTE",
        # Session / excluded hours
        "MTF2_EXCLUDED_HOURS_MODE",
        "MTF2_CONFIG_TIMEZONE",
        "MTF2_TRADE_START_HOUR",
        "MTF2_TRADE_END_HOUR",
        # Entry confirmation
        "MTF2_ENTRY_CONFIRM_ENABLED",
        "MTF2_ENTRY_CONFIRM_BARS",
        "MTF2_ENTRY_CONFIRM_THRESHOLD",
        "MTF2_ENTRY_CONFIRM_MAX_WAIT_BARS",
        # Confidence SL (if used)
        "MTF2_CONF_SL_ENABLED",
        "MTF2_CONF_SL_INTERPOLATE",
        "MTF2_CONF_SL_TIERS",
    ]

    out: Dict[str, str] = {}
    for k in keys:
        if k in env:
            out[k] = env[k]
    return out


def _iter_runs(root: Path, pattern: str) -> Iterable[Path]:
    if not root.exists():
        return
    for p in sorted(root.glob(pattern)):
        if p.is_dir():
            yield p


def _load_records(root: Path, pattern: str) -> List[RunRecord]:
    records: List[RunRecord] = []
    for run_dir in _iter_runs(root, pattern):
        env = _parse_env_file(run_dir / ".env.mtf_v2")
        metrics = _parse_summary(run_dir / "summary.txt")
        if not env and not metrics:
            continue
        records.append(RunRecord(run_dir=run_dir.name, env=env, metrics=metrics))
    return records


def _write_csv(records: List[RunRecord], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Flatten
    rows: List[Dict[str, str]] = []
    all_keys: set[str] = {"run_dir"}

    for rec in records:
        row: Dict[str, str] = {"run_dir": rec.run_dir}

        focus = _extract_focus_params(rec.env)
        for k, v in focus.items():
            row[k] = v
            all_keys.add(k)

        for k, v in rec.metrics.items():
            mk = f"metric__{k}"
            row[mk] = f"{v}"
            all_keys.add(mk)

        rows.append(row)

    fieldnames = [
        "run_dir",
        # params (stable order)
        *sorted([k for k in all_keys if k.startswith("MTF2_")]),
        # metrics
        *sorted([k for k in all_keys if k.startswith("metric__")]),
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _print_quick_report(records: List[RunRecord], top_n: int) -> None:
    # Choose a sort metric (prefer net_profit then total_pnl then sharpe)
    def score(m: Dict[str, float]) -> float:
        if "net_profit" in m:
            return float(m["net_profit"])
        if "total_pnl" in m:
            return float(m["total_pnl"])
        if "sharpe" in m:
            return float(m["sharpe"])
        return float("-inf")

    ranked = sorted(records, key=lambda r: score(r.metrics), reverse=True)

    print("\n=== Top runs (by Net Profit / Total PnL / Sharpe fallback) ===")
    for rec in ranked[: max(1, top_n)]:
        m = rec.metrics
        print(
            f"{rec.run_dir}: trades={m.get('total_trades','?')} win={m.get('win_rate','?')}% "
            f"pnl={m.get('total_pnl','?')} net={m.get('net_profit','?')} "
            f"sharpe={m.get('sharpe','?')} dd={m.get('max_drawdown_pct','?')}% pf={m.get('profit_factor','?')}"
        )

    # Parameter value “best-of” (median of top quartile)
    focus_keys = list(_extract_focus_params({"MTF2_SL_ATR_MULT": ""}).keys())
    focus_keys = [
        "MTF2_SL_ATR_MULT",
        "MTF2_POS1_TP_ATR_MULT",
        "MTF2_POS2_TP_ATR_MULT",
        "MTF2_PREDICTION_THRESHOLD",
        "MTF2_META_FILTER_MAMA_MIN_DIFF",
        "MTF2_META_FILTER_DMI_MIN_DMP",
        "MTF2_META_FILTER_DMI_MIN_DIVERGENCE",
        "MTF2_ENTRY_CONFIRM_THRESHOLD",
    ]

    # Build a list of (param, value, metric) rows for runs with the needed metric
    def top_quartile(recs: List[RunRecord]) -> List[RunRecord]:
        scored = [r for r in recs if score(r.metrics) != float("-inf")]
        if not scored:
            return []
        scored = sorted(scored, key=lambda r: score(r.metrics), reverse=True)
        k = max(1, int(math.ceil(len(scored) * 0.25)))
        return scored[:k]

    tq = top_quartile(records)
    if not tq:
        return

    print("\n=== Parameter hints (from top quartile runs) ===")
    for key in focus_keys:
        vals: List[Tuple[str, float]] = []
        for r in tq:
            if key not in r.env:
                continue
            vf = _safe_float(r.env[key])
            if vf is None:
                continue
            vals.append((r.run_dir, vf))

        if len(vals) < 3:
            continue

        only = sorted([v for _, v in vals])
        med = float(only[len(only) // 2])
        lo = float(only[int(len(only) * 0.1)])
        hi = float(only[int(len(only) * 0.9)])
        print(f"{key}: typical ~{med:.4g} (10–90%: {lo:.4g} to {hi:.4g}, n={len(only)})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=str, default="backtest_results", help="Folder containing run subfolders")
    ap.add_argument("--pattern", type=str, default="MTF_V2_ENTRY_CONFIRMED_*", help="Glob for run folders")
    ap.add_argument(
        "--out",
        type=str,
        default="reports/mtf_v2_entry_confirmed_param_review.csv",
        help="CSV output path",
    )
    ap.add_argument("--top", type=int, default=15, help="Number of top runs to print")
    args = ap.parse_args()

    root = Path(args.root)
    out_path = Path(args.out)

    records = _load_records(root=root, pattern=args.pattern)
    if not records:
        print(f"No runs found under {root} matching {args.pattern}")
        return 2

    _write_csv(records, out_path)
    print(f"Wrote {len(records)} rows -> {out_path}")

    _print_quick_report(records, top_n=args.top)
    print("\nTip: open the CSV and sort by metric__net_profit / metric__sharpe / metric__max_drawdown_pct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
