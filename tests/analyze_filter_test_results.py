#!/usr/bin/env python3
"""
Comprehensive Filter Test Results Analysis

Analyzes backtest results from comprehensive filter tests and generates validation reports.
Validates trade counts, rejection reasons, and filter behavior against expected outcomes.
"""

import json
import logging
import sys
import argparse
import csv
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import Counter
import pandas as pd
import base64
import io
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime

# Project structure
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_BASE = PROJECT_ROOT / "logs" / "test_results" / "comprehensive_filter_tests"
CATALOG_BASE = PROJECT_ROOT / "data" / "test_catalog" / "comprehensive_filter_tests"

# Filter types matching tests/run_all_filter_backtests.py
FILTER_TYPES = [
    "crossover_threshold",
    "pre_separation", 
    "dmi",
    "stochastic",
    "time_filter",
    "atr",
    "adx",
    "circuit_breaker"
]

# Rejection reason mapping for all 8 filters
REJECTION_REASON_MAP = {
    "crossover_threshold": "crossover_threshold_not_met",
    "pre_separation": "pre_crossover_separation_insufficient", 
    "dmi": "dmi_trend_mismatch",
    "stochastic": ["stochastic_unfavorable", "stochastic_crossing_too_old", "stochastic_direction_mismatch"],
    "time_filter": ["time_filter_outside_hours", "time_filter_excluded_hour"],
    "atr": ["atr_too_low", "atr_too_high"],
    "adx": "adx_trend_too_weak",
    "circuit_breaker": "circuit_breaker_active"
}

@dataclass
class ScenarioMetadata:
    """Metadata for a test scenario from catalog JSON files."""
    symbol: str
    filter_type: str
    scenario_name: str
    expected_trades: int
    expected_rejection_reason: Optional[str]
    test_purpose: str
    filter_config: Dict[str, Any]
    metadata_path: Path

@dataclass
class ValidationResult:
    """Results of validating a single test scenario."""
    scenario: ScenarioMetadata
    passed: bool
    trade_count_actual: int
    trade_count_expected: int
    trade_count_match: bool
    rejection_reason_found: bool
    rejection_reason_expected: Optional[str]
    rejection_reasons_actual: List[str]
    rejection_count: int
    filter_behavior_valid: bool
    validation_errors: List[str]
    validation_warnings: List[str]
    output_dir: Optional[Path]
    performance_stats: Dict[str, Any]
    duration_seconds: float

@dataclass
class FilterSummary:
    """Summary statistics for a specific filter type."""
    filter_type: str
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    pass_rate: float
    trade_count_mismatches: int
    rejection_reason_mismatches: int
    filter_behavior_issues: int
    scenarios: List[ValidationResult]

@dataclass
class AnalysisReport:
    """Complete analysis report with all validation results."""
    timestamp: str
    total_scenarios: int
    total_passed: int
    total_failed: int
    overall_pass_rate: float
    filter_summaries: Dict[str, FilterSummary]
    validation_results: List[ValidationResult]
    recommendations: List[str]
    execution_time: float

def discover_scenarios(results_base: Path, catalog_base: Path) -> List[ScenarioMetadata]:
    """Discover all test scenarios from results and catalog directories."""
    scenarios = []
    
    if not results_base.exists():
        logging.warning(f"Results directory not found: {results_base}")
        return scenarios
        
    if not catalog_base.exists():
        logging.warning(f"Catalog directory not found: {catalog_base}")
        return scenarios
    
    for filter_type in FILTER_TYPES:
        filter_results_dir = results_base / filter_type
        filter_catalog_dir = catalog_base / filter_type
        
        if not filter_results_dir.exists():
            logging.debug(f"Filter results directory not found: {filter_results_dir}")
            continue
            
        if not filter_catalog_dir.exists():
            logging.debug(f"Filter catalog directory not found: {filter_catalog_dir}")
            continue
        
        # Find scenario directories in results
        for scenario_dir in filter_results_dir.iterdir():
            if not scenario_dir.is_dir():
                continue
                
            scenario_name = scenario_dir.name
            
            # Look for metadata in catalog
            metadata_dir = filter_catalog_dir / "metadata"
            metadata_file = None
            
            if metadata_dir.exists():
                metadata_file = metadata_dir / f"{scenario_name}_metadata.json"
                if not metadata_file.exists():
                    metadata_file = None
            
            # Recursive fallback: search for metadata files
            if metadata_file is None:
                metadata_files = list(filter_catalog_dir.rglob("*_metadata.json"))
                # Find metadata file whose stem matches scenario directory name
                for mf in metadata_files:
                    if mf.stem == f"{scenario_name}_metadata":
                        metadata_file = mf
                        break
                
                if metadata_file is None and metadata_files:
                    # If multiple metadata files present, log debug and skip
                    logging.debug(f"Multiple metadata files found for {scenario_name}, skipping: {[mf.name for mf in metadata_files]}")
                    continue
                elif metadata_file is None:
                    logging.debug(f"No metadata file found for scenario: {scenario_name}")
                    continue
            
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                scenario = ScenarioMetadata(
                    symbol=metadata.get('symbol', ''),
                    filter_type=filter_type,
                    scenario_name=scenario_name,
                    expected_trades=metadata.get('expected_trades', 0),
                    expected_rejection_reason=metadata.get('expected_rejection_reason'),
                    test_purpose=metadata.get('test_purpose', ''),
                    filter_config=metadata.get('filter_config', {}),
                    metadata_path=metadata_file
                )
                scenarios.append(scenario)
                logging.debug(f"Discovered scenario: {filter_type}/{scenario_name}")
                
            except (json.JSONDecodeError, KeyError) as e:
                logging.warning(f"Failed to parse metadata {metadata_file}: {e}")
                continue
    
    logging.info(f"🔍 Found {len(scenarios)} scenarios across {len(set(s.filter_type for s in scenarios))} filter types")
    return scenarios

