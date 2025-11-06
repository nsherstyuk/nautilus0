"""
Verify if excluded hours are actually non-profitable and provide comprehensive statistics.
Compares current excluded hours configuration with actual profitability data.
"""
from pathlib import Path
import pandas as pd
import sys
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables from .env file
def load_env_file():
    """Load environment variables from .env file."""
    env_file = Path(".env")
    if not env_file.exists():
        return {}
    env_vars = {}
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    return env_vars

env_vars = load_env_file()

# Find latest backtest results
results_dir = Path("logs/backtest_results")
dirs = [d for d in results_dir.iterdir() if d.is_dir() and "EUR-USD_" in d.name]
if not dirs:
    print("No backtest results found!")
    sys.exit(1)

latest_dir = max(dirs, key=lambda d: d.stat().st_mtime)
print(f"Analyzing backtest: {latest_dir.name}\n")

# Load positions data
positions_file = latest_dir / "positions.csv"
if not positions_file.exists():
    print(f"Positions file not found: {positions_file}")
    sys.exit(1)

positions_df = pd.read_csv(positions_file)

# Convert timestamps to datetime
positions_df["ts_opened"] = pd.to_datetime(positions_df["ts_opened"])
positions_df["ts_closed"] = pd.to_datetime(positions_df["ts_closed"])

# Extract PnL (remove currency suffix)
def extract_pnl(value):
    if pd.isna(value):
        return 0.0
    value_str = str(value)
    import re
    cleaned = re.sub(r'\s*[A-Z]{3}\s*$', '', value_str)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

positions_df["realized_pnl_value"] = positions_df["realized_pnl"].apply(extract_pnl)

# Extract hour from entry time (ts_opened) - UTC
positions_df["entry_hour"] = positions_df["ts_opened"].dt.hour

# Group by hour and calculate comprehensive statistics
hourly_stats = positions_df.groupby("entry_hour").agg({
    "realized_pnl_value": ["sum", "mean", "count"],
}).round(2)

hourly_stats.columns = ["Total_PnL", "Avg_PnL", "Trade_Count"]

# Get current excluded hours from environment
backtest_excluded = env_vars.get("BACKTEST_EXCLUDED_HOURS", os.getenv("BACKTEST_EXCLUDED_HOURS", ""))
live_excluded = env_vars.get("LIVE_EXCLUDED_HOURS", os.getenv("LIVE_EXCLUDED_HOURS", ""))

def parse_excluded_hours(env_value):
    """Parse excluded hours from environment variable."""
    if not env_value or env_value.strip() == "":
        return []
    try:
        return sorted([int(h.strip()) for h in env_value.split(",") if h.strip()])
    except:
        return []

backtest_excluded_hours = parse_excluded_hours(backtest_excluded)
live_excluded_hours = parse_excluded_hours(live_excluded)

# Calculate actual unprofitable hours
unprofitable_hours = []
profitable_hours = []
no_trade_hours = []

for hour in range(24):
    if hour in hourly_stats.index:
        total_pnl = hourly_stats.loc[hour, "Total_PnL"]
        if total_pnl < 0:
            unprofitable_hours.append(hour)
        else:
            profitable_hours.append(hour)
    else:
        no_trade_hours.append(hour)

# Find mismatches
backtest_correctly_excluded = [h for h in backtest_excluded_hours if h in unprofitable_hours]
backtest_incorrectly_excluded = [h for h in backtest_excluded_hours if h not in unprofitable_hours]
backtest_should_exclude = [h for h in unprofitable_hours if h not in backtest_excluded_hours]

live_correctly_excluded = [h for h in live_excluded_hours if h in unprofitable_hours]
live_incorrectly_excluded = [h for h in live_excluded_hours if h not in unprofitable_hours]
live_should_exclude = [h for h in unprofitable_hours if h not in live_excluded_hours]

# Calculate PnL impact
total_pnl = positions_df['realized_pnl_value'].sum()

# Calculate loss from unprofitable hours
loss_from_unprofitable = hourly_stats[hourly_stats.index.isin(unprofitable_hours)]["Total_PnL"].sum() if unprofitable_hours else 0

# Calculate loss from incorrectly excluded profitable hours
loss_from_incorrect_exclusions = hourly_stats[hourly_stats.index.isin(backtest_incorrectly_excluded)]["Total_PnL"].sum() if backtest_incorrectly_excluded else 0

# Potential PnL if all unprofitable hours excluded
potential_pnl = total_pnl - loss_from_unprofitable

# Print comprehensive report
print("=" * 100)
print("EXCLUDED HOURS VERIFICATION REPORT")
print("=" * 100)
print()

print(f"Backtest Results Directory: {latest_dir.name}")
print(f"Total Trades Analyzed: {len(positions_df)}")
print(f"Total PnL: ${total_pnl:,.2f}")
print()

print("=" * 100)
print("PROFITABILITY BY TRADING HOUR (UTC)")
print("=" * 100)
print()
print(f"{'Hour':<6} {'Total PnL':<15} {'Avg PnL':<12} {'Trades':<8} {'Status':<15} {'In Config':<12} {'Verdict':<15}")
print("-" * 100)

