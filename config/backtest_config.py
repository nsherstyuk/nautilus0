"""
Backtest configuration management.

Provides a typed configuration object and loader for backtest parameters
sourced from environment variables.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class BacktestConfig:
    symbol: str
    venue: str = "SMART"
    start_date: str = ""
    end_date: str = ""
    bar_spec: str = "1-MINUTE-MID-EXTERNAL"
    fast_period: int = 10
    slow_period: int = 20
    trade_size: int = 100
    starting_capital: float = 100_000.0
    catalog_path: str = "data/historical"
    output_dir: str = "logs/backtest_results"
    enforce_position_limit: bool = True
    allow_position_reversal: bool = False


def _require(name: str, value: Optional[str]) -> str:
    if not value:
        raise ValueError(f"Environment variable {name} is required for backtesting")
    return value


def _parse_int(name: str, value: Optional[str], default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got: {value}")


def _parse_float(name: str, value: Optional[str], default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{name} must be a float, got: {value}")


def _validate_date(name: str, value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{name} must be in YYYY-MM-DD format, got: {value}")


def get_backtest_config() -> BacktestConfig:
    """Load backtest configuration from environment variables.

    Required env vars: BACKTEST_SYMBOL, BACKTEST_START_DATE, BACKTEST_END_DATE
    Optional with defaults: BACKTEST_VENUE, BACKTEST_BAR_SPEC, BACKTEST_FAST_PERIOD,
    BACKTEST_SLOW_PERIOD, BACKTEST_TRADE_SIZE, BACKTEST_STARTING_CAPITAL,
    CATALOG_PATH, OUTPUT_DIR, ENFORCE_POSITION_LIMIT, ALLOW_POSITION_REVERSAL
    """
    load_dotenv()

    symbol = _require("BACKTEST_SYMBOL", os.getenv("BACKTEST_SYMBOL"))
    start_date = _require("BACKTEST_START_DATE", os.getenv("BACKTEST_START_DATE"))
    end_date = _require("BACKTEST_END_DATE", os.getenv("BACKTEST_END_DATE"))

    _validate_date("BACKTEST_START_DATE", start_date)
    _validate_date("BACKTEST_END_DATE", end_date)

    venue = os.getenv("BACKTEST_VENUE", "SMART")
    bar_spec = os.getenv("BACKTEST_BAR_SPEC", "1-MINUTE-LAST-EXTERNAL")

    fast_period = _parse_int("BACKTEST_FAST_PERIOD", os.getenv("BACKTEST_FAST_PERIOD"), 10)
    slow_period = _parse_int("BACKTEST_SLOW_PERIOD", os.getenv("BACKTEST_SLOW_PERIOD"), 20)
    trade_size = _parse_int("BACKTEST_TRADE_SIZE", os.getenv("BACKTEST_TRADE_SIZE"), 100)
    starting_capital = _parse_float(
        "BACKTEST_STARTING_CAPITAL",
        os.getenv("BACKTEST_STARTING_CAPITAL"),
        100_000.0,
    )

    if fast_period >= slow_period:
        raise ValueError("BACKTEST_FAST_PERIOD must be less than BACKTEST_SLOW_PERIOD")

    catalog_path = os.getenv("CATALOG_PATH", "data/historical")
    output_dir = os.getenv("OUTPUT_DIR", "logs/backtest_results")
    enforce_position_limit = os.getenv("ENFORCE_POSITION_LIMIT", "true").lower() in ("true", "1", "yes")
    allow_position_reversal = os.getenv("ALLOW_POSITION_REVERSAL", "false").lower() in ("true", "1", "yes")

    # Normalize FX bar_spec for backtesting (Nautilus v1.220.0 format):
    # - Convert LAST->MID for forex pairs while preserving aggregation source.
    # - Ensure aggregation suffix present (default to -EXTERNAL for historical files).
    original_bar_spec = bar_spec
    if "/" in symbol:
        if "-LAST-EXTERNAL" in bar_spec:
            bar_spec = bar_spec.replace("-LAST-EXTERNAL", "-MID-EXTERNAL")
        elif "-LAST-INTERNAL" in bar_spec:
            bar_spec = bar_spec.replace("-LAST-INTERNAL", "-MID-INTERNAL")
        elif bar_spec.endswith("-LAST"):
            # Legacy format without aggregation source
            bar_spec = bar_spec[:-4] + "MID-EXTERNAL"
        elif "-MID" not in bar_spec and "-LAST" not in bar_spec:
            # Missing price side entirely (e.g., "1-MINUTE"), default to MID for FX
            if bar_spec.endswith("-EXTERNAL") or bar_spec.endswith("-INTERNAL"):
                suffix = "-EXTERNAL" if bar_spec.endswith("-EXTERNAL") else "-INTERNAL"
                bar_spec = bar_spec[: -len(suffix)] + "-MID" + suffix
            else:
                bar_spec = f"{bar_spec}-MID"

        # Ensure aggregation suffix present for FX bars (e.g., 1-MINUTE-MID -> 1-MINUTE-MID-EXTERNAL)
        if not bar_spec.endswith("-EXTERNAL") and not bar_spec.endswith("-INTERNAL"):
            bar_spec = f"{bar_spec}-EXTERNAL"

    logger = logging.getLogger(__name__)
    if bar_spec != original_bar_spec:
        logger.info(
            "Normalized bar_spec for %s: %s -> %s",
            symbol,
            original_bar_spec,
            bar_spec,
        )
    else:
        logger.debug("Bar_spec for %s already normalized: %s", symbol, bar_spec)

    return BacktestConfig(
        symbol=symbol,
        venue=venue,
        start_date=start_date,
        end_date=end_date,
        bar_spec=bar_spec,
        fast_period=fast_period,
        slow_period=slow_period,
        trade_size=trade_size,
        starting_capital=starting_capital,
        catalog_path=catalog_path,
        output_dir=output_dir,
        enforce_position_limit=enforce_position_limit,
        allow_position_reversal=allow_position_reversal,
    )


def validate_backtest_config(config: BacktestConfig) -> bool:
    """Validate backtest configuration and warn about potential issues."""
    ok = True

    # Date ordering
    sd = datetime.strptime(config.start_date, "%Y-%m-%d")
    ed = datetime.strptime(config.end_date, "%Y-%m-%d")
    if sd >= ed:
        ok = False

    # Periods
    if config.fast_period >= config.slow_period:
        ok = False

    # Catalog presence
    if not Path(config.catalog_path).exists():
        ok = False

    return ok
