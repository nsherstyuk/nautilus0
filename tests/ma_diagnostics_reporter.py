"""
MA Diagnostics Reporter

Report generation for MA diagnostics with multiple output formats.
This module provides comprehensive reporting capabilities including console summaries,
HTML reports with embedded charts, and JSON exports for programmatic access.

Supports:
- Console summary with color-coded status indicators
- HTML report with embedded charts and interactive elements
- JSON export for programmatic access
- Multiple chart types: scenario results, issue distribution, trade counts, timing analysis

Usage:
    Called by run_ma_diagnostics.py
"""

import sys
from pathlib import Path
from typing import Dict, List, Any
import json
import base64
from io import BytesIO

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Add project root to sys.path for module imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ma_diagnostics_analyzer import MADiagnosticReport, DiagnosticResult


def create_scenario_results_chart(results: List[DiagnosticResult]) -> str:
    """
    Create bar chart showing passed vs. failed scenarios.
    
    Args:
        results: List of diagnostic results
        
    Returns:
        Base64-encoded PNG image string for HTML embedding
    """
    try:
        # Prepare data
        scenario_names = [r.scenario.name.replace('_', ' ').title() for r in results]
        status_values = [1 if r.passed else 0 for r in results]
        colors = ['#28a745' if r.passed else '#dc3545' for r in results]
        
        # Create figure
        plt.figure(figsize=(12, 6))
        bars = plt.bar(scenario_names, status_values, color=colors, alpha=0.7)
        
        # Customize chart
        plt.title('Diagnostic Scenario Results', fontsize=16, fontweight='bold')
        plt.ylabel('Status (1=Pass, 0=Fail)', fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.ylim(-0.1, 1.1)
        
        # Add value labels on bars
        for bar, value in zip(bars, status_values):
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                    'PASS' if value == 1 else 'FAIL',
                    ha='center', va='bottom', fontweight='bold')
        
        plt.tight_layout()
        
        # Convert to base64
        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
        
    except Exception as e:
        print(f"Error creating scenario results chart: {e}")
        return ""


def create_issue_distribution_chart(detected_issues: Dict[str, List[str]]) -> str:
    """
    Create pie chart showing distribution of detected issues by category.
    
    Args:
        detected_issues: Dictionary mapping issue categories to findings
        
    Returns:
        Base64-encoded PNG image string
    """
    try:
        if not detected_issues:
            return ""
        
        # Prepare data
        categories = list(detected_issues.keys())
        counts = [len(findings) for findings in detected_issues.values()]
        
        # Create figure
        plt.figure(figsize=(10, 8))
        colors = plt.cm.Set3(range(len(categories)))
        
        wedges, texts, autotexts = plt.pie(counts, labels=categories, colors=colors, 
                                          autopct='%1.1f%%', startangle=90)
        
        # Customize chart
        plt.title('Distribution of Detected Issues', fontsize=16, fontweight='bold')
        
        # Improve text readability
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
        
        plt.axis('equal')
        plt.tight_layout()
        
        # Convert to base64
        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
        
    except Exception as e:
        print(f"Error creating issue distribution chart: {e}")
        return ""


def create_trade_count_comparison_chart(results: List[DiagnosticResult]) -> str:
    """
    Create grouped bar chart comparing expected vs. actual trade counts per scenario.
    
    Args:
        results: List of diagnostic results
        
    Returns:
        Base64-encoded PNG image string
    """
    try:
        # Prepare data
        scenario_names = [r.scenario.name.replace('_', ' ').title() for r in results]
        expected_trades = [r.scenario.expected_trades for r in results]
        actual_trades = [r.actual_trades for r in results]
        
        # Create figure
        fig, ax = plt.subplots(figsize=(14, 8))
        
        x = range(len(scenario_names))
        width = 0.35
        
        # Create bars
        bars1 = ax.bar([i - width/2 for i in x], expected_trades, width, 
                      label='Expected', color='#007bff', alpha=0.7)
        bars2 = ax.bar([i + width/2 for i in x], actual_trades, width,
                      label='Actual', color='#ffc107', alpha=0.7)
        
        # Highlight mismatches
        for i, (exp, act) in enumerate(zip(expected_trades, actual_trades)):
            if exp != act:
                bars2[i].set_edgecolor('red')
                bars2[i].set_linewidth(2)
        
        # Customize chart
        ax.set_title('Expected vs Actual Trade Counts', fontsize=16, fontweight='bold')
        ax.set_ylabel('Number of Trades', fontsize=12)
        ax.set_xlabel('Scenarios', fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels(scenario_names, rotation=45, ha='right')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                       f'{int(height)}', ha='center', va='bottom', fontsize=9)
        
        plt.tight_layout()
        
        # Convert to base64
        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
        
    except Exception as e:
        print(f"Error creating trade count comparison chart: {e}")
        return ""


