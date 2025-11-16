"""
Grid Search Optimizer for NautilusTrader Backtest Parameter Tuning.

Runs backtests in parallel with different parameter combinations to find
optimal strategy configuration. Supports checkpoint/resume for long-running
optimizations.

Usage Examples:

    # Basic grid search with default settings
    python optimization/grid_search.py --config optimization/grid_config.yaml
    
    # Specify number of workers and objective function
    python optimization/grid_search.py \
        --config optimization/grid_config.yaml \
        --workers 8 \
        --objective total_pnl
    
    # Custom output location
    python optimization/grid_search.py \
        --config optimization/grid_config.yaml \
        --output optimization/results/my_grid_search.csv
    
    # Resume from checkpoint after interruption
    python optimization/grid_search.py \
        --config optimization/grid_config.yaml \
        --resume
    
    # Start fresh (ignore checkpoint)
    python optimization/grid_search.py \
        --config optimization/grid_config.yaml \
        --no-resume
    
    # Verbose logging for debugging
    python optimization/grid_search.py \
        --config optimization/grid_config.yaml \
        --workers 4 \
        --verbose

Outputs:
    - CSV: All backtest results with parameters and metrics
    - JSON: Top 10 parameter sets for further validation
    - JSON: Summary statistics (best, worst, averages)
    - Checkpoint: Intermediate results (auto-saved every 10 runs)

Exit Codes:
    0: Optimization completed successfully
    1: All backtests failed or critical error
    2: Configuration error or invalid parameters
    130: Interrupted by user (Ctrl+C)
"""

import argparse
import csv
import itertools
import json
import logging
import multiprocessing
import os
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd
import yaml

# Setup project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# Objective direction metadata
# Single source of truth for whether an objective should be maximized or minimized
OBJECTIVE_DIRECTIONS: Dict[str, str] = {
    # Existing objectives (maximize)
    "total_pnl": "maximize",
    "sharpe_ratio": "maximize",
    "win_rate": "maximize",
    "profit_factor": "maximize",
    "calmar_ratio": "maximize",
    "sortino_ratio": "maximize",
    # Aliases for clarity (maximize)
    "max_win_rate": "maximize",
    "max_profit_factor": "maximize",
    # New minimization objectives
    "max_drawdown": "minimize",
    "min_max_drawdown": "minimize",
    "consecutive_losses": "minimize",
    "min_consecutive_losses": "minimize",
}


def is_minimization_objective(objective: str) -> bool:
    """Return True if the objective should be minimized."""
    return OBJECTIVE_DIRECTIONS.get(objective, "maximize") == "minimize"


@dataclass
class OptimizationConfig:
    """Configuration for optimization settings."""
    objective: str
    workers: int = 8
    checkpoint_interval: int = 10
    checkpoint_file: str = "optimization_checkpoint.csv"
    output_file: str = "grid_search_results.csv"
    timeout_seconds: int = 300


# Fixed parameter to environment variable mapping
FIXED_TO_ENV = {
    # Risk Management Parameters
    "stop_loss_pips": "BACKTEST_STOP_LOSS_PIPS",
    "take_profit_pips": "BACKTEST_TAKE_PROFIT_PIPS",
    "trailing_stop_activation_pips": "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS",
    "trailing_stop_distance_pips": "BACKTEST_TRAILING_STOP_DISTANCE_PIPS",
    # Multi-timeframe parameters
    "trend_filter_enabled": "BACKTEST_TREND_FILTER_ENABLED",
    "trend_bar_spec": "BACKTEST_TREND_BAR_SPEC",
    "trend_fast_period": "BACKTEST_TREND_FAST_PERIOD",
    "trend_slow_period": "BACKTEST_TREND_SLOW_PERIOD",
    "entry_timing_enabled": "BACKTEST_ENTRY_TIMING_ENABLED",
    "entry_timing_bar_spec": "BACKTEST_ENTRY_TIMING_BAR_SPEC",
    "entry_timing_method": "BACKTEST_ENTRY_TIMING_METHOD",
    "entry_timing_timeout_bars": "BACKTEST_ENTRY_TIMING_TIMEOUT_BARS",
    
    # Crossover Filter Parameters
    "pre_crossover_separation_pips": "STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS",
    "pre_crossover_lookback_bars": "STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS",
    
    # DMI Filter Parameters
    "dmi_enabled": "STRATEGY_DMI_ENABLED",
    "dmi_period": "STRATEGY_DMI_PERIOD",
    "dmi_bar_spec": "STRATEGY_DMI_BAR_SPEC",
    "dmi_minimum_difference": "STRATEGY_DMI_MINIMUM_DIFFERENCE",
    
    # Stochastic Filter Parameters
    "stoch_enabled": "STRATEGY_STOCH_ENABLED",
    "stoch_period_k": "STRATEGY_STOCH_PERIOD_K",
    "stoch_period_d": "STRATEGY_STOCH_PERIOD_D",
    "stoch_bullish_threshold": "STRATEGY_STOCH_BULLISH_THRESHOLD",
    "stoch_bearish_threshold": "STRATEGY_STOCH_BEARISH_THRESHOLD",
    "stoch_max_bars_since_crossing": "STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING",
    "stoch_bar_spec": "STRATEGY_STOCH_BAR_SPEC",
    
    # Trade Sizing and Position Management
    "trade_size": "BACKTEST_TRADE_SIZE",
    "enforce_position_limit": "ENFORCE_POSITION_LIMIT",
    "allow_position_reversal": "ALLOW_POSITION_REVERSAL",
    
    # Optional overrides
    "bar_spec": "BACKTEST_BAR_SPEC",
    "starting_capital": "BACKTEST_STARTING_CAPITAL",
    
    # Regime Detection Parameters
    "regime_detection_enabled": "STRATEGY_REGIME_DETECTION_ENABLED",
    "regime_adx_trending_threshold": "STRATEGY_REGIME_ADX_TRENDING_THRESHOLD",
    "regime_adx_ranging_threshold": "STRATEGY_REGIME_ADX_RANGING_THRESHOLD",
    "regime_tp_multiplier_trending": "STRATEGY_REGIME_TP_MULTIPLIER_TRENDING",
    "regime_tp_multiplier_ranging": "STRATEGY_REGIME_TP_MULTIPLIER_RANGING",
    "regime_sl_multiplier_trending": "STRATEGY_REGIME_SL_MULTIPLIER_TRENDING",
    "regime_sl_multiplier_ranging": "STRATEGY_REGIME_SL_MULTIPLIER_RANGING",
    "regime_trailing_activation_multiplier_trending": "STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING",
    "regime_trailing_activation_multiplier_ranging": "STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING",
    "regime_trailing_distance_multiplier_trending": "STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING",
    "regime_trailing_distance_multiplier_ranging": "STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING",
}

def fixed_to_env(fixed: dict[str, Any]) -> dict[str, str]:
    env = {}
    for k, v in fixed.items():
        env_name = FIXED_TO_ENV.get(k)
        if env_name is None:
            continue
        if isinstance(v, bool):
            env[env_name] = str(v).lower()
        else:
            env[env_name] = str(v)
    return env


