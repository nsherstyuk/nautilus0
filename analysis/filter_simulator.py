"""
Filter Simulator Tool

A comprehensive tool for simulating new filter ideas on historical backtest data to estimate PnL impact.
This tool loads backtest results, retrieves bar data from the catalog, calculates technical indicators,
implements multiple filter simulators, and generates detailed reports.

Usage Examples:
    # Basic simulation
    python analysis/filter_simulator.py --input logs/backtest_results/EUR-USD_20251013_200009 --catalog-path data/historical
    
    # With custom thresholds
    python analysis/filter_simulator.py --input results_dir --catalog-path catalog_dir --atr-min 0.0005 --atr-max 0.002 --adx-min 25 --time-start 08:00 --time-end 16:00
    
    # JSON export
    python analysis/filter_simulator.py --input results_dir --catalog-path catalog_dir --json --output reports/filter_simulation.html

Output Formats:
    - Console report (always): Formatted text output to stdout
    - HTML report (always): Comprehensive report with embedded charts
    - JSON export (optional): Structured data export with --json flag

Exit Codes:
    0: Success
    1: Error (file not found, invalid data, etc.)
    2: Invalid arguments

Filters Simulated:
    - ATR Volatility: Filter trades when ATR is too low (choppy) or too high (extreme volatility)
    - Time-of-Day: Filter trades outside specified trading hours
    - ADX Trend Strength: Filter trades when trend strength is weak (ADX < threshold)
    - Support/Resistance: Filter trades too close to detected S/R levels

The tool follows established patterns from analyze_filter_effectiveness.py for consistency.
"""

import argparse
import json
import logging
import sys
import re
import base64
import io
import statistics
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.model.data import Bar
from nautilus_trader.indicators import AverageTrueRange
from nautilus_trader.model.enums import MovingAverageType

from indicators.dmi import DMI
from utils.instruments import try_both_instrument_formats

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
DEFAULT_ATR_MIN_THRESHOLD = 0.0003  # Minimum ATR (below = choppy)
DEFAULT_ATR_MAX_THRESHOLD = 0.003   # Maximum ATR (above = extreme volatility)
DEFAULT_ADX_MIN_THRESHOLD = 20.0    # Minimum ADX (below = weak trend)
DEFAULT_TIME_START_HOUR = 8         # Trading start hour (UTC)
DEFAULT_TIME_END_HOUR = 16          # Trading end hour (UTC)
DEFAULT_SR_LOOKBACK_BARS = 50       # Support/resistance lookback window
DEFAULT_SR_DISTANCE_PIPS = 5.0      # Distance from S/R to filter (pips)
DEFAULT_ATR_PERIOD = 14             # ATR calculation period
DEFAULT_ADX_PERIOD = 14             # ADX calculation period


@dataclass
class FilterConfig:
    """Configuration for filter thresholds and settings."""
    atr_enabled: bool = False
    atr_min_threshold: float = DEFAULT_ATR_MIN_THRESHOLD
    atr_max_threshold: float = DEFAULT_ATR_MAX_THRESHOLD
    atr_period: int = DEFAULT_ATR_PERIOD
    time_filter_enabled: bool = False
    time_start_hour: int = DEFAULT_TIME_START_HOUR
    time_end_hour: int = DEFAULT_TIME_END_HOUR
    adx_enabled: bool = False
    adx_min_threshold: float = DEFAULT_ADX_MIN_THRESHOLD
    adx_period: int = DEFAULT_ADX_PERIOD
    sr_enabled: bool = False
    sr_lookback_bars: int = DEFAULT_SR_LOOKBACK_BARS
    sr_distance_pips: float = DEFAULT_SR_DISTANCE_PIPS


@dataclass
class TradeEvaluation:
    """Evaluation of a single trade against filters."""
    position_id: str
    entry_time: pd.Timestamp
    entry_price: float
    exit_price: float
    realized_pnl: float
    side: str  # LONG/SHORT
    atr_value: Optional[float] = None
    adx_value: Optional[float] = None
    nearest_sr_level: Optional[float] = None
    filtered_by_atr: bool = False
    filtered_by_time: bool = False
    filtered_by_adx: bool = False
    filtered_by_sr: bool = False
    filtered_overall: bool = False  # True if any filter rejects


@dataclass
class FilterImpact:
    """Impact statistics for a single filter."""
    filter_name: str
    trades_filtered: int
    winners_filtered: int
    losers_filtered: int
    pnl_of_filtered_trades: float
    estimated_pnl_improvement: float  # negative if filter removes winners
    filter_effectiveness: float  # 0-1 score based on losers removed vs winners removed


@dataclass
class SimulationReport:
    """Complete simulation report."""
    backtest_run_id: str
    catalog_path: str
    bar_type: str
    total_trades: int
    original_pnl: float
    rejected_signals_count: int
    filter_config: FilterConfig
    trade_evaluations: List[TradeEvaluation]
    filter_impacts: Dict[str, FilterImpact]
    combined_impact: FilterImpact
    recommendations: List[str]


def load_positions(results_dir: Path) -> pd.DataFrame:
    """Load positions.csv from backtest results with column validation and normalization."""
    try:
        positions_path = results_dir / "positions.csv"
        if not positions_path.exists():
            raise FileNotFoundError(f"positions.csv not found in {results_dir}")
        
        df = pd.read_csv(positions_path)
        
        # Define required columns and their aliases
        required_columns = {
            'position_id': ['position_id', 'id', 'positionId'],
            'ts_opened': ['ts_opened', 'opened_at', 'entry_time', 'timestamp'],
            'ts_closed': ['ts_closed', 'closed_at', 'exit_time'],
            'entry_price': ['entry_price', 'entryPrice', 'open_price'],
            'exit_price': ['exit_price', 'exitPrice', 'close_price'],
            'realized_pnl': ['realized_pnl', 'pnl', 'profit_loss'],
            'side': ['side', 'order_side', 'direction', 'position_side']
        }
        
        # Normalize column names by mapping aliases to standard names
        column_mapping = {}
        for standard_name, aliases in required_columns.items():
            for alias in aliases:
                if alias in df.columns:
                    column_mapping[alias] = standard_name
                    break
        
        # Rename columns
        df = df.rename(columns=column_mapping)
        
        # Validate required columns are present
        missing_columns = [col for col in required_columns.keys() if col not in df.columns]
        if missing_columns:
            available_columns = list(df.columns)
            raise ValueError(f"Missing required columns: {missing_columns}. Available columns: {available_columns}")
        
        # Parse timestamp columns with UTC enforcement
        if 'ts_opened' in df.columns:
            df['ts_opened'] = pd.to_datetime(df['ts_opened'], utc=True)
        if 'ts_closed' in df.columns:
            df['ts_closed'] = pd.to_datetime(df['ts_closed'], utc=True)
        
        # Parse realized_pnl column (remove currency suffix, convert to float)
        if 'realized_pnl' in df.columns:
            df['realized_pnl'] = df['realized_pnl'].apply(parse_currency_value)
        
        # Filter out snapshot rows if column exists
        if 'is_snapshot' in df.columns:
            df = df[df['is_snapshot'] == False]
        
        logger.info(f"Loaded {len(df)} positions from {positions_path}")
        logger.info(f"Columns: {list(df.columns)}")
        return df
        
    except Exception as e:
        logger.error(f"Error loading positions: {e}")
        raise


