"""
Backtest Comparison Tool

This module provides comprehensive comparison of performance metrics across multiple backtest runs.
It extracts metrics from backtest result directories, calculates additional metrics like Profit Factor,
Sharpe Ratio, and Max Drawdown, performs statistical significance testing, and generates multi-format reports.

Usage Examples:
    Basic comparison:
        python analysis/compare_backtests.py --baseline logs/backtest_results/EUR-USD_20251013_200009 --compare logs/backtest_results/EUR-USD_20251013_201006
    
    Multiple comparisons:
        python analysis/compare_backtests.py --baseline run1 --compare run2 run3 run4
    
    With JSON export:
        python analysis/compare_backtests.py --baseline run1 --compare run2 --json --output reports/comparison.html

Output Formats:
    - Console report (always): Formatted text output to stdout
    - HTML report (always): Comprehensive report with embedded charts saved to file
    - JSON export (optional): Structured data export with --json flag

Exit Codes:
    0: Success
    1: Error (file not found, parsing error, etc.)
    2: Invalid arguments

Metrics Compared:
    - Win Rate: Percentage of winning trades
    - Profit Factor: Gross Profit / Gross Loss
    - Sharpe Ratio: Risk-adjusted return measure
    - Max Drawdown: Maximum peak-to-trough decline
    - Average Winner/Loser: Mean PnL of winning/losing trades
    - Total PnL: Total profit/loss
    - Expectancy: Expected value per trade
    - Long Ratio: Percentage of long positions
    - Total Trades: Number of completed trades
    - Rejected Signals: Number of rejected trading signals

Statistical Testing:
    - Independent samples t-test on PnL distributions
    - Significance testing (p < 0.05) for performance differences
    - Interpretation of statistical results

Visualizations:
    - Side-by-side metrics comparison table
    - Delta/improvement bar charts
    - Win rate comparison charts
    - PnL distribution comparisons (box plots)
    - Equity curve overlays (when data available)
"""

import argparse
import json
import logging
import sys
import re
import base64
import io
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class BacktestMetrics:
    """Represents all calculated metrics for a single backtest run."""
    run_id: str
    run_path: Path
    total_pnl: float
    total_pnl_pct: float
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    avg_winner: float
    avg_loser: float
    max_winner: float
    max_loser: float
    expectancy: float
    long_ratio: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    rejected_signals_count: int


@dataclass
class MetricComparison:
    """Represents comparison between baseline and another backtest."""
    metric_name: str
    baseline_value: float
    compare_value: float
    delta: float
    delta_pct: float
    is_improvement: bool


@dataclass
class StatisticalTest:
    """Results of statistical significance testing."""
    test_name: str
    statistic: float
    p_value: float
    is_significant: bool
    interpretation: str


@dataclass
class ComparisonReport:
    """Complete comparison report."""
    baseline_metrics: BacktestMetrics
    compare_metrics_list: List[BacktestMetrics]
    comparisons: Dict[str, List[MetricComparison]]
    statistical_tests: Dict[str, StatisticalTest]
    summary: str


