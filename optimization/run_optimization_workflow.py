#!/usr/bin/env python3
"""
Automated Optimization Workflow Orchestrator

This module implements an automated optimization workflow that iteratively improves
strategy parameters through analysis-driven refinement. The workflow executes:
baseline backtest → loss analysis → parameter adjustment → grid search → 
comparison → iteration until convergence.

Workflow Stages:
1. Baseline: Run single backtest with current parameters
2. Analysis: Run loss analysis and parameter sensitivity (if previous grid search exists)
3. Adjustment: Parse suggestions from analysis tools, adjust parameter ranges
4. Optimization: Run grid search with adjusted ranges
5. Comparison: Compare new best result with baseline
6. Decision: Check convergence criteria, repeat or terminate

Usage Examples:
    Basic workflow:
        python optimization/run_optimization_workflow.py --config grid_config.yaml --iterations 3 --objective sharpe_ratio
    
    Auto-adjust parameters:
        python optimization/run_optimization_workflow.py --config grid_config.yaml --iterations 5 --auto-adjust-params --objective total_pnl
    
    Resume from checkpoint:
        python optimization/run_optimization_workflow.py --config grid_config.yaml --resume

Output Formats:
- Console progress logs with iteration summaries
- HTML report with iteration trajectory charts and parameter evolution
- JSON checkpoint files for resumability
- JSON export of final results (optional)

Exit Codes:
- 0: Success
- 1: Error
- 2: Invalid arguments
- 3: User interruption

Convergence Criteria:
- Maximum iterations reached
- Performance improvement < threshold (default: 5%)
- Parameter changes < threshold (default: 10%)
- User interruption (Ctrl+C)

The workflow integrates with existing analysis tools:
- analyze_losing_trades.py: Loss pattern analysis and parameter suggestions
- parameter_sensitivity.py: Parameter impact analysis and recommendations
- compare_backtests.py: Performance comparison and statistical testing
- grid_search.py: Parallel parameter optimization
- run_backtest.py: Individual backtest execution

All tool integration uses subprocess calls to maintain tool independence
and enable parallel execution. Data exchange uses JSON files for structured
communication between workflow stages.
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
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import yaml

# Project imports
from optimization.grid_search import (
    load_grid_config, is_minimization_objective
)
from analysis.compare_backtests import (
    BacktestMetrics, extract_metrics
)
from config.backtest_config import get_backtest_config

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Get project root for file operations
PROJECT_ROOT = Path(__file__).parent.parent

# Constants
DEFAULT_MAX_ITERATIONS = 5
CONVERGENCE_IMPROVEMENT_THRESHOLD = 0.05  # 5% minimum improvement
CONVERGENCE_PARAMETER_CHANGE_THRESHOLD = 0.1  # 10% minimum parameter change
PARAMETER_RANGE_EXPANSION_FACTOR = 0.2  # ±20% around suggested values
CHECKPOINT_FILENAME = "optimization_workflow_checkpoint.json"


@dataclass
class IterationResult:
    """Results from a single optimization iteration."""
    iteration_number: int
    baseline_result_dir: Optional[Path]  # None for iterations > 1
    best_result_dir: Optional[Path]
    best_parameters: Dict[str, Any]
    best_metrics: Optional[BacktestMetrics]
    loss_analysis_suggestions: List[str]
    sensitivity_recommendations: List[str]
    parameter_adjustments: Dict[str, Any]  # What changed from previous iteration
    improvement_vs_baseline: float  # Percentage improvement
    improvement_vs_previous: float  # Percentage improvement from last iteration
    duration_seconds: float
    timestamp: str


@dataclass
class WorkflowCheckpoint:
    """Checkpoint data for workflow resumability."""
    current_iteration: int
    max_iterations: int
    objective: str
    baseline_result_dir: Optional[str]  # Path as string for JSON serialization
    baseline_metrics: Dict[str, Any]  # BacktestMetrics as dict
    iteration_results: List[IterationResult]
    best_overall_result_dir: Optional[str]  # Path as string
    best_overall_parameters: Dict[str, Any]  # Parameters as dict
    best_overall_metrics: Dict[str, Any]  # Metrics as dict
    best_overall_iteration: int
    converged: bool
    convergence_reason: Optional[str]
    total_duration_seconds: float
    checkpoint_timestamp: str


@dataclass
class WorkflowReport:
    """Final workflow report with all results and analysis."""
    workflow_config: Dict[str, Any]
    checkpoint: WorkflowCheckpoint
    iteration_trajectory: List[Dict[str, Any]]  # Simplified iteration data for charts
    final_recommendations: List[str]
    convergence_analysis: Dict[str, Any]


def run_baseline_backtest(config: Dict[str, Any], output_dir: Path) -> Tuple[Path, BacktestMetrics]:
    """
    Execute single backtest with current environment parameters.
    
    Args:
        config: Backtest configuration dict
        output_dir: Directory to save backtest results
        
    Returns:
        Tuple of (baseline_result_dir, baseline_metrics)
    """
    logger.info("Running baseline backtest...")
    
    # Create baseline output directory
    baseline_dir = output_dir / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    
    # Run backtest via subprocess
    cmd = [
        sys.executable, "backtest/run_backtest.py"
    ]
    
    # Copy current environment and set OUTPUT_DIR
    env = os.environ.copy()
    env['OUTPUT_DIR'] = str(baseline_dir)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        logger.info(f"Baseline backtest completed successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"Baseline backtest failed: {e.stderr}")
        raise
    
    # Find the latest result directory
    result_dirs = [d for d in baseline_dir.iterdir() if d.is_dir()]
    if not result_dirs:
        raise RuntimeError("No backtest results found in baseline directory")
    
    latest_result_dir = max(result_dirs, key=lambda d: d.stat().st_mtime)
    
    # Use extract_metrics instead of manual construction
    metrics = extract_metrics(latest_result_dir)
    
    logger.info(f"Baseline metrics: PnL={metrics.total_pnl:.2f}, Sharpe={metrics.sharpe_ratio:.3f}, Win Rate={metrics.win_rate:.1%}")
    
    return latest_result_dir, metrics


def run_loss_analysis(backtest_output_dir: Path, analysis_output_dir: Path) -> Dict[str, Any]:
    """
    Run loss analysis on backtest results.
    
    Args:
        backtest_output_dir: Directory containing backtest results
        analysis_output_dir: Directory to save analysis results
        
    Returns:
        Dict with suggestions and analysis results
    """
    logger.info("Running loss analysis...")
    
    analysis_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Run loss analysis via subprocess
    cmd = [
        sys.executable, "analysis/analyze_losing_trades.py",
        "--input", str(backtest_output_dir),
        "--output", str(analysis_output_dir / "loss_analysis.html"),
        "--json"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info("Loss analysis completed successfully")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Loss analysis failed: {e.stderr}")
        return {"suggestions": [], "loss_categories": {}, "patterns_detected": {}}
    
    # Parse JSON output
    json_file = analysis_output_dir / "loss_analysis.json"
    if json_file.exists():
        with open(json_file, 'r') as f:
            analysis_data = json.load(f)
        
        suggestions = analysis_data.get('suggestions', [])
        loss_categories = analysis_data.get('loss_categories', {})
        patterns_detected = analysis_data.get('patterns_detected', {})
        
        logger.info(f"Loss analysis found {len(suggestions)} suggestions")
        return {
            "suggestions": suggestions,
            "loss_categories": loss_categories,
            "patterns_detected": patterns_detected
        }
    else:
        logger.warning("Loss analysis JSON output not found")
        return {"suggestions": [], "loss_categories": {}, "patterns_detected": {}}


def run_sensitivity_analysis(grid_search_csv: Path, analysis_output_dir: Path) -> Dict[str, Any]:
    """
    Run parameter sensitivity analysis on grid search results.
    
    Args:
        grid_search_csv: Path to grid search results CSV
        analysis_output_dir: Directory to save analysis results
        
    Returns:
        Dict with sensitivity recommendations
    """
    if not grid_search_csv.exists():
        logger.info("No previous grid search results found, skipping sensitivity analysis")
        return {"recommendations": [], "high_impact_parameters": [], "low_impact_parameters": []}
    
    logger.info("Running parameter sensitivity analysis...")
    
    analysis_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Run sensitivity analysis via subprocess
    cmd = [
        sys.executable, "analysis/parameter_sensitivity.py",
        "--input", str(grid_search_csv),
        "--output", str(analysis_output_dir / "sensitivity.html"),
        "--json"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info("Sensitivity analysis completed successfully")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Sensitivity analysis failed: {e.stderr}")
        return {"recommendations": [], "high_impact_parameters": [], "low_impact_parameters": []}
    
    # Parse JSON output
    json_file = analysis_output_dir / "sensitivity.json"
    if json_file.exists():
        with open(json_file, 'r') as f:
            sensitivity_data = json.load(f)
        
        recommendations = sensitivity_data.get('recommendations', [])
        high_impact = sensitivity_data.get('high_impact_parameters', [])
        low_impact = sensitivity_data.get('low_impact_parameters', [])
        
        logger.info(f"Sensitivity analysis found {len(recommendations)} recommendations")
        return {
            "recommendations": recommendations,
            "high_impact_parameters": high_impact,
            "low_impact_parameters": low_impact
        }
    else:
        logger.warning("Sensitivity analysis JSON output not found")
        return {"recommendations": [], "high_impact_parameters": [], "low_impact_parameters": []}


def parse_parameter_suggestions(suggestions: List[str]) -> Dict[str, Any]:
    """
    Parse natural language suggestions to extract parameter adjustments.
    
    Args:
        suggestions: List of suggestion strings from loss analysis
        
    Returns:
        Dict mapping parameter names to suggested values
    """
    adjustments = {}
    
    # Regex patterns for common suggestion formats
    patterns = [
        r"increase\s+(\w+)\s+from\s+([\d.]+)\s+to\s+([\d.]+)",
        r"decrease\s+(\w+)\s+from\s+([\d.]+)\s+to\s+([\d.]+)",
        r"set\s+(\w+)\s+to\s+([\d.]+)",
        r"consider\s+(\w+)\s*=\s*([\d.]+)",
        r"try\s+(\w+)\s*=\s*([\d.]+)",
        r"(\w+)\s+should\s+be\s+([\d.]+)",
        r"(\w+)\s+recommended\s+([\d.]+)"
    ]
    
    for suggestion in suggestions:
        suggestion_lower = suggestion.lower()
        
        for pattern in patterns:
            match = re.search(pattern, suggestion_lower)
            if match:
                param_name = match.group(1)
                suggested_value = float(match.group(2))
                adjustments[param_name] = suggested_value
                logger.info(f"Parsed suggestion: {param_name} = {suggested_value}")
                break
        else:
            logger.warning(f"Could not parse suggestion: {suggestion}")
    
    return adjustments


def adjust_parameter_ranges(
    current_ranges: Dict[str, List[Any]], 
    suggestions: Dict[str, Any], 
    sensitivity_info: Dict[str, Any],
    expansion_factor: float = 0.2
) -> Dict[str, List[Any]]:
    """
    Create new parameter ranges based on suggestions and sensitivity analysis.
    
    Args:
        current_ranges: Current parameter ranges from config
        suggestions: Parsed parameter suggestions
        sensitivity_info: Sensitivity analysis results
        expansion_factor: Factor for range expansion around suggestions
        
    Returns:
        Adjusted parameter ranges dict
    """
    adjusted_ranges = copy.deepcopy(current_ranges)
    high_impact = sensitivity_info.get('high_impact_parameters', [])
    low_impact = sensitivity_info.get('low_impact_parameters', [])
    
    for param_name, suggested_value in suggestions.items():
        if param_name not in current_ranges:
            logger.warning(f"Parameter {param_name} not found in current ranges, skipping")
            continue
        
        current_range = current_ranges[param_name]
        
        if param_name in high_impact:
            # High impact: create focused range around suggestion (±10%)
            range_size = suggested_value * 0.1
            new_range = [
                max(0, suggested_value - range_size),
                suggested_value + range_size
            ]
            # Ensure at least 3 values
            if len(new_range) < 3:
                new_range = [suggested_value * 0.9, suggested_value, suggested_value * 1.1]
            adjusted_ranges[param_name] = new_range
            logger.info(f"High impact parameter {param_name}: focused range around {suggested_value}")
            
        elif param_name in low_impact:
            # Low impact: fix to suggested value (single value)
            adjusted_ranges[param_name] = [suggested_value]
            logger.info(f"Low impact parameter {param_name}: fixed to {suggested_value}")
            
        else:
            # Medium impact: create moderate range around suggestion (±20%)
            range_size = suggested_value * expansion_factor
            new_range = [
                max(0, suggested_value - range_size),
                suggested_value + range_size
            ]
            # Ensure at least 3 values
            if len(new_range) < 3:
                new_range = [suggested_value * 0.8, suggested_value, suggested_value * 1.2]
            adjusted_ranges[param_name] = new_range
            logger.info(f"Medium impact parameter {param_name}: moderate range around {suggested_value}")
    
    # For parameters without suggestions
    for param_name, current_range in current_ranges.items():
        if param_name not in suggestions:
            if param_name in low_impact:
                # Fix low impact parameters to current best value
                if len(current_range) > 1:
                    # Use middle value as "best"
                    best_value = current_range[len(current_range) // 2]
                    adjusted_ranges[param_name] = [best_value]
                    logger.info(f"Fixed low impact parameter {param_name} to {best_value}")
            # High impact parameters keep current range for continued exploration
    
    return adjusted_ranges


def generate_adjusted_config(
    base_config_path: Path, 
    adjusted_ranges: Dict[str, List[Any]], 
    iteration: int, 
    output_dir: Path
) -> Path:
    """
    Generate adjusted config file with new parameter ranges.
    
    Args:
        base_config_path: Path to base grid search config
        adjusted_ranges: Adjusted parameter ranges
        iteration: Current iteration number
        output_dir: Directory to save adjusted config
        
    Returns:
        Path to new config file
    """
    # Load base config
    with open(base_config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Update parameter ranges
    if 'parameters' in config:
        for param_name, new_range in adjusted_ranges.items():
            if param_name in config['parameters']:
                config['parameters'][param_name] = new_range
                logger.info(f"Updated {param_name} range to {new_range}")
    
    # Save adjusted config
    adjusted_config_path = output_dir / f"iteration_{iteration}_config.yaml"
    with open(adjusted_config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, indent=2)
    
    logger.info(f"Generated adjusted config: {adjusted_config_path}")
    return adjusted_config_path


def run_grid_search_iteration(
    config_path: Path, 
    iteration: int, 
    output_dir: Path, 
    workers: int, 
    objective: str
) -> Tuple[Path, Dict[str, Any], BacktestMetrics, Path]:
    """
    Run grid search for one iteration.
    
    Args:
        config_path: Path to grid search config
        iteration: Current iteration number
        output_dir: Directory for results
        workers: Number of parallel workers
        objective: Objective function to optimize
        
    Returns:
        Tuple of (best_result_dir, best_parameters, best_metrics, results_csv)
    """
    logger.info(f"Running grid search for iteration {iteration}...")
    
    iteration_output_dir = output_dir / f"iteration_{iteration}"
    iteration_output_dir.mkdir(parents=True, exist_ok=True)
    
    results_csv = iteration_output_dir / f"iteration_{iteration}_grid_results.csv"
    
    # Run grid search via subprocess
    cmd = [
        sys.executable, "optimization/grid_search.py",
        "--config", str(config_path),
        "--workers", str(workers),
        "--objective", objective,
        "--output", str(results_csv)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"Grid search iteration {iteration} completed successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"Grid search iteration {iteration} failed: {e.stderr}")
        raise
    
    # Load and parse results
    if not results_csv.exists():
        raise RuntimeError(f"Grid search results CSV not found: {results_csv}")
    
    df = pd.read_csv(results_csv)
    if df.empty:
        raise RuntimeError("Grid search returned no results")
    
    # Sort DataFrame by objective value
    if 'objective_value' in df.columns:
        # Sort by objective value (descending for maximization, ascending for minimization)
        ascending = is_minimization_objective(objective)
        df_sorted = df.sort_values('objective_value', ascending=ascending)
    else:
        # Fallback: sort by the objective column directly
        if objective in df.columns:
            ascending = is_minimization_objective(objective)
            df_sorted = df.sort_values(objective, ascending=ascending)
        else:
            df_sorted = df
    
    # Get the best row
    best_row = df_sorted.iloc[0]
    best_result_dir = Path(best_row['output_directory'])
    
    # Extract parameters from the best row
    param_columns = [col for col in df.columns if col not in ['output_directory', 'total_pnl', 'sharpe_ratio', 'win_rate', 'max_drawdown', 'profit_factor', 'total_trades', 'avg_trade_pnl', 'objective_value', 'rank']]
    best_parameters = {col: best_row[col] for col in param_columns}
    
    # Extract metrics for the best result
    best_metrics = extract_metrics(best_result_dir)
    
    logger.info(f"Grid search iteration {iteration} found {len(df_sorted)} results")
    objective_value = getattr(best_metrics, objective, 0)
    logger.info(f"Best result: {objective}={objective_value:.3f}")
    
    return best_result_dir, best_parameters, best_metrics, results_csv


def run_comparison(
    baseline_dir: Path, 
    compare_dir: Path, 
    output_dir: Path, 
    iteration: int
) -> Dict[str, Any]:
    """
    Run comparison between baseline and current best result.
    
    Args:
        baseline_dir: Baseline backtest directory
        compare_dir: Current best result directory
        output_dir: Directory for comparison results
        iteration: Current iteration number
        
    Returns:
        Dict with comparison results
    """
    logger.info(f"Running comparison for iteration {iteration}...")
    
    comparison_output_dir = output_dir / f"iteration_{iteration}"
    comparison_output_dir.mkdir(parents=True, exist_ok=True)
    
    comparison_html = comparison_output_dir / f"iteration_{iteration}_comparison.html"
    
    # Run comparison via subprocess
    cmd = [
        sys.executable, "analysis/compare_backtests.py",
        "--baseline", str(baseline_dir),
        "--compare", str(compare_dir),
        "--output", str(comparison_html),
        "--json"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"Comparison for iteration {iteration} completed successfully")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Comparison for iteration {iteration} failed: {e.stderr}")
        return {"metric_deltas": {}, "statistical_tests": {}, "summary": "Comparison failed"}
    
    # Parse JSON output
    json_file = comparison_output_dir / f"iteration_{iteration}_comparison.json"
    if json_file.exists():
        with open(json_file, 'r') as f:
            comparison_data = json.load(f)
        
        metric_deltas = comparison_data.get('metric_deltas', {})
        statistical_tests = comparison_data.get('statistical_tests', {})
        summary = comparison_data.get('summary', '')
        
        logger.info(f"Comparison completed: {summary}")
        return {
            "metric_deltas": metric_deltas,
            "statistical_tests": statistical_tests,
            "summary": summary
        }
    else:
        logger.warning("Comparison JSON output not found")
        return {"metric_deltas": {}, "statistical_tests": {}, "summary": "Comparison failed"}


def check_convergence(iteration_results: List[IterationResult], max_iterations: int) -> Tuple[bool, str]:
    """
    Check if optimization has converged.
    
    Args:
        iteration_results: List of iteration results
        max_iterations: Maximum allowed iterations
        
    Returns:
        Tuple of (converged: bool, reason: str)
    """
    if len(iteration_results) == 0:
        return False, "No iterations completed"
    
    current_iteration = len(iteration_results)
    
    # Check max iterations
    if current_iteration >= max_iterations:
        return True, f"Maximum iterations reached ({max_iterations})"
    
    # Need at least 2 iterations to check for plateau
    if current_iteration < 2:
        return False, "Need more iterations to check convergence"
    
    # Check performance plateau
    last_improvement = iteration_results[-1].improvement_vs_previous
    if abs(last_improvement) < CONVERGENCE_IMPROVEMENT_THRESHOLD:
        return True, f"Performance plateau detected (improvement: {last_improvement:.1%})"
    
    # Check parameter stability (if we have parameter data)
    if len(iteration_results) >= 2:
        prev_params = iteration_results[-2].best_parameters
        current_params = iteration_results[-1].best_parameters
        
        # Calculate parameter changes
        param_changes = calculate_parameter_changes(prev_params, current_params)
        max_param_change = max(param_changes.values()) if param_changes else 0
        
        if max_param_change < CONVERGENCE_PARAMETER_CHANGE_THRESHOLD:
            return True, f"Parameter stability detected (max change: {max_param_change:.1%})"
    
    return False, "Continuing optimization"


def calculate_parameter_changes(prev_params: Dict[str, Any], current_params: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate percentage change for each parameter.
    
    Args:
        prev_params: Previous iteration parameters dict
        current_params: Current iteration parameters dict
        
    Returns:
        Dict mapping parameter names to change percentages
    """
    changes = {}
    
    # Get all parameter names from both sets
    all_params = set(prev_params.keys()) | set(current_params.keys())
    
    for param_name in all_params:
        try:
            prev_value = prev_params.get(param_name)
            current_value = current_params.get(param_name)
            
            if prev_value is None or current_value is None:
                continue
            
            # Handle numeric parameters
            if isinstance(prev_value, (int, float)) and isinstance(current_value, (int, float)):
                if prev_value != 0:
                    change = abs(current_value - prev_value) / abs(prev_value)
                    changes[param_name] = change
                else:
                    changes[param_name] = 1.0 if current_value != 0 else 0.0
            
            # Handle boolean parameters
            elif isinstance(prev_value, bool) and isinstance(current_value, bool):
                changes[param_name] = 1.0 if prev_value != current_value else 0.0
                
        except Exception as e:
            logger.warning(f"Could not calculate change for parameter {param_name}: {e}")
            continue
    
    return changes


