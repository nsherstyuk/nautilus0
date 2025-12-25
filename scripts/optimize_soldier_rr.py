import os
import sys
import subprocess
import pandas as pd
import json
from pathlib import Path
from datetime import datetime

# Configuration Grid
GRID = [
    {"tp": 1.0, "sl": 1.0},  # Baseline
    {"tp": 0.8, "sl": 0.6},  # User Suggestion (1.33 R:R)
    {"tp": 1.2, "sl": 0.8},  # 1.5 R:R
    {"tp": 0.6, "sl": 0.6},  # Tight 1:1
]

# Fixed Params
DATASET_START_DATE = "2022-01-01" # Extended range
BACKTEST_START_DATE = "2025-10-01"
BACKTEST_END_DATE = "2025-11-01"
THRESHOLD = 0.65  # Back to 0.65 as 0.55 was too noisy

def run_command(cmd, env=None):
    print(f"Running: {cmd}")
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    
    # Use python from current environment
    if cmd.startswith("python"):
        cmd = f"{sys.executable} {cmd[7:]}"
        
    result = subprocess.run(cmd, shell=True, env=full_env, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running command: {cmd}")
        print(result.stderr)
        return False
    return True

def main():
    results = []
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = Path("backtest_results") / f"MTF_V3_SWEEP_{timestamp}"
    base_dir.mkdir(parents=True, exist_ok=True)

    for params in GRID:
        tp = params["tp"]
        sl = params["sl"]
        print(f"\n=== Testing TP={tp} SL={sl} ===")
        
        # 1. Generate Dataset
        # We use a temporary dataset path to avoid overwriting the main one if we want to preserve it,
        # but actually, training script reads from a specific path. Let's use a temp path.
        dataset_path = f"logs/live_mtf/temp_sweep_dataset_{tp}_{sl}.csv"
        
        cmd_gen = (
            f"python scripts/build_hmtf_stitched_dataset.py "
            f"--start {DATASET_START_DATE} "
            f"--tp_atr_mult {tp} --sl_atr_mult {sl} "
            f"--out {dataset_path}"
        )
        if not run_command(cmd_gen):
            continue

        # 2. Train Model
        # We save to a temp model path
        model_path = f"models/temp_sweep_model_{tp}_{sl}.pkl"
        cmd_train = (
            f"python scripts/train_soldier_variants.py "
            f"--dataset {dataset_path} "
            f"--model-out {model_path} "
            f"--optimize-for precision" # Optimize for precision as we want high quality trades
        )
        if not run_command(cmd_train):
            continue

        # 3. Run Replay
        # We need to pass the model path and TP/SL to the replay script via env vars
        # The replay script reads MTF3_SOLDIER_MODEL_PATH, MTF3_TP_ATR_MULT, MTF3_SL_ATR_MULT
        
        out_dir = base_dir / f"run_tp{tp}_sl{sl}"
        
        env_vars = {
            "MTF3_SOLDIER_MODEL_PATH": str(Path(model_path).resolve()),
            "MTF3_TP_ATR_MULT": str(tp),
            "MTF3_SL_ATR_MULT": str(sl),
            "MTF3_SOLDIER_ENTRY_THRESHOLD": str(THRESHOLD),
            "MTF3_BACKTEST_START": BACKTEST_START_DATE,
            "MTF3_BACKTEST_END": BACKTEST_END_DATE,
            "MTF2_STALL_DETECTION_ENABLED": "True", # Enable stall detection
            "MTF2_STALL_CHECK_BARS": "6",
            "MTF2_STALL_MIN_PROFIT_ATR": "0.2",
            "MTF2_STALL_SL_ATR": "0.2",
        }
        
        cmd_replay = (
            f"python scripts/run_backtest_mtf_v3_replay_pnl.py "
            f"--start {BACKTEST_START_DATE} --end {BACKTEST_END_DATE} "
            f"--out {out_dir}"
        )
        
        if not run_command(cmd_replay, env=env_vars):
            continue
            
        # 4. Parse Results
        summary_file = out_dir / "summary.json"
        if summary_file.exists():
            with open(summary_file, 'r') as f:
                summary = json.load(f)
            
            res = {
                "tp": tp,
                "sl": sl,
                "net_pnl": summary.get("net_pnl"),
                "trades": summary.get("trades"),
                "win_rate": 0.0 # Calculate if trades > 0
            }
            
            # Calculate win rate from trades.csv if needed, or just trust summary if it had it (it doesn't have win rate explicitly)
            trades_file = out_dir / "trades.csv"
            if trades_file.exists():
                try:
                    df = pd.read_csv(trades_file)
                    if not df.empty:
                        wins = len(df[df['pnl_net'] > 0])
                        res["win_rate"] = (wins / len(df)) * 100
                except:
                    pass
            
            results.append(res)
            print(f"Result: PnL={res['net_pnl']:.2f}, Trades={res['trades']}, WinRate={res['win_rate']:.1f}%")
        else:
            print("No summary file found.")

    # Save final report
    report_df = pd.DataFrame(results)
    if not report_df.empty:
        print("\n=== Final Sweep Report ===")
        print(report_df.sort_values("net_pnl", ascending=False))
        report_df.to_csv(base_dir / "sweep_report.csv", index=False)
    else:
        print("No results collected.")

if __name__ == "__main__":
    main()