def load_orders(results_dir: Path) -> pd.DataFrame:
    """Load orders.csv from backtest results."""
    try:
        orders_path = results_dir / "orders.csv"
        if not orders_path.exists():
            raise FileNotFoundError(f"orders.csv not found in {results_dir}")
        
        df = pd.read_csv(orders_path)
        
        # Parse timestamp columns
        timestamp_cols = ['ts_event', 'ts_init', 'ts_triggered', 'ts_last']
        for col in timestamp_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
        
        logger.info(f"Loaded {len(df)} orders from {orders_path}")
        return df
        
    except Exception as e:
        logger.error(f"Error loading orders: {e}")
        raise


def load_rejected_signals(results_dir: Path) -> pd.DataFrame:
    """Load rejected_signals.csv from backtest results."""
    try:
        signals_path = results_dir / "rejected_signals.csv"
        if not signals_path.exists():
            logger.warning(f"rejected_signals.csv not found in {results_dir}")
            return pd.DataFrame()
        
        df = pd.read_csv(signals_path)
        
        # Parse timestamp column
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        logger.info(f"Loaded {len(df)} rejected signals from {signals_path}")
        return df
        
    except Exception as e:
        logger.error(f"Error loading rejected signals: {e}")
        return pd.DataFrame()


def load_performance_stats(results_dir: Path) -> Dict[str, Any]:
    """Load performance_stats.json from backtest results."""
    try:
        stats_path = results_dir / "performance_stats.json"
        if not stats_path.exists():
            logger.warning(f"performance_stats.json not found in {results_dir}")
            return {}
        
        with open(stats_path, 'r') as f:
            stats = json.load(f)
        
        logger.info(f"Loaded performance stats from {stats_path}")
        return stats
        
    except Exception as e:
        logger.error(f"Error loading performance stats: {e}")
        return {}


def derive_bar_spec_from_results(results_dir: Path) -> str:
    """Derive bar_spec from results directory by reading config JSON if present."""
    try:
        # Try to find config files that might contain bar spec
        config_files = [
            results_dir / "config.json",
            results_dir / "backtest_config.json",
            results_dir / "strategy_config.json"
        ]
        
        for config_file in config_files:
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)
                
                # Look for bar_spec in various possible keys
                bar_spec_keys = ['bar_spec', 'bar_type', 'bar_aggregation', 'timeframe']
                for key in bar_spec_keys:
                    if key in config:
                        bar_spec = config[key]
                        logger.info(f"Found bar_spec '{bar_spec}' in {config_file}")
                        return bar_spec
        
        # Default fallback
        logger.info("No bar_spec found in config files, using default: 1-MINUTE-MID-EXTERNAL")
        return "1-MINUTE-MID-EXTERNAL"
        
    except Exception as e:
        logger.warning(f"Error deriving bar_spec from results: {e}, using default")
        return "1-MINUTE-MID-EXTERNAL"


def derive_pip_value(bars: List[Bar], instrument_id: str) -> float:
    """Derive pip value from bar price precision or instrument metadata."""
    try:
        if not bars:
            logger.warning("No bars available for pip value derivation, using default")
            return 0.0001
        
        # Extract sample prices to analyze precision
        sample_prices = []
        for bar in bars[:100]:  # Sample first 100 bars
            sample_prices.extend([bar.open, bar.high, bar.low, bar.close])
        
        if not sample_prices:
            return 0.0001
        
        # Analyze price precision by looking at decimal places
        price_str = str(sample_prices[0])
        if '.' in price_str:
            decimal_places = len(price_str.split('.')[-1])
        else:
            decimal_places = 0
        
        # Determine pip value based on decimal places and instrument
        if decimal_places == 5:  # 5-decimal forex (e.g., EUR/USD)
            pip_value = 0.0001
        elif decimal_places == 3:  # 3-decimal forex (e.g., USD/JPY)
            pip_value = 0.01
        elif decimal_places == 4:  # 4-decimal forex (some pairs)
            pip_value = 0.0001
        else:
            # Fallback: try to infer from instrument name
            if 'JPY' in instrument_id:
                pip_value = 0.01  # JPY pairs typically use 3 decimals
            else:
                pip_value = 0.0001  # Most forex pairs use 5 decimals
        
        logger.info(f"Derived pip value: {pip_value} for instrument {instrument_id} (decimal places: {decimal_places})")
        return pip_value
        
    except Exception as e:
        logger.warning(f"Error deriving pip value: {e}, using default")
        return 0.0001


def parse_currency_value(value_str: str) -> float:
    """Parse currency strings like ' -256.70 USD' to float."""
    if pd.isna(value_str) or value_str == '':
        return 0.0
    
    if isinstance(value_str, (int, float)):
        return float(value_str)
    
    # Use regex to extract numeric value
    match = re.search(r'([+-]?\d+\.?\d*)\s*[A-Z]{3}', str(value_str))
    if match:
        return float(match.group(1))
    
    # Try direct conversion if no currency suffix
    try:
        return float(value_str)
    except ValueError:
        logger.warning(f"Could not parse currency value: {value_str}")
        return 0.0


def load_bar_data(catalog_path: Path, instrument_id: str, bar_spec: str, 
                  start_time: pd.Timestamp, end_time: pd.Timestamp) -> List[Bar]:
    """Load bar data from ParquetDataCatalog."""
    try:
        catalog = ParquetDataCatalog(catalog_path)
        
        # Construct bar_type string
        bar_type = f"{instrument_id}-{bar_spec}"
        
        # Try both instrument ID formats for forex pairs
        instrument_ids = try_both_instrument_formats(instrument_id)
        
        bars = []
        for inst_id in instrument_ids:
            try:
                bar_type_str = f"{inst_id}-{bar_spec}"
                bars = catalog.bars(
                    bar_types=[bar_type_str],
                    start=start_time.value,
                    end=end_time.value
                )
                if bars:
                    logger.info(f"Loaded {len(bars)} bars for {bar_type_str}")
                    break
            except Exception as e:
                logger.debug(f"Failed to load bars for {bar_type_str}: {e}")
                continue
        
        if not bars:
            raise ValueError(f"No bars found for instrument {instrument_id} with spec {bar_spec}")
        
        return bars
        
    except Exception as e:
        logger.error(f"Error loading bar data: {e}")
        raise


def calculate_atr_series(bars: List[Bar], period: int = 14) -> pd.DataFrame:
    """Calculate ATR series from bars."""
    try:
        atr = AverageTrueRange(period=period, ma_type=MovingAverageType.SIMPLE)
        
        results = []
        for bar in bars:
            atr.handle_bar(bar)
            
            # Only store values after warmup period
            if atr.initialized:
                results.append({
                    'timestamp': pd.Timestamp(bar.ts_event, unit='ns'),
                    'atr_value': atr.value
                })
            else:
                results.append({
                    'timestamp': pd.Timestamp(bar.ts_event, unit='ns'),
                    'atr_value': None
                })
        
        df = pd.DataFrame(results)
        df.set_index('timestamp', inplace=True)
        
        logger.info(f"Calculated ATR series with {len(df)} values")
        return df
        
    except Exception as e:
        logger.error(f"Error calculating ATR series: {e}")
        raise


