"""
Compare baseline (no seasonal exclusions) vs seasonal exclusions results.

Reads:
- Baseline: analysis_outputs/seasonality_mtf_v2/ (from previous monthly run)
- Seasonal: New run folders in backtest_results/ (from recent monthly run)

Outputs side-by-side comparison.
"""

import pandas as pd
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).parent.parent

# Load baseline aggregated data
baseline_dir = PROJECT_ROOT / "analysis_outputs" / "seasonality_mtf_v2"
baseline_runs = pd.read_csv(baseline_dir / "runs_discovered.csv")
baseline_runs["type"] = "baseline"

print("=== Discovering new seasonal runs ===")

# Find all run folders
backtest_results = PROJECT_ROOT / "backtest_results"
all_runs = []

for run_dir in backtest_results.iterdir():
    if not run_dir.is_dir():
        continue
    
    summary_file = run_dir / "summary.txt"
    if not summary_file.exists():
        continue
    
    # Parse summary.txt to get period
    summary_text = summary_file.read_text(encoding='utf-8', errors='ignore')
    period_match = re.search(r'Period:\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})', summary_text)
    
    if not period_match:
        continue
    
    period_start = period_match.group(1)
    period_end = period_match.group(2)
    
    # Extract YYYY-MM from start date
    yyyymm = period_start[:7]  # "2024-01"
    
    # Skip the 2-year outlier run (2024-01-01 to 2025-12-18)
    if period_start == "2024-01-01" and period_end == "2025-12-18":
        continue
    
    # Only include single-month runs (period <= 31 days)
    try:
        from datetime import datetime
        start_dt = datetime.strptime(period_start, "%Y-%m-%d")
        end_dt = datetime.strptime(period_end, "%Y-%m-%d")
        days = (end_dt - start_dt).days
        if days > 35:  # Skip runs longer than ~1 month
            continue
    except:
        continue
    
    # Check if .env.mtf_v2 file exists in run folder
    env_file = run_dir / ".env.mtf_v2"
    if env_file.exists():
        env_text = env_file.read_text(encoding='utf-8', errors='ignore')
        # Check if seasonal exclusions were enabled
        if "MTF2_SEASONAL_HOUR_EXCLUSIONS_ENABLED=true" in env_text:
            run_type = "seasonal"
        else:
            run_type = "baseline"
    else:
        # Assume older runs without saved .env are baseline
        run_type = "baseline"
    
    all_runs.append({
        "yyyymm": yyyymm,
        "run_dir": str(run_dir),
        "period_start": period_start,
        "period_end": period_end,
        "type": run_type,
        "timestamp": run_dir.name.split("_")[-1] if "_" in run_dir.name else "unknown"
    })

runs_df = pd.DataFrame(all_runs)

# Keep only the most recent run per yyyymm per type
runs_df = runs_df.sort_values(["yyyymm", "type", "timestamp"], ascending=[True, True, False])
runs_df = runs_df.drop_duplicates(subset=["yyyymm", "type"], keep="first")

print(f"Total runs found: {len(runs_df)}")
print(f"  Baseline: {len(runs_df[runs_df.type=='baseline'])}")
print(f"  Seasonal: {len(runs_df[runs_df.type=='seasonal'])}")

# Load summary metrics for each run
def load_summary_metrics(run_dir):
    """Extract key metrics from summary.txt."""
    summary_file = Path(run_dir) / "summary.txt"
    if not summary_file.exists():
        return {}
    
    text = summary_file.read_text(encoding='utf-8', errors='ignore')
    
    metrics = {}
    
    # Total Trades
    m = re.search(r'Total Trades:\s*(\d+)', text)
    if m:
        metrics["trades"] = int(m.group(1))
    
    # Win Rate
    m = re.search(r'Win Rate:\s*([\d.]+)%', text)
    if m:
        metrics["win_rate"] = float(m.group(1))
    
    # Total P&L (note: P&L not PnL in summary.txt)
    m = re.search(r'Total P&L:\s*\$([\d,.-]+)', text)
    if m:
        metrics["pnl"] = float(m.group(1).replace(",", ""))
    
    # Sharpe
    m = re.search(r'Sharpe Ratio:\s*([\d.-]+)', text)
    if m:
        metrics["sharpe"] = float(m.group(1))
    
    # Max Drawdown
    m = re.search(r'Max Drawdown:\s*\$([\d,.-]+)', text)
    if m:
        metrics["max_dd"] = float(m.group(1).replace(",", ""))
    
    # Profit Factor
    m = re.search(r'Profit Factor:\s*([\d.-]+)', text)
    if m:
        metrics["profit_factor"] = float(m.group(1))
    
    return metrics

print("\n=== Loading metrics ===")

results = []
for _, row in runs_df.iterrows():
    metrics = load_summary_metrics(row["run_dir"])
    if metrics:
        results.append({
            "yyyymm": row["yyyymm"],
            "type": row["type"],
            "trades": metrics.get("trades", 0),
            "win_rate": metrics.get("win_rate", 0),
            "pnl": metrics.get("pnl", 0),
            "sharpe": metrics.get("sharpe", 0),
            "max_dd": metrics.get("max_dd", 0),
            "profit_factor": metrics.get("profit_factor", 0),
        })

results_df = pd.DataFrame(results)

if results_df.empty:
    print("ERROR: No results found!")
    exit(1)

# Calculate pnl_per_trade
results_df["pnl_per_trade"] = results_df["pnl"] / results_df["trades"]