def run_iteration(
    iteration_number: int,
    baseline_result_dir: Path,
    baseline_metrics: BacktestMetrics,
    previous_iteration: Optional[IterationResult],
    config_path: Path,
    workflow_config: Dict[str, Any],
    output_dir: Path
) -> IterationResult:
    """
    Execute one complete optimization iteration.
    
    Args:
        iteration_number: Current iteration number
        baseline_result_dir: Baseline backtest result directory
        baseline_metrics: Baseline metrics
        previous_iteration: Previous iteration result (None for first iteration)
        config_path: Path to grid search config
        workflow_config: Workflow configuration
        output_dir: Directory for iteration results
        
    Returns:
        IterationResult object
    """
    start_time = time.time()
    logger.info(f"Starting iteration {iteration_number}")
    
    # Create iteration output directory
    iteration_output_dir = output_dir / f"iteration_{iteration_number}"
    iteration_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize iteration result
    iteration_result = IterationResult(
        iteration_number=iteration_number,
        baseline_result_dir=baseline_result_dir if iteration_number == 1 else None,
        best_result_dir=None,
        best_parameters={},  # Will be set after grid search
        best_metrics=None,  # Will be set after grid search
        loss_analysis_suggestions=[],
        sensitivity_recommendations=[],
        parameter_adjustments={},
        improvement_vs_baseline=0.0,
        improvement_vs_previous=0.0,
        duration_seconds=0.0,
        timestamp=datetime.datetime.now().isoformat()
    )
    
    try:
        # Stage 1: Loss Analysis (if not first iteration)
        if iteration_number > 1 and previous_iteration and previous_iteration.best_result_dir:
            logger.info("Running loss analysis...")
            loss_analysis = run_loss_analysis(
                previous_iteration.best_result_dir,
                iteration_output_dir / "analysis"
            )
            iteration_result.loss_analysis_suggestions = loss_analysis.get('suggestions', [])
        
        # Stage 2: Sensitivity Analysis (if not first iteration and previous grid search exists)
        if iteration_number > 1 and previous_iteration:
            # Look for previous grid search CSV
            prev_grid_csv = output_dir / f"iteration_{iteration_number-1}" / f"iteration_{iteration_number-1}_grid_results.csv"
            if prev_grid_csv.exists():
                logger.info("Running sensitivity analysis...")
                sensitivity_analysis = run_sensitivity_analysis(
                    prev_grid_csv,
                    iteration_output_dir / "analysis"
                )
                iteration_result.sensitivity_recommendations = sensitivity_analysis.get('recommendations', [])
        
        # Stage 3: Parameter Adjustment (if not first iteration)
        if iteration_number > 1:
            logger.info("Adjusting parameter ranges...")
            
            # Parse suggestions
            suggestions = parse_parameter_suggestions(iteration_result.loss_analysis_suggestions)
            
            # Get sensitivity info
            sensitivity_info = {}
            if iteration_result.sensitivity_recommendations:
                # Parse sensitivity recommendations for high/low impact parameters
                high_impact = []
                low_impact = []
                for rec in iteration_result.sensitivity_recommendations:
                    if "high impact" in rec.lower():
                        # Extract parameter name from recommendation
                        # This is a simplified parser - could be enhanced
                        pass
                    elif "low impact" in rec.lower():
                        # Extract parameter name from recommendation
                        pass
                sensitivity_info = {
                    'high_impact_parameters': high_impact,
                    'low_impact_parameters': low_impact
                }
            
            # Adjust parameter ranges only if auto_adjust_params is enabled
            if workflow_config.get('auto_adjust_params', False):
                if suggestions:
                    # Load current config to get parameter ranges
                    with open(config_path, 'r') as f:
                        config = yaml.safe_load(f)
                    
                    current_ranges = config.get('parameters', {})
                    adjusted_ranges = adjust_parameter_ranges(
                        current_ranges, suggestions, sensitivity_info
                    )
                    
                    # Generate adjusted config
                    adjusted_config_path = generate_adjusted_config(
                        config_path, adjusted_ranges, iteration_number, iteration_output_dir
                    )
                    config_path = adjusted_config_path
                    
                    iteration_result.parameter_adjustments = suggestions
            else:
                # Auto-adjust is disabled, write proposed config but don't use it
                if suggestions:
                    # Load current config to get parameter ranges
                    with open(config_path, 'r') as f:
                        config = yaml.safe_load(f)
                    
                    current_ranges = config.get('parameters', {})
                    adjusted_ranges = adjust_parameter_ranges(
                        current_ranges, suggestions, sensitivity_info
                    )
                    
                    # Generate proposed adjusted config
                    proposed_config_path = generate_adjusted_config(
                        config_path, adjusted_ranges, iteration_number, iteration_output_dir
                    )
                    
                    print(f"\nProposed parameter adjustments for iteration {iteration_number}:")
                    print(f"Adjusted config written to: {proposed_config_path}")
                    print("Review the proposed changes and manually update config if desired.")
                    
                    iteration_result.parameter_adjustments = suggestions
        
        # Stage 4: Grid Search
        logger.info("Running grid search...")
        workers = workflow_config.get('workers', 4)
        objective = workflow_config.get('objective', 'total_pnl')
        
        best_result_dir, best_parameters, best_metrics, results_csv = run_grid_search_iteration(
            config_path, iteration_number, output_dir, workers, objective
        )
        
        iteration_result.best_result_dir = best_result_dir
        iteration_result.best_parameters = best_parameters
        iteration_result.best_metrics = best_metrics
        
        # Stage 5: Comparison
        logger.info("Running comparison...")
        comparison_results = run_comparison(
            baseline_result_dir,
            iteration_result.best_result_dir,
            output_dir,
            iteration_number
        )
        
        # Calculate improvements
        baseline_value = getattr(baseline_metrics, objective, 0)
        current_value = getattr(iteration_result.best_metrics, objective, 0)
        
        if baseline_value != 0:
            iteration_result.improvement_vs_baseline = (current_value - baseline_value) / abs(baseline_value)
        else:
            iteration_result.improvement_vs_baseline = 0.0
        
        if previous_iteration and previous_iteration.best_metrics:
            prev_value = getattr(previous_iteration.best_metrics, objective, 0)
            if prev_value != 0:
                iteration_result.improvement_vs_previous = (current_value - prev_value) / abs(prev_value)
            else:
                iteration_result.improvement_vs_previous = 0.0
        
        # Calculate duration
        iteration_result.duration_seconds = time.time() - start_time
        
        logger.info(f"Iteration {iteration_number} completed in {iteration_result.duration_seconds:.1f}s")
        logger.info(f"Best {objective}: {current_value:.3f} (vs baseline: {iteration_result.improvement_vs_baseline:+.1%})")
        
        return iteration_result
        
    except Exception as e:
        logger.error(f"Iteration {iteration_number} failed: {e}")
        iteration_result.duration_seconds = time.time() - start_time
        raise


