"""Live trading configuration management.

Provides a typed configuration object and loader for live trading parameters
sourced from environment variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class LiveConfig:
    symbol: str
    venue: str = "SMART"
    bar_spec: str = "1-MINUTE-LAST"
    fast_period: int = 10
    slow_period: int = 20
    trade_size: int = 100
    enforce_position_limit: bool = True
    allow_position_reversal: bool = False
    log_dir: str = "logs/live"
    trader_id: str = "LIVE-TRADER-001"


def _require(name: str, value: Optional[str]) -> str:
    if not value:
        raise ValueError(f"Environment variable {name} is required for live trading")
    return value


def _parse_int(name: str, value: Optional[str], default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - validation
        raise ValueError(f"{name} must be an integer, got: {value}") from exc


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes")


def get_live_config() -> LiveConfig:
    """Load live trading configuration from environment variables."""
    load_dotenv()

    symbol = _require("LIVE_SYMBOL", os.getenv("LIVE_SYMBOL"))
    venue = os.getenv("LIVE_VENUE", "SMART")
    bar_spec = os.getenv("LIVE_BAR_SPEC", "1-MINUTE-LAST")

    fast_period = _parse_int("LIVE_FAST_PERIOD", os.getenv("LIVE_FAST_PERIOD"), 10)
    slow_period = _parse_int("LIVE_SLOW_PERIOD", os.getenv("LIVE_SLOW_PERIOD"), 20)
    trade_size = _parse_int("LIVE_TRADE_SIZE", os.getenv("LIVE_TRADE_SIZE"), 100)

    if fast_period >= slow_period:
        raise ValueError("LIVE_FAST_PERIOD must be less than LIVE_SLOW_PERIOD")

    enforce_position_limit = _parse_bool(os.getenv("LIVE_ENFORCE_POSITION_LIMIT"), True)
    allow_position_reversal = _parse_bool(os.getenv("LIVE_ALLOW_POSITION_REVERSAL"), False)
    log_dir = os.getenv("LIVE_LOG_DIR", "logs/live")
    trader_id = os.getenv("LIVE_TRADER_ID", "LIVE-TRADER-001")

    return LiveConfig(
        symbol=symbol,
        venue=venue,
        bar_spec=bar_spec,
        fast_period=fast_period,
        slow_period=slow_period,
        trade_size=trade_size,
        enforce_position_limit=enforce_position_limit,
        allow_position_reversal=allow_position_reversal,
        log_dir=log_dir,
        trader_id=trader_id,
    )


def validate_live_config(config: LiveConfig) -> bool:
    """Validate live trading configuration."""
    ok = True

    if not config.symbol:
        ok = False

    if config.fast_period >= config.slow_period:
        ok = False

    try:
        Path(config.log_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        ok = False

    return ok
