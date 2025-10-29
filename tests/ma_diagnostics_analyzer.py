"""
MA Diagnostics Analyzer

Automated analysis of MA crossover algorithm behavior using diagnostic test results.
This module provides pattern detection, anomaly identification, performance analysis,
and suggestion generation for the Moving Average Crossover strategy.

Key Capabilities:
- Pattern detection: Identifies false positives, false negatives, timing issues
- Anomaly identification: Detects filter failures, threshold sensitivity problems
- Performance analysis: Measures trade counts, PnL, win rates across scenarios
- Suggestion generation: Maps detected issues to actionable parameter adjustments

Usage:
    Called by run_ma_diagnostics.py or standalone for analysis
"""

from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from collections import Counter
import json
import logging

import pandas as pd
import numpy as np


@dataclass
class DiagnosticScenario:
    """Configuration for a diagnostic test scenario."""
    name: str
    symbol: str
    expected_trades: int
    expected_outcome: str  # "pass", "reject", "mixed"
    expected_rejection_reason: Optional[str] = None
    expected_bar: Optional[int] = None  # Expected crossover bar for timing analysis
    expected_min_trades: Optional[int] = None  # Minimum expected trades (for tolerance)
    expected_max_trades: Optional[int] = None  # Maximum expected trades (for tolerance)
    purpose: str = ""
    issue_indicators: List[str] = field(default_factory=list)
    slow_period: int = 20  # Slow MA period for warmup analysis


@dataclass
class CrossoverVerification:
    """Verification result for a single expected crossover."""
    expected_bar_index: int
    expected_timestamp: str
    expected_type: str  # "bullish" or "bearish"
    expected_fast_ma: float
    expected_slow_ma: float
    detected: bool
    actual_bar_index: Optional[int] = None
    actual_timestamp: Optional[str] = None
    timing_error_bars: Optional[int] = None
    issue: Optional[str] = None
    # MA buffer state analysis
    ma_buffer_length: Optional[int] = None
    ma_buffer_last_values: Optional[List[float]] = None
    ma_buffer_summary: Optional[Dict[str, float]] = None


@dataclass
class DiagnosticResult:
    """Results from analyzing a single diagnostic scenario."""
    scenario: DiagnosticScenario
    actual_trades: int
    actual_rejections: int
    rejection_reasons: List[str]
    pnl: float
    win_rate: float
    avg_trade_duration_bars: float
    crossover_detected: bool
    crossover_timing_bars: Optional[int]
    output_dir: Path
    passed: bool
    issues_detected: List[str]
    crossover_verifications: List[CrossoverVerification] = field(default_factory=list)
    expected_crossovers_count: int = 0
    detected_crossovers_count: int = 0
    missed_crossovers_count: int = 0
    false_positive_count: int = 0


@dataclass
class MADiagnosticReport:
    """Comprehensive diagnostic report with all findings and suggestions."""
    scenarios_tested: int
    scenarios_passed: int
    scenarios_failed: int
    results: List[DiagnosticResult]
    detected_issues: Dict[str, List[str]]
    performance_summary: Dict[str, Any]
    suggestions: List[Dict[str, str]]
    timestamp: str


def load_backtest_results(output_dir: Path) -> Dict[str, Any]:
    """
    Load and parse all backtest output files from directory.
    
    Args:
        output_dir: Path to backtest output directory
        
    Returns:
        Dictionary with parsed backtest data
    """
    results = {
        "performance_stats": {},
        "orders": pd.DataFrame(),
        "positions": pd.DataFrame(),
        "rejected_signals": pd.DataFrame()
    }
    
    try:
        # Load performance stats
        perf_file = output_dir / "performance_stats.json"
        if perf_file.exists():
            with open(perf_file, 'r') as f:
                results["performance_stats"] = json.load(f)
        
        # Load orders
        orders_file = output_dir / "orders.csv"
        if orders_file.exists():
            results["orders"] = pd.read_csv(orders_file)
        
        # Load positions
        positions_file = output_dir / "positions.csv"
        if positions_file.exists():
            results["positions"] = pd.read_csv(positions_file)
        
        # Load rejected signals
        rejected_file = output_dir / "rejected_signals.csv"
        if rejected_file.exists():
            results["rejected_signals"] = pd.read_csv(rejected_file)
        
    except Exception as e:
        logging.warning(f"Error loading backtest results from {output_dir}: {e}")
    
    return results


def compute_ma_values_from_catalog(catalog_path: Path, symbol: str, fast_period: int, slow_period: int) -> Optional[List[Tuple[int, float, float]]]:
    """
    Compute MA values from catalog OHLCV data.
    
    Args:
        catalog_path: Path to catalog directory
        symbol: Instrument symbol
        fast_period: Fast MA period
        slow_period: Slow MA period
        
    Returns:
        List of (bar_index, fast_ma, slow_ma) tuples or None if computation fails
    """
    try:
        from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
        from nautilus_trader.model.data import Bar
        from nautilus_trader.model.objects import Price
        
        # Create catalog instance
        catalog = ParquetDataCatalog(catalog_path)
        
        # Get instrument
        instrument_id = symbol.replace('/', '-')
        bar_type_str = f"{instrument_id}-1-MINUTE-MID-EXTERNAL"
        
        # Query bars
        bars = catalog.bars(
            bar_type=bar_type_str,
            start=pd.Timestamp("2024-01-01", tz="UTC"),
            end=pd.Timestamp("2024-01-10", tz="UTC")
        )
        
        if not bars:
            return None
        
        # Extract close prices
        close_prices = []
        for bar in bars:
            if hasattr(bar, 'close') and hasattr(bar.close, 'as_double'):
                close_prices.append(bar.close.as_double())
            else:
                # Fallback for different price object types
                close_prices.append(float(str(bar.close)))
        
        # Compute MA values
        ma_values = []
        for i in range(slow_period - 1, len(close_prices)):
            # Calculate slow SMA
            slow_sma = sum(close_prices[i - slow_period + 1:i + 1]) / slow_period
            
            # Calculate fast SMA if enough data
            if i >= fast_period - 1:
                fast_sma = sum(close_prices[i - fast_period + 1:i + 1]) / fast_period
            else:
                fast_sma = None
            
            ma_values.append((i, fast_sma, slow_sma))
        
        return ma_values
        
    except Exception as e:
        logging.warning(f"Error computing MA values from catalog for {symbol}: {e}")
        return None