def calculate_adx_series(bars: List[Bar], period: int = 14) -> pd.DataFrame:
    """Calculate ADX series from bars using DMI indicator."""
    try:
        dmi = DMI(period=period)
        
        results = []
        dx_values = []
        
        for bar in bars:
            dmi.handle_bar(bar)
            
            if dmi.initialized:
                # Calculate DX from DMI
                plus_di = dmi.plus_di
                minus_di = dmi.minus_di
                
                if plus_di + minus_di > 0:
                    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
                else:
                    dx = 0.0
                
                dx_values.append(dx)
                
                # Calculate ADX using Wilder's smoothing
                if len(dx_values) == period:
                    # First ADX value is average of first period DX values
                    adx = sum(dx_values) / period
                elif len(dx_values) > period:
                    # Subsequent ADX values use Wilder's smoothing
                    prev_adx = results[-1]['adx']
                    adx = (prev_adx * (period - 1) + dx) / period
                else:
                    adx = None
                
                results.append({
                    'timestamp': pd.Timestamp(bar.ts_event, unit='ns'),
                    'plus_di': plus_di,
                    'minus_di': minus_di,
                    'dx': dx,
                    'adx': adx
                })
            else:
                results.append({
                    'timestamp': pd.Timestamp(bar.ts_event, unit='ns'),
                    'plus_di': None,
                    'minus_di': None,
                    'dx': None,
                    'adx': None
                })
        
        df = pd.DataFrame(results)
        df.set_index('timestamp', inplace=True)
        
        logger.info(f"Calculated ADX series with {len(df)} values")
        return df
        
    except Exception as e:
        logger.error(f"Error calculating ADX series: {e}")
        raise


def detect_support_resistance_levels(bars: List[Bar], lookback: int = 50, pip_value: float = 0.0001) -> List[float]:
    """Detect support and resistance levels from bars with pip-scaled clustering."""
    try:
        if len(bars) < lookback * 2:
            logger.warning(f"Not enough bars ({len(bars)}) for S/R detection with lookback {lookback}")
            return []
        
        # Extract high and low prices
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        
        swing_highs = []
        swing_lows = []
        
        # Detect swing highs and lows
        for i in range(lookback, len(bars) - lookback):
            # Check for swing high
            is_swing_high = True
            for j in range(i - lookback, i + lookback + 1):
                if j != i and highs[j] >= highs[i]:
                    is_swing_high = False
                    break
            
            if is_swing_high:
                swing_highs.append(highs[i])
            
            # Check for swing low
            is_swing_low = True
            for j in range(i - lookback, i + lookback + 1):
                if j != i and lows[j] <= lows[i]:
                    is_swing_low = False
                    break
            
            if is_swing_low:
                swing_lows.append(lows[i])
        
        # Combine and cluster nearby levels
        all_levels = swing_highs + swing_lows
        if not all_levels:
            return []
        
        # Sort levels
        all_levels.sort()
        
        # Cluster nearby levels using pip-scaled threshold (5-10 pips)
        clustered_levels = []
        cluster_threshold_pips = 7.5  # 7.5 pips as middle ground between 5-10
        cluster_threshold = cluster_threshold_pips * pip_value
        
        for level in all_levels:
            if not clustered_levels or level - clustered_levels[-1] > cluster_threshold:
                clustered_levels.append(level)
        
        logger.info(f"Detected {len(clustered_levels)} S/R levels from {len(bars)} bars (threshold: {cluster_threshold_pips} pips)")
        return clustered_levels
        
    except Exception as e:
        logger.error(f"Error detecting S/R levels: {e}")
        return []


def find_nearest_indicator_value(timestamp: pd.Timestamp, indicator_df: pd.DataFrame, 
                                value_column: str) -> Optional[float]:
    """Find the nearest indicator value to the given timestamp."""
    try:
        if indicator_df.empty:
            return None
        
        # Find the nearest timestamp
        nearest_idx = indicator_df.index.get_indexer([timestamp], method='nearest')[0]
        
        if nearest_idx == -1:
            return None
        
        nearest_timestamp = indicator_df.index[nearest_idx]
        value = indicator_df.loc[nearest_timestamp, value_column]
        
        return value if pd.notna(value) else None
        
    except Exception as e:
        logger.debug(f"Error finding nearest indicator value: {e}")
        return None


def simulate_atr_filter(trade: pd.Series, atr_df: pd.DataFrame, config: FilterConfig) -> Tuple[bool, Optional[float]]:
    """Simulate ATR volatility filter."""
    try:
        entry_time = trade['ts_opened']
        atr_value = find_nearest_indicator_value(entry_time, atr_df, 'atr_value')
        
        if atr_value is None:
            # No ATR data available, don't filter
            return False, None
        
        # Check if ATR is outside acceptable range
        should_filter = (atr_value < config.atr_min_threshold or 
                        atr_value > config.atr_max_threshold)
        
        return should_filter, atr_value
        
    except Exception as e:
        logger.debug(f"Error in ATR filter simulation: {e}")
        return False, None


def simulate_time_filter(trade: pd.Series, config: FilterConfig) -> bool:
    """Simulate time-of-day filter with UTC timezone enforcement."""
    try:
        entry_time = trade['ts_opened']
        
        # Ensure timezone is UTC
        if entry_time.tz is None:
            entry_time = entry_time.tz_localize('UTC')
        elif entry_time.tz != pd.Timestamp.now(tz='UTC').tz:
            entry_time = entry_time.tz_convert('UTC')
        
        entry_hour = entry_time.hour
        
        # Check if hour is outside trading window
        should_filter = (entry_hour < config.time_start_hour or 
                        entry_hour >= config.time_end_hour)
        
        return should_filter
        
    except Exception as e:
        logger.debug(f"Error in time filter simulation: {e}")
        return False


def simulate_adx_filter(trade: pd.Series, adx_df: pd.DataFrame, config: FilterConfig) -> Tuple[bool, Optional[float]]:
    """Simulate ADX trend strength filter."""
    try:
        entry_time = trade['ts_opened']
        adx_value = find_nearest_indicator_value(entry_time, adx_df, 'adx')
        
        if adx_value is None:
            # No ADX data available, don't filter
            return False, None
        
        # Check if ADX indicates weak trend
        should_filter = adx_value < config.adx_min_threshold
        
        return should_filter, adx_value
        
    except Exception as e:
        logger.debug(f"Error in ADX filter simulation: {e}")
        return False, None


def simulate_sr_filter(trade: pd.Series, sr_levels: List[float], config: FilterConfig, 
                       pip_value: float) -> Tuple[bool, Optional[float]]:
    """Simulate support/resistance filter."""
    try:
        entry_price = trade['entry_price']
        
        if not sr_levels:
            return False, None
        
        # Find nearest S/R level
        distances = [abs(entry_price - level) for level in sr_levels]
        nearest_idx = distances.index(min(distances))
        nearest_sr = sr_levels[nearest_idx]
        
        # Calculate distance in pips
        distance_pips = abs(entry_price - nearest_sr) / pip_value
        
        # Check if entry is too close to S/R
        should_filter = distance_pips < config.sr_distance_pips
        
        return should_filter, nearest_sr
        
    except Exception as e:
        logger.debug(f"Error in S/R filter simulation: {e}")
        return False, None


