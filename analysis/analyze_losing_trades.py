"""
Losing Trades Analysis Tool

This module provides comprehensive analysis of losing trades from backtest results,
categorizing losses by exit reason and generating actionable parameter adjustment suggestions.

The analyzer loads backtest output files (positions.csv, orders.csv, fills.csv, 
performance_stats.json) and categorizes losing trades into:
- Stopped Out (SL Hit): Losses where stop loss order was filled
- Reversed Before TP: Losses where position was closed by reversal signal
- Trend Exhaustion: Long-duration losses with small magnitude
- False Breakout: Short-duration losses with SL hit
- Choppy Market: Consecutive losses in short timeframes

Output formats:
- Console: Formatted text report with statistics and suggestions
- HTML: Comprehensive report with embedded charts and visualizations
- JSON: Structured data export for further analysis

Usage:
    python analyze_losing_trades.py --input results_dir [--output report.html] [--json] [--verbose]

Exit codes:
    0: Success
    1: Error (invalid input, file not found, etc.)
"""

import argparse
import json
import logging
import sys
import re
import base64
import io
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Module-level constants for categorization thresholds
FALSE_BREAKOUT_DURATION_SECONDS = 300  # 5 minutes
TREND_EXHAUSTION_DURATION_SECONDS = 3600  # 1 hour
CHOPPY_MARKET_SEQUENCE_DURATION_SECONDS = 7200  # 2 hours
CHOPPY_MARKET_MIN_SEQUENCE_LENGTH = 3  # minimum consecutive losses for choppy market


@dataclass
class LossTrade:
    """Represents a single losing trade with categorization and metadata."""
    position_id: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    duration_seconds: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    side: str  # LONG or SHORT
    loss_category: str  # stopped_out, reversed_before_tp, trend_exhaustion, false_breakout, choppy_market, unknown
    closing_order_type: str  # STOP_MARKET, LIMIT, MARKET
    closing_order_tags: str


@dataclass
class LossCategoryStats:
    """Statistics for each loss category."""
    category_name: str
    count: int
    total_loss: float
    avg_loss: float
    avg_duration_seconds: float
    percentage_of_total_losses: float


@dataclass
class LossAnalysisReport:
    """Complete analysis report with all findings and suggestions."""
    backtest_run_id: str
    total_positions: int
    losing_positions: int
    winning_positions: int
    win_rate: float
    total_loss: float
    avg_loss: float
    loss_trades: List[LossTrade]
    category_stats: List[LossCategoryStats]
    parameter_suggestions: List[str]
    patterns_detected: Dict[str, Any]


def load_positions(results_dir: Path) -> pd.DataFrame:
    """Load positions data from backtest results."""
    try:
        positions_path = results_dir / "positions.csv"
        if not positions_path.exists():
            raise FileNotFoundError(f"Positions file not found: {positions_path}")
        
        df = pd.read_csv(positions_path)
        
        # Parse timestamp columns
        if 'ts_opened' in df.columns:
            df['ts_opened'] = pd.to_datetime(df['ts_opened'])
        if 'ts_closed' in df.columns:
            df['ts_closed'] = pd.to_datetime(df['ts_closed'])
        
        # Filter for closed positions only
        df = df[df['ts_closed'].notna()].copy()
        
        logger.info(f"Loaded {len(df)} closed positions from {positions_path}")
        return df
        
    except Exception as e:
        logger.error(f"Error loading positions: {e}")
        raise


def load_orders(results_dir: Path) -> pd.DataFrame:
    """Load orders data from backtest results."""
    try:
        orders_path = results_dir / "orders.csv"
        if not orders_path.exists():
            raise FileNotFoundError(f"Orders file not found: {orders_path}")
        
        df = pd.read_csv(orders_path)
        
        # Parse timestamp columns
        if 'ts_init' in df.columns:
            df['ts_init'] = pd.to_datetime(df['ts_init'])
        if 'ts_last' in df.columns:
            df['ts_last'] = pd.to_datetime(df['ts_last'])
        
        # Defensive column normalization for sides
        if 'side' not in df.columns and 'order_side' in df.columns:
            df['side'] = df['order_side']
            logger.info("Normalized 'order_side' to 'side' column")
        
        logger.info(f"Loaded {len(df)} orders from {orders_path}")
        return df
        
    except Exception as e:
        logger.error(f"Error loading orders: {e}")
        raise




def load_performance_stats(results_dir: Path) -> Dict[str, Any]:
    """Load performance statistics from backtest results."""
    try:
        stats_path = results_dir / "performance_stats.json"
        if not stats_path.exists():
            raise FileNotFoundError(f"Performance stats file not found: {stats_path}")
        
        with open(stats_path, 'r') as f:
            stats = json.load(f)
        
        logger.info(f"Loaded performance stats from {stats_path}")
        return stats
        
    except Exception as e:
        logger.error(f"Error loading performance stats: {e}")
        raise


