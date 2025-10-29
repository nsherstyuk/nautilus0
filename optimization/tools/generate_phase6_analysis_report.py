#!/usr/bin/env python3
"""
Phase 6 Comprehensive Analysis Report Generator

This script generates the comprehensive PHASE6_ANALYSIS_REPORT.md combining 
sensitivity analysis, Pareto frontier analysis, and top 5 parameter set recommendations.
"""

import json
import pandas as pd
import argparse
import sys
import pathlib
import logging
from datetime import datetime
from typing import Dict, List, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_all_phase6_artifacts(results_dir: str) -> Dict[str, Any]:
    """Load all Phase 6 output files."""
    artifacts = {}
    results_path = pathlib.Path(results_dir)
    
    # List of required files
    required_files = {
        'results_csv': 'phase6_refinement_results.csv',
        'top_10_json': 'phase6_refinement_results_top_10.json',
        'summary_json': 'phase6_refinement_results_summary.json',
        'pareto_json': 'phase6_refinement_results_pareto_frontier.json',
        'sensitivity_json': 'phase6_sensitivity_analysis.json',
        'top_5_json': 'phase6_top_5_parameters.json'
    }
    
    for key, filename in required_files.items():
        file_path = results_path / filename
        if file_path.exists():
            try:
                if filename.endswith('.csv'):
                    artifacts[key] = pd.read_csv(file_path)
                else:
                    with open(file_path, 'r') as f:
                        artifacts[key] = json.load(f)
                logger.info(f"Loaded {filename}")
            except Exception as e:
                logger.warning(f"Could not load {filename}: {e}")
                artifacts[key] = None
        else:
            logger.warning(f"File not found: {filename}")
            artifacts[key] = None
    
    return artifacts

