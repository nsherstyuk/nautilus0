"""
Analyze backtest results by time of day and day of week to identify
optimal trading hours and potential PnL improvements.

Usage:
    python tools/analyze_trade_timing.py <backtest_results_dir>
    
Example:
    python tools/analyze_trade_timing.py logs/backtest_results/EUR-USD_20251026_140549_739444
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
import json
import re

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_backtest_data(results_dir: Path) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load positions, fills, and orders from backtest results."""
    positions_df = pd.read_csv(results_dir / "positions.csv")
    fills_df = pd.read_csv(results_dir / "fills.csv")
    orders_df = pd.read_csv(results_dir / "orders.csv")
    
    return positions_df, fills_df, orders_df


def strip_currency_suffix(value_str):
    """Strip currency suffix from PnL values (e.g., '-356.17 USD' -> -356.17)."""
    if pd.isna(value_str):
        return np.nan
    if isinstance(value_str, (int, float)):
        return float(value_str)
    # Remove currency code (USD, EUR, etc.) and any whitespace
    cleaned = re.sub(r'\s*[A-Z]{3}\s*$', '', str(value_str))
    try:
        return float(cleaned)
    except ValueError:
        return np.nan


def prepare_positions_data(positions_df: pd.DataFrame) -> pd.DataFrame:
    """Prepare positions DataFrame with proper datetime and numeric conversions."""
    print(f"\n🔍 Debugging positions DataFrame:")
    print(f"   Columns: {list(positions_df.columns)}")
    print(f"   Shape: {positions_df.shape}")
    
    # Convert timestamps to datetime
    for col in ['ts_opened', 'ts_closed']:
        if col in positions_df.columns:
            # Check if already in datetime format or needs conversion
            sample_value = positions_df[col].iloc[0] if len(positions_df) > 0 else None
            print(f"   Sample {col}: {sample_value} (type: {type(sample_value)})")
            
            # Try parsing as ISO format string first
            try:
                positions_df[col] = pd.to_datetime(positions_df[col], utc=True)
                print(f"   ✅ Converted {col} to datetime (ISO format)")
            except Exception as e:
                # Fallback: try parsing as nanoseconds
                try:
                    positions_df[col] = pd.to_datetime(positions_df[col], unit='ns', utc=True)
                    print(f"   ✅ Converted {col} to datetime (nanoseconds)")
                except Exception as e2:
                    print(f"   ❌ Failed to convert {col}: {e2}")
                    raise
    
    # Convert PnL to numeric (handle string values with currency suffix)
    pnl_candidates = ['realized_pnl', 'realized_pnl_quote', 'realized_return']
    pnl_col = None
    for candidate in pnl_candidates:
        if candidate in positions_df.columns:
            pnl_col = candidate
            break
    
    if pnl_col:
        print(f"   Found PnL column: {pnl_col}")
        sample_pnl = positions_df[pnl_col].iloc[0] if len(positions_df) > 0 else None
        print(f"   Sample PnL: {sample_pnl} (type: {type(sample_pnl)})")
        
        # Strip currency suffix and convert to numeric
        positions_df['pnl'] = positions_df[pnl_col].apply(strip_currency_suffix)
        print(f"   ✅ Converted PnL to numeric (stripped currency suffix)")
        print(f"   Sample converted PnL: {positions_df['pnl'].iloc[0]}")
    else:
        raise ValueError(f"No PnL column found. Available columns: {list(positions_df.columns)}")
    
    # Filter closed positions only
    closed_positions = positions_df[positions_df['ts_closed'].notna()].copy()
    print(f"   ✅ Filtered to {len(closed_positions)} closed positions")
    
    if len(closed_positions) == 0:
        raise ValueError("No closed positions found in the dataset")
    
    # Extract time features
    closed_positions['hour'] = closed_positions['ts_opened'].dt.hour
    closed_positions['day_of_week'] = closed_positions['ts_opened'].dt.dayofweek  # 0=Monday, 6=Sunday
    closed_positions['day_name'] = closed_positions['ts_opened'].dt.day_name()
    
    print(f"   ✅ Extracted time features (hour, day_of_week, day_name)")
    print(f"   Sample hour: {closed_positions['hour'].iloc[0]}")
    print(f"   Sample day: {closed_positions['day_name'].iloc[0]}")
    
    return closed_positions


def analyze_by_hour(positions_df: pd.DataFrame) -> pd.DataFrame:
    """Analyze trade performance by hour of day."""
    hourly_stats = positions_df.groupby('hour').agg({
        'pnl': ['count', 'sum', 'mean', 'std', lambda x: (x > 0).sum()],
    }).round(2)
    
    hourly_stats.columns = ['trade_count', 'total_pnl', 'avg_pnl', 'std_pnl', 'winners']
    hourly_stats['win_rate'] = (hourly_stats['winners'] / hourly_stats['trade_count'] * 100).round(1)
    hourly_stats['losers'] = hourly_stats['trade_count'] - hourly_stats['winners']
    
    # Calculate cumulative PnL if this hour was excluded
    total_pnl = positions_df['pnl'].sum()
    hourly_stats['pnl_if_excluded'] = total_pnl - hourly_stats['total_pnl']
    hourly_stats['pnl_improvement'] = hourly_stats['pnl_if_excluded'] - total_pnl
    
    return hourly_stats.sort_values('total_pnl', ascending=False)