def categorize_loss(position_row: pd.Series, orders_df: pd.DataFrame, loss_trades: List[LossTrade] = None) -> str:
    """Categorize a losing trade based on its closing order and heuristics."""
    try:
        closing_order_id = position_row.get('closing_order_id')
        if pd.isna(closing_order_id):
            return "unknown"
        
        # Find the closing order
        closing_order = orders_df[orders_df['venue_order_id'] == closing_order_id]
        if closing_order.empty:
            return "unknown"
        
        closing_order = closing_order.iloc[0]
        tags = str(closing_order.get('tags', ''))
        order_type = str(closing_order.get('type', ''))
        status = str(closing_order.get('status', ''))
        
        # Check for stop loss hit using regex with boundaries
        if re.search(r'(?:^|,|\s)MA_CROSS_SL(?:$|,|\s)', tags) and status == 'FILLED':
            return "stopped_out"
        
        # Check for take profit hit (shouldn't be a loss, but handle edge case)
        if re.search(r'(?:^|,|\s)MA_CROSS_TP(?:$|,|\s)', tags) and status == 'FILLED':
            return "take_profit_hit"
        
        # Check for reversal (entry order for opposite direction) using regex with boundaries
        # Match MA_CROSS but explicitly exclude _SL and _TP via negative match
        if (re.search(r'(?:^|,|\s)MA_CROSS(?:$|,|\s)', tags) and 
            not re.search(r'(?:^|,|\s)MA_CROSS_SL(?:$|,|\s)', tags) and 
            not re.search(r'(?:^|,|\s)MA_CROSS_TP(?:$|,|\s)', tags)):
            return "reversed_before_tp"
        
        # Apply heuristics for uncategorized losses
        duration_seconds = position_row.get('duration_ns', 0) / 1_000_000_000  # Convert ns to seconds
        realized_pnl = position_row.get('realized_pnl', 0)
        
        # False breakout: very short duration with SL hit
        if duration_seconds < FALSE_BREAKOUT_DURATION_SECONDS and re.search(r'(?:^|,|\s)MA_CROSS_SL(?:$|,|\s)', tags):
            return "false_breakout"
        
        # Trend exhaustion: long duration with small loss (use relative threshold if available)
        if duration_seconds > TREND_EXHAUSTION_DURATION_SECONDS:
            # Use relative threshold based on distribution of losses if available
            if loss_trades and len(loss_trades) > 0:
                loss_magnitudes = [abs(trade.realized_pnl) for trade in loss_trades]
                median_loss = np.median(loss_magnitudes)
                # Consider small loss as less than 50% of median loss
                if abs(realized_pnl) < median_loss * 0.5:
                    return "trend_exhaustion"
            else:
                # Fallback to absolute threshold
                if abs(realized_pnl) < 50:
                    return "trend_exhaustion"
        
        return "unknown"
        
    except Exception as e:
        logger.warning(f"Error categorizing loss for position {position_row.get('position_id', 'unknown')}: {e}")
        return "unknown"


def detect_consecutive_loss_sequences(loss_trades: List[LossTrade]) -> List[List[LossTrade]]:
    """Detect sequences of consecutive losses for choppy market identification."""
    if not loss_trades:
        return []
    
    # Sort by entry time
    sorted_trades = sorted(loss_trades, key=lambda x: x.entry_time)
    
    sequences = []
    current_sequence = [sorted_trades[0]]
    
    for i in range(1, len(sorted_trades)):
        time_diff = (sorted_trades[i].entry_time - sorted_trades[i-1].entry_time).total_seconds()
        
        # If trades are within the choppy market sequence duration, add to current sequence
        if time_diff < CHOPPY_MARKET_SEQUENCE_DURATION_SECONDS:
            current_sequence.append(sorted_trades[i])
        else:
            # End current sequence if it has the minimum required losses
            if len(current_sequence) >= CHOPPY_MARKET_MIN_SEQUENCE_LENGTH:
                sequences.append(current_sequence)
            current_sequence = [sorted_trades[i]]
    
    # Don't forget the last sequence
    if len(current_sequence) >= CHOPPY_MARKET_MIN_SEQUENCE_LENGTH:
        sequences.append(current_sequence)
    
    return sequences