def evaluate_trade(trade: pd.Series, atr_df: pd.DataFrame, adx_df: pd.DataFrame, 
                     sr_levels: List[float], config: FilterConfig, pip_value: float) -> TradeEvaluation:
    """Evaluate a single trade against all enabled filters."""
    try:
        # Apply ATR filter
        filtered_by_atr, atr_value = False, None
        if config.atr_enabled:
            filtered_by_atr, atr_value = simulate_atr_filter(trade, atr_df, config)
        
        # Apply time filter
        filtered_by_time = False
        if config.time_filter_enabled:
            filtered_by_time = simulate_time_filter(trade, config)
        
        # Apply ADX filter
        filtered_by_adx, adx_value = False, None
        if config.adx_enabled:
            filtered_by_adx, adx_value = simulate_adx_filter(trade, adx_df, config)
        
        # Apply S/R filter
        filtered_by_sr, nearest_sr = False, None
        if config.sr_enabled:
            filtered_by_sr, nearest_sr = simulate_sr_filter(trade, sr_levels, config, pip_value)
        
        # Determine if trade is filtered overall
        filtered_overall = (filtered_by_atr or filtered_by_time or 
                          filtered_by_adx or filtered_by_sr)
        
        return TradeEvaluation(
            position_id=trade['position_id'],
            entry_time=trade['ts_opened'],
            entry_price=trade['entry_price'],
            exit_price=trade['exit_price'],
            realized_pnl=trade['realized_pnl'],
            side=trade['side'],
            atr_value=atr_value,
            adx_value=adx_value,
            nearest_sr_level=nearest_sr,
            filtered_by_atr=filtered_by_atr,
            filtered_by_time=filtered_by_time,
            filtered_by_adx=filtered_by_adx,
            filtered_by_sr=filtered_by_sr,
            filtered_overall=filtered_overall
        )
        
    except Exception as e:
        logger.error(f"Error evaluating trade {trade.get('position_id', 'unknown')}: {e}")
        # Return a default evaluation that doesn't filter the trade
        return TradeEvaluation(
            position_id=trade.get('position_id', 'unknown'),
            entry_time=trade.get('ts_opened', pd.Timestamp.now()),
            entry_price=trade.get('entry_price', 0.0),
            exit_price=trade.get('exit_price', 0.0),
            realized_pnl=trade.get('realized_pnl', 0.0),
            side=trade.get('side', 'UNKNOWN'),
            filtered_overall=False
        )


def calculate_filter_impact(trade_evaluations: List[TradeEvaluation], filter_name: str, 
                          filter_attr: str) -> FilterImpact:
    """Calculate impact statistics for a single filter."""
    try:
        # Filter trades where the specified filter rejected them
        filtered_trades = [t for t in trade_evaluations if getattr(t, filter_attr)]
        
        if not filtered_trades:
            return FilterImpact(
                filter_name=filter_name,
                trades_filtered=0,
                winners_filtered=0,
                losers_filtered=0,
                pnl_of_filtered_trades=0.0,
                estimated_pnl_improvement=0.0,
                filter_effectiveness=0.0
            )
        
        # Count winners and losers
        winners_filtered = len([t for t in filtered_trades if t.realized_pnl > 0])
        losers_filtered = len([t for t in filtered_trades if t.realized_pnl <= 0])
        
        # Calculate PnL of filtered trades
        pnl_of_filtered_trades = sum(t.realized_pnl for t in filtered_trades)
        
        # Estimate improvement (negative of PnL of filtered trades)
        estimated_pnl_improvement = -pnl_of_filtered_trades
        
        # Calculate effectiveness score
        if len(filtered_trades) > 0:
            effectiveness = (losers_filtered - winners_filtered) / len(filtered_trades)
        else:
            effectiveness = 0.0
        
        return FilterImpact(
            filter_name=filter_name,
            trades_filtered=len(filtered_trades),
            winners_filtered=winners_filtered,
            losers_filtered=losers_filtered,
            pnl_of_filtered_trades=pnl_of_filtered_trades,
            estimated_pnl_improvement=estimated_pnl_improvement,
            filter_effectiveness=effectiveness
        )
        
    except Exception as e:
        logger.error(f"Error calculating filter impact: {e}")
        return FilterImpact(
            filter_name=filter_name,
            trades_filtered=0,
            winners_filtered=0,
            losers_filtered=0,
            pnl_of_filtered_trades=0.0,
            estimated_pnl_improvement=0.0,
            filter_effectiveness=0.0
        )


def calculate_combined_impact(trade_evaluations: List[TradeEvaluation]) -> FilterImpact:
    """Calculate impact of all filters applied together."""
    try:
        # Filter trades where any filter rejected them
        filtered_trades = [t for t in trade_evaluations if t.filtered_overall]
        
        if not filtered_trades:
            return FilterImpact(
                filter_name="Combined (All Filters)",
                trades_filtered=0,
                winners_filtered=0,
                losers_filtered=0,
                pnl_of_filtered_trades=0.0,
                estimated_pnl_improvement=0.0,
                filter_effectiveness=0.0
            )
        
        # Count winners and losers
        winners_filtered = len([t for t in filtered_trades if t.realized_pnl > 0])
        losers_filtered = len([t for t in filtered_trades if t.realized_pnl <= 0])
        
        # Calculate PnL of filtered trades
        pnl_of_filtered_trades = sum(t.realized_pnl for t in filtered_trades)
        
        # Estimate improvement
        estimated_pnl_improvement = -pnl_of_filtered_trades
        
        # Calculate effectiveness score
        if len(filtered_trades) > 0:
            effectiveness = (losers_filtered - winners_filtered) / len(filtered_trades)
        else:
            effectiveness = 0.0
        
        return FilterImpact(
            filter_name="Combined (All Filters)",
            trades_filtered=len(filtered_trades),
            winners_filtered=winners_filtered,
            losers_filtered=losers_filtered,
            pnl_of_filtered_trades=pnl_of_filtered_trades,
            estimated_pnl_improvement=estimated_pnl_improvement,
            filter_effectiveness=effectiveness
        )
        
    except Exception as e:
        logger.error(f"Error calculating combined impact: {e}")
        return FilterImpact(
            filter_name="Combined (All Filters)",
            trades_filtered=0,
            winners_filtered=0,
            losers_filtered=0,
            pnl_of_filtered_trades=0.0,
            estimated_pnl_improvement=0.0,
            filter_effectiveness=0.0
        )


def generate_recommendations(filter_impacts: Dict[str, FilterImpact], 
                           combined_impact: FilterImpact, config: FilterConfig) -> List[str]:
    """Generate actionable recommendations based on filter impacts."""
    recommendations = []
    
    try:
        # Analyze individual filter impacts
        for filter_name, impact in filter_impacts.items():
            if impact.trades_filtered == 0:
                continue
            
            if filter_name == "ATR" and impact.filter_effectiveness > 0.5:
                recommendations.append(
                    f"Enable ATR volatility filter with min={config.atr_min_threshold}, "
                    f"max={config.atr_max_threshold} (effectiveness: {impact.filter_effectiveness:.2f})"
                )
            
            elif filter_name == "Time" and impact.estimated_pnl_improvement > 0:
                recommendations.append(
                    f"Enable time-of-day filter to trade only during "
                    f"{config.time_start_hour}:00-{config.time_end_hour}:00 UTC "
                    f"(PnL improvement: {impact.estimated_pnl_improvement:.2f})"
                )
            
            elif filter_name == "ADX" and impact.filter_effectiveness > 0.5:
                recommendations.append(
                    f"Enable ADX trend strength filter with min_threshold={config.adx_min_threshold} "
                    f"(effectiveness: {impact.filter_effectiveness:.2f})"
                )
            
            elif filter_name == "S/R" and impact.estimated_pnl_improvement > 0:
                recommendations.append(
                    f"Enable support/resistance filter with distance={config.sr_distance_pips} pips "
                    f"(PnL improvement: {impact.estimated_pnl_improvement:.2f})"
                )
        
        # Analyze combined impact
        if combined_impact.estimated_pnl_improvement < 0:
            recommendations.append(
                "Warning: Filters remove more winners than losers. Consider relaxing thresholds or disabling filters."
            )
        elif combined_impact.estimated_pnl_improvement > 0 and combined_impact.estimated_pnl_improvement < 100:
            recommendations.append("Filters provide marginal improvement. Consider testing different threshold values.")
        
        if not recommendations:
            recommendations.append("No strong filter recommendations based on current analysis.")
        
        return recommendations
        
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        return ["Error generating recommendations."]