def analyze_by_day(positions_df: pd.DataFrame) -> pd.DataFrame:
    """Analyze trade performance by day of week."""
    daily_stats = positions_df.groupby(['day_of_week', 'day_name']).agg({
        'pnl': ['count', 'sum', 'mean', 'std', lambda x: (x > 0).sum()],
    }).round(2)
    
    daily_stats.columns = ['trade_count', 'total_pnl', 'avg_pnl', 'std_pnl', 'winners']
    daily_stats['win_rate'] = (daily_stats['winners'] / daily_stats['trade_count'] * 100).round(1)
    daily_stats['losers'] = daily_stats['trade_count'] - daily_stats['winners']
    
    # Calculate cumulative PnL if this day was excluded
    total_pnl = positions_df['pnl'].sum()
    daily_stats['pnl_if_excluded'] = total_pnl - daily_stats['total_pnl']
    daily_stats['pnl_improvement'] = daily_stats['pnl_if_excluded'] - total_pnl
    
    return daily_stats.sort_values('total_pnl', ascending=False)


def analyze_by_session(positions_df: pd.DataFrame) -> pd.DataFrame:
    """Analyze trade performance by forex trading session."""
    def get_session(hour):
        """Classify hour into forex trading session (UTC)."""
        if 0 <= hour < 7:
            return 'Asian'
        elif 7 <= hour < 15:
            return 'European'
        elif 15 <= hour < 21:
            return 'US'
        else:
            return 'Asian'  # Late US / Early Asian overlap
    
    positions_df['session'] = positions_df['hour'].apply(get_session)
    
    session_stats = positions_df.groupby('session').agg({
        'pnl': ['count', 'sum', 'mean', 'std', lambda x: (x > 0).sum()],
    }).round(2)
    
    session_stats.columns = ['trade_count', 'total_pnl', 'avg_pnl', 'std_pnl', 'winners']
    session_stats['win_rate'] = (session_stats['winners'] / session_stats['trade_count'] * 100).round(1)
    session_stats['losers'] = session_stats['trade_count'] - session_stats['winners']
    
    # Calculate cumulative PnL if this session was excluded
    total_pnl = positions_df['pnl'].sum()
    session_stats['pnl_if_excluded'] = total_pnl - session_stats['total_pnl']
    session_stats['pnl_improvement'] = session_stats['pnl_if_excluded'] - total_pnl
    
    return session_stats.sort_values('total_pnl', ascending=False)


def identify_optimal_filters(hourly_stats: pd.DataFrame, daily_stats: pd.DataFrame) -> Dict:
    """Identify hours and days that should be filtered to improve PnL."""
    # Find hours with negative total PnL
    bad_hours = hourly_stats[hourly_stats['total_pnl'] < 0].index.tolist()
    bad_hours_pnl_loss = hourly_stats[hourly_stats['total_pnl'] < 0]['total_pnl'].sum()
    
    # Find days with negative total PnL
    bad_days = daily_stats[daily_stats['total_pnl'] < 0].index.get_level_values('day_name').tolist()
    bad_days_pnl_loss = daily_stats[daily_stats['total_pnl'] < 0]['total_pnl'].sum()
    
    # Calculate potential improvement
    current_pnl = hourly_stats['total_pnl'].sum()
    potential_pnl_hours = current_pnl - bad_hours_pnl_loss
    potential_pnl_days = current_pnl - bad_days_pnl_loss
    
    return {
        'current_pnl': round(current_pnl, 2),
        'bad_hours': bad_hours,
        'bad_hours_pnl_loss': round(bad_hours_pnl_loss, 2),
        'potential_pnl_if_hours_filtered': round(potential_pnl_hours, 2),
        'pnl_improvement_hours': round(potential_pnl_hours - current_pnl, 2),
        'bad_days': bad_days,
        'bad_days_pnl_loss': round(bad_days_pnl_loss, 2),
        'potential_pnl_if_days_filtered': round(potential_pnl_days, 2),
        'pnl_improvement_days': round(potential_pnl_days - current_pnl, 2),
    }