def analyze_ma_buffer_state(
    ma_values: List[Tuple[int, float, float]],
    crossover_bar: int,
    slow_period: int
) -> Dict[str, Any]:
    """
    Analyze MA buffer state at crossover point.
    
    Args:
        ma_values: List of (bar_index, fast_ma, slow_ma) tuples
        crossover_bar: Bar index where crossover occurs
        slow_period: Slow MA period for buffer analysis
        
    Returns:
        Dictionary with buffer state analysis
    """
    # Find MA values around crossover point
    crossover_ma_values = [mv for mv in ma_values if mv[0] == crossover_bar]
    
    if not crossover_ma_values:
        return {
            "buffer_length": 0,
            "last_values": [],
            "summary": {}
        }
    
    # Get buffer window (last slow_period values)
    buffer_start = max(0, crossover_bar - slow_period + 1)
    buffer_values = [mv for mv in ma_values if buffer_start <= mv[0] <= crossover_bar]
    
    # Extract slow MA values from buffer
    slow_ma_buffer = [mv[2] for mv in buffer_values if mv[2] is not None]
    
    if not slow_ma_buffer:
        return {
            "buffer_length": 0,
            "last_values": [],
            "summary": {}
        }
    
    # Compute summary statistics
    summary = {
        "min": min(slow_ma_buffer),
        "max": max(slow_ma_buffer),
        "mean": sum(slow_ma_buffer) / len(slow_ma_buffer),
        "std": np.std(slow_ma_buffer) if len(slow_ma_buffer) > 1 else 0.0,
        "trend": "increasing" if slow_ma_buffer[-1] > slow_ma_buffer[0] else "decreasing" if slow_ma_buffer[-1] < slow_ma_buffer[0] else "flat"
    }
    
    return {
        "buffer_length": len(slow_ma_buffer),
        "last_values": slow_ma_buffer[-5:],  # Last 5 values
        "summary": summary
    }


def load_metadata_for_scenario(catalog_path: Path, symbol: str) -> dict:
    """
    Load metadata JSON file for a scenario.
    
    Args:
        catalog_path: Path to catalog directory
        symbol: Instrument symbol
        
    Returns:
        Metadata dict with expected_crossovers list
    """
    try:
        metadata_file = catalog_path / "metadata" / f"{symbol.replace('/', '-')}_metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                return json.load(f)
        else:
            logging.warning(f"Metadata file not found: {metadata_file}")
            return {}
    except Exception as e:
        logging.warning(f"Error loading metadata for {symbol}: {e}")
        return {}


def correlate_missed_crossovers_with_rejections(
    expected_crossovers: List[dict],
    rejected_signals_df: pd.DataFrame,
    start_date: str,
    tolerance_bars: int = 1
) -> Dict[int, str]:
    """
    Correlate missed expected crossovers with rejected signals.
    
    Args:
        expected_crossovers: List of expected crossover dicts from metadata
        rejected_signals_df: DataFrame with rejected signals data
        start_date: Start date string for timestamp calculation
        tolerance_bars: Tolerance in bars for matching
        
    Returns:
        Dictionary mapping expected crossover bar index to rejection reason
    """
    rejection_correlations = {}
    
    if rejected_signals_df.empty or "reason" not in rejected_signals_df.columns:
        return rejection_correlations
    
    # Convert rejection timestamps to bar indices
    rejected_signals_df = rejected_signals_df.copy()
    rejected_signals_df['timestamp'] = pd.to_datetime(rejected_signals_df['timestamp'])
    
    # Ensure timezone-aware timestamps
    if rejected_signals_df['timestamp'].dt.tz is None:
        rejected_signals_df['timestamp'] = rejected_signals_df['timestamp'].dt.tz_localize('UTC')
    
    start_timestamp = pd.Timestamp(start_date, tz="UTC")
    rejected_signals_df['bar_index'] = ((rejected_signals_df['timestamp'] - start_timestamp).dt.total_seconds() / 60).astype(int)
    
    # Match each expected crossover with rejected signals
    for crossover in expected_crossovers:
        expected_bar = crossover["bar_index"]
        
        # Find rejected signals within tolerance
        matching_rejections = rejected_signals_df[
            (rejected_signals_df['bar_index'] >= expected_bar - tolerance_bars) &
            (rejected_signals_df['bar_index'] <= expected_bar + tolerance_bars)
        ]
        
        if not matching_rejections.empty:
            # Use the most common rejection reason
            reasons = matching_rejections['reason'].value_counts()
            if not reasons.empty:
                rejection_correlations[expected_bar] = reasons.index[0]
    
    return rejection_correlations


