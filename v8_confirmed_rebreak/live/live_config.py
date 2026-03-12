"""
Live trading configuration.

Separates broker/environment settings from pure strategy parameters.
Strategy parameters are in config/strategy_config.py.
"""
from dataclasses import dataclass, field


@dataclass
class LiveConfig:
    """Configuration for live trading via IBKR."""

    # IBKR connection
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497          # 7497=TWS paper, 4002=gateway paper
    ibkr_client_id: int = 10

    # Instrument
    symbol: str = "XAUUSD"
    exchange: str = "SMART"
    sec_type: str = "CMDTY"
    currency: str = "USD"

    # Strategy parameters (must match backtest config)
    pivot_window: int = 60
    confirm_bars: int = 3
    imbalance_window: int = 3
    divergence_threshold: float = 0.50
    max_pullback_bars: int = 60
    min_pullback_bars: int = 3
    sl_atr_multiple: float = 10.0
    tp_atr_multiple: float = 99.0
    max_hold_bars: int = 60
    atr_period: int = 60
    min_bar_ticks: int = 50
    spread_cost: float = 0.30

    # Rolling buffer
    buffer_size: int = 500         # bars to maintain in rolling buffer
    bar_seconds: int = 60          # bar aggregation period

    # Trade sizing
    quantity: float = 1.0          # lots per trade

    # Safety limits
    max_daily_trades: int = 20
    max_daily_loss: float = 500.0  # USD

    # Dry run mode (log signals but don't submit orders)
    dry_run: bool = True

    def validate(self) -> None:
        """Sanity check config values."""
        assert self.buffer_size >= 2 * self.pivot_window + 1, \
            f"buffer_size must be >= 2*pivot_window+1 = {2*self.pivot_window+1}"
        assert self.imbalance_window >= 1
        assert self.pivot_window >= 5
        assert self.bar_seconds in (60, 300, 900)
        assert self.max_daily_trades >= 1
        assert self.max_daily_loss > 0
