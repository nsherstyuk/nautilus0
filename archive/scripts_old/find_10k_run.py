import os
import json

results_dir = "logs/backtest_results"
for folder in os.listdir(results_dir):
    folder_path = os.path.join(results_dir, folder)
    stats_file = os.path.join(folder_path, "performance_stats.json")
    if os.path.exists(stats_file):
        try:
            with open(stats_file, "r") as f:
                data = json.load(f)
                pnl = data.get("pnls", {}).get("PnL (total)", 0)
                if 9000 <= pnl <= 11000:
                    print(f"Found run: {folder}, PnL: {pnl}")
                    # Check if partial close was enabled in .env if it exists
                    env_file = os.path.join(folder_path, ".env")
                    if os.path.exists(env_file):
                        with open(env_file, "r") as env:
                            content = env.read()
                            if "PARTIAL" in content or "partial" in content:
                                print(f"  -> Partial close might be enabled (found 'partial' in .env)")
        except Exception as e:
            pass