def save_checkpoint(checkpoint: WorkflowCheckpoint, checkpoint_path: Path) -> None:
    """
    Save workflow checkpoint to file.
    
    Args:
        checkpoint: Checkpoint data to save
        checkpoint_path: Path to save checkpoint file
    """
    logger.info(f"Saving checkpoint to {checkpoint_path}")
    
    # Create backup of previous checkpoint
    if checkpoint_path.exists():
        backup_path = checkpoint_path.with_suffix('.backup')
        shutil.copy2(checkpoint_path, backup_path)
    
    # Convert to serializable format
    checkpoint_dict = asdict(checkpoint)
    
    # Convert Path objects to strings and BacktestMetrics to dicts
    def convert_for_serialization(obj):
        if isinstance(obj, Path):
            return str(obj)
        elif isinstance(obj, BacktestMetrics):
            return asdict(obj)
        elif isinstance(obj, dict):
            return {k: convert_for_serialization(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_for_serialization(item) for item in obj]
        else:
            return obj
    
    checkpoint_dict = convert_for_serialization(checkpoint_dict)
    
    # Save to file
    with open(checkpoint_path, 'w') as f:
        json.dump(checkpoint_dict, f, indent=2, default=str)
    
    logger.info("Checkpoint saved successfully")


def load_checkpoint(checkpoint_path: Path) -> Optional[WorkflowCheckpoint]:
    """
    Load workflow checkpoint from file.
    
    Args:
        checkpoint_path: Path to checkpoint file
        
    Returns:
        WorkflowCheckpoint object or None if invalid/missing
    """
    if not checkpoint_path.exists():
        logger.info("No checkpoint file found")
        return None
    
    try:
        with open(checkpoint_path, 'r') as f:
            checkpoint_data = json.load(f)
        
        # Convert iteration results back to proper objects
        iteration_results = []
        for iter_data in checkpoint_data.get('iteration_results', []):
            # Convert baseline_result_dir if present
            if iter_data.get('baseline_result_dir'):
                iter_data['baseline_result_dir'] = Path(iter_data['baseline_result_dir'])
            
            # Convert best_result_dir if present
            if iter_data.get('best_result_dir'):
                iter_data['best_result_dir'] = Path(iter_data['best_result_dir'])
            
            # Convert best_metrics if present
            if iter_data.get('best_metrics'):
                iter_data['best_metrics'] = BacktestMetrics(**iter_data['best_metrics'])
            
            iteration_result = IterationResult(**iter_data)
            iteration_results.append(iteration_result)
        
        checkpoint_data['iteration_results'] = iteration_results
        
        # Convert baseline_result_dir if present
        if checkpoint_data.get('baseline_result_dir'):
            checkpoint_data['baseline_result_dir'] = Path(checkpoint_data['baseline_result_dir'])
        
        # Convert best_overall_result_dir if present
        if checkpoint_data.get('best_overall_result_dir'):
            checkpoint_data['best_overall_result_dir'] = Path(checkpoint_data['best_overall_result_dir'])
        
        # Convert best_overall_metrics if present
        if checkpoint_data.get('best_overall_metrics'):
            checkpoint_data['best_overall_metrics'] = BacktestMetrics(**checkpoint_data['best_overall_metrics'])
        
        checkpoint = WorkflowCheckpoint(**checkpoint_data)
        logger.info("Checkpoint loaded successfully")
        return checkpoint
        
    except Exception as e:
        logger.warning(f"Failed to load checkpoint: {e}")
        return None


def resume_from_checkpoint(checkpoint_path: Path) -> Tuple[WorkflowCheckpoint, int]:
    """
    Resume workflow from checkpoint.
    
    Args:
        checkpoint_path: Path to checkpoint file
        
    Returns:
        Tuple of (checkpoint, next_iteration_number)
    """
    checkpoint = load_checkpoint(checkpoint_path)
    if checkpoint is None:
        raise RuntimeError("Cannot resume: no valid checkpoint found")
    
    if checkpoint.converged:
        raise RuntimeError("Cannot resume: workflow already converged")
    
    next_iteration = checkpoint.current_iteration + 1
    logger.info(f"Resuming from iteration {next_iteration}")
    
    return checkpoint, next_iteration


def analyze_improvement_trajectory(iteration_results: List[IterationResult], objective: str) -> Dict[str, Any]:
    """
    Analyze improvement trajectory across iterations.
    
    Args:
        iteration_results: List of iteration results
        objective: Objective function name
        
    Returns:
        Dict with trajectory analysis
    """
    if not iteration_results:
        return {"trend": "no_data", "total_improvement": 0.0, "best_iteration": 0}
    
    # Extract objective values
    objective_values = []
    for result in iteration_results:
        if result.best_metrics:
            value = getattr(result.best_metrics, objective, 0)
            objective_values.append(value)
        else:
            objective_values.append(0)
    
    # Calculate trends
    if len(objective_values) >= 3:
        # Simple trend detection
        recent_trend = objective_values[-1] - objective_values[-2]
        overall_trend = objective_values[-1] - objective_values[0]
        
        if recent_trend > 0:
            trend = "improving"
        elif recent_trend < 0:
            trend = "degrading"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"
        overall_trend = 0
    
    # Find best iteration using configured objective
    best_iteration = 0
    best_value = objective_values[0] if objective_values else 0
    for i, value in enumerate(objective_values):
        if value > best_value:
            best_value = value
            best_iteration = i + 1
    
    return {
        "trend": trend,
        "total_improvement": overall_trend,
        "best_iteration": best_iteration,
        "objective_values": objective_values
    }


def generate_final_recommendations(iteration_results: List[IterationResult], convergence_reason: str, objective: str) -> List[str]:
    """
    Generate final recommendations based on workflow results.
    
    Args:
        iteration_results: List of iteration results
        convergence_reason: Reason for convergence
        objective: Objective function name
        
    Returns:
        List of recommendation strings
    """
    recommendations = []
    
    # Add convergence-specific recommendations
    if "plateau" in convergence_reason.lower():
        recommendations.append("Parameters have stabilized. Consider testing on different market conditions.")
    elif "maximum iterations" in convergence_reason.lower():
        recommendations.append("Max iterations reached. Consider running additional iterations if improvement trend continues.")
    
    # Add trajectory-based recommendations
    if len(iteration_results) >= 2:
        best_iteration = 0
        best_value = getattr(iteration_results[0].best_metrics, objective, 0)
        
        for i, result in enumerate(iteration_results):
            current_value = getattr(result.best_metrics, objective, 0)
            if current_value > best_value:
                best_value = current_value
                best_iteration = i + 1
        
        if best_iteration < len(iteration_results) - 1:
            recommendations.append(f"Best performance was in iteration {best_iteration}. Later iterations may have overfit.")
    
    # Aggregate suggestions from all iterations
    all_suggestions = []
    for result in iteration_results:
        all_suggestions.extend(result.loss_analysis_suggestions)
    
    # Count suggestion frequency
    suggestion_counts = {}
    for suggestion in all_suggestions:
        suggestion_counts[suggestion] = suggestion_counts.get(suggestion, 0) + 1
    
    # Add most frequent suggestions
    for suggestion, count in sorted(suggestion_counts.items(), key=lambda x: x[1], reverse=True)[:3]:
        if count > 1:  # Only include suggestions that appeared multiple times
            recommendations.append(f"Frequently suggested: {suggestion}")
    
    return recommendations


def create_iteration_trajectory_chart(iteration_results: List[IterationResult], objective: str, baseline_value: float = None) -> str:
    """
    Create line chart showing objective value across iterations.
    
    Args:
        iteration_results: List of iteration results
        objective: Objective function name
        baseline_value: Baseline value to draw reference line (optional)
        
    Returns:
        Base64-encoded PNG string
    """
    if not iteration_results:
        return ""
    
    # Extract data
    iterations = list(range(1, len(iteration_results) + 1))
    objective_values = []
    for result in iteration_results:
        if result.best_metrics:
            value = getattr(result.best_metrics, objective, 0)
            objective_values.append(value)
        else:
            objective_values.append(0)
    
    # Create chart
    plt.figure(figsize=(10, 6))
    plt.plot(iterations, objective_values, 'b-o', linewidth=2, markersize=6)
    
    # Add baseline reference if available
    if baseline_value is not None:
        plt.axhline(y=baseline_value, color='r', linestyle='--', alpha=0.7, label='Baseline')
    
    # Mark best iteration
    if objective_values:
        best_idx = objective_values.index(max(objective_values))
        plt.plot(iterations[best_idx], objective_values[best_idx], 'g*', markersize=12, label='Best')
    
    plt.xlabel('Iteration')
    plt.ylabel(f'{objective.replace("_", " ").title()}')
    plt.title(f'Optimization Trajectory - {objective.replace("_", " ").title()}')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    # Convert to base64
    import io
    import base64
    
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64


def create_improvement_bar_chart(iteration_results: List[IterationResult]) -> str:
    """
    Create bar chart showing improvement percentage per iteration.
    
    Args:
        iteration_results: List of iteration results
        
    Returns:
        Base64-encoded PNG string
    """
    if not iteration_results:
        return ""
    
    # Extract data
    iterations = list(range(1, len(iteration_results) + 1))
    improvements = [result.improvement_vs_baseline for result in iteration_results]
    
    # Create chart
    plt.figure(figsize=(10, 6))
    colors = ['green' if imp > 0 else 'red' for imp in improvements]
    bars = plt.bar(iterations, improvements, color=colors, alpha=0.7)
    
    # Add cumulative improvement line
    cumulative = np.cumsum(improvements)
    plt.plot(iterations, cumulative, 'b-o', linewidth=2, label='Cumulative Improvement')
    
    plt.xlabel('Iteration')
    plt.ylabel('Improvement vs Baseline (%)')
    plt.title('Iteration Improvements')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    # Add value labels on bars
    for bar, imp in zip(bars, improvements):
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height,
                f'{imp:.1%}', ha='center', va='bottom' if height > 0 else 'top')
    
    # Convert to base64
    import io
    import base64
    
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64


