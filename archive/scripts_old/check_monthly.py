#!/usr/bin/env python3
"""Quick check of monthly PnL with current config."""
import pandas as pd
from run_mtf_backtest_multi_layer import load_and_prepare_data, calculate_features, simulate_strategy, analyze_by_month
from config.mtf_config import load_mtf_config
from joblib import load
import io, sys

# Load and run with optimized config
config = load_mtf_config()
print("Loading data...")
df = load_and_prepare_data(config)
df = calculate_features(df)
model = load(config.model_path)

print("Running backtest...")
trades = simulate_strategy(df, config, model, logger=None)
df_trades = pd.DataFrame(trades)

# Suppress print from analyze_by_month but get the data
old_stdout = sys.stdout
sys.stdout = io.StringIO()
df_month = analyze_by_month(df_trades)
sys.stdout = old_stdout

# Show monthly breakdown
print()
print("=== MONTHLY PnL BREAKDOWN ===")
for _, row in df_month.iterrows():
    status = " <-- NEGATIVE" if row['total_pnl'] < 0 else ""
    print(f"{row['month']}: ${row['total_pnl']:>10,.0f}{status}")
    
print()
neg_count = len([p for p in df_month['total_pnl'] if p < 0])
print(f"Total PnL: ${df_trades['pnl'].sum():,.0f}")
print(f"Negative months: {neg_count}")
