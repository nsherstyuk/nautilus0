"""
Update .env file with live trading time filter settings to exclude unprofitable hours.
"""
from pathlib import Path
import re

env_file = Path(".env")
if not env_file.exists():
    print("ERROR: .env file not found!")
    exit(1)

# Read current .env
with open(env_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Remove existing live time filter settings
filtered_lines = []
for line in lines:
    if not line.strip().startswith("LIVE_TIME_FILTER_ENABLED") and \
       not line.strip().startswith("LIVE_EXCLUDED_HOURS") and \
       not line.strip().startswith("LIVE_TRADING_HOURS_START") and \
       not line.strip().startswith("LIVE_TRADING_HOURS_END") and \
       not line.strip().startswith("LIVE_TRADING_HOURS_TIMEZONE"):
        filtered_lines.append(line)

# Add new live time filter settings
filtered_lines.append("\n# ==============================================================================\n")
filtered_lines.append("# Live Trading Time Filter Configuration\n")
filtered_lines.append("# Based on backtest analysis - excludes unprofitable trading hours (UTC)\n")
filtered_lines.append("# ==============================================================================\n")
filtered_lines.append("LIVE_TIME_FILTER_ENABLED=true\n")
filtered_lines.append("LIVE_TRADING_HOURS_START=0\n")
filtered_lines.append("LIVE_TRADING_HOURS_END=23\n")
filtered_lines.append("LIVE_TRADING_HOURS_TIMEZONE=UTC\n")
filtered_lines.append("LIVE_EXCLUDED_HOURS=1,2,12,13,18,21,22,23\n")

# Write back
with open(env_file, "w", encoding="utf-8") as f:
    f.writelines(filtered_lines)

print("Updated .env file with live trading time filter settings:")
print("  LIVE_TIME_FILTER_ENABLED=true")
print("  LIVE_TRADING_HOURS_START=0")
print("  LIVE_TRADING_HOURS_END=23")
print("  LIVE_TRADING_HOURS_TIMEZONE=UTC")
print("  LIVE_EXCLUDED_HOURS=1,2,12,13,18,21,22,23")
print()
print("These hours will be excluded from live trading (UTC):")
print("  - Hour 01:00 UTC")
print("  - Hour 02:00 UTC")
print("  - Hour 12:00 UTC")
print("  - Hour 13:00 UTC")
print("  - Hour 18:00 UTC")
print("  - Hour 21:00 UTC")
print("  - Hour 22:00 UTC")
print("  - Hour 23:00 UTC")
print()
print("Based on backtest results, this should improve performance by avoiding")
print("unprofitable trading hours. You can now restart the live trading script.")
print()
print("Note: The strategy will only generate signals during allowed hours.")

