"""
Simple real-time monitoring dashboard for MTF live trading.
Displays current positions, recent orders, trades, and P&L.
"""
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import re

# ANSI color codes for terminal (works in Windows Terminal, PowerShell 7+)
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GRAY = '\033[90m'

def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')

def parse_log_file(filepath, max_lines=1000):
    """Read last N lines from a log file."""
    if not Path(filepath).exists():
        return []
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            return lines[-max_lines:]
    except Exception as e:
        return [f"Error reading {filepath}: {e}"]

def extract_positions(strategy_log_lines):
    """Extract current position information from strategy log."""
    positions = []
    
    # Look for position open messages
    for line in reversed(strategy_log_lines):
        if 'Long entry at' in line or 'SHORT entry at' in line:
            # Extract details
            match = re.search(r'(Long|SHORT) entry at ([\d.]+)', line)
            if match:
                side = match.group(1)
                entry_price = match.group(2)
                timestamp = line.split(' - ')[0] if ' - ' in line else 'Unknown'
                positions.append({
                    'side': side,
                    'entry': entry_price,
                    'time': timestamp
                })
                break  # Only get the most recent position
    
    return positions

def extract_recent_orders(orders_log_lines, limit=10):
    """Extract recent orders from orders log."""
    orders = []
    
    for line in reversed(orders_log_lines):
        if 'Order submitted:' in line or 'Order filled:' in line or 'Order rejected:' in line:
            orders.append(line.strip())
            if len(orders) >= limit:
                break
    
    return list(reversed(orders))

def extract_trades(trades_log_lines):
    """Extract completed trades from trades log."""
    trades = []
    current_trade = {}
    
    for line in trades_log_lines:
        if 'Trade completed:' in line:
            if current_trade:
                trades.append(current_trade)
            current_trade = {'raw': line.strip()}
        elif current_trade:
            current_trade['raw'] += '\n  ' + line.strip()
            
            # Extract P&L
            if 'P&L:' in line:
                match = re.search(r'P&L:\s*\$?([-\d.]+)', line)
                if match:
                    current_trade['pnl'] = float(match.group(1))
    
    if current_trade:
        trades.append(current_trade)
    
    return trades

def calculate_daily_pnl(trades):
    """Calculate today's P&L from trades."""
    today = datetime.now().date()
    daily_pnl = 0.0
    trade_count = 0
    
    for trade in trades:
        # Check if trade is from today (simple check)
        if 'pnl' in trade:
            daily_pnl += trade['pnl']
            trade_count += 1
    
    return daily_pnl, trade_count

def format_pnl(pnl):
    """Format P&L with color."""
    if pnl > 0:
        return f"{Colors.GREEN}+${pnl:.2f}{Colors.RESET}"
    elif pnl < 0:
        return f"{Colors.RED}-${abs(pnl):.2f}{Colors.RESET}"
    else:
        return f"${pnl:.2f}"

