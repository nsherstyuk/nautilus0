#!/usr/bin/env python3
"""
Phase 5 Parameter Sensitivity Analysis

This script performs comprehensive parameter sensitivity analysis on Phase 5 results
to identify the 4 most sensitive parameters for Phase 6 refinement.

The analysis includes:
- Pearson and Spearman correlations with Sharpe ratio
- Variance contribution analysis
- Parameter stability assessment (top 10 results)
- Boolean parameter impact analysis
- Combined sensitivity scoring

Usage:
    python analyze_phase5_sensitivity.py --csv optimization/results/phase5_filters_results.csv --output-dir optimization/results --verbose
"""

import pandas as pd
import numpy as np
import json
import argparse
import sys
from pathlib import Path
import logging
from scipy import stats
from typing import Dict, List, Tuple, Any, Set

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def _make_json_safe(obj: Any) -> Any:
    """Recursively convert numpy/pandas types and NaN/inf to JSON-safe Python types."""
    # Dict
    if isinstance(obj, dict):
        return {(_make_json_safe(k) if not isinstance(k, str) else k): _make_json_safe(v) for k, v in obj.items()}
    # List/Tuple
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    # numpy scalar types
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if np.isnan(v) or np.isinf(v):
            return None
        return v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    # pandas timestamp
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    # Plain floats with NaN/inf
    if isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return obj
    # Handle pandas NA scalars
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass
    return obj

def load_phase5_results(csv_path: str) -> pd.DataFrame:
    """
    Load Phase 5 results from CSV file and validate required columns.
    
    Args:
        csv_path: Path to phase5_filters_results.csv
        
    Returns:
        DataFrame with completed runs only
    """
    logger.info(f"Loading Phase 5 results from {csv_path}")
    
    try:
        df = pd.read_csv(csv_path)
        logger.info(f"Loaded {len(df)} total runs")
        
        # Filter to completed runs only
        if 'status' in df.columns:
            completed_df = df[df['status'] == 'completed'].copy()
            logger.info(f"Found {len(completed_df)} completed runs")
        else:
            completed_df = df.copy()
            logger.warning("No 'status' column found, using all runs")
        
        # Validate required columns - only check minimal required columns
        minimal_required_columns = ['sharpe_ratio']
        
        # Build list of analyzed parameters by intersecting predefined set with available columns
        analyzed_parameters = [
            'fast_period', 'slow_period', 'crossover_threshold_pips', 
            'stop_loss_pips', 'take_profit_pips', 'trailing_stop_activation_pips',
            'trailing_stop_distance_pips', 'dmi_enabled', 'dmi_period',
            'stoch_period_k', 'stoch_period_d', 'stoch_bullish_threshold',
            'stoch_bearish_threshold'
        ]
        
        # Intersect with available columns
        available_analyzed_params = [col for col in analyzed_parameters if col in completed_df.columns]
        required_columns = minimal_required_columns + available_analyzed_params
        
        # Check minimal required columns
        missing_minimal = [col for col in minimal_required_columns if col not in completed_df.columns]
        if missing_minimal:
            raise ValueError(f"Missing minimal required columns: {missing_minimal}")
        
        # Log warnings for missing optional columns
        missing_optional = [col for col in analyzed_parameters if col not in completed_df.columns]
        if missing_optional:
            logger.warning(f"Missing optional analyzed parameters: {missing_optional}")
        
        # Normalize dmi_enabled to boolean if present
        if 'dmi_enabled' in completed_df.columns:
            # Map various representations to boolean
            dmi_mapping = {'true': True, 'True': True, '1': True, 1: True, True: True,
                          'false': False, 'False': False, '0': False, 0: False, False: False}
            completed_df['dmi_enabled'] = completed_df['dmi_enabled'].astype(str).str.lower().map(dmi_mapping)
            # Handle any unmapped values by coercing to boolean
            completed_df['dmi_enabled'] = pd.to_numeric(completed_df['dmi_enabled'], errors='coerce').astype(bool)
        
        # Coerce parameter columns to numeric
        numeric_columns = [
            'fast_period', 'slow_period', 'crossover_threshold_pips',
            'stop_loss_pips', 'take_profit_pips', 'trailing_stop_activation_pips',
            'trailing_stop_distance_pips', 'dmi_period', 'stoch_period_k',
            'stoch_period_d', 'stoch_bullish_threshold', 'stoch_bearish_threshold',
            'sharpe_ratio'
        ]
        
        for col in numeric_columns:
            if col in completed_df.columns:
                completed_df[col] = pd.to_numeric(completed_df[col], errors='coerce')
        
        # Drop rows where sharpe_ratio is NaN
        initial_count = len(completed_df)
        completed_df = completed_df.dropna(subset=['sharpe_ratio'])
        dropped_count = initial_count - len(completed_df)
        if dropped_count > 0:
            logger.warning(f"Dropped {dropped_count} rows with NaN sharpe_ratio values")
        
        logger.info(f"Successfully loaded {len(completed_df)} completed runs with all required columns")
        return completed_df
        
    except Exception as e:
        logger.error(f"Error loading Phase 5 results: {e}")
        raise

