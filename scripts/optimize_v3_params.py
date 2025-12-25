import os
import sys
import subprocess
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
import itertools

# Fixed Params
DATASET_START_DATE = "2024-01-01" # Revert to 2024
BACKTEST_START_DATE = "2025-10-01"
BACKTEST_END_DATE = "2025-11-01"

# Optimization Grid
# We will optimize:
# 1. Stall Check Bars (4, 6, 8)
# 2. Stall Min Profit ATR (0.1, 0.2)
# 3. Stall SL ATR (0.1, 0.2, 0.4)
# 4. Soldier Threshold (0.6, 0.65, 0.7)

GRID = {
    "stall_check_bars": [4, 6, 8],
    "stall_min_profit_atr": [0.1, 0.2],
    "stall_sl_atr": [0.1, 0.2, 0.4],
    "soldier_threshold": [0.6, 0.65, 0.7]
}

def run_command(cmd, env=None):
    print(f"Running: {cmd}")
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    
    if cmd.startswith("python"):
        cmd = f"{sys.executable} {cmd[7:]}"
        
    result = subprocess.run(cmd, shell=True, env=full_env, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running command: {cmd}")
        print(result.stderr)
        return False
    return True

def main():
    # 1. Generate Dataset (Once)
    print("Generating Dataset (2024-2025)...")
    dataset_path = "logs/live_mtf/temp_opt_dataset.csv"
    cmd_gen = (
        f"python scripts/build_hmtf_stitched_dataset.py "
        f"--start {DATASET_START_DATE} "
        f"--tp_atr_mult 1.0 --sl_atr_mult 1.0 "
        f"--out {dataset_path}"
    )
    if not run_command(cmd_gen):
        return

    # 2. Train Model (Once)
    print("Training Model (TP=1.0/SL=1.0)...")
    model_path = "models/temp_opt_model.pkl"
    cmd_train = (
        f"python scripts/train_soldier_variants.py "
        f"--dataset {dataset_path} "
        f"--model-out {model_path} "
        f"--optimize-for precision"
    )
    if not run_command(cmd_train):
        return

    # 3. Run Grid Sweep
    keys = list(GRID.keys())
    values = list(GRID.values())
    combinations = list(itertools.product(*values))
    
    print(f"Running Grid Sweep: {len(combinations)} combinations...")
    
    results = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = Path("backtest_results") / f"MTF_V3_OPT_{timestamp}"
    base_dir.mkdir(parents=True, exist_ok=True)

    for i, combo in enumerate(combinations):
        params = dict(zip(keys, combo))
        
        # Skip invalid combos (SL > Min Profit doesn't make sense for locking in profit, 
        # but here SL is distance from entry, so it acts as a trailing stop or breakeven.
        # If stall_sl_atr is 0.1 and min_profit is 0.2, we lock in -0.1 risk? No.
        # The logic in script is: new_sl = entry +/- (atr * stall_sl_atr).
        # So stall_sl_atr is distance from ENTRY.
        # If stall_sl_atr is positive, it locks in profit.
        # So stall_sl_atr should be < min_profit usually? 
        # Wait, if min_profit is 0.2 (we are at +0.2), and we set SL to +0.1 (stall_sl_atr=0.1), that works.
        # If we set SL to +0.4 (stall_sl_atr=0.4), we are setting SL ABOVE current price? That would trigger immediate exit.
        # Which is fine, it acts as a market exit.
        
        print(f"[{i+1}/{len(combinations)}] Testing: {params}")
        
        out_dir = base_dir / f"run_{i}"
        
        env_vars = {
            "MTF3_SOLDIER_MODEL_PATH": str(Path(model_path).resolve()),
            "MTF3_TP_ATR_MULT": "1.0",
            "MTF3_SL_ATR_MULT": "1.0",
            "MTF3_SOLDIER_ENTRY_THRESHOLD": str(params["soldier_threshold"]),
            "MTF3_BACKTEST_START": BACKTEST_START_DATE,
            "MTF3_BACKTEST_END": BACKTEST_END_DATE,
            "MTF2_STALL_DETECTION_ENABLED": "True",
            "MTF2_STALL_CHECK_BARS": str(params["stall_check_bars"]),
            "MTF2_STALL_MIN_PROFIT_ATR": str(params["stall_min_profit_atr"]),
            "MTF2_STALL_SL_ATR": str(params["stall_sl_atr"]),
            # Ensure exclusion is active (it reads from .env.mtf_v2 by default via os.getenv if not overridden, 
            # but we should probably ensure it's set if we want to test it. 
            # The script reads .env.mtf_v3, but exclusion vars are in .env.mtf_v2.
            # We need to make sure the script loads .env.mtf_v2 or we pass them.
            # The script `run_backtest_mtf_v3_replay_pnl.py` only loads `.env.mtf_v3`.
            # So we must pass the exclusion vars explicitly or load them.
            # Let's pass them explicitly from the current environment (which has them if we source it, 
            # but python script doesn't source .env.mtf_v2 automatically).
            # We will read .env.mtf_v2 in this script and pass them.
        }
        
        # Load exclusion vars from .env.mtf_v2
        with open(".env.mtf_v2", "r") as f:
            for line in f:
                if line.startswith("MTF2_EXCLUDED_HOURS_") or line.startswith("MTF2_CONFIG_TIMEZONE"):
                    k, v = line.strip().split("=", 1)
                    env_vars[k] = v

        cmd_replay = (
            f"python scripts/run_backtest_mtf_v3_replay_pnl.py "
            f"--start {BACKTEST_START_DATE} --end {BACKTEST_END_DATE} "
            f"--out {out_dir}"
        )
        
        if not run_command(cmd_replay, env=env_vars):
            continue
            
        # Parse Results
        summary_file = out_dir / "summary.json"
        if summary_file.exists():
            with open(summary_file, 'r') as f:
                summary = json.load(f)
            
            res = params.copy()
            res["net_pnl"] = summary.get("net_pnl")
            res["trades"] = summary.get("trades")
            results.append(res)
            print(f"  -> PnL: {res['net_pnl']:.2f}, Trades: {res['trades']}")

    # Save Report
    report_df = pd.DataFrame(results)
    if not report_df.empty:
        print("\n=== Optimization Report ===")
        print(report_df.sort_values("net_pnl", ascending=False).head(10))
        report_df.to_csv(base_dir / "optimization_report.csv", index=False)
        
        # Find best
        best = report_df.sort_values("net_pnl", ascending=False).iloc[0]
        print("\nBest Configuration:")
        print(best)

if __name__ == "__main__":
    main()