def load_performance_stats(results_dir: Path) -> Dict[str, Any]:
    """Load performance statistics from JSON file."""
    stats_file = results_dir / "performance_stats.json"
    
    if not stats_file.exists():
        logger.warning(f"Performance stats file not found: {stats_file}")
        return {}
    
    try:
        with open(stats_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading performance stats from {stats_file}: {e}")
        return {}


def load_positions(results_dir: Path) -> pd.DataFrame:
    """Load positions data from CSV file."""
    positions_file = results_dir / "positions.csv"
    
    if not positions_file.exists():
        logger.warning(f"Positions file not found: {positions_file}")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(positions_file)
        
        # Parse timestamp columns if they exist
        for col in ['ts_opened', 'ts_closed']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
        
        # Filter out snapshot rows
        if 'is_snapshot' in df.columns:
            df = df[df['is_snapshot'] == False]
        
        return df
    except Exception as e:
        logger.error(f"Error loading positions from {positions_file}: {e}")
        return pd.DataFrame()


def load_equity_curve(results_dir: Path) -> pd.DataFrame:
    """Load equity curve data from CSV file."""
    equity_file = results_dir / "equity_curve_data.csv"
    
    if not equity_file.exists():
        logger.warning(f"Equity curve file not found: {equity_file}")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(equity_file)
        
        # Parse timestamp column if it exists
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        
        return df
    except Exception as e:
        logger.error(f"Error loading equity curve from {equity_file}: {e}")
        return pd.DataFrame()


def parse_currency_value(value_str: str) -> float:
    """Parse currency strings like ' -256.70 USD' to float."""
    if not value_str or pd.isna(value_str):
        return 0.0
    
    if isinstance(value_str, (int, float)):
        return float(value_str)
    
    # Use regex to extract numeric value
    pattern = r'([+-]?\d+\.?\d*)\s*[A-Z]{3}'
    match = re.search(pattern, str(value_str))
    
    if match:
        return float(match.group(1))
    else:
        # Try to parse as plain number
        try:
            return float(value_str)
        except ValueError:
            logger.warning(f"Could not parse currency value: {value_str}")
            return 0.0


def parse_commissions(commissions_str: str) -> float:
    """Parse commission strings like "['4.70 USD']" to float."""
    if not commissions_str or pd.isna(commissions_str):
        return 0.0
    
    if isinstance(commissions_str, (int, float)):
        return float(commissions_str)
    
    try:
        # Try to parse as list-like string
        import ast
        if isinstance(commissions_str, str) and commissions_str.startswith('['):
            commission_list = ast.literal_eval(commissions_str)
            if isinstance(commission_list, list):
                total = 0.0
                for item in commission_list:
                    total += parse_currency_value(str(item))
                return total
    except (ValueError, SyntaxError):
        pass
    
    # Fallback to parsing as single currency value
    return parse_currency_value(commissions_str)


def calculate_profit_factor(positions_df: pd.DataFrame) -> float:
    """Calculate profit factor from positions data."""
    if positions_df.empty or 'realized_pnl' not in positions_df.columns:
        return 0.0
    
    try:
        # Parse realized_pnl values
        pnl_values = positions_df['realized_pnl'].apply(parse_currency_value)
        
        winning_trades = pnl_values[pnl_values > 0]
        losing_trades = pnl_values[pnl_values < 0]
        
        gross_profit = winning_trades.sum() if len(winning_trades) > 0 else 0.0
        gross_loss = abs(losing_trades.sum()) if len(losing_trades) > 0 else 0.0
        
        if gross_loss > 0:
            return gross_profit / gross_loss
        elif gross_profit > 0:
            return 999.99  # No losing trades
        else:
            return 0.0
    except Exception as e:
        logger.error(f"Error calculating profit factor: {e}")
        return 0.0


def calculate_sharpe_ratio(positions_df: pd.DataFrame, risk_free_rate: float = 0.0) -> float:
    """Calculate Sharpe ratio from positions data."""
    if positions_df.empty or 'realized_return' not in positions_df.columns:
        return 0.0
    
    try:
        returns = positions_df['realized_return'].dropna()
        
        if len(returns) < 2:
            return 0.0
        
        mean_return = returns.mean()
        std_return = returns.std()
        
        if std_return > 0:
            return (mean_return - risk_free_rate) / std_return
        else:
            return 0.0
    except Exception as e:
        logger.error(f"Error calculating Sharpe ratio: {e}")
        return 0.0


def calculate_max_drawdown(equity_curve_df: pd.DataFrame) -> Tuple[float, float]:
    """Calculate maximum drawdown from equity curve data."""
    if equity_curve_df.empty or 'equity' not in equity_curve_df.columns:
        return 0.0, 0.0
    
    try:
        equity = equity_curve_df['equity'].dropna()
        
        if len(equity) < 2:
            return 0.0, 0.0
        
        # Calculate running maximum (peak)
        peak = equity.expanding().max()
        
        # Calculate drawdown
        drawdown = equity - peak
        
        # Calculate drawdown percentage
        drawdown_pct = (equity - peak) / peak * 100
        
        max_drawdown_abs = abs(drawdown.min())
        max_drawdown_pct = abs(drawdown_pct.min())
        
        return max_drawdown_abs, max_drawdown_pct
    except Exception as e:
        logger.error(f"Error calculating max drawdown: {e}")
        return 0.0, 0.0


def calculate_max_drawdown_from_positions(positions_df: pd.DataFrame, starting_capital: float = 100000.0) -> Tuple[float, float]:
    """Calculate max drawdown from positions data when equity curve is unavailable."""
    if positions_df.empty or 'realized_pnl' not in positions_df.columns:
        return 0.0, 0.0
    
    try:
        # Parse realized_pnl values
        pnl_values = positions_df['realized_pnl'].apply(parse_currency_value)
        
        # Calculate cumulative PnL
        cumulative_pnl = pnl_values.cumsum()
        
        # Calculate equity
        equity = starting_capital + cumulative_pnl
        
        # Calculate running maximum (peak)
        peak = equity.expanding().max()
        
        # Calculate drawdown
        drawdown = equity - peak
        
        # Calculate drawdown percentage
        drawdown_pct = (equity - peak) / peak * 100
        
        max_drawdown_abs = abs(drawdown.min())
        max_drawdown_pct = abs(drawdown_pct.min())
        
        return max_drawdown_abs, max_drawdown_pct
    except Exception as e:
        logger.error(f"Error calculating max drawdown from positions: {e}")
        return 0.0, 0.0


def extract_metrics(results_dir: Path, risk_free_rate: float = 0.0, starting_capital: float = 100000.0) -> BacktestMetrics:
    """Extract all metrics for a backtest run."""
    run_id = results_dir.name
    run_path = results_dir
    
    # Load performance stats
    stats_data = load_performance_stats(results_dir)
    pnls = stats_data.get('pnls', {})
    general = stats_data.get('general', {})
    rejected_signals_count = stats_data.get('rejected_signals_count', 0)
    
    # Load positions data
    positions_df = load_positions(results_dir)
    
    # Load equity curve data
    equity_curve_df = load_equity_curve(results_dir)
    
    # Extract basic metrics from performance stats
    total_pnl = pnls.get('PnL', 0.0)
    total_pnl_pct = pnls.get('PnL%', 0.0)
    win_rate = pnls.get('Win Rate', 0.0)
    avg_winner = pnls.get('Avg Winner', 0.0)
    avg_loser = pnls.get('Avg Loser', 0.0)
    max_winner = pnls.get('Max Winner', 0.0)
    max_loser = pnls.get('Min Loser', 0.0)  # Note: Min Loser is typically negative
    expectancy = pnls.get('Expectancy', 0.0)
    long_ratio = general.get('Long Ratio', 0.0)
    
    # Calculate additional metrics
    profit_factor = calculate_profit_factor(positions_df)
    sharpe_ratio = calculate_sharpe_ratio(positions_df, risk_free_rate=risk_free_rate)
    
    # Calculate max drawdown
    if equity_curve_df.empty or 'equity' not in equity_curve_df.columns:
        max_drawdown, max_drawdown_pct = calculate_max_drawdown_from_positions(positions_df, starting_capital=starting_capital)
    else:
        max_drawdown, max_drawdown_pct = calculate_max_drawdown(equity_curve_df)
    
    # Count trades
    total_trades = len(positions_df) if not positions_df.empty else 0
    winning_trades = 0
    losing_trades = 0
    
    if not positions_df.empty and 'realized_pnl' in positions_df.columns:
        pnl_values = positions_df['realized_pnl'].apply(parse_currency_value)
        winning_trades = len(pnl_values[pnl_values > 0])
        losing_trades = len(pnl_values[pnl_values < 0])
    
    return BacktestMetrics(
        run_id=run_id,
        run_path=run_path,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        win_rate=win_rate,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        avg_winner=avg_winner,
        avg_loser=avg_loser,
        max_winner=max_winner,
        max_loser=max_loser,
        expectancy=expectancy,
        long_ratio=long_ratio,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        rejected_signals_count=rejected_signals_count
    )


def compare_metrics(baseline: BacktestMetrics, compare: BacktestMetrics) -> List[MetricComparison]:
    """Compare metrics between baseline and another backtest."""
    comparisons = []
    
    # Define metrics to compare
    metrics = [
        ('total_pnl', 'Total PnL', True),  # Higher is better
        ('total_pnl_pct', 'Total PnL %', True),
        ('win_rate', 'Win Rate', True),
        ('profit_factor', 'Profit Factor', True),
        ('sharpe_ratio', 'Sharpe Ratio', True),
        ('max_drawdown', 'Max Drawdown', False),  # Lower is better
        ('max_drawdown_pct', 'Max Drawdown %', False),
        ('avg_winner', 'Avg Winner', True),
        ('avg_loser', 'Avg Loser', False),  # Less negative is better
        ('max_winner', 'Max Winner', True),
        ('max_loser', 'Max Loser', False),  # Less negative is better
        ('expectancy', 'Expectancy', True),
        ('long_ratio', 'Long Ratio', True),
        ('total_trades', 'Total Trades', True),
        ('winning_trades', 'Winning Trades', True),
        ('losing_trades', 'Losing Trades', False),  # Lower is better
        ('rejected_signals_count', 'Rejected Signals', False)
    ]
    
    for attr_name, display_name, higher_is_better in metrics:
        baseline_value = getattr(baseline, attr_name)
        compare_value = getattr(compare, attr_name)
        
        delta = compare_value - baseline_value
        delta_pct = (delta / baseline_value * 100) if baseline_value != 0 else 0.0
        
        # Determine if this is an improvement
        if higher_is_better:
            is_improvement = delta > 0
        else:
            is_improvement = delta < 0
        
        comparisons.append(MetricComparison(
            metric_name=display_name,
            baseline_value=baseline_value,
            compare_value=compare_value,
            delta=delta,
            delta_pct=delta_pct,
            is_improvement=is_improvement
        ))
    
    return comparisons


def perform_statistical_test(baseline_positions: pd.DataFrame, compare_positions: pd.DataFrame) -> StatisticalTest:
    """Perform statistical significance test on PnL distributions."""
    try:
        # Extract PnL values from both datasets
        baseline_pnls = baseline_positions['realized_pnl'].apply(parse_currency_value).dropna()
        compare_pnls = compare_positions['realized_pnl'].apply(parse_currency_value).dropna()
        
        if len(baseline_pnls) < 2 or len(compare_pnls) < 2:
            return StatisticalTest(
                test_name="Independent Samples T-Test",
                statistic=0.0,
                p_value=1.0,
                is_significant=False,
                interpretation="Insufficient data for statistical testing (need at least 2 trades in each group)."
            )
        
        # Perform independent samples t-test (Welch's t-test for unequal variances)
        statistic, p_value = stats.ttest_ind(baseline_pnls, compare_pnls, equal_var=False)
        
        is_significant = p_value < 0.05
        
        if is_significant:
            interpretation = "The PnL difference is statistically significant (p < 0.05). The performance change is unlikely due to random chance."
        else:
            interpretation = "The PnL difference is not statistically significant (p >= 0.05). The performance change may be due to random variation."
        
        return StatisticalTest(
            test_name="Independent Samples T-Test",
            statistic=float(statistic),
            p_value=float(p_value),
            is_significant=is_significant,
            interpretation=interpretation
        )
    except Exception as e:
        logger.error(f"Error performing statistical test: {e}")
        return StatisticalTest(
            test_name="Independent Samples T-Test",
            statistic=0.0,
            p_value=1.0,
            is_significant=False,
            interpretation=f"Error in statistical testing: {e}"
        )


def generate_summary(baseline: BacktestMetrics, comparisons: Dict[str, List[MetricComparison]], statistical_tests: Dict[str, StatisticalTest]) -> str:
    """Generate overall summary of comparisons."""
    summary_lines = []
    summary_lines.append("=== COMPARISON SUMMARY ===")
    summary_lines.append("")
    
    # Count improvements vs regressions
    total_improvements = 0
    total_regressions = 0
    significant_changes = 0
    
    for run_id, metric_comparisons in comparisons.items():
        improvements = sum(1 for comp in metric_comparisons if comp.is_improvement)
        regressions = len(metric_comparisons) - improvements
        
        total_improvements += improvements
        total_regressions += regressions
        
        # Check statistical significance
        if run_id in statistical_tests and statistical_tests[run_id].is_significant:
            significant_changes += 1
        
        summary_lines.append(f"Run {run_id}:")
        summary_lines.append(f"  Improvements: {improvements}")
        summary_lines.append(f"  Regressions: {regressions}")
        summary_lines.append(f"  Statistically Significant: {'Yes' if run_id in statistical_tests and statistical_tests[run_id].is_significant else 'No'}")
        
        # Show top 3 improving and regressing metrics
        improving_metrics = sorted([comp for comp in metric_comparisons if comp.is_improvement], 
                                 key=lambda x: abs(x.delta_pct), reverse=True)[:3]
        regressing_metrics = sorted([comp for comp in metric_comparisons if not comp.is_improvement], 
                                  key=lambda x: abs(x.delta_pct), reverse=True)[:3]
        
        if improving_metrics:
            summary_lines.append("  Top Improving Metrics:")
            for comp in improving_metrics:
                summary_lines.append(f"    {comp.metric_name}: {comp.delta_pct:+.1f}%")
        
        if regressing_metrics:
            summary_lines.append("  Top Regressing Metrics:")
            for comp in regressing_metrics:
                summary_lines.append(f"    {comp.metric_name}: {comp.delta_pct:+.1f}%")
        
        summary_lines.append("")
    
    # Overall assessment
    summary_lines.append("OVERALL ASSESSMENT:")
    summary_lines.append(f"Total Improvements: {total_improvements}")
    summary_lines.append(f"Total Regressions: {total_regressions}")
    summary_lines.append(f"Statistically Significant Changes: {significant_changes}")
    summary_lines.append("")
    
    if total_improvements > total_regressions:
        summary_lines.append("✓ Overall performance shows net improvement")
    elif total_regressions > total_improvements:
        summary_lines.append("⚠ Overall performance shows net regression")
    else:
        summary_lines.append("≈ Overall performance is mixed")
    
    if significant_changes > 0:
        summary_lines.append(f"✓ {significant_changes} comparison(s) show statistically significant differences")
    
    return "\n".join(summary_lines)


def create_metrics_comparison_table_chart(baseline: BacktestMetrics, compare_list: List[BacktestMetrics]) -> str:
    """Create a table-style visualization showing all metrics side-by-side."""
    try:
        # Set up the plot
        plt.style.use('seaborn-v0_8-whitegrid')
        fig, ax = plt.subplots(figsize=(16, 10))
        
        # Prepare data for table
        metrics_data = []
        run_names = ['Baseline'] + [run.run_id for run in compare_list]
        
        # Define key metrics to display
        key_metrics = [
            ('win_rate', 'Win Rate', '{:.2%}'),
            ('profit_factor', 'Profit Factor', '{:.2f}'),
            ('sharpe_ratio', 'Sharpe Ratio', '{:.2f}'),
            ('max_drawdown_pct', 'Max DD %', '{:.2f}%'),
            ('total_pnl', 'Total PnL', '{:.2f}'),
            ('total_trades', 'Total Trades', '{:.0f}'),
            ('expectancy', 'Expectancy', '{:.2f}')
        ]
        
        # Create table data
        table_data = []
        for metric_attr, display_name, format_str in key_metrics:
            row = [display_name]
            for run in [baseline] + compare_list:
                value = getattr(run, metric_attr)
                row.append(format_str.format(value))
            table_data.append(row)
        
        # Create table
        col_labels = ['Metric'] + run_names
        table = ax.table(cellText=table_data, colLabels=col_labels, cellLoc='center', loc='center')
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.2, 2)
        
        # Style the table
        for i in range(len(col_labels)):
            for j in range(len(key_metrics) + 1):
                cell = table[(i, j)]
                if i == 0:  # Header row
                    cell.set_facecolor('#4CAF50')
                    cell.set_text_props(weight='bold', color='white')
                else:
                    cell.set_facecolor('#f0f0f0' if i % 2 == 0 else 'white')
        
        ax.set_title('Metrics Comparison Table', fontsize=16, fontweight='bold', pad=20)
        ax.axis('off')
        
        # Save to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
    except Exception as e:
        logger.error(f"Error creating metrics comparison table chart: {e}")
        return ""