def enrich_loss_trades(positions_df: pd.DataFrame, orders_df: pd.DataFrame) -> List[LossTrade]:
    """Enrich losing positions with categorization and metadata."""
    loss_trades = []
    
    # Filter for losing trades
    losing_positions = positions_df[positions_df['realized_pnl'] < 0].copy()
    
    logger.info(f"Found {len(losing_positions)} losing positions to analyze")
    
    for _, position in losing_positions.iterrows():
        try:
            # Extract basic information with defensive column validation
            position_id = str(position.get('position_id', ''))
            entry_time = position.get('ts_opened')
            exit_time = position.get('ts_closed')
            duration_ns = position.get('duration_ns', 0)
            duration_seconds = duration_ns / 1_000_000_000 if duration_ns > 0 else 0
            
            # Validate required columns and default gracefully
            entry_price = position.get('avg_px_open')
            if pd.isna(entry_price):
                logger.warning(f"Missing avg_px_open for position {position_id}")
                entry_price = 0.0
            else:
                entry_price = float(entry_price)
            
            exit_price = position.get('avg_px_close')
            if pd.isna(exit_price):
                logger.warning(f"Missing avg_px_close for position {position_id}")
                exit_price = 0.0
            else:
                exit_price = float(exit_price)
            
            realized_pnl = position.get('realized_pnl')
            if pd.isna(realized_pnl):
                logger.warning(f"Missing realized_pnl for position {position_id}")
                realized_pnl = 0.0
            else:
                realized_pnl = float(realized_pnl)
            
            side = str(position.get('side', 'UNKNOWN'))
            
            # Categorize the loss (will be updated with relative thresholds after all trades are collected)
            loss_category = categorize_loss(position, orders_df)
            
            # Get closing order details with defensive ID resolution
            closing_order_id = position.get('closing_order_id')
            closing_order_type = "UNKNOWN"
            closing_order_tags = ""
            
            if not pd.isna(closing_order_id):
                # Try both venue_order_id and order_id columns
                closing_order = orders_df[orders_df['venue_order_id'] == closing_order_id]
                if closing_order.empty and 'order_id' in orders_df.columns:
                    closing_order = orders_df[orders_df['order_id'] == closing_order_id]
                
                if not closing_order.empty:
                    closing_order_type = str(closing_order.iloc[0].get('type', 'UNKNOWN'))
                    closing_order_tags = str(closing_order.iloc[0].get('tags', ''))
            
            # Create LossTrade object
            loss_trade = LossTrade(
                position_id=position_id,
                entry_time=entry_time,
                exit_time=exit_time,
                duration_seconds=duration_seconds,
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                side=side,
                loss_category=loss_category,
                closing_order_type=closing_order_type,
                closing_order_tags=closing_order_tags
            )
            
            loss_trades.append(loss_trade)
            
        except Exception as e:
            logger.warning(f"Error processing position {position.get('position_id', 'unknown')}: {e}")
            continue
    
    # Second pass: recategorize with relative thresholds now that we have all loss trades
    for trade in loss_trades:
        # Find the corresponding position row for recategorization
        position_row = positions_df[positions_df['position_id'] == trade.position_id]
        if not position_row.empty:
            # Recategorize with relative thresholds
            new_category = categorize_loss(position_row.iloc[0], orders_df, loss_trades)
            trade.loss_category = new_category
    
    # Post-process to identify choppy market sequences
    consecutive_sequences = detect_consecutive_loss_sequences(loss_trades)
    for sequence in consecutive_sequences:
        for trade in sequence:
            # Re-label trades in qualifying sequences as choppy_market
            trade.loss_category = "choppy_market"
    
    return loss_trades


def detect_patterns(loss_trades: List[LossTrade], performance_stats: Dict[str, Any]) -> Dict[str, Any]:
    """Detect patterns in losing trades."""
    patterns = {
        'time_of_day': {},
        'duration_patterns': {},
        'consecutive_losses': [],
        'side_bias': {},
        'loss_magnitude': {},
        'entry_vs_bar_range': None,
        'volatility_at_entry': None,
        'dmi_at_entry': None,
        'stoch_at_entry': None
    }
    
    if not loss_trades:
        return patterns
    
    # Time-of-day pattern
    hour_counts = {}
    for trade in loss_trades:
        hour = trade.entry_time.hour
        hour_counts[hour] = hour_counts.get(hour, 0) + 1
    
    patterns['time_of_day'] = dict(sorted(hour_counts.items(), key=lambda x: x[1], reverse=True))
    
    # Duration patterns by category
    category_durations = {}
    for trade in loss_trades:
        category = trade.loss_category
        if category not in category_durations:
            category_durations[category] = []
        category_durations[category].append(trade.duration_seconds)
    
    for category, durations in category_durations.items():
        if durations:
            patterns['duration_patterns'][category] = {
                'min': min(durations),
                'max': max(durations),
                'avg': np.mean(durations),
                'median': np.median(durations)
            }
    
    # Consecutive losses
    consecutive_sequences = detect_consecutive_loss_sequences(loss_trades)
    patterns['consecutive_losses'] = [len(seq) for seq in consecutive_sequences]
    
    # Side bias
    side_counts = {}
    for trade in loss_trades:
        side = trade.side
        side_counts[side] = side_counts.get(side, 0) + 1
    
    patterns['side_bias'] = side_counts
    
    # Loss magnitude analysis
    pnl_values = [abs(trade.realized_pnl) for trade in loss_trades]
    if pnl_values:
        patterns['loss_magnitude'] = {
            'min': min(pnl_values),
            'max': max(pnl_values),
            'avg': np.mean(pnl_values),
            'median': np.median(pnl_values)
        }
    
    # Bar/indicator pattern extractions (currently unavailable)
    # Note: These fields are set to None as bar/indicator data are not currently available
    # They can be populated when bar data is loaded at entry timestamps
    patterns['entry_vs_bar_range'] = None
    patterns['volatility_at_entry'] = None
    patterns['dmi_at_entry'] = None
    patterns['stoch_at_entry'] = None
    
    return patterns