def create_timing_lag_chart(results: List[DiagnosticResult]) -> str:
    """
    Create bar chart showing crossover timing lag for scenarios where applicable.
    
    Args:
        results: List of diagnostic results
        
    Returns:
        Base64-encoded PNG image string
    """
    try:
        # Filter results with timing data
        timing_results = [r for r in results if r.crossover_timing_bars is not None]
        
        if not timing_results:
            return ""
        
        # Prepare data
        scenario_names = [r.scenario.name.replace('_', ' ').title() for r in timing_results]
        timing_lags = [r.crossover_timing_bars for r in timing_results]
        
        # Color code based on lag severity
        colors = []
        for lag in timing_lags:
            if lag == 0:
                colors.append('#28a745')  # Green for on-time
            elif abs(lag) <= 2:
                colors.append('#ffc107')  # Yellow for slight lag
            else:
                colors.append('#dc3545')  # Red for significant lag
        
        # Create figure
        plt.figure(figsize=(12, 6))
        bars = plt.bar(scenario_names, timing_lags, color=colors, alpha=0.7)
        
        # Customize chart
        plt.title('Crossover Timing Lag Analysis', fontsize=16, fontweight='bold')
        plt.ylabel('Lag in Bars (positive=late, negative=early)', fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        plt.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for bar, lag in zip(bars, timing_lags):
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., 
                    height + (0.1 if height >= 0 else -0.3),
                    f'{lag}', ha='center', va='bottom' if height >= 0 else 'top',
                    fontweight='bold')
        
        plt.tight_layout()
        
        # Convert to base64
        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
        
    except Exception as e:
        print(f"Error creating timing lag chart: {e}")
        return ""


def create_crossover_verification_chart(results: List[DiagnosticResult]) -> str:
    """
    Create chart showing detected vs missed crossovers per scenario.
    
    Args:
        results: List of diagnostic results
        
    Returns:
        Base64-encoded PNG image string
    """
    try:
        # Filter results that have crossover verifications
        verification_results = [r for r in results if r.crossover_verifications]
        
        if not verification_results:
            return ""
        
        # Prepare data
        scenario_names = [r.scenario.name.replace('_', ' ').title() for r in verification_results]
        detected_counts = [r.detected_crossovers_count for r in verification_results]
        missed_counts = [r.missed_crossovers_count for r in verification_results]
        false_positive_counts = [r.false_positive_count for r in verification_results]
        
        # Create figure
        fig, ax = plt.subplots(figsize=(14, 8))
        
        x = range(len(scenario_names))
        width = 0.25
        
        # Create stacked bars
        bars1 = ax.bar([i - width for i in x], detected_counts, width, 
                      label='Detected', color='#28a745', alpha=0.7)
        bars2 = ax.bar(x, missed_counts, width,
                      label='Missed', color='#dc3545', alpha=0.7)
        bars3 = ax.bar([i + width for i in x], false_positive_counts, width,
                      label='False Positives', color='#ffc107', alpha=0.7)
        
        # Customize chart
        ax.set_title('Crossover Detection Accuracy by Scenario', fontsize=16, fontweight='bold')
        ax.set_ylabel('Number of Crossovers', fontsize=12)
        ax.set_xlabel('Scenarios', fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels(scenario_names, rotation=45, ha='right')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for bars in [bars1, bars2, bars3]:
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                           f'{int(height)}', ha='center', va='bottom', fontsize=9)
        
        plt.tight_layout()
        
        # Convert to base64
        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
        
    except Exception as e:
        print(f"Error creating crossover verification chart: {e}")
        return ""


