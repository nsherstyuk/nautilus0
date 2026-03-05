"""
Launcher for sequential multi-group parameter optimization.

Runs optimize_sequential_all_groups.py in a new console window
(required because Nautilus BacktestEngine needs an interactive terminal).
Monitors progress via group CSV files.
"""
import subprocess
import sys
import time
import os
import pandas as pd
from pathlib import Path
from datetime import datetime

DATE_TAG = datetime.now().strftime("%Y%m%d")

GROUP_FILES = {
    "Group1 SL/TP/MAMA":        (f"opt_group1_sl_tp_mama_{DATE_TAG}.csv",       36),
    "Group2 Pred Thresholds":   (f"opt_group2_pred_thresholds_{DATE_TAG}.csv",   16),
    "Group3 Entry Confirm":     (f"opt_group3_entry_confirm_{DATE_TAG}.csv",      12),
    "Group4 ATR Gate":          (f"opt_group4_atr_gate_{DATE_TAG}.csv",           12),
}

TRACE_FILE     = Path("seq_opt_trace.txt")
CHECK_INTERVAL = 60  # seconds


def show_progress():
    total_done  = 0
    total_all   = sum(n for _, n in GROUP_FILES.values())
    active_group = None
    for name, (csv_path, expected) in GROUP_FILES.items():
        p = Path(csv_path)
        if p.exists():
            try:
                df   = pd.read_csv(p)
                done = len(df)
                total_done += done
                if done < expected:
                    active_group = (name, done, expected, df)
                    break  # this is the group currently running
            except Exception:
                pass

    pct = total_done / total_all * 100 if total_all else 0
    print(f"  Overall: {total_done}/{total_all} combos ({pct:.0f}%)", flush=True)

    if active_group:
        name, done, expected, df = active_group
        remaining = expected - done
        if done > 0:
            # Estimate time per combo from trace
            best = df.sort_values("score", ascending=False).iloc[0]
            avg_s = df["duration_s"].mean() if "duration_s" in df.columns else None
            eta_min = (remaining * avg_s / 60) if avg_s else None
            eta_str = f"  ETA ~{eta_min:.0f} min" if eta_min else ""
            print(
                f"  Active: {name}  {done}/{expected}{eta_str}",
                flush=True,
            )
            print(
                f"  Best so far: {best.to_dict()}",
                flush=True,
            )
        else:
            print(f"  Next group starting: {name}", flush=True)


def main():
    script = Path(__file__).parent / "optimize_sequential_all_groups.py"

    print("Launching sequential multi-group optimization in a new console window...", flush=True)
    print(f"Groups: {' → '.join(GROUP_FILES.keys())}", flush=True)
    print(f"Script: {script}", flush=True)

    p = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(Path(__file__).parent),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    print(f"PID: {p.pid}", flush=True)

    start_time = time.time()

    while p.poll() is None:
        time.sleep(CHECK_INTERVAL)
        elapsed = (time.time() - start_time) / 60
        print(f"\n[{elapsed:.0f}m] Progress check:", flush=True)

        # Show trace tail
        if TRACE_FILE.exists():
            lines = TRACE_FILE.read_text().strip().splitlines()
            recent = lines[-3:] if len(lines) >= 3 else lines
            print(f"  Trace: {' | '.join(recent)}", flush=True)

        show_progress()

    exit_code = p.returncode
    elapsed   = (time.time() - start_time) / 3600
    print(f"\nOptimization finished. Exit code: {exit_code}. Total time: {elapsed:.1f} h", flush=True)

    # Final summary
    final_params = Path(f"opt_final_params_{DATE_TAG}.txt")
    if final_params.exists():
        print(f"\n{'='*60}", flush=True)
        print("FINAL OPTIMAL PARAMETERS:", flush=True)
        print(final_params.read_text(), flush=True)
    else:
        show_progress()


if __name__ == "__main__":
    main()