def print_analysis(hourly_stats: pd.DataFrame, daily_stats: pd.DataFrame, 
                   session_stats: pd.DataFrame, filters: Dict):
    """Print comprehensive analysis to console."""
    print("\n" + "="*80)
    print("TRADE TIMING ANALYSIS - BACKTEST RESULTS")
    print("="*80)
    
    print("\n" + "-"*80)
    print("HOURLY PERFORMANCE (UTC)")
    print("-"*80)
    print(hourly_stats.to_string())
    
    print("\n" + "-"*80)
    print("DAILY PERFORMANCE (Day of Week)")
    print("-"*80)
    print(daily_stats.to_string())
    
    print("\n" + "-"*80)
    print("SESSION PERFORMANCE (Forex Sessions)")
    print("-"*80)
    print("Asian: 00:00-07:00 UTC | European: 07:00-15:00 UTC | US: 15:00-21:00 UTC")
    print(session_stats.to_string())
    
    print("\n" + "="*80)
    print("OPTIMIZATION RECOMMENDATIONS")
    print("="*80)
    
    print(f"\nCurrent Total PnL: ${filters['current_pnl']:,.2f}")
    
    if filters['bad_hours']:
        print(f"\n🔴 UNPROFITABLE HOURS (UTC): {filters['bad_hours']}")
        print(f"   Loss from these hours: ${filters['bad_hours_pnl_loss']:,.2f}")
        print(f"   Potential PnL if filtered: ${filters['potential_pnl_if_hours_filtered']:,.2f}")
        improvement_pct = (filters['pnl_improvement_hours']/abs(filters['current_pnl'])*100) if filters['current_pnl'] != 0 else 0
        print(f"   Improvement: ${filters['pnl_improvement_hours']:,.2f} ({improvement_pct:.1f}%)")
    else:
        print("\n✅ No unprofitable hours detected - all hours contribute positively!")
    
    if filters['bad_days']:
        print(f"\n🔴 UNPROFITABLE DAYS: {filters['bad_days']}")
        print(f"   Loss from these days: ${filters['bad_days_pnl_loss']:,.2f}")
        print(f"   Potential PnL if filtered: ${filters['potential_pnl_if_days_filtered']:,.2f}")
        improvement_pct = (filters['pnl_improvement_days']/abs(filters['current_pnl'])*100) if filters['current_pnl'] != 0 else 0
        print(f"   Improvement: ${filters['pnl_improvement_days']:,.2f} ({improvement_pct:.1f}%)")
    else:
        print("\n✅ No unprofitable days detected - all days contribute positively!")
    
    # Best performing times
    if not hourly_stats.empty:
        best_hour = hourly_stats.iloc[0]
        worst_hour = hourly_stats.iloc[-1]
        print(f"\n📈 BEST HOUR: {best_hour.name}:00 UTC (PnL: ${best_hour['total_pnl']:,.2f}, Win Rate: {best_hour['win_rate']:.1f}%)")
        print(f"📉 WORST HOUR: {worst_hour.name}:00 UTC (PnL: ${worst_hour['total_pnl']:,.2f}, Win Rate: {worst_hour['win_rate']:.1f}%)")
    
    if not daily_stats.empty:
        best_day = daily_stats.iloc[0]
        worst_day = daily_stats.iloc[-1]
        print(f"\n📈 BEST DAY: {best_day.name[1]} (PnL: ${best_day['total_pnl']:,.2f}, Win Rate: {best_day['win_rate']:.1f}%)")
        print(f"📉 WORST DAY: {worst_day.name[1]} (PnL: ${worst_day['total_pnl']:,.2f}, Win Rate: {worst_day['win_rate']:.1f}%)")
    
    print("\n" + "="*80)


def save_analysis(results_dir: Path, hourly_stats: pd.DataFrame, daily_stats: pd.DataFrame,
                  session_stats: pd.DataFrame, filters: Dict):
    """Save analysis results to CSV and JSON files."""
    hourly_stats.to_csv(results_dir / "analysis_hourly.csv")
    daily_stats.to_csv(results_dir / "analysis_daily.csv")
    session_stats.to_csv(results_dir / "analysis_session.csv")
    
    with open(results_dir / "analysis_filters.json", 'w') as f:
        json.dump(filters, f, indent=2)
    
    print(f"\n✅ Analysis saved to:")
    print(f"   - {results_dir / 'analysis_hourly.csv'}")
    print(f"   - {results_dir / 'analysis_daily.csv'}")
    print(f"   - {results_dir / 'analysis_session.csv'}")
    print(f"   - {results_dir / 'analysis_filters.json'}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/analyze_trade_timing.py <backtest_results_dir>")
        print("Example: python tools/analyze_trade_timing.py logs/backtest_results/EUR-USD_20251026_140549_739444")
        sys.exit(1)
    
    results_dir = Path(sys.argv[1])
    
    if not results_dir.exists():
        print(f"Error: Results directory not found: {results_dir}")
        sys.exit(1)
    
    print(f"Loading backtest results from: {results_dir}")
    
    try:
        positions_df, fills_df, orders_df = load_backtest_data(results_dir)
        print(f"✅ Loaded {len(positions_df)} positions, {len(fills_df)} fills, {len(orders_df)} orders")
        
        positions_df = prepare_positions_data(positions_df)
        print(f"✅ Prepared {len(positions_df)} closed positions for analysis")
        
        hourly_stats = analyze_by_hour(positions_df)
        daily_stats = analyze_by_day(positions_df)
        session_stats = analyze_by_session(positions_df)
        
        filters = identify_optimal_filters(hourly_stats, daily_stats)
        
        print_analysis(hourly_stats, daily_stats, session_stats, filters)
        save_analysis(results_dir, hourly_stats, daily_stats, session_stats, filters)
        
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