def match_orders_to_expected_crossovers(
    orders_df: pd.DataFrame, 
    expected_crossovers: List[dict], 
    start_date: str, 
    tolerance_bars: int = 1,
    rejected_signals_df: Optional[pd.DataFrame] = None,
    ma_values: Optional[List[Tuple[int, float, float]]] = None,
    slow_period: int = 20
) -> List[CrossoverVerification]:
    """
    Match actual orders against expected crossovers from metadata.
    
    Args:
        orders_df: DataFrame with order data
        expected_crossovers: List of expected crossover dicts from metadata
        start_date: Start date string for timestamp calculation
        tolerance_bars: Tolerance in bars for timing matching
        rejected_signals_df: Optional DataFrame with rejected signals data
        ma_values: Optional MA values for buffer analysis
        slow_period: Slow MA period for buffer analysis
        
    Returns:
        List of CrossoverVerification objects
    """
    verifications = []
    
    # Get rejection correlations if rejected signals are available
    rejection_correlations = {}
    if rejected_signals_df is not None:
        rejection_correlations = correlate_missed_crossovers_with_rejections(
            expected_crossovers, rejected_signals_df, start_date, tolerance_bars
        )
    
    if orders_df.empty:
        # No orders - mark all expected crossovers as missed
        for crossover in expected_crossovers:
            expected_bar = crossover["bar_index"]
            issue = "Crossover not detected"
            
            # Check if there's a rejection reason for this crossover
            if expected_bar in rejection_correlations:
                issue = f"Rejected: {rejection_correlations[expected_bar]}"
            
            verification = CrossoverVerification(
                expected_bar_index=expected_bar,
                expected_timestamp=crossover["timestamp"],
                expected_type=crossover["type"],
                expected_fast_ma=crossover["fast_ma"],
                expected_slow_ma=crossover["slow_ma"],
                detected=False,
                issue=issue
            )
            verifications.append(verification)
        return verifications
    
    # Convert order timestamps to bar indices with proper timezone handling
    orders_df = orders_df.copy()
    orders_df['timestamp'] = pd.to_datetime(orders_df['ts_init'], unit='ns')
    
    # Ensure timezone-aware timestamps
    if orders_df['timestamp'].dt.tz is None:
        orders_df['timestamp'] = orders_df['timestamp'].dt.tz_localize('UTC')
    
    # Filter to only entry/OPEN orders for crossover matching
    if not orders_df.empty:
        # Check for common order type columns and filter accordingly
        if 'order_type' in orders_df.columns:
            # Filter for entry orders (exclude close/exit orders)
            entry_orders = orders_df[
                (orders_df['order_type'].str.contains('OPEN', case=False, na=False)) |
                (orders_df['order_type'].str.contains('ENTRY', case=False, na=False)) |
                (orders_df['order_type'].str.contains('BUY', case=False, na=False)) |
                (orders_df['order_type'].str.contains('SELL', case=False, na=False))
            ]
            if not entry_orders.empty:
                orders_df = entry_orders
        elif 'action' in orders_df.columns:
            # Filter for entry actions
            entry_orders = orders_df[
                (orders_df['action'].str.contains('OPEN', case=False, na=False)) |
                (orders_df['action'].str.contains('ENTRY', case=False, na=False)) |
                (orders_df['action'].str.contains('BUY', case=False, na=False)) |
                (orders_df['action'].str.contains('SELL', case=False, na=False))
            ]
            if not entry_orders.empty:
                orders_df = entry_orders
        elif 'side' in orders_df.columns:
            # Filter for entry sides (BUY/SELL)
            entry_orders = orders_df[
                (orders_df['side'].str.contains('BUY', case=False, na=False)) |
                (orders_df['side'].str.contains('SELL', case=False, na=False))
            ]
            if not entry_orders.empty:
                orders_df = entry_orders
    
    start_timestamp = pd.Timestamp(start_date, tz="UTC")
    orders_df['bar_index'] = ((orders_df['timestamp'] - start_timestamp).dt.total_seconds() / 60).astype(int)
    
    # Track which orders have been matched
    matched_orders = set()
    
    # Match each expected crossover
    for crossover in expected_crossovers:
        expected_bar = crossover["bar_index"]
        expected_timestamp = crossover["timestamp"]
        
        # Analyze MA buffer state if MA values are available
        ma_buffer_analysis = {}
        if ma_values:
            buffer_state = analyze_ma_buffer_state(ma_values, expected_bar, slow_period)
            ma_buffer_analysis = {
                "ma_buffer_length": buffer_state["buffer_length"],
                "ma_buffer_last_values": buffer_state["last_values"],
                "ma_buffer_summary": buffer_state["summary"]
            }
        
        # Find orders within tolerance
        matching_orders = orders_df[
            (orders_df['bar_index'] >= expected_bar - tolerance_bars) &
            (orders_df['bar_index'] <= expected_bar + tolerance_bars)
        ]
        
        if not matching_orders.empty:
            # Use first matching order
            order = matching_orders.iloc[0]
            matched_orders.add(order.name)
            
            timing_error = order['bar_index'] - expected_bar
            
            verification = CrossoverVerification(
                expected_bar_index=expected_bar,
                expected_timestamp=expected_timestamp,
                expected_type=crossover["type"],
                expected_fast_ma=crossover["fast_ma"],
                expected_slow_ma=crossover["slow_ma"],
                detected=True,
                actual_bar_index=order['bar_index'],
                actual_timestamp=order['timestamp'].isoformat(),
                timing_error_bars=timing_error,
                issue=None if abs(timing_error) <= tolerance_bars else f"Timing error: {timing_error} bars",
                **ma_buffer_analysis
            )
        else:
            # No matching order found - check for rejection reason
            issue = "Crossover not detected"
            if expected_bar in rejection_correlations:
                issue = f"Rejected: {rejection_correlations[expected_bar]}"
            
            verification = CrossoverVerification(
                expected_bar_index=expected_bar,
                expected_timestamp=expected_timestamp,
                expected_type=crossover["type"],
                expected_fast_ma=crossover["fast_ma"],
                expected_slow_ma=crossover["slow_ma"],
                detected=False,
                issue=issue,
                **ma_buffer_analysis
            )
        
        verifications.append(verification)
    
    # Identify false positives (orders without expected crossover)
    for idx, order in orders_df.iterrows():
        if idx not in matched_orders:
            verification = CrossoverVerification(
                expected_bar_index=-1,  # Indicates false positive
                expected_timestamp="",
                expected_type="",
                expected_fast_ma=0.0,
                expected_slow_ma=0.0,
                detected=True,
                actual_bar_index=order['bar_index'],
                actual_timestamp=order['timestamp'].isoformat(),
                issue="False positive: No expected crossover"
            )
            verifications.append(verification)
    
    return verifications