def calculate_parameter_correlations(df: pd.DataFrame) -> Tuple[Dict[str, Dict[str, float]], Set[str]]:
    """
    Calculate Pearson and Spearman correlations for each parameter with Sharpe ratio.
    
    Args:
        df: DataFrame with Phase 5 results
        
    Returns:
        Tuple of:
        - Dictionary with correlation coefficients and p-values
        - Set of parameter names that are constant (zero variance) across analyzed rows
    """
    logger.info("Calculating parameter correlations with Sharpe ratio")
    
    numeric_parameters = [
        'fast_period', 'slow_period', 'crossover_threshold_pips',
        'stop_loss_pips', 'take_profit_pips', 'trailing_stop_activation_pips',
        'trailing_stop_distance_pips', 'dmi_period', 'stoch_period_k',
        'stoch_period_d', 'stoch_bullish_threshold', 'stoch_bearish_threshold'
    ]
    
    correlations = {}
    constant_params: Set[str] = set()
    
    for param in numeric_parameters:
        if param in df.columns:
            # Remove NaN values for correlation calculation
            valid_data = df[[param, 'sharpe_ratio']].dropna()
            
            if len(valid_data) > 2:
                # Check variance before correlation calculations
                param_var = valid_data[param].var()
                sharpe_var = valid_data['sharpe_ratio'].var()
                
                # Track constant feature parameters (zero variance across analyzed rows)
                if param_var == 0:
                    constant_params.add(param)

                if param_var > 0 and sharpe_var > 0:
                    # Pearson correlation
                    pearson_corr, pearson_p = stats.pearsonr(valid_data[param], valid_data['sharpe_ratio'])
                    
                    # Spearman correlation
                    spearman_corr, spearman_p = stats.spearmanr(valid_data[param], valid_data['sharpe_ratio'])
                else:
                    # Set correlations to 0.0 and p-values to 1.0 for constant vectors
                    pearson_corr, pearson_p = 0.0, 1.0
                    spearman_corr, spearman_p = 0.0, 1.0
                
                # Ensure no NaN/Inf values
                pearson_corr = 0.0 if np.isnan(pearson_corr) or np.isinf(pearson_corr) else pearson_corr
                pearson_p = 1.0 if np.isnan(pearson_p) or np.isinf(pearson_p) else pearson_p
                spearman_corr = 0.0 if np.isnan(spearman_corr) or np.isinf(spearman_corr) else spearman_corr
                spearman_p = 1.0 if np.isnan(spearman_p) or np.isinf(spearman_p) else spearman_p
                
                correlations[param] = {
                    'sharpe_ratio': {
                        'pearson': round(pearson_corr, 4),
                        'pearson_p_value': round(pearson_p, 4),
                        'spearman': round(spearman_corr, 4),
                        'spearman_p_value': round(spearman_p, 4)
                    }
                }
            else:
                logger.warning(f"Insufficient data for correlation calculation: {param}")
                correlations[param] = {
                    'sharpe_ratio': {
                        'pearson': 0.0,
                        'pearson_p_value': 1.0,
                        'spearman': 0.0,
                        'spearman_p_value': 1.0
                    }
                }
    
    logger.info(f"Calculated correlations for {len(correlations)} parameters")
    return correlations, constant_params

