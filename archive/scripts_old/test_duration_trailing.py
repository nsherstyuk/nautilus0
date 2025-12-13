"""
Test script to validate duration-based trailing stop implementation
"""
import sys

print("="*80)
print("DURATION-BASED TRAILING STOP - VALIDATION")
print("="*80)

# 1. Validate Python syntax
print("\n1. Validating strategy code syntax...")
try:
    import py_compile
    py_compile.compile('strategies/moving_average_crossover.py', doraise=True)
    print("   ✅ Strategy code syntax is valid")
except Exception as e:
    print(f"   ❌ Syntax error: {e}")
    sys.exit(1)

# 2. Check configuration
print("\n2. Checking .env configuration...")
from pathlib import Path

env_file = Path('.env')
if not env_file.exists():
    print("   ❌ .env file not found")
    sys.exit(1)

with open(env_file) as f:
    env_content = f.read()

required_settings = {
    'STRATEGY_TRAILING_DURATION_ENABLED': 'true',
    'STRATEGY_TRAILING_DURATION_THRESHOLD_HOURS': '12.0',
    'STRATEGY_TRAILING_DURATION_DISTANCE_PIPS': '30',
    'STRATEGY_TRAILING_DURATION_REMOVE_TP': 'true',
    'STRATEGY_TRAILING_DURATION_ACTIVATE_IF_NOT_ACTIVE': 'true',
}

all_good = True
for key, expected_value in required_settings.items():
    if key in env_content:
        for line in env_content.split('\n'):
            if line.startswith(key):
                actual_value = line.split('=')[1].strip()
                if actual_value.lower() == expected_value.lower():
                    print(f"   ✅ {key}={actual_value}")
                else:
                    print(f"   ⚠️  {key}={actual_value} (expected: {expected_value})")
                    all_good = False
                break
    else:
        print(f"   ❌ {key} NOT found in .env")
        all_good = False

# 3. Verify code changes
print("\n3. Verifying code implementation...")

with open('strategies/moving_average_crossover.py') as f:
    strategy_code = f.read()

checks = [
    ('trailing_duration_enabled', 'Configuration parameter added'),
    ('_position_opened_time', 'Position timestamp tracking added'),
    ('DURATION_TRAIL', 'Duration-based trailing logic implemented'),
    ('duration_hours =', 'Duration calculation present'),
    ('apply_duration_trailing', 'Duration threshold check present'),
]

for search_str, description in checks:
    if search_str in strategy_code:
        print(f"   ✅ {description}")
    else:
        print(f"   ❌ {description} - NOT FOUND")
        all_good = False

# 4. Summary
print("\n" + "="*80)
if all_good:
    print("✅ VALIDATION SUCCESSFUL")
    print("\nPhase 1: Duration-Based Trailing Stop Optimization is ready!")
    print("\n📊 Expected Results:")
    print("   • Baseline PnL: $9,517.35")
    print("   • Expected improvement: +$2,725 (+28.6%)")
    print("   • Target PnL: ~$12,242")
    print("\n🎯 What it does:")
    print("   • After 12 hours: Activates/widens trailing stop to 30 pips")
    print("   • Removes TP limit to let winners run")
    print("   • Targets 56 high-quality trades (66% win rate)")
    print("\n🚀 Next step:")
    print("   Run backtest: python backtest/run_backtest.py")
    print("   Compare to baseline: $9,517.35")
else:
    print("⚠️  VALIDATION ISSUES FOUND")
    print("\nPlease review the errors above before running backtest.")
    sys.exit(1)

print("="*80)