def create_delta_bar_chart(comparisons: Dict[str, List[MetricComparison]]) -> str:
    """Create grouped bar chart showing percentage change for each metric."""
    try:
        plt.style.use('seaborn-v0_8-whitegrid')
        fig, ax = plt.subplots(figsize=(14, 8))
        
        # Prepare data
        metrics = []
        run_names = list(comparisons.keys())
        
        # Get all unique metrics
        all_metrics = set()
        for metric_comparisons in comparisons.values():
            for comp in metric_comparisons:
                all_metrics.add(comp.metric_name)
        
        # Focus on key metrics for readability
        key_metrics = ['Win Rate', 'Profit Factor', 'Sharpe Ratio', 'Max Drawdown %', 'Total PnL', 'Expectancy']
        filtered_metrics = [m for m in key_metrics if m in all_metrics]
        
        # Create data arrays
        x = np.arange(len(filtered_metrics))
        width = 0.8 / len(run_names)
        
        colors = plt.cm.Set3(np.linspace(0, 1, len(run_names)))
        
        for i, run_name in enumerate(run_names):
            values = []
            for metric in filtered_metrics:
                # Find the metric comparison
                metric_comp = next((comp for comp in comparisons[run_name] if comp.metric_name == metric), None)
                if metric_comp:
                    values.append(metric_comp.delta_pct)
                else:
                    values.append(0.0)
            
            bars = ax.bar(x + i * width, values, width, label=run_name, color=colors[i])
            
            # Color bars based on improvement/regression
            for j, (bar, value) in enumerate(zip(bars, values)):
                if value > 0:
                    bar.set_color('green' if any(comp.is_improvement for comp in comparisons[run_name] 
                                               if comp.metric_name == filtered_metrics[j]) else 'red')
                elif value < 0:
                    bar.set_color('red' if any(comp.is_improvement for comp in comparisons[run_name] 
                                             if comp.metric_name == filtered_metrics[j]) else 'green')
                else:
                    bar.set_color('gray')
        
        ax.set_xlabel('Metrics', fontsize=12)
        ax.set_ylabel('Percentage Change (%)', fontsize=12)
        ax.set_title('Metric Changes vs Baseline', fontsize=14, fontweight='bold')
        ax.set_xticks(x + width * (len(run_names) - 1) / 2)
        ax.set_xticklabels(filtered_metrics, rotation=45, ha='right')
        ax.legend()
        ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Save to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
    except Exception as e:
        logger.error(f"Error creating delta bar chart: {e}")
        return ""


