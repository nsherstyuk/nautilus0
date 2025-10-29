#!/usr/bin/env python3
"""
Phase 5 Filter Optimization Results Validation Script
=====================================================

This script validates Phase 5 filter optimization results for data quality,
parameter ranges, and performance improvements.

Purpose: Verify Phase 5 results are correct, complete, and show meaningful 
         improvements before proceeding to Phase 6 parameter refinement.

Usage:
    python optimization/scripts/validate_phase5_results.py
    python optimization/scripts/validate_phase5_results.py --phase4-sharpe 0.428
    python optimization/scripts/validate_phase5_results.py --strict
    python optimization/scripts/validate_phase5_results.py --csv results.csv --json-output validation.json --verbose

Exit codes:
    0: All validations passed
    1: Critical validation failures (wrong parameter ranges, all zero Sharpe ratios, <90% success rate)
    2: Warning-level issues (low success rate 90-95%, no improvement over Phase 4, high parameter instability)
    3: File not found or parsing errors
"""

import pandas as pd
import json
import pathlib
import sys
import argparse
import logging
from typing import Dict, List, Tuple, Any
import numpy as np

# Constants
PHASE3_BEST_SHARPE = 0.272  # Phase 3 baseline
PHASE4_BEST_SHARPE = 0.428  # Phase 4 baseline
EXPECTED_COMBINATIONS_FULL = 2400
EXPECTED_COMBINATIONS_REDUCED = 108
MIN_SUCCESS_RATE = 0.95  # 95% completion threshold

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def validate_parameter_ranges(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate that all parameters are within expected ranges.
    
    Args:
        df: DataFrame containing Phase 5 results
        
    Returns:
        Dictionary with validation results
    """
    logger.info("Validating parameter ranges...")
    
    errors = []
    warnings = []
    
    # Check DMI parameters
    if 'dmi_enabled' in df.columns:
        valid_dmi_enabled = df['dmi_enabled'].isin([True, False])
        if not valid_dmi_enabled.all():
            invalid_dmi = df[~valid_dmi_enabled]['dmi_enabled'].unique()
            errors.append(f"Invalid dmi_enabled values: {invalid_dmi}")
    else:
        errors.append("dmi_enabled column missing")
    
    if 'dmi_period' in df.columns:
        valid_dmi_period = df['dmi_period'].isin([10, 12, 14, 16, 18])
        if not valid_dmi_period.all():
            invalid_dmi_period = df[~valid_dmi_period]['dmi_period'].unique()
            errors.append(f"Invalid dmi_period values: {invalid_dmi_period}")
    else:
        errors.append("dmi_period column missing")
    
    # Check Stochastic parameters
    if 'stoch_period_k' in df.columns:
        valid_stoch_k = df['stoch_period_k'].isin([10, 12, 14, 16, 18])
        if not valid_stoch_k.all():
            invalid_stoch_k = df[~valid_stoch_k]['stoch_period_k'].unique()
            errors.append(f"Invalid stoch_period_k values: {invalid_stoch_k}")
    else:
        errors.append("stoch_period_k column missing")
    
    if 'stoch_period_d' in df.columns:
        valid_stoch_d = df['stoch_period_d'].isin([3, 5, 7])
        if not valid_stoch_d.all():
            invalid_stoch_d = df[~valid_stoch_d]['stoch_period_d'].unique()
            errors.append(f"Invalid stoch_period_d values: {invalid_stoch_d}")
    else:
        errors.append("stoch_period_d column missing")
    
    if 'stoch_bullish_threshold' in df.columns:
        valid_bullish = df['stoch_bullish_threshold'].isin([20, 25, 30, 35])
        if not valid_bullish.all():
            invalid_bullish = df[~valid_bullish]['stoch_bullish_threshold'].unique()
            errors.append(f"Invalid stoch_bullish_threshold values: {invalid_bullish}")
    else:
        errors.append("stoch_bullish_threshold column missing")
    
    if 'stoch_bearish_threshold' in df.columns:
        valid_bearish = df['stoch_bearish_threshold'].isin([65, 70, 75, 80])
        if not valid_bearish.all():
            invalid_bearish = df[~valid_bearish]['stoch_bearish_threshold'].unique()
            errors.append(f"Invalid stoch_bearish_threshold values: {invalid_bearish}")
    else:
        errors.append("stoch_bearish_threshold column missing")
    
    # Verify MA parameters are fixed at Phase 3 best values
    if 'fast_period' in df.columns:
        if not (df['fast_period'] == 42).all():
            errors.append("fast_period not fixed at 42 (Phase 3 best)")
    else:
        errors.append("fast_period column missing")
    
    if 'slow_period' in df.columns:
        if not (df['slow_period'] == 270).all():
            errors.append("slow_period not fixed at 270 (Phase 3 best)")
    else:
        errors.append("slow_period column missing")
    
    if 'crossover_threshold_pips' in df.columns:
        if not (df['crossover_threshold_pips'] == 0.35).all():
            errors.append("crossover_threshold_pips not fixed at 0.35 (Phase 3 best)")
    else:
        errors.append("crossover_threshold_pips column missing")
    
    # Verify risk management parameters are fixed at Phase 4 best values
    if 'stop_loss_pips' in df.columns:
        if not (df['stop_loss_pips'] == 35).all():
            errors.append("stop_loss_pips not fixed at 35 (Phase 4 best)")
    else:
        errors.append("stop_loss_pips column missing")
    
    if 'take_profit_pips' in df.columns:
        if not (df['take_profit_pips'] == 50).all():
            errors.append("take_profit_pips not fixed at 50 (Phase 4 best)")
    else:
        errors.append("take_profit_pips column missing")
    
    if 'trailing_stop_activation_pips' in df.columns:
        if not (df['trailing_stop_activation_pips'] == 22).all():
            errors.append("trailing_stop_activation_pips not fixed at 22 (Phase 4 best)")
    else:
        errors.append("trailing_stop_activation_pips column missing")
    
    if 'trailing_stop_distance_pips' in df.columns:
        if not (df['trailing_stop_distance_pips'] == 12).all():
            errors.append("trailing_stop_distance_pips not fixed at 12 (Phase 4 best)")
    else:
        errors.append("trailing_stop_distance_pips column missing")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }


def validate_sharpe_ratios(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate Sharpe ratio quality and detect issues.
    
    Args:
        df: DataFrame containing Phase 5 results
        
    Returns:
        Dictionary with validation results
    """
    logger.info("Validating Sharpe ratios...")
    
    errors = []
    warnings = []
    
    if 'sharpe_ratio' not in df.columns:
        return {
            'valid': False,
            'errors': ['sharpe_ratio column missing'],
            'warnings': warnings
        }
    
    sharpe_ratios = df['sharpe_ratio'].dropna()
    
    # Check for zero Sharpe ratios (bug fix verification)
    zero_count = (sharpe_ratios == 0.0).sum()
    if zero_count > 0:
        errors.append(f"Found {zero_count} zero Sharpe ratios (bug fix verification failed)")
    
    # Check for reasonable Sharpe ratio range
    extreme_ratios = sharpe_ratios[(sharpe_ratios < -1.0) | (sharpe_ratios > 5.0)]
    if len(extreme_ratios) > 0:
        warnings.append(f"Found {len(extreme_ratios)} extreme Sharpe ratios: {extreme_ratios.tolist()}")
    
    # Calculate positive Sharpe ratio percentage
    positive_count = (sharpe_ratios > 0).sum()
    positive_percentage = (positive_count / len(sharpe_ratios)) * 100 if len(sharpe_ratios) > 0 else 0
    
    # Detect outliers (values > 3 standard deviations from mean)
    if len(sharpe_ratios) > 0:
        mean_sharpe = sharpe_ratios.mean()
        std_sharpe = sharpe_ratios.std()
        outliers = sharpe_ratios[abs(sharpe_ratios - mean_sharpe) > 3 * std_sharpe]
        if len(outliers) > 0:
            warnings.append(f"Found {len(outliers)} Sharpe ratio outliers: {outliers.tolist()}")
    
    return {
        'valid': len(errors) == 0,
        'positive_count': positive_count,
        'positive_percentage': positive_percentage,
        'outliers': outliers.tolist() if len(sharpe_ratios) > 0 else [],
        'warnings': warnings,
        'errors': errors
    }


def validate_output_directories(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate output directory uniqueness and microsecond precision.
    
    Args:
        df: DataFrame containing Phase 5 results
        
    Returns:
        Dictionary with validation results
    """
    logger.info("Validating output directories...")
    
    errors = []
    warnings = []
    
    if 'output_directory' not in df.columns:
        return {
            'valid': False,
            'errors': ['output_directory column missing'],
            'warnings': warnings
        }
    
    output_dirs = df['output_directory'].dropna()
    
    # Check for microsecond precision timestamps (pattern: YYYYMMDD_HHMMSS_microseconds)
    import re
    timestamp_pattern = r'.*_\d{8}_\d{6}_\d{6}$'  # Ends with YYYYMMDD_HHMMSS_microseconds
    valid_timestamps = output_dirs.str.match(timestamp_pattern)
    
    if not valid_timestamps.all():
        invalid_dirs = output_dirs[~valid_timestamps].tolist()
        errors.append(f"Found {len(invalid_dirs)} output directories without microsecond precision: {invalid_dirs[:5]}...")
    
    # Check for duplicate output directories
    unique_dirs = output_dirs.nunique()
    total_dirs = len(output_dirs)
    
    if unique_dirs != total_dirs:
        duplicates = output_dirs[output_dirs.duplicated()].tolist()
        errors.append(f"Found {len(duplicates)} duplicate output directories: {duplicates[:5]}...")
    
    return {
        'valid': len(errors) == 0,
        'unique_count': unique_dirs,
        'duplicates': output_dirs[output_dirs.duplicated()].tolist() if unique_dirs != total_dirs else [],
        'missing_microseconds': output_dirs[~valid_timestamps].tolist() if not valid_timestamps.all() else [],
        'errors': errors,
        'warnings': warnings
    }


def validate_completion_rate(df: pd.DataFrame, expected_combinations: int) -> Dict[str, Any]:
    """
    Validate completion rate and identify failure patterns.
    
    Args:
        df: DataFrame containing Phase 5 results
        expected_combinations: Expected number of combinations
        
    Returns:
        Dictionary with validation results
    """
    logger.info("Validating completion rate...")
    
    total_expected = expected_combinations
    completed = df['sharpe_ratio'].notna().sum()
    failed = total_expected - completed
    success_rate = completed / total_expected if total_expected > 0 else 0
    
    patterns = []
    
    # Check if success rate meets minimum threshold
    if success_rate < MIN_SUCCESS_RATE:
        patterns.append(f"Low success rate: {success_rate:.1%} < {MIN_SUCCESS_RATE:.1%}")
    
    # Identify systematic failure patterns
    if 'dmi_enabled' in df.columns and failed > 0:
        failed_data = df[df['sharpe_ratio'].isna()]
        if len(failed_data) > 0:
            # Check for failures clustered around specific parameter values
            dmi_failures = failed_data['dmi_enabled'].value_counts()
            if len(dmi_failures) > 0 and dmi_failures.max() > failed * 0.3:
                patterns.append(f"Failures clustered around dmi_enabled: {dmi_failures.to_dict()}")
    
    return {
        'total_expected': total_expected,
        'completed': completed,
        'failed': failed,
        'timeout': 0,  # Not tracked in current implementation
        'success_rate': success_rate,
        'meets_threshold': success_rate >= MIN_SUCCESS_RATE,
        'patterns': patterns
    }


def compare_with_phase4(df: pd.DataFrame, phase4_sharpe: float = PHASE4_BEST_SHARPE) -> Dict[str, Any]:
    """
    Compare Phase 5 results with Phase 4 baseline.
    
    Args:
        df: DataFrame containing Phase 5 results
        phase4_sharpe: Phase 4 best Sharpe ratio for comparison
        
    Returns:
        Dictionary with comparison results
    """
    logger.info("Comparing with Phase 4 baseline...")
    
    if 'sharpe_ratio' not in df.columns:
        return {
            'phase5_best_sharpe': 0.0,
            'phase4_baseline_sharpe': phase4_sharpe,
            'improvement_percentage': 0.0,
            'improved': False,
            'within_tolerance': False,
            'metric_comparisons': {}
        }
    
    # Get Phase 5 best Sharpe ratio
    phase5_best_sharpe = df['sharpe_ratio'].max()
    
    # Calculate improvement percentage
    improvement_percentage = ((phase5_best_sharpe - phase4_sharpe) / phase4_sharpe) * 100 if phase4_sharpe != 0 else 0
    
    # Check if Phase 5 improved over Phase 4
    improved = phase5_best_sharpe >= phase4_sharpe
    within_tolerance = abs(phase5_best_sharpe - phase4_sharpe) / phase4_sharpe <= 0.05 if phase4_sharpe != 0 else True
    
    # Compare other metrics if available
    metric_comparisons = {}
    if 'win_rate' in df.columns:
        phase5_best_win_rate = df.loc[df['sharpe_ratio'].idxmax(), 'win_rate']
        metric_comparisons['win_rate'] = phase5_best_win_rate
    
    if 'total_pnl' in df.columns:
        phase5_best_pnl = df.loc[df['sharpe_ratio'].idxmax(), 'total_pnl']
        metric_comparisons['total_pnl'] = phase5_best_pnl
    
    return {
        'phase5_best_sharpe': phase5_best_sharpe,
        'phase4_baseline_sharpe': phase4_sharpe,
        'improvement_percentage': improvement_percentage,
        'improved': improved,
        'within_tolerance': within_tolerance,
        'metric_comparisons': metric_comparisons
    }


def analyze_filter_impact(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyze filter impact on performance (Phase 5 specific).
    
    Args:
        df: DataFrame containing Phase 5 results
        
    Returns:
        Dictionary with filter impact analysis
    """
    logger.info("Analyzing filter impact...")
    
    if 'dmi_enabled' not in df.columns or 'sharpe_ratio' not in df.columns:
        return {
            'dmi_enabled_impact': {},
            'optimal_dmi_period': None,
            'optimal_stoch_params': {},
            'filter_impact_summary': {}
        }
    
    # Compare DMI enabled vs disabled
    dmi_enabled_results = df[df['dmi_enabled'] == True]
    dmi_disabled_results = df[df['dmi_enabled'] == False]
    
    dmi_enabled_impact = {
        'enabled': {
            'count': len(dmi_enabled_results),
            'avg_sharpe': dmi_enabled_results['sharpe_ratio'].mean() if len(dmi_enabled_results) > 0 else 0,
            'avg_win_rate': dmi_enabled_results['win_rate'].mean() if len(dmi_enabled_results) > 0 and 'win_rate' in df.columns else 0,
            'avg_trade_count': dmi_enabled_results['trade_count'].mean() if len(dmi_enabled_results) > 0 and 'trade_count' in df.columns else 0
        },
        'disabled': {
            'count': len(dmi_disabled_results),
            'avg_sharpe': dmi_disabled_results['sharpe_ratio'].mean() if len(dmi_disabled_results) > 0 else 0,
            'avg_win_rate': dmi_disabled_results['win_rate'].mean() if len(dmi_disabled_results) > 0 and 'win_rate' in df.columns else 0,
            'avg_trade_count': dmi_disabled_results['trade_count'].mean() if len(dmi_disabled_results) > 0 and 'trade_count' in df.columns else 0
        }
    }
    
    # Find optimal DMI period
    optimal_dmi_period = None
    if len(dmi_enabled_results) > 0 and 'dmi_period' in df.columns:
        dmi_period_stats = dmi_enabled_results.groupby('dmi_period')['sharpe_ratio'].mean()
        optimal_dmi_period = dmi_period_stats.idxmax()
    
    # Find optimal Stochastic parameters
    optimal_stoch_params = {}
    if 'stoch_period_k' in df.columns:
        stoch_k_stats = df.groupby('stoch_period_k')['sharpe_ratio'].mean()
        optimal_stoch_params['stoch_period_k'] = stoch_k_stats.idxmax()
    
    if 'stoch_period_d' in df.columns:
        stoch_d_stats = df.groupby('stoch_period_d')['sharpe_ratio'].mean()
        optimal_stoch_params['stoch_period_d'] = stoch_d_stats.idxmax()
    
    if 'stoch_bullish_threshold' in df.columns:
        bullish_stats = df.groupby('stoch_bullish_threshold')['sharpe_ratio'].mean()
        optimal_stoch_params['stoch_bullish_threshold'] = bullish_stats.idxmax()
    
    if 'stoch_bearish_threshold' in df.columns:
        bearish_stats = df.groupby('stoch_bearish_threshold')['sharpe_ratio'].mean()
        optimal_stoch_params['stoch_bearish_threshold'] = bearish_stats.idxmax()
    
    # Analyze trade count and win rate impact
    filter_impact_summary = {}
    if 'win_rate' in df.columns and 'trade_count' in df.columns:
        # Compare average metrics between DMI enabled and disabled
        if len(dmi_enabled_results) > 0 and len(dmi_disabled_results) > 0:
            filter_impact_summary = {
                'trade_count_impact': {
                    'enabled_avg': dmi_enabled_results['trade_count'].mean(),
                    'disabled_avg': dmi_disabled_results['trade_count'].mean(),
                    'difference': dmi_enabled_results['trade_count'].mean() - dmi_disabled_results['trade_count'].mean()
                },
                'win_rate_impact': {
                    'enabled_avg': dmi_enabled_results['win_rate'].mean(),
                    'disabled_avg': dmi_disabled_results['win_rate'].mean(),
                    'difference': dmi_enabled_results['win_rate'].mean() - dmi_disabled_results['win_rate'].mean()
                }
            }
    
    return {
        'dmi_enabled_impact': dmi_enabled_impact,
        'optimal_dmi_period': optimal_dmi_period,
        'optimal_stoch_params': optimal_stoch_params,
        'filter_impact_summary': filter_impact_summary
    }


def check_parameter_stability(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Check parameter stability in top 10 results.
    
    Args:
        df: DataFrame containing Phase 5 results
        
    Returns:
        Dictionary with stability analysis
    """
    logger.info("Checking parameter stability...")
    
    if len(df) < 10:
        return {
            'stable': False,
            'parameter_std_devs': {},
            'at_boundaries': [],
            'clustering_score': 0.0
        }
    
    # Get top 10 results
    top_10 = df.nlargest(10, 'sharpe_ratio')
    
    # Calculate standard deviation for each parameter
    parameter_std_devs = {}
    parameters_to_check = ['dmi_period', 'stoch_period_k', 'stoch_period_d', 
                          'stoch_bullish_threshold', 'stoch_bearish_threshold']
    
    for param in parameters_to_check:
        if param in top_10.columns:
            std_dev = top_10[param].std()
            parameter_std_devs[param] = std_dev
    
    # Check if parameters are at range boundaries
    at_boundaries = []
    if 'dmi_period' in top_10.columns:
        if top_10['dmi_period'].min() == 10 or top_10['dmi_period'].max() == 18:
            at_boundaries.append('dmi_period')
    
    if 'stoch_period_k' in top_10.columns:
        if top_10['stoch_period_k'].min() == 10 or top_10['stoch_period_k'].max() == 18:
            at_boundaries.append('stoch_period_k')
    
    # Calculate clustering score (lower std dev = higher clustering)
    avg_std_dev = np.mean(list(parameter_std_devs.values())) if parameter_std_devs else 0
    clustering_score = max(0, 1 - (avg_std_dev / 5))  # Normalize to 0-1 range
    
    # Consider stable if average std dev is low and not at boundaries
    stable = avg_std_dev < 3 and len(at_boundaries) == 0
    
    return {
        'stable': stable,
        'parameter_std_devs': parameter_std_devs,
        'at_boundaries': at_boundaries,
        'clustering_score': clustering_score
    }


def main():
    """Main validation function."""
    parser = argparse.ArgumentParser(description='Validate Phase 5 filter optimization results')
    parser.add_argument('--csv', default='optimization/results/phase5_filters_results.csv',
                       help='Path to Phase 5 results CSV file')
    parser.add_argument('--phase4-sharpe', type=float, default=PHASE4_BEST_SHARPE,
                       help='Phase 4 best Sharpe ratio for comparison')
    parser.add_argument('--expected-combinations', type=int, default=EXPECTED_COMBINATIONS_FULL,
                       help='Expected number of combinations (2400 for full, 108 for reduced)')
    parser.add_argument('--strict', action='store_true',
                       help='Fail on warnings (exit code 2 becomes 1)')
    parser.add_argument('--json-output', default='optimization/results/phase5_validation_report.json',
                       help='Path to save validation report JSON')
    parser.add_argument('--no-color', action='store_true',
                       help='Disable colored console output')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load CSV file
    try:
        logger.info(f"Loading Phase 5 results from {args.csv}")
        df = pd.read_csv(args.csv)
        logger.info(f"Loaded {len(df)} results")
    except FileNotFoundError:
        logger.error(f"Phase 5 results file not found: {args.csv}")
        sys.exit(3)
    except Exception as e:
        logger.error(f"Error loading CSV file: {e}")
        sys.exit(3)
    
    # Run all validation functions
    logger.info("Running comprehensive validation...")
    
    validation_results = {
        'parameter_ranges': validate_parameter_ranges(df),
        'sharpe_ratios': validate_sharpe_ratios(df),
        'output_directories': validate_output_directories(df),
        'completion_rate': validate_completion_rate(df, args.expected_combinations),
        'phase4_comparison': compare_with_phase4(df, args.phase4_sharpe),
        'filter_impact': analyze_filter_impact(df),
        'parameter_stability': check_parameter_stability(df)
    }
    
    # Generate comprehensive validation report
    overall_status = "PASS"
    critical_failures = 0
    warnings = 0
    
    # Check for critical failures
    for validation_name, results in validation_results.items():
        if 'valid' in results and not results['valid']:
            if 'errors' in results and results['errors']:
                critical_failures += len(results['errors'])
                overall_status = "FAIL"
    
    # Check for warnings
    for validation_name, results in validation_results.items():
        if 'warnings' in results and results['warnings']:
            warnings += len(results['warnings'])
            if overall_status == "PASS":
                overall_status = "WARN"
    
    # Create detailed report
    report = {
        'overall_status': overall_status,
        'validation_timestamp': pd.Timestamp.now().isoformat(),
        'total_runs': len(df),
        'completed_runs': len(df[df['sharpe_ratio'].notna()]),
        'success_rate': len(df[df['sharpe_ratio'].notna()]) / len(df) if len(df) > 0 else 0,
        'critical_failures': critical_failures,
        'warnings': warnings,
        'validation_results': validation_results,
        'top_5_results': df.nlargest(5, 'sharpe_ratio')[['sharpe_ratio', 'dmi_enabled', 'dmi_period', 
                                                       'stoch_period_k', 'stoch_period_d', 'stoch_bullish_threshold', 'stoch_bearish_threshold']].to_dict('records'),
        'recommendations': []
    }
    
    # Add recommendations based on results
    if validation_results['phase4_comparison']['improved']:
        report['recommendations'].append("Phase 5 shows improvement over Phase 4 - proceed to Phase 6")
    else:
        report['recommendations'].append("Phase 5 shows no improvement - consider disabling filters or using different approach")
    
    if validation_results['filter_impact']['dmi_enabled_impact']:
        dmi_impact = validation_results['filter_impact']['dmi_enabled_impact']
        if 'enabled' in dmi_impact and 'disabled' in dmi_impact:
            if dmi_impact['enabled']['avg_sharpe'] > dmi_impact['disabled']['avg_sharpe']:
                report['recommendations'].append("DMI filter adds value - keep enabled with optimal parameters")
            else:
                report['recommendations'].append("DMI filter degrades performance - consider disabling")
    
    if validation_results['parameter_stability']['stable']:
        report['recommendations'].append("Parameter stability is good - top results cluster around similar values")
    else:
        report['recommendations'].append("Parameter stability is poor - consider expanding search space")
    
    # Save report
    try:
        with open(args.json_output, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Validation report saved to {args.json_output}")
    except Exception as e:
        logger.error(f"Error saving validation report: {e}")
    
    # Print summary to console
    print(f"\n{'='*60}")
    print(f"Phase 5 Validation Results")
    print(f"{'='*60}")
    print(f"Overall Status: {overall_status}")
    print(f"Total Runs: {len(df)}")
    print(f"Completed: {len(df[df['sharpe_ratio'].notna()])}")
    print(f"Success Rate: {len(df[df['sharpe_ratio'].notna()]) / len(df) * 100:.1f}%")
    print(f"Critical Failures: {critical_failures}")
    print(f"Warnings: {warnings}")
    
    if validation_results['phase4_comparison']['improved']:
        improvement = validation_results['phase4_comparison']['improvement_percentage']
        print(f"Phase 4 Comparison: ✅ Improved by {improvement:.2f}%")
    else:
        print(f"Phase 4 Comparison: ❌ No improvement")
    
    # Print filter impact analysis
    if validation_results['filter_impact']['dmi_enabled_impact']:
        dmi_impact = validation_results['filter_impact']['dmi_enabled_impact']
        if 'enabled' in dmi_impact and 'disabled' in dmi_impact:
            print(f"\nFilter Impact Analysis:")
            print(f"  DMI Enabled: Avg Sharpe = {dmi_impact['enabled']['avg_sharpe']:.3f}")
            print(f"  DMI Disabled: Avg Sharpe = {dmi_impact['disabled']['avg_sharpe']:.3f}")
            if dmi_impact['enabled']['avg_sharpe'] > dmi_impact['disabled']['avg_sharpe']:
                print(f"  Conclusion: DMI filter adds value ✅")
            else:
                print(f"  Conclusion: DMI filter degrades performance ❌")
    
    print(f"\nTop 5 Results:")
    for i, result in enumerate(report['top_5_results'][:5], 1):
        print(f"  {i}. Sharpe: {result['sharpe_ratio']:.3f}, DMI: {result['dmi_enabled']}, DMI_Period: {result['dmi_period']}, Stoch_K: {result['stoch_period_k']}, Stoch_D: {result['stoch_period_d']}")
    
    print(f"\nRecommendations:")
    for rec in report['recommendations']:
        print(f"  • {rec}")
    
    # Determine exit code
    if overall_status == "FAIL" or critical_failures > 0:
        exit_code = 1
    elif overall_status == "WARN" and not args.strict:
        exit_code = 2
    elif overall_status == "WARN" and args.strict:
        exit_code = 1
    else:
        exit_code = 0
    
    print(f"\nValidation {'PASSED' if exit_code == 0 else 'FAILED'} (exit code: {exit_code})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