def create_parameter_evolution_chart(iteration_results: List[IterationResult], param_name: str) -> str:
    """
    Create line chart showing parameter value evolution across iterations.
    
    Args:
        iteration_results: List of iteration results
        param_name: Parameter name to track
        
    Returns:
        Base64-encoded PNG string
    """
    if not iteration_results:
        return ""
    
    # Extract parameter values
    iterations = list(range(1, len(iteration_results) + 1))
    param_values = []
    
    for result in iteration_results:
        try:
            value = result.best_parameters.get(param_name, None)
            if value is not None:
                param_values.append(value)
            else:
                param_values.append(0)  # Default for missing values
        except:
            param_values.append(0)
    
    # Create chart
    plt.figure(figsize=(10, 6))
    plt.plot(iterations, param_values, 'b-o', linewidth=2, markersize=6)
    
    # Highlight final value
    if param_values:
        plt.plot(iterations[-1], param_values[-1], 'r*', markersize=12, label='Final Value')
    
    plt.xlabel('Iteration')
    plt.ylabel(f'{param_name.replace("_", " ").title()}')
    plt.title(f'Parameter Evolution - {param_name.replace("_", " ").title()}')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    # Convert to base64
    import io
    import base64
    
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64


def create_convergence_analysis_chart(iteration_results: List[IterationResult], objective: str) -> str:
    """
    Create multi-line chart showing convergence indicators.
    
    Args:
        iteration_results: List of iteration results
        objective: Objective function name
        
    Returns:
        Base64-encoded PNG string
    """
    if not iteration_results:
        return ""
    
    # Extract data
    iterations = list(range(1, len(iteration_results) + 1))
    objective_values = []
    improvements = []
    param_changes = []
    
    for result in iteration_results:
        if result.best_metrics:
            objective_values.append(getattr(result.best_metrics, objective, 0))
        else:
            objective_values.append(0)
        improvements.append(result.improvement_vs_baseline)
        # Simplified parameter change calculation
        param_changes.append(len(result.parameter_adjustments))
    
    # Create chart
    fig, ax1 = plt.subplots(figsize=(12, 8))
    
    # Primary y-axis: objective value
    color1 = 'tab:blue'
    ax1.set_xlabel('Iteration')
    ax1.set_ylabel(f'{objective.replace("_", " ").title()}', color=color1)
    line1 = ax1.plot(iterations, objective_values, 'b-o', linewidth=2, label=f'{objective.replace("_", " ").title()}', color=color1)
    ax1.tick_params(axis='y', labelcolor=color1)
    
    # Secondary y-axis: improvement rate
    ax2 = ax1.twinx()
    color2 = 'tab:green'
    ax2.set_ylabel('Improvement vs Baseline (%)', color=color2)
    line2 = ax2.plot(iterations, improvements, 'g-s', linewidth=2, label='Improvement %', color=color2)
    ax2.tick_params(axis='y', labelcolor=color2)
    
    # Add parameter changes as bars
    ax3 = ax1.twinx()
    ax3.spines['right'].set_position(('outward', 60))
    color3 = 'tab:red'
    ax3.set_ylabel('Parameter Changes', color=color3)
    bars = ax3.bar(iterations, param_changes, alpha=0.3, color=color3, label='Parameter Changes')
    ax3.tick_params(axis='y', labelcolor=color3)
    
    plt.title('Convergence Analysis')
    plt.grid(True, alpha=0.3)
    
    # Combine legends
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc='upper left')
    
    # Convert to base64
    import io
    import base64
    
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64