@dataclass
class ParameterSet:
    """A single parameter combination for backtesting."""
    run_id: int
    fast_period: int
    slow_period: int
    crossover_threshold_pips: float
    stop_loss_pips: int
    take_profit_pips: int
    trailing_stop_activation_pips: int
    trailing_stop_distance_pips: int
    dmi_enabled: bool = True
    dmi_period: int = 14
    dmi_minimum_difference: float = 0.0
    stoch_enabled: bool = True
    stoch_period_k: int = 14
    stoch_period_d: int = 3
    stoch_bullish_threshold: int = 30
    stoch_bearish_threshold: int = 70
    # Multi-timeframe parameters (all default to disabled/False for zero impact)
    trend_filter_enabled: bool = False
    trend_bar_spec: str = "1-HOUR-MID-EXTERNAL"
    trend_fast_period: int = 20
    trend_slow_period: int = 50
    entry_timing_enabled: bool = False
    entry_timing_bar_spec: str = "5-MINUTE-MID-EXTERNAL"
    entry_timing_method: str = "pullback"
    entry_timing_timeout_bars: int = 10
    # Primary bar specification (for signal generation)
    bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    # Regime Detection Parameters
    regime_detection_enabled: bool = False
    regime_adx_trending_threshold: float = 25.0
    regime_adx_ranging_threshold: float = 20.0
    regime_tp_multiplier_trending: float = 1.5
    regime_tp_multiplier_ranging: float = 0.8
    regime_sl_multiplier_trending: float = 1.0
    regime_sl_multiplier_ranging: float = 1.0
    regime_trailing_activation_multiplier_trending: float = 0.75
    regime_trailing_activation_multiplier_ranging: float = 1.25
    regime_trailing_distance_multiplier_trending: float = 0.67
    regime_trailing_distance_multiplier_ranging: float = 1.33

    def to_env_dict(self) -> Dict[str, str]:
        """Convert parameters to environment variable dictionary."""
        return {
            "BACKTEST_FAST_PERIOD": str(self.fast_period),
            "BACKTEST_SLOW_PERIOD": str(self.slow_period),
            "BACKTEST_STOP_LOSS_PIPS": str(self.stop_loss_pips),
            "BACKTEST_TAKE_PROFIT_PIPS": str(self.take_profit_pips),
            "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": str(self.trailing_stop_activation_pips),
            "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": str(self.trailing_stop_distance_pips),
            "STRATEGY_CROSSOVER_THRESHOLD_PIPS": str(self.crossover_threshold_pips),
            "STRATEGY_DMI_ENABLED": str(self.dmi_enabled).lower(),
            "STRATEGY_DMI_PERIOD": str(self.dmi_period),
            "STRATEGY_DMI_MINIMUM_DIFFERENCE": str(self.dmi_minimum_difference),
            "STRATEGY_STOCH_ENABLED": str(self.stoch_enabled).lower(),
            "STRATEGY_STOCH_PERIOD_K": str(self.stoch_period_k),
            "STRATEGY_STOCH_PERIOD_D": str(self.stoch_period_d),
            "STRATEGY_STOCH_BULLISH_THRESHOLD": str(self.stoch_bullish_threshold),
            "STRATEGY_STOCH_BEARISH_THRESHOLD": str(self.stoch_bearish_threshold),
            # Multi-timeframe parameters
            "BACKTEST_TREND_FILTER_ENABLED": str(self.trend_filter_enabled).lower(),
            "BACKTEST_TREND_BAR_SPEC": str(self.trend_bar_spec),
            "BACKTEST_TREND_FAST_PERIOD": str(self.trend_fast_period),
            "BACKTEST_TREND_SLOW_PERIOD": str(self.trend_slow_period),
            "BACKTEST_ENTRY_TIMING_ENABLED": str(self.entry_timing_enabled).lower(),
            "BACKTEST_ENTRY_TIMING_BAR_SPEC": str(self.entry_timing_bar_spec),
            "BACKTEST_ENTRY_TIMING_METHOD": str(self.entry_timing_method),
            "BACKTEST_ENTRY_TIMING_TIMEOUT_BARS": str(self.entry_timing_timeout_bars),
            # Primary bar specification
            "BACKTEST_BAR_SPEC": str(self.bar_spec),
            # Regime Detection Parameters
            "STRATEGY_REGIME_DETECTION_ENABLED": str(self.regime_detection_enabled).lower(),
            "STRATEGY_REGIME_ADX_TRENDING_THRESHOLD": str(self.regime_adx_trending_threshold),
            "STRATEGY_REGIME_ADX_RANGING_THRESHOLD": str(self.regime_adx_ranging_threshold),
            "STRATEGY_REGIME_TP_MULTIPLIER_TRENDING": str(self.regime_tp_multiplier_trending),
            "STRATEGY_REGIME_TP_MULTIPLIER_RANGING": str(self.regime_tp_multiplier_ranging),
            "STRATEGY_REGIME_SL_MULTIPLIER_TRENDING": str(self.regime_sl_multiplier_trending),
            "STRATEGY_REGIME_SL_MULTIPLIER_RANGING": str(self.regime_sl_multiplier_ranging),
            "STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING": str(self.regime_trailing_activation_multiplier_trending),
            "STRATEGY_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING": str(self.regime_trailing_activation_multiplier_ranging),
            "STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING": str(self.regime_trailing_distance_multiplier_trending),
            "STRATEGY_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING": str(self.regime_trailing_distance_multiplier_ranging),
        }