def find_latest_output_dir(scenario_dir: Path) -> Optional[Path]:
    """Find the latest output directory for a scenario."""
    # Check for 'latest' symlink first
    latest_link = scenario_dir / "latest"
    if latest_link.exists() and latest_link.is_symlink():
        try:
            target = latest_link.resolve()
            if target.exists():
                return target
        except OSError:
            pass
    
    # Look for timestamped subdirectories in runs/ folder
    runs_dir = scenario_dir / "runs"
    if runs_dir.exists():
        timestamped_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
        if timestamped_dirs:
            # Return most recent by modification time
            latest = max(timestamped_dirs, key=lambda d: d.stat().st_mtime)
            return latest
    
    # Check if scenario_dir itself contains results
    if (scenario_dir / "performance_stats.json").exists():
        return scenario_dir
    
    return None

def load_performance_stats(output_dir: Path) -> Dict[str, Any]:
    """Load performance statistics from output directory."""
    stats_file = output_dir / "performance_stats.json"
    if not stats_file.exists():
        logging.warning(f"Performance stats file not found: {stats_file}")
        return {}
    
    try:
        with open(stats_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"Failed to load performance stats {stats_file}: {e}")
        return {}

def load_rejected_signals(output_dir: Path) -> List[Dict[str, str]]:
    """Load rejected signals from output directory."""
    signals_file = output_dir / "rejected_signals.csv"
    if not signals_file.exists():
        logging.warning(f"Rejected signals file not found: {signals_file}")
        return []
    
    try:
        with open(signals_file, 'r') as f:
            reader = csv.DictReader(f)
            return list(reader)
    except (IOError, csv.Error) as e:
        logging.warning(f"Failed to load rejected signals {signals_file}: {e}")
        return []

def validate_trade_count(actual: int, expected: int) -> Tuple[bool, Optional[str]]:
    """Validate that actual trade count matches expected."""
    if actual == expected:
        return True, None
    return False, f"Trade count mismatch: expected {expected}, got {actual}"

def validate_rejection_reason(rejected_signals: List[Dict[str, str]], expected_reason: Optional[str]) -> Tuple[bool, List[str]]:
    """Validate that rejection reasons match expected."""
    actual_reasons = []
    for signal in rejected_signals:
        reason = signal.get('reason', '')
        if reason:
            actual_reasons.append(reason)
    
    actual_reasons = list(set(actual_reasons))  # Remove duplicates
    
    if expected_reason is None:
        # Should have no rejections
        if not actual_reasons:
            return True, actual_reasons
        return False, actual_reasons
    
    # Should have expected rejection reason
    expected_found = any(expected_reason.lower() in reason.lower() for reason in actual_reasons)
    return expected_found, actual_reasons

def validate_filter_behavior(scenario: ScenarioMetadata, validation_result: ValidationResult) -> Tuple[List[str], List[str]]:
    """Validate filter-specific behavior based on filter type."""
    errors = []
    warnings = []
    
    filter_type = scenario.filter_type
    actual_reasons = validation_result.rejection_reasons_actual
    
    if filter_type == "crossover_threshold":
        expected_reason = "crossover_threshold_not_met"
        if scenario.expected_trades > 0:  # Pass scenario
            if any(expected_reason in reason for reason in actual_reasons):
                errors.append(f"Unexpected rejection in pass scenario: {expected_reason}")
        else:  # Fail scenario
            if not any(expected_reason in reason for reason in actual_reasons):
                errors.append(f"Expected rejection not found in fail scenario: {expected_reason}")
    
    elif filter_type == "pre_separation":
        expected_reason = "pre_crossover_separation_insufficient"
        if scenario.expected_trades > 0:  # Pass scenario
            if any(expected_reason in reason for reason in actual_reasons):
                errors.append(f"Unexpected rejection in pass scenario: {expected_reason}")
        else:  # Fail scenario
            if not any(expected_reason in reason for reason in actual_reasons):
                errors.append(f"Expected rejection not found in fail scenario: {expected_reason}")
    
    elif filter_type == "dmi":
        expected_reason = "dmi_trend_mismatch"
        if scenario.expected_trades > 0:  # Pass scenario
            if any(expected_reason in reason for reason in actual_reasons):
                errors.append(f"Unexpected rejection in pass scenario: {expected_reason}")
        else:  # Fail scenario
            if not any(expected_reason in reason for reason in actual_reasons):
                errors.append(f"Expected rejection not found in fail scenario: {expected_reason}")
    
    elif filter_type == "stochastic":
        expected_reasons = ["stochastic_unfavorable", "stochastic_crossing_too_old", "stochastic_direction_mismatch"]
        if scenario.expected_trades > 0:  # Pass scenario
            for expected_reason in expected_reasons:
                if any(expected_reason in reason for reason in actual_reasons):
                    errors.append(f"Unexpected rejection in pass scenario: {expected_reason}")
        else:  # Fail scenario
            found_expected = any(any(expected_reason in reason for reason in actual_reasons) 
                               for expected_reason in expected_reasons)
            if not found_expected:
                errors.append(f"Expected stochastic rejection not found in fail scenario")
    
    elif filter_type == "time_filter":
        expected_reasons = ["time_filter_outside_hours", "time_filter_excluded_hour"]
        if scenario.expected_trades > 0:  # Pass scenario
            for expected_reason in expected_reasons:
                if any(expected_reason in reason for reason in actual_reasons):
                    errors.append(f"Unexpected rejection in pass scenario: {expected_reason}")
        else:  # Fail scenario
            found_expected = any(any(expected_reason in reason for reason in actual_reasons) 
                               for expected_reason in expected_reasons)
            if not found_expected:
                errors.append(f"Expected time filter rejection not found in fail scenario")
    
    elif filter_type == "atr":
        expected_reasons = ["atr_too_low", "atr_too_high"]
        if scenario.expected_trades > 0:  # Pass scenario
            for expected_reason in expected_reasons:
                if any(expected_reason in reason for reason in actual_reasons):
                    errors.append(f"Unexpected rejection in pass scenario: {expected_reason}")
        else:  # Fail scenario
            found_expected = any(any(expected_reason in reason for reason in actual_reasons) 
                               for expected_reason in expected_reasons)
            if not found_expected:
                errors.append(f"Expected ATR rejection not found in fail scenario")
    
    elif filter_type == "adx":
        expected_reason = "adx_trend_too_weak"
        if scenario.expected_trades > 0:  # Pass scenario
            if any(expected_reason in reason for reason in actual_reasons):
                errors.append(f"Unexpected rejection in pass scenario: {expected_reason}")
        else:  # Fail scenario
            if not any(expected_reason in reason for reason in actual_reasons):
                errors.append(f"Expected rejection not found in fail scenario: {expected_reason}")
    
    elif filter_type == "circuit_breaker":
        expected_reason = "circuit_breaker_active"
        if scenario.expected_trades > 0:  # Pass scenario
            if any(expected_reason in reason for reason in actual_reasons):
                errors.append(f"Unexpected rejection in pass scenario: {expected_reason}")
        else:  # Fail scenario
            if not any(expected_reason in reason for reason in actual_reasons):
                errors.append(f"Expected rejection not found in fail scenario: {expected_reason}")
    
    # Check for unexpected rejection reasons
    all_expected_reasons = []
    if isinstance(REJECTION_REASON_MAP.get(filter_type), list):
        all_expected_reasons.extend(REJECTION_REASON_MAP[filter_type])
    else:
        all_expected_reasons.append(REJECTION_REASON_MAP.get(filter_type, ""))
    
    for reason in actual_reasons:
        if not any(expected in reason for expected in all_expected_reasons if expected):
            warnings.append(f"Unexpected rejection reason: {reason}")
    
    return errors, warnings