def generate_parameter_suggestions(category_stats: List[LossCategoryStats], patterns: Dict[str, Any], performance_stats: Dict[str, Any]) -> List[str]:
    """Generate actionable parameter adjustment suggestions."""
    suggestions = []
    
    if not category_stats:
        return suggestions
    
    # Calculate percentages
    total_losses = sum(stat.count for stat in category_stats)
    if total_losses == 0:
        return suggestions
    
    # Find dominant loss categories
    stopped_out_pct = next((stat.percentage_of_total_losses for stat in category_stats if stat.category_name == "stopped_out"), 0)
    false_breakout_pct = next((stat.percentage_of_total_losses for stat in category_stats if stat.category_name == "false_breakout"), 0)
    reversed_before_tp_pct = next((stat.percentage_of_total_losses for stat in category_stats if stat.category_name == "reversed_before_tp"), 0)
    trend_exhaustion_pct = next((stat.percentage_of_total_losses for stat in category_stats if stat.category_name == "trend_exhaustion"), 0)
    
    # Generate suggestions based on loss patterns
    if stopped_out_pct > 0.4:
        suggestions.append(f"High stop-loss hit rate ({stopped_out_pct:.1f}%): Consider increasing stop_loss_pips to give trades more room")
    
    if false_breakout_pct > 0.3:
        suggestions.append(f"High false breakout rate ({false_breakout_pct:.1f}%): Consider increasing crossover_threshold_pips to filter weak signals")
    
    if reversed_before_tp_pct > 0.3:
        suggestions.append(f"High reversal rate ({reversed_before_tp_pct:.1f}%): Consider decreasing take_profit_pips or adjusting risk/reward ratio")
    
    if trend_exhaustion_pct > 0.2:
        suggestions.append(f"High trend exhaustion rate ({trend_exhaustion_pct:.1f}%): Consider tightening DMI/Stochastic filters to avoid weak trends")
    
    # Check for consecutive losses (choppy market)
    consecutive_losses = patterns.get('consecutive_losses', [])
    if consecutive_losses and max(consecutive_losses) >= 5:
        suggestions.append("Detected choppy market conditions: Consider adding time-of-day filter or ADX trend strength filter")
    
    # Time-of-day pattern suggestions
    time_patterns = patterns.get('time_of_day', {})
    if time_patterns:
        peak_hour = max(time_patterns.items(), key=lambda x: x[1])
        if peak_hour[1] > total_losses * 0.2:  # More than 20% of losses in one hour
            suggestions.append(f"High loss concentration at hour {peak_hour[0]}: Consider excluding trading during {peak_hour[0]}:00-{peak_hour[0]+1}:00")
    
    # Side bias suggestions
    side_bias = patterns.get('side_bias', {})
    if len(side_bias) == 2:
        sides = list(side_bias.items())
        if abs(sides[0][1] - sides[1][1]) > total_losses * 0.2:  # More than 20% difference
            dominant_side = max(sides, key=lambda x: x[1])
            suggestions.append(f"Side bias detected: {dominant_side[0]} trades have higher loss rate - Consider reviewing entry logic for {dominant_side[0]} trades")
    
    return suggestions