@dataclass
class BacktestResult:
    """Results from a single backtest run."""
    run_id: int
    parameters: ParameterSet
    total_pnl: float
    sharpe_ratio: float
    win_rate: float
    max_drawdown: float
    trade_count: int
    avg_winner: float
    avg_loser: float
    profit_factor: float
    expectancy: float
    rejected_signals_count: int
    status: str
    error_message: str
    backtest_duration_seconds: float
    output_directory: str
    consecutive_losses: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to flat dictionary for CSV export."""
        result = asdict(self.parameters)
        result.update({
            "run_id": self.run_id,
            "total_pnl": self.total_pnl,
            "sharpe_ratio": self.sharpe_ratio,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
            "trade_count": self.trade_count,
            "avg_winner": self.avg_winner,
            "avg_loser": self.avg_loser,
            "profit_factor": self.profit_factor,
            "expectancy": self.expectancy,
            "rejected_signals_count": self.rejected_signals_count,
            "status": self.status,
            "error_message": self.error_message,
            "backtest_duration_seconds": self.backtest_duration_seconds,
            "output_directory": self.output_directory,
            "consecutive_losses": self.consecutive_losses,
        })
        return result

    def get_objective_value(self, objective: str) -> float:
        """Extract value for specified objective function."""
        if objective == "total_pnl":
            return self.total_pnl
        elif objective == "sharpe_ratio":
            return self.sharpe_ratio
        elif objective == "win_rate":
            return self.win_rate
        elif objective == "profit_factor":
            return self.profit_factor
        elif objective == "max_win_rate":
            return self.win_rate
        elif objective == "max_profit_factor":
            return self.profit_factor
        elif objective == "max_drawdown" or objective == "min_max_drawdown":
            return self.max_drawdown
        elif objective == "consecutive_losses" or objective == "min_consecutive_losses":
            return float(self.consecutive_losses)
        elif objective == "calmar_ratio":
            return self.total_pnl / abs(self.max_drawdown) if self.max_drawdown != 0 else 0.0
        elif objective == "sortino_ratio":
            # Simplified sortino (would need downside deviation calculation)
            return self.sharpe_ratio
        else:
            raise ValueError(f"Unknown objective: {objective}")


def load_grid_config(config_path: Path) -> Tuple[OptimizationConfig, Dict[str, List[Any]], Dict[str, Any]]:
    """Load and validate YAML configuration."""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML configuration: {e}")
    except FileNotFoundError:
        raise ValueError(f"Configuration file not found: {config_path}")

    # Extract optimization settings
    opt_section = config.get("optimization", {})
    objective = opt_section.get("objective", "total_pnl")
    
    if objective not in OBJECTIVE_DIRECTIONS.keys():
        raise ValueError(f"Invalid objective: {objective}")
    if is_minimization_objective(objective):
        logger.warning(f"Using minimization objective: {objective}")

    opt_config = OptimizationConfig(
        objective=objective,
        workers=opt_section.get("workers", 8),
        checkpoint_interval=opt_section.get("checkpoint_interval", 10),
        checkpoint_file=opt_section.get("checkpoint_file", "optimization_checkpoint.csv"),
        output_file=opt_section.get("output_file", "grid_search_results.csv"),
        timeout_seconds=opt_section.get("timeout_seconds", 300)
    )

    # Extract parameter ranges
    param_ranges = config.get("parameters", {})
    if not param_ranges:
        raise ValueError("No parameters specified in configuration")

    # Validate parameter names and types
    valid_params = {
        "fast_period", "slow_period", "crossover_threshold_pips", "stop_loss_pips",
        "take_profit_pips", "trailing_stop_activation_pips", "trailing_stop_distance_pips",
        "dmi_enabled", "dmi_period", "dmi_minimum_difference", "stoch_enabled", "stoch_period_k", "stoch_period_d",
        "stoch_bullish_threshold", "stoch_bearish_threshold",
        # Multi-timeframe parameters
        "trend_filter_enabled", "trend_bar_spec", "trend_fast_period", "trend_slow_period",
        "entry_timing_enabled", "entry_timing_bar_spec", "entry_timing_method", "entry_timing_timeout_bars",
        # Primary bar specification (for signal generation)
        "bar_spec",
        # Regime Detection Parameters
        "regime_detection_enabled", "regime_adx_trending_threshold", "regime_adx_ranging_threshold",
        "regime_tp_multiplier_trending", "regime_tp_multiplier_ranging",
        "regime_sl_multiplier_trending", "regime_sl_multiplier_ranging",
        "regime_trailing_activation_multiplier_trending", "regime_trailing_activation_multiplier_ranging",
        "regime_trailing_distance_multiplier_trending", "regime_trailing_distance_multiplier_ranging"
    }

    for param_name, param_config in param_ranges.items():
        if param_name not in valid_params:
            raise ValueError(f"Invalid parameter: {param_name}")
        
        values = param_config.get("values", [])
        if not values:
            raise ValueError(f"Parameter {param_name} has no values")
        
        # Validate value types
        for value in values:
            if param_name in ["dmi_enabled", "stoch_enabled", "trend_filter_enabled", "entry_timing_enabled", "regime_detection_enabled"]:
                if not isinstance(value, bool):
                    raise ValueError(f"Parameter {param_name} values must be boolean")
            elif param_name in ["crossover_threshold_pips", "dmi_minimum_difference", 
                               "regime_adx_trending_threshold", "regime_adx_ranging_threshold",
                               "regime_tp_multiplier_trending", "regime_tp_multiplier_ranging",
                               "regime_sl_multiplier_trending", "regime_sl_multiplier_ranging",
                               "regime_trailing_activation_multiplier_trending", "regime_trailing_activation_multiplier_ranging",
                               "regime_trailing_distance_multiplier_trending", "regime_trailing_distance_multiplier_ranging"]:
                if not isinstance(value, (int, float)):
                    raise ValueError(f"Parameter {param_name} values must be numeric")
            elif param_name in ["trend_bar_spec", "entry_timing_bar_spec", "entry_timing_method", "bar_spec"]:
                if not isinstance(value, str):
                    raise ValueError(f"Parameter {param_name} values must be strings")
            else:
                if not isinstance(value, int):
                    raise ValueError(f"Parameter {param_name} values must be integers")

    # Extract fixed parameters
    fixed_params = config.get("fixed", {})

    return opt_config, param_ranges, fixed_params


def generate_parameter_combinations(param_ranges: Dict[str, List[Any]], fixed_params: Dict[str, Any]) -> List[ParameterSet]:
    """Generate all parameter combinations with unique run IDs."""
    # Extract parameter names and values
    param_names = list(param_ranges.keys())
    param_values = [param_ranges[name]["values"] for name in param_names]
    
    combinations = []
    run_id = 1
    
    for combination in itertools.product(*param_values):
        # Create parameter dictionary
        params_dict = dict(zip(param_names, combination))
        
        # Merge with fixed parameters
        params_dict.update(fixed_params)
        
        # Create ParameterSet object
        try:
            params = ParameterSet(
                run_id=run_id,
                fast_period=params_dict.get("fast_period", 10),
                slow_period=params_dict.get("slow_period", 20),
                crossover_threshold_pips=params_dict.get("crossover_threshold_pips", 0.7),
                stop_loss_pips=params_dict.get("stop_loss_pips", 25),
                take_profit_pips=params_dict.get("take_profit_pips", 50),
                trailing_stop_activation_pips=params_dict.get("trailing_stop_activation_pips", 20),
                trailing_stop_distance_pips=params_dict.get("trailing_stop_distance_pips", 15),
                dmi_enabled=params_dict.get("dmi_enabled", True),
                dmi_period=params_dict.get("dmi_period", 14),
                dmi_minimum_difference=params_dict.get("dmi_minimum_difference", 0.0),
                stoch_enabled=params_dict.get("stoch_enabled", True),
                stoch_period_k=params_dict.get("stoch_period_k", 14),
                stoch_period_d=params_dict.get("stoch_period_d", 3),
                stoch_bullish_threshold=params_dict.get("stoch_bullish_threshold", 30),
                stoch_bearish_threshold=params_dict.get("stoch_bearish_threshold", 70),
                # Multi-timeframe parameters (default to disabled)
                trend_filter_enabled=params_dict.get("trend_filter_enabled", False),
                trend_bar_spec=params_dict.get("trend_bar_spec", "1-HOUR-MID-EXTERNAL"),
                trend_fast_period=params_dict.get("trend_fast_period", 20),
                trend_slow_period=params_dict.get("trend_slow_period", 50),
                entry_timing_enabled=params_dict.get("entry_timing_enabled", False),
                entry_timing_bar_spec=params_dict.get("entry_timing_bar_spec", "5-MINUTE-MID-EXTERNAL"),
                entry_timing_method=params_dict.get("entry_timing_method", "pullback"),
                entry_timing_timeout_bars=params_dict.get("entry_timing_timeout_bars", 10),
                # Primary bar specification
                bar_spec=params_dict.get("bar_spec", "15-MINUTE-MID-EXTERNAL"),
                # Regime Detection Parameters
                regime_detection_enabled=params_dict.get("regime_detection_enabled", False),
                regime_adx_trending_threshold=params_dict.get("regime_adx_trending_threshold", 25.0),
                regime_adx_ranging_threshold=params_dict.get("regime_adx_ranging_threshold", 20.0),
                regime_tp_multiplier_trending=params_dict.get("regime_tp_multiplier_trending", 1.5),
                regime_tp_multiplier_ranging=params_dict.get("regime_tp_multiplier_ranging", 0.8),
                regime_sl_multiplier_trending=params_dict.get("regime_sl_multiplier_trending", 1.0),
                regime_sl_multiplier_ranging=params_dict.get("regime_sl_multiplier_ranging", 1.0),
                regime_trailing_activation_multiplier_trending=params_dict.get("regime_trailing_activation_multiplier_trending", 0.75),
                regime_trailing_activation_multiplier_ranging=params_dict.get("regime_trailing_activation_multiplier_ranging", 1.25),
                regime_trailing_distance_multiplier_trending=params_dict.get("regime_trailing_distance_multiplier_trending", 0.67),
                regime_trailing_distance_multiplier_ranging=params_dict.get("regime_trailing_distance_multiplier_ranging", 1.33),
            )
            
            # Validate combination
            is_valid, error_msg = validate_parameter_combination(params)
            if is_valid:
                combinations.append(params)
                run_id += 1
            else:
                logger.warning(f"Skipping invalid combination {run_id}: {error_msg}")
                run_id += 1
                
        except Exception as e:
            logger.warning(f"Skipping invalid combination {run_id}: {e}")
            run_id += 1
    
    logger.info(f"Generated {len(combinations)} valid parameter combinations")
    return combinations


def validate_parameter_combination(params: ParameterSet) -> Tuple[bool, Optional[str]]:
    """Validate parameter relationships."""
    if params.fast_period >= params.slow_period:
        return False, "fast_period must be less than slow_period"
    
    if params.take_profit_pips <= params.stop_loss_pips:
        return False, "take_profit_pips must be greater than stop_loss_pips"
    
    if params.trailing_stop_activation_pips <= params.trailing_stop_distance_pips:
        return False, "trailing_stop_activation_pips must be greater than trailing_stop_distance_pips"
    
    if params.stoch_bullish_threshold >= params.stoch_bearish_threshold:
        return False, "stoch_bullish_threshold must be less than stoch_bearish_threshold"
    
    # Multi-timeframe validations
    if params.trend_filter_enabled:
        if params.trend_fast_period >= params.trend_slow_period:
            return False, "trend_fast_period must be less than trend_slow_period"
    
    if params.entry_timing_enabled:
        if params.entry_timing_timeout_bars <= 0:
            return False, "entry_timing_timeout_bars must be greater than 0"
        if params.entry_timing_method not in ["pullback", "rsi", "stochastic", "breakout"]:
            return False, f"entry_timing_method must be one of: pullback, rsi, stochastic, breakout"
    
    return True, None


def extract_metrics_from_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Shared helper to parse performance_stats.json structure consistently.
    
    This function provides a single source of truth for extracting metrics
    from the performance_stats.json file structure used by both grid_search.py
    and validate_baseline.py.
    """
    metrics = {}
    
    # Extract PnL metrics (consistent key names)
    pnls = stats.get("pnls", {})
    metrics["total_pnl"] = pnls.get("PnL (total)", 0.0)
    metrics["pnl_percentage"] = pnls.get("PnL% (total)", 0.0)
    metrics["max_winner"] = pnls.get("Max Winner", 0.0)
    metrics["avg_winner"] = pnls.get("Avg Winner", 0.0)
    metrics["max_loser"] = pnls.get("Max Loser", 0.0)
    metrics["avg_loser"] = pnls.get("Avg Loser", 0.0)
    metrics["expectancy"] = pnls.get("Expectancy", 0.0)
    metrics["win_rate"] = pnls.get("Win Rate", 0.0)
    
    # Extract general metrics (consistent key names)
    general = stats.get("general", {})
    metrics["trade_count"] = general.get("Total trades", 0)
    metrics["sharpe_ratio"] = general.get("Sharpe ratio", 0.0)
    metrics["profit_factor"] = general.get("Profit factor", 0.0)
    metrics["max_drawdown"] = abs(general.get("Max drawdown", 0.0))
    
    # Extract rejected signals count
    metrics["rejected_signals_count"] = stats.get("rejected_signals_count", 0)
    
    return metrics


