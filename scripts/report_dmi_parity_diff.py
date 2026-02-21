from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

BAR_RE = re.compile(r"\[BAR_METRICS\]\s+(?P<t>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\+\d{2}:\d{2}).*?dmi_plus=(?P<dmi>[^\s]+)")
DMI_RE = re.compile(r"\[DMI_PARITY\]\s+t=(?P<t>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+\d{2}:\d{2})\s+dmi_plus=(?P<dmi>[^\s]+)")


def parse_live(path: Path, shift_min: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = BAR_RE.search(line)
        if not m:
            continue
        try:
            t = datetime.fromisoformat(m.group("t")) + timedelta(minutes=shift_min)
            dmi = float(m.group("dmi"))
        except Exception:
            continue
        out[t.isoformat().replace("T", " ")] = dmi
    return out


def parse_replay(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = DMI_RE.search(line)
        if not m:
            continue
        try:
            t = datetime.fromisoformat(m.group("t"))
            dmi = float(m.group("dmi"))
        except Exception:
            continue
        out[t.isoformat().replace("T", " ")] = dmi
    return out


def latest_contiguous_bounds(metrics: dict[str, float], max_gap_minutes: int = 20) -> tuple[datetime, datetime] | None:
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


def filter_window(metrics: dict[str, float], start: datetime | None, end: datetime | None) -> dict[str, float]:
    if start is None and end is None:
        return metrics
    out: dict[str, float] = {}
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Report DMI parity between live BAR_METRICS and replay DMI_PARITY")
    ap.add_argument("--live", required=True)
    ap.add_argument("--replay", required=True)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD HH:MM")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD HH:MM")
    ap.add_argument("--live-shift-min", type=int, default=-15)
    ap.add_argument("--session-start", default="", help="Optional live-session start (YYYY-MM-DD HH:MM), UTC")
    ap.add_argument("--session-end", default="", help="Optional live-session end (YYYY-MM-DD HH:MM), UTC")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    session_start = datetime.strptime(args.session_start, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) if args.session_start else None
    session_end = datetime.strptime(args.session_end, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) if args.session_end else None

    live = parse_live(Path(args.live), args.live_shift_min)
    if session_start or session_end:
        live = filter_window(live, session_start, session_end)
        print(f"live_session={session_start or 'start'}->{session_end or 'end'}")
    else:
        auto_bounds = latest_contiguous_bounds(live)
        if auto_bounds is not None:
            live = filter_window(live, auto_bounds[0], auto_bounds[1])
            print(f"live_session_auto={auto_bounds[0]}->{auto_bounds[1]}")

    replay = parse_replay(Path(args.replay))

    keys = sorted(set(live).intersection(replay))
    keys = [k for k in keys if start <= datetime.fromisoformat(k) <= end]

    print(f"common_dmi_points={len(keys)}")
    if not keys:
        return

    abs_diffs = []
    for k in keys:
        abs_diffs.append(abs(live[k] - replay[k]))

    mean_abs = sum(abs_diffs) / len(abs_diffs)
    max_abs = max(abs_diffs)
    p90 = sorted(abs_diffs)[int(0.9 * (len(abs_diffs) - 1))]

    print(f"mean_abs_diff={mean_abs:.6f}")
    print(f"p90_abs_diff={p90:.6f}")
    print(f"max_abs_diff={max_abs:.6f}")

    print("top5:")
    pairs = sorted(((abs(live[k]-replay[k]), k, live[k], replay[k]) for k in keys), reverse=True)[:5]
    for d, t, lv, rv in pairs:
        print(f"{t} live={lv:.6f} replay={rv:.6f} abs_diff={d:.6f}")


if __name__ == "__main__":
    main()