def detect_crossover_timing(orders_df: pd.DataFrame, expected_bar: Optional[int] = None) -> Optional[int]:
    """
    Parse order timestamps to determine when crossover was detected.
    
    Args:
        orders_df: DataFrame with order data
        expected_bar: Expected crossover bar (if None, uses dataset start as reference)
        
    Returns:
        Timing difference in bars (positive = late, negative = early), None if no orders
    """
    if orders_df.empty:
        return None
    
    try:
        # Convert timestamp to bar number (assuming 1-minute bars)
        orders_df = orders_df.copy()
        orders_df['timestamp'] = pd.to_datetime(orders_df['ts_init'], unit='ns')
        orders_df['bar_number'] = (orders_df['timestamp'] - orders_df['timestamp'].min()).dt.total_seconds() / 60
        
        # Find first order
        first_order_bar = orders_df['bar_number'].min()
        
        # Calculate timing difference relative to expected bar or dataset start
        if expected_bar is not None:
            timing_diff = int(first_order_bar - expected_bar)
        else:
            # Use dataset start as reference (bar 0)
            timing_diff = int(first_order_bar)
        
        return timing_diff
        
    except Exception as e:
        logging.warning(f"Error detecting crossover timing: {e}")
        return None


def analyze_scenario_result(scenario: DiagnosticScenario, output_dir: Path, catalog_path: Optional[Path] = None) -> DiagnosticResult:
    """
    Analyze results for a single diagnostic scenario.
    
    Args:
        scenario: Diagnostic scenario configuration
        output_dir: Path to backtest output directory
        catalog_path: Optional path to catalog for metadata loading
        
    Returns:
        DiagnosticResult with analysis findings
    """
    # Load backtest results
    results = load_backtest_results(output_dir)
    
    # Extract metrics
    actual_trades = len(results["orders"])
    actual_rejections = len(results["rejected_signals"])
    
    # Extract rejection reasons
    rejection_reasons = []
    if not results["rejected_signals"].empty and "reason" in results["rejected_signals"].columns:
        rejection_reasons = results["rejected_signals"]["reason"].tolist()
    
    # Extract performance metrics
    pnl = results["performance_stats"].get("total_pnl", 0.0)
    win_rate = results["performance_stats"].get("win_rate", 0.0)
    avg_trade_duration_bars = results["performance_stats"].get("avg_trade_duration_bars", 0.0)
    
    # Detect crossover timing
    crossover_timing_bars = detect_crossover_timing(results["orders"], scenario.expected_bar)
    crossover_detected = actual_trades > 0
    
    # Load metadata and perform crossover verification if available
    crossover_verifications = []
    expected_crossovers_count = 0
    detected_crossovers_count = 0
    missed_crossovers_count = 0
    false_positive_count = 0
    
    if catalog_path:
        metadata = load_metadata_for_scenario(catalog_path, scenario.symbol)
        if metadata and "expected_crossovers" in metadata:
            expected_crossovers = metadata["expected_crossovers"]
            expected_crossovers_count = len(expected_crossovers)
            
            # Get start date from metadata if available, otherwise use default
            start_date = metadata.get("start_date", "2024-01-01")
            
            # Get MA periods from metadata
            fast_period = metadata.get("fast_period", 10)
            slow_period = metadata.get("slow_period", 20)
            
            # Update scenario with actual slow_period for warmup analysis
            scenario.slow_period = slow_period
            
            # Compute MA values from catalog for buffer analysis
            ma_values = compute_ma_values_from_catalog(catalog_path, scenario.symbol, fast_period, slow_period)
            
            # Match orders to expected crossovers
            crossover_verifications = match_orders_to_expected_crossovers(
                results["orders"], expected_crossovers, start_date, tolerance_bars=1,
                rejected_signals_df=results["rejected_signals"],
                ma_values=ma_values,
                slow_period=slow_period
            )
            
            # Count verification results
            detected_crossovers_count = len([v for v in crossover_verifications if v.detected and v.expected_bar_index >= 0])
            missed_crossovers_count = len([v for v in crossover_verifications if not v.detected and v.expected_bar_index >= 0])
            false_positive_count = len([v for v in crossover_verifications if v.detected and v.expected_bar_index < 0])
    
    # Analyze issues
    issues_detected = []
    
    # Check crossover verification results if available
    if crossover_verifications:
        if missed_crossovers_count > 0:
            issues_detected.append(f"Missed crossovers: {missed_crossovers_count} expected crossovers not detected")
        if false_positive_count > 0:
            issues_detected.append(f"False positives: {false_positive_count} trades without expected crossover")
        
        # Check for timing errors
        timing_errors = [v for v in crossover_verifications if v.timing_error_bars and abs(v.timing_error_bars) > 1]
        if timing_errors:
            max_error = max(abs(v.timing_error_bars) for v in timing_errors)
            issues_detected.append(f"Timing errors: Crossovers detected up to {max_error} bars late/early")
    else:
        # Fall back to original trade count logic if no metadata
        if scenario.expected_trades == 0 and actual_trades > 0:
            issues_detected.append("False positive: Trades executed when none expected")
        elif scenario.expected_trades > 0 and actual_trades == 0:
            issues_detected.append("False negative: No trades when expected")
        elif scenario.expected_trades > 0:
            # Use tolerance ranges if available, otherwise exact equality
            if scenario.expected_min_trades is not None and scenario.expected_max_trades is not None:
                if actual_trades < scenario.expected_min_trades or actual_trades > scenario.expected_max_trades:
                    issues_detected.append(f"Trade count out of range: Expected {scenario.expected_min_trades}-{scenario.expected_max_trades}, got {actual_trades}")
            else:
                # Exact equality for deterministic scenarios
                if actual_trades != scenario.expected_trades:
                    issues_detected.append(f"Trade count mismatch: Expected {scenario.expected_trades}, got {actual_trades}")
    
    # Check rejection reasons
    if scenario.expected_rejection_reason and rejection_reasons:
        if not any(scenario.expected_rejection_reason.lower() in reason.lower() for reason in rejection_reasons):
            issues_detected.append(f"Unexpected rejection reason: Expected '{scenario.expected_rejection_reason}'")
    
    # Check timing issues (legacy)
    if crossover_timing_bars is not None and abs(crossover_timing_bars) > 2:
        issues_detected.append(f"Timing issue: Crossover detected {crossover_timing_bars} bars from expected")
    
    # Check performance issues
    if scenario.expected_outcome == "mixed" and pnl < -100:  # Excessive losses
        issues_detected.append("Performance issue: Excessive losses in diagnostic scenario")
    
    # Determine if scenario passed
    passed = len(issues_detected) == 0
    
    return DiagnosticResult(
        scenario=scenario,
        actual_trades=actual_trades,
        actual_rejections=actual_rejections,
        rejection_reasons=rejection_reasons,
        pnl=pnl,
        win_rate=win_rate,
        avg_trade_duration_bars=avg_trade_duration_bars,
        crossover_detected=crossover_detected,
        crossover_timing_bars=crossover_timing_bars,
        output_dir=output_dir,
        passed=passed,
        issues_detected=issues_detected,
        crossover_verifications=crossover_verifications,
        expected_crossovers_count=expected_crossovers_count,
        detected_crossovers_count=detected_crossovers_count,
        missed_crossovers_count=missed_crossovers_count,
        false_positive_count=false_positive_count
    )


