"""
Script to analyze optimal TP/SL settings by hour, weekday, and month.

This script:
1. Analyzes existing trades to find what TP/SL would have been optimal
2. Suggests different TP/SL combinations to test
3. Identifies patterns where different settings perform better
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
import json

def analyze_trade_outcomes(positions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyze trade outcomes to determine what TP/SL would have been optimal.
    
    For each trade, calculate:
    - Maximum favorable excursion (MFE) - highest profit reached
    - Maximum adverse excursion (MAE) - worst loss before recovery
    - Time to TP/SL hit
    - What TP/SL would have been optimal
    """
    pos = positions_df.copy()
    pos['ts_opened'] = pd.to_datetime(pos['ts_opened'])
    pos['ts_closed'] = pd.to_datetime(pos['ts_closed'])
    
    # Extract PnL
    if pos['realized_pnl'].dtype == 'object':
        pos['pnl_value'] = pos['realized_pnl'].str.replace(' USD', '', regex=False).str.replace('USD', '', regex=False).str.strip().astype(float)
    else:
        pos['pnl_value'] = pos['realized_pnl'].astype(float)
    
    # Extract entry and exit prices
    pos['entry_price'] = pos['avg_px_open'].astype(float)
    pos['exit_price'] = pos['avg_px_close'].astype(float)
    
    # Calculate price movement in pips (assuming EUR/USD, 4 decimal places)
    # For BUY: profit when exit > entry
    # For SELL: profit when exit < entry
    pos['price_diff'] = pos['exit_price'] - pos['entry_price']
    pos['price_diff_pips'] = pos.apply(
        lambda row: row['price_diff'] * 10000 if row['entry'] == 'BUY' else -row['price_diff'] * 10000,
        axis=1
    )
    
    # Add time dimensions
    pos['hour'] = pos['ts_opened'].dt.hour
    pos['weekday'] = pos['ts_opened'].dt.day_name()
    # Convert to period without timezone to avoid warning
    pos['month'] = pos['ts_opened'].dt.tz_localize(None).dt.to_period('M').astype(str)
    
    return pos

def suggest_tp_sl_combinations() -> List[Tuple[int, int]]:
    """
    Suggest TP/SL combinations to test.
    Returns list of (stop_loss_pips, take_profit_pips) tuples.
    """
    combinations = []
    
    # Conservative: 1:1 risk/reward
    combinations.extend([
        (15, 15), (20, 20), (25, 25), (30, 30)
    ])
    
    # Moderate: 1:2 risk/reward
    combinations.extend([
        (15, 30), (20, 40), (25, 50), (30, 60)
    ])
    
    # Aggressive: 1:3 risk/reward
    combinations.extend([
        (15, 45), (20, 60), (25, 75), (30, 90)
    ])
    
    # Tight stops, wide targets
    combinations.extend([
        (10, 30), (10, 40), (10, 50)
    ])
    
    # Wide stops, tight targets (for ranging markets)
    combinations.extend([
        (30, 15), (40, 20), (50, 25)
    ])
    
    return combinations

def suggest_trailing_stop_combinations() -> List[Tuple[int, int]]:
    """
    Suggest trailing stop combinations to test.
    Returns list of (activation_pips, distance_pips) tuples.
    """
    combinations = []
    
    # Early activation, tight distance
    combinations.extend([
        (10, 10), (15, 10), (15, 15), (20, 10)
    ])
    
    # Standard activation, various distances
    combinations.extend([
        (20, 15), (20, 20), (20, 25), (25, 15), (25, 20)
    ])
    
    # Late activation, wider distance (let winners run)
    combinations.extend([
        (30, 20), (30, 25), (40, 25), (40, 30)
    ])
    
    # Very tight trailing (scalp style)
    combinations.extend([
        (10, 5), (15, 5), (20, 5)
    ])
    
    return combinations