def generate_executive_summary(artifacts: Dict[str, Any]) -> str:
    """Generate executive summary section."""
    summary = []
    
    # Date and time
    summary.append(f"**Analysis Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Execution summary
    if artifacts.get('results_csv') is not None:
        df = artifacts['results_csv']
        total_runs = len(df)
        if 'status' in df.columns:
            completed_runs = len(df[df['status'] == 'completed'])
        else:
            # Assume all runs are completed if no status column
            completed_runs = total_runs
        success_rate = (completed_runs / total_runs * 100) if total_runs > 0 else 0
        
        summary.append(f"**Total runs**: {total_runs}")
        summary.append(f"**Success rate**: {success_rate:.1f}%")
    
    # Best result - try to load from summary JSON first, then top_10 JSON
    best_metrics = None
    if artifacts.get('summary_json') is not None:
        summary_data = artifacts['summary_json']
        if 'best' in summary_data and 'metrics' in summary_data['best']:
            best_metrics = summary_data['best']['metrics']
    
    if best_metrics is None and artifacts.get('top_10_json') is not None:
        top_10 = artifacts['top_10_json']
        if top_10 and len(top_10) > 0:
            best = top_10[0]
            best_metrics = {
                'sharpe_ratio': best.get('sharpe_ratio', 0),
                'total_pnl': best.get('total_pnl', 0),
                'max_drawdown': best.get('max_drawdown', 0)
            }
    
    if best_metrics:
        summary.append(f"**Best Sharpe ratio**: {best_metrics.get('sharpe_ratio', 0):.4f}")
        summary.append(f"**Best total PnL**: ${best_metrics.get('total_pnl', 0):,.0f}")
        summary.append(f"**Best max drawdown**: ${best_metrics.get('max_drawdown', 0):,.0f}")
    
    # Pareto frontier
    if artifacts.get('pareto_json') is not None:
        pareto = artifacts['pareto_json']
        frontier_size = len(pareto.get('frontier', []))
        summary.append(f"**Pareto frontier size**: {frontier_size} non-dominated solutions")
    
    # Top 5 parameter sets
    if artifacts.get('top_5_json') is not None:
        top_5 = artifacts['top_5_json']
        if top_5 and 'parameter_sets' in top_5:
            summary.append(f"**Top 5 parameter sets selected**: {len(top_5['parameter_sets'])}")
    
    # Key findings
    key_findings = []
    if artifacts.get('sensitivity_json') is not None:
        sensitivity = artifacts['sensitivity_json']
        if 'sensitive_parameters' in sensitivity and sensitivity['sensitive_parameters']:
            top_sensitive = list(sensitivity['sensitive_parameters'].keys())[:3]
            key_findings.append(f"Most sensitive parameters: {', '.join(top_sensitive)}")
    
    if key_findings:
        summary.append("**Key findings**:")
        for finding in key_findings:
            summary.append(f"- {finding}")
    
    return "\n".join(summary)

def generate_sensitivity_section(sensitivity_data: Dict[str, Any]) -> str:
    """Generate parameter sensitivity analysis section."""
    if not sensitivity_data:
        return "## Parameter Sensitivity Analysis\n\n*Sensitivity analysis data not available.*\n"
    
    sections = ["## Parameter Sensitivity Analysis\n"]
    
    # Most Sensitive Parameters
    if 'sensitive_parameters' in sensitivity_data and sensitivity_data['sensitive_parameters']:
        sections.append("### Most Sensitive Parameters\n")
        sections.append("| Parameter | Sharpe Correlation | PnL Correlation | Drawdown Correlation | Sensitivity Score |")
        sections.append("|-----------|-------------------|-----------------|---------------------|------------------|")
        
        for param, data in sensitivity_data['sensitive_parameters'].items():
            # Get correlations for each objective from parameter_correlations
            sharpe_corr = data.get('avg_abs_correlation', 0)
            pnl_corr = 0
            drawdown_corr = 0
            
            # Extract PnL and Drawdown correlations from parameter_correlations if available
            if 'parameter_correlations' in sensitivity_data and param in sensitivity_data['parameter_correlations']:
                param_correlations = sensitivity_data['parameter_correlations'][param]
                if 'total_pnl' in param_correlations:
                    pnl_corr = abs(param_correlations['total_pnl'].get('pearson', 0))
                if 'max_drawdown' in param_correlations:
                    drawdown_corr = abs(param_correlations['max_drawdown'].get('pearson', 0))
            
            sections.append(f"| {param} | {sharpe_corr:.3f} | {pnl_corr:.3f} | {drawdown_corr:.3f} | {data.get('sensitivity_score', 0):.3f} |")
    
    # Parameter Stability Analysis
    if 'parameter_stability' in sensitivity_data and sensitivity_data['parameter_stability']:
        sections.append("\n### Parameter Stability Analysis\n")
        sections.append("| Parameter | Std Dev in Top 10 | Coefficient of Variation | Stability Rating |")
        sections.append("|-----------|-------------------|-------------------------|-----------------|")
        
        for param, data in sensitivity_data['parameter_stability'].items():
            sections.append(f"| {param} | {data.get('std_dev', 0):.3f} | {data.get('coefficient_of_variation', 0):.3f} | {data.get('stability_rating', 'unknown')} |")
    
    # Key Insights
    if 'recommendations' in sensitivity_data and sensitivity_data['recommendations']:
        sections.append("\n### Key Insights\n")
        for rec in sensitivity_data['recommendations']:
            sections.append(f"- {rec}")
    
    return "\n".join(sections)

def generate_pareto_section(pareto_data: Dict[str, Any], top5_data: Dict[str, Any]) -> str:
    """Generate Pareto frontier analysis section."""
    if not pareto_data:
        return "## Pareto Frontier Analysis\n\n*Pareto frontier data not available.*\n"
    
    sections = ["## Pareto Frontier Analysis\n"]
    
    # Pareto Frontier Overview
    frontier = pareto_data.get('frontier', [])
    objectives = pareto_data.get('objectives', [])
    
    sections.append(f"**Pareto frontier size**: {len(frontier)} non-dominated solutions")
    sections.append(f"**Objectives**: {', '.join(objectives)}")
    
    if frontier:
        # Calculate ranges (support nested structures)
        def get_obj(point, key):
            return (
                point.get('objective_values', {}).get(key,
                    point.get('metrics', {}).get(key,
                        point.get(key, 0)))
            )
        sharpe_values = [get_obj(p, 'sharpe_ratio') for p in frontier]
        pnl_values = [get_obj(p, 'total_pnl') for p in frontier]
        drawdown_values = [get_obj(p, 'max_drawdown') for p in frontier]
        
        sections.append(f"**Frontier spans**:")
        sections.append(f"- Sharpe: {min(sharpe_values):.4f} - {max(sharpe_values):.4f}")
        sections.append(f"- PnL: ${min(pnl_values):,.0f} - ${max(pnl_values):,.0f}")
        sections.append(f"- Drawdown: ${min(drawdown_values):,.0f} - ${max(drawdown_values):,.0f}")
    
    # Pareto Frontier Table
    if frontier:
        sections.append("\n### Pareto Frontier Points\n")
        sections.append("| Run ID | Sharpe | PnL | Drawdown | Key Parameters |")
        sections.append("|--------|--------|-----|----------|----------------|")
        
        for i, point in enumerate(frontier[:10]):  # Show first 10
            sharpe = point.get('objective_values', {}).get('sharpe_ratio', point.get('metrics', {}).get('sharpe_ratio', point.get('sharpe_ratio', 0)))
            pnl = point.get('objective_values', {}).get('total_pnl', point.get('metrics', {}).get('total_pnl', point.get('total_pnl', 0)))
            drawdown = point.get('objective_values', {}).get('max_drawdown', point.get('metrics', {}).get('max_drawdown', point.get('max_drawdown', 0)))
            # Access parameters from point['parameters'] if available
            if 'parameters' in point:
                params = point['parameters']
                key_params = f"fast={params.get('fast_period', 0)}, slow={params.get('slow_period', 0)}"
            else:
                key_params = f"fast={point.get('fast_period', 0)}, slow={point.get('slow_period', 0)}"
            # Only show metrics that are present in the Pareto JSON
            sections.append(f"| {i+1} | {sharpe:.4f} | ${pnl:,.0f} | ${drawdown:,.0f} | {key_params} |")
    
    # Top 5 Selected Parameter Sets
    if top5_data and 'parameter_sets' in top5_data:
        sections.append("\n### Top 5 Selected Parameter Sets\n")
        
        for i, param_set in enumerate(top5_data['parameter_sets']):
            name = param_set.get('name', f'Set {i+1}')
            perf = param_set.get('expected_performance', {})
            trade_offs = param_set.get('trade_offs', 'N/A')
            
            sections.append(f"#### Parameter Set {i+1}: {name.replace('_', ' ').title()}\n")
            sections.append(f"**Performance Metrics:**")
            # Only show metrics that are present in the expected_performance
            if 'sharpe_ratio' in perf:
                sections.append(f"- Sharpe Ratio: {perf.get('sharpe_ratio', 0):.4f}")
            if 'total_pnl' in perf:
                sections.append(f"- Total PnL: ${perf.get('total_pnl', 0):,.0f}")
            if 'max_drawdown' in perf:
                sections.append(f"- Max Drawdown: ${perf.get('max_drawdown', 0):,.0f}")
            sections.append(f"\n**Trade-offs**: {trade_offs}")
            sections.append(f"\n**Strengths**: {', '.join(param_set.get('strengths', []))}")
            sections.append(f"\n**Weaknesses**: {', '.join(param_set.get('weaknesses', []))}")
            sections.append("\n---\n")
    
    return "\n".join(sections)

def generate_recommendations_section(artifacts: Dict[str, Any]) -> str:
    """Generate recommendations section."""
    sections = ["## Recommendations for Phase 7\n"]
    
    # For Phase 7 Walk-Forward Validation
    sections.append("### For Phase 7 Walk-Forward Validation\n")
    sections.append("- Use all 5 selected parameter sets for robust out-of-sample testing")
    sections.append("- Expected performance ranges based on in-sample results:")
    
    if artifacts.get('top_5_json') and 'parameter_sets' in artifacts['top_5_json']:
        param_sets = artifacts['top_5_json']['parameter_sets']
        sharpe_values = [p.get('expected_performance', {}).get('sharpe_ratio', 0) for p in param_sets]
        pnl_values = [p.get('expected_performance', {}).get('total_pnl', 0) for p in param_sets]
        
        if sharpe_values:
            sections.append(f"  - Sharpe ratio range: {min(sharpe_values):.4f} - {max(sharpe_values):.4f}")
        if pnl_values:
            sections.append(f"  - PnL range: ${min(pnl_values):,.0f} - ${max(pnl_values):,.0f}")
    
    sections.append("- Robustness assessment for each parameter set:")
    sections.append("  - Best Sharpe: High risk-adjusted returns, may have higher drawdown")
    sections.append("  - Best PnL: High absolute returns, may have lower Sharpe")
    sections.append("  - Best Drawdown: Capital preservation focus, may have lower returns")
    sections.append("  - Balanced sets: Compromise solutions for different market conditions")
    
    # Parameter Refinement Insights
    sections.append("\n### Parameter Refinement Insights\n")
    if artifacts.get('sensitivity_json') and 'parameter_stability' in artifacts['sensitivity_json']:
        stability = artifacts['sensitivity_json']['parameter_stability']
        stable_params = [p for p, d in stability.items() if d.get('stability_rating') == 'high']
        unstable_params = [p for p, d in stability.items() if d.get('stability_rating') == 'low']
        
        if stable_params:
            sections.append(f"- Well-optimized parameters (stable): {', '.join(stable_params)}")
        if unstable_params:
            sections.append(f"- Parameters that may benefit from further refinement: {', '.join(unstable_params)}")
    
    # Strategy Configuration Recommendations
    sections.append("\n### Strategy Configuration Recommendations\n")
    sections.append("- Recommended parameter set for production: Use best Sharpe for risk-adjusted performance")
    sections.append("- Alternative parameter sets for different market conditions:")
    sections.append("  - Bull markets: Best PnL parameter set")
    sections.append("  - Bear markets: Best drawdown parameter set")
    sections.append("  - Uncertain markets: Balanced parameter sets")
    sections.append("- Risk management considerations:")
    sections.append("  - Monitor drawdown limits for all parameter sets")
    sections.append("  - Adjust position sizing based on market volatility")
    sections.append("  - Consider parameter set switching based on market regime")
    
    return "\n".join(sections)

def generate_full_report(artifacts: Dict[str, Any]) -> str:
    """Generate complete Phase 6 analysis report."""
    report_sections = []
    
    # Title and header
    report_sections.append("# Phase 6: Parameter Refinement and Sensitivity Analysis - Comprehensive Report\n")
    report_sections.append(f"*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
    
    # Executive Summary
    report_sections.append("## Executive Summary\n")
    report_sections.append(generate_executive_summary(artifacts))
    report_sections.append("\n")
    
    # Parameter Sensitivity Analysis
    sensitivity_data = artifacts.get('sensitivity_json', {})
    report_sections.append(generate_sensitivity_section(sensitivity_data))
    report_sections.append("\n")
    
    # Pareto Frontier Analysis
    pareto_data = artifacts.get('pareto_json', {})
    top5_data = artifacts.get('top_5_json', {})
    report_sections.append(generate_pareto_section(pareto_data, top5_data))
    report_sections.append("\n")
    
    # Recommendations
    report_sections.append(generate_recommendations_section(artifacts))
    report_sections.append("\n")
    
    # Appendix
    report_sections.append("## Appendix: Output Files\n")
    report_sections.append("The following files were generated during Phase 6 analysis:\n")
    report_sections.append("- `phase6_refinement_results.csv` - All optimization results")
    report_sections.append("- `phase6_refinement_results_pareto_frontier.json` - Pareto frontier data")
    report_sections.append("- `phase6_sensitivity_analysis.json` - Parameter sensitivity analysis")
    report_sections.append("- `phase6_top_5_parameters.json` - Selected parameter sets for Phase 7")
    report_sections.append("- `PHASE6_ANALYSIS_REPORT.md` - This comprehensive report")
    
    return "\n".join(report_sections)

def main():
    """Main function to generate comprehensive Phase 6 analysis report."""
    parser = argparse.ArgumentParser(description='Generate comprehensive Phase 6 analysis report')
    parser.add_argument('--results-dir', default='optimization/results',
                       help='Directory with Phase 6 results')
    parser.add_argument('--output', default='optimization/results/PHASE6_ANALYSIS_REPORT.md',
                       help='Path to output report')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("Starting Phase 6 comprehensive analysis report generation...")
    
    # Load all Phase 6 artifacts
    logger.info("Loading Phase 6 artifacts...")
    artifacts = load_all_phase6_artifacts(args.results_dir)
    
    # Generate full report
    logger.info("Generating comprehensive report...")
    report = generate_full_report(artifacts)
    
    # Write report to file
    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        f.write(report)
    
    logger.info(f"Report generated successfully: {output_path}")
    
    # Print summary
    print("\n" + "="*60)
    print("PHASE 6 COMPREHENSIVE ANALYSIS REPORT GENERATED")
    print("="*60)
    print(f"Report location: {args.output}")
    print(f"Report sections:")
    print("  - Executive summary")
    print("  - Parameter sensitivity analysis")
    print("  - Pareto frontier analysis")
    print("  - Top 5 parameter sets (detailed)")
    print("  - Recommendations for Phase 7")
    print("  - Appendix (output files)")
    print("\nNext steps:")
    print("  - Review the comprehensive report")
    print("  - Review phase6_top_5_parameters.json for Phase 7")
    print("  - Prepare for Phase 7 walk-forward validation")
    print("="*60)

if __name__ == "__main__":
    main()
