"""
Launcher for parameter optimization.

Runs optimize_fixed_backtest_parameters.py in a new console window
(required because Nautilus BacktestEngine needs an interactive terminal).
Monitors progress via the results CSV file.
"""
import subprocess
import sys
import os
import time
import pandas as pd
from pathlib import Path

RESULTS_FILE = "optimization_results_fixed_20260221.csv"
TOTAL_COMBOS = 36
CHECK_INTERVAL = 60  # seconds between progress reports

def main():
    script = Path(__file__).parent / "optimize_fixed_backtest_parameters.py"
    
    # Launch the optimization in a new console window
    print("Launching optimization in a new console window...", flush=True)
    p = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(Path(__file__).parent),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    print(f"PID: {p.pid}", flush=True)

    start_time = time.time()
    last_count = 0

    while p.poll() is None:
        time.sleep(CHECK_INTERVAL)
        elapsed = time.time() - start_time

        # Read current results
        if Path(RESULTS_FILE).exists():
            try:
                df = pd.read_csv(RESULTS_FILE)
                n = len(df)
                if n > last_count:
                    last_count = n
                    best_row = df.sort_values('score', ascending=False).iloc[0]
                    print(
                        f"[{elapsed/60:.0f}m] Progress: {n}/{TOTAL_COMBOS} done. "
                        f"Best so far: sl={best_row['sl_atr_mult']}, tp1={best_row['tp1_atr_mult']}, "
                        f"tp2={best_row['tp2_atr_mult']}, mama={best_row['mama_min_diff']} "
                        f"→ PnL=${best_row['total_pnl']:.2f}, WR={best_row['win_rate']:.2%}, "
                        f"Score={best_row['score']:.2f}",
                        flush=True,
                    )
                else:
                    print(f"[{elapsed/60:.0f}m] {n}/{TOTAL_COMBOS} combos done (running next...)", flush=True)
            except Exception as e:
                print(f"[{elapsed/60:.0f}m] Could not read results: {e}", flush=True)
        else:
            print(f"[{elapsed/60:.0f}m] Waiting for first result...", flush=True)

    exit_code = p.returncode
    print(f"\nOptimization finished with exit code {exit_code}.", flush=True)

    if Path(RESULTS_FILE).exists():
        df = pd.read_csv(RESULTS_FILE)
        df_sorted = df.sort_values('score', ascending=False)
        print(f"\n{'='*60}", flush=True)
        print(f"OPTIMIZATION COMPLETE — {len(df)}/{TOTAL_COMBOS} combinations", flush=True)
        print(f"{'='*60}", flush=True)
        cols = ['sl_atr_mult', 'tp1_atr_mult', 'tp2_atr_mult', 'mama_min_diff',
                'total_trades', 'total_pnl', 'win_rate', 'max_drawdown', 'score']
        print(df_sorted[cols].head(10).to_string(index=False), flush=True)
    else:
        print("No results file found.", flush=True)


if __name__ == "__main__":
    main()