def calculate_variance_contribution(df: pd.DataFrame) -> Dict[str, float]:
    """
    Calculate variance contribution for each parameter.
    
    Args:
        df: DataFrame with Phase 5 results
        
    Returns:
        Dictionary with variance contributions (0.0 to 1.0)
    """
    logger.info("Calculating variance contributions")
    
    numeric_parameters = [
        'fast_period', 'slow_period', 'crossover_threshold_pips',
        'stop_loss_pips', 'take_profit_pips', 'trailing_stop_activation_pips',
        'trailing_stop_distance_pips', 'dmi_period', 'stoch_period_k',
        'stoch_period_d', 'stoch_bullish_threshold', 'stoch_bearish_threshold'
    ]
    
    variance_contributions = {}
    total_variance = df['sharpe_ratio'].var()
    
    for param in numeric_parameters:
        if param in df.columns:
            # Check if parameter has many unique values and sparse counts
            unique_values = df[param].nunique()
            total_count = len(df[param].dropna())
            
            # Group by unique parameter values and calculate group means
            grouped = df.groupby(param)['sharpe_ratio'].agg(['mean', 'count']).reset_index()
            grouped = grouped[grouped['count'] >= 2]  # Require at least 2 samples per group
            
            if len(grouped) > 1:
                # Check if we should use binning for continuous parameters
                if unique_values > 10 and (grouped['count'] < 3).any():
                    # Use quantile binning for continuous parameters with sparse counts
                    try:
                        df_binned = df.copy()
                        df_binned[f'{param}_binned'] = pd.qcut(df_binned[param], q=5, duplicates='drop')
                        grouped = df_binned.groupby(f'{param}_binned')['sharpe_ratio'].agg(['mean', 'count']).reset_index()
                        grouped = grouped[grouped['count'] >= 2]
                    except ValueError:
                        # Fallback to equal-width binning if quantile fails
                        df_binned = df.copy()
                        df_binned[f'{param}_binned'] = pd.cut(df_binned[param], bins=5, duplicates='drop')
                        grouped = df_binned.groupby(f'{param}_binned')['sharpe_ratio'].agg(['mean', 'count']).reset_index()
                        grouped = grouped[grouped['count'] >= 2]
                
                if len(grouped) > 1:
                    # Calculate between-group variance
                    group_means = grouped['mean']
                    group_weights = grouped['count'] / grouped['count'].sum()
                    weighted_mean = (group_means * group_weights).sum()
                    between_group_var = ((group_means - weighted_mean) ** 2 * group_weights).sum()
                    
                    # Calculate proportion of total variance
                    variance_contribution = between_group_var / total_variance if total_variance > 0 else 0.0
                    variance_contributions[param] = round(variance_contribution, 4)
                else:
                    variance_contributions[param] = 0.0
            else:
                variance_contributions[param] = 0.0
    
    logger.info(f"Calculated variance contributions for {len(variance_contributions)} parameters")
    return variance_contributions