def extract_metrics(stats: Dict[str, Any], output_directory: Optional[Path] = None) -> Dict[str, float]:
    """Extract all relevant metrics from performance_stats.json and optionally compute
    consecutive_losses from positions.csv in the provided output directory.
    """
    metrics = extract_metrics_from_stats(stats)

    # Fallback calculation for trade count: should rarely trigger now that run_backtest.py generates complete metrics
    # This serves as a safety net for legacy result files or edge cases where metric calculation might fail
    if metrics["trade_count"] == 0 and output_directory is not None:
        try:
            positions_file = Path(output_directory) / "positions.csv"
            if positions_file.exists():
                df_pos = pd.read_csv(positions_file)
                if not df_pos.empty:
                    # Filter to closed positions if column exists
                    if "ts_closed" in df_pos.columns:
                        df_pos = df_pos[df_pos["ts_closed"].notna()].copy()
                    # Count all rows as trades (matching test file behavior)
                    # Note: The test files check first column for 'snapshot' but positions.csv
                    # first column is always 'trader_id', so all rows are counted as trades
                    position_rows = len(df_pos)
                    metrics["trade_count"] = position_rows
                    logger.debug(f"Fallback: Calculated trade count from positions.csv: {metrics['trade_count']} trades")
        except Exception as e:
            logger.warning(f"Failed to extract trade count from positions.csv: {e}")

    # Fallback calculation for Sharpe ratio: should rarely trigger now that run_backtest.py generates complete metrics
    # This serves as a safety net for legacy result files or edge cases where metric calculation might fail
    if metrics["sharpe_ratio"] == 0.0 and output_directory is not None:
        try:
            positions_file = Path(output_directory) / "positions.csv"
            if positions_file.exists():
                df_pos = pd.read_csv(positions_file)
                if not df_pos.empty and 'realized_return' in df_pos.columns:
                    # Filter to closed positions if column exists
                    if "ts_closed" in df_pos.columns:
                        df_pos = df_pos[df_pos["ts_closed"].notna()].copy()
                    
                    # Calculate Sharpe ratio from realized returns
                    returns = df_pos['realized_return'].dropna()
                    if len(returns) >= 2:
                        mean_return = returns.mean()
                        std_return = returns.std()
                        if std_return > 0:
                            metrics["sharpe_ratio"] = mean_return / std_return
                            logger.debug(f"Fallback: Calculated Sharpe ratio from positions.csv: {metrics['sharpe_ratio']:.3f}")
        except Exception as e:
            logger.warning(f"Failed to calculate Sharpe ratio from positions.csv: {e}")

    # Compute consecutive_losses if output_directory is provided
    metrics["consecutive_losses"] = 0
    try:
        if output_directory is not None:
            positions_file = Path(output_directory) / "positions.csv"
            if positions_file.exists():
                df_pos = pd.read_csv(positions_file)
                if not df_pos.empty:
                    # Filter to closed positions if column exists
                    if "ts_closed" in df_pos.columns:
                        df_pos = df_pos[df_pos["ts_closed"].notna()].copy()
                    # Sort by close time if present, otherwise by open time or index
                    sort_col = "ts_closed" if "ts_closed" in df_pos.columns else ("ts_opened" if "ts_opened" in df_pos.columns else None)
                    if sort_col is not None:
                        df_pos = df_pos.sort_values(sort_col)

                    # Parse realized PnL column name variants
                    pnl_col = None
                    for candidate in [
                        "realized_pnl",
                        "realized_pnl_ccy",
                        "realized_pnl_quote",
                        "realized_pnl_usd",
                        "pnl_realized",
                    ]:
                        if candidate in df_pos.columns:
                            pnl_col = candidate
                            break

                    # If not found, try to derive from any column containing 'pnl' and 'real'
                    if pnl_col is None:
                        for c in df_pos.columns:
                            cs = str(c).lower()
                            if "pnl" in cs and ("real" in cs or "realized" in cs):
                                pnl_col = c
                                break

                    max_streak = 0
                    current_streak = 0
                    if pnl_col is not None:
                        # Ensure numeric; strip possible currency suffixes
                        series = df_pos[pnl_col]
                        if series.dtype == object:
                            series = series.astype(str).str.replace(r"[^0-9+\-\.eE]", "", regex=True)
                        pnl_values = pd.to_numeric(series, errors="coerce").fillna(0.0).tolist()

                        # Optional toggle to include break-evens in loss streak (default: exclude)
                        include_breakeven = parse_bool(os.environ.get("INCLUDE_BREAKEVEN_IN_LOSS_STREAK", False))
                        for pnl in pnl_values:
                            if (pnl < 0) or (include_breakeven and pnl == 0):
                                current_streak += 1
                                if current_streak > max_streak:
                                    max_streak = current_streak
                            else:
                                current_streak = 0
                    metrics["consecutive_losses"] = int(max_streak)
    except Exception as e:
        logger.warning(f"Failed to compute consecutive_losses: {e}")
        metrics["consecutive_losses"] = 0

    return metrics