def generate_console_report(report: WorkflowReport) -> None:
    """
    Generate formatted console report.
    
    Args:
        report: Workflow report data
    """
    print("\n" + "="*80)
    print("OPTIMIZATION WORKFLOW REPORT")
    print("="*80)
    
    # Configuration
    print(f"\nConfiguration:")
    print(f"  Max Iterations: {report.checkpoint.max_iterations}")
    print(f"  Objective: {report.checkpoint.objective}")
    print(f"  Auto-adjust Params: {report.workflow_config.get('auto_adjust_params', False)}")
    print(f"  Convergence Threshold: {CONVERGENCE_IMPROVEMENT_THRESHOLD:.1%}")
    
    # Iteration Summary
    print(f"\nIteration Summary:")
    print(f"{'Iter':<4} {'Objective':<12} {'vs Baseline':<12} {'vs Previous':<12} {'Duration':<10}")
    print("-" * 60)
    
    for i, result in enumerate(report.checkpoint.iteration_results):
        objective_value = getattr(result.best_metrics, report.checkpoint.objective, 0)
        print(f"{i+1:<4} {objective_value:<12.3f} {result.improvement_vs_baseline:<12.1%} {result.improvement_vs_previous:<12.1%} {result.duration_seconds:<10.1f}s")
    
    # Best Result
    if report.checkpoint.best_overall_result_dir:
        print(f"\nBest Result:")
        print(f"  Iteration: {report.checkpoint.best_overall_iteration + 1}")
        print(f"  Parameters: {report.checkpoint.best_overall_parameters}")
        print(f"  Metrics: {report.checkpoint.best_overall_metrics}")
    
    # Convergence Analysis
    print(f"\nConvergence Analysis:")
    print(f"  Converged: {report.checkpoint.converged}")
    print(f"  Reason: {report.checkpoint.convergence_reason}")
    print(f"  Total Iterations: {len(report.checkpoint.iteration_results)}")
    print(f"  Total Duration: {report.checkpoint.total_duration_seconds:.1f}s")
    
    # Final Recommendations
    if report.final_recommendations:
        print(f"\nFinal Recommendations:")
        for i, rec in enumerate(report.final_recommendations, 1):
            print(f"  {i}. {rec}")
    
    print("\n" + "="*80)


