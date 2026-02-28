"""
config.py -- Load and validate v5 XAUUSD ORB configuration.

Reads config.yaml from the same directory and exposes a typed
dataclass-like namespace so every script uses the same settings.

Usage:
    from v5_xauusd_orb.config import cfg, ROOT

    print(cfg.strategy.rr_ratio)      # 2.0
    print(cfg.ibkr.port)              # 4002
    print(cfg.paths.log_dir)          # resolved Path
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml

# ── Project root (directory that contains v5_xauusd_orb/) ─────────────────
ROOT = Path(__file__).resolve().parents[1]
V5_DIR = Path(__file__).resolve().parent
CONFIG_FILE = V5_DIR / "config.yaml"


# ── Typed config sections ─────────────────────────────────────────────────

@dataclass
class StrategyConfig:
    asian_start_hour: int = 0
    asian_end_hour: int = 6
    trade_start_hour: int = 8
    trade_end_hour: int = 16
    rr_ratio: float = 2.0
    min_range_pct: float = 0.05
    max_range_pct: float = 2.0
    skip_weekdays: List[int] = field(default_factory=list)
    be_hours: int = 2
    be_offset_usd: float = 2.0     # move SL to entry + offset (covers costs)
    poll_interval: int = 10


@dataclass
class PositionConfig:
    qty: int = 1


@dataclass
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 60
    symbol: str = "XAUUSD"
    sec_type: str = "CFD"
    exchange: str = "SMART"
    currency: str = "USD"
    max_retries: int = 10
    base_backoff_sec: int = 5
    max_backoff_sec: int = 300
    heartbeat_interval_sec: int = 30
    connect_timeout_sec: int = 20


@dataclass
class GatewayConfig:
    exe_path: str = r"C:\Jts\ibgateway\1041\ibgateway.exe"
    process_name: str = "ibgateway.exe"
    paper_port: int = 4002
    live_port: int = 4001
    check_interval_sec: int = 60
    startup_wait_sec: int = 60
    restart_cooldown_sec: int = 300
    port_check_timeout_sec: int = 5
    max_consecutive_port_failures: int = 3


@dataclass
class PathsConfig:
    tick_bar_file: str = "trading_system_v4/data/xauusd_1000t_bars.parquet"
    log_dir: str = "v5_xauusd_orb/logs"
    state_dir: str = "v5_xauusd_orb/state"
    trade_log: str = "v5_xauusd_orb/logs/xauusd_orb_trades.csv"
    ibgw_log: str = "v5_xauusd_orb/logs/ibgw_manager.log"
    live_log: str = "v5_xauusd_orb/logs/xauusd_orb_live.log"

    # Resolved absolute paths (set after loading)
    _resolved: bool = field(default=False, repr=False)

    def resolve(self, root: Path):
        """Convert relative paths to absolute using project root."""
        for fld in ['tick_bar_file', 'log_dir', 'state_dir',
                     'trade_log', 'ibgw_log', 'live_log']:
            val = getattr(self, fld)
            p = Path(val)
            if not p.is_absolute():
                setattr(self, fld, str(root / p))
        self._resolved = True


@dataclass
class SignalConfig:
    history_days: int = 30


@dataclass
class Config:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    position: PositionConfig = field(default_factory=PositionConfig)
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)


# ── Loader ─────────────────────────────────────────────────────────────────

def _merge(dc, raw: dict):
    """Merge a raw dict into a dataclass, ignoring unknown keys."""
    if raw is None:
        return
    for key, val in raw.items():
        if key.startswith('_'):
            continue
        if hasattr(dc, key):
            setattr(dc, key, val)


def load_config(path: Path | str | None = None) -> Config:
    """Load config from YAML. Falls back to defaults for missing keys."""
    if path is None:
        path = CONFIG_FILE

    path = Path(path)
    cfg = Config()

    if path.exists():
        with open(path, 'r') as f:
            raw = yaml.safe_load(f) or {}

        _merge(cfg.strategy, raw.get('strategy'))
        _merge(cfg.position, raw.get('position'))
        _merge(cfg.ibkr, raw.get('ibkr'))
        _merge(cfg.gateway, raw.get('gateway'))
        _merge(cfg.paths, raw.get('paths'))
        _merge(cfg.signal, raw.get('signal'))
    else:
        import warnings
        warnings.warn(f"Config file not found: {path}  -- using defaults")

    # Resolve relative paths
    cfg.paths.resolve(ROOT)

    # Ensure log/state dirs exist
    Path(cfg.paths.log_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.paths.state_dir).mkdir(parents=True, exist_ok=True)

    return cfg


# ── Module-level singleton ─────────────────────────────────────────────────
cfg = load_config()


if __name__ == "__main__":
    # Quick sanity check
    print(f"Config loaded from: {CONFIG_FILE}")
    print(f"  strategy.rr_ratio      = {cfg.strategy.rr_ratio}")
    print(f"  strategy.skip_weekdays = {cfg.strategy.skip_weekdays}")
    print(f"  ibkr.port              = {cfg.ibkr.port}")
    print(f"  ibkr.symbol            = {cfg.ibkr.symbol}")
    print(f"  position.qty           = {cfg.position.qty}")
    print(f"  gateway.exe_path       = {cfg.gateway.exe_path}")
    print(f"  paths.tick_bar_file    = {cfg.paths.tick_bar_file}")
    print(f"  paths.log_dir          = {cfg.paths.log_dir}")
    print(f"  paths.state_dir        = {cfg.paths.state_dir}")
    print(f"  signal.history_days    = {cfg.signal.history_days}")
