from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

from nautilus_trader.model.objects import Currency


def validate_instrument_id_match(expected_id: str, actual_id: str, context: str) -> bool:
    """Return True when instrument IDs match; log mismatch with context."""
    if expected_id == actual_id:
        return True
    logging.warning(
        "Instrument ID mismatch detected (%s): expected=%s actual=%s",
        context,
        expected_id,
        actual_id,
    )
    return False


def log_instrument_metadata(instrument, source: str, logger: logging.Logger) -> None:
    """Emit diagnostic logging for an instrument or identifier."""
    try:
        instrument_id = getattr(instrument, "id", instrument)
        symbol_value = getattr(instrument, "symbol", getattr(instrument, "raw_symbol", None))
        logger.info(
            "%s instrument metadata: id=%s raw_symbol=%s type=%s",
            source,
            instrument_id,
            symbol_value if symbol_value is not None else "<unknown>",
            instrument.__class__.__name__,
        )
    except Exception as exc:  # pragma: no cover - logging helper should not raise
        logger.warning("Failed to log instrument metadata for %s: %s", source, exc)


def validate_catalog_dataset_exists(
    catalog_path: Path,
    instrument_id: str,
    bar_spec: str,
    logger: logging.Logger,
) -> bool:
    """Verify dataset directory exists for instrument/bar_spec combination."""
    bar_root = Path(catalog_path) / "data" / "bar"
    dataset_name = f"{instrument_id}-{bar_spec}"
    target_rel_path = Path(*dataset_name.split("/"))
    dataset_dir = bar_root / target_rel_path

    if dataset_dir.exists():
        logger.info("Catalog dataset present: %s", dataset_dir)
        return True

    for candidate in bar_root.rglob("*.parquet"):
        try:
            rel = candidate.parent.relative_to(bar_root)
        except ValueError:
            continue
        if rel.as_posix() == dataset_name:
            logger.info("Catalog dataset present: %s", candidate.parent)
            return True

    logger.warning("Catalog dataset missing: %s", dataset_name)
    return False


def format_instrument_diagnostic(
    instrument_id: str,
    bar_spec: str,
    available_datasets: List[str],
) -> str:
    """Produce human-readable diagnostic string for missing datasets."""
    lines = [
        f"Requested dataset: {instrument_id}-{bar_spec}",
        "Available datasets:",
    ]
    lines.extend(f"  - {dataset}" for dataset in available_datasets)
    return "\n".join(lines)


def parse_fx_symbol(symbol: str) -> Tuple[str, str]:
    """Split a forex symbol into BASE/QUOTE components and validate ISO codes."""
    parts = [p.strip().upper() for p in symbol.split('/')]
    if (
        len(parts) != 2
        or any(len(p) != 3 for p in parts)
        or any(not p.isalpha() for p in parts)
    ):
        raise ValueError(
            f"Invalid forex symbol format: {symbol}. Expected BASE/QUOTE currency pair (e.g. EUR/USD)"
        )

    base, quote = parts
    try:
        Currency.from_str(base)
        Currency.from_str(quote)
    except Exception as exc:
        raise ValueError(
            f"Invalid currency code in forex symbol: {symbol}. Expected ISO codes like EUR/USD"
        ) from exc

    return base, quote


def normalize_instrument_id(symbol: str, venue: str) -> str:
    """Normalize instrument ID; forex pairs retain the slash (e.g., EUR/USD.IDEALPRO)."""
    venue = venue.strip().upper()
    if '/' in symbol:
        base, quote = parse_fx_symbol(symbol)
        normalized_symbol = f"{base}/{quote}"
    else:
        normalized_symbol = symbol.strip().upper()

    return f"{normalized_symbol}.{venue}"
