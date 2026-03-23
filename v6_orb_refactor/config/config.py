from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass(frozen=True)
class StrategyConfig:
    """Pure strategy parameters.
    Environment-agnostic: no file paths, API keys, or broker settings.
    """
    instrument: str

    # Time Windows (in UTC)
    range_start_hour: int = 0
    range_end_hour: int = 6
    trade_start_hour: int = 8
    trade_end_hour: int = 16

    # Days to avoid trading (0 = Monday, 6 = Sunday)
    skip_weekdays: tuple = ()

    # Velocity Filter
    velocity_filter_enabled: bool = True
    velocity_lookback_minutes: int = 3
    velocity_threshold: float = 200.0

    # Trade Management
    rr_ratio: float = 2.5

    # Range validity (absolute price units, e.g. dollars for XAUUSD)
    min_range_size: float = 1.0
    max_range_size: float = 15.0

    # Range validity as % of price (used if > 0, overrides absolute)
    min_range_pct: float = 0.05
    max_range_pct: float = 2.0

    # Breakeven: move SL to entry + offset after N hours (999 = disabled)
    be_hours: float = 999
    be_offset: float = 2.0

    # Cancel unfilled entries after N hours (0 = full window)
    max_pending_hours: int = 4

    # Close at market after N minutes in trade (0 = disabled)
    time_exit_minutes: int = 0

    # Gap Filter (06:00-08:00 UTC pre-trade window analysis)
    # Rolling gap volatility: skip day if gap vol < trailing percentile
    gap_filter_enabled: bool = False
    gap_vol_percentile: float = 50.0      # Rolling percentile threshold (P50)
    gap_range_filter_enabled: bool = False # Optional second filter
    gap_range_percentile: float = 40.0    # Rolling percentile for gap range
    gap_rolling_days: int = 60            # Trailing window for percentile calc
    gap_start_hour: int = 6              # Gap period start (UTC)
    gap_end_hour: int = 8                # Gap period end (UTC)

    # Position sizing
    qty: int = 1
    point_value: float = 1.0

    # Display
    price_decimals: int = 2


@dataclass
class IBKRConfig:
    """IBKR connection and contract settings."""
    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 60
    symbol: str = "XAUUSD"
    sec_type: str = "CMDTY"
    exchange: str = "SMART"
    currency: str = "USD"
    max_retries: int = 10
    base_backoff_sec: int = 5
    max_backoff_sec: int = 300
    heartbeat_interval_sec: int = 30
    connect_timeout_sec: int = 20


@dataclass
class PathsConfig:
    """File paths for logs, state, and data."""
    log_dir: str = "v6_orb_refactor/logs"
    state_dir: str = "v6_orb_refactor/state"
    trade_log: str = "v6_orb_refactor/logs/orb_trades.csv"
    live_log: str = "v6_orb_refactor/logs/orb_live.log"

    def resolve(self, root: Path):
        for fld in ('log_dir', 'state_dir', 'trade_log', 'live_log'):
            val = getattr(self, fld)
            p = Path(val)
            if not p.is_absolute():
                setattr(self, fld, str(root / p))

    def ensure_dirs(self):
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        Path(self.state_dir).mkdir(parents=True, exist_ok=True)


@dataclass
class GuardrailsConfig:
    """Safety limits for live trading."""
    daily_loss_limit_usd: float = 50.0
    max_positions_per_instrument: int = 1
    cancel_orphaned_orders: bool = True
    close_orphaned_positions: bool = True


@dataclass
class LiveConfig:
    """Complete live trading configuration.
    Composes strategy, broker, paths, and safety settings.
    """
    strategy: StrategyConfig = field(default_factory=lambda: StrategyConfig(instrument="XAUUSD"))
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    guardrails: GuardrailsConfig = field(default_factory=GuardrailsConfig)
    poll_interval: int = 2
    dry_run: bool = False


def _merge(dc, raw: dict):
    """Merge a raw dict into a dataclass, ignoring unknown keys."""
    if raw is None:
        return
    for key, val in raw.items():
        if key.startswith('_'):
            continue
        if hasattr(dc, key):
            setattr(dc, key, val)


