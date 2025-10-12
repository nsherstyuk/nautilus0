"""
Backtesting runner for the Moving Average Crossover strategy using NautilusTrader.

Loads historical bars from a ParquetDataCatalog, creates instrument (Equity or CurrencyPair),
executes a backtest via BacktestNode, and writes reports and performance stats.
Supports both stocks (e.g., SPY) and ISO 4217 forex pairs (e.g., EUR/USD).
Pairs involving metals/crypto with slashes (e.g., XAU/USD, BTC/USD) are not supported by this
CurrencyPair configuration and must be routed differently in NautilusTrader.
"""
from __future__ import annotations

import asyncio
import json
import logging
import logging.config
from logging.handlers import RotatingFileHandler
import os
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, Optional, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import yaml

from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model.data import Bar
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Equity, CurrencyPair
from nautilus_trader.model.objects import Currency, Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from nautilus_trader.backtest.config import (
    BacktestRunConfig,
    BacktestEngineConfig,
    BacktestVenueConfig,
    BacktestDataConfig,
)
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from strategies.moving_average_crossover import (
    MovingAverageCrossover,
    MovingAverageCrossoverConfig,
)
from config.backtest_config import BacktestConfig, get_backtest_config, validate_backtest_config
from utils.instruments import (
    parse_fx_symbol,
    normalize_instrument_id,
    validate_catalog_dataset_exists,
    format_instrument_diagnostic,
    log_instrument_metadata,
    instrument_id_to_catalog_format,
    catalog_format_to_instrument_id,
    try_both_instrument_formats,
)


def discover_catalog_bar_types(catalog_path: Path) -> list[str]:
    bar_root = Path(catalog_path) / "data" / "bar"
    if not bar_root.exists():
        return []

    dataset_names: set[str] = set()
    for parquet_file in bar_root.rglob("*.parquet"):
        try:
            rel = parquet_file.parent.relative_to(bar_root)
        except ValueError:
            continue
        dataset_name = rel.as_posix()
        dataset_names.add(dataset_name)
        
        # Check if this is a forex pair dataset and add normalized version
        # Extract instrument ID from dataset name (first part before first dash)
        parts = dataset_name.split('-')
        if parts:
            instrument_part = parts[0]
            # Convert no-slash format back to slashed format for forex pairs
            normalized_instrument = catalog_format_to_instrument_id(instrument_part)
            if normalized_instrument != instrument_part:
                # Reconstruct full dataset name with normalized instrument ID
                normalized_dataset = '-'.join([normalized_instrument] + parts[1:])
                dataset_names.add(normalized_dataset)

    # Fallback to include directories with metadata but no parquet files
    for metadata_name in ("_common_metadata", "_metadata"):
        for metadata_file in bar_root.rglob(metadata_name):
            try:
                rel = metadata_file.parent.relative_to(bar_root)
            except ValueError:
                continue
            dataset_name = rel.as_posix()
            dataset_names.add(dataset_name)
            
            # Check if this is a forex pair dataset and add normalized version
            parts = dataset_name.split('-')
            if parts:
                instrument_part = parts[0]
                normalized_instrument = catalog_format_to_instrument_id(instrument_part)
                if normalized_instrument != instrument_part:
                    normalized_dataset = '-'.join([normalized_instrument] + parts[1:])
                    dataset_names.add(normalized_dataset)

    return sorted(dataset_names)


def format_bar_sample(bars: List[Bar], limit: int = 5) -> list[dict[str, object]]:
    sample: list[dict[str, object]] = []
    for bar in bars[:limit]:
        sample.append(
            {
                "ts_event": pd.to_datetime(bar.ts_event, unit="ns", utc=True).isoformat(),
                "ts_init": pd.to_datetime(bar.ts_init, unit="ns", utc=True).isoformat(),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": int(bar.volume),
            }
        )
    return sample