def validate_scenario(scenario: ScenarioMetadata, results_base: Path) -> ValidationResult:
    """Validate a single test scenario against expected outcomes."""
    start_time = time.time()
    
    # Find output directory
    scenario_dir = results_base / scenario.filter_type / scenario.scenario_name
    output_dir = find_latest_output_dir(scenario_dir)
    
    if output_dir is None:
        return ValidationResult(
            scenario=scenario,
            passed=False,
            trade_count_actual=0,
            trade_count_expected=scenario.expected_trades,
            trade_count_match=False,
            rejection_reason_found=False,
            rejection_reason_expected=scenario.expected_rejection_reason,
            rejection_reasons_actual=[],
            rejection_count=0,
            filter_behavior_valid=False,
            validation_errors=["Output directory not found"],
            validation_warnings=[],
            output_dir=None,
            performance_stats={},
            duration_seconds=time.time() - start_time
        )
    
    # Load results
    performance_stats = load_performance_stats(output_dir)
    rejected_signals = load_rejected_signals(output_dir)
    
    # Extract actual trade count
    actual_trades = 0
    if 'general' in performance_stats and 'total_trades' in performance_stats['general']:
        actual_trades = performance_stats['general']['total_trades']
    
    # Fallback: if total_trades is missing or zero, count positions.csv rows
    if actual_trades == 0:
        positions_file = output_dir / "positions.csv"
        if positions_file.exists():
            try:
                with open(positions_file, 'r') as f:
                    reader = csv.reader(f)
                    # Skip header row first
                    next(reader, None)
                    # Skip snapshot rows, count actual trade rows
                    actual_trades = sum(1 for row in reader if row and len(row) > 0 and not row[0].lower().startswith('snapshot'))
            except (IOError, csv.Error) as e:
                logging.warning(f"Failed to read positions file {positions_file}: {e}")
    
    # Validate trade count
    trade_count_match, trade_count_error = validate_trade_count(actual_trades, scenario.expected_trades)
    
    # Validate rejection reason
    rejection_reason_found, actual_reasons = validate_rejection_reason(rejected_signals, scenario.expected_rejection_reason)
    
    # Create preliminary validation result
    validation_result = ValidationResult(
        scenario=scenario,
        passed=False,  # Will be determined after filter behavior validation
        trade_count_actual=actual_trades,
        trade_count_expected=scenario.expected_trades,
        trade_count_match=trade_count_match,
        rejection_reason_found=rejection_reason_found,
        rejection_reason_expected=scenario.expected_rejection_reason,
        rejection_reasons_actual=actual_reasons,
        rejection_count=len(rejected_signals),
        filter_behavior_valid=False,  # Will be determined
        validation_errors=[trade_count_error] if trade_count_error else [],
        validation_warnings=[],
        output_dir=output_dir,
        performance_stats=performance_stats,
        duration_seconds=time.time() - start_time
    )
    
    # Validate filter behavior
    behavior_errors, behavior_warnings = validate_filter_behavior(scenario, validation_result)
    validation_result.filter_behavior_valid = len(behavior_errors) == 0
    validation_result.validation_errors.extend(behavior_errors)
    validation_result.validation_warnings.extend(behavior_warnings)
    
    # Determine overall pass status
    validation_result.passed = (trade_count_match and rejection_reason_found and validation_result.filter_behavior_valid)
    
    # Log result
    status_emoji = "✅" if validation_result.passed else "❌"
    if validation_result.validation_warnings:
        status_emoji = "⚠️"
    
    logging.info(f"{status_emoji} {scenario.filter_type}/{scenario.scenario_name}: "
                f"Trades {actual_trades}/{scenario.expected_trades}, "
                f"Rejections {len(actual_reasons)}, "
                f"Passed: {validation_result.passed}")
    
    return validation_result

