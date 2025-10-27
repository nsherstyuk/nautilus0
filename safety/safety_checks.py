"""
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple
import datetime
import json
import os
import pathlib
import logging

logger = logging.getLogger("safety")

dataclass
class SafetyConfig:
    max_notional_usd: Decimal = Decimal(os.getenv("SAFETY_MAX_NOTIONAL_USD", "10000"))
    max_position_units: Decimal = Decimal(os.getenv("SAFETY_MAX_POSITION_UNITS", "100000"))
    daily_loss_limit_usd: Decimal = Decimal(os.getenv("SAFETY_DAILY_LOSS_LIMIT_USD", "500"))
    allow_live_trading: bool = os.getenv("LIVE_TRADING_ENABLED", "false").lower() in {"1", "true", "yes"}
    persistence_path: pathlib.Path = pathlib.Path(os.getenv("SAFETY_PERSISTENCE_PATH", "var/safety"))

    def ensure_dirs(self) -> None:
        self.persistence_path.mkdir(parents=True, exist_ok=True)

class SafetyState:
    def __init__(self, config: SafetyConfig):
        self.config = config
        self.config.ensure_dirs()
        self._daily_loss_file = self.config.persistence_path / "daily_pnl.json"

    def _read_daily_pnl(self) -> Decimal:
        if not self._daily_loss_file.exists():
            return Decimal("0")
        try:
            raw = json.loads(self._daily_loss_file.read_text(encoding="utf-8"))
            return Decimal(str(raw.get("realized_loss_usd", "0")))
        except Exception as e:
            logger.warning("Failed to read daily pnl file: %s", e)
            return Decimal("0")

    def _write_daily_pnl(self, value: Decimal) -> None:
        payload = {"realized_loss_usd": str(value), "ts": datetime.datetime.utcnow().isoformat()}
        try:
            self._daily_loss_file.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to write daily pnl: %s", e)

    def add_realized_loss(self, loss_usd: Decimal) -> None:
        cur = self._read_daily_pnl()
        new = cur + abs(loss_usd)
        self._write_daily_pnl(new)

    def get_realized_loss(self) -> Decimal:
        return self._read_daily_pnl()

def pre_trade_check(
    safety_config: SafetyConfig,
    safety_state: SafetyState,
    account_balance_usd: Decimal,
    current_position_units: Decimal,
    order_notional_usd: Decimal,
    is_live_mode: bool,
) -> Tuple[bool, Optional[str]]:
    """
    Returns (allowed, reason_if_blocked).
    - account_balance_usd: usable cash/margin in USD.
    - current_position_units: absolute units currently held in base units (strategy-specific).
    - order_notional_usd: estimated notional value of the order in USD.
    - is_live_mode: True if executing in live mode.
    """
    # 1) Paper-only default
    if is_live_mode and not safety_config.allow_live_trading:
        return False, "Live trading disabled by configuration (LIVE_TRADING_ENABLED=false)."

    # 2) Notional limit
    if order_notional_usd > safety_config.max_notional_usd:
        return False, f"Order notional {order_notional_usd} exceeds max_notional {safety_config.max_notional_usd}"

    # 3) Position limit
    if (abs(current_position_units) + abs(order_notional_usd)) > safety_config.max_position_units:
        return False, "Position limit breach would occur."

    # 4) Daily loss check
    realized_loss = safety_state.get_realized_loss()
    if realized_loss >= safety_config.daily_loss_limit_usd:
        return False, f"Daily loss limit reached: {realized_loss} >= {safety_config.daily_loss_limit_usd}"

    # 5) Basic balance sanity
    if account_balance_usd <= 0:
        return False, "Account balance non-positive or unavailable."

    # Passed all checks
    return True, None
