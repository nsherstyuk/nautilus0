"""
Historical data ingestion script for Interactive Brokers.

Purpose: Download historical market data from Interactive Brokers
Supports: Stocks (e.g., SPY) and ISO 4217 forex pairs (e.g., EUR/USD)
Requirements: TWS or IB Gateway must be running, .env file must be configured
Note: Metals/crypto pairs with slashes (e.g., XAU/USD, BTC/USD) are not supported
      via the CASH/IDEALPRO pathway enforced by this script.
Usage: python data/ingest_historical.py
Output: Parquet and CSV files in data/historical/ directory

Environment variables required:
- IB_HOST: IBKR host address
- IB_PORT: IBKR port number  
- IB_CLIENT_ID: Client identifier
- DATA_SYMBOLS: Comma-separated list of symbols (stocks or ISO currency pairs)
- DATA_START_DATE: Start date in YYYY-MM-DD format
- DATA_END_DATE: End date in YYYY-MM-DD format
"""

import asyncio
import datetime
import logging
import logging.config
import inspect
import logging.handlers  # ✅ FIXED: Added missing import
import os
import shutil
import sys
from decimal import Decimal
from pathlib import Path

import nautilus_trader
import pandas as pd
import yaml

from nautilus_trader.adapters.interactive_brokers.historical.client import HistoricInteractiveBrokersClient
from nautilus_trader.adapters.interactive_brokers.common import IBContract
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.model.data import BarSpecification, BarAggregation  # Requires NautilusTrader >= 1.220.0
from nautilus_trader.model.enums import AggregationSource, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import Equity, CurrencyPair
from nautilus_trader.model.objects import Currency, Price, Quantity

from config import get_ibkr_config, get_market_data_type_enum
from utils.instruments import (
    parse_fx_symbol,
    normalize_instrument_id,
    validate_instrument_id_match,
    log_instrument_metadata,
    validate_catalog_dataset_exists,
)

def create_bar_specification(step: int, aggregation: str, price_type: str) -> BarSpecification:
    """Create a BarSpecification object programmatically."""
    try:
        agg_enum = BarAggregation[aggregation.upper()]
        price_enum = PriceType[price_type.upper()]
        return BarSpecification(
            step=step,
            aggregation=agg_enum,
            price_type=price_enum,
        )
    except KeyError as e:
        valid_aggs = [a.name for a in BarAggregation]
        valid_prices = [p.name for p in PriceType]
        raise ValueError(
            f"Invalid bar specification parameter: {e}. "
            f"Valid aggregations: {valid_aggs}. Valid price types: {valid_prices}."
        ) from e


def validate_bar_specification_string(bar_spec: str) -> bool:
    """Validate that a bar specification string matches STEP-AGGREGATION-PRICE format."""
    parts = bar_spec.split('-')
    if len(parts) not in {3, 4}:
        logging.warning(
            "Invalid bar specification format: '%s'. Expected format: {step}-{aggregation}-{price_type}.",
            bar_spec,
        )
        return False

    step = parts[0]
    aggregation = parts[1]
    price_type = parts[2]
    source = parts[3] if len(parts) == 4 else None

    try:
        step_int = int(step)
        if step_int < 1:
            logging.warning("Invalid bar specification step (must be >=1): %s", bar_spec)
            return False
    except ValueError:
        logging.warning("Invalid bar specification step (must be integer): %s", bar_spec)
        return False

    if aggregation.upper() not in [a.name for a in BarAggregation]:
        logging.warning("Invalid bar aggregation '%s' in spec '%s'", aggregation, bar_spec)
        return False

    if price_type.upper() not in [p.name for p in PriceType]:
        logging.warning("Invalid price type '%s' in spec '%s'", price_type, bar_spec)
        return False

    if source is not None and source.upper() not in [s.name for s in AggregationSource]:
        logging.warning("Invalid aggregation source '%s' in spec '%s'", source, bar_spec)
        return False

    return True


