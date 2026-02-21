import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


BAR_METRICS_RE = re.compile(
    r"\[BAR_METRICS\]\s+"
    r"(?P<bar_time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\+\d{2}:\d{2})\s+"
    r"close=(?P<close>-?[0-9.]+|NA)\s+"
    r"atr=(?P<atr>-?[0-9.]+|NA)\s+"
    r"pred=(?P<pred>-?[0-9.]+|NA)\s+"
    r"conf=(?P<conf>-?[0-9.]+|NA).*?"
    r"meta=(?P<meta>[A-Z]+|NA)\s+"
    r"excluded=(?P<excluded>True|False)"
)

SIGNAL_RE = re.compile(
    r"\[SIGNAL\]\s+Generated\s+(?P<side>LONG|SHORT)\s+signal\s+at\s+"
    r"(?P<bar_time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}),\s+confidence:\s+(?P<conf>[0-9.]+)"
)


@dataclass
class ParsedLog:
    metrics: pd.DataFrame
    signals: pd.DataFrame


def _to_float(v: str):
    if v == "NA":
        return None
    try:
        return float(v)
    except Exception:
        return None


def _parse_log(path: Path, start: pd.Timestamp, end: pd.Timestamp) -> ParsedLog:
    metric_rows = []
    signal_rows = []

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = BAR_METRICS_RE.search(line)
            if m:
                bar_time = pd.Timestamp(m.group("bar_time")).tz_convert("UTC")
                if start <= bar_time < end:
                    metric_rows.append(
                        {
                            "bar_time": bar_time,
                            "close": _to_float(m.group("close")),
                            "atr": _to_float(m.group("atr")),
                            "pred": _to_float(m.group("pred")),
                            "conf": _to_float(m.group("conf")),
                            "meta": m.group("meta"),
                            "excluded": m.group("excluded") == "True",
                        }
                    )
                continue

            s = SIGNAL_RE.search(line)
            if s:
                bar_time = pd.Timestamp(s.group("bar_time")).tz_convert("UTC")
                if start <= bar_time < end:
                    signal_rows.append(
                        {
                            "bar_time": bar_time,
                            "side": s.group("side"),
                            "signal_conf": float(s.group("conf")),
                        }
                    )

    metrics = pd.DataFrame(metric_rows)
    signals = pd.DataFrame(signal_rows)

    if not metrics.empty:
        metrics = (
            metrics.sort_values("bar_time")
            .drop_duplicates(subset=["bar_time"], keep="last")
            .set_index("bar_time")
        )
    else:
        metrics = pd.DataFrame(columns=["close", "atr", "pred", "conf", "meta", "excluded"])
        metrics.index.name = "bar_time"

    if not signals.empty:
        signals = (
            signals.sort_values("bar_time")
            .drop_duplicates(subset=["bar_time", "side"], keep="last")
            .set_index("bar_time")
        )
    else:
        signals = pd.DataFrame(columns=["side", "signal_conf"])
        signals.index.name = "bar_time"

    return ParsedLog(metrics=metrics, signals=signals)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare live and replay decision parity by bar timestamp")
    parser.add_argument("--live-log", default="logs/live_mtf/live_trading.log")
    parser.add_argument("--replay-log", required=True)
    parser.add_argument("--start", required=True, help="UTC start date/time, e.g. 2026-02-18")
    parser.add_argument("--end", required=True, help="UTC end date/time, e.g. 2026-02-20")
    parser.add_argument("--out-dir", default="analysis_outputs")
    args = parser.parse_args()

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")

    live = _parse_log(Path(args.live_log), start, end)
    replay = _parse_log(Path(args.replay_log), start, end)

    merged = live.metrics.add_prefix("live_").join(replay.metrics.add_prefix("replay_"), how="outer")
    merged["close_diff_pips"] = (merged["live_close"] - merged["replay_close"]) * 10000.0
    merged["pred_match"] = merged["live_pred"] == merged["replay_pred"]
    merged["meta_match"] = merged["live_meta"] == merged["replay_meta"]
    merged["excluded_match"] = merged["live_excluded"] == merged["replay_excluded"]

    live_signal_times = set(live.signals.index.tolist())
    replay_signal_times = set(replay.signals.index.tolist())

    common = merged.dropna(subset=["live_close", "replay_close"], how="any")

    print("=" * 80)
    print("LIVE vs REPLAY DECISION PARITY")
    print("=" * 80)
    print(f"Range UTC: {start} -> {end}")
    print(f"Live metric bars: {len(live.metrics)}")
    print(f"Replay metric bars: {len(replay.metrics)}")
    print(f"Common metric bars: {len(common)}")
    print(f"Live-only metric bars: {int(merged['replay_close'].isna().sum())}")
    print(f"Replay-only metric bars: {int(merged['live_close'].isna().sum())}")

    if len(common) > 0:
        close_diff = common["close_diff_pips"].abs()
        print(f"Mean |close diff| pips: {close_diff.mean():.4f}")
        print(f"Max  |close diff| pips: {close_diff.max():.4f}")
        print(f"Pred matches: {int(common['pred_match'].sum())}/{len(common)}")
        print(f"Meta matches: {int(common['meta_match'].sum())}/{len(common)}")
        print(f"Excluded matches: {int(common['excluded_match'].sum())}/{len(common)}")

    print("-" * 80)
    print(f"Live signals: {len(live_signal_times)}")
    print(f"Replay signals: {len(replay_signal_times)}")
    print(f"Common signal bar_times: {len(live_signal_times & replay_signal_times)}")
    print(f"Live-only signal bar_times: {len(live_signal_times - replay_signal_times)}")
    print(f"Replay-only signal bar_times: {len(replay_signal_times - live_signal_times)}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"

    merged.sort_index().to_csv(out_dir / f"live_vs_replay_metrics_{tag}.csv")

    sig_rows = []
    all_sig_times = sorted(live_signal_times | replay_signal_times)
    for ts in all_sig_times:
        sig_rows.append(
            {
                "bar_time": ts,
                "in_live": ts in live_signal_times,
                "in_replay": ts in replay_signal_times,
                "live_side": (live.signals.loc[ts, "side"] if ts in live.signals.index else None),
                "replay_side": (replay.signals.loc[ts, "side"] if ts in replay.signals.index else None),
            }
        )

    pd.DataFrame(sig_rows).sort_values("bar_time").to_csv(out_dir / f"live_vs_replay_signals_{tag}.csv", index=False)
    print(f"Wrote: {out_dir / f'live_vs_replay_metrics_{tag}.csv'}")
    print(f"Wrote: {out_dir / f'live_vs_replay_signals_{tag}.csv'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
