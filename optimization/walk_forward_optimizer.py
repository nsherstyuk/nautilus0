"""
Walk-Forward Optimization Tool

This module provides comprehensive walk-forward optimization functionality for trading strategies.
It implements rolling window optimization to prevent overfitting by training on historical data
and testing on subsequent out-of-sample periods.

Usage Examples:
    Basic walk-forward optimization:
        python optimization/walk_forward_optimizer.py --config grid_config.yaml --train-months 2 --test-months 1 --step-months 1
    
    Custom objective function:
        python optimization/walk_forward_optimizer.py --config grid_config.yaml --train-months 3 --test-months 1 --step-months 1 --objective sharpe_ratio
    
    With custom output path:
        python optimization/walk_forward_optimizer.py --config grid_config.yaml --train-months 2 --test-months 1 --output optimization/results/walk_forward.html

Output Formats:
    - Console report (always generated)
    - HTML report with embedded charts (always generated)
    - JSON export (optional with --json flag)

Exit Codes:
    0: Success
    1: Error during execution
    2: Invalid arguments

Metrics Tracked:
    - In-sample vs out-of-sample performance comparison
    - Parameter stability across windows
    - Overfitting indicators and degradation analysis
    - Aggregate performance across all test windows
    - Statistical significance testing between windows
"""

import argparse
import json
import logging
import sys
import os
import subprocess
import time
import datetime
import copy
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import yaml
from io import BytesIO
import base64

# Project imports
from optimization.grid_search import (
    OptimizationConfig, ParameterSet, BacktestResult,
    load_grid_config, generate_parameter_combinations,
    run_single_backtest, rank_results, generate_summary_statistics,
    run_grid_search_parallel
)
from analysis.compare_backtests import (
    BacktestMetrics, extract_metrics, compare_metrics, perform_statistical_test
)
from config.backtest_config import get_backtest_config

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent

@dataclass
class WindowConfig:
    """Configuration for a single train/test window in walk-forward optimization."""
    window_id: int
    train_start: str  # YYYY-MM-DD
    train_end: str    # YYYY-MM-DD
    test_start: str   # YYYY-MM-DD
    test_end: str     # YYYY-MM-DD
    train_months: int
    test_months: int

@dataclass
class WindowResult:
    """Results from a single walk-forward window."""
    window_config: WindowConfig
    train_results: List[BacktestResult]  # All grid search results from training
    best_train_result: BacktestResult    # Top-ranked result from training
    test_result: BacktestResult          # Out-of-sample test result
    best_parameters: ParameterSet        # Parameters used for test
    train_metrics: BacktestMetrics       # In-sample performance metrics
    test_metrics: BacktestMetrics  # Out-of-sample performance metrics
    performance_degradation: float       # Train - test performance ratio
    statistical_test: Optional[Any] = None  # Statistical test vs previous window

@dataclass
class ParameterStability:
    """Statistics on parameter changes across windows."""
    parameter_name: str
    values: List[Any]      # Parameter values across windows
    mean: float            # Mean value (for numeric parameters)
    std: float             # Standard deviation
    min: Any               # Minimum value
    max: Any               # Maximum value
    stability_score: float # 0-1, higher = more stable

@dataclass
class WalkForwardReport:
    """Complete walk-forward optimization report."""
    global_start_date: str
    global_end_date: str
    train_months: int
    test_months: int
    step_months: int
    objective: str
    total_windows: int
    window_results: List[WindowResult]
    parameter_stability: Dict[str, ParameterStability]
    aggregate_metrics: Dict[str, Any]  # Combined test window performance
    overfitting_score: float           # Average performance degradation
    recommendations: List[str]

def generate_walk_forward_windows(
    start_date: str,
    end_date: str,
    train_months: int,
    test_months: int,
    step_months: int
) -> List[WindowConfig]:
    """
    Generate walk-forward windows using pandas date_range with DateOffset.
    
    Args:
        start_date: Global start date (YYYY-MM-DD)
        end_date: Global end date (YYYY-MM-DD)
        train_months: Number of months for training window
        test_months: Number of months for testing window
        step_months: Number of months to step forward between windows
        
    Returns:
        List of WindowConfig objects with sequential window_ids
        
    Raises:
        ValueError: If date range is insufficient for at least one window
    """
    # Parse dates to pandas Timestamps
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    
    # Validate date range is sufficient for at least one window
    min_required_days = (train_months + test_months) * 30  # Approximate
    if (end_ts - start_ts).days < min_required_days:
        raise ValueError(f"Date range insufficient for walk-forward windows. "
                        f"Need at least {min_required_days} days, got {(end_ts - start_ts).days}")
    
    windows = []
    window_id = 1
    current_start = start_ts
    
    while current_start < end_ts:
        # Calculate train window
        train_start = current_start
        train_end = train_start + pd.DateOffset(months=train_months)
        
        # Calculate test window
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=test_months)
        
        # Check if we have enough data for test window (at least 50% of test_months)
        if test_end > end_ts:
            remaining_days = (end_ts - test_start).days
            required_days = test_months * 15  # 50% of test_months in days
            if remaining_days < required_days:
                logger.info(f"Stopping at window {window_id}: insufficient data for test window")
                break
        
        # Create window config
        window_config = WindowConfig(
            window_id=window_id,
            train_start=train_start.strftime('%Y-%m-%d'),
            train_end=train_end.strftime('%Y-%m-%d'),
            test_start=test_start.strftime('%Y-%m-%d'),
            test_end=min(test_end, end_ts).strftime('%Y-%m-%d'),
            train_months=train_months,
            test_months=test_months
        )
        
        windows.append(window_config)
        
        # Step forward for next window
        current_start = current_start + pd.DateOffset(months=step_months)
        window_id += 1
        
        # Prevent infinite loop
        if window_id > 1000:
            logger.warning("Stopping window generation: too many windows (limit: 1000)")
            break
    
    logger.info(f"Generated {len(windows)} walk-forward windows")
    for i, window in enumerate(windows[:3]):  # Log first 3 windows
        logger.info(f"Window {window.window_id}: Train {window.train_start} to {window.train_end}, "
                   f"Test {window.test_start} to {window.test_end}")
    if len(windows) > 3:
        logger.info(f"... and {len(windows) - 3} more windows")
    
    return windows