def create_instrument(symbol: str, venue: str = "SMART"):
    venue = venue.strip().upper()
    instrument_id = InstrumentId.from_str(normalize_instrument_id(symbol, venue))

    if "/" in symbol:
        base, quote = parse_fx_symbol(symbol)
        return CurrencyPair(
            instrument_id=instrument_id,
            raw_symbol=Symbol(f"{base}/{quote}"),
            base_currency=Currency.from_str(base),
            quote_currency=Currency.from_str(quote),
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
    else:
        return Equity(
            instrument_id=instrument_id,
            raw_symbol=Symbol(symbol),
            currency=Currency.from_str("USD"),
            price_precision=2,
            price_increment=Price.from_str("0.01"),
            lot_size=Quantity.from_int(1),
            ts_event=0,
            ts_init=0,
        )


def setup_logging() -> logging.Logger:
    """
    Setup logging configuration from config/logging.yaml.
    
    Returns:
        logging.Logger: Configured logger instance for this module
    """
    # Construct path to logging config relative to project root
    config_path = Path(__file__).parent.parent / "config" / "logging.yaml"
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        logging.config.dictConfig(config)
        return logging.getLogger(__name__)
    except Exception as e:
        # Fallback: configure logging from environment variables
        # Read LOG_LEVEL and LOG_DIR from environment
        level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)
        log_dir = os.getenv("LOG_DIR", "logs")

        # Ensure log directory exists
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        # Create root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        # Clear existing handlers to avoid duplicates
        for h in list(root_logger.handlers):
            root_logger.removeHandler(h)

        # Formatter
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # File handler (rotating)
        file_path = Path(log_dir) / "application.log"
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(file_path), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)  # Capture detailed logs in file
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to load logging config from {config_path}: {e}. Using env-based logging (LOG_LEVEL={level_str}, LOG_DIR={log_dir}).")
        return logger


async def validate_connection(client: HistoricInteractiveBrokersClient, max_retries: int = 3) -> bool:
    """
    Validate connection to IBKR.
    
    Args:
        client: IBKR historical client instance
        
    Returns:
        bool: True if connected successfully, False otherwise
    """
    delay_seconds = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            logging.info("Attempting IBKR connection (%s/%s)...", attempt, max_retries)
            await client.connect()
            # Wait briefly to ensure connection is established
            await asyncio.sleep(2)
            logging.info("IBKR connection established on attempt %s.", attempt)
            return True
        except ConnectionRefusedError as e:
            logging.error(
                "Cannot connect to IBKR (attempt %s/%s). Ensure TWS or IB Gateway is running, API access is enabled, "
                "and host/port are correct. Error: %s",
                attempt,
                max_retries,
                e,
            )
        except TimeoutError as e:
            logging.error(
                "Connection to IBKR timed out (attempt %s/%s). Verify TWS/Gateway responsiveness and firewall settings. Error: %s",
                attempt,
                max_retries,
                e,
            )
        except Exception as e:
            logging.error(
                "Unexpected error during IBKR connection attempt %s/%s: %s",
                attempt,
                max_retries,
                e,
            )

        if attempt < max_retries:
            logging.info("Retrying IBKR connection in %.1f seconds...", delay_seconds)
            await asyncio.sleep(delay_seconds)
            delay_seconds *= 2

    logging.error(
        "Failed to connect to IBKR after %s attempts. Confirm TWS/IB Gateway is running, API sockets are enabled, "
        "and ports match .env configuration.",
        max_retries,
    )
    return False