def run_simulation(results_dir: Path, catalog_path: Path, config: FilterConfig, bar_spec: Optional[str] = None, pip_value: Optional[float] = None) -> SimulationReport:
    """Run the complete filter simulation."""
    try:
        # Load backtest results
        positions_df = load_positions(results_dir)
        orders_df = load_orders(results_dir)
        rejected_signals_df = load_rejected_signals(results_dir)
        performance_stats = load_performance_stats(results_dir)
        
        # Extract backtest metadata
        if positions_df.empty:
            raise ValueError("No positions found in backtest results")
        
        # Determine instrument and bar spec from positions
        instrument_id = positions_df['instrument_id'].iloc[0] if 'instrument_id' in positions_df.columns else "EUR-USD"
        
        # Derive bar_spec from results directory if not provided
        if bar_spec is None:
            bar_spec = derive_bar_spec_from_results(results_dir)
        
        # Get time range
        start_time = positions_df['ts_opened'].min()
        end_time = positions_df['ts_closed'].max()
        
        # Load bar data
        bars = load_bar_data(catalog_path, instrument_id, bar_spec, start_time, end_time)
        
        # Calculate indicators
        atr_df = pd.DataFrame()
        if config.atr_enabled:
            atr_df = calculate_atr_series(bars, config.atr_period)
        
        adx_df = pd.DataFrame()
        if config.adx_enabled:
            adx_df = calculate_adx_series(bars, config.adx_period)
        
        # Determine pip value for the instrument
        if pip_value is None:
            pip_value = derive_pip_value(bars, instrument_id)
        
        sr_levels = []
        if config.sr_enabled:
            sr_levels = detect_support_resistance_levels(bars, config.sr_lookback_bars, pip_value)
        
        # Evaluate each trade
        trade_evaluations = []
        for _, trade in positions_df.iterrows():
            evaluation = evaluate_trade(trade, atr_df, adx_df, sr_levels, config, pip_value)
            trade_evaluations.append(evaluation)
        
        # Calculate filter impacts
        filter_impacts = {}
        
        if config.atr_enabled:
            filter_impacts["ATR"] = calculate_filter_impact(trade_evaluations, "ATR", "filtered_by_atr")
        
        if config.time_filter_enabled:
            filter_impacts["Time"] = calculate_filter_impact(trade_evaluations, "Time", "filtered_by_time")
        
        if config.adx_enabled:
            filter_impacts["ADX"] = calculate_filter_impact(trade_evaluations, "ADX", "filtered_by_adx")
        
        if config.sr_enabled:
            filter_impacts["S/R"] = calculate_filter_impact(trade_evaluations, "S/R", "filtered_by_sr")
        
        # Calculate combined impact
        combined_impact = calculate_combined_impact(trade_evaluations)
        
        # Generate recommendations
        recommendations = generate_recommendations(filter_impacts, combined_impact, config)
        
        # Calculate original PnL
        original_pnl = positions_df['realized_pnl'].sum()
        
        # Create report
        report = SimulationReport(
            backtest_run_id=results_dir.name,
            catalog_path=str(catalog_path),
            bar_type=bar_spec,
            total_trades=len(positions_df),
            original_pnl=original_pnl,
            rejected_signals_count=len(rejected_signals_df),
            filter_config=config,
            trade_evaluations=trade_evaluations,
            filter_impacts=filter_impacts,
            combined_impact=combined_impact,
            recommendations=recommendations
        )
        
        logger.info(f"Simulation completed: {len(trade_evaluations)} trades evaluated")
        return report
        
    except Exception as e:
        logger.error(f"Error running simulation: {e}")
        raise


def create_filter_effectiveness_chart(filter_impacts: Dict[str, FilterImpact]) -> str:
    """Create bar chart showing effectiveness score for each filter."""
    try:
        plt.figure(figsize=(10, 6))
        sns.set_style('whitegrid')
        
        filter_names = list(filter_impacts.keys())
        effectiveness_scores = [impact.filter_effectiveness for impact in filter_impacts.values()]
        
        # Color bars based on effectiveness
        colors = ['green' if score > 0 else 'red' for score in effectiveness_scores]
        
        bars = plt.bar(filter_names, effectiveness_scores, color=colors, alpha=0.7)
        
        # Add value labels on bars
        for bar, score in zip(bars, effectiveness_scores):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01, 
                    f'{score:.2f}', ha='center', va='bottom')
        
        plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        plt.title('Filter Effectiveness Scores')
        plt.xlabel('Filter')
        plt.ylabel('Effectiveness Score (-1 to 1)')
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        # Convert to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        chart_data = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return chart_data
        
    except Exception as e:
        logger.error(f"Error creating effectiveness chart: {e}")
        return ""


def create_pnl_impact_chart(filter_impacts: Dict[str, FilterImpact], combined_impact: FilterImpact) -> str:
    """Create bar chart showing estimated PnL improvement for each filter."""
    try:
        plt.figure(figsize=(12, 6))
        sns.set_style('whitegrid')
        
        # Prepare data
        filter_names = list(filter_impacts.keys()) + ["Combined"]
        pnl_improvements = [impact.estimated_pnl_improvement for impact in filter_impacts.values()] + [combined_impact.estimated_pnl_improvement]
        
        # Color bars based on improvement
        colors = ['green' if imp > 0 else 'red' for imp in pnl_improvements]
        
        bars = plt.bar(filter_names, pnl_improvements, color=colors, alpha=0.7)
        
        # Add value labels on bars
        for bar, imp in zip(bars, pnl_improvements):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + (max(pnl_improvements) * 0.01), 
                    f'{imp:.2f}', ha='center', va='bottom' if imp > 0 else 'top')
        
        plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        plt.title('Estimated PnL Improvement by Filter')
        plt.xlabel('Filter')
        plt.ylabel('PnL Improvement')
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        # Convert to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        chart_data = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return chart_data
        
    except Exception as e:
        logger.error(f"Error creating PnL impact chart: {e}")
        return ""


def create_trades_filtered_chart(filter_impacts: Dict[str, FilterImpact]) -> str:
    """Create stacked bar chart showing trades filtered by each filter."""
    try:
        plt.figure(figsize=(10, 6))
        sns.set_style('whitegrid')
        
        filter_names = list(filter_impacts.keys())
        winners_filtered = [impact.winners_filtered for impact in filter_impacts.values()]
        losers_filtered = [impact.losers_filtered for impact in filter_impacts.values()]
        
        # Create stacked bar chart
        p1 = plt.bar(filter_names, winners_filtered, color='red', alpha=0.7, label='Winners Filtered')
        p2 = plt.bar(filter_names, losers_filtered, bottom=winners_filtered, color='green', alpha=0.7, label='Losers Filtered')
        
        # Add value labels
        for i, (w, l) in enumerate(zip(winners_filtered, losers_filtered)):
            total = w + l
            if total > 0:
                plt.text(i, total + max(winners_filtered + losers_filtered) * 0.01, 
                        str(total), ha='center', va='bottom')
        
        plt.title('Trades Filtered by Each Filter')
        plt.xlabel('Filter')
        plt.ylabel('Number of Trades')
        plt.legend()
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        # Convert to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        chart_data = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return chart_data
        
    except Exception as e:
        logger.error(f"Error creating trades filtered chart: {e}")
        return ""


