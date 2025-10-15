"""
Filter Effectiveness Analyzer for NautilusTrader Backtest Results.

Analyzes the performance of strategy filters (Threshold, DMI, Stochastic) by
parsing rejected signals and calculating pass rates, rejection patterns, and
filter cascade flow.

Usage Examples:

    # Basic analysis (console output only)
    python analysis/analyze_filter_effectiveness.py \
        --results logs/backtest_results/EUR-USD_20251013_201415
    
    # Generate HTML report with charts
    python analysis/analyze_filter_effectiveness.py \
        --results logs/backtest_results/EUR-USD_20251013_201415 \
        --output reports/filter_analysis.html
    
    # Export JSON for programmatic consumption
    python analysis/analyze_filter_effectiveness.py \
        --results logs/backtest_results/EUR-USD_20251013_201415 \
        --output reports/filter_analysis.html \
        --json
    
    # Text-only report (no charts)
    python analysis/analyze_filter_effectiveness.py \
        --results logs/backtest_results/EUR-USD_20251013_201415 \
        --no-charts
    
    # Verbose mode with debug logging
    python analysis/analyze_filter_effectiveness.py \
        --results logs/backtest_results/EUR-USD_20251013_201415 \
        --output reports/filter_analysis.html \
        --verbose

Outputs:
    - Console: Summary statistics and filter cascade flow
    - HTML (with --output): Comprehensive report with embedded charts
    - JSON (with --json): Machine-readable analysis results
    - Charts (unless --no-charts): PNG images in charts subdirectory

Exit Codes:
    0: Analysis completed successfully
    1: No data found or analysis failed
    2: Critical error (invalid results directory, missing files)
"""

import argparse
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from matplotlib.patches import Rectangle


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class FilterStats:
    """Store statistics for a single filter."""
    filter_name: str
    total_signals_in: int
    signals_passed: int
    signals_rejected: int
    pass_rate: float
    rejection_reasons: Dict[str, int]
    
    def format_summary(self) -> str:
        """Human-readable summary."""
        return f"{self.filter_name}: {self.signals_passed}/{self.total_signals_in} passed ({self.pass_rate:.1f}%), {self.signals_rejected} rejected"


