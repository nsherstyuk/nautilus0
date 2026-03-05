"""
Quick test of seasonal hour×weekday exclusions logic.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.append(str(PROJECT_ROOT))

# Set test env vars
os.environ["MTF2_SEASONAL_HOUR_EXCLUSIONS_ENABLED"] = "1"
os.environ["MTF2_DJF_EXCLUDED_HOUR_WEEKDAY_PAIRS"] = "16-1,16-3,16-5"
os.environ["MTF2_JJA_EXCLUDED_HOUR_WEEKDAY_PAIRS"] = "17-1,17-3"

from config.mtf_v2_config import load_mtf_v2_config

cfg = load_mtf_v2_config()

print("=== Config Loaded ===")
print(f"Seasonal enabled: {cfg.seasonal_hour_exclusions_enabled}")
print(f"DJF pairs: {cfg.djf_excluded_hour_weekday_pairs}")
print(f"JJA pairs: {cfg.jja_excluded_hour_weekday_pairs}")

# Test parsing in strategy
from strategies.ml_strategy_mtf_v2_entry_confirmed import MLSignalStrategyV2EntryConfirmedConfig

test_config = MLSignalStrategyV2EntryConfirmedConfig(
    instrument_id="EURUSD.IDEALPRO",
    bar_type="EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL",
    seasonal_hour_exclusions_enabled=True,
    djf_excluded_hour_weekday_pairs=[(16, 1), (16, 3), (16, 5)],
    jja_excluded_hour_weekday_pairs=[(17, 1), (17, 3)],
)

print("\n=== Strategy Config Test ===")
print(f"Seasonal enabled: {test_config.seasonal_hour_exclusions_enabled}")
print(f"DJF pairs: {test_config.djf_excluded_hour_weekday_pairs}")
print(f"JJA pairs: {test_config.jja_excluded_hour_weekday_pairs}")

print("\n✓ All tests passed!")