def print_console_report(report: MADiagnosticReport) -> None:
    """
    Print formatted text report to console.
    
    Args:
        report: Diagnostic report to display
    """
    print("\n" + "=" * 80)
    print("MA CROSSOVER DIAGNOSTICS REPORT")
    print("=" * 80)
    print(f"Generated: {report.timestamp}")
    print()
    
    # Summary Section
    print("SUMMARY")
    print("-" * 40)
    tested = report.scenarios_tested
    pass_rate = (report.scenarios_passed / tested * 100) if tested else 0.0
    print(f"Scenarios tested: {report.scenarios_tested}")
    print(f"Scenarios passed: {report.scenarios_passed} ({pass_rate:.1f}%)")
    print(f"Scenarios failed: {report.scenarios_failed}")
    print(f"Issues detected: {len(report.detected_issues)} categories")
    print()
    
    # Scenario Results Table
    print("SCENARIO RESULTS")
    print("-" * 80)
    print(f"{'Scenario':<20} {'Expected':<8} {'Actual':<8} {'Status':<8} {'Issues':<30}")
    print("-" * 80)
    
    for result in report.results:
        scenario_name = result.scenario.name.replace('_', ' ').title()
        expected = str(result.scenario.expected_trades)
        actual = str(result.actual_trades)
        status = "✓ PASS" if result.passed else "✗ FAIL"
        issues = ", ".join(result.issues_detected[:2])  # Show first 2 issues
        if len(result.issues_detected) > 2:
            issues += "..."
        
        print(f"{scenario_name:<20} {expected:<8} {actual:<8} {status:<8} {issues:<30}")
    
    print()
    
    # Crossover-Level Verification Section
    verification_results = [r for r in report.results if r.crossover_verifications]
    if verification_results:
        print("CROSSOVER-LEVEL VERIFICATION")
        print("-" * 80)
        
        for result in verification_results:
            scenario_name = result.scenario.name.replace('_', ' ').title()
            print(f"\n{scenario_name}:")
            print(f"  Expected: {result.expected_crossovers_count}, Detected: {result.detected_crossovers_count}, Missed: {result.missed_crossovers_count}, False Positives: {result.false_positive_count}")
            
            # Show individual crossovers (limit to first 10)
            crossovers_to_show = result.crossover_verifications[:10]
            if crossovers_to_show:
                print("  Individual Crossovers:")
                print(f"    {'Bar':<6} {'Timestamp':<20} {'Type':<8} {'Status':<12} {'Timing':<8} {'Issue':<30}")
                print("    " + "-" * 80)
                
                for v in crossovers_to_show:
                    if v.expected_bar_index >= 0:  # Real crossover, not false positive
                        status = "✅ Detected" if v.detected else "❌ Missed"
                        timing = f"{v.timing_error_bars:+d}" if v.timing_error_bars is not None else "N/A"
                        issue = v.issue or "None"
                        print(f"    {v.expected_bar_index:<6} {v.expected_timestamp[:19]:<20} {v.expected_type:<8} {status:<12} {timing:<8} {issue:<30}")
                    else:  # False positive
                        status = "🔶 False Positive"
                        timing = "N/A"
                        issue = v.issue or "None"
                        print(f"    {v.actual_bar_index:<6} {v.actual_timestamp[:19]:<20} {'N/A':<8} {status:<12} {timing:<8} {issue:<30}")
                
                if len(result.crossover_verifications) > 10:
                    print(f"    ... and {len(result.crossover_verifications) - 10} more crossovers")
        
        print()
    
    # Detected Issues Section
    if report.detected_issues:
        print("DETECTED ISSUES")
        print("-" * 40)
        for category, findings in report.detected_issues.items():
            print(f"\n{category}:")
            for finding in findings:
                print(f"  • {finding}")
        print()
    
    # Improvement Suggestions Section
    if report.suggestions:
        print("IMPROVEMENT SUGGESTIONS")
        print("-" * 40)
        for i, suggestion in enumerate(report.suggestions, 1):
            priority = suggestion.get('priority', 'medium').upper()
            print(f"\n{i}. [{priority}] {suggestion['suggestion']}")
            print(f"   Rationale: {suggestion['rationale']}")
        print()
    
    # Performance Summary
    if report.performance_summary:
        print("PERFORMANCE SUMMARY")
        print("-" * 40)
        summary = report.performance_summary
        print(f"Total trades executed: {summary.get('total_trades', 0)}")
        print(f"Total PnL: {summary.get('total_pnl', 0):.2f}")
        print(f"Average win rate: {summary.get('avg_win_rate', 0):.1f}%")
        print(f"Average timing lag: {summary.get('avg_timing_lag_bars', 0):.1f} bars")
        print()
    
    print("=" * 80)