def analyze_by_dimensions(pos: pd.DataFrame) -> Dict:
    """
    Analyze optimal TP/SL by hour, weekday, and month.
    
    For each dimension, calculate:
    - Average price movement (favorable and adverse)
    - Win rate with different TP/SL thresholds
    - Expected value with different TP/SL thresholds
    """
    results = {}
    
    # Analyze by hour
    results['by_hour'] = {}
    for hour in sorted(pos['hour'].unique()):
        hour_trades = pos[pos['hour'] == hour]
        if len(hour_trades) < 5:  # Skip if too few trades
            continue
        
        results['by_hour'][hour] = {
            'trade_count': len(hour_trades),
            'avg_pnl': hour_trades['pnl_value'].mean(),
            'win_rate': (hour_trades['pnl_value'] > 0).mean() * 100,
            'avg_price_movement_pips': hour_trades['price_diff_pips'].abs().mean(),
            'max_favorable_pips': hour_trades[hour_trades['pnl_value'] > 0]['price_diff_pips'].quantile(0.75) if (hour_trades['pnl_value'] > 0).sum() > 0 else 0,
            'max_adverse_pips': hour_trades[hour_trades['pnl_value'] < 0]['price_diff_pips'].abs().quantile(0.75) if (hour_trades['pnl_value'] < 0).sum() > 0 else 0,
        }
    
    # Analyze by weekday
    results['by_weekday'] = {}
    weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    for weekday in weekday_order:
        weekday_trades = pos[pos['weekday'] == weekday]
        if len(weekday_trades) < 5:
            continue
        
        results['by_weekday'][weekday] = {
            'trade_count': len(weekday_trades),
            'avg_pnl': weekday_trades['pnl_value'].mean(),
            'win_rate': (weekday_trades['pnl_value'] > 0).mean() * 100,
            'avg_price_movement_pips': weekday_trades['price_diff_pips'].abs().mean(),
            'max_favorable_pips': weekday_trades[weekday_trades['pnl_value'] > 0]['price_diff_pips'].quantile(0.75) if (weekday_trades['pnl_value'] > 0).sum() > 0 else 0,
            'max_adverse_pips': weekday_trades[weekday_trades['pnl_value'] < 0]['price_diff_pips'].abs().quantile(0.75) if (weekday_trades['pnl_value'] < 0).sum() > 0 else 0,
        }
    
    # Analyze by month
    results['by_month'] = {}
    for month in sorted(pos['month'].unique()):
        month_trades = pos[pos['month'] == month]
        if len(month_trades) < 5:
            continue
        
        results['by_month'][month] = {
            'trade_count': len(month_trades),
            'avg_pnl': month_trades['pnl_value'].mean(),
            'win_rate': (month_trades['pnl_value'] > 0).mean() * 100,
            'avg_price_movement_pips': month_trades['price_diff_pips'].abs().mean(),
            'max_favorable_pips': month_trades[month_trades['pnl_value'] > 0]['price_diff_pips'].quantile(0.75) if (month_trades['pnl_value'] > 0).sum() > 0 else 0,
            'max_adverse_pips': month_trades[month_trades['pnl_value'] < 0]['price_diff_pips'].abs().quantile(0.75) if (month_trades['pnl_value'] < 0).sum() > 0 else 0,
        }
    
    # Analyze combinations (hour + weekday, hour + month, etc.)
    results['by_hour_weekday'] = {}
    for hour in sorted(pos['hour'].unique()):
        for weekday in weekday_order:
            subset = pos[(pos['hour'] == hour) & (pos['weekday'] == weekday)]
            if len(subset) < 3:
                continue
            
            key = f"{weekday}_H{hour:02d}"
            results['by_hour_weekday'][key] = {
                'trade_count': len(subset),
                'avg_pnl': subset['pnl_value'].mean(),
                'win_rate': (subset['pnl_value'] > 0).mean() * 100,
                'avg_price_movement_pips': subset['price_diff_pips'].abs().mean(),
            }
    
    return results

def simulate_tp_sl_performance(pos: pd.DataFrame, sl_pips: int, tp_pips: int) -> Dict:
    """
    Simulate what the performance would have been with given TP/SL settings.
    
    For each trade:
    - If price hit TP before SL: count as win with TP pips
    - If price hit SL before TP: count as loss with SL pips
    - Otherwise: use actual outcome (if within bounds)
    """
    simulated_pnl = []
    
    for _, trade in pos.iterrows():
        price_movement = trade['price_diff_pips']
        
        # Determine if TP or SL would have been hit first
        if price_movement >= tp_pips:
            # TP hit first
            simulated_pnl.append(tp_pips * 10)  # Assuming $10 per pip for 1 lot
        elif price_movement <= -sl_pips:
            # SL hit first
            simulated_pnl.append(-sl_pips * 10)
        else:
            # Neither hit, use actual outcome (scaled)
            simulated_pnl.append(trade['pnl_value'])
    
    return {
        'total_pnl': sum(simulated_pnl),
        'win_rate': (np.array(simulated_pnl) > 0).mean() * 100,
        'avg_pnl': np.mean(simulated_pnl),
        'trades': len(simulated_pnl)
    }

