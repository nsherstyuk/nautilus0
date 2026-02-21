"""
Compare per-bar BAR_METRICS between live trading log and backtest replay log.

Parses [BAR_METRICS] lines from both logs and produces a side-by-side table
for matching bar_times showing pred, conf, mama_diff, dmi_plus, meta, atr.

Usage:
    python scripts/compare_live_vs_bt_bar_metrics.py \\
        --live    logs/live_mtf/strategy.log \\
        --replay  backtest_results/MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_XXXXXXXX_XXXXXX/replay.log \\
        --start   "2026-02-20 19:00" \\
        --end     "2026-02-20 22:00"

Timestamp alignment note:
    Live logs use bar.ts_init (~bar close time); backtest replay logs use
    ts_event (bar open time).  For 15-minute bars this is a 15-minute offset.
    --live-bar-shift-min=-15 (the default) shifts live timestamps back so they
    align with replay bar-open timestamps before comparison.  Pass 0 to disable.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

_METRICS_RE = re.compile(
    r"\[BAR_METRICS\]\s+"
    r"(?P<bar_time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\+\d{2}:\d{2})\s+"
    r"close=(?P<close>[^\s]+)\s+"
    r"atr=(?P<atr>[^\s]+)\s+"
    r"pred=(?P<pred>[^\s]+)\s+"
    r"conf=(?P<conf>[^\s]+)\s+"
    r"thresh=(?P<thresh>[^\s]+)\s+"
    r"mama_diff=(?P<mama_diff>[^\s]+)\s+"
    r"dmi_plus=(?P<dmi_plus>[^\s]+)\s+"
    r"meta=(?P<meta>[^\s]+)"
)


def _parse_metrics(log_path: str, bar_shift_minutes: int = 0) -> dict[str, dict]:
    """Return dict keyed by bar_time ISO string -> metric dict.

    If *bar_shift_minutes* is non-zero each parsed timestamp is shifted by that
    many minutes before being used as the dictionary key.  Use -15 to convert
    live ts_init (bar-close) timestamps into bar-open timestamps so they match
    the replay log convention.
    """
    results = {}
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _METRICS_RE.search(line)
            if not m:
                continue
            d = m.groupdict()
            key = d["bar_time"]
            if bar_shift_minutes:
                try:
                    shifted = datetime.fromisoformat(key) + timedelta(minutes=bar_shift_minutes)
                    # Keep space-separated format to match original regex output
                    key = shifted.isoformat().replace("T", " ")
                except ValueError:
                    pass
            results[key] = d
    return results


def _filter_window(metrics: dict, start: datetime | None, end: datetime | None) -> dict:
    if start is None and end is None:
        return metrics
    out = {}
    for k, v in metrics.items():
        try:
            t = datetime.fromisoformat(k)
        except ValueError:
            continue
        if start and t < start:
            continue
        if end and t > end:
            continue
        out[k] = v
    return out


def _latest_contiguous_bounds(metrics: dict, max_gap_minutes: int = 20) -> tuple[datetime, datetime] | None:
    times = []
    for key in metrics.keys():
        try:
            times.append(datetime.fromisoformat(key))
        except ValueError:
            continue
    if not times:
        return None
    times = sorted(set(times))
    seg_start = times[0]
    seg_end = times[0]
    segments: list[tuple[datetime, datetime]] = []
    max_gap = timedelta(minutes=max_gap_minutes)
    for t in times[1:]:
        if t - seg_end <= max_gap:
            seg_end = t
        else:
            segments.append((seg_start, seg_end))
            seg_start = t
            seg_end = t
    segments.append((seg_start, seg_end))
    return segments[-1]


# --------------------------------------------------------------------------- #
# Comparison / formatting
# --------------------------------------------------------------------------- #

_FIELDS = ["close", "atr", "pred", "conf", "thresh", "mama_diff", "dmi_plus", "meta"]
_FLOAT_FIELDS = {"close", "atr", "conf", "mama_diff", "dmi_plus", "thresh"}
_FLOAT_TOL = 0.0001


def _nearly_equal(field: str, a: str, b: str) -> bool:
    if field in _FLOAT_FIELDS:
        try:
            return abs(float(a) - float(b)) <= _FLOAT_TOL
        except ValueError:
            pass
    return a == b


def _run_comparison(live: dict, replay: dict) -> None:
    all_times = sorted(set(live) | set(replay))
    n_common = sum(1 for t in all_times if t in live and t in replay)
    n_live_only = sum(1 for t in all_times if t in live and t not in replay)
    n_replay_only = sum(1 for t in all_times if t not in live and t in replay)

    print(
        f"\nBars: {len(all_times)} total | {n_common} common | "
        f"{n_live_only} live-only | {n_replay_only} replay-only\n"
    )

    header = f"{'bar_time':<26} {'src':<7} " + " ".join(f"{f:<12}" for f in _FIELDS)
    sep = "-" * len(header)
    print(header)
    print(sep)

    diffs = []

    for t in all_times:
        in_live = t in live
        in_replay = t in replay

        def _row(src_label: str, d: dict) -> str:
            vals = " ".join(f"{d.get(f, 'N/A'):<12}" for f in _FIELDS)
            return f"{t:<26} {src_label:<7} {vals}"

        if in_live and in_replay:
            print(_row("LIVE", live[t]))
            print(_row("REPLAY", replay[t]))
            # Diff check
            markers = []
            for f in _FIELDS:
                lv = live[t].get(f, "?")
                rv = replay[t].get(f, "?")
                if not _nearly_equal(f, lv, rv):
                    markers.append(f"{f}={lv}->{rv}")
            if markers:
                diff_str = f"  *** DIFF at {t}: " + ", ".join(markers)
                diffs.append(diff_str)
                print(diff_str)
            print()
        elif in_live:
            print(_row("LIVE", live[t]))
            print(f"  *** {t}: live only (not in replay)\n")
        else:
            print(_row("REPLAY", replay[t]))
            print(f"  *** {t}: replay only (not in live)\n")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Common bars: {n_common}")
    print(f"Bars with differences: {len(diffs)}")
    if n_common:
        exact_matches = n_common - len(diffs)
        print(
            f"Exact/near matches: {exact_matches}/{n_common} "
            f"({100*exact_matches/n_common:.1f}%)"
        )

    if diffs:
        print("\nDifferences:")
        for d in diffs:
            print(d)

    # pred/conf agreement stats
    pred_agree = 0
    pred_total = 0
    for t in all_times:
        if t in live and t in replay:
            lp = live[t].get("pred", "NA")
            rp = replay[t].get("pred", "NA")
            if lp != "NA" and rp != "NA":
                pred_total += 1
                if lp == rp:
                    pred_agree += 1
    if pred_total:
        print(
            f"\npred agreement: {pred_agree}/{pred_total} "
            f"({100*pred_agree/pred_total:.1f}%)"
        )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description="Compare live vs backtest BAR_METRICS")
    ap.add_argument("--live", default="logs/live_mtf/strategy.log",
                    help="Path to live strategy log (contains BAR_METRICS)")
    ap.add_argument("--replay", required=True,
                    help="Path to backtest replay.log")
    ap.add_argument("--start", default="",
                    help="Filter start datetime (YYYY-MM-DD HH:MM), UTC")
    ap.add_argument("--end", default="",
                    help="Filter end datetime (YYYY-MM-DD HH:MM), UTC")
    ap.add_argument(
        "--live-bar-shift-min",
        type=int,
        default=-15,
        dest="live_bar_shift_min",
        help=(
            "Shift live log timestamps by this many minutes before matching against "
            "replay timestamps (default: -15, converting live ts_init/bar-close to "
            "bar-open so timestamps align with the replay log convention). "
            "Pass 0 to disable shifting."
        ),
    )
    ap.add_argument("--session-start", default="",
                    help="Optional live-session start (YYYY-MM-DD HH:MM), UTC")
    ap.add_argument("--session-end", default="",
                    help="Optional live-session end (YYYY-MM-DD HH:MM), UTC")
    ap.add_argument("--auto-session", action="store_true", default=True,
                    help="Auto-select latest contiguous live session when session bounds are omitted (default: enabled)")
    args = ap.parse_args()

    def _parse_dt(s: str) -> datetime | None:
        if not s:
            return None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    start_dt = _parse_dt(args.start)
    end_dt = _parse_dt(args.end)
    session_start_dt = _parse_dt(args.session_start)
    session_end_dt = _parse_dt(args.session_end)

    live_path = Path(args.live)
    replay_path = Path(args.replay)
    if not live_path.exists():
        print(f"ERROR: live log not found: {live_path}")
        return
    if not replay_path.exists():
        print(f"ERROR: replay log not found: {replay_path}")
        return

    print(f"Live log:   {live_path}")
    print(f"Replay log: {replay_path}")
    if start_dt:
        print(f"Window:     {start_dt} -> {end_dt or 'end'}")
    if args.live_bar_shift_min:
        print(
            f"Live timestamp shift: {args.live_bar_shift_min:+d} min "
            f"(converting ts_init -> bar-open for alignment with replay)"
        )

    live_metrics_raw = _parse_metrics(str(live_path), bar_shift_minutes=args.live_bar_shift_min)
    if session_start_dt or session_end_dt:
        live_metrics_raw = _filter_window(live_metrics_raw, session_start_dt, session_end_dt)
        print(f"Live session: {session_start_dt or 'start'} -> {session_end_dt or 'end'}")
    elif args.auto_session:
        auto_bounds = _latest_contiguous_bounds(live_metrics_raw)
        if auto_bounds is not None:
            live_metrics_raw = _filter_window(live_metrics_raw, auto_bounds[0], auto_bounds[1])
            print(f"Live session (auto latest contiguous): {auto_bounds[0]} -> {auto_bounds[1]}")

    live_metrics = _filter_window(live_metrics_raw, start_dt, end_dt)
    replay_metrics = _filter_window(_parse_metrics(str(replay_path)), start_dt, end_dt)

    print(f"\nParsed {len(live_metrics)} live bars, {len(replay_metrics)} replay bars in window")
    _run_comparison(live_metrics, replay_metrics)


if __name__ == "__main__":
    main()
