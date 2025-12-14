import argparse
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog


def _load_env_files() -> None:
    env_candidates = [".env", ".env.mtf_v2"]
    for name in env_candidates:
        p = Path(name)
        if p.exists():
            load_dotenv(dotenv_path=p, override=False)


def _parse_date_range(start_date: str, end_date: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(start_date).tz_localize("UTC")
    end = pd.Timestamp(end_date).tz_localize("UTC") + pd.Timedelta(days=1)
    return start, end


def _normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").upper()


def _default_bar_type_for_symbol(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    return f"{normalized}.IDEALPRO-15-MINUTE-MID-EXTERNAL"


def _load_catalog_closes(catalog_path: Path, bar_type: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    catalog = ParquetDataCatalog(str(catalog_path))
    bars = catalog.bars(bar_types=[bar_type])
    if len(bars) == 0:
        raise FileNotFoundError(f"No bars found in catalog for bar_type={bar_type}")

    df = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp(b.ts_init, unit="ns", tz="UTC") for b in bars],
            "open_cat": [float(b.open) for b in bars],
            "close_cat": [float(b.close) for b in bars],
        }
    )
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)
    df = df.loc[~df.index.duplicated(keep="first")]
    return df.loc[(df.index >= start) & (df.index < end)].copy()


_BAR_RE = re.compile(r"\[BAR\]\s+(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\+\d{2}:\d{2})\s+close=(?P<close>[0-9.]+)")


def _parse_strategy_log_closes(log_path: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _BAR_RE.search(line)
            if not m:
                continue

            ts = pd.Timestamp(m.group("ts"))
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")

            if ts < start or ts >= end:
                continue

            rows.append({"timestamp": ts, "close_live": float(m.group("close"))})

    if not rows:
        return pd.DataFrame(columns=["close_live"]).astype(float)

    df = pd.DataFrame(rows)
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)

    df = df.loc[~df.index.duplicated(keep="first")]
    return df


def _score_shift(df_live: pd.DataFrame, df_cat: pd.DataFrame, shift_minutes: int) -> tuple[float, int, int]:
    shifted = df_live.copy()
    shifted.index = shifted.index + pd.Timedelta(minutes=shift_minutes)

    merged = shifted.join(df_cat, how="inner")
    if len(merged) == 0:
        return float("inf"), 0, 0

    diff_pips = (merged["close_live"] - merged["close_cat"]).abs() * 10000.0
    mismatches = int((diff_pips > 2.0).sum())
    return float(diff_pips.mean()), int(len(merged)), mismatches