async def download_historical_data(symbol: str, start_date: datetime.datetime, end_date: datetime.datetime, config) -> list:
    """Download historical bars from IBKR via NautilusTrader client."""
    logger = logging.getLogger(__name__)
    # Detect forex pairs (e.g., "EUR/USD") vs stocks (e.g., "SPY")
    is_forex = "/" in symbol
    if is_forex:
        # Forex pair: create CASH contract for IDEALPRO
        base_currency, quote_currency = parse_fx_symbol(symbol)
        contract = IBContract(
            secType="CASH",              # Forex uses CASH security type
            symbol=base_currency,         # Base currency (e.g., "EUR")
            currency=quote_currency,      # Quote currency (e.g., "USD")
            exchange="IDEALPRO"           # IBKR's institutional forex venue
        )
        logger.info("Created CASH contract for forex pair: %s on IDEALPRO", symbol)
    else:
        # Stock: create STK contract for SMART routing
        contract = IBContract(
            secType="STK",
            symbol=symbol,
            exchange="SMART",
            primaryExchange="ARCA",
            currency="USD"
        )
        logger.info("Created STK contract for stock: %s on SMART", symbol)
    
    # Initialize IBKR historical client
    client = HistoricInteractiveBrokersClient(
        host=config.host,
        port=config.port,
        client_id=config.client_id,
        market_data_type=get_market_data_type_enum(config.market_data_type)
    )
    
    try:
        # Validate connection
        if not await validate_connection(client):
            logger.error(f"Cannot connect to IBKR at {config.host}:{config.port}. Ensure TWS or IB Gateway is running and API access is enabled.")
            return []
        logger.info(f"Successfully connected to IBKR at {config.host}:{config.port}")
        logger.info(
            "NautilusTrader version: %s",
            getattr(nautilus_trader, "__version__", "unknown"),
        )
        logger.info("Processing symbol: %s (forex=%s)", symbol, is_forex)

        # Define bar specifications using programmatic creation to avoid parsing issues
        logger.info(
            "Creating bar specifications for %s instrument",
            "forex" if is_forex else "equity",
        )

        if is_forex:
            bar_specs_config = [
                (15, "MINUTE", "MID"),  # 15-minute bars for backtesting
                (1, "DAY", "MID"),
            ]
        else:
            bar_specs_config = [
                (1, "MINUTE", "LAST"),
                (1, "DAY", "LAST"),
            ]

        bar_specifications: list[str] = []
        bar_spec_objects: list[BarSpecification] = []
        for step, aggregation, price_type in bar_specs_config:
            try:
                bar_spec_obj = create_bar_specification(step, aggregation, price_type)
                bar_spec_str = str(bar_spec_obj)
                if validate_bar_specification_string(bar_spec_str):
                    bar_specifications.append(bar_spec_str)
                    bar_spec_objects.append(bar_spec_obj)
                    logger.info("Prepared bar specification: %s", bar_spec_str)
                else:
                    logger.error("Generated invalid bar specification: %s", bar_spec_str)
            except Exception as spec_error:
                logger.error(
                    "Failed to create bar specification (%s-%s-%s): %s",
                    step,
                    aggregation,
                    price_type,
                    spec_error,
                    exc_info=True,
                )

        if not bar_specifications:
            logger.error("No valid bar specifications generated for %s; aborting request.", symbol)
            return []

        logger.info("Final bar specifications: %s", bar_specifications)

        # Request historical bars with enhanced error handling
        logger.info(f"Requesting historical data for {symbol} from {start_date} to {end_date}")
        use_rth = not is_forex
        logger.info("Use regular trading hours: %s", use_rth)

        retry_specs: list[list[str] | list[BarSpecification]] = []

        # Retry path 1: append -EXTERNAL suffix if not present
        external_suffix_specs = []
        for spec in bar_specifications:
            if spec.upper().endswith("-EXTERNAL"):
                external_suffix_specs.append(spec)
            else:
                external_suffix_specs.append(f"{spec}-EXTERNAL")
        retry_specs.append(external_suffix_specs)

        # Retry path 2: swap MID with MIDPOINT (if applicable)
        midpoint_specs = [
            spec.replace("-MID-", "-MIDPOINT-") if "-MID-" in spec else spec
            for spec in external_suffix_specs
        ]
        retry_specs.append(midpoint_specs)

        # Retry path 3: use BarSpecification objects directly (if accepted)
        retry_specs.append(bar_spec_objects)

        attempts: list[tuple[str, list[str] | list[BarSpecification]]] = [
            ("primary", bar_specifications),
            ("external_suffix", external_suffix_specs),
            ("midpoint_suffix", midpoint_specs),
            ("object", bar_spec_objects),
        ]

        bars = None
        successful_attempt: str | None = None
        for attempt_name, specs in attempts:
            logger.info("Attempting bar request (%s) with specs: %s", attempt_name, specs)
            try:
                bars = await client.request_bars(
                    bar_specifications=specs,
                    start_date_time=start_date,
                    end_date_time=end_date,
                    tz_name="America/New_York",
                    contracts=[contract],
                    use_rth=use_rth,
                    timeout=120,
                )
                logger.info("Bar request succeeded using '%s' specification variant.", attempt_name)
                successful_attempt = attempt_name
                break
            except ValueError as request_error:
                if "invalid literal for int()" in str(request_error):
                    logger.warning(
                        "Bar specification parsing error (attempt=%s) for %s: %s",
                        attempt_name,
                        symbol,
                        request_error,
                    )
                    continue
                logger.error(
                    "ValueError during historical data request (attempt=%s) for %s: %s",
                    attempt_name,
                    symbol,
                    request_error,
                    exc_info=True,
                )
                return []
            except Exception as request_error:
                logger.error(
                    "Unexpected error requesting historical bars (attempt=%s) for %s: %s",
                    attempt_name,
                    symbol,
                    request_error,
                    exc_info=True,
                )
                return []

        if bars is None:
            logger.error(
                "All bar specification attempts failed for %s. Last attempt specs: %s",
                symbol,
                attempts[-1][1],
            )
            logger.error(
                "This may indicate a NautilusTrader adapter compatibility issue. Consider adjusting specs or contacting support."
            )
            return []

        if not bars:
            logger.warning(
                "No bar data returned for %s. Potential causes: date range outside market hours, symbol unavailable on venue, or IBKR returned no data (e.g., error 162).",
                symbol,
            )
            logger.warning("Consider adjusting DATA_START_DATE/DATA_END_DATE or verifying instrument availability in TWS.")
            logger.warning("Sample bar_type from IBKR: <none>")
        else:
            logger.info(f"Successfully retrieved {len(bars) if bars else 0} bar records for {symbol}")
            sample_bar = bars[0]
            if hasattr(sample_bar, "bar_type"):
                logger.info("Sample bar_type from IBKR: %s", sample_bar.bar_type)
                logger.info(
                    "IB returned bar_type=%s (variant=%s)",
                    sample_bar.bar_type,
                    successful_attempt or "unknown",
                )
                ib_instrument_id = str(sample_bar.bar_type.instrument_id)
                venue_override = "IDEALPRO" if "/" in symbol else "SMART"
                custom_instrument = create_instrument(symbol, venue_override)
                custom_instrument_id = str(custom_instrument.id)
                log_instrument_metadata(custom_instrument, "Custom Instrument", logger)
                log_instrument_metadata(str(sample_bar.bar_type.instrument_id), "IB Adapter Instrument", logger)
                if not validate_instrument_id_match(
                    ib_instrument_id,
                    custom_instrument_id,
                    "IB Adapter vs Custom Creation",
                ):
                    logger.warning(
                        "Instrument ID mismatch between IB data (%s) and custom instrument (%s).",
                        ib_instrument_id,
                        custom_instrument_id,
                    )
            else:
                logger.debug("Sample bar_type unavailable on returned bars.")

        return bars or []
    except asyncio.CancelledError:
        logger.warning(
            "Historical data request for %s was cancelled or returned no data (e.g., IB error 162).",
            symbol,
        )
        return []
    except Exception as e:
        logger.error(f"Error downloading data for {symbol}: {e}", exc_info=True)
        return []
    finally:
        async def _cleanup(method_name: str) -> bool:
            method = getattr(client, method_name, None)
            if method is None:
                return False
            try:
                if inspect.iscoroutinefunction(method):
                    await method()
                else:
                    result = method()
                    if inspect.isawaitable(result):
                        await result
                logger.info(
                    "%s IBKR client", "Stopped" if method_name == "stop" else "Disconnected"
                )
                return True
            except Exception as cleanup_error:
                logger.warning(
                    "Error during client %s cleanup: %s", method_name, cleanup_error
                )
                return True

        try:
            cleaned = await _cleanup("stop")
            if not cleaned:
                cleaned = await _cleanup("disconnect")
            if not cleaned:
                logger.info(
                    "No explicit disconnect method available, client will cleanup automatically"
                )
        except Exception as e:
            logger.warning(f"Error during client cleanup: {e}")


