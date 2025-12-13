"""
MTF V2 Configuration Loader
Loads settings from .env.mtf_v2 for the three-position bracket strategy.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


@dataclass
class MTFV2Config:
    """Configuration for MTF V2 Strategy."""
    
    # IBKR Connection
    ibkr_host: str
    ibkr_port: int
    ibkr_client_id: int
    ibkr_account: str
    ibkr_gateway: bool
    
    # Instrument
    instrument: str
    bar_type: str
    venue: str
    symbol: str
    bar_spec: str
    
    # Model
    model_path: str
    
    # Position Sizing
    total_position_size: int
    pos1_fraction: float
    pos2_fraction: float
    pos3_fraction: float
    
    # Stop Loss
    sl_atr_mult: float
    
    # Take Profit
    pos1_tp_atr_mult: float
    pos2_tp_atr_mult: float
    pos3_tp_atr_mult: float
    
    # Trailing Stop
    trailing_activation_atr_mult: float
    trailing_distance_atr_mult: float
    
    # Stall Detection (tighten SL if trade not progressing)
    stall_detection_enabled: bool
    stall_check_bars: int
    stall_min_profit_atr: float
    stall_sl_atr: float
    
    # Prediction
    prediction_threshold: float
    
    # Session
    trade_start_hour: int
    trade_end_hour: int
    config_timezone: str  # 'EST' or 'UTC' - timezone for excluded hours in config
    
    # Weekday-specific excluded hours (in config_timezone, converted to UTC internally)
    excluded_hours_mode: str  # 'simple' or 'weekday'
    excluded_hours_monday: list
    excluded_hours_tuesday: list
    excluded_hours_wednesday: list
    excluded_hours_thursday: list
    excluded_hours_friday: list
    excluded_hours_saturday: list
    excluded_hours_sunday: list
    
    # ATR Limits
    min_atr: float
    max_atr: float
    
    # Risk Management
    max_positions: int
    enforce_position_limit: bool
    
    # Backtest
    backtest_start: str
    backtest_end: str
    initial_balance: float
    
    # Convenience properties for live runner compatibility
    @property
    def ib_host(self) -> str:
        return self.ibkr_host
    
    @property
    def ib_port(self) -> int:
        return self.ibkr_port
    
    @property
    def ib_client_id(self) -> int:
        return self.ibkr_client_id
    
    @property
    def ib_account(self) -> str:
        return self.ibkr_account
    
    @property
    def ib_market_data_type(self) -> str:
        return "DELAYED_FROZEN"  # Default for V2
    
    def _est_hour_to_utc(self, est_hour: int, est_weekday: int) -> tuple:
        """
        Convert EST hour to UTC hour, handling day rollover.
        EST is UTC-5 (ignoring daylight saving for simplicity).
        
        Args:
            est_hour: Hour in EST (0-23)
            est_weekday: Weekday in EST (0=Monday, 6=Sunday)
            
        Returns:
            Tuple of (utc_hour, utc_weekday)
        """
        utc_hour = est_hour + 5  # EST + 5 = UTC
        utc_weekday = est_weekday
        
        if utc_hour >= 24:
            utc_hour -= 24
            utc_weekday = (est_weekday + 1) % 7  # Roll to next day
            
        return utc_hour, utc_weekday
    
    def _utc_hour_to_est(self, utc_hour: int, utc_weekday: int) -> tuple:
        """
        Convert UTC hour to EST hour, handling day rollover.
        
        Args:
            utc_hour: Hour in UTC (0-23)
            utc_weekday: Weekday in UTC (0=Monday, 6=Sunday)
            
        Returns:
            Tuple of (est_hour, est_weekday)
        """
        est_hour = utc_hour - 5  # UTC - 5 = EST
        est_weekday = utc_weekday
        
        if est_hour < 0:
            est_hour += 24
            est_weekday = (utc_weekday - 1) % 7  # Roll to previous day
            
        return est_hour, est_weekday
    
    def get_excluded_hours_for_weekday(self, weekday: int) -> list:
        """Get excluded hours for a specific weekday (0=Monday, 6=Sunday)."""
        if self.excluded_hours_mode != 'weekday':
            return []
        
        weekday_map = {
            0: self.excluded_hours_monday,
            1: self.excluded_hours_tuesday,
            2: self.excluded_hours_wednesday,
            3: self.excluded_hours_thursday,
            4: self.excluded_hours_friday,
            5: self.excluded_hours_saturday,
            6: self.excluded_hours_sunday,
        }
        return weekday_map.get(weekday, [])
    
    def is_hour_excluded_utc(self, utc_hour: int, utc_weekday: int) -> bool:
        """
        Check if a UTC hour is excluded, handling timezone conversion.
        
        If config_timezone is 'EST', converts UTC to EST for comparison.
        If config_timezone is 'UTC', compares directly.
        
        Args:
            utc_hour: Hour in UTC (0-23) - from bar timestamp
            utc_weekday: Weekday in UTC (0=Monday, 6=Sunday)
            
        Returns:
            True if hour should be excluded, False if allowed
        """
        if self.excluded_hours_mode != 'weekday':
            return False
            
        if self.config_timezone.upper() == 'EST':
            # Convert UTC to EST for comparison with config
            est_hour, est_weekday = self._utc_hour_to_est(utc_hour, utc_weekday)
            excluded = self.get_excluded_hours_for_weekday(est_weekday)
            return est_hour in excluded
        else:
            # Config is in UTC, compare directly
            excluded = self.get_excluded_hours_for_weekday(utc_weekday)
            return utc_hour in excluded
    
    def is_hour_allowed(self, utc_hour: int, utc_weekday: int) -> bool:
        """
        Check if trading is allowed at this UTC hour on this weekday.
        Handles timezone conversion based on config_timezone setting.
        
        Args:
            utc_hour: Hour in UTC (0-23) - from bar timestamp
            utc_weekday: Weekday in UTC (0=Monday, 6=Sunday)
        """
        # First check basic hour range (always in UTC)
        if not (self.trade_start_hour <= utc_hour < self.trade_end_hour):
            return False
        
        # Then check weekday-specific exclusions (handles timezone)
        if self.is_hour_excluded_utc(utc_hour, utc_weekday):
            return False
        
        return True


def _parse_hours(hours_str: str) -> list:
    """Parse comma-separated hours string to list of ints."""
    if not hours_str:
        return []
    return [int(h.strip()) for h in hours_str.split(',') if h.strip()]


def load_mtf_v2_config(env_file: Optional[str] = None) -> MTFV2Config:
    """Load MTF V2 configuration from .env.mtf_v2 file."""
    
    if env_file is None:
        project_root = Path(__file__).parent.parent
        env_file = project_root / ".env.mtf_v2"
    
    load_dotenv(env_file, override=True)
    
    # Parse instrument
    instrument = os.getenv("MTF2_INSTRUMENT", "EUR/USD.IDEALPRO")
    parts = instrument.split(".")
    symbol = parts[0] if parts else "EUR/USD"
    venue = parts[1] if len(parts) > 1 else "IDEALPRO"
    
    # Parse bar type for bar_spec
    bar_type = os.getenv("MTF2_BAR_TYPE", "EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL")
    # Extract bar spec from bar type (e.g., "15-MINUTE-MID-EXTERNAL")
    bar_spec = "-".join(bar_type.split("-")[1:]) if "-" in bar_type else "15-MINUTE-MID-EXTERNAL"
    
    return MTFV2Config(
        # IBKR Connection
        ibkr_host=os.getenv("MTF2_IBKR_HOST", "127.0.0.1"),
        ibkr_port=int(os.getenv("MTF2_IBKR_PORT", "7497")),
        ibkr_client_id=int(os.getenv("MTF2_IBKR_CLIENT_ID", "18")),
        ibkr_account=os.getenv("MTF2_IBKR_ACCOUNT", ""),
        ibkr_gateway=os.getenv("MTF2_IBKR_GATEWAY", "False").lower() == "true",
        
        # Instrument
        instrument=instrument,
        bar_type=bar_type,
        venue=venue,
        symbol=symbol,
        bar_spec=bar_spec,
        
        # Model
        model_path=os.getenv("MTF2_MODEL_PATH", "models/rf_model_mtf.joblib"),
        
        # Position Sizing (OPTIMIZED Dec 2025: 85/15 two-position)
        total_position_size=int(os.getenv("MTF2_TOTAL_POSITION_SIZE", "100000")),
        pos1_fraction=float(os.getenv("MTF2_POS1_FRACTION", "0.85")),
        pos2_fraction=float(os.getenv("MTF2_POS2_FRACTION", "0.15")),
        pos3_fraction=float(os.getenv("MTF2_POS3_FRACTION", "0.00")),
        
        # Stop Loss
        sl_atr_mult=float(os.getenv("MTF2_SL_ATR_MULT", "1.4")),
        
        # Take Profit
        pos1_tp_atr_mult=float(os.getenv("MTF2_POS1_TP_ATR_MULT", "0.6")),
        pos2_tp_atr_mult=float(os.getenv("MTF2_POS2_TP_ATR_MULT", "1.5")),
        pos3_tp_atr_mult=float(os.getenv("MTF2_POS3_TP_ATR_MULT", "1.5")),
        
        # Trailing Stop
        trailing_activation_atr_mult=float(os.getenv("MTF2_TRAILING_ACTIVATION_ATR_MULT", "0.6")),
        trailing_distance_atr_mult=float(os.getenv("MTF2_TRAILING_DISTANCE_ATR_MULT", "0.4")),
        
        # Stall Detection
        stall_detection_enabled=os.getenv("MTF2_STALL_DETECTION_ENABLED", "False").lower() == "true",
        stall_check_bars=int(os.getenv("MTF2_STALL_CHECK_BARS", "6")),
        stall_min_profit_atr=float(os.getenv("MTF2_STALL_MIN_PROFIT_ATR", "0.2")),
        stall_sl_atr=float(os.getenv("MTF2_STALL_SL_ATR", "0.2")),
        
        # Prediction
        prediction_threshold=float(os.getenv("MTF2_PREDICTION_THRESHOLD", "0.55")),
        
        # Session
        trade_start_hour=int(os.getenv("MTF2_TRADE_START_HOUR", "7")),
        trade_end_hour=int(os.getenv("MTF2_TRADE_END_HOUR", "20")),
        config_timezone=os.getenv("MTF2_CONFIG_TIMEZONE", "UTC"),  # 'EST' or 'UTC'
        
        # Weekday-specific excluded hours
        excluded_hours_mode=os.getenv("MTF2_EXCLUDED_HOURS_MODE", "simple"),
        excluded_hours_monday=_parse_hours(os.getenv("MTF2_EXCLUDED_HOURS_MONDAY", "")),
        excluded_hours_tuesday=_parse_hours(os.getenv("MTF2_EXCLUDED_HOURS_TUESDAY", "")),
        excluded_hours_wednesday=_parse_hours(os.getenv("MTF2_EXCLUDED_HOURS_WEDNESDAY", "")),
        excluded_hours_thursday=_parse_hours(os.getenv("MTF2_EXCLUDED_HOURS_THURSDAY", "")),
        excluded_hours_friday=_parse_hours(os.getenv("MTF2_EXCLUDED_HOURS_FRIDAY", "")),
        excluded_hours_saturday=_parse_hours(os.getenv("MTF2_EXCLUDED_HOURS_SATURDAY", "")),
        excluded_hours_sunday=_parse_hours(os.getenv("MTF2_EXCLUDED_HOURS_SUNDAY", "")),
        
        # ATR Limits
        min_atr=float(os.getenv("MTF2_MIN_ATR", "0.0003")),
        max_atr=float(os.getenv("MTF2_MAX_ATR", "0.005")),
        
        # Risk Management
        max_positions=int(os.getenv("MTF2_MAX_POSITIONS", "2")),
        enforce_position_limit=os.getenv("MTF2_ENFORCE_POSITION_LIMIT", "True").lower() == "true",
        
        # Backtest
        backtest_start=os.getenv("MTF2_BACKTEST_START", "2024-01-01"),
        backtest_end=os.getenv("MTF2_BACKTEST_END", "2025-12-30"),
        initial_balance=float(os.getenv("MTF2_INITIAL_BALANCE", "50000")),
    )


def print_mtf_v2_config(config: MTFV2Config):
    """Print configuration summary."""
    two_position_mode = config.pos3_fraction == 0
    mode_name = "Two-Position" if two_position_mode else "Three-Position"
    
    print("\n" + "=" * 70)
    print(f"MTF V2 CONFIGURATION ({mode_name} Bracket)")
    print("=" * 70)
    
    print("\n[Position Sizing]")
    print(f"  Total Size: {config.total_position_size:,}")
    print(f"  POS1 (Quick Win):  {config.pos1_fraction*100:.0f}% = {int(config.total_position_size * config.pos1_fraction):,}")
    print(f"  POS2 (Extended):   {config.pos2_fraction*100:.0f}% = {int(config.total_position_size * config.pos2_fraction):,}")
    if not two_position_mode:
        print(f"  POS3 (Runner):     {config.pos3_fraction*100:.0f}% = {int(config.total_position_size * config.pos3_fraction):,}")
    
    print("\n[Stop Loss / Take Profit]")
    print(f"  Initial SL (all):  {config.sl_atr_mult}x ATR")
    print(f"  POS1 TP:           {config.pos1_tp_atr_mult}x ATR")
    print(f"  POS2 TP:           {config.pos2_tp_atr_mult}x ATR")
    if not two_position_mode:
        print(f"  POS3 TP:           {config.pos3_tp_atr_mult}x ATR")
    
    if two_position_mode:
        print("\n[Trailing Stop (POS2 after POS1 TP)]")
    else:
        print("\n[Trailing Stop (POS3 after POS2 TP)]")
    print(f"  Activation:        {config.trailing_activation_atr_mult}x ATR")
    print(f"  Distance:          {config.trailing_distance_atr_mult}x ATR")
    
    print("\n[Stall Detection]")
    if config.stall_detection_enabled:
        print(f"  Enabled:           Yes")
        print(f"  Check after:       {config.stall_check_bars} bars ({config.stall_check_bars * 15} mins)")
        print(f"  Min profit:        {config.stall_min_profit_atr}x ATR")
        print(f"  Tighten SL to:     {config.stall_sl_atr}x ATR")
    else:
        print(f"  Enabled:           No")
    
    print("\n[Session & Filters]")
    print(f"  Trading Hours:     {config.trade_start_hour}:00 - {config.trade_end_hour}:00 UTC")
    print(f"  Config Timezone:   {config.config_timezone.upper()}")
    print(f"  Excluded Hours:    {config.excluded_hours_mode} mode")
    if config.excluded_hours_mode == 'weekday':
        tz = config.config_timezone.upper()
        print(f"    Monday:    {config.excluded_hours_monday} ({tz})")
        print(f"    Tuesday:   {config.excluded_hours_tuesday} ({tz})")
        print(f"    Wednesday: {config.excluded_hours_wednesday} ({tz})")
        print(f"    Thursday:  {config.excluded_hours_thursday} ({tz})")
        print(f"    Friday:    {config.excluded_hours_friday} ({tz})")
    print(f"  Prediction Thresh: {config.prediction_threshold}")
    print(f"  ATR Range:         {config.min_atr} - {config.max_atr}")
    
    print("\n[Risk Management]")
    num_pos = 2 if two_position_mode else 3
    print(f"  Max Positions:     {config.max_positions} (allows {num_pos} simultaneous)")
    
    print("=" * 70)


if __name__ == "__main__":
    config = load_mtf_v2_config()
    print_mtf_v2_config(config)