def analyze_losing_trades(results_dir: Path) -> LossAnalysisReport:
    """Main analysis function that orchestrates the entire losing trades analysis."""
    logger.info(f"Starting losing trades analysis for {results_dir}")
    
    # Load all data
    positions_df = load_positions(results_dir)
    orders_df = load_orders(results_dir)
    performance_stats = load_performance_stats(results_dir)
    
    # Enrich loss trades
    loss_trades = enrich_loss_trades(positions_df, orders_df)
    
    # Calculate overall statistics
    total_positions = len(positions_df)
    losing_positions = len(loss_trades)
    winning_positions = total_positions - losing_positions
    win_rate = winning_positions / total_positions if total_positions > 0 else 0
    
    total_loss = sum(trade.realized_pnl for trade in loss_trades)
    avg_loss = total_loss / len(loss_trades) if loss_trades else 0
    
    # Calculate category statistics
    category_stats = []
    category_counts = {}
    category_totals = {}
    category_durations = {}
    
    for trade in loss_trades:
        category = trade.loss_category
        category_counts[category] = category_counts.get(category, 0) + 1
        category_totals[category] = category_totals.get(category, 0) + trade.realized_pnl
        if category not in category_durations:
            category_durations[category] = []
        category_durations[category].append(trade.duration_seconds)
    
    for category, count in category_counts.items():
        total_loss_cat = category_totals[category]
        avg_loss_cat = total_loss_cat / count
        avg_duration = np.mean(category_durations[category]) if category_durations[category] else 0
        percentage = (count / len(loss_trades)) * 100 if loss_trades else 0
        
        category_stats.append(LossCategoryStats(
            category_name=category,
            count=count,
            total_loss=total_loss_cat,
            avg_loss=avg_loss_cat,
            avg_duration_seconds=avg_duration,
            percentage_of_total_losses=percentage
        ))
    
    # Detect patterns
    patterns = detect_patterns(loss_trades, performance_stats)
    
    # Generate parameter suggestions
    suggestions = generate_parameter_suggestions(category_stats, patterns, performance_stats)
    
    # Extract backtest run ID from directory name or use default
    backtest_run_id = results_dir.name
    
    # Create report
    report = LossAnalysisReport(
        backtest_run_id=backtest_run_id,
        total_positions=total_positions,
        losing_positions=losing_positions,
        winning_positions=winning_positions,
        win_rate=win_rate,
        total_loss=total_loss,
        avg_loss=avg_loss,
        loss_trades=loss_trades,
        category_stats=category_stats,
        parameter_suggestions=suggestions,
        patterns_detected=patterns
    )
    
    logger.info(f"Analysis complete: {losing_positions} losing trades analyzed across {len(category_stats)} categories")
    return report


def create_loss_category_pie_chart(category_stats: List[LossCategoryStats]) -> str:
    """Create pie chart showing loss category distribution."""
    try:
        plt.figure(figsize=(10, 8))
        
        categories = [stat.category_name for stat in category_stats]
        counts = [stat.count for stat in category_stats]
        
        colors = sns.color_palette("Set3", len(categories))
        wedges, texts, autotexts = plt.pie(counts, labels=categories, autopct='%1.1f%%', 
                                          colors=colors, startangle=90)
        
        plt.title('Loss Category Distribution', fontsize=16, fontweight='bold')
        
        # Convert to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
        
    except Exception as e:
        logger.error(f"Error creating pie chart: {e}")
        return ""


def create_loss_count_bar_chart(category_stats: List[LossCategoryStats]) -> str:
    """Create bar chart showing loss count by category."""
    try:
        plt.figure(figsize=(12, 8))
        
        # Sort by count descending
        sorted_stats = sorted(category_stats, key=lambda x: x.count, reverse=True)
        categories = [stat.category_name for stat in sorted_stats]
        counts = [stat.count for stat in sorted_stats]
        
        bars = plt.bar(categories, counts, color=sns.color_palette("viridis", len(categories)))
        plt.title('Loss Count by Category', fontsize=16, fontweight='bold')
        plt.xlabel('Loss Category')
        plt.ylabel('Number of Losses')
        plt.xticks(rotation=45, ha='right')
        
        # Add value labels on bars
        for bar, count in zip(bars, counts):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                    str(count), ha='center', va='bottom')
        
        plt.tight_layout()
        
        # Convert to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
        
    except Exception as e:
        logger.error(f"Error creating bar chart: {e}")
        return ""


def create_duration_histogram(loss_trades: List[LossTrade]) -> str:
    """Create histogram of time-in-trade distribution."""
    try:
        plt.figure(figsize=(12, 8))
        
        durations = [trade.duration_seconds for trade in loss_trades]
        
        # Define bins for duration categories
        bins = [0, 300, 900, 1800, 3600, 7200, 14400, float('inf')]  # 5min, 15min, 30min, 1hr, 2hr, 4hr, 4hr+
        labels = ['0-5min', '5-15min', '15-30min', '30-60min', '1-2hr', '2-4hr', '4hr+']
        
        # Create histogram
        counts, bin_edges, patches = plt.hist(durations, bins=bins, alpha=0.7, color='skyblue', edgecolor='black')
        
        plt.title('Time-in-Trade Distribution', fontsize=16, fontweight='bold')
        plt.xlabel('Duration')
        plt.ylabel('Number of Trades')
        plt.xticks(bin_edges[:-1], labels, rotation=45, ha='right')
        
        # Add count labels on bars
        for i, (count, patch) in enumerate(zip(counts, patches)):
            if count > 0:
                plt.text(patch.get_x() + patch.get_width()/2, patch.get_height() + 0.1, 
                        str(int(count)), ha='center', va='bottom')
        
        plt.tight_layout()
        
        # Convert to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
        
    except Exception as e:
        logger.error(f"Error creating duration histogram: {e}")
        return ""


