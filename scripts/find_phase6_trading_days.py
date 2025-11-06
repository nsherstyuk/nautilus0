"""
Find and analyze Phase 6 backtest trading days.
"""
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

# Load Phase 6 results
phase6_file = Path("optimization/results/phase6_refinement_results_top_10.json")
data = json.load(open(phase6_file))
best = data[0]

print("=" * 80)
print("PHASE 6 SETUP - TRADING DAYS ANALYSIS")
print("=" * 80)
print()

print(f"Phase 6 Best Setup:")
print(f"  Run ID: {best['run_id']}")
print(f"  Total Trades: {best['trade_count']}")
print(f"  Sharpe Ratio: {best['sharpe_ratio']:.3f}")
print(f"  Total PnL: ${best['total_pnl']:.2f}")
print()

# Search for Phase 6 backtest by checking recent directories
# Phase 6 was run around Oct 24, 2025 based on config file timestamps
results_dir = Path("logs/backtest_results")
dirs = [d for d in results_dir.iterdir() if d.is_dir() and "EUR-USD_" in d.name]

# Sort by modification time (newest first)
dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)

print(f"Searching {len(dirs)} backtest directories for Phase 6 match...")
print("(Looking for: 58 trades, Sharpe ~0.48, PnL ~$10,859)")
print()

found = False
for d in dirs[:50]:  # Check top 50 most recent
    stats_file = d / "performance_stats.json"
    positions_file = d / "positions.csv"
    
    if not stats_file.exists() or not positions_file.exists():
        continue
        
    try:
        with open(stats_file) as f:
            stats = json.load(f)
        trades = stats.get("general", {}).get("Total trades", 0)
        sharpe = stats.get("general", {}).get("Sharpe ratio", 0)
        pnl = stats.get("pnls", {}).get("PnL (total)", 0)
        
        # Phase 6 has 58 trades, Sharpe ~0.48, PnL ~$10,859
        if trades == 58 and abs(sharpe - 0.48) < 0.05 and abs(pnl - 10859) < 100:
            print(f"FOUND PHASE 6 BACKTEST: {d.name}")
            print(f"  Trades: {trades}, Sharpe: {sharpe:.3f}, PnL: ${pnl:.2f}")
            print()
            
            # Analyze trading days
            df = pd.read_csv(positions_file)
            if len(df) > 0:
                df["ts_opened"] = pd.to_datetime(df["ts_opened"])
                df["trade_date"] = df["ts_opened"].dt.date
                
                min_date = df["trade_date"].min()
                max_date = df["trade_date"].max()
                all_dates = pd.date_range(start=min_date, end=max_date, freq='D').date
                
                dates_with_trades = set(df["trade_date"].unique())
                dates_without_trades = set(all_dates) - dates_with_trades
                
                print(f"Backtest Period: {min_date} to {max_date}")
                print(f"Total Days: {len(all_dates)}")
                print()
                print(f"Days WITH Trades: {len(dates_with_trades)} ({100*len(dates_with_trades)/len(all_dates):.1f}%)")
                print(f"Days WITHOUT Trades: {len(dates_without_trades)} ({100*len(dates_without_trades)/len(all_dates):.1f}%)")
                print()
                
                # Show trade distribution
                trades_per_day = df.groupby("trade_date").size()
                print(f"Trade Distribution:")
                print(f"  Average trades per day: {trades_per_day.mean():.1f}")
                print(f"  Max trades in a single day: {trades_per_day.max()}")
                print(f"  Min trades in a single day: {trades_per_day.min()}")
                
                found = True
                break
    except Exception as e:
        continue

if not found:
    print("Phase 6 backtest directory not found in recent results.")
    print("Estimating from Phase 6 metrics:")
    print(f"  Total Trades: {best['trade_count']}")
    print(f"  Period: 2025-01-01 to 2025-10-30 = 303 days")
    print()
    print("Assuming trades are distributed across days:")
    print(f"  Minimum days with trades: {best['trade_count']} (if 1 trade per day)")
    print(f"  Maximum days without trades: ~{303 - best['trade_count']} days")
    print(f"  Percentage: ~{100*(303-best['trade_count'])/303:.1f}%")

print()
print("=" * 80)
