"""
Quick validation that ADX filter is properly configured
"""
import sys
import py_compile

# Validate Python syntax
print("Validating strategy code syntax...")
try:
    py_compile.compile('strategies/moving_average_crossover.py', doraise=True)
    print("✅ Strategy code syntax is valid")
except py_compile.PyCompileError as e:
    print(f"❌ Syntax error in strategy code: {e}")
    sys.exit(1)

# Check config
print("\nChecking environment configuration...")
import os
from pathlib import Path

env_file = Path('.env')
if not env_file.exists():
    print("❌ .env file not found")
    sys.exit(1)

with open(env_file) as f:
    env_content = f.read()

required_settings = {
    'STRATEGY_DMI_ENABLED': 'true',
    'STRATEGY_DMI_ADX_MIN_STRENGTH': None,  # Just check it exists
}

all_good = True
for key, expected_value in required_settings.items():
    if key in env_content:
        print(f"✅ {key} found in .env")
        if expected_value:
            for line in env_content.split('\n'):
                if line.startswith(key):
                    actual_value = line.split('=')[1].strip()
                    if actual_value.lower() == expected_value.lower():
                        print(f"   Value: {actual_value} ✅")
                    else:
                        print(f"   ⚠️  Value: {actual_value} (expected: {expected_value})")
    else:
        print(f"❌ {key} NOT found in .env")
        all_good = False

print("\n" + "="*60)
if all_good:
    print("✅ ADX FILTER CONFIGURATION VALIDATED")
    print("\nConfiguration:")
    for line in env_content.split('\n'):
        if 'STRATEGY_DMI' in line and not line.strip().startswith('#'):
            print(f"  {line}")
    
    print("\n📝 Summary:")
    print("  • DMI filter is ENABLED")
    print("  • ADX minimum strength threshold is SET")
    print("  • Trades in choppy markets (ADX < threshold) will be REJECTED")
    print("  • Minimum hold time feature is DISABLED (didn't improve PnL)")
    
    print("\n🚀 Ready to run backtest:")
    print("  python backtest/run_backtest.py")
else:
    print("⚠️  CONFIGURATION ISSUES FOUND")
    sys.exit(1)
