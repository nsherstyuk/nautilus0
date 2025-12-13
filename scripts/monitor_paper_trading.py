#!/usr/bin/env python3
"""
Monitor paper trading performance and compare with backtest expectations.
Run this daily during paper trading phase.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import glob

# Expected performance (from backtest)
EXPECTED_METRICS = {
    'win_rate': 0.451,
    'avg_win': 181.78,
    'avg_loss': -131.83,
    'rr_ratio': 1.38,
    'trades_per_day': 5.0,
    'profit_factor': 1.13
}

def load_trade_logs():
    """Load trade logs from CSV files."""
    log_dir = PROJECT_ROOT / "logs"
    
    # Find all trade log files
    trade_files = glob.glob(str(log_dir / "trades_*.csv"))
    
    if not trade_files:
        print("❌ No trade log files found in logs/ directory")
        print("   Make sure strategy is logging trades to CSV")
        return None
    
    # Load and combine all trade logs
    dfs = []
    for file in trade_files:
        try:
            df = pd.read_csv(file)
            dfs.append(df)
        except Exception as e:
            print(f"⚠️  Could not load {file}: {e}")
    
    if not dfs:
        return None
    
    df_all = pd.concat(dfs, ignore_index=True)
    df_all['timestamp'] = pd.to_datetime(df_all['timestamp'])
    
    return df_all

def analyze_performance(df):
    """Analyze trading performance."""
    if df is None or len(df) == 0:
        return None
    
    # Calculate metrics
    total_trades = len(df)
    winning_trades = len(df[df['pnl'] > 0])
    losing_trades = len(df[df['pnl'] < 0])
    
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    
    avg_win = df[df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = df[df['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0
    
    rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    total_pnl = df['pnl'].sum()
    
    gross_profit = df[df['pnl'] > 0]['pnl'].sum() if winning_trades > 0 else 0
    gross_loss = abs(df[df['pnl'] < 0]['pnl'].sum()) if losing_trades > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    
    # Calculate trades per day
    if len(df) > 0:
        first_trade = df['timestamp'].min()
        last_trade = df['timestamp'].max()
        days = (last_trade - first_trade).days + 1
        trades_per_day = total_trades / days if days > 0 else 0
    else:
        trades_per_day = 0
    
    # Long/Short balance
    long_trades = len(df[df['side'] == 'LONG'])
    short_trades = len(df[df['side'] == 'SHORT'])
    
    return {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'rr_ratio': rr_ratio,
        'total_pnl': total_pnl,
        'profit_factor': profit_factor,
        'trades_per_day': trades_per_day,
        'long_trades': long_trades,
        'short_trades': short_trades
    }

def compare_with_backtest(actual):
    """Compare actual performance with backtest expectations."""
    print("\n" + "="*80)
    print("PERFORMANCE COMPARISON")
    print("="*80)
    
    print(f"\n{'Metric':<20} {'Expected':<15} {'Actual':<15} {'Status':<10}")
    print("-"*60)
    
    # Win Rate
    expected_wr = EXPECTED_METRICS['win_rate'] * 100
    actual_wr = actual['win_rate'] * 100
    deviation_wr = abs(actual_wr - expected_wr) / expected_wr * 100
    status_wr = "✅ OK" if deviation_wr < 15 else "⚠️  WARNING" if deviation_wr < 25 else "❌ ALERT"
    print(f"{'Win Rate':<20} {expected_wr:<14.1f}% {actual_wr:<14.1f}% {status_wr}")
    
    # R/R Ratio
    expected_rr = EXPECTED_METRICS['rr_ratio']
    actual_rr = actual['rr_ratio']
    deviation_rr = abs(actual_rr - expected_rr) / expected_rr * 100
    status_rr = "✅ OK" if deviation_rr < 20 else "⚠️  WARNING" if deviation_rr < 35 else "❌ ALERT"
    print(f"{'R/R Ratio':<20} {expected_rr:<14.2f} {actual_rr:<14.2f} {status_rr}")
    
    # Profit Factor
    expected_pf = EXPECTED_METRICS['profit_factor']
    actual_pf = actual['profit_factor']
    deviation_pf = abs(actual_pf - expected_pf) / expected_pf * 100
    status_pf = "✅ OK" if deviation_pf < 20 else "⚠️  WARNING" if deviation_pf < 35 else "❌ ALERT"
    print(f"{'Profit Factor':<20} {expected_pf:<14.2f} {actual_pf:<14.2f} {status_pf}")
    
    # Trades per day
    expected_tpd = EXPECTED_METRICS['trades_per_day']
    actual_tpd = actual['trades_per_day']
    deviation_tpd = abs(actual_tpd - expected_tpd) / expected_tpd * 100
    status_tpd = "✅ OK" if deviation_tpd < 30 else "⚠️  WARNING" if deviation_tpd < 50 else "❌ ALERT"
    print(f"{'Trades/Day':<20} {expected_tpd:<14.1f} {actual_tpd:<14.1f} {status_tpd}")
    
    # Overall assessment
    print("\n" + "="*80)
    
    alerts = sum([1 for s in [status_wr, status_rr, status_pf, status_tpd] if "❌" in s])
    warnings = sum([1 for s in [status_wr, status_rr, status_pf, status_tpd] if "⚠️" in s])
    
    if alerts > 0:
        print("❌ CRITICAL: Performance significantly below backtest expectations")
        print("   Action: STOP paper trading and investigate issues")
    elif warnings > 1:
        print("⚠️  WARNING: Performance deviating from backtest")
        print("   Action: Monitor closely, investigate if continues")
    else:
        print("✅ GOOD: Performance within acceptable range of backtest")
        print("   Action: Continue paper trading")

def main():
    """Main monitoring function."""
    print("="*80)
    print("PAPER TRADING MONITOR")
    print("="*80)
    print(f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Load trade logs
    print("\nLoading trade logs...")
    df = load_trade_logs()
    
    if df is None or len(df) == 0:
        print("\n❌ No trades found")
        print("   Either strategy hasn't executed any trades yet,")
        print("   or trade logging is not configured correctly.")
        return
    
    # Analyze performance
    actual = analyze_performance(df)
    
    print(f"\n✅ Loaded {actual['total_trades']} trades")
    
    # Display summary
    print("\n" + "="*80)
    print("CURRENT PERFORMANCE")
    print("="*80)
    
    print(f"\nTotal Trades: {actual['total_trades']}")
    print(f"  Long: {actual['long_trades']} ({actual['long_trades']/actual['total_trades']*100:.1f}%)")
    print(f"  Short: {actual['short_trades']} ({actual['short_trades']/actual['total_trades']*100:.1f}%)")
    
    print(f"\nWin/Loss:")
    print(f"  Winning: {actual['winning_trades']}")
    print(f"  Losing: {actual['losing_trades']}")
    print(f"  Win Rate: {actual['win_rate']*100:.1f}%")
    
    print(f"\nP&L:")
    print(f"  Total: ${actual['total_pnl']:,.2f}")
    print(f"  Avg Win: ${actual['avg_win']:,.2f}")
    print(f"  Avg Loss: ${actual['avg_loss']:,.2f}")
    print(f"  R/R Ratio: {actual['rr_ratio']:.2f}")
    print(f"  Profit Factor: {actual['profit_factor']:.2f}")
    
    print(f"\nActivity:")
    print(f"  Trades/Day: {actual['trades_per_day']:.1f}")
    
    # Compare with backtest
    compare_with_backtest(actual)
    
    print("\n" + "="*80)
    print("END OF REPORT")
    print("="*80)

if __name__ == "__main__":
    main()