def find_latest_backtest_output(base_dir: Path, symbol: str) -> Optional[Path]:
    """Find most recent backtest output directory."""
    results_dir = base_dir / "logs" / "backtest_results"
    if not results_dir.exists():
        return None
    
    # Find directories matching pattern {symbol}_*
    pattern_dirs = [d for d in results_dir.iterdir() if d.is_dir() and d.name.startswith(f"{symbol}_")]
    
    if not pattern_dirs:
        return None
    
    # Sort by timestamp in directory name and return most recent
    pattern_dirs.sort(key=lambda x: x.name, reverse=True)
    return pattern_dirs[0]


def run_single_backtest(params: ParameterSet, base_env: Dict[str, str], timeout: int, fixed_params: Dict[str, Any] = None) -> BacktestResult:
    """Execute a single backtest with given parameters."""
    try:
        # Prepare environment
        env = base_env.copy()
        env.update(params.to_env_dict())
        if fixed_params:
            env.update(fixed_to_env(fixed_params))
        
        # Ensure required environment variables are present
        required_vars = ["BACKTEST_SYMBOL", "BACKTEST_START_DATE", "BACKTEST_END_DATE"]
        for var in required_vars:
            if var not in env:
                return BacktestResult(
                    run_id=params.run_id,
                    parameters=params,
                    total_pnl=0.0, sharpe_ratio=0.0, win_rate=0.0, max_drawdown=0.0,
                    trade_count=0, avg_winner=0.0, avg_loser=0.0, profit_factor=0.0,
                    expectancy=0.0, rejected_signals_count=0,
                    status="failed", error_message=f"Missing environment variable: {var}",
                    backtest_duration_seconds=0.0, output_directory="", consecutive_losses=0
                )
        
        # Execute backtest subprocess
        start_time = time.time()
        # Optionally force child stdout encoding via PYTHONIOENCODING to reduce replacements
        if 'PYTHONIOENCODING' not in env:
            env['PYTHONIOENCODING'] = 'utf-8'
        result = subprocess.run(
            [sys.executable, "backtest/run_backtest.py"],
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            cwd=str(PROJECT_ROOT)
        )
        duration = time.time() - start_time
        
        # Check subprocess exit code
        if result.returncode != 0:
            return BacktestResult(
                run_id=params.run_id,
                parameters=params,
                total_pnl=0.0, sharpe_ratio=0.0, win_rate=0.0, max_drawdown=0.0,
                trade_count=0, avg_winner=0.0, avg_loser=0.0, profit_factor=0.0,
                expectancy=0.0, rejected_signals_count=0,
                status="failed", error_message=result.stderr.strip(),
                backtest_duration_seconds=duration, output_directory="", consecutive_losses=0
            )
        
        # Find output directory
        output_dir = None
        
        # Try to parse from stdout
        import re
        match = re.search(r"Results written to: (.+)", result.stdout)
        if match:
            output_dir = Path(match.group(1))
        else:
            # Fallback: find most recent output directory
            symbol = env.get("BACKTEST_SYMBOL", "EUR-USD")
            output_dir = find_latest_backtest_output(PROJECT_ROOT, symbol)
        
        if not output_dir or not output_dir.exists():
            return BacktestResult(
                run_id=params.run_id,
                parameters=params,
                total_pnl=0.0, sharpe_ratio=0.0, win_rate=0.0, max_drawdown=0.0,
                trade_count=0, avg_winner=0.0, avg_loser=0.0, profit_factor=0.0,
                expectancy=0.0, rejected_signals_count=0,
                status="failed", error_message="No backtest output directory found",
                backtest_duration_seconds=duration, output_directory="", consecutive_losses=0
            )
        
        # Load performance stats
        stats_file = output_dir / "performance_stats.json"
        if not stats_file.exists():
            return BacktestResult(
                run_id=params.run_id,
                parameters=params,
                total_pnl=0.0, sharpe_ratio=0.0, win_rate=0.0, max_drawdown=0.0,
                trade_count=0, avg_winner=0.0, avg_loser=0.0, profit_factor=0.0,
                expectancy=0.0, rejected_signals_count=0,
                status="failed", error_message="No performance stats generated",
                backtest_duration_seconds=duration, output_directory=str(output_dir), consecutive_losses=0
            )
        
        with open(stats_file, 'r') as f:
            stats = json.load(f)
        
        metrics = extract_metrics(stats, output_dir)
        
        # Create BacktestResult
        return BacktestResult(
            run_id=params.run_id,
            parameters=params,
            total_pnl=metrics["total_pnl"],
            sharpe_ratio=metrics["sharpe_ratio"],
            win_rate=metrics["win_rate"],
            max_drawdown=metrics["max_drawdown"],
            trade_count=metrics["trade_count"],
            avg_winner=metrics["avg_winner"],
            avg_loser=metrics["avg_loser"],
            profit_factor=metrics["profit_factor"],
            expectancy=metrics["expectancy"],
            rejected_signals_count=metrics["rejected_signals_count"],
            status="completed",
            error_message="",
            backtest_duration_seconds=duration,
            output_directory=str(output_dir),
            consecutive_losses=metrics.get("consecutive_losses", 0)
        )
        
    except subprocess.TimeoutExpired:
        return BacktestResult(
            run_id=params.run_id,
            parameters=params,
            total_pnl=0.0, sharpe_ratio=0.0, win_rate=0.0, max_drawdown=0.0,
            trade_count=0, avg_winner=0.0, avg_loser=0.0, profit_factor=0.0,
            expectancy=0.0, rejected_signals_count=0,
            status="timeout", error_message=f"Backtest timed out after {timeout} seconds",
            backtest_duration_seconds=timeout, output_directory="", consecutive_losses=0
        )
    except Exception as e:
        return BacktestResult(
            run_id=params.run_id,
            parameters=params,
            total_pnl=0.0, sharpe_ratio=0.0, win_rate=0.0, max_drawdown=0.0,
            trade_count=0, avg_winner=0.0, avg_loser=0.0, profit_factor=0.0,
            expectancy=0.0, rejected_signals_count=0,
            status="failed", error_message=str(e),
            backtest_duration_seconds=0.0, output_directory="", consecutive_losses=0
        )


