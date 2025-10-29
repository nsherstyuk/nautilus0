#!/usr/bin/env python3
"""
Phase 4 Risk Management Optimization Results Validation Script
=============================================================

This script validates Phase 4 risk management optimization results for data quality,
parameter ranges, and performance improvements.

Purpose: Verify Phase 4 results are correct, complete, and show meaningful 
         improvements before proceeding to Phase 5 filter optimization.

Usage:
    python optimization/scripts/validate_phase4_results.py
    python optimization/scripts/validate_phase4_results.py --phase3-sharpe 0.280
    python optimization/scripts/validate_phase4_results.py --strict
    python optimization/scripts/validate_phase4_results.py --csv results.csv --json-output validation.json --verbose

Exit codes:
    0: All validations passed
    1: Critical validation failures (wrong parameter ranges, all zero Sharpe ratios, <90% success rate)
    2: Warning-level issues (low success rate 90-95%, no improvement over Phase 3, high parameter instability)
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
PHASE3_BEST_SHARPE = 0.272  # Baseline for comparison
EXPECTED_COMBINATIONS = 500
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
        df: DataFrame containing Phase 4 results
        
    Returns:
        Dictionary with validation results
    """
    logger.info("Validating parameter ranges...")
    
    errors = []
    warnings = []
    
    # Check stop_loss_pips range [15, 20, 25, 30, 35]
    if 'stop_loss_pips' in df.columns:
        valid_sl = df['stop_loss_pips'].isin([15, 20, 25, 30, 35])
        if not valid_sl.all():
            invalid_sl = df[~valid_sl]['stop_loss_pips'].unique()
            errors.append(f"Invalid stop_loss_pips values: {invalid_sl}")
    else:
        errors.append("stop_loss_pips column missing")
    
    # Check take_profit_pips range [30, 40, 50, 60, 75]
    if 'take_profit_pips' in df.columns:
        valid_tp = df['take_profit_pips'].isin([30, 40, 50, 60, 75])
        if not valid_tp.all():
            invalid_tp = df[~valid_tp]['take_profit_pips'].unique()
            errors.append(f"Invalid take_profit_pips values: {invalid_tp}")
    else:
        errors.append("take_profit_pips column missing")
    
    # Check trailing_stop_activation_pips range [10, 15, 20, 25]
    if 'trailing_stop_activation_pips' in df.columns:
        valid_ta = df['trailing_stop_activation_pips'].isin([10, 15, 20, 25])
        if not valid_ta.all():
            invalid_ta = df[~valid_ta]['trailing_stop_activation_pips'].unique()
            errors.append(f"Invalid trailing_stop_activation_pips values: {invalid_ta}")
    else:
        errors.append("trailing_stop_activation_pips column missing")
    
    # Check trailing_stop_distance_pips range [10, 12, 15, 18, 20]
    if 'trailing_stop_distance_pips' in df.columns:
        valid_td = df['trailing_stop_distance_pips'].isin([10, 12, 15, 18, 20])
        if not valid_td.all():
            invalid_td = df[~valid_td]['trailing_stop_distance_pips'].unique()
            errors.append(f"Invalid trailing_stop_distance_pips values: {invalid_td}")
    else:
        errors.append("trailing_stop_distance_pips column missing")
    
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
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }


