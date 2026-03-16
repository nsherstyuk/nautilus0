"""
V7 Live Trading Configuration

Defines the live trading parameters for the confirmed rebreak strategy.
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LiveConfig:
    """Live trading configuration for V7 confirmed rebreak strategy."""
    
    # IBKR connection
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 4002
    ibkr_client_id: int = 99
    
    # Instrument
    symbol: str = "XAUUSD"
    sec_type: str = "CMDTY"
    exchange: str = "SMART"
    currency: str = "USD"
    quantity: float = 1.0
    
    # Strategy parameters (match backtest best config)
    pivot_window: int = 60
    confirm_bars: int = 3
    max_hold_bars: int = 60
    sl_atr_multiple: float = 10.0
    min_bar_ticks: int = 50
    spread_cost: float = 0.30
    
    # Rolling buffer size (bars to keep in memory)
    buffer_size: int = 500
    
    # Bar aggregation
    bar_size_seconds: int = 60
    
    # Paths
    state_file: str = "v7_confirmed_rebreak/live/state/live_state.json"
    trade_log: str = "v7_confirmed_rebreak/live/logs/trades.csv"
    
    # Safety
    max_daily_trades: int = 10
    max_daily_loss: float = 100.0
    
    # Dry run mode
    dry_run: bool = False
    
    @classmethod
    def from_file(cls, path: str) -> "LiveConfig":
        """Load config from YAML (future enhancement)."""
        return cls()
    
    def validate(self):
        """Validate configuration."""
        assert self.pivot_window > 0
        assert self.confirm_bars >= 0
        assert self.max_hold_bars > 0
        assert self.buffer_size >= 2 * self.pivot_window + 100
        assert self.quantity > 0