def _scan_shifts(df_live: pd.DataFrame, df_cat: pd.DataFrame, tolerance_pips: float) -> list[dict]:
    rows = []
    for shift in range(-16, 17):
        shift_minutes = shift * 15
        shifted = df_live.copy()
        shifted.index = shifted.index + pd.Timedelta(minutes=shift_minutes)
        merged = shifted.join(df_cat, how="inner")
        if len(merged) == 0:
            continue
        diff_pips = (merged["close_live"] - merged["close_cat"]).abs() * 10000.0
        rows.append(
            {
                "shift_minutes": shift_minutes,
                "overlap": int(len(merged)),
                "mean_abs_pips": float(diff_pips.mean()),
                "mismatches": int((diff_pips > tolerance_pips).sum()),
            }
        )

    return sorted(rows, key=lambda r: (r["mean_abs_pips"], r["mismatches"], -r["overlap"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default=str(Path("logs") / "live_mtf" / "strategy.log"))
    parser.add_argument("--symbol", default="EUR/USD")
    parser.add_argument("--start", default="2025-12-08")
    parser.add_argument("--end", default="2025-12-12")
    parser.add_argument("--bar-type", default=None)
    parser.add_argument("--catalog", default=str(Path("data") / "historical"))
    parser.add_argument("--tolerance-pips", type=float, default=2.0)
    parser.add_argument("--scan-shifts", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    _load_env_files()

    start, end = _parse_date_range(args.start, args.end)
    log_path = Path(args.log)
    bar_type = args.bar_type or _default_bar_type_for_symbol(args.symbol)

    df_live = _parse_strategy_log_closes(log_path, start, end)
    df_cat = _load_catalog_closes(Path(args.catalog), bar_type, start, end)

    if df_live.empty:
        raise FileNotFoundError(f"No [BAR] lines parsed from {log_path} for range {start}..{end}")

    scan = _scan_shifts(df_live, df_cat, float(args.tolerance_pips))
    if args.scan_shifts:
        print("Shift scan (sorted best to worst):")
        for r in scan[:10]:
            print(
                f"shift={r['shift_minutes']:>4} min  overlap={r['overlap']:>4}  mean_abs_pips={r['mean_abs_pips']:.4f}  mismatches={r['mismatches']}"
            )
        print("(Showing top 10)\n")

    best = None
    for r in scan:
        if r["overlap"] < 10:
            continue
        key = (r["mean_abs_pips"], r["mismatches"], -r["overlap"])
        best = (key, r["shift_minutes"], r["mean_abs_pips"], r["overlap"], r["mismatches"])
        break

    if best is None:
        best_shift_minutes = 0
        best_mean_abs_pips, best_overlap, best_mismatches = float("inf"), 0, 0
    else:
        _, best_shift_minutes, best_mean_abs_pips, best_overlap, best_mismatches = best

    aligned = df_live.copy()
    aligned.index = aligned.index + pd.Timedelta(minutes=best_shift_minutes)

    merged = aligned.join(df_cat, how="outer")
    merged["close_diff_pips"] = (merged["close_live"] - merged["close_cat"]) * 10000.0
    merged["abs_close_diff_pips"] = merged["close_diff_pips"].abs()
    merged["open_diff_pips"] = (merged["close_live"] - merged["open_cat"]) * 10000.0
    merged["abs_open_diff_pips"] = merged["open_diff_pips"].abs()

    overlap_mask = merged["close_live"].notna() & merged["close_cat"].notna()
    mismatch_mask = overlap_mask & (merged["abs_close_diff_pips"] > float(args.tolerance_pips))

    print("Live strategy.log vs Parquet catalog bar comparison")
    print(f"Log: {log_path}")
    print(f"Symbol: {args.symbol}")
    print(f"Range UTC: {start} to {end} (end exclusive)")
    print(f"Bar type: {bar_type}")
    print(f"Live rows parsed: {len(df_live)}  Catalog rows: {len(df_cat)}")
    print(f"Best alignment shift: {best_shift_minutes} minutes")
    print(f"Overlap rows: {int(overlap_mask.sum())}")
    print(f"Mean abs close diff (best alignment): {best_mean_abs_pips:.4f} pips")
    print(f"Tolerance: {args.tolerance_pips} pips")
    print(f"Mismatches: {int(mismatch_mask.sum())} / {int(overlap_mask.sum())}")
    if int(overlap_mask.sum()) > 0:
        mean_abs_open_pips = float(merged.loc[overlap_mask, "abs_open_diff_pips"].mean())
        print(f"Mean abs (live_close - catalog_open): {mean_abs_open_pips:.4f} pips")

    if int(mismatch_mask.sum()) > 0:
        sample = merged.loc[
            mismatch_mask,
            [
                "close_live",
                "open_cat",
                "close_cat",
                "open_diff_pips",
                "close_diff_pips",
            ],
        ].head(30)
        print("Sample mismatches (first 30):")
        print(sample.to_string())

    out_path = args.out
    if out_path is None:
        safe_symbol = _normalize_symbol(args.symbol)
        out_dir = Path("analysis_outputs")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(out_dir / f"log_bar_compare_{safe_symbol}_{args.start}_{args.end}.csv")

    merged.sort_index(inplace=True)
    merged.to_csv(out_path, index=True)
    print(f"Wrote merged comparison CSV: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
