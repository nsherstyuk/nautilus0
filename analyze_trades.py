#!/usr/bin/env python3
"""
Trade Analysis Script
Analyzes trading performance from strategy logs for a specified period.

Usage:
    python analyze_trades.py                    # Today's trades
    python analyze_trades.py 2025-12-10        # From Dec 10 to now
    python analyze_trades.py 2025-12-09 2025-12-11  # Specific date range
"""

import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from zoneinfo import ZoneInfo

# Configuration
LOG_FILE = Path(__file__).parent / "logs" / "live_mtf" / "strategy.log"
EST = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def parse_args():
    """Parse command line arguments for date range."""
    today = datetime.now(EST).date()
    
    if len(sys.argv) == 1:
        # No args - today only
        start_date = today
        end_date = today
    elif len(sys.argv) == 2:
        # One arg - from that date to now
        start_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        end_date = today
    else:
        # Two args - specific range
        start_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        end_date = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
    
    return start_date, end_date


def utc_to_est(utc_dt):
    """Convert UTC datetime to EST."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
    return utc_dt.astimezone(EST)


def parse_log_file(log_file, start_date, end_date):
    """Parse strategy log file and extract trades."""
    trades = []
    current_trade = None
    
    # Patterns
    signal_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*\[SIGNAL\] (LONG|SHORT) - conf=([\d.]+), ATR=([\d.]+)")
    entry_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*\[STATE\] POS1 ENTRY FILLED @ ([\d.]+)")
    submit_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*\[SUBMIT\] POS1: (LONG|SHORT) (\d+) units.*SL=([\d.]+), TP=([\d.]+)")
    tp_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*\[STATE\] POS1 TP HIT @ ([\d.]+) \(PnL: \$([-\d.]+)\)")
    sl_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*\[STATE\] POS1 SL HIT @ ([\d.]+) \(PnL: \$([-\d.]+)\)")
    close_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*\[STATE\] ALL POSITIONS CLOSED")
    
    # Convert dates to datetime for comparison (in EST)
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=EST)
    end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=EST)
    
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            # Check for SIGNAL
            match = signal_pattern.search(line)
            if match:
                timestamp_str, direction, confidence, atr = match.groups()
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                timestamp_est = utc_to_est(timestamp)
                
                # Check if within date range
                if start_dt <= timestamp_est <= end_dt:
                    current_trade = {
                        'signal_time': timestamp_est,
                        'direction': direction,
                        'confidence': float(confidence),
                        'atr': float(atr),
                        'entry_price': None,
                        'exit_price': None,
                        'exit_time': None,
                        'pnl': None,
                        'result': None,
                        'sl': None,
                        'tp': None,
                        'size': None
                    }
                continue
            
            # Check for SUBMIT (get SL/TP/size)
            if current_trade:
                match = submit_pattern.search(line)
                if match:
                    _, _, size, sl, tp = match.groups()
                    current_trade['size'] = int(size)
                    current_trade['sl'] = float(sl)
                    current_trade['tp'] = float(tp)
                    continue
            
            # Check for ENTRY FILLED
            if current_trade:
                match = entry_pattern.search(line)
                if match:
                    _, entry_price = match.groups()
                    current_trade['entry_price'] = float(entry_price)
                    continue
            
            # Check for TP HIT
            if current_trade:
                match = tp_pattern.search(line)
                if match:
                    timestamp_str, exit_price, pnl = match.groups()
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    current_trade['exit_time'] = utc_to_est(timestamp)
                    current_trade['exit_price'] = float(exit_price)
                    current_trade['pnl'] = float(pnl)
                    current_trade['result'] = 'TP'
                    continue
            
            # Check for SL HIT
            if current_trade:
                match = sl_pattern.search(line)
                if match:
                    timestamp_str, exit_price, pnl = match.groups()
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    current_trade['exit_time'] = utc_to_est(timestamp)
                    current_trade['exit_price'] = float(exit_price)
                    current_trade['pnl'] = float(pnl)
                    current_trade['result'] = 'SL'
                    continue
            
            # Check for ALL POSITIONS CLOSED
            if current_trade:
                match = close_pattern.search(line)
                if match:
                    if current_trade['pnl'] is not None:
                        trades.append(current_trade)
                    current_trade = None
    
    return trades


def get_account_info():
    """Get current account info from NautilusTrader logs."""
    # Find the latest TRADER-V2 log file in project root
    project_root = Path(__file__).parent
    trader_logs = list(project_root.glob("TRADER-V2-001_*.log"))
    
    if not trader_logs:
        return None
    
    # Get the most recent log file
    latest_log = max(trader_logs, key=lambda p: p.stat().st_mtime)
    
    try:
        # Read last portion of file looking for account summary
        with open(latest_log, 'r', encoding='utf-8') as f:
            # Seek to end and read last 100KB
            f.seek(0, 2)  # End of file
            file_size = f.tell()
            read_size = min(100000, file_size)
            f.seek(max(0, file_size - read_size))
            content = f.read()
        
        # Look for NetLiquidation in the account summary dict
        pattern = re.compile(r"'NetLiquidation':\s*([\d.]+)")
        matches = pattern.findall(content)
        if matches:
            return float(matches[-1])  # Return most recent
    except Exception:
        pass
    
    return None


def print_report(trades, start_date, end_date):
    """Print formatted trade analysis report."""
    print("\n" + "=" * 60)
    print("TRADE ANALYSIS REPORT")
    print("=" * 60)
    print(f"Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"Generated: {datetime.now(EST).strftime('%Y-%m-%d %H:%M:%S')} EST")
    print("=" * 60)
    
    # Account info
    account_balance = get_account_info()
    if account_balance:
        print(f"\nCurrent Account (NetLiq): ${account_balance:,.2f}")
    else:
        print("\n(Account balance not available in logs)")
    
    if not trades:
        print("\nNo trades found in the specified period.")
        print("=" * 60)
        return
    
    # Summary statistics
    total_trades = len(trades)
    wins = sum(1 for t in trades if t['pnl'] > 0)
    losses = sum(1 for t in trades if t['pnl'] <= 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    total_pnl = sum(t['pnl'] for t in trades)
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
    
    # Best/worst trades
    best_trade = max(trades, key=lambda t: t['pnl'])
    worst_trade = min(trades, key=lambda t: t['pnl'])
    
    print("\n" + "-" * 60)
    print("SUMMARY")
    print("-" * 60)
    print(f"{'Total Trades':<15} {total_trades:>8}")
    print(f"{'Wins':<15} {wins:>8}")
    print(f"{'Losses':<15} {losses:>8}")
    print(f"{'Win Rate':<15} {win_rate:>7.1f}%")
    print(f"{'Total PnL':<15} ${total_pnl:>+10,.2f}")
    print(f"{'Average PnL':<15} ${avg_pnl:>+10,.2f}")
    print(f"{'Best Trade':<15} ${best_trade['pnl']:>+10,.2f}")
    print(f"{'Worst Trade':<15} ${worst_trade['pnl']:>+10,.2f}")
    
    # Daily breakdown
    daily_pnl = defaultdict(lambda: {'pnl': 0, 'trades': 0, 'wins': 0})
    for trade in trades:
        day = trade['signal_time'].date()
        daily_pnl[day]['pnl'] += trade['pnl']
        daily_pnl[day]['trades'] += 1
        if trade['pnl'] > 0:
            daily_pnl[day]['wins'] += 1
    
    if len(daily_pnl) > 1:
        print("\n" + "-" * 60)
        print("DAILY BREAKDOWN")
        print("-" * 60)
        print(f"{'Date':<12} {'Trades':>8} {'Wins':>6} {'Win%':>8} {'PnL':>12}")
        print("-" * 60)
        for day in sorted(daily_pnl.keys()):
            data = daily_pnl[day]
            day_win_rate = (data['wins'] / data['trades'] * 100) if data['trades'] > 0 else 0
            print(f"{day.strftime('%Y-%m-%d'):<12} {data['trades']:>8} {data['wins']:>6} {day_win_rate:>7.1f}% ${data['pnl']:>+10,.2f}")
        print("-" * 60)
        print(f"{'TOTAL':<12} {total_trades:>8} {wins:>6} {win_rate:>7.1f}% ${total_pnl:>+10,.2f}")
    
    # Trade list
    print("\n" + "-" * 60)
    print("TRADE LIST")
    print("-" * 60)
    print(f"{'#':<3} {'Time (EST)':<14} {'Dir':<6} {'Entry':>8} {'Exit':>8} {'Res':<3} {'PnL':>8} {'Conf':>5}")
    print("-" * 60)
    
    for i, trade in enumerate(trades, 1):
        signal_time = trade['signal_time'].strftime('%m/%d %H:%M')
        direction = trade['direction'][:5]
        entry = f"{trade['entry_price']:.4f}" if trade['entry_price'] else "N/A"
        exit_price = f"{trade['exit_price']:.4f}" if trade['exit_price'] else "N/A"
        result = trade['result'] or "?"
        pnl = f"${trade['pnl']:+.0f}" if trade['pnl'] is not None else "N/A"
        conf = f"{trade['confidence']:.2f}"
        
        print(f"{i:<3} {signal_time:<14} {direction:<6} {entry:>8} {exit_price:>8} {result:<3} {pnl:>8} {conf:>5}")
    
    print("=" * 60)
    print()


def main():
    try:
        start_date, end_date = parse_args()
    except ValueError as e:
        print(f"Error parsing dates: {e}")
        print("Usage: python analyze_trades.py [start_date] [end_date]")
        print("Date format: YYYY-MM-DD")
        sys.exit(1)
    
    if not LOG_FILE.exists():
        print(f"Error: Log file not found: {LOG_FILE}")
        sys.exit(1)
    
    trades = parse_log_file(LOG_FILE, start_date, end_date)
    print_report(trades, start_date, end_date)


if __name__ == "__main__":
    main()
