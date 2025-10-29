#!/usr/bin/env python3
"""
Phase 3 Results Validation Script

Purpose: Validate Phase 3 optimization results for data quality, parameter ranges, 
and performance metrics.

Usage:
    python optimization/scripts/validate_phase3_results.py
    python optimization/scripts/validate_phase3_results.py --phase2-sharpe 0.350
    python optimization/scripts/validate_phase3_results.py --strict
"""

import pandas as pd
import json
import sys
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Any
import re

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def validate_parameter_ranges(df: pd.DataFrame) -> List[str]:
    """
    Validate that all parameters are within expected Phase 3 ranges.
    
    Args:
        df: DataFrame with Phase 3 results
        
    Returns:
        List of validation errors (empty if all pass)
    """
    errors = []
    
    # Expected parameter ranges
    expected_fast = [36, 38, 40, 42, 44]
    expected_slow = [230, 240, 250, 260, 270]
    expected_threshold = [0.35, 0.425, 0.5, 0.575, 0.65]
    
    # Check fast_period
    if 'fast_period' in df.columns:
        invalid_fast = df[~df['fast_period'].isin(expected_fast)]
        if not invalid_fast.empty:
            errors.append(f"Found {len(invalid_fast)} rows with invalid fast_period values: {invalid_fast['fast_period'].unique()}")
    else:
        errors.append("fast_period column not found")
    
    # Check slow_period
    if 'slow_period' in df.columns:
        invalid_slow = df[~df['slow_period'].isin(expected_slow)]
        if not invalid_slow.empty:
            errors.append(f"Found {len(invalid_slow)} rows with invalid slow_period values: {invalid_slow['slow_period'].unique()}")
    else:
        errors.append("slow_period column not found")
    
    # Check crossover_threshold_pips
    if 'crossover_threshold_pips' in df.columns:
        invalid_threshold = df[~df['crossover_threshold_pips'].isin(expected_threshold)]
        if not invalid_threshold.empty:
            errors.append(f"Found {len(invalid_threshold)} rows with invalid crossover_threshold_pips values: {invalid_threshold['crossover_threshold_pips'].unique()}")
    else:
        errors.append("crossover_threshold_pips column not found")
    
    return errors

