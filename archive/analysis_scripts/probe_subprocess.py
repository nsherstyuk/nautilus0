"""Quick probe script to test if subprocess with new console can run a backtest."""
import os
import sys
import time

probe_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_result.txt")

with open(probe_file, "w") as f:
    f.write("started\n")

import pandas as pd
with open(probe_file, "a") as f:
    f.write("pandas_ok\n")

from run_backtest_mtf_v2_entry_confirmed_adaptive import run_v2_entry_confirmed_adaptive_backtest
with open(probe_file, "a") as f:
    f.write("backtest_import_ok\n")

os.environ['MTF2_SL_ATR_MULT'] = '1.5'
os.environ['MTF2_POS1_TP_ATR_MULT'] = '1.2'
os.environ['MTF2_POS2_TP_ATR_MULT'] = '2.0'
os.environ['MTF2_META_FILTER_MAMA_MIN_DIFF'] = '0.0001'

with open(probe_file, "a") as f:
    f.write("calling_backtest\n")

result, results_dir = run_v2_entry_confirmed_adaptive_backtest(
    symbol='EUR/USD', venue='IDEALPRO',
    start_date='2026-01-15', end_date='2026-01-31',
)
import shutil
trades_files = list(__import__('pathlib').Path(results_dir).glob('trades_*.csv'))
df = pd.read_csv(trades_files[0]) if trades_files else pd.DataFrame()
shutil.rmtree(results_dir, ignore_errors=True)

with open(probe_file, "a") as f:
    f.write(f"done: trades={len(df)}, pnl={df['pnl'].sum() if len(df) else 0:.2f}\n")