def create_win_rate_comparison_chart(baseline: BacktestMetrics, compare_list: List[BacktestMetrics]) -> str:
    """Create bar chart comparing win rates."""
    try:
        plt.style.use('seaborn-v0_8-whitegrid')
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Prepare data
        run_names = ['Baseline'] + [run.run_id for run in compare_list]
        win_rates = [baseline.win_rate] + [run.win_rate for run in compare_list]
        
        # Create bars
        colors = ['#2E8B57'] + ['#4682B4'] * len(compare_list)  # Green for baseline, blue for others
        bars = ax.bar(run_names, win_rates, color=colors)
        
        # Add value labels on bars
        for bar, rate in zip(bars, win_rates):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                   f'{rate:.1%}', ha='center', va='bottom', fontweight='bold')
        
        ax.set_ylabel('Win Rate', fontsize=12)
        ax.set_title('Win Rate Comparison', fontsize=14, fontweight='bold')
        ax.set_ylim(0, max(win_rates) * 1.2)
        ax.grid(True, alpha=0.3)
        
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        
        # Save to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
    except Exception as e:
        logger.error(f"Error creating win rate comparison chart: {e}")
        return ""


def create_pnl_distribution_chart(baseline_positions: pd.DataFrame, compare_positions_list: List[Tuple[str, pd.DataFrame]]) -> str:
    """Create box plot comparing PnL distributions."""
    try:
        plt.style.use('seaborn-v0_8-whitegrid')
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Prepare data
        all_data = []
        all_labels = []
        
        # Add baseline data
        if not baseline_positions.empty and 'realized_pnl' in baseline_positions.columns:
            baseline_pnls = baseline_positions['realized_pnl'].apply(parse_currency_value).dropna()
            if len(baseline_pnls) > 0:
                all_data.append(baseline_pnls)
                all_labels.append('Baseline')
        
        # Add compare data
        for run_name, positions_df in compare_positions_list:
            if not positions_df.empty and 'realized_pnl' in positions_df.columns:
                compare_pnls = positions_df['realized_pnl'].apply(parse_currency_value).dropna()
                if len(compare_pnls) > 0:
                    all_data.append(compare_pnls)
                    all_labels.append(run_name)
        
        if not all_data:
            return ""
        
        # Create box plot
        box_plot = ax.boxplot(all_data, labels=all_labels, patch_artist=True)
        
        # Color the boxes
        colors = ['#2E8B57'] + ['#4682B4'] * (len(all_data) - 1)
        for patch, color in zip(box_plot['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        
        ax.set_ylabel('Realized PnL', fontsize=12)
        ax.set_title('PnL Distribution Comparison', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        
        # Save to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
    except Exception as e:
        logger.error(f"Error creating PnL distribution chart: {e}")
        return ""


def create_equity_curve_overlay_chart(baseline_equity: pd.DataFrame, compare_equity_list: List[Tuple[str, pd.DataFrame]]) -> str:
    """Create line chart overlaying equity curves."""
    try:
        if baseline_equity.empty or 'equity' not in baseline_equity.columns:
            return ""
        
        plt.style.use('seaborn-v0_8-whitegrid')
        fig, ax = plt.subplots(figsize=(14, 8))
        
        # Plot baseline equity curve
        if 'timestamp' in baseline_equity.columns:
            ax.plot(baseline_equity['timestamp'], baseline_equity['equity'], 
                   label='Baseline', linewidth=2, color='#2E8B57')
        else:
            ax.plot(baseline_equity['equity'], label='Baseline', linewidth=2, color='#2E8B57')
        
        # Plot compare equity curves
        colors = ['#4682B4', '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4']
        for i, (run_name, equity_df) in enumerate(compare_equity_list):
            if not equity_df.empty and 'equity' in equity_df.columns:
                color = colors[i % len(colors)]
                if 'timestamp' in equity_df.columns:
                    ax.plot(equity_df['timestamp'], equity_df['equity'], 
                           label=run_name, linewidth=2, color=color, linestyle='--')
                else:
                    ax.plot(equity_df['equity'], label=run_name, linewidth=2, color=color, linestyle='--')
        
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel('Equity', fontsize=12)
        ax.set_title('Equity Curve Overlay', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Save to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
    except Exception as e:
        logger.error(f"Error creating equity curve overlay chart: {e}")
        return ""


def generate_console_report(report: ComparisonReport) -> None:
    """Generate formatted console report."""
    print("=" * 80)
    print("BACKTEST COMPARISON REPORT")
    print("=" * 80)
    print()
    
    # Baseline section
    print("BASELINE RUN:")
    print(f"Run ID: {report.baseline_metrics.run_id}")
    print(f"Path: {report.baseline_metrics.run_path}")
    print()
    
    # Baseline metrics table
    print("Baseline Metrics:")
    print("-" * 50)
    baseline = report.baseline_metrics
    print(f"{'Metric':<20} {'Value':<15}")
    print("-" * 50)
    print(f"{'Total PnL':<20} {baseline.total_pnl:<15.2f}")
    print(f"{'Total PnL %':<20} {baseline.total_pnl_pct:<15.2f}")
    print(f"{'Win Rate':<20} {baseline.win_rate:<15.2%}")
    print(f"{'Profit Factor':<20} {baseline.profit_factor:<15.2f}")
    print(f"{'Sharpe Ratio':<20} {baseline.sharpe_ratio:<15.2f}")
    print(f"{'Max Drawdown':<20} {baseline.max_drawdown:<15.2f}")
    print(f"{'Max Drawdown %':<20} {baseline.max_drawdown_pct:<15.2f}")
    print(f"{'Avg Winner':<20} {baseline.avg_winner:<15.2f}")
    print(f"{'Avg Loser':<20} {baseline.avg_loser:<15.2f}")
    print(f"{'Expectancy':<20} {baseline.expectancy:<15.2f}")
    print(f"{'Total Trades':<20} {baseline.total_trades:<15}")
    print(f"{'Rejected Signals':<20} {baseline.rejected_signals_count:<15}")
    print()
    
    # Comparison sections
    for run_id, metric_comparisons in report.comparisons.items():
        print(f"COMPARISON: {run_id}")
        print("-" * 50)
        
        # Find the compare metrics
        compare_metrics = next((run for run in report.compare_metrics_list if run.run_id == run_id), None)
        if compare_metrics:
            print(f"Run ID: {compare_metrics.run_id}")
            print(f"Path: {compare_metrics.run_path}")
            print()
        
        # Comparison table
        print("Metric Comparison:")
        print(f"{'Metric':<20} {'Baseline':<12} {'Compare':<12} {'Delta':<10} {'Delta %':<10} {'Status':<10}")
        print("-" * 80)
        
        for comp in metric_comparisons:
            status = "✓ IMPROVE" if comp.is_improvement else "✗ REGRESS"
            print(f"{comp.metric_name:<20} {comp.baseline_value:<12.2f} {comp.compare_value:<12.2f} "
                  f"{comp.delta:<10.2f} {comp.delta_pct:<10.1f}% {status:<10}")
        
        print()
        
        # Statistical test results
        if run_id in report.statistical_tests:
            test = report.statistical_tests[run_id]
            print("Statistical Test Results:")
            print(f"Test: {test.test_name}")
            print(f"Statistic: {test.statistic:.4f}")
            print(f"P-value: {test.p_value:.4f}")
            print(f"Significant: {'Yes' if test.is_significant else 'No'}")
            print(f"Interpretation: {test.interpretation}")
            print()
    
    # Summary
    print("SUMMARY:")
    print("-" * 50)
    print(report.summary)


def generate_json_report(report: ComparisonReport, output_path: Path) -> None:
    """Generate JSON report."""
    try:
        # Convert report to dictionary
        report_dict = {
            "baseline": {
                "run_id": report.baseline_metrics.run_id,
                "run_path": str(report.baseline_metrics.run_path),
                "total_pnl": report.baseline_metrics.total_pnl,
                "total_pnl_pct": report.baseline_metrics.total_pnl_pct,
                "win_rate": report.baseline_metrics.win_rate,
                "profit_factor": report.baseline_metrics.profit_factor,
                "sharpe_ratio": report.baseline_metrics.sharpe_ratio,
                "max_drawdown": report.baseline_metrics.max_drawdown,
                "max_drawdown_pct": report.baseline_metrics.max_drawdown_pct,
                "avg_winner": report.baseline_metrics.avg_winner,
                "avg_loser": report.baseline_metrics.avg_loser,
                "max_winner": report.baseline_metrics.max_winner,
                "max_loser": report.baseline_metrics.max_loser,
                "expectancy": report.baseline_metrics.expectancy,
                "long_ratio": report.baseline_metrics.long_ratio,
                "total_trades": report.baseline_metrics.total_trades,
                "winning_trades": report.baseline_metrics.winning_trades,
                "losing_trades": report.baseline_metrics.losing_trades,
                "rejected_signals_count": report.baseline_metrics.rejected_signals_count
            },
            "comparisons": [],
            "summary": report.summary
        }
        
        # Add comparison data
        for i, compare_metrics in enumerate(report.compare_metrics_list):
            run_id = compare_metrics.run_id
            comparison_data = {
                "run_id": run_id,
                "run_path": str(compare_metrics.run_path),
                "metrics": {
                    "total_pnl": compare_metrics.total_pnl,
                    "total_pnl_pct": compare_metrics.total_pnl_pct,
                    "win_rate": compare_metrics.win_rate,
                    "profit_factor": compare_metrics.profit_factor,
                    "sharpe_ratio": compare_metrics.sharpe_ratio,
                    "max_drawdown": compare_metrics.max_drawdown,
                    "max_drawdown_pct": compare_metrics.max_drawdown_pct,
                    "avg_winner": compare_metrics.avg_winner,
                    "avg_loser": compare_metrics.avg_loser,
                    "max_winner": compare_metrics.max_winner,
                    "max_loser": compare_metrics.max_loser,
                    "expectancy": compare_metrics.expectancy,
                    "long_ratio": compare_metrics.long_ratio,
                    "total_trades": compare_metrics.total_trades,
                    "winning_trades": compare_metrics.winning_trades,
                    "losing_trades": compare_metrics.losing_trades,
                    "rejected_signals_count": compare_metrics.rejected_signals_count
                },
                "metric_comparisons": [
                    {
                        "metric_name": comp.metric_name,
                        "baseline_value": comp.baseline_value,
                        "compare_value": comp.compare_value,
                        "delta": comp.delta,
                        "delta_pct": comp.delta_pct,
                        "is_improvement": comp.is_improvement
                    }
                    for comp in report.comparisons.get(run_id, [])
                ],
                "statistical_test": {
                    "test_name": report.statistical_tests[run_id].test_name,
                    "statistic": report.statistical_tests[run_id].statistic,
                    "p_value": report.statistical_tests[run_id].p_value,
                    "is_significant": report.statistical_tests[run_id].is_significant,
                    "interpretation": report.statistical_tests[run_id].interpretation
                } if run_id in report.statistical_tests else None
            }
            report_dict["comparisons"].append(comparison_data)
        
        # Write JSON file
        with open(output_path, 'w') as f:
            json.dump(report_dict, f, indent=2)
        
        logger.info(f"JSON report saved to: {output_path}")
    except Exception as e:
        logger.error(f"Error generating JSON report: {e}")


def generate_html_report(report: ComparisonReport, output_path: Path, charts: Dict[str, str]) -> None:
    """Generate comprehensive HTML report."""
    try:
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backtest Comparison Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 0 20px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            text-align: center;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            border-left: 4px solid #3498db;
            padding-left: 15px;
            margin-top: 30px;
        }}
        h3 {{
            color: #2c3e50;
            margin-top: 25px;
        }}
        .metric-card {{
            background: #ecf0f1;
            border: 1px solid #bdc3c7;
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
            display: inline-block;
            min-width: 200px;
        }}
        .metric-value {{
            font-size: 1.5em;
            font-weight: bold;
            color: #2c3e50;
        }}
        .metric-label {{
            color: #7f8c8d;
            font-size: 0.9em;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: white;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 12px;
            text-align: left;
        }}
        th {{
            background-color: #3498db;
            color: white;
            font-weight: bold;
        }}
        tr:nth-child(even) {{
            background-color: #f2f2f2;
        }}
        .improvement {{
            color: #27ae60;
            font-weight: bold;
        }}
        .regression {{
            color: #e74c3c;
            font-weight: bold;
        }}
        .significant {{
            background-color: #d5f4e6;
            border-left: 4px solid #27ae60;
        }}
        .not-significant {{
            background-color: #fdf2e9;
            border-left: 4px solid #f39c12;
        }}
        .chart-container {{
            text-align: center;
            margin: 20px 0;
        }}
        .chart-container img {{
            max-width: 100%;
            height: auto;
            border: 1px solid #ddd;
            border-radius: 8px;
        }}
        .summary {{
            background: #e8f4fd;
            border: 1px solid #3498db;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}
        .footer {{
            text-align: center;
            color: #7f8c8d;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ecf0f1;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Backtest Comparison Report</h1>
        <p><strong>Generated:</strong> {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Baseline Run:</strong> {report.baseline_metrics.run_id}</p>
        <p><strong>Baseline Path:</strong> {report.baseline_metrics.run_path}</p>
        
        <h2>Baseline Metrics Overview</h2>
        <div class="metric-card">
            <div class="metric-value">{report.baseline_metrics.total_pnl:.2f}</div>
            <div class="metric-label">Total PnL</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{report.baseline_metrics.win_rate:.1%}</div>
            <div class="metric-label">Win Rate</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{report.baseline_metrics.profit_factor:.2f}</div>
            <div class="metric-label">Profit Factor</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{report.baseline_metrics.sharpe_ratio:.2f}</div>
            <div class="metric-label">Sharpe Ratio</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{report.baseline_metrics.max_drawdown_pct:.2f}%</div>
            <div class="metric-label">Max Drawdown</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{report.baseline_metrics.total_trades}</div>
            <div class="metric-label">Total Trades</div>
        </div>
"""
        
        # Add comparison sections
        for run_id, metric_comparisons in report.comparisons.items():
            compare_metrics = next((run for run in report.compare_metrics_list if run.run_id == run_id), None)
            
            html_content += f"""
        <h2>Comparison: {run_id}</h2>
        <p><strong>Run Path:</strong> {compare_metrics.run_path if compare_metrics else 'Unknown'}</p>
        
        <h3>Metric Comparison</h3>
        <table>
            <tr>
                <th>Metric</th>
                <th>Baseline</th>
                <th>Compare</th>
                <th>Delta</th>
                <th>Delta %</th>
                <th>Status</th>
            </tr>
"""
            
            for comp in metric_comparisons:
                status_class = "improvement" if comp.is_improvement else "regression"
                status_text = "✓ IMPROVE" if comp.is_improvement else "✗ REGRESS"
                
                html_content += f"""
            <tr>
                <td>{comp.metric_name}</td>
                <td>{comp.baseline_value:.2f}</td>
                <td>{comp.compare_value:.2f}</td>
                <td>{comp.delta:.2f}</td>
                <td>{comp.delta_pct:.1f}%</td>
                <td class="{status_class}">{status_text}</td>
            </tr>
"""
            
            html_content += """
        </table>
"""
            
            # Add statistical test results
            if run_id in report.statistical_tests:
                test = report.statistical_tests[run_id]
                significance_class = "significant" if test.is_significant else "not-significant"
                
                html_content += f"""
        <h3>Statistical Test Results</h3>
        <div class="{significance_class}">
            <p><strong>Test:</strong> {test.test_name}</p>
            <p><strong>Statistic:</strong> {test.statistic:.4f}</p>
            <p><strong>P-value:</strong> {test.p_value:.4f}</p>
            <p><strong>Significant:</strong> {'Yes' if test.is_significant else 'No'}</p>
            <p><strong>Interpretation:</strong> {test.interpretation}</p>
        </div>
"""
        
        # Add charts
        if charts:
            html_content += """
        <h2>Visualizations</h2>
"""
            
            if 'metrics_table' in charts and charts['metrics_table']:
                html_content += f"""
        <h3>Metrics Comparison Table</h3>
        <div class="chart-container">
            <img src="data:image/png;base64,{charts['metrics_table']}" alt="Metrics Comparison Table">
        </div>
"""
            
            if 'delta_bar' in charts and charts['delta_bar']:
                html_content += f"""
        <h3>Metric Changes vs Baseline</h3>
        <div class="chart-container">
            <img src="data:image/png;base64,{charts['delta_bar']}" alt="Delta Bar Chart">
        </div>
"""
            
            if 'win_rate' in charts and charts['win_rate']:
                html_content += f"""
        <h3>Win Rate Comparison</h3>
        <div class="chart-container">
            <img src="data:image/png;base64,{charts['win_rate']}" alt="Win Rate Comparison">
        </div>
"""
            
            if 'pnl_distribution' in charts and charts['pnl_distribution']:
                html_content += f"""
        <h3>PnL Distribution Comparison</h3>
        <div class="chart-container">
            <img src="data:image/png;base64,{charts['pnl_distribution']}" alt="PnL Distribution">
        </div>
"""
            
            if 'equity_curve' in charts and charts['equity_curve']:
                html_content += f"""
        <h3>Equity Curve Overlay</h3>
        <div class="chart-container">
            <img src="data:image/png;base64,{charts['equity_curve']}" alt="Equity Curve Overlay">
        </div>
"""
        
        # Add summary
        html_content += f"""
        <h2>Summary</h2>
        <div class="summary">
            <pre>{report.summary}</pre>
        </div>
        
        <div class="footer">
            <p>Generated by Backtest Comparison Tool</p>
            <p>Report generated on {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </div>
</body>
</html>
"""
        
        # Write HTML file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"HTML report saved to: {output_path}")
    except Exception as e:
        logger.error(f"Error generating HTML report: {e}")


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Compare performance metrics across multiple backtest runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Basic comparison:
    python analysis/compare_backtests.py --baseline logs/backtest_results/EUR-USD_20251013_200009 --compare logs/backtest_results/EUR-USD_20251013_201006
  
  Multiple comparisons:
    python analysis/compare_backtests.py --baseline run1 --compare run2 run3 run4
  
  With JSON export:
    python analysis/compare_backtests.py --baseline run1 --compare run2 --json --output reports/comparison.html
        """
    )
    
    parser.add_argument(
        '--baseline',
        type=Path,
        required=True,
        help='Path to baseline backtest results directory'
    )
    
    parser.add_argument(
        '--compare',
        type=Path,
        nargs='+',
        required=True,
        help='Paths to comparison backtest results directories (one or more)'
    )
    
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('reports/backtest_comparison.html'),
        help='Path for HTML report output (default: reports/backtest_comparison.html)'
    )
    
    parser.add_argument(
        '--json',
        action='store_true',
        help='Export JSON report in addition to HTML'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable debug logging'
    )
    
    parser.add_argument(
        '--risk-free-rate',
        type=float,
        default=0.0,
        help='Risk-free rate for Sharpe ratio calculation (default: 0.0)'
    )
    
    parser.add_argument(
        '--starting-capital',
        type=float,
        default=100000.0,
        help='Starting capital for drawdown calculation (default: 100000.0)'
    )
    
    args = parser.parse_args(argv)
    
    # Validate directories exist
    if not args.baseline.exists():
        parser.error(f"Baseline directory does not exist: {args.baseline}")
    
    for compare_dir in args.compare:
        if not compare_dir.exists():
            parser.error(f"Compare directory does not exist: {compare_dir}")
    
    return args


def main(argv: Optional[List[str]] = None) -> int:
    """Main function."""
    try:
        # Parse arguments
        args = parse_arguments(argv)
        
        # Set logging level
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        # Validate input directories contain required files
        baseline_dir = args.baseline
        compare_dirs = args.compare
        
        # Check baseline directory
        required_files = ['performance_stats.json', 'positions.csv']
        for file_name in required_files:
            if not (baseline_dir / file_name).exists():
                logger.error(f"Required file not found in baseline directory: {baseline_dir / file_name}")
                return 1
        
        # Check compare directories
        for compare_dir in compare_dirs:
            for file_name in required_files:
                if not (compare_dir / file_name).exists():
                    logger.error(f"Required file not found in compare directory: {compare_dir / file_name}")
                    return 1
        
        logger.info(f"Comparing baseline: {baseline_dir}")
        logger.info(f"Comparing against: {compare_dirs}")
        
        # Extract metrics for baseline
        logger.info("Extracting baseline metrics...")
        baseline_metrics = extract_metrics(baseline_dir, risk_free_rate=args.risk_free_rate, starting_capital=args.starting_capital)
        
        # Extract metrics for compare runs
        logger.info("Extracting compare metrics...")
        compare_metrics_list = []
        for compare_dir in compare_dirs:
            compare_metrics = extract_metrics(compare_dir, risk_free_rate=args.risk_free_rate, starting_capital=args.starting_capital)
            compare_metrics_list.append(compare_metrics)
        
        # Load positions data for statistical testing
        baseline_positions = load_positions(baseline_dir)
        compare_positions_list = []
        for compare_dir in compare_dirs:
            compare_positions = load_positions(compare_dir)
            compare_positions_list.append((compare_dir.name, compare_positions))
        
        # Perform comparisons
        logger.info("Performing metric comparisons...")
        comparisons = {}
        for cmp_metrics in compare_metrics_list:
            run_id = cmp_metrics.run_id
            comparisons[run_id] = compare_metrics(baseline_metrics, cmp_metrics)
        
        # Perform statistical tests
        logger.info("Performing statistical tests...")
        statistical_tests = {}
        for i, cmp_metrics in enumerate(compare_metrics_list):
            run_id = cmp_metrics.run_id
            compare_positions = compare_positions_list[i][1]
            statistical_tests[run_id] = perform_statistical_test(baseline_positions, compare_positions)
        
        # Generate summary
        logger.info("Generating summary...")
        summary = generate_summary(baseline_metrics, comparisons, statistical_tests)
        
        # Create comparison report
        report = ComparisonReport(
            baseline_metrics=baseline_metrics,
            compare_metrics_list=compare_metrics_list,
            comparisons=comparisons,
            statistical_tests=statistical_tests,
            summary=summary
        )
        
        # Generate console report (always)
        logger.info("Generating console report...")
        generate_console_report(report)
        
        # Generate charts
        logger.info("Generating charts...")
        charts = {}
        
        # Metrics comparison table
        charts['metrics_table'] = create_metrics_comparison_table_chart(baseline_metrics, compare_metrics_list)
        
        # Delta bar chart
        charts['delta_bar'] = create_delta_bar_chart(comparisons)
        
        # Win rate comparison
        charts['win_rate'] = create_win_rate_comparison_chart(baseline_metrics, compare_metrics_list)
        
        # PnL distribution
        charts['pnl_distribution'] = create_pnl_distribution_chart(baseline_positions, compare_positions_list)
        
        # Equity curve overlay
        baseline_equity = load_equity_curve(baseline_dir)
        compare_equity_list = []
        for compare_dir in compare_dirs:
            compare_equity = load_equity_curve(compare_dir)
            if not compare_equity.empty:
                compare_equity_list.append((compare_dir.name, compare_equity))
        
        if not baseline_equity.empty and compare_equity_list:
            charts['equity_curve'] = create_equity_curve_overlay_chart(baseline_equity, compare_equity_list)
        
        # Generate HTML report (always)
        logger.info("Generating HTML report...")
        generate_html_report(report, args.output, charts)
        
        # Generate JSON report (if requested)
        if args.json:
            logger.info("Generating JSON report...")
            json_output = args.output.with_suffix('.json')
            generate_json_report(report, json_output)
        
        # Log output paths
        logger.info(f"HTML report: {args.output}")
        if args.json:
            logger.info(f"JSON report: {args.output.with_suffix('.json')}")
        
        logger.info("Comparison completed successfully!")
        return 0
        
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