def generate_json_report(report: WorkflowReport, output_path: Path) -> None:
    """
    Generate JSON report.
    
    Args:
        report: Workflow report data
        output_path: Path to save JSON report
    """
    # Convert report to serializable format
    report_dict = {
        "workflow_config": report.workflow_config,
        "iterations": [],
        "best_overall": {},
        "convergence": {
            "converged": report.checkpoint.converged,
            "reason": report.checkpoint.convergence_reason,
            "total_iterations": len(report.checkpoint.iteration_results),
            "total_duration": report.checkpoint.total_duration_seconds
        },
        "trajectory_analysis": report.convergence_analysis,
        "final_recommendations": report.final_recommendations
    }
    
    # Add iteration data
    for result in report.checkpoint.iteration_results:
        iteration_data = {
            "iteration_number": result.iteration_number,
            "best_result": {
                "parameters": result.best_parameters,
                "metrics": asdict(result.best_metrics)
            },
            "suggestions": result.loss_analysis_suggestions,
            "improvements": {
                "vs_baseline": result.improvement_vs_baseline,
                "vs_previous": result.improvement_vs_previous
            },
            "duration": result.duration_seconds
        }
        report_dict["iterations"].append(iteration_data)
    
    # Add best overall result
    if report.checkpoint.best_overall_result_dir:
        report_dict["best_overall"] = {
            "iteration": report.checkpoint.best_overall_iteration + 1,
            "parameters": report.checkpoint.best_overall_parameters,
            "metrics": report.checkpoint.best_overall_metrics
        }
    
    # Save JSON report
    with open(output_path, 'w') as f:
        json.dump(report_dict, f, indent=2, default=str)
    
    logger.info(f"JSON report saved to {output_path}")


