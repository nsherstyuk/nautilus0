"""
Verify Phase 6 configuration in .env file.
"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("PHASE 6 CONFIGURATION VERIFICATION")
print("=" * 80)
print()

# Load Phase 6 expected values
phase6_file = Path("optimization/results/phase6_refinement_results_top_10.json")
phase6_data = json.load(open(phase6_file))
phase6_best = phase6_data[0]
phase6_params = phase6_best["parameters"]

print("Expected Phase 6 Values (from results):")
print(f"  Fast/Slow: {phase6_params['fast_period']}/{phase6_params['slow_period']}")
print(f"  SL/TP: {phase6_params['stop_loss_pips']}/{phase6_params['take_profit_pips']}")
print(f"  Trailing: {phase6_params['trailing_stop_activation_pips']}/{phase6_params['trailing_stop_distance_pips']}")
print(f"  Threshold: {phase6_params['crossover_threshold_pips']}")
print(f"  DMI: {phase6_params['dmi_enabled']} (period={phase6_params['dmi_period']})")
print(f"  Stoch: {phase6_params['stoch_enabled']} (K={phase6_params['stoch_period_k']}, D={phase6_params['stoch_period_d']}, thresholds={phase6_params['stoch_bullish_threshold']}/{phase6_params['stoch_bearish_threshold']})")
print()

print("Current .env Values:")
print(f"  Symbol: {os.getenv('BACKTEST_SYMBOL')}")
print(f"  Venue: {os.getenv('BACKTEST_VENUE')}")
print(f"  Dates: {os.getenv('BACKTEST_START_DATE')} to {os.getenv('BACKTEST_END_DATE')}")
print(f"  Fast/Slow: {os.getenv('BACKTEST_FAST_PERIOD')}/{os.getenv('BACKTEST_SLOW_PERIOD')}")
print(f"  SL/TP: {os.getenv('BACKTEST_STOP_LOSS_PIPS')}/{os.getenv('BACKTEST_TAKE_PROFIT_PIPS')}")
print(f"  Trailing: {os.getenv('BACKTEST_TRAILING_STOP_ACTIVATION_PIPS')}/{os.getenv('BACKTEST_TRAILING_STOP_DISTANCE_PIPS')}")
print(f"  Threshold: {os.getenv('STRATEGY_CROSSOVER_THRESHOLD_PIPS')}")
print(f"  DMI: {os.getenv('STRATEGY_DMI_ENABLED')} (period={os.getenv('STRATEGY_DMI_PERIOD')})")
print(f"  Stoch: {os.getenv('STRATEGY_STOCH_ENABLED')} (K={os.getenv('STRATEGY_STOCH_PERIOD_K')}, D={os.getenv('STRATEGY_STOCH_PERIOD_D')}, thresholds={os.getenv('STRATEGY_STOCH_BULLISH_THRESHOLD')}/{os.getenv('STRATEGY_STOCH_BEARISH_THRESHOLD')})")
print()

print("New Features Status (should all be disabled):")
print(f"  Dormant Mode: {os.getenv('BACKTEST_DORMANT_MODE_ENABLED')}")
print(f"  Trend Filter: {os.getenv('BACKTEST_TREND_FILTER_ENABLED')}")
print(f"  Entry Timing: {os.getenv('BACKTEST_ENTRY_TIMING_ENABLED')}")
print()

# Verify matches
def verify_match(name, expected, actual):
    """Verify a parameter matches."""
    # Normalize boolean values
    if isinstance(expected, bool):
        expected_str = str(expected).lower()
        actual_str = str(actual).lower() if actual else ""
        if expected_str == actual_str:
            return True, ""
        return False, f"  {name}: Expected {expected}, got {actual}"
    elif str(expected).lower() == str(actual).lower():
        return True, ""
    return False, f"  {name}: Expected {expected}, got {actual}"

mismatches = []

mismatches.extend([
    verify_match("Fast Period", phase6_params['fast_period'], os.getenv('BACKTEST_FAST_PERIOD'))[1],
    verify_match("Slow Period", phase6_params['slow_period'], os.getenv('BACKTEST_SLOW_PERIOD'))[1],
    verify_match("Stop Loss", phase6_params['stop_loss_pips'], os.getenv('BACKTEST_STOP_LOSS_PIPS'))[1],
    verify_match("Take Profit", phase6_params['take_profit_pips'], os.getenv('BACKTEST_TAKE_PROFIT_PIPS'))[1],
    verify_match("Trailing Activation", phase6_params['trailing_stop_activation_pips'], os.getenv('BACKTEST_TRAILING_STOP_ACTIVATION_PIPS'))[1],
    verify_match("Trailing Distance", phase6_params['trailing_stop_distance_pips'], os.getenv('BACKTEST_TRAILING_STOP_DISTANCE_PIPS'))[1],
    verify_match("Crossover Threshold", phase6_params['crossover_threshold_pips'], os.getenv('STRATEGY_CROSSOVER_THRESHOLD_PIPS'))[1],
    verify_match("DMI Enabled", phase6_params['dmi_enabled'], os.getenv('STRATEGY_DMI_ENABLED'))[1],
    verify_match("DMI Period", phase6_params['dmi_period'], os.getenv('STRATEGY_DMI_PERIOD'))[1],
    verify_match("Stoch Enabled", phase6_params['stoch_enabled'], os.getenv('STRATEGY_STOCH_ENABLED'))[1],
    verify_match("Stoch Period K", phase6_params['stoch_period_k'], os.getenv('STRATEGY_STOCH_PERIOD_K'))[1],
    verify_match("Stoch Period D", phase6_params['stoch_period_d'], os.getenv('STRATEGY_STOCH_PERIOD_D'))[1],
    verify_match("Stoch Bullish", phase6_params['stoch_bullish_threshold'], os.getenv('STRATEGY_STOCH_BULLISH_THRESHOLD'))[1],
    verify_match("Stoch Bearish", phase6_params['stoch_bearish_threshold'], os.getenv('STRATEGY_STOCH_BEARISH_THRESHOLD'))[1],
])

mismatches = [m for m in mismatches if m]

if mismatches:
    print("VERIFICATION FAILED - Mismatches found:")
    for mismatch in mismatches:
        print(mismatch)
    exit(1)
else:
    print("[OK] All Phase 6 parameters match!")
    print("[OK] All new features are disabled")
    print()
    print("Configuration is ready for Phase 6 backtest verification!")