def save_data(bars: list, symbol: str, output_dir: str) -> None:
    """
    Save bar data to Parquet and CSV formats.
    
    Args:
        bars: List of bar data objects from NautilusTrader
        symbol: Stock symbol
        output_dir: Output directory path
    """
    # Create output directory if it doesn't exist
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    if not bars:
        logging.warning(f"No data to save for {symbol}")
        return

    catalog = ParquetDataCatalog(output_dir)
    parquet_saved = False
    csv_saved = False

    # Attempt to persist bars to the Parquet catalog
    try:
        # Ensure instrument is registered in the catalog (needed for lookups by instrument_id)
        venue = os.getenv("BACKTEST_VENUE", "IDEALPRO") if "/" in symbol else os.getenv("STOCK_VENUE", "SMART")
        instrument = create_instrument(symbol, venue)
        try:
            catalog.write_data([instrument])
            logging.info("Registered instrument %s in catalog %s", instrument.id, output_dir)
        except Exception as inst_err:
            logging.debug("Instrument registration skipped or failed: %s", inst_err)

        catalog.write_data(bars)
        logging.info(f"Saved Parquet data for {symbol} to {output_dir}")
        parquet_saved = True
    except AssertionError as e:
        if "Intervals are not disjoint" in str(e):
            logging.warning(
                "Duplicate data detected for %s, clearing existing Parquet files before retrying...",
                symbol,
            )

            is_forex = "/" in symbol
            instrument_venue = os.getenv("BACKTEST_VENUE", "IDEALPRO") if is_forex else os.getenv("STOCK_VENUE", "SMART")
            instrument_id = normalize_instrument_id(symbol, instrument_venue or ("IDEALPRO" if is_forex else "SMART"))

            requested_specs: set[str] = set()
            for bar in bars:
                if hasattr(bar, "bar_type"):
                    bar_type_str = str(bar.bar_type)
                    prefix = f"{instrument_id}-"
                    if bar_type_str.startswith(prefix):
                        requested_specs.add(bar_type_str[len(prefix):])
                    else:
                        requested_specs.add(bar_type_str)

            if not requested_specs:
                if is_forex:
                    requested_specs = {"1-MINUTE-MID-EXTERNAL", "1-DAY-MID-EXTERNAL"}
                else:
                    requested_specs = {"1-MINUTE-LAST-EXTERNAL", "1-DAY-LAST-EXTERNAL"}

            catalog_path = Path(output_dir)
            dataset_root = catalog_path / "data" / "bar"
            deleted_any = False

            instrument_prefix = f"{instrument_id}-"
            target_specs = requested_specs or None

            dataset_names_seen: set[str] = set()
            deleted_datasets: set[str] = set()
            try:
                dataset_iter = dataset_root.rglob("*") if dataset_root.exists() else []
            except Exception as iter_err:
                logging.warning("Failed to enumerate dataset directories under %s: %s", dataset_root, iter_err)
                dataset_iter = []

            for entry in dataset_iter:
                if not entry.is_dir() or "-" not in entry.name:
                    continue
                dataset_name = entry.relative_to(dataset_root).as_posix()
                if not dataset_name.startswith(instrument_prefix):
                    continue
                spec = dataset_name[len(instrument_prefix):]
                if target_specs is not None and spec not in target_specs:
                    continue
                if dataset_name in dataset_names_seen:
                    continue
                dataset_names_seen.add(dataset_name)
                try:
                    shutil.rmtree(entry, ignore_errors=True)
                    logging.info("Deleted existing dataset directory: %s", entry)
                    deleted_datasets.add(dataset_name)
                    deleted_any = True
                except Exception as cleanup_error:
                    logging.warning(
                        "Failed to delete dataset directory %s during cleanup: %s",
                        entry,
                        cleanup_error,
                    )

            if not deleted_any:
                logging.warning(
                    "No existing Parquet files found to remove for %s despite duplicate interval error.",
                    symbol,
                )
            else:
                logging.info("Removed %s dataset directories prior to rewrite: %s", len(deleted_datasets), sorted(deleted_datasets))

            try:
                bar_type_spec = None
                if bars and hasattr(bars[0], "bar_type"):
                    bar_type_spec = str(bars[0].bar_type).split("-", 1)[-1]
                logging.info(
                    "Writing %s bars to catalog: instrument_id=%s output_dir=%s expected_dataset=%s",
                    len(bars),
                    instrument.id,
                    output_dir,
                    f"{instrument.id}-{bar_type_spec}" if bar_type_spec else "<unknown>",
                )
                catalog.write_data(bars)
                logging.info(
                    "Successfully wrote %s bars for %s to catalog %s",
                    len(bars),
                    instrument.id,
                    output_dir,
                )
                parquet_saved = True
            except AssertionError as retry_error:
                logging.error(
                    "Parquet write failed for %s after clearing duplicates: %s",
                    symbol,
                    retry_error,
                )
            except Exception as retry_error:
                logging.error(
                    "Unexpected error re-writing Parquet data for %s: %s",
                    symbol,
                    retry_error,
                    exc_info=True,
                )
        else:
            logging.error(
                "Failed to save Parquet data for %s: %s", symbol, e, exc_info=True
            )
    except (IOError, PermissionError) as e:
        logging.error(f"Failed to write Parquet data for {symbol}: {e}")
    except Exception as e:
        logging.error(
            f"Unexpected error saving Parquet data for {symbol}: {e}", exc_info=True
        )

    # Always attempt to save CSV files for inspection
    try:
        bar_groups = {}
        for bar in bars:
            if hasattr(bar, 'bar_type'):
                bar_spec = str(bar.bar_type)
            else:
                bar_spec = "unknown"

            bar_groups.setdefault(bar_spec, []).append(bar)

        for bar_spec, spec_bars in bar_groups.items():
            data = {
                "timestamp": [],
                "open": [],
                "high": [],
                "low": [],
                "close": [],
                "volume": [],
            }

            for bar in spec_bars:
                ts = pd.to_datetime(bar.ts_init, unit='ns', utc=True).tz_convert('America/New_York')
                data["timestamp"].append(ts.isoformat())
                data["open"].append(float(bar.open))
                data["high"].append(float(bar.high))
                data["low"].append(float(bar.low))
                data["close"].append(float(bar.close))
                data["volume"].append(int(bar.volume))

            df = pd.DataFrame(data)
            safe_symbol = symbol.replace('/', '-')
            safe_spec = (
                str(bar_spec)
                .replace('/', '-')
                .replace(' ', '_')
                .replace('-', '_')
                .replace('.', '_')
            )
            csv_filename = f"{safe_symbol}_{safe_spec}.csv"
            csv_path = Path(output_dir) / csv_filename
            df.to_csv(csv_path, index=False)
            logging.info(f"Saved CSV data for {symbol} ({bar_spec}) to {csv_path}")

        csv_saved = True
    except (IOError, PermissionError) as e:
        logging.error(f"Failed to write CSV data for {symbol}: {e}")
    except Exception as e:
        logging.error(
            f"Unexpected error saving CSV data for {symbol}: {e}", exc_info=True
        )

    if not parquet_saved and csv_saved:
        logging.warning(
            "Parquet save failed or was skipped for %s, but CSV files were created successfully.",
            symbol,
        )


