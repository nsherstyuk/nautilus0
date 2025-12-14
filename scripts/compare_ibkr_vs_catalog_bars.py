import argparse
import os
from datetime import datetime
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from ib_insync import IB, Forex
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


def _load_catalog_bars(catalog_path: Path, bar_type: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    catalog = ParquetDataCatalog(str(catalog_path))
    bars = catalog.bars(bar_types=[bar_type])
    if len(bars) == 0:
        raise FileNotFoundError(f"No bars found in catalog for bar_type={bar_type}")

    df = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp(b.ts_init, unit="ns", tz="UTC") for b in bars],
            "open": [float(b.open) for b in bars],
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
            "volume": [float(b.volume) for b in bars],
        }
    )
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)

    return df.loc[(df.index >= start) & (df.index < end)].copy()


def _fetch_ibkr_bars(
    symbol: str,
    host: str,
    port: int,
    client_id: int,
    start: pd.Timestamp,
    end: pd.Timestamp,
    bar_size: str,
    what_to_show: str,
    use_rth: bool,
) -> pd.DataFrame:
    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=20)
    try:
        normalized = _normalize_symbol(symbol)
        contract = Forex(normalized)
        ib.qualifyContracts(contract)

        duration_days = max(1, int(ceil((end - start).total_seconds() / 86400.0)))
        end_str = end.tz_convert("UTC").strftime("%Y%m%d %H:%M:%S")

        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end_str,
            durationStr=f"{duration_days} D",
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=use_rth,
            formatDate=1,
            keepUpToDate=False,
        )

        rows = []
        for b in bars:
            ts = pd.Timestamp(b.date)
            rows.append(
                {
                    "timestamp": ts,
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(getattr(b, "volume", 0.0) or 0.0),
                }
            )

        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]).astype(float)

        df = pd.DataFrame(rows)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df
    finally:
        ib.disconnect()


def _score_alignment(
    df_ib: pd.DataFrame,
    df_cat: pd.DataFrame,
    shift_minutes: int,
) -> tuple[float, int]:
    shifted = df_ib.copy()
    shifted.index = shifted.index + pd.Timedelta(minutes=shift_minutes)

    merged = shifted[["open", "high", "low", "close"]].join(
        df_cat[["open", "high", "low", "close"]],
        how="inner",
        lsuffix="_ib",
        rsuffix="_cat",
    )

    if len(merged) == 0:
        return float("inf"), 0

    diff_pips = (merged["close_ib"] - merged["close_cat"]).abs() * 10000.0
    return float(diff_pips.mean()), int(len(merged))


def _choose_best_alignment(df_ib_base: pd.DataFrame, df_cat: pd.DataFrame) -> tuple[pd.DataFrame, str, int, float, int]:
    candidates: list[tuple[str, pd.DataFrame]] = []

    if getattr(df_ib_base.index, "tz", None) is None:
        df_utc = df_ib_base.copy()
        df_utc.index = df_utc.index.tz_localize("UTC")
        candidates.append(("UTC", df_utc))

        df_ny = df_ib_base.copy()
        df_ny.index = df_ny.index.tz_localize("America/New_York").tz_convert("UTC")
        candidates.append(("America/New_York", df_ny))
    else:
        candidates.append((str(df_ib_base.index.tz), df_ib_base.tz_convert("UTC")))

    best = None
    for tz_name, df_ib in candidates:
        for shift in range(-16, 17):
            shift_minutes = shift * 15
            mean_abs_pips, overlap = _score_alignment(df_ib, df_cat, shift_minutes)
            if overlap < 10:
                continue
            key = (mean_abs_pips, -overlap)
            if best is None or key < best[0]:
                best = (key, tz_name, shift_minutes, mean_abs_pips, overlap, df_ib)

    if best is None:
        tz_name, df_ib = candidates[0]
        return df_ib, tz_name, 0, float("inf"), 0

    _, tz_name, shift_minutes, mean_abs_pips, overlap, df_ib = best
    aligned = df_ib.copy()
    aligned.index = aligned.index + pd.Timedelta(minutes=shift_minutes)
    return aligned, tz_name, shift_minutes, mean_abs_pips, overlap


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="EUR/USD")
    parser.add_argument("--start", default="2025-12-08")
    parser.add_argument("--end", default="2025-12-12")
    parser.add_argument("--bar-type", default=None)
    parser.add_argument("--catalog", default=str(Path("data") / "historical"))
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--client-id", type=int, default=110)
    parser.add_argument("--bar-size", default="15 mins")
    parser.add_argument("--what-to-show", default="MIDPOINT")
    parser.add_argument("--tolerance-pips", type=float, default=2.0)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    _load_env_files()

    start, end = _parse_date_range(args.start, args.end)

    host = args.host or os.getenv("IB_HOST", "127.0.0.1")
    port = args.port or int(os.getenv("IB_PORT", "7497"))

    bar_type = args.bar_type or _default_bar_type_for_symbol(args.symbol)

    catalog_path = Path(args.catalog)
    df_cat = _load_catalog_bars(catalog_path, bar_type, start, end)

    df_ib_raw = _fetch_ibkr_bars(
        symbol=args.symbol,
        host=host,
        port=port,
        client_id=args.client_id,
        start=start,
        end=end,
        bar_size=args.bar_size,
        what_to_show=args.what_to_show,
        use_rth=False,
    )

    df_ib_aligned, tz_used, shift_minutes, mean_abs_pips, overlap = _choose_best_alignment(df_ib_raw, df_cat)

    merged = df_ib_aligned[["open", "high", "low", "close", "volume"]].join(
        df_cat[["open", "high", "low", "close", "volume"]],
        how="outer",
        lsuffix="_ib",
        rsuffix="_cat",
    )

    merged["close_diff_pips"] = (merged["close_ib"] - merged["close_cat"]) * 10000.0
    merged["abs_close_diff_pips"] = merged["close_diff_pips"].abs()

    overlap_mask = merged["close_ib"].notna() & merged["close_cat"].notna()
    overlap_count = int(overlap_mask.sum())

    mismatch_mask = overlap_mask & (merged["abs_close_diff_pips"] > float(args.tolerance_pips))
    mismatch_count = int(mismatch_mask.sum())

    print("IBKR vs Catalog bar comparison")
    print(f"Symbol: {args.symbol}")
    print(f"Range UTC: {start} to {end} (end exclusive)")
    print(f"Catalog: {catalog_path}")
    print(f"Bar type: {bar_type}")
    print(f"IB host: {host}:{port} client_id={args.client_id}")
    print(f"IB interpretation: tz={tz_used} shift_minutes={shift_minutes}")
    print(f"IB rows: {len(df_ib_raw)}  Catalog rows: {len(df_cat)}  Overlap rows: {overlap_count}")
    print(f"Mean abs close diff (best alignment): {mean_abs_pips:.4f} pips over {overlap} rows")
    print(f"Tolerance: {args.tolerance_pips} pips")
    print(f"Mismatches: {mismatch_count} / {overlap_count}")

    if mismatch_count > 0:
        sample = merged.loc[mismatch_mask, ["close_ib", "close_cat", "close_diff_pips"]].head(20)
        print("Sample mismatches (first 20):")
        print(sample.to_string())

    out_path = args.out
    if out_path is None:
        safe_symbol = _normalize_symbol(args.symbol)
        out_dir = Path("analysis_outputs")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(out_dir / f"bar_compare_{safe_symbol}_{args.start}_{args.end}.csv")

    merged.sort_index(inplace=True)
    merged.to_csv(out_path, index=True)
    print(f"Wrote merged comparison CSV: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