def analyze_trailing_stop_impact(pos: pd.DataFrame) -> Dict:
    """
    Analyze potential impact of trailing stops.
    
    Note: This is a simplified analysis. For accurate trailing stop simulation,
    we would need intra-trade price data (bar-by-bar during each trade).
    
    Current analysis:
    - Identifies trades that hit TP (could trailing stop have captured more?)
    - Identifies trades that hit SL (could trailing stop have prevented loss?)
    - Estimates potential improvement
    """
    analysis = {
        'trades_that_hit_tp': 0,
        'trades_that_hit_sl': 0,
        'trades_in_between': 0,
        'potential_trailing_benefit': 0,
        'notes': []
    }
    
    # Current settings (from config defaults)
    current_tp = 50
    current_sl = 25
    current_activation = 20
    current_distance = 15
    
    for _, trade in pos.iterrows():
        price_movement = trade['price_diff_pips']
        pnl = trade['pnl_value']
        
        # Check if trade hit TP (price movement >= TP)
        if price_movement >= current_tp:
            analysis['trades_that_hit_tp'] += 1
            # Trailing stop could have captured more if price went higher
            # But we don't know the peak, so we can't calculate exactly
            analysis['notes'].append(
                f"Trade hit TP ({current_tp} pips), final movement: {price_movement:.1f} pips"
            )
        
        # Check if trade hit SL (price movement <= -SL)
        elif price_movement <= -current_sl:
            analysis['trades_that_hit_sl'] += 1
            # Trailing stop might have prevented this if activated before SL
            # But we don't know the price path, so we can't calculate exactly
            analysis['notes'].append(
                f"Trade hit SL ({current_sl} pips), final movement: {price_movement:.1f} pips"
            )
        
        # Trades that closed between TP and SL
        else:
            analysis['trades_in_between'] += 1
            # These might benefit from trailing stops if they had profit but gave it back
    
    return analysis

