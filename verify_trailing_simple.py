#!/usr/bin/env python3
"""Simple script to verify trailing stop fix by checking logs and results."""

import re
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent

# Check logs
log_file = PROJECT_ROOT / "logs" / "application.log"
if log_file.exists():
    with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    print("=" * 80)
    print("CHECKING LOGS FOR TRAILING STOP ACTIVITY")
    print("=" * 80)
    
    # Check version
    version = re.search(r'TRAILING STOP FIX v(\d+\.\d+)', content)
    if version:
        print(f"[OK] Fix version found: v{version.group(1)}")
    else:
        print("[WARN] No fix version found")
    
    # Count activations
    activations = len(re.findall(r'TRAILING ACTIVATED', content, re.I))
    print(f"[INFO] Trailing activations: {activations}")
    
    # Count modifications
    modifications = len(re.findall(r'MODIFYING ORDER', content, re.I))
    print(f"[INFO] Order modifications: {modifications}")
    
    # Count clears
    clears = len(re.findall(r'order reference cleared', content, re.I))
    print(f"[INFO] Order reference clears: {clears}")
    
    # Show sample
    if modifications > 0:
        print("\n[OK] Found trailing stop modifications - fix appears to work!")
    elif activations > 0:
        print("\n[WARN] Trailing activated but no modifications found")
    else:
        print("\n[INFO] No trailing activity found - may need trades that reach activation threshold")
    
    # Check for strategy initialization
    init = re.search(r'STRATEGY INITIALIZED.*?v(\d+\.\d+)', content)
    if init:
        print(f"\n[OK] Strategy initialized with version: v{init.group(1)}")

# Check latest backtest results
results_dir = PROJECT_ROOT / "logs" / "backtest_results"
if results_dir.exists():
    folders = sorted([f for f in results_dir.iterdir() if f.is_dir()], 
                     key=lambda x: x.stat().st_mtime, reverse=True)
    if folders:
        latest = folders[0]
        print("\n" + "=" * 80)
        print(f"CHECKING LATEST BACKTEST: {latest.name}")
        print("=" * 80)
        
        positions_file = latest / "positions.csv"
        if positions_file.exists():
            df = pd.read_csv(positions_file)
            print(f"[INFO] Total positions: {len(df)}")
            
            if len(df) > 0:
                print(f"[INFO] Sample PnL range: ${df['realized_pnl'].min():.2f} to ${df['realized_pnl'].max():.2f}")
                print(f"[INFO] Total PnL: ${df['realized_pnl'].sum():.2f}")
                
                # Check orders
                orders_file = latest / "orders.csv"
                if orders_file.exists():
                    orders_df = pd.read_csv(orders_file)
                    stop_orders = orders_df[orders_df['order_type'].str.contains('STOP', case=False, na=False)]
                    print(f"[INFO] Total stop orders: {len(stop_orders)}")
                    
                    if 'position_id' in stop_orders.columns:
                        stops_per_pos = stop_orders.groupby('position_id').size()
                        multiple = (stops_per_pos > 1).sum()
                        print(f"[INFO] Positions with multiple stops: {multiple}")
                        if multiple > 0:
                            print("[OK] Evidence of trailing stops found!")
            else:
                print("[WARN] No positions found in backtest")

