#!/usr/bin/env python3
"""
Parameter Sensitivity Analysis Tool for Phase 6 Optimization Results

This script analyzes how each parameter affects multiple objectives using Phase 6 results.
It performs correlation analysis, variance decomposition, and parameter stability assessment.
"""

import pandas as pd
import numpy as np
import json
import argparse
import sys
import pathlib
import logging
from scipy import stats
from typing import Dict, List, Any, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_results(csv_path: str) -> pd.DataFrame:
    """Load Phase 6 results CSV and validate required columns."""
    try:
        df = pd.read_csv(csv_path)
        logger.info(f"Loaded {len(df)} results from {csv_path}")
        
        # Filter to completed runs only
        if 'status' in df.columns:
            df = df[df['status'] == 'completed']
            logger.info(f"Filtered to {len(df)} completed runs")
        
        # Validate required columns exist
        required_columns = [
            'fast_period', 'slow_period', 'crossover_threshold_pips',
            'stop_loss_pips', 'take_profit_pips', 'trailing_distance_pips',
            'dmi_enabled', 'dmi_period', 'stoch_period_k', 'stoch_period_d',
            'stoch_bullish_threshold', 'stoch_bearish_threshold',
            'sharpe_ratio', 'total_pnl', 'max_drawdown'
        ]
        
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns: {missing_columns}")
        
        return df
        
    except Exception as e:
        logger.error(f"Error loading results: {e}")
        sys.exit(1)