def load_live_config(yaml_path: Optional[str] = None,
                     instrument: str = "XAUUSD") -> LiveConfig:
    """Load LiveConfig from V5-format config.yaml.

    Reads the 'instruments' section for the given instrument name,
    plus ibkr, paths, and guardrails sections.
    """
    if yaml_path is None:
        # Default: look for config.yaml in v5_xauusd_orb/
        root = Path(__file__).resolve().parents[2]
        yaml_path = str(root / "v5_xauusd_orb" / "config.yaml")

    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, 'r') as f:
        raw = yaml.safe_load(f) or {}

    # Build StrategyConfig from instruments section
    instruments_raw = raw.get('instruments', {})
    inst_raw = instruments_raw.get(instrument, {})

    strategy = StrategyConfig(
        instrument=instrument,
        range_start_hour=inst_raw.get('asian_start_hour', 0),
        range_end_hour=inst_raw.get('asian_end_hour', 6),
        trade_start_hour=inst_raw.get('trade_start_hour', 8),
        trade_end_hour=inst_raw.get('trade_end_hour', 16),
        skip_weekdays=tuple(inst_raw.get('skip_weekdays', [])),
        velocity_filter_enabled=inst_raw.get('velocity_filter_enabled', True),
        velocity_lookback_minutes=inst_raw.get('velocity_lookback_minutes', 3),
        velocity_threshold=float(inst_raw.get('velocity_threshold', 200)),
        rr_ratio=float(inst_raw.get('rr_ratio', 2.5)),
        min_range_size=float(inst_raw.get('min_range_size', 1.0)),
        max_range_size=float(inst_raw.get('max_range_size', 15.0)),
        min_range_pct=float(inst_raw.get('min_range_pct', 0.05)),
        max_range_pct=float(inst_raw.get('max_range_pct', 2.0)),
        be_hours=float(inst_raw.get('be_hours', 999)),
        be_offset=float(inst_raw.get('be_offset', 2.0)),
        max_pending_hours=int(inst_raw.get('max_pending_hours', 4)),
        time_exit_minutes=int(inst_raw.get('time_exit_minutes', 0)),
        qty=int(inst_raw.get('qty', 1)),
        point_value=float(inst_raw.get('point_value', 1.0)),
        price_decimals=int(inst_raw.get('price_decimals', 2)),
        # Gap filter
        gap_filter_enabled=bool(inst_raw.get('gap_filter_enabled', False)),
        gap_vol_percentile=float(inst_raw.get('gap_vol_percentile', 50.0)),
        gap_range_filter_enabled=bool(inst_raw.get('gap_range_filter_enabled', False)),
        gap_range_percentile=float(inst_raw.get('gap_range_percentile', 40.0)),
        gap_rolling_days=int(inst_raw.get('gap_rolling_days', 60)),
        gap_start_hour=int(inst_raw.get('gap_start_hour', 6)),
        gap_end_hour=int(inst_raw.get('gap_end_hour', 8)),
    )

    # Build IBKRConfig
    ibkr = IBKRConfig()
    ibkr_raw = raw.get('ibkr', {})
    _merge(ibkr, ibkr_raw)
    # Override contract from instrument section
    ibkr.symbol = inst_raw.get('symbol', ibkr.symbol)
    ibkr.sec_type = inst_raw.get('sec_type', ibkr.sec_type)
    ibkr.exchange = inst_raw.get('exchange', ibkr.exchange)
    ibkr.currency = inst_raw.get('currency', ibkr.currency)

    # Build PathsConfig
    paths = PathsConfig(
        log_dir=f"v6_orb_refactor/logs",
        state_dir=f"v6_orb_refactor/state",
        trade_log=f"v6_orb_refactor/logs/orb_{instrument.lower()}_trades.csv",
        live_log=f"v6_orb_refactor/logs/orb_{instrument.lower()}_live.log",
    )
    root = Path(__file__).resolve().parents[2]
    paths.resolve(root)
    paths.ensure_dirs()

    # Build GuardrailsConfig
    guardrails = GuardrailsConfig()
    gr_raw = raw.get('guardrails', {})
    if gr_raw:
        _merge(guardrails, gr_raw)

    poll_interval = raw.get('strategy', {}).get('poll_interval', 2)

    return LiveConfig(
        strategy=strategy,
        ibkr=ibkr,
        paths=paths,
        guardrails=guardrails,
        poll_interval=poll_interval,
    )