def run_window_grid_search(
    window_config: WindowConfig,
    opt_config: OptimizationConfig,
    param_ranges: Dict[str, List[Any]],
    fixed_params: Dict[str, Any],
    base_env: Dict[str, str],
    symbol: str,
    catalog_path: str,
    resume: bool = True
) -> List[BacktestResult]:
    """
    Run grid search for a single window's training period.
    
    Args:
        window_config: Window configuration
        opt_config: Optimization configuration
        param_ranges: Parameter ranges for grid search
        fixed_params: Fixed parameters
        base_env: Base environment variables
        symbol: Trading symbol
        catalog_path: Path to data catalog
        resume: Whether to resume from checkpoint
        
    Returns:
        List of BacktestResult objects from grid search
    """
    logger.info(f"Starting grid search for window {window_config.window_id}")
    
    # Create window-specific environment variables
    window_env = base_env.copy()
    window_env.update({
        'BACKTEST_START_DATE': window_config.train_start,
        'BACKTEST_END_DATE': window_config.train_end,
        'BACKTEST_SYMBOL': symbol,
        'CATALOG_PATH': catalog_path
    })
    
    # Set window-specific checkpoint file
    opt_config.checkpoint_file = f"walk_forward_window_{window_config.window_id}_checkpoint.csv"
    
    # Generate parameter combinations
    param_combinations = generate_parameter_combinations(param_ranges, fixed_params)
    logger.info(f"Generated {len(param_combinations)} parameter combinations for window {window_config.window_id}")
    
    # Use run_grid_search_parallel for proper checkpoint/resume and progress tracking
    results = run_grid_search_parallel(param_combinations, opt_config, window_env, fixed_params, resume=resume)
    
    logger.info(f"Grid search completed for window {window_config.window_id}: {len(results)} results")
    
    return results

def run_out_of_sample_test(
    window_config: WindowConfig,
    best_params: ParameterSet,
    base_env: Dict[str, str],
    fixed_params: Dict[str, Any],
    timeout: int,
    symbol: str,
    catalog_path: str
) -> BacktestResult:
    """
    Run out-of-sample test with best parameters from training.
    
    Args:
        window_config: Window configuration
        best_params: Best parameters from training
        base_env: Base environment variables
        fixed_params: Fixed parameters
        timeout: Backtest timeout in seconds
        symbol: Trading symbol
        catalog_path: Path to data catalog
        
    Returns:
        BacktestResult from out-of-sample test
    """
    logger.info(f"Running out-of-sample test for window {window_config.window_id}")
    
    # Create test window environment variables
    test_env = base_env.copy()
    test_env.update({
        'BACKTEST_START_DATE': window_config.test_start,
        'BACKTEST_END_DATE': window_config.test_end,
        'BACKTEST_SYMBOL': symbol,
        'CATALOG_PATH': catalog_path,
        **best_params.to_env_dict()
    })
    
    start_time = time.time()
    
    try:
        # Execute single backtest
        result = run_single_backtest(best_params, test_env, timeout, fixed_params)
        
        duration = time.time() - start_time
        
        if result is not None:
            logger.info(f"Out-of-sample test completed for window {window_config.window_id} "
                       f"in {duration:.1f}s")
        else:
            logger.error(f"Out-of-sample test failed for window {window_config.window_id}")
            
        return result
        
    except Exception as e:
        logger.error(f"Error in out-of-sample test for window {window_config.window_id}: {e}")
        return None

