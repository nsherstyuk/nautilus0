"""Summarize a `strategy_decisions.log` for parameter-tuning decisions.

This is meant to answer:
- Are we blocked by excluded hours, warmup, ATR limits, or meta filters?
- What does the confidence distribution look like for generated signals?

Example:
  python scripts/review_strategy_decisions_log.py \
    --log backtest_results/MTF_V2_ENTRY_CONFIRMED_20260125_144405/strategy_decisions.log

Output is printed to stdout.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


_RE_SIGNAL = re.compile(r"\[SIGNAL\]\s+Generated\s+(?P<side>LONG|SHORT)\s+signal.*?confidence:\s*(?P<conf>[0-9.]+)")
_RE_FILTERED = re.compile(r"\[FILTERED\]\s+(?P<reason>.+)$")
_RE_BAR_METRICS = re.compile(
    r"\[BAR_METRICS\].*?atr=(?P<atr>NA|[0-9.]+).*?meta=(?P<meta>NA|PASS|FAIL).*?excluded=(?P<excluded>True|False)",
    re.IGNORECASE,
)


@dataclass
class Summary:
    bars: int = 0
    bars_meta_pass: int = 0
    bars_meta_fail: int = 0
    bars_excluded: int = 0
    bars_atr_na: int = 0

    filtered_reasons: Dict[str, int] = None  # type: ignore[assignment]

    signals: int = 0
    signals_long: int = 0
    signals_short: int = 0
    confidences: List[float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.filtered_reasons is None:
            self.filtered_reasons = {}
        if self.confidences is None:
            self.confidences = []


def _bucket_reason(reason: str) -> str:
    r = reason.strip()

    # Coarse bucketing so similar lines group together
    if r.lower().startswith("excluded hour/time"):
        return "Excluded hour/time"
    if r.lower().startswith("warmup"):
        return "Warmup"
    if r.lower().startswith("atr unavailable"):
        return "ATR unavailable"
    if "atr" in r.lower() and ("below" in r.lower() or "above" in r.lower() or "out of" in r.lower()):
        return "ATR min/max"
    if "meta" in r.lower() and "filter" in r.lower():
        return "Meta filter"
    if r.lower().startswith("prediction"):
        return "Prediction threshold"

    # Fallback: keep the line but truncate to reduce noise
    return r[:80]


def _quantiles(values: List[float], qs: List[float]) -> Dict[float, float]:
    if not values:
        return {}
    xs = sorted(values)
    out: Dict[float, float] = {}
    n = len(xs)
    for q in qs:
        if q <= 0:
            out[q] = xs[0]
            continue
        if q >= 1:
            out[q] = xs[-1]
            continue
        idx = q * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        t = idx - lo
        out[q] = xs[lo] * (1 - t) + xs[hi] * t
    return out


def summarize(log_path: Path) -> Summary:
    s = Summary()
    for raw_line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = _RE_BAR_METRICS.search(raw_line)
        if m:
            s.bars += 1
            atr = m.group("atr")
            meta = m.group("meta").upper()
            excluded = m.group("excluded").lower() == "true"

            if atr.upper() == "NA":
                s.bars_atr_na += 1
            if excluded:
                s.bars_excluded += 1
            if meta == "PASS":
                s.bars_meta_pass += 1
            elif meta == "FAIL":
                s.bars_meta_fail += 1

        m = _RE_FILTERED.search(raw_line)
        if m:
            reason = _bucket_reason(m.group("reason"))
            s.filtered_reasons[reason] = s.filtered_reasons.get(reason, 0) + 1

        m = _RE_SIGNAL.search(raw_line)
        if m:
            s.signals += 1
            side = m.group("side").upper()
            if side == "LONG":
                s.signals_long += 1
            else:
                s.signals_short += 1
            try:
                s.confidences.append(float(m.group("conf")))
            except Exception:
                pass

    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=str, required=True, help="Path to strategy_decisions.log")
    args = ap.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"Log not found: {log_path}")
        return 2

    s = summarize(log_path)

    print("\n=== strategy_decisions.log summary ===")
    print(f"file: {log_path}")
    print(f"bars_with_metrics: {s.bars}")
    if s.bars:
        print(f"excluded_bars: {s.bars_excluded} ({s.bars_excluded / s.bars * 100:.1f}%)")
        print(f"meta_pass: {s.bars_meta_pass} ({s.bars_meta_pass / s.bars * 100:.1f}%)")
        print(f"meta_fail: {s.bars_meta_fail} ({s.bars_meta_fail / s.bars * 100:.1f}%)")
        print(f"atr_na_bars: {s.bars_atr_na} ({s.bars_atr_na / s.bars * 100:.1f}%)")

    print("\n=== Filtered reasons (top) ===")
    for reason, cnt in sorted(s.filtered_reasons.items(), key=lambda x: x[1], reverse=True)[:12]:
        print(f"{cnt:6d}  {reason}")

    print("\n=== Signals ===")
    print(f"signals: {s.signals} (LONG={s.signals_long}, SHORT={s.signals_short})")
    if s.confidences:
        qs = _quantiles(s.confidences, [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1])
        print("confidence quantiles:")
        for q in [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]:
            v = qs.get(q)
            if v is not None:
                print(f"  q{int(q*100):>3d}: {v:.3f}")
        for thr in [0.70, 0.75, 0.78, 0.80, 0.82, 0.85, 0.90]:
            n = sum(1 for c in s.confidences if c >= thr)
            print(f"  >= {thr:.2f}: {n}/{len(s.confidences)} ({n/len(s.confidences)*100:.1f}%)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