def detect_issue_patterns(results: List[DiagnosticResult]) -> Dict[str, List[str]]:
    """
    Analyze all diagnostic results to identify systemic issues.
    
    Args:
        results: List of diagnostic results
        
    Returns:
        Dictionary mapping issue categories to detailed findings
    """
    patterns = {
        "False Positives": [],
        "False Negatives": [],
        "Timing Issues": [],
        "Filter Failures": [],
        "Threshold Sensitivity": [],
        "Performance Issues": []
    }
    
    for result in results:
        scenario_name = result.scenario.name
        
        # Categorize issues
        for issue in result.issues_detected:
            if "False positive" in issue:
                patterns["False Positives"].append(f"{scenario_name}: {issue}")
            elif "False negative" in issue:
                patterns["False Negatives"].append(f"{scenario_name}: {issue}")
            elif "Timing issue" in issue:
                patterns["Timing Issues"].append(f"{scenario_name}: {issue}")
            elif "rejection reason" in issue.lower():
                patterns["Filter Failures"].append(f"{scenario_name}: {issue}")
            elif "threshold" in issue.lower():
                patterns["Threshold Sensitivity"].append(f"{scenario_name}: {issue}")
            elif "Performance issue" in issue:
                patterns["Performance Issues"].append(f"{scenario_name}: {issue}")
    
    # Remove empty categories
    return {k: v for k, v in patterns.items() if v}