def validate_sharpe_ratios(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate Sharpe ratio quality and distribution.
    
    Args:
        df: DataFrame with Phase 3 results
        
    Returns:
        Dictionary with validation results
    """
    results = {}
    
    if 'sharpe_ratio' not in df.columns:
        results['error'] = "sharpe_ratio column not found"
        return results
    
    sharpe_ratios = df['sharpe_ratio'].dropna()
    
    # Check for zero Sharpe ratios (bug fix verification)
    zero_sharpe_count = (sharpe_ratios == 0.0).sum()
    results['zero_sharpe_count'] = int(zero_sharpe_count)
    results['zero_sharpe_percentage'] = float(zero_sharpe_count / len(sharpe_ratios) * 100) if len(sharpe_ratios) > 0 else 0
    
    # Check for reasonable range
    min_sharpe = float(sharpe_ratios.min())
    max_sharpe = float(sharpe_ratios.max())
    results['min_sharpe'] = min_sharpe
    results['max_sharpe'] = max_sharpe
    
    # Check for extreme values
    extreme_negative = (sharpe_ratios < -1.0).sum()
    extreme_positive = (sharpe_ratios > 5.0).sum()
    results['extreme_negative_count'] = int(extreme_negative)
    results['extreme_positive_count'] = int(extreme_positive)
    
    # Calculate positive Sharpe ratio percentage
    positive_count = (sharpe_ratios > 0).sum()
    results['positive_sharpe_count'] = int(positive_count)
    results['positive_sharpe_percentage'] = float(positive_count / len(sharpe_ratios) * 100) if len(sharpe_ratios) > 0 else 0
    
    # Validation flags
    results['has_zero_sharpe'] = zero_sharpe_count > 0
    results['has_extreme_values'] = extreme_negative > 0 or extreme_positive > 0
    results['all_positive'] = positive_count == len(sharpe_ratios)
    
    return results

def validate_output_directories(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate output directory format and uniqueness.
    
    Args:
        df: DataFrame with Phase 3 results
        
    Returns:
        Dictionary with validation results
    """
    results = {}
    
    # Check for either output_dir or output_directory column
    output_col = None
    if 'output_directory' in df.columns:
        output_col = 'output_directory'
    elif 'output_dir' in df.columns:
        output_col = 'output_dir'
    
    if output_col is None:
        results['error'] = "Neither output_dir nor output_directory column found"
        return results
    
    output_dirs = df[output_col].dropna()
    results['total_directories'] = len(output_dirs)
    
    # Check for microsecond precision pattern: YYYYMMDD_HHMMSS_microseconds
    microsecond_pattern = re.compile(r'.*_\d{8}_\d{6}_\d{6}$')
    microsecond_dirs = output_dirs[output_dirs.str.match(microsecond_pattern, na=False)]
    results['microsecond_precision_count'] = len(microsecond_dirs)
    results['microsecond_precision_percentage'] = float(len(microsecond_dirs) / len(output_dirs) * 100) if len(output_dirs) > 0 else 0
    
    # Check for duplicates
    duplicate_count = len(output_dirs) - len(output_dirs.unique())
    results['duplicate_count'] = duplicate_count
    results['has_duplicates'] = duplicate_count > 0
    
    # Validation flags
    results['all_microsecond_precision'] = len(microsecond_dirs) == len(output_dirs)
    results['no_duplicates'] = duplicate_count == 0
    
    return results

def validate_completion_rate(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate completion rate and identify failure patterns.
    
    Args:
        df: DataFrame with Phase 3 results
        
    Returns:
        Dictionary with completion statistics
    """
    results = {}
    
    total_runs = len(df)
    results['total_runs'] = total_runs
    
    # Check for status column if available
    if 'status' in df.columns:
        status_counts = df['status'].value_counts()
        results['status_counts'] = status_counts.to_dict()
        
        completed = status_counts.get('completed', 0)
        failed = status_counts.get('failed', 0)
        timeout = status_counts.get('timeout', 0)
        
        results['completed_count'] = int(completed)
        results['failed_count'] = int(failed)
        results['timeout_count'] = int(timeout)
        results['success_rate'] = float(completed / total_runs * 100) if total_runs > 0 else 0
    else:
        # Assume all runs completed if no status column
        results['completed_count'] = total_runs
        results['failed_count'] = 0
        results['timeout_count'] = 0
        results['success_rate'] = 100.0
    
    # Check for systematic failures
    results['has_failures'] = results['failed_count'] > 0
    results['has_timeouts'] = results['timeout_count'] > 0
    results['low_success_rate'] = results['success_rate'] < 90.0
    
    return results

def compare_with_phase2(df: pd.DataFrame, phase2_best_sharpe: float = 0.344) -> Dict[str, Any]:
    """
    Compare Phase 3 results with Phase 2 baseline.
    
    Args:
        df: DataFrame with Phase 3 results
        phase2_best_sharpe: Phase 2 best Sharpe ratio for comparison
        
    Returns:
        Dictionary with comparison results
    """
    results = {}
    
    if 'sharpe_ratio' not in df.columns:
        results['error'] = "sharpe_ratio column not found"
        return results
    
    sharpe_ratios = df['sharpe_ratio'].dropna()
    if len(sharpe_ratios) == 0:
        results['error'] = "No valid Sharpe ratios found"
        return results
    
    phase3_best = float(sharpe_ratios.max())
    results['phase3_best_sharpe'] = phase3_best
    results['phase2_best_sharpe'] = phase2_best_sharpe
    
    # Calculate improvement
    improvement = phase3_best - phase2_best_sharpe
    improvement_percentage = (improvement / phase2_best_sharpe) * 100 if phase2_best_sharpe != 0 else 0
    
    results['improvement'] = improvement
    results['improvement_percentage'] = improvement_percentage
    
    # Validation flags
    results['improved'] = improvement > 0
    results['within_5_percent'] = abs(improvement_percentage) <= 5.0
    results['significantly_improved'] = improvement_percentage > 10.0
    results['significantly_degraded'] = improvement_percentage < -10.0
    
    return results

def check_parameter_stability(df: pd.DataFrame, top_n: int = 10) -> Dict[str, Any]:
    """
    Check parameter stability in top results.
    
    Args:
        df: DataFrame with Phase 3 results
        top_n: Number of top results to analyze
        
    Returns:
        Dictionary with stability analysis
    """
    results = {}
    
    if 'sharpe_ratio' not in df.columns:
        results['error'] = "sharpe_ratio column not found"
        return results
    
    # Get top N results
    top_results = df.nlargest(top_n, 'sharpe_ratio')
    results['top_n_analyzed'] = len(top_results)
    
    # Calculate parameter statistics for top results
    param_stats = {}
    for param in ['fast_period', 'slow_period', 'crossover_threshold_pips']:
        if param in top_results.columns:
            values = top_results[param].dropna()
            param_stats[param] = {
                'mean': float(values.mean()),
                'std': float(values.std()),
                'min': float(values.min()),
                'max': float(values.max()),
                'unique_count': len(values.unique())
            }
    
    results['parameter_stats'] = param_stats
    
    # Check for clustering (low standard deviation indicates clustering)
    clustering_scores = {}
    for param, stats in param_stats.items():
        # Normalize std by mean to get coefficient of variation
        cv = stats['std'] / stats['mean'] if stats['mean'] != 0 else float('inf')
        clustering_scores[param] = cv
        results[f'{param}_clustering_score'] = cv
    
    results['clustering_scores'] = clustering_scores
    
    # Check if best parameters are at range boundaries (warning sign)
    boundary_warnings = {}
    expected_ranges = {
        'fast_period': [36, 44],
        'slow_period': [230, 270],
        'crossover_threshold_pips': [0.35, 0.65]
    }
    
    for param, (min_val, max_val) in expected_ranges.items():
        if param in top_results.columns:
            best_value = top_results[param].iloc[0]  # Best result
            at_min_boundary = best_value == min_val
            at_max_boundary = best_value == max_val
            boundary_warnings[param] = {
                'at_min_boundary': at_min_boundary,
                'at_max_boundary': at_max_boundary,
                'at_any_boundary': at_min_boundary or at_max_boundary
            }
    
    results['boundary_warnings'] = boundary_warnings
    results['any_boundary_warnings'] = any(w['at_any_boundary'] for w in boundary_warnings.values())
    
    return results

def main():
    """Main validation function."""
    parser = argparse.ArgumentParser(description='Validate Phase 3 optimization results')
    parser.add_argument('--csv', default='optimization/results/phase3_fine_grid_results.csv',
                       help='Path to Phase 3 results CSV file')
    parser.add_argument('--phase2-sharpe', type=float, default=0.344,
                       help='Phase 2 best Sharpe ratio for comparison')
    parser.add_argument('--strict', action='store_true',
                       help='Fail on warnings (exit code 2 becomes 1)')
    parser.add_argument('--json-output', default='optimization/results/phase3_validation_report.json',
                       help='Path to save validation report JSON')
    
    args = parser.parse_args()
    
    # Check if CSV file exists
    csv_path = Path(args.csv)
    if not csv_path.exists():
        logger.error(f"CSV file not found: {csv_path}")
        sys.exit(1)
    
    # Load CSV file
    try:
        df = pd.read_csv(csv_path)
        logger.info(f"Loaded {len(df)} rows from {csv_path}")
    except Exception as e:
        logger.error(f"Failed to load CSV file: {e}")
        sys.exit(1)
    
    # Run all validations
    logger.info("Running validations...")
    
    validation_results = {
        'timestamp': pd.Timestamp.now().isoformat(),
        'csv_file': str(csv_path),
        'total_rows': len(df),
        'phase2_baseline_sharpe': args.phase2_sharpe
    }
    
    # Parameter range validation
    param_errors = validate_parameter_ranges(df)
    validation_results['parameter_validation'] = {
        'errors': param_errors,
        'passed': len(param_errors) == 0
    }
    
    # Sharpe ratio validation
    sharpe_results = validate_sharpe_ratios(df)
    validation_results['sharpe_validation'] = sharpe_results
    
    # Output directory validation
    output_results = validate_output_directories(df)
    validation_results['output_directory_validation'] = output_results
    
    # Completion rate validation
    completion_results = validate_completion_rate(df)
    validation_results['completion_validation'] = completion_results
    
    # Phase 2 comparison
    phase2_comparison = compare_with_phase2(df, args.phase2_sharpe)
    validation_results['phase2_comparison'] = phase2_comparison
    
    # Parameter stability
    stability_results = check_parameter_stability(df)
    validation_results['parameter_stability'] = stability_results
    
    # Determine overall validation status
    critical_failures = []
    warnings = []
    
    # Check for critical failures
    if param_errors:
        critical_failures.extend(param_errors)
    
    if sharpe_results.get('has_zero_sharpe', False):
        critical_failures.append("Found zero Sharpe ratios (bug fix not working)")
    
    if output_results.get('has_duplicates', False):
        critical_failures.append("Found duplicate output directories")
    
    if completion_results.get('low_success_rate', False):
        warnings.append(f"Low success rate: {completion_results['success_rate']:.1f}%")
    
    if phase2_comparison.get('significantly_degraded', False):
        warnings.append(f"Significant degradation vs Phase 2: {phase2_comparison['improvement_percentage']:.1f}%")
    
    if stability_results.get('any_boundary_warnings', False):
        warnings.append("Best parameters at range boundaries (may need wider search)")
    
    # Print validation summary
    print("\n=== Phase 3 Results Validation Summary ===")
    print(f"Total runs: {len(df)}")
    print(f"Success rate: {completion_results.get('success_rate', 0):.1f}%")
    
    if 'sharpe_ratio' in df.columns:
        best_sharpe = df['sharpe_ratio'].max()
        print(f"Best Sharpe ratio: {best_sharpe:.4f}")
        if 'phase3_best_sharpe' in phase2_comparison:
            improvement = phase2_comparison['improvement_percentage']
            print(f"vs Phase 2: {improvement:+.1f}%")
    
    print(f"\nParameter validation: {'PASS' if not param_errors else 'FAIL'}")
    print(f"Sharpe ratio quality: {'PASS' if not sharpe_results.get('has_zero_sharpe', False) else 'FAIL'}")
    print(f"Output directories: {'PASS' if not output_results.get('has_duplicates', False) else 'FAIL'}")
    
    if critical_failures:
        print(f"\n❌ CRITICAL FAILURES ({len(critical_failures)}):")
        for failure in critical_failures:
            print(f"  - {failure}")
    
    if warnings:
        print(f"\n⚠️  WARNINGS ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")
    
    if not critical_failures and not warnings:
        print("\n✅ All validations passed!")
    
    # Save validation report
    try:
        with open(args.json_output, 'w') as f:
            json.dump(validation_results, f, indent=2)
        logger.info(f"Validation report saved to {args.json_output}")
    except Exception as e:
        logger.warning(f"Failed to save validation report: {e}")
    
    # Determine exit code
    if critical_failures:
        exit_code = 1
    elif warnings and args.strict:
        exit_code = 1
    elif warnings:
        exit_code = 2
    else:
        exit_code = 0
    
    print(f"\nValidation completed with exit code: {exit_code}")
    sys.exit(exit_code)

if __name__ == '__main__':
    main()