def create_indicator_distribution_chart(trade_evaluations: List[TradeEvaluation], 
                                      indicator_name: str, indicator_attr: str) -> str:
    """Create histogram showing distribution of indicator values at trade entries."""
    try:
        plt.figure(figsize=(10, 6))
        sns.set_style('whitegrid')
        
        # Extract indicator values
        winners = [getattr(t, indicator_attr) for t in trade_evaluations 
                  if t.realized_pnl > 0 and getattr(t, indicator_attr) is not None]
        losers = [getattr(t, indicator_attr) for t in trade_evaluations 
                 if t.realized_pnl <= 0 and getattr(t, indicator_attr) is not None]
        
        if not winners and not losers:
            return ""
        
        # Create histograms
        plt.hist(winners, bins=20, alpha=0.7, color='green', label='Winners', density=True)
        plt.hist(losers, bins=20, alpha=0.7, color='red', label='Losers', density=True)
        
        plt.title(f'{indicator_name} Distribution at Trade Entries')
        plt.xlabel(f'{indicator_name} Value')
        plt.ylabel('Density')
        plt.legend()
        plt.tight_layout()
        
        # Convert to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        chart_data = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return chart_data
        
    except Exception as e:
        logger.error(f"Error creating indicator distribution chart: {e}")
        return ""


def generate_console_report(report: SimulationReport) -> None:
    """Generate formatted console report."""
    try:
        print("=" * 80)
        print("FILTER SIMULATION REPORT")
        print("=" * 80)
        print()
        
        # Backtest Info
        print("-" * 40)
        print("BACKTEST INFORMATION")
        print("-" * 40)
        print(f"Run ID: {report.backtest_run_id}")
        print(f"Catalog Path: {report.catalog_path}")
        print(f"Bar Type: {report.bar_type}")
        print(f"Total Trades: {report.total_trades}")
        print(f"Rejected Signals: {report.rejected_signals_count}")
        print(f"Original PnL: {report.original_pnl:.2f}")
        print()
        
        # Filter Configuration
        print("-" * 40)
        print("FILTER CONFIGURATION")
        print("-" * 40)
        config = report.filter_config
        if config.atr_enabled:
            print(f"ATR Filter: ENABLED (min={config.atr_min_threshold}, max={config.atr_max_threshold}, period={config.atr_period})")
        else:
            print("ATR Filter: DISABLED")
        
        if config.time_filter_enabled:
            print(f"Time Filter: ENABLED ({config.time_start_hour}:00-{config.time_end_hour}:00 UTC)")
        else:
            print("Time Filter: DISABLED")
        
        if config.adx_enabled:
            print(f"ADX Filter: ENABLED (min={config.adx_min_threshold}, period={config.adx_period})")
        else:
            print("ADX Filter: DISABLED")
        
        if config.sr_enabled:
            print(f"S/R Filter: ENABLED (lookback={config.sr_lookback_bars}, distance={config.sr_distance_pips} pips)")
        else:
            print("S/R Filter: DISABLED")
        print()
        
        # Individual Filter Impacts
        if report.filter_impacts:
            print("-" * 40)
            print("INDIVIDUAL FILTER IMPACTS")
            print("-" * 40)
            print(f"{'Filter':<10} {'Trades':<8} {'Winners':<8} {'Losers':<8} {'PnL Impact':<12} {'Effectiveness':<12}")
            print("-" * 70)
            
            for filter_name, impact in report.filter_impacts.items():
                print(f"{filter_name:<10} {impact.trades_filtered:<8} {impact.winners_filtered:<8} "
                      f"{impact.losers_filtered:<8} {impact.estimated_pnl_improvement:<12.2f} {impact.filter_effectiveness:<12.2f}")
            print()
        
        # Combined Impact
        print("-" * 40)
        print("COMBINED IMPACT")
        print("-" * 40)
        combined = report.combined_impact
        print(f"Trades Filtered: {combined.trades_filtered}")
        print(f"Winners Filtered: {combined.winners_filtered}")
        print(f"Losers Filtered: {combined.losers_filtered}")
        print(f"Estimated PnL Improvement: {combined.estimated_pnl_improvement:.2f}")
        print(f"Filter Effectiveness: {combined.filter_effectiveness:.2f}")
        print()
        
        # Recommendations
        print("-" * 40)
        print("RECOMMENDATIONS")
        print("-" * 40)
        for i, rec in enumerate(report.recommendations, 1):
            print(f"{i}. {rec}")
        print()
        
    except Exception as e:
        logger.error(f"Error generating console report: {e}")


def generate_json_report(report: SimulationReport, output_path: Path) -> None:
    """Export report as JSON."""
    try:
        # Convert report to dictionary
        report_dict = {
            'backtest_run_id': report.backtest_run_id,
            'catalog_path': report.catalog_path,
            'bar_type': report.bar_type,
            'total_trades': report.total_trades,
            'rejected_signals_count': report.rejected_signals_count,
            'original_pnl': report.original_pnl,
            'filter_config': {
                'atr_enabled': report.filter_config.atr_enabled,
                'atr_min_threshold': report.filter_config.atr_min_threshold,
                'atr_max_threshold': report.filter_config.atr_max_threshold,
                'atr_period': report.filter_config.atr_period,
                'time_filter_enabled': report.filter_config.time_filter_enabled,
                'time_start_hour': report.filter_config.time_start_hour,
                'time_end_hour': report.filter_config.time_end_hour,
                'adx_enabled': report.filter_config.adx_enabled,
                'adx_min_threshold': report.filter_config.adx_min_threshold,
                'adx_period': report.filter_config.adx_period,
                'sr_enabled': report.filter_config.sr_enabled,
                'sr_lookback_bars': report.filter_config.sr_lookback_bars,
                'sr_distance_pips': report.filter_config.sr_distance_pips
            },
            'filter_impacts': [
                {
                    'filter_name': impact.filter_name,
                    'trades_filtered': impact.trades_filtered,
                    'winners_filtered': impact.winners_filtered,
                    'losers_filtered': impact.losers_filtered,
                    'pnl_of_filtered_trades': impact.pnl_of_filtered_trades,
                    'estimated_pnl_improvement': impact.estimated_pnl_improvement,
                    'filter_effectiveness': impact.filter_effectiveness
                }
                for impact in report.filter_impacts.values()
            ],
            'combined_impact': {
                'filter_name': report.combined_impact.filter_name,
                'trades_filtered': report.combined_impact.trades_filtered,
                'winners_filtered': report.combined_impact.winners_filtered,
                'losers_filtered': report.combined_impact.losers_filtered,
                'pnl_of_filtered_trades': report.combined_impact.pnl_of_filtered_trades,
                'estimated_pnl_improvement': report.combined_impact.estimated_pnl_improvement,
                'filter_effectiveness': report.combined_impact.filter_effectiveness
            },
            'trade_evaluations': [
                {
                    'position_id': eval.position_id,
                    'entry_time': eval.entry_time.isoformat(),
                    'entry_price': eval.entry_price,
                    'exit_price': eval.exit_price,
                    'realized_pnl': eval.realized_pnl,
                    'side': eval.side,
                    'atr_value': eval.atr_value,
                    'adx_value': eval.adx_value,
                    'nearest_sr_level': eval.nearest_sr_level,
                    'filtered_by_atr': eval.filtered_by_atr,
                    'filtered_by_time': eval.filtered_by_time,
                    'filtered_by_adx': eval.filtered_by_adx,
                    'filtered_by_sr': eval.filtered_by_sr,
                    'filtered_overall': eval.filtered_overall
                }
                for eval in report.trade_evaluations
            ],
            'recommendations': report.recommendations
        }
        
        # Write JSON file
        with open(output_path, 'w') as f:
            json.dump(report_dict, f, indent=2)
        
        logger.info(f"JSON report saved to {output_path}")
        
    except Exception as e:
        logger.error(f"Error generating JSON report: {e}")