def process_window(
    window_config: WindowConfig,
    opt_config: OptimizationConfig,
    param_ranges: Dict[str, List[Any]],
    fixed_params: Dict[str, Any],
    base_env: Dict[str, str],
    symbol: str,
    catalog_path: str,
    resume: bool = True
) -> WindowResult:
    """
    Process a single walk-forward window: train, optimize, and test.
    
    Args:
        window_config: Window configuration
        opt_config: Optimization configuration
        param_ranges: Parameter ranges for grid search
        fixed_params: Fixed parameters
        base_env: Base environment variables
        symbol: Trading symbol
        catalog_path: Path to data catalog
        resume: Whether to resume from checkpoint
        
    Returns:
        WindowResult with train/test results and metrics
    """
    logger.info(f"Processing window {window_config.window_id}: "
               f"Train {window_config.train_start} to {window_config.train_end}, "
               f"Test {window_config.test_start} to {window_config.test_end}")
    
    # Run grid search on train window
    train_results = run_window_grid_search(
        window_config, opt_config, param_ranges, fixed_params,
        base_env, symbol, catalog_path, resume
    )
    
    if not train_results:
        logger.error(f"No successful backtests for window {window_config.window_id}")
        return None
    
    # Rank train results by objective
    ranked_train = rank_results(train_results, opt_config.objective)
    best_train_result = ranked_train[0]
    best_parameters = best_train_result.parameters
    
    logger.info(f"Best parameters for window {window_config.window_id}: {best_parameters}")
    
    # Run out-of-sample test
    test_result = run_out_of_sample_test(
        window_config, best_parameters, base_env, fixed_params, opt_config.timeout_seconds, symbol, catalog_path
    )
    
    if test_result is None:
        logger.error(f"Out-of-sample test failed for window {window_config.window_id}")
        return None
    
    # Check test result status before extracting metrics
    if test_result.status != 'completed':
        logger.error(f"Out-of-sample test not completed for window {window_config.window_id}: status={test_result.status}")
        return None
    
    if not test_result.output_directory or not Path(test_result.output_directory).exists():
        logger.error(f"Out-of-sample test output directory missing for window {window_config.window_id}")
        return None
    
    # Extract metrics
    try:
        train_metrics = extract_metrics(Path(best_train_result.output_directory))
        test_metrics = extract_metrics(Path(test_result.output_directory))
    except Exception as e:
        logger.error(f"Error extracting metrics for window {window_config.window_id}: {e}")
        return None
    
    # Calculate performance degradation
    train_pnl = train_metrics.total_pnl
    test_pnl = test_metrics.total_pnl
    
    if train_pnl != 0:
        degradation = (train_pnl - test_pnl) / abs(train_pnl)
    else:
        degradation = 0.0 if test_pnl == 0 else float('inf')
    
    # Create window result
    window_result = WindowResult(
        window_config=window_config,
        train_results=train_results,
        best_train_result=best_train_result,
        test_result=test_result,
        best_parameters=best_parameters,
        train_metrics=train_metrics,
        test_metrics=test_metrics,
        performance_degradation=degradation
    )
    
    logger.info(f"Window {window_config.window_id} completed: "
               f"Train PnL: {train_pnl:.2f}, Test PnL: {test_pnl:.2f}, "
               f"Degradation: {degradation:.1%}")
    
    return window_result

def calculate_parameter_stability(window_results: List[WindowResult]) -> Dict[str, ParameterStability]:
    """
    Calculate parameter stability across all windows.
    
    Args:
        window_results: List of window results
        
    Returns:
        Dict mapping parameter names to ParameterStability objects
    """
    if not window_results:
        return {}
    
    # Extract parameter values across windows
    param_values = {}
    # Define non-parameter fields to exclude
    non_parameter_fields = {'run_id'}
    
    for result in window_results:
        if result.best_parameters:
            for param_name, param_value in result.best_parameters.__dict__.items():
                if not param_name.startswith('_') and param_name not in non_parameter_fields:  # Skip private attributes and non-parameter fields
                    if param_name not in param_values:
                        param_values[param_name] = []
                    param_values[param_name].append(param_value)
    
    # Calculate stability for each parameter
    stability = {}
    for param_name, values in param_values.items():
        if not values:
            continue
            
        # Calculate statistics
        if all(isinstance(v, (int, float)) for v in values):
            # Numeric parameter
            mean_val = np.mean(values)
            std_val = np.std(values)
            min_val = min(values)
            max_val = max(values)
            
            # Calculate stability score (0-1, higher = more stable)
            if mean_val != 0:
                stability_score = max(0, 1.0 - (std_val / abs(mean_val)))
            else:
                stability_score = 1.0 if std_val == 0 else 0.0
        else:
            # Non-numeric parameter (e.g., boolean, string)
            mean_val = 0.0
            std_val = 0.0
            min_val = min(values)
            max_val = max(values)
            
            # For non-numeric, stability is 1.0 if all same, 0.0 otherwise
            stability_score = 1.0 if len(set(values)) == 1 else 0.0
        
        stability[param_name] = ParameterStability(
            parameter_name=param_name,
            values=values,
            mean=mean_val,
            std=std_val,
            min=min_val,
            max=max_val,
            stability_score=stability_score
        )
    
    # Log stability summary
    if stability:
        most_stable = max(stability.items(), key=lambda x: x[1].stability_score)
        least_stable = min(stability.items(), key=lambda x: x[1].stability_score)
        logger.info(f"Parameter stability: Most stable: {most_stable[0]} ({most_stable[1].stability_score:.3f}), "
                   f"Least stable: {least_stable[0]} ({least_stable[1].stability_score:.3f})")
    
    return stability

def calculate_overfitting_metrics(window_results: List[WindowResult]) -> Dict[str, Any]:
    """
    Calculate overfitting metrics from window results.
    
    Args:
        window_results: List of window results
        
    Returns:
        Dict with overfitting metrics
    """
    if not window_results:
        return {}
    
    # Calculate per-window degradation
    degradations = [wr.performance_degradation for wr in window_results if not np.isinf(wr.performance_degradation)]
    
    if not degradations:
        return {"overfitting_score": 0.0, "avg_degradation": 0.0}
    
    # Calculate aggregate metrics
    avg_degradation = np.mean(degradations)
    max_degradation = np.max(degradations)
    degradation_std = np.std(degradations)
    
    # Calculate overfitting score (0-1, higher = more overfitting)
    overfitting_score = min(1.0, avg_degradation)
    
    # Identify problematic windows
    problematic_threshold = 0.3
    problematic_windows = [i for i, d in enumerate(degradations) if d > problematic_threshold]
    
    # Calculate train vs test correlation
    train_values = [wr.train_metrics.total_pnl for wr in window_results]
    test_values = [wr.test_metrics.total_pnl for wr in window_results]
    
    if len(train_values) > 1 and len(test_values) > 1:
        correlation = np.corrcoef(train_values, test_values)[0, 1]
        if np.isnan(correlation):
            correlation = 0.0
    else:
        correlation = 0.0
    
    metrics = {
        "avg_degradation": avg_degradation,
        "max_degradation": max_degradation,
        "degradation_std": degradation_std,
        "overfitting_score": overfitting_score,
        "problematic_windows": problematic_windows,
        "train_test_correlation": correlation
    }
    
    # Log overfitting assessment
    if overfitting_score > 0.3:
        logger.warning(f"High overfitting detected: score {overfitting_score:.3f}")
    elif overfitting_score > 0.1:
        logger.info(f"Moderate overfitting detected: score {overfitting_score:.3f}")
    else:
        logger.info(f"Low overfitting detected: score {overfitting_score:.3f}")
    
    return metrics

