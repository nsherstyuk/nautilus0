"""Production live trading configuration loader and validator."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from config.live_config import LiveConfig

_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-(.*))?\}")
_DEFAULT_CONFIG_PATH = Path("config/live_trading.yaml")


@dataclass
class ProductionConfig(LiveConfig):
    """Extended configuration including production risk controls."""

    starting_capital: float = 100_000.0
    max_daily_loss_pct: float = 2.0
    max_daily_loss_absolute: float = 1_000.0
    max_position_value: float = 50_000.0
    max_total_exposure: float = 100_000.0
    position_limit: int = 1

    enable_circuit_breakers: bool = True
    max_consecutive_losses: int = 5
    max_orders_per_minute: int = 10
    cooldown_period_minutes: int = 30

    require_paper_account: bool = True
    trading_hours_only: bool = True
    enable_position_monitoring: bool = True
    alert_on_fill: bool = True

    account_id: str = ""
    operator_email: str = ""
    operator_phone: str = ""


def _substitute_env_vars(raw: Any) -> Any:
    """Recursively substitute ${VAR} patterns with environment variables."""

    if isinstance(raw, dict):
        return {key: _substitute_env_vars(value) for key, value in raw.items()}
    if isinstance(raw, list):
        return [_substitute_env_vars(item) for item in raw]
    if isinstance(raw, str):
        match = _ENV_PATTERN.fullmatch(raw)
        if match:
            var_name, default = match.groups()
            value = os.getenv(var_name)
            if value is None:
                if default is not None:
                    return default
                raise ValueError(f"Environment variable {var_name} is required but not set")
            return value
        return raw
    return raw


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def load_production_config(path: Path | None = None) -> ProductionConfig:
    """Load the production configuration from YAML."""

    config_path = path or _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Production config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    substituted = _substitute_env_vars(raw)

    trading: Dict[str, Any] = substituted.get("trading", {})
    risk: Dict[str, Any] = substituted.get("risk_management", {})
    breakers: Dict[str, Any] = substituted.get("circuit_breakers", {})
    safety: Dict[str, Any] = substituted.get("safety", {})
    account: Dict[str, Any] = substituted.get("account", {})

    base = ProductionConfig(
        symbol=trading.get("symbol", ""),
        venue=trading.get("venue", "SMART"),
        bar_spec=trading.get("bar_spec", "1-MINUTE-LAST"),
        fast_period=_to_int(trading.get("fast_period", 10), 10),
        slow_period=_to_int(trading.get("slow_period", 20), 20),
        trade_size=_to_int(trading.get("trade_size", 100), 100),
        starting_capital=_to_float(trading.get("starting_capital", 100_000.0), 100_000.0),
        enforce_position_limit=_to_bool(trading.get("enforce_position_limit", True), True),
        allow_position_reversal=_to_bool(trading.get("allow_position_reversal", False), False),
        log_dir="logs/live",
        trader_id=account.get("account_id", "LIVE-TRADER-001"),
    )

    base.max_daily_loss_pct = _to_float(risk.get("max_daily_loss_pct", base.max_daily_loss_pct), base.max_daily_loss_pct)
    base.max_daily_loss_absolute = _to_float(
        risk.get("max_daily_loss_absolute", base.max_daily_loss_absolute), base.max_daily_loss_absolute
    )
    base.max_position_value = _to_float(risk.get("max_position_value", base.max_position_value), base.max_position_value)
    base.max_total_exposure = _to_float(risk.get("max_total_exposure", base.max_total_exposure), base.max_total_exposure)
    base.position_limit = _to_int(risk.get("position_limit", base.position_limit), base.position_limit)

    base.enable_circuit_breakers = _to_bool(breakers.get("enable_circuit_breakers", base.enable_circuit_breakers), base.enable_circuit_breakers)
    base.max_consecutive_losses = _to_int(breakers.get("max_consecutive_losses", base.max_consecutive_losses), base.max_consecutive_losses)
    base.max_orders_per_minute = _to_int(breakers.get("max_orders_per_minute", base.max_orders_per_minute), base.max_orders_per_minute)
    base.cooldown_period_minutes = _to_int(breakers.get("cooldown_period_minutes", base.cooldown_period_minutes), base.cooldown_period_minutes)

    base.require_paper_account = _to_bool(safety.get("require_paper_account", base.require_paper_account), base.require_paper_account)
    base.trading_hours_only = _to_bool(safety.get("trading_hours_only", base.trading_hours_only), base.trading_hours_only)
    base.enable_position_monitoring = _to_bool(
        safety.get("enable_position_monitoring", base.enable_position_monitoring), base.enable_position_monitoring
    )
    base.alert_on_fill = _to_bool(safety.get("alert_on_fill", base.alert_on_fill), base.alert_on_fill)

    base.account_id = str(account.get("account_id", ""))
    base.operator_email = str(account.get("operator_email", ""))
    base.operator_phone = str(account.get("operator_phone", ""))

    return base


def validate_production_config(config: ProductionConfig) -> Tuple[bool, List[str]]:
    """Validate production configuration parameters."""

    errors: List[str] = []

    if not config.symbol:
        errors.append("Trading symbol must be specified.")

    if config.fast_period >= config.slow_period:
        errors.append("Fast period must be less than slow period.")

    if not (0.1 <= config.max_daily_loss_pct <= 10.0):
        errors.append("max_daily_loss_pct must be between 0.1 and 10.0")

    if config.max_daily_loss_absolute <= 0:
        errors.append("max_daily_loss_absolute must be greater than zero")

    if config.max_position_value > config.max_total_exposure:
        errors.append("max_position_value cannot exceed max_total_exposure")

    if config.position_limit < 1:
        errors.append("position_limit must be at least 1")

    if config.max_consecutive_losses < 1:
        errors.append("max_consecutive_losses must be at least 1")

    if config.max_orders_per_minute < 1:
        errors.append("max_orders_per_minute must be at least 1")

    if config.cooldown_period_minutes < 1:
        errors.append("cooldown_period_minutes must be at least 1")

    if config.require_paper_account and config.account_id and not config.account_id.upper().startswith("DU"):
        errors.append("Account must be a paper trading account (starts with 'DU')")

    return len(errors) == 0, errors