def detect_algorithm_issues(results: List[DiagnosticResult]) -> Dict[str, List[str]]:
    """
    Detect specific algorithm issues from crossover verifications.
    
    Args:
        results: List of diagnostic results
        
    Returns:
        Dictionary mapping issue type to list of affected scenarios
    """
    issues = {
        "Off-by-one errors": [],
        "Warmup issues": [],
        "MA calculation errors": [],
        "Incorrect crossover logic": []
    }
    
    for result in results:
        if not result.crossover_verifications:
            continue
            
        scenario_name = result.scenario.name
        
        # Check for off-by-one errors (consistent ±1 bar timing errors)
        timing_errors = [v.timing_error_bars for v in result.crossover_verifications 
                        if v.timing_error_bars is not None and v.expected_bar_index >= 0]
        if timing_errors and all(abs(e) == 1 for e in timing_errors):
            issues["Off-by-one errors"].append(f"{scenario_name}: Consistent ±1 bar timing errors")
        
        # Check for warmup issues (missed crossovers in first slow_period bars)
        slow_period = result.scenario.slow_period
        early_misses = [v for v in result.crossover_verifications 
                       if not v.detected and v.expected_bar_index < slow_period]
        if early_misses:
            issues["Warmup issues"].append(f"{scenario_name}: {len(early_misses)} crossovers missed in warmup period (first {slow_period} bars)")
        
        # Check for MA calculation errors (detected crossovers at wrong bars)
        large_timing_errors = [v for v in result.crossover_verifications 
                              if v.timing_error_bars and abs(v.timing_error_bars) > 2]
        if large_timing_errors:
            issues["MA calculation errors"].append(f"{scenario_name}: {len(large_timing_errors)} crossovers detected at wrong bars")
        
        # Check for systematic misses or false positives
        if result.missed_crossovers_count > 0 and result.detected_crossovers_count == 0:
            issues["Incorrect crossover logic"].append(f"{scenario_name}: All crossovers missed - possible logic error")
        elif result.false_positive_count > 0 and result.detected_crossovers_count == 0:
            issues["Incorrect crossover logic"].append(f"{scenario_name}: Only false positives detected - possible logic error")
    
    # Remove empty categories
    return {k: v for k, v in issues.items() if v}


def generate_improvement_suggestions(detected_issues: Dict[str, List[str]], results: List[DiagnosticResult]) -> List[Dict[str, str]]:
    """
    Map detected issues to actionable parameter recommendations.
    
    Args:
        detected_issues: Detected issue patterns
        results: List of diagnostic results
        
    Returns:
        List of improvement suggestions with rationale
    """
    suggestions = []
    
    # Detect algorithm issues from crossover verifications
    algorithm_issues = detect_algorithm_issues(results)
    
    # Add suggestions based on algorithm issues
    if "Off-by-one errors" in algorithm_issues:
        suggestions.append({
            "category": "Algorithm Issues",
            "suggestion": "Review crossover detection logic in on_bar() - check if using current or previous bar values",
            "rationale": "Consistent ±1 bar timing errors suggest off-by-one error in crossover detection",
            "priority": "high"
        })
    
    if "Warmup issues" in algorithm_issues:
        suggestions.append({
            "category": "Algorithm Issues",
            "suggestion": "Ensure strategy waits for slow_period bars before detecting crossovers",
            "rationale": "Crossovers missed in warmup period indicate insufficient initialization",
            "priority": "high"
        })
    
    if "MA calculation errors" in algorithm_issues:
        suggestions.append({
            "category": "Algorithm Issues",
            "suggestion": "Verify SMA calculation logic - compare against expected MA values from metadata",
            "rationale": "Crossovers detected at wrong bars suggest MA calculation errors",
            "priority": "high"
        })
    
    if "Incorrect crossover logic" in algorithm_issues:
        suggestions.append({
            "category": "Algorithm Issues",
            "suggestion": "Review MA history buffer implementation - ensure values are stored correctly",
            "rationale": "Systematic misses or false positives suggest buffer or comparison logic errors",
            "priority": "high"
        })
    
    # False positives in choppy market
    if "False Positives" in detected_issues:
        choppy_issues = [issue for issue in detected_issues["False Positives"] if "choppy" in issue.lower()]
        if choppy_issues:
            suggestions.append({
                "category": "False Positives",
                "suggestion": "Increase STRATEGY_CROSSOVER_THRESHOLD_PIPS from 1.0 to 2.0",
                "rationale": "Reduces false positives in choppy market scenario by requiring larger MA separation",
                "priority": "high"
            })
            suggestions.append({
                "category": "False Positives", 
                "suggestion": "Increase STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS from 2.0 to 3.0",
                "rationale": "Adds additional separation requirement to filter out small crossovers",
                "priority": "medium"
            })
    
    # Whipsaw losses
    whipsaw_results = [r for r in results if "whipsaw" in r.scenario.name.lower()]
    if whipsaw_results and any(r.pnl < -50 for r in whipsaw_results):
        suggestions.append({
            "category": "Performance Issues",
            "suggestion": "Enable STRATEGY_DMI_ENABLED=true for trend confirmation",
            "rationale": "Adds trend confirmation to reduce whipsaw trades",
            "priority": "high"
        })
        suggestions.append({
            "category": "Performance Issues",
            "suggestion": "Enable STRATEGY_STOCH_ENABLED=true with momentum confirmation",
            "rationale": "Adds momentum confirmation to filter out rapid reversals",
            "priority": "medium"
        })
    
    # Timing lag
    if "Timing Issues" in detected_issues:
        timing_issues = detected_issues["Timing Issues"]
        if any("lag" in issue.lower() for issue in timing_issues):
            suggestions.append({
                "category": "Timing Issues",
                "suggestion": "Consider reducing MA periods to 8/15 instead of 10/20",
                "rationale": "Reduces lag but increases noise sensitivity - trade-off decision",
                "priority": "medium"
            })
    
    # Threshold boundary failures
    if "Threshold Sensitivity" in detected_issues:
        threshold_issues = detected_issues["Threshold Sensitivity"]
        if threshold_issues:
            suggestions.append({
                "category": "Threshold Sensitivity",
                "suggestion": "Review code: Verify >= comparison in _check_crossover_threshold()",
                "rationale": "Ensure boundary condition logic is correct for exact threshold values",
                "priority": "high"
            })
    
    # Filter cascade failures
    if "Filter Failures" in detected_issues:
        filter_issues = detected_issues["Filter Failures"]
        if filter_issues:
            suggestions.append({
                "category": "Filter Failures",
                "suggestion": "Review filter order and rejection reason logging",
                "rationale": "Ensure filters are applied in correct sequence and reasons are accurate",
                "priority": "medium"
            })
    
    # False breakouts
    breakout_results = [r for r in results if "breakout" in r.scenario.name.lower()]
    if breakout_results and any(r.actual_trades > 0 for r in breakout_results):
        suggestions.append({
            "category": "False Positives",
            "suggestion": "Enable STRATEGY_ATR_ENABLED=true to detect abnormal volatility spikes",
            "rationale": "Filters out trades during false breakout scenarios",
            "priority": "medium"
        })
    
    # Sort by priority
    priority_order = {"high": 1, "medium": 2, "low": 3}
    suggestions.sort(key=lambda x: priority_order.get(x["priority"], 4))
    
    return suggestions


