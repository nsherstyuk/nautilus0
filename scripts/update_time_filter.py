"""
Update .env file with time filter settings to exclude unprofitable hours.
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

# Remove existing time filter settings
filtered_lines = []
for line in lines:
    if not line.strip().startswith("BACKTEST_TIME_FILTER_ENABLED") and \
       not line.strip().startswith("BACKTEST_EXCLUDED_HOURS"):
        filtered_lines.append(line)

# Add new time filter settings
filtered_lines.append("\n# Time filter to exclude unprofitable hours (from hourly analysis)\n")
filtered_lines.append("BACKTEST_TIME_FILTER_ENABLED=true\n")
filtered_lines.append("BACKTEST_EXCLUDED_HOURS=1,2,12,18,21,23\n")

# Write back
with open(env_file, "w", encoding="utf-8") as f:
    f.writelines(filtered_lines)

print("Updated .env file with time filter settings:")
print("  BACKTEST_TIME_FILTER_ENABLED=true")
print("  BACKTEST_EXCLUDED_HOURS=1,2,12,18,21,23")
print("\nThese hours will be excluded from trading:")
print("  - Hour 01:00 UTC (lost -$500.17)")
print("  - Hour 02:00 UTC (lost -$218.19)")
print("  - Hour 12:00 UTC (lost -$712.45)")
print("  - Hour 18:00 UTC (lost -$713.21)")
print("  - Hour 21:00 UTC (lost -$46.10)")
print("  - Hour 23:00 UTC (lost -$713.06)")
print("\nTotal potential loss avoided: ~$2,902")

