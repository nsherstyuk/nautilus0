"""
Analyze how many days had no trades in the latest backtest.
"""
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def find_latest_backtest():
    """Find the most recent backtest results directory."""
    results_dir = Path("logs/backtest_results")
    if not results_dir.exists():
        return None
    
    dirs = [d for d in results_dir.iterdir() if d.is_dir() and "EUR-USD_" in d.name]
    if not dirs:
        return None
    
    return max(dirs, key=lambda d: d.stat().st_mtime)

def analyze_trading_days(backtest_dir):
    """Analyze days with and without trades."""
    positions_file = backtest_dir / "positions.csv"
    if not positions_file.exists():
        print(f"Error: positions.csv not found in {backtest_dir}")
        return None
    
    df = pd.read_csv(positions_file)
    
    # Convert timestamps to datetime
    df["ts_opened"] = pd.to_datetime(df["ts_opened"])
    
    # Extract date (without time)
    df["trade_date"] = df["ts_opened"].dt.date
    
    # Count trades per day
    trades_per_day = df.groupby("trade_date").size()
    
    # Get date range from backtest config or from data
    min_date = df["trade_date"].min()
    max_date = df["trade_date"].max()
    
    # Create full date range
    from datetime import timedelta
    all_dates = pd.date_range(start=min_date, end=max_date, freq='D').date
    
    # Count days with trades vs no trades
    days_with_trades = len(trades_per_day)
    days_without_trades = len(all_dates) - days_with_trades
    total_days = len(all_dates)
    
    return {
        'backtest_dir': backtest_dir.name,
        'min_date': min_date,
        'max_date': max_date,
        'total_days': total_days,
        'days_with_trades': days_with_trades,
        'days_without_trades': days_without_trades,
        'percentage_with_trades': (days_with_trades / total_days * 100) if total_days > 0 else 0,
        'percentage_without_trades': (days_without_trades / total_days * 100) if total_days > 0 else 0,
        'trades_per_day': trades_per_day.to_dict(),
        'dates_without_trades': sorted(set(all_dates) - set(trades_per_day.index))
    }

def main():
    print("=" * 100)
    print("ANALYZING TRADING DAYS IN LATEST BACKTEST")
    print("=" * 100)
    print()
    
    backtest_dir = find_latest_backtest()
    if not backtest_dir:
        print("Error: No backtest results found!")
        return 1
    
    print(f"Analyzing backtest: {backtest_dir.name}")
    print()
    
    analysis = analyze_trading_days(backtest_dir)
    if not analysis:
        return 1
    
    print("=" * 100)
    print("TRADING DAYS ANALYSIS")
    print("=" * 100)
    print()
    print(f"Backtest Period: {analysis['min_date']} to {analysis['max_date']}")
    print(f"Total Days: {analysis['total_days']}")
    print()
    print(f"Days WITH Trades: {analysis['days_with_trades']} ({analysis['percentage_with_trades']:.1f}%)")
    print(f"Days WITHOUT Trades: {analysis['days_without_trades']} ({analysis['percentage_without_trades']:.1f}%)")
    print()
    
    if analysis['dates_without_trades']:
        print(f"Dates with NO TRADES ({len(analysis['dates_without_trades'])} days):")
        # Show first 20 dates
        for date in analysis['dates_without_trades'][:20]:
            print(f"  - {date}")
        if len(analysis['dates_without_trades']) > 20:
            print(f"  ... and {len(analysis['dates_without_trades']) - 20} more")
        print()
    
    # Show distribution of trades per day
    trades_per_day = analysis['trades_per_day']
    if trades_per_day:
        print("Trade Distribution:")
        print(f"  Average trades per day: {sum(trades_per_day.values()) / len(trades_per_day):.1f}")
        print(f"  Max trades in a single day: {max(trades_per_day.values())}")
        print(f"  Min trades in a single day: {min(trades_per_day.values())}")
        print()
        
        # Count days by trade frequency
        trade_counts = {}
        for count in trades_per_day.values():
            trade_counts[count] = trade_counts.get(count, 0) + 1
        
        print("Days by Trade Count:")
        for count in sorted(trade_counts.keys()):
            print(f"  {count} trade(s): {trade_counts[count]} day(s)")
    
    print()
    print("=" * 100)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

