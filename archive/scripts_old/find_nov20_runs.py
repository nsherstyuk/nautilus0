import os
import json

results_dir = "logs/backtest_results"
for folder in os.listdir(results_dir):
    if "20251120" in folder: # Look for runs on Nov 20
        folder_path = os.path.join(results_dir, folder)
        stats_file = os.path.join(folder_path, "performance_stats.json")
        if os.path.exists(stats_file):
            try:
                with open(stats_file, "r") as f:
                    data = json.load(f)
                    pnl = data.get("pnls", {}).get("PnL (total)", 0)
                    print(f"Found run: {folder}, PnL: {pnl}")
            except Exception as e:
                pass