def calculate_parameter_correlations(df: pd.DataFrame, objectives: List[str]) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Calculate Pearson and Spearman correlations for each parameter with each objective."""
    correlations = {}
    
    # Get numeric parameters (exclude boolean and categorical)
    numeric_params = [
        'fast_period', 'slow_period', 'crossover_threshold_pips',
        'stop_loss_pips', 'take_profit_pips', 'trailing_distance_pips',
        'dmi_period', 'stoch_period_k', 'stoch_period_d',
        'stoch_bullish_threshold', 'stoch_bearish_threshold'
    ]
    
    for param in numeric_params:
        if param not in df.columns:
            continue
            
        correlations[param] = {}
        
        for objective in objectives:
            if objective not in df.columns:
                continue
                
            # Remove NaN values
            mask = ~(df[param].isna() | df[objective].isna())
            if mask.sum() < 10:  # Need at least 10 valid pairs
                continue
                
            x = df[param][mask]
            y = df[objective][mask]
            
            # Calculate Pearson correlation
            pearson_r, pearson_p = stats.pearsonr(x, y)
            
            # Calculate Spearman correlation
            spearman_r, spearman_p = stats.spearmanr(x, y)
            
            correlations[param][objective] = {
                'pearson': pearson_r,
                'pearson_p_value': pearson_p,
                'spearman': spearman_r,
                'spearman_p_value': spearman_p
            }
    
    return correlations

def calculate_parameter_variance_contribution(df: pd.DataFrame, objectives: List[str]) -> Dict[str, Dict[str, float]]:
    """Calculate variance contribution for each parameter on each objective."""
    variance_contributions = {}
    
    numeric_params = [
        'fast_period', 'slow_period', 'crossover_threshold_pips',
        'stop_loss_pips', 'take_profit_pips', 'trailing_distance_pips',
        'dmi_period', 'stoch_period_k', 'stoch_period_d',
        'stoch_bullish_threshold', 'stoch_bearish_threshold'
    ]
    
    for param in numeric_params:
        if param not in df.columns:
            continue
            
        variance_contributions[param] = {}
        
        for objective in objectives:
            if objective not in df.columns:
                continue
                
            # Remove NaN values
            mask = ~(df[param].isna() | df[objective].isna())
            if mask.sum() < 10:
                continue
                
            param_values = df[param][mask]
            objective_values = df[objective][mask]
            
            # Calculate total variance
            total_var = np.var(objective_values)
            if total_var == 0:
                continue
                
            # Group by parameter value and calculate between-group variance
            unique_values = param_values.unique()
            if len(unique_values) < 2:
                continue
                
            group_means = []
            group_sizes = []
            
            for value in unique_values:
                group_mask = param_values == value
                group_data = objective_values[group_mask]
                if len(group_data) > 0:
                    group_means.append(np.mean(group_data))
                    group_sizes.append(len(group_data))
            
            if len(group_means) < 2:
                continue
                
            # Calculate between-group variance
            overall_mean = np.mean(objective_values)
            between_var = np.sum([size * (mean - overall_mean)**2 for mean, size in zip(group_means, group_sizes)]) / len(objective_values)
            
            # Calculate variance contribution
            variance_contribution = between_var / total_var
            variance_contributions[param][objective] = variance_contribution
    
    return variance_contributions

def identify_sensitive_parameters(correlations: Dict, variance_contributions: Dict, threshold: float = 0.1) -> Dict[str, Dict[str, Any]]:
    """Identify parameters with high sensitivity based on correlations and variance contributions."""
    sensitive_params = {}
    
    for param in correlations:
        if param not in variance_contributions:
            continue
            
        # Calculate average absolute correlation across objectives
        avg_abs_correlation = 0
        affects_objectives = []
        
        for objective in correlations[param]:
            abs_corr = abs(correlations[param][objective]['pearson'])
            avg_abs_correlation += abs_corr
            
            if abs_corr > threshold:
                affects_objectives.append(objective)
        
        if len(correlations[param]) > 0:
            avg_abs_correlation /= len(correlations[param])
        
        # Check variance contribution
        avg_variance_contribution = 0
        for objective in variance_contributions[param]:
            avg_variance_contribution += variance_contributions[param][objective]
        
        if len(variance_contributions[param]) > 0:
            avg_variance_contribution /= len(variance_contributions[param])
        
        # Determine if parameter is sensitive
        is_sensitive = (avg_abs_correlation > threshold or 
                       avg_variance_contribution > threshold or 
                       len(affects_objectives) > 0)
        
        if is_sensitive:
            sensitive_params[param] = {
                'sensitivity_score': avg_abs_correlation,
                'variance_contribution': avg_variance_contribution,
                'affects_objectives': affects_objectives,
                'avg_abs_correlation': avg_abs_correlation
            }
    
    # Sort by sensitivity score
    sensitive_params = dict(sorted(sensitive_params.items(), 
                                 key=lambda x: x[1]['sensitivity_score'], 
                                 reverse=True))
    
    return sensitive_params

def analyze_parameter_stability(df: pd.DataFrame, parameters: List[str]) -> Dict[str, Dict[str, float]]:
    """Analyze parameter stability in top 10 results."""
    stability = {}
    
    # Get top 10 results by Sharpe ratio
    top_10 = df.nlargest(10, 'sharpe_ratio')
    
    for param in parameters:
        if param not in df.columns:
            continue
            
        param_values = top_10[param]
        
        # Calculate statistics
        std_dev = np.std(param_values)
        mean_val = np.mean(param_values)
        
        if mean_val != 0:
            coefficient_of_variation = std_dev / abs(mean_val)
        else:
            coefficient_of_variation = float('inf')
        
        # Determine stability rating
        if coefficient_of_variation < 0.1:
            stability_rating = "high"
        elif coefficient_of_variation < 0.3:
            stability_rating = "medium"
        else:
            stability_rating = "low"
        
        stability[param] = {
            'std_dev': std_dev,
            'coefficient_of_variation': coefficient_of_variation,
            'stability_rating': stability_rating,
            'mean_value': mean_val,
            'min_value': np.min(param_values),
            'max_value': np.max(param_values)
        }
    
    return stability

def generate_sensitivity_report(correlations: Dict, variance_contributions: Dict, 
                             sensitive_params: Dict, stability: Dict) -> Dict[str, Any]:
    """Generate comprehensive sensitivity report."""
    report = {
        'parameter_correlations': correlations,
        'variance_contributions': variance_contributions,
        'sensitive_parameters': sensitive_params,
        'parameter_stability': stability,
        'recommendations': []
    }
    
    # Generate insights
    if sensitive_params:
        top_sensitive = list(sensitive_params.keys())[:5]
        report['recommendations'].append(
            f"Parameters with strongest impact on Sharpe ratio: {', '.join(top_sensitive)}"
        )
    
    # Identify stable parameters
    stable_params = [param for param, data in stability.items() 
                    if data['stability_rating'] == 'high']
    if stable_params:
        report['recommendations'].append(
            f"Most stable parameters (low variance in top 10): {', '.join(stable_params)}"
        )
    
    # Identify parameters requiring refinement
    unstable_params = [param for param, data in stability.items() 
                      if data['stability_rating'] == 'low']
    if unstable_params:
        report['recommendations'].append(
            f"Parameters requiring further refinement: {', '.join(unstable_params)}"
        )
    
    return report

def export_sensitivity_report(report: Dict[str, Any], output_path: str) -> None:
    """Export sensitivity report to multiple formats."""
    output_dir = pathlib.Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Export JSON
    json_path = output_dir / "phase6_sensitivity_analysis.json"
    with open(json_path, 'w') as f:
        json.dump(report, f, indent=2)
    logger.info(f"Exported sensitivity analysis to {json_path}")
    
    # Generate markdown summary
    md_path = output_dir / "phase6_sensitivity_summary.md"
    with open(md_path, 'w') as f:
        f.write("# Phase 6 Parameter Sensitivity Analysis Summary\n\n")
        
        # Sensitive parameters
        f.write("## Most Sensitive Parameters\n\n")
        if report['sensitive_parameters']:
            f.write("| Parameter | Sensitivity Score | Variance Contribution | Affects Objectives |\n")
            f.write("|-----------|------------------|----------------------|-------------------|\n")
            for param, data in report['sensitive_parameters'].items():
                f.write(f"| {param} | {data['sensitivity_score']:.3f} | {data['variance_contribution']:.3f} | {', '.join(data['affects_objectives'])} |\n")
        else:
            f.write("No highly sensitive parameters identified.\n")
        
        # Parameter stability
        f.write("\n## Parameter Stability Analysis\n\n")
        f.write("| Parameter | CV | Stability | Mean | Range |\n")
        f.write("|-----------|----|-----------|------|-------|\n")
        for param, data in report['parameter_stability'].items():
            f.write(f"| {param} | {data['coefficient_of_variation']:.3f} | {data['stability_rating']} | {data['mean_value']:.2f} | {data['min_value']:.2f}-{data['max_value']:.2f} |\n")
        
        # Recommendations
        f.write("\n## Recommendations\n\n")
        for rec in report['recommendations']:
            f.write(f"- {rec}\n")
    
    logger.info(f"Exported sensitivity summary to {md_path}")
    
    # Export correlation matrix CSV
    csv_path = output_dir / "phase6_correlation_matrix.csv"
    correlation_data = []
    for param in report['parameter_correlations']:
        for objective in report['parameter_correlations'][param]:
            correlation_data.append({
                'parameter': param,
                'objective': objective,
                'pearson_correlation': report['parameter_correlations'][param][objective]['pearson'],
                'spearman_correlation': report['parameter_correlations'][param][objective]['spearman'],
                'pearson_p_value': report['parameter_correlations'][param][objective]['pearson_p_value'],
                'spearman_p_value': report['parameter_correlations'][param][objective]['spearman_p_value']
            })
    
    if correlation_data:
        corr_df = pd.DataFrame(correlation_data)
        corr_df.to_csv(csv_path, index=False)
        logger.info(f"Exported correlation matrix to {csv_path}")

def main():
    """Main function to run parameter sensitivity analysis."""
    parser = argparse.ArgumentParser(description='Analyze parameter sensitivity from Phase 6 results')
    parser.add_argument('--csv', default='optimization/results/phase6_refinement_results.csv',
                       help='Path to Phase 6 results CSV')
    parser.add_argument('--objectives', nargs='+', 
                       default=['sharpe_ratio', 'total_pnl', 'max_drawdown'],
                       help='List of objectives to analyze')
    parser.add_argument('--output-dir', default='optimization/results',
                       help='Output directory for reports')
    parser.add_argument('--threshold', type=float, default=0.1,
                       help='Sensitivity threshold')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("Starting parameter sensitivity analysis...")
    
    # Load results
    df = load_results(args.csv)
    
    # Calculate correlations
    logger.info("Calculating parameter correlations...")
    correlations = calculate_parameter_correlations(df, args.objectives)
    
    # Calculate variance contributions
    logger.info("Calculating variance contributions...")
    variance_contributions = calculate_parameter_variance_contribution(df, args.objectives)
    
    # Identify sensitive parameters
    logger.info("Identifying sensitive parameters...")
    sensitive_params = identify_sensitive_parameters(correlations, variance_contributions, args.threshold)
    
    # Analyze parameter stability
    logger.info("Analyzing parameter stability...")
    # Restrict to valid parameter names only
    valid_params = [
        'fast_period', 'slow_period', 'crossover_threshold_pips',
        'stop_loss_pips', 'take_profit_pips', 'trailing_distance_pips',
        'trailing_activation_pips', 'dmi_period', 'stoch_period_k', 'stoch_period_d',
        'stoch_bullish_threshold', 'stoch_bearish_threshold'
    ]
    stability = analyze_parameter_stability(df, valid_params)
    
    # Generate sensitivity report
    logger.info("Generating sensitivity report...")
    report = generate_sensitivity_report(correlations, variance_contributions, sensitive_params, stability)
    
    # Export reports
    export_sensitivity_report(report, args.output_dir)
    
    # Print summary
    print("\n" + "="*60)
    print("PARAMETER SENSITIVITY ANALYSIS SUMMARY")
    print("="*60)
    print(f"Total parameters analyzed: {len(correlations)}")
    print(f"Sensitive parameters identified: {len(sensitive_params)}")
    print(f"Stable parameters: {len([p for p, d in stability.items() if d['stability_rating'] == 'high'])}")
    print(f"Unstable parameters: {len([p for p, d in stability.items() if d['stability_rating'] == 'low'])}")
    
    if sensitive_params:
        print(f"\nTop 5 most sensitive parameters:")
        for i, (param, data) in enumerate(list(sensitive_params.items())[:5], 1):
            print(f"  {i}. {param}: sensitivity={data['sensitivity_score']:.3f}")
    
    print(f"\nReports exported to: {args.output_dir}")
    print("="*60)

if __name__ == "__main__":
    main()
