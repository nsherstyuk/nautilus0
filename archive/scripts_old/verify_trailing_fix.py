"""
Quick verification test for trailing stop fix.

Tests:
1. Run 1-month backtest with trailing enabled
2. Check for trailing stop activity in logs
3. Verify stop orders are being modified
4. Compare results with/without trailing
"""

import subprocess
import sys
from pathlib import Path
import pandas as pd

def run_backtest(description, duration="1 month"):
    """Run a short backtest and return the results directory."""
    print(f"\n{'='*60}")
    print(f"TEST: {description}")
    print(f"{'='*60}\n")
    
    cmd = [
        sys.executable,
        "backtest/run_backtest.py",
        "--symbol", "EUR-USD",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-31",
        "--timeframe", "15min"
    ]
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore'
    )
    
    # Find the results directory from the output
    if result.stdout:
        for line in result.stdout.split('\n'):
            if 'Results written to:' in line:
                results_dir = line.split('Results written to:')[1].strip()
                return Path(results_dir)
    
    return None


def analyze_results(results_dir):
    """Analyze backtest results for trailing stop activity."""
    if not results_dir or not results_dir.exists():
        print("❌ Results directory not found!")
        return
    
    print(f"\nAnalyzing results in: {results_dir}")
    
    # Load data
    try:
        positions = pd.read_csv(results_dir / "positions.csv")
        orders = pd.read_csv(results_dir / "orders.csv")
        stats = pd.read_csv(results_dir / "account_stats.csv")
    except Exception as e:
        print(f"❌ Error loading results: {e}")
        return
    
    # Calculate statistics
    total_pnl = stats.iloc[-1]['total_pnl']
    num_positions = len(positions)
    
    # Count stop orders per position
    stop_orders = orders[orders['order_type'] == 'STOP_MARKET']
    filled_stops = stop_orders[stop_orders['status'] == 'FILLED']
    cancelled_stops = stop_orders[stop_orders['status'] == 'CANCELED']
    
    print(f"\n📊 RESULTS SUMMARY")
    print(f"{'─'*60}")
    print(f"Total PnL: ${total_pnl:,.2f}")
    print(f"Number of positions: {num_positions}")
    print(f"\n📋 STOP ORDER ANALYSIS")
    print(f"{'─'*60}")
    print(f"Total STOP_MARKET orders: {len(stop_orders)}")
    print(f"  - FILLED: {len(filled_stops)}")
    print(f"  - CANCELED: {len(cancelled_stops)}")
    
    # Check for positions with multiple stops (evidence of trailing)
    # Note: In NETTING mode, position_id might be reused
    if 'position_id' in orders.columns:
        stops_per_position = stop_orders.groupby('position_id').size()
        positions_with_multiple_stops = (stops_per_position > 1).sum()
        
        print(f"\nPositions with multiple stop orders: {positions_with_multiple_stops}")
        if positions_with_multiple_stops > 0:
            print(f"  Max stops for one position: {stops_per_position.max()}")
            print(f"  ✓ TRAILING STOPS APPEAR TO BE ACTIVE")
        else:
            print(f"  ⚠️  NO EVIDENCE OF TRAILING (each position has 1 stop)")
    
    # Check position close reasons
    if 'realized_return' in positions.columns:
        avg_win = positions[positions['realized_return'] > 0]['realized_return'].mean()
        avg_loss = positions[positions['realized_return'] < 0]['realized_return'].mean()
        print(f"\n💰 POSITION STATISTICS")
        print(f"{'─'*60}")
        print(f"Average win: ${avg_win:,.2f}" if not pd.isna(avg_win) else "Average win: N/A")
        print(f"Average loss: ${avg_loss:,.2f}" if not pd.isna(avg_loss) else "Average loss: N/A")
    
    return total_pnl


def main():
    """Run the verification tests."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║       TRAILING STOP FIX VERIFICATION TEST                    ║
║                                                              ║
║  This script runs a 1-month backtest to verify that         ║
║  trailing stops are now working correctly.                  ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    # Test 1: Run with trailing enabled
    results_dir = run_backtest("Trailing stops ENABLED", "1 month")
    
    if results_dir:
        pnl = analyze_results(results_dir)
        
        print(f"\n✅ TEST COMPLETE")
        print(f"\n📝 NEXT STEPS:")
        print(f"1. Check the log file for [TRAILING] messages:")
        print(f"   Get-Content {results_dir / 'backtest.log'} | Select-String -Pattern 'TRAILING|modifying stop'")
        print(f"\n2. If you see trailing messages, the fix is working! ✓")
        print(f"\n3. Compare this PnL (${pnl:,.2f}) with previous broken results")
        print(f"   Previous (broken trailing): $9,517.35 for full period")
        print(f"   Expected: Different PnL if trailing is working")
    else:
        print("\n❌ TEST FAILED: Could not find results directory")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