def calculate_performance_summary(results: List[DiagnosticResult]) -> Dict[str, Any]:
    """
    Aggregate metrics across all diagnostic scenarios.
    
    Args:
        results: List of diagnostic results
        
    Returns:
        Dictionary with summary statistics
    """
    if not results:
        return {}
    
    total_trades = sum(r.actual_trades for r in results)
    total_pnl = sum(r.pnl for r in results)
    avg_win_rate = np.mean([r.win_rate for r in results if r.win_rate > 0])
    
    # Most common rejection reasons
    all_rejection_reasons = []
    for result in results:
        all_rejection_reasons.extend(result.rejection_reasons)
    
    rejection_counter = Counter(all_rejection_reasons)
    most_common_rejections = dict(rejection_counter.most_common(5))
    
    # Average timing lag
    timing_lags = [r.crossover_timing_bars for r in results if r.crossover_timing_bars is not None]
    avg_timing_lag = np.mean(timing_lags) if timing_lags else 0
    
    return {
        "total_trades": total_trades,
        "total_pnl": total_pnl,
        "avg_win_rate": avg_win_rate,
        "most_common_rejections": most_common_rejections,
        "avg_timing_lag_bars": avg_timing_lag,
        "scenarios_with_trades": len([r for r in results if r.actual_trades > 0]),
        "scenarios_with_rejections": len([r for r in results if r.actual_rejections > 0])
    }


def analyze_diagnostic_results(scenarios: List[DiagnosticScenario], output_base_dir: Path, backtest_results: Optional[Dict[str, Path]] = None, catalog_path: Optional[Path] = None) -> MADiagnosticReport:
    """
    Orchestrate full analysis workflow.
    
    Args:
        scenarios: List of diagnostic scenarios
        output_base_dir: Base directory containing backtest outputs
        backtest_results: Optional dict mapping scenario names to output paths
        catalog_path: Optional path to catalog for metadata loading
        
    Returns:
        MADiagnosticReport with all findings
    """
    logging.info("Starting diagnostic results analysis...")
    
    results = []
    
    # Analyze each scenario
    for scenario in scenarios:
        logging.info(f"Analyzing scenario: {scenario.name}")
        
        # Use provided path if available, otherwise discover
        if backtest_results and scenario.name in backtest_results:
            output_dir = backtest_results[scenario.name]
        else:
            # Find corresponding output directory
            scenario_dir = output_base_dir / scenario.name
            if scenario_dir.exists():
                # List subdirs and select most recent
                subdirs = [d for d in scenario_dir.iterdir() if d.is_dir()]
                if subdirs:
                    latest = max(subdirs, key=lambda x: x.stat().st_mtime)
                    output_dir = latest
                else:
                    # Files written directly to scenario directory
                    output_dir = scenario_dir
            else:
                logging.warning(f"No output directory found for scenario {scenario.name}")
                continue
        
        # Analyze scenario result
        result = analyze_scenario_result(scenario, output_dir, catalog_path)
        results.append(result)
        
        logging.info(f"Scenario {scenario.name}: {'PASSED' if result.passed else 'FAILED'}")
    
    # Detect issue patterns
    detected_issues = detect_issue_patterns(results)
    
    # Generate suggestions
    suggestions = generate_improvement_suggestions(detected_issues, results)
    
    # Calculate performance summary
    performance_summary = calculate_performance_summary(results)
    
    # Count passed/failed scenarios
    scenarios_passed = len([r for r in results if r.passed])
    scenarios_failed = len(results) - scenarios_passed
    
    # Create report
    from datetime import datetime
    report = MADiagnosticReport(
        scenarios_tested=len(results),
        scenarios_passed=scenarios_passed,
        scenarios_failed=scenarios_failed,
        results=results,
        detected_issues=detected_issues,
        performance_summary=performance_summary,
        suggestions=suggestions,
        timestamp=datetime.now().isoformat()
    )
    
    logging.info(f"Analysis complete: {scenarios_passed}/{len(results)} scenarios passed")
    
    return report