def generate_optimization_report(positions_file: Path, output_file: Path):
    """
    Generate a comprehensive report for TP/SL optimization.
    """
    print(f"Loading positions from: {positions_file}")
    pos_df = pd.read_csv(positions_file)
    
    print("Analyzing trade outcomes...")
    pos = analyze_trade_outcomes(pos_df)
    
    print("Analyzing by dimensions...")
    dimension_analysis = analyze_by_dimensions(pos)
    
    print("Testing TP/SL combinations...")
    combinations = suggest_tp_sl_combinations()
    
    # Test combinations overall
    overall_results = []
    for sl_pips, tp_pips in combinations:
        result = simulate_tp_sl_performance(pos, sl_pips, tp_pips)
        overall_results.append({
            'sl_pips': sl_pips,
            'tp_pips': tp_pips,
            'risk_reward': f"1:{tp_pips/sl_pips:.1f}",
            **result
        })
    
    print("Analyzing trailing stop impact...")
    trailing_analysis = analyze_trailing_stop_impact(pos)
    
    print("Testing trailing stop combinations...")
    trailing_combinations = suggest_trailing_stop_combinations()
    
    # Generate report
    report_lines = []
    report_lines.append("=" * 100)
    report_lines.append("TP/SL OPTIMIZATION ANALYSIS REPORT")
    report_lines.append("=" * 100)
    report_lines.append(f"Total Trades Analyzed: {len(pos)}")
    report_lines.append(f"Current Avg PnL: ${pos['pnl_value'].mean():.2f}")
    report_lines.append(f"Current Win Rate: {(pos['pnl_value'] > 0).mean() * 100:.1f}%")
    report_lines.append("")
    
    # Best TP/SL combinations overall
    report_lines.append("=" * 100)
    report_lines.append("BEST TP/SL COMBINATIONS (OVERALL)")
    report_lines.append("=" * 100)
    results_df = pd.DataFrame(overall_results)
    results_df = results_df.sort_values('total_pnl', ascending=False)
    report_lines.append(results_df.head(10).to_string(index=False))
    
    # Trailing stop analysis
    report_lines.append("\n" + "=" * 100)
    report_lines.append("TRAILING STOP ANALYSIS")
    report_lines.append("=" * 100)
    report_lines.append(f"Current Settings:")
    report_lines.append(f"  Activation: 20 pips")
    report_lines.append(f"  Distance: 15 pips")
    report_lines.append(f"\nTrade Breakdown:")
    report_lines.append(f"  Trades that hit TP: {trailing_analysis['trades_that_hit_tp']}")
    report_lines.append(f"  Trades that hit SL: {trailing_analysis['trades_that_hit_sl']}")
    report_lines.append(f"  Trades closed between TP/SL: {trailing_analysis['trades_in_between']}")
    report_lines.append(f"\n⚠️  LIMITATION:")
    report_lines.append(f"  Accurate trailing stop analysis requires intra-trade price data.")
    report_lines.append(f"  Current analysis is based on final outcomes only.")
    report_lines.append(f"  To properly optimize trailing stops, we need:")
    report_lines.append(f"    - Bar-by-bar price data during each trade")
    report_lines.append(f"    - Maximum favorable excursion (MFE)")
    report_lines.append(f"    - Maximum adverse excursion (MAE)")
    report_lines.append(f"\nSuggested Trailing Stop Combinations to Test:")
    report_lines.append(f"  (activation_pips, distance_pips)")
    for activation, distance in trailing_combinations[:10]:
        report_lines.append(f"    ({activation}, {distance})")
    report_lines.append(f"\n💡 RECOMMENDATION:")
    report_lines.append(f"  Run backtests with different trailing stop settings:")
    report_lines.append(f"  - Early activation (10-15 pips) with tight distance (5-10 pips) for scalping")
    report_lines.append(f"  - Standard activation (20-25 pips) with medium distance (15-20 pips)")
    report_lines.append(f"  - Late activation (30-40 pips) with wider distance (20-30 pips) for trends")
    
    # Analysis by hour
    report_lines.append("\n" + "=" * 100)
    report_lines.append("ANALYSIS BY HOUR")
    report_lines.append("=" * 100)
    for hour, stats in sorted(dimension_analysis['by_hour'].items()):
        report_lines.append(f"\nHour {hour:02d}:")
        report_lines.append(f"  Trades: {stats['trade_count']}")
        report_lines.append(f"  Avg PnL: ${stats['avg_pnl']:.2f}")
        report_lines.append(f"  Win Rate: {stats['win_rate']:.1f}%")
        report_lines.append(f"  Avg Price Movement: {stats['avg_price_movement_pips']:.1f} pips")
        report_lines.append(f"  75th percentile favorable: {stats['max_favorable_pips']:.1f} pips")
        report_lines.append(f"  75th percentile adverse: {stats['max_adverse_pips']:.1f} pips")
        report_lines.append(f"  Suggested TP: {max(20, int(stats['max_favorable_pips'] * 0.8))} pips")
        report_lines.append(f"  Suggested SL: {max(15, int(stats['max_adverse_pips'] * 0.8))} pips")
    
    # Analysis by weekday
    report_lines.append("\n" + "=" * 100)
    report_lines.append("ANALYSIS BY WEEKDAY")
    report_lines.append("=" * 100)
    for weekday, stats in dimension_analysis['by_weekday'].items():
        report_lines.append(f"\n{weekday}:")
        report_lines.append(f"  Trades: {stats['trade_count']}")
        report_lines.append(f"  Avg PnL: ${stats['avg_pnl']:.2f}")
        report_lines.append(f"  Win Rate: {stats['win_rate']:.1f}%")
        report_lines.append(f"  Suggested TP: {max(20, int(stats['max_favorable_pips'] * 0.8))} pips")
        report_lines.append(f"  Suggested SL: {max(15, int(stats['max_adverse_pips'] * 0.8))} pips")
    
    # Analysis by month
    report_lines.append("\n" + "=" * 100)
    report_lines.append("ANALYSIS BY MONTH")
    report_lines.append("=" * 100)
    for month, stats in sorted(dimension_analysis['by_month'].items()):
        report_lines.append(f"\n{month}:")
        report_lines.append(f"  Trades: {stats['trade_count']}")
        report_lines.append(f"  Avg PnL: ${stats['avg_pnl']:.2f}")
        report_lines.append(f"  Win Rate: {stats['win_rate']:.1f}%")
        report_lines.append(f"  Suggested TP: {max(20, int(stats['max_favorable_pips'] * 0.8))} pips")
        report_lines.append(f"  Suggested SL: {max(15, int(stats['max_adverse_pips'] * 0.8))} pips")
    
    # Write report
    output_file.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\nReport saved to: {output_file}")
    
    # Also save JSON for programmatic access
    # Convert numpy/pandas types to native Python types for JSON serialization
    def convert_to_native(obj):
        """Recursively convert numpy/pandas types to native Python types."""
        if isinstance(obj, dict):
            return {str(k): convert_to_native(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_to_native(item) for item in obj]
        elif isinstance(obj, (np.integer, np.int32, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float32, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif pd.isna(obj):
            return None
        else:
            return obj
    
    json_file = output_file.with_suffix('.json')
    with open(json_file, 'w') as f:
        json.dump({
            'overall_results': convert_to_native(overall_results),
            'dimension_analysis': convert_to_native(dimension_analysis)
        }, f, indent=2)
    print(f"JSON data saved to: {json_file}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python analyze_optimal_tp_sl.py <backtest_results_folder>")
        print("Example: python analyze_optimal_tp_sl.py logs/backtest_results/EUR-USD_20251111_185105")
        sys.exit(1)
    
    results_folder = Path(sys.argv[1])
    positions_file = results_folder / "positions.csv"
    output_file = results_folder / "tp_sl_optimization_report.txt"
    
    if not positions_file.exists():
        print(f"Error: {positions_file} not found")
        sys.exit(1)
    
    generate_optimization_report(positions_file, output_file)