def _worker_run_backtest(args: Tuple[ParameterSet, Dict[str, str], int, Dict[str, Any]]) -> BacktestResult:
    """Worker function for multiprocessing."""
    params, base_env, timeout, fixed_params = args
    return run_single_backtest(params, base_env, timeout, fixed_params)


def save_checkpoint(results: List[BacktestResult], checkpoint_file: str) -> None:
    """Save intermediate results to CSV with directory creation and error handling."""
    if not results:
        return
    
    try:
        # Ensure checkpoint directory exists
        checkpoint_path = Path(checkpoint_file)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        
        results_dicts = [result.to_dict() for result in results]
        df = pd.DataFrame(results_dicts)
        df.to_csv(checkpoint_file, index=False)
        logger.info(f"Checkpoint saved: {len(results)} results to {checkpoint_file}")
    except OSError as e:
        logger.error(f"Failed to save checkpoint to {checkpoint_file}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error saving checkpoint: {e}")
        raise


def parse_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "1", "yes")


def load_checkpoint(checkpoint_file: str) -> List[BacktestResult]:
    """Load previously completed results with enhanced logging and error handling."""
    checkpoint_path = Path(checkpoint_file)
    if not checkpoint_path.exists():
        logger.info(f"No checkpoint file found at {checkpoint_file}")
        return []
    
    try:
        logger.info(f"Loading checkpoint from {checkpoint_file}")
        df = pd.read_csv(checkpoint_file)
        results = []
        
        for _, row in df.iterrows():
            # Create ParameterSet from row
            params = ParameterSet(
                run_id=int(row["run_id"]),
                fast_period=int(row["fast_period"]),
                slow_period=int(row["slow_period"]),
                crossover_threshold_pips=float(row["crossover_threshold_pips"]),
                stop_loss_pips=int(row["stop_loss_pips"]),
                take_profit_pips=int(row["take_profit_pips"]),
                trailing_stop_activation_pips=int(row["trailing_stop_activation_pips"]),
                trailing_stop_distance_pips=int(row["trailing_stop_distance_pips"]),
                dmi_enabled=parse_bool(row["dmi_enabled"]),
                dmi_period=int(row["dmi_period"]),
                dmi_minimum_difference=float(row.get("dmi_minimum_difference", 0.0)),
                stoch_enabled=parse_bool(row["stoch_enabled"]),
                stoch_period_k=int(row["stoch_period_k"]),
                stoch_period_d=int(row["stoch_period_d"]),
                stoch_bullish_threshold=int(row["stoch_bullish_threshold"]),
                stoch_bearish_threshold=int(row["stoch_bearish_threshold"]),
            )
            
            # Create BacktestResult from row
            result = BacktestResult(
                run_id=int(row["run_id"]),
                parameters=params,
                total_pnl=float(row["total_pnl"]),
                sharpe_ratio=float(row["sharpe_ratio"]),
                win_rate=float(row["win_rate"]),
                max_drawdown=float(row["max_drawdown"]),
                trade_count=int(row["trade_count"]),
                avg_winner=float(row["avg_winner"]),
                avg_loser=float(row["avg_loser"]),
                profit_factor=float(row["profit_factor"]),
                expectancy=float(row["expectancy"]),
                rejected_signals_count=int(row["rejected_signals_count"]),
                status=str(row["status"]),
                error_message=str(row["error_message"]),
                backtest_duration_seconds=float(row["backtest_duration_seconds"]),
                output_directory=str(row["output_directory"]),
                consecutive_losses=int(row.get("consecutive_losses", 0)) if "consecutive_losses" in row else 0,
            )
            
            results.append(result)
        
        logger.info(f"Successfully loaded checkpoint: {len(results)} completed results from {checkpoint_file}")
        logger.info(f"Checkpoint file used: {checkpoint_file}")
        logger.info(f"Number of restored records: {len(results)}")
        return results
        
    except FileNotFoundError:
        logger.warning(f"Checkpoint file not found: {checkpoint_file}")
        return []
    except pd.errors.EmptyDataError:
        logger.warning(f"Checkpoint file is empty: {checkpoint_file}")
        return []
    except KeyError as e:
        logger.error(f"Checkpoint file missing required column: {e}")
        return []
    except Exception as e:
        logger.error(f"Failed to load checkpoint from {checkpoint_file}: {e}")
        return []


def run_grid_search_parallel(combinations: List[ParameterSet], opt_config: OptimizationConfig, base_env: Dict[str, str], fixed_params: Dict[str, Any] = None, resume: bool = True) -> List[BacktestResult]:
    """Orchestrate parallel backtest execution with progress tracking."""
    if resume:
        # Load checkpoint if exists
        completed = load_checkpoint(opt_config.checkpoint_file)
        completed_ids = {result.run_id for result in completed}
        pending = [c for c in combinations if c.run_id not in completed_ids]
        
        if completed:
            logger.info(f"Resuming from checkpoint: {len(completed)} completed, {len(pending)} remaining")
        else:
            logger.info(f"Starting fresh: {len(combinations)} combinations")
            pending = combinations
    else:
        # Start fresh, ignore checkpoint
        completed = []
        pending = combinations
        logger.info(f"Starting fresh (ignoring checkpoint): {len(combinations)} combinations")
    
    # Initialize progress tracking
    total = len(combinations)
    completed_count = len(completed)
    start_time = time.time()
    results = list(completed)
    
    if not pending:
        logger.info("All combinations already completed")
        return results
    
    # Create multiprocessing pool
    try:
        with multiprocessing.Pool(processes=opt_config.workers, maxtasksperchild=50) as pool:
            # Prepare task arguments
            task_args = [(params, base_env, opt_config.timeout_seconds, fixed_params) for params in pending]
            
            # Submit tasks and process results
            for result in pool.imap_unordered(_worker_run_backtest, task_args):
                results.append(result)
                completed_count += 1
                
                # Calculate progress
                elapsed = time.time() - start_time
                avg_time = elapsed / (completed_count - len(completed)) if completed_count > len(completed) else 0
                remaining = total - completed_count
                eta_seconds = remaining * avg_time if avg_time > 0 else 0
                
                # Log progress
                logger.info(
                    f"Progress: {completed_count}/{total} ({completed_count/total*100:.1f}%) - "
                    f"Avg: {avg_time:.1f}s/backtest - ETA: {eta_seconds/3600:.1f}h"
                )
                
                # Checkpoint every N backtests
                if completed_count % opt_config.checkpoint_interval == 0:
                    save_checkpoint(results, opt_config.checkpoint_file)
                    logger.info(f"Checkpoint saved: {completed_count} backtests completed")
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user, saving checkpoint...")
        save_checkpoint(results, opt_config.checkpoint_file)
        raise
    
    # Final checkpoint save
    save_checkpoint(results, opt_config.checkpoint_file)
    logger.info(f"Grid search completed: {len(results)} backtests in {elapsed/3600:.1f}h")
    
    return results