def setup_logging() -> logging.Logger:
    """Setup logging from YAML or fallback to env-based config."""
    config_path = Path(__file__).parent.parent / "config" / "logging.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        logging.config.dictConfig(cfg)
        return logging.getLogger(__name__)
    except Exception as e:
        # Fallback using env vars if YAML missing or invalid
        level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)
        log_dir = os.getenv("LOG_DIR", "logs")
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        root = logging.getLogger()
        root.setLevel(level)
        for h in list(root.handlers):
            root.removeHandler(h)

        fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        ch.setFormatter(fmt)
        root.addHandler(ch)

        fh = RotatingFileHandler(
            filename=str(Path(log_dir) / "application.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)

        logger = logging.getLogger(__name__)
        logger.warning(
            f"Failed to load logging config from {config_path}: {e}. Using env-based logging."
        )
        return logger


aSYNC = False  # backtest node run is synchronous API

def create_instrument(symbol: str, venue: str = "SMART"):
    """
    Create instrument for backtesting (supports stocks and forex).
    
    Automatically detects instrument type based on symbol format:
    - Stocks: "SPY", "AAPL", etc. → Creates Equity instrument
    - Forex: "EUR/USD", "GBP/JPY", etc. → Creates CurrencyPair instrument
    
    Args:
        symbol: Ticker or forex pair (e.g., "SPY" or "EUR/USD")
        venue: Trading venue (default "SMART" for stocks)
        
    Returns:
        Equity or CurrencyPair instrument configured for backtesting
    """
    venue = venue.strip().upper()
    # Normalize instrument ID to match catalog format (slashed forex IDs retained)
    normalized_id = normalize_instrument_id(symbol, venue)
    instrument_id = InstrumentId.from_str(normalized_id)
    
    # Detect forex pairs by "/" separator
    if "/" in symbol:
        # Forex pair: create CurrencyPair instrument
        base_currency, quote_currency = parse_fx_symbol(symbol)
        
        currency_pair = CurrencyPair(
            instrument_id=instrument_id,
            raw_symbol=Symbol(f"{base_currency}/{quote_currency}"),  # Retain slash for raw symbol
            base_currency=Currency.from_str(base_currency),  # EUR
            quote_currency=Currency.from_str(quote_currency),  # USD
            price_precision=5,  # Forex typically uses 5 decimals (e.g., 1.08234)
            size_precision=2,  # Match IB bar volume precision
            size_increment=Quantity.from_str("0.01"),  # Minimum 0.01 units (precision=2)
            price_increment=Price.from_str("0.00001"),  # 1/10th pip (0.1 pip)
            lot_size=Quantity.from_str("1000.00"),  # Micro lot = 1,000 units
            max_quantity=Quantity.from_str("50000000.00"),  # 50M units max
            min_quantity=Quantity.from_str("0.01"),  # 0.01 unit minimum (precision=2)
            max_price=None,  # No price limits
            min_price=None,
            margin_init=Decimal("0.03"),  # 3% initial margin (example, adjust per broker)
            margin_maint=Decimal("0.02"),  # 2% maintenance margin (example)
            maker_fee=Decimal("0.00002"),  # 0.002% maker fee (example)
            taker_fee=Decimal("0.00002"),  # 0.002% taker fee (example)
            ts_event=0,
            ts_init=0,
        )
        return currency_pair
    else:
        # Stock: create Equity instrument (original logic)
        equity = Equity(
            instrument_id=instrument_id,
            raw_symbol=Symbol(symbol),
            currency=Currency.from_str("USD"),
            price_precision=2,  # Stocks use 2 decimals (e.g., 450.25)
            price_increment=Price.from_str("0.01"),  # 1 cent
            lot_size=Quantity.from_int(1),
            ts_event=0,
            ts_init=0,
        )
        return equity


def create_backtest_run_config(
    symbol: str,
    venue: str,
    start_date: str,
    end_date: str,
    catalog_path: str,
    fast_period: int,
    slow_period: int,
    trade_size: int,
    bar_spec: str,
    starting_capital: float,
    enforce_position_limit: bool,
    allow_position_reversal: bool,
    stop_loss_pips: int,
    take_profit_pips: int,
    trailing_stop_activation_pips: int,
    trailing_stop_distance_pips: int,
) -> BacktestRunConfig:
    """Create BacktestRunConfig wiring data, venue and strategy."""
    # Time bounds
    venue = venue.strip().upper()
    start_ns = dt_to_unix_nanos(pd.Timestamp(start_date, tz="UTC").to_pydatetime())
    end_ns = dt_to_unix_nanos(pd.Timestamp(end_date, tz="UTC").to_pydatetime())

    is_fx = "/" in symbol
    account_type = "MARGIN" if is_fx else "CASH"

    starting_balances = [f"{starting_capital} USD"]
    base_currency = "USD"
    if is_fx:
        base_currency = None  # Enable multi-currency balances
        base_currency_code = symbol.split("/")[0].strip().upper()
        if base_currency_code != "USD":
            starting_balances.append(f"{starting_capital} {base_currency_code}")

    venue_cfg = BacktestVenueConfig(
        name=venue,
        oms_type="NETTING",
        account_type=account_type,
        base_currency=base_currency,
        starting_balances=starting_balances,
    )

    # Normalize instrument ID for catalog and strategy config
    normalized_id = normalize_instrument_id(symbol, venue)
    logger = logging.getLogger(__name__)
    logger.info(
        "Creating BacktestDataConfig with instrument_id=%s, bar_spec=%s, start=%s, end=%s",
        normalized_id,
        bar_spec,
        start_date,
        end_date,
    )

    data_cfg = BacktestDataConfig(
        catalog_path=str(catalog_path),
        data_cls=Bar,
        instrument_id=normalized_id,
        bar_spec=bar_spec,
        start_time=start_ns,
        end_time=end_ns,
    )

    strat_cfg = ImportableStrategyConfig(
        strategy_path="strategies.moving_average_crossover:MovingAverageCrossover",
        config_path="strategies.moving_average_crossover:MovingAverageCrossoverConfig",
        config={
            "instrument_id": normalized_id,
            "bar_spec": bar_spec,
            "fast_period": fast_period,
            "slow_period": slow_period,
            "trade_size": str(trade_size),
            "enforce_position_limit": enforce_position_limit,
            "allow_position_reversal": allow_position_reversal,
            "stop_loss_pips": stop_loss_pips,
            "take_profit_pips": take_profit_pips,
            "trailing_stop_activation_pips": trailing_stop_activation_pips,
            "trailing_stop_distance_pips": trailing_stop_distance_pips,
        },
    )

    engine_cfg = BacktestEngineConfig(
        strategies=[strat_cfg],
    )

    return BacktestRunConfig(
        engine=engine_cfg,
        data=[data_cfg],
        venues=[venue_cfg],
        raise_exception=True,
        dispose_on_completion=False,
    )


def generate_reports(
    engine,
    output_dir: Path,
    symbol: str,
    venue: str,
    strategy: Optional[Strategy],
    processed_bars: int,
    config: BacktestConfig,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(__name__)
    orders_df = engine.trader.generate_orders_report()
    fills_df = engine.trader.generate_fills_report()
    positions_df = engine.trader.generate_positions_report()
    account_df = engine.trader.generate_account_report(Venue(venue))

    logger.debug(
        "Report shapes - orders: %s, fills: %s, positions: %s, account: %s",
        orders_df.shape,
        fills_df.shape,
        positions_df.shape,
        account_df.shape,
    )

    orders_df.to_csv(output_dir / "orders.csv", index=False)
    fills_df.to_csv(output_dir / "fills.csv", index=False)
    positions_df.to_csv(output_dir / "positions.csv", index=False)
    account_df.to_csv(output_dir / "account.csv", index=False)

    rejected_signals: List[Dict[str, Any]] = []

    if strategy is not None and hasattr(strategy, "get_rejected_signals"):
        try:
            rejected_signals = strategy.get_rejected_signals()
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to retrieve rejected signals: %s", exc)
            rejected_signals = []

        if rejected_signals:
            rejected_df = pd.DataFrame(rejected_signals)
            for col in ["timestamp", "bar_close_time"]:
                if col in rejected_df.columns:
                    rejected_df[col] = pd.to_datetime(rejected_df[col], unit="ns", utc=True)
            rejected_df.to_csv(output_dir / "rejected_signals.csv", index=False)
            logger.info("Rejected signals recorded: %s", len(rejected_df))
            reason_counts = Counter(rejected_df.get("reason", []))
            logger.info("Rejected signal reasons: %s", dict(reason_counts))
        else:
            logger.info("No rejected signals to report")
    else:
        logger.info("Strategy does not expose rejected signal information")

    # Choose reporting currency (use FX quote currency when applicable)
    reporting_currency = Currency.from_str("USD")
    try:
        if "/" in symbol:
            _, quote = parse_fx_symbol(symbol)
            reporting_currency = Currency.from_str(quote)
    except Exception:
        reporting_currency = Currency.from_str("USD")

    try:
        pnls_stats = engine.portfolio.analyzer.get_performance_stats_pnls(currency=reporting_currency)
    except TypeError:
        pnls_stats = engine.portfolio.analyzer.get_performance_stats_pnls()

    try:
        general_stats = engine.portfolio.analyzer.get_performance_stats_general(currency=reporting_currency)
    except TypeError:
        # Older signatures may not accept currency parameter
        general_stats = engine.portfolio.analyzer.get_performance_stats_general()

    stats = {
        "pnls": pnls_stats,
        "general": general_stats,
        "rejected_signals_count": len(rejected_signals),
    }
    with open(output_dir / "performance_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    # Optional equity curve plot derived from account history
    try:
        import matplotlib.pyplot as plt

        # Determine timestamp and equity columns
        timestamp_cols = ["timestamp", "ts_event", "ts"]
        equity_cols = [
            "net_liquidation",
            "equity",
            "balance",
            "net_liq",
            "account_value",
        ]

        ts_col = next((col for col in timestamp_cols if col in account_df.columns), None)
        eq_col = next((col for col in equity_cols if col in account_df.columns), None)

        if ts_col and eq_col:
            equity_curve_df = account_df[[ts_col, eq_col]].copy()
            equity_curve_df.columns = ["timestamp", "equity"]
            equity_curve_df["timestamp"] = pd.to_datetime(equity_curve_df["timestamp"])

            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(equity_curve_df["timestamp"], equity_curve_df["equity"], label="Equity")
            ax.set_title(f"Equity Curve - {symbol}")
            ax.set_xlabel("Time")
            ax.set_ylabel("Account Equity (USD)")
            ax.grid(True)
            ax.legend()
            fig.tight_layout()
            fig.savefig(output_dir / "equity_curve.png")
            plt.close(fig)

            equity_curve_df.to_csv(output_dir / "equity_curve_data.csv", index=False)
        else:
            account_df.to_csv(output_dir / "equity_curve_data.csv", index=False)
    except Exception:
        account_df.to_csv(output_dir / "equity_curve_data.csv", index=False)

    if orders_df.empty and fills_df.empty and positions_df.empty:
        diagnostics: list[str] = []
        diagnostics.append("No orders or fills generated during backtest.")
        diagnostics.append(
            "Possible causes: insufficient bars for warmup, no SMA crossovers, or bar data not streaming to strategy."
        )
        diagnostics.append(f"Bars processed: {processed_bars}")
        diagnostics.append(f"Configured fast/slow periods: {config.fast_period}/{config.slow_period}")
        zero_trade_path = output_dir / "zero_trade_diagnostic.txt"
        zero_trade_path.write_text("\n".join(diagnostics), encoding="utf-8")
        logger.warning("Zero trade diagnostic written to %s", zero_trade_path)

    return stats


async def main() -> int:
    logger = setup_logging()
    logger.info("Starting backtest...")

    cfg = get_backtest_config()

    if not validate_backtest_config(cfg):
        logger.error("Backtest configuration validation failed. Check .env settings and data availability.")
        return 1

    # Validate catalog path
    catalog_path = Path(cfg.catalog_path)
    if not catalog_path.exists():
        logger.error(f"Catalog path does not exist: {catalog_path}")
        return 1

    # Create instrument and run configuration
    instrument = create_instrument(cfg.symbol, cfg.venue)
    if os.getenv("BACKTEST_ASSERT_INSTRUMENT_ID", "0").lower() in {"1", "true", "yes"}:
        expected_instrument_id = normalize_instrument_id(cfg.symbol, cfg.venue.strip().upper())
        if str(instrument.id) != expected_instrument_id:
            logger.error(
                "Instrument ID mismatch: expected %s, got %s",
                expected_instrument_id,
                instrument.id,
            )
            return 1

    catalog: ParquetDataCatalog | None = None
    try:
        catalog = ParquetDataCatalog(cfg.catalog_path)
    except Exception as e:
        logger.error("Failed to open catalog %s: %s", cfg.catalog_path, e, exc_info=True)
        logger.info("Run 'python data/ingest_historical.py' to ingest data or verify the catalog path.")
        return 1

    try:
        catalog.write_data([instrument])
        logger.info("Registered instrument %s in catalog %s", instrument.id, cfg.catalog_path)
    except Exception as e:
        logger.warning(
            "Instrument registration failed for %s in catalog %s: %s",
            instrument.id,
            cfg.catalog_path,
            e,
            exc_info=True,
        )

    normalized_id = normalize_instrument_id(cfg.symbol, cfg.venue.strip().upper())
    full_bar_type = f"{normalized_id}-{cfg.bar_spec}"

    try:
        start_ts = pd.Timestamp(cfg.start_date)
        end_ts = pd.Timestamp(cfg.end_date)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize("UTC")
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize("UTC")
    except Exception as exc:
        logger.error("Failed to parse backtest date range: %s", exc, exc_info=True)
        return 1

    available_datasets = discover_catalog_bar_types(catalog_path)
    logger.info("Available catalog datasets (%s): %s", len(available_datasets), available_datasets)
    logger.info("Requesting bar type: %s", full_bar_type)

    if full_bar_type not in available_datasets:
        candidates = [
            dataset for dataset in available_datasets if dataset.split("-")[0] == normalized_id
        ]
        logger.warning(
            "Requested bar type %s not found in catalog datasets. Data ingestion may have saved a different spec.",
            full_bar_type,
        )
        if candidates:
            logger.warning("Candidate datasets with matching instrument: %s", candidates)
        else:
            logger.warning("No datasets share instrument_id %s; available: %s", normalized_id, available_datasets)
            logger.warning("Note: Will try both slashed and no-slash format variants for forex pairs")

    # Try both instrument ID formats for catalog query
    instrument_id_variants = try_both_instrument_formats(normalized_id)
    # Deduplicate variants to avoid redundant catalog queries for identical variants
    instrument_id_variants = list(dict.fromkeys(instrument_id_variants))
    bar_type_variants = [f"{variant}-{cfg.bar_spec}" for variant in instrument_id_variants]
    
    catalog_bars = []
    successful_variant = None
    
    for attempt_num, bar_type_variant in enumerate(bar_type_variants, 1):
        try:
            catalog_bars = catalog.bars(
                bar_types=[bar_type_variant],
                start=start_ts.value,
                end=end_ts.value,
            )
            if catalog_bars:
                successful_variant = bar_type_variant
                logger.info(f"Found {len(catalog_bars)} bars using format variant {attempt_num}: {bar_type_variant}")
                break
            else:
                logger.debug(f"No bars found with variant {attempt_num}: {bar_type_variant}")
        except Exception as exc:
            logger.debug(f"Query failed with variant {attempt_num}: {bar_type_variant} - {exc}")
            continue
    
    if not catalog_bars:
        logger.error(
            "No bars found in catalog for any format variant. Tried: %s",
            bar_type_variants
        )
        logger.info("Run 'python data/verify_catalog.py --json' to inspect catalog contents or re-run ingestion.")
        return 1

    logger.info(
        "Catalog validation succeeded: %s bars available for %s (%s).",
        len(catalog_bars),
        normalized_id,
        cfg.bar_spec,
    )

    sample_info = format_bar_sample(catalog_bars)
    if sample_info:
        logger.debug("Sample bars (first %s): %s", len(sample_info), sample_info)
        sample_start = sample_info[0]["ts_init"]
        sample_end = sample_info[-1]["ts_init"]
        logger.info("Sample coverage from %s to %s", sample_start, sample_end)

    if len(catalog_bars) < cfg.slow_period:
        logger.warning(
            "Only %s bars available but slow SMA requires %s bars to warm up.",
            len(catalog_bars),
            cfg.slow_period,
        )

    run_cfg = create_backtest_run_config(
        symbol=cfg.symbol,
        venue=cfg.venue,
        start_date=cfg.start_date,
        end_date=cfg.end_date,
        catalog_path=cfg.catalog_path,
        fast_period=cfg.fast_period,
        slow_period=cfg.slow_period,
        trade_size=cfg.trade_size,
        bar_spec=cfg.bar_spec,
        starting_capital=cfg.starting_capital,
        enforce_position_limit=cfg.enforce_position_limit,
        allow_position_reversal=cfg.allow_position_reversal,
        stop_loss_pips=cfg.stop_loss_pips,
        take_profit_pips=cfg.take_profit_pips,
        trailing_stop_activation_pips=cfg.trailing_stop_activation_pips,
        trailing_stop_distance_pips=cfg.trailing_stop_distance_pips,
    )

    logger.info(
        "Building BacktestNode with instrument_id=%s, bar_spec=%s, start_ns=%s, end_ns=%s",
        normalized_id,
        cfg.bar_spec,
        start_ts.value,
        end_ts.value,
    )

    node = BacktestNode(configs=[run_cfg])
    try:
        node.build()
    except Exception as build_error:
        logger.error("Backtest engine build failed: %s", build_error, exc_info=True)
        return 1

    # Access engine and add instrument before running
    engine = node.get_engine(run_cfg.id)
    if engine is None:
        logger.error("Failed to retrieve engine for run config %s", run_cfg.id)
        return 1
    engine.add_instrument(instrument)

    # Run backtest
    logger.info("Running backtest...")
    node.run()
    logger.info("Backtest completed.")

    try:
        processed_count = engine.data_engine.data_count(run_cfg.id)
    except Exception as exc:
        processed_count = 0
        logger.warning("Failed to retrieve processed bar count: %s", exc)
    order_count = len(engine.trader.generate_orders_report())
    fill_count = len(engine.trader.generate_fills_report())
    logger.info(
        "Execution summary: bars_processed=%s, orders=%s, fills=%s",
        processed_count,
        order_count,
        fill_count,
    )

    # Write reports
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_symbol = cfg.symbol.replace('/', '-')
    output_dir = Path(cfg.output_dir) / f"{safe_symbol}_{timestamp}"
    strategies = engine.trader.strategies()
    strategy_instance = strategies[0] if strategies else None
    stats = generate_reports(
        engine,
        output_dir,
        cfg.symbol,
        cfg.venue,
        strategy_instance,
        processed_count,
        cfg,
    )

    logger.info(f"Results written to: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