for hour in range(24):
    if hour in hourly_stats.index:
        total_pnl_hour = hourly_stats.loc[hour, "Total_PnL"]
        avg_pnl_hour = hourly_stats.loc[hour, "Avg_PnL"]
        count = int(hourly_stats.loc[hour, "Trade_Count"])
        status = "PROFITABLE" if total_pnl_hour > 0 else "UNPROFITABLE"
        in_backtest = "EXCLUDED" if hour in backtest_excluded_hours else ""
        in_live = "EXCLUDED" if hour in live_excluded_hours else ""
        in_config = f"BT:{'Y' if hour in backtest_excluded_hours else 'N'} LV:{'Y' if hour in live_excluded_hours else 'N'}"
        
        if total_pnl_hour < 0:
            verdict = "[OK]" if hour in backtest_excluded_hours else "[MISSING]"
        elif total_pnl_hour > 0 and hour in backtest_excluded_hours:
            verdict = "[WRONG]"
        else:
            verdict = "[OK]"
            
        print(f"{hour:02d}:00  ${total_pnl_hour:>12.2f}  ${avg_pnl_hour:>10.2f}  {count:>7}  {status:<15} {in_config:<12} {verdict:<15}")
    else:
        in_backtest = "EXCLUDED" if hour in backtest_excluded_hours else ""
        in_live = "EXCLUDED" if hour in live_excluded_hours else ""
        in_config = f"BT:{'Y' if hour in backtest_excluded_hours else 'N'} LV:{'Y' if hour in live_excluded_hours else 'N'}"
        verdict = "[WRONG]" if hour in backtest_excluded_hours else "[NO DATA]"
        print(f"{hour:02d}:00  ${0:>12.2f}  ${0:>10.2f}  {0:>7}  {'NO TRADES':<15} {in_config:<12} {verdict:<15}")

print()
print("=" * 100)
print("CURRENT CONFIGURATION")
print("=" * 100)
print(f"BACKTEST_EXCLUDED_HOURS={','.join(map(str, backtest_excluded_hours)) if backtest_excluded_hours else '(empty)'}")
print(f"LIVE_EXCLUDED_HOURS={','.join(map(str, live_excluded_hours)) if live_excluded_hours else '(empty)'}")
print()

print("=" * 100)
print("ANALYSIS RESULTS")
print("=" * 100)
print()
print(f"[OK] Actually Unprofitable Hours: {sorted(unprofitable_hours)}")
print(f"   Total Loss: ${loss_from_unprofitable:,.2f}")
print()
print(f"[OK] Actually Profitable Hours: {sorted(profitable_hours)}")
print()
print(f"[!] Hours with No Trades: {sorted(no_trade_hours)}")
print()

print("=" * 100)
print("BACKTEST CONFIGURATION VERIFICATION")
print("=" * 100)
print()
print(f"[OK] Correctly Excluded (unprofitable): {sorted(backtest_correctly_excluded)}")
print(f"[X] Incorrectly Excluded (profitable): {sorted(backtest_incorrectly_excluded)}")
if backtest_incorrectly_excluded:
    incorrect_loss = hourly_stats[hourly_stats.index.isin(backtest_incorrectly_excluded)]["Total_PnL"].sum()
    print(f"   Lost Profit from Incorrect Exclusions: ${incorrect_loss:,.2f}")
print(f"[!] Should Exclude (unprofitable, not excluded): {sorted(backtest_should_exclude)}")
if backtest_should_exclude:
    missing_loss = hourly_stats[hourly_stats.index.isin(backtest_should_exclude)]["Total_PnL"].sum()
    print(f"   Loss from Missing Exclusions: ${missing_loss:,.2f}")
print()

print("=" * 100)
print("LIVE CONFIGURATION VERIFICATION")
print("=" * 100)
print()
print(f"[OK] Correctly Excluded (unprofitable): {sorted(live_correctly_excluded)}")
print(f"[X] Incorrectly Excluded (profitable): {sorted(live_incorrectly_excluded)}")
if live_incorrectly_excluded:
    incorrect_loss = hourly_stats[hourly_stats.index.isin(live_incorrectly_excluded)]["Total_PnL"].sum()
    print(f"   Lost Profit from Incorrect Exclusions: ${incorrect_loss:,.2f}")
print(f"[!] Should Exclude (unprofitable, not excluded): {sorted(live_should_exclude)}")
if live_should_exclude:
    missing_loss = hourly_stats[hourly_stats.index.isin(live_should_exclude)]["Total_PnL"].sum()
    print(f"   Loss from Missing Exclusions: ${missing_loss:,.2f}")
print()

print("=" * 100)
print("RECOMMENDATIONS")
print("=" * 100)
print()
print(f"Current Total PnL: ${total_pnl:,.2f}")
print(f"Loss from Unprofitable Hours: ${loss_from_unprofitable:,.2f}")
print(f"Potential PnL if All Unprofitable Hours Excluded: ${potential_pnl:,.2f}")
print(f"Potential Improvement: ${potential_pnl - total_pnl:,.2f} ({((potential_pnl - total_pnl) / abs(total_pnl) * 100) if total_pnl != 0 else 0:.1f}%)")
print()

print("Recommended BACKTEST_EXCLUDED_HOURS:")
print(f"  BACKTEST_EXCLUDED_HOURS={','.join(map(str, sorted(unprofitable_hours)))}")
print()
print("Recommended LIVE_EXCLUDED_HOURS:")
print(f"  LIVE_EXCLUDED_HOURS={','.join(map(str, sorted(unprofitable_hours)))}")
print()

print("=" * 100)
print("DETAILED HOURLY STATISTICS")
print("=" * 100)
print()
for hour in sorted(unprofitable_hours):
    if hour in hourly_stats.index:
        stats = hourly_stats.loc[hour]
        print(f"Hour {hour:02d}:00 UTC - Loss: ${stats['Total_PnL']:,.2f}, Avg: ${stats['Avg_PnL']:,.2f}, Trades: {int(stats['Trade_Count'])}")
print()

print("=" * 100)