@dataclass
class FilterCascadeReport:
    """Complete filter cascade analysis."""
    backtest_run_id: str
    total_crossovers: int
    filter_stats: List[FilterStats]
    final_signals: int
    overall_pass_rate: float
    rejection_breakdown: Dict[str, int]
    signal_type_breakdown: Dict[str, Dict[str, int]]
    close_only_count: int = 0
    
    def format_cascade_flow(self) -> str:
        """ASCII art showing signal flow."""
        lines = [f"{self.total_crossovers} MA Crossovers"]
        
        for i, filter_stat in enumerate(self.filter_stats):
            lines.append(f"  ↓ {filter_stat.filter_name}")
            lines.append(f"  → {filter_stat.signals_passed} passed ({filter_stat.pass_rate:.1f}%), {filter_stat.signals_rejected} rejected")
        
        lines.append(f"\nFinal: {self.final_signals} trades executed ({self.overall_pass_rate:.1f}% of original crossovers)")
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON export."""
        return {
            "backtest_run_id": self.backtest_run_id,
            "total_crossovers": self.total_crossovers,
            "filter_stats": [asdict(stat) for stat in self.filter_stats],
            "final_signals": self.final_signals,
            "overall_pass_rate": self.overall_pass_rate,
            "rejection_breakdown": self.rejection_breakdown,
            "signal_type_breakdown": self.signal_type_breakdown,
            "close_only_count": self.close_only_count
        }


@dataclass
class FilterContribution:
    """Estimate PnL contribution of each filter."""
    filter_name: str
    estimated_pnl_impact: Optional[float]
    actual_pnl_impact: Optional[float]
    methodology: str
    notes: str


def load_rejected_signals(results_dir: Path) -> pd.DataFrame:
    """Load and parse rejected_signals.csv."""
    rejected_file = results_dir / "rejected_signals.csv"
    
    if not rejected_file.exists():
        logger.warning(f"rejected_signals.csv not found in {results_dir}")
        return pd.DataFrame(columns=['timestamp', 'bar_close_time', 'signal_type', 'action', 'reason', 'fast_sma', 'slow_sma'])
    
    try:
        df = pd.read_csv(rejected_file)
        # Parse timestamps if they exist
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        if 'bar_close_time' in df.columns:
            df['bar_close_time'] = pd.to_datetime(df['bar_close_time'])
        return df
    except Exception as e:
        logger.error(f"Error loading rejected_signals.csv: {e}")
        return pd.DataFrame(columns=['timestamp', 'bar_close_time', 'signal_type', 'action', 'reason', 'fast_sma', 'slow_sma'])


def load_orders(results_dir: Path) -> pd.DataFrame:
    """Load orders.csv to count executed signals."""
    orders_file = results_dir / "orders.csv"
    
    if not orders_file.exists():
        logger.warning(f"orders.csv not found in {results_dir}")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(orders_file)
        
        # Normalize order side column (Comment 2)
        if 'side' not in df.columns and 'order_side' in df.columns:
            df['side'] = df['order_side']
        
        # Filter for entry orders (exclude SL/TP orders) - Comment 3
        if 'tags' in df.columns:
            # Coerce tags to string and use regex for filtering
            df['tags'] = df['tags'].astype(str)
            entry_orders = df[df['tags'].str.contains(r'(?:^|,|\s)MA_CROSS(?:$|,|\s)', na=False, regex=True) & 
                            ~df['tags'].str.contains(r'_SL|_TP', na=False, regex=True)]
        else:
            # Fallback: assume all orders are entry orders if no tags column
            entry_orders = df
        return entry_orders
    except Exception as e:
        logger.error(f"Error loading orders.csv: {e}")
        return pd.DataFrame()


def load_performance_stats(results_dir: Path) -> Dict[str, Any]:
    """Load performance_stats.json."""
    stats_file = results_dir / "performance_stats.json"
    
    if not stats_file.exists():
        logger.warning(f"performance_stats.json not found in {results_dir}")
        return {}
    
    try:
        with open(stats_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading performance_stats.json: {e}")
        return {}


def load_positions(results_dir: Path) -> pd.DataFrame:
    """Load positions.csv for PnL analysis."""
    positions_file = results_dir / "positions.csv"
    
    if not positions_file.exists():
        logger.warning(f"positions.csv not found in {results_dir}")
        return pd.DataFrame()
    
    try:
        return pd.read_csv(positions_file)
    except Exception as e:
        logger.error(f"Error loading positions.csv: {e}")
        return pd.DataFrame()


def parse_rejection_reason(reason: str) -> Tuple[str, Optional[str]]:
    """Extract filter name and details from rejection reason string."""
    if pd.isna(reason) or reason == "":
        return ("unknown", None)
    
    reason = str(reason).strip()
    
    # Pattern matching for different rejection reasons
    if "crossover_threshold_not_met" in reason:
        # Extract pip difference if available
        diff_match = re.search(r'diff=([\d.]+)\s+pips', reason)
        details = f"diff={diff_match.group(1)} pips" if diff_match else None
        return ("threshold", details)
    elif "stochastic_unfavorable" in reason:
        return ("stochastic", None)
    elif "dmi_trend_mismatch" in reason:
        # Extract DMI values if available
        dmi_match = re.search(r'\+DI=([\d.]+)\s+<\s+-DI=([\d.]+)', reason)
        details = f"+DI={dmi_match.group(1)} < -DI={dmi_match.group(2)}" if dmi_match else None
        return ("dmi", details)
    elif "close_only" in reason:
        return ("close_only", None)  # Not a rejection
    elif "position" in reason.lower() or "already open" in reason.lower():
        return ("position_limit", reason)
    else:
        return ("unknown", reason)


def calculate_filter_cascade(rejected_df: pd.DataFrame, orders_df: pd.DataFrame, results_dir: Optional[Path] = None) -> FilterCascadeReport:
    """Analyze signal flow through filter cascade."""
    # Count total crossovers (rejected + executed)
    total_crossovers = len(rejected_df) + len(orders_df)
    
    if total_crossovers == 0:
        logger.warning("No signals found in data")
        return FilterCascadeReport(
            backtest_run_id="unknown",
            total_crossovers=0,
            filter_stats=[],
            final_signals=0,
            overall_pass_rate=0.0,
            rejection_breakdown={},
            signal_type_breakdown={},
            close_only_count=0
        )
    
    # Parse rejection reasons and group by filter (Comment 4)
    filter_rejections = defaultdict(int)
    rejection_reasons = defaultdict(int)
    filter_rejection_reasons = defaultdict(lambda: defaultdict(int))  # filter_name -> Counter(raw_reason)
    
    # Detect close_only events via action column when available (Comment 2)
    if 'action' in rejected_df.columns:
        close_only_count = int((rejected_df['action'] == 'close_only').sum())
    else:
        close_only_count = 0
    
    # Defensive column access (Comment 8)
    if 'reason' in rejected_df.columns:
        for _, row in rejected_df.iterrows():
            if pd.isna(row.get('reason')):
                continue
            
            # Skip close_only events if using action-based counting
            if 'action' in rejected_df.columns and row.get('action') == 'close_only':
                continue
                
            filter_name, details = parse_rejection_reason(row['reason'])
            
            # Count close_only events (fallback for reason-based counting)
            if filter_name == "close_only":
                close_only_count += 1
                continue
                
            filter_rejections[filter_name] += 1
            rejection_reasons[row['reason']] += 1
            filter_rejection_reasons[filter_name][row['reason']] += 1
    
    # Calculate cascade flow
    # Stage 0: Total crossovers
    signals_after_threshold = total_crossovers - filter_rejections.get('threshold', 0)
    signals_after_dmi = signals_after_threshold - filter_rejections.get('dmi', 0)
    signals_after_stochastic = signals_after_dmi - filter_rejections.get('stochastic', 0)
    signals_after_position = signals_after_stochastic - filter_rejections.get('position_limit', 0)
    final_signals = len(orders_df)
    
    # Create FilterStats for each stage
    filter_stats = []
    
    # Threshold filter
    threshold_rejections = filter_rejections.get('threshold', 0)
    filter_stats.append(FilterStats(
        filter_name="Threshold Filter",
        total_signals_in=total_crossovers,
        signals_passed=signals_after_threshold,
        signals_rejected=threshold_rejections,
        pass_rate=(signals_after_threshold / total_crossovers * 100) if total_crossovers > 0 else 0,
        rejection_reasons=dict(filter_rejection_reasons.get('threshold', {}))
    ))
    
    # DMI filter
    dmi_rejections = filter_rejections.get('dmi', 0)
    filter_stats.append(FilterStats(
        filter_name="DMI Filter",
        total_signals_in=signals_after_threshold,
        signals_passed=signals_after_dmi,
        signals_rejected=dmi_rejections,
        pass_rate=(signals_after_dmi / signals_after_threshold * 100) if signals_after_threshold > 0 else 100,
        rejection_reasons=dict(filter_rejection_reasons.get('dmi', {}))
    ))
    
    # Stochastic filter
    stoch_rejections = filter_rejections.get('stochastic', 0)
    filter_stats.append(FilterStats(
        filter_name="Stochastic Filter",
        total_signals_in=signals_after_dmi,
        signals_passed=signals_after_stochastic,
        signals_rejected=stoch_rejections,
        pass_rate=(signals_after_stochastic / signals_after_dmi * 100) if signals_after_dmi > 0 else 100,
        rejection_reasons=dict(filter_rejection_reasons.get('stochastic', {}))
    ))
    
    # Position limit filter
    position_rejections = filter_rejections.get('position_limit', 0)
    filter_stats.append(FilterStats(
        filter_name="Position Limit",
        total_signals_in=signals_after_stochastic,
        signals_passed=signals_after_position,
        signals_rejected=position_rejections,
        pass_rate=(signals_after_position / signals_after_stochastic * 100) if signals_after_stochastic > 0 else 100,
        rejection_reasons=dict(filter_rejection_reasons.get('position_limit', {}))
    ))
    
    # Calculate signal type breakdown
    signal_type_breakdown = {"BUY": {"total": 0, "executed": 0, "rejected": 0}, 
                           "SELL": {"total": 0, "executed": 0, "rejected": 0}}
    
    # Count by signal type in rejected signals (defensive access)
    if 'signal_type' in rejected_df.columns:
        for signal_type in ['BUY', 'SELL']:
            type_rejections = len(rejected_df[rejected_df['signal_type'] == signal_type])
            signal_type_breakdown[signal_type]["rejected"] = type_rejections
    
    # Count by signal type in executed orders (defensive access)
    if 'side' in orders_df.columns:
        for side in ['BUY', 'SELL']:
            type_executed = len(orders_df[orders_df['side'] == side])
            signal_type_breakdown[side]["executed"] = type_executed
    
    # Calculate totals
    for signal_type in signal_type_breakdown:
        signal_type_breakdown[signal_type]["total"] = (
            signal_type_breakdown[signal_type]["executed"] + 
            signal_type_breakdown[signal_type]["rejected"]
        )
    
    return FilterCascadeReport(
        backtest_run_id=results_dir.name if results_dir and hasattr(results_dir, 'name') else "unknown",
        total_crossovers=total_crossovers,
        filter_stats=filter_stats,
        final_signals=final_signals,
        overall_pass_rate=(final_signals / total_crossovers * 100) if total_crossovers > 0 else 0,
        rejection_breakdown=dict(rejection_reasons),
        signal_type_breakdown=signal_type_breakdown,
        close_only_count=close_only_count
    )


def calculate_comparative_contribution(baseline_dir: Optional[Path], threshold_only_dir: Optional[Path], 
                                       threshold_dmi_dir: Optional[Path], all_filters_dir: Optional[Path]) -> List[FilterContribution]:
    """Calculate actual PnL contribution using comparative backtests (Comment 1)."""
    contributions = []
    
    def load_pnl_from_dir(results_dir: Path) -> Optional[float]:
        """Load PnL from performance_stats.json."""
        try:
            stats_file = results_dir / "performance_stats.json"
            if stats_file.exists():
                with open(stats_file, 'r') as f:
                    stats = json.load(f)
                    return stats.get('total_pnl', None)
        except Exception as e:
            logger.warning(f"Could not load PnL from {results_dir}: {e}")
        return None
    
    # Load PnL from each configuration
    baseline_pnl = load_pnl_from_dir(baseline_dir) if baseline_dir else None
    threshold_only_pnl = load_pnl_from_dir(threshold_only_dir) if threshold_only_dir else None
    threshold_dmi_pnl = load_pnl_from_dir(threshold_dmi_dir) if threshold_dmi_dir else None
    all_filters_pnl = load_pnl_from_dir(all_filters_dir) if all_filters_dir else None
    
    # Calculate filter contributions
    if baseline_pnl is not None and threshold_only_pnl is not None:
        threshold_impact = threshold_only_pnl - baseline_pnl
        contributions.append(FilterContribution(
            filter_name="Threshold Filter",
            estimated_pnl_impact=None,
            actual_pnl_impact=threshold_impact,
            methodology="comparative_backtest",
            notes=f"Threshold filter impact: {threshold_impact:.2f} (vs baseline)"
        ))
    
    if threshold_only_pnl is not None and threshold_dmi_pnl is not None:
        dmi_impact = threshold_dmi_pnl - threshold_only_pnl
        contributions.append(FilterContribution(
            filter_name="DMI Filter",
            estimated_pnl_impact=None,
            actual_pnl_impact=dmi_impact,
            methodology="comparative_backtest",
            notes=f"DMI filter impact: {dmi_impact:.2f} (vs threshold-only)"
        ))
    
    if threshold_dmi_pnl is not None and all_filters_pnl is not None:
        stochastic_impact = all_filters_pnl - threshold_dmi_pnl
        contributions.append(FilterContribution(
            filter_name="Stochastic Filter",
            estimated_pnl_impact=None,
            actual_pnl_impact=stochastic_impact,
            methodology="comparative_backtest",
            notes=f"Stochastic filter impact: {stochastic_impact:.2f} (vs threshold+dmi)"
        ))
    
    # If no comparative data available, return estimated contributions
    if not contributions:
        filters = ["Threshold Filter", "DMI Filter", "Stochastic Filter", "Position Limit"]
        for filter_name in filters:
            contributions.append(FilterContribution(
                filter_name=filter_name,
                estimated_pnl_impact=None,
                actual_pnl_impact=None,
                methodology="requires_comparative_backtest",
                notes="To measure actual PnL contribution, run backtests with this filter disabled and compare results"
            ))
    
    return contributions


def estimate_filter_contribution(rejected_df: pd.DataFrame, positions_df: pd.DataFrame, performance_stats: Dict) -> List[FilterContribution]:
    """Estimate PnL impact of each filter."""
    contributions = []
    
    # Note: Direct PnL contribution cannot be calculated from a single backtest
    # This requires comparative backtests with filters disabled
    
    filters = ["Threshold Filter", "DMI Filter", "Stochastic Filter", "Position Limit"]
    
    for filter_name in filters:
        contributions.append(FilterContribution(
            filter_name=filter_name,
            estimated_pnl_impact=None,
            actual_pnl_impact=None,
            methodology="requires_comparative_backtest",
            notes="To measure actual PnL contribution, run backtests with this filter disabled and compare results"
        ))
    
    return contributions


def analyze_rejection_patterns(rejected_df: pd.DataFrame) -> Dict[str, Any]:
    """Find patterns in rejected signals."""
    patterns = {
        "temporal": {},
        "signal_type": {},
        "threshold_proximity": {},
        "filter_correlation": {}
    }
    
    if len(rejected_df) == 0:
        return patterns
    
    # Temporal patterns
    if 'timestamp' in rejected_df.columns:
        hours = rejected_df['timestamp'].dt.hour
        hourly_rejections = hours.value_counts().to_dict()
        patterns["temporal"]["hourly_rejections"] = hourly_rejections
    
    # Signal type patterns
    if 'signal_type' in rejected_df.columns:
        signal_type_counts = rejected_df['signal_type'].value_counts().to_dict()
        patterns["signal_type"]["rejection_counts"] = signal_type_counts
    
    # Threshold proximity analysis (only if reason column exists)
    if 'reason' in rejected_df.columns:
        threshold_rejections = rejected_df[rejected_df['reason'].str.contains('crossover_threshold_not_met', na=False)].copy()
        if len(threshold_rejections) > 0:
            pip_differences = []
            for reason in threshold_rejections['reason']:
                match = re.search(r'diff=([\d.]+)\s+pips', str(reason))
                if match:
                    pip_differences.append(float(match.group(1)))
            
            if pip_differences:
                patterns["threshold_proximity"] = {
                    "pip_differences": pip_differences,
                    "mean_diff": sum(pip_differences) / len(pip_differences),
                    "close_to_threshold": len([d for d in pip_differences if d >= 0.6])
                }
    
    return patterns


def create_cascade_funnel_chart(cascade_report: FilterCascadeReport, output_path: Optional[Path]) -> None:
    """Generate funnel chart showing signal flow through filters."""
    plt.figure(figsize=(12, 8))
    
    # Prepare data for funnel
    stages = ["Crossovers"] + [stat.filter_name for stat in cascade_report.filter_stats] + ["Executed"]
    signal_counts = [cascade_report.total_crossovers] + [stat.signals_passed for stat in cascade_report.filter_stats] + [cascade_report.final_signals]
    
    # Create horizontal funnel
    y_pos = range(len(stages))
    colors = ['lightblue'] + ['lightgreen'] * len(cascade_report.filter_stats) + ['darkgreen']
    
    bars = plt.barh(y_pos, signal_counts, color=colors)
    
    # Add labels
    for i, (stage, count) in enumerate(zip(stages, signal_counts)):
        plt.text(count/2, i, f"{count}\n({count/cascade_report.total_crossovers*100:.1f}%)", 
                ha='center', va='center', fontweight='bold')
    
    plt.yticks(y_pos, stages)
    plt.xlabel('Number of Signals')
    plt.title('Filter Cascade Flow')
    plt.grid(axis='x', alpha=0.3)
    
    if output_path:
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        logger.info(f"Cascade funnel chart saved to {output_path}")
    else:
        plt.show()
    
    plt.close()


def create_rejection_breakdown_chart(cascade_report: FilterCascadeReport, output_path: Optional[Path]) -> None:
    """Generate pie chart of rejection reasons."""
    plt.figure(figsize=(10, 8))
    
    # Prepare data
    filter_names = [stat.filter_name for stat in cascade_report.filter_stats]
    rejection_counts = [stat.signals_rejected for stat in cascade_report.filter_stats]
    
    # Remove filters with no rejections
    non_zero_data = [(name, count) for name, count in zip(filter_names, rejection_counts) if count > 0]
    
    if not non_zero_data:
        plt.text(0.5, 0.5, 'No Rejections Found', ha='center', va='center', fontsize=16)
        plt.title('Rejection Breakdown')
    else:
        names, counts = zip(*non_zero_data)
        colors = plt.cm.Set3(range(len(names)))
        
        wedges, texts, autotexts = plt.pie(counts, labels=names, autopct='%1.1f%%', colors=colors)
        plt.title('Rejection Breakdown by Filter')
        
        # Add count labels
        for i, (wedge, count) in enumerate(zip(wedges, counts)):
            angle = (wedge.theta2 + wedge.theta1) / 2
            x = wedge.r * 0.7 * np.cos(angle * np.pi / 180)
            y = wedge.r * 0.7 * np.sin(angle * np.pi / 180)
            plt.text(x, y, str(count), ha='center', va='center', fontweight='bold')
    
    if output_path:
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        logger.info(f"Rejection breakdown chart saved to {output_path}")
    else:
        plt.show()
    
    plt.close()


def create_signal_type_comparison(cascade_report: FilterCascadeReport, output_path: Optional[Path]) -> None:
    """Compare BUY vs SELL rejection rates per filter."""
    plt.figure(figsize=(12, 6))
    
    # This is a simplified version - in practice, you'd need to parse signal types from rejected signals
    # For now, show overall signal type breakdown
    signal_types = list(cascade_report.signal_type_breakdown.keys())
    executed = [cascade_report.signal_type_breakdown[st]["executed"] for st in signal_types]
    rejected = [cascade_report.signal_type_breakdown[st]["rejected"] for st in signal_types]
    
    x = range(len(signal_types))
    width = 0.35
    
    plt.bar([i - width/2 for i in x], executed, width, label='Executed', color='green', alpha=0.7)
    plt.bar([i + width/2 for i in x], rejected, width, label='Rejected', color='red', alpha=0.7)
    
    plt.xlabel('Signal Type')
    plt.ylabel('Count')
    plt.title('BUY vs SELL Signal Processing')
    plt.xticks(x, signal_types)
    plt.legend()
    plt.grid(axis='y', alpha=0.3)
    
    if output_path:
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        logger.info(f"Signal type comparison chart saved to {output_path}")
    else:
        plt.show()
    
    plt.close()


def create_threshold_proximity_histogram(rejected_df: pd.DataFrame, output_path: Optional[Path]) -> None:
    """Show distribution of crossover differences for threshold rejections."""
    plt.figure(figsize=(10, 6))
    
    # Early return if reason column is missing
    if 'reason' not in rejected_df.columns:
        plt.text(0.5, 0.5, 'Reason column not found in data', ha='center', va='center', fontsize=16)
        plt.title('Threshold Proximity Distribution')
        if output_path:
            plt.savefig(output_path, dpi=100, bbox_inches='tight')
            logger.info(f"Threshold proximity histogram saved to {output_path}")
        else:
            plt.show()
        plt.close()
        return
    
    # Extract pip differences from threshold rejections
    threshold_rejections = rejected_df[rejected_df['reason'].str.contains('crossover_threshold_not_met', na=False)]
    pip_differences = []
    
    # Use local Series for reasons and iterate safely
    reasons = threshold_rejections['reason']
    for reason in reasons:
        match = re.search(r'diff=([\d.]+)\s+pips', str(reason))
        if match:
            pip_differences.append(float(match.group(1)))
    
    if not pip_differences:
        plt.text(0.5, 0.5, 'No Threshold Rejections Found', ha='center', va='center', fontsize=16)
        plt.title('Threshold Proximity Distribution')
    else:
        plt.hist(pip_differences, bins=20, alpha=0.7, color='orange', edgecolor='black')
        plt.axvline(x=0.7, color='red', linestyle='--', linewidth=2, label='Threshold (0.7 pips)')
        plt.xlabel('Pip Difference')
        plt.ylabel('Count')
        plt.title('Distribution of Crossover Differences (Threshold Rejections)')
        plt.legend()
        plt.grid(alpha=0.3)
    
    if output_path:
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        logger.info(f"Threshold proximity histogram saved to {output_path}")
    else:
        plt.show()
    
    plt.close()


def generate_console_report(cascade_report: FilterCascadeReport, patterns: Dict, contributions: List[FilterContribution] = None) -> str:
    """Generate human-readable console report."""
    report = []
    report.append("Filter Effectiveness Analysis")
    report.append("=" * 50)
    report.append(f"Backtest Run: {cascade_report.backtest_run_id}")
    report.append(f"Total MA Crossovers: {cascade_report.total_crossovers}")
    report.append(f"Final Trades Executed: {cascade_report.final_signals} ({cascade_report.overall_pass_rate:.1f}%)")
    
    # Add close-only count (Comment 5)
    if cascade_report.close_only_count > 0:
        report.append(f"Close-only Events: {cascade_report.close_only_count} (non-rejection)")
    
    report.append("")
    
    report.append("Filter Cascade Flow:")
    report.append("-" * 20)
    report.append(cascade_report.format_cascade_flow())
    report.append("")
    
    report.append("Rejection Breakdown:")
    report.append("-" * 20)
    for stat in cascade_report.filter_stats:
        if stat.signals_rejected > 0:
            report.append(f"{stat.filter_name}: {stat.signals_rejected} rejections ({stat.signals_rejected/cascade_report.total_crossovers*100:.1f}%)")
            for reason, count in stat.rejection_reasons.items():
                if count > 0:
                    report.append(f"  - {reason}: {count}")
    report.append("")
    
    report.append("Signal Type Analysis:")
    report.append("-" * 20)
    for signal_type, data in cascade_report.signal_type_breakdown.items():
        if data["total"] > 0:
            executed_pct = (data["executed"] / data["total"] * 100) if data["total"] > 0 else 0
            report.append(f"{signal_type} Signals:")
            report.append(f"  - Total: {data['total']}")
            report.append(f"  - Executed: {data['executed']} ({executed_pct:.1f}%)")
            report.append(f"  - Rejected: {data['rejected']} ({100-executed_pct:.1f}%)")
    report.append("")
    
    report.append("Filter Contribution:")
    report.append("-" * 20)
    if contributions:
        has_actual_contributions = any(c.actual_pnl_impact is not None for c in contributions)
        if has_actual_contributions:
            report.append("Actual PnL Contributions (from comparative backtests):")
            for contrib in contributions:
                if contrib.actual_pnl_impact is not None:
                    report.append(f"  - {contrib.filter_name}: {contrib.actual_pnl_impact:.2f} PnL impact")
                    report.append(f"    {contrib.notes}")
        else:
            report.append("Estimated Contributions (requires comparative backtests):")
            for contrib in contributions:
                report.append(f"  - {contrib.filter_name}: {contrib.notes}")
    else:
        report.append("Note: Direct PnL contribution cannot be calculated from a single backtest.")
        report.append("To measure filter impact, run comparative backtests:")
        report.append("  1. Baseline: All filters disabled")
        report.append("  2. Threshold only: STRATEGY_CROSSOVER_THRESHOLD_PIPS=0.7, others disabled")
        report.append("  3. Threshold + DMI: Both enabled, Stochastic disabled")
        report.append("  4. All filters: Current configuration")
        report.append("")
        report.append("Compare PnL across runs to isolate each filter's contribution.")
    
    report.append("")
    
    report.append("Recommendations:")
    report.append("-" * 15)
    if cascade_report.filter_stats:
        most_active = max(cascade_report.filter_stats, key=lambda x: x.signals_rejected)
        report.append(f"- {most_active.filter_name} is most active ({most_active.signals_rejected/cascade_report.total_crossovers*100:.1f}% rejection rate)")
    
    report.append("- Consider adjusting threshold if many rejections are close to 0.7 pips")
    report.append("- DMI and Stochastic provide additional filtering")
    report.append("- Overall filter cascade reduces signals by quality over quantity")
    
    return "\n".join(report)


def generate_json_report(cascade_report: FilterCascadeReport, patterns: Dict, output_path: Path, contributions: List[FilterContribution] = None) -> None:
    """Export analysis as JSON."""
    data = {
        "backtest_run_id": cascade_report.backtest_run_id,
        "analysis_timestamp": pd.Timestamp.now().isoformat(),
        "summary": {
            "total_crossovers": cascade_report.total_crossovers,
            "final_trades": cascade_report.final_signals,
            "overall_pass_rate": cascade_report.overall_pass_rate,
            "total_rejections": sum(stat.signals_rejected for stat in cascade_report.filter_stats),
            "close_only_events": cascade_report.close_only_count
        },
        "filter_cascade": [asdict(stat) for stat in cascade_report.filter_stats],
        "signal_type_breakdown": cascade_report.signal_type_breakdown,
        "patterns": patterns,
        "contributions": [asdict(contrib) for contrib in contributions] if contributions else [],
        "recommendations": [
            "Threshold filter is most active",
            "Consider running comparative backtests to measure PnL contribution"
        ]
    }
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    logger.info(f"JSON report exported to {output_path}")


def generate_html_report(cascade_report: FilterCascadeReport, patterns: Dict, charts_dir: Path, output_path: Path, contributions: List[FilterContribution] = None) -> None:
    """Generate comprehensive HTML report with embedded charts."""
    # Calculate relative paths for charts (Comment 7)
    import os
    charts_relative_path = os.path.relpath(charts_dir, output_path.parent)
    
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Filter Effectiveness Analysis - {cascade_report.backtest_run_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        .summary {{ display: flex; justify-content: space-around; margin: 20px 0; }}
        .metric {{ text-align: center; padding: 20px; border: 2px solid #ecf0f1; border-radius: 8px; background: #f8f9fa; }}
        .metric h3 {{ margin: 0 0 10px 0; color: #2c3e50; }}
        .metric .value {{ font-size: 24px; font-weight: bold; }}
        .pass {{ color: #27ae60; }}
        .reject {{ color: #e74c3c; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #f2f2f2; font-weight: bold; }}
        .chart {{ text-align: center; margin: 30px 0; }}
        .chart img {{ max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 5px; }}
        .recommendations {{ background: #e8f4fd; padding: 20px; border-left: 4px solid #3498db; margin: 20px 0; }}
        .recommendations ul {{ margin: 10px 0; }}
        .recommendations li {{ margin: 5px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Filter Effectiveness Analysis</h1>
        <h2>Backtest Run: {cascade_report.backtest_run_id}</h2>
        
        <div class="summary">
            <div class="metric">
                <h3>Total Crossovers</h3>
                <p class="value">{cascade_report.total_crossovers}</p>
            </div>
            <div class="metric">
                <h3>Final Trades</h3>
                <p class="value pass">{cascade_report.final_signals} ({cascade_report.overall_pass_rate:.1f}%)</p>
            </div>
            <div class="metric">
                <h3>Total Rejections</h3>
                <p class="value reject">{sum(stat.signals_rejected for stat in cascade_report.filter_stats)} ({100-cascade_report.overall_pass_rate:.1f}%)</p>
            </div>
            <div class="metric">
                <h3>Close-only Events</h3>
                <p class="value">{cascade_report.close_only_count}</p>
            </div>
        </div>
        
        <h2>Filter Cascade Flow</h2>
        <div class="chart">
            <img src="{charts_relative_path}/cascade_funnel.png" alt="Filter Cascade Funnel Chart">
        </div>
        
        <h2>Rejection Breakdown</h2>
        <div class="chart">
            <img src="{charts_relative_path}/rejection_breakdown.png" alt="Rejection Breakdown Pie Chart">
        </div>
        
        <h2>Filter Statistics</h2>
        <table>
            <tr>
                <th>Filter</th>
                <th>Signals In</th>
                <th>Passed</th>
                <th>Rejected</th>
                <th>Pass Rate</th>
            </tr>
"""
    
    for stat in cascade_report.filter_stats:
        html_content += f"""
            <tr>
                <td>{stat.filter_name}</td>
                <td>{stat.total_signals_in}</td>
                <td class="pass">{stat.signals_passed}</td>
                <td class="reject">{stat.signals_rejected}</td>
                <td>{stat.pass_rate:.1f}%</td>
            </tr>
"""
    
    html_content += f"""
        </table>
        
        <h2>Signal Type Comparison</h2>
        <div class="chart">
            <img src="{charts_relative_path}/signal_type_comparison.png" alt="BUY vs SELL Rejection Rates">
        </div>
        
        <h2>Threshold Proximity Analysis</h2>
        <div class="chart">
            <img src="{charts_relative_path}/threshold_proximity.png" alt="Threshold Proximity Histogram">
        </div>
        
        <h2>Filter Contribution</h2>
        <table>
            <tr>
                <th>Filter</th>
                <th>Actual PnL Impact</th>
                <th>Methodology</th>
                <th>Notes</th>
            </tr>
"""
    
    if contributions:
        has_actual_contributions = any(c.actual_pnl_impact is not None for c in contributions)
        if has_actual_contributions:
            for contrib in contributions:
                if contrib.actual_pnl_impact is not None:
                    html_content += f"""
            <tr>
                <td>{contrib.filter_name}</td>
                <td>{contrib.actual_pnl_impact:.2f}</td>
                <td>{contrib.methodology}</td>
                <td>{contrib.notes}</td>
            </tr>
"""
        else:
            html_content += f"""
            <tr>
                <td colspan="4" style="text-align: center; font-style: italic; color: #666;">
                    Methodology only - Comparative backtests required for actual PnL impact
                </td>
            </tr>
"""
            for contrib in contributions:
                html_content += f"""
            <tr>
                <td>{contrib.filter_name}</td>
                <td>-</td>
                <td>{contrib.methodology}</td>
                <td>{contrib.notes}</td>
            </tr>
"""
    else:
        html_content += f"""
            <tr>
                <td colspan="4" style="text-align: center; font-style: italic; color: #666;">
                    No contribution data available
                </td>
            </tr>
"""
    
    html_content += f"""
        </table>
        
        <div class="recommendations">
            <h2>Recommendations</h2>
            <ul>
                <li>Threshold filter is most active ({max(stat.signals_rejected for stat in cascade_report.filter_stats)/cascade_report.total_crossovers*100:.1f}% rejection rate)</li>
                <li>Consider running comparative backtests to measure PnL contribution</li>
                <li>Analyze threshold proximity to optimize crossover threshold</li>
                <li>Monitor DMI and Stochastic filter effectiveness over time</li>
            </ul>
        </div>
    </div>
</body>
</html>
"""
    
    with open(output_path, 'w') as f:
        f.write(html_content)
    
    logger.info(f"HTML report generated: {output_path}")


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Analyze filter effectiveness from NautilusTrader backtest results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analysis/analyze_filter_effectiveness.py --results logs/backtest_results/EUR-USD_20251013_201415
  python analysis/analyze_filter_effectiveness.py --results logs/backtest_results/EUR-USD_20251013_201415 --output reports/analysis.html
  python analysis/analyze_filter_effectiveness.py --results logs/backtest_results/EUR-USD_20251013_201415 --json --no-charts
        """
    )
    
    parser.add_argument(
        '--results',
        required=True,
        type=Path,
        help='Path to backtest results directory (e.g., logs/backtest_results/EUR-USD_20251013_201415)'
    )
    
    parser.add_argument(
        '--output',
        type=Path,
        help='Output path for HTML report (default: reports/filter_analysis_{run_id}.html)'
    )
    
    parser.add_argument(
        '--json',
        action='store_true',
        help='Also export JSON report'
    )
    
    parser.add_argument(
        '--charts-dir',
        type=Path,
        help='Directory for chart images (default: {output_dir}/charts)'
    )
    
    parser.add_argument(
        '--no-charts',
        action='store_true',
        help='Skip chart generation (text report only)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable debug logging'
    )
    
    # Comparative analysis arguments
    parser.add_argument(
        '--baseline',
        type=Path,
        help='Path to baseline results directory (all filters disabled)'
    )
    
    parser.add_argument(
        '--threshold-only',
        type=Path,
        help='Path to threshold-only results directory'
    )
    
    parser.add_argument(
        '--threshold-dmi',
        type=Path,
        help='Path to threshold+dmi results directory'
    )
    
    parser.add_argument(
        '--all-filters',
        type=Path,
        help='Path to all-filters results directory'
    )
    
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_arguments()
    
    # Setup logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate results directory
    if not args.results.exists():
        logger.error(f"Results directory not found: {args.results}")
        return 2
    
    # Determine output paths (Comment 6)
    if args.output:
        output_path = args.output
    else:
        run_id = args.results.name
        output_path = Path('reports') / f'filter_analysis_{run_id}.html'
    
    if args.charts_dir:
        charts_dir = args.charts_dir
    else:
        charts_dir = output_path.with_suffix('').parent / 'charts'
    
    # Create output directories
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.no_charts:
        charts_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Load data
        logger.info(f"Loading data from {args.results}")
        rejected_df = load_rejected_signals(args.results)
        orders_df = load_orders(args.results)
        positions_df = load_positions(args.results)
        performance_stats = load_performance_stats(args.results)
        
        logger.info(f"Loaded {len(rejected_df)} rejected signals, {len(orders_df)} orders")
        
        if len(rejected_df) == 0 and len(orders_df) == 0:
            logger.warning("No data found in results directory")
            return 1
        
        # Run analysis
        logger.info("Running filter cascade analysis...")
        cascade_report = calculate_filter_cascade(rejected_df, orders_df, args.results)
        patterns = analyze_rejection_patterns(rejected_df)
        
        # Calculate contributions (Comment 1)
        if args.baseline or args.threshold_only or args.threshold_dmi or args.all_filters:
            contributions = calculate_comparative_contribution(
                args.baseline, args.threshold_only, args.threshold_dmi, args.all_filters
            )
        else:
            contributions = estimate_filter_contribution(rejected_df, positions_df, performance_stats)
        
        logger.info("Analysis complete")
        
        # Generate console report (always)
        console_report = generate_console_report(cascade_report, patterns, contributions)
        print(console_report)
        
        # Generate charts (unless --no-charts)
        if not args.no_charts:
            logger.info(f"Generating charts in {charts_dir}")
            create_cascade_funnel_chart(cascade_report, charts_dir / "cascade_funnel.png")
            create_rejection_breakdown_chart(cascade_report, charts_dir / "rejection_breakdown.png")
            create_signal_type_comparison(cascade_report, charts_dir / "signal_type_comparison.png")
            create_threshold_proximity_histogram(rejected_df, charts_dir / "threshold_proximity.png")
            logger.info(f"Charts saved to {charts_dir}")
        
        # Generate HTML report (always, using derived or provided path)
        logger.info(f"Generating HTML report: {output_path}")
        generate_html_report(cascade_report, patterns, charts_dir, output_path, contributions)
        logger.info(f"HTML report generated: {output_path}")
        
        # Generate JSON export (if --json)
        if args.json:
            json_path = output_path.with_suffix('.json')
            logger.info(f"Exporting JSON report: {json_path}")
            generate_json_report(cascade_report, patterns, json_path, contributions)
            logger.info(f"JSON report exported: {json_path}")
        
        # Summary
        logger.info("✅ Analysis complete")
        logger.info(f"📊 HTML Report: {output_path}")
        if args.json:
            logger.info(f"📄 JSON Report: {json_path}")
        if not args.no_charts:
            logger.info(f"📈 Charts: {charts_dir}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
