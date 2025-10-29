#!/usr/bin/env python3
"""
Phase 6 Results Validation Script

This script validates Phase 6 refinement optimization results including Pareto frontier quality.
It performs comprehensive validation of parameter ranges, Sharpe ratios, completion rates, 
Pareto frontier quality, and top 5 parameter set exports.
"""

import pandas as pd
import json
import pathlib
import sys
import argparse
import logging
import numpy as np
from typing import Dict, List, Any, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
PHASE5_BEST_SHARPE = 0.4779
EXPECTED_COMBINATIONS_MIN = 150
EXPECTED_COMBINATIONS_MAX = 600
MIN_SUCCESS_RATE = 0.95
MIN_PARETO_FRONTIER_SIZE = 5

def validate_parameter_ranges(df: pd.DataFrame, phase5_best_params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate parameter ranges are within ±10% of Phase 5 best values."""
    validation_results = {
        'valid': True,
        'issues': [],
        'parameter_validation': {}
    }
    
    # Parameters that should be refined (with ±10% tolerance)
    refined_params = {
        'trailing_stop_distance_pips': phase5_best_params.get('trailing_stop_distance_pips', 12),
        'stop_loss_pips': phase5_best_params.get('stop_loss_pips', 35),
        'take_profit_pips': phase5_best_params.get('take_profit_pips', 50),
        'stoch_period_k': phase5_best_params.get('stoch_period_k', 18)
    }
    
    # Parameters that should be fixed at Phase 5 best
    fixed_params = {
        'fast_period': phase5_best_params.get('fast_period', 42),
        'slow_period': phase5_best_params.get('slow_period', 270),
        'crossover_threshold_pips': phase5_best_params.get('crossover_threshold_pips', 0.35),
        'dmi_period': phase5_best_params.get('dmi_period', 10),
        'stoch_period_d': phase5_best_params.get('stoch_period_d', 3),
        'stoch_bullish_threshold': phase5_best_params.get('stoch_bullish_threshold', 30),
        'stoch_bearish_threshold': phase5_best_params.get('stoch_bearish_threshold', 65)
    }
    
    # Check refined parameters
    for param, best_value in refined_params.items():
        if param in df.columns:
            values = df[param].dropna()
            if len(values) > 0:
                min_val = values.min()
                max_val = values.max()
                tolerance = best_value * 0.1  # ±10%
                expected_min = best_value - tolerance
                expected_max = best_value + tolerance
                
                if min_val < expected_min or max_val > expected_max:
                    validation_results['issues'].append(
                        f"Parameter {param} values ({min_val}-{max_val}) outside ±10% of Phase 5 best ({expected_min}-{expected_max})"
                    )
                    validation_results['valid'] = False
                
                validation_results['parameter_validation'][param] = {
                    'range': f"{min_val}-{max_val}",
                    'expected': f"{expected_min}-{expected_max}",
                    'valid': min_val >= expected_min and max_val <= expected_max
                }
    
    # Check fixed parameters
    for param, expected_value in fixed_params.items():
        if param in df.columns:
            values = df[param].dropna()
            if len(values) > 0:
                unique_values = values.unique()
                if len(unique_values) > 1 or (len(unique_values) == 1 and unique_values[0] != expected_value):
                    validation_results['issues'].append(
                        f"Parameter {param} should be fixed at {expected_value} but has values: {unique_values}"
                    )
                    validation_results['valid'] = False
                
                validation_results['parameter_validation'][param] = {
                    'values': unique_values.tolist(),
                    'expected': expected_value,
                    'valid': len(unique_values) == 1 and unique_values[0] == expected_value
                }
    
    return validation_results

def validate_sharpe_ratios(df: pd.DataFrame) -> Dict[str, Any]:
    """Validate Sharpe ratio quality and distribution."""
    validation_results = {
        'valid': True,
        'issues': [],
        'sharpe_stats': {}
    }
    
    if 'sharpe_ratio' not in df.columns:
        validation_results['issues'].append("Sharpe ratio column not found")
        validation_results['valid'] = False
        return validation_results
    
    sharpe_values = df['sharpe_ratio'].dropna()
    
    if len(sharpe_values) == 0:
        validation_results['issues'].append("No valid Sharpe ratio values found")
        validation_results['valid'] = False
        return validation_results
    
    # Check for reasonable Sharpe ratios
    max_sharpe = sharpe_values.max()
    min_sharpe = sharpe_values.min()
    mean_sharpe = sharpe_values.mean()
    
    validation_results['sharpe_stats'] = {
        'max': max_sharpe,
        'min': min_sharpe,
        'mean': mean_sharpe,
        'count': len(sharpe_values)
    }
    
    # Check for reasonable range
    if max_sharpe > 5.0:
        validation_results['issues'].append(f"Maximum Sharpe ratio ({max_sharpe:.4f}) seems unreasonably high")
        validation_results['valid'] = False
    
    if min_sharpe < -2.0:
        validation_results['issues'].append(f"Minimum Sharpe ratio ({min_sharpe:.4f}) seems unreasonably low")
        validation_results['valid'] = False
    
    # Check for NaN or infinite values
    nan_count = df['sharpe_ratio'].isna().sum()
    if nan_count > 0:
        validation_results['issues'].append(f"Found {nan_count} NaN Sharpe ratio values")
        validation_results['valid'] = False
    
    return validation_results

def validate_output_directories(df: pd.DataFrame) -> Dict[str, Any]:
    """Validate output directories exist and are accessible."""
    validation_results = {
        'valid': True,
        'issues': [],
        'directory_validation': {}
    }
    
    if 'output_directory' not in df.columns:
        validation_results['issues'].append("Output directory column not found")
        validation_results['valid'] = False
        return validation_results
    
    output_dirs = df['output_directory'].dropna().unique()
    
    for output_dir in output_dirs:
        if not pathlib.Path(output_dir).exists():
            validation_results['issues'].append(f"Output directory does not exist: {output_dir}")
            validation_results['valid'] = False
        else:
            validation_results['directory_validation'][output_dir] = True
    
    return validation_results

def validate_completion_rate(df: pd.DataFrame) -> Dict[str, Any]:
    """Validate completion rate meets minimum threshold."""
    validation_results = {
        'valid': True,
        'issues': [],
        'completion_stats': {}
    }
    
    total_runs = len(df)
    if 'status' in df.columns:
        completed_runs = len(df[df['status'] == 'completed'])
    else:
        # Assume all runs are completed if no status column
        completed_runs = total_runs
    
    success_rate = completed_runs / total_runs if total_runs > 0 else 0
    
    validation_results['completion_stats'] = {
        'total_runs': total_runs,
        'completed_runs': completed_runs,
        'success_rate': success_rate
    }
    
    if success_rate < MIN_SUCCESS_RATE:
        validation_results['issues'].append(
            f"Success rate ({success_rate:.1%}) below minimum threshold ({MIN_SUCCESS_RATE:.1%})"
        )
        validation_results['valid'] = False
    
    return validation_results

def compare_with_phase5(df: pd.DataFrame, phase5_sharpe: float = PHASE5_BEST_SHARPE) -> Dict[str, Any]:
    """Compare Phase 6 results with Phase 5 baseline."""
    validation_results = {
        'valid': True,
        'issues': [],
        'comparison_stats': {}
    }
    
    if 'sharpe_ratio' not in df.columns:
        validation_results['issues'].append("Sharpe ratio column not found for comparison")
        validation_results['valid'] = False
        return validation_results
    
    phase6_best_sharpe = df['sharpe_ratio'].max()
    improvement = phase6_best_sharpe - phase5_sharpe
    improvement_pct = (improvement / phase5_sharpe) * 100 if phase5_sharpe != 0 else 0
    
    validation_results['comparison_stats'] = {
        'phase5_sharpe': phase5_sharpe,
        'phase6_best_sharpe': phase6_best_sharpe,
        'improvement': improvement,
        'improvement_pct': improvement_pct
    }
    
    # Check if Phase 6 maintains or improves Phase 5 performance
    if phase6_best_sharpe < phase5_sharpe * 0.95:  # Allow 5% tolerance
        validation_results['issues'].append(
            f"Phase 6 best Sharpe ({phase6_best_sharpe:.4f}) significantly below Phase 5 baseline ({phase5_sharpe:.4f})"
        )
        validation_results['valid'] = False
    
    return validation_results

def validate_pareto_frontier(pareto_json: str, min_size: int = MIN_PARETO_FRONTIER_SIZE) -> Dict[str, Any]:
    """Validate Pareto frontier quality and structure."""
    validation_results = {
        'valid': True,
        'issues': [],
        'frontier_stats': {}
    }
    
    try:
        with open(pareto_json, 'r') as f:
            pareto_data = json.load(f)
    except Exception as e:
        validation_results['issues'].append(f"Could not load Pareto frontier JSON: {e}")
        validation_results['valid'] = False
        return validation_results
    
    # Check structure
    if 'frontier' not in pareto_data or 'objectives' not in pareto_data:
        validation_results['issues'].append("Invalid Pareto frontier structure")
        validation_results['valid'] = False
        return validation_results
    
    frontier = pareto_data['frontier']
    objectives = pareto_data['objectives']
    
    # Check frontier size
    frontier_size = len(frontier)
    validation_results['frontier_stats']['size'] = frontier_size
    
    if frontier_size < min_size:
        validation_results['issues'].append(
            f"Pareto frontier size ({frontier_size}) below minimum ({min_size})"
        )
        validation_results['valid'] = False
    
    # Check objectives
    expected_objectives = ['sharpe_ratio', 'total_pnl', 'max_drawdown']
    if not all(obj in objectives for obj in expected_objectives):
        validation_results['issues'].append(
            f"Missing expected objectives. Found: {objectives}, Expected: {expected_objectives}"
        )
        validation_results['valid'] = False
    
    # Check diversity metrics
    if frontier_size > 0:
        sharpe_values = [point.get('sharpe_ratio', 0) for point in frontier]
        pnl_values = [point.get('total_pnl', 0) for point in frontier]
        drawdown_values = [point.get('max_drawdown', 0) for point in frontier]
        
        validation_results['frontier_stats']['diversity'] = {
            'sharpe_range': f"{min(sharpe_values):.4f} - {max(sharpe_values):.4f}",
            'pnl_range': f"${min(pnl_values):,.0f} - ${max(pnl_values):,.0f}",
            'drawdown_range': f"${min(drawdown_values):,.0f} - ${max(drawdown_values):,.0f}"
        }
        
        # Check for reasonable diversity
        sharpe_span = max(sharpe_values) - min(sharpe_values)
        if sharpe_span < 0.01:  # Less than 0.01 Sharpe difference
            validation_results['issues'].append("Pareto frontier shows very low diversity in Sharpe ratios")
            validation_results['valid'] = False
    
    return validation_results

def validate_top5_export(top5_json: str) -> Dict[str, Any]:
    """Validate top 5 parameter sets export for Phase 7."""
    validation_results = {
        'valid': True,
        'issues': [],
        'export_stats': {}
    }
    
    try:
        with open(top5_json, 'r') as f:
            top5_data = json.load(f)
    except Exception as e:
        validation_results['issues'].append(f"Could not load top 5 JSON: {e}")
        validation_results['valid'] = False
        return validation_results
    
    # Check structure
    if 'parameter_sets' not in top5_data:
        validation_results['issues'].append("Missing 'parameter_sets' in top 5 JSON")
        validation_results['valid'] = False
        return validation_results
    
    parameter_sets = top5_data['parameter_sets']
    validation_results['export_stats']['count'] = len(parameter_sets)
    
    # Check exactly 5 parameter sets
    if len(parameter_sets) != 5:
        validation_results['issues'].append(
            f"Expected exactly 5 parameter sets, found {len(parameter_sets)}"
        )
        validation_results['valid'] = False
    
    # Check each parameter set
    required_fields = ['id', 'name', 'parameters', 'expected_performance', 'trade_offs']
    required_params = [
        'fast_period', 'slow_period', 'crossover_threshold_pips',
        'stop_loss_pips', 'take_profit_pips', 'trailing_stop_distance_pips',
        'dmi_enabled', 'dmi_period', 'stoch_period_k', 'stoch_period_d',
        'stoch_bullish_threshold', 'stoch_bearish_threshold'
    ]
    
    for i, param_set in enumerate(parameter_sets):
        # Check required fields
        for field in required_fields:
            if field not in param_set:
                validation_results['issues'].append(
                    f"Parameter set {i+1} missing required field: {field}"
                )
                validation_results['valid'] = False
        
        # Check parameters
        if 'parameters' in param_set:
            for param in required_params:
                if param not in param_set['parameters']:
                    validation_results['issues'].append(
                        f"Parameter set {i+1} missing required parameter: {param}"
                    )
                    validation_results['valid'] = False
        
        # Check performance metrics
        if 'expected_performance' in param_set:
            perf = param_set['expected_performance']
            for metric in ['sharpe_ratio', 'total_pnl', 'max_drawdown']:
                if metric not in perf:
                    validation_results['issues'].append(
                        f"Parameter set {i+1} missing performance metric: {metric}"
                    )
                    validation_results['valid'] = False
    
    # Check diversity (not all parameter sets should be identical)
    if len(parameter_sets) > 1:
        first_params = parameter_sets[0].get('parameters', {})
        identical_count = 0
        
        for param_set in parameter_sets[1:]:
            if param_set.get('parameters', {}) == first_params:
                identical_count += 1
        
        if identical_count == len(parameter_sets) - 1:
            validation_results['issues'].append("All parameter sets are identical - no diversity")
            validation_results['valid'] = False
    
    return validation_results

def check_parameter_stability(df: pd.DataFrame) -> Dict[str, Any]:
    """Check parameter stability in top 10 results."""
    validation_results = {
        'valid': True,
        'issues': [],
        'stability_stats': {}
    }
    
    # Get top 10 results
    top_10 = df.nlargest(10, 'sharpe_ratio')
    
    # Check parameter stability
    numeric_params = [
        'fast_period', 'slow_period', 'crossover_threshold_pips',
        'stop_loss_pips', 'take_profit_pips', 'trailing_stop_distance_pips',
        'dmi_period', 'stoch_period_k', 'stoch_period_d',
        'stoch_bullish_threshold', 'stoch_bearish_threshold'
    ]
    
    for param in numeric_params:
        if param in top_10.columns:
            values = top_10[param].dropna()
            if len(values) > 0:
                std_dev = values.std()
                mean_val = values.mean()
                cv = std_dev / abs(mean_val) if mean_val != 0 else float('inf')
                
                validation_results['stability_stats'][param] = {
                    'std_dev': std_dev,
                    'coefficient_of_variation': cv,
                    'stability': 'high' if cv < 0.1 else 'medium' if cv < 0.3 else 'low'
                }
                
                # Flag highly unstable parameters
                if cv > 0.5:
                    validation_results['issues'].append(
                        f"Parameter {param} shows high instability (CV={cv:.3f}) in top 10 results"
                    )
                    validation_results['valid'] = False
    
    return validation_results

def main():
    """Main validation function."""
    parser = argparse.ArgumentParser(description='Validate Phase 6 optimization results')
    parser.add_argument('--csv', default='optimization/results/phase6_refinement_results.csv',
                       help='Path to Phase 6 results CSV')
    parser.add_argument('--phase5-sharpe', type=float, default=PHASE5_BEST_SHARPE,
                       help='Phase 5 baseline Sharpe ratio')
    parser.add_argument('--pareto-json', 
                       default='optimization/results/phase6_refinement_results_pareto_frontier.json',
                       help='Path to Pareto frontier JSON')
    parser.add_argument('--top5-json', 
                       default='optimization/results/phase6_top_5_parameters.json',
                       help='Path to top 5 parameters JSON')
    parser.add_argument('--strict', action='store_true',
                       help='Fail on warnings')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("Starting Phase 6 results validation...")
    
    # Load results
    try:
        df = pd.read_csv(args.csv)
        logger.info(f"Loaded {len(df)} results from {args.csv}")
    except Exception as e:
        logger.error(f"Could not load results CSV: {e}")
        sys.exit(3)
    
    # Load Phase 5 baseline parameters
    phase5_best_params = {
        'fast_period': 42,
        'slow_period': 270,
        'crossover_threshold_pips': 0.35,
        'stop_loss_pips': 35,
        'take_profit_pips': 50,
        'trailing_stop_distance_pips': 12,
        'dmi_period': 10,
        'stoch_period_k': 18,
        'stoch_period_d': 3,
        'stoch_bullish_threshold': 30,
        'stoch_bearish_threshold': 65
    }
    
    # Run all validations
    validations = {}
    
    logger.info("Validating parameter ranges...")
    validations['parameter_ranges'] = validate_parameter_ranges(df, phase5_best_params)
    
    logger.info("Validating Sharpe ratios...")
    validations['sharpe_ratios'] = validate_sharpe_ratios(df)
    
    logger.info("Validating output directories...")
    validations['output_directories'] = validate_output_directories(df)
    
    logger.info("Validating completion rate...")
    validations['completion_rate'] = validate_completion_rate(df)
    
    logger.info("Comparing with Phase 5...")
    validations['phase5_comparison'] = compare_with_phase5(df, args.phase5_sharpe)
    
    logger.info("Validating Pareto frontier...")
    if pathlib.Path(args.pareto_json).exists():
        validations['pareto_frontier'] = validate_pareto_frontier(args.pareto_json)
    else:
        logger.warning(f"Pareto frontier JSON not found: {args.pareto_json}")
        validations['pareto_frontier'] = {'valid': False, 'issues': ['Pareto frontier JSON not found']}
    
    logger.info("Validating top 5 export...")
    if pathlib.Path(args.top5_json).exists():
        validations['top5_export'] = validate_top5_export(args.top5_json)
    else:
        logger.warning(f"Top 5 JSON not found: {args.top5_json}")
        validations['top5_export'] = {'valid': False, 'issues': ['Top 5 JSON not found']}
    
    logger.info("Checking parameter stability...")
    validations['parameter_stability'] = check_parameter_stability(df)
    
    # Generate validation report
    all_valid = all(v.get('valid', False) for v in validations.values())
    total_issues = sum(len(v.get('issues', [])) for v in validations.values())
    
    # Print validation summary
    print("\n" + "="*60)
    print("PHASE 6 VALIDATION RESULTS")
    print("="*60)
    
    for validation_name, results in validations.items():
        status = "✓ PASS" if results.get('valid', False) else "✗ FAIL"
        print(f"{validation_name.replace('_', ' ').title()}: {status}")
        
        if results.get('issues'):
            for issue in results['issues']:
                print(f"  - {issue}")
    
    print(f"\nOverall Status: {'✓ ALL VALIDATIONS PASSED' if all_valid else '✗ SOME VALIDATIONS FAILED'}")
    print(f"Total Issues: {total_issues}")
    
    # Save detailed validation report
    validation_report = {
        'timestamp': pd.Timestamp.now().isoformat(),
        'overall_valid': all_valid,
        'total_issues': total_issues,
        'validations': validations
    }
    
    report_path = 'optimization/results/phase6_validation_report.json'
    with open(report_path, 'w') as f:
        json.dump(validation_report, f, indent=2, default=str)
    
    logger.info(f"Detailed validation report saved to {report_path}")
    
    # Exit codes
    if not all_valid:
        if total_issues > 5:  # Critical failures
            sys.exit(1)
        else:  # Warnings
            sys.exit(2)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
