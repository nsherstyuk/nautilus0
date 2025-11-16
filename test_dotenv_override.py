import os
from dotenv import load_dotenv

# Set environment variables BEFORE load_dotenv
os.environ['STRATEGY_REGIME_DETECTION_ENABLED'] = 'true'
os.environ['STRATEGY_REGIME_TP_MULTIPLIER_RANGING'] = '0.5'

print("BEFORE load_dotenv:")
print(f"  REGIME_DETECTION_ENABLED: {os.getenv('STRATEGY_REGIME_DETECTION_ENABLED')}")
print(f"  TP_MULTIPLIER_RANGING: {os.getenv('STRATEGY_REGIME_TP_MULTIPLIER_RANGING')}")

# Load .env with override=False
load_dotenv(override=False)

print("\nAFTER load_dotenv(override=False):")
print(f"  REGIME_DETECTION_ENABLED: {os.getenv('STRATEGY_REGIME_DETECTION_ENABLED')}")
print(f"  TP_MULTIPLIER_RANGING: {os.getenv('STRATEGY_REGIME_TP_MULTIPLIER_RANGING')}")

# Check what's in .env file
print("\nWhat's in .env file:")
with open('.env', 'r') as f:
    for line in f:
        if 'REGIME_DETECTION_ENABLED' in line or 'REGIME_TP_MULTIPLIER_RANGING' in line:
            print(f"  {line.strip()}")