def rank_results(results: List[BacktestResult], objective: str) -> List[BacktestResult]:
    """Sort results by objective function, supporting minimization and maximization."""
    completed = [r for r in results if r.status == "completed"]
    if not completed:
        logger.warning("No completed backtests to rank")
        return results
    
    # Determine sort order based on objective direction
    minimize = is_minimization_objective(objective)
    ranked = sorted(completed, key=lambda r: r.get_objective_value(objective), reverse=not minimize)
    
    # Add failed runs at the end
    failed = [r for r in results if r.status != "completed"]
    ranked.extend(failed)
    
    logger.info(f"Ranked {len(completed)} completed results by {objective} ({'minimizing' if minimize else 'maximizing'})")
    return ranked


def generate_summary_statistics(results: List[BacktestResult], objective: str) -> Dict[str, Any]:
    """Calculate aggregate statistics across all runs."""
    completed = [r for r in results if r.status == "completed"]
    failed = [r for r in results if r.status == "failed"]
    timeout = [r for r in results if r.status == "timeout"]
    
    summary = {
        "overall": {
            "total_runs": len(results),
            "completed": len(completed),
            "failed": len(failed),
            "timeout": len(timeout),
            "success_rate": len(completed) / len(results) if results else 0.0
        }
    }
    
    if completed:
        # Best/worst depend on objective direction
        minimize = is_minimization_objective(objective)
        best = (min if minimize else max)(completed, key=lambda r: r.get_objective_value(objective))
        summary["best"] = {
            "run_id": best.run_id,
            "objective_value": best.get_objective_value(objective),
            "parameters": asdict(best.parameters),
            "metrics": {
                "total_pnl": best.total_pnl,
                "sharpe_ratio": best.sharpe_ratio,
                "win_rate": best.win_rate,
                "max_drawdown": best.max_drawdown,
                "trade_count": best.trade_count
            }
        }
        
        # Worst result
        worst = (max if minimize else min)(completed, key=lambda r: r.get_objective_value(objective))
        summary["worst"] = {
            "run_id": worst.run_id,
            "objective_value": worst.get_objective_value(objective),
            "parameters": asdict(worst.parameters),
            "metrics": {
                "total_pnl": worst.total_pnl,
                "sharpe_ratio": worst.sharpe_ratio,
                "win_rate": worst.win_rate,
                "max_drawdown": worst.max_drawdown,
                "trade_count": worst.trade_count
            }
        }
        
        # Average metrics
        df = pd.DataFrame([r.to_dict() for r in completed])
        summary["averages"] = {
            "total_pnl": df["total_pnl"].mean(),
            "sharpe_ratio": df["sharpe_ratio"].mean(),
            "win_rate": df["win_rate"].mean(),
            "max_drawdown": df["max_drawdown"].mean(),
            "trade_count": df["trade_count"].mean(),
            "profit_factor": df["profit_factor"].mean(),
            "expectancy": df["expectancy"].mean()
        }
        
        # Parameter sensitivity (correlation with objective)
        objective_values = [r.get_objective_value(objective) for r in completed]
        param_columns = ["fast_period", "slow_period", "crossover_threshold_pips", 
                        "stop_loss_pips", "take_profit_pips"]
        
        sensitivity = {}
        for col in param_columns:
            if col in df.columns:
                correlation = df[col].corr(pd.Series(objective_values))
                if minimize and not pd.isna(correlation):
                    correlation = abs(correlation)
                sensitivity[col] = correlation if not pd.isna(correlation) else 0.0
        
        summary["sensitivity"] = sensitivity
    
    return summary


def _dominates(a: BacktestResult, b: BacktestResult, objectives: List[str]) -> bool:
    """Return True if a dominates b under the given objectives and their directions."""
    all_better_or_equal = True
    strictly_better = False
    for obj in objectives:
        a_val = a.get_objective_value(obj)
        b_val = b.get_objective_value(obj)
        if is_minimization_objective(obj):
            if a_val > b_val:
                all_better_or_equal = False
                break
            if a_val < b_val:
                strictly_better = True
        else:
            if a_val < b_val:
                all_better_or_equal = False
                break
            if a_val > b_val:
                strictly_better = True
    return all_better_or_equal and strictly_better


def calculate_pareto_frontier(results: List[BacktestResult], objectives: List[str]) -> List[BacktestResult]:
    """Compute non-dominated set (Pareto frontier) across objectives."""
    completed = [r for r in results if r.status == "completed"]
    frontier: List[BacktestResult] = []
    for r in completed:
        dominated = False
        for q in completed:
            if q is r:
                continue
            if _dominates(q, r, objectives):
                dominated = True
                break
        if not dominated:
            frontier.append(r)
    logger.info(f"Pareto frontier size: {len(frontier)} across objectives {objectives}")
    return frontier