def create_avg_loss_by_category_chart(category_stats: List[LossCategoryStats]) -> str:
    """Create bar chart showing average loss by category."""
    try:
        plt.figure(figsize=(12, 8))
        
        # Sort by average loss descending
        sorted_stats = sorted(category_stats, key=lambda x: abs(x.avg_loss), reverse=True)
        categories = [stat.category_name for stat in sorted_stats]
        avg_losses = [abs(stat.avg_loss) for stat in sorted_stats]  # Use absolute values for display
        
        bars = plt.bar(categories, avg_losses, color=sns.color_palette("Reds", len(categories)))
        plt.title('Average Loss by Category', fontsize=16, fontweight='bold')
        plt.xlabel('Loss Category')
        plt.ylabel('Average Loss (absolute value)')
        plt.xticks(rotation=45, ha='right')
        
        # Add value labels on bars
        for bar, loss in zip(bars, avg_losses):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                    f'{loss:.1f}', ha='center', va='bottom')
        
        plt.tight_layout()
        
        # Convert to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
        
    except Exception as e:
        logger.error(f"Error creating avg loss chart: {e}")
        return ""


def generate_console_report(report: LossAnalysisReport) -> None:
    """Generate formatted console report."""
    print("\n" + "="*80)
    print(f"LOSING TRADES ANALYSIS REPORT - {report.backtest_run_id}")
    print("="*80)
    
    # Overall statistics
    print(f"\nOVERALL STATISTICS:")
    print(f"  Total Positions: {report.total_positions}")
    print(f"  Winning Positions: {report.winning_positions}")
    print(f"  Losing Positions: {report.losing_positions}")
    print(f"  Win Rate: {report.win_rate:.1%}")
    print(f"  Total Loss: ${report.total_loss:.2f}")
    print(f"  Average Loss: ${report.avg_loss:.2f}")
    
    # Loss category breakdown
    print(f"\nLOSS CATEGORY BREAKDOWN:")
    print(f"{'Category':<20} {'Count':<8} {'Total Loss':<12} {'Avg Loss':<12} {'% of Losses':<12}")
    print("-" * 70)
    
    for stat in sorted(report.category_stats, key=lambda x: x.count, reverse=True):
        print(f"{stat.category_name:<20} {stat.count:<8} ${stat.total_loss:<11.2f} ${stat.avg_loss:<11.2f} {stat.percentage_of_total_losses:<11.1f}%")
    
    # Patterns detected
    print(f"\nPATTERNS DETECTED:")
    patterns = report.patterns_detected
    
    if patterns.get('time_of_day'):
        peak_hour = max(patterns['time_of_day'].items(), key=lambda x: x[1])
        print(f"  Peak Loss Hour: {peak_hour[0]}:00 ({peak_hour[1]} losses)")
    
    if patterns.get('consecutive_losses'):
        max_consecutive = max(patterns['consecutive_losses']) if patterns['consecutive_losses'] else 0
        print(f"  Max Consecutive Losses: {max_consecutive}")
    
    if patterns.get('side_bias'):
        for side, count in patterns['side_bias'].items():
            print(f"  {side} Losses: {count}")
    
    # Parameter suggestions
    if report.parameter_suggestions:
        print(f"\nPARAMETER ADJUSTMENT SUGGESTIONS:")
        for i, suggestion in enumerate(report.parameter_suggestions, 1):
            print(f"  {i}. {suggestion}")
    else:
        print(f"\nNo specific parameter adjustments suggested based on current loss patterns.")
    
    print("\n" + "="*80)


def generate_json_report(report: LossAnalysisReport, output_path: Path) -> None:
    """Generate JSON report."""
    try:
        # Convert report to dictionary
        report_dict = {
            'backtest_run_id': report.backtest_run_id,
            'overall_stats': {
                'total_positions': report.total_positions,
                'win_rate': report.win_rate,
                'total_loss': report.total_loss,
                'avg_loss': report.avg_loss
            },
            'loss_categories': [
                {
                    'category': stat.category_name,
                    'count': stat.count,
                    'total_loss': stat.total_loss,
                    'avg_loss': stat.avg_loss,
                    'percentage': stat.percentage_of_total_losses
                }
                for stat in report.category_stats
            ],
            'loss_trades': [
                {
                    'position_id': trade.position_id,
                    'entry_time': trade.entry_time.isoformat(),
                    'exit_time': trade.exit_time.isoformat(),
                    'duration_seconds': trade.duration_seconds,
                    'realized_pnl': trade.realized_pnl,
                    'category': trade.loss_category,
                    'side': trade.side
                }
                for trade in report.loss_trades
            ],
            'patterns_detected': report.patterns_detected,
            'parameter_suggestions': report.parameter_suggestions
        }
        
        with open(output_path, 'w') as f:
            json.dump(report_dict, f, indent=2, default=str)
        
        logger.info(f"JSON report saved to {output_path}")
        
    except Exception as e:
        logger.error(f"Error generating JSON report: {e}")
        raise