def generate_html_report(report: WorkflowReport, output_path: Path, charts: Dict[str, str]) -> None:
    """
    Generate HTML report with embedded charts.
    
    Args:
        report: Workflow report data
        output_path: Path to save HTML report
        charts: Dict of chart names to base64-encoded PNG strings
    """
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Optimization Workflow Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
            .section {{ margin: 20px 0; }}
            .metric {{ display: inline-block; margin: 10px; padding: 10px; background-color: #e8f4f8; border-radius: 3px; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .chart {{ text-align: center; margin: 20px 0; }}
            .recommendation {{ background-color: #fff3cd; padding: 10px; margin: 5px 0; border-left: 4px solid #ffc107; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Optimization Workflow Report</h1>
            <p>Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="section">
            <h2>Configuration</h2>
            <div class="metric">Max Iterations: {report.checkpoint.max_iterations}</div>
            <div class="metric">Objective: {report.checkpoint.objective}</div>
            <div class="metric">Auto-adjust: {report.workflow_config.get('auto_adjust_params', False)}</div>
        </div>
        
        <div class="section">
            <h2>Iteration Summary</h2>
            <table>
                <tr>
                    <th>Iteration</th>
                    <th>Objective Value</th>
                    <th>vs Baseline</th>
                    <th>vs Previous</th>
                    <th>Duration</th>
                </tr>
    """
    
    # Add iteration rows
    for i, result in enumerate(report.checkpoint.iteration_results):
        objective_value = getattr(result.best_metrics, report.checkpoint.objective, 0)
        html_content += f"""
                <tr>
                    <td>{i+1}</td>
                    <td>{objective_value:.3f}</td>
                    <td>{result.improvement_vs_baseline:+.1%}</td>
                    <td>{result.improvement_vs_previous:+.1%}</td>
                    <td>{result.duration_seconds:.1f}s</td>
                </tr>
        """
    
    html_content += """
            </table>
        </div>
    """
    
    # Add charts
    if charts.get('trajectory'):
        html_content += f"""
        <div class="section">
            <h2>Optimization Trajectory</h2>
            <div class="chart">
                <img src="data:image/png;base64,{charts['trajectory']}" alt="Trajectory Chart">
            </div>
        </div>
        """
    
    if charts.get('improvement'):
        html_content += f"""
        <div class="section">
            <h2>Improvement Analysis</h2>
            <div class="chart">
                <img src="data:image/png;base64,{charts['improvement']}" alt="Improvement Chart">
            </div>
        </div>
        """
    
    if charts.get('convergence'):
        html_content += f"""
        <div class="section">
            <h2>Convergence Analysis</h2>
            <div class="chart">
                <img src="data:image/png;base64,{charts['convergence']}" alt="Convergence Chart">
            </div>
        </div>
        """
    
    # Add best result
    if report.checkpoint.best_overall_result_dir:
        html_content += f"""
        <div class="section">
            <h2>Best Result</h2>
            <p><strong>Iteration:</strong> {report.checkpoint.best_overall_iteration + 1}</p>
            <p><strong>Parameters:</strong> {report.checkpoint.best_overall_parameters}</p>
            <p><strong>Metrics:</strong> {report.checkpoint.best_overall_metrics}</p>
        </div>
        """
    
    # Add convergence analysis
    html_content += f"""
        <div class="section">
            <h2>Convergence Analysis</h2>
            <p><strong>Converged:</strong> {report.checkpoint.converged}</p>
            <p><strong>Reason:</strong> {report.checkpoint.convergence_reason}</p>
            <p><strong>Total Duration:</strong> {report.checkpoint.total_duration_seconds:.1f}s</p>
        </div>
    """
    
    # Add recommendations
    if report.final_recommendations:
        html_content += """
        <div class="section">
            <h2>Final Recommendations</h2>
        """
        for rec in report.final_recommendations:
            html_content += f'<div class="recommendation">{rec}</div>'
        html_content += "</div>"
    
    html_content += """
    </body>
    </html>
    """
    
    # Save HTML report
    with open(output_path, 'w') as f:
        f.write(html_content)
    
    logger.info(f"HTML report saved to {output_path}")


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """
    Parse command line arguments.
    
    Args:
        argv: Command line arguments (None for sys.argv)
        
    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Automated optimization workflow orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    Basic workflow:
        python optimization/run_optimization_workflow.py --config grid_config.yaml --iterations 3 --objective sharpe_ratio
    
    Auto-adjust parameters:
        python optimization/run_optimization_workflow.py --config grid_config.yaml --iterations 5 --auto-adjust-params --objective total_pnl
    
    Resume from checkpoint:
        python optimization/run_optimization_workflow.py --config grid_config.yaml --resume
        """
    )
    
    parser.add_argument(
        '--config',
        type=Path,
        required=True,
        help='Path to base grid search YAML config file'
    )
    
    parser.add_argument(
        '--iterations',
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help=f'Maximum number of optimization iterations (default: {DEFAULT_MAX_ITERATIONS})'
    )
    
    parser.add_argument(
        '--objective',
        type=str,
        default='total_pnl',
        help='Objective function to optimize (default: total_pnl)'
    )
    
    parser.add_argument(
        '--auto-adjust-params',
        action='store_true',
        help='Automatically apply parameter suggestions without user confirmation'
    )
    
    parser.add_argument(
        '--workers',
        type=int,
        default=4,
        help='Number of parallel workers for grid search (default: 4)'
    )
    
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('optimization/results/workflow'),
        help='Path for workflow results directory (default: optimization/results/workflow)'
    )
    
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from checkpoint'
    )
    
    parser.add_argument(
        '--checkpoint-path',
        type=Path,
        help='Custom checkpoint file path (default: auto-generated)'
    )
    
    parser.add_argument(
        '--json',
        action='store_true',
        help='Export JSON report'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable debug logging'
    )
    
    args = parser.parse_args(argv)
    
    # Validate arguments
    if not args.config.exists():
        parser.error(f"Config file not found: {args.config}")
    
    if args.iterations <= 0:
        parser.error("Iterations must be positive")
    
    return args


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main workflow orchestration function.
    
    Args:
        argv: Command line arguments (None for sys.argv)
        
    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Parse arguments
        args = parse_arguments(argv)
        
        # Set logging level
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        # Load base grid search configuration
        logger.info(f"Loading configuration from {args.config}")
        grid_config = load_grid_config(args.config)
        
        # Get backtest config
        backtest_config = get_backtest_config()
        
        # Create output directory
        output_dir = args.output
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine checkpoint path
        if args.checkpoint_path:
            checkpoint_path = args.checkpoint_path
        else:
            checkpoint_path = output_dir / CHECKPOINT_FILENAME
        
        # Initialize workflow state
        workflow_config = {
            'max_iterations': args.iterations,
            'objective': args.objective,
            'auto_adjust_params': args.auto_adjust_params,
            'workers': args.workers
        }
        
        # Resume or start fresh
        if args.resume:
            logger.info("Resuming from checkpoint...")
            checkpoint, start_iteration = resume_from_checkpoint(checkpoint_path)
            baseline_result_dir = checkpoint.baseline_result_dir
            baseline_metrics = BacktestMetrics(**checkpoint.baseline_metrics)
            iteration_results = checkpoint.iteration_results
            best_overall_result_dir = checkpoint.best_overall_result_dir
            best_overall_parameters = checkpoint.best_overall_parameters
            best_overall_metrics = BacktestMetrics(**checkpoint.best_overall_metrics) if checkpoint.best_overall_metrics else None
        else:
            logger.info("Starting fresh workflow...")
            start_iteration = 1
            
            # Run baseline backtest
            logger.info("Running baseline backtest...")
            baseline_result_dir, baseline_metrics = run_baseline_backtest(backtest_config, output_dir / "baseline")
            
            iteration_results = []
            best_overall_result_dir = baseline_result_dir
            best_overall_parameters = {}
            best_overall_metrics = baseline_metrics
        
        # Main iteration loop
        total_start_time = time.time()
        
        for iteration in range(start_iteration, args.iterations + 1):
            logger.info(f"Starting iteration {iteration}")
            
            try:
                # Run iteration
                iteration_result = run_iteration(
                    iteration,
                    baseline_result_dir,
                    baseline_metrics,
                    iteration_results[-1] if iteration_results else None,
                    args.config,
                    workflow_config,
                    output_dir
                )
                
                iteration_results.append(iteration_result)
                
                # Update best overall result
                current_value = getattr(iteration_result.best_metrics, args.objective, 0)
                best_value = getattr(best_overall_metrics, args.objective, 0)
                
                if current_value > best_value:
                    best_overall_result_dir = iteration_result.best_result_dir
                    best_overall_parameters = iteration_result.best_parameters
                    best_overall_metrics = iteration_result.best_metrics
                    best_overall_iteration = iteration - 1  # 0-based index
                    logger.info(f"New best result found in iteration {iteration}")
                
                # Save checkpoint
                checkpoint = WorkflowCheckpoint(
                    current_iteration=iteration,
                    max_iterations=args.iterations,
                    objective=args.objective,
                    baseline_result_dir=str(baseline_result_dir) if baseline_result_dir else None,
                    baseline_metrics=asdict(baseline_metrics),
                    iteration_results=iteration_results,
                    best_overall_result_dir=str(best_overall_result_dir) if best_overall_result_dir else None,
                    best_overall_parameters=best_overall_parameters,
                    best_overall_metrics=asdict(best_overall_metrics) if best_overall_metrics else {},
                    best_overall_iteration=best_overall_iteration if 'best_overall_iteration' in locals() else len(iteration_results) - 1,
                    converged=False,
                    convergence_reason=None,
                    total_duration_seconds=time.time() - total_start_time,
                    checkpoint_timestamp=datetime.datetime.now().isoformat()
                )
                
                save_checkpoint(checkpoint, checkpoint_path)
                
                # Check convergence
                converged, reason = check_convergence(iteration_results, args.iterations)
                if converged:
                    logger.info(f"Convergence detected: {reason}")
                    checkpoint.converged = True
                    checkpoint.convergence_reason = reason
                    save_checkpoint(checkpoint, checkpoint_path)
                    break
                
                # Manual review mode
                if not args.auto_adjust_params and iteration < args.iterations:
                    print(f"\nIteration {iteration} completed.")
                    print(f"Best {args.objective}: {current_value:.3f}")
                    print(f"Improvement vs baseline: {iteration_result.improvement_vs_baseline:+.1%}")
                    
                    if iteration_result.loss_analysis_suggestions:
                        print(f"\nSuggestions for next iteration:")
                        for suggestion in iteration_result.loss_analysis_suggestions[:3]:
                            print(f"  - {suggestion}")
                    
                    response = input("\nContinue to next iteration? (y/n): ").lower().strip()
                    if response != 'y':
                        logger.info("User chose to stop optimization")
                        break
                
            except Exception as e:
                logger.error(f"Iteration {iteration} failed: {e}")
                # Continue with next iteration if possible
                continue
        
        # Finalization
        total_duration = time.time() - total_start_time
        logger.info(f"Workflow completed in {total_duration:.1f}s")
        
        # Analyze trajectory
        trajectory_analysis = analyze_improvement_trajectory(iteration_results, args.objective)
        
        # Generate final recommendations
        final_recommendations = generate_final_recommendations(
            iteration_results, 
            checkpoint.convergence_reason or "Workflow completed",
            args.objective
        )
        
        # Build iteration trajectory
        iteration_trajectory = []
        for i, result in enumerate(iteration_results):
            objective_value = getattr(result.best_metrics, args.objective, 0)
            iteration_trajectory.append({
                "iteration": i + 1,
                "objective_value": objective_value,
                "vs_baseline": result.improvement_vs_baseline,
                "vs_previous": result.improvement_vs_previous
            })
        
        # Create final report
        report = WorkflowReport(
            workflow_config=workflow_config,
            checkpoint=checkpoint,
            iteration_trajectory=iteration_trajectory,
            final_recommendations=final_recommendations,
            convergence_analysis=trajectory_analysis
        )
        
        # Generate reports
        logger.info("Generating reports...")
        
        # Console report
        generate_console_report(report)
        
        # Generate charts
        charts = {}
        if iteration_results:
            baseline_value = getattr(baseline_metrics, args.objective, 0)
            charts['trajectory'] = create_iteration_trajectory_chart(iteration_results, args.objective, baseline_value)
            charts['improvement'] = create_improvement_bar_chart(iteration_results)
            charts['convergence'] = create_convergence_analysis_chart(iteration_results, args.objective)
        
        # HTML report
        html_output = output_dir / "workflow_report.html"
        generate_html_report(report, html_output, charts)
        
        # JSON report
        if args.json:
            json_output = output_dir / "workflow_report.json"
            generate_json_report(report, json_output)
        
        # Final summary
        logger.info("="*60)
        logger.info("OPTIMIZATION WORKFLOW COMPLETED")
        logger.info("="*60)
        logger.info(f"Total iterations: {len(iteration_results)}")
        logger.info(f"Total duration: {total_duration:.1f}s")
        logger.info(f"Best {args.objective}: {getattr(best_overall_metrics, args.objective, 0):.3f}")
        logger.info(f"Improvement vs baseline: {((getattr(best_overall_metrics, args.objective, 0) - getattr(baseline_metrics, args.objective, 0)) / abs(getattr(baseline_metrics, args.objective, 0)) if getattr(baseline_metrics, args.objective, 0) != 0 else 0):+.1%}")
        logger.info(f"Converged: {checkpoint.converged}")
        logger.info(f"HTML report: {html_output}")
        if args.json:
            logger.info(f"JSON report: {json_output}")
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("Workflow interrupted by user")
        return 3
    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
