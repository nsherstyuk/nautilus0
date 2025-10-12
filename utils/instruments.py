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


def instrument_id_to_catalog_format(instrument_id: str) -> str:
    """Convert slashed forex IDs to no-slash format for catalog filesystem queries.
    
    Args:
        instrument_id: Instrument ID in format like "EUR/USD.IDEALPRO"
        
    Returns:
        Catalog format like "EURUSD.IDEALPRO" for forex pairs, unchanged for others
        
    Examples:
        EUR/USD.IDEALPRO -> EURUSD.IDEALPRO
        SPY.SMART -> SPY.SMART (unchanged)
    """
    parts = instrument_id.split('.')
    if len(parts) != 2:
        return instrument_id
    
    symbol, venue = parts
    if '/' in symbol:
        # Remove slash for forex pairs
        symbol_no_slash = symbol.replace('/', '')
        return f"{symbol_no_slash}.{venue}"
    
    return instrument_id


def catalog_format_to_instrument_id(catalog_name: str) -> str:
    """Convert no-slash catalog names back to slashed format for display/matching.
    
    Args:
        catalog_name: Catalog name in format like "EURUSD.IDEALPRO"
        
    Returns:
        Slashed format like "EUR/USD.IDEALPRO" for forex pairs, unchanged for others
        
    Examples:
        EURUSD.IDEALPRO -> EUR/USD.IDEALPRO
        SPY.SMART -> SPY.SMART (unchanged)
    """
    parts = catalog_name.split('.')
    if len(parts) != 2:
        return catalog_name
    
    symbol, venue = parts
    # Check if symbol is 6 characters and all uppercase (likely forex pair)
    if len(symbol) == 6 and symbol.isalpha() and symbol.isupper():
        # Validate that both 3-letter parts are valid ISO currency codes
        base_currency = symbol[:3]
        quote_currency = symbol[3:]
        try:
            Currency.from_str(base_currency)
            Currency.from_str(quote_currency)
            # Insert slash at position 3 for forex pairs
            symbol_with_slash = f"{base_currency}/{quote_currency}"
            return f"{symbol_with_slash}.{venue}"
        except Exception:
            # Not valid currency codes, return unchanged
            pass
    
    return catalog_name


def try_both_instrument_formats(instrument_id: str) -> List[str]:
    """Generate both possible formats for fallback queries.
    
    Args:
        instrument_id: Instrument ID in either slashed or no-slash format
        
    Returns:
        List with original format first, then alternative format
        
    Examples:
        EUR/USD.IDEALPRO -> ['EUR/USD.IDEALPRO', 'EURUSD.IDEALPRO']
        EURUSD.IDEALPRO -> ['EURUSD.IDEALPRO', 'EUR/USD.IDEALPRO']
    """
    if '/' in instrument_id:
        # Input has slash, return slashed first, then no-slash
        return [instrument_id, instrument_id_to_catalog_format(instrument_id)]
    else:
        # Input has no slash, return no-slash first, then slashed
        return [instrument_id, catalog_format_to_instrument_id(instrument_id)]