async def main() -> int:
    """
    Main execution function for historical data ingestion.
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    logger = setup_logging()
    logger.info("Starting IBKR historical data ingestion...")
    
    try:
        # Load IBKR configuration
        config = get_ibkr_config()
        logger.info(f"Loaded IBKR config: {config.host}:{config.port} (client_id={config.client_id})")
        
        # Read data parameters from environment
        symbols_str = os.getenv("DATA_SYMBOLS", "SPY")
        symbols = [s.strip() for s in symbols_str.split(",")]
        
        start_date_str = os.getenv("DATA_START_DATE")
        end_date_str = os.getenv("DATA_END_DATE")
        
        # Parse dates with defaults
        if start_date_str:
            start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
        else:
            start_date = datetime.datetime.now() - datetime.timedelta(days=30)
            logger.info(f"No DATA_START_DATE specified, using default: {start_date.strftime('%Y-%m-%d')}")
        
        if end_date_str:
            end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d")
        else:
            end_date = datetime.datetime.now()
            logger.info(f"No DATA_END_DATE specified, using default: {end_date.strftime('%Y-%m-%d')}")
        
        # Validate date range
        if start_date >= end_date:
            logger.error(f"Invalid date range: start_date ({start_date}) must be before end_date ({end_date})")
            return 1
        
        # Define output directory (use same CATALOG_PATH as backtest)
        output_dir = os.getenv("CATALOG_PATH", "data/historical")
        try:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            logger.error("Cannot create or access catalog directory '%s': %s", output_dir, exc)
            return 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error preparing catalog directory '%s': %s", output_dir, exc)
            return 1

        if not os.access(output_dir, os.W_OK):
            logger.error("Catalog directory '%s' is not writable. Check permissions.", output_dir)
            return 1

        logger.info(f"Output directory: {output_dir}")
        logger.info("Catalog directory ready: %s", output_dir)
        logger.info(f"Symbols to process: {symbols}")
        logger.info(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        
        # Process each symbol
        catalog = ParquetDataCatalog(output_dir)

        for i, symbol in enumerate(symbols):
            logger.info(f"Downloading data for {symbol}... ({i+1}/{len(symbols)})")

            venue = os.getenv("BACKTEST_VENUE", "IDEALPRO") if "/" in symbol else os.getenv("STOCK_VENUE", "SMART")
            instrument = create_instrument(symbol, venue)
            try:
                catalog.write_data([instrument])
                logger.info(
                    "Registered instrument %s in catalog %s (pre-ingestion)",
                    instrument.id,
                    output_dir,
                )
            except Exception as inst_err:  # noqa: BLE001
                logger.debug("Instrument registration skipped or failed: %s", inst_err)

            bars = await download_historical_data(symbol, start_date, end_date, config)

            if bars:
                save_data(bars, symbol, output_dir)
            else:
                logger.warning(f"No data downloaded for {symbol}. Check date range and market hours.")
            
            # Add delay between symbols to respect IBKR pacing limits
            if i < len(symbols) - 1:  # Don't delay after the last symbol
                logger.info("Waiting 3 seconds before next request...")
                await asyncio.sleep(3)
        logger.info("Data ingestion completed successfully.")
        logger.info("Run 'python data/verify_catalog.py --json' for a structured catalog summary.")

        # Verify expected bar specs were persisted for each symbol
        for symbol in symbols:
            is_forex = "/" in symbol
            venue = os.getenv("BACKTEST_VENUE", "IDEALPRO") if is_forex else os.getenv("STOCK_VENUE", "SMART")
            instrument_id = normalize_instrument_id(symbol, venue or ("IDEALPRO" if is_forex else "SMART"))
            expected_bar_spec = "15-MINUTE-MID-EXTERNAL" if is_forex else "1-MINUTE-LAST-EXTERNAL"

            bar_identifier = f"{instrument_id}-{expected_bar_spec}"

            try:
                if not validate_catalog_dataset_exists(Path(output_dir), instrument_id, expected_bar_spec, logger):
                    logger.error("Dataset %s not found in catalog after ingestion.", bar_identifier)
                    continue
                bars = catalog.bars(bar_types=[bar_identifier])
                count = len(bars)
                if count == 0:
                    logger.warning(
                        "Ingestion completed but catalog query returned no bars for %s (instrument %s, bar_spec %s). Backtest may fail.",
                        symbol,
                        instrument_id,
                        expected_bar_spec,
                    )
                else:
                    logger.info(
                        "Verified %s bars for %s (%s).",
                        count,
                        symbol,
                        bar_identifier,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Catalog lookup failed for %s (%s): %s",
                    symbol,
                    bar_identifier,
                    exc,
                )

        # Summarize catalog contents with suffix check
        try:
            from data.verify_catalog import collect_bar_summaries  # type: ignore # noqa: WPS433

            summaries = collect_bar_summaries(catalog)
            missing = [s for s in summaries if not str(s.bar_type).endswith("-EXTERNAL")]

            logger.info(
                "Verification: %s bar types found; %s missing -EXTERNAL suffix",
                len(summaries),
                len(missing),
            )
            for summary in missing:
                logger.warning("Catalog bar missing -EXTERNAL: %s", summary.bar_type)
        except ImportError:
            logger.debug("Catalog verification skipped: collect_bar_summaries unavailable.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Catalog verification skipped or failed: %s", exc)

        return 0
        
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1
        logger.error(f"Unexpected error during data ingestion: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))