# Add season
def get_season(yyyymm):
    month = int(yyyymm.split("-")[1])
    if month in [12, 1, 2]:
        return "DJF"
    elif month in [3, 4, 5]:
        return "MAM"
    elif month in [6, 7, 8]:
        return "JJA"
    else:
        return "SON"

results_df["season"] = results_df["yyyymm"].apply(get_season)

# Pivot to compare baseline vs seasonal
pivot = results_df.pivot_table(
    index="yyyymm",
    columns="type",
    values=["trades", "win_rate", "pnl", "pnl_per_trade"],
    aggfunc="first"
)

# Calculate differences
comparison = pd.DataFrame()
comparison["yyyymm"] = pivot.index
comparison["baseline_trades"] = pivot[("trades", "baseline")].values
comparison["seasonal_trades"] = pivot[("trades", "seasonal")].values
comparison["trade_delta"] = comparison["seasonal_trades"] - comparison["baseline_trades"]

comparison["baseline_pnl"] = pivot[("pnl", "baseline")].values
comparison["seasonal_pnl"] = pivot[("pnl", "seasonal")].values
comparison["pnl_delta"] = comparison["seasonal_pnl"] - comparison["baseline_pnl"]

comparison["baseline_pnl_per_trade"] = pivot[("pnl_per_trade", "baseline")].values
comparison["seasonal_pnl_per_trade"] = pivot[("pnl_per_trade", "seasonal")].values
comparison["pnl_per_trade_delta"] = comparison["seasonal_pnl_per_trade"] - comparison["baseline_pnl_per_trade"]

comparison["baseline_win_rate"] = pivot[("win_rate", "baseline")].values
comparison["seasonal_win_rate"] = pivot[("win_rate", "seasonal")].values
comparison["win_rate_delta"] = comparison["seasonal_win_rate"] - comparison["baseline_win_rate"]

# Add season
comparison["season"] = comparison["yyyymm"].apply(get_season)

# Summary by season
season_summary = results_df.groupby(["season", "type"]).agg({
    "trades": "sum",
    "pnl": "sum",
    "win_rate": "mean"
}).reset_index()

season_summary["pnl_per_trade"] = season_summary["pnl"] / season_summary["trades"]

# Overall totals
overall = results_df.groupby("type").agg({
    "trades": "sum",
    "pnl": "sum",
    "win_rate": "mean"
}).reset_index()

overall["pnl_per_trade"] = overall["pnl"] / overall["trades"]

print("\n" + "=" * 100)
print("BASELINE vs SEASONAL COMPARISON")
print("=" * 100)

print("\n=== OVERALL TOTALS ===\n")
for _, row in overall.iterrows():
    print(f"{row['type'].upper()}:")
    print(f"  Total Trades: {int(row['trades'])}")
    print(f"  Total PnL: ${row['pnl']:,.2f}")
    print(f"  Avg Win Rate: {row['win_rate']:.2f}%")
    print(f"  PnL/Trade: ${row['pnl_per_trade']:.2f}")
    print()

# Calculate delta
if len(overall) == 2:
    baseline_row = overall[overall.type == "baseline"].iloc[0]
    seasonal_row = overall[overall.type == "seasonal"].iloc[0]
    
    print("DELTA (Seasonal - Baseline):")
    print(f"  Trades: {int(seasonal_row['trades'] - baseline_row['trades'])} ({100*(seasonal_row['trades']/baseline_row['trades']-1):.1f}%)")
    print(f"  PnL: ${seasonal_row['pnl'] - baseline_row['pnl']:+,.2f}")
    print(f"  Win Rate: {seasonal_row['win_rate'] - baseline_row['win_rate']:+.2f}pp")
    print(f"  PnL/Trade: ${seasonal_row['pnl_per_trade'] - baseline_row['pnl_per_trade']:+.2f}")

print("\n=== BY SEASON ===\n")
for season in ["DJF", "MAM", "JJA", "SON"]:
    season_data = season_summary[season_summary.season == season]
    if season_data.empty:
        continue
    
    print(f"{season}:")
    for _, row in season_data.iterrows():
        print(f"  {row['type']}:")
        print(f"    Trades: {int(row['trades'])}, PnL: ${row['pnl']:,.2f}, PnL/Trade: ${row['pnl_per_trade']:.2f}")
    
    # Delta
    if len(season_data) == 2:
        baseline = season_data[season_data.type == "baseline"].iloc[0]
        seasonal = season_data[season_data.type == "seasonal"].iloc[0]
        print(f"  DELTA: Trades {int(seasonal['trades'] - baseline['trades']):+d}, PnL ${seasonal['pnl'] - baseline['pnl']:+,.2f}, PnL/Trade ${seasonal['pnl_per_trade'] - baseline['pnl_per_trade']:+.2f}")
    print()

print("\n=== MONTH-BY-MONTH ===\n")
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 200)

display_cols = ["yyyymm", "season", "baseline_trades", "seasonal_trades", "trade_delta", 
                "baseline_pnl", "seasonal_pnl", "pnl_delta", "pnl_per_trade_delta"]
print(comparison[display_cols].to_string(index=False))

# Save results
output_dir = PROJECT_ROOT / "analysis_outputs" / "baseline_vs_seasonal"
output_dir.mkdir(parents=True, exist_ok=True)

comparison.to_csv(output_dir / "month_by_month_comparison.csv", index=False)
season_summary.to_csv(output_dir / "season_comparison.csv", index=False)
overall.to_csv(output_dir / "overall_comparison.csv", index=False)

print(f"\n\nResults saved to: {output_dir}")
print("=" * 100)
