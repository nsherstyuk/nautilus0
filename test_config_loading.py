"""Test that duration-based trailing config parameters are being loaded correctly."""
import os
from dotenv import load_dotenv
from config.backtest_config import get_backtest_config

# Load .env file
load_dotenv(override=True)

print("=" * 80)
print("ENVIRONMENT VARIABLE VALUES (from .env)")
print("=" * 80)
print(f"STRATEGY_TRAILING_DURATION_ENABLED: {os.getenv('STRATEGY_TRAILING_DURATION_ENABLED')}")
print(f"STRATEGY_TRAILING_DURATION_THRESHOLD_HOURS: {os.getenv('STRATEGY_TRAILING_DURATION_THRESHOLD_HOURS')}")
print(f"STRATEGY_TRAILING_DURATION_DISTANCE_PIPS: {os.getenv('STRATEGY_TRAILING_DURATION_DISTANCE_PIPS')}")
print(f"STRATEGY_TRAILING_DURATION_REMOVE_TP: {os.getenv('STRATEGY_TRAILING_DURATION_REMOVE_TP')}")
print(f"STRATEGY_TRAILING_DURATION_ACTIVATE_IF_NOT_ACTIVE: {os.getenv('STRATEGY_TRAILING_DURATION_ACTIVATE_IF_NOT_ACTIVE')}")
print()
print(f"STRATEGY_MIN_HOLD_TIME_ENABLED: {os.getenv('STRATEGY_MIN_HOLD_TIME_ENABLED')}")
print(f"STRATEGY_MIN_HOLD_TIME_HOURS: {os.getenv('STRATEGY_MIN_HOLD_TIME_HOURS')}")
print(f"STRATEGY_MIN_HOLD_TIME_STOP_MULTIPLIER: {os.getenv('STRATEGY_MIN_HOLD_TIME_STOP_MULTIPLIER')}")
print()

print("=" * 80)
print("BACKTEST CONFIG OBJECT VALUES (loaded by get_backtest_config())")
print("=" * 80)
config = get_backtest_config()
print(f"trailing_duration_enabled: {config.trailing_duration_enabled}")
print(f"trailing_duration_threshold_hours: {config.trailing_duration_threshold_hours}")
print(f"trailing_duration_distance_pips: {config.trailing_duration_distance_pips}")
print(f"trailing_duration_remove_tp: {config.trailing_duration_remove_tp}")
print(f"trailing_duration_activate_if_not_active: {config.trailing_duration_activate_if_not_active}")
print()
print(f"min_hold_time_enabled: {config.min_hold_time_enabled}")
print(f"min_hold_time_hours: {config.min_hold_time_hours}")
print(f"min_hold_time_stop_multiplier: {config.min_hold_time_stop_multiplier}")
print()

print("=" * 80)
print("VERIFICATION")
print("=" * 80)
if config.trailing_duration_enabled:
    print("✅ Duration-based trailing is ENABLED")
    print(f"   Threshold: {config.trailing_duration_threshold_hours} hours")
    print(f"   Distance: {config.trailing_duration_distance_pips} pips")
    print(f"   Remove TP: {config.trailing_duration_remove_tp}")
    print(f"   Force activation: {config.trailing_duration_activate_if_not_active}")
else:
    print("❌ Duration-based trailing is DISABLED")

if config.min_hold_time_enabled:
    print("⚠️  Minimum hold time is ENABLED (may conflict)")
else:
    print("✅ Minimum hold time is DISABLED")

print()
print("Now your .env changes should affect backtests!")