def calculate_aggregate_performance(window_results: List[WindowResult]) -> Dict[str, Any]:
    """
    Calculate aggregate performance across all test windows.
    
    Args:
        window_results: List of window results
        
    Returns:
        Dict with aggregate performance metrics
    """
    if not window_results:
        return {}
    
    # Aggregate test window performance (out-of-sample only)
    test_pnls = [wr.test_metrics.total_pnl for wr in window_results]
    test_sharpes = [wr.test_metrics.sharpe_ratio for wr in window_results]
    test_win_rates = [wr.test_metrics.win_rate for wr in window_results]
    test_drawdowns = [wr.test_metrics.max_drawdown for wr in window_results]
    test_trades = [wr.test_metrics.total_trades for wr in window_results]
    
    # Calculate aggregate metrics
    total_pnl = sum(test_pnls)
    avg_sharpe = np.mean(test_sharpes) if test_sharpes else 0.0
    avg_win_rate = np.mean(test_win_rates) if test_win_rates else 0.0
    max_drawdown = max(test_drawdowns) if test_drawdowns else 0.0
    total_trades = sum(test_trades)
    
    # Calculate consistency metrics
    winning_windows = sum(1 for pnl in test_pnls if pnl > 0)
    losing_windows = sum(1 for pnl in test_pnls if pnl < 0)
    total_windows = len(test_pnls)
    consistency_score = winning_windows / total_windows if total_windows > 0 else 0.0
    
    metrics = {
        "total_pnl": total_pnl,
        "avg_sharpe": avg_sharpe,
        "avg_win_rate": avg_win_rate,
        "max_drawdown": max_drawdown,
        "total_trades": total_trades,
        "winning_windows": winning_windows,
        "losing_windows": losing_windows,
        "consistency_score": consistency_score
    }
    
    logger.info(f"Aggregate performance: Total PnL: {total_pnl:.2f}, "
               f"Avg Sharpe: {avg_sharpe:.3f}, Consistency: {consistency_score:.1%}")
    
    return metrics

def generate_recommendations(report: WalkForwardReport) -> List[str]:
    """
    Generate actionable recommendations based on walk-forward results.
    
    Args:
        report: WalkForwardReport object
        
    Returns:
        List of recommendation strings
    """
    recommendations = []
    
    # Check for high overfitting
    if report.overfitting_score > 0.3:
        recommendations.append("High overfitting detected. Consider simplifying strategy or using more robust parameters.")
    
    # Check parameter stability
    for param_name, stability in report.parameter_stability.items():
        if stability.stability_score < 0.5 and stability.std > 0.5 * abs(stability.mean):
            recommendations.append(f"Parameter instability detected for {param_name}. "
                                 f"Consider fixing this parameter or using wider ranges.")
    
    # Check consistency
    if report.aggregate_metrics.get("consistency_score", 0) < 0.5:
        recommendations.append("Low consistency across windows. "
                           "Strategy may not be robust to changing market conditions.")
    
    # Check profitability
    if report.aggregate_metrics.get("total_pnl", 0) < 0:
        recommendations.append("Negative out-of-sample performance. "
                             "Strategy is not profitable in walk-forward testing.")
    
    # Check train/test correlation
    overfitting_metrics = calculate_overfitting_metrics(report.window_results)
    if overfitting_metrics.get("train_test_correlation", 1.0) < 0.5:
        recommendations.append("Low correlation between in-sample and out-of-sample performance. "
                             "Overfitting likely.")
    
    # Positive recommendations
    if (report.overfitting_score < 0.1 and 
        report.aggregate_metrics.get("consistency_score", 0) > 0.6 and
        report.aggregate_metrics.get("total_pnl", 0) > 0):
        recommendations.append("Strong walk-forward performance. "
                             "Parameters show stability and consistent out-of-sample profitability.")
    
    return recommendations

def create_parameter_evolution_chart(window_results: List[WindowResult], param_name: str) -> str:
    """Create line chart showing parameter value over windows."""
    if not window_results:
        return ""
    
    # Extract parameter values
    window_ids = [wr.window_config.window_id for wr in window_results]
    param_values = []
    
    for wr in window_results:
        if wr.best_parameters and hasattr(wr.best_parameters, param_name):
            param_values.append(getattr(wr.best_parameters, param_name))
        else:
            param_values.append(None)
    
    # Filter out None values
    valid_data = [(wid, val) for wid, val in zip(window_ids, param_values) if val is not None]
    if not valid_data:
        return ""
    
    window_ids, param_values = zip(*valid_data)
    
    # Create chart
    plt.figure(figsize=(10, 6))
    plt.plot(window_ids, param_values, marker='o', linewidth=2, markersize=6)
    plt.title(f'Parameter Evolution: {param_name}', fontsize=14, fontweight='bold')
    plt.xlabel('Window ID', fontsize=12)
    plt.ylabel(f'{param_name}', fontsize=12)
    plt.grid(True, alpha=0.3)
    
    # Convert to base64
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64