def generate_html_report(report: MADiagnosticReport, output_path: Path) -> None:
    """
    Generate comprehensive HTML report with embedded charts.
    
    Args:
        report: Diagnostic report to generate HTML for
        output_path: Path to write HTML file
    """
    try:
        # Generate charts
        scenario_chart = create_scenario_results_chart(report.results)
        issue_chart = create_issue_distribution_chart(report.detected_issues)
        trade_chart = create_trade_count_comparison_chart(report.results)
        timing_chart = create_timing_lag_chart(report.results)
        crossover_chart = create_crossover_verification_chart(report.results)
        
        # HTML template
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MA Crossover Diagnostics Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f8f9fa;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 0 20px rgba(0,0,0,0.1);
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
            color: #6c757d;
            margin: 10px 0 0 0;
        }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            border-left: 4px solid #007bff;
        }}
        .card h3 {{
            margin: 0 0 10px 0;
            color: #495057;
        }}
        .card .number {{
            font-size: 2em;
            font-weight: bold;
            color: #007bff;
        }}
        .card.success .number {{
            color: #28a745;
        }}
        .card.danger .number {{
            color: #dc3545;
        }}
        .section {{
            margin-bottom: 40px;
        }}
        .section h2 {{
            color: #495057;
            border-bottom: 2px solid #e9ecef;
            padding-bottom: 10px;
        }}
        .chart-container {{
            text-align: center;
            margin: 20px 0;
        }}
        .chart-container img {{
            max-width: 100%;
            height: auto;
            border: 1px solid #dee2e6;
            border-radius: 8px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #dee2e6;
        }}
        th {{
            background-color: #f8f9fa;
            font-weight: bold;
        }}
        .status-pass {{
            color: #28a745;
            font-weight: bold;
        }}
        .status-fail {{
            color: #dc3545;
            font-weight: bold;
        }}
        .suggestion {{
            background: #f8f9fa;
            border-left: 4px solid #007bff;
            padding: 15px;
            margin: 10px 0;
            border-radius: 4px;
        }}
        .suggestion.high {{
            border-left-color: #dc3545;
        }}
        .suggestion.medium {{
            border-left-color: #ffc107;
        }}
        .suggestion.low {{
            border-left-color: #6c757d;
        }}
        .priority-badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .priority-high {{
            background-color: #dc3545;
            color: white;
        }}
        .priority-medium {{
            background-color: #ffc107;
            color: black;
        }}
        .priority-low {{
            background-color: #6c757d;
            color: white;
        }}
        .issue-category {{
            margin: 20px 0;
        }}
        .issue-category h4 {{
            color: #dc3545;
            margin-bottom: 10px;
        }}
        .issue-list {{
            list-style: none;
            padding: 0;
        }}
        .issue-list li {{
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            padding: 10px;
            margin: 5px 0;
            border-radius: 4px;
        }}
        .success {{
            background-color: #d4edda !important;
        }}
        .danger {{
            background-color: #f8d7da !important;
        }}
        .warning {{
            background-color: #fff3cd !important;
        }}
        details {{
            margin: 20px 0;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 15px;
        }}
        summary {{
            cursor: pointer;
            font-weight: bold;
            padding: 10px;
            background-color: #f8f9fa;
            border-radius: 4px;
            margin: -15px -15px 15px -15px;
        }}
        summary:hover {{
            background-color: #e9ecef;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #dee2e6;
            color: #6c757d;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>MA Crossover Diagnostics Report</h1>
            <p>Generated: {report.timestamp}</p>
        </div>
        
        <!-- Executive Summary -->
        <div class="section">
            <h2>Executive Summary</h2>
            <div class="summary-cards">
                <div class="card">
                    <h3>Scenarios Tested</h3>
                    <div class="number">{report.scenarios_tested}</div>
                </div>
                <div class="card success">
                    <h3>Scenarios Passed</h3>
                    <div class="number">{report.scenarios_passed}</div>
                </div>
                <div class="card danger">
                    <h3>Scenarios Failed</h3>
                    <div class="number">{report.scenarios_failed}</div>
                </div>
                <div class="card">
                    <h3>Issues Detected</h3>
                    <div class="number">{len(report.detected_issues)}</div>
                </div>
            </div>
        </div>
        
        <!-- Scenario Results -->
        <div class="section">
            <h2>Scenario Results</h2>
            <div class="chart-container">
                <img src="data:image/png;base64,{scenario_chart}" alt="Scenario Results Chart">
            </div>
            <div class="chart-container">
                <img src="data:image/png;base64,{trade_chart}" alt="Trade Count Comparison Chart">
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>Scenario</th>
                        <th>Purpose</th>
                        <th>Expected</th>
                        <th>Actual</th>
                        <th>Status</th>
                        <th>Issues</th>
                    </tr>
                </thead>
                <tbody>
"""
        
        # Add scenario results rows
        for result in report.results:
            scenario_name = result.scenario.name.replace('_', ' ').title()
            status_class = "status-pass" if result.passed else "status-fail"
            status_text = "✓ PASS" if result.passed else "✗ FAIL"
            issues_text = ", ".join(result.issues_detected[:3])
            if len(result.issues_detected) > 3:
                issues_text += "..."
            
            html_content += f"""
                    <tr>
                        <td>{scenario_name}</td>
                        <td>{result.scenario.purpose}</td>
                        <td>{result.scenario.expected_trades}</td>
                        <td>{result.actual_trades}</td>
                        <td class="{status_class}">{status_text}</td>
                        <td>{issues_text}</td>
                    </tr>
"""
        
        html_content += """
                </tbody>
            </table>
        </div>
        
        <!-- Detected Issues -->
        <div class="section">
            <h2>Detected Issues</h2>
"""
        
        if report.detected_issues:
            if issue_chart:
                html_content += f"""
            <div class="chart-container">
                <img src="data:image/png;base64,{issue_chart}" alt="Issue Distribution Chart">
            </div>
"""
            
            for category, findings in report.detected_issues.items():
                html_content += f"""
            <div class="issue-category">
                <h4>{category}</h4>
                <ul class="issue-list">
"""
                for finding in findings:
                    html_content += f"                    <li>{finding}</li>\n"
                html_content += "                </ul>\n            </div>\n"
        else:
            html_content += "<p>No issues detected.</p>\n"
        
        html_content += "        </div>\n"
        
        # Crossover-Level Verification
        verification_results = [r for r in report.results if r.crossover_verifications]
        if verification_results:
            html_content += """
        <div class="section">
            <h2>Crossover-Level Verification</h2>
"""
            if crossover_chart:
                html_content += f"""
            <div class="chart-container">
                <img src="data:image/png;base64,{crossover_chart}" alt="Crossover Verification Chart">
            </div>
"""
            
            for result in verification_results:
                scenario_name = result.scenario.name.replace('_', ' ').title()
                html_content += f"""
            <details>
                <summary><strong>{scenario_name}</strong> - Expected: {result.expected_crossovers_count}, Detected: {result.detected_crossovers_count}, Missed: {result.missed_crossovers_count}, False Positives: {result.false_positive_count}</summary>
                <table>
                    <thead>
                        <tr>
                            <th>Bar Index</th>
                            <th>Timestamp</th>
                            <th>Type</th>
                            <th>Expected MA Values</th>
                            <th>Status</th>
                            <th>Timing Error</th>
                            <th>Issue</th>
                        </tr>
                    </thead>
                    <tbody>
"""
                for v in result.crossover_verifications:
                    if v.expected_bar_index >= 0:  # Real crossover
                        status = "✅ Detected" if v.detected else "❌ Missed"
                        timing = f"{v.timing_error_bars:+d} bars" if v.timing_error_bars is not None else "N/A"
                        ma_values = f"Fast: {v.expected_fast_ma:.5f}, Slow: {v.expected_slow_ma:.5f}"
                        issue = v.issue or "None"
                        row_class = "success" if v.detected else "danger"
                    else:  # False positive
                        status = "🔶 False Positive"
                        timing = "N/A"
                        ma_values = "N/A"
                        issue = v.issue or "None"
                        row_class = "warning"
                    
                    html_content += f"""
                        <tr class="{row_class}">
                            <td>{v.expected_bar_index if v.expected_bar_index >= 0 else v.actual_bar_index}</td>
                            <td>{v.expected_timestamp if v.expected_bar_index >= 0 else v.actual_timestamp}</td>
                            <td>{v.expected_type if v.expected_bar_index >= 0 else 'N/A'}</td>
                            <td>{ma_values}</td>
                            <td>{status}</td>
                            <td>{timing}</td>
                            <td>{issue}</td>
                        </tr>
"""
                html_content += """
                    </tbody>
                </table>
            </details>
"""
            html_content += "        </div>\n"
        
        # Timing Analysis
        if timing_chart:
            html_content += f"""
        <div class="section">
            <h2>Timing Analysis</h2>
            <div class="chart-container">
                <img src="data:image/png;base64,{timing_chart}" alt="Timing Lag Chart">
            </div>
        </div>
"""
        
        # Improvement Suggestions
        if report.suggestions:
            html_content += """
        <div class="section">
            <h2>Improvement Suggestions</h2>
"""
            for i, suggestion in enumerate(report.suggestions, 1):
                priority = suggestion.get('priority', 'medium')
                html_content += f"""
            <div class="suggestion {priority}">
                <h4>{i}. <span class="priority-badge priority-{priority}">{priority.upper()}</span> {suggestion['suggestion']}</h4>
                <p><strong>Rationale:</strong> {suggestion['rationale']}</p>
            </div>
"""
            html_content += "        </div>\n"
        
        # Performance Summary
        if report.performance_summary:
            html_content += """
        <div class="section">
            <h2>Performance Summary</h2>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
"""
            for metric, value in report.performance_summary.items():
                if isinstance(value, dict):
                    continue  # Skip complex objects
                html_content += f"""
                <tr>
                    <td>{metric.replace('_', ' ').title()}</td>
                    <td>{value}</td>
                </tr>
"""
            html_content += "            </table>\n        </div>\n"
        
        # Footer
        html_content += f"""
        <div class="footer">
            <p>Report generated by MA Crossover Diagnostics System</p>
            <p>This is a diagnostic report for algorithm testing purposes</p>
        </div>
    </div>
</body>
</html>
"""
        
        # Write HTML file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"HTML report generated: {output_path}")
        
    except Exception as e:
        print(f"Error generating HTML report: {e}")


def format_suggestion_priority(priority: str) -> str:
    """
    Return HTML badge for priority level.
    
    Args:
        priority: Priority level (high, medium, low)
        
    Returns:
        HTML badge string
    """
    priority_colors = {
        "high": "danger",
        "medium": "warning", 
        "low": "secondary"
    }
    
    color = priority_colors.get(priority.lower(), "secondary")
    return f'<span class="badge badge-{color}">{priority.upper()}</span>'


def format_status_indicator(passed: bool) -> str:
    """
    Return HTML formatted status indicator.
    
    Args:
        passed: Whether scenario passed
        
    Returns:
        HTML status indicator
    """
    if passed:
        return '<span class="text-success">✓ PASS</span>'
    else:
        return '<span class="text-danger">✗ FAIL</span>'


def generate_markdown_report(report: MADiagnosticReport, output_path: Path) -> None:
    """
    Generate comprehensive Markdown report.
    
    Args:
        report: Diagnostic report to generate Markdown for
        output_path: Path to write Markdown file
    """
    try:
        # Markdown content
        markdown_content = f"""# MA Crossover Diagnostics Report

**Generated:** {report.timestamp}

## Executive Summary

| Metric | Value |
|--------|-------|
| Scenarios Tested | {report.scenarios_tested} |
| Scenarios Passed | {report.scenarios_passed} |
| Scenarios Failed | {report.scenarios_failed} |
| Pass Rate | {(report.scenarios_passed / report.scenarios_tested * 100):.1f}% |
| Issues Detected | {len(report.detected_issues)} categories |

## Scenario Results

| Scenario | Purpose | Expected | Actual | Status | Issues |
|----------|---------|----------|--------|--------|--------|
"""
        
        # Add scenario results rows
        for result in report.results:
            scenario_name = result.scenario.name.replace('_', ' ').title()
            status_text = "✅ PASS" if result.passed else "❌ FAIL"
            issues_text = ", ".join(result.issues_detected[:2])
            if len(result.issues_detected) > 2:
                issues_text += "..."
            
            markdown_content += f"| {scenario_name} | {result.scenario.purpose} | {result.scenario.expected_trades} | {result.actual_trades} | {status_text} | {issues_text} |\n"
        
        markdown_content += "\n"
        
        # Crossover-Level Verification
        verification_results = [r for r in report.results if r.crossover_verifications]
        if verification_results:
            markdown_content += "## Crossover-Level Verification\n\n"
            
            for result in verification_results:
                scenario_name = result.scenario.name.replace('_', ' ').title()
                markdown_content += f"### {scenario_name}\n\n"
                markdown_content += f"**Summary:** Expected: {result.expected_crossovers_count}, Detected: {result.detected_crossovers_count}, Missed: {result.missed_crossovers_count}, False Positives: {result.false_positive_count}\n\n"
                
                # Individual crossovers table
                markdown_content += "| Bar | Timestamp | Type | Status | Timing | Issue | MA Buffer |\n"
                markdown_content += "|-----|-----------|------|--------|--------|-------|----------|\n"
                
                for v in result.crossover_verifications[:10]:  # Limit to first 10
                    if v.expected_bar_index >= 0:  # Real crossover
                        status = "✅ Detected" if v.detected else "❌ Missed"
                        timing = f"{v.timing_error_bars:+d} bars" if v.timing_error_bars is not None else "N/A"
                        issue = v.issue or "None"
                        ma_buffer = f"Length: {v.ma_buffer_length}" if v.ma_buffer_length else "N/A"
                    else:  # False positive
                        status = "🔶 False Positive"
                        timing = "N/A"
                        issue = v.issue or "None"
                        ma_buffer = "N/A"
                    
                    bar_index = v.expected_bar_index if v.expected_bar_index >= 0 else v.actual_bar_index
                    timestamp = v.expected_timestamp if v.expected_bar_index >= 0 else v.actual_timestamp
                    crossover_type = v.expected_type if v.expected_bar_index >= 0 else "N/A"
                    
                    markdown_content += f"| {bar_index} | {timestamp[:19] if timestamp else 'N/A'} | {crossover_type} | {status} | {timing} | {issue} | {ma_buffer} |\n"
                
                if len(result.crossover_verifications) > 10:
                    markdown_content += f"| ... | ... | ... | ... | ... | ... | ... |\n"
                    markdown_content += f"*... and {len(result.crossover_verifications) - 10} more crossovers*\n"
                
                markdown_content += "\n"
        
        # Detected Issues
        if report.detected_issues:
            markdown_content += "## Detected Issues\n\n"
            for category, findings in report.detected_issues.items():
                markdown_content += f"### {category}\n\n"
                for finding in findings:
                    markdown_content += f"- {finding}\n"
                markdown_content += "\n"
        
        # Improvement Suggestions
        if report.suggestions:
            markdown_content += "## Improvement Suggestions\n\n"
            for i, suggestion in enumerate(report.suggestions, 1):
                priority = suggestion.get('priority', 'medium').upper()
                markdown_content += f"### {i}. [{priority}] {suggestion['suggestion']}\n\n"
                markdown_content += f"**Rationale:** {suggestion['rationale']}\n\n"
        
        # Performance Summary
        if report.performance_summary:
            markdown_content += "## Performance Summary\n\n"
            markdown_content += "| Metric | Value |\n"
            markdown_content += "|--------|-------|\n"
            for metric, value in report.performance_summary.items():
                if isinstance(value, dict):
                    continue  # Skip complex objects
                markdown_content += f"| {metric.replace('_', ' ').title()} | {value} |\n"
            markdown_content += "\n"
        
        # Footer
        markdown_content += "---\n\n"
        markdown_content += "*Report generated by MA Crossover Diagnostics System*\n"
        markdown_content += "*This is a diagnostic report for algorithm testing purposes*\n"
        
        # Write Markdown file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        
        print(f"Markdown report generated: {output_path}")
        
    except Exception as e:
        print(f"Error generating Markdown report: {e}")


# Chart style configuration
CHART_STYLE_CONFIG = {
    'figure.facecolor': 'white',
    'axes.facecolor': 'white',
    'axes.grid': True,
    'grid.alpha': 0.3,
    'font.size': 10,
    'axes.titlesize': 14,
    'axes.labelsize': 12,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'legend.fontsize': 10
}

# Apply style
plt.style.use('default')
for key, value in CHART_STYLE_CONFIG.items():
    plt.rcParams[key] = value