def export_report_json(report: MADiagnosticReport, output_path: Path) -> None:
    """
    Convert MADiagnosticReport to JSON-serializable dict and write to file.
    
    Args:
        report: Diagnostic report to export
        output_path: Path to write JSON file
    """
    try:
        # Convert to dict
        report_dict = {
            "scenarios_tested": report.scenarios_tested,
            "scenarios_passed": report.scenarios_passed,
            "scenarios_failed": report.scenarios_failed,
            "timestamp": report.timestamp,
            "detected_issues": report.detected_issues,
            "performance_summary": report.performance_summary,
            "suggestions": report.suggestions,
            "scenario_results": []
        }
        
        # Add scenario results
        for result in report.results:
            result_dict = {
                "scenario_name": result.scenario.name,
                "symbol": result.scenario.symbol,
                "expected_trades": result.scenario.expected_trades,
                "actual_trades": result.actual_trades,
                "actual_rejections": result.actual_rejections,
                "pnl": result.pnl,
                "win_rate": result.win_rate,
                "crossover_detected": result.crossover_detected,
                "crossover_timing_bars": result.crossover_timing_bars,
                "passed": result.passed,
                "issues_detected": result.issues_detected,
                "rejection_reasons": result.rejection_reasons,
                "expected_crossovers_count": result.expected_crossovers_count,
                "detected_crossovers_count": result.detected_crossovers_count,
                "missed_crossovers_count": result.missed_crossovers_count,
                "false_positive_count": result.false_positive_count,
                "crossover_verifications": [
                    {
                        "expected_bar_index": v.expected_bar_index,
                        "expected_timestamp": v.expected_timestamp,
                        "expected_type": v.expected_type,
                        "expected_fast_ma": v.expected_fast_ma,
                        "expected_slow_ma": v.expected_slow_ma,
                        "detected": v.detected,
                        "actual_bar_index": v.actual_bar_index,
                        "actual_timestamp": v.actual_timestamp,
                        "timing_error_bars": v.timing_error_bars,
                        "issue": v.issue
                    } for v in result.crossover_verifications
                ]
            }
            report_dict["scenario_results"].append(result_dict)
        
        # Write to file
        with open(output_path, 'w') as f:
            json.dump(report_dict, f, indent=2)
        
        logging.info(f"JSON report exported to {output_path}")
        
    except Exception as e:
        logging.error(f"Error exporting JSON report: {e}")


# Diagnostic scenarios configuration
DIAGNOSTIC_SCENARIOS_CONFIG = [
    DiagnosticScenario(
        name="choppy_market",
        symbol="DIAG-CHOPPY/USD",
        expected_trades=10,
        expected_outcome="mixed",
        purpose="Test behavior in ranging market with frequent small crossovers",
        issue_indicators=["excessive_trades", "poor_performance"]
    ),
    DiagnosticScenario(
        name="whipsaw_pattern",
        symbol="DIAG-WHIPSAW/USD",
        expected_trades=2,
        expected_outcome="mixed",
        purpose="Test handling of immediate signal reversals",
        issue_indicators=["rapid_reversals", "losing_trades"]
    ),
    DiagnosticScenario(
        name="threshold_boundary",
        symbol="DIAG-THRESH-EXACT/USD",
        expected_trades=1,
        expected_outcome="pass",
        purpose="Test boundary condition handling for crossover threshold",
        issue_indicators=["boundary_failure", "off_by_one"]
    ),
    DiagnosticScenario(
        name="delayed_crossover",
        symbol="DIAG-DELAYED/USD",
        expected_trades=1,
        expected_outcome="pass",
        purpose="Test crossover detection timing with slow MA convergence",
        issue_indicators=["timing_issues", "delayed_detection"]
    ),
    DiagnosticScenario(
        name="false_breakout",
        symbol="DIAG-BREAKOUT/USD",
        expected_trades=0,
        expected_outcome="reject",
        purpose="Test resilience to price spikes causing temporary crossovers",
        issue_indicators=["false_breakout_trades", "filter_failure"]
    ),
    DiagnosticScenario(
        name="no_trade_zone",
        symbol="DIAG-NOTRADE/USD",
        expected_trades=0,
        expected_outcome="reject",
        purpose="Test that strategy doesn't generate false signals when MAs are close but not crossing",
        issue_indicators=["false_positives", "near_crossover_signals"]
    ),
    DiagnosticScenario(
        name="filter_cascade_failure",
        symbol="DIAG-CASCADE/USD",
        expected_trades=0,
        expected_outcome="reject",
        expected_rejection_reason="dmi",
        purpose="Test filter cascade logic and rejection reason accuracy",
        issue_indicators=["filter_order_issues", "incorrect_rejection_reasons"]
    ),
    DiagnosticScenario(
        name="ma_lag_test",
        symbol="DIAG-LAG/USD",
        expected_trades=1,
        expected_outcome="pass",
        purpose="Quantify inherent MA lag in trending markets",
        issue_indicators=["excessive_lag", "delayed_crossover"]
    )
]

# Issue severity mapping
ISSUE_SEVERITY_MAP = {
    "False Positives": "high",
    "False Negatives": "high", 
    "Timing Issues": "medium",
    "Filter Failures": "medium",
    "Threshold Sensitivity": "high",
    "Performance Issues": "medium"
}