def create_performance_comparison_chart(window_results: List[WindowResult]) -> str:
    """Create grouped bar chart comparing train vs test performance."""
    if not window_results:
        return ""
    
    window_ids = [wr.window_config.window_id for wr in window_results]
    train_pnls = [wr.train_metrics.total_pnl for wr in window_results]
    test_pnls = [wr.test_metrics.total_pnl for wr in window_results]
    
    # Create chart
    fig, ax = plt.subplots(figsize=(12, 6))
    
    x = np.arange(len(window_ids))
    width = 0.35
    
    bars1 = ax.bar(x - width/2, train_pnls, width, label='Train (In-Sample)', alpha=0.8)
    bars2 = ax.bar(x + width/2, test_pnls, width, label='Test (Out-of-Sample)', alpha=0.8)
    
    # Color bars based on performance
    for i, (train_pnl, test_pnl) in enumerate(zip(train_pnls, test_pnls)):
        if test_pnl > train_pnl:
            bars2[i].set_color('green')
        else:
            bars2[i].set_color('red')
    
    ax.set_xlabel('Window ID', fontsize=12)
    ax.set_ylabel('Total PnL', fontsize=12)
    ax.set_title('Train vs Test Performance Comparison', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(window_ids)
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Convert to base64
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64

def create_overfitting_heatmap(window_results: List[WindowResult]) -> str:
    """Create heatmap showing performance degradation per window."""
    if not window_results:
        return ""
    
    window_ids = [wr.window_config.window_id for wr in window_results]
    degradations = [wr.performance_degradation for wr in window_results]
    
    # Create heatmap data
    data = np.array(degradations).reshape(1, -1)
    
    fig, ax = plt.subplots(figsize=(12, 4))
    im = ax.imshow(data, cmap='RdYlGn_r', aspect='auto', vmin=0, vmax=1)
    
    # Set ticks and labels
    ax.set_xticks(range(len(window_ids)))
    ax.set_xticklabels(window_ids)
    ax.set_yticks([0])
    ax.set_yticklabels(['Degradation'])
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Performance Degradation', rotation=270, labelpad=20)
    
    ax.set_title('Overfitting Heatmap: Performance Degradation by Window', 
                fontsize=14, fontweight='bold')
    ax.set_xlabel('Window ID', fontsize=12)
    
    # Convert to base64
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64

def create_aggregate_equity_curve(window_results: List[WindowResult]) -> str:
    """Create line chart showing cumulative PnL across test windows."""
    if not window_results:
        return ""
    
    # Calculate cumulative PnL
    cumulative_pnl = 0
    cumulative_pnls = [cumulative_pnl]
    
    for wr in window_results:
        cumulative_pnl += wr.test_metrics.total_pnl
        cumulative_pnls.append(cumulative_pnl)
    
    # Create chart
    plt.figure(figsize=(12, 6))
    plt.plot(range(len(cumulative_pnls)), cumulative_pnls, linewidth=2, marker='o', markersize=4)
    plt.title('Aggregate Equity Curve (Out-of-Sample)', fontsize=14, fontweight='bold')
    plt.xlabel('Window', fontsize=12)
    plt.ylabel('Cumulative PnL', fontsize=12)
    plt.grid(True, alpha=0.3)
    
    # Add horizontal line at zero
    plt.axhline(y=0, color='black', linestyle='--', alpha=0.5)
    
    # Convert to base64
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64

def create_parameter_stability_chart(parameter_stability: Dict[str, ParameterStability]) -> str:
    """Create bar chart showing stability score for each parameter."""
    if not parameter_stability:
        return ""
    
    param_names = list(parameter_stability.keys())
    stability_scores = [ps.stability_score for ps in parameter_stability.values()]
    
    # Create chart
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(param_names, stability_scores, alpha=0.8)
    
    # Color bars based on stability
    for i, score in enumerate(stability_scores):
        if score > 0.7:
            bars[i].set_color('green')
        elif score > 0.4:
            bars[i].set_color('orange')
        else:
            bars[i].set_color('red')
    
    ax.set_xlabel('Parameter', fontsize=12)
    ax.set_ylabel('Stability Score', fontsize=12)
    ax.set_title('Parameter Stability Analysis', fontsize=14, fontweight='bold')
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    
    # Rotate x-axis labels if needed
    plt.xticks(rotation=45, ha='right')
    
    # Convert to base64
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64

def generate_console_report(report: WalkForwardReport) -> None:
    """Generate formatted console report."""
    print("=" * 80)
    print("WALK-FORWARD OPTIMIZATION REPORT")
    print("=" * 80)
    
    # Configuration
    print(f"\nConfiguration:")
    print(f"  Train Months: {report.train_months}")
    print(f"  Test Months: {report.test_months}")
    print(f"  Step Months: {report.step_months}")
    print(f"  Objective: {report.objective}")
    print(f"  Total Windows: {report.total_windows}")
    print(f"  Date Range: {report.global_start_date} to {report.global_end_date}")
    
    # Window Results Table
    print(f"\nWindow Results:")
    print("-" * 80)
    print(f"{'Window':<6} {'Train Dates':<20} {'Test Dates':<20} {'Train PnL':<10} {'Test PnL':<10} {'Degradation':<12}")
    print("-" * 80)
    
    for wr in report.window_results:
        train_dates = f"{wr.window_config.train_start} to {wr.window_config.train_end}"
        test_dates = f"{wr.window_config.test_start} to {wr.window_config.test_end}"
        degradation_pct = f"{wr.performance_degradation:.1%}"
        
        print(f"{wr.window_config.window_id:<6} {train_dates:<20} {test_dates:<20} "
              f"{wr.train_metrics.total_pnl:<10.2f} {wr.test_metrics.total_pnl:<10.2f} {degradation_pct:<12}")
    
    # Parameter Stability
    if report.parameter_stability:
        print(f"\nParameter Stability:")
        print("-" * 60)
        print(f"{'Parameter':<20} {'Mean':<10} {'Std':<10} {'Stability':<10}")
        print("-" * 60)
        
        for param_name, stability in report.parameter_stability.items():
            print(f"{param_name:<20} {stability.mean:<10.3f} {stability.std:<10.3f} {stability.stability_score:<10.3f}")
    
    # Aggregate Performance
    print(f"\nAggregate Performance:")
    print("-" * 40)
    print(f"Total Test PnL: {report.aggregate_metrics.get('total_pnl', 0):.2f}")
    print(f"Average Sharpe: {report.aggregate_metrics.get('avg_sharpe', 0):.3f}")
    print(f"Consistency Score: {report.aggregate_metrics.get('consistency_score', 0):.1%}")
    print(f"Total Trades: {report.aggregate_metrics.get('total_trades', 0)}")
    
    # Overfitting Metrics
    print(f"\nOverfitting Metrics:")
    print("-" * 40)
    print(f"Overfitting Score: {report.overfitting_score:.3f}")
    
    # Recommendations
    if report.recommendations:
        print(f"\nRecommendations:")
        print("-" * 40)
        for i, rec in enumerate(report.recommendations, 1):
            print(f"{i}. {rec}")
    
    print("\n" + "=" * 80)

def generate_json_report(report: WalkForwardReport, output_path: Path) -> None:
    """Generate JSON report."""
    # Convert report to dict, handling Path objects and special types
    report_dict = asdict(report)
    
    # Convert Path objects to strings
    def convert_paths(obj):
        if isinstance(obj, Path):
            return str(obj)
        elif isinstance(obj, dict):
            return {k: convert_paths(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_paths(item) for item in obj]
        else:
            return obj
    
    report_dict = convert_paths(report_dict)
    
    # Write JSON file
    with open(output_path, 'w') as f:
        json.dump(report_dict, f, indent=2, default=str)
    
    logger.info(f"JSON report written to {output_path}")

def generate_html_report(report: WalkForwardReport, output_path: Path, charts: Dict[str, str]) -> None:
    """Generate comprehensive HTML report with embedded charts."""
    
    # Generate charts
    performance_chart = create_performance_comparison_chart(report.window_results)
    overfitting_chart = create_overfitting_heatmap(report.window_results)
    equity_chart = create_aggregate_equity_curve(report.window_results)
    stability_chart = create_parameter_stability_chart(report.parameter_stability)
    
    # Generate parameter evolution charts for key parameters
    param_evolution_charts = {}
    for param_name in list(report.parameter_stability.keys())[:3]:  # Top 3 parameters
        chart = create_parameter_evolution_chart(report.window_results, param_name)
        if chart:
            param_evolution_charts[param_name] = chart
    
    # Create HTML content
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Walk-Forward Optimization Report</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f5f5f5;
                color: #333;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            .header {{
                text-align: center;
                border-bottom: 3px solid #007bff;
                padding-bottom: 20px;
                margin-bottom: 30px;
            }}
            .header h1 {{
                color: #007bff;
                margin: 0;
                font-size: 2.5em;
            }}
            .header p {{
                color: #666;
                margin: 10px 0 0 0;
                font-size: 1.1em;
            }}
            .section {{
                margin: 30px 0;
                padding: 20px;
                border: 1px solid #ddd;
                border-radius: 8px;
                background: #fafafa;
            }}
            .section h2 {{
                color: #007bff;
                margin-top: 0;
                border-bottom: 2px solid #007bff;
                padding-bottom: 10px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 15px 0;
            }}
            th, td {{
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #ddd;
            }}
            th {{
                background-color: #007bff;
                color: white;
                font-weight: bold;
            }}
            tr:nth-child(even) {{
                background-color: #f2f2f2;
            }}
            .metric-card {{
                display: inline-block;
                background: #007bff;
                color: white;
                padding: 15px;
                margin: 10px;
                border-radius: 8px;
                text-align: center;
                min-width: 150px;
            }}
            .metric-card h3 {{
                margin: 0 0 10px 0;
                font-size: 1.2em;
            }}
            .metric-card .value {{
                font-size: 1.5em;
                font-weight: bold;
            }}
            .chart {{
                text-align: center;
                margin: 20px 0;
            }}
            .chart img {{
                max-width: 100%;
                height: auto;
                border: 1px solid #ddd;
                border-radius: 8px;
            }}
            .recommendations {{
                background: #fff3cd;
                border: 1px solid #ffeaa7;
                border-radius: 8px;
                padding: 20px;
            }}
            .recommendations ul {{
                margin: 0;
                padding-left: 20px;
            }}
            .recommendations li {{
                margin: 10px 0;
                line-height: 1.5;
            }}
            .footer {{
                text-align: center;
                margin-top: 40px;
                padding-top: 20px;
                border-top: 1px solid #ddd;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Walk-Forward Optimization Report</h1>
                <p>Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            
            <div class="section">
                <h2>Configuration</h2>
                <table>
                    <tr><th>Parameter</th><th>Value</th></tr>
                    <tr><td>Train Months</td><td>{report.train_months}</td></tr>
                    <tr><td>Test Months</td><td>{report.test_months}</td></tr>
                    <tr><td>Step Months</td><td>{report.step_months}</td></tr>
                    <tr><td>Objective</td><td>{report.objective}</td></tr>
                    <tr><td>Total Windows</td><td>{report.total_windows}</td></tr>
                    <tr><td>Date Range</td><td>{report.global_start_date} to {report.global_end_date}</td></tr>
                </table>
            </div>
            
            <div class="section">
                <h2>Window Results</h2>
                <table>
                    <tr>
                        <th>Window</th>
                        <th>Train Dates</th>
                        <th>Test Dates</th>
                        <th>Train PnL</th>
                        <th>Test PnL</th>
                        <th>Degradation</th>
                    </tr>
    """
    
    # Add window results rows
    for wr in report.window_results:
        train_dates = f"{wr.window_config.train_start} to {wr.window_config.train_end}"
        test_dates = f"{wr.window_config.test_start} to {wr.window_config.test_end}"
        degradation_pct = f"{wr.performance_degradation:.1%}"
        
        html_content += f"""
                    <tr>
                        <td>{wr.window_config.window_id}</td>
                        <td>{train_dates}</td>
                        <td>{test_dates}</td>
                        <td>{wr.train_metrics.total_pnl:.2f}</td>
                        <td>{wr.test_metrics.total_pnl:.2f}</td>
                        <td>{degradation_pct}</td>
                    </tr>
        """
    
    html_content += """
                </table>
            </div>
            
            <div class="section">
                <h2>Performance Comparison</h2>
                <div class="chart">
    """
    
    if performance_chart:
        html_content += f'<img src="data:image/png;base64,{performance_chart}" alt="Performance Comparison Chart">'
    
    html_content += """
                </div>
            </div>
            
            <div class="section">
                <h2>Overfitting Analysis</h2>
                <div class="chart">
    """
    
    if overfitting_chart:
        html_content += f'<img src="data:image/png;base64,{overfitting_chart}" alt="Overfitting Heatmap">'
    
    html_content += """
                </div>
            </div>
            
            <div class="section">
                <h2>Aggregate Equity Curve</h2>
                <div class="chart">
    """
    
    if equity_chart:
        html_content += f'<img src="data:image/png;base64,{equity_chart}" alt="Aggregate Equity Curve">'
    
    html_content += """
                </div>
            </div>
            
            <div class="section">
                <h2>Parameter Stability</h2>
                <div class="chart">
    """
    
    if stability_chart:
        html_content += f'<img src="data:image/png;base64,{stability_chart}" alt="Parameter Stability Chart">'
    
    html_content += """
                </div>
                <table>
                    <tr><th>Parameter</th><th>Mean</th><th>Std</th><th>Stability Score</th></tr>
    """
    
    # Add parameter stability rows
    for param_name, stability in report.parameter_stability.items():
        html_content += f"""
                    <tr>
                        <td>{param_name}</td>
                        <td>{stability.mean:.3f}</td>
                        <td>{stability.std:.3f}</td>
                        <td>{stability.stability_score:.3f}</td>
                    </tr>
        """
    
    html_content += """
                </table>
            </div>
            
            <div class="section">
                <h2>Aggregate Performance</h2>
                <div class="metric-card">
                    <h3>Total Test PnL</h3>
                    <div class="value">{:.2f}</div>
                </div>
                <div class="metric-card">
                    <h3>Average Sharpe</h3>
                    <div class="value">{:.3f}</div>
                </div>
                <div class="metric-card">
                    <h3>Consistency Score</h3>
                    <div class="value">{:.1%}</div>
                </div>
                <div class="metric-card">
                    <h3>Overfitting Score</h3>
                    <div class="value">{:.3f}</div>
                </div>
            </div>
    """.format(
        report.aggregate_metrics.get('total_pnl', 0),
        report.aggregate_metrics.get('avg_sharpe', 0),
        report.aggregate_metrics.get('consistency_score', 0),
        report.overfitting_score
    )
    
    # Add parameter evolution charts
    if param_evolution_charts:
        html_content += """
            <div class="section">
                <h2>Parameter Evolution</h2>
        """
        
        for param_name, chart in param_evolution_charts.items():
            html_content += f"""
                <h3>{param_name}</h3>
                <div class="chart">
                    <img src="data:image/png;base64,{chart}" alt="Parameter Evolution: {param_name}">
                </div>
            """
        
        html_content += """
            </div>
        """
    
    # Add recommendations
    if report.recommendations:
        html_content += """
            <div class="section">
                <h2>Recommendations</h2>
                <div class="recommendations">
                    <ul>
        """
        
        for rec in report.recommendations:
            html_content += f"<li>{rec}</li>"
        
        html_content += """
                    </ul>
                </div>
            </div>
        """
    
    html_content += f"""
            <div class="footer">
                <p>Generated by Walk-Forward Optimizer on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    # Write HTML file
    with open(output_path, 'w') as f:
        f.write(html_content)
    
    logger.info(f"HTML report written to {output_path}")

def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Walk-Forward Optimization Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python optimization/walk_forward_optimizer.py --config grid_config.yaml --train-months 2 --test-months 1
  python optimization/walk_forward_optimizer.py --config grid_config.yaml --train-months 3 --test-months 1 --objective sharpe_ratio
  python optimization/walk_forward_optimizer.py --config grid_config.yaml --train-months 2 --test-months 1 --output results/walk_forward.html
        """
    )
    
    parser.add_argument(
        '--config',
        type=str,
        required=True,
        help='Path to grid search YAML configuration file'
    )
    
    parser.add_argument(
        '--train-months',
        type=int,
        required=True,
        help='Number of months for training window'
    )
    
    parser.add_argument(
        '--test-months',
        type=int,
        required=True,
        help='Number of months for testing window'
    )
    
    parser.add_argument(
        '--step-months',
        type=int,
        default=1,
        help='Number of months to step forward between windows (default: 1)'
    )
    
    parser.add_argument(
        '--start-date',
        type=str,
        help='Global start date (YYYY-MM-DD). Default: from BACKTEST_START_DATE environment variable'
    )
    
    parser.add_argument(
        '--end-date',
        type=str,
        help='Global end date (YYYY-MM-DD). Default: from BACKTEST_END_DATE environment variable'
    )
    
    parser.add_argument(
        '--objective',
        type=str,
        help='Objective function for optimization. Default: from config file'
    )
    
    parser.add_argument(
        '--workers',
        type=int,
        help='Number of parallel workers. Default: from config file'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='optimization/results/walk_forward.html',
        help='Path for HTML report output (default: optimization/results/walk_forward.html)'
    )
    
    parser.add_argument(
        '--json',
        action='store_true',
        help='Export JSON report in addition to HTML'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable debug logging'
    )
    
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from checkpoint'
    )
    
    args = parser.parse_args(argv)
    
    # Validate arguments
    if not Path(args.config).exists():
        parser.error(f"Config file not found: {args.config}")
    
    if args.train_months <= 0:
        parser.error("train-months must be positive")
    
    if args.test_months <= 0:
        parser.error("test-months must be positive")
    
    if args.step_months <= 0:
        parser.error("step-months must be positive")
    
    return args

def main(argv: Optional[List[str]] = None) -> int:
    """Main function for walk-forward optimization."""
    try:
        # Parse arguments
        args = parse_arguments(argv)
        
        # Set logging level
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        logger.info("Starting walk-forward optimization")
        
        # Load grid search configuration
        opt_config, param_ranges, fixed_params = load_grid_config(args.config)
        logger.info(f"Loaded configuration from {args.config}")
        
        # Override config with CLI arguments
        if args.objective:
            opt_config.objective = args.objective
        if args.workers:
            opt_config.workers = args.workers
        
        # Get global date range
        if args.start_date and args.end_date:
            start_date = args.start_date
            end_date = args.end_date
        else:
            # Get from environment variables
            start_date = os.getenv('BACKTEST_START_DATE')
            end_date = os.getenv('BACKTEST_END_DATE')
            
            if not start_date or not end_date:
                logger.error("Date range not provided. Use --start-date and --end-date or set BACKTEST_START_DATE and BACKTEST_END_DATE environment variables.")
                return 1
        
        # Get symbol and catalog path from environment
        symbol = os.getenv('BACKTEST_SYMBOL', 'EUR-USD')
        catalog_path = os.getenv('CATALOG_PATH', 'data/catalog')
        
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Symbol: {symbol}")
        logger.info(f"Catalog path: {catalog_path}")
        
        # Generate walk-forward windows
        windows = generate_walk_forward_windows(
            start_date, end_date, args.train_months, args.test_months, args.step_months
        )
        
        if not windows:
            logger.error("No windows generated. Check date range and window parameters.")
            return 1
        
        # Prepare base environment
        base_env = os.environ.copy()
        
        # Process each window
        window_results = []
        total_windows = len(windows)
        
        for i, window_config in enumerate(windows, 1):
            logger.info(f"Processing window {i}/{total_windows}")
            
            result = process_window(
                window_config, opt_config, param_ranges, fixed_params,
                base_env, symbol, catalog_path, args.resume
            )
            
            if result is not None:
                window_results.append(result)
                logger.info(f"Window {i}/{total_windows} completed successfully")
            else:
                logger.error(f"Window {i}/{total_windows} failed")
        
        if not window_results:
            logger.error("No successful windows processed")
            return 1
        
        logger.info(f"Processed {len(window_results)}/{total_windows} windows successfully")
        
        # Calculate analysis metrics
        param_stability = calculate_parameter_stability(window_results)
        overfitting_metrics = calculate_overfitting_metrics(window_results)
        aggregate_metrics = calculate_aggregate_performance(window_results)
        
        # Generate recommendations
        recommendations = generate_recommendations(
            WalkForwardReport(
                global_start_date=start_date,
                global_end_date=end_date,
                train_months=args.train_months,
                test_months=args.test_months,
                step_months=args.step_months,
                objective=opt_config.objective,
                total_windows=len(window_results),
                window_results=window_results,
                parameter_stability=param_stability,
                aggregate_metrics=aggregate_metrics,
                overfitting_score=overfitting_metrics.get('overfitting_score', 0.0),
                recommendations=[]
            )
        )
        
        # Create final report
        report = WalkForwardReport(
            global_start_date=start_date,
            global_end_date=end_date,
            train_months=args.train_months,
            test_months=args.test_months,
            step_months=args.step_months,
            objective=opt_config.objective,
            total_windows=len(window_results),
            window_results=window_results,
            parameter_stability=param_stability,
            aggregate_metrics=aggregate_metrics,
            overfitting_score=overfitting_metrics.get('overfitting_score', 0.0),
            recommendations=recommendations
        )
        
        # Generate reports
        logger.info("Generating reports...")
        
        # Console report (always)
        generate_console_report(report)
        
        # HTML report (always)
        html_path = Path(args.output)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        generate_html_report(report, html_path, {})
        
        # JSON report (if requested)
        if args.json:
            json_path = html_path.with_suffix('.json')
            generate_json_report(report, json_path)
            logger.info(f"JSON report written to {json_path}")
        
        logger.info(f"HTML report written to {html_path}")
        logger.info("Walk-forward optimization completed successfully")
        
        return 0
        
    except KeyboardInterrupt:
        logger.warning("Walk-forward optimization interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Error in walk-forward optimization: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