def export_results(results: List[BacktestResult], output_file: str, summary: Dict[str, Any], objective: str, pareto_objectives: Optional[List[str]] = None) -> None:
    """Export results to CSV with summary header."""
    if not results:
        logger.warning("No results to export")
        return
    
    # Convert results to DataFrame respecting the existing order (already ranked)
    results_dicts = [result.to_dict() for result in results]
    df = pd.DataFrame(results_dicts)

    # Add objective value column; set to NaN for non-completed to ensure they sort last if re-sorted externally
    objective_values = []
    for r in results:
        if r.status == "completed":
            objective_values.append(r.get_objective_value(objective))
        else:
            objective_values.append(pd.NA)
    df["objective_value"] = objective_values

    # Derive rank only for completed runs, preserving their current order; non-completed have rank as NaN
    completed_mask = df["status"] == "completed"
    ranks = pd.Series(pd.NA, index=df.index, dtype="Int64")
    ranks.loc[completed_mask] = range(1, completed_mask.sum() + 1)
    df["rank"] = ranks
    
    # Ensure parent directory exists before writing CSV
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    
    # Write to CSV
    df.to_csv(output_file, index=False)
    
    # Export top 10 parameters as JSON (trusting pre-ranked order among completed)
    output_path = Path(output_file)
    top_10_file = output_path.parent / f"{output_path.stem}_top_10.json"
    top_10_params = []
    
    completed_results = [r for r in results if r.status == "completed"]
    for i, result in enumerate(completed_results[:10]):
        top_10_params.append({
            "rank": i + 1,
            "run_id": result.run_id,
            "sharpe_ratio": result.sharpe_ratio,
            "total_pnl": result.total_pnl,
            "win_rate": result.win_rate,
            "max_drawdown": result.max_drawdown,
            "trade_count": result.trade_count,
            "avg_winner": result.avg_winner,
            "avg_loser": result.avg_loser,
            "profit_factor": result.profit_factor,
            "expectancy": result.expectancy,
            "rejected_signals_count": result.rejected_signals_count,
            "consecutive_losses": result.consecutive_losses,
            "parameters": asdict(result.parameters)
        })
    
    with open(top_10_file, 'w') as f:
        json.dump(top_10_params, f, indent=2)
    
    # Add objective to summary
    summary["objective"] = objective
    
    # Export summary as JSON
    summary_file = output_path.parent / f"{output_path.stem}_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    # Consolidated export logging - all artifact paths in one block
    logger.info("Export completed - Artifact paths:")
    logger.info(f"  CSV results: {output_file}")
    logger.info(f"  Top 10 JSON: {top_10_file}")
    logger.info(f"  Summary JSON: {summary_file}")

    # Optional: export Pareto frontier
    if pareto_objectives:
        # Validate objectives
        invalid = [o for o in pareto_objectives if o not in OBJECTIVE_DIRECTIONS]
        if invalid:
            logger.warning(f"Skipping Pareto export due to invalid objectives: {invalid}")
            return
        frontier_results = calculate_pareto_frontier(results, pareto_objectives)
        pf = []
        for r in frontier_results:
            pf.append({
                "run_id": r.run_id,
                "parameters": asdict(r.parameters),
                "metrics": {
                    "total_pnl": r.total_pnl,
                    "sharpe_ratio": r.sharpe_ratio,
                    "win_rate": r.win_rate,
                    "max_drawdown": r.max_drawdown,
                    "trade_count": r.trade_count,
                    "avg_winner": r.avg_winner,
                    "avg_loser": r.avg_loser,
                    "profit_factor": r.profit_factor,
                    "expectancy": r.expectancy,
                    "rejected_signals_count": r.rejected_signals_count,
                    "consecutive_losses": r.consecutive_losses,
                },
                "objective_values": {obj: r.get_objective_value(obj) for obj in pareto_objectives},
            })
        pareto_file = output_path.parent / f"{output_path.stem}_pareto_frontier.json"
        with open(pareto_file, "w") as f:
            json.dump({"objectives": pareto_objectives, "frontier": pf}, f, indent=2)
        logger.info(f"Pareto frontier exported to {pareto_file}")


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Grid Search Optimizer for NautilusTrader Backtest Parameter Tuning",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--config", required=True,
        help="Path to YAML configuration file"
    )
    
    parser.add_argument(
        "--workers", type=int,
        help="Number of parallel workers (overrides config)"
    )
    
    parser.add_argument(
        "--objective",
        help="Objective function to optimize (overrides config)"
    )
    
    parser.add_argument(
        "--output",
        help="Output CSV file path (overrides config)"
    )
    
    mx = parser.add_mutually_exclusive_group()
    mx.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    mx.add_argument("--no-resume", action="store_true", help="Start fresh (ignore checkpoint)")
    
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug logging"
    )

    parser.add_argument(
        "--pareto", nargs='+',
        help="Calculate Pareto frontier across multiple objectives (specify 2+ objectives)"
    )
    
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    try:
        # Parse arguments
        args = parse_arguments()
        
        # Setup logging
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        logger.info("Starting grid search optimization")
        
        # Load configuration
        config_path = Path(args.config)
        if not config_path.exists():
            logger.error(f"Configuration file not found: {config_path}")
            return 2
        
        opt_config, param_ranges, fixed_params = load_grid_config(config_path)
        
        # Override with CLI arguments
        if args.workers:
            opt_config.workers = args.workers
        if args.objective:
            opt_config.objective = args.objective
            # Validate CLI objective override
            if opt_config.objective not in OBJECTIVE_DIRECTIONS:
                logger.error(f"Invalid objective override: {opt_config.objective}. Allowed: {list(OBJECTIVE_DIRECTIONS.keys())}")
                return 2
        if args.output:
            opt_config.output_file = args.output
        
        logger.info(f"Loaded configuration: {len(param_ranges)} parameters, objective={opt_config.objective}")
        
        # Generate combinations
        combinations = generate_parameter_combinations(param_ranges, fixed_params)
        if not combinations:
            logger.error("No valid parameter combinations generated")
            return 2
        
        logger.info(f"Generated {len(combinations)} parameter combinations")
        if len(combinations) > 10000:
            logger.warning(f"Large grid detected: {len(combinations)} combinations. This may take several hours.")
        
        # Prepare base environment
        base_env = os.environ.copy()
        required_vars = [
            "BACKTEST_SYMBOL", "BACKTEST_START_DATE", "BACKTEST_END_DATE",
            "BACKTEST_VENUE", "BACKTEST_BAR_SPEC", "CATALOG_PATH", "OUTPUT_DIR"
        ]
        missing_vars = [var for var in required_vars if var not in base_env]
        if missing_vars:
            logger.error(f"Missing required environment variables: {missing_vars}")
            return 2
        
        logger.info("Base environment prepared")
        logger.info(f"Resolved environment values: VENUE={base_env.get('BACKTEST_VENUE')}, BAR_SPEC={base_env.get('BACKTEST_BAR_SPEC')}, CATALOG_PATH={base_env.get('CATALOG_PATH')}, OUTPUT_DIR={base_env.get('OUTPUT_DIR')}")
        
        # Compute resume behavior
        resume = args.resume or not args.no_resume
        
        # Run optimization
        results = run_grid_search_parallel(combinations, opt_config, base_env, fixed_params, resume)
        if not results:
            logger.error("No results generated")
            return 1
        
        logger.info(f"Grid search completed: {len(results)} backtests")
        
        # Analyze results
        ranked_results = rank_results(results, opt_config.objective)
        summary = generate_summary_statistics(ranked_results, opt_config.objective)
        
        # Print best result
        if "best" in summary:
            best = summary["best"]
            logger.info(f"Best parameters: fast={best['parameters']['fast_period']}, "
                       f"slow={best['parameters']['slow_period']}, "
                       f"{opt_config.objective}={best['objective_value']:.2f}")
        
        # Optional Pareto frontier objectives from CLI
        pareto_objectives: Optional[List[str]] = None
        if getattr(args, "pareto", None):
            if len(args.pareto) < 2:
                logger.warning("--pareto requires at least 2 objectives; skipping Pareto analysis")
            else:
                invalid = [o for o in args.pareto if o not in OBJECTIVE_DIRECTIONS]
                if invalid:
                    logger.error(f"Invalid Pareto objectives: {invalid}")
                else:
                    pareto_objectives = args.pareto

        # Export results (and Pareto frontier if requested)
        export_results(ranked_results, opt_config.output_file, summary, opt_config.objective, pareto_objectives)
        
        # Print summary
        if "overall" in summary:
            overall = summary["overall"]
            logger.info(f"Summary: {overall['completed']}/{overall['total_runs']} completed "
                       f"({overall['success_rate']*100:.1f}% success rate)")
        
        logger.info("Optimization completed successfully")
        return 0
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Critical error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