def calculate_parameter_stability(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """
    Calculate parameter stability metrics for top 10 results.
    
    Args:
        df: DataFrame with Phase 5 results
        
    Returns:
        Dictionary with stability metrics for each parameter
    """
    logger.info("Calculating parameter stability for top 10 results")
    
    # Get top 10 results by Sharpe ratio
    top_10 = df.nlargest(10, 'sharpe_ratio')
    
    numeric_parameters = [
        'fast_period', 'slow_period', 'crossover_threshold_pips',
        'stop_loss_pips', 'take_profit_pips', 'trailing_stop_activation_pips',
        'trailing_stop_distance_pips', 'dmi_period', 'stoch_period_k',
        'stoch_period_d', 'stoch_bullish_threshold', 'stoch_bearish_threshold'
    ]
    
    stability_metrics = {}
    
    for param in numeric_parameters:
        if param in top_10.columns:
            values = top_10[param].dropna()
            
            if len(values) > 0:
                mean_val = values.mean()
                std_val = values.std()
                
                # Handle edge cases for CV calculation
                epsilon = 1e-9
                if std_val == 0:
                    cv = 0.0  # No variation
                    stability_rating = 'high'
                elif abs(mean_val) < epsilon:
                    cv = 1000.0  # Large sentinel value for near-zero mean
                    stability_rating = 'undefined'
                else:
                    cv = std_val / abs(mean_val)
                    # Classify stability
                    if cv < 0.1:
                        stability_rating = 'high'
                    elif cv < 0.3:
                        stability_rating = 'medium'
                    else:
                        stability_rating = 'low'
                
                stability_metrics[param] = {
                    'mean_value': round(mean_val, 4),
                    'std_dev': round(std_val, 4),
                    'coefficient_of_variation': round(cv, 4),
                    'stability_rating': stability_rating,
                    'min_value': round(values.min(), 4),
                    'max_value': round(values.max(), 4)
                }
            else:
                stability_metrics[param] = {
                    'mean_value': 0.0,
                    'std_dev': 0.0,
                    'coefficient_of_variation': 0.0,
                    'stability_rating': 'low',
                    'min_value': 0.0,
                    'max_value': 0.0
                }
    
    logger.info(f"Calculated stability metrics for {len(stability_metrics)} parameters")
    return stability_metrics

def identify_top_4_sensitive_parameters(correlations: Dict, variance_contributions: Dict, 
                                     stability_metrics: Dict) -> List[Dict[str, Any]]:
    """
    Identify the top 4 most sensitive parameters using combined scoring.
    
    Args:
        correlations: Parameter correlation results
        variance_contributions: Variance contribution results
        stability_metrics: Parameter stability results
        
    Returns:
        List of top 4 parameters with sensitivity scores
    """
    logger.info("Identifying top 4 sensitive parameters")
    
    # Calculate combined sensitivity scores
    sensitivity_scores = {}
    
    for param in correlations.keys():
        if param in variance_contributions and param in stability_metrics:
            # Get absolute Pearson correlation
            abs_correlation = abs(correlations[param]['sharpe_ratio']['pearson'])
            
            # Get variance contribution
            variance_contrib = variance_contributions[param]
            
            # Combined score: 60% correlation + 40% variance
            sensitivity_score = 0.6 * abs_correlation + 0.4 * variance_contrib
            
            sensitivity_scores[param] = {
                'parameter_name': param,
                'sensitivity_score': round(sensitivity_score, 4),
                'pearson_correlation': correlations[param]['sharpe_ratio']['pearson'],
                'spearman_correlation': correlations[param]['sharpe_ratio']['spearman'],
                'variance_contribution': variance_contrib,
                'stability_rating': stability_metrics[param]['stability_rating']
            }
    
    # Sort by sensitivity score and get top 4
    sorted_params = sorted(sensitivity_scores.items(), key=lambda x: x[1]['sensitivity_score'], reverse=True)
    top_4 = sorted_params[:4]
    
    # Add rationale for each parameter
    top_4_with_rationale = []
    for rank, (param, metrics) in enumerate(top_4, 1):
        rationale = f"High sensitivity score ({metrics['sensitivity_score']:.3f}) due to "
        rationale += f"correlation ({abs(metrics['pearson_correlation']):.3f}) and "
        rationale += f"variance contribution ({metrics['variance_contribution']:.3f})"
        
        top_4_with_rationale.append({
            'rank': rank,
            'parameter_name': param,
            'sensitivity_score': metrics['sensitivity_score'],
            'pearson_correlation': metrics['pearson_correlation'],
            'spearman_correlation': metrics['spearman_correlation'],
            'variance_contribution': metrics['variance_contribution'],
            'stability_rating': metrics['stability_rating'],
            'rationale': rationale
        })
    
    logger.info(f"Identified top 4 sensitive parameters: {[p['parameter_name'] for p in top_4_with_rationale]}")
    return top_4_with_rationale

def analyze_boolean_parameters(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyze boolean parameter (dmi_enabled) impact on Sharpe ratio.
    
    Args:
        df: DataFrame with Phase 5 results
        
    Returns:
        Dictionary with boolean parameter analysis results
    """
    logger.info("Analyzing boolean parameter (dmi_enabled)")
    
    if 'dmi_enabled' not in df.columns:
        logger.warning("dmi_enabled column not found")
        return {}
    
    # Split data by dmi_enabled values
    dmi_true = df[df['dmi_enabled'] == True]['sharpe_ratio'].dropna()
    dmi_false = df[df['dmi_enabled'] == False]['sharpe_ratio'].dropna()
    
    if len(dmi_true) > 0 and len(dmi_false) > 0:
        # Calculate statistics
        true_mean = dmi_true.mean()
        true_std = dmi_true.std()
        false_mean = dmi_false.mean()
        false_std = dmi_false.std()
        
        # Perform statistical test with fallback options
        test_used = "equal_var_t_test"
        
        # Check for normality and sample size requirements
        if len(dmi_true) >= 3 and len(dmi_false) >= 3:
            # Try Shapiro-Wilk test for normality (only for small samples)
            if len(dmi_true) <= 5000 and len(dmi_false) <= 5000:
                try:
                    _, p_true = stats.shapiro(dmi_true)
                    _, p_false = stats.shapiro(dmi_false)
                    normal_data = p_true > 0.05 and p_false > 0.05
                except:
                    normal_data = True  # Assume normal if test fails
            else:
                normal_data = True  # Assume normal for large samples
            
            # Check for equal variances
            if normal_data:
                try:
                    _, p_var = stats.levene(dmi_true, dmi_false)
                    equal_var = p_var > 0.05
                except:
                    equal_var = False  # Assume unequal variance if test fails
            else:
                equal_var = False
            
            if normal_data and equal_var:
                # Equal variance t-test
                t_stat, t_p_value = stats.ttest_ind(dmi_true, dmi_false, equal_var=True)
                test_used = "equal_var_t_test"
            elif normal_data:
                # Unequal variance t-test
                t_stat, t_p_value = stats.ttest_ind(dmi_true, dmi_false, equal_var=False)
                test_used = "unequal_var_t_test"
            else:
                # Non-parametric Mann-Whitney U test
                t_stat, t_p_value = stats.mannwhitneyu(dmi_true, dmi_false, alternative='two-sided')
                test_used = "mann_whitney_u"
        else:
            # Fallback to unequal variance t-test for small samples
            t_stat, t_p_value = stats.ttest_ind(dmi_true, dmi_false, equal_var=False)
            test_used = "unequal_var_t_test_fallback"
        
        # Calculate effect size (Cohen's d)
        pooled_std = np.sqrt(((len(dmi_true) - 1) * true_std**2 + (len(dmi_false) - 1) * false_std**2) / 
                           (len(dmi_true) + len(dmi_false) - 2))
        cohens_d = (true_mean - false_mean) / pooled_std if pooled_std > 0 else 0.0
        
        # Determine conclusion
        if abs(cohens_d) < 0.2:
            conclusion = "Minimal impact on Sharpe ratio"
        elif abs(cohens_d) < 0.5:
            conclusion = "Small impact on Sharpe ratio"
        elif abs(cohens_d) < 0.8:
            conclusion = "Medium impact on Sharpe ratio"
        else:
            conclusion = "Large impact on Sharpe ratio"
        
        return {
            'parameter_name': 'dmi_enabled',
            'true_sharpe_mean': round(true_mean, 4),
            'true_sharpe_std': round(true_std, 4),
            'false_sharpe_mean': round(false_mean, 4),
            'false_sharpe_std': round(false_std, 4),
            't_test_p_value': round(t_p_value, 4),
            'effect_size': round(cohens_d, 4),
            'test_used': test_used,
            'conclusion': conclusion
        }
    else:
        logger.warning("Insufficient data for boolean parameter analysis")
        return {}

def generate_phase5_sensitivity_report(df: pd.DataFrame, correlations: Dict, 
                                    variance_contributions: Dict, stability_metrics: Dict,
                                    top_4_parameters: List[Dict], boolean_analysis: Dict,
                                    source_csv_path: str) -> Dict[str, Any]:
    """
    Generate comprehensive Phase 5 sensitivity analysis report.
    
    Args:
        df: DataFrame with Phase 5 results
        correlations: Parameter correlation results
        variance_contributions: Variance contribution results
        stability_metrics: Parameter stability results
        top_4_parameters: Top 4 sensitive parameters
        boolean_analysis: Boolean parameter analysis results
        
    Returns:
        Complete sensitivity analysis report
    """
    logger.info("Generating comprehensive sensitivity analysis report")
    
    # Get best Sharpe ratio
    best_sharpe = df['sharpe_ratio'].max()
    
    # Identify remaining parameters (not in top 4)
    all_parameters = list(correlations.keys())
    top_4_names = [p['parameter_name'] for p in top_4_parameters]
    remaining_parameters = [p for p in all_parameters if p not in top_4_names]
    
    # Get best values for remaining parameters (from best result)
    best_result = df.loc[df['sharpe_ratio'].idxmax()]
    remaining_parameters_list = []
    
    for param in remaining_parameters:
        if param in best_result.index:
            remaining_parameters_list.append({
                'parameter_name': param,
                'sensitivity_score': 0.0,  # Not selected for refinement
                'phase5_best_value': best_result[param],
                'rationale': f"Low sensitivity, fix at Phase 5 best value ({best_result[param]})"
            })
    
    # Generate recommendations
    remaining_count = len(remaining_parameters_list)
    recommendations = [
        f"Refine 4 most sensitive parameters: {', '.join(top_4_names)}",
        f"Fix {remaining_count} remaining parameters at Phase 5 best values",
        "Expected Phase 6 combinations: 200-300 (vs 5.9M current)",
        "Expected runtime reduction: 4-6 hours (vs 20-40 hours current)",
        "Use ±10% ranges around Phase 5 best values for top 4 parameters"
    ]
    
    # Phase 6 configuration suggestion
    phase6_config = {
        'parameters_to_refine': top_4_names,
        'parameters_to_fix': {param: best_result[param] for param in remaining_parameters if param in best_result.index},
        'estimated_combinations': 250,  # Rough estimate
        'estimated_runtime_hours': 5    # Rough estimate
    }
    
    report = {
        'metadata': {
            'analysis_date': pd.Timestamp.now().isoformat(),
            'phase': 'Phase 5 Sensitivity Analysis',
            'dataset_size': len(df),
            'best_sharpe_ratio': round(best_sharpe, 4),
            'parameters_analyzed': len(all_parameters),
            'objectives_analyzed': ['sharpe_ratio'],
            'source_csv': str(Path(source_csv_path).resolve())
        },
        'parameter_correlations': correlations,
        'variance_contributions': variance_contributions,
        'parameter_stability': stability_metrics,
        'top_4_sensitive_parameters': top_4_parameters,
        'remaining_parameters': remaining_parameters_list,
        'boolean_parameter_analysis': boolean_analysis,
        'recommendations': recommendations,
        'phase6_configuration_suggestion': phase6_config
    }
    
    logger.info("Generated comprehensive sensitivity analysis report")
    return report

def export_sensitivity_report(report: Dict[str, Any], output_dir: str, constant_params: Set[str]) -> None:
    """
    Export sensitivity analysis results to multiple formats.
    
    Args:
        report: Complete sensitivity analysis report
        output_dir: Output directory path
    """
    logger.info(f"Exporting sensitivity analysis results to {output_dir}")
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Export JSON (complete data)
    json_path = output_path / 'phase5_sensitivity_analysis.json'
    with open(json_path, 'w') as f:
        json.dump(_make_json_safe(report), f, indent=2, allow_nan=False)
    logger.info(f"Exported JSON report: {json_path}")
    
    # Export Markdown report
    md_path = output_path / 'PHASE5_SENSITIVITY_REPORT.md'
    generate_markdown_report(report, md_path, constant_params)
    logger.info(f"Exported Markdown report: {md_path}")
    
    # Export CSV correlation matrix
    csv_path = output_path / 'phase5_correlation_matrix.csv'
    generate_correlation_csv(report, csv_path, constant_params)
    logger.info(f"Exported CSV correlation matrix: {csv_path}")

def generate_markdown_report(report: Dict[str, Any], output_path: Path, constant_params: Set[str]) -> None:
    """Generate human-readable Markdown report."""
    
    with open(output_path, 'w') as f:
        f.write("# Phase 5 Parameter Sensitivity Analysis Report\n\n")
        
        # Executive Summary
        f.write("## Executive Summary\n\n")
        f.write(f"**Analysis Date:** {report['metadata']['analysis_date']}\n")
        f.write(f"**Dataset Size:** {report['metadata']['dataset_size']} completed runs\n")
        f.write(f"**Best Sharpe Ratio:** {report['metadata']['best_sharpe_ratio']}\n")
        f.write(f"**Parameters Analyzed:** {report['metadata']['parameters_analyzed']}\n\n")
        
        # Top 4 Parameters
        f.write("## Top 4 Most Sensitive Parameters\n\n")
        f.write("| Rank | Parameter | Sensitivity Score | Pearson Corr | Spearman Corr | Variance Contrib | Stability |\n")
        f.write("|------|-----------|------------------|--------------|---------------|------------------|----------|\n")
        
        for param in report['top_4_sensitive_parameters']:
            f.write(f"| {param['rank']} | {param['parameter_name']} | {param['sensitivity_score']:.3f} | "
                   f"{param['pearson_correlation']:.3f} | {param['spearman_correlation']:.3f} | "
                   f"{param['variance_contribution']:.3f} | {param['stability_rating']} |\n")
        
        f.write("\n")
        
        # All Parameters Correlation
        f.write("## All Parameters Correlation Analysis\n\n")
        f.write("| Parameter | Pearson Corr | Pearson P-Value | Spearman Corr | Spearman P-Value |\n")
        f.write("|-----------|--------------|-----------------|---------------|------------------|\n")
        
        # Sort by absolute correlation
        sorted_correlations = sorted(report['parameter_correlations'].items(), 
                                  key=lambda x: abs(x[1]['sharpe_ratio']['pearson']), reverse=True)
        
        for param, corr_data in sorted_correlations:
            f.write(f"| {param} | {corr_data['sharpe_ratio']['pearson']:.3f} | "
                   f"{corr_data['sharpe_ratio']['pearson_p_value']:.4f} | "
                   f"{corr_data['sharpe_ratio']['spearman']:.3f} | "
                   f"{corr_data['sharpe_ratio']['spearman_p_value']:.4f} |\n")
        
        f.write("\n")
        # Add note about constant features
        if constant_params:
            const_list = ", ".join(sorted(constant_params))
            f.write("> Note: Correlation is not defined for parameters with zero variance across analyzed rows. "
                    "These constant features are shown with numeric placeholders (0.0, p=1.0): "
                    f"{const_list}.\n\n")
        else:
            f.write(
                "> Note: Correlation is not defined for parameters with zero variance across analyzed rows. "
                "If present, such constant features will be shown with numeric placeholders (0.0, p=1.0).\n\n"
            )
        
        # Variance Contributions
        f.write("## Variance Contribution Analysis\n\n")
        f.write("| Parameter | Variance Contribution |\n")
        f.write("|-----------|----------------------|\n")
        
        sorted_variance = sorted(report['variance_contributions'].items(), 
                               key=lambda x: x[1], reverse=True)
        
        for param, contrib in sorted_variance:
            f.write(f"| {param} | {contrib:.3f} |\n")
        
        f.write("\n")
        
        # Parameter Stability
        f.write("## Parameter Stability Analysis (Top 10 Results)\n\n")
        f.write("| Parameter | Mean | Std Dev | CV | Stability | Min | Max |\n")
        f.write("|-----------|------|---------|----|-----------|-----|-----|\n")
        
        for param, stability in report['parameter_stability'].items():
            f.write(f"| {param} | {stability['mean_value']:.2f} | {stability['std_dev']:.2f} | "
                   f"{stability['coefficient_of_variation']:.3f} | {stability['stability_rating']} | "
                   f"{stability['min_value']:.2f} | {stability['max_value']:.2f} |\n")
        
        f.write("\n")
        
        # Boolean Parameter Analysis
        if report['boolean_parameter_analysis']:
            f.write("## Boolean Parameter Analysis (dmi_enabled)\n\n")
            bool_analysis = report['boolean_parameter_analysis']
            f.write(f"**True Values:** Mean={bool_analysis['true_sharpe_mean']:.3f}, "
                   f"Std={bool_analysis['true_sharpe_std']:.3f}\n")
            f.write(f"**False Values:** Mean={bool_analysis['false_sharpe_mean']:.3f}, "
                   f"Std={bool_analysis['false_sharpe_std']:.3f}\n")
            f.write(f"**Statistical Test:** {bool_analysis['test_used']}\n")
            f.write(f"**P-value:** {bool_analysis['t_test_p_value']:.4f}\n")
            f.write(f"**Effect Size (Cohen's d):** {bool_analysis['effect_size']:.3f}\n")
            f.write(f"**Conclusion:** {bool_analysis['conclusion']}\n\n")
        
        # Recommendations
        f.write("## Recommendations for Phase 6\n\n")
        for i, rec in enumerate(report['recommendations'], 1):
            f.write(f"{i}. {rec}\n")
        
        f.write("\n")
        
        # Next Steps
        f.write("## Next Steps\n\n")
        f.write("1. Review the top 4 sensitive parameters identified above\n")
        f.write("2. Update `optimization/configs/phase6_refinement.yaml` to refine only these 4 parameters\n")
        remaining_count = len(report.get('remaining_parameters', []))
        f.write(f"3. Fix the remaining {remaining_count} parameters at their Phase 5 best values\n")
        f.write("4. Run Phase 6 with the updated configuration\n\n")

def generate_correlation_csv(report: Dict[str, Any], output_path: Path, constant_params: Set[str]) -> None:
    """Generate CSV correlation matrix."""
    
    with open(output_path, 'w') as f:
        f.write("parameter,objective,pearson_correlation,pearson_p_value,spearman_correlation,spearman_p_value,variance_contribution,stability_rating\n")
        
        # Sort by absolute correlation
        sorted_correlations = sorted(report['parameter_correlations'].items(), 
                                  key=lambda x: abs(x[1]['sharpe_ratio']['pearson']), reverse=True)
        
        for param, corr_data in sorted_correlations:
            variance_contrib = report['variance_contributions'].get(param, 0.0)
            # Use 'undefined' stability for constant features in correlation outputs
            if param in constant_params:
                stability_rating = 'undefined'
            else:
                stability_rating = report['parameter_stability'].get(param, {}).get('stability_rating', 'unknown')
            
            f.write(f"{param},sharpe_ratio,{corr_data['sharpe_ratio']['pearson']:.3f},"
                   f"{corr_data['sharpe_ratio']['pearson_p_value']:.4f},"
                   f"{corr_data['sharpe_ratio']['spearman']:.3f},"
                   f"{corr_data['sharpe_ratio']['spearman_p_value']:.4f},"
                   f"{variance_contrib:.3f},{stability_rating}\n")

def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description='Phase 5 Parameter Sensitivity Analysis')
    parser.add_argument('--csv', required=True, help='Path to phase5_filters_results.csv')
    parser.add_argument('--output-dir', required=True, help='Output directory for results')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Load Phase 5 results
        df = load_phase5_results(args.csv)
        
        # Perform sensitivity analysis
        correlations, constant_params = calculate_parameter_correlations(df)
        variance_contributions = calculate_variance_contribution(df)
        stability_metrics = calculate_parameter_stability(df)
        top_4_parameters = identify_top_4_sensitive_parameters(correlations, variance_contributions, stability_metrics)
        boolean_analysis = analyze_boolean_parameters(df)
        
        # Generate comprehensive report
        report = generate_phase5_sensitivity_report(
            df, correlations, variance_contributions, stability_metrics, top_4_parameters, boolean_analysis, args.csv
        )
        
        # Export results
        export_sensitivity_report(report, args.output_dir, constant_params)
        
        # Display summary
        print("\n" + "="*60)
        print("PHASE 5 SENSITIVITY ANALYSIS COMPLETE")
        print("="*60)
        print(f"Dataset: {len(df)} completed runs")
        print(f"Best Sharpe Ratio: {report['metadata']['best_sharpe_ratio']}")
        print("\nTop 4 Most Sensitive Parameters:")
        for param in top_4_parameters:
            print(f"  {param['rank']}. {param['parameter_name']}: {param['sensitivity_score']:.3f}")
        print(f"\nResults exported to: {args.output_dir}")
        print("Next step: Update phase6_refinement.yaml based on findings")
        print("="*60)
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()