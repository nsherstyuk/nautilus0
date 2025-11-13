"""Analyze backtest results and provide monthly PnL breakdown."""
import pandas as pd
from pathlib import Path
import sys

def analyze_monthly_pnl(backtest_folder):
    """Analyze monthly PnL from backtest positions."""
    folder = Path(backtest_folder)
    positions_file = folder / 'positions.csv'
    
    if not positions_file.exists():
        print(f"ERROR: positions.csv not found in {folder}")
        return
    
    # Load positions data
    df = pd.read_csv(positions_file, parse_dates=['ts_opened', 'ts_closed'])
    
    # Clean realized_pnl column (remove ' USD' suffix)
    df['realized_pnl'] = df['realized_pnl'].str.replace(' USD', '', regex=False).astype(float)
    
    # Extract month from closing timestamp
    df['month'] = df['ts_closed'].dt.to_period('M')
    
    # Group by month and calculate stats
    monthly = df.groupby('month').agg(
        trades=('realized_pnl', 'size'),
        pnl=('realized_pnl', 'sum')
    ).sort_index()
    
    # Print results
    print("=" * 60)
    print(f"BACKTEST: {folder.name}")
    print("=" * 60)
    print("\nMONTHLY PNL BREAKDOWN:")
    print("-" * 60)
    print(f"{'MONTH':<15} {'TRADES':>10} {'PNL':>15}")
    print("-" * 60)
    
    total_pnl = 0
    total_trades = 0
    negative_months = []
    
    for month, row in monthly.iterrows():
        trades = int(row['trades'])
        pnl = row['pnl']
        total_pnl += pnl
        total_trades += trades
        
        status = "✓" if pnl >= 0 else "✗"
        print(f"{str(month):<15} {trades:>10} {pnl:>14.2f} {status}")
        
        if pnl < 0:
            negative_months.append((str(month), pnl, trades))
    
    print("-" * 60)
    print(f"{'TOTAL':<15} {total_trades:>10} {total_pnl:>14.2f}")
    print("=" * 60)
    
    # Summary of negative months
    if negative_months:
        print(f"\nUNPROFITABLE MONTHS: {len(negative_months)}")
        print("-" * 60)
        for month, pnl, trades in negative_months:
            print(f"  {month}: {pnl:.2f} USD ({trades} trades)")
    else:
        print("\n✓ All months were profitable!")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        backtest_folder = sys.argv[1]
    else:
        # Default to the specified backtest
        backtest_folder = r'c:\nautilus0\logs\backtest_results\EUR-USD_20251109_211155'
    
    analyze_monthly_pnl(backtest_folder)