def aggregate_results(validation_results: List[ValidationResult]) -> AnalysisReport:
    """Aggregate validation results into analysis report."""
    # Group by filter type
    filter_groups = {}
    for result in validation_results:
        filter_type = result.scenario.filter_type
        if filter_type not in filter_groups:
            filter_groups[filter_type] = []
        filter_groups[filter_type].append(result)
    
    # Create filter summaries
    filter_summaries = {}
    for filter_type, results in filter_groups.items():
        total_scenarios = len(results)
        passed_scenarios = sum(1 for r in results if r.passed)
        failed_scenarios = total_scenarios - passed_scenarios
        pass_rate = (passed_scenarios / total_scenarios * 100) if total_scenarios > 0 else 0
        
        trade_count_mismatches = sum(1 for r in results if not r.trade_count_match)
        rejection_reason_mismatches = sum(1 for r in results if not r.rejection_reason_found)
        filter_behavior_issues = sum(1 for r in results if not r.filter_behavior_valid)
        
        filter_summaries[filter_type] = FilterSummary(
            filter_type=filter_type,
            total_scenarios=total_scenarios,
            passed_scenarios=passed_scenarios,
            failed_scenarios=failed_scenarios,
            pass_rate=pass_rate,
            trade_count_mismatches=trade_count_mismatches,
            rejection_reason_mismatches=rejection_reason_mismatches,
            filter_behavior_issues=filter_behavior_issues,
            scenarios=results
        )
    
    # Calculate overall statistics
    total_scenarios = len(validation_results)
    total_passed = sum(1 for r in validation_results if r.passed)
    total_failed = total_scenarios - total_passed
    overall_pass_rate = (total_passed / total_scenarios * 100) if total_scenarios > 0 else 0
    
    # Generate recommendations
    recommendations = generate_recommendations(filter_summaries, total_scenarios, total_passed, overall_pass_rate)
    
    return AnalysisReport(
        timestamp=datetime.now().isoformat(),
        total_scenarios=total_scenarios,
        total_passed=total_passed,
        total_failed=total_failed,
        overall_pass_rate=overall_pass_rate,
        filter_summaries=filter_summaries,
        validation_results=validation_results,
        recommendations=recommendations,
        execution_time=0  # Will be set by caller
    )

def generate_recommendations(filter_summaries: Dict[str, FilterSummary], 
                           total_scenarios: int, total_passed: int, 
                           overall_pass_rate: float) -> List[str]:
    """Generate actionable recommendations based on analysis results."""
    recommendations = []
    
    # Overall pass rate recommendations
    if overall_pass_rate == 100:
        recommendations.append("✅ All filter tests passed! The strategy filters are working as expected.")
    elif overall_pass_rate < 50:
        recommendations.append("🔴 Critical: More than half of filter tests failed. Review filter implementations urgently.")
    elif overall_pass_rate < 80:
        recommendations.append("🟡 Warning: Significant number of filter test failures. Review filter logic and test data.")
    
    # Filter-specific recommendations
    for filter_type, summary in filter_summaries.items():
        if summary.pass_rate < 100:
            recommendations.append(f"Review {filter_type} filter: {summary.failed_scenarios}/{summary.total_scenarios} scenarios failed")
            
            if summary.trade_count_mismatches > 0:
                recommendations.append(f"Check {filter_type} filter logic - trade count mismatches detected")
            
            if summary.rejection_reason_mismatches > 0:
                recommendations.append(f"Verify {filter_type} rejection reason logging - expected reasons not found")
            
            if summary.filter_behavior_issues > 0:
                recommendations.append(f"Investigate {filter_type} filter behavior - inconsistencies detected")
    
    # Specific issue recommendations
    rejection_issues = sum(1 for s in filter_summaries.values() if s.rejection_reason_mismatches > 0)
    if rejection_issues > 1:
        recommendations.append("Consider reviewing rejection reason logging in `strategies/moving_average_crossover.py`")
    
    circuit_breaker_issues = filter_summaries.get("circuit_breaker", FilterSummary("", 0, 0, 0, 0, 0, 0, 0, []))
    if circuit_breaker_issues.failed_scenarios > 0:
        recommendations.append("Review circuit breaker state management and cooldown logic")
    
    time_filter_issues = filter_summaries.get("time_filter", FilterSummary("", 0, 0, 0, 0, 0, 0, 0, []))
    if time_filter_issues.failed_scenarios > 0:
        recommendations.append("Verify timezone handling in time-of-day filter")
    
    return recommendations

def generate_pass_fail_chart(filter_summaries: Dict[str, FilterSummary]) -> str:
    """Generate pass/fail chart for HTML embedding."""
    plt.figure(figsize=(10, 6))
    
    filter_types = list(filter_summaries.keys())
    passed_counts = [filter_summaries[ft].passed_scenarios for ft in filter_types]
    failed_counts = [filter_summaries[ft].failed_scenarios for ft in filter_types]
    
    y_pos = range(len(filter_types))
    
    # Create horizontal bar chart
    plt.barh(y_pos, passed_counts, color='#2ecc71', alpha=0.8, label='Passed')
    plt.barh(y_pos, failed_counts, left=passed_counts, color='#e74c3c', alpha=0.8, label='Failed')
    
    # Add pass rate labels
    for i, (ft, summary) in enumerate(filter_summaries.items()):
        plt.text(summary.total_scenarios + 0.1, i, f'{summary.pass_rate:.1f}%', 
                va='center', fontweight='bold')
    
    plt.yticks(y_pos, filter_types)
    plt.xlabel('Number of Scenarios')
    plt.title('Filter Test Results by Type')
    plt.legend()
    plt.grid(axis='x', alpha=0.3)
    plt.tight_layout()
    
    # Convert to base64
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64

def generate_validation_breakdown_chart(filter_summaries: Dict[str, FilterSummary]) -> str:
    """Generate validation breakdown chart for HTML embedding."""
    plt.figure(figsize=(12, 6))
    
    filter_types = list(filter_summaries.keys())
    trade_mismatches = [filter_summaries[ft].trade_count_mismatches for ft in filter_types]
    rejection_mismatches = [filter_summaries[ft].rejection_reason_mismatches for ft in filter_types]
    behavior_issues = [filter_summaries[ft].filter_behavior_issues for ft in filter_types]
    
    y_pos = range(len(filter_types))
    
    # Create stacked bar chart
    plt.barh(y_pos, trade_mismatches, color='#f39c12', alpha=0.8, label='Trade Count Mismatches')
    plt.barh(y_pos, rejection_mismatches, left=trade_mismatches, color='#9b59b6', alpha=0.8, label='Rejection Reason Mismatches')
    plt.barh(y_pos, behavior_issues, left=[t + r for t, r in zip(trade_mismatches, rejection_mismatches)], 
             color='#e67e22', alpha=0.8, label='Filter Behavior Issues')
    
    plt.yticks(y_pos, filter_types)
    plt.xlabel('Number of Issues')
    plt.title('Validation Issues Breakdown by Filter Type')
    plt.legend()
    plt.grid(axis='x', alpha=0.3)
    plt.tight_layout()
    
    # Convert to base64
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64

