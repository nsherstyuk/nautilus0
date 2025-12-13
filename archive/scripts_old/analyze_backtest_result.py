#!/usr/bin/env python3
"""
Analyze a specific backtest result by timestamp.
Usage: python analyze_backtest_result.py MTF_ML_20251127_202724
"""
import sys
import json
from pathlib import Path
from datetime import datetime

def analyze_backtest(result_name: str):
    """Analyze a backtest result by name."""
    
    # Find the result directory
    results_dir = Path("logs/backtest_results")
    result_path = results_dir / result_name
    
    if not result_path.exists():
        print(f"❌ Result not found: {result_path}")
        print(f"\nAvailable results:")
        for item in sorted(results_dir.glob("MTF_ML_*"), reverse=True):
            if item.is_dir():
                print(f"  - {item.name}")
        return 1
    
    print("="*80)
    print(f"BACKTEST RESULT ANALYSIS: {result_name}")
    print("="*80)
    
    # Look for summary file
    summary_file = result_path / "summary.json"
    if summary_file.exists():
        with open(summary_file, 'r') as f:
            summary = json.load(f)
        
        print("\n📊 SUMMARY:")
        print(f"   Period: {summary.get('start_date')} to {summary.get('end_date')}")
        print(f"   Total P&L: ${summary.get('total_pnl', 0):,.2f}")
        print(f"   Return: {summary.get('return_pct', 0):.2f}%")
        print(f"   Total Trades: {summary.get('total_trades', 0)}")
        print(f"   Win Rate: {summary.get('win_rate', 0):.1f}%")
        print(f"   Sharpe Ratio: {summary.get('sharpe_ratio', 0):.2f}")
    
    # Look for trades file
    trades_file = result_path / "trades.csv"
    if trades_file.exists():
        import pandas as pd
        trades = pd.read_csv(trades_file)
        
        print(f"\n📈 TRADES:")
        print(f"   Total: {len(trades)}")
        
        if 'pnl' in trades.columns:
            winning = trades[trades['pnl'] > 0]
            losing = trades[trades['pnl'] < 0]
            
            print(f"   Winning: {len(winning)} (${winning['pnl'].sum():,.2f})")
            print(f"   Losing: {len(losing)} (${losing['pnl'].sum():,.2f})")
            
            if len(winning) > 0:
                print(f"   Avg Win: ${winning['pnl'].mean():,.2f}")
            if len(losing) > 0:
                print(f"   Avg Loss: ${losing['pnl'].mean():,.2f}")
    
    # Look for orders file
    orders_file = result_path / "orders.csv"
    if orders_file.exists():
        import pandas as pd
        orders = pd.read_csv(orders_file)
        print(f"\n📝 ORDERS:")
        print(f"   Total: {len(orders)}")
        
        if 'side' in orders.columns:
            buy_orders = len(orders[orders['side'] == 'BUY'])
            sell_orders = len(orders[orders['side'] == 'SELL'])
            print(f"   Buy: {buy_orders}")
            print(f"   Sell: {sell_orders}")
    
    # Look for positions file
    positions_file = result_path / "positions.csv"
    if positions_file.exists():
        import pandas as pd
        positions = pd.read_csv(positions_file)
        print(f"\n💼 POSITIONS:")
        print(f"   Total: {len(positions)}")
    
    # List all files in the result directory
    print(f"\n📁 FILES:")
    for file in sorted(result_path.glob("*")):
        size = file.stat().st_size
        print(f"   - {file.name} ({size:,} bytes)")
    
    print("\n" + "="*80)
    print(f"Result location: {result_path.absolute()}")
    print("="*80)
    
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_backtest_result.py <result_name>")
        print("\nExample:")
        print("  python analyze_backtest_result.py MTF_ML_20251127_202724")
        print("\nAvailable results:")
        
        results_dir = Path("logs/backtest_results")
        if results_dir.exists():
            for item in sorted(results_dir.glob("MTF_ML_*"), reverse=True)[:10]:
                if item.is_dir():
                    print(f"  - {item.name}")
        sys.exit(1)
    
    result_name = sys.argv[1]
    sys.exit(analyze_backtest(result_name))