def generate_html_report(report: LossAnalysisReport, output_path: Path, category_stats: List[LossCategoryStats]) -> None:
    """Generate comprehensive HTML report with embedded charts."""
    try:
        # Generate charts
        pie_chart = create_loss_category_pie_chart(category_stats)
        bar_chart = create_loss_count_bar_chart(category_stats)
        duration_hist = create_duration_histogram(report.loss_trades)
        avg_loss_chart = create_avg_loss_by_category_chart(category_stats)
        
        # HTML template
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Losing Trades Analysis - {report.backtest_run_id}</title>
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
            margin-bottom: 30px;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
            border-left: 4px solid #3498db;
            padding-left: 15px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }}
        .stat-value {{
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        .stat-label {{
            font-size: 0.9em;
            opacity: 0.9;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        th, td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background: #3498db;
            color: white;
            font-weight: bold;
        }}
        tr:nth-child(even) {{
            background: #f8f9fa;
        }}
        tr:hover {{
            background: #e3f2fd;
        }}
        .chart-container {{
            text-align: center;
            margin: 30px 0;
            padding: 20px;
            background: #fafafa;
            border-radius: 8px;
        }}
        .suggestions {{
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}
        .suggestions h3 {{
            color: #856404;
            margin-top: 0;
        }}
        .suggestions ul {{
            margin: 10px 0;
            padding-left: 20px;
        }}
        .suggestions li {{
            margin: 8px 0;
            color: #856404;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Losing Trades Analysis Report</h1>
        <p style="text-align: center; color: #666; font-size: 1.1em;">Backtest Run: {report.backtest_run_id}</p>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{report.total_positions}</div>
                <div class="stat-label">Total Positions</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{report.win_rate:.1%}</div>
                <div class="stat-label">Win Rate</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{report.losing_positions}</div>
                <div class="stat-label">Losing Positions</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${report.total_loss:.2f}</div>
                <div class="stat-label">Total Loss</div>
            </div>
        </div>
        
        <h2>Loss Category Breakdown</h2>
        <table>
            <thead>
                <tr>
                    <th>Category</th>
                    <th>Count</th>
                    <th>Total Loss</th>
                    <th>Avg Loss</th>
                    <th>Avg Duration</th>
                    <th>% of Losses</th>
                </tr>
            </thead>
            <tbody>
"""
        
        # Add category rows
        for stat in sorted(report.category_stats, key=lambda x: x.count, reverse=True):
            duration_str = f"{stat.avg_duration_seconds/60:.1f}min" if stat.avg_duration_seconds < 3600 else f"{stat.avg_duration_seconds/3600:.1f}hr"
            html_content += f"""
                <tr>
                    <td>{stat.category_name}</td>
                    <td>{stat.count}</td>
                    <td>${stat.total_loss:.2f}</td>
                    <td>${stat.avg_loss:.2f}</td>
                    <td>{duration_str}</td>
                    <td>{stat.percentage_of_total_losses:.1f}%</td>
                </tr>
"""
        
        html_content += """
            </tbody>
        </table>
        
        <h2>Loss Category Distribution</h2>
        <div class="chart-container">
            <img src="data:image/png;base64,""" + pie_chart + """" alt="Loss Category Pie Chart" style="max-width: 100%; height: auto;">
        </div>
        
        <h2>Loss Count by Category</h2>
        <div class="chart-container">
            <img src="data:image/png;base64,""" + bar_chart + """" alt="Loss Count Bar Chart" style="max-width: 100%; height: auto;">
        </div>
        
        <h2>Time-in-Trade Distribution</h2>
        <div class="chart-container">
            <img src="data:image/png;base64,""" + duration_hist + """" alt="Duration Histogram" style="max-width: 100%; height: auto;">
        </div>
        
        <h2>Average Loss by Category</h2>
        <div class="chart-container">
            <img src="data:image/png;base64,""" + avg_loss_chart + """" alt="Average Loss Chart" style="max-width: 100%; height: auto;">
        </div>
"""
        
        # Add patterns section
        if report.patterns_detected:
            html_content += """
        <h2>Patterns Detected</h2>
        <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
"""
            
            patterns = report.patterns_detected
            if patterns.get('time_of_day'):
                peak_hour = max(patterns['time_of_day'].items(), key=lambda x: x[1])
                html_content += f"<p><strong>Peak Loss Hour:</strong> {peak_hour[0]}:00 ({peak_hour[1]} losses)</p>"
            
            if patterns.get('consecutive_losses'):
                max_consecutive = max(patterns['consecutive_losses']) if patterns['consecutive_losses'] else 0
                html_content += f"<p><strong>Max Consecutive Losses:</strong> {max_consecutive}</p>"
            
            if patterns.get('side_bias'):
                for side, count in patterns['side_bias'].items():
                    html_content += f"<p><strong>{side} Losses:</strong> {count}</p>"
            
            # Add bar/indicator pattern fields
            entry_vs_bar_range = patterns.get('entry_vs_bar_range')
            volatility_at_entry = patterns.get('volatility_at_entry')
            dmi_at_entry = patterns.get('dmi_at_entry')
            stoch_at_entry = patterns.get('stoch_at_entry')
            
            if entry_vs_bar_range is not None:
                html_content += f"<p><strong>Entry vs Bar Range:</strong> {entry_vs_bar_range}</p>"
            else:
                html_content += "<p><strong>Entry vs Bar Range:</strong> Unavailable (no bar/indicator data)</p>"
            
            if volatility_at_entry is not None:
                html_content += f"<p><strong>Volatility at Entry:</strong> {volatility_at_entry}</p>"
            else:
                html_content += "<p><strong>Volatility at Entry:</strong> Unavailable (no bar/indicator data)</p>"
            
            if dmi_at_entry is not None:
                html_content += f"<p><strong>DMI at Entry:</strong> {dmi_at_entry}</p>"
            else:
                html_content += "<p><strong>DMI at Entry:</strong> Unavailable (no bar/indicator data)</p>"
            
            if stoch_at_entry is not None:
                html_content += f"<p><strong>Stochastic at Entry:</strong> {stoch_at_entry}</p>"
            else:
                html_content += "<p><strong>Stochastic at Entry:</strong> Unavailable (no bar/indicator data)</p>"
            
            html_content += "</div>"
        
        # Add suggestions section
        if report.parameter_suggestions:
            html_content += """
        <div class="suggestions">
            <h3>Parameter Adjustment Suggestions</h3>
            <ul>
"""
            for suggestion in report.parameter_suggestions:
                html_content += f"<li>{suggestion}</li>"
            
            html_content += """
            </ul>
        </div>
"""
        
        # Footer
        html_content += f"""
        <div class="footer">
            <p>Report generated on {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>Generated by Losing Trades Analysis Tool</p>
        </div>
    </div>
</body>
</html>
"""
        
        with open(output_path, 'w') as f:
            f.write(html_content)
        
        logger.info(f"HTML report saved to {output_path}")
        
    except Exception as e:
        logger.error(f"Error generating HTML report: {e}")
        raise


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Analyze losing trades from backtest results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyze_losing_trades.py --input results/backtest_20240101_120000
  python analyze_losing_trades.py --input results/backtest_20240101_120000 --output custom_report.html
  python analyze_losing_trades.py --input results/backtest_20240101_120000 --json --verbose
        """
    )
    
    parser.add_argument(
        '--input',
        type=Path,
        required=True,
        help='Path to backtest results directory containing positions.csv, orders.csv, fills.csv, performance_stats.json'
    )
    
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('reports/loss_analysis.html'),
        help='Path for output HTML report (default: reports/loss_analysis.html)'
    )
    
    parser.add_argument(
        '--json',
        action='store_true',
        help='Export analysis results as JSON file'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Main function."""
    try:
        args = parse_arguments(argv)
        
        # Set logging level
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        # Validate input directory
        if not args.input.exists():
            logger.error(f"Input directory does not exist: {args.input}")
            return 1
        
        if not args.input.is_dir():
            logger.error(f"Input path is not a directory: {args.input}")
            return 1
        
        # Create output directory if needed
        args.output.parent.mkdir(parents=True, exist_ok=True)
        
        # Run analysis
        logger.info("Starting losing trades analysis...")
        report = analyze_losing_trades(args.input)
        
        # Generate console report (always)
        generate_console_report(report)
        
        # Generate HTML report (always)
        generate_html_report(report, args.output, report.category_stats)
        logger.info(f"HTML report saved to: {args.output}")
        
        # Generate JSON report (if requested)
        if args.json:
            json_path = args.output.with_suffix('.json')
            generate_json_report(report, json_path)
            logger.info(f"JSON report saved to: {json_path}")
        
        logger.info("Analysis completed successfully")
        return 0
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