def generate_overall_summary_chart(analysis_report: AnalysisReport) -> str:
    """Generate overall summary pie chart for HTML embedding."""
    plt.figure(figsize=(8, 8))
    
    labels = ['Passed', 'Failed']
    sizes = [analysis_report.total_passed, analysis_report.total_failed]
    colors = ['#2ecc71', '#e74c3c']
    
    # Only show pie chart if there are results
    if sum(sizes) > 0:
        wedges, texts, autotexts = plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', 
                                          startangle=90, textprops={'fontsize': 12, 'fontweight': 'bold'})
        
        # Make percentage text white for better visibility
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(14)
    else:
        plt.text(0.5, 0.5, 'No Test Results', ha='center', va='center', fontsize=16, fontweight='bold')
        plt.xlim(0, 1)
        plt.ylim(0, 1)
    
    plt.title('Overall Test Results Summary', fontsize=16, fontweight='bold', pad=20)
    plt.axis('equal')
    plt.tight_layout()
    
    # Convert to base64
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64

def generate_html_report(analysis_report: AnalysisReport, output_path: Path) -> None:
    """Generate comprehensive HTML report with embedded charts."""
    # Generate charts
    pass_fail_chart = generate_pass_fail_chart(analysis_report.filter_summaries)
    breakdown_chart = generate_validation_breakdown_chart(analysis_report.filter_summaries)
    summary_chart = generate_overall_summary_chart(analysis_report)
    
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Comprehensive Filter Test Results Analysis</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f6fa;
            color: #2c3e50;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 2.5em;
            font-weight: 300;
        }}
        .header .subtitle {{
            margin: 10px 0 0 0;
            font-size: 1.1em;
            opacity: 0.9;
        }}
        .summary-stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            padding: 30px;
            background: #f8f9fa;
        }}
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .stat-number {{
            font-size: 2.5em;
            font-weight: bold;
            margin: 0;
        }}
        .stat-label {{
            color: #7f8c8d;
            margin: 5px 0 0 0;
            font-size: 0.9em;
        }}
        .pass {{ color: #27ae60; }}
        .fail {{ color: #e74c3c; }}
        .warning {{ color: #f39c12; }}
        .section {{
            padding: 30px;
            border-bottom: 1px solid #ecf0f1;
        }}
        .section h2 {{
            margin: 0 0 20px 0;
            color: #2c3e50;
            font-size: 1.8em;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }}
        .chart-container {{
            text-align: center;
            margin: 20px 0;
        }}
        .chart-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .filter-section {{
            margin: 20px 0;
            border: 1px solid #ddd;
            border-radius: 8px;
            overflow: hidden;
        }}
        .filter-header {{
            background: #34495e;
            color: white;
            padding: 15px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .filter-header:hover {{
            background: #2c3e50;
        }}
        .filter-content {{
            padding: 20px;
            background: white;
        }}
        .scenario-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        .scenario-table th,
        .scenario-table td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        .scenario-table th {{
            background: #f8f9fa;
            font-weight: 600;
        }}
        .scenario-table tr:nth-child(even) {{
            background: #f8f9fa;
        }}
        .status-pass {{ color: #27ae60; font-weight: bold; }}
        .status-fail {{ color: #e74c3c; font-weight: bold; }}
        .status-warning {{ color: #f39c12; font-weight: bold; }}
        .recommendations {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
        }}
        .recommendations ul {{
            margin: 0;
            padding-left: 20px;
        }}
        .recommendations li {{
            margin: 8px 0;
            line-height: 1.5;
        }}
        .error-details {{
            background: #fff5f5;
            border: 1px solid #fed7d7;
            border-radius: 4px;
            padding: 10px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 0.9em;
        }}
        .warning-details {{
            background: #fffbeb;
            border: 1px solid #f6e05e;
            border-radius: 4px;
            padding: 10px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 0.9em;
        }}
        .collapsible {{
            display: none;
        }}
        .collapsible.active {{
            display: block;
        }}
        .toggle-icon {{
            transition: transform 0.3s ease;
        }}
        .toggle-icon.rotated {{
            transform: rotate(180deg);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Comprehensive Filter Test Results Analysis</h1>
            <div class="subtitle">
                Generated: {analysis_report.timestamp} | 
                Execution Time: {analysis_report.execution_time:.2f}s
            </div>
        </div>
        
        <div class="summary-stats">
            <div class="stat-card">
                <div class="stat-number pass">{analysis_report.total_passed}</div>
                <div class="stat-label">Passed Scenarios</div>
            </div>
            <div class="stat-card">
                <div class="stat-number fail">{analysis_report.total_failed}</div>
                <div class="stat-label">Failed Scenarios</div>
            </div>
            <div class="stat-card">
                <div class="stat-number {'pass' if analysis_report.overall_pass_rate >= 80 else 'fail'}">{analysis_report.overall_pass_rate:.1f}%</div>
                <div class="stat-label">Overall Pass Rate</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{analysis_report.total_scenarios}</div>
                <div class="stat-label">Total Scenarios</div>
            </div>
        </div>
        
        <div class="section">
            <h2>📊 Overall Summary</h2>
            <div class="chart-container">
                <img src="data:image/png;base64,{summary_chart}" alt="Overall Summary Chart">
            </div>
        </div>
        
        <div class="section">
            <h2>📈 Filter Results Breakdown</h2>
            <div class="chart-container">
                <img src="data:image/png;base64,{pass_fail_chart}" alt="Pass/Fail Chart">
            </div>
        </div>
        
        <div class="section">
            <h2>🔍 Validation Issues Analysis</h2>
            <div class="chart-container">
                <img src="data:image/png;base64,{breakdown_chart}" alt="Validation Breakdown Chart">
            </div>
        </div>
        
        <div class="section">
            <h2>📋 Filter-by-Filter Results</h2>
"""
    
    # Add filter sections
    for filter_type, summary in analysis_report.filter_summaries.items():
        status_class = "pass" if summary.pass_rate == 100 else "fail" if summary.pass_rate < 50 else "warning"
        status_icon = "✅" if summary.pass_rate == 100 else "❌" if summary.pass_rate < 50 else "⚠️"
        
        html_content += f"""
            <div class="filter-section">
                <div class="filter-header" onclick="toggleFilter('{filter_type}')">
                    <span>{status_icon} {filter_type.replace('_', ' ').title()} - {summary.pass_rate:.1f}% Pass Rate</span>
                    <span class="toggle-icon" id="icon-{filter_type}">▼</span>
                </div>
                <div class="filter-content collapsible" id="content-{filter_type}">
                    <p><strong>Scenarios:</strong> {summary.passed_scenarios}/{summary.total_scenarios} passed</p>
                    <p><strong>Issues:</strong> {summary.trade_count_mismatches} trade count, {summary.rejection_reason_mismatches} rejection reason, {summary.filter_behavior_issues} behavior</p>
                    
                    <table class="scenario-table">
                        <thead>
                            <tr>
                                <th>Scenario</th>
                                <th>Symbol</th>
                                <th>Status</th>
                                <th>Trade Count</th>
                                <th>Rejection Reason</th>
                                <th>Issues</th>
                            </tr>
                        </thead>
                        <tbody>
"""
        
        for result in summary.scenarios:
            status_class = "status-pass" if result.passed else "status-fail"
            if result.validation_warnings:
                status_class = "status-warning"
            
            status_icon = "✅" if result.passed else "❌"
            if result.validation_warnings:
                status_icon = "⚠️"
            
            trade_count_text = f"{result.trade_count_actual}/{result.trade_count_expected}"
            rejection_text = f"Expected: {result.rejection_reason_expected or 'None'}<br>Actual: {', '.join(result.rejection_reasons_actual) or 'None'}"
            
            issues_text = ""
            if result.validation_errors:
                issues_text += f"<strong>Errors:</strong> {len(result.validation_errors)}<br>"
            if result.validation_warnings:
                issues_text += f"<strong>Warnings:</strong> {len(result.validation_warnings)}"
            
            html_content += f"""
                            <tr>
                                <td>{result.scenario.scenario_name}</td>
                                <td>{result.scenario.symbol}</td>
                                <td class="{status_class}">{status_icon}</td>
                                <td>{trade_count_text}</td>
                                <td>{rejection_text}</td>
                                <td>{issues_text}</td>
                            </tr>
"""
            
            # Add detailed error/warning information
            if result.validation_errors or result.validation_warnings:
                html_content += f"""
                            <tr>
                                <td colspan="6">
"""
                if result.validation_errors:
                    html_content += f"""
                                    <div class="error-details">
                                        <strong>Validation Errors:</strong><br>
                                        {'<br>'.join(result.validation_errors)}
                                    </div>
"""
                if result.validation_warnings:
                    html_content += f"""
                                    <div class="warning-details">
                                        <strong>Validation Warnings:</strong><br>
                                        {'<br>'.join(result.validation_warnings)}
                                    </div>
"""
                html_content += """
                                </td>
                            </tr>
"""
        
        html_content += """
                        </tbody>
                    </table>
                </div>
            </div>
"""
    
    # Add deep-dive section for failed scenarios
    failed_scenarios = [r for r in analysis_report.validation_results if not r.passed]
    if failed_scenarios:
        html_content += f"""
        </div>
        
        <div class="section">
            <h2>🔍 Deep Dive: Failed Scenarios</h2>
            <p>Detailed analysis of failed test scenarios with configuration and performance data.</p>
"""
        
        for i, result in enumerate(failed_scenarios, 1):
            # Load rejected signals for display
            rejected_signals = []
            if result.output_dir:
                rejected_signals = load_rejected_signals(result.output_dir)
            
            # Get first N rows from rejected signals
            display_signals = rejected_signals[:5]  # First 5 rows
            
            html_content += f"""
            <div class="filter-section">
                <div class="filter-header" onclick="toggleFailedScenario('failed_{i}')">
                    <span>❌ {result.scenario.filter_type}/{result.scenario.scenario_name} - {result.scenario.symbol}</span>
                    <span class="toggle-icon" id="icon-failed_{i}">▼</span>
                </div>
                <div class="filter-content collapsible" id="content-failed_{i}">
                    <h3>Test Purpose</h3>
                    <p>{result.scenario.test_purpose}</p>
                    
                    <h3>Filter Configuration</h3>
                    <div class="error-details">
                        <pre>{json.dumps(result.scenario.filter_config, indent=2)}</pre>
                    </div>
                    
                    <h3>Performance Summary</h3>
                    <div class="warning-details">
                        <p><strong>Trade Count:</strong> {result.trade_count_actual}/{result.trade_count_expected}</p>
                        <p><strong>Rejection Count:</strong> {result.rejection_count}</p>
                        <p><strong>Rejection Reasons:</strong> {', '.join(result.rejection_reasons_actual) or 'None'}</p>
                    </div>
                    
                    <h3>Validation Issues</h3>
                    <div class="error-details">
                        <strong>Errors ({len(result.validation_errors)}):</strong><br>
                        {'<br>'.join(result.validation_errors) if result.validation_errors else 'None'}
                    </div>
                    {f'<div class="warning-details"><strong>Warnings ({len(result.validation_warnings)}):</strong><br>{"<br>".join(result.validation_warnings)}</div>' if result.validation_warnings else ''}
                    
                    <h3>Rejected Signals Sample (First 5)</h3>
                    <div class="warning-details">
                        {f'<table class="scenario-table"><thead><tr><th>Timestamp</th><th>Reason</th><th>Details</th></tr></thead><tbody>' + ''.join([f'<tr><td>{signal.get("timestamp", "")}</td><td>{signal.get("reason", "")}</td><td>{signal.get("details", "")}</td></tr>' for signal in display_signals]) + '</tbody></table>' if display_signals else '<p>No rejected signals found</p>'}
                    </div>
                    
                    <h3>Output Directory</h3>
                    <p><a href="file:///{result.output_dir}" target="_blank">{result.output_dir}</a></p>
                </div>
            </div>
"""
        
        html_content += """
        </div>
"""
    
    # Add recommendations section
    html_content += f"""
        </div>
        
        <div class="section">
            <h2>💡 Recommendations</h2>
            <div class="recommendations">
                <ul>
"""
    
    for i, recommendation in enumerate(analysis_report.recommendations, 1):
        html_content += f"                    <li>{recommendation}</li>\n"
    
    html_content += f"""
                </ul>
            </div>
        </div>
        
        <div class="section">
            <h2>📁 Test Configuration</h2>
            <p><strong>Results Directory:</strong> {RESULTS_BASE}</p>
            <p><strong>Catalog Directory:</strong> {CATALOG_BASE}</p>
            <p><strong>Filter Types Tested:</strong> {', '.join(FILTER_TYPES)}</p>
        </div>
        
        <div class="section">
            <h2>📋 Appendix</h2>
            <h3>Directory Paths</h3>
            <ul>
                <li><strong>Results Base:</strong> {RESULTS_BASE}</li>
                <li><strong>Catalog Base:</strong> {CATALOG_BASE}</li>
            </ul>
            
            <h3>Execution Environment</h3>
            <ul>
                <li><strong>Python Version:</strong> {sys.version}</li>
                <li><strong>Operating System:</strong> {sys.platform}</li>
                <li><strong>Analysis Timestamp:</strong> {analysis_report.timestamp}</li>
                <li><strong>Execution Time:</strong> {analysis_report.execution_time:.2f} seconds</li>
            </ul>
            
            <h3>Filter Types Analyzed</h3>
            <ul>
                {''.join([f'<li>{ft}</li>' for ft in FILTER_TYPES])}
            </ul>
        </div>
    </div>
    
    <script>
        function toggleFilter(filterType) {{
            const content = document.getElementById('content-' + filterType);
            const icon = document.getElementById('icon-' + filterType);
            
            if (content.classList.contains('active')) {{
                content.classList.remove('active');
                icon.classList.remove('rotated');
            }} else {{
                content.classList.add('active');
                icon.classList.add('rotated');
            }}
        }}
        
        function toggleFailedScenario(scenarioId) {{
            const content = document.getElementById('content-' + scenarioId);
            const icon = document.getElementById('icon-' + scenarioId);
            
            if (content.classList.contains('active')) {{
                content.classList.remove('active');
                icon.classList.remove('rotated');
            }} else {{
                content.classList.add('active');
                icon.classList.add('rotated');
            }}
        }}
        
        // Auto-expand failed filters
        document.addEventListener('DOMContentLoaded', function() {{
            const filterSections = document.querySelectorAll('.filter-section');
            filterSections.forEach(section => {{
                const header = section.querySelector('.filter-header');
                const content = section.querySelector('.filter-content');
                const statusFail = content.querySelector('.status-fail');
                
                if (statusFail) {{
                    content.classList.add('active');
                    const icon = section.querySelector('.toggle-icon');
                    icon.classList.add('rotated');
                }}
            }});
        }});
    </script>
</body>
</html>
"""
    
    # Write HTML file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    logging.info(f"📊 HTML report generated at {output_path}")

def print_console_report(analysis_report: AnalysisReport) -> None:
    """Print formatted console report."""
    print("\n" + "="*80)
    print("🔍 COMPREHENSIVE FILTER TEST RESULTS ANALYSIS")
    print("="*80)
    print(f"Generated: {analysis_report.timestamp}")
    print(f"Execution Time: {analysis_report.execution_time:.2f}s")
    print()
    
    # Overall summary
    print("📊 OVERALL SUMMARY")
    print("-" * 40)
    print(f"Total Scenarios: {analysis_report.total_scenarios}")
    print(f"Passed: {analysis_report.total_passed} ✅")
    print(f"Failed: {analysis_report.total_failed} ❌")
    print(f"Pass Rate: {analysis_report.overall_pass_rate:.1f}%")
    print()
    
    # Filter breakdown
    print("📈 FILTER BREAKDOWN")
    print("-" * 40)
    print(f"{'Filter Type':<20} {'Passed':<8} {'Failed':<8} {'Pass Rate':<10} {'Issues':<8}")
    print("-" * 80)
    
    for filter_type, summary in analysis_report.filter_summaries.items():
        status_icon = "✅" if summary.pass_rate == 100 else "❌" if summary.pass_rate < 50 else "⚠️"
        total_issues = summary.trade_count_mismatches + summary.rejection_reason_mismatches + summary.filter_behavior_issues
        print(f"{filter_type:<20} {summary.passed_scenarios:<8} {summary.failed_scenarios:<8} {summary.pass_rate:>7.1f}% {total_issues:>6} {status_icon}")
    
    print()
    
    # Failed scenarios details
    failed_scenarios = [r for r in analysis_report.validation_results if not r.passed]
    if failed_scenarios:
        print("❌ FAILED SCENARIOS")
        print("-" * 40)
        for result in failed_scenarios:
            print(f"\n{result.scenario.filter_type}/{result.scenario.scenario_name}:")
            print(f"  Symbol: {result.scenario.symbol}")
            print(f"  Trade Count: {result.trade_count_actual}/{result.trade_count_expected}")
            print(f"  Rejection Reason: {result.rejection_reason_expected} -> {', '.join(result.rejection_reasons_actual)}")
            
            if result.validation_errors:
                print(f"  Errors: {'; '.join(result.validation_errors)}")
            if result.validation_warnings:
                print(f"  Warnings: {'; '.join(result.validation_warnings)}")
    
    # Recommendations
    if analysis_report.recommendations:
        print("\n💡 RECOMMENDATIONS")
        print("-" * 40)
        for i, recommendation in enumerate(analysis_report.recommendations, 1):
            print(f"{i}. {recommendation}")
    
    print("\n" + "="*80)

def export_json_report(analysis_report: AnalysisReport, output_path: Path) -> None:
    """Export analysis report as JSON."""
    # Convert dataclasses to dictionaries for JSON serialization
    report_dict = asdict(analysis_report)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(report_dict, f, indent=2, default=str)
    
    logging.info(f"📄 JSON report exported to {output_path}")

def run_analysis(results_base: Path, catalog_base: Path, 
                filter_types: Optional[List[str]] = None, 
                scenarios: Optional[List[str]] = None) -> AnalysisReport:
    """Run complete analysis of filter test results."""
    start_time = time.time()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Validate directories with graceful handling
    if not results_base.exists():
        logging.warning(f"Results directory not found: {results_base}")
        return AnalysisReport(
            timestamp=datetime.now().isoformat(),
            total_scenarios=0,
            total_passed=0,
            total_failed=0,
            overall_pass_rate=0,
            filter_summaries={},
            validation_results=[],
            recommendations=[f"Results directory not found: {results_base}. Generate test data or run backtests first."],
            execution_time=time.time() - start_time
        )
    if not catalog_base.exists():
        logging.warning(f"Catalog directory not found: {catalog_base}")
        return AnalysisReport(
            timestamp=datetime.now().isoformat(),
            total_scenarios=0,
            total_passed=0,
            total_failed=0,
            overall_pass_rate=0,
            filter_summaries={},
            validation_results=[],
            recommendations=[f"Catalog directory not found: {catalog_base}. Generate test data or run backtests first."],
            execution_time=time.time() - start_time
        )
    
    # Discover scenarios
    logging.info("🔍 Discovering test scenarios...")
    all_scenarios = discover_scenarios(results_base, catalog_base)
    
    if not all_scenarios:
        logging.warning("No scenarios found!")
        return AnalysisReport(
            timestamp=datetime.now().isoformat(),
            total_scenarios=0,
            total_passed=0,
            total_failed=0,
            overall_pass_rate=0,
            filter_summaries={},
            validation_results=[],
            recommendations=["No test scenarios found. Run filter test generation first."],
            execution_time=time.time() - start_time
        )
    
    # Filter scenarios based on arguments
    filtered_scenarios = all_scenarios
    if filter_types:
        filtered_scenarios = [s for s in filtered_scenarios if s.filter_type in filter_types]
    if scenarios:
        filtered_scenarios = [s for s in filtered_scenarios if s.scenario_name in scenarios]
    
    filter_count = len(set(s.filter_type for s in filtered_scenarios))
    logging.info(f"🔍 Analyzing {len(filtered_scenarios)} scenarios across {filter_count} filters")
    
    # Validate scenarios
    validation_results = []
    for i, scenario in enumerate(filtered_scenarios, 1):
        logging.info(f"[{i}/{len(filtered_scenarios)}] Validating {scenario.filter_type}/{scenario.scenario_name}...")
        result = validate_scenario(scenario, results_base)
        validation_results.append(result)
    
    # Aggregate results
    logging.info("📊 Aggregating results...")
    analysis_report = aggregate_results(validation_results)
    analysis_report.execution_time = time.time() - start_time
    
    # Log final summary
    logging.info(f"🎉 Analysis completed in {analysis_report.execution_time:.2f}s")
    logging.info(f"📊 Results: {analysis_report.total_passed}/{analysis_report.total_scenarios} passed ({analysis_report.overall_pass_rate:.1f}%)")
    
    return analysis_report

def main():
    """Main entry point with command-line interface."""
    parser = argparse.ArgumentParser(
        description="Analyze comprehensive filter test results and generate validation report"
    )
    
    parser.add_argument(
        '--results-dir',
        type=Path,
        default=RESULTS_BASE,
        help=f"Path to results directory (default: {RESULTS_BASE})"
    )
    parser.add_argument(
        '--catalog-dir',
        type=Path,
        default=CATALOG_BASE,
        help=f"Path to catalog directory (default: {CATALOG_BASE})"
    )
    parser.add_argument(
        '--filter',
        choices=FILTER_TYPES,
        help="Filter type to analyze"
    )
    parser.add_argument(
        '--scenario',
        help="Specific scenario name to analyze"
    )
    parser.add_argument(
        '--output-html',
        type=Path,
        default=Path("reports/filter_test_analysis.html"),
        help="Path for HTML report (default: reports/filter_test_analysis.html)"
    )
    parser.add_argument(
        '--output-json',
        type=Path,
        help="Path for JSON report (optional)"
    )
    parser.add_argument(
        '--no-html',
        action='store_true',
        help="Skip HTML report generation"
    )
    parser.add_argument(
        '--no-console',
        action='store_true',
        help="Skip console report"
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help="Enable DEBUG logging"
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help="List all available scenarios and exit"
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # List scenarios if requested
        if args.list:
            scenarios = discover_scenarios(args.results_dir, args.catalog_dir)
            if not scenarios:
                print("No scenarios found.")
                return 0
            
            print(f"Found {len(scenarios)} scenarios:")
            print()
            for filter_type in FILTER_TYPES:
                filter_scenarios = [s for s in scenarios if s.filter_type == filter_type]
                if filter_scenarios:
                    print(f"{filter_type}:")
                    for scenario in filter_scenarios:
                        print(f"  - {scenario.scenario_name} ({scenario.symbol})")
                    print()
            return 0
        
        # Run analysis
        filter_types = [args.filter] if args.filter else None
        scenarios = [args.scenario] if args.scenario else None
        
        analysis_report = run_analysis(args.results_dir, args.catalog_dir, filter_types, scenarios)
        
        # Generate reports
        if not args.no_console:
            print_console_report(analysis_report)
        
        if not args.no_html:
            generate_html_report(analysis_report, args.output_html)
        
        if args.output_json:
            export_json_report(analysis_report, args.output_json)
        
        # Return appropriate exit code
        if analysis_report.total_failed == 0 and not any("not found" in rec for rec in analysis_report.recommendations):
            return 0  # All passed
        elif any("not found" in rec for rec in analysis_report.recommendations):
            return 2  # Missing directories
        else:
            return 1  # Some failures
    
    except FileNotFoundError as e:
        logging.error(f"File not found: {e}")
        return 2
    except json.JSONDecodeError as e:
        logging.error(f"JSON decode error: {e}")
        return 2
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        return 2

if __name__ == "__main__":
    sys.exit(main())
