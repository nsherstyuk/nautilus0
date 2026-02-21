"""
Extend the NautilusTrader parquet data catalog with live bar data saved by the live trading system.

This reads the daily-partitioned live bar CSVs from logs/live_mtf/live_bars/
and writes them into the data/historical catalog as proper NautilusTrader Bar objects,
filling the gap between the existing parquet coverage and today.

Usage:
    python scripts/extend_catalog_with_live_bars.py
    python scripts/extend_catalog_with_live_bars.py --bar-sizes 15m 1m --start 2026-02-19
    python scripts/extend_catalog_with_live_bars.py --dry-run

Notes:
- Only bars AFTER the current catalog end are written (deduplication by timestamp filter).
- Use --force-overwrite to replace all existing data in the extended range.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── constants ──────────────────────────────────────────────────────────────────

LIVE_BAR_SPEC_MAP = {
    "15m": {
        "csv_bar_size": "15 mins",
        "aggregation": BarAggregation.MINUTE,
        "step": 15,
        "price_type": PriceType.MID,
        "filename_pattern": "EUR_USD_15_mins_MIDPOINT_rth0.csv",
    },
    "1m": {
        "csv_bar_size": "1 min",
        "aggregation": BarAggregation.MINUTE,
        "step": 1,
        "price_type": PriceType.MID,
        "filename_pattern": "EUR_USD_1_min_MIDPOINT_rth0.csv",
    },
}

# ── helpers ────────────────────────────────────────────────────────────────────


def _build_instrument() -> CurrencyPair:
    """Build the EURUSD.IDEALPRO CurrencyPair instrument object."""
    instrument_id = InstrumentId(Symbol("EUR/USD"), Venue("IDEALPRO"))
    return CurrencyPair(
        instrument_id=instrument_id,
        raw_symbol=Symbol("EUR/USD"),
        base_currency=Currency.from_str("EUR"),
        quote_currency=Currency.from_str("USD"),
        price_precision=5,
        size_precision=2,
        price_increment=Price.from_str("0.00001"),
        lot_size=Quantity.from_str("1000.00"),
        size_increment=Quantity.from_str("0.01"),
        max_quantity=Quantity.from_str("50000000.00"),
        min_quantity=Quantity.from_str("0.01"),
        margin_init=Decimal("0.03"),
        margin_maint=Decimal("0.02"),
        maker_fee=Decimal("0.00002"),
        taker_fee=Decimal("0.00002"),
        ts_event=0,
        ts_init=0,
    )


def _build_bar_type(instrument: CurrencyPair, step: int, aggregation: BarAggregation, price_type: PriceType) -> BarType:
    spec = BarSpecification(step=step, aggregation=aggregation, price_type=price_type)
    return BarType(
        instrument_id=instrument.id,
        bar_spec=spec,
        aggregation_source=AggregationSource.EXTERNAL,
    )


def _ts_ns(ts: pd.Timestamp) -> int:
    """Convert pandas Timestamp to unix nanoseconds."""
    return int(ts.value)


def _load_live_bar_csvs(live_bar_dir: Path, date_folders: list[str], filename_pattern: str) -> pd.DataFrame:
    """Load and concatenate live bar CSVs for given date folders."""
    frames = []
    for date_str in date_folders:
        csv_path = live_bar_dir / date_str / filename_pattern
        if not csv_path.exists():
            logger.warning("No file: %s", csv_path)
            continue
        df = pd.read_csv(csv_path, parse_dates=["time_utc"])
        # Ensure timezone-aware UTC
        if df["time_utc"].dt.tz is None:
            df["time_utc"] = df["time_utc"].dt.tz_localize("UTC")
        else:
            df["time_utc"] = df["time_utc"].dt.tz_convert("UTC")
        frames.append(df)
        logger.info("Loaded %d rows from %s", len(df), csv_path)

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["time_utc"]).sort_values("time_utc").reset_index(drop=True)
    return combined


def _rows_to_bars(df: pd.DataFrame, bar_type: BarType) -> list[Bar]:
    """Convert DataFrame rows to NautilusTrader Bar objects."""
    bars = []
    for _, row in df.iterrows():
        ts = row["time_utc"]
        ts_ns = _ts_ns(ts)
        try:
            bar = Bar(
                bar_type=bar_type,
                open=Price.from_str(f"{float(row['open']):.5f}"),
                high=Price.from_str(f"{float(row['high']):.5f}"),
                low=Price.from_str(f"{float(row['low']):.5f}"),
                close=Price.from_str(f"{float(row['close']):.5f}"),
                volume=Quantity.from_str("0.00"),
                ts_event=ts_ns,
                ts_init=ts_ns,
            )
            bars.append(bar)
        except Exception as exc:
            logger.warning("Skipping row %s: %s", ts, exc)
    return bars


def _get_catalog_max_ts(catalog: ParquetDataCatalog, bar_type: BarType) -> pd.Timestamp | None:
    """Query the catalog for the latest ts_event for the given bar_type."""
    try:
        bars = catalog.bars(
            bar_types=[str(bar_type)],
        )
        if bars is None or len(bars) == 0:
            return None
        # bars returns a DataFrame with ts_event in nanoseconds index or column
        if isinstance(bars, pd.DataFrame):
            if "ts_event" in bars.columns:
                max_ns = bars["ts_event"].max()
            else:
                max_ns = bars.index.max()
            return pd.Timestamp(max_ns, tz="UTC")
        # pyarrow table
        import pyarrow as pa  # type: ignore
        if hasattr(bars, "column"):
            ts_col = bars.column("ts_event")
            max_ns = ts_col.to_pylist()[-1]
            return pd.Timestamp(max_ns, tz="UTC")
    except Exception as exc:
        logger.warning("Could not determine catalog max ts: %s", exc)
    return None


def _get_catalog_end_from_filenames(catalog_path: Path, bar_type_str: str) -> pd.Timestamp | None:
    """Infer catalog end timestamp from parquet filename conventions."""
    bar_dir = catalog_path / "data" / "bar" / bar_type_str.replace("/", "-").replace("|", "-").replace(" ", "-")
    # NautilusTrader uses format: EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL
    # Map bar_type_str to directory name
    # bar_type_str example: "EURUSD.IDEALPRO|15-MINUTE-MID[EXTERNAL]"
    # directory: EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL
    pass


def _find_bar_dataset_dir(catalog_path: Path, instrument_id_part: str, bar_spec_part: str) -> Path | None:
    """Find the dataset directory under data/bar/ for this bar type."""
    bar_root = catalog_path / "data" / "bar"
    if not bar_root.exists():
        return None
    prefix = f"{instrument_id_part}-{bar_spec_part}"
    for d in bar_root.iterdir():
        if d.is_dir() and d.name == prefix:
            return d
    return None


def get_catalog_end_ts(catalog_dir: Path, instrument_dot: str, bar_spec_str: str) -> pd.Timestamp | None:
    """
    Read the latest timestamp from the parquet filenames for this bar type.
    Parquet files are named like:
        <start>_<end>.parquet  (UTC nanosecond timestamps in filename)
    Returns the latest end timestamp found.
    """
    dataset_dir = catalog_dir / "data" / "bar" / f"{instrument_dot}-{bar_spec_str}"
    if not dataset_dir.exists():
        logger.warning("Dataset dir not found: %s", dataset_dir)
        return None

    max_ts = None
    for pfile in dataset_dir.glob("*.parquet"):
        # filename format: 2026-02-05T22-30-00-000000000Z_2026-02-19T05-00-00-000000000Z.parquet
        parts = pfile.stem.split("_")
        if len(parts) < 2:
            continue
        end_str = parts[-1]  # e.g. 2026-02-19T05-00-00-000000000Z
        # Convert to ISO format: replace last hyphen-separated groups
        # Format: YYYY-MM-DDTHH-MM-SS-nnnnnnnnnZ  → YYYY-MM-DDTHH:MM:SS.nnnnnnnnnZ
        try:
            # Replace all hyphens after the T
            date_part, time_part = end_str.split("T")
            time_part = time_part.rstrip("Z")
            hms, ns = time_part.rsplit("-", 1)
            hms = hms.replace("-", ":")
            iso = f"{date_part}T{hms}.{ns.zfill(9)}+00:00"
            ts = pd.Timestamp(iso)
            if max_ts is None or ts > max_ts:
                max_ts = ts
        except Exception:
            continue
    return max_ts


# ── main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Extend NautilusTrader catalog with recent live bar data.")
    parser.add_argument(
        "--bar-sizes",
        nargs="+",
        choices=list(LIVE_BAR_SPEC_MAP.keys()),
        default=["15m", "1m"],
        help="Bar sizes to extend (default: 15m 1m)",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Earliest date folder to consider (YYYY-MM-DD). Defaults to 7 days ago.",
    )
    parser.add_argument(
        "--catalog-dir",
        default=str(PROJECT_ROOT / "data" / "historical"),
        help="Path to NautilusTrader parquet catalog directory.",
    )
    parser.add_argument(
        "--live-bar-dir",
        default=str(PROJECT_ROOT / "logs" / "live_mtf" / "live_bars"),
        help="Path to live bar CSV root directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without actually writing.",
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Write all bars from --start even if they overlap with existing catalog data.",
    )
    args = parser.parse_args()

    catalog_dir = Path(args.catalog_dir)
    live_bar_dir = Path(args.live_bar_dir)

    if not live_bar_dir.exists():
        logger.error("Live bar directory not found: %s", live_bar_dir)
        sys.exit(1)

    # Determine date folders to scan
    if args.start:
        start_date = pd.Timestamp(args.start, tz="UTC")
    else:
        start_date = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=7)

    # List all daily folders >= start_date
    date_folders = sorted(
        [
            d.name
            for d in live_bar_dir.iterdir()
            if d.is_dir() and pd.Timestamp(d.name, tz="UTC") >= start_date
        ]
    )
    logger.info("Date folders to process: %s", date_folders)
    if not date_folders:
        logger.warning("No date folders found after %s", start_date.date())
        sys.exit(0)

    # Build instrument
    instrument = _build_instrument()
    catalog = ParquetDataCatalog(str(catalog_dir))

    for bar_size_key in args.bar_sizes:
        spec_meta = LIVE_BAR_SPEC_MAP[bar_size_key]
        bar_type = _build_bar_type(
            instrument,
            step=spec_meta["step"],
            aggregation=spec_meta["aggregation"],
            price_type=spec_meta["price_type"],
        )

        # Determine catalog end time
        # Map bar_type to dataset dir name, e.g. EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL
        instrument_dot = "EURUSD.IDEALPRO"
        bar_spec_str = f"{spec_meta['step']}-MINUTE-MID-EXTERNAL"
        catalog_end_ts = get_catalog_end_ts(catalog_dir, instrument_dot, bar_spec_str)

        if catalog_end_ts is not None:
            logger.info("[%s] Catalog end timestamp: %s", bar_size_key, catalog_end_ts)
        else:
            logger.info("[%s] No existing catalog data found — will write all loaded bars.", bar_size_key)

        # Load live bar CSVs
        df = _load_live_bar_csvs(live_bar_dir, date_folders, spec_meta["filename_pattern"])
        if df.empty:
            logger.info("[%s] No live bar data found.", bar_size_key)
            continue

        logger.info("[%s] Loaded %d total rows from live bar CSVs.", bar_size_key, len(df))

        # Filter to only NEW bars (after catalog end)
        if catalog_end_ts is not None and not args.force_overwrite:
            new_df = df[df["time_utc"] > catalog_end_ts].copy()
            logger.info(
                "[%s] Filtering bars > %s: %d new bars (from %d total)",
                bar_size_key,
                catalog_end_ts,
                len(new_df),
                len(df),
            )
        else:
            new_df = df.copy()

        if new_df.empty:
            logger.info("[%s] No new bars to write (catalog already up to date).", bar_size_key)
            continue

        logger.info(
            "[%s] New bars: %s → %s",
            bar_size_key,
            new_df["time_utc"].min(),
            new_df["time_utc"].max(),
        )

        if args.dry_run:
            logger.info("[%s] DRY RUN — would write %d bars.", bar_size_key, len(new_df))
            continue

        # Convert to Bar objects
        bars = _rows_to_bars(new_df, bar_type)
        logger.info("[%s] Converted %d bars.", bar_size_key, len(bars))

        # Ensure instrument is registered
        try:
            catalog.write_data([instrument])
        except Exception:
            pass

        # Write bars
        try:
            catalog.write_data(bars, skip_disjoint_check=False)
            logger.info("[%s] Successfully wrote %d bars to catalog.", bar_size_key, len(bars))
        except AssertionError as exc:
            if "Intervals are not disjoint" in str(exc):
                logger.warning("[%s] Interval conflict — retrying with skip_disjoint_check=True", bar_size_key)
                catalog.write_data(bars, skip_disjoint_check=True)
                logger.info("[%s] Wrote %d bars (skip_disjoint_check=True).", bar_size_key, len(bars))
            else:
                raise

    logger.info("Done.")


if __name__ == "__main__":
    main()