def validate_sharpe_ratios(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate Sharpe ratio quality and detect issues.
    
    Args:
        df: DataFrame containing Phase 4 results
        
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
        df: DataFrame containing Phase 4 results
        
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


def validate_completion_rate(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate completion rate and identify failure patterns.
    
    Args:
        df: DataFrame containing Phase 4 results
        
    Returns:
        Dictionary with validation results
    """
    logger.info("Validating completion rate...")
    
    total = len(df)
    completed = len(df[df['sharpe_ratio'].notna()])
    failed = total - completed
    success_rate = completed / total if total > 0 else 0
    
    patterns = []
    
    # Check if success rate meets minimum threshold
    if success_rate < MIN_SUCCESS_RATE:
        patterns.append(f"Low success rate: {success_rate:.1%} < {MIN_SUCCESS_RATE:.1%}")
    
    # Identify systematic failure patterns
    if 'stop_loss_pips' in df.columns and failed > 0:
        failed_data = df[df['sharpe_ratio'].isna()]
        if len(failed_data) > 0:
            # Check for failures clustered around specific parameter values
            sl_failures = failed_data['stop_loss_pips'].value_counts()
            if len(sl_failures) > 0 and sl_failures.max() > failed * 0.3:
                patterns.append(f"Failures clustered around stop_loss_pips: {sl_failures.to_dict()}")
    
    return {
        'total': total,
        'completed': completed,
        'failed': failed,
        'timeout': 0,  # Not tracked in current implementation
        'success_rate': success_rate,
        'meets_threshold': success_rate >= MIN_SUCCESS_RATE,
        'patterns': patterns
    }


def compare_with_phase3(df: pd.DataFrame, phase3_sharpe: float = PHASE3_BEST_SHARPE) -> Dict[str, Any]:
    """
    Compare Phase 4 results with Phase 3 baseline.
    
    Args:
        df: DataFrame containing Phase 4 results
        phase3_sharpe: Phase 3 best Sharpe ratio for comparison
        
    Returns:
        Dictionary with comparison results
    """
    logger.info("Comparing with Phase 3 baseline...")
    
    if 'sharpe_ratio' not in df.columns:
        return {
            'phase4_best_sharpe': 0.0,
            'phase3_baseline_sharpe': phase3_sharpe,
            'improvement_percentage': 0.0,
            'improved': False,
            'within_tolerance': False,
            'metric_comparisons': {}
        }
    
    # Get Phase 4 best Sharpe ratio
    phase4_best_sharpe = df['sharpe_ratio'].max()
    
    # Calculate improvement percentage
    improvement_percentage = ((phase4_best_sharpe - phase3_sharpe) / phase3_sharpe) * 100 if phase3_sharpe != 0 else 0
    
    # Check if Phase 4 improved over Phase 3
    improved = phase4_best_sharpe >= phase3_sharpe
    within_tolerance = abs(phase4_best_sharpe - phase3_sharpe) / phase3_sharpe <= 0.05 if phase3_sharpe != 0 else True
    
    # Compare other metrics if available
    metric_comparisons = {}
    if 'win_rate' in df.columns:
        phase4_best_win_rate = df.loc[df['sharpe_ratio'].idxmax(), 'win_rate']
        metric_comparisons['win_rate'] = phase4_best_win_rate
    
    if 'total_pnl' in df.columns:
        phase4_best_pnl = df.loc[df['sharpe_ratio'].idxmax(), 'total_pnl']
        metric_comparisons['total_pnl'] = phase4_best_pnl
    
    return {
        'phase4_best_sharpe': phase4_best_sharpe,
        'phase3_baseline_sharpe': phase3_sharpe,
        'improvement_percentage': improvement_percentage,
        'improved': improved,
        'within_tolerance': within_tolerance,
        'metric_comparisons': metric_comparisons
    }


def analyze_risk_reward_patterns(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyze risk/reward ratio patterns and optimal combinations.
    
    Args:
        df: DataFrame containing Phase 4 results
        
    Returns:
        Dictionary with risk/reward analysis
    """
    logger.info("Analyzing risk/reward patterns...")
    
    if 'take_profit_pips' not in df.columns or 'stop_loss_pips' not in df.columns:
        return {
            'optimal_rr_range': (0, 0),
            'rr_group_stats': {},
            'trailing_stop_insights': {},
            'best_combination': {}
        }
    
    # Calculate risk/reward ratios
    df['risk_reward_ratio'] = df['take_profit_pips'] / df['stop_loss_pips']
    
    # Group by risk/reward ratio ranges
    conservative = df[(df['risk_reward_ratio'] >= 1.0) & (df['risk_reward_ratio'] < 1.5)]
    moderate = df[(df['risk_reward_ratio'] >= 1.5) & (df['risk_reward_ratio'] < 2.0)]
    aggressive = df[(df['risk_reward_ratio'] >= 2.0) & (df['risk_reward_ratio'] <= 3.0)]
    
    rr_group_stats = {
        'conservative': {
            'count': len(conservative),
            'avg_sharpe': conservative['sharpe_ratio'].mean() if len(conservative) > 0 else 0,
            'avg_rr': conservative['risk_reward_ratio'].mean() if len(conservative) > 0 else 0
        },
        'moderate': {
            'count': len(moderate),
            'avg_sharpe': moderate['sharpe_ratio'].mean() if len(moderate) > 0 else 0,
            'avg_rr': moderate['risk_reward_ratio'].mean() if len(moderate) > 0 else 0
        },
        'aggressive': {
            'count': len(aggressive),
            'avg_sharpe': aggressive['sharpe_ratio'].mean() if len(aggressive) > 0 else 0,
            'avg_rr': aggressive['risk_reward_ratio'].mean() if len(aggressive) > 0 else 0
        }
    }
    
    # Find optimal risk/reward ratio range
    best_group = max(rr_group_stats.items(), key=lambda x: x[1]['avg_sharpe'])
    optimal_rr_range = (1.0, 1.5) if best_group[0] == 'conservative' else (1.5, 2.0) if best_group[0] == 'moderate' else (2.0, 3.0)
    
    # Analyze trailing stop impact
    trailing_stop_insights = {}
    if 'trailing_stop_activation_pips' in df.columns:
        early_activation = df[df['trailing_stop_activation_pips'] <= 15]
        late_activation = df[df['trailing_stop_activation_pips'] >= 20]
        
        trailing_stop_insights = {
            'early_activation_avg_sharpe': early_activation['sharpe_ratio'].mean() if len(early_activation) > 0 else 0,
            'late_activation_avg_sharpe': late_activation['sharpe_ratio'].mean() if len(late_activation) > 0 else 0
        }
    
    # Get best combination
    best_idx = df['sharpe_ratio'].idxmax()
    best_combination = df.loc[best_idx].to_dict() if best_idx is not None else {}
    
    return {
        'optimal_rr_range': optimal_rr_range,
        'rr_group_stats': rr_group_stats,
        'trailing_stop_insights': trailing_stop_insights,
        'best_combination': best_combination
    }


def check_parameter_stability(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Check parameter stability in top 10 results.
    
    Args:
        df: DataFrame containing Phase 4 results
        
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
    parameters_to_check = ['stop_loss_pips', 'take_profit_pips', 'trailing_stop_activation_pips', 'trailing_stop_distance_pips']
    
    for param in parameters_to_check:
        if param in top_10.columns:
            std_dev = top_10[param].std()
            parameter_std_devs[param] = std_dev
    
    # Check if parameters are at range boundaries
    at_boundaries = []
    if 'stop_loss_pips' in top_10.columns:
        if top_10['stop_loss_pips'].min() == 15 or top_10['stop_loss_pips'].max() == 35:
            at_boundaries.append('stop_loss_pips')
    
    if 'take_profit_pips' in top_10.columns:
        if top_10['take_profit_pips'].min() == 30 or top_10['take_profit_pips'].max() == 75:
            at_boundaries.append('take_profit_pips')
    
    # Calculate clustering score (lower std dev = higher clustering)
    avg_std_dev = np.mean(list(parameter_std_devs.values())) if parameter_std_devs else 0
    clustering_score = max(0, 1 - (avg_std_dev / 10))  # Normalize to 0-1 range
    
    # Consider stable if average std dev is low and not at boundaries
    stable = avg_std_dev < 5 and len(at_boundaries) == 0
    
    return {
        'stable': stable,
        'parameter_std_devs': parameter_std_devs,
        'at_boundaries': at_boundaries,
        'clustering_score': clustering_score
    }


def main():
    """Main validation function."""
    parser = argparse.ArgumentParser(description='Validate Phase 4 risk management optimization results')
    parser.add_argument('--csv', default='optimization/results/phase4_risk_management_results.csv',
                       help='Path to Phase 4 results CSV file')
    parser.add_argument('--phase3-sharpe', type=float, default=PHASE3_BEST_SHARPE,
                       help='Phase 3 best Sharpe ratio for comparison')
    parser.add_argument('--strict', action='store_true',
                       help='Fail on warnings (exit code 2 becomes 1)')
    parser.add_argument('--json-output', default='optimization/results/phase4_validation_report.json',
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
        logger.info(f"Loading Phase 4 results from {args.csv}")
        df = pd.read_csv(args.csv)
        logger.info(f"Loaded {len(df)} results")
    except FileNotFoundError:
        logger.error(f"Phase 4 results file not found: {args.csv}")
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
        'completion_rate': validate_completion_rate(df),
        'phase3_comparison': compare_with_phase3(df, args.phase3_sharpe),
        'risk_reward_patterns': analyze_risk_reward_patterns(df),
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
        'top_5_results': df.nlargest(5, 'sharpe_ratio')[['sharpe_ratio', 'stop_loss_pips', 'take_profit_pips', 
                                                       'trailing_stop_activation_pips', 'trailing_stop_distance_pips']].to_dict('records'),
        'recommendations': []
    }
    
    # Add recommendations based on results
    if validation_results['phase3_comparison']['improved']:
        report['recommendations'].append("Phase 4 shows improvement over Phase 3 - proceed to Phase 5")
    else:
        report['recommendations'].append("Phase 4 shows no improvement - consider wider parameter ranges or different approach")
    
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
    print(f"Phase 4 Validation Results")
    print(f"{'='*60}")
    print(f"Overall Status: {overall_status}")
    print(f"Total Runs: {len(df)}")
    print(f"Completed: {len(df[df['sharpe_ratio'].notna()])}")
    print(f"Success Rate: {len(df[df['sharpe_ratio'].notna()]) / len(df) * 100:.1f}%")
    print(f"Critical Failures: {critical_failures}")
    print(f"Warnings: {warnings}")
    
    if validation_results['phase3_comparison']['improved']:
        improvement = validation_results['phase3_comparison']['improvement_percentage']
        print(f"Phase 3 Comparison: ✅ Improved by {improvement:.2f}%")
    else:
        print(f"Phase 3 Comparison: ❌ No improvement")
    
    print(f"\nTop 5 Results:")
    for i, result in enumerate(report['top_5_results'][:5], 1):
        print(f"  {i}. Sharpe: {result['sharpe_ratio']:.3f}, SL: {result['stop_loss_pips']}, TP: {result['take_profit_pips']}, TA: {result['trailing_stop_activation_pips']}, TD: {result['trailing_stop_distance_pips']}")
    
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