def generate_html_report(report: SimulationReport, output_path: Path, charts: Dict[str, str]) -> None:
    """Generate comprehensive HTML report."""
    try:
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Filter Simulation Report - {report.backtest_run_id}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            border-bottom: 2px solid #ecf0f1;
            padding-bottom: 5px;
        }}
        .metric-card {{
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 5px;
            padding: 15px;
            margin: 10px 0;
            display: inline-block;
            min-width: 200px;
        }}
        .metric-value {{
            font-size: 24px;
            font-weight: bold;
            color: #2c3e50;
        }}
        .metric-label {{
            color: #7f8c8d;
            font-size: 14px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 12px;
            text-align: left;
        }}
        th {{
            background-color: #3498db;
            color: white;
        }}
        tr:nth-child(even) {{
            background-color: #f2f2f2;
        }}
        .positive {{
            color: #27ae60;
            font-weight: bold;
        }}
        .negative {{
            color: #e74c3c;
            font-weight: bold;
        }}
        .filter-enabled {{
            color: #27ae60;
            font-weight: bold;
        }}
        .filter-disabled {{
            color: #95a5a6;
        }}
        .chart-container {{
            text-align: center;
            margin: 20px 0;
        }}
        .recommendation {{
            background: #e8f4fd;
            border-left: 4px solid #3498db;
            padding: 15px;
            margin: 10px 0;
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ecf0f1;
            color: #7f8c8d;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Filter Simulation Report</h1>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h2>Backtest Information</h2>
        <div class="metric-card">
            <div class="metric-value">{report.backtest_run_id}</div>
            <div class="metric-label">Run ID</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{report.total_trades}</div>
            <div class="metric-label">Total Trades</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{report.rejected_signals_count}</div>
            <div class="metric-label">Rejected Signals</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{report.original_pnl:.2f}</div>
            <div class="metric-label">Original PnL</div>
        </div>
        
        <h2>Filter Configuration</h2>
        <table>
            <tr>
                <th>Filter</th>
                <th>Status</th>
                <th>Parameters</th>
            </tr>
            <tr>
                <td>ATR Volatility</td>
                <td class="{'filter-enabled' if report.filter_config.atr_enabled else 'filter-disabled'}">
                    {'ENABLED' if report.filter_config.atr_enabled else 'DISABLED'}
                </td>
                <td>
                    {f"min={report.filter_config.atr_min_threshold}, max={report.filter_config.atr_max_threshold}, period={report.filter_config.atr_period}" if report.filter_config.atr_enabled else "N/A"}
                </td>
            </tr>
            <tr>
                <td>Time-of-Day</td>
                <td class="{'filter-enabled' if report.filter_config.time_filter_enabled else 'filter-disabled'}">
                    {'ENABLED' if report.filter_config.time_filter_enabled else 'DISABLED'}
                </td>
                <td>
                    {f"{report.filter_config.time_start_hour}:00-{report.filter_config.time_end_hour}:00 UTC" if report.filter_config.time_filter_enabled else "N/A"}
                </td>
            </tr>
            <tr>
                <td>ADX Trend Strength</td>
                <td class="{'filter-enabled' if report.filter_config.adx_enabled else 'filter-disabled'}">
                    {'ENABLED' if report.filter_config.adx_enabled else 'DISABLED'}
                </td>
                <td>
                    {f"min={report.filter_config.adx_min_threshold}, period={report.filter_config.adx_period}" if report.filter_config.adx_enabled else "N/A"}
                </td>
            </tr>
            <tr>
                <td>Support/Resistance</td>
                <td class="{'filter-enabled' if report.filter_config.sr_enabled else 'filter-disabled'}">
                    {'ENABLED' if report.filter_config.sr_enabled else 'DISABLED'}
                </td>
                <td>
                    {f"lookback={report.filter_config.sr_lookback_bars}, distance={report.filter_config.sr_distance_pips} pips" if report.filter_config.sr_enabled else "N/A"}
                </td>
            </tr>
        </table>
        
        <h2>Filter Impacts</h2>
        <table>
            <tr>
                <th>Filter</th>
                <th>Trades Filtered</th>
                <th>Winners Filtered</th>
                <th>Losers Filtered</th>
                <th>PnL Impact</th>
                <th>Effectiveness</th>
            </tr>
"""
        
        # Add individual filter impacts
        for filter_name, impact in report.filter_impacts.items():
            pnl_class = "positive" if impact.estimated_pnl_improvement > 0 else "negative"
            eff_class = "positive" if impact.filter_effectiveness > 0 else "negative"
            
            html_content += f"""
            <tr>
                <td>{filter_name}</td>
                <td>{impact.trades_filtered}</td>
                <td>{impact.winners_filtered}</td>
                <td>{impact.losers_filtered}</td>
                <td class="{pnl_class}">{impact.estimated_pnl_improvement:.2f}</td>
                <td class="{eff_class}">{impact.filter_effectiveness:.2f}</td>
            </tr>
"""
        
        # Add combined impact
        combined = report.combined_impact
        pnl_class = "positive" if combined.estimated_pnl_improvement > 0 else "negative"
        eff_class = "positive" if combined.filter_effectiveness > 0 else "negative"
        
        html_content += f"""
            <tr style="background-color: #f8f9fa; font-weight: bold;">
                <td>Combined (All Filters)</td>
                <td>{combined.trades_filtered}</td>
                <td>{combined.winners_filtered}</td>
                <td>{combined.losers_filtered}</td>
                <td class="{pnl_class}">{combined.estimated_pnl_improvement:.2f}</td>
                <td class="{eff_class}">{combined.filter_effectiveness:.2f}</td>
            </tr>
        </table>
        
        <h2>Charts</h2>
"""
        
        # Add charts
        if charts.get('effectiveness'):
            html_content += f"""
        <div class="chart-container">
            <h3>Filter Effectiveness</h3>
            <img src="data:image/png;base64,{charts['effectiveness']}" alt="Filter Effectiveness Chart">
        </div>
"""
        
        if charts.get('pnl_impact'):
            html_content += f"""
        <div class="chart-container">
            <h3>PnL Impact</h3>
            <img src="data:image/png;base64,{charts['pnl_impact']}" alt="PnL Impact Chart">
        </div>
"""
        
        if charts.get('trades_filtered'):
            html_content += f"""
        <div class="chart-container">
            <h3>Trades Filtered</h3>
            <img src="data:image/png;base64,{charts['trades_filtered']}" alt="Trades Filtered Chart">
        </div>
"""
        
        # Add Trade Evaluations section
        html_content += """
        <h2>Trade Evaluations</h2>
        <p>Sample of filtered trades (first 20):</p>
        <table>
            <tr>
                <th>Position ID</th>
                <th>Entry Time</th>
                <th>Realized PnL</th>
                <th>Filtered by ATR</th>
                <th>Filtered by Time</th>
                <th>Filtered by ADX</th>
                <th>Filtered by S/R</th>
                <th>Filtered Overall</th>
            </tr>
"""
        
        # Add first 20 trade evaluations
        sample_trades = report.trade_evaluations[:20]
        for trade in sample_trades:
            atr_class = "positive" if trade.filtered_by_atr else ""
            time_class = "positive" if trade.filtered_by_time else ""
            adx_class = "positive" if trade.filtered_by_adx else ""
            sr_class = "positive" if trade.filtered_by_sr else ""
            overall_class = "positive" if trade.filtered_overall else ""
            pnl_class = "positive" if trade.realized_pnl > 0 else "negative"
            
            html_content += f"""
            <tr>
                <td>{trade.position_id}</td>
                <td>{trade.entry_time.strftime('%Y-%m-%d %H:%M:%S')}</td>
                <td class="{pnl_class}">{trade.realized_pnl:.2f}</td>
                <td class="{atr_class}">{'Yes' if trade.filtered_by_atr else 'No'}</td>
                <td class="{time_class}">{'Yes' if trade.filtered_by_time else 'No'}</td>
                <td class="{adx_class}">{'Yes' if trade.filtered_by_adx else 'No'}</td>
                <td class="{sr_class}">{'Yes' if trade.filtered_by_sr else 'No'}</td>
                <td class="{overall_class}">{'Yes' if trade.filtered_overall else 'No'}</td>
            </tr>
"""
        
        html_content += """
        </table>
"""
        
        # Add recommendations
        html_content += """
        <h2>Recommendations</h2>
"""
        
        for i, rec in enumerate(report.recommendations, 1):
            html_content += f"""
        <div class="recommendation">
            <strong>{i}.</strong> {rec}
        </div>
"""
        
        # Add footer
        html_content += f"""
        <div class="footer">
            <p>Generated by Filter Simulator Tool</p>
            <p>Report generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </div>
</body>
</html>
"""
        
        # Write HTML file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"HTML report saved to {output_path}")
        
    except Exception as e:
        logger.error(f"Error generating HTML report: {e}")


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Simulate new filter ideas on historical backtest data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analysis/filter_simulator.py --input logs/backtest_results/EUR-USD_20251013_200009 --catalog-path data/historical
  python analysis/filter_simulator.py --input results_dir --catalog-path catalog_dir --atr-min 0.0005 --atr-max 0.002 --adx-min 25 --time-start 08:00 --time-end 16:00
  python analysis/filter_simulator.py --input results_dir --catalog-path catalog_dir --json --output reports/filter_simulation.html
        """
    )
    
    # Required arguments
    parser.add_argument('--input', type=Path, required=True,
                       help='Path to backtest results directory')
    parser.add_argument('--catalog-path', type=Path, required=True,
                       help='Path to Parquet data catalog')
    
    # Bar spec option
    parser.add_argument('--bar-spec', type=str,
                       help='Bar specification (e.g., 1-MINUTE-MID-EXTERNAL). If not provided, will attempt to derive from results directory.')
    
    # Pip value option
    parser.add_argument('--pip-value', type=float,
                       help='Pip value for the instrument (e.g., 0.0001 for 5-decimal forex). If not provided, will attempt to derive from bar data.')
    
    # Output options
    parser.add_argument('--output', type=Path, default=Path('reports/filter_simulation.html'),
                       help='Path for HTML report output (default: reports/filter_simulation.html)')
    parser.add_argument('--json', action='store_true',
                       help='Export JSON report')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable debug logging')
    
    # ATR filter options
    parser.add_argument('--atr-enabled', action='store_true',
                       help='Enable ATR volatility filter')
    parser.add_argument('--atr-min', type=float, default=DEFAULT_ATR_MIN_THRESHOLD,
                       help=f'Minimum ATR threshold (default: {DEFAULT_ATR_MIN_THRESHOLD})')
    parser.add_argument('--atr-max', type=float, default=DEFAULT_ATR_MAX_THRESHOLD,
                       help=f'Maximum ATR threshold (default: {DEFAULT_ATR_MAX_THRESHOLD})')
    parser.add_argument('--atr-period', type=int, default=DEFAULT_ATR_PERIOD,
                       help=f'ATR calculation period (default: {DEFAULT_ATR_PERIOD})')
    
    # Time filter options
    parser.add_argument('--time-enabled', action='store_true',
                       help='Enable time-of-day filter')
    parser.add_argument('--time-start', type=int, default=DEFAULT_TIME_START_HOUR,
                       help=f'Trading start hour UTC (default: {DEFAULT_TIME_START_HOUR})')
    parser.add_argument('--time-end', type=int, default=DEFAULT_TIME_END_HOUR,
                       help=f'Trading end hour UTC (default: {DEFAULT_TIME_END_HOUR})')
    
    # ADX filter options
    parser.add_argument('--adx-enabled', action='store_true',
                       help='Enable ADX trend strength filter')
    parser.add_argument('--adx-min', type=float, default=DEFAULT_ADX_MIN_THRESHOLD,
                       help=f'Minimum ADX threshold (default: {DEFAULT_ADX_MIN_THRESHOLD})')
    parser.add_argument('--adx-period', type=int, default=DEFAULT_ADX_PERIOD,
                       help=f'ADX calculation period (default: {DEFAULT_ADX_PERIOD})')
    
    # S/R filter options
    parser.add_argument('--sr-enabled', action='store_true',
                       help='Enable support/resistance filter')
    parser.add_argument('--sr-lookback', type=int, default=DEFAULT_SR_LOOKBACK_BARS,
                       help=f'S/R lookback bars (default: {DEFAULT_SR_LOOKBACK_BARS})')
    parser.add_argument('--sr-distance', type=float, default=DEFAULT_SR_DISTANCE_PIPS,
                       help=f'S/R distance threshold in pips (default: {DEFAULT_SR_DISTANCE_PIPS})')
    
    args = parser.parse_args(argv)
    
    # Validate input directories
    if not args.input.exists():
        parser.error(f"Input directory does not exist: {args.input}")
    
    if not args.catalog_path.exists():
        parser.error(f"Catalog path does not exist: {args.catalog_path}")
    
    # Validate required files
    required_files = ['positions.csv', 'orders.csv']
    for file in required_files:
        if not (args.input / file).exists():
            parser.error(f"Required file not found: {args.input / file}")
    
    return args


def main(argv: Optional[List[str]] = None) -> int:
    """Main function."""
    try:
        # Parse arguments
        args = parse_arguments(argv)
        
        # Set logging level
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        # Create output directory
        args.output.parent.mkdir(parents=True, exist_ok=True)
        
        # Create FilterConfig from arguments
        config = FilterConfig(
            atr_enabled=args.atr_enabled,
            atr_min_threshold=args.atr_min,
            atr_max_threshold=args.atr_max,
            atr_period=args.atr_period,
            time_filter_enabled=args.time_enabled,
            time_start_hour=args.time_start,
            time_end_hour=args.time_end,
            adx_enabled=args.adx_enabled,
            adx_min_threshold=args.adx_min,
            adx_period=args.adx_period,
            sr_enabled=args.sr_enabled,
            sr_lookback_bars=args.sr_lookback,
            sr_distance_pips=args.sr_distance
        )
        
        # Run simulation
        logger.info("Starting filter simulation...")
        report = run_simulation(args.input, args.catalog_path, config, args.bar_spec, args.pip_value)
        
        # Generate console report (always)
        generate_console_report(report)
        
        # Generate charts
        logger.info("Generating charts...")
        charts = {}
        
        if report.filter_impacts:
            charts['effectiveness'] = create_filter_effectiveness_chart(report.filter_impacts)
            charts['pnl_impact'] = create_pnl_impact_chart(report.filter_impacts, report.combined_impact)
            charts['trades_filtered'] = create_trades_filtered_chart(report.filter_impacts)
        
        # Generate HTML report (always)
        generate_html_report(report, args.output, charts)
        
        # Generate JSON report (if requested)
        if args.json:
            json_path = args.output.with_suffix('.json')
            generate_json_report(report, json_path)
            logger.info(f"JSON report saved to {json_path}")
        
        logger.info(f"HTML report saved to {args.output}")
        logger.info("Filter simulation completed successfully")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
