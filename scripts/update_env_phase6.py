"""
Update .env file with Phase 6 configuration values.
All new features (dormant mode, trend filter, entry timing) are disabled.
"""
import re
from pathlib import Path

# Phase 6 Best Parameters (run_id 21)
PHASE6_CONFIG = {
    # Basic Settings
    "BACKTEST_SYMBOL": "EUR/USD",
    "BACKTEST_VENUE": "IDEALPRO",
    "BACKTEST_START_DATE": "2025-01-01",
    "BACKTEST_END_DATE": "2025-07-31",
    "BACKTEST_BAR_SPEC": "15-MINUTE-MID-EXTERNAL",
    
    # Phase 6 MA Parameters
    "BACKTEST_FAST_PERIOD": "42",
    "BACKTEST_SLOW_PERIOD": "270",
    
    # Phase 6 Risk Management
    "BACKTEST_STOP_LOSS_PIPS": "35",
    "BACKTEST_TAKE_PROFIT_PIPS": "50",
    "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": "22",
    "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": "12",
    
    # Phase 6 Signal Filters
    "STRATEGY_CROSSOVER_THRESHOLD_PIPS": "0.35",
    
    # Phase 6 DMI
    "STRATEGY_DMI_ENABLED": "true",
    "STRATEGY_DMI_BAR_SPEC": "2-MINUTE-MID-EXTERNAL",
    "STRATEGY_DMI_PERIOD": "10",
    "STRATEGY_DMI_MINIMUM_DIFFERENCE": "0.0",
    
    # Phase 6 Stochastic
    "STRATEGY_STOCH_ENABLED": "true",
    "STRATEGY_STOCH_BAR_SPEC": "15-MINUTE-MID-EXTERNAL",
    "STRATEGY_STOCH_PERIOD_K": "19",
    "STRATEGY_STOCH_PERIOD_D": "3",
    "STRATEGY_STOCH_BULLISH_THRESHOLD": "27",
    "STRATEGY_STOCH_BEARISH_THRESHOLD": "63",
    "STRATEGY_STOCH_MAX_BARS_SINCE_CROSSING": "9",
    
    # Trade Settings
    "BACKTEST_TRADE_SIZE": "100000",
    "ENFORCE_POSITION_LIMIT": "true",
    "ALLOW_POSITION_REVERSAL": "false",
    
    # Pre-crossover (disabled)
    "STRATEGY_PRE_CROSSOVER_SEPARATION_PIPS": "0.0",
    "STRATEGY_PRE_CROSSOVER_LOOKBACK_BARS": "1",
    
    # Time Filter (disabled)
    "BACKTEST_TIME_FILTER_ENABLED": "false",
    # Excluded hours (clear for Phase 6 - time filter wasn't working)
    "BACKTEST_EXCLUDED_HOURS": "",
    
    # Order Settings
    "USE_LIMIT_ORDERS": "false",
    "LIMIT_ORDER_TIMEOUT_BARS": "5",
    
    # New Features - ALL DISABLED
    "BACKTEST_TREND_FILTER_ENABLED": "false",
    "BACKTEST_ENTRY_TIMING_ENABLED": "false",
    "BACKTEST_DORMANT_MODE_ENABLED": "false",
}

def update_env_file(env_path: Path):
    """Update .env file with Phase 6 values, keeping other variables."""
    if not env_path.exists():
        print(f"Creating new .env file at {env_path}")
        lines = []
    else:
        lines = env_path.read_text(encoding='utf-8').split('\n')
    
    # Track which variables we've updated
    updated_vars = set()
    new_lines = []
    
    # Process each line
    for line in lines:
        stripped = line.strip()
        
        # Keep comments and empty lines
        if not stripped or stripped.startswith('#'):
            new_lines.append(line)
            continue
        
        # Check if this line defines a variable we want to update
        if '=' in stripped:
            var_name = stripped.split('=', 1)[0].strip()
            
            # Update if it's in our Phase 6 config
            if var_name in PHASE6_CONFIG:
                new_lines.append(f"{var_name}={PHASE6_CONFIG[var_name]}")
                updated_vars.add(var_name)
                continue
        
        # Keep line as-is
        new_lines.append(line)
    
    # Add any missing variables
    for var_name, var_value in PHASE6_CONFIG.items():
        if var_name not in updated_vars:
            # Add before dormant mode section if exists, otherwise at end
            if "BACKTEST_DORMANT_MODE_ENABLED" in [l.split('=')[0].strip() if '=' in l else '' for l in new_lines]:
                # Find the dormant mode section and insert before it
                insert_idx = None
                for i, line in enumerate(new_lines):
                    if line.strip().startswith("BACKTEST_DORMANT_MODE_ENABLED"):
                        insert_idx = i
                        break
                if insert_idx is not None:
                    new_lines.insert(insert_idx, f"{var_name}={var_value}")
                else:
                    new_lines.append(f"{var_name}={var_value}")
            else:
                new_lines.append(f"{var_name}={var_value}")
    
    # Write updated file
    env_path.write_text('\n'.join(new_lines), encoding='utf-8')
    print(f"Updated .env file: {len(updated_vars)} variables updated, {len(PHASE6_CONFIG) - len(updated_vars)} variables added")
    print(f"\nPhase 6 Configuration Applied:")
    print(f"  Symbol: {PHASE6_CONFIG['BACKTEST_SYMBOL']}")
    print(f"  Dates: {PHASE6_CONFIG['BACKTEST_START_DATE']} to {PHASE6_CONFIG['BACKTEST_END_DATE']}")
    print(f"  Fast/Slow: {PHASE6_CONFIG['BACKTEST_FAST_PERIOD']}/{PHASE6_CONFIG['BACKTEST_SLOW_PERIOD']}")
    print(f"  SL/TP: {PHASE6_CONFIG['BACKTEST_STOP_LOSS_PIPS']}/{PHASE6_CONFIG['BACKTEST_TAKE_PROFIT_PIPS']}")
    print(f"\nAll New Features Disabled:")
    print(f"  Dormant Mode: {PHASE6_CONFIG['BACKTEST_DORMANT_MODE_ENABLED']}")
    print(f"  Trend Filter: {PHASE6_CONFIG['BACKTEST_TREND_FILTER_ENABLED']}")
    print(f"  Entry Timing: {PHASE6_CONFIG['BACKTEST_ENTRY_TIMING_ENABLED']}")

if __name__ == "__main__":
    env_file = Path(".env")
    update_env_file(env_file)
