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
        # Create base logs directory before dictConfig
        base_log_dir = Path(__file__).parent.parent / "logs"
        base_log_dir.mkdir(parents=True, exist_ok=True)
        
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
    adaptive_stop_mode: str,
    adaptive_atr_period: int,
    tp_atr_mult: float,
    sl_atr_mult: float,
    trail_activation_atr_mult: float,
    trail_distance_atr_mult: float,
    volatility_window: int,
    volatility_sensitivity: float,
    min_stop_distance_pips: float,
    regime_detection_enabled: bool,
    regime_adx_trending_threshold: float,
    regime_adx_ranging_threshold: float,
    regime_tp_multiplier_trending: float,
    regime_tp_multiplier_ranging: float,
    regime_sl_multiplier_trending: float,
    regime_sl_multiplier_ranging: float,
    regime_trailing_activation_multiplier_trending: float,
    regime_trailing_activation_multiplier_ranging: float,
    regime_trailing_distance_multiplier_trending: float,
    regime_trailing_distance_multiplier_ranging: float,
    *,
    # Strategy filter parameters (from env)
    crossover_threshold_pips: float,
    # Trend filter
    trend_filter_enabled: bool,
    trend_bar_spec: str,
    trend_ema_period: int,
    trend_ema_threshold_pips: float,
    # RSI filter
    rsi_enabled: bool,
    rsi_period: int,
    rsi_overbought: int,
    rsi_oversold: int,
    rsi_divergence_lookback: int,
    # Volume filter
    volume_enabled: bool,
    volume_avg_period: int,
    volume_min_multiplier: float,
    # ATR filter
    atr_enabled: bool,
    atr_period: int,
    atr_min_strength: float,
    dmi_enabled: bool,
    dmi_bar_spec: str,
    dmi_period: int,
    stoch_enabled: bool,
    stoch_bar_spec: str,
    stoch_period_k: int,
    stoch_period_d: int,
    stoch_bullish_threshold: int,
    stoch_bearish_threshold: int,
    stoch_max_bars_since_crossing: int,
    time_filter_enabled: bool,
    excluded_hours: list[int],
    excluded_hours_mode: str,
    excluded_hours_by_weekday: dict[str, list[int]],
    # Time-of-day multipliers
    time_multiplier_enabled: bool,
    time_tp_multiplier_eu_morning: float,
    time_tp_multiplier_us_session: float,
    time_tp_multiplier_other: float,
    time_sl_multiplier_eu_morning: float,
    time_sl_multiplier_us_session: float,
    time_sl_multiplier_other: float,
    # Entry timing parameters
    entry_timing_enabled: bool,
    entry_timing_bar_spec: str,
    entry_timing_method: str,
    entry_timing_timeout_bars: int,
    # Duration-based trailing stop optimization
    trailing_duration_enabled: bool,
    trailing_duration_threshold_hours: float,
    trailing_duration_distance_pips: int,
    trailing_duration_remove_tp: bool,
    trailing_duration_activate_if_not_active: bool,
    # Minimum hold time feature
    min_hold_time_enabled: bool,
    min_hold_time_hours: float,
    min_hold_time_stop_multiplier: float,
    # Partial close on first trailing activation
    partial_close_enabled: bool,
    partial_close_fraction: float,
    partial_close_move_sl_to_be: bool,
    partial_close_remainder_trail_multiplier: float,
    # First partial close BEFORE trailing activation
    partial1_enabled: bool,
    partial1_fraction: float,
    partial1_threshold_pips: float,
    partial1_move_sl_to_be: bool,
    # Market structure filter
    structure_filter_enabled: bool,
    structure_lookback_bars: int,
    structure_buffer_pips: float,
    structure_mode: str,
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

    # Always include primary bar stream
    data_cfgs: list[BacktestDataConfig] = [
        BacktestDataConfig(
            catalog_path=str(catalog_path),
            data_cls=Bar,
            instrument_id=normalized_id,
            bar_spec=bar_spec,
            start_time=start_ns,
            end_time=end_ns,
        )
    ]

    # Optionally include Trend filter bar stream if different timeframe
    if trend_filter_enabled and trend_bar_spec and trend_bar_spec != bar_spec:
        data_cfgs.append(
            BacktestDataConfig(
                catalog_path=str(catalog_path),
                data_cls=Bar,
                instrument_id=normalized_id,
                bar_spec=trend_bar_spec,
                start_time=start_ns,
                end_time=end_ns,
            )
        )

    # Optionally include DMI bar stream if different timeframe
    if dmi_enabled and dmi_bar_spec and dmi_bar_spec != bar_spec:
        data_cfgs.append(
            BacktestDataConfig(
                catalog_path=str(catalog_path),
                data_cls=Bar,
                instrument_id=normalized_id,
                bar_spec=dmi_bar_spec,
                start_time=start_ns,
                end_time=end_ns,
            )
        )

    # Optionally include Stochastic bar stream if different timeframe
    if stoch_enabled and stoch_bar_spec and stoch_bar_spec != bar_spec:
        data_cfgs.append(
            BacktestDataConfig(
                catalog_path=str(catalog_path),
                data_cls=Bar,
                instrument_id=normalized_id,
                bar_spec=stoch_bar_spec,
                start_time=start_ns,
                end_time=end_ns,
            )
        )

    # Optionally include Entry Timing bar stream if enabled and different timeframe
    if entry_timing_enabled and entry_timing_bar_spec and entry_timing_bar_spec != bar_spec:
        data_cfgs.append(
            BacktestDataConfig(
                catalog_path=str(catalog_path),
                data_cls=Bar,
                instrument_id=normalized_id,
                bar_spec=entry_timing_bar_spec,
                start_time=start_ns,
                end_time=end_ns,
            )
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
            # Adaptive stops
            "adaptive_stop_mode": adaptive_stop_mode,
            "adaptive_atr_period": adaptive_atr_period,
            "tp_atr_mult": tp_atr_mult,
            "sl_atr_mult": sl_atr_mult,
            "trail_activation_atr_mult": trail_activation_atr_mult,
            "trail_distance_atr_mult": trail_distance_atr_mult,
            "volatility_window": volatility_window,
            "volatility_sensitivity": volatility_sensitivity,
            "min_stop_distance_pips": min_stop_distance_pips,
            "regime_detection_enabled": regime_detection_enabled,
            "regime_adx_trending_threshold": regime_adx_trending_threshold,
            "regime_adx_ranging_threshold": regime_adx_ranging_threshold,
            "regime_tp_multiplier_trending": regime_tp_multiplier_trending,
            "regime_tp_multiplier_ranging": regime_tp_multiplier_ranging,
            "regime_sl_multiplier_trending": regime_sl_multiplier_trending,
            "regime_sl_multiplier_ranging": regime_sl_multiplier_ranging,
            "regime_trailing_activation_multiplier_trending": regime_trailing_activation_multiplier_trending,
            "regime_trailing_activation_multiplier_ranging": regime_trailing_activation_multiplier_ranging,
            "regime_trailing_distance_multiplier_trending": regime_trailing_distance_multiplier_trending,
            "regime_trailing_distance_multiplier_ranging": regime_trailing_distance_multiplier_ranging,
            # Filters
            "crossover_threshold_pips": crossover_threshold_pips,
            # Trend filter
            "trend_filter_enabled": trend_filter_enabled,
            "trend_bar_spec": trend_bar_spec,
            "trend_ema_period": trend_ema_period,
            "trend_ema_threshold_pips": trend_ema_threshold_pips,
            # RSI filter
            "rsi_enabled": rsi_enabled,
            "rsi_period": rsi_period,
            "rsi_overbought": rsi_overbought,
            "rsi_oversold": rsi_oversold,
            "rsi_divergence_lookback": rsi_divergence_lookback,
            # Volume filter
            "volume_enabled": volume_enabled,
            "volume_avg_period": volume_avg_period,
            "volume_min_multiplier": volume_min_multiplier,
            # ATR filter
            "atr_enabled": atr_enabled,
            "atr_period": atr_period,
            "atr_min_strength": atr_min_strength,
            # DMI
            "dmi_enabled": dmi_enabled,
            "dmi_period": dmi_period,
            "dmi_bar_spec": dmi_bar_spec,
            # Stochastic
            "stoch_enabled": stoch_enabled,
            "stoch_bar_spec": stoch_bar_spec,
            "stoch_period_k": stoch_period_k,
            "stoch_period_d": stoch_period_d,
            "stoch_bullish_threshold": stoch_bullish_threshold,
            "stoch_bearish_threshold": stoch_bearish_threshold,
            "stoch_max_bars_since_crossing": stoch_max_bars_since_crossing,
            # Time filter
            "time_filter_enabled": time_filter_enabled,
            "excluded_hours": excluded_hours,
            "excluded_hours_mode": excluded_hours_mode,
            "excluded_hours_by_weekday": excluded_hours_by_weekday,
            # Time-of-day multipliers
            "time_multiplier_enabled": time_multiplier_enabled,
            "time_tp_multiplier_eu_morning": time_tp_multiplier_eu_morning,
            "time_tp_multiplier_us_session": time_tp_multiplier_us_session,
            "time_tp_multiplier_other": time_tp_multiplier_other,
            "time_sl_multiplier_eu_morning": time_sl_multiplier_eu_morning,
            "time_sl_multiplier_us_session": time_sl_multiplier_us_session,
            "time_sl_multiplier_other": time_sl_multiplier_other,
            # Entry timing
            "entry_timing_enabled": entry_timing_enabled,
            "entry_timing_bar_spec": entry_timing_bar_spec,
            "entry_timing_method": entry_timing_method,
            "entry_timing_timeout_bars": entry_timing_timeout_bars,
            # Duration-based trailing stop optimization
            "trailing_duration_enabled": trailing_duration_enabled,
            "trailing_duration_threshold_hours": trailing_duration_threshold_hours,
            "trailing_duration_distance_pips": trailing_duration_distance_pips,
            "trailing_duration_remove_tp": trailing_duration_remove_tp,
            "trailing_duration_activate_if_not_active": trailing_duration_activate_if_not_active,
            # Minimum hold time feature
            "min_hold_time_enabled": min_hold_time_enabled,
            "min_hold_time_hours": min_hold_time_hours,
            "min_hold_time_stop_multiplier": min_hold_time_stop_multiplier,
            # Partial close on first trailing activation
            "partial_close_enabled": partial_close_enabled,
            "partial_close_fraction": partial_close_fraction,
            "partial_close_move_sl_to_be": partial_close_move_sl_to_be,
            "partial_close_remainder_trail_multiplier": partial_close_remainder_trail_multiplier,
            # First partial close BEFORE trailing activation
            "partial1_enabled": partial1_enabled,
            "partial1_fraction": partial1_fraction,
            "partial1_threshold_pips": partial1_threshold_pips,
            "partial1_move_sl_to_be": partial1_move_sl_to_be,
            # Market structure filter
            "structure_filter_enabled": structure_filter_enabled,
            "structure_lookback_bars": structure_lookback_bars,
            "structure_buffer_pips": structure_buffer_pips,
            "structure_mode": structure_mode,
        },
    )

    engine_cfg = BacktestEngineConfig(
        strategies=[strat_cfg],
    )

    return BacktestRunConfig(
        engine=engine_cfg,
        data=data_cfgs,
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

    # Generate statistical analysis report
    if not positions_df.empty:
        generate_statistical_analysis(positions_df, output_dir, logger)

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

    # Save environment configuration to results folder
    env_lines = []
    env_lines.append("# Backtest Configuration - Saved from environment variables")
    env_lines.append(f"# Generated: {datetime.now().isoformat()}")
    env_lines.append("")
    
    # Backtest parameters
    env_lines.append("# ============================================================================")
    env_lines.append("# BACKTESTING PARAMETERS")
    env_lines.append("# ============================================================================")
    env_lines.append(f"BACKTEST_SYMBOL={config.symbol}")
    env_lines.append(f"BACKTEST_START_DATE={config.start_date}")
    env_lines.append(f"BACKTEST_END_DATE={config.end_date}")
    env_lines.append(f"BACKTEST_VENUE={config.venue}")
    env_lines.append(f"BACKTEST_BAR_SPEC={config.bar_spec}")
    env_lines.append(f"BACKTEST_FAST_PERIOD={config.fast_period}")
    env_lines.append(f"BACKTEST_SLOW_PERIOD={config.slow_period}")
    env_lines.append(f"BACKTEST_TRADE_SIZE={config.trade_size}")
    env_lines.append(f"BACKTEST_STARTING_CAPITAL={config.starting_capital}")
    env_lines.append(f"CATALOG_PATH={config.catalog_path}")
    env_lines.append(f"OUTPUT_DIR={config.output_dir}")
    env_lines.append(f"ENFORCE_POSITION_LIMIT={str(config.enforce_position_limit).lower()}")
    env_lines.append(f"ALLOW_POSITION_REVERSAL={str(config.allow_position_reversal).lower()}")
    env_lines.append(f"BACKTEST_STOP_LOSS_PIPS={config.stop_loss_pips}")
    env_lines.append(f"BACKTEST_TAKE_PROFIT_PIPS={config.take_profit_pips}")
    env_lines.append(f"BACKTEST_TRAILING_STOP_ACTIVATION_PIPS={config.trailing_stop_activation_pips}")
    env_lines.append(f"BACKTEST_TRAILING_STOP_DISTANCE_PIPS={config.trailing_stop_distance_pips}")
    # Market regime detection
    env_lines.append("# Market Regime Detection")
    env_lines.append(f"STRATEGY_REGIME_DETECTION_ENABLED={str(config.regime_detection_enabled).lower()}")
    env_lines.append(f"STRATEGY_REGIME_ADX_TRENDING_THRESHOLD={config.regime_adx_trending_threshold}")
    env_lines.append(f"STRATEGY_REGIME_ADX_RANGING_THRESHOLD={config.regime_adx_ranging_threshold}")
    env_lines.append(f"STRATEGY_REGIME_TP_MULTIPLIER_TRENDING={config.regime_tp_multiplier_trending}")
    env_lines.append(f"STRATEGY_REGIME_TP_MULTIPLIER_RANGING={config.regime_tp_multiplier_ranging}")
    env_lines.append(f"STRATEGY_REGIME_SL_MULTIPLIER_TRENDING={config.regime_sl_multiplier_trending}")
    env_lines.append(f"STRATEGY_REGIME_SL_MULTIPLIER_RANGING={config.regime_sl_multiplier_ranging}")
    env_lines.append(f"STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING={config.regime_trailing_activation_multiplier_trending}")
    env_lines.append(f"STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING={config.regime_trailing_activation_multiplier_ranging}")
    env_lines.append(f"STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING={config.regime_trailing_distance_multiplier_trending}")
    env_lines.append(f"STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING={config.regime_trailing_distance_multiplier_ranging}")
    env_lines.append("")
    
    # Strategy filters
    env_lines.append("# ============================================================================")
    env_lines.append("# STRATEGY FILTER CONFIGURATION")
    env_lines.append("# ============================================================================")
    env_lines.append(f"STRATEGY_CROSSOVER_THRESHOLD_PIPS={config.crossover_threshold_pips}")
    env_lines.append("")
    
    # Trend filter
    env_lines.append("# Trend Filter")
    env_lines.append(f"STRATEGY_TREND_FILTER_ENABLED={str(config.trend_filter_enabled).lower()}")
    env_lines.append(f"STRATEGY_TREND_BAR_SPEC={config.trend_bar_spec}")
    env_lines.append(f"STRATEGY_TREND_EMA_PERIOD={config.trend_ema_period}")
    env_lines.append(f"STRATEGY_TREND_EMA_THRESHOLD_PIPS={config.trend_ema_threshold_pips}")
    env_lines.append("")
    
    # RSI filter
    env_lines.append("# RSI Filter")
    env_lines.append(f"STRATEGY_RSI_ENABLED={str(config.rsi_enabled).lower()}")
    env_lines.append(f"STRATEGY_RSI_PERIOD={config.rsi_period}")
    env_lines.append(f"STRATEGY_RSI_OVERBOUGHT={config.rsi_overbought}")
    env_lines.append(f"STRATEGY_RSI_OVERSOLD={config.rsi_oversold}")
    env_lines.append(f"STRATEGY_RSI_DIVERGENCE_LOOKBACK={config.rsi_divergence_lookback}")
    env_lines.append("")
    
    # Volume filter
    env_lines.append("# Volume Filter")
    env_lines.append(f"STRATEGY_VOLUME_ENABLED={str(config.volume_enabled).lower()}")
    env_lines.append(f"STRATEGY_VOLUME_AVG_PERIOD={config.volume_avg_period}")
    env_lines.append(f"STRATEGY_VOLUME_MIN_MULTIPLIER={config.volume_min_multiplier}")
    env_lines.append("")
    
    # ATR filter
    env_lines.append("# ATR Filter")
    env_lines.append(f"STRATEGY_ATR_ENABLED={str(config.atr_enabled).lower()}")
    env_lines.append(f"STRATEGY_ATR_PERIOD={config.atr_period}")
    env_lines.append(f"STRATEGY_ATR_MIN_STRENGTH={config.atr_min_strength}")
    env_lines.append("")
    
    # DMI filter
    env_lines.append("# DMI Filter")
    env_lines.append(f"STRATEGY_DMI_ENABLED={str(config.dmi_enabled).lower()}")
    env_lines.append(f"STRATEGY_DMI_BAR_SPEC={config.dmi_bar_spec}")
    env_lines.append(f"STRATEGY_DMI_PERIOD={config.dmi_period}")
    env_lines.append("")
    
    # Stochastic filter
    env_lines.append("# Stochastic Filter")
    env_lines.append(f"STRATEGY_STOCH_ENABLED={str(config.stoch_enabled).lower()}")
    env_lines.append(f"STRATEGY_STOCH_BAR_SPEC={config.stoch_bar_spec}")
    env_lines.append(f"STRATEGY_STOCH_PERIOD_K={config.stoch_period_k}")
    env_lines.append(f"STRATEGY_STOCH_PERIOD_D={config.stoch_period_d}")
    env_lines.append(f"STRATEGY_STOCH_BULLISH_THRESHOLD={config.stoch_bullish_threshold}")
    env_lines.append(f"STRATEGY_STOCH_BEARISH_THRESHOLD={config.stoch_bearish_threshold}")
    env_lines.append(f"STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING={config.stoch_max_bars_since_crossing}")
    env_lines.append("")
    
    # Time filter
    env_lines.append("# Time Filter")
    env_lines.append(f"BACKTEST_TIME_FILTER_ENABLED={str(config.time_filter_enabled).lower()}")
    env_lines.append(f"BACKTEST_EXCLUDED_HOURS={','.join(map(str, config.excluded_hours)) if config.excluded_hours else ''}")
    env_lines.append(f"BACKTEST_EXCLUDED_HOURS_MODE={config.excluded_hours_mode}")
    
    # Write weekday-specific exclusions if in weekday mode
    if config.excluded_hours_mode == "weekday" and config.excluded_hours_by_weekday:
        for weekday, hours in config.excluded_hours_by_weekday.items():
            env_lines.append(f"BACKTEST_EXCLUDED_HOURS_{weekday.upper()}={','.join(map(str, hours)) if hours else ''}")
    
    env_lines.append("")
    
    # Entry timing
    env_lines.append("# Entry Timing (Pullback/Breakout Entry)")
    env_lines.append(f"STRATEGY_ENTRY_TIMING_ENABLED={str(config.entry_timing_enabled).lower()}")
    env_lines.append(f"STRATEGY_ENTRY_TIMING_BAR_SPEC={config.entry_timing_bar_spec}")
    env_lines.append(f"STRATEGY_ENTRY_TIMING_METHOD={config.entry_timing_method}")
    env_lines.append(f"STRATEGY_ENTRY_TIMING_TIMEOUT_BARS={config.entry_timing_timeout_bars}")
    env_lines.append("")
    
    # Duration-based trailing stop optimization
    env_lines.append("# Duration-Based Trailing Stop Optimization")
    env_lines.append(f"STRATEGY_TRAILING_DURATION_ENABLED={str(config.trailing_duration_enabled).lower()}")
    env_lines.append(f"STRATEGY_TRAILING_DURATION_THRESHOLD_HOURS={config.trailing_duration_threshold_hours}")
    env_lines.append(f"STRATEGY_TRAILING_DURATION_DISTANCE_PIPS={config.trailing_duration_distance_pips}")
    env_lines.append(f"STRATEGY_TRAILING_DURATION_REMOVE_TP={str(config.trailing_duration_remove_tp).lower()}")
    env_lines.append(f"STRATEGY_TRAILING_DURATION_ACTIVATE_IF_NOT_ACTIVE={str(config.trailing_duration_activate_if_not_active).lower()}")
    env_lines.append("")
    
    # Minimum hold time feature
    env_lines.append("# Minimum Hold Time Feature (Wider Initial Stops)")
    env_lines.append(f"STRATEGY_MIN_HOLD_TIME_ENABLED={str(config.min_hold_time_enabled).lower()}")
    env_lines.append(f"STRATEGY_MIN_HOLD_TIME_HOURS={config.min_hold_time_hours}")
    env_lines.append(f"STRATEGY_MIN_HOLD_TIME_STOP_MULTIPLIER={config.min_hold_time_stop_multiplier}")
    env_lines.append("")
    
    # Partial close on first trailing activation
    env_lines.append("# Partial Close on First Trailing Activation")
    env_lines.append(f"STRATEGY_PARTIAL_CLOSE_ENABLED={str(config.partial_close_enabled).lower()}")
    env_lines.append(f"STRATEGY_PARTIAL_CLOSE_FRACTION={config.partial_close_fraction}")
    env_lines.append(f"STRATEGY_PARTIAL_CLOSE_MOVE_SL_TO_BE={str(config.partial_close_move_sl_to_be).lower()}")
    env_lines.append(f"STRATEGY_PARTIAL_CLOSE_REMAINDER_TRAIL_MULTIPLIER={config.partial_close_remainder_trail_multiplier}")
    env_lines.append("")
    
    # First partial close BEFORE trailing activation
    env_lines.append("# First Partial Close BEFORE Trailing Activation")
    env_lines.append(f"STRATEGY_PARTIAL1_ENABLED={str(config.partial1_enabled).lower()}")
    env_lines.append(f"STRATEGY_PARTIAL1_FRACTION={config.partial1_fraction}")
    env_lines.append(f"STRATEGY_PARTIAL1_THRESHOLD_PIPS={config.partial1_threshold_pips}")
    env_lines.append(f"STRATEGY_PARTIAL1_MOVE_SL_TO_BE={str(config.partial1_move_sl_to_be).lower()}")
    env_lines.append("")
    
    # Market structure filter
    env_lines.append("# Market Structure Filter (Avoid Recent Extremes)")
    env_lines.append(f"STRATEGY_STRUCTURE_FILTER_ENABLED={str(config.structure_filter_enabled).lower()}")
    env_lines.append(f"STRATEGY_STRUCTURE_LOOKBACK_BARS={config.structure_lookback_bars}")
    env_lines.append(f"STRATEGY_STRUCTURE_BUFFER_PIPS={config.structure_buffer_pips}")
    env_lines.append(f"STRATEGY_STRUCTURE_MODE={config.structure_mode}")
    
    env_file_path = output_dir / ".env"
    env_file_path.write_text("\n".join(env_lines), encoding="utf-8")
    logger.info("Environment configuration saved to: %s", env_file_path)
    
    # Save FULL environment (all OS environment variables)
    full_env_lines = []
    full_env_lines.append("# COMPLETE ENVIRONMENT SNAPSHOT - All OS Environment Variables")
    full_env_lines.append(f"# Generated: {datetime.now().isoformat()}")
    full_env_lines.append("# This file contains ALL environment variables at the time of backtest execution")
    full_env_lines.append("")
    
    # Get all environment variables and sort them
    for key in sorted(os.environ.keys()):
        value = os.environ[key]
        # Escape special characters for .env format
        # Handle multiline values and quotes
        if '\n' in value or '\r' in value:
            # For multiline values, use JSON encoding
            value_escaped = json.dumps(value)
            full_env_lines.append(f'{key}={value_escaped}')
        elif '"' in value or "'" in value or ' ' in value:
            # Quote values with special characters
            value_escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            full_env_lines.append(f'{key}="{value_escaped}"')
        else:
            full_env_lines.append(f'{key}={value}')
    
    full_env_file_path = output_dir / ".env.full"
    full_env_file_path.write_text("\n".join(full_env_lines), encoding="utf-8")
    logger.info("Full environment snapshot saved to: %s", full_env_file_path)

    return stats


def generate_statistical_analysis(
    positions_df: pd.DataFrame,
    output_dir: Path,
    logger: logging.Logger,
) -> None:
    """
    Generate comprehensive statistical analysis report for trading hours, weekdays, and months.
    
    Creates:
    - trading_hours_analysis.txt: Comprehensive text report
    - hourly_pnl_overall.csv: PnL statistics by hour (overall)
    - hourly_pnl_by_weekday.csv: PnL statistics by hour and weekday
    - weekday_pnl_overall.csv: PnL statistics by weekday (overall)
    - weekday_pnl_by_month.csv: PnL statistics by weekday and month
    - monthly_pnl_analysis.csv: PnL statistics by month
    """
    try:
        # Parse timestamps and extract PnL
        if 'ts_opened' not in positions_df.columns:
            logger.warning("positions_df missing 'ts_opened' column, skipping statistical analysis")
            return
        
        if 'realized_pnl' not in positions_df.columns:
            logger.warning("positions_df missing 'realized_pnl' column, skipping statistical analysis")
            return
        
        pos = positions_df.copy()
        pos['ts_opened'] = pd.to_datetime(pos['ts_opened'])
        
        # Extract PnL value (handle different formats)
        if pos['realized_pnl'].dtype == 'object':
            pos['pnl_value'] = pos['realized_pnl'].str.replace(' USD', '', regex=False).str.replace('USD', '', regex=False).str.strip().astype(float)
        else:
            pos['pnl_value'] = pos['realized_pnl'].astype(float)
        
        pos['hour'] = pos['ts_opened'].dt.hour
        pos['weekday'] = pos['ts_opened'].dt.day_name()
        pos['month'] = pos['ts_opened'].dt.to_period('M').astype(str)
        pos['date'] = pos['ts_opened'].dt.date
        
        # ============================================================================
        # 1. HOURLY PnL ANALYSIS (OVERALL)
        # ============================================================================
        hourly_overall = pos.groupby('hour').agg({
            'pnl_value': ['sum', 'mean', 'count', 'std']
        }).reset_index()
        hourly_overall.columns = ['hour', 'total_pnl', 'avg_pnl', 'trade_count', 'std_pnl']
        # Calculate wins/losses correctly - merge to ensure all hours are included
        wins_df = pos[pos['pnl_value'] > 0].groupby('hour').size().reset_index(name='wins')
        losses_df = pos[pos['pnl_value'] < 0].groupby('hour').size().reset_index(name='losses')
        hourly_overall = hourly_overall.merge(wins_df, on='hour', how='left')
        hourly_overall = hourly_overall.merge(losses_df, on='hour', how='left')
        hourly_overall['wins'] = hourly_overall['wins'].fillna(0).astype(int)
        hourly_overall['losses'] = hourly_overall['losses'].fillna(0).astype(int)
        hourly_overall['win_rate'] = (hourly_overall['wins'] / hourly_overall['trade_count'] * 100).round(1)
        hourly_overall['std_pnl'] = hourly_overall['std_pnl'].fillna(0)
        hourly_overall = hourly_overall.sort_values('hour')
        hourly_overall.to_csv(output_dir / "hourly_pnl_overall.csv", index=False)
        
        # ============================================================================
        # 2. HOURLY PnL BY WEEKDAY (OVERALL)
        # ============================================================================
        hourly_weekday = pos.groupby(['hour', 'weekday']).agg({
            'pnl_value': ['sum', 'mean', 'count', 'std']
        }).reset_index()
        hourly_weekday.columns = ['hour', 'weekday', 'total_pnl', 'avg_pnl', 'trade_count', 'std_pnl']
        # Calculate wins/losses correctly
        wins_df = pos[pos['pnl_value'] > 0].groupby(['hour', 'weekday']).size().reset_index(name='wins')
        losses_df = pos[pos['pnl_value'] < 0].groupby(['hour', 'weekday']).size().reset_index(name='losses')
        hourly_weekday = hourly_weekday.merge(wins_df, on=['hour', 'weekday'], how='left')
        hourly_weekday = hourly_weekday.merge(losses_df, on=['hour', 'weekday'], how='left')
        hourly_weekday['wins'] = hourly_weekday['wins'].fillna(0).astype(int)
        hourly_weekday['losses'] = hourly_weekday['losses'].fillna(0).astype(int)
        hourly_weekday['win_rate'] = (hourly_weekday['wins'] / hourly_weekday['trade_count'] * 100).round(1)
        hourly_weekday['std_pnl'] = hourly_weekday['std_pnl'].fillna(0)
        hourly_weekday = hourly_weekday.sort_values(['weekday', 'hour'])
        hourly_weekday.to_csv(output_dir / "hourly_pnl_by_weekday.csv", index=False)
        
        # ============================================================================
        # 3. WEEKDAY PnL ANALYSIS (OVERALL)
        # ============================================================================
        weekday_overall = pos.groupby('weekday').agg({
            'pnl_value': ['sum', 'mean', 'count', 'std']
        }).reset_index()
        weekday_overall.columns = ['weekday', 'total_pnl', 'avg_pnl', 'trade_count', 'std_pnl']
        # Calculate wins/losses correctly - merge to ensure all weekdays are included
        wins_df = pos[pos['pnl_value'] > 0].groupby('weekday').size().reset_index(name='wins')
        losses_df = pos[pos['pnl_value'] < 0].groupby('weekday').size().reset_index(name='losses')
        weekday_overall = weekday_overall.merge(wins_df, on='weekday', how='left')
        weekday_overall = weekday_overall.merge(losses_df, on='weekday', how='left')
        weekday_overall['wins'] = weekday_overall['wins'].fillna(0).astype(int)
        weekday_overall['losses'] = weekday_overall['losses'].fillna(0).astype(int)
        weekday_overall['win_rate'] = (weekday_overall['wins'] / weekday_overall['trade_count'] * 100).round(1)
        weekday_overall['std_pnl'] = weekday_overall['std_pnl'].fillna(0)
        # Order by weekday (Monday to Sunday)
        weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        weekday_overall['weekday'] = pd.Categorical(weekday_overall['weekday'], categories=weekday_order, ordered=True)
        weekday_overall = weekday_overall.sort_values('weekday')
        weekday_overall.to_csv(output_dir / "weekday_pnl_overall.csv", index=False)
        
        # ============================================================================
        # 4. WEEKDAY PnL BY MONTH
        # ============================================================================
        weekday_month = pos.groupby(['month', 'weekday']).agg({
            'pnl_value': ['sum', 'mean', 'count', 'std']
        }).reset_index()
        weekday_month.columns = ['month', 'weekday', 'total_pnl', 'avg_pnl', 'trade_count', 'std_pnl']
        # Calculate wins/losses correctly
        wins_df = pos[pos['pnl_value'] > 0].groupby(['month', 'weekday']).size().reset_index(name='wins')
        losses_df = pos[pos['pnl_value'] < 0].groupby(['month', 'weekday']).size().reset_index(name='losses')
        weekday_month = weekday_month.merge(wins_df, on=['month', 'weekday'], how='left')
        weekday_month = weekday_month.merge(losses_df, on=['month', 'weekday'], how='left')
        weekday_month['wins'] = weekday_month['wins'].fillna(0).astype(int)
        weekday_month['losses'] = weekday_month['losses'].fillna(0).astype(int)
        weekday_month['win_rate'] = (weekday_month['wins'] / weekday_month['trade_count'] * 100).round(1)
        weekday_month['std_pnl'] = weekday_month['std_pnl'].fillna(0)
        weekday_month['weekday'] = pd.Categorical(weekday_month['weekday'], categories=weekday_order, ordered=True)
        weekday_month = weekday_month.sort_values(['month', 'weekday'])
        weekday_month.to_csv(output_dir / "weekday_pnl_by_month.csv", index=False)
        
        # ============================================================================
        # 5. MONTHLY PnL ANALYSIS
        # ============================================================================
        monthly = pos.groupby('month').agg({
            'pnl_value': ['sum', 'mean', 'count', 'std']
        }).reset_index()
        monthly.columns = ['month', 'total_pnl', 'avg_pnl', 'trade_count', 'std_pnl']
        # Calculate wins/losses correctly - merge to ensure all months are included
        wins_df = pos[pos['pnl_value'] > 0].groupby('month').size().reset_index(name='wins')
        losses_df = pos[pos['pnl_value'] < 0].groupby('month').size().reset_index(name='losses')
        monthly = monthly.merge(wins_df, on='month', how='left')
        monthly = monthly.merge(losses_df, on='month', how='left')
        monthly['wins'] = monthly['wins'].fillna(0).astype(int)
        monthly['losses'] = monthly['losses'].fillna(0).astype(int)
        monthly['win_rate'] = (monthly['wins'] / monthly['trade_count'] * 100).round(1)
        monthly['std_pnl'] = monthly['std_pnl'].fillna(0)
        monthly = monthly.sort_values('month')
        monthly.to_csv(output_dir / "monthly_pnl_analysis.csv", index=False)
        
        # ============================================================================
        # GENERATE COMPREHENSIVE TEXT REPORT
        # ============================================================================
        report_lines = []
        report_lines.append("=" * 100)
        report_lines.append("TRADING STATISTICAL ANALYSIS REPORT")
        report_lines.append("=" * 100)
        report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"Total Trades: {len(pos)}")
        report_lines.append(f"Total PnL: ${pos['pnl_value'].sum():.2f}")
        report_lines.append(f"Average PnL per Trade: ${pos['pnl_value'].mean():.2f}")
        report_lines.append(f"Overall Win Rate: {(pos['pnl_value'] > 0).sum() / len(pos) * 100:.1f}%")
        report_lines.append(f"Winning Trades: {(pos['pnl_value'] > 0).sum()}")
        report_lines.append(f"Losing Trades: {(pos['pnl_value'] < 0).sum()}")
        if (pos['pnl_value'] > 0).sum() > 0:
            report_lines.append(f"Average Win: ${pos[pos['pnl_value'] > 0]['pnl_value'].mean():.2f}")
        if (pos['pnl_value'] < 0).sum() > 0:
            report_lines.append(f"Average Loss: ${pos[pos['pnl_value'] < 0]['pnl_value'].mean():.2f}")
        report_lines.append("")
        
        # HOURLY ANALYSIS (OVERALL)
        report_lines.append("=" * 100)
        report_lines.append("1. TRADING HOURS PROFITABILITY (OVERALL - UTC)")
        report_lines.append("=" * 100)
        report_lines.append(f"{'Hour':<6} {'Trades':<8} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12} {'Wins':<8} {'Losses':<8}")
        report_lines.append("-" * 100)
        for _, row in hourly_overall.iterrows():
            win_rate_str = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "N/A"
            report_lines.append(
                f"{row['hour']:<6} {row['trade_count']:<8} ${row['total_pnl']:>13.2f}  "
                f"${row['avg_pnl']:>13.2f}  {win_rate_str:>10}  {row['wins']:<8} {row['losses']:<8}"
            )
        
        report_lines.append("\nBest Performing Hours (Top 10):")
        report_lines.append(f"{'Hour':<6} {'Trades':<8} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12}")
        report_lines.append("-" * 60)
        for _, row in hourly_overall.nlargest(10, 'total_pnl').iterrows():
            win_rate_str = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "N/A"
            report_lines.append(
                f"{row['hour']:<6} {row['trade_count']:<8} ${row['total_pnl']:>13.2f}  "
                f"${row['avg_pnl']:>13.2f}  {win_rate_str:>10}"
            )
        
        report_lines.append("\nWorst Performing Hours (Bottom 10):")
        report_lines.append(f"{'Hour':<6} {'Trades':<8} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12}")
        report_lines.append("-" * 60)
        for _, row in hourly_overall.nsmallest(10, 'total_pnl').iterrows():
            win_rate_str = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "N/A"
            report_lines.append(
                f"{row['hour']:<6} {row['trade_count']:<8} ${row['total_pnl']:>13.2f}  "
                f"${row['avg_pnl']:>13.2f}  {win_rate_str:>10}"
            )
        
        # HOURLY BY WEEKDAY
        report_lines.append("\n" + "=" * 100)
        report_lines.append("2. TRADING HOURS PROFITABILITY BY WEEKDAY (OVERALL)")
        report_lines.append("=" * 100)
        for weekday in weekday_order:
            weekday_hours = hourly_weekday[hourly_weekday['weekday'] == weekday]
            if not weekday_hours.empty:
                report_lines.append(f"\n{weekday}:")
                report_lines.append(f"{'Hour':<6} {'Trades':<8} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12}")
                report_lines.append("-" * 60)
                for _, row in weekday_hours.sort_values('hour').iterrows():
                    win_rate_str = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "N/A"
                    report_lines.append(
                        f"{row['hour']:<6} {row['trade_count']:<8} ${row['total_pnl']:>13.2f}  "
                        f"${row['avg_pnl']:>13.2f}  {win_rate_str:>10}"
                    )
        
        # WEEKDAY OVERALL
        report_lines.append("\n" + "=" * 100)
        report_lines.append("3. WEEKDAY PROFITABILITY (OVERALL)")
        report_lines.append("=" * 100)
        report_lines.append(f"{'Weekday':<12} {'Trades':<8} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12} {'Wins':<8} {'Losses':<8}")
        report_lines.append("-" * 100)
        for _, row in weekday_overall.iterrows():
            win_rate_str = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "N/A"
            report_lines.append(
                f"{row['weekday']:<12} {row['trade_count']:<8} ${row['total_pnl']:>13.2f}  "
                f"${row['avg_pnl']:>13.2f}  {win_rate_str:>10}  {row['wins']:<8} {row['losses']:<8}"
            )
        
        # WEEKDAY BY MONTH
        report_lines.append("\n" + "=" * 100)
        report_lines.append("4. WEEKDAY PROFITABILITY BY MONTH")
        report_lines.append("=" * 100)
        for month in sorted(weekday_month['month'].unique()):
            month_data = weekday_month[weekday_month['month'] == month]
            if not month_data.empty:
                report_lines.append(f"\n{month}:")
                report_lines.append(f"{'Weekday':<12} {'Trades':<8} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12}")
                report_lines.append("-" * 60)
                for _, row in month_data.iterrows():
                    win_rate_str = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "N/A"
                    report_lines.append(
                        f"{row['weekday']:<12} {row['trade_count']:<8} ${row['total_pnl']:>13.2f}  "
                        f"${row['avg_pnl']:>13.2f}  {win_rate_str:>10}"
                    )
        
        # MONTHLY ANALYSIS
        report_lines.append("\n" + "=" * 100)
        report_lines.append("5. MONTHLY PnL STATISTICS")
        report_lines.append("=" * 100)
        report_lines.append(f"{'Month':<12} {'Trades':<8} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12} {'Wins':<8} {'Losses':<8}")
        report_lines.append("-" * 100)
        for _, row in monthly.iterrows():
            win_rate_str = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "N/A"
            report_lines.append(
                f"{row['month']:<12} {row['trade_count']:<8} ${row['total_pnl']:>13.2f}  "
                f"${row['avg_pnl']:>13.2f}  {win_rate_str:>10}  {row['wins']:<8} {row['losses']:<8}"
            )
        
        report_lines.append("\nBest Performing Months:")
        report_lines.append(f"{'Month':<12} {'Trades':<8} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12}")
        report_lines.append("-" * 60)
        for _, row in monthly.nlargest(5, 'total_pnl').iterrows():
            win_rate_str = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "N/A"
            report_lines.append(
                f"{row['month']:<12} {row['trade_count']:<8} ${row['total_pnl']:>13.2f}  "
                f"${row['avg_pnl']:>13.2f}  {win_rate_str:>10}"
            )
        
        report_lines.append("\nWorst Performing Months:")
        report_lines.append(f"{'Month':<12} {'Trades':<8} {'Total PnL':<15} {'Avg PnL':<15} {'Win Rate':<12}")
        report_lines.append("-" * 60)
        for _, row in monthly.nsmallest(5, 'total_pnl').iterrows():
            win_rate_str = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "N/A"
            report_lines.append(
                f"{row['month']:<12} {row['trade_count']:<8} ${row['total_pnl']:>13.2f}  "
                f"${row['avg_pnl']:>13.2f}  {win_rate_str:>10}"
            )
        
        # Write report
        report_path = output_dir / "trading_hours_analysis.txt"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        logger.info("Statistical analysis report generated: %s", report_path)
        
    except Exception as e:
        logger.error("Failed to generate statistical analysis: %s", e, exc_info=True)


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
        adaptive_stop_mode=cfg.adaptive_stop_mode,
        adaptive_atr_period=cfg.adaptive_atr_period,
        tp_atr_mult=cfg.tp_atr_mult,
        sl_atr_mult=cfg.sl_atr_mult,
        trail_activation_atr_mult=cfg.trail_activation_atr_mult,
        trail_distance_atr_mult=cfg.trail_distance_atr_mult,
        volatility_window=cfg.volatility_window,
        volatility_sensitivity=cfg.volatility_sensitivity,
        min_stop_distance_pips=cfg.min_stop_distance_pips,
        regime_detection_enabled=cfg.regime_detection_enabled,
        regime_adx_trending_threshold=cfg.regime_adx_trending_threshold,
        regime_adx_ranging_threshold=cfg.regime_adx_ranging_threshold,
        regime_tp_multiplier_trending=cfg.regime_tp_multiplier_trending,
        regime_tp_multiplier_ranging=cfg.regime_tp_multiplier_ranging,
        regime_sl_multiplier_trending=cfg.regime_sl_multiplier_trending,
        regime_sl_multiplier_ranging=cfg.regime_sl_multiplier_ranging,
        regime_trailing_activation_multiplier_trending=cfg.regime_trailing_activation_multiplier_trending,
        regime_trailing_activation_multiplier_ranging=cfg.regime_trailing_activation_multiplier_ranging,
        regime_trailing_distance_multiplier_trending=cfg.regime_trailing_distance_multiplier_trending,
        regime_trailing_distance_multiplier_ranging=cfg.regime_trailing_distance_multiplier_ranging,
        crossover_threshold_pips=cfg.crossover_threshold_pips,
        trend_filter_enabled=cfg.trend_filter_enabled,
        trend_bar_spec=cfg.trend_bar_spec,
        trend_ema_period=cfg.trend_ema_period,
        trend_ema_threshold_pips=cfg.trend_ema_threshold_pips,
        rsi_enabled=cfg.rsi_enabled,
        rsi_period=cfg.rsi_period,
        rsi_overbought=cfg.rsi_overbought,
        rsi_oversold=cfg.rsi_oversold,
        rsi_divergence_lookback=cfg.rsi_divergence_lookback,
        volume_enabled=cfg.volume_enabled,
        volume_avg_period=cfg.volume_avg_period,
        volume_min_multiplier=cfg.volume_min_multiplier,
        atr_enabled=cfg.atr_enabled,
        atr_period=cfg.atr_period,
        atr_min_strength=cfg.atr_min_strength,
        dmi_enabled=cfg.dmi_enabled,
        dmi_bar_spec=cfg.dmi_bar_spec,
        dmi_period=cfg.dmi_period,
        stoch_enabled=cfg.stoch_enabled,
        stoch_bar_spec=cfg.stoch_bar_spec,
        stoch_period_k=cfg.stoch_period_k,
        stoch_period_d=cfg.stoch_period_d,
        stoch_bullish_threshold=cfg.stoch_bullish_threshold,
        stoch_bearish_threshold=cfg.stoch_bearish_threshold,
        stoch_max_bars_since_crossing=cfg.stoch_max_bars_since_crossing,
        time_filter_enabled=cfg.time_filter_enabled,
        excluded_hours=cfg.excluded_hours,
        excluded_hours_mode=cfg.excluded_hours_mode,
        excluded_hours_by_weekday=cfg.excluded_hours_by_weekday,
        time_multiplier_enabled=cfg.time_multiplier_enabled,
        time_tp_multiplier_eu_morning=cfg.time_tp_multiplier_eu_morning,
        time_tp_multiplier_us_session=cfg.time_tp_multiplier_us_session,
        time_tp_multiplier_other=cfg.time_tp_multiplier_other,
        time_sl_multiplier_eu_morning=cfg.time_sl_multiplier_eu_morning,
        time_sl_multiplier_us_session=cfg.time_sl_multiplier_us_session,
        time_sl_multiplier_other=cfg.time_sl_multiplier_other,
        entry_timing_enabled=cfg.entry_timing_enabled,
        entry_timing_bar_spec=cfg.entry_timing_bar_spec,
        entry_timing_method=cfg.entry_timing_method,
        entry_timing_timeout_bars=cfg.entry_timing_timeout_bars,
        trailing_duration_enabled=cfg.trailing_duration_enabled,
        trailing_duration_threshold_hours=cfg.trailing_duration_threshold_hours,
        trailing_duration_distance_pips=cfg.trailing_duration_distance_pips,
        trailing_duration_remove_tp=cfg.trailing_duration_remove_tp,
        trailing_duration_activate_if_not_active=cfg.trailing_duration_activate_if_not_active,
        min_hold_time_enabled=cfg.min_hold_time_enabled,
        min_hold_time_hours=cfg.min_hold_time_hours,
        min_hold_time_stop_multiplier=cfg.min_hold_time_stop_multiplier,
        partial_close_enabled=cfg.partial_close_enabled,
        partial_close_fraction=cfg.partial_close_fraction,
        partial_close_move_sl_to_be=cfg.partial_close_move_sl_to_be,
        partial_close_remainder_trail_multiplier=cfg.partial_close_remainder_trail_multiplier,
        partial1_enabled=cfg.partial1_enabled,
        partial1_fraction=cfg.partial1_fraction,
        partial1_threshold_pips=cfg.partial1_threshold_pips,
        partial1_move_sl_to_be=cfg.partial1_move_sl_to_be,
        structure_filter_enabled=cfg.structure_filter_enabled,
        structure_lookback_bars=cfg.structure_lookback_bars,
        structure_buffer_pips=cfg.structure_buffer_pips,
        structure_mode=cfg.structure_mode,
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