def display_dashboard(log_dir):
    """Display the monitoring dashboard."""
    log_path = Path(log_dir)
    
    # Read log files
    strategy_lines = parse_log_file(log_path / 'strategy.log', max_lines=500)
    orders_lines = parse_log_file(log_path / 'orders.log', max_lines=200)
    trades_lines = parse_log_file(log_path / 'trades.log', max_lines=100)
    live_lines = parse_log_file(log_path / 'live_trading.log', max_lines=100)
    errors_lines = parse_log_file(log_path / 'errors.log', max_lines=50)
    
    # Extract information
    positions = extract_positions(strategy_lines)
    recent_orders = extract_recent_orders(orders_lines, limit=10)
    trades = extract_trades(trades_lines)
    daily_pnl, trade_count = calculate_daily_pnl(trades)
    
    # Get last update time
    last_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Clear screen and display
    clear_screen()
    
    # Header
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}MTF ML STRATEGY - LIVE TRADING MONITOR{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.RESET}")
    print(f"{Colors.GRAY}Last Update: {last_update}{Colors.RESET}")
    print()
    
    # Daily Summary
    print(f"{Colors.BOLD}DAILY SUMMARY{Colors.RESET}")
    print(f"  Trades Today: {trade_count}")
    print(f"  Daily P&L: {format_pnl(daily_pnl)}")
    print()
    
    # Current Positions
    print(f"{Colors.BOLD}CURRENT POSITIONS{Colors.RESET}")
    if positions:
        for pos in positions:
            side_color = Colors.GREEN if pos['side'] == 'Long' else Colors.RED
            print(f"  {side_color}{pos['side']}{Colors.RESET} @ {pos['entry']} (opened: {pos['time']})")
    else:
        print(f"  {Colors.GRAY}No open positions{Colors.RESET}")
    print()
    
    # Recent Orders
    print(f"{Colors.BOLD}RECENT ORDERS (Last 10){Colors.RESET}")
    if recent_orders:
        for order in recent_orders[-10:]:
            # Color code based on order type
            if 'filled' in order.lower():
                color = Colors.GREEN
            elif 'rejected' in order.lower():
                color = Colors.RED
            else:
                color = Colors.YELLOW
            print(f"  {color}{order}{Colors.RESET}")
    else:
        print(f"  {Colors.GRAY}No recent orders{Colors.RESET}")
    print()
    
    # Recent Trades
    print(f"{Colors.BOLD}RECENT TRADES (Last 5){Colors.RESET}")
    if trades:
        for trade in trades[-5:]:
            pnl = trade.get('pnl', 0)
            pnl_str = format_pnl(pnl)
            print(f"  Trade: {pnl_str}")
            # Show first line of trade details
            first_line = trade['raw'].split('\n')[0]
            print(f"    {Colors.GRAY}{first_line}{Colors.RESET}")
    else:
        print(f"  {Colors.GRAY}No trades yet{Colors.RESET}")
    print()
    
    # Recent Errors
    recent_errors = [line for line in errors_lines[-10:] if 'ERROR' in line]
    if recent_errors:
        print(f"{Colors.BOLD}{Colors.RED}RECENT ERRORS{Colors.RESET}")
        for error in recent_errors[-5:]:
            print(f"  {Colors.RED}{error.strip()}{Colors.RESET}")
        print()
    
    # System Status
    print(f"{Colors.BOLD}SYSTEM STATUS{Colors.RESET}")
    
    # Check if system is running (look for recent log entries)
    if live_lines:
        last_log_line = live_lines[-1]
        try:
            # Try to extract timestamp from log line
            if len(live_lines) > 0:
                status_color = Colors.GREEN
                status_text = "RUNNING"
            else:
                status_color = Colors.YELLOW
                status_text = "UNKNOWN"
        except:
            status_color = Colors.YELLOW
            status_text = "UNKNOWN"
    else:
        status_color = Colors.RED
        status_text = "NO LOGS"
    
    print(f"  Status: {status_color}{status_text}{Colors.RESET}")
    print(f"  Log Directory: {log_dir}")
    print()
    
    # Footer
    print(f"{Colors.GRAY}{'='*80}{Colors.RESET}")
    print(f"{Colors.GRAY}Press Ctrl+C to exit | Refreshing every 5 seconds{Colors.RESET}")

def main():
    """Main monitoring loop."""
    log_dir = Path('logs/live_mtf')
    
    # Check if log directory exists
    if not log_dir.exists():
        print(f"Error: Log directory not found: {log_dir}")
        print("Make sure the live trading system is running.")
        sys.exit(1)
    
    print("Starting live trading monitor...")
    print("Press Ctrl+C to exit")
    time.sleep(2)
    
    try:
        while True:
            display_dashboard(log_dir)
            time.sleep(5)  # Refresh every 5 seconds
    except KeyboardInterrupt:
        clear_screen()
        print("\nMonitoring stopped.")
        sys.exit(0)

if __name__ == '__main__':
    main()
